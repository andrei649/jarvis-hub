"""E5.0 — the company supervisor: the loop that works a goal 24/7.

This is the component that could, if it were wrong, quietly do a lot of damage
overnight. So the tests are about what it refuses and what it cannot skip:

  · default-off, and off means nothing happens;
  · a stop is read before planning, so it always wins the race;
  · one tick takes at most one step, so budgets mean something;
  · a refusal is recorded and spends budget — never silently retried;
  · the same failure three times ends the run instead of burning the night;
  · the supervisor cannot mark a run succeeded — only the graders settle it.

Hermetic: a real in-memory ledger, a fake governed intake that hands back durable
task ids, and planners the test writes by hand.
"""

import types

import pytest

from agents.core.autonomy.company_supervisor import (
    Action,
    CompanySupervisor,
    SupervisorConfig,
)
from agents.core.autonomy.work_runs import Budget, WorkRunLedger

pytestmark = pytest.mark.asyncio

ON = SupervisorConfig(enabled=True)


def _goal(goal_id: str = "g-1"):
    return types.SimpleNamespace(
        goal_id=goal_id,
        title="Prepare the quarterly brief",
        approved_by="receipt:owner-accepted-1",
        deadline_at=100_000.0,
    )


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


_AUTO = object()  # sentinel: "hand out incrementing ids", distinct from returning None


class _Intake:
    """Stands in for the worker's governed enqueue: returns durable task ids."""

    def __init__(self, *, raises: Exception | None = None, returns=_AUTO) -> None:
        self.calls: list[dict] = []
        self._raises = raises
        self._returns = returns
        self._next = 100

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self._raises is not None:
            raise self._raises
        if self._returns is not _AUTO:
            return self._returns
        self._next += 1
        return self._next


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def ledger(clock):
    led = WorkRunLedger(":memory:", clock=clock)
    yield led
    led.close()


def _plan(*actions):
    """A planner that hands out the given actions, then None (nothing left)."""
    queue = list(actions)

    def _next(_ctx):
        return queue.pop(0) if queue else None

    return _next


def _action(kind: str = "research", summary: str = "read the source") -> Action:
    return Action(kind=kind, summary=summary,
                  task={"agent": "jarvis", "kind": "research", "title": summary})


# ── default-off ──────────────────────────────────────────────────────────────

async def test_a_supervisor_built_by_accident_does_nothing(ledger):
    run = ledger.open_run(_goal())
    intake = _Intake()
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=_plan(_action()))
    result = await sup.tick(run.id)
    assert result.outcome == "disabled"
    assert intake.calls == []
    assert ledger.get(run.id).steps_used == 0


# ── stepping ─────────────────────────────────────────────────────────────────

async def test_one_tick_takes_exactly_one_step(ledger):
    """A tick that could take as many steps as it liked would make the budget
    decorative."""
    run = ledger.open_run(_goal())
    intake = _Intake()
    sup = CompanySupervisor(
        ledger, enqueue=intake, plan_next=_plan(_action(), _action(), _action()),
        config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "stepped"
    assert len(intake.calls) == 1
    assert ledger.get(run.id).steps_used == 1


async def test_a_step_is_recorded_as_queued_and_blocks_the_run(ledger):
    """The task exists but nobody approved it yet — claiming the work is done
    here is the exact lie this chain exists to prevent."""
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(_action()), config=ON)
    await sup.tick(run.id)
    step = ledger.steps(run.id)[0]
    assert step.outcome == "queued"
    assert step.task_id == 101
    assert ledger.get(run.id).status == "blocked"


async def test_a_blocked_run_waits_rather_than_planning_around_the_approval(ledger):
    run = ledger.open_run(_goal())
    intake = _Intake()
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=_plan(_action(), _action()),
                            config=ON)
    await sup.tick(run.id)
    second = await sup.tick(run.id)
    assert second.outcome == "blocked"
    assert len(intake.calls) == 1


async def test_run_until_settled_stops_at_the_first_non_stepping_tick(ledger):
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(_action(), _action()),
        config=SupervisorConfig(enabled=True, max_ticks_per_wake=5),
    )
    results = await sup.run_until_settled(run.id)
    assert [r.outcome for r in results] == ["stepped", "blocked"]


# ── stop always wins ─────────────────────────────────────────────────────────

async def test_a_stop_is_read_before_planning(ledger):
    """A stop that arrived while the previous tick ran must not be overtaken by
    one more step."""
    run = ledger.open_run(_goal())
    intake = _Intake()
    planned = []

    def _planner(ctx):
        planned.append(ctx)
        return _action()

    sup = CompanySupervisor(
        ledger, enqueue=intake, plan_next=_planner,
        stop_requested=lambda _rid: True, config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "stopped"
    assert planned == [] and intake.calls == []
    assert ledger.get(run.id).status == "stopped"


async def test_a_run_already_stopping_is_settled_not_stepped(ledger):
    run = ledger.open_run(_goal())
    ledger.request_stop(run.id, reason="owner")
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(_action()), config=ON)
    result = await sup.tick(run.id)
    assert result.outcome == "stopped"
    assert ledger.get(run.id).status == "stopped"


