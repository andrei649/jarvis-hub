"""Selected Ollama image turns bind exact images and commit only successful replies."""

import base64
import hashlib
import io
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from agents import web
from agents.core.checkpoint import CheckpointManager
from agents.core.llm.base import OllamaBackend
from agents.core.llm.egress import llm_async_client
from agents.core.llm.vision_review import VisionReviewRefused, VisionReviewStore
from agents.core.llm.vision_turn import (
    SelectedImageTurn,
    history_fingerprint,
    prepare_selected_image_turn,
)
from agents.core.memory import conversation, persistence
from agents.core.memory.conversation import ConversationMemory
from agents.core.routers import composer_vision
from tests.test_composer_vision import PNG


@pytest.fixture
def selected(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    checkpoints = CheckpointManager(str(tmp_path / "checkpoints.db"))
    checkpoints.initialize()
    checkpoints.create_session_record("selected_s")
    calls = []
    response = {"done": True, "message": {"role": "assistant", "content": "A blue square."}}
    state = SimpleNamespace(late=None)

    def send(request):
        calls.append(request)
        if state.late:
            state.late()
        return httpx.Response(200, json=response)

    backend = OllamaBackend.__new__(OllamaBackend)
    backend.base_url = "http://127.0.0.1:11434"
    backend.client = llm_async_client(
        "ollama", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(send))
    memory = ConversationMemory(persist=False)
    memory.sessions["selected_s"] = []
    orch = SimpleNamespace(agents={"jarvis": object()}, memory=SimpleNamespace(conversation=memory),
                           checkpoints=checkpoints)
    turn = SelectedImageTurn("selected_s", "jarvis", "prompt-digest", "", backend,
                             "vision-model", "local", "prompt with context")
    turn = SelectedImageTurn(turn.session_id, turn.agent_id, turn.prompt_digest,
                             history_fingerprint(orch, "selected_s"), turn.backend,
                             turn.model, turn.route, turn.prompt)
    orch.llm_router = SimpleNamespace(select_backend=lambda agent, prompt: (
        backend, "vision-model", "local"))

    @asynccontextmanager
    async def lease(_session):
        yield True

    async def complete(**kwargs):
        from agents.core.orchestrator import current_principal

        orch.principals.append(current_principal())
        orch.committed.append(kwargs)
        await memory.add_turn("selected_s", "user", kwargs["question"])
        await memory.add_turn("selected_s", "assistant", kwargs["answer"])

    orch.turn_lease = lease
    orch.complete_selected_image_turn = complete
    orch.committed = []
    orch.principals = []
    orch.prepare_principals = []

    async def prepare(_orch, _body):
        from agents.core.orchestrator import current_principal

        orch.prepare_principals.append(current_principal())
        return turn, composer_vision._selected_destination(turn)

    monkeypatch.setattr(composer_vision, "_selected_turn", prepare)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "USER_TOKEN", "selected-test")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "selected-admin")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "selected-test")
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "selected-admin")
    client = TestClient(web.app, headers={"X-User-Token": "selected-test", "X-Admin-Token": "selected-admin"})
    user_client = TestClient(web.app, headers={"X-User-Token": "selected-test"})
    yield SimpleNamespace(client=client, user_client=user_client, calls=calls, response=response, state=state, orch=orch,
                          memory=memory, turn=turn)
    client.close()
    user_client.close()
    checkpoints.close()


def _review(selected, images=(PNG,), handles=()):
    payload = {"prompt": "What is shown?", "agent": "jarvis", "session_id": "selected_s",
               "image_digests": [hashlib.sha256(image.encode()).hexdigest() for image in images],
               "active_image_handles": list(handles)}
    prepared = selected.client.post("/api/vlm/composer/selected-prepare", json=payload)
    assert prepared.status_code == 200, prepared.text
    public = prepared.json()
    return {"prompt": payload["prompt"], "agent": "jarvis", "session_id": "selected_s",
            "images": list(images), "active_image_handles": list(handles),
            "expected_destination": public["destination"],
            "expected_binding": public["review_token"],
            "review_token": public["review_token"], "remote_ack": False}


