"""H511 — prove every credential that is checked inside a handler body.

The route-auth matrix (test_route_auth_matrix.py) reads guards from the resolved
dependency graph, so a credential checked *inside* a handler classifies as
"open" (or, for a step-up, as the weaker dependency tier) and was carried by a
hand-written allowlist entry nobody exercised. Here every IN_HANDLER_GUARDED /
WS_GUARDED_IN_HANDLER / IN_HANDLER_STEP_UP entry gets a probe against the live app:

* without the credential the route refuses (401/403 — or the route's documented
  non-leaking refusal: 404 for a capability URL, 400 for an OAuth state);
* with the credential the same request gets past that check and reaches the
  handler's work, so the refusal is proved to come from the named guard and not
  from a disabled surface.

The probes use the hub's real verifiers (WebhookStore, A2ARegistry, the OAuth
state minted by the plugin, MCPResourceServer, WidgetStore) on a temporary data
dir, so deleting a verification line in any of them fails a probe here.

A new entry in any map without a probe fails test_every_entry_has_a_probe, and a
pinned in-body call site (IN_HANDLER_GUARD_SITES / IN_HANDLER_TIER_SITES) whose
named probe does not exist fails test_every_pinned_site_names_a_live_probe. The
tier-decision probes below cover the sites no older test proved (each was checked
by forcing the site's decision and watching the probe fail).
"""
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_route_auth_matrix import (
    IN_HANDLER_GUARDED,
    IN_HANDLER_STEP_UP,
    WS_GUARDED_IN_HANDLER,
)

ADMIN = "synthetic-h511-owner"
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIi"
       "cLsAAAAAElFTkSuQmCC")


class _Tokens:
    """No issued tokens; the env admin token is live until `revoked` flips (the
    effect of `token_recover.py rotate admin`)."""

    revoked = False

    def verify(self, token):
        return None

    def env_revoked(self, scope):
        return self.revoked and scope == "admin"

    def list_tokens(self):
        return []


class _Orch:
    def __init__(self, **settings):
        self._settings = settings
        self.widgets = None

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)


@pytest.fixture
def tokens():
    return _Tokens()


@pytest.fixture
def client(monkeypatch, tokens):
    """The real app with an admin credential configured (so nothing rides the
    localhost dev bypass) and no lifespan — each probe stubs only what it needs."""
    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", ADMIN)
    monkeypatch.setattr(web, "get_token_store", lambda: tokens)
    return TestClient(web.app, base_url="http://127.0.0.1")


# ── HTTP probes: each returns (unauthenticated response, credentialed response) ──

def _real_webhook_store(monkeypatch, tmp_path):
    """The hub's own WebhookStore on a temp file: a plain hook and a signed hook,
    both switched off so a delivery that authenticates stops before anything runs."""
    from agents.core.routers import webhooks
    from agents.core.webhooks import WebhookStore

    async def no_refusal():
        return None

    store = WebhookStore(tmp_path / "webhooks.json")
    plain = store.create("jarvis", name="h511-plain")
    signed = store.create("jarvis", name="h511-signed", signed=True)
    store.set_enabled(plain["id"], False)
    store.set_enabled(signed["id"], False)
    monkeypatch.setattr(webhooks, "get_orch", lambda: _Orch())
    monkeypatch.setattr(webhooks, "_receiver_refusal", no_refusal)
    monkeypatch.setattr(webhooks, "_get_webhook_store", lambda: store)
    return plain, signed


