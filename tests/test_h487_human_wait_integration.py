"""Human-wait accounting at the real Company runtime/queue boundary, offline."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agents.core.autonomy import queue as qm
from agents.core.autonomy.company_runtime import build_company_runtime
from agents.core.autonomy.company_supervisor import Action
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.work_runs import Budget, WorkRunLedger
from agents.core.autonomy.worker import AutonomyWorker

BASE = datetime(2026, 9, 27, 12, tzinfo=UTC).timestamp()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    now = [BASE]

    def stamp():
        return datetime.fromtimestamp(now[0], UTC)

    monkeypatch.setattr(qm, "_now", lambda: stamp().isoformat())
    monkeypatch.setattr(
        qm, "_approval_now", lambda moment=None: stamp() if moment is None else moment
    )
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    path = tmp_path / "runs.db"
    ledger = WorkRunLedger(path, clock=lambda: now[0])
    worker = AutonomyWorker(queue)
    orch = SimpleNamespace(work_runs=ledger, task_queue=queue, govern_enqueue=worker.govern_enqueue)

    def runtime(kind="delete_file", reader=True, *, autonomy_level="ask", risk_tier=2):
        action = Action(
            kind=kind,
            summary="approved checklist action",
            task={
                "agent": "jarvis",
                "kind": kind,
                "title": "bounded action",
                "payload": {"path": "old.txt"},
                "autonomy_level": autonomy_level,
                "risk_tier": risk_tier,
            },
        )
        return build_company_runtime(
            orch, read_task=queue.get if reader else None, planner=lambda _: action
        )

    def open_run(seconds=60, deadline=0):
        goal = SimpleNamespace(
            goal_id="goal", title="bounded goal", approved_by="owner", deadline_at=deadline
        )
        return orch.work_runs.open_run(goal, budget=Budget(max_seconds=seconds, max_steps=50))

    value = SimpleNamespace(
        now=now,
        q=queue,
        ledger=ledger,
        path=path,
        worker=worker,
        orch=orch,
        runtime=runtime,
        open=open_run,
    )
    yield value
    orch.work_runs.close()
    queue.close()


async def first_ask(rig, *, seconds=60, kind="delete_file", deadline=0, **intake):
    runtime = rig.runtime(kind, **intake)
    run = rig.open(seconds, deadline)
    result = await runtime.parts.supervisor.tick(run.id)
    assert result.outcome == "stepped"
    (step,) = rig.ledger.outstanding_asks(run.id)
    while rig.worker._bg_tasks:
        await asyncio.gather(*tuple(rig.worker._bg_tasks))
    return runtime, run, rig.q.get(step.task_id)


@pytest.mark.asyncio
async def test_actual_runtime_binds_real_pending_task_reader_and_preserves_raw_wall_time(rig):
    runtime, run, task = await first_ask(rig)
    assert task.status == "blocked" and task.autonomy_level == "ask"
    rig.now[0] += 200
    state = rig.ledger.budget_state(run.id)
    assert state["exceeded"] is None and state["seconds_used"] == 0
    assert state["wall_seconds_used"] == state["human_wait_seconds"] == 200
    assert rig.ledger.get(run.id).seconds_used(rig.now[0]) == 200
    assert not runtime.parts.reconciler.reconcile(run.id).resumed


@pytest.mark.asyncio
async def test_real_runtime_long_deadline_preserves_wait_beyond_360_seconds(rig, monkeypatch):
    enqueue = rig.q.enqueue

    def with_deadline(*args, **kwargs):
        kwargs["approval_deadline_at"] = datetime.fromtimestamp(BASE + 900, UTC).isoformat()
        return enqueue(*args, **kwargs)

    monkeypatch.setattr(rig.q, "enqueue", with_deadline)
    _, run, task = await first_ask(rig, seconds=30)
    assert task.status == "blocked" and task.approval_deadline_at is not None
    rig.now[0] = BASE + 500
    state = rig.ledger.budget_state(run.id)
    assert state["wall_seconds_used"] == 500
    assert state["human_wait_seconds"] == 500
    assert state["seconds_used"] == 0 and state["exceeded"] is None


@pytest.mark.asyncio
async def test_autoapproved_task_id_does_not_purchase_wait_credit(rig):
    runtime, run, task = await first_ask(
        rig, kind="draft_email", autonomy_level="act", risk_tier=1
    )
    assert task.status == "approved"
    rig.now[0] += 100
    state = rig.ledger.budget_state(run.id)
    assert state["seconds_used"] == 100 and state["human_wait_seconds"] == 0
    assert state["exceeded"] == "seconds"
    assert not runtime.parts.reconciler.reconcile(run.id).resumed


@pytest.mark.asyncio
async def test_actual_human_timestamp_caps_credit_before_delayed_reconciliation(rig):
    runtime, run, task = await first_ask(rig)
    rig.now[0] += 40
    await rig.worker.apply_decision(task.id, "accept", decided_by="owner")
    rig.now[0] += 100
    state = rig.ledger.budget_state(run.id)
    assert state["human_wait_seconds"] == 40 and state["seconds_used"] == 100
    result = runtime.parts.reconciler.reconcile(run.id)
    assert not result.resumed and rig.ledger.get(run.id).status == "blocked"


@pytest.mark.asyncio
async def test_overlap_is_one_union_window_and_never_restarts_360_second_cap(rig):
    runtime, run, first = await first_ask(rig)
    rig.now[0] += 100
    second = rig.worker.govern_enqueue(
        "jarvis", "delete_file", "second ask", payload={"path": "other.txt"}
    )
    rig.ledger.record_step(
        run.id, kind="delete_file", summary="second", outcome="queued", task_id=second
    )
    rig.now[0] = BASE + 400
    state = rig.ledger.budget_state(run.id)
    assert state["human_wait_seconds"] == 360 and state["seconds_used"] == 40
    assert state["exceeded"] is None
    rig.now[0] += 21
    assert rig.ledger.budget_state(run.id)["exceeded"] == "seconds"
    assert not runtime.parts.reconciler.reconcile(run.id).resumed
    while rig.worker._bg_tasks:
        await asyncio.gather(*tuple(rig.worker._bg_tasks))


@pytest.mark.asyncio
async def test_restart_preserves_window_and_original_cap(rig):
    _, run, _ = await first_ask(rig)
    rig.now[0] += 180
    rig.ledger.close()
    restarted = WorkRunLedger(rig.path, clock=lambda: rig.now[0])
    rig.orch.work_runs = restarted
    rig.ledger = restarted
    rig.runtime()
    rig.now[0] = BASE + 400
    state = restarted.budget_state(run.id)
    assert state["human_wait_seconds"] == 360 and state["seconds_used"] == 40
    assert restarted.get(run.id).seconds_used(rig.now[0]) == 400


@pytest.mark.asyncio
async def test_expiry_closes_credit_at_deadline_before_atomic_resume_budget_check(rig, monkeypatch):
    enqueue = rig.q.enqueue
    deadline = BASE + 30

    def with_deadline(*args, **kwargs):
        kwargs["approval_deadline_at"] = datetime.fromtimestamp(deadline, UTC).isoformat()
        return enqueue(*args, **kwargs)

    monkeypatch.setattr(rig.q, "enqueue", with_deadline)
    runtime, run, task = await first_ask(rig, seconds=75)
    rig.now[0] += 30
    rig.q.expire_pending_approvals()
    assert rig.q.get(task.id).status == "expired"
    rig.now[0] += 60
    result = runtime.parts.reconciler.reconcile(run.id)
    assert result.resumed and rig.ledger.get(run.id).status == "working"
    state = rig.ledger.budget_state(run.id)
    assert state["human_wait_seconds"] == 30 and state["seconds_used"] == 60
    assert result.outcomes[0].resolution == "expired_unanswered"
    assert rig.ledger.steps(run.id)[0].outcome == "failed"


@pytest.mark.asyncio
async def test_absolute_goal_deadline_still_outranks_long_human_wait_credit(rig, monkeypatch):
    enqueue = rig.q.enqueue

    def with_deadline(*args, **kwargs):
        kwargs["approval_deadline_at"] = datetime.fromtimestamp(BASE + 900, UTC).isoformat()
        return enqueue(*args, **kwargs)

    monkeypatch.setattr(rig.q, "enqueue", with_deadline)
    _, run, _ = await first_ask(rig, deadline=BASE + 90)
    rig.now[0] += 100
    state = rig.ledger.budget_state(run.id)
    assert state["human_wait_seconds"] == 100
    assert state["seconds_used"] == 0 and state["exceeded"] == "deadline"


@pytest.mark.asyncio
async def test_stop_is_not_resumed_by_later_owner_answer(rig):
    runtime, run, task = await first_ask(rig)
    rig.now[0] += 40
    rig.ledger.request_stop(run.id, reason="owner stopped")
    await rig.worker.apply_decision(task.id, "accept", decided_by="owner")
    assert not runtime.parts.reconciler.reconcile(run.id).resumed
    assert rig.ledger.get(run.id).status == "stopping"


@pytest.mark.asyncio
async def test_nonapproval_barrier_remains_held_when_human_answers(rig):
    runtime = rig.runtime()
    run = rig.open()
    rig.ledger.set_barrier(
        run.id,
        {"id": "external-wait", "kind": "deadline", "cap_at": BASE + 500, "until": BASE + 400},
    )
    task_id = rig.worker.govern_enqueue(
        "jarvis", "delete_file", "real ask", payload={"path": "old.txt"}
    )
    rig.ledger.record_step(
        run.id, kind="delete_file", summary="queued while parked", outcome="queued", task_id=task_id
    )
    rig.now[0] += 40
    await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
    assert not runtime.parts.reconciler.reconcile(run.id).resumed
    assert rig.ledger.get(run.id).barrier
    while rig.worker._bg_tasks:
        await asyncio.gather(*tuple(rig.worker._bg_tasks))


@pytest.mark.asyncio
async def test_unbound_library_ledger_keeps_wall_time_for_real_pending_id(rig):
    task_id = rig.worker.govern_enqueue(
        "jarvis", "delete_file", "real ask", payload={"path": "old.txt"}
    )
    ledger = WorkRunLedger(":memory:", clock=lambda: rig.now[0])
    try:
        run = ledger.open_run(
            SimpleNamespace(goal_id="library", title="library", approved_by="owner"),
            budget=Budget(max_seconds=60),
        )
        ledger.record_step(
            run.id, kind="delete_file", summary="waiting", outcome="queued", task_id=task_id
        )
        rig.now[0] += 200
        state = ledger.budget_state(run.id)
        assert state["seconds_used"] == 200 and state["exceeded"] == "seconds"
    finally:
        ledger.close()
        while rig.worker._bg_tasks:
            await asyncio.gather(*tuple(rig.worker._bg_tasks))


@pytest.mark.asyncio
async def test_unreadable_bound_task_does_not_create_wait_credit(rig):
    def unreadable(_):
        raise RuntimeError("synthetic unavailable queue")

    runtime = build_company_runtime(
        rig.orch,
        read_task=unreadable,
        planner=lambda _: Action(
            kind="delete_file",
            summary="real ask",
            task={
                "agent": "jarvis",
                "kind": "delete_file",
                "title": "real ask",
                "payload": {"path": "old.txt"},
            },
        ),
    )
    run = rig.open()
    assert (await runtime.parts.supervisor.tick(run.id)).outcome == "stepped"
    rig.now[0] += 200
    state = rig.ledger.budget_state(run.id)
    assert state["human_wait_seconds"] == 0 and state["exceeded"] == "seconds"
    while rig.worker._bg_tasks:
        await asyncio.gather(*tuple(rig.worker._bg_tasks))


@pytest.mark.asyncio
async def test_runtime_can_admit_next_real_step_after_proven_wait(rig):
    runtime, run, task = await first_ask(rig)
    rig.now[0] += 200
    await rig.worker.apply_decision(task.id, "accept", decided_by="owner")
    assert runtime.parts.reconciler.reconcile(run.id).resumed
    assert (await runtime.parts.supervisor.tick(run.id)).outcome == "stepped"
    assert len(rig.ledger.steps(run.id)) == 2 and len(rig.q.list()) == 2
    assert rig.ledger.budget_state(run.id)["seconds_used"] == 0
    while rig.worker._bg_tasks:
        await asyncio.gather(*tuple(rig.worker._bg_tasks))


@pytest.mark.asyncio
async def test_defer_then_accept_without_refresh_cannot_credit_intervening_delay(rig):
    runtime, run, task = await first_ask(rig)
    rig.now[0] += 40
    await rig.worker.apply_decision(task.id, "defer", decided_by="owner")
    # No ledger budget read/reconcile between the two durable decisions.
    rig.now[0] += 100
    await rig.worker.apply_decision(task.id, "accept", decided_by="owner")
    rig.now[0] += 60
    state = rig.ledger.budget_state(run.id)
    assert state["human_wait_seconds"] <= 40 and state["seconds_used"] >= 160
    assert not runtime.parts.reconciler.reconcile(run.id).resumed