def test_selected_ollama_sends_native_chat_and_retains_private_bytes_after_commit(selected):
    payload = _review(selected)
    response = selected.client.post("/api/vlm/composer/selected-chat", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["committed"] is True
    assert selected.orch.committed[0]["model"] == "vision-model"
    assert selected.orch.prepare_principals[0].admin is True
    assert selected.orch.principals[0].channel == "web"
    assert selected.orch.principals[0].admin is True
    assert selected.calls[0].url.path == "/api/chat"
    wire = selected.calls[0].read().decode()
    assert '"images"' in wire and '"model":"vision-model"' in wire
    instance = selected.memory.active_image_instance("selected_s")
    handle = response.json()["active_image_handle"]
    assert selected.memory.active_images.resolve("selected_s", instance, "jarvis", [handle]) == (
        base64.b64decode(PNG.partition(",")[2]),)
    assert base64.b64decode(PNG.partition(",")[2]) not in repr(selected.memory.sessions).encode()


def test_user_scope_cannot_read_prepare_or_send_selected_owner_images(selected):
    instance = selected.memory.active_image_instance("selected_s")
    selected.memory.active_images.remember(
        "selected_s", instance, "jarvis", "private question", "private answer",
        [base64.b64decode(PNG.partition(",")[2])])
    payload = _review(selected)
    prepare = {"prompt": payload["prompt"], "agent": "jarvis", "session_id": "selected_s",
               "image_digests": [hashlib.sha256(PNG.encode()).hexdigest()]}
    listing = selected.user_client.get("/api/vlm/composer/active-images",
                                       params={"session_id": "selected_s", "agent": "jarvis"})
    review = selected.user_client.post("/api/vlm/composer/selected-prepare", json=prepare)
    send = selected.user_client.post("/api/vlm/composer/selected-chat", json=payload)
    assert [listing.status_code, review.status_code, send.status_code] == [401, 401, 401]
    assert selected.user_client.post("/api/vlm/composer/describe", json={}).status_code == 422
    assert "private question" not in listing.text
    assert selected.calls == [] and selected.orch.committed == []
    assert len(selected.orch.prepare_principals) == 1
    assert selected.memory.sessions["selected_s"] == []


def test_user_scope_cannot_use_legacy_selected_turn_routes(selected):
    prepare = {"prompt": "What is shown?", "agent": "jarvis",
               "session_id": "selected_s", "selected_turn": True,
               "image_digests": [hashlib.sha256(PNG.encode()).hexdigest()]}
    send = {"prompt": "What is shown?", "agent": "jarvis",
            "session_id": "selected_s", "selected_turn": True,
            "images": [PNG], "review_token": "unusable-review-token-123456",
            "expected_destination": "http://127.0.0.1:11434", "expected_binding": "0" * 64}
    assert selected.user_client.post("/api/vlm/composer/prepare", json=prepare).status_code == 401
    assert selected.user_client.post("/api/vlm/composer/describe-prepared", json=send).status_code == 401
    assert selected.user_client.post("/api/vlm/composer/chat-prepared", json=send).status_code == 401
    assert selected.calls == [] and selected.orch.committed == []


def test_selected_review_binds_resolved_owner_profile():
    store = VisionReviewStore()
    args = {"session_id": "selected_s", "agent_id": "jarvis", "prompt": "question",
            "model": "vision-model", "route": "local", "binding": ("exact images",)}
    token = store.issue(**args, principal=("web", None, True, None))
    with pytest.raises(VisionReviewRefused, match="vlm_destination_changed"):
        store.consume(token, **args, principal=("web", None, False, None))
    with pytest.raises(VisionReviewRefused, match="vlm_review_unavailable"):
        store.consume(token, **args, principal=("web", None, True, None))


def test_changed_image_burns_review_without_sending(selected):
    payload = _review(selected)
    image = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(image, "PNG")
    payload["images"] = ["data:image/png;base64," + base64.b64encode(image.getvalue()).decode()]
    assert selected.client.post("/api/vlm/composer/selected-chat", json=payload).status_code == 409
    assert selected.client.post("/api/vlm/composer/selected-chat", json={
        **payload, "images": [PNG]}).status_code == 409
    assert selected.calls == [] and selected.orch.committed == []


def test_failed_ollama_answer_does_not_commit_or_retain(selected):
    payload = _review(selected)
    selected.response["message"]["content"] = ""
    response = selected.client.post("/api/vlm/composer/selected-chat", json=payload)
    assert response.status_code == 502
    assert selected.orch.committed == []
    instance = selected.memory.active_image_instance("selected_s")
    assert selected.memory.active_images.list("selected_s", instance, "jarvis") == []


def test_active_image_reuse_requires_a_fresh_review_on_the_same_session(selected):
    instance = selected.memory.active_image_instance("selected_s")
    handle = selected.memory.active_images.remember(
        "selected_s", instance, "jarvis", "Earlier question", "Earlier answer",
        [base64.b64decode(PNG.partition(",")[2])])
    payload = _review(selected, images=(), handles=(handle,))
    response = selected.client.post("/api/vlm/composer/selected-chat", json=payload)
    assert response.status_code == 200, response.text
    wire = selected.calls[0].read().decode()
    assert '"content":"Earlier answer"' in wire
    assert wire.count('"images"') == 1
    assert selected.client.post("/api/vlm/composer/selected-chat", json=payload).status_code == 409
    assert len(selected.calls) == 1


def test_route_change_after_review_refuses_before_wire(selected):
    payload = _review(selected)
    selected.orch.llm_router.select_backend = lambda agent, prompt: (
        selected.turn.backend, "different-model", "local")
    response = selected.client.post("/api/vlm/composer/selected-chat", json=payload)
    assert response.status_code == 409
    assert selected.calls == [] and selected.orch.committed == []


def test_route_change_during_wire_refuses_commit(selected):
    payload = _review(selected)
    selected.state.late = lambda: setattr(
        selected.orch.llm_router, "select_backend",
        lambda agent, prompt: (selected.turn.backend, "changed-model", "local"))
    response = selected.client.post("/api/vlm/composer/selected-chat", json=payload)
    assert response.status_code == 409
    assert len(selected.calls) == 1 and selected.orch.committed == []


@pytest.mark.asyncio
async def test_turn_preparation_selects_from_the_current_agent_prompt(selected):
    orch = selected.orch
    orch._session_id_default = "selected_s"
    orch.get_setting = lambda key, default: default

    async def history(session, last_n):
        assert session == "selected_s"
        return [{"role": "user", "content": "Earlier context"}]

    async def classify(question, agents):
        return SimpleNamespace(context="intent")

    async def turn_text(agent, question, **kwargs):
        assert agent == "jarvis" and question == "What is shown?"
        return question + kwargs["history"]

    orch.memory.get_history = history
    orch.router = SimpleNamespace(classify_deterministic=classify)
    orch._runtime_state_block = lambda: ""
    orch._language_block = lambda: ""
    orch._data_grounding_block = lambda data: ""
    orch._build_agent_turn_text = turn_text
    orch._build_agent_prompt = lambda agent, text, context: text + context
    await selected.memory.add_turn("selected_s", "user", "Earlier context")
    turn = await prepare_selected_image_turn(
        orch, question="What is shown?", agent_id="jarvis", session_id="selected_s")
    assert turn.backend is selected.turn.backend
    assert turn.model == "vision-model" and turn.route == "local"
    assert turn.prompt == "What is shown?[user]: Earlier contextintent"
