"""E5.0 — the goal contract: how a goal becomes approved, and what that means.

Everything downstream refuses; this is the one path that grants. So the tests are
about making an approval mean something specific:

  · a draft cannot omit scope, budget, deadline, stop conditions or success
    checks — an owner accepting "sort out the quarterly stuff" has agreed to
    nothing the rest of the chain can hold a step against;
  · an unlimited scope must be DECLARED, never defaulted into by an empty list;
  · a goal with no success check is refused up front, because the verifier will
    (correctly) refuse to pass it at 4am otherwise;
  · only a HUMAN accept/edit mints an approved goal — a policy auto-decision
    cannot;
  · a payload edited between proposal and execution cannot ride an approval that
    was given for a different goal.

Hermetic: a fake governed intake, hand-built tasks, an injected clock.
"""

from __future__ import annotations

import types

import pytest

from agents.core.autonomy.goal_contract import (
    KIND,
    SCHEMA,
    ApprovedGoal,
    GoalContractError,
    GoalDraft,
    SuccessCheck,
    approve_from_task,
    draft_from_payload,
    propose,
)
from agents.core.autonomy.work_runs import Budget

NOW = 1_000.0


def _check(check_id="brief-exists", probe_ref="", required=True):
    return SuccessCheck(
        id=check_id, describe="the brief is in docs/", probe_ref=probe_ref, required=required
    )


def _draft(**over):
    base = {
        "title": "Prepare the quarterly brief",
        "scope_kinds": ("research", "write"),
        "budget": Budget(max_steps=20),
        "deadline_at": NOW + 86_400,
        "stop_conditions": ("the source data goes stale",),
        "checks": (_check(),),
        "deliverable": "a brief in docs/",
    }
    base.update(over)
    return GoalDraft(**base)


class _Enqueue:
    def __init__(self, task_id: int = 77) -> None:
        self.calls: list[dict] = []
        self._id = task_id

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self._id


def _task(payload, *, decided_by="owner", decision="accept", kind=KIND, task_id=77):
    return types.SimpleNamespace(
        id=task_id, kind=kind, payload=payload,
        decided_by=decided_by, decision=decision,
    )


# ── a draft names what is being agreed to ────────────────────────────────────

def test_a_complete_draft_is_accepted():
    draft = _draft()
    assert draft.title == "Prepare the quarterly brief"
    assert draft.scope_kinds == ("research", "write")
    assert draft.stop_conditions == ("the source data goes stale",)
    assert len(draft.checks) == 1


def test_a_goal_with_no_success_check_is_refused_up_front():
    """The verifier would refuse it at grading time anyway — better to say so now
    than at 4am after a night of work nobody can accept."""
    with pytest.raises(GoalContractError) as exc:
        _draft(checks=())
    assert exc.value.reason == "success_check_required"


def test_a_goal_whose_every_check_is_optional_is_refused():
    """All-optional checks means a run could pass having verified nothing."""
    with pytest.raises(GoalContractError) as exc:
        _draft(checks=(_check(required=False),))
    assert exc.value.reason == "at_least_one_required_check"


def test_a_goal_with_no_stop_condition_is_refused():
    """Without one, the only thing that ends the run is its budget."""
    with pytest.raises(GoalContractError) as exc:
        _draft(stop_conditions=())
    assert exc.value.reason == "stop_condition_required"


def test_an_unlimited_scope_must_be_declared_not_defaulted_into():
    """A blank scope field and a deliberate "anything goes" look identical in a
    payload; only one of them is a decision."""
    with pytest.raises(GoalContractError) as exc:
        _draft(scope_kinds=())
    assert exc.value.reason == "scope_required_or_declare_unrestricted"

    wide = _draft(scope_kinds=(), unrestricted=True)
    assert wide.scope_kinds == ()
    assert wide.unrestricted is True


def test_declaring_unrestricted_alongside_a_scope_is_a_contradiction():
    with pytest.raises(GoalContractError) as exc:
        _draft(scope_kinds=("research",), unrestricted=True)
    assert exc.value.reason == "scope_and_unrestricted_conflict"


