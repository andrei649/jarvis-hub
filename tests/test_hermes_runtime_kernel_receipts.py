"""Hermes uses the Kernel's existing trusted receipt seam, never payload authority."""

from dataclasses import replace

import pytest

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Action, Verdict, authorize, revalidate


def subject(task_id=19):
    return Action(kind="hermes.runtime", agent="hermes", title="Hermes rpc: shell.exec",
                  payload={"operation": "rpc", "target": "shell.exec",
                           "arguments": {"command": "true"}, "generation": "generation-1",
                           "risk_tier": 3, "approved_task_id": task_id})


@pytest.mark.parametrize("front_door", [authorize, revalidate])
def test_trusted_hermes_receipt_can_satisfy_only_its_exact_action(front_door):
    action = subject()
    checked = []

    def checker(actual):
        checked.append(actual)
        return actual == action

    decision = front_door(action, policy=AutonomyPolicy(), approval_check=checker)
    assert decision.verdict is Verdict.GRANT and decision.task_id == 19
    assert checked == [action]
    changed = replace(action, payload={**action.payload, "generation": "replacement"})
    assert front_door(changed, policy=AutonomyPolicy(), approval_check=checker).verdict is Verdict.QUEUE


@pytest.mark.parametrize("task_id", [None, True, 0, -1, "19"])
def test_payload_id_never_grants_hermes_authority(task_id):
    assert authorize(subject(task_id), policy=AutonomyPolicy()).verdict is Verdict.QUEUE


@pytest.mark.parametrize("mode", ["ask", "off"])
def test_owner_receipt_does_not_override_live_policy_hold(mode):
    checked = []
    decision = revalidate(subject(), policy=AutonomyPolicy(mode=mode),
                          approval_check=lambda action: checked.append(action) or True)
    assert decision.verdict is Verdict.QUEUE and checked == []


def test_hermes_approval_checker_failure_fails_closed():
    def unavailable(action):
        raise OSError("approval store unavailable")
    assert authorize(subject(), policy=AutonomyPolicy(), approval_check=unavailable).verdict is Verdict.QUEUE
