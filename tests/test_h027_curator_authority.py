"""H027 uses live kernel floors even when the optional global hook is off."""

from types import SimpleNamespace

import pytest

from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.security.capability import KillSwitch


class _Audit:
    def __init__(self):
        self.actions = []

    def record(self, actor, action, why, metadata=None):
        self.actions.append(action)


@pytest.mark.parametrize("flag", ["0", "1"])
@pytest.mark.parametrize("operation,kind,tier,expected", [
    ("pause", "skill.generation", 1, "grant"),
    ("purge", "skill.install", 3, "queue"),
])
def test_live_curator_kernel_rechecks_halt_and_binding(monkeypatch, tmp_path, flag,
                                                      operation, kind, tier, expected):
    from agents.core.skills.curator_authority import curator_authorize

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", flag)
    audit = _Audit()
    orch = SimpleNamespace(autonomy_policy=AutonomyPolicy(), capabilities=None,
                           kill_switch=KillSwitch(tmp_path / "halt.json"), intent_log=audit)
    authorize = curator_authorize(orch)
    payload = {"kind": kind, "operation": operation, "risk_tier": tier,
               "preview_fingerprint": "a" * 64, "targets": []}
    assert authorize(payload) == expected
    # Replacing the hub's halt object revokes a callback created before the edit.
    stopped = KillSwitch(tmp_path / "new-halt.json")
    stopped.engage(reason="owner halt")
    orch.kill_switch = stopped
    assert authorize(payload) == "deny"
    assert audit.actions == [f"authorize:{kind}", f"authorize:{kind}"]


@pytest.mark.parametrize("origin", ["inbound", "recall:untrusted"])
def test_curator_callback_never_resolves_untrusted_origin_as_owner(origin):
    from agents.core.skills.curator_authority import curator_authorize

    token = bind_action_origin(origin)
    try:
        assert curator_authorize(SimpleNamespace())({
            "kind": "skill.generation", "operation": "pin", "risk_tier": 1}) == "deny"
    finally:
        reset_action_origin(token)


@pytest.mark.parametrize("payload", [
    {"kind": "skill.curator.purge", "operation": "purge", "risk_tier": 3},
    {"kind": "skill.install", "operation": "purge", "risk_tier": 1},
    {"kind": "skill.install", "operation": "purge", "risk_tier": True},
    {"kind": "skill.generation", "operation": "unknown", "risk_tier": 1},
    {"kind": "skill.generation", "operation": "pin", "risk_tier": 0},
    {"kind": [], "operation": "pin", "risk_tier": 1},
    {"kind": "skill.generation", "operation": [], "risk_tier": 1},
])
def test_curator_callback_cannot_downgrade_or_invent_authority(payload):
    from agents.core.skills.curator_authority import curator_authorize

    assert curator_authorize(SimpleNamespace())(payload) == "error"


def test_curator_callback_refuses_missing_policy_and_tainted_claim():
    from agents.core.skills.curator_authority import curator_authorize

    authorize = curator_authorize(SimpleNamespace())
    payload = {"kind": "skill.generation", "operation": "pin", "risk_tier": 1}
    assert authorize(payload) == "error"
    assert authorize({**payload, "tainted": True}) == "deny"


def test_approved_curator_failure_is_named_and_never_discloses_private_error(monkeypatch):
    from fastapi.testclient import TestClient

    import agents.web as web
    from agents.core.autonomy.action_approvals import ActionApprovalQueue

    class BrokenOperations:
        def apply_decision(self, card_id, *, authorize):
            raise OSError("private-owner-path-and-credential")

    approvals = ActionApprovalQueue()
    card = approvals.request({"tool": "skill.curator.pin", "args": {"request_id": "test"}})
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    monkeypatch.setattr(web, "orch", SimpleNamespace(
        action_approvals=approvals, curator_operations=BrokenOperations()))
    response = TestClient(web.app).post(f"/api/actions/{card['id']}/decide",
                                        json={"approved": True},
                                        headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 503
    assert response.json()["action"]["applied"]["reason"] == "curator_apply_unavailable"
    assert "private-owner" not in response.text
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
