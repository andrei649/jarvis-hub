"""Tests for H12.11 — Extended escalation channels."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.escalation import EscalationRouter, render_escalation


class _FakeChannel:
    def __init__(self, ok=True, boom=False):
        self.ok = ok
        self.boom = boom
        self.sent = []

    async def send(self, message, **kwargs):
        if self.boom:
            raise RuntimeError("channel down")
        self.sent.append(message)
        return self.ok


def _channels():
    return {"telegram": _FakeChannel(), "slack": _FakeChannel(), "discord": _FakeChannel()}


# ── rendering ────────────────────────────────────────────────────────────────

def test_render_escalation_plain_text():
    msg = render_escalation({"id": 7, "title": "Send report", "agent": "pepper",
                             "kind": "send_email", "risk_tier": 2,
                             "payload": {"to": "boss@x.com"}})
    assert "#7" in msg and "Send report" in msg and "Preview:" in msg


# ── governed targeting ───────────────────────────────────────────────────────

def test_targets_default_all():
    r = EscalationRouter(_channels())
    assert r.targets() == ["discord", "slack", "telegram"]


def test_targets_allowlist():
    r = EscalationRouter(_channels(), allow=["slack", "telegram"])
    assert r.targets() == ["slack", "telegram"]      # discord excluded by allowlist


def test_targets_requested_intersect_allow():
    r = EscalationRouter(_channels(), allow=["slack", "telegram"])
    assert r.targets(["discord", "slack"]) == ["slack"]   # discord not allowed


# ── delivery ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_escalate_delivers_to_allowed():
    chans = _channels()
    r = EscalationRouter(chans, allow=["slack", "telegram"])
    out = await r.escalate("alert!")
    assert set(out["delivered"]) == {"slack", "telegram"}
    assert chans["discord"].sent == []               # not allowed → never sent
    assert chans["slack"].sent == ["alert!"]


@pytest.mark.asyncio
async def test_escalate_best_effort_on_failure():
    chans = {"good": _FakeChannel(ok=True), "bad": _FakeChannel(boom=True)}
    out = await EscalationRouter(chans).escalate("x")
    assert out["delivered"] == ["good"] and out["failed"] == ["bad"]


# ── endpoints ────────────────────────────────────────────────────────────────

def test_escalation_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    try:
        with TestClient(web.app) as c:
            assert c.get("/api/autonomy/escalation/targets").status_code == 200
            # admin-guarded send
            assert c.post("/api/autonomy/escalate", json={"message": "hi"}).status_code == 401
            r = c.post("/api/autonomy/escalate", json={"message": "hi"},
                       headers={"X-Admin-Token": "test-secret"})
            assert r.status_code == 200 and "delivered" in r.json()
            assert c.post("/api/autonomy/escalate", json={},
                          headers={"X-Admin-Token": "test-secret"}).status_code == 400
    finally:
        web.ADMIN_TOKEN = old
