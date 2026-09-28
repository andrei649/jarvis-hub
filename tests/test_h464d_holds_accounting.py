"""H464d — a held run is visible and settles; a checklist row is done only once queued.

Round 3 of the H464 review, the builder-B half:

  · item 4 — a run held because its approval task cannot be read leaves ONE durable
    event (not one per sweep), shows in the brief and in the run's snapshot, and is
    settled by the sweep once its budget is spent, like any spent run;
  · item 5 — a row whose intake failed is retried on a later sweep, at most
    ``MAX_ROW_ATTEMPTS`` times, then the run stops with a readable reason; a steps
    read that fails holds the tick instead of re-asking row 1;
  · item 6 — ``open_run``'s idempotent return and its ``approval_already_used``
    refusal both end their transaction;
  · item 7b — a stop Hold names its cause, so a scope refusal is not reported as an
    unbound plan.

Hermetic: a real task queue and ledger under tmp_path on one hand-driven clock, a spy
intake, and the real company runtime where the wiring is what is under test.
"""

from __future__ import annotations

import sqlite3
import types
from datetime import UTC, datetime

import pytest

from agents.core.autonomy.company_planner import MAX_ROW_ATTEMPTS, ChecklistPlanner, PlanStep
from agents.core.autonomy.company_report import build_company_brief, render_company_brief
from agents.core.autonomy.company_runtime import build_company_runtime
from agents.core.autonomy.company_supervisor import (
    Action,
    CompanySupervisor,
    Hold,
    SupervisorConfig,
)
from agents.core.autonomy.goal_contract import GoalDraft, SuccessCheck, approve_from_task
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.schedule_runtime import ScheduleConfig, ScheduleRuntime
from agents.core.autonomy.work_runs import Budget, WorkRunError, WorkRunLedger

pytestmark = pytest.mark.asyncio

T0 = 1_800_000_000.0
ON = SupervisorConfig(enabled=True)

