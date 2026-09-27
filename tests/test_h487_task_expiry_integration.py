"""Persisted approval expiry consumers; all dispatch remains offline."""
from types import SimpleNamespace

import pytest

from agents.core.autonomy.work_runs import WorkRunError, WorkRunLedger

STAMP = '2026-09-27T12:00:00.000000+00:00'


def open_run(ledger, name='goal'):
    return ledger.open_run(SimpleNamespace(goal_id=name, title=name, approved_by='owner'))


def ask(ledger, run, task_id=1):
    return ledger.record_step(run.id, kind='ask', summary='owner decision', outcome='queued', task_id=task_id)


def test_atomic_expiry_resumes_once_and_old_receipt_cannot_resume_later_block(tmp_path):
    path = tmp_path / 'runs.db'
    ledger = WorkRunLedger(path, clock=lambda: 1000)
    run = open_run(ledger)
    source = ask(ledger, run)
    identity = ledger.get(run.id).fingerprint
    settled = ledger.settle_expired_ask(run.id, source.seq, task_id=1, expired_at=STAMP)
    assert settled.first_settlement and settled.resumed
    assert ledger.steps(run.id)[0].outcome == 'failed'
    assert ledger.steps(run.id)[0].detail['resolution'] == 'expired_unanswered'
    assert ledger.get(run.id).fingerprint == identity
    later = ask(ledger, run, 2)
    ledger.close()
    ledger = WorkRunLedger(path, clock=lambda: 1000)
    repeated = ledger.settle_expired_ask(run.id, source.seq, task_id=1, expired_at=STAMP)
    assert repeated.settled and not repeated.first_settlement and not repeated.resumed
    assert ledger.get(run.id).status == 'blocked'
    assert ledger.outstanding_asks(run.id)[0].seq == later.seq
    ledger.close()


@pytest.mark.parametrize('hold', ['legacy', 'budget', 'stopping'])
def test_expiry_closes_ask_without_resuming_unproven_or_other_block(hold):
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    source = ask(ledger, run)
    if hold == 'legacy':
        ledger._conn.execute('UPDATE runs SET approval_block_seq=NULL WHERE id=?', (run.id,))
        ledger._conn.commit()
    elif hold == 'budget':
        ledger._conn.execute("UPDATE runs SET stop_reason='budget:interrupts' WHERE id=?", (run.id,))
        ledger._conn.commit()
    else:
        ledger.request_stop(run.id)
    result = ledger.settle_expired_ask(run.id, source.seq, task_id=1, expired_at=STAMP)
    assert result.settled and not result.resumed
    assert ledger.steps(run.id)[0].outcome == 'failed'
    ledger.close()


def test_shared_task_sources_all_settle_and_only_last_ask_resumes():
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    first, second = ask(ledger, run), ask(ledger, run)
    assert [s.seq for s in ledger.pending_asks_for_task(1, limit=1)] == [first.seq]
    assert not ledger.settle_expired_ask(run.id, first.seq, task_id=1, expired_at=STAMP).resumed
    assert ledger.settle_expired_ask(run.id, second.seq, task_id=1, expired_at=STAMP).resumed
    assert ledger.pending_asks_for_task(1) == []
    with pytest.raises(WorkRunError):
        ledger.settle_expired_ask(run.id, second.seq, task_id=9, expired_at=STAMP)
    ledger.close()


def test_failed_atomic_resume_rolls_back_step_and_run(monkeypatch):
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    source = ask(ledger, run)
    transition = ledger._transition_locked
    def fail(*args, **kwargs):
        transition(*args, **kwargs)
        raise RuntimeError('crash before commit')
    monkeypatch.setattr(ledger, '_transition_locked', fail)
    with pytest.raises(RuntimeError):
        ledger.settle_expired_ask(run.id, source.seq, task_id=1, expired_at=STAMP)
    assert ledger.get(run.id).status == 'blocked'
    assert ledger.outstanding_asks(run.id)[0].seq == source.seq
    monkeypatch.setattr(ledger, '_transition_locked', transition)
    assert ledger.settle_expired_ask(run.id, source.seq, task_id=1, expired_at=STAMP).resumed
    ledger.close()

from datetime import UTC, datetime, timezone

from agents.core.autonomy.pending_requests import PendingRequests
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv('JARVIS_COMPANY_MODE', '1')
    from agents.core.autonomy import queue as queue_module
    original = queue_module._approval_now
    monkeypatch.setattr(queue_module, '_approval_now',
                        lambda now=None: original(now or datetime(2026,9,27,11,tzinfo=UTC)))
    q = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    yield q
    q.close()


def expired_task(queue):
    task_id = queue.enqueue('jarvis', 'delete_file', 'old ask', approval_deadline_at=STAMP)
    queue.transition(task_id, TaskStatus.BLOCKED)
    queue.expire_pending_approvals(now=datetime(2026, 9, 27, 12, tzinfo=UTC))
    return queue.get(task_id)


