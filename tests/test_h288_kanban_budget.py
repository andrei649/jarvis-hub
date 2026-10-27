"""H288 review — the finite queued-task budget must not override Kanban's per-card cap.

The Kanban worker enforces the card's own ``max_runtime_seconds`` (``asyncio.timeout(... or
1800)``) and records the card's own outcome. The executor's global wall clock
(``autonomy.task_max_seconds``, 1800 s by default) therefore must not apply to it: a card
capped above the default runs to its own cap, and at the defaults the dispatcher's own
timeout path — not the executor's cancel — records the outcome.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.queue import TaskStatus
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.dispatcher import KanbanDispatcher
from agents.core.kanban.upstream import kanban_db as kb
from tests.test_hermes_kanban_dispatch_wiring import queue_task
from tests.test_hermes_kanban_dispatcher import OWNER, create, fixture_runtime, read
from tests.test_web_tools_wiring import _coordinator

BUDGET = 0.3  # the executor's (patched) global budget in these tests


# -- the shipped executor (build_executor) -------------------------------------------


@pytest.mark.asyncio
async def test_build_executor_exempts_the_kanban_worker_from_the_global_budget(monkeypatch):
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", str(BUDGET))
    coordinator = _coordinator({})
    coordinator._orch.autonomy.execution_allowed = lambda task: True
    controller = coordinator.kanban_dispatcher()
    entered, release = asyncio.Event(), asyncio.Event()

    async def long_card(task):
        entered.set()
        await release.wait()
        return {"status": "ok", "task_id": task.id}

    monkeypatch.setattr(controller, "execute", long_card)
    executor = coordinator.build_executor()
    assert executor.max_wall_seconds == BUDGET

    running = asyncio.create_task(executor.execute(queue_task()))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        # It is still running beyond the global budget, until the card itself
        # finishes. Windows timer granularity need not equal the requested sleep.
        await asyncio.sleep(BUDGET * 2)
        assert not running.done()
    finally:
        release.set()
    result = await asyncio.wait_for(running, 5)
    assert result == {"status": "ok", "task_id": 17}  # not wall_time_budget_exceeded
    assert executor.budget_for(KanbanDispatcher.KIND) is None
    assert executor.budget_for("summarize the week") == BUDGET


@pytest.mark.asyncio
async def test_build_executor_still_bounds_ordinary_kinds(monkeypatch):
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", str(BUDGET))
    coordinator = _coordinator({})
    coordinator._orch.autonomy.execution_allowed = lambda task: True
    executor = coordinator.build_executor()

    async def hung(task):
        await asyncio.Event().wait()

    executor.register("summarize", hung)
    task = queue_task()
    task = task.__class__(**{**task.__dict__, "kind": "summarize"})
    result = await asyncio.wait_for(executor.execute(task), 5)
    assert result["reason"] == "wall_time_budget_exceeded"
    assert result["budget_seconds"] == BUDGET


def test_build_executor_warns_when_the_budget_is_not_below_the_reaper_ttl(monkeypatch, caplog):
    monkeypatch.delenv("JARVIS_TASK_MAX_SECONDS", raising=False)
    settings = {"autonomy.task_max_seconds": 4000, "autonomy.running_ttl_seconds": 3600}
    coordinator = _coordinator({})
    coordinator._orch.get_setting = lambda key, default=None: settings.get(key, default)
    with caplog.at_level("WARNING", logger="jarvis.orchestrator"):
        executor = coordinator.build_executor()
    assert executor.max_wall_seconds == 4000.0
    assert any("running_ttl_seconds" in r.getMessage() for r in caplog.records)

    caplog.clear()
    settings["autonomy.task_max_seconds"] = 1800
    with caplog.at_level("WARNING", logger="jarvis.orchestrator"):
        coordinator.build_executor()
    assert not any("running_ttl_seconds" in r.getMessage() for r in caplog.records)


# -- the executor contract -----------------------------------------------------------


@pytest.mark.asyncio
async def test_self_bounded_registration_is_per_prefix_and_reversible():
    executor = TaskExecutor(max_wall_seconds=BUDGET)

    async def handler(task):
        return {"status": "ok"}

    executor.register("kanban.worker", handler, self_bounded=True)
    executor.register("kanban", handler)
    assert executor.budget_for("kanban.worker") is None
    assert executor.budget_for("kanban.other") == BUDGET
    executor.register("kanban.worker", handler)  # re-registered without the flag
    assert executor.budget_for("kanban.worker") == BUDGET


# -- the real dispatcher under a budgeted executor ----------------------------------


def _budgeted(orch, controller):
    """The production registration (self-bounded) on an executor with a small budget."""
    executor = TaskExecutor(max_wall_seconds=BUDGET, execution_guard=orch.autonomy.execution_allowed)
    executor.register(controller.KIND, controller.execute, self_bounded=True)
    orch.autonomy.executor = executor.execute


@pytest.mark.asyncio
async def test_card_capped_above_the_budget_runs_to_completion(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    _budgeted(orch, c)
    tid = create(c, max_runtime_seconds=30)  # the card's own cap, far above BUDGET

    async def slow_then_complete(orch_, *, prompt, agent_id, session_id):
        from agents.core.kanban.context import current_context

        await asyncio.sleep(BUDGET * 3)
        ctx = current_context()
        with kb.connect_closing() as conn:
            assert kb.complete_task(conn, ctx.task_id, result="done late",
                                    expected_run_id=ctx.run_id)
        return "done late"

    c.runner = slow_then_complete
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    assert (await asyncio.wait_for(orch.autonomy.tick(), 10))["done"] == 1
    assert read(c, tid).status == "done"
    result = orch.autonomy_queue.get(qid).result or {}
    assert result.get("reason") != "wall_time_budget_exceeded"


@pytest.mark.asyncio
async def test_the_cards_own_timeout_records_the_outcome_not_the_executor_cancel(
        tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    _budgeted(orch, c)
    tid = create(c, max_runtime_seconds=1)  # the card's cap, above BUDGET

    async def never_returns(*args, **kwargs):
        await asyncio.Event().wait()

    c.runner = never_returns
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    started = time.monotonic()
    assert (await asyncio.wait_for(orch.autonomy.tick(), 10))["failed"] == 1
    assert time.monotonic() - started >= 1.0  # ran to the card's own 1 s cap
    result = orch.autonomy_queue.get(qid).result or {}
    assert result.get("reason") != "wall_time_budget_exceeded"
    assert result.get("error") != "kanban_worker_cancelled"
    task = read(c, tid)
    assert task.status != "done" and task.claim_lock is None
    assert task.consecutive_failures == 1
    with (
        kanban_scope(KanbanContext(c.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
    ):
        run = kb.latest_run(conn, tid)
    assert run is not None and run.ended_at is not None
    assert "TimeoutError" in (run.error or "")      # the card's own timeout
    assert "CancelledError" not in (run.error or "")  # not the executor's cancel