def _probe_webhook(client, monkeypatch, tmp_path):
    plain, signed = _real_webhook_store(monkeypatch, tmp_path)
    body = b'{"event": "h511"}'
    hdr = {"content-type": "application/json"}
    good_sig = "sha256=" + hmac.new(signed["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    bad = client.post(f"/api/webhooks/{signed['id']}", content=body,
                      headers={**hdr, "x-signature-256": "sha256=" + "0" * 64})
    assert bad.status_code == 401 and "signature" in bad.json()["error"]
    ok = client.post(f"/api/webhooks/{signed['id']}", content=body, headers={**hdr, "x-signature-256": good_sig})
    assert ok.json()["error"] == "webhook disabled", ok.text
    assert client.post(f"/api/webhooks/{plain['id']}", content=body,
                       headers={**hdr, "x-webhook-token": "not-the-token"}).status_code == 401
    return (client.post(f"/api/webhooks/{plain['id']}", content=body, headers=hdr),
            client.post(f"/api/webhooks/{plain['id']}", content=body,
                        headers={**hdr, "x-webhook-token": plain["token"]}))


def _probe_a2a(client, monkeypatch, tmp_path):
    """The real A2ARegistry: an allowlisted peer, a body signed with its secret."""
    from agents.core import a2a
    from agents.core.routers import a2a as a2a_router

    monkeypatch.setenv("JARVIS_A2A_ENABLED", "1")
    registry = a2a.A2ARegistry(tmp_path / "a2a.json", identity_secret="h511-identity")  # nosec
    secret = "h511-peer-secret"  # nosec
    registry.add_peer("peer", secret=secret, name="h511")
    monkeypatch.setattr(a2a_router, "_get_a2a_registry", lambda: registry)
    body = json.dumps({"task": "h511 probe"}).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    hdr = {"content-type": "application/json", "x-a2a-peer": "peer"}
    assert client.post("/api/a2a/task", content=body,
                       headers={**hdr, "x-signature-256": "sha256=" + "0" * 64}).status_code == 401
    assert client.post("/api/a2a/task", content=body,
                       headers={**hdr, "x-a2a-peer": "stranger", "x-signature-256": sig}).status_code == 401
    return (client.post("/api/a2a/task", content=body, headers=hdr),
            client.post("/api/a2a/task", content=body, headers={**hdr, "x-signature-256": sig}))


class _McpServer:
    async def handle(self, message, identity=None):
        who = getattr(identity, "subject", identity)
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"identity": who}}


def _probe_mcp_rpc(client, monkeypatch, tmp_path):
    """OAuth off: the HF-1 user/admin token posture."""
    from agents import web
    from agents.core.routers import mcp

    monkeypatch.setattr(mcp, "get_orch", lambda: _Orch(**{"mcp.server_enabled": True}))
    monkeypatch.setattr(web, "_user_credential_required", lambda: True)
    monkeypatch.setattr(web, "_build_mcp_server", lambda: _McpServer())
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    return (client.post("/api/mcp/server/rpc", json=rpc),
            client.post("/api/mcp/server/rpc", json=rpc, headers={"x-admin-token": ADMIN}))


def _probe_mcp_rpc_oauth(client, monkeypatch, tmp_path):
    """OAuth on: a bearer from the real MCPResourceServer, bound to this resource."""
    from agents import web
    from agents.core.mcp.oauth import MCPResourceServer
    from agents.core.routers import mcp

    rs = MCPResourceServer(secret="h511-rs-secret")  # nosec
    resource = "http://127.0.0.1/api/mcp/server"
    monkeypatch.setattr(mcp, "get_orch", lambda: _Orch(**{"mcp.server_enabled": True,
                                                         "mcp.oauth_required": True}))
    monkeypatch.setattr(web, "_mcp_rs", rs)
    monkeypatch.setattr(web, "_build_mcp_server", lambda: _McpServer())
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    forged = MCPResourceServer(secret="someone-else").issue_token("owner", resource, ["mcp"])  # nosec
    assert client.post("/api/mcp/server/rpc", json=rpc,
                       headers={"authorization": f"Bearer {forged}"}).status_code == 401
    other_resource = rs.issue_token("owner", "http://elsewhere/api/mcp/server", ["mcp"])
    assert client.post("/api/mcp/server/rpc", json=rpc,
                       headers={"authorization": f"Bearer {other_resource}"}).status_code == 401
    # Even the owner's admin header does not stand in for the bearer in this posture.
    assert client.post("/api/mcp/server/rpc", json=rpc, headers={"x-admin-token": ADMIN}).status_code == 401
    good = rs.issue_token("owner", resource, ["mcp"])
    return (client.post("/api/mcp/server/rpc", json=rpc),
            client.post("/api/mcp/server/rpc", json=rpc, headers={"authorization": f"Bearer {good}"}))


