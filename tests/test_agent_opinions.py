"""A comparison asks exactly two live agents without opening a chat turn."""

import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.llm.egress import llm_async_client
from agents.core.routers._deps import admin_guard, owner_web_principal


def _backend(answer, *, arrived=None, release=None):
    async def respond(request):
        if arrived is not None:
            arrived.append(request)
            if len(arrived) == 2:
                release.set()
            await asyncio.wait_for(release.wait(), 1)
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]})

    backend = LMStudioBackend()
    backend.client = llm_async_client("lm-studio", base_url="http://localhost:1234",
                                      transport=httpx.MockTransport(respond), trust_env=False)
    return backend


@pytest.mark.asyncio
async def test_two_opinions_run_concurrently_and_keep_selected_order():
    from agents.core.agent_opinions import run_opinions

    arrived = []
    release = asyncio.Event()
    backends = {"alpha": _backend("first", arrived=arrived, release=release),
                "beta": _backend("second", arrived=arrived, release=release)}
    router = SimpleNamespace(
        select_backend=lambda aid, question: (backends[aid], f"model-{aid}", "local"),
        check_data_handling=lambda *a, **kw: None,
    )
    result = await run_opinions(router, "one question", ["beta", "alpha"], allow_cloud=False)
    assert [row["agent"] for row in result] == ["beta", "alpha"]
    assert [row["text"] for row in result] == ["second", "first"]
    assert all(row["ok"] and row["route"] == "local" for row in result)
    assert len(arrived) == 2


@pytest.mark.asyncio
async def test_opinion_sends_static_question_language_guidance_without_private_context():
    from agents.core.agent_opinions import run_opinions

    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Bonjour"},
                                                   "finish_reason": "stop"}]})

    backend = LMStudioBackend()
    backend.client = llm_async_client("lm-studio", base_url="http://localhost:1234",
                                      transport=httpx.MockTransport(respond), trust_env=False)
    question = 'Write a French invitation that quotes "Hello" unchanged.'
    router = SimpleNamespace(select_backend=lambda aid, text: (backend, "m", "local"),
                             check_data_handling=lambda *a: None)

    result = await run_opinions(router, question, ["alpha"], allow_cloud=False,
                                labels={"alpha": ("Alpha", "community writer")})

    assert result[0]["text"] == "Bonjour"
    assert len(requests) == 1
    system, user = [row["content"] for row in json.loads(requests[0].read())["messages"]]
    assert user == question
    assert "Alpha" in system and "community writer" in system
    assert "private context" in system and question not in system
    assert "requested language" in system
    assert "draft" in system and "translation" in system
    assert "question's language" in system and "quotations" in system


@pytest.mark.asyncio
async def test_local_only_refuses_cloud_selection_without_a_send():
    from agents.core.agent_opinions import run_opinions

    sent = []
    backend = _backend("wrong")
    router = SimpleNamespace(
        select_backend=lambda aid, question: (backend, "cloud-model", "cloud"),
        check_data_handling=lambda *a, **kw: sent.append("consent"),
    )
    result = await run_opinions(router, "question", ["a", "b"], allow_cloud=False)
    assert [row["reason"] for row in result] == ["cloud_disabled", "cloud_disabled"]
    assert not sent


@pytest.mark.asyncio
async def test_cloud_needs_request_opt_in_and_fresh_consent(monkeypatch):
    from agents.core import agent_opinions
    from agents.core.llm.data_handling import DataHandlingRefused

    monkeypatch.setattr(agent_opinions, "_preflight", lambda backend, **kw: backend)

    sent = []

    async def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "yes"}, "finish_reason": "stop"}]})

    backend = _backend("unused")
    backend.client = llm_async_client("lm-studio", base_url="http://localhost:1234",
                                      transport=httpx.MockTransport(respond), trust_env=False)
    checks = []

    def consent(*args):
        checks.append(1)
        raise DataHandlingRefused("secret provider detail")

    router = SimpleNamespace(select_backend=lambda aid, question: (backend, "m", "cloud"),
                             check_data_handling=consent)
    assert [r["reason"] for r in await agent_opinions.run_opinions(router, "q", ["a", "b"], allow_cloud=False)] == [
        "cloud_disabled", "cloud_disabled"]
    assert not sent and not checks
    result = await agent_opinions.run_opinions(router, "q", ["a", "b"], allow_cloud=True)
    assert [r["reason"] for r in result] == ["generation_failed", "generation_failed"]
    assert "secret" not in str(result)
    assert checks and not sent


