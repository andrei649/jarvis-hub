"""H464d — the hub's park before grading leaves exactly the room the real sweep needs.

H464c reserved "the longest of a minute, a tenth of the run's wall-clock budget and
one sweep plus a minute" at the end of a run's time. Both halves were wrong:

  · the tenth is 48 minutes of an 8-hour night, so a run with less than that left was
    graded at once, before the task it had queued had landed;
  · the sweep ignored the per-run interval (``ScheduleConfig.interval_seconds``, which
    ``ScheduleRuntime.due`` enforces): at a cadence under it, a run whose park hit its
    cap sat ``not_due`` until its budget or deadline was spent, and was never graded.

The rule now: ``ceil(interval / cadence) * cadence + 60 s`` — the park is taken in a
tick, so the run is next due on the first sweep at least one interval later, and that
is at most ``ceil(interval / cadence)`` sweeps after it; the minute is slack for a late
timer. These drive the REAL chain — ``build_company_runtime``, the real
``ScheduleRuntime.due`` gate with its own ``_last`` (never cleared or edited here), the
approved checklist read back from a real task queue — on one hand-driven clock, one
sweep per cadence, against the default 300 s interval, with the run's time bound by
its budget and by its deadline:

  (i)   enough time left: the finished plan parks on its in-flight task and is graded
        only after that task lands, never before;
  (ii)  less time left than the margin: the park is refused ``no_time_left`` and the
        run is graded at this very tick;
  (iii) the task never lands: the cap passes and the run is still graded before its
        budget or deadline ends.
"""

from __future__ import annotations

import math
import types
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agents.core.autonomy.company_runtime import build_company_runtime
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.schedule_runtime import ScheduleConfig
from agents.core.autonomy.work_runs import Budget, WorkRunError, WorkRunLedger
from tests.test_h464c_company_run_binding import (
    _ROW,
    _draft,
    _finish,
    _goal_task,
    _open,
    _RealOrch,
)

pytestmark = pytest.mark.asyncio

T0 = 1_800_000_000.0
INTERVAL = ScheduleConfig().interval_seconds     # 300 s: the default per-run interval
CADENCES = (60.0, 120.0, 240.0, 300.0, 1_200.0)  # autonomy.company_tick_seconds
BOUNDS = ("budget", "deadline")
NIGHT = Budget().max_seconds                     # the default 8 h budget
FAR = 9_999_999_999.0


def _due_after(cadence: float) -> float:
    """How long after a tick the run is next due: the first sweep on the cadence that
    is at least one interval later."""
    return math.ceil(INTERVAL / cadence) * cadence


def _margin(cadence: float) -> float:
    """The rule under test, written out independently of the code."""
    return _due_after(cadence) + 60.0


@pytest.fixture
def clock(monkeypatch):
    now = [T0]
    monkeypatch.setattr("agents.core.autonomy.queue._now",
                        lambda: datetime.fromtimestamp(now[0], UTC).isoformat())
    monkeypatch.setattr("agents.core.autonomy.queue._approval_now",
                        lambda supplied=None: supplied or datetime.fromtimestamp(now[0], UTC))
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_SAFE_MODE", raising=False)
    return now


@dataclass
class Night:
    """What one scenario saw, sweep by sweep."""

    parked_at: float | None = None     # the tick that finished the plan (park or grade)
    end: float | None = None           # when the run's budget or deadline is spent
    cap: float | None = None           # the hub park's cap, when it parked
    landed_at: float | None = None
    graded: list = field(default_factory=list)     # (moment, task status) per grading
    skipped: list = field(default_factory=list)    # (moment, skip reason) per sweep
    hub_parks: int = 0
    refusal: str = ""                  # why the hub did not park, when it did not


