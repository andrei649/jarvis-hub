"""E5.0 — scheduled continuity: what makes a run keep going without being asked.

This is the "24/7" half, and waking is not a licence, so the tests are about
restraint:

  · a terminal, stopping or budget-spent run is never ticked — waking it would
    burn the supervisor's failure streak against a wall;
  · a blocked run is not poked: it waits on the owner, and a tick changes nothing;
  · a run that ticked recently is not due again;
  · concurrency is bounded, so enabling company mode with ten open goals does not
    mean ten simultaneous agents;
  · night hours are quiet hours for ATTENTION, not for work — steps continue, only
    interruptions wait;
  · a failed tick is reported, never retried here, because the scheduler having
    its own retry loop would multiply the supervisor's failure budget behind it.

Hermetic: a real in-memory ledger, an injected clock and hour, and a fake tick.
"""

import types

import pytest

from agents.core.autonomy.schedule_runtime import (
    ScheduleConfig,
    ScheduleRuntime,
    is_night,
    next_due_at,
    sweep_summary,
)
from agents.core.autonomy.work_runs import Budget, WorkRunLedger

pytestmark = pytest.mark.asyncio

ON = ScheduleConfig(enabled=True, interval_seconds=300.0)


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class _Tick:
    """Stands in for CompanySupervisor.tick."""

    def __init__(self, *, raises: Exception | None = None, outcome: str = "stepped") -> None:
        self.calls: list[str] = []
        self._raises = raises
        self._outcome = outcome

    async def __call__(self, run_id: str):
        self.calls.append(run_id)
        if self._raises is not None:
            raise self._raises
        return types.SimpleNamespace(outcome=self._outcome)


def _goal(goal_id: str = "g-1"):
    return types.SimpleNamespace(
        goal_id=goal_id, title="Prepare the quarterly brief",
        approved_by="receipt:1", deadline_at=1_000_000.0,
    )


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def ledger(clock):
    led = WorkRunLedger(":memory:", clock=clock)
    yield led
    led.close()


def _runtime(ledger, tick, clock, *, config=ON, hour: int = 12):
    return ScheduleRuntime(
        ledger, tick=tick, config=config, clock=clock, local_hour=lambda: hour
    )


# ── default-off ──────────────────────────────────────────────────────────────

async def test_a_scheduler_built_by_accident_sweeps_nothing(ledger, clock):
    ledger.open_run(_goal())
    tick = _Tick()
    result = await _runtime(ledger, tick, clock, config=ScheduleConfig()).sweep()
    assert result.entries == ()
    assert tick.calls == []


# ── who gets woken ───────────────────────────────────────────────────────────

async def test_an_open_run_is_ticked(ledger, clock):
    run = ledger.open_run(_goal())
    tick = _Tick()
    result = await _runtime(ledger, tick, clock).sweep()
    assert tick.calls == [run.id]
    assert result.ticked == (run.id,)
    assert result.entries[0].outcome == "stepped"


async def test_a_finished_run_is_never_woken(ledger, clock):
    """It is a record, not a resource. Waking it would burn the supervisor's
    failure streak against a wall."""
    run = ledger.open_run(_goal())
    ledger.request_stop(run.id)
    ledger.settle_stop(run.id)
    tick = _Tick()
    result = await _runtime(ledger, tick, clock).sweep()
    # list_runs(active_only=True) already excludes it, so it is not even a skip
    assert tick.calls == []
    assert result.entries == ()


async def test_a_stopping_run_is_left_to_the_supervisor(ledger, clock):
    run = ledger.open_run(_goal())
    ledger.request_stop(run.id)
    tick = _Tick()
    result = await _runtime(ledger, tick, clock).sweep()
    assert tick.calls == []
    assert result.skipped == {run.id: "stopping"}


