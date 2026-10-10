"""Selected Grok images use a reviewed xAI Responses request without replay."""

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
from agents.core.llm import vision_xai_wire as xai_wire
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client
from agents.core.llm.vision_main import selected_main_config
from agents.core.llm.xai import XAIBackend
from agents.core.orchestrator import Orchestrator
from tests.h441_native_fixture import bind_native
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401

MODEL = "grok-4.6"
IMAGE_DIGEST = hashlib.sha256(PNG.encode("utf-8")).hexdigest()


def _selected(monkeypatch, *, effort=""):
    orch = Orchestrator(JarvisConfig())
    bind_native(orch, monkeypatch)
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = XAIBackend("selected-xai-key", reasoning_effort=effort)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, MODEL, "cloud-compatible")
    sid = asyncio.run(orch.memory.new_session("xai_selected_image"))
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


def _body(status, sid, *, images=None):
    body = {**approved(status), "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "review_token": status["review_token"]}
    if images is not None:
        body["images"] = images
    for requirement in status.get("selection_requirements", []):
        body[requirement["needs"]] = True
    return body


def _answer(text="A square.", *, reasoning=False):
    rows = [{"type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text}]}]
    if reasoning:
        rows.insert(0, {"type": "reasoning", "status": "completed", "summary": []})
    return {"status": "completed", "output": rows}


def test_selected_xai_image_uses_native_responses_wire(route, monkeypatch):
    orch, backend, sid = _selected(monkeypatch, effort="high")

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer(reasoning=True))

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        assert (status["backend"], status["model"], status["selection_source"]) == (
            "xai", MODEL, "auto:main")
        assert status["destination"] == "https://api.x.ai/v1"
        assert "selected-xai-key" not in str(status)
        assert route.requests == []

        sent = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["response"] == "A square."
        assert len(route.requests) == 1
        request = route.requests[0]
        assert str(request.url) == "https://api.x.ai/v1/responses"
        assert request.headers["Authorization"] == "Bearer selected-xai-key"
        payload = json.loads(request.content)
        assert payload["model"] == MODEL and payload["store"] is False
        assert payload["reasoning"] == {"effort": "high"}
        assert "prompt_cache_retention" not in payload
        assert "messages" not in payload and "tools" not in payload
        image = next(part for part in payload["input"][-1]["content"]
                     if part["type"] == "input_image")
        assert base64.b64decode(image["image_url"].partition(",")[2]) == base64.b64decode(PNG.partition(",")[2])
        assert len(asyncio.run(orch.memory.get_history(sid))) == 0
    finally:
        asyncio.run(backend.aclose())


def test_selected_xai_refuses_changed_key_before_egress(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    try:
        status = _preview(route, sid)
        backend.api_key = "other-key"
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_xai_refuses_late_body_mutation(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)

    async def tamper(request):
        body = json.loads(request.content)
        body["input"][-1]["content"][0]["text"] = "unreviewed prompt"
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


def test_selected_xai_refuses_late_authorization_mutation(route, monkeypatch):
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


def test_xai_image_review_refuses_changed_digest_before_egress(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    try:
        status = _preview(route, sid)
        invalid = PNG.replace("data:image/png;", "data:image/gif;")
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid, images=[invalid]))
        assert refused.status_code in {409, 422, 502}, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_xai_wire_rejects_unsupported_mime_before_decode(monkeypatch):
    def forbid_decode(*_args, **_kwargs):
        raise AssertionError("unsupported image was decoded")

    monkeypatch.setattr(responses_wire.base64, "b64decode", forbid_decode)
    compatible = {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/gif;base64,AAAA"}},
    ]}], "max_tokens": 256, "temperature": 0.2}
    with pytest.raises(ValueError, match="invalid Responses image data"):
        xai_wire.xai_payload(compatible, reasoning_effort="")


def test_xai_image_refuses_tool_and_refusal_outputs():
    for output in (
        [{"type": "function_call", "call_id": "c1", "name": "tool", "arguments": "{}"}],
        [{"type": "message", "role": "assistant", "content": [
            {"type": "refusal", "refusal": "No"}]}],
    ):
        with pytest.raises(ValueError):
            xai_wire.xai_answer({"status": "completed", "output": output})


def test_selected_xai_refuses_changed_reasoning_effort_before_egress(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch, effort="high")
    try:
        status = _preview(route, sid)
        backend.reasoning_effort = "low"
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_xai_requires_remote_ack(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/describe-prepared", json={
            **_body(status, sid), "remote_ack": False})
        assert refused.status_code in {403, 409}, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_xai_image_authority_is_canonical_and_model_pinned():
    backend = XAIBackend("selected-xai-key")
    try:
        config = selected_main_config(backend, MODEL, "cloud-compatible")
        assert config is not None
        assert (config.backend, config.base_url, config.wire_mode) == (
            "xai", "https://api.x.ai/v1", "xai_responses")
        with pytest.raises(vp.VisionPolicyUnavailable, match="authority"):
            vp.describe(vlm.VLMConfig("xai", "https://other.example/v1", MODEL,
                                      "selected-xai-key", False, wire_mode="xai_responses"))
        with pytest.raises(vlm.VLMNotConfigured):
            selected_main_config(backend, "grok-other", "cloud-compatible")
    finally:
        asyncio.run(backend.aclose())


def test_selected_xai_empty_success_retries_same_body_once(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    _orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer(" " if len(route.requests) == 1 else "A square."))

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