_ROW = {
    "kind": "research", "summary": "collect the figures",
    "task": {"agent": "jarvis", "kind": "research.collect", "title": "Collect the figures",
             "payload": {"source": "q3"}},
}
_ROW2 = {
    "kind": "write", "summary": "write the brief",
    "task": {"agent": "jarvis", "kind": "write.brief", "title": "Write the brief",
             "payload": {}},
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr("agents.core.autonomy.queue._now",
                        lambda: datetime.fromtimestamp(clock[0], UTC).isoformat())
    monkeypatch.setattr("agents.core.autonomy.queue._approval_now",
                        lambda supplied=None: supplied or datetime.fromtimestamp(clock[0], UTC))
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_SAFE_MODE", raising=False)
    q = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    store = WorkRunLedger(tmp_path / "work.db", clock=lambda: clock[0])
    yield types.SimpleNamespace(clock=clock, q=q, ledger=store, path=tmp_path / "work.db")
    store.close()
    q.close()


def _draft(plan=(_ROW, _ROW2), budget=None):
    return GoalDraft(
        title="Prepare the brief", scope_kinds=("research", "write"), unrestricted=False,
        budget=budget or Budget(), deadline_at=9_999_999_999.0,
        stop_conditions=("the source data changes",),
        checks=(SuccessCheck(id="c1", describe="a brief exists", probe_ref="p:x"),),
        deliverable="one brief", plan=tuple(plan),
    )


def _goal_task(q, draft):
    payload = draft.as_payload()
    payload["fingerprint"] = draft.fingerprint()
    tid = q.enqueue("jarvis", "goal.approve", f"Approve goal: {draft.title}", payload)
    q.transition(tid, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                 human_reason=None)
    return tid


def _open(world, tid):
    goal = approve_from_task(world.q.get(tid))
    return world.ledger.open_run(goal, budget=goal.budget, deadline_at=goal.deadline_at)


def _finish(q, tid):
    q.transition(tid, TaskStatus.RUNNING)
    q.transition(tid, TaskStatus.DONE, result={"status": "ok"})


class _Orch:
    """Only the names the shipped orchestrator has; the intake is a spy that ends as
    the real one does for an ask: a durable row, blocked on the owner."""

    def __init__(self, world, *, read=None):
        self.work_runs = world.ledger
        self.company_runtime = None
        self.calls: list[dict] = []
        q = world.q

        def govern_enqueue(**kwargs):
            self.calls.append(dict(kwargs))
            tid = q.enqueue(kwargs["agent"], kwargs["kind"], kwargs["title"],
                            dict(kwargs.get("payload") or {}))
            q.transition(tid, TaskStatus.BLOCKED)
            return tid

        self.autonomy_queue = types.SimpleNamespace(get=read or q.get)
        self.autonomy = types.SimpleNamespace(govern_enqueue=govern_enqueue)


def _record_ticks(runtime):
    seen = []
    tick = runtime.parts.scheduler._tick

    async def _tick(run_id):
        result = await tick(run_id)
        seen.append(result)
        return result

    runtime.parts.scheduler._tick = _tick
    return seen


async def _sweep(runtime):
    runtime.parts.scheduler._last.clear()      # the interval is not what is under test
    return await runtime.sweep()


def _unreadable_approval(world, tid):
    """A reader for which the run's approval task cannot be read just now."""

    def read(task_id):
        if int(task_id) == tid:
            raise sqlite3.OperationalError("database is locked")
        return world.q.get(task_id)

    return read


def _hold_events(ledger, run_id):
    return [(e["kind"], e["detail"].get("reason"))
            for e in reversed(ledger.events(run_id, limit=100))
            if e["kind"].startswith("hold.")]


async def _held_run(world, *, budget=None):
    draft = _draft(budget=budget)
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    orch = _Orch(world, read=_unreadable_approval(world, tid))
    runtime = build_company_runtime(orch, config=ScheduleConfig(enabled=True))
    return run, orch, runtime


# ── item 4a: one durable event per hold, not one per sweep ───────────────────

async def test_a_held_run_leaves_exactly_one_event_across_several_sweeps(world):
    run, orch, runtime = await _held_run(world)
    ticks = _record_ticks(runtime)
    for _ in range(4):
        world.clock[0] += 300
        await _sweep(runtime)
    assert [(t.outcome, t.detail) for t in ticks] == [
        ("idle", "held: approval_task_unreadable")] * 4
    assert orch.calls == []
    assert _hold_events(world.ledger, run.id) == [("hold.started", "approval_task_unreadable")]
    started = [e for e in world.ledger.events(run.id) if e["kind"] == "hold.started"]
    assert started[0]["at"] == T0 + 300            # when the hold began, not the last sweep


async def test_a_new_hold_event_only_when_the_reason_changes_or_after_a_step(world):
    """Deduplicated on (reason, steps taken): the same hold on every tick is one
    event; a different reason is another; the plan answering again ends it."""
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))
    answers = [Hold("a"), Hold("a"), Hold("b"),
               Action(kind="research", summary="one", task={"agent": "jarvis"}),
               Hold("b"), Hold("b")]
    ids = iter(range(100, 200))
    sup = CompanySupervisor(ledger, enqueue=lambda **_kw: next(ids),
                            plan_next=lambda _c: answers.pop(0), config=ON)
    outcomes = []
    for _ in range(6):
        outcomes.append((await sup.tick(run.id)).outcome)
        if ledger.get(run.id).status == "blocked":
            ledger.resume(run.id)
    assert outcomes == ["idle", "idle", "idle", "stepped", "idle", "idle"]
    assert _hold_events(ledger, run.id) == [
        ("hold.started", "a"), ("hold.started", "b"), ("hold.ended", "b"),
        ("hold.started", "b")]


async def test_a_hold_that_cannot_be_recorded_still_holds_the_tick(world, monkeypatch):
    """The event is a record, not a gate: a ledger that refuses it never turns a hold
    into a step, a grade or an exception out of the tick."""
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))

    def _boom(*_a, **_kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger, "note_hold", _boom)
    sup = CompanySupervisor(ledger, enqueue=lambda **_kw: 1,
                            plan_next=lambda _c: Hold("approval_task_unreadable"), config=ON)
    result = await sup.tick(run.id)
    assert (result.outcome, result.detail) == ("idle", "held: approval_task_unreadable")
    assert ledger.steps(run.id) == []


# ── item 4b: the brief and the snapshot show it ──────────────────────────────

async def test_the_brief_and_the_snapshot_show_a_held_run_and_why(world):
    run, _orch, runtime = await _held_run(world)
    await _sweep(runtime)
    snapshot = world.ledger.snapshot(run.id)
    assert snapshot["hold"]["reason"] == "approval_task_unreadable"
    brief = build_company_brief([snapshot], company_mode_enabled=True, now=world.clock[0])
    assert brief["held"] == [run.id]
    (summary,) = brief["runs"]
    assert summary["held"] == "approval_task_unreadable"
    assert summary["headline"] == "held — approval_task_unreadable"
    text = render_company_brief(brief)
    assert "is held: approval_task_unreadable" in text