def test_reconcile_mixed_answers_uses_atomic_expiry_without_generic_resume(queue, monkeypatch):
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    expired = expired_task(queue)
    accepted_id = queue.enqueue('jarvis', 'delete_file', 'accepted ask')
    queue.transition(accepted_id, TaskStatus.APPROVED)
    source = ask(ledger, run, expired.id)
    ask(ledger, run, accepted_id)
    monkeypatch.setattr(ledger, 'resume', lambda *args: pytest.fail('nonatomic second resume'))
    result = PendingRequests(ledger, read_task=queue.get).reconcile(run.id)
    assert result.resumed
    assert {o.resolution for o in result.outcomes} == {'approved', 'expired_unanswered'}
    out = next(o for o in result.outcomes if o.step_seq == source.seq)
    assert out.by_machine and not out.human_reason
    assert ledger.get(run.id).status == 'working'
    ledger.close()


@pytest.mark.asyncio
async def test_housekeeping_drains_all_shared_sources_with_bounded_continuation(queue):
    task = expired_task(queue)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    runs = [open_run(ledger, str(i)) for i in range(3)]
    for run in runs:
        ask(ledger, run, task.id)
    worker = AutonomyWorker(queue)
    worker.work_run_ledger = ledger
    await worker.approval_housekeeping(limit=1)
    assert queue.pending_approval_expiry_effects().effects
    await worker.approval_housekeeping(limit=1)
    await worker.approval_housekeeping(limit=1)
    assert queue.pending_approval_expiry_effects().effects == ()
    assert all(ledger.get(r.id).status == 'working' for r in runs)
    ledger.close()


@pytest.mark.asyncio
async def test_halt_sweeps_only_metadata_then_release_reconciles(queue):
    task_id = queue.enqueue('jarvis', 'delete_file', 'due', approval_deadline_at=STAMP)
    queue.transition(task_id, TaskStatus.BLOCKED)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    ask(ledger, run, task_id)
    halted = [True]
    worker = AutonomyWorker(queue, kill_switch=SimpleNamespace(is_halted=lambda *args: halted[0]), clock=lambda: datetime(2026,9,27,12,tzinfo=UTC).timestamp())
    worker.work_run_ledger = ledger
    cleared = []
    worker.approval_judge = SimpleNamespace(clear_pending=cleared.append)
    await worker.tick()
    assert queue.get(task_id).status == 'expired'
    assert cleared == [task_id]
    assert ledger.outstanding_asks(run.id)
    assert queue.pending_approval_expiry_effects().effects
    halted[0] = False
    await worker.tick()
    assert ledger.get(run.id).status == 'working'
    assert queue.pending_approval_expiry_effects().effects == ()
    ledger.close()


@pytest.mark.asyncio
async def test_audit_failure_preserves_effect_and_retry_is_idempotent(queue):
    task = expired_task(queue)
    broken = [True]
    def log(*args):
        if broken[0]:
            raise OSError('disk unavailable')
    worker = AutonomyWorker(queue, audit=SimpleNamespace(log=log))
    await worker.approval_housekeeping()
    assert queue.pending_approval_expiry_effects().effects
    broken[0] = False
    await worker.approval_housekeeping()
    assert queue.pending_approval_expiry_effects().effects == ()
    assert not queue.get(task.id).decision


@pytest.mark.asyncio
async def test_intake_deadline_is_ask_only(queue):
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    auto = await worker.submit('jarvis', 'draft_email', 'auto', approval_deadline_at=STAMP)
    pending = await worker.submit('jarvis', 'delete_file', 'ask', approval_deadline_at=STAMP)
    assert auto.status == 'approved' and auto.approval_deadline_at is None
    assert pending.approval_deadline_at == STAMP

@pytest.mark.parametrize('deadline', [True, 42, '2026-09-27', '2099-01-01T00:00:00', 'no-date', '2000-01-01T00:00:00Z'])
def test_owner_task_schema_rejects_invalid_or_past_deadline(deadline):
    from pydantic import ValidationError

    from agents.core.routers.autonomy import AutonomyTaskBody
    with pytest.raises(ValidationError):
        AutonomyTaskBody(agent='jarvis', kind='delete_file', title='ask', approval_deadline_at=deadline)


def test_owner_task_schema_normalizes_offset():
    from agents.core.routers.autonomy import AutonomyTaskBody
    body = AutonomyTaskBody(agent='jarvis', kind='delete_file', title='ask', approval_deadline_at='2099-01-01T02:00:00+02:00')
    assert body.approval_deadline_at == '2099-01-01T00:00:00.000000+00:00'


