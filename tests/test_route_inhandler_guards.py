"""H511 — prove every credential that is checked inside a handler body.

The route-auth matrix (test_route_auth_matrix.py) reads guards from the resolved
dependency graph, so a credential checked *inside* a handler classifies as
"open" and was carried by a hand-written allowlist entry nobody exercised. Here
every IN_HANDLER_GUARDED / WS_GUARDED_IN_HANDLER entry gets a probe against the
live app:

* without the credential the route refuses (401/403 — or the route's documented
  non-leaking refusal: 404 for a capability URL, 400 for an OAuth state);
* with the credential the same request gets past that check, so the refusal is
  proved to come from the named guard and not from a disabled surface.

A new entry in either map without a probe fails test_every_entry_has_a_probe.
"""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_route_auth_matrix import IN_HANDLER_GUARDED, WS_GUARDED_IN_HANDLER

ADMIN = "synthetic-h511-owner"


class _Tokens:
    def verify(self, token):
        return None

    def env_revoked(self, scope):
        return False

    def list_tokens(self):
        return []


class _Orch:
    def __init__(self, **settings):
        self._settings = settings
        self.widgets = None

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)


@pytest.fixture
def client(monkeypatch):
    """The real app with an admin credential configured (so nothing rides the
    localhost dev bypass) and no lifespan — each probe stubs only what it needs."""
    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", ADMIN)
    monkeypatch.setattr(web, "get_token_store", lambda: _Tokens())
    return TestClient(web.app, base_url="http://127.0.0.1")


# ── HTTP probes: each returns (unauthenticated response, credentialed response) ──

def _probe_webhook(client, monkeypatch):
    from agents.core.routers import webhooks

    class Store:
        hooks = {"plain": {"signed": False}, "signed": {"signed": True}}

        def get(self, hook_id):
            return self.hooks.get(hook_id)

        def verify(self, hook_id, token):
            return token == "hook-secret"

        def verify_signature(self, hook_id, raw, signature):
            return signature == "sha256=good"

        def is_enabled(self, hook):
            return False   # past the credential, stop before anything runs

    async def no_refusal():
        return None

    monkeypatch.setattr(webhooks, "get_orch", lambda: _Orch())
    monkeypatch.setattr(webhooks, "_receiver_refusal", no_refusal)
    monkeypatch.setattr(webhooks, "_get_webhook_store", lambda: Store())
    signed = client.post("/api/webhooks/signed", json={})
    assert signed.status_code == 401 and "signature" in signed.json()["error"]
    assert client.post("/api/webhooks/signed", json={},
                       headers={"x-signature-256": "sha256=good"}).json()["error"] == "webhook disabled"
    return (client.post("/api/webhooks/plain", json={}),
            client.post("/api/webhooks/plain", json={}, headers={"x-webhook-token": "hook-secret"}))


def _probe_a2a(client, monkeypatch):
    from agents.core import a2a
    from agents.core.routers import a2a as a2a_router

    class Registry:
        def verify_peer(self, peer_id, raw, signature):
            return peer_id == "peer" and signature == "sha256=good"

        def receive_task(self, peer_id, raw, signature):
            if not self.verify_peer(peer_id, raw, signature):
                raise PermissionError("rejected")
            return {"id": "t1", "status": "pending", "accepted": True}

    monkeypatch.setattr(a2a, "a2a_enabled", lambda: True)
    monkeypatch.setattr(a2a_router, "_get_a2a_registry", lambda: Registry())
    return (client.post("/api/a2a/task", json={"task": "x"}, headers={"x-a2a-peer": "peer"}),
            client.post("/api/a2a/task", json={"task": "x"},
                        headers={"x-a2a-peer": "peer", "x-signature-256": "sha256=good"}))


def _probe_mcp_rpc(client, monkeypatch):
    from agents import web
    from agents.core.routers import mcp

    class Server:
        async def handle(self, message, identity=None):
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"identity": identity}}

    monkeypatch.setattr(mcp, "get_orch", lambda: _Orch(**{"mcp.server_enabled": True}))
    monkeypatch.setattr(web, "_user_credential_required", lambda: True)
    monkeypatch.setattr(web, "_build_mcp_server", lambda: Server())
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    return (client.post("/api/mcp/server/rpc", json=rpc),
            client.post("/api/mcp/server/rpc", json=rpc, headers={"x-admin-token": ADMIN}))


def _probe_oauth_callback(client, monkeypatch):
    from agents.core.routers import oauth

    real_verify = oauth.verify_state

    async def exchange(code, state):
        return {"access_token": "a"}

    # The unauthenticated call runs the real verify_state against a state this hub
    # never minted; the credentialed call stands in a minted one.
    monkeypatch.setattr(oauth, "verify_state", lambda s: "spotify" if s == "minted" else real_verify(s))
    monkeypatch.setattr(oauth, "exchange_spotify_code", exchange)
    return (client.post("/api/oauth/callback", json={"code": "c", "state": "forged"}),
            client.post("/api/oauth/callback", json={"code": "c", "state": "minted"}))


def _widget_orch(monkeypatch):
    from agents.core.routers import secrets

    class Widgets:
        def get(self, token):
            return {"token": token} if token == "good" else None

    orch = _Orch()
    orch.widgets = Widgets()
    monkeypatch.setattr(secrets, "get_orch", lambda: orch)


