"""H277: a trusted receipt may satisfy the real terminal kernel policy ASK only."""

from __future__ import annotations

import pytest

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import (
    Action,
    BudgetLedger,
    BudgetLimits,
    Capability,
    LoopDetector,
    Verdict,
    authorize,
)
from agents.core.kernel.binding import MediationKernelBridge
from agents.core.security.capability import GLOBAL, CapabilityBroker, KillSwitch


class _Audit:
    def __init__(self):
        self.records = []

    def record(self, actor, action, why, metadata=None):
        self.records.append((actor, action, why, metadata))


def _terminal(*, payload=None, agent="jarvis", origin="generated"):
    return Action(
        kind="terminal.exec", agent=agent, title="terminal on sandbox",
        payload={"approved_task_id": 23} if payload is None else payload,
        origin=origin,
    )


def _approve_exact(expected):
    def check(actual):
        return actual is expected

    return check


def test_actual_default_policy_queues_without_trusted_receipt():
    action = _terminal()
    audit = _Audit()
    decision = authorize(action, policy=AutonomyPolicy(), audit=audit)
    assert decision.verdict is Verdict.QUEUE
    assert decision.card is not None
    assert "approved_task_id" not in audit.records[0][3]


def test_trusted_exact_action_receipt_grants_and_audits_final_id():
    action = _terminal()
    audit = _Audit()
    decision = authorize(
        action, policy=AutonomyPolicy(), audit=audit,
        approval_check=_approve_exact(action),
    )
    assert decision.verdict is Verdict.GRANT
    assert decision.task_id == 23
    assert decision.reason.startswith("sealed_terminal_approval; ")
    assert audit.records == [
        ("kernel", "authorize:terminal.exec", f"grant:{decision.reason}",
         {"verdict": "grant", "tier": 3, "scope": "global", "agent": "jarvis",
          "approved_task_id": 23}),
    ]


@pytest.mark.parametrize("task_id", [None, 0, -1, True, "23", 23.0, [], {}])
def test_missing_or_malformed_task_id_never_calls_receipt(task_id):
    action = _terminal(payload={"approved_task_id": task_id})
    calls = []
    decision = authorize(
        action, policy=AutonomyPolicy(),
        approval_check=lambda actual: calls.append(actual) or True,
    )
    assert decision.verdict is Verdict.QUEUE
    assert calls == []


@pytest.mark.parametrize("check", [None, False, True, 7, "yes"])
def test_non_proof_callback_cannot_grant(check):
    action = _terminal()
    callback = check if check is None else lambda _action: check
    decision = authorize(action, policy=AutonomyPolicy(), approval_check=callback)
    assert decision.verdict is Verdict.GRANT if check is True else Verdict.QUEUE


def test_receipt_check_failure_queues_without_leaking_exception():
    action = _terminal()

    def broken(_action):
        raise RuntimeError("private receipt failure")

    decision = authorize(action, policy=AutonomyPolicy(), approval_check=broken)
    assert decision.verdict is Verdict.QUEUE
    assert "private receipt failure" not in decision.reason


def test_non_callable_receipt_check_queues():
    action = _terminal()
    decision = authorize(action, policy=AutonomyPolicy(), approval_check=True)
    assert decision.verdict is Verdict.QUEUE


def test_untrusted_payload_flags_cannot_create_receipt():
    action = _terminal(payload={
        "approved_task_id": 23, "approval_check": True, "grant": True,
        "smart_approval": {"decision": "approve"},
    })
    decision = authorize(action, policy=AutonomyPolicy())
    assert decision.verdict is Verdict.QUEUE


def test_receipt_callback_must_match_actual_action():
    action = _terminal()
    different = _terminal(payload={"approved_task_id": 24})
    decision = authorize(
        action, policy=AutonomyPolicy(), approval_check=_approve_exact(different),
    )
    assert decision.verdict is Verdict.QUEUE


