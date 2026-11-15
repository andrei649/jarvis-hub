"""Physical-phase ordering with a fake stopper; signed proof is tested separately."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.core import hub_restart_apply as restart
from agents.core.autonomy.restart_records import PhysicalClaim, VerifiedRestart
from agents.core.restart_runtime import runtime_for


@pytest.fixture
def rig(monkeypatch):
    restart.hub_update.reset_for_tests()
    monkeypatch.setattr(restart.hub_restart, 'available', lambda: True)
    monkeypatch.setattr(restart.hub_update_apply, 'current', lambda: None)
    monkeypatch.setattr(restart.backup, 'boot_restore_due', lambda: False)
    monkeypatch.setattr(restart.backup, 'restore_in_progress', lambda: False)
    recipient = {'current': True}
    monkeypatch.setattr(restart, 'recipient_current', lambda *a: recipient['current'])
    monkeypatch.setattr(restart, '_kernel_current', lambda *a, **kw: kw['check']())
    events = []
    meta = VerifiedRestart(7, 'a' * 64, restart.BOOT_ID, 'telegram:8:9', 8, 42, 42)

    class Queue:
        mediation_mode = 'enforce'
        consumed = False
        valid = True

        def validate_restart_completion(self, task_id, digest, **kwargs):
            return meta if self.valid and (task_id, digest) == (meta.task_id, meta.intent_digest) else None

        def get(self, task_id):
            return SimpleNamespace(id=task_id)

        def claim_restart_physical(self, *args):
            if self.consumed:
                return None
            self.consumed = True
            events.append('claim committed')
            return PhysicalClaim('owned-claim', meta)

        def finish_restart_physical(self, claim, outcome):
            events.append(('finished', outcome))
            return True

        def refuse_restart_physical(self, *args):
            if not self.consumed:
                events.append('unclaimed refused')
            return not self.consumed

    queue = Queue()
    worker = SimpleNamespace(queue=queue, policy=object())
    orch = SimpleNamespace(autonomy=worker, autonomy_queue=queue, restart_work_pending=lambda: False)
    runtime = runtime_for(orch)

    def stop(reason):
        assert events[0] == 'claim committed'
        assert not runtime.snapshot()['accepting']
        assert runtime.snapshot()['active'] == 0
        events.append('stopper called')
        return True

    monkeypatch.setattr(restart.hub_restart, 'request', stop)
    yield SimpleNamespace(orch=orch, queue=queue, meta=meta, runtime=runtime,
                          events=events, recipient=recipient)
    restart.hub_update.reset_for_tests()


async def wait_closed(runtime):
    for _ in range(100):
        if not runtime.snapshot()['accepting']:
            return
        await asyncio.sleep(0.001)
    pytest.fail('drain did not close admission')


@pytest.mark.asyncio
async def test_drain_finishes_existing_work_before_one_stopper_call(rig):
    lease = rig.runtime.acquire('job')
    pending = asyncio.create_task(restart.after_completion(rig.orch, 7, 'a' * 64))
    await wait_closed(rig.runtime)
    assert 'stopper called' not in rig.events
    lease.release()
    assert await pending == {'status': 'requested'}
    assert rig.events == ['claim committed', 'stopper called', ('finished', 'requested')]
    assert not rig.runtime.snapshot()['accepting']
    assert any(row['status'] == 'running' for row in restart.hub_update._ACTIONS.values())
    assert await restart.after_completion(rig.orch, 7, 'a' * 64) == {'status': 'refused'}
    assert rig.events.count('stopper called') == 1


@pytest.mark.asyncio
async def test_timeout_is_known_no_effect_and_reopens_only_owned_gate(rig, monkeypatch):
    monkeypatch.setattr(restart, 'DRAIN_SECONDS', 0)
    lease = rig.runtime.acquire('job')
    assert await restart.after_completion(rig.orch, 7, 'a' * 64) == {'status': 'refused'}
    assert rig.runtime.snapshot()['accepting']
    assert rig.events == ['claim committed', ('finished', 'refused')]
    lease.release()


@pytest.mark.asyncio
async def test_cancellation_during_drain_records_no_effect(rig):
    lease = rig.runtime.acquire('job')
    pending = asyncio.create_task(restart.after_completion(rig.orch, 7, 'a' * 64))
    await wait_closed(rig.runtime)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert rig.runtime.snapshot()['accepting']
    assert rig.events == ['claim committed', ('finished', 'refused')]
    lease.release()


@pytest.mark.asyncio
async def test_recipient_revoked_while_work_finishes_prevents_stop(rig):
    lease = rig.runtime.acquire('job')
    pending = asyncio.create_task(restart.after_completion(rig.orch, 7, 'a' * 64))
    await wait_closed(rig.runtime)
    rig.recipient['current'] = False
    lease.release()
    assert await pending == {'status': 'refused'}
    assert rig.runtime.snapshot()['accepting']
    assert 'stopper called' not in rig.events


@pytest.mark.asyncio
async def test_stopper_exception_is_unknown_and_never_replayed(rig, monkeypatch):
    def uncertain(_reason):
        rig.events.append('stop attempted')
        raise RuntimeError('stopper outcome uncertain')

    monkeypatch.setattr(restart.hub_restart, 'request', uncertain)
    assert await restart.after_completion(rig.orch, 7, 'a' * 64) == {'status': 'unknown'}
    assert ('finished', 'unknown') in rig.events
    assert not rig.runtime.snapshot()['accepting']
    assert await restart.after_completion(rig.orch, 7, 'a' * 64) == {'status': 'refused'}
    assert rig.events.count('stop attempted') == 1


@pytest.mark.asyncio
async def test_invalid_completion_never_closes_gate_or_stops(rig):
    rig.queue.valid = False
    assert await restart.after_completion(rig.orch, 7, 'a' * 64) == {'status': 'refused'}
    assert rig.runtime.snapshot()['accepting']
    assert rig.events == ['unclaimed refused']


@pytest.mark.asyncio
async def test_unreadable_update_marker_prevents_physical_stop(rig, tmp_path, monkeypatch):
    directory = tmp_path / 'update'
    directory.mkdir()
    (directory / 'current.json').write_text('{broken')
    monkeypatch.setattr(restart.hub_update_apply, 'state_dir', lambda: directory)
    assert await restart.after_completion(rig.orch, 7, 'a' * 64) == {'status': 'refused'}
    assert 'stopper called' not in rig.events
    assert rig.runtime.snapshot()['accepting']