async def _night(base, clock, *, cadence, bound, left, max_seconds=None, land_after=None):
    """One approved one-row goal, swept once per ``cadence`` until graded or spent.

    The row is queued at ``T0`` and the owner accepts its task at once, so the plan is
    finished on the first sweep the run is due again, ``T0 + _due_after(cadence)``. The
    run is set up to have exactly ``left`` seconds of its time left then: by its budget
    (``bound="budget"``, opened early enough) or by its deadline. Its task stays
    approved — in flight — until ``land_after`` seconds after that tick, or forever.
    """
    due = _due_after(cadence)
    if bound == "budget":
        max_seconds = max_seconds or left + due
        opened, deadline = T0 - (max_seconds - due - left), FAR
    else:
        max_seconds = max_seconds or left + due + 600.0
        opened, deadline = T0, T0 + due + left
    assert opened <= T0 and max_seconds >= left + due
    base.mkdir()
    clock[0] = opened
    q = TaskQueue(str(base / "tasks.db")).initialize()
    ledger = WorkRunLedger(base / "work.db", clock=lambda: clock[0])
    world = types.SimpleNamespace(clock=clock, q=q, ledger=ledger)
    night = Night()
    task: dict[str, int] = {}

    def verify(run_id):
        status = q.get(task["id"]).status
        night.graded.append((clock[0], str(getattr(status, "value", status))))
        return types.SimpleNamespace(passed=True, reason="checked")

    def judge(run_id):
        return types.SimpleNamespace(passed=True, reason="judged")

    try:
        draft = _draft(plan=[_ROW], budget=Budget(max_seconds=max_seconds), deadline=deadline)
        goal_task = _goal_task(q, draft)
        run = _open(world, goal_task)
        _finish(q, goal_task)
        runtime = build_company_runtime(
            _RealOrch(world), verify=verify, judge=judge,
            config=ScheduleConfig(enabled=True), sweep_seconds=cadence,
        )
        # The scheduler's own clock, so due() runs on the hand-driven time. Its _last
        # is left alone: the per-run interval is exactly what is under test.
        runtime.parts.scheduler._clock = lambda: clock[0]
        clock[0] = T0
        await runtime.sweep()                         # the row is queued; the run blocks
        task["id"] = ledger.steps(run.id)[0].task_id
        world.q.transition(task["id"], TaskStatus.APPROVED, decided_by="owner",
                           decision="accept", human_reason=None)
        now = T0
        while not night.graded and now <= T0 + due + left + cadence:
            now += cadence
            if (land_after is not None and night.landed_at is None
                    and night.parked_at is not None and night.parked_at + land_after <= now):
                clock[0] = night.parked_at + land_after       # the worker finishes it
                q.transition(task["id"], TaskStatus.RUNNING)
                q.transition(task["id"], TaskStatus.DONE, result={"ok": True})
                night.landed_at = clock[0]
            clock[0] = now
            result = await runtime.sweep()
            night.skipped.append((now, dict(result.get("skipped") or {}).get(run.id)))
            if night.parked_at is None and (
                night.graded or ledger.barrier_sets(run.id, source="hub")
            ):
                night.parked_at = now
                seconds_left = ledger.budget_state(run.id, settle=False)["seconds_left"]
                night.end = min(deadline, now + seconds_left)
                barrier = ledger.get(run.id).barrier
                night.cap = barrier["cap_at"] if barrier else None
                if night.graded:
                    # Graded at the tick that finished the plan: ask the hub's park, at
                    # this same moment, why it did not wait.
                    try:
                        runtime.parts.barriers.park_in_flight(run.id)
                        night.refusal = "parked"
                    except WorkRunError as exc:
                        night.refusal = exc.reason
        night.hub_parks = len(ledger.barrier_sets(run.id, source="hub"))
    finally:
        ledger.close()
        q.close()
    return night


def _where(night: Night) -> str:
    return ", ".join(f"+{m - T0:g}s {r or 'ticked'}" for m, r in night.skipped)


# ── (i) enough time left: graded only after the task lands ─────────────────────

