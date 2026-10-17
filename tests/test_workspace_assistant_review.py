"""Review-driven regressions of the assistant slice (S3): isolation, robustness, streaming.

Each test pins a defect found in the independent review of the chat router and the
model layer, so it cannot come back:

* SQLite reuses the rowids of deleted rows (``messages`` has no ``AUTOINCREMENT``). An
  answer still being written when its conversation is deleted must never land in —
  or be read back from — the newer message that inherited its id, which may belong to
  another user in another department;
* a failure between storing the pending row and finishing the answer (building the
  prompt, writing the outcome, the runner itself) must answer the workspace's own
  error and never leave the conversation busy or the stream pinging forever;
* a backend failure reply that follows a short partial answer is never streamed;
* the model posture and the admin model test survive an unexpected engine fault, and a
  data-handling gate that cannot decide is ``model_unavailable``, not a crash.

The isolation probes at the end complete the generic ones of
``test_workspace_assistant_isolation``: every route, after the caller lost the
department, and for colleagues of the same department.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from agents.core.routers import workspace_chat
from agents.core.workspace import assistant, llm
from agents.core.workspace import db as workspace_db
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    FakeEngine,
    authed,
    db,
    login,
    seed_company,
    ws,
)
from tests.test_workspace_assistant_helpers import (
    SSE_ACCEPT,
    ask,
    ask_stream,
    audit_actions,
    chat_app,
    chat_client,
    live_answers,
    message_row,
    new_conversation,
    parse_sse,
    seed_doc,
)
from tests.test_workspace_llm import (  # noqa: F401  (hub is a fixture)
    LONG_ANSWER,
    UNREACHABLE,
    StubBackend,
    StubRouter,
    hub,
)

ORIGIN = {"Origin": "http://testserver"}
QUESTION_A = "întrebarea lui A despre prime"
QUESTION_B = "întrebarea lui B despre concediu"


@pytest.fixture
def cast(ws):
    conn = db()
    company = seed_company(conn)
    clients = {}
    for key in ("member_a", "approver_a", "member_b", "admin"):
        client = chat_client()
        clients[key] = (client, login(client, getattr(company, key).email))
    yield SimpleNamespace(conn=conn, company=company, clients=clients, ws=ws)
    conn.close()


def _client(cast, key: str) -> tuple:
    return cast.clients[key]


# ── rowid reuse: a deleted conversation's answer never reaches another one ────────────

class GatedEngine(FakeEngine):
    """Answers A's and B's questions only when the test opens their gate."""

    def __init__(self) -> None:
        super().__init__(reply=self._answer)
        self.gates = {"A": asyncio.Event(), "B": asyncio.Event()}

    @staticmethod
    def _answer(*, system: str, prompt: str) -> str:
        return "Răspunsul pentru B." if QUESTION_B in prompt else "Răspunsul pentru A."

    async def _run(self, system: str, prompt: str, on_token: Any) -> str:
        await self.gates["B" if QUESTION_B in prompt else "A"].wait()
        return await super()._run(system, prompt, on_token)


async def _signed_in(client: httpx.AsyncClient, email: str) -> dict:
    response = await client.post("/api/workspace/login", headers=ORIGIN,
                                 json={"email": email, "password": DEFAULT_PASSWORD})
    assert response.status_code == 200, response.text
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


async def _pending_in(conn: sqlite3.Connection, conversation_id: int) -> int:
    for _ in range(300):
        row = conn.execute("SELECT id FROM messages WHERE conversation_id = ? "
                           "AND status = 'pending'", (conversation_id,)).fetchone()
        if row is not None:
            return int(row["id"])
        await asyncio.sleep(0.01)
    raise AssertionError("the question was never stored")


async def test_an_answer_whose_conversation_was_deleted_never_lands_in_a_reused_row(cast):
    """A deletes a conversation while its answer is written; B (another department)
    asks right after and inherits the deleted rows' ids. A's late answer must not
    overwrite B's row, free B's busy lock, or come back as B's message."""
    engine = cast.ws.use_engine(GatedEngine())
    transport = httpx.ASGITransport(app=chat_app())
    async with (httpx.AsyncClient(transport=transport, base_url="http://testserver") as a,
                httpx.AsyncClient(transport=transport, base_url="http://testserver") as b):
        headers_a = await _signed_in(a, cast.company.member_a.email)
        headers_b = await _signed_in(b, cast.company.member_b.email)
        conv_a = (await a.post("/api/workspace/conversations", headers=headers_a,
                               json={"department_id": cast.company.dept_a})).json()["id"]
        conv_b = (await b.post("/api/workspace/conversations", headers=headers_b,
                               json={"department_id": cast.company.dept_b})).json()["id"]
        first = asyncio.create_task(a.post(f"/api/workspace/conversations/{conv_a}/messages",
                                           headers=headers_a, json={"content": QUESTION_A}))
        stale_id = await _pending_in(cast.conn, conv_a)
        assert (await a.delete(f"/api/workspace/conversations/{conv_a}",
                               headers=headers_a)).status_code == 204
        second = asyncio.create_task(b.post(f"/api/workspace/conversations/{conv_b}/messages",
                                            headers=headers_b, json={"content": QUESTION_B}))
        # The defect needs SQLite to really hand A's id to B: prove that it did.
        assert await _pending_in(cast.conn, conv_b) == stale_id
        engine.gates["A"].set()
        answer_a = (await first).json()
        busy = await b.post(f"/api/workspace/conversations/{conv_b}/messages",
                            headers=headers_b, json={"content": "încă una"})
        assert (busy.status_code, busy.json()["error"]) == (409, "conversation_busy")
        row = message_row(cast.conn, stale_id)
        assert (row["conversation_id"], row["status"], row["content"]) == (conv_b, "pending", "")
        engine.gates["B"].set()
        answer_b = (await second).json()
    assert answer_a["assistant_message"]["conversation_id"] == conv_a
    assert answer_a["assistant_message"]["content"] == "Răspunsul pentru A."
    assert answer_b["assistant_message"]["content"] == "Răspunsul pentru B."
    row = message_row(cast.conn, stale_id)
    assert (row["conversation_id"], row["status"], row["content"]) == (
        conv_b, "complete", "Răspunsul pentru B.")
    assert not live_answers()


