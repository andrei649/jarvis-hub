"""H464d — the shipped company run is graded after its work lands, at any cadence.

The H464c review (round 3) found the grading margin, the approval-wait credit and
the hold path still leaning on things they must not lean on. These pin the fixes,
each ported from the reviewer's repro (``SP/h464ch/exp``, ``SP/h464cv/exp_c.py``):

  · A1/B2 — the hub's park before grading stops exactly the room grading needs: the
    time from a tick to the next sweep on which the scheduler's own per-run interval
    lets the run be due, plus a minute. No share of the budget, so a run with time
    to spare waits for its task; and never less, so the run is graded at ANY sweep
    cadence — driven through the real ``due()`` gate, never by clearing ``_last``;
  · B1 — any exception out of re-minting the approved goal is provable: the run is
    stopped with the reason, and the tick never fails on it;
  · B3 — an open approval wait is observed on the tick path, so its credit is the
    same whether or not a HUD polled the (read-only) report;
  · B4 — a hold leaves one durable event per hold, the brief says the run is held and
    why, and a held run whose budget runs out is settled like any spent run;
  · F2/F3 — a step the intake failed is retried (bounded); a failed read of the
    run's own steps holds the tick instead of queueing row 1 again;
  · M43 — the idempotent re-open leaves no transaction open;
  · C1/C2/C4 — dotted scope kinds, plain stop reasons in the brief.

Hermetic: real task queues and ledgers under tmp_path on one hand-driven clock that
the scheduler reads too, spies for the governed intake, and fake graders.
"""

from __future__ import annotations

import sqlite3
import traceback
import types
from datetime import UTC, datetime

import pytest

from agents.core.autonomy.company_report import build_company_brief, render_company_brief
from agents.core.autonomy.company_runtime import build_company_runtime
from agents.core.autonomy.goal_contract import GoalDraft, SuccessCheck, approve_from_task
from agents.core.autonomy.pending_requests import PendingRequests
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.schedule_runtime import ScheduleConfig, ScheduleRuntime
from agents.core.autonomy.work_runs import Budget, WorkRunLedger

pytestmark = pytest.mark.asyncio

T0 = 1_800_000_000.0
EIGHT_HOURS = 8 * 3_600.0

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


class _Worlds:
    """Fresh queue + ledger pairs under tmp_path, all on ONE clock (the queue's own
    timestamps included), so a test can drive several runs from zero."""

    def __init__(self, tmp_path, clock):
        self._tmp = tmp_path
        self.clock = clock
        self._open: list = []

    def new(self):
        self.clock[0] = T0
        path = self._tmp / f"w{len(self._open)}"
        path.mkdir()
        q = TaskQueue(str(path / "tasks.db")).initialize()
        ledger = WorkRunLedger(path / "work.db", clock=lambda: self.clock[0])
        self._open.append((q, ledger))
        return types.SimpleNamespace(clock=self.clock, q=q, ledger=ledger, path=path)

    def close(self):
        for q, ledger in self._open:
            ledger.close()
            q.close()


