"""Value-free audit at the MCP transport's own authentication boundary."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from agents.core.mcp.server import VerifiedMCPIdentity
from agents.core.routers import mcp
from agents.core.security import auth_audit
from agents.core.security.audit import AuditLogger

_MESSAGE = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "body": "rpc-body-secret"}


def _request(headers=None, host="10.0.0.9"):
    return Request({
        "type": "http", "method": "POST", "scheme": "http",
        "path": "/api/mcp/server/rpc", "server": ("127.0.0.1", 8123),
        "client": (host, 34567),
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
    })


@pytest.fixture
def rig(tmp_path, monkeypatch):
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    monkeypatch.setattr(auth_audit, "_active_sink", lambda: audit)
    seen = []

    class Server:
        async def handle(self, message, *, identity):
            seen.append((message, identity))
            return {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}

    settings = {"mcp.server_enabled": True, "mcp.oauth_required": False}
    orch = SimpleNamespace(get_setting=lambda name, default=None: settings.get(name, default))
    web = SimpleNamespace(
        _user_credential_required=lambda: True,
        _request_is_authed=lambda req: req.headers.get("x-user-token") == "user-secret"
        or req.headers.get("x-admin-token") == "admin-secret",
        _real_client_host=lambda req: req.client.host,
        _LOCALHOSTS={"127.0.0.1", "::1"},
        _build_mcp_server=lambda: Server(),
        _get_mcp_rs=lambda: SimpleNamespace(validate=lambda token, *_args, **_kwargs: (
            {"ok": True, "claims": {"sub": "oauth-subject-secret"}} if token == "Bearer oauth-secret"
            else {"ok": True, "claims": {"sub": ""}} if token == "Bearer blank-sub"
            else {"ok": False, "error": "validation-error-secret"}
        )),
    )
    monkeypatch.setattr(mcp, "get_orch", lambda: orch)
    monkeypatch.setattr(mcp, "_web", lambda: web)
    yield SimpleNamespace(audit=audit, settings=settings, web=web, seen=seen)
    auth_audit.flush_pending()


def _rows(rig):
    auth_audit.flush_pending()
    rows = [row for row in rig.audit.query(limit=100) if row.event_type.value.startswith("auth_")]
    assert rig.audit.verify_chain() == (True, None)
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "status", "kind", "reason", "identity"),
    [
        ({"x-user-token": "user-secret"}, 200, "auth_success", "credential", "user-secret"),
        ({"x-admin-token": "admin-secret"}, 200, "auth_success", "credential", "admin-secret"),
        ({"x-user-token": "wrong-secret"}, 401, "auth_failure", "invalid", None),
        ({}, 401, "auth_failure", "missing", None),
    ],
)
async def test_legacy_credential_decision_emits_one_mcp_row(
    rig, headers, status, kind, reason, identity
):
    response = await mcp.mcp_server_rpc(_MESSAGE, _request(headers))
    assert response.status_code == status
    assert [item[1] for item in rig.seen] == ([] if identity is None else [identity])
    rows = _rows(rig)
    assert len(rows) == 1
    assert rows[0].event_type.value == kind
    assert rows[0].action_taken == f"user:{reason}"
    assert json.loads(rows[0].content_preview) == {
        "tier": "user", "outcome": "success" if status == 200 else "failure",
        "reason": reason, "client": "10.0.0.9", "surface": "mcp",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("host", "status", "kind", "reason"),
    [
        ("127.0.0.1", 200, "auth_success", "local_bypass"),
        ("10.0.0.9", 403, "auth_failure", "network_disabled"),
    ],
)
async def test_unconfigured_legacy_locality_is_audited(rig, host, status, kind, reason):
    rig.web._user_credential_required = lambda: False
    response = await mcp.mcp_server_rpc(_MESSAGE, _request(host=host))
    assert response.status_code == status
    assert len(rig.seen) == (1 if status == 200 else 0)
    rows = _rows(rig)
    assert len(rows) == 1
    assert rows[0].event_type.value == kind
    assert rows[0].action_taken == f"user:{reason}"
    assert json.loads(rows[0].content_preview)["client"] == host


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorization", "status", "reason"),
    [
        ("Bearer oauth-secret", 200, "credential"),
        ("Bearer blank-sub", 401, "invalid"),
        ("Bearer invalid-secret", 401, "invalid"),
        ("", 401, "missing"),
    ],
)
async def test_oauth_transport_decision_keeps_challenge_and_verified_identity(
    rig, authorization, status, reason
):
    rig.settings["mcp.oauth_required"] = True
    headers = {"Authorization": authorization} if authorization else {}
    response = await mcp.mcp_server_rpc(_MESSAGE, _request(headers))
    assert response.status_code == status
    if status == 401:
        assert response.headers["WWW-Authenticate"].startswith('Bearer resource_metadata="')
        assert rig.seen == []
    else:
        assert len(rig.seen) == 1
        assert rig.seen[0][0] == _MESSAGE
        assert isinstance(rig.seen[0][1], VerifiedMCPIdentity)
        assert rig.seen[0][1].subject == "oauth-subject-secret"
    rows = _rows(rig)
    assert len(rows) == 1
    assert rows[0].event_type.value == ("auth_success" if status == 200 else "auth_failure")
    assert rows[0].action_taken == f"user:{reason}"
    assert json.loads(rows[0].content_preview)["surface"] == "mcp"
    stored = rig.audit._db_path.read_bytes()
    for sentinel in (b"oauth-secret", b"oauth-subject-secret", b"rpc-body-secret", b"validation-error-secret"):
        assert sentinel not in stored


@pytest.mark.asyncio
@pytest.mark.parametrize("initialized,enabled,status", [(False, True, 503), (True, False, 403)])
async def test_unavailable_or_disabled_server_is_not_an_auth_decision(
    rig, monkeypatch, initialized, enabled, status
):
    if not initialized:
        monkeypatch.setattr(mcp, "get_orch", lambda: None)
    rig.settings["mcp.server_enabled"] = enabled
    response = await mcp.mcp_server_rpc(_MESSAGE, _request())
    assert response.status_code == status
    assert _rows(rig) == []
    assert rig.seen == []


@pytest.mark.asyncio
async def test_failed_sink_and_secret_error_leave_auth_outcome_unchanged(rig, monkeypatch, caplog):
    class BrokenSink:
        def log(self, _event):
            raise RuntimeError("sink-error-secret")

    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BrokenSink())
    with caplog.at_level(logging.WARNING):
        denied = await mcp.mcp_server_rpc(_MESSAGE, _request({"x-user-token": "wrong-secret"}))
        allowed = await mcp.mcp_server_rpc(_MESSAGE, _request({"x-user-token": "user-secret"}))
        rig.settings["mcp.oauth_required"] = True
        oauth_denied = await mcp.mcp_server_rpc(
            _MESSAGE, _request({"Authorization": "Bearer invalid-secret"})
        )
        auth_audit.flush_pending()
    assert (denied.status_code, allowed.status_code, oauth_denied.status_code) == (401, 200, 401)
    assert [item[1] for item in rig.seen] == ["user-secret"]
    assert "sink-error-secret" not in caplog.text
    assert "wrong-secret" not in caplog.text
    assert "validation-error-secret" not in caplog.text
    assert "invalid-secret" not in caplog.text
    assert "rpc-body-secret" not in caplog.text


@pytest.mark.asyncio
async def test_blocked_sink_cannot_delay_mcp_or_capture_secret_fields(rig, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    captured = []

    class BlockedSink:
        def log(self, event):
            captured.append(event)
            entered.set()
            assert release.wait(3)

    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BlockedSink())
    try:
        started = time.monotonic()
        denied = await asyncio.wait_for(
            mcp.mcp_server_rpc(_MESSAGE, _request({"x-user-token": "wrong-secret"})), 1
        )
        assert time.monotonic() - started < 1
        assert denied.status_code == 401
        assert entered.wait(1)
        started = time.monotonic()
        allowed = await asyncio.wait_for(
            mcp.mcp_server_rpc(_MESSAGE, _request({"x-user-token": "user-secret"})), 1
        )
        assert time.monotonic() - started < 1
        assert allowed.status_code == 200
        rig.settings["mcp.oauth_required"] = True
        oauth_allowed = await asyncio.wait_for(
            mcp.mcp_server_rpc(_MESSAGE, _request({"Authorization": "Bearer oauth-secret"})), 1
        )
        oauth_denied = await asyncio.wait_for(
            mcp.mcp_server_rpc(_MESSAGE, _request({"Authorization": "Bearer invalid-secret"})), 1
        )
        assert (oauth_allowed.status_code, oauth_denied.status_code) == (200, 401)
        queued_items = list(auth_audit._queue.queue)
        assert queued_items
        assert all(
            set(fields) == {"tier", "reason", "client", "count", "revoke_env", "sink", "surface"}
            and fields["surface"] == "mcp"
            for _kind, fields, _submitted_at in queued_items
        )
        queued = repr(queued_items)
        for secret in (
            "wrong-secret", "user-secret", "oauth-secret", "oauth-subject-secret",
            "invalid-secret", "validation-error-secret", "rpc-body-secret",
        ):
            assert secret not in queued
            assert all(secret not in event.content_preview for event in captured)
    finally:
        release.set()
        auth_audit.flush_pending()


def test_surface_is_exact_literal_only_and_existing_events_omit_it(rig):
    class Poison:
        def __str__(self):
            raise AssertionError("surface value must not be converted")

        def __eq__(self, _other):
            raise AssertionError("surface value must not be compared")

    auth_audit.submit_auth_event(
        "auth_failure", tier="user", reason="invalid", surface=Poison(),
        token="queued-token-secret", arbitrary="queued-payload-secret",
    )
    auth_audit.record_auth_event(
        "auth_success", tier="user", reason="credential", surface="mcp",
        token="direct-token-secret",
    )
    auth_audit.record_auth_event(
        "auth_success", tier="user", reason="credential", surface="MCP",
    )
    auth_audit.record_auth_event(
        "token_issued", tier="user", reason="issue", surface="mcp",
    )
    auth_audit.submit_auth_event(
        "token_issued", tier="user", reason="issue", surface="mcp",
    )
    auth_audit.submit_auth_event(
        "token_issued", tier="user", reason="issue", surface=Poison(),
    )
    auth_audit.record_auth_event(
        "token_issued", tier="user", reason="issue", surface="MCP",
    )
    auth_audit.record_auth_event("token_issued", tier="user", reason="issue")
    auth_audit.record_auth_event(
        "token_rotated", tier="user", reason="rotate", surface="mcp",
    )
    auth_audit.record_auth_event(
        "token_revoked", tier="user", reason="revoke", surface="mcp",
    )
    auth_audit.flush_pending()
    rows = rig.audit.query(limit=100)
    previews = [json.loads(row.content_preview) for row in rows]
    assert len(previews) == 10
    assert sum(item.get("surface") == "mcp" for item in previews) == 3
    issued = [json.loads(row.content_preview) for row in rows
              if row.event_type.value == "token_issued"]
    assert sum(item.get("surface") == "mcp" for item in issued) == 2
    assert all("surface" not in item for item in previews
               if item["reason"] in ("rotate", "revoke"))
    assert rig.audit.verify_chain() == (True, None)
    stored = rig.audit._db_path.read_bytes()
    for secret in (b"queued-token-secret", b"queued-payload-secret", b"direct-token-secret"):
        assert secret not in stored