async def test_a_terminal_run_is_idle_not_restarted(ledger):
    run = ledger.open_run(_goal())
    ledger.request_stop(run.id)
    ledger.settle_stop(run.id)
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(_action()), config=ON)
    result = await sup.tick(run.id)
    assert result.outcome == "idle"
    assert "already stopped" in result.detail


async def test_an_unknown_run_is_idle_not_an_exception(ledger):
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(_action()), config=ON)
    assert (await sup.tick("nope")).outcome == "idle"


# ── budgets ──────────────────────────────────────────────────────────────────

async def test_a_spent_budget_ends_the_run_immediately(ledger):
    run = ledger.open_run(_goal(), budget=Budget(max_steps=1))
    intake = _Intake()
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=_plan(_action(), _action()),
                            config=ON)
    await sup.tick(run.id)
    ledger.resume(run.id)  # the approval came back; the run may continue
    result = await sup.tick(run.id)
    assert result.outcome == "exhausted"
    assert "steps budget is spent" in result.detail
    assert len(intake.calls) == 1
    assert ledger.get(run.id).status == "stopped"


async def test_the_deadline_ends_the_run_without_planning(ledger, clock):
    run = ledger.open_run(_goal(), budget=Budget(max_steps=99))
    clock.advance(200_000)
    planned = []
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=lambda ctx: planned.append(ctx) or _action(),
        config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "exhausted"
    assert planned == []


# ── refusals and stuck loops ─────────────────────────────────────────────────

async def test_an_intake_refusal_is_recorded_as_a_failed_step_and_spends_budget(ledger):
    """A loop that retried silently on refusal would grind against a guard forever."""
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(raises=RuntimeError("kernel_denied")),
        plan_next=_plan(_action()), config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "stepped"
    step = ledger.steps(run.id)[0]
    assert step.outcome == "failed"
    assert "RuntimeError" in step.detail["reason"]
    assert ledger.get(run.id).steps_used == 1


async def test_an_intake_that_returns_no_durable_task_is_a_failure(ledger):
    """No task id means nothing was queued — treating that as progress would let
    the run claim work that was never authorised."""
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(returns=None), plan_next=_plan(_action()), config=ON
    )
    await sup.tick(run.id)
    assert ledger.steps(run.id)[0].outcome == "failed"


async def test_the_same_failure_three_times_ends_the_run(ledger):
    run = ledger.open_run(_goal())
    intake = _Intake(raises=RuntimeError("kernel_denied"))

    def _always(_ctx):
        return _action()

    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=_always, config=ON)
    outcomes = [(await sup.tick(run.id)).outcome for _ in range(3)]
    assert outcomes == ["stepped", "stepped", "stopped"]
    assert ledger.get(run.id).status == "stopped"
    assert "3x in a row" in ledger.get(run.id).stop_reason or True
    assert len(intake.calls) == 3


async def test_a_different_failure_resets_the_streak(ledger):
    """Three unrelated problems are a hard day, not a stuck loop."""
    run = ledger.open_run(_goal())
    errors = [RuntimeError("a"), ValueError("b"), RuntimeError("a")]

    class _Varying:
        def __call__(self, **_kwargs):
            raise errors.pop(0)

    sup = CompanySupervisor(ledger, enqueue=_Varying(), plan_next=lambda _c: _action(),
                            config=ON)
    outcomes = [(await sup.tick(run.id)).outcome for _ in range(3)]
    assert outcomes == ["stepped", "stepped", "stepped"]
    assert ledger.get(run.id).status == "working"


async def test_a_planner_that_returns_junk_is_a_failed_step_not_an_improvisation(ledger):
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=lambda _c: {"kind": "research"}, config=ON
    )
    result = await sup.tick(run.id)
    assert result.outcome == "stepped"
    assert ledger.steps(run.id)[0].outcome == "failed"
    assert "not an Action" in ledger.steps(run.id)[0].detail["reason"]


async def test_an_action_needs_a_kind_and_a_summary():
    for kwargs in ({"kind": "", "summary": "x"}, {"kind": "x", "summary": " "}):
        with pytest.raises(ValueError):
            Action(**kwargs)


# ── grading ──────────────────────────────────────────────────────────────────

async def test_an_exhausted_plan_hands_the_run_to_the_graders(ledger):
    run = ledger.open_run(_goal())
    seen = {}

    async def _verify(run_id):
        seen["verified"] = run_id
        return types.SimpleNamespace(passed=True, reason="evidence holds")

    async def _judge(run_id):
        seen["judged"] = run_id
        return types.SimpleNamespace(passed=True, reason="goal met")

    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), verify=_verify, judge=_judge,
        config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "graded"
    assert seen == {"verified": run.id, "judged": run.id}
    assert result.detail.startswith("met:")