def test_task_judge_does_not_snapshot_due_ask_before_sweep(queue, monkeypatch):
    import agents.core.autonomy.queue as queue_module
    from agents.core.autonomy.task_approval_judge import TaskApprovalJudge
    task_id = queue.enqueue('jarvis', 'delete_file', 'due', approval_deadline_at=STAMP)
    queue.transition(task_id, TaskStatus.BLOCKED)
    judge = TaskApprovalJudge(queue)
    assert judge._snapshot(queue.get(task_id)) is not None
    monkeypatch.setattr(queue_module, '_approval_now', lambda now=None: datetime(2026,9,27,12,tzinfo=UTC))
    assert judge._snapshot(queue.get(task_id)) is None


@pytest.mark.asyncio
async def test_failed_effect_does_not_starve_later_reconciliation(queue):
    tasks = [expired_task(queue), expired_task(queue)]
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    ask(ledger, run, tasks[1].id)
    def log(_event, metadata):
        if metadata['task_id'] == tasks[0].id:
            raise OSError('one record fails')
    worker = AutonomyWorker(queue, audit=SimpleNamespace(log=log))
    worker.work_run_ledger = ledger
    await worker.approval_housekeeping(limit=1)
    assert ledger.get(run.id).status == 'blocked'
    await worker.approval_housekeeping(limit=1)
    assert ledger.get(run.id).status == 'working'
    assert [e.task_id for e in queue.pending_approval_expiry_effects().effects] == [tasks[0].id]
    ledger.close()

@pytest.mark.asyncio
async def test_housekeeping_mixed_run_closes_other_answer_before_expiry(queue):
    task = expired_task(queue)
    accepted_id = queue.enqueue('jarvis', 'draft_email', 'answered')
    queue.transition(accepted_id, TaskStatus.APPROVED)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    ask(ledger, run, task.id)
    ask(ledger, run, accepted_id)
    worker = AutonomyWorker(queue)
    worker.work_run_ledger = ledger
    await worker.approval_housekeeping()
    assert ledger.get(run.id).status == 'working'
    assert ledger.outstanding_asks(run.id) == []
    assert queue.pending_approval_expiry_effects().effects == ()
    ledger.close()


@pytest.mark.asyncio
async def test_coordinator_estop_invokes_only_metadata_housekeeping(queue, monkeypatch):
    import asyncio

    from agents.core import estop
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    calls = []
    async def housekeeping(**kwargs):
        calls.append(kwargs)
    sleeps = [0]
    async def one_tick(_seconds):
        sleeps[0] += 1
        if sleeps[0] == 2:
            raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'sleep', one_tick)
    monkeypatch.setattr(estop, 'check_paused', lambda *args: True)
    orch = SimpleNamespace(get_setting=lambda *args: 15,
                           autonomy=SimpleNamespace(approval_housekeeping=housekeeping))
    with pytest.raises(asyncio.CancelledError):
        await AutonomyCoordinator(orch).loop()
    assert calls == [{'reconcile': False, 'notify_promotions': False}]