async def test_the_hold_leaves_the_brief_once_the_plan_reads_again(world):
    draft = _draft()
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    broken = {"on": True}

    def read(task_id):
        if broken["on"] and int(task_id) == tid:
            raise sqlite3.OperationalError("database is locked")
        return world.q.get(task_id)

    orch = _Orch(world, read=read)
    runtime = build_company_runtime(orch, config=ScheduleConfig(enabled=True))
    await _sweep(runtime)
    assert world.ledger.snapshot(run.id)["hold"] is not None
    broken["on"] = False
    await _sweep(runtime)                               # row 1 queued: the hold is over
    assert len(orch.calls) == 1
    assert world.ledger.snapshot(run.id)["hold"] is None
    brief = build_company_brief([world.ledger.snapshot(run.id)], company_mode_enabled=True,
                                now=world.clock[0])
    assert brief["held"] == [] and brief["runs"][0]["held"] is None
    assert _hold_events(world.ledger, run.id) == [
        ("hold.started", "approval_task_unreadable"),
        ("hold.ended", "approval_task_unreadable")]


async def test_a_run_that_is_no_longer_live_is_never_reported_held(world):
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))
    ledger.note_hold(run.id, "approval_task_unreadable")
    ledger.request_stop(run.id)
    ledger.settle_stop(run.id)
    brief = build_company_brief([ledger.snapshot(run.id)], company_mode_enabled=True,
                                now=world.clock[0])
    assert brief["held"] == [] and brief["runs"][0]["held"] is None
    assert "held" not in brief["runs"][0]["headline"]


async def test_a_step_after_the_hold_began_ends_it_even_without_an_end_event(world):
    """A step taken on any path (not only a tick that noted the end) means the run
    moved on: the hold record is no longer current, and the next hold is new."""
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))
    assert ledger.note_hold(run.id, "approval_task_unreadable") is True
    assert ledger.note_hold(run.id, "approval_task_unreadable") is False
    ledger.record_step(run.id, kind="research", summary="one", outcome="ok", task_id=1)
    assert ledger.current_hold(run.id) is None
    assert ledger.note_hold(run.id, "approval_task_unreadable") is True
    assert ledger.current_hold(run.id)["steps_used"] == 1


async def test_a_terminal_run_takes_no_new_hold_event(world):
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))
    ledger.request_stop(run.id)
    ledger.settle_stop(run.id)
    assert ledger.note_hold(run.id, "x") is False
    assert _hold_events(ledger, run.id) == []


# ── item 4c: a spent run is settled by the sweep ─────────────────────────────

async def test_a_held_run_whose_budget_runs_out_is_settled_by_the_sweep(world):
    run, orch, runtime = await _held_run(world, budget=Budget(max_seconds=900.0))
    ticks = _record_ticks(runtime)
    await _sweep(runtime)
    assert [t.detail for t in ticks] == ["held: approval_task_unreadable"]
    world.clock[0] += 1_000
    result = await _sweep(runtime)
    assert result["skipped"] == {run.id: "budget_spent"}
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == ("stopped", "budget:seconds")
    assert len(ticks) == 1 and orch.calls == []
    # idempotent: a settled run is a record, never settled (or ticked) again
    world.clock[0] += 300
    assert (await _sweep(runtime))["skipped"] == {}
    assert world.ledger.get(run.id).stop_reason == "budget:seconds"


class _Tick:
    def __init__(self):
        self.calls: list[str] = []

    async def __call__(self, run_id):
        self.calls.append(run_id)
        return types.SimpleNamespace(outcome="stepped")


def _scheduler(ledger, clock, tick=None):
    return ScheduleRuntime(ledger, tick=tick or _Tick(), config=ScheduleConfig(enabled=True),
                           clock=lambda: clock[0], local_hour=lambda: 12)