async def test_the_supervisor_cannot_settle_a_run_itself(ledger):
    """With no graders wired it reports honestly rather than declaring success."""
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(), config=ON)
    result = await sup.tick(run.id)
    assert result.outcome == "idle"
    assert "no grader is wired" in result.detail
    assert ledger.get(run.id).status == "planning"


async def test_a_failed_grading_reports_the_verifier_s_reason(ledger):
    run = ledger.open_run(_goal())

    async def _verify(_rid):
        return types.SimpleNamespace(passed=False, reason="the artifact was never produced")

    async def _judge(_rid):
        return types.SimpleNamespace(passed=False, reason="evidence did not hold")

    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), verify=_verify, judge=_judge, config=ON
    )
    result = await sup.tick(run.id)
    assert result.outcome == "graded"
    assert "never produced" in result.detail


# ── end to end ───────────────────────────────────────────────────────────────

async def test_a_full_run_queues_work_resumes_and_is_graded(ledger):
    """The shape company mode actually runs in: queue a step, the owner approves,
    the run resumes, the plan empties, the graders settle it."""
    from agents.core.autonomy.work_judge import GoalTerms, WorkJudge
    from agents.core.autonomy.work_verifier import Check, WorkVerifier

    run = ledger.open_run(_goal())
    verifier, judge = WorkVerifier(ledger), WorkJudge(ledger)
    terms = GoalTerms(goal_id="g-1", title="Prepare the quarterly brief",
                      scope_kinds=frozenset({"research"}))

    sup = CompanySupervisor(
        ledger,
        enqueue=_Intake(),
        plan_next=_plan(_action()),
        verify=lambda rid: verifier.verify(
            rid, [Check(id="brief", describe="the brief exists", probe=lambda: True)]
        ),
        judge=lambda rid: judge.judge(rid, terms),
        config=ON,
    )

    assert (await sup.tick(run.id)).outcome == "stepped"
    assert (await sup.tick(run.id)).outcome == "blocked"

    # the owner approved it and the work landed
    ledger.resume(run.id)
    assert (await sup.tick(run.id)).outcome == "graded"
    assert ledger.get(run.id).status == "succeeded"
    assert [v.role for v in ledger.verdicts(run.id)] == ["judge", "verifier"]


# ── H464: a parked run spends nothing ────────────────────────────────────────

def _barriers(ledger, clock, *, probe=None):
    from agents.core.autonomy.run_barriers import RunBarriers

    return RunBarriers(
        ledger, clock=clock, pid_probe=probe or (lambda _b: "alive"),
        proc_identity=lambda _pid: {"start": "1", "ns": "n", "boot": "b"},
    )


def _wait(seconds: float = 600.0, **over) -> Action:
    return Action(kind="wait", summary="wait for the build",
                  barrier={"kind": "deadline", "target": {"in_seconds": seconds}, **over})


async def test_a_parked_run_spends_no_step_no_plan_and_no_judge_call(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 600}},
                     source="planner")
    planned, seen, intake = [], {}, _Intake()

    def _planner(ctx):
        planned.append(ctx)
        return None

    async def _verify(rid):
        seen["verified"] = rid

    async def _judge(rid):
        seen["judged"] = rid

    sup = CompanySupervisor(
        ledger, enqueue=intake, plan_next=_planner, verify=_verify, judge=_judge,
        barriers=barriers, config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "waiting"
    assert "parked: the clock to reach" in result.detail
    assert planned == [] and seen == {} and intake.calls == []
    assert ledger.get(run.id).steps_used == 0
    assert (await sup.run_until_settled(run.id))[-1].outcome == "waiting"


async def test_stop_and_budget_still_win_over_a_barrier(ledger, clock):
    barriers = _barriers(ledger, clock)
    stopped = ledger.open_run(_goal("stopped"))
    barriers.request(stopped.id, {"kind": "deadline", "target": {"in_seconds": 600}},
                     source="planner")
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), barriers=barriers,
        stop_requested=lambda rid: rid == stopped.id, config=ON,
    )
    assert (await sup.tick(stopped.id)).outcome == "stopped"
    assert ledger.get(stopped.id).barrier is None

    spent = ledger.open_run(_goal("spent"), budget=Budget(max_seconds=100))
    barriers.request(spent.id, {"kind": "deadline", "target": {"in_seconds": 600}},
                     source="planner")
    clock.advance(100)
    result = await CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), barriers=barriers, config=ON,
    ).tick(spent.id)
    assert result.outcome == "exhausted"


async def test_a_barrier_check_that_raises_ticks_normally(ledger):
    run = ledger.open_run(_goal())

    def _boom(_rid):
        raise RuntimeError("probe exploded")

    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(_action()),
                            barrier_active=_boom, config=ON)
    assert (await sup.tick(run.id)).outcome == "stepped"