def test_a_title_is_required_because_it_is_what_a_person_reads():
    with pytest.raises(GoalContractError) as exc:
        _draft(title="   ")
    assert exc.value.reason == "missing_title"


def test_duplicate_check_ids_are_refused():
    with pytest.raises(GoalContractError) as exc:
        _draft(checks=(_check("a"), _check("a")))
    assert exc.value.reason == "duplicate_check_id"


def test_scope_kinds_are_deduplicated_and_normalised():
    draft = _draft(scope_kinds=("Research", "research", " WRITE "))
    assert draft.scope_kinds == ("research", "write")


def test_the_lists_are_bounded():
    with pytest.raises(GoalContractError) as exc:
        _draft(scope_kinds=tuple(f"k{i}" for i in range(25)))
    assert exc.value.reason == "too_many_scope_kinds"
    with pytest.raises(GoalContractError) as exc:
        _draft(stop_conditions=tuple(f"s{i}" for i in range(15)))
    assert exc.value.reason == "too_many_stop_conditions"
    with pytest.raises(GoalContractError) as exc:
        _draft(checks=tuple(_check(f"c{i}") for i in range(25)))
    assert exc.value.reason == "too_many_checks"


def test_a_check_needs_an_id_and_a_sentence():
    for kwargs in ({"id": "", "describe": "x"}, {"id": "x", "describe": "  "}):
        with pytest.raises(GoalContractError):
            SuccessCheck(**kwargs)


# ── proposing grants nothing ─────────────────────────────────────────────────

def test_propose_enqueues_an_ask_and_grants_nothing():
    enq = _Enqueue()
    task_id = propose(_draft(), enq, now=NOW)
    assert task_id == 77
    call = enq.calls[0]
    assert call["kind"] == KIND
    assert call["autonomy_level"] == "ask"
    assert call["title"].startswith("Approve goal:")
    # everything the owner is agreeing to travels in the payload
    payload = call["payload"]
    assert payload["schema"] == SCHEMA
    assert payload["scope_kinds"] == ["research", "write"]
    assert payload["stop_conditions"] == ["the source data goes stale"]
    assert payload["checks"][0]["id"] == "brief-exists"
    assert payload["budget"]["max_steps"] == 20
    assert payload["fingerprint"]


def test_a_deadline_in_the_past_is_refused_at_proposal_time():
    enq = _Enqueue()
    with pytest.raises(GoalContractError) as exc:
        propose(_draft(deadline_at=NOW - 1), enq, now=NOW)
    assert exc.value.reason == "deadline_in_the_past"
    assert enq.calls == []


def test_a_non_numeric_deadline_is_refused():
    enq = _Enqueue()
    with pytest.raises(GoalContractError) as exc:
        propose(_draft(deadline_at=True), enq, now=NOW)
    assert exc.value.reason == "invalid_deadline"


# ── only a human's decision mints a goal ─────────────────────────────────────

def test_a_human_accept_mints_an_approved_goal():
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"]), now=NOW)
    assert isinstance(goal, ApprovedGoal)
    assert goal.approved_by == "task:77:owner"
    assert goal.title == "Prepare the quarterly brief"
    assert goal.scope_kinds == frozenset({"research", "write"})
    assert goal.budget.max_steps == 20


@pytest.mark.parametrize("decider", ["policy", "system", "kernel", "auto", "worker", ""])
def test_a_machine_decision_cannot_mint_a_goal(decider):
    """A policy auto-decision is not an owner deciding to spend a night of work."""
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    with pytest.raises(GoalContractError) as exc:
        approve_from_task(_task(enq.calls[0]["payload"], decided_by=decider))
    assert exc.value.reason == "not_decided_by_a_human"


@pytest.mark.parametrize("decision", ["reject", "defer", "", "maybe"])
def test_anything_other_than_accept_or_edit_is_not_an_approval(decision):
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    with pytest.raises(GoalContractError) as exc:
        approve_from_task(_task(enq.calls[0]["payload"], decision=decision))
    assert exc.value.reason == "not_accepted"


