"""Prepared browser image sends must use the active conversation route."""

import asyncio
import json

import pytest

from agents import web
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.providers import DEFAULT_REGISTRY
from agents.core.llm.vision_review import VisionReviewRefused, VisionReviewStore
from agents.core.orchestrator import Orchestrator
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401


def _bind_local(monkeypatch, agent="jarvis"):
    orch = Orchestrator(JarvisConfig())
    orch.agents[agent] = Agent(agent, {}, orch.llm_router)
    backend = LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, "local/vision", "local")
    sid = asyncio.run(orch.memory.new_session("selected_image_turn"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    return orch, backend, sid


def test_selected_image_turn_sends_to_main_local_model(route, monkeypatch):
    orch, backend, sid = _bind_local(monkeypatch)
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
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
    backend.model_vision_capabilities = {"local/vision": False}
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
            "selected_turn": True,
        })
        assert preview.status_code == 200, preview.text
        status = preview.json()
        assert status["selection_source"] == "auto:openrouter"
        assert status["backend"] == "openrouter"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_strict_local_agent_never_discovers_remote_image_fallback(route, monkeypatch):
    _orch, backend, sid = _bind_local(monkeypatch, agent="frigga")
    backend.model_vision_capabilities = {"local/vision": False}
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    try:
        preview = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Describe this", "agent": "frigga", "session_id": sid,
            "selected_turn": True,
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
