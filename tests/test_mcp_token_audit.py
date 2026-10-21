"""H512: value-free lifecycle audit for locally signed MCP tokens."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents import web
from agents.core.mcp.oauth import MCPResourceServer
from agents.core.routers import mcp
from agents.core.security import auth_audit
from agents.core.security.audit import AuditLogger
from agents.core.security.token_store import TokenStore


@pytest.fixture
def rig(tmp_path, monkeypatch):
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    store = TokenStore(db_path=str(tmp_path / "tokens.db"))
    server = MCPResourceServer(secret="fixture-signing-secret")
    monkeypatch.setattr(auth_audit, "_active_sink", lambda: audit)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "fixture-admin-secret")
    monkeypatch.setattr(web, "get_token_store", lambda: store)
    monkeypatch.setattr(web, "_get_mcp_rs", lambda: server)
    monkeypatch.setattr(mcp, "get_orch", lambda: SimpleNamespace())
    app = FastAPI()
    app.include_router(mcp.router)
    yield SimpleNamespace(
        client=TestClient(app, raise_server_exceptions=False),
        audit=audit, server=server, store=store,
    )
    auth_audit.flush_pending()
    store.close()


def _token_rows(rig):
    auth_audit.flush_pending()
    assert rig.audit.verify_chain() == (True, None)
    return rig.audit.query(event_type="token_issued")


def test_successful_mcp_signing_adds_one_fixed_lifecycle_row(rig):
    subject = "private-subject-issuance-sentinel"
    scope = "private-scope-issuance-sentinel"
    response = rig.client.post(
        "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
        json={"subject": subject, "scopes": ["mcp", scope], "ttl": 120},
    )
    assert response.status_code == 200
    issued = response.json()
    assert issued["ok"] is True
    assert issued["scopes"] == ["mcp", scope]
    assert rig.server.validate(issued["token"], issued["resource"], required_scope="mcp")["ok"]
    rows = _token_rows(rig)
    assert len(rows) == 1
    assert rows[0].action_taken == "user:issue"
    assert json.loads(rows[0].content_preview) == {
        "tier": "user", "outcome": "success", "reason": "issue", "count": 1,
        "revoke_env": False, "surface": "mcp",
    }
    assert [row.event_type.value for row in rig.audit.query(limit=10)].count("auth_success") == 1
    stored = rig.audit._db_path.read_bytes()
    for private in (issued["token"], subject, scope, issued["resource"], "fixture-admin-secret"):
        assert private.encode() not in stored


def test_unsuccessful_mcp_issuance_adds_no_lifecycle_row(rig, monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    network_denied = rig.client.post("/api/mcp/token")
    assert network_denied.status_code == 403
    monkeypatch.setattr(web, "ADMIN_TOKEN", "fixture-admin-secret")
    denied = rig.client.post("/api/mcp/token", headers={"X-Admin-Token": "wrong-secret"})
    assert denied.status_code == 401
    missing = rig.client.post("/api/mcp/token")
    assert missing.status_code == 401
    for ttl in ("invalid-ttl", 0, -1):
        invalid = rig.client.post(
            "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
            json={"ttl": ttl},
        )
        assert invalid.status_code == 400
        assert invalid.json() == {"error": (
            "ttl must be an integer number of seconds" if ttl == "invalid-ttl"
            else "ttl must be positive"
        )}
    monkeypatch.setattr(mcp, "get_orch", lambda: None)
    unavailable = rig.client.post(
        "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
    )
    assert unavailable.status_code == 503
    monkeypatch.setattr(mcp, "get_orch", lambda: SimpleNamespace())

    class BrokenSigner:
        def issue_token(self, **_kwargs):
            raise RuntimeError("private-signing-error")

    monkeypatch.setattr(web, "_get_mcp_rs", lambda: BrokenSigner())
    failed = rig.client.post(
        "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
    )
    assert failed.status_code == 500
    assert _token_rows(rig) == []
    assert b"private-signing-error" not in rig.audit._db_path.read_bytes()


def test_audit_submit_exception_does_not_undo_signed_token(rig, monkeypatch, caplog):
    def broken_submit(*_args, **_kwargs):
        raise RuntimeError("private-submit-error")

    monkeypatch.setattr(mcp, "submit_auth_event", broken_submit)
    response = rig.client.post(
        "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
    )
    assert response.status_code == 200
    issued = response.json()
    assert rig.server.validate(issued["token"], issued["resource"])["ok"]
    assert _token_rows(rig) == []
    assert b"private-submit-error" not in rig.audit._db_path.read_bytes()
    assert "private-submit-error" not in caplog.text


def test_blocked_sink_does_not_hold_token_response_or_queue_private_values(rig, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class BlockedSink:
        def log(self, event):
            entered.set()
            assert release.wait(3)
            rig.audit.log(event)

    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BlockedSink())
    try:
        started = time.monotonic()
        response = rig.client.post(
            "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
            json={"subject": "private-queued-subject", "scopes": ["mcp"]},
        )
        assert time.monotonic() - started < 1
        assert response.status_code == 200
        assert entered.wait(1)
        queued = repr(list(auth_audit._queue.queue))
        assert "private-queued-subject" not in queued
        assert response.json()["token"] not in queued
        assert "fixture-admin-secret" not in queued
    finally:
        release.set()
    assert len(_token_rows(rig)) == 1


def test_saturated_or_failed_sink_does_not_change_issuance(rig, monkeypatch, caplog):
    entered = threading.Event()
    release = threading.Event()

    class BlockedSink:
        def log(self, _event):
            entered.set()
            assert release.wait(3)

    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BlockedSink())
    try:
        for _ in range(64):
            auth_audit.submit_auth_event("auth_failure", tier="admin", reason="missing")
        assert entered.wait(1)
        assert auth_audit._queue.unfinished_tasks == 64
        response = rig.client.post(
            "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
        )
        assert response.status_code == 200
        assert rig.server.validate(response.json()["token"], response.json()["resource"])["ok"]
        assert auth_audit._queue.unfinished_tasks == 64
    finally:
        release.set()
        auth_audit.flush_pending()

    class BrokenSink:
        def log(self, _event):
            raise RuntimeError("private-audit-error")

    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BrokenSink())
    response = rig.client.post(
        "/api/mcp/token", headers={"X-Admin-Token": "fixture-admin-secret"},
    )
    assert response.status_code == 200
    assert rig.server.validate(response.json()["token"], response.json()["resource"])["ok"]
    auth_audit.flush_pending()
    assert "private-audit-error" not in caplog.text
    assert response.json()["token"] not in caplog.text
