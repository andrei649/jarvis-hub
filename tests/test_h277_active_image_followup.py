"""Explicit active-image follow-up uses a new review and the selected route."""

import asyncio
import base64
import hashlib
import json
from io import BytesIO
from unittest.mock import AsyncMock

import httpx
from PIL import Image
from starlette.requests import Request

from agents.core.llm import selection_guards as sg
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import route  # noqa: F401
from tests.test_h277_xai_image import _answer, _body, _preview, _selected


def _remember(orch, sid, *, question="Describe this", answer="A blue square."):
    media = {"kind": "image", "count": 1, "model": "grok-4.6",
             "backend": "xai", "local": False}
    asyncio.run(orch.memory.add_turn(sid, "user", f"{question}\n[1 image attached]",
                                     channel="web", media=media))
    asyncio.run(orch.memory.add_turn(sid, "assistant", answer, agent_id="jarvis",
                                     channel="web", media=media))
    conversation = orch.memory.conversation
    instance = conversation.active_image_instance(sid)
    return conversation.active_images.remember(
        sid, instance, "jarvis", question, answer,
        [base64.b64decode(PNG.partition(",")[2])])


def _followup(route, sid, handles, *, images=()):
    prompt = "What is its handle made of?"
    prepared = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": prompt, "agent": "jarvis", "session_id": sid,
        "selected_turn": True, "active_image_handles": list(handles),
        **({"image_digests": [hashlib.sha256(image.encode()).hexdigest()
                               for image in images]} if images else {}),
    })
    assert prepared.status_code == 200, prepared.text
    body = {**_body(prepared.json(), sid, images=list(images)), "prompt": prompt,
            "active_image_handles": list(handles)}
    return body


def test_reviewed_followup_reuses_selected_active_image_once(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    replies = iter(("A blue square with a brass handle.", "The handle is brass."))

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer(next(replies)))

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        first = _preview(route, sid)
        sent = route.client.post("/api/vlm/composer/chat-prepared", json=_body(first, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["committed"] is True

        available = route.client.get("/api/vlm/composer/active-images", params={
            "agent": "jarvis", "session_id": sid,
        })
        assert available.status_code == 200, available.text
        rows = available.json()["images"]
        assert len(rows) == 1
        assert rows[0]["question"] == "Describe this"
        handle = rows[0]["handle"]

        prompt = "What is its handle made of?"
        reviewed = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": prompt, "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "active_image_handles": [handle],
        })
        assert reviewed.status_code == 200, reviewed.text
        followup = {**_body(reviewed.json(), sid, images=[]), "prompt": prompt,
                    "active_image_handles": [handle]}
        sent = route.client.post("/api/vlm/composer/chat-prepared", json=followup)
        assert sent.status_code == 200, sent.text
        assert sent.json()["committed"] is True
        assert sent.json()["response"] == "The handle is brass."
        assert len(route.requests) == 2

        wire = json.loads(route.requests[1].content)
        assert [item["role"] for item in wire["input"]] == ["user", "assistant", "user"]
        assert any(part["type"] == "input_image" for part in wire["input"][0]["content"])
        assert wire["input"][1]["content"] == [{"type": "output_text",
                                                  "text": "A blue square with a brass handle."}]
        assert wire["input"][2]["content"][0]["type"] == "input_text"

        history = asyncio.run(orch.memory.get_history(sid))
        assert [row["role"] for row in history] == ["user", "assistant", "user", "assistant"]
        assert all(row["media"]["count"] == 1 for row in history)
        assert "data:image/" not in repr(history)
        assert len(route.client.get("/api/vlm/composer/active-images", params={
            "agent": "jarvis", "session_id": sid,
        }).json()["images"]) == 1
    finally:
        asyncio.run(backend.aclose())


def test_reviewed_followup_combines_old_and_new_images(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    handle = _remember(orch, sid)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer("Both are blue."))

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        body = _followup(route, sid, [handle], images=[PNG])
        sent = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert sent.status_code == 200, sent.text
        assert sent.json()["committed"] is True
        assert len(route.requests) == 1
        wire = json.loads(route.requests[0].content)
        assert any(part["type"] == "input_image" for part in wire["input"][0]["content"])
        assert any(part["type"] == "input_image" for part in wire["input"][2]["content"])
        history = asyncio.run(orch.memory.get_history(sid))
        assert history[-2]["media"]["count"] == 2
        assert history[-2]["content"].endswith(
            "[1 image attached]\n[1 previous image referenced]")
        handles = orch.memory.conversation.active_images.list(
            sid, orch.memory.conversation.active_image_instance(sid), "jarvis")
        assert len(handles) == 2 and handles[0]["handle"] == handle
    finally:
        asyncio.run(backend.aclose())


def test_new_selected_image_does_not_replay_available_history_implicitly(
        route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _remember(orch, sid)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer("A blue square."))

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        sent = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert len(route.requests) == 1
        wire = json.loads(route.requests[0].content)
        assert [item["role"] for item in wire["input"]] == ["user"]
        assert sum(part["type"] == "input_image" for part in wire["input"][0]["content"]) == 1
    finally:
        asyncio.run(backend.aclose())