def _probe_widget_message(client, monkeypatch):
    from agents.core import app_state

    class Gateway:
        async def route(self, message, channel=None):
            return "hello"

    _widget_orch(monkeypatch)
    monkeypatch.setattr(app_state, "get_gateway", lambda: Gateway())
    return (client.post("/api/widget/guess/message", json={"message": "hi"}),
            client.post("/api/widget/good/message", json={"message": "hi"}))


def _probe_widget_snippet(client, monkeypatch):
    _widget_orch(monkeypatch)
    return client.get("/api/widget/guess"), client.get("/api/widget/good")


def _probe_widget_config(client, monkeypatch):
    _widget_orch(monkeypatch)
    return client.get("/api/widget/guess/config"), client.get("/api/widget/good/config")


# Route -> (probe, refusal statuses). A capability URL answers an unknown token
# with 404 so it never confirms a token exists; a forged OAuth state is a 400.
HTTP_PROBES = {
    "POST /api/webhooks/{hook_id}": (_probe_webhook, {401}),
    "POST /api/a2a/task": (_probe_a2a, {401}),
    "POST /api/mcp/server/rpc": (_probe_mcp_rpc, {401}),
    "POST /api/oauth/callback": (_probe_oauth_callback, {400}),
    "POST /api/widget/{token}/message": (_probe_widget_message, {404}),
    "GET /api/widget/{token}": (_probe_widget_snippet, {404}),
    "GET /api/widget/{token}/config": (_probe_widget_config, {404}),
}


def test_every_entry_has_a_probe():
    assert set(HTTP_PROBES) == set(IN_HANDLER_GUARDED), (
        "IN_HANDLER_GUARDED and HTTP_PROBES disagree — every in-handler guard needs a probe: "
        f"{sorted(set(HTTP_PROBES) ^ set(IN_HANDLER_GUARDED))}")
    assert set(WS_PROBES) == set(WS_GUARDED_IN_HANDLER), (
        "WS_GUARDED_IN_HANDLER and WS_PROBES disagree: "
        f"{sorted(set(WS_PROBES) ^ set(WS_GUARDED_IN_HANDLER))}")


@pytest.mark.parametrize("route", sorted(HTTP_PROBES))
def test_in_handler_guard_refuses_without_credential(route, client, monkeypatch):
    probe, refusal = HTTP_PROBES[route]
    denied, allowed = probe(client, monkeypatch)
    assert denied.status_code in refusal, f"{route} answered {denied.status_code} without its credential"
    assert allowed.status_code not in refusal, (
        f"{route} still refused ({allowed.status_code}) WITH its credential — the probe "
        "did not isolate the in-handler check")


def test_in_handler_guards_admit_the_credential(client, monkeypatch):
    """The credentialed half reaches the handler's work, not just a different error."""
    # A webhook's next gate after its credential is the enable switch (stubbed off).
    assert _probe_webhook(client, monkeypatch)[1].json()["error"] == "webhook disabled"
    assert _probe_a2a(client, monkeypatch)[1].json()["accepted"] is True
    assert _probe_mcp_rpc(client, monkeypatch)[1].json()["result"]["identity"] == ADMIN
    assert _probe_oauth_callback(client, monkeypatch)[1].json() == {
        "ok": True, "service": "spotify", "has_refresh": False}
    assert _probe_widget_message(client, monkeypatch)[1].json() == {"reply": "hello"}


# ── WebSocket probes ──────────────────────────────────────────────────────────

class _FakeHermes:
    async def status(self):
        return {"ready": False}


def _ws_setup_hermes(monkeypatch):
    from agents.core.routers import hermes_runtime

    monkeypatch.setattr(hermes_runtime, "_service", lambda: _FakeHermes())


WS_PROBES = {
    "WS /api/kanban/events": ("/api/kanban/events", lambda mp: None),
    "WS /api/hermes/ws": ("/api/hermes/ws", _ws_setup_hermes),
}


def _spy_admin_guard(monkeypatch):
    """Record every admin_guard verdict reached through the routers' lazy wrapper."""
    from agents import web

    real = web._admin_guard
    verdicts = []

    async def spy(request):
        try:
            await real(request)
        except Exception as exc:
            verdicts.append(getattr(exc, "status_code", None))
            raise
        verdicts.append("ok")

    monkeypatch.setattr(web, "_admin_guard", spy)
    return verdicts


@pytest.mark.parametrize("route", sorted(WS_PROBES))
def test_websocket_in_handler_guard_refuses_unauthenticated(route, client, monkeypatch):
    path, setup = WS_PROBES[route]
    setup(monkeypatch)
    verdicts = _spy_admin_guard(monkeypatch)
    with pytest.raises(WebSocketDisconnect) as caught, client.websocket_connect(path):
        pass
    assert caught.value.code == 1008
    assert verdicts == [401], f"{route} closed, but not because admin_guard refused: {verdicts}"
    # The same upgrade with the owner credential passes that guard; the stubbed
    # surface (disabled Kanban, unready Hermes) then closes it before accept().
    verdicts.clear()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(path, headers={"x-admin-token": ADMIN}):
        pass
    assert verdicts == ["ok"], f"{route} did not admit the owner credential: {verdicts}"
    assert WS_GUARDED_IN_HANDLER[route] == "admin"
