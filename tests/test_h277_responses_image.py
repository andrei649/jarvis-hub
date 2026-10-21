"""The selected GPT-4.1 Responses route sends reviewed images natively."""

import asyncio
import base64
import hashlib
import json

import httpx
import pytest

from agents import web
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm import vision_policy as vp
from agents.core.llm import vision_responses_wire as responses_wire
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client
from agents.core.llm.responses import ResponsesBackend
from agents.core.llm.vision_main import selected_main_config
from agents.core.orchestrator import Orchestrator
from tests.h441_native_fixture import bind_native
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401

MODEL = "gpt-4.1"
IMAGE_DIGEST = hashlib.sha256(PNG.encode("utf-8")).hexdigest()


def _selected(monkeypatch):
    orch = Orchestrator(JarvisConfig())
    bind_native(orch, monkeypatch)
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = ResponsesBackend("selected-key")
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, MODEL, "cloud-compatible")
    sid = asyncio.run(orch.memory.new_session("responses_selected_image"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    return orch, backend, sid


def _preview(route, sid):
    response = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
        "selected_turn": True, "image_digests": [IMAGE_DIGEST],
    })
    assert response.status_code == 200, response.text
    return response.json()


def _body(status, sid):
    body = {**approved(status), "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "review_token": status["review_token"]}
    for requirement in status.get("selection_requirements", []):
        body[requirement["needs"]] = True
    return body


def _answer(text="A square."):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "status": "completed", "content": [{"type": "output_text", "text": text}]}]}


def test_selected_responses_uses_native_image_wire(route, monkeypatch):
    orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer())

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        assert (status["backend"], status["model"], status["selection_source"]) == (
            "openai-responses", MODEL, "auto:main")
        assert status["destination"] == "https://api.openai.com/v1"
        assert "selected-key" not in str(status)
        assert route.requests == []

        sent = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["response"] == "A square."
        assert len(route.requests) == 1
        request = route.requests[0]
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer selected-key"
        assert request.headers.get("x-goog-api-key") is None
        payload = json.loads(request.content)
        assert payload["model"] == MODEL and payload["store"] is False
        assert "messages" not in payload and "tools" not in payload
        content = payload["input"][-1]["content"]
        image = next(part for part in content if part["type"] == "input_image")
        assert base64.b64decode(image["image_url"].partition(",")[2]) == base64.b64decode(PNG.partition(",")[2])
        assert len(asyncio.run(orch.memory.get_history(sid))) == 0
    finally:
        asyncio.run(backend.aclose())


def test_selected_responses_refuses_changed_key_before_egress(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    try:
        status = _preview(route, sid)
        backend.api_key = "other-key"
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_responses_image_key_cannot_target_other_origin_or_model():
    config = vlm.VLMConfig("openai-responses", "https://other.example/v1", MODEL,
                           "selected-key", False, wire_mode="responses")
    with pytest.raises(vp.VisionPolicyUnavailable, match="authority"):
        vp.describe(config)
    backend = ResponsesBackend("selected-key")
    try:
        with pytest.raises(vlm.VLMNotConfigured):
            selected_main_config(backend, "gpt-4.1-other", "cloud-compatible")
    finally:
        asyncio.run(backend.aclose())


def test_selected_responses_refuses_late_body_mutation(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)

    async def tamper(request):
        body = json.loads(request.content)
        body["input"][-1]["content"][0]["text"] = "new unreviewed question"
        request._content = json.dumps(body).encode()

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer())

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond),
                                         event_hooks={"request": [tamper]}, **kwargs))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_responses_empty_success_retries_same_body_once(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    _orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer("  " if len(route.requests) == 1 else "A square."))

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        sent = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert len(route.requests) == 2
        assert route.requests[0].content == route.requests[1].content
    finally:
        asyncio.run(backend.aclose())


def test_selected_responses_requires_remote_ack(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json={
            **_body(status, sid), "remote_ack": False})
        assert refused.status_code in {403, 409}, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_responses_refuses_late_authorization_mutation(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)

    async def tamper(request):
        request.headers["Authorization"] = "Bearer other-key"

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer())

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond),
                                         event_hooks={"request": [tamper]}, **kwargs))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_responses_inline_limit_checked_before_decode(monkeypatch):
    monkeypatch.setattr(responses_wire, "MAX_INLINE_REQUEST_BYTES", 100)

    def forbid_decode(*_args, **_kwargs):
        raise AssertionError("oversized image was decoded before refusal")

    monkeypatch.setattr(responses_wire.base64, "b64decode", forbid_decode)
    compatible = {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 200}},
    ]}], "max_tokens": 256, "temperature": 0.2}
    with pytest.raises(ValueError, match="too large"):
        responses_wire.responses_payload(compatible, retention="in_memory")


def test_selected_responses_rejects_refusal_without_empty_retry(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    _orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "role": "assistant", "content": [
                {"type": "refusal", "refusal": "I cannot help"}]}]})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 502, refused.text
        assert len(route.requests) == 1
    finally:
        asyncio.run(backend.aclose())


def test_responses_selected_retention_is_bound_to_review():
    backend = ResponsesBackend("selected-key", retention="24h")
    try:
        config = selected_main_config(backend, MODEL, "cloud-compatible")
        assert config.prompt_cache_retention == "24h"
        identity = vp.describe(config)
        assert identity.prompt_cache_retention == "24h"
        assert "Prompt cache retention: 24h." in identity.public()["data_policy_note"]
        assert identity.binding != vp.describe(vlm.VLMConfig(
            "openai-responses", config.base_url, MODEL, "selected-key", False,
            wire_mode="responses", prompt_cache_retention="in_memory")).binding
    finally:
        asyncio.run(backend.aclose())