def test_owner_http_deadline_roundtrip_and_late_decision_conflict(queue, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import autonomy
    from agents.core.routers._deps import admin_guard
    worker = AutonomyWorker(queue)
    monkeypatch.setattr(autonomy, 'get_orch', lambda: SimpleNamespace(autonomy=worker, autonomy_queue=queue))
    monkeypatch.setitem(web.app.dependency_overrides, admin_guard, lambda: None)
    client = TestClient(web.app)
    payload = {'agent': 'jarvis', 'kind': 'delete_file', 'title': 'owner ask',
               'approval_deadline_at': '2099-01-01T02:00:00+02:00'}
    response = client.post('/autonomy/tasks', json=payload)
    assert response.status_code == 200
    task = response.json()['task']
    assert task['approval_deadline_at'] == '2099-01-01T00:00:00.000000+00:00'
    queue.expire_pending_approvals(now=datetime(2099,1,1,tzinfo=UTC))
    response = client.post(f"/autonomy/tasks/{task['id']}/decision", json={'action': 'accept'})
    assert response.status_code == 409
    assert queue.get(task['id']).status == 'expired'
    assert not queue.get(task['id']).human_decision
    before = len(queue.list())
    payload['approval_deadline_at'] = '2000-01-01T00:00:00Z'
    assert client.post('/autonomy/tasks', json=payload).status_code == 422
    assert len(queue.list()) == before


def test_interrupt_budget_hold_clears_approval_epoch():
    from agents.core.autonomy.work_runs import Budget
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = ledger.open_run(SimpleNamespace(goal_id='budget', title='budget', approved_by='owner'),
                          budget=Budget(max_interrupts=0))
    source = ask(ledger, run)
    with pytest.raises(WorkRunError):
        ledger.record_step(run.id, kind='ask', summary='another', outcome='queued', task_id=2, interrupted=True)
    result = ledger.settle_expired_ask(run.id, source.seq, task_id=1, expired_at=STAMP)
    assert not result.resumed
    assert ledger.get(run.id).status == 'blocked'
    assert ledger.get(run.id).stop_reason == 'budget:interrupts'
    ledger.close()


@pytest.mark.asyncio
async def test_more_than_one_ask_page_keeps_effect_until_every_source_settles(queue):
    from agents.core.autonomy.work_runs import Budget
    task = expired_task(queue)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = ledger.open_run(SimpleNamespace(goal_id='many', title='many', approved_by='owner'),
                          budget=Budget(max_steps=200))
    for _ in range(101):
        ask(ledger, run, task.id)
    worker = AutonomyWorker(queue)
    worker.work_run_ledger = ledger
    await worker.approval_housekeeping(limit=1)
    assert queue.pending_approval_expiry_effects().effects
    assert len(ledger.outstanding_asks(run.id)) == 1
    await worker.approval_housekeeping(limit=1)
    assert ledger.get(run.id).status == 'working'
    assert queue.pending_approval_expiry_effects().effects == ()
    ledger.close()


@pytest.mark.asyncio
async def test_promoted_group_notification_failure_retries_from_outbox(queue):
    from agents.core.autonomy.inbox import OwnerTaskRegistrationContext
    request = {'agent':'jarvis', 'kind':'delete_file', 'title':'same', 'payload':{'path':'old'}}
    context = OwnerTaskRegistrationContext.from_request(request)
    notifications = []
    delivered = [True]
    class Broker:
        async def dispatch(self, _id, _category, callback):
            if not delivered[0]:
                return {'status':'downgraded'}
            await callback()
            return {'status':'delivered'}
    async def notify(task):
        notifications.append(task.id)
        return True
    worker = AutonomyWorker(queue, notifier=notify, delivery_broker=Broker())
    first = await worker.submit(**request, grouping_context=context, approval_deadline_at=STAMP)
    second = await worker.submit(**request, grouping_context=context)
    assert notifications == [first.id]
    delivered[0] = False
    await worker.approval_housekeeping(now=datetime(2026,9,27,12,tzinfo=UTC))
    assert queue.get(first.id).status == 'expired' and queue.get(second.id).status == 'blocked'
    assert queue.pending_approval_expiry_effects().effects
    delivered[0] = True
    await worker.approval_housekeeping()
    assert notifications == [first.id, second.id]
    assert queue.pending_approval_expiry_effects().effects == ()
    await worker.approval_housekeeping()
    assert notifications == [first.id, second.id]


def test_http_deadline_passing_during_intake_reports_committed_task_without_push(queue, monkeypatch):
    from fastapi.testclient import TestClient

    import agents.core.autonomy.queue as queue_module
    from agents import web
    from agents.core.routers import autonomy
    from agents.core.routers._deps import admin_guard
    async def notify(_task):
        pytest.fail('expired intake must not push')
    worker = AutonomyWorker(queue, notifier=notify)
    monkeypatch.setattr(autonomy, 'get_orch', lambda: SimpleNamespace(autonomy=worker, autonomy_queue=queue))
    monkeypatch.setitem(web.app.dependency_overrides, admin_guard, lambda: None)
    monkeypatch.setattr(queue_module, '_approval_now', lambda now=None: datetime(2100,1,1,tzinfo=UTC))
    response = TestClient(web.app).post('/autonomy/tasks', json={
        'agent':'jarvis', 'kind':'delete_file', 'title':'ask', 'approval_deadline_at':'2099-01-01T00:00:00Z',
    })
    assert response.status_code == 409
    task, = queue.list()
    assert task.status == 'expired'
    assert response.json()['expired_task_ids'] == [task.id]
    assert queue.pending_approval_expiry_effects().effects


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['accept', 'reject', 'defer', 'edit'])
async def test_due_decision_without_sweep_consumes_exact_effect_immediately(queue, monkeypatch, action):
    import agents.core.autonomy.queue as queue_module
    from agents.core.autonomy.queue import TaskApprovalExpired
    task_id = queue.enqueue('jarvis', 'delete_file', 'due decision', approval_deadline_at=STAMP)
    queue.transition(task_id, TaskStatus.BLOCKED)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    ask(ledger, run, task_id)
    worker = AutonomyWorker(queue)
    worker.work_run_ledger = ledger
    cleared = []
    worker.approval_judge = SimpleNamespace(clear_pending=cleared.append)
    monkeypatch.setattr(queue_module, '_approval_now', lambda now=None: datetime(2026,9,27,12,tzinfo=UTC))
    with pytest.raises(TaskApprovalExpired):
        await worker.apply_decision(task_id, action, payload={'path':'changed'} if action == 'edit' else None)
    assert queue.get(task_id).status == 'expired'
    assert queue.get(task_id).payload == {}
    assert not queue.get(task_id).human_decision
    assert cleared == [task_id]
    assert ledger.get(run.id).status == 'working'
    assert queue.pending_approval_expiry_effects().effects == ()
    ledger.close()


