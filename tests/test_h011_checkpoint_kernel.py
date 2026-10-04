"""Checkpoint actions gain authority only from an exact, current sealed task."""

from __future__ import annotations

import pytest

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS
from agents.core.kernel import (
    Action,
    BudgetLedger,
    BudgetLimits,
    Capability,
    LoopDetector,
    Verdict,
    authorize,
    revalidate,
)
from agents.core.kernel.registry import ACTION_REGISTRY, Mediation
from agents.core.security.capability import GLOBAL, CapabilityBroker, KillSwitch

KINDS = ("checkpoint.restore", "checkpoint.maintenance")


def action(kind: str = "checkpoint.restore", *, task_id=31, **payload):
    return Action(kind=kind, title="owner checkpoint", payload={
        "approved_task_id": task_id, "risk_tier": 3, **payload,
    })


def exact(expected):
    return lambda actual: actual is expected


@pytest.mark.parametrize("kind", KINDS)
def test_exact_action_bound_receipt_grants_only_tier_three_auto_ask(kind):
    subject = action(kind)
    baseline = authorize(subject, policy=AutonomyPolicy())
    assert baseline.verdict is Verdict.QUEUE
    granted = authorize(subject, policy=AutonomyPolicy(), approval_check=exact(subject))
    assert granted.verdict is Verdict.GRANT
    assert granted.task_id == 31
    assert granted.tier == 3
    assert granted.reason.startswith("sealed_checkpoint_approval; ")
    assert revalidate(subject, policy=AutonomyPolicy(), approval_check=exact(subject)) == granted


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("task_id", [None, 0, -1, True, "31", 31.0, [], {}])
def test_malformed_or_missing_id_does_not_call_checker(kind, task_id):
    subject = action(kind, task_id=task_id)
    called = []
    decision = authorize(subject, policy=AutonomyPolicy(),
                         approval_check=lambda actual: called.append(actual) or True)
    assert decision.verdict is Verdict.QUEUE
    assert called == []


@pytest.mark.parametrize("kind", KINDS)
def test_actual_action_and_literal_true_required(kind):
    subject = action(kind)
    other = action(kind)
    assert authorize(subject, policy=AutonomyPolicy(),
                     approval_check=exact(other)).verdict is Verdict.QUEUE
    for answer in (False, 1, "yes", None):
        assert authorize(subject, policy=AutonomyPolicy(),
                         approval_check=lambda _, value=answer: value).verdict is Verdict.QUEUE
    assert authorize(subject, policy=AutonomyPolicy(),
                     approval_check=True).verdict is Verdict.QUEUE


@pytest.mark.parametrize("kind", KINDS)
def test_broken_checker_fails_closed_without_leak(kind):
    subject = action(kind)
    def broken(_):
        raise RuntimeError("secret approval detail")
    decision = authorize(subject, policy=AutonomyPolicy(), approval_check=broken)
    assert decision.verdict is Verdict.QUEUE
    assert "secret approval detail" not in decision.reason


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", ["ask", "off", "invalid"])
def test_non_auto_mode_does_not_lift_ask(kind, mode):
    subject = action(kind)
    assert authorize(subject, policy=AutonomyPolicy(mode=mode),
                     approval_check=exact(subject)).verdict is Verdict.QUEUE
    restricted = Action(kind=kind, agent="restricted", payload=subject.payload)
    policy = AutonomyPolicy(agent_modes={"restricted": mode})
    assert authorize(restricted, policy=policy,
                     approval_check=exact(restricted)).verdict is Verdict.QUEUE


def test_neighboring_kind_never_uses_receipt_override():
    subject = action("checkpoint.other")
    called = []
    decision = authorize(subject, policy=AutonomyPolicy(),
                         approval_check=lambda actual: called.append(actual) or True)
    assert decision.verdict is Verdict.QUEUE
    assert called == []


