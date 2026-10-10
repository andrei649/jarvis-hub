"""Selected Gemini image turns use the same reviewed native route as text turns."""

import asyncio
import base64
import hashlib
import json

import httpx
import pytest

from agents import web
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm import vision_gemini_wire as gemini_wire
from agents.core.llm import vision_policy as vp
from agents.core.llm import vlm
from agents.core.llm.auth_rotation import AuthProfilePool
from agents.core.llm.egress import llm_async_client
from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.vision_main import selected_main_config
from agents.core.orchestrator import Orchestrator
from tests.h441_native_fixture import bind_native
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401

MODEL = "gemini-2.5-flash"
IMAGE_DIGEST = hashlib.sha256(PNG.encode("utf-8")).hexdigest()


def _selected(monkeypatch, *, pool=None):
    orch = Orchestrator(JarvisConfig())
    bind_native(orch, monkeypatch)
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = GeminiBackend("selected-key", model=MODEL, auth_pool=pool)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, MODEL, "cloud-flash")
    sid = asyncio.run(orch.memory.new_session("gemini_selected_image"))
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


def test_selected_gemini_image_uses_native_generate_content(route, monkeypatch):
    orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": "A square."}]}}]})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        assert (status["backend"], status["model"], status["selection_source"]) == (
            "gemini", MODEL, "auto:main")
        assert status["destination"] == "https://generativelanguage.googleapis.com/v1beta"
        assert "selected-key" not in str(status)
        assert route.requests == []

        sent = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["response"] == "A square."
        assert len(route.requests) == 1
        request = route.requests[0]
        assert str(request.url) == (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash:generateContent")
        assert request.headers.get("Authorization") is None
        assert request.headers["x-goog-api-key"] == "selected-key"
        payload = json.loads(request.content)
        parts = payload["contents"][0]["parts"]
        image = next(part["inline_data"] for part in parts if "inline_data" in part)
        assert image["mime_type"] == "image/png"
        assert base64.b64decode(image["data"]) == base64.b64decode(PNG.partition(",")[2])
        assert len(asyncio.run(orch.memory.get_history(sid))) == 0
    finally:
        asyncio.run(backend.close())


def test_selected_gemini_uses_active_pool_key_not_ambient(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-other-key")
    pool = AuthProfilePool(["first-key", "second-key"], provider="gemini")
    backend = GeminiBackend("backend-fallback-key", model=MODEL, auth_pool=pool)
    try:
        config = selected_main_config(backend, MODEL, "cloud-flash")
        assert config is not None
        assert (config.backend, config.api_key, config.base_url, config.wire_mode) == (
            "gemini", "first-key", "https://generativelanguage.googleapis.com/v1beta",
            "gemini_generate_content")
        pool.rotate()
        assert selected_main_config(backend, MODEL, "cloud-flash").api_key == "second-key"
    finally:
        asyncio.run(backend.close())


def test_selected_gemini_refuses_rotated_key_before_egress(route, monkeypatch):
    pool = AuthProfilePool(["first-key", "second-key"], provider="gemini")
    _orch, backend, sid = _selected(monkeypatch, pool=pool)
    try:
        status = _preview(route, sid)
        pool.rotate()
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.close())


def test_selected_gemini_requires_remote_ack(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json={
            **_body(status, sid), "remote_ack": False})
        assert refused.status_code in {403, 409}, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.close())


def test_selected_gemini_refuses_late_key_mutation(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)

    async def tamper(request):
        request.headers["x-goog-api-key"] = "other-key"

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": "Should not arrive."}]}}]})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond),
                                         event_hooks={"request": [tamper]}, **kwargs))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.close())


def test_gemini_image_key_cannot_target_other_origin_or_model_path():
    config = vlm.VLMConfig("gemini", "https://other.example/v1beta", MODEL,
                           "selected-key", False, wire_mode="gemini_generate_content")
    with pytest.raises(vp.VisionPolicyUnavailable, match="authority"):
        vp.describe(config)
    invalid = vlm.VLMConfig("gemini", "https://generativelanguage.googleapis.com/v1beta",
                            "gemini-2.5-flash/other", "selected-key", False,
                            wire_mode="gemini_generate_content")
    with pytest.raises(vp.VisionPolicyUnavailable, match="model"):
        vp.describe(invalid)


def test_selected_gemini_refuses_late_body_mutation(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)

    async def tamper(request):
        body = json.loads(request.content)
        body["contents"][0]["parts"][0]["text"] = "new unreviewed question"
        request._content = json.dumps(body).encode()

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": "Should not arrive."}]}}]})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond),
                                         event_hooks={"request": [tamper]}, **kwargs))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.close())


def test_gemini_inline_limit_checked_before_base64_decode(monkeypatch):
    monkeypatch.setattr(gemini_wire, "MAX_INLINE_REQUEST_BYTES", 100)

    def forbid_decode(*_args, **_kwargs):
        raise AssertionError("oversized image was decoded before refusal")

    monkeypatch.setattr(gemini_wire.base64, "b64decode", forbid_decode)
    compatible = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 200}},
    ]}], "max_tokens": 256, "temperature": 0.2}
    with pytest.raises(ValueError, match="too large"):
        gemini_wire.generate_content_payload(compatible)


def test_selected_gemini_empty_success_retries_same_reviewed_body_once(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    _orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        answer = "  " if len(route.requests) == 1 else "A square."
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": answer}]}}]})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        assert status["empty_retries"] == 1
        sent = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["response"] == "A square."
        assert len(route.requests) == 2
        assert route.requests[0].content == route.requests[1].content
    finally:
        asyncio.run(backend.close())


def test_selected_gemini_malformed_response_does_not_retry(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    _orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY",
            "content": {"parts": [{"text": "blocked"}]}}]})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 502
        assert len(route.requests) == 1
    finally:
        asyncio.run(backend.close())