@pytest.fixture
def worlds(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr("agents.core.autonomy.queue._now",
                        lambda: datetime.fromtimestamp(clock[0], UTC).isoformat())
    monkeypatch.setattr("agents.core.autonomy.queue._approval_now",
                        lambda supplied=None: supplied or datetime.fromtimestamp(clock[0], UTC))
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_SAFE_MODE", raising=False)
    made = _Worlds(tmp_path, clock)
    yield made
    made.close()


@pytest.fixture
def world(worlds):
    return worlds.new()


def _draft(plan=(), scope=("research", "write"), budget=None, deadline=9_999_999_999.0):
    return GoalDraft(
        title="Prepare the brief", scope_kinds=tuple(scope),
        budget=budget or Budget(), deadline_at=deadline,
        stop_conditions=("the source data changes",),
        checks=(SuccessCheck(id="c1", describe="a brief exists", probe_ref="p:x"),),
        deliverable="one brief", plan=tuple(plan),
    )


def _goal_task(q, draft, decided_by="owner"):
    payload = draft.as_payload()
    payload["fingerprint"] = draft.fingerprint()
    tid = q.enqueue("jarvis", "goal.approve", f"Approve goal: {draft.title}", payload)
    q.transition(tid, TaskStatus.APPROVED, decided_by=decided_by, decision="accept",
                 human_reason=None)
    return tid


def _open(world, tid):
    goal = approve_from_task(world.q.get(tid))
    return world.ledger.open_run(goal, budget=goal.budget, deadline_at=goal.deadline_at)


def _finish(q, tid):
    q.transition(tid, TaskStatus.RUNNING)
    q.transition(tid, TaskStatus.DONE, result={"status": "ok"})


def _approve(q, tid):
    q.transition(tid, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                 human_reason=None)


class _RealOrch:
    """Only the names the shipped orchestrator has; the intake is a spy that ends as
    the real one does for an ask: a durable row, blocked on the owner. ``fail`` is a
    list of exceptions the intake raises, one per call, before it works again."""

    def __init__(self, world, *, read=None, fail=None):
        self.work_runs = world.ledger
        self.company_runtime = None
        self.calls: list[dict] = []
        self.fail = list(fail or [])
        q = world.q

        def govern_enqueue(**kwargs):
            self.calls.append(dict(kwargs))
            if self.fail:
                raise self.fail.pop(0)
            tid = q.enqueue(kwargs["agent"], kwargs["kind"], kwargs["title"],
                            dict(kwargs.get("payload") or {}))
            q.transition(tid, TaskStatus.BLOCKED)
            return tid

        self.autonomy_queue = types.SimpleNamespace(get=read or q.get)
        self.autonomy = types.SimpleNamespace(govern_enqueue=govern_enqueue)


def _graders(world, graded, *, passed=True):
    """Graders that record when they were asked and what the run's own tasks were
    doing at that moment."""

    def _statuses(run_id):
        return [world.q.get(s.task_id).status for s in world.ledger.steps(run_id)
                if s.task_id is not None]

    def verify(run_id):
        graded.append(("verify", world.clock[0] - T0, _statuses(run_id)))
        return types.SimpleNamespace(passed=passed, reason="checked")

    def judge(run_id):
        graded.append(("judge", world.clock[0] - T0, _statuses(run_id)))
        return types.SimpleNamespace(passed=passed, reason="judged")

    return verify, judge


def _runtime(world, orch=None, *, sweep_seconds=None, **kwargs):
    """The shipped runtime, with the scheduler on the test clock. ``_last`` is never
    touched: the per-run interval gate is part of what is under test."""
    runtime = build_company_runtime(orch or _RealOrch(world), config=ScheduleConfig(enabled=True),
                                    sweep_seconds=sweep_seconds, **kwargs)
    runtime.parts.scheduler._clock = lambda: world.clock[0]
    return runtime


def _record_ticks(runtime):
    seen = []
    tick = runtime.parts.scheduler._tick

    async def _tick(run_id):
        result = await tick(run_id)
        seen.append(result)
        return result

    runtime.parts.scheduler._tick = _tick
    return seen


def _hold_events(ledger, run_id):
    return [(e["kind"], e["detail"].get("reason")) for e in reversed(ledger.events(run_id, limit=500))
            if e["kind"].startswith("hold.")]


# ── A1 / B2: the room grading needs, and no more ────────────────────────────

async def test_the_grading_margin_is_the_next_due_sweep_plus_a_minute():
    """No share of the budget any more; the floor is the time from a tick to the next
    sweep on which the scheduler's per-run interval lets the run be due, plus a
    minute — at least a minute, whatever a direct caller passes."""
    from agents.core.autonomy import run_barriers
    from agents.core.autonomy.run_barriers import GRADE_MARGIN_SECONDS, RunBarriers, grade_margin
    from agents.core.autonomy.schedule_runtime import next_due_after_tick

    assert not hasattr(run_barriers, "GRADE_MARGIN_SHARE")
    assert GRADE_MARGIN_SECONDS == 60.0
    # the per-run interval is 300 s; the sweep cadence is the owner's setting
    assert next_due_after_tick(60.0, 300.0) == 300.0
    assert next_due_after_tick(120.0, 300.0) == 360.0      # sweeps at 120, 240, 360
    assert next_due_after_tick(200.0, 300.0) == 400.0      # max(S, I) would say 300
    assert next_due_after_tick(300.0, 300.0) == 300.0
    assert next_due_after_tick(1_200.0, 300.0) == 1_200.0
    assert grade_margin(360.0) == 360.0
    assert grade_margin(0.0) == 60.0 and grade_margin(float("nan")) == 60.0
    assert RunBarriers(object(), grade_floor=0.0)._grade_floor == 60.0
    assert RunBarriers(object(), grade_floor=float("nan"))._grade_floor == 60.0


@pytest.mark.parametrize("sweep, floor", [
    (60, 360.0), (120, 420.0), (200, 460.0), (300, 360.0), (1_200, 1_260.0),
])
async def test_the_runtime_sizes_the_margin_from_the_cadence_and_the_interval(
        world, sweep, floor):
    runtime = _runtime(world, sweep_seconds=float(sweep))
    assert runtime.parts.barriers._grade_floor == floor


def _next_due(sweep):
    return {60: 300, 120: 360, 200: 400, 300: 300, 1_200: 1_200}[sweep]


async def _drive(worlds, *, sweep, budget=None, deadline_after=None, finish_at=None,
                 start_task=False):
    """One run on the shipped chain, swept every ``sweep`` seconds from T0 with the
    real interval gate. Row 1's task is approved by the owner 30 s in and then either
    never runs, or runs (``start_task``) and finishes at ``finish_at`` (seconds from
    T0). Returns what happened."""
    world = worlds.new()
    deadline = T0 + deadline_after if deadline_after is not None else 9_999_999_999.0
    draft = _draft(plan=[_ROW], budget=Budget(max_seconds=budget) if budget else Budget(),
                   deadline=deadline)
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    graded: list = []
    verify, judge = _graders(world, graded)
    runtime = _runtime(world, verify=verify, judge=judge, sweep_seconds=float(sweep))
    skipped: list = []
    await runtime.sweep()                                   # T0: row 1 queued, blocked
    step = world.ledger.steps(run.id)[0]
    world.clock[0] = T0 + 30
    _approve(world.q, step.task_id)
    if start_task:
        world.q.transition(step.task_id, TaskStatus.RUNNING)
    k = 0
    while not graded and k < 400:
        k += 1
        world.clock[0] = T0 + k * sweep
        if (finish_at is not None and world.clock[0] - T0 >= finish_at
                and world.q.get(step.task_id).status == "running"):
            world.q.transition(step.task_id, TaskStatus.DONE, result={"ok": True})
        result = await runtime.sweep()
        reason = dict(result.get("skipped") or {}).get(run.id)
        skipped.append(reason)
        if reason == "budget_spent":
            break
    parks = world.ledger.barrier_sets(run.id, source="hub")
    return types.SimpleNamespace(run=run, graded=graded, skipped=skipped, parks=parks,
                                 end=(deadline - T0) if deadline_after is not None else budget,
                                 ledger=world.ledger)


@pytest.mark.parametrize("sweep", [60, 120, 200, 300, 1_200])
async def test_a_parked_run_is_graded_before_its_time_runs_out_at_any_cadence(worlds, sweep):
    """Its task approved but never started, the run is parked by the hub and must still
    be graded — at every cadence, with the park starting anywhere from just past the
    margin to far before it, for a run bounded by its budget or by its deadline. The
    scheduler's ``_last`` is never cleared: the real ``due()`` gate decides."""
    first_tick = _next_due(sweep)        # the owner's approval is read on this sweep
    margin = first_tick + 60.0
    lefts = sorted({61, first_tick - 30, first_tick, first_tick + 1, first_tick + 59,
                    first_tick + 61, first_tick + sweep + 61, 2 * first_tick + 61} - {0})
    parked_any = False
    for left in lefts:
        for bound in ("budget", "deadline"):
            kwargs = ({"budget": float(first_tick + left)} if bound == "budget"
                      else {"deadline_after": float(first_tick + left)})
            got = await _drive(worlds, sweep=sweep, **kwargs)
            label = f"sweep={sweep} left={left} bound={bound}"
            assert [g[0] for g in got.graded] == ["verify", "judge"], (label, got.skipped)
            assert "budget_spent" not in got.skipped, (label, got.skipped)
            assert got.ledger.budget_state(got.run.id)["exceeded"] is None, label
            if left > margin:            # time to spare past the margin: it waited
                assert got.parks, label
            parked_any = parked_any or bool(got.parks)
    assert parked_any


async def test_a_run_with_time_to_spare_waits_for_its_running_task_before_grading(worlds):
    """The reviewer's e10: an 8 h run whose checklist is done with 40 minutes left while
    its task is still running, finishing 15 minutes later. A tenth of the budget (48
    minutes) used to leave no room to wait, so the run's single verdict was spent on a
    running task. Now it waits, and is graded on the finished work."""
    world = worlds.new()
    tid = _goal_task(world.q, _draft(plan=[_ROW]))
    run = _open(world, tid)
    _finish(world.q, tid)
    graded: list = []
    verify, judge = _graders(world, graded)
    runtime = _runtime(world, verify=verify, judge=judge, sweep_seconds=300.0)
    await runtime.sweep()                                   # row 1 queued, blocked
    step = world.ledger.steps(run.id)[0]
    world.clock[0] += 30
    _approve(world.q, step.task_id)
    await runtime.sweep()                                   # resumed; not due yet
    world.q.transition(step.task_id, TaskStatus.RUNNING)    # the worker starts it
    world.clock[0] = T0 + EIGHT_HOURS - 40 * 60             # 40 minutes left
    finish_at = world.clock[0] + 15 * 60
    while not graded and world.clock[0] < T0 + EIGHT_HOURS + 600:
        if world.clock[0] >= finish_at and world.q.get(step.task_id).status == "running":
            world.q.transition(step.task_id, TaskStatus.DONE, result={"status": "ok"})
        await runtime.sweep()
        world.clock[0] += 300
    assert [g[0] for g in graded] == ["verify", "judge"]
    assert graded[0][2] == ["done"]                         # the task had landed
    assert graded[0][1] >= finish_at - T0
    assert world.ledger.barrier_sets(run.id, source="hub")[0]["target"] == f"task:{step.task_id}"
    assert world.ledger.budget_state(run.id)["exceeded"] is None


@pytest.mark.parametrize("left_minutes", [60, 40, 10])
async def test_the_hub_park_stops_the_margin_short_of_the_end_whatever_the_budget(
        world, left_minutes):
    """The reviewer's e9: an 8 h run with its task still running parks until the end
    of its time less the margin, not less a tenth of the budget."""
    from agents.core.autonomy.run_barriers import RunBarriers

    run = world.ledger.open_run(types.SimpleNamespace(goal_id="g", title="t",
                                                      approved_by="receipt:1"),
                                budget={"max_steps": 50, "max_seconds": EIGHT_HOURS,
                                        "max_interrupts": 2})
    tid = world.q.enqueue("jarvis", "research.collect", "Collect", {})
    _approve(world.q, tid)
    world.ledger.record_step(run.id, kind="research", summary="collect", outcome="ok",
                             task_id=tid)
    world.clock[0] += EIGHT_HOURS - left_minutes * 60
    barriers = RunBarriers(world.ledger, read_task=world.q.get, clock=lambda: world.clock[0],
                           grade_floor=360.0)
    state = barriers.park_in_flight(run.id)
    assert state is not None and state["source"] == "hub"
    assert state["cap_at"] - world.clock[0] == pytest.approx(left_minutes * 60 - 360.0)


async def test_a_sweep_that_starts_a_moment_early_still_finds_the_run_due(world):
    """The timer fires on a fixed schedule and each sweep reads the clock a few
    milliseconds after it fires; a run ticked on one sweep must be due on the sweep one
    interval later, not skipped for being a millisecond short (which would push its
    grading a whole sweep past the margin)."""
    ticks: list = []
    runtime = ScheduleRuntime(world.ledger, tick=lambda run_id: ticks.append(run_id),
                              config=ScheduleConfig(enabled=True, interval_seconds=300.0),
                              clock=lambda: world.clock[0])
    run = world.ledger.open_run(types.SimpleNamespace(goal_id="g", title="t",
                                                      approved_by="receipt:1"))
    world.clock[0] = T0 + 0.004
    await runtime.sweep()
    world.clock[0] = T0 + 300.001                            # 299.997 s later
    await runtime.sweep()
    assert ticks == [run.id, run.id]
    world.clock[0] = T0 + 598.0                              # 297.999 s later
    result = await runtime.sweep()
    assert result.skipped == {run.id: "not_due"}


# ── B1: whatever re-minting raises is provable, never a failed tick ──────────

async def test_an_edit_that_makes_the_approved_goal_unmintable_stops_the_run(world):
    """The reviewer's e8: the DONE approval task edited to ``budget.max_steps=0``
    made the re-mint raise WorkRunError, which escaped: every sweep was tick_failed,
    and the run stayed ``planning`` with nothing on its record."""
    draft = _draft(plan=[_ROW], budget=Budget(max_seconds=1_800.0))
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    payload = dict(world.q.get(tid).payload)
    payload["budget"] = dict(payload["budget"], max_steps=0)
    world.q.update_payload(tid, payload)
    graded: list = []
    verify, judge = _graders(world, graded)
    orch = _RealOrch(world)
    runtime = _runtime(world, orch, verify=verify, judge=judge)
    result = await runtime.parts.scheduler.sweep()
    assert [(e.reason, e.outcome) for e in result.entries] == [("", "stopped")]
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == (
        "stopped", "plan not bound to its approval: invalid_max_steps")
    assert orch.calls == [] and graded == []


@pytest.mark.parametrize("error, reason", [
    (ValueError("bad number"), "approved_goal_invalid"),
    (TypeError("not a mapping"), "approved_goal_invalid"),
    (KeyError("plan"), "approved_goal_invalid"),
])
async def test_any_exception_from_re_minting_is_provable_but_a_failed_read_holds(
        world, monkeypatch, error, reason):
    from agents.core.autonomy import goal_contract
    from agents.core.autonomy.company_runtime import _read_back

    tid = _goal_task(world.q, _draft(plan=[_ROW]))
    run = _open(world, tid)

    def _raise(_task, **_kw):
        raise error

    monkeypatch.setattr(goal_contract, "approve_from_task", _raise)
    found = _read_back(run, world.q.get)
    assert (found.goal, found.reason, found.transient) == (None, reason, False)

    def _locked(_task_id):
        raise sqlite3.OperationalError("database is locked")

    unread = _read_back(run, _locked)
    assert (unread.reason, unread.transient) == ("approval_task_unreadable", True)


# ── B3: an open approval wait is observed on the tick path ───────────────────

@pytest.mark.parametrize("hud_polls", [True, False])
async def test_an_edited_ask_is_credited_the_same_whether_or_not_the_hud_polled(
        world, hud_polls):
    """The reviewer's e1/e1b: with the report routes read-only, nothing on the tick
    path observed a blocked run's open ask, so an ask the owner edited before approving
    (whose decision stamp cannot be used) was credited nothing — and at BASE only what
    the HUD's polling had happened to write. The reconciler, which already reads every
    blocked run's asks on each sweep, now records the open wait."""
    led, q, clock = world.ledger, world.q, world.clock
    led.bind_approval_task_reader(q.get)
    reconciler = PendingRequests(led, read_task=q.get)
    scheduler = ScheduleRuntime(led, tick=lambda _run_id: None, reconcile=reconciler.sweep,
                                config=ScheduleConfig(enabled=True, interval_seconds=60.0),
                                clock=lambda: clock[0])
    run = led.open_run(types.SimpleNamespace(goal_id="g", title="Goal", approved_by="owner"),
                       budget={"max_steps": 50, "max_seconds": 1_800, "max_interrupts": 5})
    tid = q.enqueue("jarvis", "test", "Ask", {})
    q.transition(tid, TaskStatus.BLOCKED)
    led.record_step(run.id, kind="ask", summary="Ask", outcome="queued", task_id=tid)
    for _ in range(3):                      # a sweep a minute, the HUD maybe polling
        clock[0] += 60
        await scheduler.sweep()
        if hud_polls:
            changes = led._conn.total_changes
            led.snapshot(run.id)
            assert led._conn.total_changes == changes      # the report writes nothing
    clock[0] += 10
    q.update_payload(tid, {"owner": "tweaked the step"})   # the owner edits the ask ...
    clock[0] += 10
    _approve(q, tid)                                        # ... and approves it
    clock[0] += 10
    await scheduler.sweep()                                 # the reconcile resumes the run
    after = led.budget_state(run.id)
    assert led.get(run.id).status == "working"
    assert after["human_wait_seconds"] == 180.0
    assert after["seconds_used"] == 30.0


# ── B4: a hold is on the record, in the brief, and bounded by the budget ─────

async def test_a_held_run_is_recorded_once_shown_in_the_brief_and_settled_when_spent(world):
    """The reviewer's e4: an approval task that cannot be read on any sweep held the
    run until its budget ran out, and it ended ``planning`` with an empty stop reason,
    no event, nothing in the brief — only a WARNING per sweep in the logs."""
    draft = _draft(plan=[_ROW], budget=Budget(max_seconds=1_800.0))
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)

    def reader(task_id):
        if task_id == tid:
            raise sqlite3.DatabaseError("database disk image is malformed")
        return world.q.get(task_id)

    graded: list = []
    verify, judge = _graders(world, graded)
    orch = _RealOrch(world, read=reader)
    runtime = _runtime(world, orch, verify=verify, judge=judge, sweep_seconds=300.0)
    ticks = _record_ticks(runtime)
    await runtime.sweep()
    assert [(t.outcome, t.detail) for t in ticks] == [("idle", "held: approval_task_unreadable")]
    brief = build_company_brief([world.ledger.snapshot(run.id)], company_mode_enabled=True,
                                now=world.clock[0])
    assert brief["held"] == [run.id]
    [summary] = brief["runs"]
    assert summary["held"] == "its approval could not be read"
    assert summary["headline"].startswith("held — its approval could not be read")
    assert "held" in render_company_brief(brief)
    for _ in range(8):
        world.clock[0] += 300
        await runtime.sweep()
    assert _hold_events(world.ledger, run.id) == [("hold.start", "approval_task_unreadable")]
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == ("stopped", "budget:seconds")
    assert orch.calls == [] and graded == []
    brief = build_company_brief([world.ledger.snapshot(run.id)], company_mode_enabled=True,
                                now=world.clock[0])
    assert brief["held"] == []
    assert brief["runs"][0]["headline"] == "ran out of budget — it ran out of time"