def _probe_oauth_callback(client, monkeypatch, tmp_path):
    """A state minted by the hub's own auth-url path vs one it never minted."""
    from agents.core.routers import oauth

    async def exchange(code, state):
        return {"access_token": "a"}  # nosec

    monkeypatch.setattr(oauth, "exchange_spotify_code", exchange)   # no network
    url = oauth.get_spotify_auth_url()
    minted = parse_qs(urlsplit(url).query)["state"][0]
    denied = client.post("/api/oauth/callback", json={"code": "c", "state": "spotify:forged"})
    allowed = client.post("/api/oauth/callback", json={"code": "c", "state": minted})
    # A minted state is single-use: replaying it is refused like a forged one.
    assert client.post("/api/oauth/callback", json={"code": "c", "state": minted}).status_code == 400
    return denied, allowed


def _real_widgets(monkeypatch, tmp_path):
    from agents.core.routers import secrets
    from agents.core.widget import WidgetStore

    store = WidgetStore(tmp_path / "widgets.json")
    cfg = store.issue({"title": "H511 probe widget"})
    revoked = store.issue({})
    store.revoke(revoked["token"])
    orch = _Orch()
    orch.widgets = store
    monkeypatch.setattr(secrets, "get_orch", lambda: orch)
    return cfg["token"], revoked["token"]


def _probe_widget_message(client, monkeypatch, tmp_path):
    from agents.core import app_state

    class Gateway:
        async def route(self, message, channel=None):
            return "hello"

    token, revoked = _real_widgets(monkeypatch, tmp_path)
    monkeypatch.setattr(app_state, "get_gateway", lambda: Gateway())
    assert client.post(f"/api/widget/{revoked}/message", json={"message": "hi"}).status_code == 404
    return (client.post("/api/widget/guess/message", json={"message": "hi"}),
            client.post(f"/api/widget/{token}/message", json={"message": "hi"}))


def _probe_widget_snippet(client, monkeypatch, tmp_path):
    token, revoked = _real_widgets(monkeypatch, tmp_path)
    assert client.get(f"/api/widget/{revoked}").status_code == 404
    return client.get("/api/widget/guess"), client.get(f"/api/widget/{token}")


def _probe_widget_config(client, monkeypatch, tmp_path):
    token, revoked = _real_widgets(monkeypatch, tmp_path)
    assert client.get(f"/api/widget/{revoked}/config").status_code == 404
    return client.get("/api/widget/guess/config"), client.get(f"/api/widget/{token}/config")


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

# Routes whose in-handler credential has more than one posture: each extra posture
# named in IN_HANDLER_GUARDED gets its own probe.
EXTRA_POSTURE_PROBES = {
    "POST /api/mcp/server/rpc [oauth]": (_probe_mcp_rpc_oauth, {401}),
}


def test_every_entry_has_a_probe():
    assert set(HTTP_PROBES) == set(IN_HANDLER_GUARDED), (
        "IN_HANDLER_GUARDED and HTTP_PROBES disagree — every in-handler guard needs a probe: "
        f"{sorted(set(HTTP_PROBES) ^ set(IN_HANDLER_GUARDED))}")
    assert set(WS_PROBES) == set(WS_GUARDED_IN_HANDLER), (
        "WS_GUARDED_IN_HANDLER and WS_PROBES disagree: "
        f"{sorted(set(WS_PROBES) ^ set(WS_GUARDED_IN_HANDLER))}")
    assert set(STEP_UP_PROBES) == set(IN_HANDLER_STEP_UP), (
        "IN_HANDLER_STEP_UP and STEP_UP_PROBES disagree: "
        f"{sorted(set(STEP_UP_PROBES) ^ set(IN_HANDLER_STEP_UP))}")


@pytest.mark.parametrize("route", sorted(HTTP_PROBES) + sorted(EXTRA_POSTURE_PROBES))
def test_in_handler_guard_refuses_without_credential(route, client, monkeypatch, tmp_path):
    probe, refusal = {**HTTP_PROBES, **EXTRA_POSTURE_PROBES}[route]
    denied, allowed = probe(client, monkeypatch, tmp_path)
    assert denied.status_code in refusal, f"{route} answered {denied.status_code} without its credential"
    assert allowed.status_code not in refusal, (
        f"{route} still refused ({allowed.status_code}) WITH its credential — the probe "
        "did not isolate the in-handler check")