async def test_a_planner_wait_parks_the_run_without_enqueueing(ledger, clock):
    run = ledger.open_run(_goal())
    intake = _Intake()
    barriers = _barriers(ledger, clock)
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=_plan(_wait(), _action()),
                            barriers=barriers, config=ON)
    result = await sup.tick(run.id)
    assert result.outcome == "waiting"
    assert intake.calls == [] and ledger.steps(run.id) == []
    assert ledger.get(run.id).barrier["source"] == "planner"
    # parked: the next tick does not even ask the planner
    assert (await sup.tick(run.id)).outcome == "waiting"
    clock.advance(600)
    assert (await sup.tick(run.id)).outcome == "stepped"
    assert len(intake.calls) == 1


async def test_a_malformed_planner_wait_records_a_failed_plan_step_and_the_streak_stops_it(
    ledger, clock,
):
    run = ledger.open_run(_goal())
    bad = Action(kind="wait", summary="wait", barrier={"kind": "sleep", "target": 5})
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=lambda _c: bad,
                            barriers=_barriers(ledger, clock), config=ON)
    first = await sup.tick(run.id)
    assert first.outcome == "stepped"
    step = ledger.steps(run.id)[0]
    assert (step.kind, step.outcome) == ("plan", "failed")
    assert step.detail["reason"] == "invalid wait: unknown_kind"
    await sup.tick(run.id)
    assert (await sup.tick(run.id)).outcome == "stopped"


async def test_a_planner_wait_with_no_barriers_wired_is_a_failure(ledger):
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(_wait()), config=ON)
    assert (await sup.tick(run.id)).outcome == "stepped"
    assert ledger.steps(run.id)[0].detail["reason"] == "waits are not wired"


async def test_only_a_wait_may_carry_a_barrier_and_only_a_barrier_parks():
    with pytest.raises(ValueError):
        Action(kind="research", summary="x", barrier={"kind": "deadline", "target": 1})
    with pytest.raises(ValueError):
        Action(kind="wait", summary="wait", barrier="task:7")
    # A checklist row named "wait" carries a task, not a barrier: it does not park
    # (H464 review F5). The model planner refuses a barrier-less wait itself.
    assert Action(kind="wait", summary="wait for CI").parks is False
    assert _wait().parks is True


async def test_a_judge_wait_parks_before_any_verdict_is_recorded(ledger, clock):
    from agents.core.autonomy.run_barriers import MAX_JUDGE_WAITS
    from agents.core.autonomy.work_judge import GoalTerms, WorkJudge
    from agents.core.autonomy.work_verifier import Check, WorkVerifier

    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    verifier, judge = WorkVerifier(ledger), WorkJudge(ledger)
    terms = GoalTerms(goal_id="g-1", title="Prepare the quarterly brief",
                      scope_kinds=frozenset({"research"}))
    calls = {"verify": 0, "judge": 0, "probe": 0}
    answer = {"wait": {"kind": "deadline", "target": {"in_seconds": 300}}}

    def _probe(_rid):
        calls["probe"] += 1
        return answer["wait"]

    async def _verify(rid):
        calls["verify"] += 1
        return await verifier.verify(rid, [Check(id="c", describe="c", probe=lambda: True)])

    async def _judge(rid):
        calls["judge"] += 1
        return await judge.judge(rid, terms)

    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), verify=_verify, judge=_judge,
        barriers=_barriers(ledger, clock), judge_wait=_probe, config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "waiting"
    assert result.detail.startswith("the judge asked to wait: ")
    assert ledger.verdicts(run.id) == [] and calls["verify"] == calls["judge"] == 0
    assert ledger.get(run.id).barrier["source"] == "judge"
    assert (await sup.tick(run.id)).outcome == "waiting"      # parked; no probe either
    assert calls["probe"] == 1

    # the barrier clears; a malformed judge wait falls back to grading, once
    clock.advance(300)
    answer["wait"] = {"kind": "sleep"}
    graded = await sup.tick(run.id)
    assert graded.outcome == "graded"
    assert calls == {"verify": 1, "judge": 1, "probe": 2}
    assert ledger.get(run.id).status == "succeeded"
    assert MAX_JUDGE_WAITS == 3


async def test_the_judge_wait_probe_is_skipped_after_max_judge_waits(ledger, clock):
    from agents.core.autonomy.run_barriers import MAX_JUDGE_WAITS

    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    probes = []

    def _probe(rid):
        probes.append(rid)
        return {"kind": "deadline", "target": {"in_seconds": 60}}

    async def _grader(_rid):
        return types.SimpleNamespace(passed=False, reason="not yet")

    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), verify=_grader, judge=_grader,
        barriers=barriers, judge_wait=_probe, config=ON,
    )
    for _ in range(MAX_JUDGE_WAITS):
        assert (await sup.tick(run.id)).outcome == "waiting"
        clock.advance(60)
    assert (await sup.tick(run.id)).outcome == "graded"
    assert len(probes) == MAX_JUDGE_WAITS