@pytest.mark.asyncio
async def test_due_group_without_sweep_retains_whole_group_conflict_and_promotes(queue, monkeypatch):
    import agents.core.autonomy.queue as queue_module
    from agents.core.autonomy.inbox import OwnerTaskRegistrationContext
    body = {'agent':'jarvis', 'kind':'delete_file', 'title':'same', 'payload':{'path':'old'}}
    context = OwnerTaskRegistrationContext.from_request(body)
    worker = AutonomyWorker(queue)
    first = await worker.submit(**body, grouping_context=context, approval_deadline_at=STAMP)
    second = await worker.submit(**body, grouping_context=context)
    group, = queue.pending_groups()
    cleared = []
    worker.approval_judge = SimpleNamespace(clear_pending=cleared.append)
    monkeypatch.setattr(queue_module, '_approval_now', lambda now=None: datetime(2026,9,27,12,tzinfo=UTC))
    result = await worker.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'])
    assert result is None
    assert queue.get(first.id).status == 'expired' and queue.get(second.id).status == 'blocked'
    assert cleared == [first.id]
    assert queue.pending_approval_expiry_effects().effects == ()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['delete','mismatch'])
async def test_selected_receipt_is_reread_before_any_effect(queue, monkeypatch, change):
    task = expired_task(queue)
    queue._conn.execute("UPDATE task_approval_expiry_effects SET group_id='old-group' WHERE task_id=?", (task.id,))
    queue._conn.commit()
    original = queue.pending_approval_expiry_effects
    def selected(**kwargs):
        batch = original(**kwargs)
        if change == 'delete':
            queue._conn.execute('DELETE FROM tasks WHERE id=?', (task.id,))
        else:
            queue._conn.execute("UPDATE tasks SET expired_at='2099-01-01T00:00:00.000000+00:00' WHERE id=?", (task.id,))
        queue._conn.commit()
        return batch
    monkeypatch.setattr(queue, 'pending_approval_expiry_effects', selected)
    monkeypatch.setattr(queue, 'pending_group_leader', lambda *args: pytest.fail('stale promotion'))
    worker = AutonomyWorker(queue, audit=SimpleNamespace(log=lambda *args: pytest.fail('stale audit')))
    worker.work_run_ledger = SimpleNamespace(pending_asks_for_task=lambda *args, **kwargs: pytest.fail('stale reconcile'))
    await worker.approval_housekeeping()
    assert original().effects == ()


@pytest.mark.asyncio
async def test_disabled_company_mode_retains_only_relevant_effect_for_reenable(queue, monkeypatch):
    task = expired_task(queue)
    unrelated = expired_task(queue)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    run = open_run(ledger)
    ask(ledger, run, task.id)
    worker = AutonomyWorker(queue)
    worker.work_run_ledger = ledger
    monkeypatch.setenv('JARVIS_COMPANY_MODE','0')
    await worker.approval_housekeeping()
    assert ledger.get(run.id).status == 'blocked'
    assert [e.task_id for e in queue.pending_approval_expiry_effects().effects] == [task.id]
    assert queue.get(unrelated.id).status == 'expired'
    monkeypatch.setenv('JARVIS_COMPANY_MODE','1')
    await worker.approval_housekeeping()
    assert ledger.get(run.id).status == 'working'
    assert queue.pending_approval_expiry_effects().effects == ()
    ledger.close()


# ── review F5: runs blocked before migration v3 (no approval_block_seq) ──────


def legacy_v2_blocked_run(path, task_id, monkeypatch):
    """A runs DB as the pre-v3 ledger (bd2bb70e) left a run blocked on one ask:
    schema v2 (no ``approval_block_seq``), the run opened with the unchanged
    ``open_run``, and the queued step written with that ledger's own SQL."""
    import sqlite3

    from agents.core.autonomy import work_runs
    from agents.core.persistence.migrations import schema_version

    with monkeypatch.context() as m:
        m.setattr(work_runs, 'MIGRATIONS', work_runs.MIGRATIONS[:2])
        old = WorkRunLedger(path, clock=lambda: 1000)
        run = open_run(old)
        cur = old._conn.execute(
            """INSERT INTO steps (run_id, kind, summary, outcome, task_id, interrupted, at, detail)
               VALUES (?, 'ask', 'owner decision', 'queued', ?, 0, 1000, '{}')""", (run.id, task_id))
        old._conn.execute(
            """UPDATE runs SET steps_used = steps_used + 1, interrupts_used = 0,
                   status = 'blocked', updated_at = 1000 WHERE id = ?""", (run.id,))
        old._conn.commit()
        seq = cur.lastrowid
        old.close()
    conn = sqlite3.connect(str(path))
    try:
        assert schema_version(conn) == 2
        assert 'approval_block_seq' not in {row[1] for row in conn.execute('PRAGMA table_info(runs)')}
    finally:
        conn.close()
    return run, seq


