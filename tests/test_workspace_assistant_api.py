"""The assistant API in JSON mode: conversations, questions, feedback, model status (spec §7 S3).

The model is the fixtures' ``FakeEngine`` (citation-aware: it cites ``[1]`` when the
prompt holds a ``<source id="1">``); streaming has its own suite, isolation too.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.llm.base import THINKING_EXHAUSTED_REPLY
from agents.core.routers import workspace_chat
from agents.core.workspace import audit, llm
from agents.core.workspace import db as workspace_db
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    FakeEngine,
    authed,
    db,
    freeze_clock,
    login,
    make_user,
    seed_company,
    ws,
)
from tests.test_workspace_assistant_helpers import (
    ask,
    audit_actions,
    chat_app,
    chat_client,
    live_answers,
    message_row,
    new_conversation,
    seed_doc,
)

POLICY_TEXT = "Concediul anual este de 21 de zile lucrătoare. Cererea se depune din timp."


@pytest.fixture
def cast(ws):
    conn = db()
    company = seed_company(conn)
    client = chat_client()
    csrf = login(client, company.member_a.email)
    yield SimpleNamespace(conn=conn, company=company, client=client, csrf=csrf, ws=ws)
    conn.close()


def _conversation(cast, **kwargs) -> int:
    return new_conversation(cast.client, cast.csrf, cast.company.dept_a, **kwargs)


# ── conversations ────────────────────────────────────────────────────────────────────

def test_a_new_conversation_gets_the_default_title_of_the_users_locale(cast):
    response = cast.client.post("/api/workspace/conversations",
                                json={"department_id": cast.company.dept_a},
                                headers=authed(cast.client, cast.csrf))
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Conversație nouă"
    assert (body["department_id"], body["message_count"]) == (cast.company.dept_a, 0)
    assert response.headers["cache-control"] == "no-store"

    english = make_user(cast.conn, role="member", department_ids=[cast.company.dept_a],
                        locale="en")
    client = chat_client()
    csrf = login(client, english.email)
    conversation_id = new_conversation(client, csrf, cast.company.dept_a)
    assert client.get(f"/api/workspace/conversations/{conversation_id}").json()[
        "conversation"]["title"] == "New conversation"


def test_a_conversation_can_be_created_with_a_title(cast):
    conversation_id = _conversation(cast, title="  Buget T4 ")
    body = cast.client.get(f"/api/workspace/conversations/{conversation_id}").json()
    assert body == {"conversation": {**body["conversation"], "title": "Buget T4"},
                    "messages": [], "truncated": False}


@pytest.mark.parametrize("payload,field,reason", [
    ({}, "department_id", "required"),
    ({"department_id": "1"}, "department_id", "type"),
    ({"department_id": 0}, "department_id", "too_small"),
    ({"department_id": 1, "title": "x" * 201}, "title", "too_long"),
    ({"department_id": 1, "title": "a\u0000b"}, "title", "control_characters"),
])
def test_creating_validates_the_body(cast, payload, field, reason):
    response = cast.client.post("/api/workspace/conversations", json=payload,
                                headers=authed(cast.client, cast.csrf))
    assert response.status_code == 422
    assert (response.json()["field"], response.json()["reason"]) == (field, reason)


def test_creating_needs_json_and_csrf(cast):
    assert cast.client.post("/api/workspace/conversations", content=b"department_id=1",
                            headers={**authed(cast.client, cast.csrf),
                                     "Content-Type": "application/x-www-form-urlencoded"}
                            ).status_code == 415
    response = cast.client.post("/api/workspace/conversations",
                                json={"department_id": cast.company.dept_a})
    assert (response.status_code, response.json()["error"]) == (403, "csrf_failed")


@pytest.mark.parametrize("department", ["other", "missing"])
def test_creating_outside_ones_departments_is_not_found(cast, department):
    department_id = cast.company.dept_b if department == "other" else 9999
    response = cast.client.post("/api/workspace/conversations",
                                json={"department_id": department_id},
                                headers=authed(cast.client, cast.csrf))
    assert (response.status_code, response.json()["error"]) == (404, "not_found")


def test_an_archived_department_takes_no_new_conversations(cast):
    with workspace_db.tx(cast.conn):
        cast.conn.execute("UPDATE departments SET archived = 1 WHERE id = ?",
                          (cast.company.dept_b,))
    admin = chat_client()
    csrf = login(admin, cast.company.admin.email)
    response = admin.post("/api/workspace/conversations",
                          json={"department_id": cast.company.dept_b}, headers=authed(admin, csrf))
    assert (response.status_code, response.json()["error"]) == (409, "department_archived")


def test_the_list_shows_own_conversations_newest_activity_first(cast, monkeypatch):
    clock = freeze_clock(monkeypatch)
    first = _conversation(cast, title="Prima")
    clock.advance(10)
    second = _conversation(cast, title="A doua")
    clock.advance(10)
    assert ask(cast.client, cast.csrf, first, "Câte zile de concediu avem?").status_code == 201
    items = cast.client.get("/api/workspace/conversations").json()["conversations"]
    assert [item["id"] for item in items] == [first, second]
    assert items[0]["message_count"] == 2 and items[1]["message_count"] == 0
    assert set(items[0]) == {"id", "title", "department_id", "created_at", "updated_at",
                             "message_count"}


def test_the_list_filters_by_department(cast):
    conversation_id = _conversation(cast)
    listed = cast.client.get("/api/workspace/conversations",
                             params={"department_id": cast.company.dept_a}).json()
    assert [item["id"] for item in listed["conversations"]] == [conversation_id]
    response = cast.client.get("/api/workspace/conversations",
                               params={"department_id": cast.company.dept_b})
    assert (response.status_code, response.json()["error"]) == (404, "not_found")
    response = cast.client.get("/api/workspace/conversations", params={"department_id": "x"})
    assert (response.status_code, response.json()["field"]) == (422, "department_id")


def test_renaming_a_conversation(cast):
    conversation_id = _conversation(cast)
    url = f"/api/workspace/conversations/{conversation_id}"
    response = cast.client.patch(url, json={"title": "Concedii 2026"},
                                 headers=authed(cast.client, cast.csrf))
    assert response.status_code == 200
    assert response.json()["title"] == "Concedii 2026"
    assert response.json()["id"] == conversation_id
    response = cast.client.patch(url, json={"title": "  "}, headers=authed(cast.client, cast.csrf))
    assert (response.status_code, response.json()["reason"]) == (422, "required")


def test_deleting_a_conversation_removes_its_messages_and_is_audited(cast):
    conversation_id = _conversation(cast)
    ask(cast.client, cast.csrf, conversation_id, "Câte zile de concediu avem?")
    response = cast.client.delete(f"/api/workspace/conversations/{conversation_id}",
                                  headers=authed(cast.client, cast.csrf))
    assert response.status_code == 204
    assert cast.client.get(f"/api/workspace/conversations/{conversation_id}").status_code == 404
    assert cast.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    [row] = audit_actions(cast.conn, "conversation.deleted")
    assert row["actor_user_id"] == cast.company.member_a.id
    assert (row["target_id"], row["department_id"]) == (str(conversation_id), cast.company.dept_a)
    assert json.loads(row["details_json"]) == {"messages": 2}


def test_ids_beyond_the_database_range_are_invalid_not_a_crash(cast):
    response = cast.client.get(f"/api/workspace/conversations/{10 ** 20}")
    assert (response.status_code, response.json()["error"]) == (422, "invalid_request")


# ── asking (JSON mode) ───────────────────────────────────────────────────────────────

def test_asking_answers_with_cited_sources_and_titles_the_conversation(cast):
    seed_doc(cast.conn, department_id=cast.company.dept_a, title="Politica de concedii",
             text=POLICY_TEXT, page=3)
    seed_doc(cast.conn, department_id=None, visibility="company", title="Regulament intern",
             text="Concediul medical se anunță în aceeași zi.")
    conversation_id = _conversation(cast)
    response = ask(cast.client, cast.csrf, conversation_id, "Câte zile de concediu de odihnă avem?")
    assert response.status_code == 201, response.text
    body = response.json()
    user_message, answer = body["user_message"], body["assistant_message"]
    assert (user_message["role"], user_message["content"]) == (
        "user", "Câte zile de concediu de odihnă avem?")
    assert answer["status"] == "complete" and answer["error_code"] is None
    assert answer["content"].startswith("Conform documentelor companiei:")
    assert answer["content"].endswith("[1]")
    assert [(c["n"], c["title"], c["page"]) for c in answer["citations"]] == [
        (1, "Politica de concedii", 3)]
    assert (answer["model"], answer["locality"]) == ("fake-local-model", "local")
    assert isinstance(answer["latency_ms"], int)
    assert body["conversation"]["title"] == "Câte zile de concediu de odihnă avem?"
    row = message_row(cast.conn, answer["id"])
    assert [{**c, "can_open": True} for c in json.loads(row["citations_json"])] == (
        answer["citations"])
    assert row["route"] == "local"


def _store_citations(conn, message_id: int, citations: list[dict]) -> None:
    with workspace_db.tx(conn):
        conn.execute("UPDATE messages SET citations_json = ? WHERE id = ?",
                     (json.dumps(citations, ensure_ascii=False), message_id))


def test_citations_say_at_read_time_whether_the_reader_may_open_each_document(cast):
    """Like a report run's, an answer's citations carry ``can_open`` judged when read: a
    document deleted since, or one outside the reader's departments, keeps its excerpt but
    is no longer offered as a link (spec §7 S3, §10 source drawer)."""
    kept = seed_doc(cast.conn, department_id=cast.company.dept_a, title="Politica de concedii",
                    text=POLICY_TEXT)
    company = seed_doc(cast.conn, department_id=None, visibility="company", title="Regulament",
                       text="Concediul medical se anunță în aceeași zi.")
    deleted = seed_doc(cast.conn, department_id=cast.company.dept_a, title="Anexă veche",
                       text="Anexa veche a politicii de concedii.")
    other = seed_doc(cast.conn, department_id=cast.company.dept_b, title="Buget Financiar",
                     text="Bugetul departamentului Financiar.")
    conversation_id = _conversation(cast)
    answer = ask(cast.client, cast.csrf, conversation_id, "Câte zile de concediu avem?").json()[
        "assistant_message"]
    assert answer["citations"] and all(c["can_open"] is True for c in answer["citations"])

    def citation(n: int, document_id: int, title: str) -> dict:
        return {"n": n, "document_id": document_id, "title": title, "chunk_id": n, "page": None,
                "excerpt": f"Fragmentul {n}."}

    _store_citations(cast.conn, answer["id"], [
        citation(1, kept, "Politica de concedii"), citation(2, company, "Regulament"),
        citation(3, deleted, "Anexă veche"), citation(4, other, "Buget Financiar")])
    with workspace_db.tx(cast.conn):
        cast.conn.execute("DELETE FROM documents WHERE id = ?", (deleted,))

    read = cast.client.get(f"/api/workspace/conversations/{conversation_id}").json()
    stored = [m for m in read["messages"] if m["role"] == "assistant"][0]
    assert [(c["n"], c["can_open"]) for c in stored["citations"]] == [
        (1, True), (2, True), (3, False), (4, False)]
    assert [c["excerpt"] for c in stored["citations"]] == [
        "Fragmentul 1.", "Fragmentul 2.", "Fragmentul 3.", "Fragmentul 4."]
    assert "can_open" not in message_row(cast.conn, answer["id"])["citations_json"], (
        "judged when read, never stored")

    rated = _feedback(cast, answer["id"], {"value": 1}).json()["message"]
    assert [(c["n"], c["can_open"]) for c in rated["citations"]] == [
        (1, True), (2, True), (3, False), (4, False)]

    # A document published company-wide since is judged as it is today.
    with workspace_db.tx(cast.conn):
        cast.conn.execute("UPDATE documents SET visibility = 'company', department_id = NULL "
                          "WHERE id = ?", (other,))
    again = cast.client.get(f"/api/workspace/conversations/{conversation_id}").json()
    stored = [m for m in again["messages"] if m["role"] == "assistant"][0]
    assert [(c["n"], c["can_open"]) for c in stored["citations"]] == [
        (1, True), (2, True), (3, False), (4, True)]


def test_a_malformed_citation_is_shown_as_stored_and_never_crashes_the_read(cast):
    conversation_id = _conversation(cast)
    answer = ask(cast.client, cast.csrf, conversation_id, "Întrebare").json()["assistant_message"]
    _store_citations(cast.conn, answer["id"], [
        {"n": 1, "document_id": True, "title": "bool"}, {"n": 2, "title": "fără id"}, "text"])
    read = cast.client.get(f"/api/workspace/conversations/{conversation_id}")
    assert read.status_code == 200
    stored = [m for m in read.json()["messages"] if m["role"] == "assistant"][0]
    assert stored["citations"] == [{"n": 1, "document_id": True, "title": "bool", "can_open": False},
                                   {"n": 2, "title": "fără id", "can_open": False}, "text"]


def test_the_model_gets_the_departments_instructions_sources_and_the_org_policy(cast):
    with workspace_db.tx(cast.conn):
        cast.conn.execute("UPDATE departments SET assistant_instructions = ? WHERE id = ?",
                          ("Răspunde mereu cu sume în lei.", cast.company.dept_a))
        cast.conn.execute("UPDATE org SET model_policy = 'allow_cloud' WHERE id = 1")
    seed_doc(cast.conn, department_id=cast.company.dept_a, title="Politica de concedii",
             text=POLICY_TEXT)
    conversation_id = _conversation(cast)
    ask(cast.client, cast.csrf, conversation_id, "Câte zile de concediu avem?")
    call = cast.ws.engine.calls[-1]
    assert "Răspunde mereu cu sume în lei." in call["system"]
    assert '<source id="1" title="Politica de concedii">' in call["prompt"]
    assert call["prompt"].endswith("Întrebarea utilizatorului:\nCâte zile de concediu avem?")
    assert (call["policy"], call["max_tokens"], call["timeout_seconds"]) == (
        "allow_cloud", 1200, 180.0)
    assert call["streamed"] is False


def test_a_follow_up_carries_the_history_and_keeps_the_title(cast):
    conversation_id = _conversation(cast)
    ask(cast.client, cast.csrf, conversation_id, "Prima întrebare despre concedii")
    second = ask(cast.client, cast.csrf, conversation_id, "Și pentru zilele libere?").json()
    assert second["conversation"]["title"] == "Prima întrebare despre concedii"
    prompt = cast.ws.engine.calls[-1]["prompt"]
    assert "Utilizator: Prima întrebare despre concedii" in prompt
    assert "Asistent: Nu am găsit această informație" in prompt


def test_asking_is_audited_without_the_question(cast):
    conversation_id = _conversation(cast)
    body = ask(cast.client, cast.csrf, conversation_id, "Întrebare confidențială").json()
    [row] = audit_actions(cast.conn, "chat.asked")
    details = json.loads(row["details_json"])
    assert details == {"user_message_id": body["user_message"]["id"],
                       "assistant_message_id": body["assistant_message"]["id"],
                       "chars": len("Întrebare confidențială")}
    assert "confidențială" not in row["details_json"]
    assert row["department_id"] == cast.company.dept_a


@pytest.mark.parametrize("payload,status,reason", [
    ({}, 422, "required"),
    ({"content": "   "}, 422, "required"),
    ({"content": 5}, 422, "type"),
    ({"content": "x" * 8001}, 422, "too_long"),
    ({"content": "a\u0007b"}, 422, "control_characters"),
])
def test_the_question_is_validated(cast, payload, status, reason):
    conversation_id = _conversation(cast)
    response = cast.client.post(f"/api/workspace/conversations/{conversation_id}/messages",
                                json=payload, headers=authed(cast.client, cast.csrf))
    assert (response.status_code, response.json()["reason"]) == (status, reason)
    assert cast.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_a_multiline_question_is_accepted(cast):
    conversation_id = _conversation(cast)
    response = ask(cast.client, cast.csrf, conversation_id, "Rândul unu\r\nRândul doi\tok")
    assert response.json()["user_message"]["content"] == "Rândul unu\nRândul doi\tok"


@pytest.mark.parametrize("error,status,reason", [
    (llm.LLMUnavailable("no_local_model"), 503, "no_local_model"),
    (llm.ModelPolicyBlocked("provider_may_train"), 409, "provider_may_train"),
    (llm.ModelBusy(), 503, None),
    (llm.ContentBlocked(), 422, None),
])
def test_a_failed_answer_is_stored_and_reported_with_its_code(cast, error, status, reason):
    cast.ws.use_engine(FakeEngine(fail=error))
    conversation_id = _conversation(cast)
    response = ask(cast.client, cast.csrf, conversation_id, "Câte zile de concediu avem?")
    assert response.status_code == status
    body = response.json()
    assert body["error"] == error.code and body.get("reason") == reason
    assert body["user_message"]["content"] == "Câte zile de concediu avem?"
    assert body["assistant_message"]["status"] == "error"
    assert body["assistant_message"]["error_code"] == error.code
    assert body["assistant_message"]["content"] == ""
    row = message_row(cast.conn, body["assistant_message"]["id"])
    assert (row["status"], row["error_code"]) == ("error", error.code)
    assert body["assistant_message"]["id"] not in live_answers()


def test_model_busy_says_when_to_retry(cast):
    cast.ws.use_engine(FakeEngine(fail=llm.ModelBusy()))
    response = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare")
    assert response.headers["retry-after"] == str(llm.BUSY_RETRY_AFTER_SECONDS)


def test_an_answer_past_the_deadline_is_model_timeout(cast, monkeypatch):
    monkeypatch.setattr(workspace_chat, "ANSWER_TIMEOUT_SECONDS", 0.05)
    cast.ws.use_engine(FakeEngine(delay=1.0))
    response = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare")
    assert (response.status_code, response.json()["error"]) == (504, "model_timeout")
    assert response.json()["assistant_message"]["error_code"] == "model_timeout"


def test_a_degraded_reply_from_the_model_is_never_stored_as_an_answer(cast):
    cast.ws.use_engine(FakeEngine(reply="⚠️ I can't reach the local LM Studio model right now."))
    response = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare")
    body = response.json()
    assert (response.status_code, body["error"], body["reason"]) == (
        503, "model_unavailable", "model_error")
    assert body["assistant_message"]["content"] == ""


def test_an_unexpected_engine_crash_is_internal_error_not_a_stuck_row(cast):
    def explode(**_: str) -> str:
        raise KeyError("boom")

    cast.ws.use_engine(FakeEngine(reply=explode))
    response = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare")
    body = response.json()
    assert (response.status_code, body["error"]) == (500, "internal_error")
    assert message_row(cast.conn, body["assistant_message"]["id"])["error_code"] == \
        "internal_error"


def test_an_archived_department_takes_no_new_questions(cast):
    admin = chat_client()
    csrf = login(admin, cast.company.admin.email)
    conversation_id = new_conversation(admin, csrf, cast.company.dept_b)
    with workspace_db.tx(cast.conn):
        cast.conn.execute("UPDATE departments SET archived = 1 WHERE id = ?",
                          (cast.company.dept_b,))
    response = ask(admin, csrf, conversation_id, "Întrebare")
    assert (response.status_code, response.json()["error"]) == (409, "department_archived")
    assert admin.get(f"/api/workspace/conversations/{conversation_id}").status_code == 200


def test_an_orphaned_pending_row_never_locks_the_conversation(cast):
    conversation_id = _conversation(cast)
    with workspace_db.tx(cast.conn):
        orphan = int(cast.conn.execute(
            "INSERT INTO messages (conversation_id, role, content, status, created_at) "
            "VALUES (?, 'assistant', '', 'pending', ?)",
            (conversation_id, workspace_db.now())).lastrowid)
    shown = cast.client.get(f"/api/workspace/conversations/{conversation_id}").json()
    assert (shown["messages"][0]["status"], shown["messages"][0]["error_code"]) == (
        "error", "interrupted")
    assert ask(cast.client, cast.csrf, conversation_id, "Întrebare").status_code == 201
    row = message_row(cast.conn, orphan)
    assert (row["status"], row["error_code"]) == ("error", "interrupted")


async def test_a_second_question_while_an_answer_is_written_is_conversation_busy(cast):
    cast.ws.use_engine(FakeEngine(delay=0.4))
    conversation_id = _conversation(cast)
    transport = httpx.ASGITransport(app=chat_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        origin = {"Origin": "http://testserver"}
        signed_in = await client.post("/api/workspace/login", headers=origin, json={
            "email": cast.company.member_a.email, "password": DEFAULT_PASSWORD})
        headers = {**origin, "X-CSRF-Token": signed_in.json()["csrf_token"]}
        url = f"/api/workspace/conversations/{conversation_id}/messages"
        first = asyncio.create_task(client.post(url, headers=headers,
                                                json={"content": "Prima"}))
        for _ in range(100):
            if live_answers():
                break
            await asyncio.sleep(0.01)
        busy = await client.post(url, headers=headers, json={"content": "A doua"})
        assert (busy.status_code, busy.json()["error"]) == (409, "conversation_busy")
        assert (await first).status_code == 201
        again = await client.post(url, headers=headers, json={"content": "A treia"})
        assert again.status_code == 201
    contents = [row["content"] for row in cast.conn.execute(
        "SELECT content FROM messages WHERE role = 'user' ORDER BY id")]
    assert contents == ["Prima", "A treia"]


def test_questions_are_rate_limited_per_user(cast, monkeypatch):
    clock = freeze_clock(monkeypatch)
    monkeypatch.setattr(workspace_chat, "CHAT_RATE_LIMIT", 3)
    conversation_id = _conversation(cast)
    for number in range(3):
        assert ask(cast.client, cast.csrf, conversation_id, f"Întrebarea {number}").status_code \
            == 201
        clock.advance(1)
    limited = ask(cast.client, cast.csrf, conversation_id, "Una în plus")
    assert (limited.status_code, limited.json()["error"]) == (429, "rate_limited")
    # The oldest of the three is 3 s old: it leaves the 60 s window in 57 s.
    assert limited.json()["retry_after_seconds"] == 57
    assert limited.headers["retry-after"] == "57"
    assert cast.conn.execute("SELECT COUNT(*) FROM messages WHERE content = 'Una în plus'"
                             ).fetchone()[0] == 0
    other = chat_client()
    other_csrf = login(other, cast.company.approver_a.email)
    assert ask(other, other_csrf, new_conversation(other, other_csrf, cast.company.dept_a),
               "Alt utilizator").status_code == 201
    clock.advance(57)
    assert ask(cast.client, cast.csrf, conversation_id, "După pauză").status_code == 201


def test_the_default_limit_is_thirty_a_minute_counted_in_the_audit(cast, monkeypatch):
    freeze_clock(monkeypatch)
    conversation_id = _conversation(cast)
    with workspace_db.tx(cast.conn):
        for _ in range(workspace_chat.CHAT_RATE_LIMIT):
            audit.record(cast.conn, actor=cast.company.member_a, action="chat.asked")
    response = ask(cast.client, cast.csrf, conversation_id, "Una în plus")
    assert (response.status_code, response.json()["retry_after_seconds"]) == (429, 60)


# ── feedback ─────────────────────────────────────────────────────────────────────────

def _answered(cast) -> int:
    body = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare").json()
    return int(body["assistant_message"]["id"])


def _feedback(cast, message_id: int, payload: dict) -> httpx.Response:
    return cast.client.post(f"/api/workspace/messages/{message_id}/feedback", json=payload,
                            headers=authed(cast.client, cast.csrf))


def test_rating_an_answer_with_a_note_and_clearing_it(cast):
    message_id = _answered(cast)
    response = _feedback(cast, message_id, {"value": -1, "note": "Lipsește\nsursa."})
    assert response.status_code == 200
    message = response.json()["message"]
    assert (message["feedback"], message["feedback_note"]) == (-1, "Lipsește\nsursa.")
    assert _feedback(cast, message_id, {"value": 1}).json()["message"]["feedback"] == 1
    cleared = _feedback(cast, message_id, {"value": 0, "note": "ignorată"}).json()["message"]
    assert (cleared["feedback"], cleared["feedback_note"]) == (None, None)
    rows = audit_actions(cast.conn, "message.feedback")
    assert [json.loads(row["details_json"]) for row in rows] == [
        {"value": -1, "has_note": True}, {"value": 1, "has_note": False},
        {"value": 0, "has_note": False}]
    assert all("Lipsește" not in row["details_json"] for row in rows)


@pytest.mark.parametrize("payload,reason", [
    ({}, "required"), ({"value": 2}, "too_large"), ({"value": -2}, "too_small"),
    ({"value": "1"}, "type"), ({"value": True}, "type"),
    ({"value": 1, "note": "x" * 1001}, "too_long"),
])
def test_feedback_is_validated(cast, payload, reason):
    response = _feedback(cast, _answered(cast), payload)
    assert (response.status_code, response.json()["reason"]) == (422, reason)


def test_only_finished_answers_can_be_rated(cast):
    body = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare").json()
    assert _feedback(cast, body["user_message"]["id"], {"value": 1}).status_code == 404
    cast.ws.use_engine(FakeEngine(fail=llm.LLMUnavailable("no_local_model")))
    failed = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare").json()
    assert _feedback(cast, failed["assistant_message"]["id"], {"value": 1}).status_code == 404
    assert _feedback(cast, 999_999, {"value": 1}).status_code == 404


# ── model status ─────────────────────────────────────────────────────────────────────

def test_model_status_is_the_posture_under_the_org_policy(cast):
    with workspace_db.tx(cast.conn):
        cast.conn.execute("UPDATE org SET model_policy = 'allow_cloud' WHERE id = 1")
    response = cast.client.get("/api/workspace/model")
    assert response.status_code == 200
    assert response.json() == {"available": True, "backend": "fake",
                               "model": "fake-local-model", "route": "local",
                               "locality": "local", "policy": "allow_cloud", "reason": "",
                               "guardrails_mode": "off"}
    assert cast.ws.engine.posture_calls == ["allow_cloud"]


def test_model_status_reports_an_unavailable_model_honestly(cast):
    cast.ws.use_engine(FakeEngine(fail=llm.LLMUnavailable("no_local_model")))
    body = cast.client.get("/api/workspace/model").json()
    assert (body["available"], body["reason"]) == (False, "no_local_model")


def _admin(cast) -> tuple:
    client = chat_client()
    return client, login(client, cast.company.admin.email)


def test_the_admin_model_test_sends_one_real_request(cast):
    client, csrf = _admin(cast)
    response = client.post("/api/workspace/admin/model/test", headers=authed(client, csrf))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and isinstance(body["latency_ms"], int)
    assert (body["model"], body["locality"], body["route"]) == (
        "fake-local-model", "local", "local")
    assert cast.ws.engine.calls[-1]["max_tokens"] >= 64
    [row] = audit_actions(cast.conn, "model.tested")
    assert json.loads(row["details_json"]) == {"ok": True, "error": "", "route": "local",
                                               "locality": "local"}


@pytest.mark.parametrize("error,code,reason", [
    (llm.LLMUnavailable("no_local_model"), "model_unavailable", "no_local_model"),
    (llm.ModelPolicyBlocked("data_policy_unacknowledged"), "model_policy_blocked",
     "data_policy_unacknowledged"),
    (llm.ModelTimeout(60), "model_timeout", ""),
])
def test_the_admin_model_test_reports_failures(cast, error, code, reason):
    cast.ws.use_engine(FakeEngine(fail=error))
    client, csrf = _admin(cast)
    body = client.post("/api/workspace/admin/model/test", headers=authed(client, csrf)).json()
    assert (body["ok"], body["error"], body["reason"]) == (False, code, reason)
    assert body["message"] and isinstance(body["latency_ms"], int)
    [row] = audit_actions(cast.conn, "model.tested")
    assert json.loads(row["details_json"])["error"] == code


def test_a_model_that_only_thought_still_counts_as_reachable(cast):
    cast.ws.use_engine(FakeEngine(reply=THINKING_EXHAUSTED_REPLY))
    client, csrf = _admin(cast)
    body = client.post("/api/workspace/admin/model/test", headers=authed(client, csrf)).json()
    assert body["ok"] is True and "error" not in body
    assert body["model"] == "fake-local-model"


def test_the_model_test_is_for_admins_only(cast):
    response = cast.client.post("/api/workspace/admin/model/test",
                                headers=authed(cast.client, cast.csrf))
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")
    client, _ = _admin(cast)
    response = client.post("/api/workspace/admin/model/test")
    assert (response.status_code, response.json()["error"]) == (403, "csrf_failed")
    assert cast.ws.engine.calls == []


def test_workspace_errors_from_the_engine_keep_their_extras(cast):
    cast.ws.use_engine(FakeEngine(fail=WorkspaceError("model_unavailable", "down", 503,
                                                      reason="hub_not_ready")))
    body = ask(cast.client, cast.csrf, _conversation(cast), "Întrebare").json()
    assert (body["error"], body["reason"], body["message"]) == (
        "model_unavailable", "hub_not_ready", "down")


def test_an_eight_thousand_character_question_fits_even_when_json_escaped(cast):
    conversation_id = _conversation(cast)
    body = json.dumps({"content": "😀" * 8000}, ensure_ascii=True).encode("ascii")
    assert len(body) > 65536
    response = cast.client.post(f"/api/workspace/conversations/{conversation_id}/messages",
                                content=body, headers={**authed(cast.client, cast.csrf),
                                                       "Content-Type": "application/json"})
    assert response.status_code == 201, response.text
    assert response.json()["user_message"]["content"] == "😀" * 8000


def test_a_conversation_deleted_just_before_the_question_is_stored_is_not_found(cast):
    conversation_id = _conversation(cast)
    row = cast.conn.execute(
        "SELECT c.*, 0 AS department_archived FROM conversations c WHERE id = ?",
        (conversation_id,)).fetchone()
    with workspace_db.tx(cast.conn):
        cast.conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    with pytest.raises(WorkspaceError) as caught:
        workspace_chat.open_turn(cast.conn, cast.company.member_a, row, "Întrebare", ip="")
    assert (caught.value.code, caught.value.status) == ("not_found", 404)
    assert cast.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert not live_answers() and audit_actions(cast.conn, "chat.asked") == []
