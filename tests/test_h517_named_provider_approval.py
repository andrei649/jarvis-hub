"""Named speech identities cross real strict signed approval and execution."""
import pytest

from agents.core import settings_db
from agents.core.voice import command_settings, provider_store
from tests.test_h517_voice_kernel import make_rig


@pytest.fixture
def rig(tmp_path, monkeypatch):
    value = make_rig(tmp_path, monkeypatch)
    yield value
    value.q.close()


async def install(rig, name):
    code, result = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id=name)
    assert code == 202, result
    await rig.worker.apply_decision(result['pending'], 'accept', decided_by='owner')
    await rig.worker.tick()
    return result['pending']


async def test_named_strict_registration_binds_identity_and_never_changes_legacy(rig):
    tid = await install(rig, 'studio')
    task = rig.q.get(tid)
    assert task.payload['provider_id'] == 'studio'
    assert task.payload['provider_revision'] == 0
    assert task.payload['preview']['provider_id'] == 'studio'
    assert task.risk_tier == 3 and task.mediation_receipt['effective_tier'] == 3
    value = provider_store.load('tts', 'studio')
    assert value['approved_task'] == tid and value['provider_revision'] == 1
    assert settings_db.get_value('voice', 'tts_command', {}) == {}
    assert rig.q.verified_mediation_stats()['valid']


async def test_pending_names_and_legacy_are_independent_and_status_shows_pending(rig):
    for name in ['studio', 'other', None]:
        code, _ = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id=name)
        assert code == 202
    view = command_settings.status(rig.orch)
    assert {r['provider_id'] for r in view['providers']['tts']} == {'studio', 'other'}
    assert all(r['pending_task'] and not r['configured'] for r in view['providers']['tts'])
    assert view['sides']['tts']['pending_task']


async def test_clear_before_first_approval_invalidates_zero_revision(rig):
    code, pending = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 202
    assert (await command_settings.clear(rig.orch, 'tts', provider_id='studio'))[0] == 200
    await rig.worker.apply_decision(pending['pending'], 'accept', decided_by='owner')
    await rig.worker.tick()
    assert not provider_store.load('tts', 'studio').get('argv')
    assert rig.q.get(pending['pending']).result['reason'] == 'provider_revision_conflict'


async def test_named_dry_run_and_record_failure_never_claim_usable_registration(rig, monkeypatch):
    before = settings_db.DB_PATH.read_bytes()
    code, result = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio', dry_run=True)
    assert code == 200 and result['provider_revision'] == 0
    assert rig.q.list() == [] and settings_db.DB_PATH.read_bytes() == before
    monkeypatch.setattr(command_settings, '_record_request', lambda *args: False)
    code, result = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 503 and result['error'] == 'approval_record_unavailable'
    task = rig.q.list()[0]
    await rig.worker.apply_decision(task.id, 'accept', decided_by='owner')
    await rig.worker.tick()
    assert task.id and not provider_store.load('tts', 'studio').get('argv')


async def test_clearing_one_name_preserves_other(rig):
    await install(rig, 'studio')
    other = await install(rig, 'other')
    await command_settings.clear(rig.orch, 'tts', provider_id='studio')
    assert not provider_store.load('tts', 'studio').get('argv')
    assert provider_store.load('tts', 'other')['approved_task'] == other


@pytest.mark.parametrize('name', ['piper', 'Studio', ' studio', 'x'*33])
async def test_invalid_identity_never_enqueues(rig, name):
    code, answer = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id=name)
    assert code == 422 and answer['error'] == 'invalid_provider_id'
    assert rig.q.list() == []


async def test_changed_named_identity_or_edit_cannot_apply_original_record(rig):
    from copy import deepcopy
    from types import SimpleNamespace
    code, pending = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 202
    task = rig.q.get(pending['pending'])
    payload = deepcopy(task.payload)
    payload['provider_id'] = 'other'
    changed = SimpleNamespace(id=task.id, payload=payload, decision='accept', decided_by='owner')
    assert (await command_settings.apply_approved(changed, rig.orch))['reason'] == 'payload_changed'
    changed.payload = task.payload
    changed.decision = 'edit'
    assert (await command_settings.apply_approved(changed, rig.orch))['reason'] == 'edit_not_supported'
    assert provider_store.list_records('tts') == []


async def test_full_catalog_refuses_before_enqueue_and_store_failure_does_not_fall_back(rig, monkeypatch):
    for n in range(provider_store.MAX_ACTIVE):
        provider_store.save_approved('tts', f'n{n}', {'argv': ['x']}, expected_revision=0)
    code, reply = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 409 and reply['error'] == 'provider_capacity_full'
    assert rig.q.list() == []
    def unavailable(*args):
        raise provider_store.ProviderStoreError('unavailable')
    monkeypatch.setattr(provider_store, 'load', unavailable)
    code, reply = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 503 and reply['error'] == 'provider_store_unavailable'
    assert settings_db.get_value('voice', 'tts_command', {}) == {}