def test_in_handler_guards_admit_the_credential(client, monkeypatch, tmp_path):
    """The credentialed half reaches the handler's work, not just a different error."""
    # A webhook's next gate after its credential is the enable switch (switched off).
    assert _probe_webhook(client, monkeypatch, tmp_path)[1].json()["error"] == "webhook disabled"
    receipt = _probe_a2a(client, monkeypatch, tmp_path)[1].json()
    assert receipt["accepted"] is True and receipt["status"] == "pending"
    assert _probe_mcp_rpc(client, monkeypatch, tmp_path)[1].json()["result"]["identity"] == ADMIN
    assert _probe_mcp_rpc_oauth(client, monkeypatch, tmp_path)[1].json()["result"]["identity"] == "owner"
    assert _probe_oauth_callback(client, monkeypatch, tmp_path)[1].json() == {
        "ok": True, "service": "spotify", "has_refresh": False}
    assert _probe_widget_message(client, monkeypatch, tmp_path)[1].json() == {"reply": "hello"}
    snippet = _probe_widget_snippet(client, monkeypatch, tmp_path)[1]
    assert snippet.headers["content-type"].startswith("application/javascript")
    assert "H511 probe widget" in snippet.text
    config = _probe_widget_config(client, monkeypatch, tmp_path)[1].json()
    assert config["title"] == "H511 probe widget" and config["token"]


# ── Guard spies ───────────────────────────────────────────────────────────────

def _spy_guards(monkeypatch):
    """Record every admin/user guard verdict reached through the routers' lazy
    wrappers, per tier."""
    from agents import web

    verdicts = {"admin": [], "user": []}
    for tier, name in (("admin", "_admin_guard"), ("user", "_user_guard")):
        real = getattr(web, name)

        def make(real, log):
            async def spy(request):
                try:
                    await real(request)
                except Exception as exc:
                    log.append(getattr(exc, "status_code", None))
                    raise
                log.append("ok")
            return spy

        monkeypatch.setattr(web, name, make(real, verdicts[tier]))
    return verdicts


# ── Step-up probes: a user-tier route that demands the owner for part of its input ──

_PREPARED = {"prompt": "what is this", "images": [PNG], "expected_destination": "local",
             "expected_binding": "0" * 64, "review_token": "r" * 24}
STEP_UP_PROBES = {
    "POST /api/vlm/composer/prepare": (
        "/api/vlm/composer/prepare",
        {"prompt": "what is this", "selected_turn": True, "image_digests": ["0" * 64]},
        {"prompt": "what is this"}),
    "POST /api/vlm/composer/describe-prepared": (
        "/api/vlm/composer/describe-prepared", {**_PREPARED, "selected_turn": True}, _PREPARED),
    "POST /api/vlm/composer/chat-prepared": (
        "/api/vlm/composer/chat-prepared", {**_PREPARED, "selected_turn": True}, _PREPARED),
}


@pytest.mark.parametrize("route", sorted(STEP_UP_PROBES))
def test_step_up_refuses_a_user_tier_caller(route, client, monkeypatch):
    """The user tier passes (conftest admits it); selected_turn=true then demands the
    admin credential in the handler — refused without it, admitted with it — and a
    non-selected body never asks for it."""
    path, selected, plain = STEP_UP_PROBES[route]
    verdicts = _spy_guards(monkeypatch)
    denied = client.post(path, json=selected)
    assert denied.status_code == 401, f"{route} answered {denied.status_code} to a user-tier selected turn"
    assert verdicts["admin"] == [401], verdicts
    verdicts["admin"].clear()
    allowed = client.post(path, json=selected, headers={"x-admin-token": ADMIN})
    assert allowed.status_code not in (401, 403), allowed.text
    assert verdicts["admin"][0] == "ok", verdicts
    verdicts["admin"].clear()
    client.post(path, json=plain)
    assert verdicts["admin"] == [], f"{route} demanded the owner for a non-selected body"