async def test_a_hold_that_clears_is_recorded_as_ended_and_the_next_one_as_new(world):
    draft = _draft(plan=[_ROW, _ROW2])
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    broken = {"on": 0}

    def reader(task_id):
        if broken["on"] and int(task_id) == tid:
            broken["on"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return world.q.get(task_id)

    orch = _RealOrch(world, read=reader)
    runtime = _runtime(world, orch)
    broken["on"] = 2
    await runtime.sweep()                                   # held
    world.clock[0] += 300
    await runtime.sweep()                                   # still held: no new event
    assert _hold_events(world.ledger, run.id) == [("hold.start", "approval_task_unreadable")]
    world.clock[0] += 300
    await runtime.sweep()                                   # read works: row 1 queued
    assert _hold_events(world.ledger, run.id) == [
        ("hold.start", "approval_task_unreadable"), ("hold.end", None)]
    assert [s.summary for s in world.ledger.steps(run.id)] == ["collect the figures"]
    assert world.ledger.snapshot(run.id)["hold"] is None
    for step in world.ledger.steps(run.id):                 # the owner approves row 1
        _approve(world.q, step.task_id)
    world.clock[0] += 300
    await runtime.sweep()                                   # row 2 queued: no second end
    assert [s.summary for s in world.ledger.steps(run.id)] == [
        "collect the figures", "write the brief"]
    assert _hold_events(world.ledger, run.id) == [
        ("hold.start", "approval_task_unreadable"), ("hold.end", None)]
    _approve(world.q, world.ledger.steps(run.id)[-1].task_id)
    broken["on"] = 1
    world.clock[0] += 300
    await runtime.sweep()                                   # held again: a new hold
    assert _hold_events(world.ledger, run.id) == [
        ("hold.start", "approval_task_unreadable"), ("hold.end", None),
        ("hold.start", "approval_task_unreadable")]
    assert world.ledger.snapshot(run.id)["hold"]["reason"] == "approval_task_unreadable"


async def test_the_scheduler_settles_a_spent_run_it_will_never_tick(world):
    """A run whose budget is spent is skipped ``budget_spent`` and never ticked, so the
    supervisor's own settle never ran on it: it stayed open for ever. The sweep settles
    it the way the supervisor settles any spent run — but never on a budget it merely
    failed to read."""
    run = world.ledger.open_run(types.SimpleNamespace(goal_id="g", title="t",
                                                      approved_by="receipt:1"),
                                budget={"max_steps": 5, "max_seconds": 600.0,
                                        "max_interrupts": 1})
    runtime = _runtime(world)
    world.clock[0] += 601
    result = await runtime.parts.scheduler.sweep()
    assert result.skipped == {run.id: "budget_spent"}
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == ("stopped", "budget:seconds")

    other = world.ledger.open_run(types.SimpleNamespace(goal_id="g2", title="t",
                                                        approved_by="receipt:2"))
    real = world.ledger.budget_state

    def broken(run_id, **kw):
        raise sqlite3.OperationalError("database is locked")

    world.ledger.budget_state = broken
    try:
        result = await runtime.parts.scheduler.sweep()
    finally:
        world.ledger.budget_state = real
    assert result.skipped == {other.id: "budget_spent"}
    assert world.ledger.get(other.id).status == "planning"


# ── F2 / F3: a transient failure never skips a row nor repeats one ───────────

async def _to_row_two(world, orch):
    """Row 1 queued, approved, run and done; returns the runtime and the run."""
    draft = _draft(plan=[_ROW, _ROW2])
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    runtime = _runtime(world, orch)
    await runtime.sweep()
    step = world.ledger.steps(run.id)[0]
    _approve(world.q, step.task_id)
    _finish(world.q, step.task_id)
    world.clock[0] += 300
    return runtime, run


async def test_a_step_the_intake_failed_is_retried_on_a_later_sweep(world):
    """``intake_fail``: the governed intake raised once for row 2; the failed step
    counted as done, and the run went to grading with row 2 never queued."""
    orch = _RealOrch(world)
    runtime, run = await _to_row_two(world, orch)
    orch.fail = [sqlite3.OperationalError("database is locked")]
    ticks = _record_ticks(runtime)
    await runtime.sweep()                                   # row 2: the intake fails
    world.clock[0] += 300
    await runtime.sweep()                                   # row 2 again: queued
    assert [(s.summary, s.outcome) for s in world.ledger.steps(run.id)] == [
        ("collect the figures", "ok"), ("write the brief", "failed"),
        ("write the brief", "queued")]
    assert [t.outcome for t in ticks] == ["stepped", "stepped"]


async def test_a_row_that_keeps_failing_stops_the_run_with_the_reason(world):
    """Retried, but not for ever: after three failed attempts at one row the run is
    stopped with the row named — even when the failures differ, so the same-failure
    streak never fires."""
    orch = _RealOrch(world)
    runtime, run = await _to_row_two(world, orch)
    orch.fail = [sqlite3.OperationalError("database is locked"), TimeoutError(),
                 sqlite3.OperationalError("database is locked"), TimeoutError()]
    for _ in range(4):
        await runtime.sweep()
        world.clock[0] += 300
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == (
        "stopped", "approved row kept failing: write the brief (3 attempts)")
    assert len(orch.calls) == 1 + 3


async def test_a_failed_read_of_the_run_steps_holds_instead_of_asking_again(world):
    """``steps_fail``: a transient failure reading the ledger's steps inside the
    checklist read as "nothing done", and row 1 was queued a second time — a duplicate
    ask for the owner and a spent step."""
    orch = _RealOrch(world)
    runtime, run = await _to_row_two(world, orch)
    real = world.ledger.steps

    def steps(run_id, *a, **kw):
        if any("company_planner" in frame.filename for frame in traceback.extract_stack()):
            raise sqlite3.OperationalError("database is locked")
        return real(run_id, *a, **kw)

    world.ledger.steps = steps
    ticks = _record_ticks(runtime)
    try:
        await runtime.sweep()
    finally:
        world.ledger.steps = real
    assert [(t.outcome, t.detail) for t in ticks] == [("idle", "held: run_steps_unreadable")]
    assert len(orch.calls) == 1
    world.clock[0] += 300
    await runtime.sweep()
    assert [s.summary for s in world.ledger.steps(run.id)] == [
        "collect the figures", "write the brief"]


# ── M43: the idempotent re-open ends its transaction ─────────────────────────

async def test_a_retried_open_leaves_no_transaction_open_for_the_next_write(world):
    tid = _goal_task(world.q, _draft(plan=[_ROW]))
    first = _open(world, tid)
    again = _open(world, tid)
    assert again.id == first.id
    assert world.ledger._conn.in_transaction is False
    step = world.ledger.record_step(first.id, kind="research", summary="x", outcome="ok")
    assert step.seq == 1


# ── C1: a dotted scope kind admits its own sub-kinds ─────────────────────────

async def test_a_dotted_scope_kind_admits_its_own_sub_kinds():
    from agents.core.autonomy.goal_contract import task_kind_in_scope

    assert task_kind_in_scope("file.write.append", ("file.write",))
    assert task_kind_in_scope("file.write", ("file.write",))
    assert not task_kind_in_scope("file.writer", ("file.write",))
    assert not task_kind_in_scope("file", ("file.write",))
    assert not task_kind_in_scope("file.read", ("file.write",))
    assert task_kind_in_scope("research.collect", ("research",))
    assert not task_kind_in_scope("researcher.x", ("research",))
    row = {"kind": "file.write", "summary": "save the brief",
           "task": {"agent": "jarvis", "kind": "file.write.append", "title": "Save"}}
    _draft(plan=[row], scope=("file.write",))              # the card is accepted


# ── C2 / C4: the stop reasons read plainly ───────────────────────────────────

async def test_a_run_stopped_on_its_approval_reads_plainly_in_the_brief(world):
    """An in-flight run from before the upgrade is stopped once, with a reason the owner
    can act on — not the bare code."""
    run = world.ledger.open_run(types.SimpleNamespace(
        goal_id="g", title="Old run", approved_by="task:7:owner"))
    orch = _RealOrch(world)
    await _runtime(world, orch).sweep()
    snap = world.ledger.snapshot(run.id)
    assert snap["run"]["stop_reason"] == "plan not bound to its approval: no_approved_fingerprint"
    [summary] = build_company_brief([snap], company_mode_enabled=True,
                                    now=world.clock[0])["runs"]
    assert summary["headline"] == (
        "stopped — it was opened before this version tied a run to the plan you "
        "approved; approve the goal again to run it")


async def test_an_approved_row_refused_by_scope_says_so_not_unbound(world):
    from agents.core.autonomy.company_planner import PlanStep

    run = world.ledger.open_run(types.SimpleNamespace(
        goal_id="g", title="t", approved_by="receipt:1"))
    goal = types.SimpleNamespace(
        scope_kinds=frozenset({"research"}),
        plan_steps=lambda: [PlanStep(kind="research", summary="collect", task={
            "agent": "jarvis", "kind": "file.write", "title": "Collect", "payload": {}})],
    )
    orch = _RealOrch(world)
    await _runtime(world, orch, goals=lambda _gid: goal).sweep()
    after = world.ledger.get(run.id)
    assert after.status == "stopped" and orch.calls == []
    assert after.stop_reason.startswith("approved row refused by scope: task kind file.write")
    [summary] = build_company_brief([world.ledger.snapshot(run.id)],
                                    company_mode_enabled=True, now=world.clock[0])["runs"]
    assert summary["headline"].startswith("stopped — approved row refused by scope")