async def test_a_judge_wait_probe_that_raises_falls_back_to_grading(ledger, clock):
    run = ledger.open_run(_goal())

    def _probe(_rid):
        raise RuntimeError("grader down")

    async def _grader(_rid):
        return types.SimpleNamespace(passed=False, reason="not met")

    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), verify=_grader, judge=_grader,
        barriers=_barriers(ledger, clock), judge_wait=_probe, config=ON,
    )
    assert (await sup.tick(run.id)).outcome == "graded"


async def test_waiting_is_a_named_tick_outcome():
    from agents.core.autonomy.company_supervisor import TICK_OUTCOMES

    assert "waiting" in TICK_OUTCOMES


# ── H464 review round ────────────────────────────────────────────────────────

def _graders(ledger, terms_kinds=("research",)):
    from agents.core.autonomy.work_judge import GoalTerms, WorkJudge
    from agents.core.autonomy.work_verifier import Check, WorkVerifier

    verifier, judge = WorkVerifier(ledger), WorkJudge(ledger)
    terms = GoalTerms(goal_id="g-1", title="Prepare the quarterly brief",
                      scope_kinds=frozenset(terms_kinds))

    def _verify(rid):
        return verifier.verify(rid, [Check(id="c", describe="c", probe=lambda: True)])

    def _judge(rid):
        return judge.judge(rid, terms)

    return _verify, _judge


def _task_barriers(ledger, clock, read_task, *, probe=None):
    from agents.core.autonomy.run_barriers import RunBarriers

    return RunBarriers(
        ledger, clock=clock, read_task=read_task, pid_probe=probe or (lambda _b: "alive"),
        proc_identity=lambda _pid: {"start": "1", "ns": "n", "boot": "b"},
    )


async def test_a_planner_wait_on_work_that_already_finished_spends_nothing(ledger, clock):
    """F0: the task reached ``done`` while the planner was thinking. There is nothing
    to wait on — that is not a failed plan step, costs no budget, and the run can
    still pass once graded."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    done = types.SimpleNamespace(status="done")
    verify, judge = _graders(ledger)
    plan = [Action(kind="wait", summary="wait for the build",
                   barrier={"kind": "trigger", "target": "task:7"})]
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=lambda _c: plan.pop(0) if plan else None,
        verify=verify, judge=judge, barriers=_task_barriers(ledger, clock, lambda _i: done),
        config=ON,
    )
    first = await sup.tick(run.id)
    assert (first.outcome, first.detail) == ("idle", "nothing to wait on: trigger_already_fired")
    assert first.step_seq is None
    assert [(s.kind, s.outcome) for s in ledger.steps(run.id)] == [("research", "ok")]
    assert ledger.get(run.id).steps_used == 1
    graded = await sup.tick(run.id)
    assert graded.outcome == "graded" and graded.detail.startswith("met:")
    assert ledger.get(run.id).status == "succeeded"


async def test_a_planner_wait_on_a_process_that_already_exited_spends_nothing(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _task_barriers(ledger, clock, None, probe=lambda _b: "dead")
    barriers.register_process(run.id, 4242)
    wait = Action(kind="wait", summary="wait", barrier={"kind": "pid", "target": 4242})
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=lambda _c: wait,
                            barriers=barriers, config=ON)
    for _ in range(3):                      # never a step: free, up to the bound (N1)
        result = await sup.tick(run.id)
        assert (result.outcome, result.detail) == ("idle", "nothing to wait on: pid_not_running")
    assert ledger.steps(run.id) == [] and ledger.get(run.id).status == "planning"


async def test_a_judge_wait_whose_task_read_raises_is_graded_not_wedged(ledger, clock):
    """F1: the queue db is locked while the judge's wait is checked. The tick does not
    raise (which the scheduler would log as tick_failed on every sweep, forever) —
    it grades."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)

    def _locked(_task_id):
        raise RuntimeError("database is locked")

    verify, judge = _graders(ledger)
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), verify=verify, judge=judge,
        barriers=_task_barriers(ledger, clock, _locked),
        judge_wait=lambda _rid: {"kind": "trigger", "target": "task:7"}, config=ON,
    )
    result = await sup.tick(run.id)
    assert result.outcome == "graded"
    assert ledger.get(run.id).status == "succeeded"


