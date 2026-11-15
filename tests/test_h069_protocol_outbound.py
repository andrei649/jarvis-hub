"""H069: model prose crosses the OpenAI and Workspace HTTP/SSE safety gate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core.channels import outbound_safety
from tests.support.workspace_fixtures import (  # noqa: F401 - pytest fixtures
    FakeEngine,
    db,
    login,
    seed_company,
    ws,
)
from tests.test_g12_openai_compat import (  # noqa: F401 - pytest fixtures
    _auth,
    _chat,
    _events,
    _frames,
    _key,
    client,
    enabled,
    hub,
    settings,
    store,
)
from tests.test_workspace_assistant_helpers import (
    ask,
    ask_stream,
    chat_client,
    message_row,
    new_conversation,
    parse_sse,
)


@pytest.fixture
def credential(monkeypatch):
    value = "split white secret 123456"
    monkeypatch.setenv("JARVIS_H069_TEST_TOKEN", value)
    return value


@pytest.fixture
def workspace(ws):
    conn = db()
    company = seed_company(conn)
    client = chat_client()
    csrf = login(client, company.member_a.email)
    conversation_id = new_conversation(client, csrf, company.dept_a)
    yield SimpleNamespace(ws=ws, conn=conn, client=client, csrf=csrf,
                          conversation_id=conversation_id)
    conn.close()


def _chat_text(body: str) -> str:
    return "".join(frame["choices"][0]["delta"].get("content", "")
                   for frame in _frames(body)[:-1] if frame.get("choices"))


def _responses_text(body: str) -> tuple[str, dict]:
    events = _events(body)
    delta = "".join(data["delta"] for kind, data in events
                    if kind == "response.output_text.delta")
    return delta, events[-1][1]["response"]


@pytest.mark.parametrize("stream", [False, True])
def test_openai_chat_redacts_split_credential_at_the_route(
        enabled, store, hub, client, credential, stream):
    key, _ = _key(store, owner=True)
    hub.reply = f"Here is {credential} and safe prose."
    reply = client.post("/v1/chat/completions", json=_chat("user input", stream=stream),
                        headers=_auth(key))
    assert reply.status_code == 200
    assert credential not in reply.text
    shown = _chat_text(reply.text) if stream else reply.json()["choices"][0]["message"]["content"]
    assert "[REDACTED:JARVIS_H069_TEST_TOKEN]" in shown
    assert hub.seen[-1]["text"] == "user input"


@pytest.mark.parametrize("stream", [False, True])
def test_openai_responses_redacts_and_stores_only_safe_prose(
        enabled, store, hub, client, credential, stream):
    key, _ = _key(store, owner=True)
    hub.reply = f"Here is {credential} and safe prose."
    reply = client.post("/v1/responses", json={"input": "user input", "stream": stream},
                        headers=_auth(key))
    assert reply.status_code == 200
    assert credential not in reply.text
    shown, done = _responses_text(reply.text) if stream else (reply.json()["output_text"], reply.json())
    assert shown == done["output_text"]
    assert "[REDACTED:JARVIS_H069_TEST_TOKEN]" in shown
    stored = client.get(f"/v1/responses/{done['id']}", headers=_auth(key))
    assert stored.status_code == 200 and stored.json()["output_text"] == shown


@pytest.mark.parametrize("path", ["chat", "responses"])
def test_openai_stream_waits_for_final_prose_and_suppresses_markers(
        enabled, store, hub, client, monkeypatch, path):
    async def divergent(_text, _channel, on_token, _agent_override, _session_id):
        await on_token("[Claude API error: Error code: 401 - private request_id]")
        await on_token("[SILENT]")
        return "Final safe answer."

    monkeypatch.setattr(hub.orch, "_handle_input_stream", divergent)
    key, _ = _key(store, owner=True)
    if path == "chat":
        reply = client.post("/v1/chat/completions", json=_chat(stream=True), headers=_auth(key))
        shown = _chat_text(reply.text)
    else:
        reply = client.post("/v1/responses", json={"input": "x", "stream": True},
                            headers=_auth(key))
        shown, done = _responses_text(reply.text)
        assert done["output_text"] == shown
    assert reply.status_code == 200
    assert shown == "Final safe answer."
    assert "request_id" not in reply.text and "[SILENT]" not in reply.text


@pytest.mark.parametrize("path", ["chat", "responses"])
@pytest.mark.parametrize("reply_text", [
    "[SILENT]",
    "[Claude API error: Error code: 401 - private request_id]",
])
def test_openai_final_marker_is_safe_in_json_and_stream(
        enabled, store, hub, client, path, reply_text):
    key, _ = _key(store, owner=True)
    hub.reply = reply_text
    expected = "" if reply_text == "[SILENT]" else outbound_safety.sanitize_text(reply_text)
    for stream in (False, True):
        if path == "chat":
            reply = client.post("/v1/chat/completions", json=_chat(stream=stream), headers=_auth(key))
            shown = _chat_text(reply.text) if stream else reply.json()["choices"][0]["message"]["content"]
        else:
            reply = client.post("/v1/responses", json={"input": "x", "stream": stream},
                                headers=_auth(key))
            shown = _responses_text(reply.text)[0] if stream else reply.json()["output_text"]
        assert reply.status_code == 200
        assert shown == expected
        assert "request_id" not in reply.text and "[SILENT]" not in reply.text


def test_openai_get_rechecks_late_credential_without_rewriting_client_fields(
        enabled, store, hub, client, monkeypatch):
    key, record = _key(store, owner=True)
    raw = "late known secret 987654"
    hub.reply = f"The answer contains {raw}."
    created = client.post("/v1/responses", json={"input": "user input", "instructions": raw},
                          headers=_auth(key))
    assert created.status_code == 200 and raw in created.json()["output_text"]
    response_id = created.json()["id"]
    monkeypatch.setenv("JARVIS_H069_LATE_TOKEN", raw)
    fetched = client.get(f"/v1/responses/{response_id}", headers=_auth(key))
    assert fetched.status_code == 200
    data = fetched.json()
    assert raw not in data["output_text"]
    assert data["output"][0]["content"][0]["text"] == data["output_text"]
    assert data["instructions"] == raw
    assert data["id"] == response_id
    assert raw in store.get_response(response_id, record.key_id)[1]["output_text"]


@pytest.mark.parametrize("path", ["chat", "responses"])
def test_openai_failed_stream_never_replays_provisional_text(
        enabled, store, hub, client, monkeypatch, path):
    async def fails(_text, _channel, on_token, _agent_override, _session_id):
        await on_token("provisional private provider detail")
        raise RuntimeError("model stopped")

    monkeypatch.setattr(hub.orch, "_handle_input_stream", fails)
    key, _ = _key(store, owner=True)
    if path == "chat":
        reply = client.post("/v1/chat/completions", json=_chat(stream=True), headers=_auth(key))
        assert _chat_text(reply.text) == ""
    else:
        reply = client.post("/v1/responses", json={"input": "x", "stream": True},
                            headers=_auth(key))
        assert _responses_text(reply.text)[0] == ""
    assert reply.status_code == 200
    assert "provisional private provider detail" not in reply.text


def test_openai_opaque_redactor_failure_withholds_stream_prose(
        enabled, store, hub, client, monkeypatch):
    def broken(_text):
        raise RuntimeError("redactor offline")

    monkeypatch.setattr(outbound_safety, "_known_redactor", broken)
    hub.reply = "private unclassified credential"
    key, _ = _key(store, owner=True)
    reply = client.post("/v1/chat/completions", json=_chat(stream=True), headers=_auth(key))
    assert reply.status_code == 200
    assert _chat_text(reply.text) == "A reply could not be checked before sending, so it was withheld."
    assert "private unclassified credential" not in reply.text


@pytest.mark.parametrize("stream", [False, True])
def test_workspace_stores_and_delivers_sanitized_assistant_prose(workspace, credential, stream):
    workspace.ws.use_engine(FakeEngine(reply=f"The answer has {credential} inside."))
    if stream:
        response, body = ask_stream(workspace.client, workspace.csrf,
                                    workspace.conversation_id, "What is this?")
        events = parse_sse(body)
        shown = "".join(data["t"] for kind, data in events if kind == "token")
        message = events[-1][1]["assistant_message"]
        assert shown == message["content"]
    else:
        response = ask(workspace.client, workspace.csrf, workspace.conversation_id,
                       "What is this?")
        message = response.json()["assistant_message"]
    assert response.status_code == (200 if stream else 201)
    assert credential not in (body if stream else response.text)
    assert "[REDACTED:JARVIS_H069_TEST_TOKEN]" in message["content"]
    assert message_row(workspace.conn, message["id"])["content"] == message["content"]


def test_workspace_history_rechecks_late_secret_and_preserves_user_input(workspace, monkeypatch):
    raw = "late known secret 987654"
    workspace.ws.use_engine(FakeEngine(reply=f"Answer contains {raw}."))
    created = ask(workspace.client, workspace.csrf, workspace.conversation_id, raw)
    assert created.status_code == 201
    assistant_id = created.json()["assistant_message"]["id"]
    assert raw in message_row(workspace.conn, assistant_id)["content"]
    monkeypatch.setenv("JARVIS_H069_LATE_TOKEN", raw)
    history = workspace.client.get(f"/api/workspace/conversations/{workspace.conversation_id}")
    assert history.status_code == 200
    user, assistant = history.json()["messages"]
    assert user["role"] == "user" and user["content"] == raw
    assert assistant["role"] == "assistant" and raw not in assistant["content"]
    assert "[REDACTED:JARVIS_H069_LATE_TOKEN]" in assistant["content"]
    assert raw in message_row(workspace.conn, assistant_id)["content"]


def test_workspace_opaque_redactor_failure_withholds_stream_and_storage(workspace, monkeypatch):
    def broken(_text):
        raise RuntimeError("redactor offline")

    monkeypatch.setattr(outbound_safety, "_known_redactor", broken)
    raw = "private unclassified credential"
    workspace.ws.use_engine(FakeEngine(reply=raw))
    response, body = ask_stream(workspace.client, workspace.csrf,
                                workspace.conversation_id, "What is this?")
    events = parse_sse(body)
    message = events[-1][1]["assistant_message"]
    assert response.status_code == 200
    assert message["content"] == "A reply could not be checked before sending, so it was withheld."
    assert raw not in body
    assert message_row(workspace.conn, message["id"])["content"] == message["content"]


def test_workspace_stream_holds_provider_marker_and_suppresses_silence(workspace):
    for raw in ("[SILENT]", "[Claude API error: Error code: 401 - private request_id]"):
        workspace.ws.use_engine(FakeEngine(reply=raw))
        response, body = ask_stream(workspace.client, workspace.csrf,
                                    workspace.conversation_id, "What is this?")
        events = parse_sse(body)
        message = events[-1][1]["assistant_message"]
        shown = "".join(data["t"] for kind, data in events if kind == "token")
        assert response.status_code == 200
        assert shown == message["content"]
        assert message["content"] == ""
        assert events[-1][0] == ("done" if raw == "[SILENT]" else "error")
        assert "request_id" not in body and "[SILENT]" not in body
        assert message_row(workspace.conn, message["id"])["content"] == message["content"]