@pytest.mark.asyncio
async def test_internal_retry_is_refused_before_second_http_send(monkeypatch):
    from agents.core import agent_opinions

    monkeypatch.setattr(agent_opinions, "_preflight", lambda backend, **kw: backend)

    sent = []

    async def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "yes"}, "finish_reason": "stop"}]})

    class RetryingBackend:
        client = llm_async_client("lm-studio", base_url="http://localhost:1234",
                                  transport=httpx.MockTransport(respond), trust_env=False)

        async def generate(self, model, question, **kwargs):
            await self.client.post("/v1/chat/completions", json={"model": model})
            # An adapter may swallow an HTTP refusal and return a stale reply.
            with suppress(Exception):
                await self.client.post("/v1/chat/completions", json={"model": model})
            return "stale reply"

    backend = RetryingBackend()
    router = SimpleNamespace(select_backend=lambda aid, question: (backend, "m", "cloud"),
                             check_data_handling=lambda *a: None)
    result = await agent_opinions.run_opinions(router, "q", ["a"], allow_cloud=True)
    assert result == [{"agent": "a", "ok": False, "reason": "generation_failed"}]
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_howard_ollama_alias_forces_local_wire_model():
    from agents.core.agent_opinions import run_opinions

    sent = []

    async def respond(request):
        sent.append(request)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"thinking": {"values": [True]}})
        return httpx.Response(200, json={"response": "Howard answer"})

    backend = OllamaBackend()
    backend.client = llm_async_client("ollama", base_url="http://localhost:11434",
                                      transport=httpx.MockTransport(respond), trust_env=False)
    router = SimpleNamespace(select_backend=lambda aid, question: (backend, "howard-model", "ollama-howard"),
                             check_data_handling=lambda *a: None)
    result = await run_opinions(router, "question", ["howard"], allow_cloud=False)
    assert result[0]["ok"] is True
    assert result[0]["route"] == "ollama-howard"
    generation = [request for request in sent if request.url.path == "/api/generate"]
    assert len(generation) == 1
    assert generation[0].read().decode().find('"model":"howard-model:latest:local"') >= 0
    assert '"think":false' not in generation[0].read().decode()


@pytest.mark.asyncio
async def test_supported_ollama_model_uses_native_no_think_once():
    from agents.core.agent_opinions import run_opinions

    sent = []

    async def respond(request):
        sent.append(request)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"thinking": {"values": [True, False]}})
        return httpx.Response(200, json={"response": "Direct answer"})

    backend = OllamaBackend()
    backend.client = llm_async_client("ollama", base_url="http://localhost:11434",
                                      transport=httpx.MockTransport(respond), trust_env=False)
    router = SimpleNamespace(select_backend=lambda aid, question: (backend, "model", "local-ollama"),
                             check_data_handling=lambda *a: None)
    result = await run_opinions(router, "question", ["a"], allow_cloud=False)
    assert result[0]["text"] == "Direct answer"
    generation = [request for request in sent if request.url.path == "/api/generate"]
    assert len(generation) == 1
    assert '"think":false' in generation[0].read().decode()


@pytest.mark.asyncio
async def test_disconnected_request_does_not_select_or_send():
    from agents.core.agent_opinions import run_opinions

    called = []

    async def disconnected():
        return True

    router = SimpleNamespace(select_backend=lambda *a: called.append(1))
    result = await run_opinions(router, "q", ["a", "b"], allow_cloud=False,
                                is_disconnected=disconnected)
    assert [r["reason"] for r in result] == ["disconnected", "disconnected"]
    assert not called