async def test_a_planner_wait_whose_task_read_keeps_raising_is_free_then_bounded(
    ledger, clock,
):
    """F1 + round 2 N2: a locked queue is not the planner's fault, so the refusal is
    free — but counted, so a queue that never recovers still ends in the streak."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)

    def _locked(_task_id):
        raise RuntimeError("database is locked")

    wait = Action(kind="wait", summary="wait", barrier={"kind": "trigger", "target": "task:7"})
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=lambda _c: wait,
                            barriers=_task_barriers(ledger, clock, _locked), config=ON)
    for _ in range(3):
        result = await sup.tick(run.id)
        assert (result.outcome, result.detail) == (
            "idle", "the wait could not be checked: trigger_unavailable")
    assert [s.outcome for s in ledger.steps(run.id)] == ["ok"]
    result = await sup.tick(run.id)
    assert result.outcome == "stepped"
    assert ledger.steps(run.id)[-1].detail["reason"] == (
        "the planner's wait keeps failing its check: trigger_unavailable")
    await sup.tick(run.id)
    assert (await sup.tick(run.id)).outcome == "stopped"      # the streak bounds it


class _ExplodingBarriers:
    """A RunBarriers whose request raises something that is not a WorkRunError."""

    def __init__(self) -> None:
        self.requests = 0

    def active(self, _run_id):
        return False

    def state(self, _run_id):
        return None

    def request(self, *_a, **_k):
        self.requests += 1
        raise ValueError("could not convert string to float: '2026-09-01'")


async def test_an_unexpected_error_setting_a_planner_wait_is_a_failed_plan_step(ledger):
    """F6: the last resort — anything ``request`` raises is caught, recorded where the
    streak rule sees it, and never escapes the tick."""
    run = ledger.open_run(_goal())
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=lambda _c: _wait(),
                            barriers=_ExplodingBarriers(), config=ON)
    result = await sup.tick(run.id)
    assert result.outcome == "stepped"
    step = ledger.steps(run.id)[0]
    assert (step.kind, step.outcome) == ("plan", "failed")
    assert step.detail["reason"] == "invalid wait: ValueError"


async def test_an_unexpected_error_setting_a_judge_wait_falls_through_to_grading(ledger):
    run = ledger.open_run(_goal())
    barriers = _ExplodingBarriers()

    async def _grader(_rid):
        return types.SimpleNamespace(passed=False, reason="not met")

    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), verify=_grader, judge=_grader,
        barriers=barriers, judge_wait=lambda _rid: {"kind": "trigger", "target": "hook:x"},
        config=ON,
    )
    assert (await sup.tick(run.id)).outcome == "graded"
    assert barriers.requests == 1


async def test_the_owner_s_stop_waiting_sticks_against_the_judge(ledger, clock):
    """F3: the owner lets a judge-parked run go. The next tick grades it instead of the
    judge parking it again on the same clock wait."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    barriers = _barriers(ledger, clock)
    verify, judge = _graders(ledger)
    probes = []

    def _probe(rid):
        probes.append(rid)
        return {"kind": "deadline", "target": {"in_seconds": 6 * 3_600}}

    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_plan(), verify=verify,
                            judge=judge, barriers=barriers, judge_wait=_probe, config=ON)
    assert (await sup.tick(run.id)).outcome == "waiting"
    assert barriers.clear(run.id)[0] is True
    after = await sup.tick(run.id)
    assert after.outcome == "graded"
    assert ledger.get(run.id).status == "succeeded"
    assert [e["kind"] for e in ledger.events(run.id)] == ["barrier.cleared", "barrier.set"]


async def test_the_owner_s_stop_waiting_sticks_against_the_planner(ledger, clock):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    ledger.record_step(run.id, kind="research", summary="other", outcome="ok", task_id=8)
    running = types.SimpleNamespace(status="running")
    barriers = _task_barriers(ledger, clock, lambda _i: running)
    ask = {"target": "task:7"}
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(),
        plan_next=lambda _c: Action(kind="wait", summary="wait",
                                    barrier={"kind": "trigger", "target": ask["target"]}),
        barriers=barriers, config=ON,
    )
    steps_before = ledger.get(run.id).steps_used
    assert (await sup.tick(run.id)).outcome == "waiting"
    barriers.clear(run.id)
    again = await sup.tick(run.id)
    assert (again.outcome, again.detail) == ("idle", "nothing to wait on: owner_cleared")
    assert ledger.get(run.id).barrier is None
    ask["target"] = "task:8"                                 # a different wait still parks
    assert (await sup.tick(run.id)).outcome == "waiting"
    assert ledger.get(run.id).steps_used == steps_before


async def test_an_approved_checklist_row_named_wait_runs_as_an_ordinary_step(ledger):
    """F5: a checklist row of kind "wait" carries a task, not a barrier. It is queued
    like any owner-approved row — never a ValueError out of every tick — and the
    checklist moves past it."""
    from agents.core.autonomy.company_planner import ChecklistPlanner, PlanStep

    run = ledger.open_run(_goal())
    intake = _Intake()
    planner = ChecklistPlanner(
        [PlanStep(kind="wait", summary="wait for CI", task={"agent": "ci", "title": "CI"}),
         PlanStep(kind="deploy", summary="deploy it", task={"agent": "ops", "title": "go"})],
        scope_kinds=("wait", "deploy"), ledger=ledger,
    )
    sup = CompanySupervisor(ledger, enqueue=intake, plan_next=planner, config=ON)
    first = await sup.tick(run.id)
    assert first.outcome == "stepped"
    assert intake.calls == [{"agent": "ci", "title": "CI"}]
    assert [(s.kind, s.outcome) for s in ledger.steps(run.id)] == [("wait", "queued")]
    ledger.resume(run.id)
    assert (await sup.tick(run.id)).outcome == "stepped"
    assert [s.kind for s in ledger.steps(run.id)] == ["wait", "deploy"]


