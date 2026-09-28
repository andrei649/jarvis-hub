"""H464c — the approved checklist is bound to what the owner approved, once.

The H464b review (round 2) found the shipped chain trusting too much of what it
reads back. These pin the fixes, each ported from the reviewer's repro:

  · M1 — the run pins the approved goal's fingerprint when it opens; an edit of the
    approval task afterwards (fingerprint kept, recomputed or dropped) drives nothing;
  · M2 — one approval task opens one run, however often ``goal.approve`` is retried;
  · M3 — the hub's park on a running task stops early enough for the run to be graded;
  · M4 — safe mode leaves the company sweep out, at boot and at every sweep;
  · M5 — an approval task that cannot be read just now HOLDS the run (no step, no
    park, no grade); one that provably does not bind STOPS it with the reason on its
    record — never a half-done checklist graded as finished;
  · M6 — a checklist row's queued task kind is inside the goal's scope, or refused;
  · N1 — the report routes read only what they show and write nothing;
  · N2 — the task reader is bound on the shared ledger only when the runtime builds.

Hermetic: a real task queue and a ledger under tmp_path on one hand-driven clock, a
spy for the governed intake, and fake graders.
"""

from __future__ import annotations

import sqlite3
import types
from datetime import UTC, datetime

import pytest

from agents.core.autonomy import goal_contract
from agents.core.autonomy.company_runtime import build_company_runtime
from agents.core.autonomy.goal_contract import (
    GoalContractError,
    GoalDraft,
    SuccessCheck,
    approve_from_task,
    draft_from_payload,
)
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.schedule_runtime import ScheduleConfig
from agents.core.autonomy.work_runs import Budget, WorkRunError, WorkRunLedger

pytestmark = pytest.mark.asyncio

T0 = 1_800_000_000.0

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
# In scope, never approved: what an edit of the approval task would slip in.
_EDIT = {
    "kind": "research", "summary": "send the figures out",
    "task": {"agent": "jarvis", "kind": "research.publish", "title": "Publish the figures",
             "payload": {"to": "everyone"}},
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


def _draft(plan=(), scope=("research", "write"), budget=None, deadline=9_999_999_999.0,
           unrestricted=False):
    return GoalDraft(
        title="Prepare the brief", scope_kinds=tuple(scope), unrestricted=unrestricted,
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
    """The goal.approve task executes and completes, as the worker does."""
    q.transition(tid, TaskStatus.RUNNING)
    q.transition(tid, TaskStatus.DONE, result={"status": "ok"})


class _RealOrch:
    """Only the names the shipped orchestrator has; the intake is a spy that ends
    as the real one does for an ask: a durable row, blocked on the owner."""

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


def _queued(ledger, run_id):
    return [s for s in ledger.steps(run_id) if s.outcome == "queued"]


def _graders(graded, *, passed=True):
    def verify(run_id):
        graded.append(("verify", run_id))
        return types.SimpleNamespace(passed=passed, reason="checked")

    def judge(run_id):
        graded.append(("judge", run_id))
        return types.SimpleNamespace(passed=passed, reason="judged")

    return verify, judge


# ── M1: bound to the fingerprint the owner approved, pinned when the run opened ──

@pytest.mark.parametrize("variant, reason", [
    ("keep_stale_fingerprint", "payload_changed_after_approval"),
    ("recompute_fingerprint", "approved_goal_changed"),
    ("strip_fingerprint", "approved_goal_changed"),
])
async def test_an_edit_of_the_approval_task_after_the_run_opened_drives_nothing(
    world, variant, reason
):
    """The read-back used to compare the payload only with the fingerprint the payload
    carries about itself: dropping or recomputing it ran a plan nobody approved."""
    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)

    payload = dict(world.q.get(tid).payload)
    payload["plan"] = [_EDIT]
    if variant == "strip_fingerprint":
        payload.pop("fingerprint")
    elif variant == "recompute_fingerprint":
        payload["fingerprint"] = draft_from_payload(payload).fingerprint()
    world.q.update_payload(tid, payload)       # the task is DONE; the queue API allows it

    orch = _RealOrch(world)
    await _sweep(build_company_runtime(orch))
    assert orch.calls == []
    assert _queued(world.ledger, run.id) == []
    after = world.ledger.get(run.id)
    assert after.status == "stopped"
    assert after.stop_reason == f"plan not bound to its approval: {reason}"


async def test_the_run_pins_the_fingerprint_the_owner_approved(world):
    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft)
    goal = approve_from_task(world.q.get(tid))
    assert goal.approved_fingerprint == draft.fingerprint()
    run = world.ledger.open_run(goal, budget=goal.budget, deadline_at=goal.deadline_at)
    assert run.approved_fingerprint == draft.fingerprint()

    reopened = WorkRunLedger(world.path, clock=lambda: world.clock[0])
    try:
        assert reopened.get(run.id).approved_fingerprint == draft.fingerprint()
        assert reopened.tampered(run.id) is False
        # Inside the row's own fingerprint: a hand edit of the pin reads as tampering.
        with sqlite3.connect(world.path) as conn:
            conn.execute("UPDATE runs SET approved_fingerprint = ? WHERE id = ?",
                         ("0" * 64, run.id))
        assert reopened.tampered(run.id) is True
    finally:
        reopened.close()