# ── WebSocket probes ──────────────────────────────────────────────────────────

class _FakeHermes:
    """`pushed` (a thread-safe queue.Queue) feeds the event stream from the test
    thread; without it the stream never yields."""

    def __init__(self, ready=False, pushed=None):
        self.ready = ready
        self.pushed = pushed

    async def status(self):
        return {"ready": self.ready}

    async def events(self):
        import asyncio
        import queue

        if self.pushed is None:
            await asyncio.Event().wait()
        while True:
            try:
                yield self.pushed.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)

    async def rpc(self, method, params):
        return {"ok": True}

    async def reply(self, frame):
        return None


def _ws_setup_hermes(monkeypatch, live=False):
    from agents.core.routers import hermes_runtime

    service = _FakeHermes(ready=live)
    monkeypatch.setattr(hermes_runtime, "_service", lambda: service)


def _ws_setup_kanban(monkeypatch, live=False):
    if not live:
        return
    from agents.core.kanban import dashboard_api
    from agents.core.routers import kanban

    class Tail:
        def __init__(self, board):
            pass

        async def latest(self):
            return 0

        async def poll(self, cursor):
            return cursor, []

        async def shutdown(self):
            return None

    monkeypatch.setattr(kanban, "get_orch", lambda: _Orch(**{"llm.kanban": True}))
    monkeypatch.setattr(dashboard_api, "_EventTail", Tail)


WS_PROBES = {
    "WS /api/kanban/events": ("/api/kanban/events", _ws_setup_kanban),
    "WS /api/hermes/ws": ("/api/hermes/ws", _ws_setup_hermes),
}


@pytest.mark.parametrize("route", sorted(WS_PROBES))
def test_websocket_in_handler_guard_refuses_unauthenticated(route, client, monkeypatch):
    path, setup = WS_PROBES[route]
    tier = WS_GUARDED_IN_HANDLER[route]
    other = "user" if tier == "admin" else "admin"
    setup(monkeypatch)
    verdicts = _spy_guards(monkeypatch)
    with pytest.raises(WebSocketDisconnect) as caught, client.websocket_connect(path):
        pass
    assert caught.value.code == 1008
    assert verdicts[tier] == [401], f"{route} closed, but not because its {tier} guard refused: {verdicts}"
    assert verdicts[other] == [], f"{route} consulted the {other} guard: {verdicts}"
    # The same upgrade with the owner credential passes that guard; the stubbed
    # surface (disabled Kanban, unready Hermes) then closes it before accept().
    verdicts[tier].clear()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(path, headers={"x-admin-token": ADMIN}):
        pass
    assert verdicts[tier] == ["ok"], f"{route} did not admit the owner credential: {verdicts}"


@pytest.mark.timeout(20)   # a dropped re-check leaves the stream open: fail, never hang
@pytest.mark.parametrize("route", sorted(WS_PROBES))
def test_websocket_closes_when_credential_is_revoked_mid_stream(route, client, monkeypatch, tokens):
    """The per-frame re-check: an accepted stream whose credential is revoked
    (env admin token rotated) closes with 1008 on the next guard pass."""
    path, setup = WS_PROBES[route]
    setup(monkeypatch, live=True)
    verdicts = _spy_guards(monkeypatch)
    tier = WS_GUARDED_IN_HANDLER[route]
    with client.websocket_connect(path, headers={"x-admin-token": ADMIN}) as ws:
        assert verdicts[tier][0] == "ok"
        tokens.revoked = True
        # Wake the loop: an RPC frame for Hermes, any frame for the Kanban tail.
        ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}))
        with pytest.raises(WebSocketDisconnect) as caught:
            for _ in range(10):
                ws.receive_text()
    assert caught.value.code == 1008
    assert verdicts[tier][-1] == 401, f"{route} closed, but not on a refused re-check: {verdicts}"