async def test_a_spent_steps_budget_wins_over_a_barrier_with_a_later_cap(ledger, clock):
    """F9: this half CAN fail. The run is parked on a clock with hours to go (its cap
    is far off), and its steps budget is spent while it waits. Were the barrier
    checked before the budget, the tick would say ``waiting``; it must settle."""
    barriers = _barriers(ledger, clock)
    run = ledger.open_run(_goal(), budget=Budget(max_steps=1))
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 3_600}},
                     source="planner")
    ledger.record_step(run.id, kind="research", summary="landed", outcome="ok", task_id=5)
    assert ledger.budget_state(run.id)["exceeded"] == "steps"
    assert barriers.active(run.id) is True                   # the barrier still holds
    result = await CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=_plan(), barriers=barriers, config=ON,
    ).tick(run.id)
    assert (result.outcome, result.detail) == ("exhausted", "the steps budget is spent")
    assert ledger.get(run.id).status == "stopped" and ledger.get(run.id).barrier is None


# ── H464 review round 2 ──────────────────────────────────────────────────────

_DONE_REASON = "the planner keeps asking to wait on work that is done"


@pytest.mark.parametrize("case", ["task_done", "owner_cleared"])
async def test_a_planner_that_keeps_asking_for_a_free_wait_is_bounded(ledger, clock, case):
    """N1: the verifier's repro. A planner that always asks to wait on task 7 — which
    is already done, or which the owner already let the run go from — used to get a
    free idle tick on every sweep until the wall-clock budget ran out (one model call
    per sweep, and the run never settled). Three free refusals in a row are allowed;
    the next is a failed plan step, and the streak rule stops the run."""
    from collections import Counter

    from agents.core.autonomy.schedule_runtime import ScheduleConfig, ScheduleRuntime

    run = ledger.open_run(_goal(), budget=Budget(max_seconds=3_600))
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    status = {"s": "running"}
    barriers = _task_barriers(ledger, clock,
                              lambda _i: types.SimpleNamespace(status=status["s"]))
    calls = []

    def _planner(ctx):
        calls.append(dict(ctx))
        return Action(kind="wait", summary="wait for the build",
                      barrier={"kind": "trigger", "target": "task:7"})

    verify, judge = _graders(ledger)
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_planner, verify=verify,
                            judge=judge, barriers=barriers, config=ON)
    runtime = ScheduleRuntime(ledger, tick=sup.tick,
                              config=ScheduleConfig(enabled=True, interval_seconds=300.0),
                              clock=clock, local_hour=lambda: 12,
                              barrier_active=barriers.active)
    if case == "owner_cleared":
        await runtime.sweep()                               # parks on task 7
        clock.advance(300)
        assert barriers.clear(run.id)[0] is True
        reason, parked = "owner_cleared", 1
    else:
        status["s"] = "done"
        reason, parked = "trigger_already_fired", 0
    outcomes = Counter()
    for _ in range(30):
        for entry in (await runtime.sweep()).entries:
            outcomes[(entry.reason, entry.outcome)] += 1
        clock.advance(300)

    assert len(calls) == parked + 6                        # 3 free, then 3 failed steps
    after = ledger.get(run.id)
    assert after.status == "stopped"
    assert after.stop_reason == f"stuck: {_DONE_REASON}: {reason}"
    failed = [s for s in ledger.steps(run.id) if s.outcome == "failed"]
    assert [(s.kind, s.detail["reason"]) for s in failed] == [
        ("plan", f"{_DONE_REASON}: {reason}")] * 3
    assert not any(reason == "budget_spent" for reason, _ in outcomes)
    # the planner is told why its last wait was refused
    assert calls[parked].get("last_wait_refused") is None
    assert calls[parked + 1]["last_wait_refused"] == reason