async def test_a_run_opened_without_a_pinned_fingerprint_drives_nothing(world):
    """A run opened before the pin existed (or from anything but an ApprovedGoal)
    cannot prove which plan was approved, so it runs none."""
    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft)
    legacy = types.SimpleNamespace(goal_id="g-legacy", title=draft.title,
                                   approved_by=f"task:{tid}:owner",
                                   deadline_at=draft.deadline_at)
    run = world.ledger.open_run(legacy, budget=draft.budget, deadline_at=draft.deadline_at)
    assert run.approved_fingerprint == ""
    orch = _RealOrch(world)
    await _sweep(build_company_runtime(orch))
    assert orch.calls == []
    assert world.ledger.get(run.id).stop_reason == (
        "plan not bound to its approval: no_approved_fingerprint")


async def test_a_v4_database_gains_the_pin_column_and_its_runs_read_as_unpinned(tmp_path):
    from agents.core.autonomy import work_runs
    from agents.core.persistence.migrations import apply_migrations

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    apply_migrations(conn, work_runs.MIGRATIONS[:4], name="work_runs")
    # A row written before the pin existed, fingerprinted over the identity it had then.
    run = work_runs.WorkRun(id="r1", goal_id="g", title="t", status="planning",
                            approved_by="task:5:owner", budget=Budget(max_steps=5),
                            started_at=1_000.0, updated_at=1_000.0)
    conn.execute(
        "INSERT INTO runs (id, goal_id, title, status, approved_by, budget, started_at, "
        "updated_at, deadline_at, fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run.id, run.goal_id, run.title, run.status, run.approved_by,
         work_runs._canonical(run.budget.as_dict()), 1_000.0, 1_000.0, 0.0,
         work_runs._fingerprint(run.identity())),
    )
    conn.commit()
    conn.close()
    for _ in range(2):      # idempotent
        led = WorkRunLedger(path, clock=lambda: 1_000.0)
        try:
            assert led.get("r1").approved_fingerprint == ""
            assert led.tampered("r1") is False
        finally:
            led.close()
    with sqlite3.connect(path) as check:
        assert check.execute("PRAGMA user_version").fetchone()[0] == len(work_runs.MIGRATIONS)


# ── M2: one approval task, one run ───────────────────────────────────────────

async def test_a_retried_approval_opens_one_run_and_the_plan_runs_once(world):
    """``goal.approve`` retried after a broken attempt mints a new goal id from the
    same task; the second open is the first run, not a second one."""
    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft)
    first = _open(world, tid)
    again = _open(world, tid)
    assert again.id == first.id
    assert [r.id for r in world.ledger.list_runs()] == [first.id]
    _finish(world.q, tid)
    orch = _RealOrch(world)
    runtime = build_company_runtime(orch)
    for _ in range(3):
        await _sweep(runtime)
    assert len(orch.calls) == 1


class _CommitFailsOnce:
    """The ledger's connection, whose next commit raises without committing."""

    def __init__(self, conn):
        self._conn = conn
        self.armed = True

    def commit(self):
        if self.armed:
            self.armed = False
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


