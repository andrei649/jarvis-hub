"""The bounded chat/session discovery document is a protocol contract, not readiness."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from weakref import WeakKeyDictionary

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import analytics

_ROUTES = {
    ("POST", "/chat"),
    ("POST", "/chat/stream"),
    ("GET", "/sessions"),
    ("POST", "/sessions/resume"),
    ("DELETE", "/sessions/{session_id}"),
}


def _descriptor():
    response = TestClient(web.app).get("/v1/capabilities")
    assert response.status_code == 200
    return response.json()


def test_descriptor_is_narrow_and_separate_from_readiness(monkeypatch):
    def no_orch_probe():
        raise AssertionError("protocol discovery must not probe readiness")

    monkeypatch.setattr(analytics, "get_orch", no_orch_probe)
    payload = _descriptor()
    assert payload["descriptor_schema"] == 1
    assert payload["protocol_version"] is None
    assert payload["server_version"] == web.app.version
    assert {(row["method"], row["path"]) for row in payload["routes"]} == _ROUTES
    assert payload["readiness"] == {"href": "/api/capabilities", "auth": "user"}
    assert payload["auth"]["user"]["headers"] == ["X-User-Token", "X-Admin-Token"]
    assert payload["auth"]["admin"]["headers"] == ["X-Admin-Token"]
    assert "capabilities" not in payload
    assert "harness_pending" not in payload

    monkeypatch.setattr(analytics, "get_orch", lambda: object())
    from agents.core.observability import capability_registry
    monkeypatch.setattr(capability_registry, "snapshot", lambda _orch: {"readiness_marker": True})
    assert TestClient(web.app).get("/api/capabilities").json() == {"readiness_marker": True}
    legacy = TestClient(web.app).get("/v1")
    assert legacy.status_code == 200
    assert "text/html" in legacy.headers["content-type"]


def test_openapi_schemas_media_and_handler_gaps_are_honest():
    payload = _descriptor()
    source = web.app.openapi()
    routes = {(row["method"], row["path"]): row for row in payload["routes"]}
    for (method, path), row in routes.items():
        assert path in source["paths"] and method.lower() in source["paths"][path]
        assert row["parameters"] == source["paths"][path][method.lower()].get("parameters", [])
    chat = routes[("POST", "/chat")]
    stream = routes[("POST", "/chat/stream")]
    assert chat["request"]["media_type"] == "application/json"
    assert chat["request"]["required"] is True
    assert chat["request"]["schema"] == {"$ref": "#/components/schemas/ChatRequest"}
    assert chat["response"]["schema"] == {"$ref": "#/components/schemas/ChatResponse"}
    assert stream["request"] == chat["request"]
    assert stream["response"]["media_type"] == "text/event-stream"
    assert stream["response"]["source"] == "handler"
    assert set(stream["stream_events"]) == {"start", "token", "end"}
    assert {"text", "session_id", "pending_approvals", "warming", "notices"}.issubset(
        stream["stream_events"]["end"]
    )
    schemas = payload["components"]["schemas"]
    assert set(schemas) == {"ChatRequest", "ChatResponse", "TurnNotice", "TurnOutcome"}
    assert schemas["ChatRequest"] == source["components"]["schemas"]["ChatRequest"]
    assert schemas["ChatResponse"] == source["components"]["schemas"]["ChatResponse"]
    assert schemas["TurnNotice"] == source["components"]["schemas"]["TurnNotice"]
    assert schemas["ChatRequest"]["additionalProperties"] is False
    assert "model" not in schemas["ChatRequest"]["properties"]
    assert "provider" not in schemas["ChatRequest"]["properties"]
    assert routes[("POST", "/sessions/resume")]["request"]["source"] == "handler"
    assert routes[("POST", "/sessions/resume")]["request"]["required"] is True
    assert routes[("POST", "/sessions/resume")]["request"]["schema"]["required"] == ["session_id"]
    assert routes[("GET", "/sessions")]["response"]["schema"]["properties"]["sessions"]["type"] == "array"
    assert routes[("DELETE", "/sessions/{session_id}")]["response"]["schema"]["required"] == [
        "ok", "session", "backup", "removed", "pruned",
    ]

    def refs(value):
        if isinstance(value, dict):
            found = {value["$ref"]} if "$ref" in value else set()
            for item in value.values():
                found.update(refs(item))
            return found
        if isinstance(value, list):
            return set().union(*(refs(item) for item in value))
        return set()

    for ref in refs(payload["routes"]) | refs(schemas):
        # Emitted OpenAPI pointers resolve against this descriptor itself.
        assert ref.startswith("#/")
        target = payload
        for segment in ref[2:].split("/"):
            target = target[segment]
        assert isinstance(target, dict)


def test_per_route_auth_session_and_replay_facts():
    payload = _descriptor()
    routes = {(row["method"], row["path"]): row for row in payload["routes"]}
    assert {key: row["auth"] for key, row in routes.items()} == {
        key: "admin" if key == ("DELETE", "/sessions/{session_id}") else "user"
        for key in _ROUTES
    }
    assert routes[("GET", "/sessions")]["semantics"]["limit"] == 20
    assert routes[("GET", "/sessions")]["semantics"]["archived_default"] is False
    assert routes[("POST", "/sessions/resume")]["semantics"]["may_unarchive"] is True
    assert routes[("POST", "/sessions/resume")]["semantics"]["sets_active_session"] is True
    assert payload["compatibility"]["session_header"] is None
    assert payload["compatibility"]["chat_session_id"] == "optional JSON body field"
    assert payload["compatibility"]["chat_session_id_returned_in"] == "/chat response body or /chat/stream end event"
    assert payload["compatibility"]["chat_model_override"] is False
    assert payload["compatibility"]["chat_provider_override"] is False
    assert payload["compatibility"]["chat_message_must_be_nonblank"] is True
    assert payload["compatibility"]["explicit_session_hydrated_before_turn"] is True
    assert payload["compatibility"]["idempotency_key_supported"] is False
    assert "GET" not in payload["compatibility"]["idempotency_key_note"]
    user_auth = payload["auth"]["user"]
    admin_auth = payload["auth"]["admin"]
    for auth in (user_auth, admin_auth):
        assert "persisted revocation marker" in auth["when_configured"]
        assert "in-process" in auth["when_configured"]
        assert "without a revocation marker" in auth["local_fallback"]
    assert "admin credential alone" in user_auth["admin_only_configuration"]


def test_user_guard_and_admin_superset_are_enforced_on_discovery(monkeypatch):
    from agents.core.routers._deps import user_guard

    web.app.dependency_overrides.pop(user_guard, None)
    monkeypatch.setattr(web, "_user_credential_required", lambda: True)
    monkeypatch.setattr(
        web, "_user_credential_ok",
        lambda user_supplied="", admin_supplied="": (
            user_supplied == "user-test-token" or admin_supplied == "admin-test-token"
        ),
    )
    client = TestClient(web.app)
    assert client.get("/v1/capabilities").status_code == 401
    assert client.get("/v1/capabilities", headers={"X-User-Token": "wrong-test-token"}).status_code == 401
    assert client.get("/v1/capabilities", headers={"X-User-Token": "user-test-token"}).status_code == 200
    assert client.get("/v1/capabilities", headers={"X-Admin-Token": "admin-test-token"}).status_code == 200
    body = client.get("/v1/capabilities", headers={"X-Admin-Token": "admin-test-token"}).text
    for secret in ("user-test-token", "admin-test-token", "wrong-test-token"):
        assert secret not in body

    monkeypatch.setattr(web, "_admin_configured", lambda: True)
    monkeypatch.setattr(web, "_admin_credential_ok", lambda token: token == "admin-test-token")
    assert client.delete("/sessions/example", headers={"X-User-Token": "user-test-token"}).status_code == 401
    # The admin guard passes; the existing handler then refuses missing ?confirm=DELETE.
    assert client.delete("/sessions/example", headers={"X-Admin-Token": "admin-test-token"}).status_code == 400

    # The user guard tests its own configured predicate first. An admin-only
    # configured remote client does not bypass the localhost user posture.
    monkeypatch.setattr(web, "_user_credential_required", lambda: False)
    assert client.get("/v1/capabilities", headers={"X-Admin-Token": "admin-test-token"}).status_code == 403


def test_revoked_sole_issued_token_history_can_disappear_after_restart(monkeypatch, tmp_path):
    from agents.core.security.token_store import TokenStore

    db_path = str(tmp_path / "tokens.db")
    store = TokenStore(db_path=db_path)
    monkeypatch.setattr(web, "_user_env_token", lambda: "")
    monkeypatch.setattr(web, "get_token_store", lambda: store)
    monkeypatch.setattr(web, "_CONFIGURED_SCOPES", WeakKeyDictionary())
    store.issue("user")
    assert web._user_credential_required() is True
    store.revoke_all("user", revoke_env=False)
    assert web._user_credential_required() is True  # positive process memo
    store.close()

    reopened = TokenStore(db_path=db_path)
    try:
        monkeypatch.setattr(web, "get_token_store", lambda: reopened)
        monkeypatch.setattr(web, "_CONFIGURED_SCOPES", WeakKeyDictionary())
        assert web._user_credential_required() is False
        reopened.revoke_all("user", revoke_env=True)
        assert web._user_credential_required() is True  # persistent marker
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_delete_descriptor_includes_actual_orphan_outcomes_success(monkeypatch):
    from agents.core import session_archive

    @asynccontextmanager
    async def lease(_session_id):
        yield True

    async def missing_session(*_args, **_kwargs):
        raise session_archive.SessionDeleteError("not_found")

    monkeypatch.setattr(session_archive, "delete_session", missing_session)
    orch = SimpleNamespace(
        session_id="another",
        turn_lease=lease,
        checkpoints=SimpleNamespace(clock_snapshot=lambda _sid: None),
        autonomy_queue=SimpleNamespace(purge_chat_outcomes=lambda _sid: 2),
    )
    result = await session_archive.delete_leased(orch, "orphan", prune=False)
    assert result == {
        "ok": True, "session": "orphan", "backup": None,
        "removed": {"chat_approval_outcomes": 2}, "pruned": [],
    }
    row = next(row for row in _descriptor()["routes"] if row["path"] == "/sessions/{session_id}")
    backup_schema = row["response"]["schema"]["properties"]["backup"]
    assert backup_schema == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert "requires_existing_session" not in row["semantics"]
    assert row["semantics"]["orphan_outcomes_cleanup_without_session"] is True


def test_unmounted_routes_are_not_advertised():
    from fastapi import FastAPI

    from agents.core.client_protocol import describe_client_protocol

    small = FastAPI(version="test-release")

    @small.post("/chat")
    def _chat():
        return {}

    result = describe_client_protocol(small)
    assert [(row["method"], row["path"]) for row in result["routes"]] == [("POST", "/chat")]
    assert result["server_version"] == "test-release"
    assert result["components"] == {"schemas": {}}
