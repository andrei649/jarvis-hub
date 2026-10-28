"""Provider installation through the real, locally bound Action Kernel."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Verdict
from agents.core.kernel.binding import make_action_kernel
from agents.core.llm.providers.packages import ProviderPackageError
from agents.core.security.capability import KillSwitch
from tests.test_h361_provider_install_service import owner, service, staged


def _bind_real_kernel(service, tmp_path):
    svc, _, _, _ = service
    policy = AutonomyPolicy()
    kill = KillSwitch(tmp_path / "provider-kill.json")
    orch = SimpleNamespace(
        autonomy=SimpleNamespace(policy=policy),
        kill_switch=kill,
        capabilities=None,
        intent_log=None,
    )
    seen = []

    def kernel():
        bound = make_action_kernel(orch)
        if bound is None:
            return None

        def authorize(action, *, approval_check):
            decision = bound(action, approval_check=approval_check)
            seen.append((action, decision))
            return decision

        return authorize

    svc.kernel = kernel
    return svc, orch, kill, seen


def _approve(svc, preview):
    offer = svc.propose(preview["artifact_id"], actor=owner())
    svc.decide(
        offer["proposal_id"],
        artifact_id=preview["artifact_id"],
        package_hash=preview["package_hash"],
        approved=True,
        permanent=True,
        actor=owner(),
    )
    return offer


def test_pending_proposal_never_reaches_real_kernel_or_active_inventory(service, tmp_path):
    svc, _, _, seen = _bind_real_kernel(service, tmp_path)
    preview = staged(service)
    offer = svc.propose(preview["artifact_id"], actor=owner())

    with pytest.raises(ProviderPackageError, match="permanent owner approval"):
        svc.promote(offer["proposal_id"], actor=owner())
    assert seen == []
    assert svc._store().list_active(home=svc.home) == ()


def test_permanent_exact_owner_approval_grants_real_tier_three_kernel(service, tmp_path):
    svc, _, _, seen = _bind_real_kernel(service, tmp_path)
    preview = staged(service)
    offer = _approve(svc, preview)
    assert seen == []

    active = svc.promote(offer["proposal_id"], actor=owner())
    assert active["status"] == "active"
    record = svc._store().require_runnable(
        "synthetic-addon", expected_hash=preview["package_hash"], home=svc.home
    )
    assert record.package_hash == preview["package_hash"]
    assert [(action.payload["phase"], decision.verdict, decision.tier)
            for action, decision in seen] == [
                ("promote", Verdict.GRANT, 3),
                ("execute", Verdict.GRANT, 3),
            ]
    assert all(decision.task_id is None for _, decision in seen)
    assert all(action.scope == "provider:synthetic-addon" and
               action.payload["package_hash"] == preview["package_hash"] and
               action.payload["permanent"] is True and
               action.payload["irreversible"] is True
               for action, _ in seen)


def test_real_kernel_requires_exact_receipt_and_valid_contract(service, tmp_path):
    svc, orch, _, seen = _bind_real_kernel(service, tmp_path)
    preview = staged(service)
    offer = _approve(svc, preview)
    svc.promote(offer["proposal_id"], actor=owner())
    action = seen[-1][0]
    bound = make_action_kernel(orch)

    # Package-provided approval-looking fields have no independent authority.
    assert action.payload["permanent"] is True
    assert action.payload["package_hash"] == preview["package_hash"]
    assert bound(action).verdict is Verdict.QUEUE
    assert bound(action, approval_check=lambda _: False).verdict is Verdict.QUEUE

    # The receipt is for the whole Action, including its provider scope.
    wrong_scope = replace(action, scope="provider:another-addon")
    assert bound(wrong_scope, approval_check=lambda candidate: candidate == action).verdict \
        is Verdict.QUEUE

    # A callable alone cannot bypass the provider-load contract.
    bad_payload = deepcopy(action.payload)
    bad_payload["package_hash"] = "not-a-signed-hash"
    malformed = replace(action, payload=bad_payload)
    assert bound(malformed, approval_check=lambda _: True).verdict is Verdict.QUEUE

    for mode in ("ask", "off"):
        orch.autonomy.policy.mode = mode
        assert bound(action, approval_check=lambda candidate: candidate == action).verdict \
            is Verdict.QUEUE


def test_live_scoped_kill_switch_blocks_promotion_and_execution(service, tmp_path):
    svc, _, kill, seen = _bind_real_kernel(service, tmp_path)
    preview = staged(service)
    offer = _approve(svc, preview)

    kill.engage("provider:synthetic-addon", reason="synthetic halt")
    with pytest.raises(ProviderPackageError, match="kernel did not grant"):
        svc.promote(offer["proposal_id"], actor=owner())
    assert seen[-1][1].verdict is Verdict.DENY
    assert svc._store().list_active(home=svc.home) == ()

    kill.disengage("provider:synthetic-addon")
    svc.promote(offer["proposal_id"], actor=owner())
    kill.engage("provider:synthetic-addon", reason="synthetic runtime halt")
    with pytest.raises(ProviderPackageError, match="kernel did not grant"):
        svc._store().require_runnable(
            "synthetic-addon", expected_hash=preview["package_hash"], home=svc.home
        )
    assert seen[-1][0].payload["phase"] == "execute"
    assert seen[-1][1].verdict is Verdict.DENY


def test_kernel_flag_off_refuses_promotion_before_invoking_bound_kernel(
    service, tmp_path, monkeypatch
):
    svc, _, _, seen = _bind_real_kernel(service, tmp_path)
    preview = staged(service)
    offer = _approve(svc, preview)

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
    with pytest.raises(ProviderPackageError, match="kernel authority unavailable"):
        svc.promote(offer["proposal_id"], actor=owner())
    assert seen == []
    assert svc._store().list_active(home=svc.home) == ()


def test_missing_bound_policy_refuses_promotion(service, tmp_path):
    svc, orch, _, seen = _bind_real_kernel(service, tmp_path)
    preview = staged(service)
    offer = _approve(svc, preview)

    orch.autonomy.policy = None
    with pytest.raises(ProviderPackageError, match="kernel did not grant"):
        svc.promote(offer["proposal_id"], actor=owner())
    assert seen == []
    assert svc._store().list_active(home=svc.home) == ()