def test_an_edit_counts_as_an_approval():
    """Editing a card and accepting it is still a person deciding."""
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"], decision="edit"))
    assert goal.title == "Prepare the quarterly brief"


def test_a_task_of_the_wrong_kind_is_refused():
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    with pytest.raises(GoalContractError) as exc:
        approve_from_task(_task(enq.calls[0]["payload"], kind="writeback"))
    assert exc.value.reason == "kind_mismatch"


def test_a_payload_edited_after_approval_cannot_ride_the_approval():
    """The fingerprint is over exactly what the owner saw. Widening the scope
    between the card and the execution is the attack this closes."""
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    payload = dict(enq.calls[0]["payload"])
    payload["scope_kinds"] = ["research", "write", "terminal"]
    with pytest.raises(GoalContractError) as exc:
        approve_from_task(_task(payload))
    assert exc.value.reason == "payload_changed_after_approval"


def test_an_unknown_schema_is_refused():
    with pytest.raises(GoalContractError) as exc:
        draft_from_payload({"schema": "something.else.v1"})
    assert exc.value.reason == "unknown_schema"


def test_a_malformed_payload_is_refused_rather_than_guessed_at():
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    payload = dict(enq.calls[0]["payload"])
    payload["checks"] = "the usual ones"
    with pytest.raises(GoalContractError) as exc:
        draft_from_payload(payload)
    assert exc.value.reason == "invalid_checks"


def test_a_task_with_no_payload_is_refused():
    with pytest.raises(GoalContractError) as exc:
        approve_from_task(_task(None))
    assert exc.value.reason == "invalid_payload"


# ── the approved goal is what the rest of the chain consumes ─────────────────

def test_the_approved_goal_opens_a_run_and_nothing_else_does():
    from agents.core.autonomy.work_runs import WorkRunError, WorkRunLedger

    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"]), now=NOW)

    led = WorkRunLedger(":memory:", clock=lambda: NOW)
    try:
        run = led.open_run(goal, budget=goal.budget)
        assert run.approved_by == "task:77:owner"
        assert run.status == "planning"

        # the same draft without an approval opens nothing
        unapproved = types.SimpleNamespace(
            goal_id="x", title="Prepare the quarterly brief",
            approved_by=None, deadline_at=NOW + 86_400,
        )
        with pytest.raises(WorkRunError) as exc:
            led.open_run(unapproved)
        assert exc.value.reason == "goal_not_approved"
    finally:
        led.close()