def test_generic_settings_do_not_install_or_reset_named_authority(rig):
    value = {'argv': ['x'], 'approved_task': 123}
    provider_store.save_approved('tts', 'studio', value, expected_revision=0)
    updated, skipped = settings_db.put_category('voice', {'voice_command_providers': {'studio': {'argv': ['forged']}}})
    assert updated == 0 and skipped == ['voice_command_providers']
    exported = settings_db.export_settings()
    assert 'voice_command_providers' not in str(exported)
    settings_db.reset_category('voice')
    settings_db.undo_last_reset()
    assert provider_store.load('tts', 'studio')['approved_task'] == 123


@pytest.mark.parametrize('selector', ['piper', 'Studio', ' studio', 0, None])
def test_invalid_named_stt_setting_is_rejected(rig, selector):
    assert settings_db.validate_category('voice', {'stt_command_provider': selector})
    assert not settings_db.validate_category('voice', {'stt_command_provider': ''})
    assert not settings_db.validate_category('voice', {'stt_command_provider': 'studio'})


def test_strict_body_rejects_numeric_provider_and_keeps_omission_legacy():
    from pydantic import ValidationError

    from agents.core.routers.voice import VoiceCommandBody
    assert VoiceCommandBody(side='tts').provider_id is None
    with pytest.raises(ValidationError):
        VoiceCommandBody(side='tts', provider_id=42)


def test_status_reports_saved_stt_selection_and_corrupt_catalog_refusal(rig):
    import sqlite3
    settings_db.put_category('voice', {'stt_command_provider': 'studio'})
    assert command_settings.status(rig.orch)['selected_stt_provider'] == 'studio'
    provider_store.clear('tts', 'studio')
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute("UPDATE voice_command_providers SET approved_json='invalid'")
    view = command_settings.status(rig.orch)
    assert view['error'] == 'provider_store_unavailable'
    assert view['providers'] == {'tts': [], 'stt': []}
    assert view['selected_stt_provider'] == 'studio'


async def test_clear_then_recreate_does_not_restore_an_older_pending_approval(rig):
    code, pending = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 202
    revision = provider_store.clear('tts', 'studio')
    assert provider_store.save_approved('tts', 'studio', {'argv': ['new-authority'], 'approved_task': 999},
                                       expected_revision=revision) == 2
    await rig.worker.apply_decision(pending['pending'], 'accept', decided_by='owner')
    await rig.worker.tick()
    assert provider_store.load('tts', 'studio')['approved_task'] == 999
    assert rig.q.get(pending['pending']).result['reason'] == 'provider_revision_conflict'


async def test_actual_named_approvals_on_both_sides_are_independent(rig):
    code, tts = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 202
    stt_argv = [part.replace('{output}', '{audio}') for part in rig.argv]
    code, stt = await command_settings.request(rig.orch, 'stt', stt_argv, provider_id='studio')
    assert code == 202 and stt['pending'] != tts['pending']
    for tid in [tts['pending'], stt['pending']]:
        await rig.worker.apply_decision(tid, 'accept', decided_by='owner')
    await rig.worker.tick()
    await rig.worker.tick()
    assert provider_store.load('tts', 'studio')['approved_task'] == tts['pending']
    assert provider_store.load('stt', 'studio')['approved_task'] == stt['pending']
    assert rig.q.verified_mediation_stats()['valid']


def test_capabilities_corrupt_selected_named_store_is_structured_unavailable(rig):
    import sqlite3

    from agents.core.routers.voice import _local_providers_state
    settings_db.put_category('voice', {'stt_command_provider': 'studio'})
    provider_store.clear('stt', 'studio')
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute("UPDATE voice_command_providers SET approved_json='invalid'")
    view = _local_providers_state(False)
    assert view['provider_store_error'] == 'provider_store_unavailable'
    assert view['selected_stt_ready'] is False and view['stt'] is False
    assert view['selected_stt_provider'] == 'studio'
    assert view['named'] == {'tts': [], 'stt': []}


