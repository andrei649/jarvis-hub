"""Simultaneous board workers through the real signed queue and execution guard."""

import asyncio
import uuid

import pytest

from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kanban.context import current_context
from agents.core.kanban.dispatcher import KanbanDispatcher
from tests.test_hermes_kanban_dispatcher import OWNER, create, fixture_runtime, read


async def approve_cards(controller, orch, *agents):
    tids = [create(controller, assignee=agent) for agent in agents]
    queued = (await controller.request(OWNER, limit=16))["queued"]
    assert len(queued) == len(tids)
    for row in queued:
        orch.autonomy_queue.transition(
            row["queue_id"], TaskStatus.APPROVED, decided_by="owner", decision="approve"
        )
    return tids, [row["queue_id"] for row in queued]


def parallel_options(total=2, per_agent=1):
    return {
        "parallel_kind": KanbanDispatcher.KIND,
        "parallel_limit": total,
        "parallel_agent_limit": per_agent,
    }


@pytest.mark.asyncio
async def test_two_signed_workers_overlap_with_distinct_runs_and_permits(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    original = c.runner
    tids, qids = await approve_cards(c, orch, "jarvis", "reviewer")
    both = asyncio.Event()
    entered = []

    async def runner(*args, **kwargs):
        ctx = current_context()
        permit = orch.autonomy._execution_context.get()
        assert permit.consumed
        entered.append((ctx.task_id, ctx.run_id, ctx.session_id, permit))
        if len(entered) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=1)
        assert current_context() == ctx
        assert orch.autonomy._execution_context.get() is permit
        return await original(*args, **kwargs)

    c.runner = runner
    summary = await orch.autonomy.tick(**parallel_options())
    assert summary["done"] == summary["ran"] == 2
    assert summary["failed"] == 0
    assert {entry[0] for entry in entered} == set(tids)
    assert len({entry[1] for entry in entered}) == len({entry[2] for entry in entered}) == 2
    assert entered[0][3] is not entered[1][3]
    assert all(read(c, tid).status == "done" for tid in tids)
    assert all(orch.autonomy_queue.get(qid).status == "done" for qid in qids)
    assert current_context() is None and orch.autonomy._execution_context.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("total,per_agent,done", [(0, 1, 0), (2, 0, 0), (1, 1, 1), (2, 1, 2)])
async def test_lowered_execution_caps_hold_existing_approvals(
    tmp_path, monkeypatch, total, per_agent, done
):
    c, orch, settings, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    settings.update({"llm.kanban_max_workers": 4, "llm.kanban_max_workers_per_agent": 4})
    _, qids = await approve_cards(c, orch, "jarvis", "jarvis", "reviewer")
    summary = await orch.autonomy.tick(**parallel_options(total, per_agent))
    assert summary["done"] == len(seen) == done
    assert summary["held"] == 3 - done
    assert sum(orch.autonomy_queue.get(qid).status == "approved" for qid in qids) == 3 - done
    if done == 2:
        assert {row[2] for row in seen} == {"jarvis", "reviewer"}


@pytest.mark.asyncio
async def test_parallel_failure_does_not_cancel_independent_worker(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    original = c.runner
    tids, qids = await approve_cards(c, orch, "jarvis", "reviewer")
    both = asyncio.Event()
    started = set()

    async def runner(*args, **kwargs):
        started.add(kwargs["agent_id"])
        if len(started) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=1)
        if kwargs["agent_id"] == "jarvis":
            raise RuntimeError("synthetic provider failure")
        return await original(*args, **kwargs)

    c.runner = runner
    summary = await orch.autonomy.tick(**parallel_options())
    assert summary["failed"] == summary["done"] == 1
    assert orch.autonomy_queue.get(qids[0]).status == "failed"
    assert orch.autonomy_queue.get(qids[1]).status == "done"
    assert read(c, tids[0]).claim_lock is None
    assert read(c, tids[1]).status == "done"


@pytest.mark.asyncio
async def test_parallel_night_tier_and_global_halt_preserve_approvals(tmp_path, monkeypatch):
    c, orch, _, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    _, qids = await approve_cards(c, orch, "jarvis", "reviewer")
    assert (await orch.autonomy.tick(max_tier=1, **parallel_options()))["ran"] == 0
    monkeypatch.setattr(orch.autonomy, "_halted", lambda scope=None: True)
    assert (await orch.autonomy.tick(**parallel_options()))["halted"] is True
    assert seen == []
    assert all(orch.autonomy_queue.get(qid).status == "approved" for qid in qids)