async def test_an_open_whose_commit_raised_leaves_nothing_for_the_retry_to_double(world):
    """The known gap: the first attempt's INSERT stayed pending on the connection and
    the retry's commit wrote it next to the retry's own — two runs, one approval."""
    tid = _goal_task(world.q, _draft(plan=[_ROW]))
    real = world.ledger._conn
    world.ledger._conn = _CommitFailsOnce(real)
    try:
        with pytest.raises(sqlite3.OperationalError):
            _open(world, tid)
        run = _open(world, tid)                       # the worker's retry
    finally:
        world.ledger._conn = real
    fresh = WorkRunLedger(world.path, clock=lambda: world.clock[0])
    try:
        assert [r.id for r in fresh.list_runs()] == [run.id]
    finally:
        fresh.close()


async def test_an_approval_already_spent_on_another_run_is_refused(world):
    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft)
    other = types.SimpleNamespace(goal_id="g-other", title=draft.title,
                                  approved_by=f"task:{tid}:owner",
                                  deadline_at=draft.deadline_at)
    world.ledger.open_run(other, budget=draft.budget, deadline_at=draft.deadline_at)
    with pytest.raises(WorkRunError) as exc:
        _open(world, tid)
    assert exc.value.reason == "approval_already_used"
    assert len(world.ledger.list_runs()) == 1


async def test_a_retried_goal_approve_reports_the_one_run_it_opened(world):
    """The ``goal.approve`` handler, retried: the same run, and the run's own goal id
    — not the id the retry minted for a goal that never got a run."""
    from tests.test_web_tools_wiring import _coordinator

    coordinator = _coordinator({})
    executor = coordinator.build_executor()
    built = coordinator._orch.work_runs
    coordinator._orch.work_runs = world.ledger
    built.close()
    task = world.q.get(_goal_task(world.q, _draft(plan=[_ROW])))
    handler = executor.resolve("goal.approve")
    first = await handler(task)
    again = await handler(task)
    assert first["status"] == again["status"] == "ok"
    assert again["run_id"] == first["run_id"]
    assert again["goal_id"] == first["goal_id"] == world.ledger.get(first["run_id"]).goal_id


async def test_an_unpinned_open_never_reuses_a_run_for_the_same_approval(world):
    """Nothing proves an unpinned goal is the one the first run was opened for, so a
    second open for the same approval task is refused rather than handed that run."""
    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft)

    def _unpinned(goal_id):
        return types.SimpleNamespace(goal_id=goal_id, title=draft.title,
                                     approved_by=f"task:{tid}:owner",
                                     deadline_at=draft.deadline_at)

    world.ledger.open_run(_unpinned("g-1"), budget=draft.budget, deadline_at=draft.deadline_at)
    with pytest.raises(WorkRunError) as exc:
        world.ledger.open_run(_unpinned("g-2"), budget=draft.budget,
                              deadline_at=draft.deadline_at)
    assert exc.value.reason == "approval_already_used"


async def test_approval_refs_outside_the_goal_contract_keep_their_meaning(world):
    """Only a ``task:<id>:…`` ref names one durable decision; other refs (a receipt,
    a test's) may back more than one goal, as before."""
    for goal_id in ("g-1", "g-2"):
        world.ledger.open_run(types.SimpleNamespace(
            goal_id=goal_id, title="t", approved_by="receipt:owner-accepted-1"))
    assert len(world.ledger.list_runs()) == 2


# ── M3: the hub's park leaves room to grade ──────────────────────────────────

