"""E5.0 — the company planner: the one place a model gets to propose.

Everything else in the chain refuses; this is the component that suggests. That
makes its clamps the interesting part, and they are all tested here as refusals
of untrusted input:

  · a proposal outside the goal's scope never becomes a step;
  · a repeat of work already done is refused, because looping while looking busy
    is the classic failure of a long-running agent;
  · a proposer that crashes, times out or answers junk proposes NOTHING — which
    the supervisor reads as "out of ideas", not as "finished";
  · with no step budget left the planner stops proposing rather than feeding the
    ledger refusals.

The checklist planner gets the same treatment: a hand-written list is not more
trusted than a model for having been typed by a person.
"""

import types

import pytest

from agents.core.autonomy.company_planner import (
    ChecklistPlanner,
    ModelPlanner,
    PlanStep,
)
from agents.core.autonomy.company_supervisor import Action
from agents.core.autonomy.work_runs import WorkRunLedger

pytestmark = pytest.mark.asyncio

SCOPE = frozenset({"research", "write"})


def _goal(goal_id: str = "g-1"):
    return types.SimpleNamespace(
        goal_id=goal_id,
        title="Prepare the quarterly brief",
        approved_by="receipt:owner-accepted-1",
        deadline_at=100_000.0,
    )


@pytest.fixture
def ledger():
    led = WorkRunLedger(":memory:", clock=lambda: 1_000.0)
    yield led
    led.close()


@pytest.fixture
def run(ledger):
    return ledger.open_run(_goal())


def _ctx(run, ledger, **budget):
    state = ledger.budget_state(run.id)
    state.update(budget)
    return {"run": run.as_dict(), "budget": state}


def _step(kind="research", summary="read last quarter's numbers"):
    return PlanStep(kind=kind, summary=summary, task={"agent": "jarvis", "kind": kind})


# ── the scope clamp ──────────────────────────────────────────────────────────

async def test_a_model_proposal_outside_the_goal_scope_is_refused_at_proposal_time(
    ledger, run
):
    """Refusing here rather than at judgement means the run never spends a step
    on work the judge would reject at the end."""
    planner = ModelPlanner(
        lambda _c: {"kind": "terminal", "summary": "just a quick shell command"},
        scope_kinds=SCOPE, ledger=ledger,
    )
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == "out_of_scope"
    assert "terminal" in planner.last.detail


async def test_an_in_scope_proposal_becomes_an_action(ledger, run):
    planner = ModelPlanner(
        lambda _c: {"kind": "research", "summary": "read the docs", "task": {"x": 1}},
        scope_kinds=SCOPE, ledger=ledger,
    )
    action = await planner(_ctx(run, ledger))
    assert isinstance(action, Action)
    assert action.kind == "research"
    assert action.task == {"x": 1}
    assert planner.last.refusal == ""


async def test_an_empty_scope_is_unrestricted_by_explicit_decision(ledger, run):
    planner = ModelPlanner(lambda _c: {"kind": "anything", "summary": "at all"},
                           ledger=ledger)
    assert (await planner(_ctx(run, ledger))).kind == "anything"


async def test_a_hand_written_checklist_is_clamped_like_a_model(ledger, run):
    """A list is not more trusted for having been typed by a person."""
    planner = ChecklistPlanner(
        [_step(kind="terminal", summary="run the deploy")], scope_kinds=SCOPE, ledger=ledger
    )
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == "out_of_scope"


# ── the repeat clamp ─────────────────────────────────────────────────────────

async def test_a_proposal_repeating_a_step_already_taken_is_refused(ledger, run):
    """Repeating a step is how an agent loops forever while looking busy."""
    ledger.record_step(run.id, kind="research", summary="read the docs",
                       outcome="ok", task_id=1)
    planner = ModelPlanner(
        lambda _c: {"kind": "research", "summary": "read the docs"},
        scope_kinds=SCOPE, ledger=ledger,
    )
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == "already_done"


async def test_the_repeat_check_is_not_fooled_by_whitespace_or_casing(ledger, run):
    ledger.record_step(run.id, kind="research", summary="Read The Docs",
                       outcome="ok", task_id=1)
    planner = ModelPlanner(
        lambda _c: {"kind": "research", "summary": "  read   the docs  "},
        scope_kinds=SCOPE, ledger=ledger,
    )
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == "already_done"


async def test_genuinely_new_work_is_not_treated_as_a_repeat(ledger, run):
    ledger.record_step(run.id, kind="research", summary="read the docs",
                       outcome="ok", task_id=1)
    planner = ModelPlanner(
        lambda _c: {"kind": "write", "summary": "draft the summary"},
        scope_kinds=SCOPE, ledger=ledger,
    )
    assert (await planner(_ctx(run, ledger))).kind == "write"


# ── a broken proposer proposes nothing ───────────────────────────────────────

async def test_a_proposer_that_raises_proposes_nothing(ledger, run):
    """"Out of ideas" is the honest outcome; the supervisor then grades the run."""
    def _boom(_ctx):
        raise TimeoutError("the model did not answer")

    planner = ModelPlanner(_boom, scope_kinds=SCOPE, ledger=ledger)
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == "proposer_failed"
    assert planner.last.detail == "TimeoutError"