@pytest.mark.parametrize("kind", ["file.write", "node.dispatch", "terminal.run"])
def test_receipt_cannot_satisfy_other_action_kind(kind):
    action = Action(kind=kind, payload={"approved_task_id": 23})
    calls = []
    decision = authorize(
        action, policy=AutonomyPolicy(),
        approval_check=lambda actual: calls.append(actual) or True,
    )
    assert decision.verdict is Verdict.QUEUE
    assert calls == []


@pytest.mark.parametrize("mode", ["ask", "off", "invalid"])
def test_receipt_cannot_override_non_auto_global_mode(mode):
    action = _terminal()
    decision = authorize(action, policy=AutonomyPolicy(mode=mode), approval_check=lambda _: True)
    assert decision.verdict is Verdict.QUEUE


@pytest.mark.parametrize("mode", ["ask", "off"])
def test_receipt_cannot_override_per_agent_mode(mode):
    action = _terminal(agent="restricted")
    policy = AutonomyPolicy(agent_modes={"restricted": mode})
    decision = authorize(action, policy=policy, approval_check=lambda _: True)
    assert decision.verdict is Verdict.QUEUE


@pytest.mark.parametrize("origin,payload", [
    ("external", {"approved_task_id": 23}),
    ("generated", {"approved_task_id": 23, "tainted": True}),
])
def test_taint_escalates_even_a_trusted_receipt(origin, payload):
    action = _terminal(origin=origin, payload=payload)
    audit = _Audit()
    decision = authorize(
        action, policy=AutonomyPolicy(), audit=audit,
        approval_check=lambda _: True,
    )
    assert decision.verdict is Verdict.QUEUE
    assert decision.task_id is None
    assert "approved_task_id" not in audit.records[0][3]


def test_kill_switch_denial_wins_before_receipt_check(tmp_path):
    action = _terminal()
    kill = KillSwitch(tmp_path / "kill.json")
    kill.engage(GLOBAL, "halt")
    calls = []
    decision = authorize(
        action, policy=AutonomyPolicy(), kill_switch=kill,
        approval_check=lambda actual: calls.append(actual) or True,
    )
    assert decision.verdict is Verdict.DENY
    assert calls == []


def test_capability_denial_wins_before_receipt_check(tmp_path):
    action = _terminal()
    calls = []
    decision = authorize(
        action, capability=Capability(token_id="missing", name="terminal.exec"),
        capabilities=CapabilityBroker(), kill_switch=KillSwitch(tmp_path / "kill.json"),
        policy=AutonomyPolicy(),
        approval_check=lambda actual: calls.append(actual) or True,
    )
    assert decision.verdict is Verdict.DENY
    assert calls == []


def test_budget_denial_wins_before_receipt_check():
    action = _terminal()
    ledger = BudgetLedger(limits=BudgetLimits(max_tokens=5), tokens_used=6)
    calls = []
    decision = authorize(
        action, policy=AutonomyPolicy(), budget_ledger=ledger,
        approval_check=lambda actual: calls.append(actual) or True,
    )
    assert decision.verdict is Verdict.DENY
    assert calls == []


def test_loop_denial_wins_before_receipt_check():
    action = _terminal()
    detector = LoopDetector(max_repeats=1, window_seconds=60)
    assert detector.record(action.kind, now=10)
    calls = []
    decision = authorize(
        action, policy=AutonomyPolicy(), loop_detector=detector, now=10,
        approval_check=lambda actual: calls.append(actual) or True,
    )
    assert decision.verdict is Verdict.DENY
    assert calls == []


def test_bridge_forwards_trusted_callback_only_when_supplied():
    calls = []

    def kernel(*args, **kwargs):
        calls.append((args, kwargs))
        return authorize(*args, policy=AutonomyPolicy(), **kwargs)

    bridge = MediationKernelBridge(kernel)
    action = _terminal()
    assert bridge(action).verdict is Verdict.QUEUE
    assert calls[-1] == ((action,), {})
    assert bridge(action, approval_check=_approve_exact(action)).verdict is Verdict.GRANT
    assert calls[-1][0] == (action,)
    assert set(calls[-1][1]) == {"approval_check"}
    assert calls[-1][1]["approval_check"](action) is True