@pytest.mark.parametrize("bound, sweep", [
    ("budget", None), ("deadline", None),
    ("budget", 1_200.0),         # the reviewer's cadence: a sweep every 20 minutes
])
async def test_the_hub_park_ends_early_enough_for_the_run_to_be_graded(world, bound, sweep):
    """The park's cap used to be the exact end of the budget (or the deadline): a task
    approved but never started ate the time left and the run was never graded."""
    from agents.core.autonomy.run_barriers import grade_margin

    if bound == "budget":
        draft = _draft(plan=[_ROW], budget=Budget(max_seconds=3_600.0))
    else:   # a night run: 8 h budget, deadline one hour out
        draft = _draft(plan=[_ROW], deadline=T0 + 3_600.0)
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    graded: list = []
    verify, judge = _graders(graded)
    config = ScheduleConfig(enabled=True)
    runtime = build_company_runtime(_RealOrch(world), verify=verify, judge=judge,
                                    config=config, sweep_seconds=sweep)
    cadence = sweep or config.interval_seconds
    await _sweep(runtime)                                  # step queued, run blocked
    step = world.ledger.steps(run.id)[0]
    world.clock[0] += 60
    # the owner approves the step's task; the worker never picks it up
    world.q.transition(step.task_id, TaskStatus.APPROVED, decided_by="owner",
                       decision="accept", human_reason=None)
    await _sweep(runtime)
    parked = world.ledger.get(run.id).barrier
    assert parked is not None and parked["source"] == "hub"
    # H464d: whole sweeps to the next due one, plus a minute — no share of the budget.
    margin = grade_margin(interval_seconds=config.interval_seconds, sweep_seconds=sweep)
    assert margin == -(-config.interval_seconds // cadence) * cadence + 60.0
    if bound == "budget":
        left = world.ledger.budget_state(run.id)["seconds_left"]
        assert parked["cap_at"] == pytest.approx(world.clock[0] + left - margin)
    else:
        assert parked["cap_at"] == pytest.approx(T0 + 3_600.0 - margin)

    skipped = []
    for _ in range(20):                                   # one sweep per cadence
        world.clock[0] += cadence
        result = await _sweep(runtime)
        skipped.append(dict(result.get("skipped") or {}).get(run.id))
        if graded:
            break
    assert graded == [("verify", run.id), ("judge", run.id)]
    assert "budget_spent" not in skipped
    assert world.ledger.budget_state(run.id)["exceeded"] is None


async def test_no_park_when_the_time_left_is_all_needed_to_grade(world):
    """Nothing to spare past the grading margin: the hub does not park at all. The
    plan finishes at T0 + 30 with exactly the margin left (H464d: 360 s at the
    default interval and cadence)."""
    draft = _draft(plan=[_ROW], deadline=T0 + 30.0 + 360.0)
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    graded: list = []
    verify, judge = _graders(graded)
    runtime = build_company_runtime(_RealOrch(world), verify=verify, judge=judge,
                                    config=ScheduleConfig(enabled=True))
    ticks = _record_ticks(runtime)
    await _sweep(runtime)
    step = world.ledger.steps(run.id)[0]
    world.clock[0] += 30
    world.q.transition(step.task_id, TaskStatus.APPROVED, decided_by="owner",
                       decision="accept", human_reason=None)
    ticks.clear()
    await _sweep(runtime)
    assert [t.outcome for t in ticks] == ["graded"]
    assert world.ledger.barrier_sets(run.id, source="hub") == []


async def test_the_grading_margin_is_whole_sweeps_to_the_next_due_one_plus_a_minute(world):
    """H464d: ``ceil(interval / cadence) * cadence + 60 s`` — the interval counts, the
    budget does not, and a RunBarriers built with no margin keeps the minute."""
    from agents.core.autonomy import run_barriers
    from agents.core.autonomy.run_barriers import GRADE_MARGIN_SECONDS, RunBarriers, grade_margin

    assert GRADE_MARGIN_SECONDS == 60.0
    assert not hasattr(run_barriers, "GRADE_MARGIN_SHARE")
    for cadence, margin in ((60.0, 360.0), (120.0, 420.0), (240.0, 540.0),
                            (300.0, 360.0), (450.0, 510.0), (1_200.0, 1_260.0),
                            (None, 360.0)):
        assert grade_margin(interval_seconds=300.0, sweep_seconds=cadence) == margin
    for broken in (None, 0, -5.0, float("nan"), "300", True):
        assert grade_margin(interval_seconds=broken, sweep_seconds=60.0) == 60.0
    with pytest.raises(TypeError):
        grade_margin(3_600.0)      # the old (max_seconds, floor) call fails loudly
    assert RunBarriers(world.ledger)._grade_margin == 60.0
    assert RunBarriers(world.ledger, grade_margin_seconds=10.0)._grade_margin == 60.0
    assert RunBarriers(world.ledger, grade_margin_seconds=540.0)._grade_margin == 540.0
    for cadence, margin in ((None, 360.0), (240.0, 540.0), (1_200.0, 1_260.0)):
        runtime = build_company_runtime(_RealOrch(world), config=ScheduleConfig(enabled=True),
                                        sweep_seconds=cadence)
        assert runtime.parts.barriers._grade_margin == margin


# ── M4: safe mode leaves the company sweep out ───────────────────────────────

class _Sched:
    def __init__(self):
        self.jobs = []

    def add_job(self, fn, trigger, **kw):
        self.jobs.append(kw.get("id"))


async def test_safe_mode_registers_no_company_sweep(world, monkeypatch):
    from agents.core import safe_mode
    from agents.core.scheduler_service import SchedulerService

    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    safe_mode.reset()
    try:
        sched = _Sched()
        orch = _RealOrch(world)
        orch.heartbeat_scheduler = types.SimpleNamespace(scheduler=sched)
        orch.get_setting = lambda key, default=None: default
        SchedulerService(orch).schedule_company_mode()
        assert sched.jobs == []
        assert orch.company_runtime is None
        assert world.ledger._approval_task_reader is None
        assert "company_mode" in safe_mode.status()["skipped"]
    finally:
        safe_mode.reset()


async def test_the_scheduler_tells_the_runtime_its_sweep_cadence(world, monkeypatch):
    from agents.core.scheduler_service import SchedulerService

    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    sched = _Sched()
    orch = _RealOrch(world)
    orch.heartbeat_scheduler = types.SimpleNamespace(scheduler=sched)
    orch.get_setting = lambda key, default=None: 1_200 if "company_tick" in key else default
    SchedulerService(orch).schedule_company_mode()
    assert sched.jobs == ["company-mode-sweep"]
    # 1 200 s sweeps against the 300 s interval: one sweep and a minute (H464d).
    assert orch.company_runtime.parts.barriers._grade_margin == 1_260.0


async def test_a_sweep_does_nothing_while_safe_mode_is_on(world, monkeypatch):
    """Safe mode is read at call time (H275/H490), so the sweep re-checks it."""
    from agents.core import safe_mode

    tid = _goal_task(world.q, _draft(plan=[_ROW]))
    _open(world, tid)
    orch = _RealOrch(world)
    runtime = build_company_runtime(orch)
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    try:
        assert await _sweep(runtime) == {"ok": True, "swept": 0, "reason": "safe mode is on"}
        assert orch.calls == []
    finally:
        safe_mode.reset()
    monkeypatch.delenv("JARVIS_SAFE_MODE")
    await _sweep(runtime)
    assert len(orch.calls) == 1


# ── M5: cannot read now → hold; provably not bound → stop, never grade ────────

async def test_one_failed_read_of_the_approval_task_holds_instead_of_grading(world):
    """A locked queue for one read used to empty the plan, and the supervisor graded
    a two-row checklist after its first row."""
    draft = _draft(plan=[_ROW, _ROW2])
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    graded: list = []
    verify, judge = _graders(graded, passed=False)
    broken = {"on": False}

    def read(task_id):
        if broken["on"] and int(task_id) == tid:
            broken["on"] = False
            raise sqlite3.OperationalError("database is locked")
        return world.q.get(task_id)

    runtime = build_company_runtime(_RealOrch(world, read=read), verify=verify, judge=judge,
                                    config=ScheduleConfig(enabled=True))
    ticks = _record_ticks(runtime)
    await _sweep(runtime)                                  # row 1 queued, blocked
    step = world.ledger.steps(run.id)[0]
    for status in (TaskStatus.APPROVED, TaskStatus.RUNNING, TaskStatus.DONE):
        kwargs = {"decided_by": "owner", "decision": "accept", "human_reason": None} \
            if status is TaskStatus.APPROVED else ({"result": {"ok": True}}
                                                     if status is TaskStatus.DONE else {})
        world.q.transition(step.task_id, status, **kwargs)
    world.clock[0] += 60
    broken["on"] = True
    ticks.clear()
    await _sweep(runtime)
    assert [(t.outcome, t.detail) for t in ticks] == [
        ("idle", "held: approval_task_unreadable")]
    assert graded == []
    assert world.ledger.get(run.id).status not in {"failed", "stopped", "succeeded"}
    assert world.ledger.barrier_sets(run.id) == []
    await _sweep(runtime)                                  # the read works again
    assert [s.summary for s in world.ledger.steps(run.id)] == [
        "collect the figures", "write the brief"]
    assert graded == []


async def test_a_goal_decided_by_policy_stops_the_run_with_the_reason_and_no_grade(world):
    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft, decided_by="policy")
    run = world.ledger.open_run(
        types.SimpleNamespace(goal_id="g-p", title=draft.title,
                              approved_by=f"task:{tid}:policy",
                              deadline_at=draft.deadline_at,
                              approved_fingerprint=draft.fingerprint()),
        budget=draft.budget, deadline_at=draft.deadline_at,
    )
    graded: list = []
    verify, judge = _graders(graded)
    orch = _RealOrch(world)
    runtime = build_company_runtime(orch, verify=verify, judge=judge,
                                    config=ScheduleConfig(enabled=True))
    ticks = _record_ticks(runtime)
    await _sweep(runtime)
    assert [(t.outcome, t.detail) for t in ticks] == [
        ("stopped", "the approved plan cannot be proven: not_decided_by_a_human")]
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == (
        "stopped", "plan not bound to its approval: not_decided_by_a_human")
    assert graded == [] and orch.calls == []
    assert world.ledger.verdicts(run.id) == []
    from agents.core.autonomy.company_report import build_company_brief

    brief = build_company_brief([world.ledger.snapshot(run.id)], company_mode_enabled=True,
                                now=world.clock[0])
    assert "not_decided_by_a_human" in str(brief)


