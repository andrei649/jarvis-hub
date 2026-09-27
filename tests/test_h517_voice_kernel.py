"""Voice command registration crosses the real strict worker and signed queue."""
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.autonomy import irreversible
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kernel import Decision, Verdict
from agents.core.kernel.binding import MediationKernelBridge
from agents.core.voice import command_settings
from tests.test_h613_piper_command_voice import _py
from tests.test_task_mediation_evidence import NOW_MS, _head_anchor, _signer


def make_rig(tmp_path, monkeypatch, *, mode='enforce', kernel=None, missing=False):
    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    monkeypatch.setenv('JARVIS_VOICE_COMMANDS', '1')
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.delenv('JARVIS_SAFE_MODE', raising=False)
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    script = tmp_path / 'speech.py'
    script.write_text('print("synthetic speech provider")\n')
    script.chmod(0o700)
    argv = [_py(), str(script), '{output}']
    path = tmp_path / 'queue.db'
    q = TaskQueue(str(path), mediation_mode=mode, mediation_signer=_signer(),
                  mediation_head_anchor=_head_anchor(path), mediation_scope='global',
                  mediation_policy_revision='voice-test', mediation_clock_ms=lambda: NOW_MS).initialize()
    calls = []
    def authorize(action, **kwargs):
        calls.append(action)
        return Decision(Verdict.GRANT, reason='owner requested', tier=0)
    bridge = None if missing else MediationKernelBridge(kernel or authorize)
    worker = AutonomyWorker(q, policy=AutonomyPolicy(mode='act'), kernel=bridge,
                            mediation_signer=_signer(), mediation_clock_ms=lambda: NOW_MS)
    orch = SimpleNamespace(autonomy=worker, autonomy_queue=q, audit=None, intent_log=None)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    async def execute(task):
        return await irreversible.execute(task, orch=orch)
    executor.register(command_settings.APPROVAL_KIND, execute)
    worker.executor = executor.execute
    return SimpleNamespace(q=q, worker=worker, orch=orch, argv=argv, calls=calls, executor=executor)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    value = make_rig(tmp_path, monkeypatch)
    yield value
    value.q.close()


async def request(rig):
    return await command_settings.request(rig.orch, 'tts', rig.argv)


async def test_real_strict_request_keeps_human_floor_and_writes_only_on_execution(rig):
    code, response = await request(rig)
    assert code == 202, response
    tid = response['pending']
    task = rig.q.get(tid)
    assert task.status == 'blocked' and task.risk_tier == 3 and task.autonomy_level == 'ask'
    assert task.mediation_receipt['verdict'] == 'grant'
    assert task.mediation_receipt['effective_tier'] == 3
    assert rig.q.pending_group(tid) is None
    assert rig.q.pending_groups() == []
    assert settings_db.get_value('voice', 'tts_command', {}) == {}
    await rig.worker.apply_decision(tid, 'accept', decided_by='owner')
    assert settings_db.get_value('voice', 'tts_command', {}) == {}
    await rig.worker.tick()
    assert rig.q.get(tid).status == 'done', rig.q.get(tid).result
    stored = settings_db.get_value('voice', 'tts_command', {})
    assert stored['approved_task'] == tid and stored['argv'] == rig.argv
    assert rig.q.verified_mediation_stats()['valid']
    assert len(rig.calls) >= 1


@pytest.mark.parametrize('mode', ['hold', 'enforce'])
async def test_hold_or_unavailable_kernel_never_registers(tmp_path, monkeypatch, mode):
    value = make_rig(tmp_path, monkeypatch, mode=mode, missing=(mode == 'enforce'))
    try:
        code, _ = await request(value)
        assert code == 503 and value.q.list() == []
        assert settings_db.get_value('voice', 'tts_command', {}) == {}
    finally:
        value.q.close()


@pytest.mark.parametrize('verdict', [Verdict.DENY, None])
async def test_kernel_refusal_prevents_intake_write(tmp_path, monkeypatch, verdict):
    def refuse(action):
        return None if verdict is None else Decision(verdict, reason='refused', tier=3)
    value = make_rig(tmp_path, monkeypatch, kernel=refuse)
    try:
        code, _ = await request(value)
        assert code == 503 and value.q.list() == []
        assert settings_db.get_value('voice', 'tts_command', {}) == {}
    finally:
        value.q.close()


async def test_existing_non_strict_registration_stays_compatible(tmp_path, monkeypatch):
    value = make_rig(tmp_path, monkeypatch, mode='off', missing=True)
    try:
        monkeypatch.delenv('JARVIS_ACTION_KERNEL', raising=False)
        code, response = await request(value)
        assert code == 202
        await value.worker.apply_decision(response['pending'], 'accept', decided_by='owner')
        await value.worker.tick()
        assert settings_db.get_value('voice', 'tts_command', {})['approved_task'] == response['pending']
    finally:
        value.q.close()


@pytest.mark.parametrize('machine', ['policy', 'system', 'kernel', 'worker'])
async def test_machine_decision_cannot_install_command(rig, machine):
    code, response = await request(rig)
    assert code == 202
    await rig.worker.apply_decision(response['pending'], 'accept', decided_by=machine)
    await rig.worker.tick()
    assert settings_db.get_value('voice', 'tts_command', {}) == {}
    assert rig.q.get(response['pending']).result['reason'] == 'human_decision_required'


