"""Live owner/Kernel/audit decisions precede every H367 authority mutation."""
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.kernel import Decision, Verdict
from agents.core.llm import custom_endpoints as metadata
from agents.core.llm.providers.packages import ProviderPackageError
from tests.test_h361_provider_install_service import owner


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    settings_db.init_db(force=True)
    from agents.core.llm.custom_endpoint_service import CustomEndpointService

    seen = []
    events = []

    def kernel(action, *, approval_check):
        seen.append(action)
        assert approval_check(action) is True
        return Decision(Verdict.GRANT, tier=3)

    audit = SimpleNamespace(log=lambda event: events.append(event))
    svc = CustomEndpointService(root=tmp_path / "custom", home="owner-home",
                                kernel=lambda: kernel, audit=audit)
    return svc, seen, events


def test_create_and_activate_require_owner_kernel_guard_and_audit(service):
    svc, seen, events = service
    with pytest.raises(ProviderPackageError):
        svc.create("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local", actor="owner")
    assert metadata.list_endpoints() == []
    created = svc.create("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local",
                         actor=owner())
    assert created["identity"] == "custom:one"
    assert seen[-1].kind == "provider.custom_endpoint"
    assert events
    with pytest.raises(ProviderPackageError):
        svc.activate("one", expected_revision=created["revision"],
                     expected_choice_epoch=metadata.read_choice().epoch,
                     acknowledge_unknown_price=False, actor=owner())
    assert metadata.read_choice().active_key is None
    chosen = svc.activate("one", expected_revision=created["revision"],
                          expected_choice_epoch=metadata.read_choice().epoch,
                          acknowledge_unknown_price=True, actor=owner())
    assert chosen["active"] == "custom:one"
    assert svc.current_runtime().endpoint.identity == "custom:one"


def test_special_private_ipv4_never_reaches_owner_approval_or_catalog(service):
    svc, seen, events = service
    with pytest.raises(metadata.CustomEndpointInvalid):
        svc.create('bench', 'Bench', 'http://198.18.0.1:9999/v1', 'm',
                   'none', 'unknown', grant_destination=True, actor=owner())
    assert seen == [] and events == []
    assert metadata.list_endpoints() == []


def test_raw_metadata_cannot_mint_consent_and_audit_failure_is_atomic(service):
    svc, _, _ = service
    from agents.core.llm import custom_endpoint_consent

    with pytest.raises(ProviderPackageError):
        custom_endpoint_consent.mint(svc.root, object(), 1, 0, capability=None)
    proposed = metadata.CustomEndpoint('direct', 'Direct', 'http://127.0.0.1:1234/v1',
                                       'm', 'none', 'local', 1, 1)
    with pytest.raises(ProviderPackageError):
        custom_endpoint_consent.mint_creation(svc.root, svc.home, proposed)
    created = svc.create("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local",
                         actor=owner())
    choice = metadata.read_choice()
    metadata.activate_endpoint("one", expected_revision=created["revision"],
                               expected_choice_epoch=choice.epoch, proof="0" * 64)
    assert svc.list(actor=owner())['unavailable'] is True
    with pytest.raises(ProviderPackageError):
        svc.current_runtime()
    metadata.clear_endpoint_choice(expected_choice_epoch=metadata.read_choice().epoch)
    svc.audit = SimpleNamespace(log=lambda event: (_ for _ in ()).throw(OSError("audit down")))
    with pytest.raises(ProviderPackageError):
        svc.activate("one", expected_revision=created["revision"],
                     expected_choice_epoch=metadata.read_choice().epoch,
                     acknowledge_unknown_price=True, actor=owner())
    assert metadata.read_choice().active_key is None


def test_raw_catalog_copy_or_changed_config_cannot_recover_legacy_alias(service):
    svc, _, _ = service
    svc.create('one', 'One', 'http://127.0.0.1:1234/v1',
               'm', 'none', 'local', actor=owner())
    original = metadata.read_endpoint('one')
    assert original.admission_proof
    metadata.create_endpoint('raw', 'Raw', original.base_url, original.model,
                             original.auth_type, original.data_policy,
                             admission_proof=original.admission_proof)
    conn = settings_db.get_conn()
    with conn:
        conn.execute("UPDATE custom_endpoints SET model='changed',config_revision=2,revision=2 "
                     "WHERE key='one'")
    conn.close()
    settings_db.put_category('llm', {'compatible_provider': 'custom'})
    assert svc.list(actor=owner())['legacy_recovery_candidate'] is None