async def test_a_blocked_run_is_not_poked(ledger, clock):
    """It is waiting on the owner's decision; a tick changes nothing and adds noise."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="ask", summary="needs approval",
                       outcome="queued", task_id=5)
    tick = _Tick()
    result = await _runtime(ledger, tick, clock).sweep()
    assert tick.calls == []
    assert result.skipped == {run.id: "blocked"}


async def test_a_run_whose_budget_is_spent_is_not_woken(ledger, clock):
    run = ledger.open_run(_goal(), budget=Budget(max_steps=1))
    ledger.record_step(run.id, kind="a", summary="one", outcome="ok", task_id=1)
    tick = _Tick()
    result = await _runtime(ledger, tick, clock).sweep()
    assert tick.calls == []
    assert result.skipped == {run.id: "budget_spent"}


async def test_a_ledger_that_cannot_answer_is_treated_as_spent_not_as_ready(
    ledger, clock, monkeypatch
):
    """Fail closed: an unreadable budget must not mean "go ahead"."""
    run = ledger.open_run(_goal())

    def _boom(_run_id, **_kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(ledger, "budget_state", _boom)
    tick = _Tick()
    result = await _runtime(ledger, tick, clock).sweep()
    assert tick.calls == []
    assert result.skipped == {run.id: "budget_spent"}


# ── how often ────────────────────────────────────────────────────────────────

async def test_a_run_ticked_a_moment_ago_is_not_due_again(ledger, clock):
    run = ledger.open_run(_goal())
    tick = _Tick()
    runtime = _runtime(ledger, tick, clock)
    await runtime.sweep()
    clock.advance(60)
    result = await runtime.sweep()
    assert tick.calls == [run.id]
    assert result.skipped == {run.id: "not_due"}


async def test_a_run_becomes_due_again_after_the_interval(ledger, clock):
    run = ledger.open_run(_goal())
    tick = _Tick()
    runtime = _runtime(ledger, tick, clock)
    await runtime.sweep()
    clock.advance(301)
    await runtime.sweep()
    assert tick.calls == [run.id, run.id]


async def test_a_fresh_scheduler_treats_every_run_as_due(ledger, clock):
    """After a restart the safe direction is a possible extra tick, not a missed
    one: the ledger's budget already bounds what an extra tick can spend."""
    run = ledger.open_run(_goal())
    first = _Tick()
    await _runtime(ledger, first, clock).sweep()
    second = _Tick()
    await _runtime(ledger, second, clock).sweep()
    assert second.calls == [run.id]


def test_next_due_at_is_immediate_for_a_run_never_ticked():
    assert next_due_at(None, interval=300.0, now=1_000.0) == 1_000.0
    assert next_due_at(1_000.0, interval=300.0, now=1_000.0) == 1_300.0


# ── how many at once ─────────────────────────────────────────────────────────

async def test_concurrency_is_bounded_and_the_rest_are_reported(ledger, clock):
    """Ten open goals must not mean ten simultaneous agents."""
    runs = [ledger.open_run(_goal(goal_id=f"g-{i}")) for i in range(4)]
    tick = _Tick()
    result = await _runtime(ledger, tick, clock).sweep()
    assert len(tick.calls) == 1
    at_capacity = [rid for rid, reason in result.skipped.items() if reason == "at_capacity"]
    assert len(at_capacity) == 3
    assert set(at_capacity) | set(tick.calls) == {r.id for r in runs}


async def test_max_concurrent_lets_more_through_when_asked(ledger, clock):
    for i in range(4):
        ledger.open_run(_goal(goal_id=f"g-{i}"))
    tick = _Tick()
    runtime = _runtime(
        ledger, tick, clock,
        config=ScheduleConfig(enabled=True, interval_seconds=300.0, max_concurrent=3),
    )
    await runtime.sweep()
    assert len(tick.calls) == 3


# ── night is quiet for attention, not for work ───────────────────────────────

def test_the_night_window_wraps_past_midnight():
    assert is_night(23, start=23, end=6) is True
    assert is_night(3, start=23, end=6) is True
    assert is_night(6, start=23, end=6) is False
    assert is_night(12, start=23, end=6) is False
    # a daytime window does not wrap
    assert is_night(10, start=9, end=17) is True
    assert is_night(20, start=9, end=17) is False
    # an empty window is never night
    assert is_night(5, start=5, end=5) is False


async def test_work_continues_at_night_and_only_interruptions_wait(ledger, clock):
    run = ledger.open_run(_goal())
    tick = _Tick()
    runtime = _runtime(ledger, tick, clock, hour=3)
    result = await runtime.sweep()
    assert tick.calls == [run.id]           # the work happened
    assert runtime.quiet_hours() is True
    assert runtime.interruptions_allowed() is False
    assert result.ticked == (run.id,)