def test_the_declared_checks_become_the_verifier_s_checks():
    enq = _Enqueue()
    propose(_draft(checks=(_check("a", probe_ref="probes:a"), _check("b"))), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"]))
    checks = goal.verifier_checks({"probes:a": lambda: True})
    assert [c.id for c in checks] == ["a", "b"]
    assert checks[0].probe is not None
    # b declared no probe, so it stays unprobed — and grades as unverifiable
    assert checks[1].probe is None


def test_a_check_whose_probe_is_missing_is_kept_not_dropped():
    """Dropping it would quietly shrink the success criteria the owner approved."""
    enq = _Enqueue()
    propose(_draft(checks=(_check("a", probe_ref="probes:missing"),)), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"]))
    checks = goal.verifier_checks({})
    assert len(checks) == 1
    assert checks[0].probe is None


def test_the_goal_terms_carry_the_scope_the_judge_enforces():
    enq = _Enqueue()
    propose(_draft(), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"]))
    terms = goal.goal_terms()
    assert terms.goal_id == goal.goal_id
    assert terms.scope_kinds == frozenset({"research", "write"})
    assert terms.deliverable == "a brief in docs/"
    assert terms.covers("research") is True
    assert terms.covers("terminal") is False


def test_an_unrestricted_goal_produces_terms_that_cover_everything():
    enq = _Enqueue()
    propose(_draft(scope_kinds=(), unrestricted=True), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"]))
    assert goal.goal_terms().covers("terminal") is True


def test_the_committed_fixture_is_a_real_contract_and_stays_one():
    """docs/nerva2/fixtures/goal_contract_v1.json is the worked example a reader
    copies. A fixture that no longer round-trips through the code it documents is
    worse than none, so it is validated here rather than eyeballed."""
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    doc = json.loads(
        (repo / "docs/nerva2/fixtures/goal_contract_v1.json").read_text(encoding="utf-8")
    )
    payload = doc["example"]
    draft = draft_from_payload(payload)
    assert draft.title == "Prepare the Q3 board brief"
    # the recorded fingerprint still matches what the code computes
    assert payload["fingerprint"] == draft.fingerprint()
    # and the example really does exercise the unprobed-check case it claims to
    unprobed = [c for c in draft.checks if not c.probe_ref]
    assert unprobed and all(not c.required for c in unprobed)


def test_the_kernel_refuses_a_goal_before_the_inbox_sees_it():
    """A DENY (kill-switch, budget, loop) stops the night's work at the door."""
    from agents.core.kernel import Decision, Verdict

    seen = []

    def _deny(action, capability=None):
        seen.append(action)
        return Decision(Verdict.DENY, reason="kill_switch")

    enq = _Enqueue()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("JARVIS_ACTION_KERNEL", "1")
        with pytest.raises(GoalContractError) as exc:
            propose(_draft(), enq, authorizer=_deny, now=NOW)
    assert exc.value.reason == "kernel_denied:kill_switch"
    assert enq.calls == []
    assert seen and seen[0].kind == KIND


def test_the_kernel_hook_is_not_consulted_while_the_flag_is_off():
    """Default-off, like FileTools and the permission ledger: the ask still
    reaches the inbox, which is the pre-kernel behaviour."""
    from agents.core.kernel import Decision, Verdict

    seen = []

    def _deny(action, capability=None):
        seen.append(action)
        return Decision(Verdict.DENY, reason="kill_switch")

    enq = _Enqueue()
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("JARVIS_ACTION_KERNEL", raising=False)
        assert propose(_draft(), enq, authorizer=_deny, now=NOW) == 77
    assert seen == []
    assert len(enq.calls) == 1


def test_a_kernel_queue_still_reaches_the_inbox():
    """QUEUE means "ask the owner", and the inbox is exactly where it was going."""
    from agents.core.kernel import Decision, Verdict

    enq = _Enqueue()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("JARVIS_ACTION_KERNEL", "1")
        assert propose(
            _draft(), enq,
            authorizer=lambda a, capability=None: Decision(Verdict.QUEUE, reason="ask"),
            now=NOW,
        ) == 77
    assert len(enq.calls) == 1


def test_the_whole_chain_runs_from_one_approved_goal():
    """Approve → open → step → verify → judge, with the goal's own declarations
    driving the graders rather than anything the run made up."""
    import asyncio

    from agents.core.autonomy.work_judge import WorkJudge
    from agents.core.autonomy.work_runs import WorkRunLedger
    from agents.core.autonomy.work_verifier import WorkVerifier

    enq = _Enqueue()
    propose(_draft(checks=(_check("brief", probe_ref="p"),)), enq, now=NOW)
    goal = approve_from_task(_task(enq.calls[0]["payload"]), now=NOW)

    led = WorkRunLedger(":memory:", clock=lambda: NOW)
    try:
        run = led.open_run(goal, budget=goal.budget)
        led.record_step(run.id, kind="research", summary="read it", outcome="ok", task_id=5)

        report = asyncio.run(
            WorkVerifier(led).verify(run.id, goal.verifier_checks({"p": lambda: True}))
        )
        assert report.passed is True

        judgement = asyncio.run(WorkJudge(led).judge(run.id, goal.goal_terms()))
        assert judgement.passed is True
        assert led.get(run.id).status == "succeeded"
    finally:
        led.close()