def upgraded(path, queue, *, clock=lambda: 1000):
    ledger = WorkRunLedger(path, clock=clock)
    ledger.bind_approval_task_reader(queue.get)     # as company_runtime binds it
    return ledger


def test_legacy_block_resumes_once_the_owner_answers(queue, tmp_path, monkeypatch):
    task_id = queue.enqueue('jarvis', 'delete_file', 'owner decision')
    queue.transition(task_id, TaskStatus.BLOCKED)
    path = tmp_path / 'runs.db'
    run, seq = legacy_v2_blocked_run(path, task_id, monkeypatch)
    ledger = upgraded(path, queue)
    try:
        marker = ledger._conn.execute('SELECT approval_block_seq FROM runs WHERE id=?', (run.id,)).fetchone()[0]
        assert marker is None
        reconciler = PendingRequests(ledger, read_task=queue.get)
        waiting = reconciler.reconcile(run.id)
        assert not waiting.resumed and ledger.get(run.id).status == 'blocked'
        queue.transition(task_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        result = reconciler.reconcile(run.id)
        assert result.resumed, result.note
        assert [(o.step_seq, o.resolution) for o in result.outcomes] == [(seq, 'approved')]
        assert ledger.get(run.id).status == 'working'
        assert not reconciler.reconcile(run.id).resumed
    finally:
        ledger.close()


@pytest.mark.parametrize('hold', ['stop_reason', 'barrier', 'budget', 'second_ask_waiting'])
def test_legacy_block_keeps_every_hold_the_marked_resume_has(queue, tmp_path, monkeypatch, hold):
    task_id = queue.enqueue('jarvis', 'delete_file', 'owner decision')
    queue.transition(task_id, TaskStatus.BLOCKED)
    path = tmp_path / 'runs.db'
    run, _ = legacy_v2_blocked_run(path, task_id, monkeypatch)
    clock = (lambda: 1000 + 9 * 3600) if hold == 'budget' else (lambda: 1000)
    ledger = upgraded(path, queue, clock=clock)
    try:
        if hold == 'stop_reason':
            ledger._conn.execute("UPDATE runs SET stop_reason='budget:interrupts' WHERE id=?", (run.id,))
        elif hold == 'barrier':
            ledger._conn.execute("""UPDATE runs SET barrier='{"id":"b1","kind":"deadline"}' WHERE id=?""",
                                 (run.id,))
        elif hold == 'second_ask_waiting':
            other = queue.enqueue('jarvis', 'delete_file', 'second decision')
            queue.transition(other, TaskStatus.BLOCKED)
            ledger._conn.execute(
                """INSERT INTO steps (run_id, kind, summary, outcome, task_id, interrupted, at, detail)
                   VALUES (?, 'ask', 'owner decision', 'queued', ?, 0, 1000, '{}')""", (run.id, other))
        ledger._conn.commit()
        queue.transition(task_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        result = PendingRequests(ledger, read_task=queue.get).reconcile(run.id)
        assert not result.resumed, result.note
        assert ledger.get(run.id).status == 'blocked'
    finally:
        ledger.close()


def test_expired_legacy_block_is_still_held(queue, tmp_path, monkeypatch):
    expired = expired_task(queue)
    path = tmp_path / 'runs.db'
    run, seq = legacy_v2_blocked_run(path, expired.id, monkeypatch)
    ledger = upgraded(path, queue)
    try:
        monkeypatch.setattr(ledger, 'resume', lambda *args: pytest.fail('expiry must not resume a legacy block'))
        result = PendingRequests(ledger, read_task=queue.get).reconcile(run.id)
        assert not result.resumed and result.note == 'expiry settled; run held'
        assert [(o.step_seq, o.resolution) for o in result.outcomes] == [(seq, 'expired_unanswered')]
        assert ledger.get(run.id).status == 'blocked'
        assert ledger.outstanding_asks(run.id) == []
    finally:
        ledger.close()


def _fails_first_read(queue):
    """A task reader whose first call raises (a briefly locked queue), then reads."""
    calls = {'n': 0}

    def read(task_id):
        calls['n'] += 1
        if calls['n'] == 1:
            raise OSError('queue briefly locked')
        return queue.get(task_id)
    return read, calls


def test_expired_legacy_block_is_held_when_the_first_read_fails(queue, tmp_path, monkeypatch):
    """Round-2 MINOR 1: the first read of the only ask raises, so the pass does not know
    up front that it is an expiry; the ask is re-read, found expired and settled. That
    settlement holds an unmarked block, and the pass must not then resume it through
    the pre-v3 path as if the owner had answered."""
    expired = expired_task(queue)
    path = tmp_path / 'runs.db'
    run, seq = legacy_v2_blocked_run(path, expired.id, monkeypatch)
    ledger = upgraded(path, queue)
    try:
        monkeypatch.setattr(ledger, 'resume_unmarked_after_asks',
                            lambda *args: pytest.fail('expiry must not resume a legacy block'))
        read, calls = _fails_first_read(queue)
        result = PendingRequests(ledger, read_task=read).reconcile(run.id)
        assert calls['n'] == 2
        assert [(o.step_seq, o.resolution) for o in result.outcomes] == [(seq, 'expired_unanswered')]
        assert not result.resumed and result.note == 'expiry settled; run held'
        assert ledger.get(run.id).status == 'blocked'
        assert ledger.outstanding_asks(run.id) == []
    finally:
        ledger.close()


def test_expiry_found_on_a_reread_reports_the_atomic_resume_of_a_marked_block(queue, monkeypatch):
    """The same transient read on a marked block: the expiry settlement resumes the run
    atomically, and the pass reports that resume instead of trying a second one."""
    expired = expired_task(queue)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    ledger.bind_approval_task_reader(queue.get)
    try:
        run = open_run(ledger)
        ask(ledger, run, expired.id)
        monkeypatch.setattr(ledger, 'resume_after_asks',
                            lambda *args, **kwargs: pytest.fail('nonatomic second resume'))
        read, _ = _fails_first_read(queue)
        result = PendingRequests(ledger, read_task=read).reconcile(run.id)
        assert result.resumed and result.note == 'expiry settled atomically'
        assert [o.resolution for o in result.outcomes] == ['expired_unanswered']
        assert ledger.get(run.id).status == 'working'
    finally:
        ledger.close()


def test_expiry_found_on_a_reread_still_settles_after_the_other_answers(queue, monkeypatch):
    """An expiry learned only on the re-read is ordered like any other expiry: after the
    ordinary answers, so its settlement closes the epoch instead of leaving a marked run
    blocked with every ask answered and nothing left that could resume it."""
    expired = expired_task(queue)
    accepted_id = queue.enqueue('jarvis', 'delete_file', 'accepted ask')
    queue.transition(accepted_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    ledger.bind_approval_task_reader(queue.get)
    try:
        run = open_run(ledger)
        first = ask(ledger, run, expired.id)          # its first read fails
        ask(ledger, run, accepted_id)
        read, _ = _fails_first_read(queue)
        result = PendingRequests(ledger, read_task=read).reconcile(run.id)
        assert result.resumed and result.note == 'expiry settled atomically', result.note
        assert [o.resolution for o in result.outcomes] == ['approved', 'expired_unanswered']
        assert result.outcomes[-1].step_seq == first.seq
        assert ledger.get(run.id).status == 'working'
    finally:
        ledger.close()


def test_unmarked_resume_refuses_a_marked_block_and_an_open_ask(queue, tmp_path, monkeypatch):
    marked = WorkRunLedger(':memory:', clock=lambda: 1000)
    try:
        run = open_run(marked)
        step = ask(marked, run)
        marked.resolve_step(run.id, step.seq, outcome='refused')
        assert marked.approval_block_seq(run.id) == step.seq
        with pytest.raises(WorkRunError, match='approval_resume_held'):
            marked.resume_unmarked_after_asks(run.id)
        assert marked.get(run.id).status == 'blocked'
    finally:
        marked.close()
    path = tmp_path / 'runs.db'
    legacy_run, seq = legacy_v2_blocked_run(path, 1, monkeypatch)
    ledger = upgraded(path, queue)
    try:
        ledger.record_step(legacy_run.id, kind='ask', summary='second', outcome='queued', task_id=2)
        assert ledger.approval_block_seq(legacy_run.id) is None
        ledger.resolve_step(legacy_run.id, seq, outcome='refused')
        with pytest.raises(WorkRunError, match='approval_resume_held'):
            ledger.resume_unmarked_after_asks(legacy_run.id)
        assert ledger.get(legacy_run.id).status == 'blocked'
    finally:
        ledger.close()


@pytest.mark.parametrize('status', ['planning', 'working', 'succeeded'])
def test_unmarked_resume_refuses_a_run_that_is_not_blocked(status):
    """Round-2 NIT 3: the pre-v3 resume moves only a BLOCKED run. A run with no marker
    because it never blocked (planning, working) or has finished (succeeded) is held:
    no ask was answered that could move it, and a finished run is never reopened."""
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    try:
        run = open_run(ledger)
        if status != 'planning':
            ledger.record_step(run.id, kind='act', summary='did one thing', outcome='ok')
        if status == 'succeeded':
            ledger.record_verdict(run.id, role='verifier', passed=True, reason='holds')
            ledger.record_verdict(run.id, role='judge', passed=True, reason='goal met')
        assert ledger.get(run.id).status == status
        assert ledger.approval_block_seq(run.id) is None
        with pytest.raises(WorkRunError, match='approval_resume_held'):
            ledger.resume_unmarked_after_asks(run.id)
        assert ledger.get(run.id).status == status
    finally:
        ledger.close()


def _legacy_block_on(queue, path, monkeypatch, task_ids):
    """A pre-v3 run blocked on one ask per task id (no approval_block_seq)."""
    run, _ = legacy_v2_blocked_run(path, task_ids[0], monkeypatch)
    ledger = upgraded(path, queue)
    for task_id in task_ids[1:]:
        ledger._conn.execute(
            """INSERT INTO steps (run_id, kind, summary, outcome, task_id, interrupted, at, detail)
               VALUES (?, 'ask', 'owner decision', 'queued', ?, 0, 1000, '{}')""", (run.id, task_id))
    ledger._conn.execute("UPDATE runs SET steps_used = ? WHERE id=?", (len(task_ids), run.id))
    ledger._conn.commit()
    return ledger, run


def test_legacy_block_stays_held_when_its_expiry_settled_in_an_earlier_pass(queue, tmp_path, monkeypatch):
    """Round 3, item 6 (pre-existing): ask A of an unmarked block expires unanswered and
    is settled in pass 1 while ask B still waits; the owner approves B and pass 2 sees
    only that answer. The block still has an ask nobody answered, so it stays held —
    the hold is read from the block's asks, not from what this pass settled."""
    expired = expired_task(queue)
    pending_id = queue.enqueue('jarvis', 'delete_file', 'second ask')
    queue.transition(pending_id, TaskStatus.BLOCKED)
    ledger, run = _legacy_block_on(queue, tmp_path / 'runs.db', monkeypatch, [expired.id, pending_id])
    try:
        reconciler = PendingRequests(ledger, read_task=queue.get)
        first = reconciler.reconcile(run.id)
        assert first.note == 'expiry settled; run held'
        assert [o.resolution for o in first.outcomes] == ['waiting', 'expired_unanswered']
        queue.transition(pending_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        second = reconciler.reconcile(run.id)
        assert [o.resolution for o in second.outcomes] == ['approved']
        assert not second.resumed, second.note
        assert ledger.get(run.id).status == 'blocked'
        assert ledger.outstanding_asks(run.id) == []
        with pytest.raises(WorkRunError, match='approval_resume_held'):
            ledger.resume_unmarked_after_asks(run.id)
    finally:
        ledger.close()


def test_legacy_block_resumes_when_every_ask_was_answered_across_passes(queue, tmp_path, monkeypatch):
    """The hold is the expiry, not the second pass: two asks answered in two passes
    (none expired) still resume the unmarked block."""
    first_id = queue.enqueue('jarvis', 'delete_file', 'first ask')
    second_id = queue.enqueue('jarvis', 'delete_file', 'second ask')
    for task_id in (first_id, second_id):
        queue.transition(task_id, TaskStatus.BLOCKED)
    ledger, run = _legacy_block_on(queue, tmp_path / 'runs.db', monkeypatch, [first_id, second_id])
    try:
        reconciler = PendingRequests(ledger, read_task=queue.get)
        queue.transition(first_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        assert not reconciler.reconcile(run.id).resumed
        queue.transition(second_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        result = reconciler.reconcile(run.id)
        assert result.resumed, result.note
        assert ledger.get(run.id).status == 'working'
    finally:
        ledger.close()


def test_marked_block_resumes_after_an_expiry_settled_in_an_earlier_pass(queue):
    """Marked runs keep their contract: the expiry settled in pass 1 held the run only
    because B still waited; B's approval in pass 2 closes the epoch and resumes it."""
    expired = expired_task(queue)
    pending_id = queue.enqueue('jarvis', 'delete_file', 'second ask')
    queue.transition(pending_id, TaskStatus.BLOCKED)
    ledger = WorkRunLedger(':memory:', clock=lambda: 1000)
    ledger.bind_approval_task_reader(queue.get)
    try:
        run = open_run(ledger)
        ask(ledger, run, expired.id)
        ask(ledger, run, pending_id)
        reconciler = PendingRequests(ledger, read_task=queue.get)
        first = reconciler.reconcile(run.id)
        assert not first.resumed and first.note == 'expiry settled; run held'
        queue.transition(pending_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        second = reconciler.reconcile(run.id)
        assert second.resumed and second.note == 'every ask is answered', second.note
        assert ledger.get(run.id).status == 'working'
    finally:
        ledger.close()
