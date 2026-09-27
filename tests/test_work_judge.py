"""E5.0 — the work judge: was this actually the goal?

The verifier proves the evidence holds; the judge is the gate after it. Its value
is entirely in what it refuses, so these tests are mostly refusals: a run graded
against the wrong goal, one that drifted outside its approved scope, one whose
stop condition fired, one nobody verified, and — the one that matters most for an
autonomous system — a rubric that likes the result.

Hermetic: a real in-memory ledger so verdicts really settle the run.
"""

import types

import pytest

from agents.core.autonomy.work_judge import GoalTerms, WorkJudge
from agents.core.autonomy.work_runs import WorkRunLedger

pytestmark = pytest.mark.asyncio

TERMS = GoalTerms(
    goal_id="g-1",
    title="Prepare the quarterly brief",
    scope_kinds=frozenset({"research", "write"}),
    deliverable="a brief in docs/",
)


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


def _verified_run(ledger, *, kinds=("research", "write"), verifier_passed=True):
    run = ledger.open_run(_goal())
    for index, kind in enumerate(kinds, start=1):
        ledger.record_step(run.id, kind=kind, summary=f"step {index}",
                           outcome="ok", task_id=index)
    ledger.record_verdict(run.id, role="verifier", passed=verifier_passed,
                          reason="evidence holds" if verifier_passed else "did not match")
    return run


# ── the pass ─────────────────────────────────────────────────────────────────

async def test_a_verified_in_scope_run_passes_and_settles(ledger):
    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.passed is True
    assert judgement.rule == "met"
    assert ledger.get(run.id).status == "succeeded"


# ── refusals, in the order the judge applies them ────────────────────────────

async def test_a_run_opened_for_a_different_goal_is_refused_first(ledger):
    """Grading run A against goal B is the one mistake that makes every later
    rule meaningless, so it is checked before anything else."""
    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger).judge(
        run.id, GoalTerms(goal_id="a-different-goal", title="Something else")
    )
    assert judgement.passed is False
    assert judgement.rule == "goal_identity"
    assert ledger.get(run.id).status == "failed"


async def test_a_tampered_row_is_refused(ledger, monkeypatch):
    run = _verified_run(ledger)
    real = ledger.snapshot
    monkeypatch.setattr(ledger, "snapshot",
                        lambda rid, **kw: {**real(rid, **kw), "tampered": True})
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.rule == "integrity"
    assert judgement.passed is False


async def test_unauthorised_work_is_refused_even_when_verified(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="write", summary="wrote it", outcome="ok")  # no task
    ledger.record_verdict(run.id, role="verifier", passed=True, reason="looks right")
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "authorisation"
    assert judgement.detail["steps"] == [1]


async def test_a_run_nobody_verified_cannot_pass(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="write", summary="wrote it", outcome="ok", task_id=1)
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "verification_missing"


async def test_a_failed_verification_is_reported_as_itself(ledger):
    """The ledger would refuse this anyway; the judge names the real problem so
    the owner reads "the evidence did not hold", not a database error."""
    run = _verified_run(ledger, verifier_passed=False)
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "verification_failed"
    assert "did not match" in judgement.reason


async def test_a_fired_stop_condition_is_decisive(ledger):
    """Finishing first does not excuse a condition the goal said should end it."""
    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger).judge(
        run.id, TERMS, fired_stop_conditions=["the source data went stale"]
    )
    assert judgement.passed is False
    assert judgement.rule == "stop_condition"
    assert "went stale" in judgement.reason


async def test_useful_work_outside_the_approved_scope_still_fails(ledger):
    """Drifting into helpful adjacent work is how an autonomous system stops
    being governable — so it fails, even though the step succeeded."""
    run = _verified_run(ledger, kinds=("research", "terminal"))
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "scope"
    assert judgement.detail["kinds"] == ["terminal"]


async def test_an_empty_scope_means_unrestricted_by_explicit_decision(ledger):
    run = _verified_run(ledger, kinds=("research", "terminal"))
    judgement = await WorkJudge(ledger).judge(
        run.id, GoalTerms(goal_id="g-1", title="Anything goes")
    )
    assert judgement.passed is True


async def test_an_unrecovered_failed_step_fails_the_run(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="write", summary="tried", outcome="failed", task_id=1)
    ledger.record_verdict(run.id, role="verifier", passed=True, reason="what shipped is right")
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "failed_steps"


async def test_a_run_that_did_nothing_cannot_pass(ledger):
    run = ledger.open_run(_goal())
    ledger.record_verdict(run.id, role="verifier", passed=True, reason="nothing to check")
    judgement = await WorkJudge(ledger).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "no_work"


# ── the rubric can only ever withhold ────────────────────────────────────────

async def test_a_rubric_can_withhold_a_pass(ledger):
    run = _verified_run(ledger)
    judge = WorkJudge(ledger, rubric=lambda _ctx: {"passed": False, "reason": "thin"})
    judgement = await judge.judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "rubric"
    assert judgement.reason == "thin"


async def test_a_happy_rubric_cannot_rescue_a_run_that_broke_a_rule(ledger):
    """The one property that matters most: a model saying "looks good" must never
    turn a failing run into a successful one."""
    run = _verified_run(ledger, kinds=("research", "terminal"))  # out of scope
    judge = WorkJudge(ledger, rubric=lambda _ctx: {"passed": True, "reason": "great work"})
    judgement = await judge.judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "scope"
    assert ledger.get(run.id).status == "failed"