@pytest.mark.timeout(20)
def test_hermes_event_push_stops_when_credential_is_revoked(client, monkeypatch, tokens):
    """The push path's own re-check (hermes_runtime._send_events): once the owner
    credential is revoked, the next pushed event is never delivered — the stream
    closes 1008 instead. No client frame is sent, so the receive loop sits in its
    5 s wait and its own re-check cannot pre-empt the push: without the per-event
    check the queued event goes out before the loop wakes."""
    import queue

    from agents.core.routers import hermes_runtime

    pushed = queue.Queue()
    service = _FakeHermes(ready=True, pushed=pushed)
    monkeypatch.setattr(hermes_runtime, "_service", lambda: service)
    verdicts = _spy_guards(monkeypatch)
    with client.websocket_connect("/api/hermes/ws", headers={"x-admin-token": ADMIN}) as ws:
        pushed.put({"event": "before-revocation"})
        assert json.loads(ws.receive_text()) == {"event": "before-revocation"}
        tokens.revoked = True
        pushed.put({"event": "after-revocation"})
        with pytest.raises(WebSocketDisconnect) as caught:
            leaked = ws.receive_text()
            pytest.fail(f"an event was pushed after the credential was revoked: {leaked}")
    assert caught.value.code == 1008
    assert 401 in verdicts["admin"], verdicts


# ── Tier-decision probes: the admin/user branch a user-tier handler takes ─────

def _request(headers=None, host="127.0.0.1"):
    from starlette.requests import Request

    return Request({"type": "http", "method": "POST", "path": "/", "scheme": "http",
                    "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
                    "client": (host, 50000), "server": ("127.0.0.1", 80), "query_string": b""})


def test_chat_stream_binds_the_credentialed_principal(client, monkeypatch, tmp_path):
    """/chat/stream hands the turn the principal its credential earns: the owner only
    with a valid admin token — a wrong one, or none, is a plain user."""
    from agents import web
    from agents.core.checkpoint import CheckpointManager

    # The H441 foreign-history fence reads the session's lineage first; a real
    # (empty) store answers "native", so the turn itself is what is probed here.
    checkpoints = CheckpointManager(str(tmp_path / "history.db"))
    checkpoints.initialize()

    seen = []

    async def fake_stream(orch, message, agent, agent_override, principal=None, **kw):
        seen.append(principal)
        yield "data: {}\n\n"

    class Orch:
        notes = None
        session_id = "h511"

    Orch.checkpoints = checkpoints
    monkeypatch.setattr(web, "orch", Orch())
    monkeypatch.setattr(web, "_chat_event_stream", fake_stream)
    for headers in ({}, {"x-admin-token": "not-the-owner"}, {"x-admin-token": ADMIN}):
        assert client.post("/chat/stream", json={"message": "hi"}, headers=headers).status_code == 200
    assert [(p.channel, p.admin) for p in seen] == [("web", False), ("web", False), ("web", True)]
    checkpoints.close()


def test_sandbox_principal_follows_the_credential(client):
    """skills._request_principal (the /sandbox/execute binding) resolves the owner only
    from a valid admin credential; an unreadable request is nobody."""
    from agents.core.routers.skills import _request_principal

    assert _request_principal(_request({"x-admin-token": ADMIN})).admin is True
    assert _request_principal(_request({"x-admin-token": "not-the-owner"})).admin is False
    assert _request_principal(_request()).admin is False
    assert _request_principal(None) is None


def test_pending_input_actor_follows_the_credential(client, monkeypatch, tokens):
    """chat_pending.http_actor: with a user credential required, only a *valid* admin
    or user token yields an actor; on the localhost posture the owner and a plain
    local caller are different actors (so one cannot answer the other's wait)."""
    from agents import web
    from agents.core.routers.chat_pending import http_actor

    monkeypatch.setattr(web, "_user_credential_required", lambda: True)
    owner = http_actor(_request({"x-admin-token": ADMIN}))
    assert owner is not None
    assert http_actor(_request({"x-admin-token": "not-the-owner"})) is None
    assert http_actor(_request()) is None
    tokens.revoked = True
    assert http_actor(_request({"x-admin-token": ADMIN})) is None
    tokens.revoked = False

    monkeypatch.setattr(web, "_user_credential_required", lambda: False)
    local_owner = http_actor(_request({"x-admin-token": ADMIN}))
    local_user = http_actor(_request())
    assert local_owner and local_user and local_owner != local_user
    assert http_actor(_request({"x-admin-token": ADMIN}, host="203.0.113.9")) is None