def test_unrelated_corrupt_named_catalog_does_not_disable_legacy_stt(rig):
    import sqlite3

    from agents.core.routers.voice import _local_providers_state
    from agents.core.voice import local_providers as lp
    argv = [part.replace('{output}', '{audio}') for part in rig.argv]
    files = lp.bound_files(argv, 'stt')
    bound = lp.bound_identities(files)
    settings_db.put_category('voice', {'stt_command': {
        'argv': argv, 'fingerprint': command_settings._fingerprint(argv),
        'exe': bound[0], 'bound': bound, 'approved_task': 12, 'approved_at': 1,
    }, 'stt_engine': 'command', 'stt_command_provider': ''})
    provider_store.clear('tts', 'studio')
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute("UPDATE voice_command_providers SET approved_json='invalid'")
    view = _local_providers_state(False)
    assert view['provider_store_error'] == 'provider_store_unavailable'
    assert view['selected_stt_provider'] is None
    assert view['selected_stt_ready'] and view['stt']


def test_named_capability_metadata_does_not_hash_approved_content(rig, monkeypatch):
    from agents.core.routers.voice import _local_providers_state
    from agents.core.voice import local_providers as lp
    settings_db.put_category('voice', {'stt_command_provider': 'studio'})
    calls = []
    original = lp.command_ready
    def capture(side, *, provider_id=None, verify_content=True):
        if provider_id is not None:
            calls.append(verify_content)
        return original(side, provider_id=provider_id, verify_content=verify_content)
    monkeypatch.setattr(lp, 'command_ready', capture)
    _local_providers_state(False)
    assert calls and not any(calls)


class _Rows:
    """Captures the security audit rows and the intent-log entries a change writes."""

    def __init__(self):
        self.audit, self.intents = [], []

    def log(self, event):
        self.audit.append((event.action_taken, event.content_preview))

    def record(self, **entry):
        self.intents.append(entry)

    def audited(self, action):
        return [preview for taken, preview in self.audit if taken == action]

    def intended(self, action):
        return [entry for entry in self.intents if entry['action'] == action]


async def test_audit_and_intent_rows_name_the_provider_identity(rig):
    """Review F3: a named provider's request, approval and clear name the provider and
    its revision; clearing it never reads as revoking the legacy voice.tts_command.
    Round-2 NIT 1: each row says which revision it means — the request the revision it
    is based on, the approval the revision it wrote, the clear the revision it revoked
    (the one in force, never the tombstone the clear writes) — so a clear matches the
    approval it revoked, and the intent metadata carries the same numbers by name."""
    rows = _Rows()
    rig.orch.audit = rows
    rig.orch.intent_log = rows
    await install(rig, 'studio')
    await install(rig, None)
    requested = rows.audited('voice_command_requested')
    approved = rows.audited('voice_command_approved')
    assert requested[0].startswith("voice.tts provider 'studio' (based on revision 0) change sent to approval")
    assert approved[0].startswith("voice.tts provider 'studio' (now revision 1) approved")
    assert requested[1].startswith('voice.tts_command change sent to approval')
    assert approved[1].startswith('voice.tts_command approved')
    named_set, legacy_set = rows.intended('voice.command.set')
    assert named_set['metadata']['provider_id'] == 'studio'
    assert named_set['metadata']['based_on_revision'] == 0
    assert named_set['metadata']['now_revision'] == 1
    assert 'provider_revision' not in named_set['metadata']
    assert "'studio'" in named_set['why'] and 'now revision 1' in named_set['why']
    assert 'provider_id' not in legacy_set['metadata']

    rows.audit.clear()
    code, named = await command_settings.clear(rig.orch, 'tts', provider_id='studio')
    assert code == 200
    code, _ = await command_settings.clear(rig.orch, 'tts')
    assert code == 200
    named_row, legacy_row = rows.audited('voice_command_cleared')
    assert named_row != legacy_row
    assert named['provider_revision'] == 2          # the tombstone the clear wrote
    assert named_row.startswith("voice.tts provider 'studio' (revoked revision 1) cleared")
    assert 'revision 2' not in named_row
    assert legacy_row.startswith('voice.tts_command cleared')
    named_clear, legacy_clear = rows.intended('voice.command.clear')
    assert named_clear['metadata']['provider_id'] == 'studio'
    assert named_clear['metadata']['revoked_revision'] == named_set['metadata']['now_revision'] == 1
    assert 'provider_revision' not in named_clear['metadata']
    assert "'studio'" in named_clear['why'] and 'revoked revision 1' in named_clear['why']
    assert 'provider_id' not in legacy_clear['metadata']


