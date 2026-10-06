"""Hermes owner routes preserve authentication and one-use protocol frames."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agents.core.routers import _deps
from agents.core.routers import hermes_runtime as routes


class FakeService:
    def __init__(self):
        self.calls = []
        self.replies = []
        self.events_queue = asyncio.Queue()
        self.running = False

    async def status(self):
        return {"enabled": self.running, "ready": self.running, "reason": "not configured"}

    def catalog(self):
        return {"source_sha": "pinned", "methods": [{"name": "session.list", "summary": "List sessions"}]}

    async def start(self):
        self.running = True
        return await self.status()

    async def stop(self):
        self.running = False
        return await self.status()

    async def rpc(self, method, params):
        self.calls.append((method, params))
        return {"method": method, "params": params}

    async def reply(self, frame):
        self.replies.append(frame)

    async def events(self):
        while True:
            yield await self.events_queue.get()


@pytest.fixture
def hub(monkeypatch):
    async def guard(request):
        if request.headers.get("x-admin-token") != "secret":
            raise HTTPException(401, "admin token required")

    service = FakeService()
    monkeypatch.setattr(_deps, "_web", lambda: SimpleNamespace(_admin_guard=guard))
    monkeypatch.setattr(routes, "_service", lambda: service)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, service


def test_http_admin_contract_and_no_caller_selected_runtime(hub):
    client, service = hub
    for path in ("/api/hermes/status", "/api/hermes/catalog"):
        assert client.get(path).status_code == 401
    for path in ("/api/hermes/start", "/api/hermes/stop", "/api/hermes/rpc"):
        assert client.post(path, json={}).status_code == 401
    headers = {"x-admin-token": "secret"}
    assert client.get("/api/hermes/status", headers=headers).json()["ready"] is False
    assert client.get("/api/hermes/catalog", headers=headers).json()["methods"][0]["name"] == "session.list"
    for field in ("source_url", "profile_path", "executable", "owner_id"):
        assert client.post("/api/hermes/start", headers=headers, json={field: "forged"}).status_code == 422
        assert client.post("/api/hermes/rpc", headers=headers,
                           json={"method": "session.list", "params": {}, field: "forged"}).status_code == 422
    assert not service.running and service.calls == []
    assert client.post("/api/hermes/start", headers=headers).json()["ready"] is True
    response = client.post("/api/hermes/rpc", headers=headers,
                           json={"method": "session.list", "params": {"limit": 5}})
    assert response.json()["result"] == {"method": "session.list", "params": {"limit": 5}}
    assert service.calls == [("session.list", {"limit": 5})]
    assert client.post("/api/hermes/stop", headers=headers).json()["ready"] is False


@pytest.mark.parametrize(("path", "headers"), [
    ("/api/hermes/ws", {}),
    ("/api/hermes/ws?token=secret", {"x-admin-token": "secret"}),
    ("/api/hermes/ws", {"x-admin-token": "secret", "Origin": "https://foreign.invalid"}),
    ("/api/hermes/ws", {"x-admin-token": "secret", "Host": "foreign.invalid"}),
])
def test_websocket_rejects_unauthorized_origins_and_query_credentials(hub, path, headers):
    client, _ = hub
    with pytest.raises(WebSocketDisconnect) as caught, client.websocket_connect(path, headers=headers):
        pass
    assert caught.value.code == 1008


def test_websocket_does_not_upgrade_a_disabled_runtime(hub):
    client, service = hub
    with pytest.raises(WebSocketDisconnect) as caught, client.websocket_connect(
        "/api/hermes/ws", headers={"x-admin-token": "secret"}
    ):
        pass
    assert caught.value.code == 1008
    assert service.calls == []


def test_websocket_forwards_events_rpc_and_pending_server_reply(hub):
    client, service = hub
    service.running = True
    service.events_queue.put_nowait({"jsonrpc": "2.0", "id": "upstream-7",
                                     "method": "approval.request", "params": {"tool": "safe"},
                                     "generation": "abc123"})
    protocols = [routes.PROTOCOL, "nerva-admin.secret"]
    with client.websocket_connect("/api/hermes/ws", subprotocols=protocols,
                                  headers={"Host": "127.0.0.1", "Origin": "http://127.0.0.1"}) as ws:
        assert ws.accepted_subprotocol == routes.PROTOCOL
        assert ws.receive_json()["id"] == "upstream-7"
        ws.send_json({"jsonrpc": "2.0", "id": "upstream-7", "generation": "abc123",
                      "result": {"approved": False}})
        ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "session.list", "params": {}})
        assert ws.receive_json() == {"jsonrpc": "2.0", "id": 1,
                                     "result": {"method": "session.list", "params": {}}}
    assert service.replies == [{"jsonrpc": "2.0", "id": "upstream-7", "generation": "abc123",
                                "result": {"approved": False}}]
    assert service.calls == [("session.list", {})]


def test_websocket_refuses_extra_authority_fields_before_dispatch(hub):
    client, service = hub
    service.running = True
    with client.websocket_connect("/api/hermes/ws", headers={"x-admin-token": "secret"}) as ws:
        ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "session.list",
                      "params": {}, "owner_id": "forged"})
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 1008
    assert service.calls == []


def test_websocket_duplicate_rpc_id_never_dispatches_twice(hub):
    client, service = hub
    service.running = True
    frame = {"jsonrpc": "2.0", "id": 7, "method": "session.create", "params": {}}
    with client.websocket_connect("/api/hermes/ws", headers={"x-admin-token": "secret"}) as ws:
        ws.send_json(frame)
        assert ws.receive_json()["id"] == 7
        ws.send_json(frame)
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 1008
    assert service.calls == [("session.create", {})]


def test_websocket_accepts_server_reply_while_rpc_is_pending(hub, monkeypatch):
    client, service = hub
    service.running = True
    answered = asyncio.Event()

    async def pending_rpc(method, params):
        service.calls.append((method, params))
        service.events_queue.put_nowait({"jsonrpc": "2.0", "id": "upstream-approval",
                                         "generation": "abc123", "method": "approval.request",
                                         "params": {"operation": method}})
        await answered.wait()
        return {"approved": True}

    async def reply(frame):
        service.replies.append(frame)
        answered.set()

    monkeypatch.setattr(service, "rpc", pending_rpc)
    monkeypatch.setattr(service, "reply", reply)
    with client.websocket_connect("/api/hermes/ws", headers={"x-admin-token": "secret"}) as ws:
        ws.send_json({"jsonrpc": "2.0", "id": 4, "method": "llm.oneshot", "params": {}})
        server_request = ws.receive_json()
        assert server_request["method"] == "approval.request"
        ws.send_json({"jsonrpc": "2.0", "id": server_request["id"],
                      "generation": server_request["generation"], "result": {"approved": True}})
        assert ws.receive_json() == {"jsonrpc": "2.0", "id": 4, "result": {"approved": True}}
    assert service.replies[0]["id"] == "upstream-approval"
    assert service.calls == [("llm.oneshot", {})]


def test_websocket_reply_needs_generation(hub):
    client, service = hub
    service.running = True
    with client.websocket_connect("/api/hermes/ws", headers={"x-admin-token": "secret"}) as ws:
        ws.send_json({"jsonrpc": "2.0", "id": "request-1", "result": {}})
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 1008
    assert service.replies == []


def test_service_denial_and_unavailable_map_to_safe_http_status(hub, monkeypatch):
    from agents.core.hermes_runtime.service import RuntimeDenied, RuntimeUnavailable

    client, service = hub

    async def queued(method, params):
        raise RuntimeDenied("provider-secret-value", verdict="queue")

    monkeypatch.setattr(service, "rpc", queued)
    result = client.post("/api/hermes/rpc", headers={"x-admin-token": "secret"},
                         json={"method": "session.create", "params": {}})
    assert result.status_code == 409
    assert result.json()["detail"]["error"] == "approval_required"
    assert "provider-secret-value" not in result.text

    async def unavailable():
        raise RuntimeUnavailable("private worker URL and token")

    monkeypatch.setattr(service, "start", unavailable)
    result = client.post("/api/hermes/start", headers={"x-admin-token": "secret"})
    assert result.status_code == 503
    assert "private worker URL and token" not in result.text


def test_hermes_routes_are_mounted_under_real_web_admin_guard(monkeypatch):
    from agents import web
    from agents.core.hermes_runtime import service as service_module

    class Tokens:
        def verify(self, token):
            return None

        def env_revoked(self, scope):
            return False

        def list_tokens(self):
            return []

    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    monkeypatch.setattr(web, "get_token_store", lambda: Tokens())
    monkeypatch.setattr(service_module, "get_service", FakeService)
    with TestClient(web.app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/hermes/status").status_code == 401
        assert client.get("/api/hermes/status", headers={"x-admin-token": "secret"}).json()["ready"] is False