async def test_the_sweep_settles_a_spent_run_exactly_as_the_supervisor_would(world):
    """Same status, same reason: the sweep's settle is the supervisor's, never a
    second opinion about how a spent run ends."""
    ledger = world.ledger
    by_sweep = ledger.open_run(types.SimpleNamespace(goal_id="a", title="t",
                                                     approved_by="receipt:1"),
                               budget=Budget(max_steps=1))
    by_tick = ledger.open_run(types.SimpleNamespace(goal_id="b", title="t",
                                                    approved_by="receipt:1"),
                              budget=Budget(max_steps=1))
    for run in (by_sweep, by_tick):
        ledger.record_step(run.id, kind="research", summary="one", outcome="ok", task_id=1)
    sup = CompanySupervisor(ledger, enqueue=lambda **_kw: 1, plan_next=lambda _c: None,
                            config=ON)
    ticked = await sup.tick(by_tick.id)
    tick = _Tick()
    result = await _scheduler(ledger, world.clock, tick).sweep()
    assert tick.calls == []
    (entry,) = [e for e in result.entries if e.run_id == by_sweep.id]
    assert (entry.ticked, entry.reason, entry.outcome) == (False, "budget_spent", ticked.outcome)
    a, b = ledger.get(by_sweep.id), ledger.get(by_tick.id)
    assert (a.status, a.stop_reason) == (b.status, b.stop_reason) == ("stopped", "budget:steps")


async def test_a_budget_that_cannot_be_read_is_skipped_never_settled(world, monkeypatch):
    """``due`` reads an unreadable budget as spent so the run is not ticked; the
    settle step re-reads it and settles nothing on a guess."""
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))

    def _boom(*_a, **_kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger, "budget_state", _boom)
    result = await _scheduler(ledger, world.clock).sweep()
    assert result.skipped == {run.id: "budget_spent"}
    assert result.entries[0].outcome == ""
    assert ledger.get(run.id).status == "planning" and ledger.get(run.id).stop_reason == ""


async def test_a_settle_that_raises_never_escapes_the_sweep(world, monkeypatch):
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"),
                          budget=Budget(max_steps=1))
    ledger.record_step(run.id, kind="research", summary="one", outcome="ok", task_id=1)

    def _boom(*_a, **_kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ledger, "request_stop", _boom)
    result = await _scheduler(ledger, world.clock).sweep()
    assert result.skipped == {run.id: "budget_spent"}
    assert ledger.get(run.id).status == "working"


# ── item 5 (1): a failed row is retried, bounded ─────────────────────────────

class _FlakyIntake:
    """Raises for the rows in ``failures`` (their text changes each time, unless
    ``same``), and otherwise hands back durable ids."""

    def __init__(self, failures: int, *, same: bool = False):
        self.failures = failures
        self.same = same
        self.calls: list[str] = []
        self._next = 100

    def __call__(self, **kwargs):
        self.calls.append(kwargs["title"])
        if self.failures > 0:
            self.failures -= 1
            name = "OSError" if self.same else ("OSError", "TimeoutError", "ConnectionError",
                                                "BrokenPipeError")[self.failures % 4]
            raise {"OSError": OSError, "TimeoutError": TimeoutError,
                   "ConnectionError": ConnectionError,
                   "BrokenPipeError": BrokenPipeError}[name]("transient")
        self._next += 1
        return self._next


def _rows():
    return [PlanStep(kind=r["kind"], summary=r["summary"], task=dict(r["task"]))
            for r in (_ROW, _ROW2)]


def _checklist_run(ledger):
    return ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))


async def test_a_row_whose_intake_failed_once_is_asked_again_not_skipped(world):
    ledger = world.ledger
    run = _checklist_run(ledger)
    intake = _FlakyIntake(1)
    planner = ChecklistPlanner(_rows(), scope_kinds={"research", "write"}, ledger=ledger)
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=planner, config=ON)
    first = await sup.tick(run.id)
    assert first.outcome == "stepped" and ledger.steps(run.id)[0].outcome == "failed"
    second = await sup.tick(run.id)
    assert second.outcome == "stepped"
    assert intake.calls == ["Collect the figures", "Collect the figures"]
    assert [(s.summary, s.outcome) for s in ledger.steps(run.id)] == [
        ("collect the figures", "failed"), ("collect the figures", "queued")]


async def test_a_row_that_keeps_failing_stops_the_run_with_a_named_reason(world):
    """Different failures each time, so the in-memory streak never matches: the row's
    durable attempt count is what ends it, before a fourth attempt."""
    ledger = world.ledger
    run = _checklist_run(ledger)
    intake = _FlakyIntake(99)
    planner = ChecklistPlanner(_rows(), scope_kinds={"research", "write"}, ledger=ledger)
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=planner, config=ON)
    outcomes = [(await sup.tick(run.id)).outcome for _ in range(MAX_ROW_ATTEMPTS + 1)]
    assert outcomes == ["stepped"] * MAX_ROW_ATTEMPTS + ["stopped"]
    assert len(intake.calls) == MAX_ROW_ATTEMPTS
    after = ledger.get(run.id)
    assert after.status == "stopped"
    assert after.stop_reason == (
        f"approved row failed too often: collect the figures ({MAX_ROW_ATTEMPTS} attempts)")


