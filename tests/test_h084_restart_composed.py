"""Real signed restart queue and Kernel; only the process stopper is replaced."""
from types import SimpleNamespace

import pytest

from agents.core import hub_restart_apply as restart
from agents.core.autonomy import irreversible
from agents.core.command_source import bind_source
from agents.core.kernel import authorize, revalidate
from agents.core.kernel.binding import MediationKernelBridge
from agents.core.restart_runtime import runtime_for
from tests.test_h084_restart_authority import _source
from tests.test_h084_update_kernel import _rig


@pytest.fixture
def rig(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    restart.hub_update.reset_for_tests()
    monkeypatch.setattr(restart.backup, 'boot_restore_due', lambda: False)
    monkeypatch.setattr(restart.backup, 'restore_in_progress', lambda: False)
    monkeypatch.setattr(restart.hub_update_apply, 'current', lambda: None)
    rig.worker.policy.mode = 'auto'
    rig.orch.sender_pairing = SimpleNamespace(is_allowed=lambda *_: True)
    rig.orch.restart_work_pending = lambda: False
    rig.runtime = runtime_for(rig.orch)
    rig.worker._restart_runtime = rig.runtime
    rig.executor._restart_runtime = rig.runtime
    rig.effects = []

    def kernel(action, **kw):
        return authorize(action, policy=rig.worker.policy)

    def current(action, capability=None, *, approval_check=None):
        return revalidate(action, policy=rig.worker.policy, approval_check=approval_check)

    kernel.revalidate = current
    rig.worker._mediation_kernel = MediationKernelBridge(kernel)

    async def execute(task):
        return await irreversible.execute(task, orch=rig.orch)

    rig.executor.register('hub.restart', execute)

    async def completed(task_id, digest):
        assert rig.queue.get(task_id).status == 'done'
        assert rig.runtime.snapshot()['active'] == 0
        rig.effects.append('committed and released')
        return await restart.after_completion(rig.orch, task_id, digest)

    rig.worker._restart_completed = completed

    def stop(reason):
        assert rig.effects == ['committed and released']
        assert not rig.runtime.snapshot()['accepting']
        assert rig.runtime.snapshot()['active'] == 0
        rig.effects.append('stop')
        return True

    monkeypatch.setattr(restart.hub_restart, 'request', stop)
    yield rig
    rig.queue.close()
    restart.hub_update.reset_for_tests()


async def request(rig):
    source, principal = _source(rig)
    with bind_source(source):
        result = await restart.request_restart(rig.orch, principal=principal, source=source)
    assert 'pending' in result, result
    return result['pending']


@pytest.mark.asyncio
async def test_signed_request_worker_done_then_one_physical_effect(rig):
    task_id = await request(rig)
    assert rig.effects == []
    await rig.worker.tick()
    assert rig.effects == []
    await rig.worker.apply_decision(task_id, 'accept', decided_by='owner')
    assert rig.effects == []
    result = await rig.worker.tick()
    assert result['done'] == 1, (result, rig.queue.get(task_id))
    assert rig.effects == ['committed and released', 'stop']
    task = rig.queue.get(task_id)
    assert task.status == 'done' and task.attempts == 1
    assert await restart.after_completion(rig.orch, task_id, task.result['intent_digest']) == {'status': 'refused'}
    assert rig.effects.count('stop') == 1


@pytest.mark.asyncio
async def test_failed_done_commit_never_calls_post_completion(rig, monkeypatch):
    task_id = await request(rig)
    await rig.worker.apply_decision(task_id, 'accept', decided_by='owner')
    monkeypatch.setattr(rig.queue, 'complete_restart', lambda *_: None)
    await rig.worker.tick()
    assert rig.effects == []
    assert rig.queue.get(task_id).status == 'failed'
    assert rig.runtime.snapshot()['accepting']
    await rig.worker.tick()
    assert rig.effects == []


@pytest.mark.asyncio
async def test_approval_mode_revoked_before_execution_never_stops(rig):
    task_id = await request(rig)
    await rig.worker.apply_decision(task_id, 'accept', decided_by='owner')
    rig.worker.policy.mode = 'ask'
    await rig.worker.tick()
    assert rig.effects == []
    assert rig.runtime.snapshot()['accepting']


@pytest.mark.asyncio
async def test_post_done_hook_error_never_requeues_effect(rig):
    task_id = await request(rig)
    await rig.worker.apply_decision(task_id, 'accept', decided_by='owner')

    async def broken(*_):
        raise RuntimeError('post-DONE hook unavailable')

    rig.worker._restart_completed = broken
    await rig.worker.tick()
    task = rig.queue.get(task_id)
    assert task.status == 'done' and task.attempts == 1
    assert rig.queue.claim_restart_physical(task_id, task.result['intent_digest'], restart.BOOT_ID) is None
    await rig.worker.tick()
    assert rig.effects == []


@pytest.mark.asyncio
async def test_missing_post_done_hook_releases_unspent_intent(rig):
    task_id = await request(rig)
    await rig.worker.apply_decision(task_id, 'accept', decided_by='owner')
    rig.worker._restart_completed = None
    await rig.worker.tick()
    task = rig.queue.get(task_id)
    assert task.status == 'done'
    assert rig.queue.claim_restart_physical(task_id, task.result['intent_digest'], restart.BOOT_ID) is None
    assert rig.effects == []


@pytest.mark.asyncio
async def test_policy_revoked_after_done_refuses_without_replaying_task(rig):
    task_id = await request(rig)
    await rig.worker.apply_decision(task_id, 'accept', decided_by='owner')

    async def revoked(task_id, digest):
        assert rig.queue.get(task_id).status == 'done'
        rig.worker.policy.mode = 'off'
        return await restart.after_completion(rig.orch, task_id, digest)

    rig.worker._restart_completed = revoked
    await rig.worker.tick()
    task = rig.queue.get(task_id)
    assert task.status == 'done'
    assert rig.queue.claim_restart_physical(task_id, task.result['intent_digest'], restart.BOOT_ID) is None
    assert rig.effects == []
    assert rig.runtime.snapshot()['accepting']


@pytest.mark.asyncio
async def test_boot_recovery_of_old_unspent_intent_is_metadata_only_when_disabled(rig):
    from tests.test_h084_restart_authority import _signed_completion

    task_id, arm, _verified, _ticket = await _signed_completion(rig, boot_id='a' * 32)
    rig.queue.mediation_mode = 'off'
    await restart.after_boot(rig.orch)
    # Recording a known no-effect old-boot intent requires historical evidence,
    # not new execution authority. Physical execution and notification stay off.
    row = rig.queue._conn.execute(
        'SELECT physical_state FROM task_restart_intents WHERE task_id=?', (task_id,)).fetchone()
    assert row['physical_state'] == 'refused'
    assert rig.effects == []
    rig.queue.mediation_mode = 'enforce'
    assert rig.queue.claim_restart_physical(task_id, arm.intent_digest, 'a' * 32) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', ['recall:untrusted', 'external', 'model', 'manual'])
async def test_derived_origin_cannot_be_reclassified_by_restart_source(rig, origin):
    from agents.core.action_origin import (
        bind_action_origin,
        current_action_origin,
        reset_action_origin,
    )

    source, principal = _source(rig)
    token = bind_action_origin(origin)
    try:
        with bind_source(source):
            result = await restart.request_restart(rig.orch, principal=principal, source=source)
        assert result == {'refused': 'original_owner_dm_required'}
        assert current_action_origin() == origin
        assert rig.queue.list() == []
    finally:
        reset_action_origin(token)


@pytest.mark.asyncio
async def test_model_producer_cannot_use_original_command_context(rig, monkeypatch):
    from agents.core.autonomy import approval_grouping

    source, principal = _source(rig)
    monkeypatch.setattr(approval_grouping, 'current_model_producer', lambda: object())
    with bind_source(source):
        result = await restart.request_restart(rig.orch, principal=principal, source=source)
    assert result == {'refused': 'original_owner_dm_required'}
    assert rig.queue.list() == []


@pytest.mark.asyncio
async def test_original_owner_intake_restores_inbound_origin_and_generic_taint_remains(rig):
    from agents.core.action_origin import (
        bind_action_origin,
        current_action_origin,
        reset_action_origin,
    )
    from agents.core.autonomy.restart_records import KIND, PREVIEW, TITLE
    from tests.test_h084_restart_authority import _payload_and_ticket

    # A copied signed ticket is not a context-wide declassification permission.
    payload, _ticket = _payload_and_ticket(rig, update_id=81)
    token = bind_action_origin('inbound')
    try:
        generic = irreversible.enqueue(rig.orch, KIND, title=TITLE, payload=payload, preview=PREVIEW)
        assert 'refused' in generic and rig.queue.list() == []
        source, principal = _source(rig)
        with bind_source(source):
            result = await restart.request_restart(rig.orch, principal=principal, source=source)
        assert current_action_origin() == 'inbound'
        assert 'pending' in result
        task = rig.queue.get(result['pending'])
        assert task.origin == 'manual' and 'tainted' not in task.payload
        assert task.status == 'blocked' and task.attempts == 0
    finally:
        reset_action_origin(token)


@pytest.mark.asyncio
async def test_intake_cancellation_restores_inbound_origin(rig, monkeypatch):
    import asyncio

    from agents.core.action_origin import (
        bind_action_origin,
        current_action_origin,
        reset_action_origin,
    )

    async def cancelled(*args):
        assert current_action_origin() == 'manual'
        raise asyncio.CancelledError

    monkeypatch.setattr(restart, '_owned_enqueue', cancelled)
    source, principal = _source(rig)
    token = bind_action_origin('inbound')
    try:
        with bind_source(source), pytest.raises(asyncio.CancelledError):
            await restart.request_restart(rig.orch, principal=principal, source=source)
        assert current_action_origin() == 'inbound'
        assert rig.queue.list() == []
    finally:
        reset_action_origin(token)