async def test_daytime_allows_interruptions(ledger, clock):
    ledger.open_run(_goal())
    runtime = _runtime(ledger, _Tick(), clock, hour=12)
    assert runtime.quiet_hours() is False
    assert runtime.interruptions_allowed() is True


# ── failures are reported, never retried here ────────────────────────────────

async def test_a_failed_tick_is_recorded_and_not_retried(ledger, clock):
    """A scheduler with its own retry loop would multiply the supervisor's
    failure budget behind its back."""
    run = ledger.open_run(_goal())
    tick = _Tick(raises=RuntimeError("supervisor blew up"))
    runtime = _runtime(ledger, tick, clock)
    result = await runtime.sweep()
    assert tick.calls == [run.id]
    assert result.entries[0].reason == "tick_failed"
    assert result.entries[0].outcome == "RuntimeError"
    # and it is not due again until the interval elapses, exactly like a success
    clock.advance(60)
    await runtime.sweep()
    assert tick.calls == [run.id]


async def test_a_ledger_that_cannot_list_runs_sweeps_nothing_rather_than_raising(
    ledger, clock, monkeypatch
):
    monkeypatch.setattr(ledger, "list_runs", lambda **_kw: (_ for _ in ()).throw(OSError()))
    result = await _runtime(ledger, _Tick(), clock).sweep()
    assert result.entries == ()


# ── observability ────────────────────────────────────────────────────────────

async def test_the_snapshot_says_what_is_due_and_what_is_waiting_and_why(ledger, clock):
    due = ledger.open_run(_goal(goal_id="due"))
    blocked = ledger.open_run(_goal(goal_id="blocked"))
    ledger.record_step(blocked.id, kind="ask", summary="waiting",
                       outcome="queued", task_id=1)
    snap = _runtime(ledger, _Tick(), clock, hour=3).snapshot()
    assert snap["enabled"] is True
    assert snap["open_runs"] == 2
    assert snap["due"] == [due.id]
    assert snap["waiting"] == {blocked.id: "blocked"}
    assert snap["quiet_hours"] is True
    assert snap["night_window"] == [23, 6]


def test_sweep_summary_rolls_several_sweeps_into_counts():
    from agents.core.autonomy.schedule_runtime import SweepEntry, SweepResult

    a = SweepResult((SweepEntry("r1", True), SweepEntry("r2", False, "blocked")), 1.0)
    b = SweepResult((SweepEntry("r1", False, "not_due"), SweepEntry("r2", False, "blocked")), 2.0)
    assert sweep_summary([a, b]) == {
        "sweeps": 2, "ticked": 1, "skipped": {"blocked": 2, "not_due": 1},
    }


# ── construction ─────────────────────────────────────────────────────────────

def test_a_nonsense_config_is_refused_at_construction():
    for kwargs in (
        {"interval_seconds": 0},
        {"max_concurrent": 0},
        {"night_start": 24},
        {"night_end": -1},
    ):
        with pytest.raises(ValueError):
            ScheduleConfig(enabled=True, **kwargs)


# ── with the whole chain ─────────────────────────────────────────────────────

async def test_the_scheduler_drives_a_real_supervisor_to_a_blocked_run(ledger, clock):
    """End to end: the scheduler wakes the run, the supervisor queues one step for
    approval, and the next sweep leaves the now-blocked run alone."""
    from agents.core.autonomy.company_planner import ChecklistPlanner, PlanStep
    from agents.core.autonomy.company_supervisor import (
        CompanySupervisor,
        SupervisorConfig,
    )

    run = ledger.open_run(_goal())
    planner = ChecklistPlanner(
        [PlanStep(kind="research", summary="read the numbers", task={"agent": "jarvis"})],
        scope_kinds=frozenset({"research"}), ledger=ledger,
    )
    sup = CompanySupervisor(
        ledger, enqueue=lambda **_kw: 101, plan_next=planner,
        config=SupervisorConfig(enabled=True),
    )
    runtime = ScheduleRuntime(
        ledger, tick=sup.tick, config=ON, clock=clock, local_hour=lambda: 12
    )

    first = await runtime.sweep()
    assert first.entries[0].outcome == "stepped"
    assert ledger.get(run.id).status == "blocked"

    clock.advance(301)
    second = await runtime.sweep()
    assert second.skipped == {run.id: "blocked"}