async def test_owner_edit_is_not_registration_of_different_program(rig):
    from agents.core.autonomy.queue import TaskStatus
    code, response = await request(rig)
    assert code == 202
    rig.q.transition(response['pending'], TaskStatus.APPROVED, decided_by='owner', decision='edit', human_reason=None)
    await rig.worker.tick()
    assert settings_db.get_value('voice', 'tts_command', {}) == {}
    assert rig.q.get(response['pending']).result['reason'] == 'edit_not_supported'


async def test_valid_mediated_but_unrecorded_request_is_not_owner_registration(rig):
    from agents.core.voice import local_providers as lp
    ready = await command_settings.request(rig.orch, 'tts', rig.argv, dry_run=True)
    assert ready[0] == 200
    problems, _ = lp.validate_command(rig.argv, 'tts')
    assert not problems
    tid = rig.worker.govern_enqueue('owner', command_settings.APPROVAL_KIND, 'Forged provider',
        payload={'side': 'tts', 'argv': rig.argv, 'risk_tier': 3, 'reversible': False},
        risk_tier=3, autonomy_level='ask', origin='manual')
    await rig.worker.apply_decision(tid, 'accept', decided_by='owner')
    await rig.worker.tick()
    assert rig.q.get(tid).result['reason'] == 'not_requested'
    assert settings_db.get_value('voice', 'tts_command', {}) == {}


@pytest.mark.parametrize('drift', ['file', 'setting', 'unarmed', 'safe_mode'])
async def test_live_registration_preconditions_are_rechecked_before_write(rig, monkeypatch, drift):
    code, response = await request(rig)
    assert code == 202
    await rig.worker.apply_decision(response['pending'], 'accept', decided_by='owner')
    if drift == 'file':
        from pathlib import Path
        Path(rig.argv[1]).write_text('print("changed")\n')
    elif drift == 'setting':
        settings_db.put_category('voice', {'tts_command': {'fingerprint': 'another-approved-value'}})
    elif drift == 'unarmed':
        monkeypatch.delenv('JARVIS_VOICE_COMMANDS')
    else:
        monkeypatch.setenv('JARVIS_SAFE_MODE', '1')
    await rig.worker.tick()
    stored = settings_db.get_value('voice', 'tts_command', {})
    assert not stored.get('argv')


@pytest.mark.parametrize('revoke', ['receipt', 'scope', 'policy', 'halt'])
async def test_actual_worker_refuses_revoked_execution_evidence(rig, revoke):
    code, response = await request(rig)
    assert code == 202
    await rig.worker.apply_decision(response['pending'], 'accept', decided_by='owner')
    if revoke == 'receipt':
        rig.q._conn.execute('UPDATE tasks SET mediation_receipt=? WHERE id=?', ('{}', response['pending']))
        rig.q._conn.commit()
    elif revoke == 'scope':
        rig.q._mediation_scope = 'different-owner-scope'
    elif revoke == 'policy':
        rig.q._mediation_policy_revision = 'new-policy'
    else:
        rig.worker._kill_switch = SimpleNamespace(is_halted=lambda *args: True)
    await rig.worker.tick()
    assert settings_db.get_value('voice', 'tts_command', {}) == {}


def test_registration_is_exact_without_settings_wildcard():
    from agents.core.kernel.registry import Mediation, classify, known_broker_action_kinds
    assert classify(command_settings.APPROVAL_KIND) is Mediation.KERNEL
    assert command_settings.APPROVAL_KIND in known_broker_action_kinds()
    assert classify('settings.retention') is None
    assert classify('settings.arbitrary') is None


@pytest.mark.parametrize('missing', ['signer', 'kernel_flag'])
async def test_strict_intake_requires_signed_kernel_evidence(rig, monkeypatch, missing):
    if missing == 'signer':
        rig.worker._mediation_signer = None
        rig.q._mediation_signer = None
    else:
        monkeypatch.delenv('JARVIS_ACTION_KERNEL')
    code, _ = await request(rig)
    assert code == 503 and rig.q.list() == []
    assert settings_db.get_value('voice', 'tts_command', {}) == {}


async def test_direct_executor_dispatch_requires_private_worker_claim(rig):
    code, response = await request(rig)
    assert code == 202
    await rig.worker.apply_decision(response['pending'], 'accept', decided_by='owner')
    result = await rig.executor.execute(rig.q.get(response['pending']))
    assert result == {'status': 'refused', 'reason': 'mediation_execution_context_required'}
    assert settings_db.get_value('voice', 'tts_command', {}) == {}
    await rig.worker.tick()
    assert settings_db.get_value('voice', 'tts_command', {})['approved_task'] == response['pending']


def test_voice_manifest_exposes_human_floor_and_truthful_revoke_contract():
    from agents.core.capability_manifests import manifest_for_action
    manifest = manifest_for_action(command_settings.APPROVAL_KIND)
    assert manifest is not None
    assert manifest.risk == 'irreversible_or_money'
    assert manifest.confidence == 0.0
    assert 'human-approval' in manifest.requires
    assert 'recorded-request' in manifest.requires
    assert manifest.implementation == 'agents.core.voice.command_settings:apply_approved'
    assert set(manifest.inputs['required']) == {
        'side', 'argv', 'fingerprint', 'exe_identity', 'bound', 'before_fingerprint', 'preview',
    }
    assert manifest.rollback.mode == 'revoke' and not manifest.rollback.automatic
    assert manifest.rollback.handler_ref == 'agents.core.voice.command_settings:clear'
    assert 'future' in manifest.rollback.description.lower()
    assert 'not undone' in manifest.rollback.limitations.lower()