@pytest.mark.asyncio
async def test_timeout_cancels_member_and_blocks_a_late_send(monkeypatch):
    from agents.core import agent_opinions

    sent = []

    async def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "late"}}]})

    class LateBackend:
        client = llm_async_client("lm-studio", base_url="http://localhost:1234",
                                  transport=httpx.MockTransport(respond), trust_env=False)

        async def generate(self, model, question, **kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                with suppress(Exception):
                    await self.client.post("/v1/chat/completions", json={"model": model})
                raise

    monkeypatch.setattr(agent_opinions, "_preflight", lambda backend, **kw: backend)
    monkeypatch.setattr(agent_opinions, "_TIMEOUT_S", 0.01)
    router = SimpleNamespace(select_backend=lambda aid, question: (LateBackend(), "m", "cloud"),
                             check_data_handling=lambda *a: None)
    result = await agent_opinions.run_opinions(router, "q", ["a"], allow_cloud=True)
    assert result == [{"agent": "a", "ok": False, "reason": "timed_out"}]
    assert sent == []


@pytest.mark.asyncio
async def test_unknown_backend_wrapper_cannot_generate():
    from agents.core.agent_opinions import run_opinions

    called = []

    class Wrapper:
        def __init__(self, backend):
            self._backend = backend

        async def generate(self, *args, **kwargs):
            called.append(1)
            return "untrusted wrapper answer"

    backend = Wrapper(_backend("unrelated"))
    router = SimpleNamespace(select_backend=lambda aid, question: (backend, "m", "local"),
                             check_data_handling=lambda *a: None)
    result = await run_opinions(router, "q", ["a"], allow_cloud=False)
    assert result == [{"agent": "a", "ok": False, "reason": "route_unavailable"}]
    assert not called


def test_route_rejects_unknown_fields_duplicates_and_disabled_agents(monkeypatch):
    from agents.core.routers import agents_api

    app = FastAPI()
    app.include_router(agents_api.router)
    app.dependency_overrides[admin_guard] = lambda: None
    app.dependency_overrides[owner_web_principal] = lambda: SimpleNamespace(admin=True, channel="web")
    monkeypatch.setattr(agents_api, "get_orch", lambda: SimpleNamespace(
        agents={"alpha": object(), "beta": object()}, llm_router=object()))
    monkeypatch.setattr(agents_api, "_agent_settings", lambda: {"beta": {"enabled": False}})
    client = TestClient(app)
    body = {"question": " x ", "agents": ["alpha", "beta"]}
    assert client.post("/api/agents/opinions", json={**body, "unexpected": 1}).status_code == 422
    assert client.post("/api/agents/opinions", json={**body, "question": "   "}).status_code == 422
    assert client.post("/api/agents/opinions", json={**body, "allow_cloud": "true"}).status_code == 422
    assert client.post("/api/agents/opinions", json={**body, "agents": ["alpha", "alpha"]}).status_code == 422
    assert client.post("/api/agents/opinions", json=body).status_code == 422


def test_route_rejects_parallel_comparison_without_queue_or_model_call(monkeypatch):
    from agents.core import agent_opinions
    from agents.core.routers import agents_api

    app = FastAPI()
    app.include_router(agents_api.router)
    app.dependency_overrides[admin_guard] = lambda: None
    app.dependency_overrides[owner_web_principal] = lambda: SimpleNamespace(admin=True, channel="web")
    monkeypatch.setattr(agents_api, "get_orch", lambda: SimpleNamespace(
        agents={"alpha": SimpleNamespace(name="Alpha"), "beta": SimpleNamespace(name="Beta")},
        llm_router=SimpleNamespace()))
    monkeypatch.setattr(agents_api, "_agent_settings", lambda: {})
    assert agent_opinions.acquire_comparison()
    try:
        response = TestClient(app).post("/api/agents/opinions", json={
            "question": "q", "agents": ["alpha", "beta"]})
        assert response.status_code == 429
        assert response.json()["detail"] == "comparison_busy"
    finally:
        agent_opinions.release_comparison()


def test_route_returns_typed_receipts_without_starting_an_orchestrator_turn(monkeypatch):
    from agents.core.routers import agents_api

    app = FastAPI()
    app.include_router(agents_api.router)
    app.dependency_overrides[admin_guard] = lambda: None
    app.dependency_overrides[owner_web_principal] = lambda: SimpleNamespace(admin=True, channel="web")
    backend = _backend("answer")
    calls = []
    router = SimpleNamespace(select_backend=lambda aid, question: (
        calls.append((aid, question)) or backend, "local-model", "local"),
        check_data_handling=lambda *a: None)
    orch = SimpleNamespace(agents={"alpha": SimpleNamespace(name="Alpha", role="Research"),
                                   "beta": SimpleNamespace(name="Beta", role="Review")},
                           llm_router=router, handle_input=lambda *a: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(agents_api, "get_orch", lambda: orch)
    monkeypatch.setattr(agents_api, "_agent_settings", lambda: {})
    response = TestClient(app).post("/api/agents/opinions", json={
        "question": " q ", "agents": ["beta", "alpha"]})
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
    rows = response.json()["opinions"]
    assert [row["agent"] for row in rows] == ["beta", "alpha"]
    assert all(row == {"agent": row["agent"], "ok": True, "text": "answer",
                       "route": "local", "model": "local-model"} for row in rows)
    assert calls == [("beta", "q"), ("alpha", "q")]
