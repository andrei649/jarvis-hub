"""Prepared browser image sends must use the active conversation route."""

import asyncio
import base64
import hashlib
import io
import json

import httpx
import pytest
from PIL import Image

from agents import web
from agents.core import settings_db
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.egress import llm_async_client
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.providers import DEFAULT_REGISTRY
from agents.core.llm.vision_review import VisionReviewRefused, VisionReviewStore
from agents.core.orchestrator import Orchestrator
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401

IMAGE_DIGEST = hashlib.sha256(PNG.encode("utf-8")).hexdigest()


def _bind_local(monkeypatch, agent="jarvis"):
    orch = Orchestrator(JarvisConfig())
    orch.agents[agent] = Agent(agent, {}, orch.llm_router)
    backend = LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "local/vision", "local")
    sid = asyncio.run(orch.memory.new_session("selected_image_turn"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    return orch, backend, sid


def _local_model_metadata(backend, *, vision: bool, requests=None):
    asyncio.run(backend.client.aclose())

    def local_models(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(200, json={"models": [{
            "key": "local/vision", "type": "llm",
            "capabilities": {"vision": vision},
        }]})

    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(local_models),
    )


def test_selected_review_requires_image_digests_before_issuing_token(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
        })
        assert preview.status_code == 422
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_review_refuses_a_different_image_after_preflight(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch)
    image_digest = hashlib.sha256(PNG.encode("utf-8")).hexdigest()
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [image_digest],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        changed = io.BytesIO()
        Image.new("RGB", (1, 1), (255, 0, 0)).save(changed, format="PNG")
        another = "data:image/png;base64," + base64.b64encode(changed.getvalue()).decode()
        assert another != PNG
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"],
                "images": [another]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
        replay = route.client.post("/api/vlm/composer/describe-prepared", json={
            **body, "images": [PNG]})
        assert replay.status_code == 409
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_review_refuses_reordered_images(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch)
    changed = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(changed, format="PNG")
    another = "data:image/png;base64," + base64.b64encode(changed.getvalue()).decode()
    assert another != PNG
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST, hashlib.sha256(another.encode("utf-8")).hexdigest()],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"],
                "images": [another, PNG]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert route.requests == []
        replay = route.client.post("/api/vlm/composer/describe-prepared", json={
            **body, "images": [PNG, another]})
        assert replay.status_code == 409
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_image_turn_sends_to_main_local_model(route, monkeypatch):
    orch, backend, sid = _bind_local(monkeypatch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        assert (status["backend"], status["model"], status["selection_source"]) == (
            "lmstudio", "local/vision", "auto:main"
        )
        assert status["session_id"] == sid
        assert route.requests == []

        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        sent = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert sent.status_code == 200, sent.text
        assert len(route.requests) == 1
        request = route.requests[0]
        assert str(request.url) == "http://127.0.0.1:1234/v1/chat/completions"
        assert json.loads(request.content)["model"] == "local/vision"
        assert len(asyncio.run(orch.memory.get_history(sid))) == 0
    finally:
        asyncio.run(backend.aclose())


def test_selected_image_turn_refuses_changed_history_before_egress(route, monkeypatch):
    orch, backend, sid = _bind_local(monkeypatch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        asyncio.run(orch.memory.add_turn(sid, "assistant", "New context", agent_id="jarvis"))
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_image_turn_skips_explicitly_text_only_main(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch)
    _local_model_metadata(backend, vision=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        assert status["selection_source"] == "auto:openrouter"
        assert status["backend"] == "openrouter"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_image_turn_uses_local_model_vision_metadata(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch)
    metadata = []
    _local_model_metadata(backend, vision=False, requests=metadata)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        assert preview.json()["selection_source"] == "auto:openrouter"
        assert len(metadata) == 1
        assert metadata[0].method == "GET"
        assert str(metadata[0].url) == "http://127.0.0.1:1234/api/v1/models"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_changed_local_vision_capability_invalidates_image_review(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch)
    asyncio.run(backend.client.aclose())
    verdicts = iter((True, False))
    metadata = []

    def local_models(request):
        metadata.append(request)
        return httpx.Response(200, json={"models": [{
            "key": "local/vision", "type": "llm",
            "capabilities": {"vision": next(verdicts)},
        }]})

    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(local_models),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        assert status["selection_source"] == "auto:main"
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert len(metadata) == 2 and route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_changed_owner_model_declaration_invalidates_image_review(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch)
    rows = [{"backend": "lmstudio", "base_url": "http://127.0.0.1:1234/v1",
             "model": "local/vision", "supports_vision": True}]
    original_read = settings_db.read_setting

    def read(category, key):
        if (category, key) == ("llm", "vision_model_capabilities"):
            return True, rows
        return original_read(category, key)

    monkeypatch.setattr(settings_db, "read_setting", read)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        assert status["selection_source"] == "auto:main"
        rows[0]["supports_vision"] = False
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_owner_declaration_change_after_consume_refuses_physical_request(route, monkeypatch):
    from agents.core.llm.vlm import VLMBackend

    _orch, backend, sid = _bind_local(monkeypatch)
    rows = [{"backend": "lmstudio", "base_url": "http://127.0.0.1:1234/v1",
             "model": "local/vision", "supports_vision": True}]
    original_read = settings_db.read_setting

    def read(category, key):
        if (category, key) == ("llm", "vision_model_capabilities"):
            return True, rows
        return original_read(category, key)

    original_generate = VLMBackend.generate_vision_checked

    async def change_before_request(self, *args, **kwargs):
        rows[0]["supports_vision"] = False
        return await original_generate(self, *args, **kwargs)

    monkeypatch.setattr(settings_db, "read_setting", read)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        monkeypatch.setattr(VLMBackend, "generate_vision_checked", change_before_request)
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_unselected_composer_status_does_not_probe_main_metadata(route, monkeypatch):
    _orch, backend, _sid = _bind_local(monkeypatch)
    asyncio.run(backend.client.aclose())
    metadata = []
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(
            lambda request: (metadata.append(request), httpx.Response(500))[1]
        ),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        status = route.client.get("/api/vlm/composer/status")
        assert status.status_code == 200
        assert status.json()["selection_source"] == "auto:openrouter"
        assert metadata == []
    finally:
        asyncio.run(backend.aclose())


def test_strict_local_agent_never_discovers_remote_image_fallback(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch, agent="frigga")
    _local_model_metadata(backend, vision=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "frigga", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 503
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_review_cannot_change_agent_before_image_egress(route, monkeypatch):
    orch, backend, sid = _bind_local(monkeypatch)
    orch.agents["athena"] = Agent("athena", {}, orch.llm_router)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        body = {**approved(status), "agent": "athena", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_review_fingerprint_binds_agent_with_identical_route():
    store = VisionReviewStore()
    claim = {"session_id": "shared-session", "prompt": "Describe this",
             "model": "local/vision", "route": "turn:same-prompt:auto:main",
             "binding": ("lmstudio", "http://127.0.0.1:1234/v1", "local/vision")}
    token = store.issue(agent_id="jarvis", **claim)
    with pytest.raises(VisionReviewRefused, match="vlm_destination_changed"):
        store.consume(token, agent_id="athena", **claim)
    with pytest.raises(VisionReviewRefused, match="vlm_review_unavailable"):
        store.consume(token, agent_id="jarvis", **claim)


def test_selected_remote_model_uses_only_its_backend_key_and_origin(route, monkeypatch):
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = OpenRouterBackend(
        api_key="selected-private-key", base_url="https://selected.example/api/v1",
        client=object(), profile=DEFAULT_REGISTRY.get("openrouter"),
    )
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "vendor/vision", "cloud-compatible")
    sid = asyncio.run(orch.memory.new_session("selected_remote_image"))
    orch._session_id_default = sid
    asyncio.run(orch.memory.add_turn(sid, "user", "Earlier private conversation context"))
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-other-key")

    preview = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
        "selected_turn": True,
        "image_digests": [IMAGE_DIGEST],
    })
    assert preview.status_code == 200, preview.text
    status = preview.json()
    assert (status["destination"], status["model"], status["selection_source"]) == (
        "https://selected.example/api/v1", "vendor/vision", "auto:main"
    )
    assert "selected-private-key" not in str(status)
    assert "ambient-other-key" not in str(status)
    body = {**approved(status), "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "review_token": status["review_token"]}
    if any(item["needs"] == "acknowledge_training" for item in status.get("selection_requirements", [])):
        body["acknowledge_training"] = True
    if any(item["needs"] == "confirm_expensive" for item in status.get("selection_requirements", [])):
        body["confirm_expensive"] = True
    sent = route.client.post("/api/vlm/composer/describe-prepared", json=body)
    assert sent.status_code == 200, sent.text
    assert len(route.requests) == 1
    request = route.requests[0]
    assert str(request.url) == "https://selected.example/api/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer selected-private-key"
    payload = json.loads(request.content)
    assert payload["model"] == "vendor/vision"
    assert "Earlier private conversation context" in str(payload["messages"])


def test_selected_route_change_after_review_refuses_before_image_egress(route, monkeypatch):
    orch, backend, sid = _bind_local(monkeypatch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "other-model", "local")
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_review_cannot_cross_sessions(route, monkeypatch):
    orch, backend, sid = _bind_local(monkeypatch)
    other = asyncio.run(orch.memory.new_session("selected_other_session"))
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        body = {**approved(status), "agent": "jarvis", "session_id": other,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_review_refuses_when_shared_chat_moves_to_another_session(route, monkeypatch):
    orch, backend, sid = _bind_local(monkeypatch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        other = asyncio.run(orch.memory.new_session("new_shared_chat"))
        orch._session_id_default = other
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_selected_session_switch_after_review_consume_refuses_at_physical_guard(route, monkeypatch):
    from agents.core.llm.vlm import VLMBackend

    orch, backend, sid = _bind_local(monkeypatch)
    other = asyncio.run(orch.memory.new_session("new_shared_chat"))
    original = VLMBackend.generate_vision_checked

    async def switch_before_request(self, *args, **kwargs):
        orch._session_id_default = other
        return await original(self, *args, **kwargs)

    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        monkeypatch.setattr(VLMBackend, "generate_vision_checked", switch_before_request)
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        orch._session_id_default = sid
        asyncio.run(backend.aclose())


def test_selected_route_switch_after_review_consume_refuses_at_physical_guard(route, monkeypatch):
    from agents.core.llm.vlm import VLMBackend

    orch, backend, sid = _bind_local(monkeypatch)
    original = VLMBackend.generate_vision_checked

    async def switch_before_request(self, *args, **kwargs):
        orch.llm_router.select_backend = lambda _agent, _prompt: (
            backend, "local/vision", "local-after-review"
        )
        return await original(self, *args, **kwargs)

    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
            "image_digests": [IMAGE_DIGEST],
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        monkeypatch.setattr(VLMBackend, "generate_vision_checked", switch_before_request)
        body = {**approved(status), "agent": "jarvis", "session_id": sid,
                "selected_turn": True, "review_token": status["review_token"]}
        refused = route.client.post("/api/vlm/composer/describe-prepared", json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())