async def test_the_attempt_count_outlives_a_restart_of_the_supervisor(world):
    ledger = world.ledger
    run = _checklist_run(ledger)
    intake = _FlakyIntake(99, same=True)
    for _ in range(MAX_ROW_ATTEMPTS - 1):          # a fresh supervisor: no streak carried
        planner = ChecklistPlanner(_rows(), scope_kinds={"research", "write"}, ledger=ledger)
        sup = CompanySupervisor(ledger, enqueue=intake, plan_next=planner, config=ON)
        assert (await sup.tick(run.id)).outcome == "stepped"
    sup = CompanySupervisor(ledger, enqueue=intake, config=ON,
                            plan_next=ChecklistPlanner(_rows(), scope_kinds={"research", "write"},
                                                       ledger=ledger))
    assert (await sup.tick(run.id)).outcome == "stepped"        # the third attempt
    result = await sup.tick(run.id)
    assert result.outcome == "stopped" and "failed too often" in result.detail
    assert len(intake.calls) == MAX_ROW_ATTEMPTS


async def test_the_same_failure_three_times_is_stopped_by_the_streak_first(world):
    """The two limits agree: with the defaults, a row failing the same way three
    ticks in a row is stopped by the supervisor's streak on its third failure — the
    row limit is the backstop for failures that differ or straddle a restart."""
    assert SupervisorConfig().max_consecutive_failures == MAX_ROW_ATTEMPTS
    ledger = world.ledger
    run = _checklist_run(ledger)
    intake = _FlakyIntake(99, same=True)
    planner = ChecklistPlanner(_rows(), scope_kinds={"research", "write"}, ledger=ledger)
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=planner, config=ON)
    outcomes = [(await sup.tick(run.id)).outcome for _ in range(MAX_ROW_ATTEMPTS)]
    assert outcomes == ["stepped", "stepped", "stopped"]
    assert ledger.get(run.id).stop_reason == "stuck: the governed intake refused it: OSError"


@pytest.mark.parametrize("resolution", ["rejected", "lost", "expired"])
async def test_a_row_the_queue_answered_is_done_and_never_asked_again(world, resolution):
    """A refusal, a vanished task and an ask that expired unanswered all reached the
    owner: re-asking would be a duplicate ask, so the checklist moves on."""
    ledger = world.ledger
    run = _checklist_run(ledger)
    step = ledger.record_step(run.id, kind="research", summary="collect the figures",
                              outcome="queued", task_id=7)
    if resolution == "expired":
        ledger._conn.execute("UPDATE steps SET outcome='failed', detail=? WHERE seq=?",
                             ('{"resolution":"expired_unanswered"}', step.seq))
        ledger._conn.commit()
    else:
        ledger.resolve_step(run.id, step.seq,
                            outcome="refused" if resolution == "rejected" else "failed",
                            detail={"resolution": resolution})
    ledger.resume(run.id)
    planner = ChecklistPlanner(_rows(), scope_kinds={"research", "write"}, ledger=ledger)
    action = await planner({"run": {"id": run.id}, "budget": {"steps_left": 10}})
    assert action.summary == "write the brief"


# ── item 5 (2): a steps read that fails holds; it never re-asks row 1 ────────

class _StepsFailFor:
    """Make ``ledger.steps`` raise the next ``n`` times it is called."""

    def __init__(self, ledger, n):
        self.left = n
        self._steps = ledger.steps

    def __call__(self, *args, **kwargs):
        if self.left > 0:
            self.left -= 1
            raise sqlite3.OperationalError("database is locked")
        return self._steps(*args, **kwargs)


@pytest.mark.parametrize("failing_reads", [1, 2])
async def test_a_steps_read_that_fails_holds_instead_of_re_asking_row_one(world, monkeypatch,
                                                                         failing_reads):
    """One failed read used to return "nothing done" (and a grade, since the repeat
    check then refused row 1); two re-queued row 1 — a duplicate ask to the owner."""
    ledger = world.ledger
    run = _checklist_run(ledger)
    intake = _FlakyIntake(0)
    graded: list = []
    planner = ChecklistPlanner(_rows(), scope_kinds={"research", "write"}, ledger=ledger)
    sup = CompanySupervisor(
        ledger, enqueue=intake, plan_next=planner, config=ON,
        verify=lambda rid: graded.append(rid) or types.SimpleNamespace(passed=True, reason=""),
        judge=lambda rid: graded.append(rid) or types.SimpleNamespace(passed=True, reason=""),
    )
    assert (await sup.tick(run.id)).outcome == "stepped"
    ledger.resume(run.id)
    monkeypatch.setattr(ledger, "steps", _StepsFailFor(ledger, failing_reads))
    held = await sup.tick(run.id)
    assert held.outcome == "idle" and held.detail.startswith("held: ")
    assert intake.calls == ["Collect the figures"] and graded == []
    monkeypatch.undo()
    assert (await sup.tick(run.id)).outcome == "stepped"
    assert intake.calls == ["Collect the figures", "Write the brief"]


