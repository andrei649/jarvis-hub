"""A live owner dispatch rechecks kernel floors without a second authorization."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core.autonomy.policy import ACT, AutonomyPolicy, RiskTier
from agents.core.autonomy.policy import Decision as PolicyDecision
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kernel import Action, BudgetLedger, BudgetLimits, LoopDetector, Verdict
from agents.core.kernel.binding import MediationKernelBridge, make_action_kernel
from agents.core.security.capability import KillSwitch


def _action():
    return Action(kind="terminal.exec", agent="jarvis", title="terminal on dev",
                  payload={"approved_task_id": 23, "target": "dev", "command": "printf ok"})


def _bound(tmp_path, *, loop=None, budget=None, policy=None, kill=None):
    policy = policy or AutonomyPolicy()
    kill = kill or KillSwitch(tmp_path / "kill.json")
    orch = SimpleNamespace(autonomy=SimpleNamespace(policy=policy), kill_switch=kill,
                           capabilities=None, intent_log=None)
    return make_action_kernel(orch, loop_detector=loop, budget_ledger=budget), policy, kill


def test_dispatch_rechecks_new_budget_without_accruing_loop_or_audit(tmp_path):
    loop = LoopDetector(max_repeats=1)
    budget = BudgetLedger(BudgetLimits(max_tokens=1))
    kernel, _, _ = _bound(tmp_path, loop=loop, budget=budget)
    action = _action()
    bridge = MediationKernelBridge(kernel)
    assert bridge(action, approval_check=lambda candidate: candidate is action).verdict is Verdict.GRANT
    count = len(loop._events)
    assert bridge.revalidate(action, approval_check=lambda candidate: candidate is action).verdict is Verdict.GRANT
    assert len(loop._events) == count
    budget.tokens_used = 2
    assert bridge.revalidate(action, approval_check=lambda candidate: candidate is action).verdict is Verdict.DENY
    assert len(loop._events) == count
    # Read-only dispatch revalidation cannot consume the broker's pending B7 handoff.
    assert bridge.consume(action).verdict is Verdict.GRANT


def test_dispatch_rechecks_tripped_loop_and_kill_switch(tmp_path):
    loop = LoopDetector(max_repeats=1)
    kernel, _, kill = _bound(tmp_path, loop=loop)
    action = _action()
    assert kernel(action, approval_check=lambda _: True).verdict is Verdict.GRANT
    assert loop.record(action.kind) is False
    count = len(loop._events)
    assert kernel.revalidate(action, approval_check=lambda _: True).verdict is Verdict.DENY
    assert len(loop._events) == count
    loop.reset()
    kill.engage(reason="emergency")
    assert kernel.revalidate(action, approval_check=lambda _: True).verdict is Verdict.DENY


@pytest.mark.parametrize("mode", ["ask", "off"])
def test_dispatch_rechecks_policy_mode_and_receipt(tmp_path, mode):
    kernel, policy, _ = _bound(tmp_path)
    action = _action()
    assert kernel(action, approval_check=lambda _: True).verdict is Verdict.GRANT
    policy.mode = mode
    assert kernel.revalidate(action, approval_check=lambda _: True).verdict is Verdict.QUEUE
    policy.mode = "auto"
    assert kernel.revalidate(action, approval_check=lambda _: False).verdict is Verdict.QUEUE


def test_dispatch_revalidation_fails_closed_on_unreadable_live_floor(tmp_path):
    kernel, _, kill = _bound(tmp_path)
    action = _action()
    assert kernel(action, approval_check=lambda _: True).verdict is Verdict.GRANT

    def unreadable(_scope):
        raise OSError("private store contents")

    kill.is_halted = unreadable
    denied = kernel.revalidate(action, approval_check=lambda _: True)
    assert denied.verdict is Verdict.DENY
    assert "private store contents" not in denied.reason


def test_terminal_dispatch_requires_sealed_receipt_even_if_policy_drifts_to_act(tmp_path):
    class MutablePolicy(AutonomyPolicy):
        force_act = False

        def decide(self, action):
            if self.force_act:
                return PolicyDecision(ACT, RiskTier.IRREVERSIBLE_OR_MONEY, "drift")
            return super().decide(action)

    policy = MutablePolicy()
    kernel, _, _ = _bound(tmp_path, policy=policy)
    action = _action()
    assert kernel(action, approval_check=lambda _: True).task_id == 23
    policy.force_act = True
    assert kernel.revalidate(action, approval_check=lambda _: False).verdict is not Verdict.GRANT


def test_worker_dispatch_uses_bound_revalidation_without_consuming_handoff(tmp_path):
    kernel, _, _ = _bound(tmp_path)
    bridge = MediationKernelBridge(kernel)
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue, kernel=bridge)
    action = _action()
    assert worker.kernel_gate(action, approval_check=lambda _: True).verdict is Verdict.GRANT
    assert worker.kernel_dispatch_current(action, approval_check=lambda _: True).verdict is Verdict.GRANT
    assert bridge.consume(action).verdict is Verdict.GRANT
    queue.close()


@pytest.mark.parametrize("primitive", ["policy", "kill_switch", "capabilities"])
def test_revalidation_refuses_replaced_bound_primitive(tmp_path, primitive):
    original_policy = AutonomyPolicy()
    original_kill = KillSwitch(tmp_path / "old-kill.json")
    original_capabilities = object()
    orch = SimpleNamespace(
        autonomy=SimpleNamespace(policy=original_policy), kill_switch=original_kill,
        capabilities=original_capabilities, intent_log=None,
    )
    kernel = make_action_kernel(orch)
    action = _action()
    assert kernel(action, approval_check=lambda _: True).verdict is Verdict.GRANT
    if primitive == "policy":
        orch.autonomy.policy = AutonomyPolicy(mode="ask")
    elif primitive == "kill_switch":
        orch.kill_switch = KillSwitch(tmp_path / "new-kill.json")
        orch.kill_switch.engage(reason="new emergency")
    else:
        orch.capabilities = object()
    # Existing broker authorization retains its original binding, while an
    # in-flight owner dispatch must refuse the replacement until rebound.
    assert kernel(action, approval_check=lambda _: True).verdict is Verdict.GRANT
    assert kernel.revalidate(action, approval_check=lambda _: True).verdict is Verdict.DENY


def test_revalidation_refuses_replaced_fallback_policy(tmp_path):
    orch = SimpleNamespace(
        autonomy=SimpleNamespace(policy=None), autonomy_policy=AutonomyPolicy(),
        kill_switch=KillSwitch(tmp_path / "kill.json"), capabilities=None, intent_log=None,
    )
    kernel = make_action_kernel(orch)
    action = _action()
    assert kernel.revalidate(action, approval_check=lambda _: True).verdict is Verdict.GRANT
    orch.autonomy_policy = AutonomyPolicy(mode="off")
    assert kernel.revalidate(action, approval_check=lambda _: True).verdict is Verdict.DENY