def test_a_stale_registry_entry_for_a_reused_id_neither_locks_nor_reads_as_live(cast):
    client, csrf = _client(cast, "member_a")
    conversation_id = new_conversation(client, csrf, cast.company.dept_a)
    stamp = workspace_db.now()
    with workspace_db.tx(cast.conn):
        orphan = int(cast.conn.execute(
            "INSERT INTO messages (conversation_id, role, content, status, created_at) "
            "VALUES (?, 'assistant', '', 'pending', ?)", (conversation_id, stamp)).lastrowid)
    # An older turn whose conversation was deleted still holds this id in the registry.
    live_answers()[orphan] = (conversation_id + 1000, stamp - 5)
    try:
        shown = client.get(f"/api/workspace/conversations/{conversation_id}").json()
        assert (shown["messages"][0]["status"], shown["messages"][0]["error_code"]) == (
            "error", "interrupted")
        assert ask(client, csrf, conversation_id, "Merge?").status_code == 201
    finally:
        live_answers().pop(orphan, None)
    assert message_row(cast.conn, orphan)["error_code"] == "interrupted"


# ── failures after the pending row exists ────────────────────────────────────────────

def _assert_free_again(client, csrf, conversation_id: int) -> None:
    again = ask(client, csrf, conversation_id, "Din nou")
    assert again.status_code == 201, again.text
    assert not live_answers()