@pytest.mark.parametrize(
    "junk",
    [
        "run the thing",
        42,
        {"summary": "no kind at all"},
        {"kind": "research"},          # no summary
        {"kind": "", "summary": "x"},  # empty kind
        ["research", "read the docs"],
    ],
)
async def test_a_malformed_proposal_is_refused_not_guessed_at(ledger, run, junk):
    planner = ModelPlanner(lambda _c: junk, scope_kinds=SCOPE, ledger=ledger)
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == "malformed"


async def test_a_proposer_returning_none_is_not_a_refusal(ledger, run):
    """Nothing left to do is a legitimate answer, and must be distinguishable
    from a refusal — the supervisor grades on one and keeps going on the other."""
    planner = ModelPlanner(lambda _c: None, scope_kinds=SCOPE, ledger=ledger)
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == ""


async def test_an_async_proposer_is_awaited(ledger, run):
    async def _propose(_ctx):
        return {"kind": "research", "summary": "read it"}

    planner = ModelPlanner(_propose, scope_kinds=SCOPE, ledger=ledger)
    assert (await planner(_ctx(run, ledger))).kind == "research"


# ── the budget clamp ─────────────────────────────────────────────────────────

async def test_no_budget_left_means_stop_proposing(ledger, run):
    """Proposing into a spent budget just feeds the ledger refusals; a refusal
    loop is not a plan."""
    called = []
    planner = ModelPlanner(
        lambda c: called.append(c) or {"kind": "research", "summary": "more"},
        scope_kinds=SCOPE, ledger=ledger,
    )
    assert await planner(_ctx(run, ledger, steps_left=0)) is None
    assert planner.last.refusal == "budget_spent"
    assert called == []


async def test_an_already_exceeded_budget_stops_the_planner(ledger, run):
    planner = ModelPlanner(lambda _c: {"kind": "research", "summary": "more"},
                           scope_kinds=SCOPE, ledger=ledger)
    assert await planner(_ctx(run, ledger, exceeded="deadline")) is None
    assert planner.last.detail == "deadline"


# ── the checklist ────────────────────────────────────────────────────────────

async def test_the_checklist_hands_out_its_steps_in_order(ledger, run):
    planner = ChecklistPlanner(
        [_step(summary="one"), _step(summary="two")], scope_kinds=SCOPE, ledger=ledger
    )
    first = await planner(_ctx(run, ledger))
    assert first.summary == "one"
    ledger.record_step(run.id, kind=first.kind, summary=first.summary,
                       outcome="ok", task_id=1)
    second = await planner(_ctx(run, ledger))
    assert second.summary == "two"


async def test_the_checklist_resumes_from_the_ledger_after_a_restart(ledger, run):
    """Position comes from what the run actually did, not from a counter — so a
    planner rebuilt after a reboot does not start the list again."""
    steps = [_step(summary="one"), _step(summary="two"), _step(summary="three")]
    ledger.record_step(run.id, kind="research", summary="one", outcome="ok", task_id=1)
    ledger.record_step(run.id, kind="research", summary="two", outcome="ok", task_id=2)
    fresh = ChecklistPlanner(steps, scope_kinds=SCOPE, ledger=ledger)
    assert (await fresh(_ctx(run, ledger))).summary == "three"


async def test_an_exhausted_checklist_proposes_nothing(ledger, run):
    planner = ChecklistPlanner([_step(summary="only")], scope_kinds=SCOPE, ledger=ledger)
    ledger.record_step(run.id, kind="research", summary="only", outcome="ok", task_id=1)
    assert await planner(_ctx(run, ledger)) is None
    assert planner.last.refusal == ""


async def test_a_plan_step_needs_a_kind_and_a_summary():
    for kwargs in ({"kind": "", "summary": "x"}, {"kind": "x", "summary": " "}):
        with pytest.raises(ValueError):
            PlanStep(task={}, **kwargs)


# ── with the supervisor ──────────────────────────────────────────────────────

async def test_the_supervisor_drives_a_checklist_to_grading(ledger, run):
    """End to end: the planner walks its list, each step is queued for approval,
    and when the list is empty the run goes to the graders — never to 'done'."""
    from agents.core.autonomy.company_supervisor import (
        CompanySupervisor,
        SupervisorConfig,
    )

    class _Intake:
        def __init__(self):
            self.n = 100

        def __call__(self, **_kwargs):
            self.n += 1
            return self.n

    graded = []
    planner = ChecklistPlanner(
        [_step(summary="one"), _step(summary="two")], scope_kinds=SCOPE, ledger=ledger
    )
    sup = CompanySupervisor(
        ledger, enqueue=_Intake(), plan_next=planner,
        verify=lambda rid: graded.append(("verify", rid))
        or types.SimpleNamespace(passed=True, reason="ok"),
        judge=lambda rid: graded.append(("judge", rid))
        or types.SimpleNamespace(passed=True, reason="met"),
        config=SupervisorConfig(enabled=True),
    )

    assert (await sup.tick(run.id)).outcome == "stepped"
    ledger.resume(run.id)
    assert (await sup.tick(run.id)).outcome == "stepped"
    ledger.resume(run.id)
    assert (await sup.tick(run.id)).outcome == "graded"
    assert [g[0] for g in graded] == ["verify", "judge"]
    assert [s.summary for s in ledger.steps(run.id)] == ["one", "two"]