@pytest.mark.parametrize("bound", BOUNDS)
@pytest.mark.parametrize("cadence", CADENCES)
async def test_with_time_to_spare_the_run_is_graded_only_after_its_task_lands(
    tmp_path, clock, cadence, bound
):
    """A night run (the default 8 h budget) with a second, or twenty minutes, to spare
    past the margin: the finished plan waits on its running task, and the verdict is
    spent on work that has landed. A tenth of the budget (48 min) used to refuse this
    park and grade the run at once, with its task still running."""
    margin = _margin(cadence)
    for spare in (1.0, 1_200.0):
        left = margin + spare
        night = await _night(tmp_path / f"spare{spare:g}", clock, cadence=cadence,
                             bound=bound, left=left, max_seconds=NIGHT, land_after=spare / 2)
        assert night.parked_at == T0 + _due_after(cadence)
        assert night.end == pytest.approx(night.parked_at + left)
        assert night.hub_parks == 1, f"{left:g}s left: the hub did not wait on the task"
        assert night.cap == pytest.approx(night.end - margin)
        assert night.landed_at is not None
        assert len(night.graded) == 1, _where(night)
        when, status = night.graded[0]
        assert when >= night.landed_at and status == "done"
        assert when < night.end


# ── (ii) less time left than the margin: graded at this tick ───────────────────

@pytest.mark.parametrize("bound", BOUNDS)
@pytest.mark.parametrize("cadence", CADENCES)
async def test_with_less_time_left_than_the_margin_the_run_is_graded_now(
    tmp_path, clock, cadence, bound
):
    margin = _margin(cadence)
    for left in (1.0, margin / 2, margin - 1.0, margin):
        night = await _night(tmp_path / f"left{left:g}", clock, cadence=cadence,
                             bound=bound, left=left, max_seconds=NIGHT)
        tick = T0 + _due_after(cadence)
        assert night.hub_parks == 0, f"{left:g}s left: the hub parked with no room to grade"
        assert night.refusal == "no_time_left"
        # Graded at the very tick that finished the plan, the task still in flight.
        assert night.graded == [(tick, "approved")]
        assert night.end == pytest.approx(tick + left)


# ── (iii) the task never lands: still graded before the end ────────────────────

@pytest.mark.parametrize("bound", BOUNDS)
@pytest.mark.parametrize("cadence", CADENCES)
async def test_a_task_that_never_lands_still_leaves_a_graded_run(tmp_path, clock, cadence, bound):
    """Whatever time is left when the plan finishes, the run gets its verdict before
    its budget or deadline ends: it parks only when the margin leaves a due sweep after
    the cap, and otherwise is graded at once. The budgets here are as small as the
    scenario allows (``left`` plus the wait to the next due sweep), so no share of the
    budget can mask the interval — plus two night runs."""
    due, margin = _due_after(cadence), _margin(cadence)
    lefts = sorted({
        1.0, 30.0, cadence / 2, INTERVAL / 2, due - 1.0, due, margin - 1.0, margin,
        margin + 1.0, margin + cadence / 2, margin + due, 2 * margin + 7.0,
    })
    cases = [(left, None) for left in lefts] + [(margin + 1.0, NIGHT), (margin + 1_200.0, NIGHT)]
    problems: list[str] = []
    for n, (left, budget) in enumerate(cases):
        night = await _night(tmp_path / f"case{n}", clock, cadence=cadence, bound=bound,
                             left=left, max_seconds=budget)
        what = f"{left:g}s left" + (" (8 h budget)" if budget else "")
        assert night.end == pytest.approx(T0 + due + left), what
        if not night.graded:
            problems.append(f"{what}: never graded — {_where(night)}")
            continue
        when, status = night.graded[0]
        assert status == "approved"
        if when >= night.end:
            problems.append(f"{what}: graded at +{when - T0:g}s, at or after its end")
        if night.hub_parks != (1 if left > margin else 0):
            problems.append(f"{what}: {night.hub_parks} hub park(s) with a {margin:g}s margin")
        if night.hub_parks and when < night.cap:
            problems.append(f"{what}: graded before the park's cap")
    assert not problems, "\n".join(problems)