@pytest.mark.asyncio
async def test_cancelling_parallel_tick_awaits_all_board_cleanup(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    original = c.runner
    tids, qids = await approve_cards(c, orch, "jarvis", "reviewer")
    both = asyncio.Event()
    started, exited = set(), set()

    async def runner(*args, **kwargs):
        agent = kwargs["agent_id"]
        started.add(agent)
        if len(started) == 2:
            both.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.add(agent)

    c.runner = runner
    task = asyncio.create_task(orch.autonomy.tick(**parallel_options()))
    try:
        await asyncio.wait_for(both.wait(), timeout=1)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exited == {"jarvis", "reviewer"}
    assert all(read(c, tid).claim_lock is None for tid in tids)
    assert all(orch.autonomy_queue.get(qid).status == "failed" for qid in qids)
    assert all(
        orch.autonomy_queue.get(qid).result == {"error": "kanban_worker_cancelled"}
        for qid in qids
    )
    assert current_context() is None
    c.runner = original
    _, next_qids = await approve_cards(c, orch, "jarvis", "reviewer")
    assert (await orch.autonomy.tick(**parallel_options()))["done"] == 2
    assert all(orch.autonomy_queue.get(qid).status == "done" for qid in next_qids)


@pytest.mark.asyncio
async def test_queue_settlement_rejects_another_execution_atomically(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    _, qids = await approve_cards(c, orch, "jarvis")
    queue = orch.autonomy_queue
    before = queue.get(qids[0])
    claimed = queue.claim_mediated(qids[0], execution_id=str(uuid.uuid4()))
    assert claimed is not None
    with pytest.raises(TaskQueueError, match="execution changed"):
        queue.transition(
            claimed.id, TaskStatus.FAILED, expected_status=TaskStatus.RUNNING,
            expected_execution_sha256=TaskQueue.execution_fingerprint(before),
        )
    assert queue.get(claimed.id).status == "running"
    assert queue.get(claimed.id).result is None
    settled = queue.transition(
        claimed.id, TaskStatus.FAILED, expected_status=TaskStatus.RUNNING,
        expected_execution_sha256=TaskQueue.execution_fingerprint(claimed),
    )
    assert settled.status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("settled_elsewhere", [True, False])
async def test_cancellation_preserves_external_settlement_or_storage_failure(
    tmp_path, monkeypatch, settled_elsewhere
):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tids, qids = await approve_cards(c, orch, "jarvis")
    entered = asyncio.Event()

    async def runner(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    c.runner = runner
    task = asyncio.create_task(orch.autonomy.tick(**parallel_options(1, 1)))
    await asyncio.wait_for(entered.wait(), timeout=1)
    if settled_elsewhere:
        orch.autonomy_queue.transition(qids[0], TaskStatus.DONE, result={"external": True})
    else:
        def unavailable(*args, **kwargs):
            raise OSError("synthetic unavailable queue storage")
        monkeypatch.setattr(orch.autonomy_queue, "transition", unavailable)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert read(c, tids[0]).claim_lock is None
    row = orch.autonomy_queue.get(qids[0])
    assert row.status == ("done" if settled_elsewhere else "running")
    assert row.result == ({"external": True} if settled_elsewhere else None)


@pytest.mark.asyncio
async def test_durable_running_row_consumes_total_and_agent_capacity(tmp_path, monkeypatch):
    c, orch, settings, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    settings.update({"llm.kanban_max_workers": 4, "llm.kanban_max_workers_per_agent": 4})
    _, qids = await approve_cards(c, orch, "jarvis", "jarvis", "reviewer")
    # An authenticated claim left by another worker consumes capacity even
    # though this process has no coroutine or in-memory handle for that row.
    claimed = orch.autonomy_queue.claim_mediated(qids[0], execution_id=str(uuid.uuid4()))
    assert claimed is not None and claimed.status == "running"
    summary = await orch.autonomy.tick(**parallel_options(2, 1))
    assert summary["done"] == summary["held"] == 1
    assert [row[2] for row in seen] == ["reviewer"]
    assert [orch.autonomy_queue.get(qid).status for qid in qids] == [
        "running", "approved", "done"
    ]


@pytest.mark.asyncio
async def test_competing_configured_ticks_execute_each_approval_once(tmp_path, monkeypatch):
    c, orch, _, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    _, qids = await approve_cards(c, orch, "jarvis", "reviewer")
    summaries = await asyncio.gather(
        orch.autonomy.tick(**parallel_options()), orch.autonomy.tick(**parallel_options())
    )
    assert sum(summary["done"] for summary in summaries) == len(seen) == 2
    assert len({row[3] for row in seen}) == 2
    assert all(orch.autonomy_queue.get(qid).attempts == 1 for qid in qids)


@pytest.mark.asyncio
async def test_other_kinds_stay_serial_when_board_capacity_is_zero(tmp_path):
    queue = TaskQueue(str(tmp_path / "ordinary.db")).initialize()
    active = peak = 0
    completed = []

    async def execute(task):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        completed.append(task.id)
        active -= 1
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=execute)
    for index in range(3):
        qid = queue.enqueue(agent="jarvis", kind="ordinary", title=f"task {index}")
        queue.transition(qid, TaskStatus.APPROVED)
    summary = await worker.tick(**parallel_options(0, 0))
    assert summary["done"] == 3 and peak == 1
    assert completed == [1, 2, 3]


@pytest.mark.asyncio
async def test_agent_halt_does_not_reserve_an_available_worker_slot(tmp_path, monkeypatch):
    c, orch, _, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    _, qids = await approve_cards(c, orch, "jarvis", "reviewer")
    monkeypatch.setattr(orch.autonomy, "_halted", lambda scope=None: scope == "jarvis")
    summary = await orch.autonomy.tick(**parallel_options(1, 1))
    assert summary["done"] == summary["held"] == 1
    assert [row[2] for row in seen] == ["reviewer"]
    assert orch.autonomy_queue.get(qids[0]).status == "approved"


@pytest.mark.asyncio
async def test_ordinary_queue_work_is_not_delayed_by_long_board_batch(tmp_path):
    queue = TaskQueue(str(tmp_path / "ordering.db")).initialize()
    ordinary_done = asyncio.Event()

    async def execute(task):
        if task.kind == "ordinary":
            ordinary_done.set()
        else:
            await asyncio.wait_for(ordinary_done.wait(), timeout=0.1)
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=execute)
    for kind, agent in [("ordinary", "jarvis"), (KanbanDispatcher.KIND, "jarvis"),
                        (KanbanDispatcher.KIND, "reviewer")]:
        qid = queue.enqueue(agent=agent, kind=kind, title="synthetic task")
        queue.transition(qid, TaskStatus.APPROVED)
    assert (await worker.tick(**parallel_options()))["done"] == 3