async def test_what_the_read_back_answers_for_each_kind_of_doubt(world):
    """``transient`` is "cannot tell now" (hold); anything else is provable (stop)."""
    from agents.core.autonomy.company_runtime import _read_back

    draft = _draft(plan=[_ROW])
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)

    def _locked(_task_id):
        raise sqlite3.OperationalError("database is locked")

    ok = _read_back(run, world.q.get)
    assert ok.goal is not None and ok.reason == "" and ok.transient is False
    assert (_read_back(run, None).reason, _read_back(run, None).transient) == (
        "no_task_queue", True)
    assert (_read_back(run, _locked).reason, _read_back(run, _locked).transient) == (
        "approval_task_unreadable", True)
    gone = _read_back(run, lambda _tid: None)
    assert (gone.goal, gone.reason, gone.transient) == (None, "approval_task_gone", False)
    legacy = types.SimpleNamespace(**{**run.__dict__, "approved_by": "owner:accept:7"})
    assert _read_back(legacy, world.q.get).reason == "not_opened_from_a_goal_card"


async def test_a_binding_check_that_raises_is_a_mismatch_never_a_match(world):
    """CR8: an exception while binding the goal to the run fails closed."""
    from agents.core.autonomy.company_runtime import _approved_goal_for, _read_back

    tid = _goal_task(world.q, _draft(plan=[_ROW]))
    run = _open(world, tid)
    odd = types.SimpleNamespace(**{**run.__dict__, "deadline_at": "soon"})
    assert _approved_goal_for(odd, world.q.get) is None
    assert _read_back(odd, world.q.get).reason == "goal_does_not_match_run"