def test_consent_recheck_follows_the_credential(client, monkeypatch, tokens):
    """autonomy._consent_admin_current — the live owner re-check at the consent queue
    seam — holds only while a valid admin credential is presented to the same orch."""
    from agents.core.routers import autonomy

    orch = object()
    monkeypatch.setattr(autonomy, "get_orch", lambda: orch)
    assert autonomy._consent_admin_current(_request({"x-admin-token": ADMIN}), orch) is True
    assert autonomy._consent_admin_current(_request({"x-admin-token": "not-the-owner"}), orch) is False
    assert autonomy._consent_admin_current(_request(), orch) is False
    assert autonomy._consent_admin_current(_request({"x-admin-token": ADMIN}), object()) is False
    tokens.revoked = True
    assert autonomy._consent_admin_current(_request({"x-admin-token": ADMIN}), orch) is False


def test_mcp_mutating_tools_are_bound_to_the_identity_check(client, monkeypatch):
    """web._build_mcp_mutating_route_tools hands `_mcp_identity_check` to every write
    tool as a callback (a bare reference, found by the round-3 scan): with a user
    credential configured, a bound tool admits only that credential (or the admin's)."""
    from types import SimpleNamespace

    from agents import web

    monkeypatch.setenv("JARVIS_MCP_ROUTE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_MCP_MUTATING_TOOLS", "1")
    monkeypatch.setattr(web, "orch", SimpleNamespace(audit=object(), memory=None))
    monkeypatch.setattr(web, "USER_TOKEN", "synthetic-h511-user")
    monkeypatch.setattr(web, "_user_credential_required", lambda: True)
    tools = web._build_mcp_mutating_route_tools()
    assert tools, "both switches on with an auditor must bind the write tools"
    for tool in tools:
        assert tool._identity_ok(None) is False
        assert tool._identity_ok("not-a-credential") is False
        assert tool._identity_ok("synthetic-h511-user") is True
        assert tool._identity_ok(ADMIN) is True


# ── Every pinned in-body site names a probe that exists ───────────────────────

_PARAMETRIZED = {
    "test_in_handler_guard_refuses_without_credential": {**HTTP_PROBES, **EXTRA_POSTURE_PROBES},
    "test_websocket_in_handler_guard_refuses_unauthenticated": WS_PROBES,
    "test_websocket_closes_when_credential_is_revoked_mid_stream": WS_PROBES,
    "test_step_up_refuses_a_user_tier_caller": STEP_UP_PROBES,
}


def test_every_pinned_site_names_a_live_probe():
    """A pin is only as good as its probe: each probe id in IN_HANDLER_GUARD_SITES /
    IN_HANDLER_TIER_SITES must name an existing test function (and, for a test in
    this file, an existing parameter), so a pinned call site cannot go unexercised."""
    import ast
    from pathlib import Path

    from tests.test_route_auth_matrix import IN_HANDLER_GUARD_SITES, IN_HANDLER_TIER_SITES

    root = Path(__file__).resolve().parent.parent
    here = Path(__file__).resolve().relative_to(root).as_posix()
    missing = []
    for site, probes in {**IN_HANDLER_GUARD_SITES, **IN_HANDLER_TIER_SITES}.items():
        if not probes:
            missing.append(f"{site}: no probe")
        for probe in probes:
            file, _, test = probe.partition("::")
            name, _, param = test.partition("[")
            param = param[:-1] if param.endswith("]") else param
            path = root / file
            names = set()
            if path.is_file():
                names = {n.name for n in ast.parse(path.read_text(encoding="utf-8")).body
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if name not in names or not name.startswith("test_"):
                missing.append(f"{site}: {probe} (no such test)")
            elif param and (file != here or param not in _PARAMETRIZED.get(name, {})):
                missing.append(f"{site}: {probe} (no such parameter)")
    assert not missing, "pinned in-body guard sites without a live probe:\n" + "\n".join(missing)