async def test_the_runtime_s_walk_passes_the_planner_s_hold_through(world, monkeypatch):
    """``company_runtime._walk`` turns only an out-of-scope refusal into a stop; any
    other answer — a transient Hold included — reaches the supervisor unchanged."""
    ledger = world.ledger
    run = _checklist_run(ledger)
    goal = types.SimpleNamespace(scope_kinds=frozenset({"research", "write"}),
                                 plan_steps=_rows)
    orch = _Orch(world)
    runtime = build_company_runtime(orch, goals=lambda _gid: goal,
                                    config=ScheduleConfig(enabled=True))
    ticks = _record_ticks(runtime)
    monkeypatch.setattr(ledger, "steps", _StepsFailFor(ledger, 1))
    await _sweep(runtime)
    assert [(t.outcome, t.detail) for t in ticks] == [
        ("idle", "held: the run's steps could not be read")]
    assert orch.calls == [] and ledger.get(run.id).status == "planning"


# ── item 6: open_run's idempotent return ends its transaction ────────────────

def _write_probe(path):
    """A second connection that must get the write lock at once (timeout=0)."""
    other = sqlite3.connect(str(path), timeout=0)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.rollback()
    finally:
        other.close()


async def test_a_retried_open_returns_the_run_and_leaves_no_transaction_open(world):
    tid = _goal_task(world.q, _draft())
    first = _open(world, tid)
    again = _open(world, tid)
    assert again.id == first.id
    assert world.ledger._conn.in_transaction is False
    _write_probe(world.path)
    step = world.ledger.record_step(first.id, kind="research", summary="next",
                                    outcome="ok", task_id=1)
    assert step.seq == 1


async def test_a_refused_reuse_of_an_approval_leaves_no_transaction_open(world):
    draft = _draft()
    tid = _goal_task(world.q, draft)
    other = types.SimpleNamespace(goal_id="g-other", title=draft.title,
                                  approved_by=f"task:{tid}:owner",
                                  deadline_at=draft.deadline_at)
    run = world.ledger.open_run(other, budget=draft.budget, deadline_at=draft.deadline_at)
    with pytest.raises(WorkRunError) as exc:
        _open(world, tid)
    assert exc.value.reason == "approval_already_used"
    assert world.ledger._conn.in_transaction is False
    _write_probe(world.path)
    assert world.ledger.record_step(run.id, kind="research", summary="next",
                                    outcome="ok", task_id=1).seq == 1


# ── item 7b: a stop Hold names its cause ─────────────────────────────────────

@pytest.mark.parametrize("cause, prefix, tick_prefix", [
    ("not_bound", "plan not bound to its approval", "the approved plan cannot be proven"),
    ("scope", "approved row refused by scope", "approved row refused by scope"),
    ("retries", "approved row failed too often", "approved row failed too often"),
])
async def test_a_stop_hold_is_reported_by_its_cause(world, cause, prefix, tick_prefix):
    ledger = world.ledger
    run = ledger.open_run(types.SimpleNamespace(goal_id="g", title="t", approved_by="receipt:1"))
    hold = Hold("task kind file.write is not in ['research']", stop=True, cause=cause)
    sup = CompanySupervisor(ledger, enqueue=lambda **_kw: 1, plan_next=lambda _c: hold,
                            config=ON)
    result = await sup.tick(run.id)
    assert (result.outcome, result.detail) == (
        "stopped", f"{tick_prefix}: task kind file.write is not in ['research']")
    assert ledger.get(run.id).stop_reason == (
        f"{prefix}: task kind file.write is not in ['research']")


async def test_a_hold_s_cause_defaults_to_not_bound_and_is_validated():
    assert Hold("x").cause == "not_bound"
    assert Hold("x", stop=True).cause == "not_bound"
    with pytest.raises(ValueError):
        Hold("x", stop=True, cause="whatever")