# ── M6: a row's queued task kind is scope-checked ────────────────────────────

_OUTSIDE = {
    "kind": "research", "summary": "collect the figures",
    "task": {"agent": "jarvis", "kind": "file.write", "title": "Collect the figures",
             "payload": {"path": "notes.txt", "body": "x"}},
}


async def test_the_task_kind_scope_rule():
    from agents.core.autonomy.goal_contract import task_kind_in_scope

    scope = frozenset({"research", "file.write"})
    assert task_kind_in_scope("research", scope)
    assert task_kind_in_scope("research.collect", scope)
    assert task_kind_in_scope("file.write", scope)
    assert not task_kind_in_scope("file.delete", scope)
    assert not task_kind_in_scope("file", scope)
    assert not task_kind_in_scope("researcher.collect", scope)
    assert not task_kind_in_scope(None, scope)
    assert task_kind_in_scope("anything.at.all", frozenset())      # unrestricted


async def test_a_card_whose_row_queues_a_task_outside_its_scope_is_refused():
    with pytest.raises(GoalContractError) as exc:
        _draft(plan=[_OUTSIDE], scope=("research",))
    assert exc.value.reason == "plan_task_out_of_scope"
    # a row with no task, or a task in scope, or an unrestricted goal is fine
    _draft(plan=[{"kind": "research", "summary": "think"}], scope=("research",))
    _draft(plan=[_ROW], scope=("research",))
    _draft(plan=[_OUTSIDE], scope=(), unrestricted=True)