@pytest.mark.parametrize("kind", KINDS)
def test_tier_one_ask_does_not_use_sealed_override(kind):
    subject = Action(kind=kind, payload={"approved_task_id": 31, "risk_tier": 1})
    called = []
    decision = authorize(subject, policy=AutonomyPolicy(mode="ask"),
                         approval_check=lambda actual: called.append(actual) or True)
    assert decision.verdict is Verdict.QUEUE
    assert called == []


@pytest.mark.parametrize("kind", KINDS)
def test_taint_still_queues_after_receipt(kind):
    subject = action(kind, tainted=True)
    decision = authorize(subject, policy=AutonomyPolicy(), approval_check=exact(subject))
    assert decision.verdict is Verdict.QUEUE
    assert decision.task_id is None
    external = Action(kind=kind, origin="external", payload=action(kind).payload)
    assert authorize(external, policy=AutonomyPolicy(),
                     approval_check=exact(external)).verdict is Verdict.QUEUE


@pytest.mark.parametrize("kind", KINDS)
def test_halt_capability_budget_and_loop_refuse_before_checker(kind, tmp_path):
    subject = action(kind)
    calls = []
    def checker(actual):
        calls.append(actual)
        return True
    kill = KillSwitch(tmp_path / "halt.json")
    kill.engage(GLOBAL, "halt")
    assert authorize(subject, policy=AutonomyPolicy(), kill_switch=kill,
                     approval_check=checker).verdict is Verdict.DENY
    assert authorize(subject, capability=Capability(token_id="missing", name=kind),
                     capabilities=CapabilityBroker(), kill_switch=KillSwitch(tmp_path / "cap-halt.json"),
                     policy=AutonomyPolicy(),
                     approval_check=checker).verdict is Verdict.DENY
    ledger = BudgetLedger(limits=BudgetLimits(max_tokens=5), tokens_used=6)
    assert authorize(subject, policy=AutonomyPolicy(), budget_ledger=ledger,
                     approval_check=checker).verdict is Verdict.DENY
    loop = LoopDetector(max_repeats=1, window_seconds=60)
    assert loop.record(kind, now=10)
    assert authorize(subject, policy=AutonomyPolicy(), loop_detector=loop, now=10,
                     approval_check=checker).verdict is Verdict.DENY
    assert calls == []


@pytest.mark.parametrize("kind", KINDS)
def test_revalidate_refuses_revoked_receipt_and_preserves_budget(kind):
    subject = action(kind)
    current = {"valid": True}
    def checker(actual):
        return actual is subject and current["valid"]
    ledger = BudgetLedger(limits=BudgetLimits(max_tokens=100))
    first = authorize(subject, policy=AutonomyPolicy(), approval_check=checker,
                      budget_ledger=ledger)
    assert first.verdict is Verdict.GRANT
    assert revalidate(subject, policy=AutonomyPolicy(), approval_check=checker,
                      budget_ledger=ledger).verdict is Verdict.GRANT
    current["valid"] = False
    assert revalidate(subject, policy=AutonomyPolicy(), approval_check=checker,
                      budget_ledger=ledger).verdict is not Verdict.GRANT
    assert ledger.tokens_used == 0


@pytest.mark.parametrize("kind", KINDS)
def test_registry_and_manifests_describe_bounded_effect(kind):
    assert ACTION_REGISTRY[kind] is Mediation.KERNEL
    manifest = ACTION_CAPABILITY_MANIFESTS[kind]
    assert manifest.action_kind == kind
    assert "approved_task_id" in manifest.inputs["required"]
    assert manifest.verification.endswith(kind.replace(".", "-") + "-kernel-halt")
    assert manifest.rollback.automatic is False
    assert manifest.rollback.limitations


def test_reversible_restore_revalidates_after_separate_owner_task_gate():
    # Kernel policy may ACT at reversible tier; the producer/executor still
    # requires the real human task independently of this kernel decision.
    subject = Action(kind="checkpoint.restore", payload={
        "approved_task_id": 31, "risk_tier": 1,
    })
    assert authorize(subject, policy=AutonomyPolicy()).verdict is Verdict.GRANT
    assert revalidate(subject, policy=AutonomyPolicy()).verdict is Verdict.GRANT