async def test_clear_names_only_the_revision_in_force(rig):
    """Round 3, item 4: a clear names the revision it actually revoked, read inside its
    own write. Clearing a name with nothing in force — never approved, or already
    cleared — says so and names no revision (not 0, not the tombstone)."""
    rows = _Rows()
    rig.orch.audit = rows
    rig.orch.intent_log = rows
    await install(rig, 'studio')
    answers = []
    for name in ('studio', 'studio', 'never'):
        code, answer = await command_settings.clear(rig.orch, 'tts', provider_id=name)
        assert code == 200
        answers.append(answer['provider_revision'])
    assert answers == [2, 3, 1]                         # the tombstones the clears wrote
    first, second, never = rows.audited('voice_command_cleared')
    assert first.startswith("voice.tts provider 'studio' (revoked revision 1) cleared (was argv sha256 ")
    assert 'argv sha256 none' not in first
    for row, name in ((second, 'studio'), (never, 'never')):
        assert row == f"voice.tts provider '{name}' (nothing in force) cleared", row
        assert 'revision' not in row
    metadata = [entry['metadata'] for entry in rows.intended('voice.command.clear')]
    assert [m['revoked_revision'] for m in metadata] == [1, None, None]
    assert [m['fingerprint'] is None for m in metadata] == [False, True, True]
    whys = [entry['why'] for entry in rows.intended('voice.command.clear')]
    assert "'studio' (revoked revision 1)" in whys[0]
    assert whys[1].endswith("'studio' (nothing in force)") and whys[2].endswith("'never' (nothing in force)")


async def test_clear_names_the_revision_its_own_write_replaced(rig, monkeypatch):
    """An approval that lands between a read and the clear's write must not leave the
    row naming the revision before it: the revision named is the one the write replaced
    (the tombstone minus one), whatever happened before the write."""
    rows = _Rows()
    rig.orch.audit = rows
    rig.orch.intent_log = rows
    await install(rig, 'studio')
    real_load, raced = provider_store.load, []

    def load_then_race(side, provider_id):
        value = real_load(side, provider_id)
        if not raced:
            raced.append(value['provider_revision'])     # before the write, which loads too
            provider_store.save_approved(side, provider_id, {'argv': ['newer'], 'approved_task': 7},
                                         expected_revision=value['provider_revision'])
        return value

    monkeypatch.setattr(provider_store, 'load', load_then_race)
    code, answer = await command_settings.clear(rig.orch, 'tts', provider_id='studio')
    assert code == 200
    revoked = rows.intended('voice.command.clear')[0]['metadata']['revoked_revision']
    assert revoked == answer['provider_revision'] - 1, (revoked, answer, raced)
    assert rows.audited('voice_command_cleared')[0].startswith(
        f"voice.tts provider 'studio' (revoked revision {revoked}) cleared")


@pytest.mark.parametrize('seam', ['read', 'write'])
async def test_provider_store_failure_while_applying_is_a_failure(rig, monkeypatch, seam):
    """Round 3, item 5: ``provider_store_unavailable`` is the store's own I/O failing —
    before the write or during it — so the apply fails (and records a failure) instead
    of being reported as a refusal that ran nothing."""
    code, result = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 202

    def unavailable(*_args, **_kwargs):
        raise provider_store.ProviderStoreError('provider_store_unavailable')

    monkeypatch.setattr(provider_store, 'load' if seam == 'read' else 'save_approved', unavailable)
    await rig.worker.apply_decision(result['pending'], 'accept', decided_by='owner')
    await rig.worker.tick()
    assert rig.q.get(result['pending']).result == {'status': 'failed', 'reason': 'provider_store_unavailable'}
    stats = rig.q.capability_outcome_stats('action:settings.voice_command')
    assert (stats['successes'], stats['failures']) == (0, 1), stats


@pytest.mark.parametrize('seam', ['before_write', 'in_write_conflict', 'in_write_full'])
async def test_revision_conflict_or_full_catalog_while_applying_stays_a_refusal(rig, monkeypatch, seam):
    """A revision conflict or a full catalog is a guard (the write is refused or rolled
    back, nothing written) — found before the write or inside it. It stays a
    ``refused`` result and records no capability outcome."""
    code, result = await command_settings.request(rig.orch, 'tts', rig.argv, provider_id='studio')
    assert code == 202
    expected = 'provider_revision_conflict'
    if seam == 'before_write':
        provider_store.clear('tts', 'studio')          # the owner changed the name meanwhile
    else:
        error = (provider_store.ProviderConflict('provider_revision_conflict') if seam == 'in_write_conflict'
                 else provider_store.ProviderLimit('provider_capacity_full'))
        expected = 'provider_revision_conflict' if seam == 'in_write_conflict' else 'provider_capacity_full'

        def refused(*_args, **_kwargs):
            raise error

        monkeypatch.setattr(provider_store, 'save_approved', refused)
    await rig.worker.apply_decision(result['pending'], 'accept', decided_by='owner')
    await rig.worker.tick()
    assert rig.q.get(result['pending']).result == {'status': 'refused', 'reason': expected}
    stats = rig.q.capability_outcome_stats('action:settings.voice_command')
    assert stats['total'] == 0, stats