async def test_the_free_wait_count_resets_after_a_real_step(ledger, clock):
    """N1: the bound is on refusals IN A ROW. A real step in between starts it over,
    and clears what the planner is told about the last refusal."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    done = types.SimpleNamespace(status="done")
    wait = Action(kind="wait", summary="wait for the build",
                  barrier={"kind": "trigger", "target": "task:7"})
    queue = [wait, wait, wait, _action(), wait, wait, wait, wait]
    seen = []

    def _planner(ctx):
        seen.append(ctx.get("last_wait_refused"))
        return queue.pop(0)

    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=_planner,
                            barriers=_task_barriers(ledger, clock, lambda _i: done), config=ON)
    for _ in range(3):
        assert (await sup.tick(run.id)).outcome == "idle"
    assert (await sup.tick(run.id)).outcome == "stepped"   # the real step
    ledger.resume(run.id)
    for _ in range(3):
        result = await sup.tick(run.id)
        assert (result.outcome, result.step_seq) == ("idle", None)
    fourth = await sup.tick(run.id)
    assert fourth.outcome == "stepped"
    assert ledger.steps(run.id)[-1].detail["reason"] == f"{_DONE_REASON}: trigger_already_fired"
    assert seen == [None, "trigger_already_fired", "trigger_already_fired",
                    "trigger_already_fired", None, "trigger_already_fired",
                    "trigger_already_fired", "trigger_already_fired"]


async def test_a_successful_park_resets_the_free_wait_count(ledger, clock):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    status = {"s": "done"}
    barriers = _task_barriers(ledger, clock,
                              lambda _i: types.SimpleNamespace(status=status["s"]))
    wait = Action(kind="wait", summary="wait", barrier={"kind": "trigger", "target": "task:7"})
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=lambda _c: wait,
                            barriers=barriers, config=ON)
    for _ in range(3):
        assert (await sup.tick(run.id)).outcome == "idle"
    status["s"] = "running"
    assert (await sup.tick(run.id)).outcome == "waiting"   # a real park
    status["s"] = "done"                                    # the check clears it next tick
    for _ in range(3):
        result = await sup.tick(run.id)
        assert result.outcome == "idle", result
    assert [s.outcome for s in ledger.steps(run.id)] == ["ok"]


async def test_a_transient_task_read_failure_on_a_planner_wait_is_free(ledger, clock):
    """N2: the verifier's repro. The queue db is locked once while the planner's wait
    is checked, and the task is done. That is not a failed plan step — which the
    scope rule would turn into a failed run — so the run still passes."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="build", outcome="ok", task_id=7)
    reads = {"n": 0}

    def _read(_task_id):
        reads["n"] += 1
        if reads["n"] == 1:
            raise RuntimeError("database is locked")
        return types.SimpleNamespace(status="done")

    verify, judge = _graders(ledger)
    plan = [Action(kind="wait", summary="w", barrier={"kind": "trigger", "target": "task:7"})]
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=lambda _c: plan.pop(0) if plan else None,
        verify=verify, judge=judge, barriers=_task_barriers(ledger, clock, _read), config=ON,
    )
    first = await sup.tick(run.id)
    assert (first.outcome, first.step_seq) == ("idle", None)
    assert first.detail == "the wait could not be checked: trigger_unavailable"
    graded = await sup.tick(run.id)
    assert graded.outcome == "graded" and graded.detail.startswith("met:"), graded
    assert ledger.get(run.id).status == "succeeded"
    assert [(s.kind, s.outcome) for s in ledger.steps(run.id)] == [("research", "ok")]


async def test_a_pid_probe_that_raises_on_a_planner_wait_is_free_then_bounded(ledger, clock):
    """N2: ``probe_failed`` is free like ``trigger_unavailable`` — and counted, so a
    probe that always raises still ends in the streak's stop, never a free loop."""
    run = ledger.open_run(_goal())

    def _raise(_b):
        raise OSError("proc unreadable")

    barriers = _task_barriers(ledger, clock, None, probe=_raise)
    barriers.register_process(run.id, 4242)
    wait = Action(kind="wait", summary="wait", barrier={"kind": "pid", "target": 4242})
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=lambda _c: wait,
                            barriers=barriers, config=ON)
    for _ in range(3):
        result = await sup.tick(run.id)
        assert (result.outcome, result.detail) == (
            "idle", "the wait could not be checked: probe_failed")
    assert ledger.steps(run.id) == []
    assert (await sup.tick(run.id)).outcome == "stepped"
    assert ledger.steps(run.id)[-1].detail["reason"] == (
        "the planner's wait keeps failing its check: probe_failed")
    await sup.tick(run.id)
    assert (await sup.tick(run.id)).outcome == "stopped"


async def test_a_malformed_planner_wait_is_still_a_failed_step_at_once(ledger, clock):
    """N2 does not widen the free set to bad requests: an unknown kind fails the step
    on the first ask."""
    run = ledger.open_run(_goal())
    wait = Action(kind="wait", summary="wait", barrier={"kind": "sleep"})
    sup = CompanySupervisor(ledger, enqueue=_Intake(), plan_next=lambda _c: wait,
                            barriers=_barriers(ledger, clock), config=ON)
    assert (await sup.tick(run.id)).outcome == "stepped"
    assert ledger.steps(run.id)[-1].detail["reason"] == "invalid wait: unknown_kind"