async def test_a_broken_rubric_cannot_fail_a_run_that_satisfied_every_rule(ledger):
    """A grader that crashes is not evidence of anything, in either direction."""
    def _boom(_ctx):
        raise RuntimeError("model unavailable")

    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger, rubric=_boom).judge(run.id, TERMS)
    assert judgement.passed is True
    assert judgement.rule == "met"


async def test_a_rubric_that_returns_nonsense_is_ignored(ledger):
    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger, rubric=lambda _ctx: "looks fine to me").judge(
        run.id, TERMS
    )
    assert judgement.passed is True


async def test_an_async_rubric_is_awaited(ledger):
    async def _rubric(_ctx):
        return {"passed": False, "reason": "needs another pass"}

    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger, rubric=_rubric).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.reason == "needs another pass"


# ── looking without settling ─────────────────────────────────────────────────

async def test_record_false_grades_without_settling_the_run(ledger):
    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger).judge(run.id, TERMS, record=False)
    assert judgement.passed is True
    assert ledger.get(run.id).status == "working"
    assert [v.role for v in ledger.verdicts(run.id)] == ["verifier"]


# ── H464: the judge may ask to wait, and sees what is still running ──────────

def _unverified_run(ledger, *, kinds=("research",)):
    run = ledger.open_run(_goal())
    for index, kind in enumerate(kinds, start=1):
        ledger.record_step(run.id, kind=kind, summary=f"step {index}",
                           outcome="ok", task_id=index)
    return run


_WAIT = {"verdict": "wait", "wait": {"kind": "trigger", "target": "task:1",
                                     "reason": "the build is still running", "max_wait": 600,
                                     "extra": "dropped"}}


async def test_wait_probe_accepts_only_a_structured_wait(ledger):
    run = _unverified_run(ledger)
    judge = WorkJudge(ledger, rubric=lambda _ctx: _WAIT)
    assert await judge.wait_probe(run.id, TERMS) == {
        "kind": "trigger", "target": "task:1", "reason": "the build is still running",
        "max_wait": 600,
    }
    # it records nothing: no verdict, no settle
    assert ledger.verdicts(run.id) == [] and ledger.get(run.id).status == "working"

    def _boom(_ctx):
        raise RuntimeError("grader down")

    for rubric in (
        lambda _ctx: "wait",
        lambda _ctx: {"passed": True},
        lambda _ctx: {"verdict": "wait"},
        lambda _ctx: {"verdict": "wait", "wait": {"target": 5}},
        lambda _ctx: {"verdict": "pass", "wait": _WAIT["wait"]},
        _boom,
    ):
        assert await WorkJudge(ledger, rubric=rubric).wait_probe(run.id, TERMS) is None
    assert await WorkJudge(ledger).wait_probe(run.id, TERMS) is None


async def test_wait_probe_never_waits_out_a_mechanical_refusal(ledger, monkeypatch):
    """Waiting cannot fix the wrong goal, a tampered row or unauthorised work."""
    asked = []
    judge = WorkJudge(ledger, rubric=lambda ctx: asked.append(ctx) or _WAIT)
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="no task", outcome="ok")
    assert await judge.wait_probe(run.id, TERMS) is None
    assert await judge.wait_probe(run.id, GoalTerms(goal_id="other", title="x")) is None
    real = ledger.snapshot
    monkeypatch.setattr(ledger, "snapshot",
                        lambda rid, **kw: {**real(rid, **kw), "tampered": True,
                                           "unauthorised_steps": []})
    assert await judge.wait_probe(run.id, TERMS) is None
    assert asked == []


async def test_the_rubric_sees_the_background_list_and_phase(ledger):
    run = _unverified_run(ledger)
    seen = []
    background = [{"kind": "task", "id": 1, "status": "running", "done": False}]
    judge = WorkJudge(ledger, rubric=lambda ctx: seen.append(ctx) or None,
                      background=lambda rid: background if rid == run.id else [])
    await judge.wait_probe(run.id, TERMS)
    ledger.record_verdict(run.id, role="verifier", passed=True, reason="ok")
    await judge.judge(run.id, TERMS, record=False)
    assert [ctx["phase"] for ctx in seen] == ["wait_probe", "settle"]
    assert all(ctx["background"] == background for ctx in seen)
    assert seen[0]["goal"] == TERMS.title and seen[0]["deliverable"] == TERMS.deliverable


async def test_a_background_reader_that_fails_hands_the_rubric_an_empty_list(ledger):
    run = _verified_run(ledger)
    seen = []

    def _boom(_rid):
        raise RuntimeError("queue unreadable")

    judge = WorkJudge(ledger, rubric=lambda ctx: seen.append(ctx) or None, background=_boom)
    assert (await judge.judge(run.id, TERMS)).passed is True
    assert seen[0]["background"] == []


async def test_a_settle_phase_wait_withholds_and_never_passes(ledger):
    """A dict without `passed` used to read as "no opinion", i.e. a pass. A wait at
    settlement is a grader saying "not yet", so it withholds."""
    run = _verified_run(ledger)
    judgement = await WorkJudge(ledger, rubric=lambda _ctx: _WAIT).judge(run.id, TERMS)
    assert judgement.passed is False
    assert judgement.rule == "rubric"
    assert judgement.reason == "the grader asked to wait at settlement"
    assert ledger.get(run.id).status == "failed"