def test_owner_can_clear_malformed_active_choice_without_restoring_old_signed(service):
    svc, _, _ = service
    created = svc.create("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local",
                         actor=owner())
    svc.activate("one", expected_revision=created["revision"],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    conn = settings_db.get_conn()
    with conn:
        conn.execute("UPDATE custom_endpoint_choice SET consent_proof='broken' WHERE singleton=1")
    conn.close()
    with pytest.raises(metadata.CustomEndpointInvalid):
        svc.current_runtime()
    assert svc.list(actor=owner())['unavailable'] is True
    cleared = svc.clear(expected_choice_epoch=metadata._with_read(
        lambda conn: conn.execute('SELECT epoch FROM provider_choice_epoch').fetchone()[0]),
        actor=owner())
    assert cleared['active'] is None
    assert metadata.read_choice().active_key is None


def test_real_kernel_sealed_owner_receipt_and_kill_switch(service, tmp_path):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.security.capability import KillSwitch

    svc, _, _ = service
    kill = KillSwitch(tmp_path / 'custom-kill.json')
    orch = SimpleNamespace(autonomy=SimpleNamespace(policy=AutonomyPolicy()),
                           kill_switch=kill, capabilities=None, intent_log=None)
    bound = make_action_kernel(orch)
    decisions = []
    def kernel(action, *, approval_check):
        decision = bound(action, approval_check=approval_check)
        decisions.append((action, decision))
        return decision
    svc.kernel = lambda: kernel
    created = svc.create('one', 'One', 'http://127.0.0.1:1234/v1', 'm',
                         'none', 'local', actor=owner())
    assert created['identity'] == 'custom:one'
    assert decisions[-1][1].verdict is Verdict.GRANT
    assert decisions[-1][1].tier == 3
    assert bound(decisions[-1][0]).verdict is Verdict.QUEUE
    kill.engage('provider:custom:two', reason='synthetic halt')
    with pytest.raises(ProviderPackageError):
        svc.create('two', 'Two', 'http://127.0.0.1:1235/v1', 'm',
                   'none', 'local', actor=owner())
    assert metadata.read_endpoint('two') is None


def test_kernel_off_or_denied_never_creates_or_audits(service, monkeypatch):
    svc, seen, events = service
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '0')
    with pytest.raises(ProviderPackageError):
        svc.create('off', 'Off', 'http://127.0.0.1:1234/v1',
                   'm', 'none', 'local', actor=owner())
    assert seen == events == []
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    svc.kernel = lambda: (lambda action, *, approval_check:
                          Decision(Verdict.DENY, tier=3))
    with pytest.raises(ProviderPackageError):
        svc.create('denied', 'Denied', 'http://127.0.0.1:1234/v1',
                   'm', 'none', 'local', actor=owner())
    assert metadata.list_endpoints() == []
    assert events == []


def test_lan_and_public_activation_need_fresh_exact_destination_grant(service):
    svc, seen, events = service
    metadata.create_endpoint('raw-public', 'Raw', 'https://endpoint.invalid/v1',
                             'm', 'none', 'unknown')
    with pytest.raises(ProviderPackageError):
        svc.activate('raw-public', expected_revision=1,
                     expected_choice_epoch=metadata.read_choice().epoch,
                     acknowledge_unknown_price=True, acknowledge_data_policy=True,
                     actor=owner())
    assert metadata.read_choice().active_key is None
    assert seen == events == []
    chosen = svc.activate('raw-public', expected_revision=1,
                          expected_choice_epoch=metadata.read_choice().epoch,
                          acknowledge_unknown_price=True, acknowledge_data_policy=True,
                          grant_destination=True, actor=owner())
    assert chosen['active'] == 'custom:raw-public'
    assert seen[-1].payload['grant_destination'] is True
    assert events


def test_legacy_bare_custom_reports_first_owner_authorized_candidate_only(service):
    svc, _, _ = service
    metadata.create_endpoint('aa-raw', 'Raw', 'http://127.0.0.1:1233/v1',
                             'm', 'none', 'local')
    svc.create('bb-owner', 'Owner', 'http://127.0.0.1:1234/v1',
               'm', 'none', 'local', actor=owner())
    svc.create('cc-owner', 'Other', 'http://127.0.0.1:1235/v1',
               'm', 'none', 'local', actor=owner())
    settings_db.put_category('llm', {'compatible_provider': 'custom'})
    assert svc.list(actor=owner())['legacy_recovery_candidate'] == 'custom:bb-owner'
    assert metadata.read_choice().active_key is None


def test_unreadable_legacy_hint_is_silent_about_values_and_cannot_activate(service, monkeypatch, caplog):
    svc, _, _ = service
    svc.create('one', 'One', 'http://127.0.0.1:1234/v1',
               'm', 'none', 'local', actor=owner())

    def unreadable(*_args):
        raise RuntimeError('private setting value')

    monkeypatch.setattr(settings_db, 'read_setting', unreadable)
    status = svc.list(actor=owner())
    assert status['legacy_recovery_candidate'] is None
    assert status['active'] is None
    assert metadata.read_choice().active_key is None
    assert 'custom endpoint legacy hint unavailable' in caplog.text
    assert 'private setting value' not in caplog.text


