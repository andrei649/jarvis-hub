"""The selected Claude conversation route sends reviewed images on Messages."""

import asyncio
import base64
import hashlib
import json

import httpx
import pytest

from agents import web
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm import vision_catalog, vlm
from agents.core.llm import vision_policy as vp
from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.auth_rotation import AuthProfilePool
from agents.core.llm.egress import llm_async_client
from agents.core.llm.vision_main import selected_main_config
from agents.core.orchestrator import Orchestrator
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401

MODEL = "claude-sonnet-4-6"
IMAGE_DIGEST = hashlib.sha256(PNG.encode("utf-8")).hexdigest()


def _selected(monkeypatch, *, pool=None):
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = ClaudeBackend("selected-key", model=MODEL, auth_pool=pool)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, MODEL, "claude")
    sid = asyncio.run(orch.memory.new_session("claude_selected_image"))
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


def test_selected_claude_uses_only_its_active_key_and_canonical_origin(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-other-key")
    backend = ClaudeBackend("selected-key", model=MODEL)
    try:
        config = selected_main_config(backend, MODEL, "claude")
        assert config is not None
        assert (config.backend, config.base_url, config.model, config.api_key,
                config.is_local, config.wire_mode, config.route_source) == (
                    "anthropic", "https://api.anthropic.com/v1", MODEL,
                    "selected-key", False, "anthropic_messages", "auto:main")
    finally:
        asyncio.run(backend.aclose())


def test_selected_claude_image_uses_native_messages_wire(route, monkeypatch):
    orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "A square."}],
            "stop_reason": "end_turn"})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        assert (status["backend"], status["model"], status["selection_source"]) == (
            "anthropic", MODEL, "auto:main")
        assert status["destination"] == "https://api.anthropic.com/v1"
        assert "selected-key" not in str(status)
        assert route.requests == []

        sent = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["response"] == "A square."
        assert len(route.requests) == 1
        request = route.requests[0]
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers.get("Authorization") is None
        assert request.headers["x-api-key"] == "selected-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        payload = json.loads(request.content)
        assert payload["model"] == MODEL
        assert payload["messages"][0]["role"] == "user"
        image = next(block for block in payload["messages"][0]["content"]
                     if block["type"] == "image")
        assert image["source"]["media_type"] == "image/png"
        assert base64.b64decode(image["source"]["data"]) == base64.b64decode(PNG.partition(",")[2])
        assert len(asyncio.run(orch.memory.get_history(sid))) == 0
    finally:
        asyncio.run(backend.aclose())


def test_selected_claude_refuses_rotated_pool_key_before_image_egress(route, monkeypatch):
    pool = AuthProfilePool(["first-key", "second-key"], provider="anthropic")
    _orch, backend, sid = _selected(monkeypatch, pool=pool)
    try:
        status = _preview(route, sid)
        assert "first-key" not in str(status)
        pool.rotate()
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_claude_requires_explicit_remote_acknowledgement(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    try:
        status = _preview(route, sid)
        body = {**_body(status, sid), "remote_ack": False}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code in {403, 409}, refused.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_anthropic_vision_key_cannot_target_another_origin():
    config = vlm.VLMConfig("anthropic", "https://other.example/v1", MODEL,
                           "selected-key", False, wire_mode="anthropic_messages")
    with pytest.raises(vp.VisionPolicyUnavailable, match="authority"):
        vp.describe(config)


def test_selected_claude_text_only_model_is_not_offered(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    backend.model_vision_capabilities = {MODEL: False}
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 503
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_catalog_text_only_claude_is_not_offered_an_image(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)

    async def prepared(*_args):
        return None

    monkeypatch.setattr(vision_catalog, "prepare_catalog_vision", prepared)
    monkeypatch.setattr(vision_catalog, "cached_vision_eligibility", lambda _config: False)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 503, preview.text
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_claude_uses_fetched_catalog_verdict_before_review(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    calls = []

    async def fetch():
        calls.append("catalog")
        return {"anthropic": {MODEL: False}}

    vision_catalog.reset_cache()
    monkeypatch.setattr(vision_catalog, "_fetch_catalog", fetch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 503, preview.text
        assert calls == ["catalog"]
        assert route.requests == []
    finally:
        vision_catalog.reset_cache()
        asyncio.run(backend.aclose())


def test_catalog_change_after_review_refuses_image_before_egress(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)
    verdict = {"value": True}

    async def prepared(*_args):
        return None

    monkeypatch.setattr(vision_catalog, "prepare_catalog_vision", prepared)
    monkeypatch.setattr(vision_catalog, "cached_vision_eligibility",
                        lambda _config: verdict["value"])
    try:
        status = _preview(route, sid)
        assert status["selection_source"] == "auto:main"
        verdict["value"] = False
        refused = route.client.post("/api/vlm/composer/describe-prepared",
                                    json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_catalog_change_after_review_consume_refuses_physical_send(route, monkeypatch):
    from agents.core.llm.vlm import VLMBackend

    _orch, backend, sid = _selected(monkeypatch)
    verdict = {"value": True}

    async def prepared(*_args):
        return None

    original = VLMBackend.generate_vision_checked

    async def change_before_request(self, *args, **kwargs):
        verdict["value"] = False
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(vision_catalog, "prepare_catalog_vision", prepared)
    monkeypatch.setattr(vision_catalog, "cached_vision_eligibility",
                        lambda _config: verdict["value"])
    try:
        status = _preview(route, sid)
        monkeypatch.setattr(VLMBackend, "generate_vision_checked", change_before_request)
        refused = route.client.post("/api/vlm/composer/describe-prepared",
                                    json=_body(status, sid))
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_claude_refuses_late_key_header_mutation(route, monkeypatch):
    _orch, backend, sid = _selected(monkeypatch)

    async def tamper(request):
        request.headers["x-api-key"] = "different-key"

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json={"type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "Should not arrive."}],
            "stop_reason": "end_turn"})

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
