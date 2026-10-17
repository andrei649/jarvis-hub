"""The streamed answer: SSE framing, events, pings, hold-back and the pending row (spec §8).

TestClient buffers a streamed body, which is enough for framing and ordering. A
client that goes away mid-answer is driven at the ASGI level instead: the app gets an
``http.disconnect`` right after the first token, exactly as uvicorn delivers one.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agents.core.routers import workspace_chat
from agents.core.workspace import db as workspace_db
from agents.core.workspace import llm
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    FakeEngine,
    authed,
    db,
    login,
    origin_of,
    seed_company,
    ws,
)
from tests.test_workspace_assistant_helpers import (
    SSE_ACCEPT,
    ask_stream,
    chat_app,
    chat_client,
    live_answers,
    message_row,
    new_conversation,
    parse_sse,
    seed_doc,
)

LONG_REPLY = ("Conform politicii interne, concediul anual de odihnă este de 21 de zile "
              "lucrătoare, iar cererea se depune cu cel puțin zece zile înainte [1]. "
              "Zilele neefectuate se pot reporta până la finalul lunii martie [2].")
UNREACHABLE = "⚠️ I can't reach the local LM Studio model right now. Start LM Studio and retry."


@pytest.fixture
def cast(ws):
    conn = db()
    company = seed_company(conn)
    client = chat_client()
    csrf = login(client, company.member_a.email)
    conversation_id = new_conversation(client, csrf, company.dept_a)
    yield SimpleNamespace(conn=conn, company=company, client=client, csrf=csrf, ws=ws,
                          conversation_id=conversation_id)
    conn.close()


def _stream(cast, content: str = "Câte zile de concediu avem?"):
    response, body = ask_stream(cast.client, cast.csrf, cast.conversation_id, content)
    return response, body, parse_sse(body)


def _kinds(events) -> list[str]:
    return [kind for kind, _ in events]


# ── the happy path ───────────────────────────────────────────────────────────────────

def test_the_stream_is_start_sources_tokens_done_with_sse_headers(cast):
    seed_doc(cast.conn, department_id=cast.company.dept_a, title="Politica de concedii",
             text="Concediul anual este de 21 de zile lucrătoare. Se cere din timp.")
    response, body, events = _stream(cast)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    kinds = _kinds(events)
    assert kinds[:2] == ["start", "sources"] and kinds[-1] == "done"
    assert set(kinds[2:-1]) == {"token"}
    for frame in body.strip().split("\n\n"):
        lines = frame.split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
        json.loads(lines[1][len("data: "):])


def test_start_carries_the_question_the_answer_id_and_the_new_title(cast):
    _, _, events = _stream(cast, "Care este politica de concedii?")
    start = events[0][1]
    assert start["user_message"]["role"] == "user"
    assert start["user_message"]["content"] == "Care este politica de concedii?"
    assert isinstance(start["assistant_message_id"], int)
    assert start["conversation"]["title"] == "Care este politica de concedii?"
    assert events[-1][1]["assistant_message"]["id"] == start["assistant_message_id"]


def test_sources_list_every_retrieved_passage_and_done_keeps_only_the_cited(cast):
    seed_doc(cast.conn, department_id=cast.company.dept_a, title="Politica de concedii",
             text="Concediul anual este de 21 de zile lucrătoare.")
    seed_doc(cast.conn, department_id=None, visibility="company", title="Regulament",
             text="Concediul medical se anunță în aceeași zi.")
    _, _, events = _stream(cast, "Ce spun regulile despre concediu?")
    sources = events[1][1]["citations"]
    assert [c["n"] for c in sources] == [1, 2]
    assert {c["title"] for c in sources} == {"Politica de concedii", "Regulament"}
    done = events[-1][1]["assistant_message"]
    assert done["content"].endswith("[1]")
    assert done["citations"] == [sources[0]]  # numbering exactly as streamed
    row = message_row(cast.conn, done["id"])
    assert row["status"] == "complete" and json.loads(row["citations_json"]) == [sources[0]]


def test_tokens_are_held_back_to_sixty_four_characters_then_flow(cast):
    cast.ws.use_engine(FakeEngine(reply=LONG_REPLY))
    _, _, events = _stream(cast)
    tokens = [data["t"] for kind, data in events if kind == "token"]
    assert len(tokens[0]) >= llm.HOLD_BACK_CHARS and len(tokens) > 3
    done = events[-1][1]["assistant_message"]
    assert "".join(tokens) == LONG_REPLY == done["content"]
    assert done["citations"] == []  # [1] and [2] cite nothing that was retrieved


def test_a_short_answer_arrives_as_one_token_at_the_end(cast):
    cast.ws.use_engine(FakeEngine(reply="Da."))
    _, _, events = _stream(cast)
    assert [(kind, data) for kind, data in events if kind == "token"] == [("token", {"t": "Da."})]


def test_the_stream_pings_while_the_model_is_quiet(cast, monkeypatch):
    monkeypatch.setattr(workspace_chat, "PING_INTERVAL_SECONDS", 0.05)
    cast.ws.use_engine(FakeEngine(reply=LONG_REPLY, delay=0.4))
    _, body, events = _stream(cast)
    assert ": ping\n\n" in body
    kinds = _kinds(events)
    first_token = kinds.index("token")
    assert kinds[2:first_token] and set(kinds[2:first_token]) == {"ping"}
    assert kinds[-1] == "done"


def test_the_model_gets_the_streaming_callback(cast):
    _stream(cast)
    assert cast.ws.engine.calls[-1]["streamed"] is True


# ── failures inside the stream ───────────────────────────────────────────────────────

@pytest.mark.parametrize("error", [
    llm.LLMUnavailable("no_local_model"), llm.ModelPolicyBlocked("provider_may_train"),
    llm.ModelBusy(), llm.ModelTimeout(180), llm.ContentBlocked(),
])
def test_a_failed_answer_ends_with_an_error_event_and_an_error_row(cast, error):
    cast.ws.use_engine(FakeEngine(fail=error))
    response, _, events = _stream(cast)
    assert response.status_code == 200
    assert _kinds(events) == ["start", "sources", "error"]
    payload = events[-1][1]
    assert payload["error"] == error.code and payload["message"] == error.message
    assert payload.get("reason") == error.extra.get("reason")
    assert payload["assistant_message"]["status"] == "error"
    row = message_row(cast.conn, events[0][1]["assistant_message_id"])
    assert (row["status"], row["error_code"], row["content"]) == ("error", error.code, "")
    assert not live_answers()


def test_a_degraded_reply_is_never_streamed(cast):
    cast.ws.use_engine(FakeEngine(reply=UNREACHABLE))
    _, body, events = _stream(cast)
    assert "event: token" not in body and "⚠️" not in body
    assert events[-1] == ("error", events[-1][1])
    assert (events[-1][1]["error"], events[-1][1]["reason"]) == ("model_unavailable",
                                                                 "model_error")


def test_a_model_timeout_inside_the_stream(cast, monkeypatch):
    monkeypatch.setattr(workspace_chat, "ANSWER_TIMEOUT_SECONDS", 0.05)
    cast.ws.use_engine(FakeEngine(delay=1.0))
    _, _, events = _stream(cast)
    assert events[-1][1]["error"] == "model_timeout"


def test_errors_before_the_stream_starts_are_plain_json(cast):
    url = f"/api/workspace/conversations/{cast.conversation_id}/messages"
    headers = {**authed(cast.client, cast.csrf), **SSE_ACCEPT}
    response = cast.client.post(url, json={"content": ""}, headers=headers)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    response = cast.client.post("/api/workspace/conversations/999999/messages",
                                json={"content": "x"}, headers=headers)
    assert (response.status_code, response.json()["error"]) == (404, "not_found")


def test_a_live_answer_makes_the_conversation_busy_for_streams_too(cast):
    stamp = workspace_db.now()
    with workspace_db.tx(cast.conn):
        pending = int(cast.conn.execute(
            "INSERT INTO messages (conversation_id, role, content, status, created_at) "
            "VALUES (?, 'assistant', '', 'pending', ?)",
            (cast.conversation_id, stamp)).lastrowid)
    live_answers()[pending] = (cast.conversation_id, stamp)
    try:
        response = cast.client.post(
            f"/api/workspace/conversations/{cast.conversation_id}/messages",
            json={"content": "x"}, headers={**authed(cast.client, cast.csrf), **SSE_ACCEPT})
        assert (response.status_code, response.json()["error"]) == (409, "conversation_busy")
    finally:
        live_answers().pop(pending, None)


# ── the client going away ────────────────────────────────────────────────────────────

def _asgi_request(cast, content: str) -> tuple[dict, bytes]:
    path = f"/api/workspace/conversations/{cast.conversation_id}/messages"
    body = json.dumps({"content": content}).encode("utf-8")
    cookie = f"nerva_ws_session={cast.client.cookies.get('nerva_ws_session')}"
    headers = [(b"host", b"testserver"), (b"content-type", b"application/json"),
               (b"content-length", str(len(body)).encode()), (b"accept", b"text/event-stream"),
               (b"origin", origin_of(cast.client).encode()),
               (b"x-csrf-token", cast.csrf.encode()), (b"cookie", cookie.encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "headers": headers,
             "client": ("127.0.0.1", 50000), "server": ("testserver", 80)}
    return scope, body


async def _settled(conn, message_id: int) -> dict:
    for _ in range(200):
        row = message_row(conn, message_id)
        if row["status"] != "pending":
            return dict(row)
        await asyncio.sleep(0.01)
    raise AssertionError("the assistant row stayed pending")


async def test_a_client_that_disconnects_cancels_the_answer(cast):
    engine = cast.ws.use_engine(FakeEngine(reply=LONG_REPLY * 3, token_delay=0.02))
    scope, body = _asgi_request(cast, "Câte zile de concediu avem?")
    first_token = asyncio.Event()
    request_sent = False
    sent: list[bytes] = []

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await first_token.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body":
            sent.append(message.get("body", b""))
            if b"event: token" in message.get("body", b""):
                first_token.set()

    await asyncio.wait_for(chat_app()(scope, receive, send), timeout=5)
    events = parse_sse(b"".join(sent).decode("utf-8"))
    assert "done" not in _kinds(events)
    row = await _settled(cast.conn, events[0][1]["assistant_message_id"])
    assert (row["status"], row["error_code"], row["content"]) == ("error", "cancelled", "")
    assert not live_answers()
    assert len(engine.calls) == 1
    # The conversation is free again at once.
    cast.ws.use_engine(FakeEngine())
    assert ask_stream(cast.client, cast.csrf, cast.conversation_id, "Din nou")[0].status_code \
        == 200


async def test_an_answer_is_still_finished_when_the_stream_is_never_read(cast):
    cast.ws.use_engine(FakeEngine(reply=LONG_REPLY))
    scope, body = _asgi_request(cast, "Câte zile de concediu avem?")
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()  # like a server: nothing more until the socket closes
        raise AssertionError("unreachable")

    async def send(message: dict) -> None:
        raise OSError("the client is gone")

    with pytest.raises(OSError):
        await chat_app()(scope, receive, send)
    [pending] = [int(r["id"]) for r in cast.conn.execute(
        "SELECT id FROM messages WHERE role = 'assistant'").fetchall()]
    row = await _settled(cast.conn, pending)
    assert (row["status"], row["content"]) == ("complete", LONG_REPLY)
