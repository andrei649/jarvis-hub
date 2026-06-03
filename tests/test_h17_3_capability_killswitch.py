"""Tests for H17.3 — Capability gating + out-of-band kill-switch."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.security.capability import CapabilityBroker, KillSwitch, authorize


# ── capability tokens ────────────────────────────────────────────────────────

def test_token_grants_only_listed_capabilities():
    b = CapabilityBroker()
    tok = b.issue(["read_email"], source="task1")
    assert b.check(tok["id"], "read_email") is True
    assert b.check(tok["id"], "send_email") is False     # not granted → no escalation


def test_token_expires():
    b = CapabilityBroker()
    tok = b.issue(["read_email"], ttl=100, now=1000)
    assert b.check(tok["id"], "read_email", now=1050) is True
    assert b.check(tok["id"], "read_email", now=1101) is False   # expired


def test_token_revoke_and_unknown():
    b = CapabilityBroker()
    tok = b.issue(["x"])
    assert b.revoke(tok["id"]) is True
    assert b.check(tok["id"], "x") is False
    assert b.check("nonexistent", "x") is False


# ── kill-switch ──────────────────────────────────────────────────────────────

def test_kill_switch_scopes_and_persistence(tmp_path):
    p = tmp_path / "k.json"
    k = KillSwitch(path=p)
    assert k.is_halted("agentX") is False
    k.engage("agentX", reason="went rogue")
    assert k.is_halted("agentX") is True
    assert k.is_halted("agentY") is False              # scoped
    # global halt halts everything
    k.engage("global")
    assert k.is_halted("agentY") is True
    # survives reload
    assert KillSwitch(path=p).is_halted("agentY") is True
    assert k.disengage("global") is True
    assert k.disengage("global") is False


# ── authorize (combined gate) ────────────────────────────────────────────────

def test_authorize_matrix(tmp_path):
    b = CapabilityBroker()
    k = KillSwitch(path=tmp_path / "k.json")
    tok = b.issue(["send_email"], source="task1")

    # valid token, not halted → allowed
    assert authorize(b, k, tok["id"], "send_email")["allowed"] is True
    # capability not granted → blocked
    assert authorize(b, k, tok["id"], "delete_file")["allowed"] is False
    # kill-switch engaged → blocked even with a valid token
    k.engage("global", reason="halt")
    blocked = authorize(b, k, tok["id"], "send_email")
    assert blocked["allowed"] is False and "kill-switch" in blocked["reason"]


# ── endpoints ────────────────────────────────────────────────────────────────

def test_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    hdr = {"X-Admin-Token": "test-secret"}
    try:
        with TestClient(web.app) as c:
            if getattr(web.orch, "capabilities", None) is None:
                return
            web.orch.kill_switch.disengage("global")
            # minting requires admin
            assert c.post("/api/security/capabilities/issue",
                          json={"capabilities": ["read_email"]}).status_code == 401
            issued = c.post("/api/security/capabilities/issue",
                            json={"capabilities": ["read_email"]}, headers=hdr)
            assert issued.status_code == 200
            tid = issued.json()["token"]["id"]
            # check is read-only (no admin needed)
            chk = c.get("/api/security/capabilities/check",
                        params={"token": tid, "capability": "read_email"})
            assert chk.json()["allowed"] is True
            # engage kill-switch (admin) → check now blocked
            assert c.post("/api/security/kill-switch", json={"engage": True}).status_code == 401
            c.post("/api/security/kill-switch", json={"engage": True, "scope": "global"}, headers=hdr)
            chk2 = c.get("/api/security/capabilities/check",
                         params={"token": tid, "capability": "read_email"})
            assert chk2.json()["allowed"] is False
            web.orch.kill_switch.disengage("global")
    finally:
        web.ADMIN_TOKEN = old