def test_ordinary_text_chat_does_not_select_active_image_handles(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _remember(orch, sid)
    monkeypatch.setattr(orch, "handle_input", AsyncMock(return_value="Text answer."))

    def unexpected_history(*_args, **_kwargs):
        raise AssertionError("ordinary text chat requested private image parts")

    monkeypatch.setattr(orch.memory.conversation.active_images, "resolve_turns",
                        unexpected_history)
    try:
        reply = route.client.post("/chat", json={"message": "Can you help?"})
        assert reply.status_code == 200, reply.text
        assert reply.json()["reply"] == "Text answer."
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_optional_active_cache_failure_does_not_disguise_committed_turn(
        route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer("A blue square."))

    def failed_cache(*_args, **_kwargs):
        raise RuntimeError("synthetic cache fault")

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(orch.memory.conversation.active_images, "remember", failed_cache)
    try:
        status = _preview(route, sid)
        sent = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["committed"] is True
        assert len(asyncio.run(orch.memory.get_history(sid))) == 2
    finally:
        asyncio.run(backend.aclose())


def test_reordered_history_burns_review_without_image_egress(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        first = _remember(orch, sid)
        second = orch.memory.conversation.active_images.remember(
            sid, orch.memory.conversation.active_image_instance(sid), "jarvis",
            "Another view", "Still blue.", [base64.b64decode(PNG.partition(",")[2])])
        body = _followup(route, sid, [first, second])
        changed = {**body, "active_image_handles": [second, first]}
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=changed)
        assert refused.status_code == 409
        replay = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert replay.status_code == 409
        assert route.requests == []
        assert len(asyncio.run(orch.memory.get_history(sid))) == 2
    finally:
        asyncio.run(backend.aclose())


def test_changed_fresh_image_burns_history_review_without_egress(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        handle = _remember(orch, sid)
        body = _followup(route, sid, [handle], images=[PNG])
        out = BytesIO()
        Image.new("RGB", (1, 1), "red").save(out, format="PNG")
        changed = {**body, "images": ["data:image/png;base64," +
                                       base64.b64encode(out.getvalue()).decode()]}
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=changed)
        assert refused.status_code == 409
        replay = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert replay.status_code == 409
        assert route.requests == []
        assert len(asyncio.run(orch.memory.get_history(sid))) == 2
    finally:
        asyncio.run(backend.aclose())


def test_reset_same_session_id_makes_active_review_unusable(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        body = _followup(route, sid, [_remember(orch, sid)])
        asyncio.run(orch.memory.clear(sid))
        asyncio.run(orch.memory.new_session(sid))
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert refused.status_code == 409
        assert route.requests == []
        assert asyncio.run(orch.memory.get_history(sid)) == []
    finally:
        asyncio.run(backend.aclose())


def test_rotated_selected_key_refuses_history_before_egress(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        body = _followup(route, sid, [_remember(orch, sid)])
        backend.api_key = "rotated-key"
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert refused.status_code == 409
        assert route.requests == []
        assert len(asyncio.run(orch.memory.get_history(sid))) == 2
    finally:
        asyncio.run(backend.aclose())


def test_new_training_consent_requirement_refuses_old_history_review(
        route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        body = _followup(route, sid, [_remember(orch, sid)])
        def guard(choice):
            return sg.Finding("new_data_policy", "acknowledge_training", choice,
                              "This route now requires training consent")
        monkeypatch.setattr(sg, "GUARDS", [*sg.GUARDS, guard])
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
        assert len(asyncio.run(orch.memory.get_history(sid))) == 2
    finally:
        asyncio.run(backend.aclose())


def test_combined_image_count_over_limit_refuses_before_review(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        _remember(orch, sid)
        conversation = orch.memory.conversation
        raw = base64.b64decode(PNG.partition(",")[2])
        handle = conversation.active_images.remember(
            sid, conversation.active_image_instance(sid), "jarvis", "Two views",
            "Both blue.", [raw, raw])
        prepared = route.client.post("/api/vlm/composer/prepare", json={
            "prompt": "Compare all", "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "active_image_handles": [handle],
            "image_digests": [hashlib.sha256(PNG.encode()).hexdigest()] * 7,
        })
        assert prepared.status_code == 422
        assert prepared.json()["reason"] == "vlm_image_limit"
        assert route.requests == []
    finally:
        asyncio.run(backend.aclose())


def test_physical_guard_refuses_evicted_history_after_review(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        body = _followup(route, sid, [_remember(orch, sid)])

        async def evict(_request):
            orch.memory.conversation.active_images.clear(sid)

        def respond(request):
            route.requests.append(request)
            return httpx.Response(200, json=_answer())

        monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                            llm_async_client(provider, transport=httpx.MockTransport(respond),
                                             event_hooks={"request": [evict]}, **kwargs))
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_destination_changed"
        assert route.requests == []
        assert len(asyncio.run(orch.memory.get_history(sid))) == 2
    finally:
        asyncio.run(backend.aclose())


def test_stopped_history_followup_commits_no_turn_or_new_image(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    try:
        body = _followup(route, sid, [_remember(orch, sid)], images=[PNG])
        state = {"started": False, "cancelled": False}

        async def respond(request):
            route.requests.append(request)
            state["started"] = True
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
            return httpx.Response(200, json=_answer())

        async def disconnected(_request):
            return state["started"]

        monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                            llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
        monkeypatch.setattr(Request, "is_disconnected", disconnected)
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=body)
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_client_disconnected"
        assert state == {"started": True, "cancelled": True}
        assert len(asyncio.run(orch.memory.get_history(sid))) == 2
        assert len(orch.memory.conversation.active_images.list(
            sid, orch.memory.conversation.active_image_instance(sid), "jarvis")) == 1
    finally:
        asyncio.run(backend.aclose())