async def test_the_planner_refuses_a_row_whose_task_is_outside_the_scope(world):
    from agents.core.autonomy.company_planner import ChecklistPlanner, ModelPlanner, PlanStep

    run = world.ledger.open_run(types.SimpleNamespace(
        goal_id="g", title="t", approved_by="receipt:1"))
    context = {"run": {"id": run.id}, "budget": {"steps_left": 5}}
    step = PlanStep(kind="research", summary="collect", task=dict(_OUTSIDE["task"]))
    checklist = ChecklistPlanner([step], scope_kinds={"research"}, ledger=world.ledger)
    assert await checklist(context) is None
    assert checklist.last.refusal == "out_of_scope"
    assert "file.write" in checklist.last.detail
    model = ModelPlanner(lambda _c: dict(_OUTSIDE), scope_kinds={"research"},
                         ledger=world.ledger)
    assert await model(context) is None
    assert model.last.refusal == "out_of_scope"
    fine = ChecklistPlanner([PlanStep(kind="research", summary="collect",
                                      task=dict(_ROW["task"]))],
                            scope_kinds={"research"}, ledger=world.ledger)
    assert (await fine(context)).task["kind"] == "research.collect"


async def test_an_approved_row_outside_the_scope_stops_the_run_unqueued(world, monkeypatch):
    """A card approved before the check existed: the read-back refuses the goal by
    name and the run stops; the task outside the scope never reaches the intake."""
    monkeypatch.setattr(goal_contract, "task_kind_in_scope", lambda *_a: True, raising=False)
    draft = _draft(plan=[_OUTSIDE], scope=("research",))
    tid = _goal_task(world.q, draft)
    run = _open(world, tid)
    _finish(world.q, tid)
    monkeypatch.undo()
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    orch = _RealOrch(world)
    await _sweep(build_company_runtime(orch))
    assert orch.calls == []
    assert world.ledger.get(run.id).stop_reason == (
        "plan not bound to its approval: plan_task_out_of_scope")


async def test_the_runtime_stops_a_run_whose_approved_row_the_planner_refuses(world):
    """However the goal reached the planner, a refused approved row ends the run with
    the reason — it is not "nothing left to do", so it is never graded."""
    from agents.core.autonomy.company_planner import PlanStep

    run = world.ledger.open_run(types.SimpleNamespace(
        goal_id="g", title="t", approved_by="receipt:1"))
    goal = types.SimpleNamespace(
        scope_kinds=frozenset({"research"}),
        plan_steps=lambda: [PlanStep(kind="research", summary="collect",
                                     task=dict(_OUTSIDE["task"]))],
    )
    graded: list = []
    verify, judge = _graders(graded)
    orch = _RealOrch(world)
    runtime = build_company_runtime(orch, goals=lambda _gid: goal, verify=verify,
                                    judge=judge)
    await _sweep(runtime)
    assert orch.calls == [] and graded == []
    after = world.ledger.get(run.id)
    assert after.status == "stopped"
    assert after.stop_reason.startswith("approved row refused by scope: ")
    assert "file.write" in after.stop_reason


# ── N1: the report routes are read-only and bounded ──────────────────────────