def test_bare_custom_alias_of_proven_active_choice_self_heals_without_new_consent(service):
    svc, seen, events = service
    created = svc.create('one', 'One', 'http://127.0.0.1:1234/v1', 'm',
                         'none', 'local', actor=owner())
    svc.activate('one', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    before = metadata.read_choice()
    decisions, audits = len(seen), len(events)
    settings_db.put_category('llm', {'compatible_provider': 'custom'})
    assert metadata.read_choice() == before
    assert svc.current_runtime().endpoint.identity == 'custom:one'
    assert settings_db.compatible_pair_state()[1] == 'custom:one'
    assert metadata.read_choice() == before
    assert (len(seen), len(events)) == (decisions, audits)


def test_unproved_bare_custom_alias_does_not_restore_prior_choice(service):
    svc, _, _ = service
    created = svc.create('one', 'One', 'http://127.0.0.1:1234/v1', 'm',
                         'none', 'local', actor=owner())
    svc.activate('one', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    settings_db.put_category('llm', {'compatible_model': 'different'})
    settings_db.put_category('llm', {'compatible_provider': 'custom'})
    assert metadata.read_choice().active_key is None
    assert svc.current_runtime() is None
    assert svc.list(actor=owner())['legacy_recovery_candidate'] == 'custom:one'


def test_legacy_candidate_skips_earlier_raw_and_missing_credential(service):
    svc, _, _ = service
    metadata.create_endpoint('aa-raw', 'Raw', 'http://127.0.0.1:1233/v1',
                             'm', 'none', 'local')
    svc.create('bb-no-key', 'Needs key', 'http://127.0.0.1:1234/v1',
               'm', 'bearer', 'unknown', actor=owner())
    svc.create('cc-ready', 'Ready', 'http://127.0.0.1:1235/v1',
               'm', 'none', 'local', actor=owner())
    settings_db.put_category('llm', {'compatible_provider': 'custom'})
    assert svc.list(actor=owner())['legacy_recovery_candidate'] == 'custom:cc-ready'


def test_proofless_legacy_candidate_recovers_only_after_owner_activation(service):
    svc, _, _ = service
    created = svc.create('one', 'One', 'http://127.0.0.1:1234/v1',
                         'm', 'none', 'local', actor=owner())
    settings_db.put_category('llm', {'compatible_provider': 'custom'})
    assert svc.current_runtime() is None
    assert svc.list(actor=owner())['legacy_recovery_candidate'] == 'custom:one'
    svc.activate('one', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    assert svc.current_runtime().check().identity == 'custom:one'
    assert settings_db.compatible_pair_state()[1] == 'custom:one'


def test_bare_alias_repairs_later_authorized_choice_not_first_catalog_row(service):
    svc, _, _ = service
    metadata.create_endpoint('aa-raw', 'Raw', 'http://127.0.0.1:1233/v1',
                             'm', 'none', 'local')
    created = svc.create('zz-current', 'Current', 'http://127.0.0.1:1234/v1',
                         'm', 'none', 'local', actor=owner())
    svc.activate('zz-current', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    settings_db.put_category('llm', {'compatible_provider': 'custom'})
    assert svc.current_runtime().endpoint.identity == 'custom:zz-current'
    assert settings_db.compatible_pair_state()[1] == 'custom:zz-current'


@pytest.mark.parametrize('writer', ['provider', 'model', 'import', 'reset', 'undo', 'init_force'])
def test_generic_writers_invalidate_different_effective_choice(service, writer):
    svc, _, _ = service
    created = svc.create('one', 'One', 'http://127.0.0.1:1234/v1',
                         'm', 'none', 'local', actor=owner())
    if writer == 'undo':
        settings_db.put_category('llm', {'compatible_provider': 'openrouter'})
        settings_db.reset_settings('llm')
    svc.activate('one', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    old = metadata.read_choice()
    if writer == 'provider':
        settings_db.put_category('llm', {'compatible_provider': 'openrouter'})
    elif writer == 'model':
        settings_db.put_category('llm', {'compatible_model': 'other'})
    elif writer == 'import':
        settings_db.apply_import({'llm': {'compatible_provider': 'openrouter'}})
    elif writer == 'reset':
        settings_db.put_category('llm', {'compatible_provider': 'custom'})
        settings_db.reset_settings('llm')
    elif writer == 'undo':
        settings_db.undo_last_reset()
    else:
        settings_db.init_db(force=True)
    assert metadata.read_choice().active_key is None
    assert metadata.read_choice().epoch > old.epoch
    assert svc.current_runtime() is None


def test_idempotent_init_preserves_proven_current_choice(service):
    svc, _, _ = service
    created = svc.create('one', 'One', 'http://127.0.0.1:1234/v1',
                         'm', 'none', 'local', actor=owner())
    svc.activate('one', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    choice = metadata.read_choice()
    settings_db.init_db()
    assert metadata.read_choice() == choice
    assert svc.current_runtime().check().identity == 'custom:one'


def test_active_rename_keeps_stable_identity_and_existing_exact_consent(service):
    svc, _, _ = service
    created = svc.create('one', 'One', 'http://127.0.0.1:1234/v1',
                         'm', 'none', 'local', actor=owner())
    svc.activate('one', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    old = metadata.read_choice()
    runtime = svc.current_runtime()
    renamed = svc.rename('one', 'New display', expected_revision=created['revision'], actor=owner())
    assert renamed['identity'] == 'custom:one'
    assert renamed['active'] is True
    assert metadata.read_choice() == old
    assert runtime.check().identity == 'custom:one'