@pytest.mark.parametrize("accept", [{}, SSE_ACCEPT], ids=["json", "sse"])
def test_a_prompt_that_cannot_be_built_is_a_workspace_500_and_frees_the_turn(
        cast, monkeypatch, accept):
    client, csrf = _client(cast, "member_a")
    conversation_id = new_conversation(client, csrf, cast.company.dept_a)

    real = assistant.plan_answer

    def broken(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(assistant, "plan_answer", broken)
    response = client.post(f"/api/workspace/conversations/{conversation_id}/messages",
                           json={"content": "Întrebare"}, headers={**authed(client, csrf),
                                                                   **accept})
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert (body["error"], body["assistant_message"]["status"]) == ("internal_error", "error")
    assert body["user_message"]["content"] == "Întrebare"
    row = message_row(cast.conn, body["assistant_message"]["id"])
    assert (row["status"], row["error_code"]) == ("error", "internal_error")
    assert cast.ws.engine.calls == []
    monkeypatch.setattr(assistant, "plan_answer", real)
    _assert_free_again(client, csrf, conversation_id)


def test_an_outcome_that_cannot_be_stored_is_internal_error_not_a_stuck_answer(
        cast, monkeypatch):
    client, csrf = _client(cast, "member_a")
    conversation_id = new_conversation(client, csrf, cast.company.dept_a)
    real = workspace_chat._store_outcome
    failures = iter([sqlite3.OperationalError("database is locked")])

    def flaky(*args: Any, **kwargs: Any) -> dict:
        error = next(failures, None)
        if error is not None:
            raise error
        return real(*args, **kwargs)

    monkeypatch.setattr(workspace_chat, "_store_outcome", flaky)
    response = ask(client, csrf, conversation_id, "Întrebare")
    assert (response.status_code, response.json()["error"]) == (500, "internal_error")
    pending = response.json()["assistant_message"]["id"]
    assert message_row(cast.conn, pending)["status"] == "pending"
    shown = client.get(f"/api/workspace/conversations/{conversation_id}").json()
    assert (shown["messages"][1]["status"], shown["messages"][1]["error_code"]) == (
        "error", "interrupted")
    _assert_free_again(client, csrf, conversation_id)
    assert message_row(cast.conn, pending)["error_code"] == "interrupted"


def test_a_runner_that_crashes_still_ends_the_stream_with_an_error(cast, monkeypatch):
    client, csrf = _client(cast, "member_a")
    conversation_id = new_conversation(client, csrf, cast.company.dept_a)

    async def crashing(turn: Any, *args: Any) -> tuple:
        workspace_chat._release(turn)
        raise RuntimeError("bug")

    monkeypatch.setattr(workspace_chat, "produce_answer", crashing)
    response, body = ask_stream(client, csrf, conversation_id, "Întrebare")
    events = parse_sse(body)
    assert response.status_code == 200
    assert [kind for kind, _ in events] == ["start", "sources", "error"]
    assert events[-1][1]["error"] == "internal_error"
    assert events[-1][1]["assistant_message"]["id"] == events[0][1]["assistant_message_id"]


# ── the model layer ──────────────────────────────────────────────────────────────────

async def test_a_failure_after_a_short_partial_answer_is_never_streamed():
    forwarded: list[str] = []

    async def sink(text: str) -> None:
        forwarded.append(text)

    gate = llm.TokenGate(sink)
    await gate.feed("Concediul ")
    await gate.feed(UNREACHABLE)
    await gate.feed(" mai mult text")
    await gate.finish()
    assert forwarded == []


async def test_complete_streams_nothing_when_a_short_start_is_followed_by_a_failure(hub):
    pieces = [LONG_ANSWER[:20], UNREACHABLE]
    hub(StubRouter(backend=StubBackend(UNREACHABLE, pieces=pieces)))
    tokens: list[str] = []

    async def on_token(text: str) -> None:
        tokens.append(text)

    with pytest.raises(llm.LLMUnavailable) as caught:
        await llm.complete(system="s", prompt="p", policy="local_only", on_token=on_token)
    assert caught.value.extra["reason"] == "model_error"
    assert tokens == []


async def test_a_data_handling_gate_that_cannot_decide_is_model_unavailable(hub):
    hub(StubRouter(handling_error=RuntimeError("consent store unavailable")))
    with pytest.raises(llm.LLMUnavailable) as caught:
        await llm.complete(system="s", prompt="p", policy="local_only")
    assert (caught.value.status, caught.value.extra["reason"]) == (503, "backend_error")
    posture = await llm.posture("local_only")
    assert (posture["available"], posture["reason"]) == (False, "backend_error")


class BrokenEngine(FakeEngine):
    """An engine with a fault nobody foresaw: neither call raises a WorkspaceError."""

    async def complete(self, **kwargs: Any) -> Any:
        raise TypeError("unforeseen")

    async def posture(self, policy: str) -> dict:
        raise KeyError("unforeseen")


def test_the_model_status_survives_an_unforeseen_engine_fault(cast):
    cast.ws.use_engine(BrokenEngine())
    client, _ = _client(cast, "member_a")
    response = client.get("/api/workspace/model")
    assert response.status_code == 200
    body = response.json()
    assert (body["available"], body["reason"], body["policy"]) == (False, "backend_error",
                                                                   "local_only")
    assert set(body) == {"available", "backend", "model", "route", "locality", "policy",
                         "reason", "guardrails_mode"}


def test_the_admin_model_test_reports_an_unforeseen_fault_and_audits_it(cast):
    cast.ws.use_engine(BrokenEngine())
    client, csrf = _client(cast, "admin")
    response = client.post("/api/workspace/admin/model/test", headers=authed(client, csrf))
    assert response.status_code == 200
    body = response.json()
    assert (body["ok"], body["error"]) == (False, "internal_error")
    [row] = audit_actions(cast.conn, "model.tested")
    assert json.loads(row["details_json"])["error"] == "internal_error"


@pytest.mark.parametrize("key", ["member_a", "approver_a", "member_b"])
def test_only_admins_test_the_model(cast, key):
    client, csrf = _client(cast, key)
    response = client.post("/api/workspace/admin/model/test", headers=authed(client, csrf))
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")
    assert cast.ws.engine.calls == [] and audit_actions(cast.conn, "model.tested") == []


# ── isolation: every route, colleagues, and a lost department ────────────────────────

@pytest.fixture
def owned(cast):
    """member_a's conversation in department A with one rated-able answer."""
    client, csrf = _client(cast, "member_a")
    conversation_id = new_conversation(client, csrf, cast.company.dept_a, title="A mea")
    answer = ask(client, csrf, conversation_id, "Câte zile de concediu avem?").json()
    return SimpleNamespace(conversation_id=conversation_id,
                           message_id=answer["assistant_message"]["id"])


def test_a_missing_department_filter_is_not_found_for_admins_too(cast):
    client, _ = _client(cast, "admin")
    response = client.get("/api/workspace/conversations", params={"department_id": 999_999})
    assert (response.status_code, response.json()["error"]) == (404, "not_found")


@pytest.mark.parametrize("key", ["approver_a", "admin"])
def test_a_colleague_filtering_by_the_same_department_sees_only_their_own(cast, owned, key):
    client, csrf = _client(cast, key)
    own = new_conversation(client, csrf, cast.company.dept_a)
    listed = client.get("/api/workspace/conversations",
                        params={"department_id": cast.company.dept_a}).json()["conversations"]
    assert [item["id"] for item in listed] == [own]


@pytest.mark.parametrize("key", ["approver_a", "member_b"])
def test_nobody_lists_or_opens_conversations_in_a_department_outside_their_scope(cast, key):
    client, csrf = _client(cast, key)
    foreign = cast.company.dept_b if key == "approver_a" else cast.company.dept_a
    response = client.get("/api/workspace/conversations", params={"department_id": foreign})
    assert (response.status_code, response.json()["error"]) == (404, "not_found")
    response = client.post("/api/workspace/conversations", json={"department_id": foreign},
                           headers=authed(client, csrf))
    assert (response.status_code, response.json()["error"]) == (404, "not_found")
    assert cast.conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0


def test_a_colleagues_history_never_reaches_the_prompt(cast, owned):
    secret = "Codul intern al proiectului este ZEBRA-7731."
    owner, owner_csrf = _client(cast, "member_a")
    ask(owner, owner_csrf, owned.conversation_id, secret)
    client, csrf = _client(cast, "approver_a")
    conversation_id = new_conversation(client, csrf, cast.company.dept_a)
    _, body = ask_stream(client, csrf, conversation_id, "Care este codul proiectului?")
    prompt = cast.ws.engine.calls[-1]["prompt"]
    assert "ZEBRA-7731" not in prompt and "ZEBRA-7731" not in body
    assert "Câte zile de concediu" not in prompt


def test_strangers_leave_no_trace_on_someone_elses_conversation(cast, owned):
    client, csrf = _client(cast, "member_b")
    before = {action: len(audit_actions(cast.conn, action))
              for action in ("chat.asked", "conversation.deleted", "message.feedback")}
    messages_before = cast.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    base = f"/api/workspace/conversations/{owned.conversation_id}"
    headers = authed(client, csrf)
    statuses = [
        client.post(f"{base}/messages", json={"content": "x"}, headers=headers).status_code,
        client.post(f"{base}/messages", json={"content": "x"},
                    headers={**headers, **SSE_ACCEPT}).status_code,
        client.patch(base, json={"title": "Furată"}, headers=headers).status_code,
        client.post(f"/api/workspace/messages/{owned.message_id}/feedback",
                    json={"value": 0}, headers=headers).status_code,
        client.delete(base, headers=headers).status_code,
    ]
    assert statuses == [404] * 5
    after = {action: len(audit_actions(cast.conn, action)) for action in before}
    assert after == before
    assert cast.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == messages_before
    assert cast.conn.execute("SELECT title FROM conversations WHERE id = ?",
                             (owned.conversation_id,)).fetchone()["title"] == "A mea"


@pytest.mark.parametrize("how", ["removed", "archived"])
def test_a_lost_department_closes_every_route_to_its_conversations(cast, owned, how):
    with workspace_db.tx(cast.conn):
        if how == "removed":
            cast.conn.execute("DELETE FROM user_departments WHERE user_id = ? "
                              "AND department_id = ?",
                              (cast.company.member_a.id, cast.company.dept_a))
        else:
            cast.conn.execute("UPDATE departments SET archived = 1 WHERE id = ?",
                              (cast.company.dept_a,))
    client, csrf = _client(cast, "member_a")
    base = f"/api/workspace/conversations/{owned.conversation_id}"
    headers = authed(client, csrf)
    responses = [
        client.get(base),
        client.patch(base, json={"title": "Nouă"}, headers=headers),
        client.post(f"{base}/messages", json={"content": "x"}, headers=headers),
        client.post(f"/api/workspace/messages/{owned.message_id}/feedback",
                    json={"value": 1}, headers=headers),
        client.delete(base, headers=headers),
        client.get("/api/workspace/conversations",
                   params={"department_id": cast.company.dept_a}),
    ]
    assert [(r.status_code, r.json()["error"]) for r in responses] == [(404, "not_found")] * 6
    assert client.get("/api/workspace/conversations").json()["conversations"] == []
    row = message_row(cast.conn, owned.message_id)
    assert row["feedback"] is None
    assert cast.conn.execute("SELECT title FROM conversations WHERE id = ?",
                             (owned.conversation_id,)).fetchone()["title"] != "Nouă"


def test_an_admin_chats_in_any_department_with_retrieval_scoped_to_it(cast):
    seed_doc(cast.conn, department_id=cast.company.dept_b, title="Regulament HR",
             text="Concediul medical se anunță în aceeași zi.")
    seed_doc(cast.conn, department_id=cast.company.dept_a, title="Vânzări interne",
             text="Concediul echipei de vânzări se planifică trimestrial.")
    client, csrf = _client(cast, "admin")
    conversation_id = new_conversation(client, csrf, cast.company.dept_b)
    _, body = ask_stream(client, csrf, conversation_id, "Cum se anunță concediul?")
    events = parse_sse(body)
    titles = [citation["title"] for citation in events[1][1]["citations"]]
    assert titles == ["Regulament HR"]
    member, _ = _client(cast, "member_b")
    assert member.get(f"/api/workspace/conversations/{conversation_id}").status_code == 404


def test_feedback_on_a_message_deleted_with_its_conversation_is_not_found(cast, owned):
    client, csrf = _client(cast, "member_a")
    assert client.delete(f"/api/workspace/conversations/{owned.conversation_id}",
                         headers=authed(client, csrf)).status_code == 204
    response = client.post(f"/api/workspace/messages/{owned.message_id}/feedback",
                           json={"value": 1}, headers=authed(client, csrf))
    assert (response.status_code, response.json()["error"]) == (404, "not_found")
    assert audit_actions(cast.conn, "message.feedback") == []


def test_a_workspace_error_in_json_mode_keeps_both_messages(cast):
    cast.ws.use_engine(FakeEngine(fail=WorkspaceError("model_unavailable", "down", 503,
                                                      reason="no_local_model")))
    client, csrf = _client(cast, "member_a")
    conversation_id = new_conversation(client, csrf, cast.company.dept_a)
    body = ask(client, csrf, conversation_id, "Întrebare").json()
    assert body["user_message"]["conversation_id"] == conversation_id
    assert body["assistant_message"]["conversation_id"] == conversation_id