def _client(ledger, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core.routers import company as company_routes
    from agents.core.routers._deps import user_guard

    async def _get():
        return ledger

    monkeypatch.setattr(company_routes, "_get_ledger", _get)
    app = FastAPI()
    app.include_router(company_routes.router)
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


async def test_the_runs_report_reads_only_open_waits_and_writes_nothing(world, monkeypatch):
    ledger, q = world.ledger, world.q
    reads: list[int] = []

    def counting(task_id):
        reads.append(int(task_id))
        return q.get(task_id)

    ledger.bind_approval_task_reader(counting)
    for n in range(3):                                   # finished runs, five steps each
        done = ledger.open_run(types.SimpleNamespace(
            goal_id=f"done-{n}", title="t", approved_by="receipt:1"))
        for i in range(5):
            tid = q.enqueue("jarvis", "research.collect", f"t{n}{i}", {})
            ledger.record_step(done.id, kind="research", summary=f"s{i}", outcome="ok",
                               task_id=tid)
        ledger.request_stop(done.id)
        ledger.settle_stop(done.id)
    # a run whose approval wait is over: the owner answered, the run went on
    answered = ledger.open_run(types.SimpleNamespace(goal_id="answered", title="t",
                                                     approved_by="receipt:1"))
    old_ask = q.enqueue("jarvis", "research.collect", "Old ask", {})
    q.transition(old_ask, TaskStatus.BLOCKED)
    step = ledger.record_step(answered.id, kind="research", summary="ask", outcome="queued",
                              task_id=old_ask)
    world.clock[0] += 50
    q.transition(old_ask, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                 human_reason=None)
    ledger.resolve_step(answered.id, step.seq, outcome="ok")
    ledger.resume(answered.id)
    assert ledger.budget_state(answered.id)["human_wait_seconds"] == 50
    live = ledger.open_run(types.SimpleNamespace(goal_id="live", title="t",
                                                 approved_by="receipt:1"))
    ask = q.enqueue("jarvis", "research.collect", "Ask", {})
    q.transition(ask, TaskStatus.BLOCKED)
    ledger.record_step(live.id, kind="research", summary="ask", outcome="queued", task_id=ask)
    world.clock[0] += 100
    reads.clear()
    changes = ledger._conn.total_changes

    resp = _client(ledger, monkeypatch).get("/api/company/runs")
    assert resp.status_code == 200
    assert reads == [ask]                # only the task an open approval wait is on
    assert ledger._conn.total_changes == changes
    assert ledger._conn.in_transaction is False

    reads.clear()
    closed = _client(ledger, monkeypatch).get(f"/api/company/runs/{answered.id}").json()
    assert reads == [] and closed["budget"]["human_wait_seconds"] == 50

    reads.clear()
    one = _client(ledger, monkeypatch).get(f"/api/company/runs/{live.id}").json()
    assert reads == [ask] and ledger._conn.total_changes == changes
    # the same numbers the tick path settles
    assert one["budget"]["human_wait_seconds"] == 100
    assert ledger.budget_state(live.id)["seconds_used"] == one["budget"]["seconds_used"]


# ── N2: the reader is bound only when the runtime builds ─────────────────────

async def test_a_runtime_that_refuses_to_build_binds_no_reader(world):
    orch = types.SimpleNamespace(work_runs=world.ledger, company_runtime=None,
                                 autonomy_queue=types.SimpleNamespace(get=world.q.get),
                                 autonomy=types.SimpleNamespace(govern_enqueue=None))
    assert build_company_runtime(orch) is None
    assert world.ledger._approval_task_reader is None


# ── CS5: a park that answers nothing is not a park ───────────────────────────

async def test_an_empty_answer_from_the_hub_park_reads_as_not_waiting(world):
    from agents.core.autonomy.company_supervisor import CompanySupervisor, SupervisorConfig

    class _EmptyPark:
        def active(self, _run_id):
            return False

        def state(self, _run_id):
            return None

        def park_in_flight(self, _run_id):
            return {}                    # the barrier vanished between set and state()

    run = world.ledger.open_run(types.SimpleNamespace(goal_id="g", title="t",
                                                      approved_by="receipt:1"))
    graded: list = []
    verify, judge = _graders(graded)
    sup = CompanySupervisor(world.ledger, enqueue=lambda **_kw: 1, plan_next=lambda _c: None,
                            verify=verify, judge=judge, barriers=_EmptyPark(),
                            config=SupervisorConfig(enabled=True))
    assert (await sup.tick(run.id)).outcome == "graded"
    assert graded == [("verify", run.id), ("judge", run.id)]
