"""A reviewed selected image belongs to the server conversation."""

import asyncio
from contextlib import asynccontextmanager

import httpx
from starlette.requests import Request

from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client
from agents.core.llm.vision_turn import prepare_selected_image_turn
from tests.test_h277_selected_composer import _bind_native_store
from tests.test_h277_vision_auto_consumer import route  # noqa: F401
from tests.test_h277_xai_image import _answer, _body, _preview, _selected


def test_selected_image_commits_one_real_conversation_turn(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer("A blue square."))

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        sent = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert sent.status_code == 200, sent.text
        assert sent.json()["committed"] is True
        assert sent.json()["response"] == "A blue square."
        assert len(route.requests) == 1

        history = asyncio.run(orch.memory.get_history(sid))
        assert [(row["role"], row["content"]) for row in history] == [
            ("user", "Describe this\n[1 image attached]"),
            ("assistant", "A blue square."),
        ]
        assert all(row["media"] == {"kind": "image", "count": 1,
                                     "model": "grok-4.6", "backend": "xai", "local": False}
                   for row in history)
        memory = route.client.get("/memory")
        assert memory.status_code == 200
        assert len(memory.json()["turns"]) == 2

        followup = asyncio.run(prepare_selected_image_turn(
            orch, question="What color was it?", agent_id="jarvis", session_id=sid))
        assert "A blue square." in followup.prompt
    finally:
        asyncio.run(backend.aclose())


def test_busy_selected_session_refuses_before_image_send(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)
    try:
        status = _preview(route, sid)

        @asynccontextmanager
        async def busy(_session):
            yield False

        monkeypatch.setattr(orch, "turn_lease", busy)
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_turn_busy"
        assert route.requests == []
        assert asyncio.run(orch.memory.get_history(sid)) == []
    finally:
        asyncio.run(backend.aclose())


def test_changed_history_refuses_selected_image_before_egress(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)
    try:
        status = _preview(route, sid)
        asyncio.run(orch.memory.add_turn(sid, "user", "A newer message."))
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert refused.status_code == 409
        assert route.requests == []
        assert len(asyncio.run(orch.memory.get_history(sid))) == 1
    finally:
        asyncio.run(backend.aclose())


def test_failed_provider_writes_no_successful_image_pair(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(503, json={"error": "synthetic failure"})

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert refused.status_code == 502
        assert len(route.requests) == 1
        assert asyncio.run(orch.memory.get_history(sid)) == []
    finally:
        asyncio.run(backend.aclose())


def test_changed_key_refuses_selected_conversation_before_egress(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)
    try:
        status = _preview(route, sid)
        backend.api_key = "rotated-key"
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert refused.status_code == 409
        assert route.requests == []
        assert asyncio.run(orch.memory.get_history(sid)) == []
    finally:
        asyncio.run(backend.aclose())


def test_reset_refuses_selected_conversation_before_egress(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)
    try:
        status = _preview(route, sid)
        orch._session_id_default = "new_shared_session"
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert refused.status_code == 409
        assert route.requests == []
        assert asyncio.run(orch.memory.get_history(sid)) == []
    finally:
        asyncio.run(backend.aclose())


def test_disconnected_client_does_not_commit_provider_answer(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)

    def respond(request):
        route.requests.append(request)
        return httpx.Response(200, json=_answer("A blue square."))

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(Request, "is_disconnected", lambda _request: asyncio.sleep(0, result=True))
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_client_disconnected"
        assert asyncio.run(orch.memory.get_history(sid)) == []
    finally:
        asyncio.run(backend.aclose())


def test_client_stop_cancels_slow_image_request(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch, backend, sid = _selected(monkeypatch)
    _bind_native_store(orch, monkeypatch, tmp_path, sid)
    events = {"started": False, "cancelled": False}

    async def respond(request):
        route.requests.append(request)
        events["started"] = True
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            events["cancelled"] = True
            raise
        return httpx.Response(200, json=_answer("Too late."))

    async def disconnected(_request):
        return events["started"]

    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    try:
        status = _preview(route, sid)
        refused = route.client.post("/api/vlm/composer/chat-prepared", json=_body(status, sid))
        assert refused.status_code == 409
        assert refused.json()["reason"] == "vlm_client_disconnected"
        assert events == {"started": True, "cancelled": True}
        assert len(route.requests) == 1
        assert asyncio.run(orch.memory.get_history(sid)) == []
    finally:
        asyncio.run(backend.aclose())
