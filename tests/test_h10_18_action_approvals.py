"""Tests for H10.18 — Action-Level Approval."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.action_approvals import ActionApprovalQueue


# ── request / decide ─────────────────────────────────────────────────────────

def test_request_creates_pending_with_preview():
    q = ActionApprovalQueue()
    item = q.request({"tool": "send_email", "args": {"to": "x@y.com"},
                      "agent": "pepper", "risk_tier": 2})
    assert item["status"] == "pending" and item["tool"] == "send_email"
    assert item["preview"]["irreversible"] is True       # send_* flagged via H12.5
    assert q.stats()["pending"] == 1


def test_decide_approve_and_reject():
    q = ActionApprovalQueue()
    a = q.request({"tool": "t1"})
    b = q.request({"tool": "t2"})
    assert q.decide(a["id"], True)["status"] == "approved"
    assert q.decide(b["id"], False, by="andrei")["status"] == "rejected"
    assert q.decide(b["id"], False)["decided_by"] == "andrei"   # idempotent, keeps first
    assert q.decide("missing", True) is None
    s = q.stats()
    assert s["approved"] == 1 and s["rejected"] == 1 and s["pending"] == 0


def test_list_filters_by_status():
    q = ActionApprovalQueue()
    a = q.request({"tool": "t1"})
    q.request({"tool": "t2"})
    q.decide(a["id"], True)
    assert len(q.list("pending")) == 1 and len(q.list("approved")) == 1


# ── await_decision (blocking tool flow) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_await_decision_unblocks_on_approve():
    q = ActionApprovalQueue()
    item = q.request({"tool": "deploy"})

    async def approve_soon():
        await asyncio.sleep(0.01)
        q.decide(item["id"], True)

    asyncio.create_task(approve_soon())
    status = await q.await_decision(item["id"], timeout=1.0)
    assert status == "approved"


@pytest.mark.asyncio
async def test_await_decision_times_out():
    q = ActionApprovalQueue()
    item = q.request({"tool": "deploy"})
    assert await q.await_decision(item["id"], timeout=0.02) == "timeout"


@pytest.mark.asyncio
async def test_await_already_decided_returns_immediately():
    q = ActionApprovalQueue()
    item = q.request({"tool": "x"})
    q.decide(item["id"], False)
    assert await q.await_decision(item["id"], timeout=0.01) == "rejected"


# ── endpoints ────────────────────────────────────────────────────────────────

def test_action_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    hdr = {"X-Admin-Token": "test-secret"}
    try:
        with TestClient(web.app) as c:
            if getattr(web.orch, "action_approvals", None) is None:
                return
            web.orch.action_approvals.clear()
            assert c.post("/api/actions/request", json={}).status_code == 400
            req = c.post("/api/actions/request",
                         json={"tool": "transfer", "args": {"amount": 100}})
            assert req.status_code == 200
            aid = req.json()["action"]["id"]
            assert len(c.get("/api/actions/pending").json()["actions"]) == 1
            # decide is admin-guarded
            assert c.post(f"/api/actions/{aid}/decide", json={"approved": True}).status_code == 401
            ok = c.post(f"/api/actions/{aid}/decide", json={"approved": True}, headers=hdr)
            assert ok.status_code == 200 and ok.json()["action"]["status"] == "approved"
            assert c.get("/api/actions").json()["stats"]["approved"] == 1
    finally:
        web.ADMIN_TOKEN = old
