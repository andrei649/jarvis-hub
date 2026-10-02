"""The selected Ollama conversation route must send native image chat requests."""

import asyncio
import base64
import json

import httpx
import pytest

from agents import web
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm import vlm
from agents.core.llm.base import OllamaBackend
from agents.core.llm.egress import llm_async_client
from agents.core.orchestrator import Orchestrator
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401


def test_selected_ollama_image_uses_native_chat_wire(route, monkeypatch):
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "qwen3-vl:8b", "local")
    sid = asyncio.run(orch.memory.new_session("ollama_selected_image"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"model": "qwen3-vl:8b", "message": {
            "role": "assistant", "content": "A red square."}, "done": True,
            "done_reason": "stop", "prompt_eval_count": 18, "eval_count": 5})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        assert (status["backend"], status["model"], status["selection_source"]) == (
            "ollama", "qwen3-vl:8b", "auto:main")
        assert status["destination"] == "http://127.0.0.1:11434"
        assert route.requests == []

        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        sent = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert sent.status_code == 200, sent.text
        assert sent.json()["response"] == "A red square."
        assert len(route.requests) == 1
        request = route.requests[0]
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert request.headers.get("Authorization") is None
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3-vl:8b"
        assert payload["stream"] is False
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert "Describe this" in payload["messages"][0]["content"]
        assert [base64.b64decode(image) for image in payload["messages"][0]["images"]] == [
            base64.b64decode(PNG.partition(",")[2])]
        assert len(asyncio.run(orch.memory.get_history(sid))) == 0
    finally:
        asyncio.run(backend.aclose())


def test_selected_ollama_destination_drift_refuses_before_image_request(route, monkeypatch):
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "qwen3-vl:8b", "local")
    sid = asyncio.run(orch.memory.new_session("ollama_changed_destination"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        backend.base_url = "http://127.0.0.1:11435"
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_remote_ollama_requires_explicit_acknowledgement(route, monkeypatch):
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = OllamaBackend("https://ollama.example", trust_env=False)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "qwen3-vl:8b", "local")
    sid = asyncio.run(orch.memory.new_session("ollama_remote_review"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        assert status["destination"] == "https://ollama.example"
        assert status["data_policy"] == "unknown"
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"],
                "remote_ack": False}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["reason"] == "vlm_remote_ack_required"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


@pytest.mark.parametrize("retry", ["0", "1"])
def test_late_ollama_image_body_mutation_never_reaches_transport(route, monkeypatch, retry):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", retry)
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "qwen3-vl:8b", "local")
    sid = asyncio.run(orch.memory.new_session("ollama_image_body_guard"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)

    async def tamper(request):
        payload = json.loads(request.content)
        payload["messages"][-1]["images"] = [base64.b64encode(b"different").decode()]
        request._content = json.dumps(payload).encode()

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"model": "qwen3-vl:8b", "message": {
            "role": "assistant", "content": "Unexpected."}, "done": True,
            "done_reason": "stop"})

    def factory(provider, **kwargs):
        client = llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs)
        client.event_hooks["request"].append(tamper)
        return client

    monkeypatch.setattr(vlm, "llm_async_client", factory)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())
