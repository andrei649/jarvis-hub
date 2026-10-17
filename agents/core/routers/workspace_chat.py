"""Nerva Workspace — the assistant API (spec §7 "S3", §8).

Conversations belong to one user and one department. Every route answers a
conversation or message that is not the caller's own — or whose department the
caller may no longer use — with ``404 not_found``; admins are no exception, nobody
reads anyone else's conversations.

Asking a question (``POST /conversations/{id}/messages``) runs in three steps:

1. one transaction stores the user's message and a ``pending`` assistant row (and the
   automatic title), after the busy check (``409 conversation_busy``) and the
   30-messages-per-minute limit (``429 rate_limited``) — inside the same
   ``BEGIN IMMEDIATE``, so parallel requests cannot slip past either;
2. the context is read (history, department instructions, retrieval scoped to the
   conversation's department plus company-wide documents) and the prompt built;
3. the model answers through ``llm.complete``, and the final row — ``complete``, or
   ``error`` with its ``error_code`` — is written through a fresh connection.

With ``Accept: text/event-stream`` step 3 is streamed as Server-Sent Events (§8):
``start``, ``sources``, ``token``…, then ``done`` or ``error``, with ``: ping`` every
15 s. The model runs in a runner task started before the response is returned, so a
turn is finished even if the stream is never read; closing the stream (the client
went away) cancels the runner and the row ends as ``error`` / ``cancelled``.

A ``pending`` row is "live" only while this process is producing it (the hub is one
process per data root). A pending row left behind by a crash or restart is marked
``error`` / ``interrupted`` by the next question, so it can never lock a conversation.

An answer row is identified by its id *and* its conversation and creation time, never
by the id alone: ``messages`` has no ``AUTOINCREMENT``, so SQLite hands the ids of
deleted rows to the next insert. A conversation deleted while its answer is still
being written gives its ids away — possibly to another user in another department —
and the late answer must neither overwrite that newer row nor read it back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from agents.core.workspace import assistant, audit, auth, db, documents, llm
from agents.core.workspace.assistant import AnswerPlan
from agents.core.workspace.auth import WsAdmin, WsUser
from agents.core.workspace.db import Db, tx
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.http import (
    MAX_ID,
    read_json,
    require_int,
    require_str,
    ws_json,
    ws_no_content,
)
from agents.core.workspace.identity import WorkspaceUser

logger = logging.getLogger("nerva.workspace.routers.chat")

router = APIRouter(prefix="/api/workspace")

ConversationId = Annotated[int, Path(ge=1, le=MAX_ID)]
MessageId = Annotated[int, Path(ge=1, le=MAX_ID)]
DepartmentFilter = Annotated[int | None, Query(ge=1, le=MAX_ID)]

MAX_TITLE = 200
MAX_CONTENT = 8000
MAX_NOTE = 1000
#: A question body: 8 000 characters of 4-byte UTF-8 always fit, with room for JSON escapes.
MAX_MESSAGE_BODY_BYTES = 128 * 1024
#: Newest conversations a list returns, and newest messages a conversation returns.
MAX_CONVERSATIONS = 500
MAX_MESSAGES = 1000
CHAT_RATE_LIMIT = 30
CHAT_RATE_WINDOW_SECONDS = 60
ANSWER_MAX_TOKENS = 1200
ANSWER_TEMPERATURE = 0.2
ANSWER_TIMEOUT_SECONDS = 180.0
PING_INTERVAL_SECONDS = 15.0
MODEL_TEST_MAX_TOKENS = 64
MODEL_TEST_TIMEOUT_SECONDS = 60.0
MODEL_TEST_SYSTEM = "You are a connectivity check. Reply with the single word OK."
MODEL_TEST_PROMPT = "Reply with the single word OK."
SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
PING_FRAME = ": ping\n\n"

#: Assistant rows this process is producing right now: id → (conversation id, created_at),
#: the identity that survives rowid reuse (see the module docstring).
_LIVE_ANSWERS: dict[int, tuple[int, float]] = {}
#: Runner tasks, referenced until they finish (the event loop holds tasks weakly).
_RUNNERS: set[asyncio.Task] = set()


def _not_found(what: str) -> WorkspaceError:
    return WorkspaceError("not_found", f"no such {what}", 404)


def _row_key(row: sqlite3.Row) -> tuple[int, float]:
    return int(row["conversation_id"]), float(row["created_at"])


def _is_live(row: sqlite3.Row) -> bool:
    """True while this process produces exactly this row (not an older owner of its id)."""
    return _LIVE_ANSWERS.get(int(row["id"])) == _row_key(row)


# ── JSON shapes ──────────────────────────────────────────────────────────────────────

def _citations(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _cited_document_id(citation: object) -> int | None:
    if not isinstance(citation, dict):
        return None
    document_id = citation.get("document_id")
    if isinstance(document_id, int) and not isinstance(document_id, bool):
        return document_id
    return None


def openable_documents(conn: sqlite3.Connection, user: WorkspaceUser,
                       rows: list[sqlite3.Row]) -> set[int]:
    """The documents cited by *rows* that *user* may open now (``documents.visible_ids``).

    An answer keeps the excerpts it was given, but a cited document can be deleted later,
    or its department can leave the reader's scope; like a report run's, each citation is
    then judged at read time, so the source drawer offers a link only where it works.
    """
    wanted = [document_id for row in rows for citation in _citations(row["citations_json"])
              if (document_id := _cited_document_id(citation)) is not None]
    return documents.visible_ids(conn, user, wanted)


def message_json(row: sqlite3.Row, openable: set[int] | None = None) -> dict:
    """A message as the API shows it. A pending row no process is producing reads as
    ``error`` / ``interrupted`` — that is what it is.

    With *openable* (:func:`openable_documents` for the reader) every citation carries
    ``can_open``: whether the reader may open its document now.
    """
    status, error_code = row["status"], row["error_code"]
    if status == "pending" and not _is_live(row):
        status, error_code = "error", "interrupted"
    citations = _citations(row["citations_json"])
    if openable is not None:
        citations = [{**citation, "can_open": _cited_document_id(citation) in openable}
                     if isinstance(citation, dict) else citation for citation in citations]
    return {
        "id": int(row["id"]), "conversation_id": int(row["conversation_id"]),
        "role": row["role"], "content": row["content"],
        "citations": citations, "status": status,
        "error_code": error_code, "model": row["model"], "locality": row["locality"],
        "latency_ms": row["latency_ms"], "feedback": row["feedback"],
        "feedback_note": row["feedback_note"], "created_at": row["created_at"],
    }


def conversation_json(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """``{id, title, department_id, created_at, updated_at, message_count}``."""
    count = conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                         (row["id"],)).fetchone()[0]
    return {"id": int(row["id"]), "title": row["title"],
            "department_id": int(row["department_id"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"], "message_count": int(count)}


def _message(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()


# ── scope ────────────────────────────────────────────────────────────────────────────

def _usable_department(conn: sqlite3.Connection, user: WorkspaceUser,
                       department_id: int) -> sqlite3.Row:
    """A department the user may chat in: 404 outside their scope, 409 when archived."""
    row = conn.execute("SELECT id, archived FROM departments WHERE id = ?",
                       (department_id,)).fetchone()
    if row is None or not user.can_access_department(department_id):
        raise WorkspaceError("not_found", "department not found", 404)
    if row["archived"]:
        raise WorkspaceError("department_archived", "this department is archived", 409)
    return row


def _own_conversation(conn: sqlite3.Connection, user: WorkspaceUser,
                      conversation_id: int) -> sqlite3.Row:
    """The caller's own conversation in a department they may still use, else 404."""
    row = conn.execute(
        "SELECT c.*, d.archived AS department_archived FROM conversations c "
        "JOIN departments d ON d.id = c.department_id WHERE c.id = ? AND c.user_id = ?",
        (conversation_id, user.id),
    ).fetchone()
    if row is None or not user.can_access_department(int(row["department_id"])):
        raise _not_found("conversation")
    return row


def _visible_department_ids(conn: sqlite3.Connection, user: WorkspaceUser) -> list[int]:
    """Departments whose conversations the user may list (admins: archived ones too)."""
    if not user.is_admin:
        return list(user.department_ids)
    return [int(row["id"]) for row in conn.execute("SELECT id FROM departments").fetchall()]


def _org_policy(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT model_policy FROM org WHERE id = 1").fetchone()
    return llm.normalize_policy(row["model_policy"] if row else llm.LOCAL_ONLY)


# ── conversations ────────────────────────────────────────────────────────────────────

_LIST_SQL = (
    "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) "
    "AS message_count FROM conversations c "
    "WHERE c.user_id = ? AND c.department_id IN (SELECT value FROM json_each(?)) "
    "AND (? IS NULL OR c.department_id = ?) ORDER BY c.updated_at DESC, c.id DESC LIMIT ?"
)


@router.get("/conversations")
def list_conversations(user: WsUser, conn: Db,
                       department_id: DepartmentFilter = None) -> JSONResponse:
    """The caller's own conversations, most recently active first.

    A department filter must name a department the caller may use — one that does
    not exist is ``404`` for admins too, like any other out-of-scope id.
    """
    if department_id is not None and (
            not user.can_access_department(department_id)
            or conn.execute("SELECT 1 FROM departments WHERE id = ?",
                            (department_id,)).fetchone() is None):
        raise WorkspaceError("not_found", "department not found", 404)
    rows = conn.execute(_LIST_SQL, (user.id, json.dumps(_visible_department_ids(conn, user)),
                                    department_id, department_id,
                                    MAX_CONVERSATIONS)).fetchall()
    items = [{"id": int(row["id"]), "title": row["title"],
              "department_id": int(row["department_id"]), "created_at": row["created_at"],
              "updated_at": row["updated_at"], "message_count": int(row["message_count"])}
             for row in rows]
    return ws_json({"conversations": items})


@router.post("/conversations")
async def create_conversation(request: Request, user: WsUser, conn: Db) -> JSONResponse:
    """``{department_id, title?}`` → 201 conversation (default title by the user's locale)."""
    body = await read_json(request)
    department_id = require_int(body, "department_id", minimum=1)
    title = require_str(body, "title", max_len=MAX_TITLE, required=False)
    stamp = db.now()
    with tx(conn):
        _usable_department(conn, user, department_id)
        conversation_id = int(conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.id, department_id, title or assistant.default_title(user.locale), stamp, stamp),
        ).lastrowid)
    return ws_json(conversation_json(conn, _own_conversation(conn, user, conversation_id)),
                   status=201)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: ConversationId, user: WsUser, conn: Db) -> JSONResponse:
    """The conversation and its newest :data:`MAX_MESSAGES` messages, oldest first.

    The message read repeats the ownership condition in SQL: this sync route runs in a
    thread pool, and a conversation id freed by a concurrent delete can be reused.
    """
    row = _own_conversation(conn, user, conversation_id)
    rows = conn.execute(
        "SELECT m.* FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.conversation_id = ? AND c.user_id = ? ORDER BY m.id DESC LIMIT ?",
        (conversation_id, user.id, MAX_MESSAGES + 1)).fetchall()
    truncated = len(rows) > MAX_MESSAGES
    shown = rows[:MAX_MESSAGES]
    openable = openable_documents(conn, user, shown)
    messages = [message_json(message, openable) for message in reversed(shown)]
    return ws_json({"conversation": conversation_json(conn, row), "messages": messages,
                    "truncated": truncated})


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: ConversationId, request: Request, user: WsUser,
                              conn: Db) -> JSONResponse:
    """``{title}`` → the conversation (the same shape ``POST /conversations`` answers)."""
    body = await read_json(request)
    title = require_str(body, "title", max_len=MAX_TITLE, min_len=1)
    with tx(conn):
        _own_conversation(conn, user, conversation_id)
        conn.execute("UPDATE conversations SET title = ?, updated_at = ? "
                     "WHERE id = ? AND user_id = ?",
                     (title, db.now(), conversation_id, user.id))
        renamed = _own_conversation(conn, user, conversation_id)
    return ws_json(conversation_json(conn, renamed))


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: ConversationId, request: Request, user: WsUser,
                        conn: Db) -> Response:
    """Delete the conversation and its messages → 204 (audited, without content).

    The ownership check and the delete share one transaction: sync routes run in a
    thread pool, so nothing else may slip in between them.
    """
    with tx(conn):
        row = _own_conversation(conn, user, conversation_id)
        count = conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                             (conversation_id,)).fetchone()[0]
        conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?",
                     (conversation_id, user.id))
        audit.record(conn, actor=user, action="conversation.deleted", target_type="conversation",
                     target_id=conversation_id, department_id=int(row["department_id"]),
                     ip=auth.client_ip(request), details={"messages": int(count)})
    return ws_no_content()


# ── asking: step 1, the transaction ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Turn:
    """One question in flight: who asked where, and the two rows it created.

    ``stamp`` is both rows' ``created_at``. With the conversation id it tells this
    turn's answer row apart from a later row that inherited the same id.
    """

    user: WorkspaceUser
    conversation_id: int
    department_id: int
    user_message: dict
    assistant_id: int
    stamp: float
    conversation: dict

    @property
    def key(self) -> tuple[int, float]:
        return self.conversation_id, self.stamp


def _release(turn: Turn) -> None:
    """This turn's answer is no longer live; a newer owner of the same id stays live."""
    if _LIVE_ANSWERS.get(turn.assistant_id) == turn.key:
        _LIVE_ANSWERS.pop(turn.assistant_id, None)


def _refuse_if_busy(conn: sqlite3.Connection, conversation_id: int) -> None:
    """``409 conversation_busy`` while an answer is live; orphans become ``interrupted``."""
    pending = conn.execute(
        "SELECT id, conversation_id, created_at FROM messages "
        "WHERE conversation_id = ? AND status = 'pending'", (conversation_id,)).fetchall()
    if any(_is_live(row) for row in pending):
        raise WorkspaceError("conversation_busy", "an answer is still being written", 409)
    if pending:
        conn.execute("UPDATE messages SET status = 'error', error_code = 'interrupted' "
                     "WHERE id IN (SELECT value FROM json_each(?)) AND conversation_id = ? "
                     "AND status = 'pending'",
                     (json.dumps([int(row["id"]) for row in pending]), conversation_id))


def _check_rate(conn: sqlite3.Connection, user_id: int) -> None:
    """``429 rate_limited`` past 30 questions a minute (counted in the append-only audit)."""
    stamp = db.now()
    times = [float(row[0]) for row in conn.execute(
        "SELECT ts FROM audit WHERE actor_user_id = ? AND action = 'chat.asked' AND ts > ? "
        "ORDER BY id DESC LIMIT ?",
        (user_id, stamp - CHAT_RATE_WINDOW_SECONDS, CHAT_RATE_LIMIT)).fetchall()]
    if len(times) >= CHAT_RATE_LIMIT:
        retry = max(1, math.ceil(times[CHAT_RATE_LIMIT - 1] + CHAT_RATE_WINDOW_SECONDS - stamp))
        raise WorkspaceError("rate_limited", "too many questions; wait a moment", 429,
                             retry_after_seconds=retry)


def _insert_turn_rows(conn: sqlite3.Connection, conversation_id: int, content: str,
                      stamp: float) -> tuple[int, int]:
    """Insert the question and its pending answer; titles a still-default conversation.

    The title is re-read inside the transaction, so a rename that landed a moment
    earlier is kept, and a conversation deleted meanwhile is a 404, not a foreign-key
    failure.
    """
    current = conn.execute("SELECT title FROM conversations WHERE id = ?",
                           (conversation_id,)).fetchone()
    if current is None:
        raise _not_found("conversation")
    user_message_id = int(conn.execute(
        "INSERT INTO messages (conversation_id, role, content, status, created_at) "
        "VALUES (?, 'user', ?, 'complete', ?)", (conversation_id, content, stamp)).lastrowid)
    assistant_id = int(conn.execute(
        "INSERT INTO messages (conversation_id, role, content, status, created_at) "
        "VALUES (?, 'assistant', '', 'pending', ?)", (conversation_id, stamp)).lastrowid)
    title = current["title"]
    if assistant.is_default_title(title):
        title = assistant.auto_title(content)
    conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                 (title, stamp, conversation_id))
    return user_message_id, assistant_id


def open_turn(conn: sqlite3.Connection, user: WorkspaceUser, conversation: sqlite3.Row,
              content: str, *, ip: str) -> Turn:
    """Step 1: store the question and its pending answer row, in one transaction.

    The assistant row is marked live before the commit: the code between the insert
    and the commit never awaits, so no other request can see it pending yet not live.
    """
    conversation_id = int(conversation["id"])
    department_id = int(conversation["department_id"])
    stamp = db.now()
    assistant_id = 0  # rowids start at 1: 0 means "not inserted yet"
    try:
        with tx(conn):
            _refuse_if_busy(conn, conversation_id)
            _check_rate(conn, user.id)
            user_message_id, assistant_id = _insert_turn_rows(conn, conversation_id, content,
                                                              stamp)
            _LIVE_ANSWERS[assistant_id] = (conversation_id, stamp)
            audit.record(conn, actor=user, action="chat.asked", target_type="conversation",
                         target_id=conversation_id, department_id=department_id, ip=ip,
                         details={"user_message_id": user_message_id,
                                  "assistant_message_id": assistant_id,
                                  "chars": len(content)})
    except BaseException:
        if _LIVE_ANSWERS.get(assistant_id) == (conversation_id, stamp):
            _LIVE_ANSWERS.pop(assistant_id, None)
        raise
    user_row = _message(conn, user_message_id)
    return Turn(user=user, conversation_id=conversation_id, department_id=department_id,
                user_message=message_json(user_row), assistant_id=assistant_id, stamp=stamp,
                conversation=conversation_json(conn, _own_conversation(conn, user,
                                                                       conversation_id)))


# ── asking: step 3, the answer and its final row ─────────────────────────────────────

def _transient_message(turn: Turn, *, status: str, content: str = "",
                       citations: list | None = None, error_code: str | None = None,
                       meta: dict | None = None) -> dict:
    """The outcome in the message shape when there is no stored row to show for it."""
    meta = meta or {}
    return {"id": turn.assistant_id, "conversation_id": turn.conversation_id,
            "role": "assistant", "content": content, "citations": citations or [],
            "status": status, "error_code": error_code, "model": meta.get("model"),
            "locality": meta.get("locality"), "latency_ms": meta.get("latency_ms"),
            "feedback": None, "feedback_note": None, "created_at": turn.stamp}


def _store_outcome(turn: Turn, *, status: str, content: str = "", citations: list | None = None,
                   error_code: str | None = None, meta: dict | None = None) -> dict:
    """Write the final assistant row through a fresh connection; returns its JSON.

    The row is matched on its whole identity and only while still ``pending``: a
    cancelled or interrupted turn cannot overwrite a newer outcome, and an answer whose
    conversation was deleted cannot reach — or read back — the row that inherited its
    id. Then nothing is written and the outcome is answered as it would have been.
    """
    meta = meta or {}
    identity = (turn.assistant_id, turn.conversation_id, turn.stamp)
    conn = db.connect()
    try:
        with tx(conn):
            updated = conn.execute(
                "UPDATE messages SET status = ?, content = ?, citations_json = ?, error_code = ?, "
                "model = ?, route = ?, locality = ?, latency_ms = ? "
                "WHERE id = ? AND conversation_id = ? AND created_at = ? AND status = 'pending'",
                (status, content, json.dumps(citations or [], ensure_ascii=False), error_code,
                 meta.get("model"), meta.get("route"), meta.get("locality"),
                 meta.get("latency_ms"), *identity),
            ).rowcount
            if updated:
                conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                             (db.now(), turn.conversation_id))
        row = conn.execute("SELECT * FROM messages WHERE id = ? AND conversation_id = ? "
                           "AND created_at = ?", identity).fetchone()
        stored = None if row is None else message_json(
            row, openable_documents(conn, turn.user, [row]))
    finally:
        conn.close()
        _release(turn)
    if stored is None:
        logger.info("conversation %s was deleted before its answer was stored",
                    turn.conversation_id)
        return _transient_message(turn, status=status, content=content, citations=citations,
                                  error_code=error_code, meta=meta)
    return stored


def _stored(turn: Turn, error: WorkspaceError | None,
            **outcome: Any) -> tuple[dict, WorkspaceError | None]:
    """:func:`_store_outcome`, where a database failure becomes the turn's own error.

    The row then stays ``pending`` without being live, so it reads — and is later
    marked — ``interrupted``; the caller still gets a well-formed answer.
    """
    try:
        return _store_outcome(turn, **outcome), error
    except (sqlite3.Error, OSError):
        logger.exception("workspace answer could not be stored (conversation %s)",
                         turn.conversation_id)
        failure = WorkspaceError("internal_error", "the answer could not be stored", 500)
        return _transient_message(turn, status="error", error_code=failure.code), failure


def _failure_meta(error: WorkspaceError) -> dict:
    return {key: error.extra.get(key) for key in ("model", "route", "locality", "latency_ms")}


async def produce_answer(turn: Turn, plan: AnswerPlan, policy: str,
                         on_token: Callable[[str], Awaitable[None]] | None = None,
                         ) -> tuple[dict, WorkspaceError | None]:
    """Step 3: run the model and store the outcome; ``(assistant_message, error or None)``.

    Model and policy failures are expected outcomes, stored with their code. A
    cancellation (the client left) is stored as ``cancelled`` and re-raised.
    """
    try:
        try:
            result = await llm.complete(
                system=plan.system, prompt=plan.prompt, policy=policy,
                max_tokens=ANSWER_MAX_TOKENS, temperature=ANSWER_TEMPERATURE,
                on_token=on_token, timeout_seconds=ANSWER_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            _stored(turn, None, status="error", error_code="cancelled")
            raise
        except WorkspaceError as error:
            logger.info("workspace answer failed: %s", error.code)
            return _stored(turn, error, status="error", error_code=error.code,
                           meta=_failure_meta(error))
        except Exception:
            logger.exception("workspace answer failed unexpectedly (conversation %s)",
                             turn.conversation_id)
            error = WorkspaceError("internal_error", "the answer could not be produced", 500)
            return _stored(turn, error, status="error", error_code=error.code)
        content = result.text.strip()
        return _stored(
            turn, None, status="complete", content=content,
            citations=assistant.filter_citations(content, plan.citations),
            meta={"model": result.model, "route": result.route, "locality": result.locality,
                  "latency_ms": result.latency_ms},
        )
    finally:
        _release(turn)


# ── asking: the two response modes ───────────────────────────────────────────────────

def sse(event: str, data: dict) -> str:
    """One Server-Sent Event frame (JSON never holds a raw newline)."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _error_payload(error: WorkspaceError, message: dict | None) -> dict:
    return {**error.extra, "error": error.code, "message": error.message,
            "assistant_message": message}


def _spawn(coroutine: Coroutine[Any, Any, None]) -> asyncio.Task:
    task = asyncio.create_task(coroutine)
    _RUNNERS.add(task)
    task.add_done_callback(_RUNNERS.discard)
    return task


async def _stop(task: asyncio.Task) -> None:
    """Cancel the runner unless it finished, and reap it."""
    if not task.done():
        task.cancel()
    with suppress(asyncio.CancelledError):
        try:
            await task
        except Exception:
            logger.exception("workspace answer runner failed during cleanup")


async def _event_stream(turn: Turn, plan: AnswerPlan, queue: asyncio.Queue,
                        task: asyncio.Task) -> AsyncIterator[str]:
    """The SSE body: drains the runner's queue, pinging while the model is quiet."""
    try:
        yield sse("start", {"user_message": turn.user_message,
                            "assistant_message_id": turn.assistant_id,
                            "conversation": turn.conversation})
        yield sse("sources", {"citations": plan.citations})
        while True:
            try:
                kind, data = await asyncio.wait_for(queue.get(), PING_INTERVAL_SECONDS)
            except TimeoutError:
                yield PING_FRAME
                continue
            if kind == "token":
                yield sse("token", {"t": data})
            elif kind == "done":
                yield sse("done", {"assistant_message": data})
                return
            else:
                error, message = data
                yield sse("error", _error_payload(error, message))
                return
    finally:
        await _stop(task)


def stream_answer(turn: Turn, plan: AnswerPlan, policy: str) -> StreamingResponse:
    """Start the runner now and stream its events (spec §8 "SSE framing")."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_token(text: str) -> None:
        await queue.put(("token", text))

    async def runner() -> None:
        try:
            message, error = await produce_answer(turn, plan, policy, on_token)
        except Exception:
            # A runner that dies silently would leave the stream pinging forever.
            logger.exception("workspace answer runner failed (conversation %s)",
                             turn.conversation_id)
            error = WorkspaceError("internal_error", "the answer could not be produced", 500)
            message = _transient_message(turn, status="error", error_code=error.code)
        await queue.put(("error", (error, message)) if error is not None else ("done", message))

    task = _spawn(runner())
    return StreamingResponse(_event_stream(turn, plan, queue, task),
                             media_type="text/event-stream", headers=SSE_HEADERS)


async def answer_json(turn: Turn, plan: AnswerPlan, policy: str) -> JSONResponse:
    """The non-streaming mode: 201 ``{user_message, assistant_message, conversation}``.

    A failed answer keeps the HTTP status of its error, and the error body carries both
    stored messages, so a client can show the question and the failed answer alike.
    """
    message, error = await produce_answer(turn, plan, policy)
    if error is not None:
        raise WorkspaceError(error.code, error.message, error.status,
                             **{**error.extra, "user_message": turn.user_message,
                                "assistant_message": message})
    return ws_json({"user_message": turn.user_message, "assistant_message": message,
                    "conversation": turn.conversation}, status=201)


def _wants_stream(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "").lower()


def _plan(conn: sqlite3.Connection, turn: Turn, question: str) -> AnswerPlan:
    """Step 2. A failure here still finishes the turn — stored as ``internal_error`` and
    answered as the workspace's own 500 JSON, never as an unhandled exception."""
    try:
        return assistant.plan_answer(conn, conversation_id=turn.conversation_id,
                                     department_id=turn.department_id, question=question,
                                     user_message_id=int(turn.user_message["id"]),
                                     locale=turn.user.locale)
    except Exception as exc:
        logger.exception("workspace answer context failed (conversation %s)",
                         turn.conversation_id)
        failure = WorkspaceError("internal_error", "the answer could not be prepared", 500)
        message, failure = _stored(turn, failure, status="error", error_code=failure.code)
        raise WorkspaceError(failure.code, failure.message, failure.status,
                             user_message=turn.user_message,
                             assistant_message=message) from exc


@router.post("/conversations/{conversation_id}/messages")
async def post_message(conversation_id: ConversationId, request: Request, user: WsUser,
                       conn: Db) -> Response:
    """``{content}`` → SSE with ``Accept: text/event-stream``, else JSON (spec §7, §8).

    Everything that can fail before the model starts — the policy read included — runs
    before the turn is opened or finishes it, so no failure leaves a live pending row.
    """
    body = await read_json(request, max_bytes=MAX_MESSAGE_BODY_BYTES)
    content = require_str(body, "content", max_len=MAX_CONTENT, min_len=1, multiline=True)
    conversation = _own_conversation(conn, user, conversation_id)
    if conversation["department_archived"]:
        raise WorkspaceError("department_archived", "this department is archived", 409)
    policy = _org_policy(conn)
    turn = open_turn(conn, user, conversation, content, ip=auth.client_ip(request))
    plan = _plan(conn, turn, content)
    if _wants_stream(request):
        return stream_answer(turn, plan, policy)
    return await answer_json(turn, plan, policy)


# ── feedback ─────────────────────────────────────────────────────────────────────────

def _rateable_message(conn: sqlite3.Connection, user: WorkspaceUser,
                      message_id: int) -> sqlite3.Row:
    """A finished answer in one of the caller's own conversations, else 404."""
    row = conn.execute(
        "SELECT m.*, c.department_id FROM messages m JOIN conversations c "
        "ON c.id = m.conversation_id WHERE m.id = ? AND c.user_id = ? "
        "AND m.role = 'assistant' AND m.status = 'complete'",
        (message_id, user.id),
    ).fetchone()
    if row is None or not user.can_access_department(int(row["department_id"])):
        raise _not_found("answer")
    return row


@router.post("/messages/{message_id}/feedback")
async def message_feedback(message_id: MessageId, request: Request, user: WsUser,
                           conn: Db) -> JSONResponse:
    """``{value: 1 | -1 | 0, note?}`` → ``{message}``; 0 clears the rating and its note.

    The scope check, the write and the read-back share one transaction, so a
    conversation deleted by a concurrent request is a 404, never a half-written rating.
    """
    body = await read_json(request)
    value = require_int(body, "value", minimum=-1, maximum=1)
    note = require_str(body, "note", max_len=MAX_NOTE, required=False, multiline=True)
    stored_note = note if value != 0 and note else None
    with tx(conn):
        row = _rateable_message(conn, user, message_id)
        conn.execute("UPDATE messages SET feedback = ?, feedback_note = ? "
                     "WHERE id = ? AND role = 'assistant' AND status = 'complete'",
                     (value or None, stored_note, message_id))
        audit.record(conn, actor=user, action="message.feedback", target_type="message",
                     target_id=message_id, department_id=int(row["department_id"]),
                     ip=auth.client_ip(request),
                     details={"value": value, "has_note": stored_note is not None})
        rated = _message(conn, message_id)
        openable = openable_documents(conn, user, [rated])
    return ws_json({"message": message_json(rated, openable)})


# ── model status ─────────────────────────────────────────────────────────────────────

@router.get("/model")
async def model_posture(user: WsUser, conn: Db) -> JSONResponse:
    """What the assistant would use now, under the organisation's model policy."""
    return ws_json(await llm.posture(_org_policy(conn)))


def _model_test_outcome(error: WorkspaceError, started: float) -> dict:
    """A failed test call as the admin page shows it; a model that spent its whole
    budget thinking still answered, so it counts as reachable."""
    meta = _failure_meta(error)
    reachable = (error.code == "model_unavailable"
                 and error.extra.get("reason") == "thinking_exhausted")
    outcome = {"ok": reachable,
               "latency_ms": meta["latency_ms"] if meta["latency_ms"] is not None
               else int((time.monotonic() - started) * 1000),
               "model": meta["model"], "locality": meta["locality"], "route": meta["route"]}
    if not reachable:
        outcome.update(error=error.code, reason=error.extra.get("reason", ""),
                       message=error.message)
    return outcome


@router.post("/admin/model/test")
async def test_model(request: Request, admin: WsAdmin, conn: Db) -> JSONResponse:
    """Send one tiny real request → ``{ok, latency_ms, model, locality, route, error?}``."""
    started = time.monotonic()
    try:
        result = await llm.complete(system=MODEL_TEST_SYSTEM, prompt=MODEL_TEST_PROMPT,
                                    policy=_org_policy(conn), max_tokens=MODEL_TEST_MAX_TOKENS,
                                    temperature=0.0, timeout_seconds=MODEL_TEST_TIMEOUT_SECONDS)
        outcome: dict = {"ok": True, "latency_ms": result.latency_ms, "model": result.model,
                         "locality": result.locality, "route": result.route}
    except WorkspaceError as error:
        outcome = _model_test_outcome(error, started)
    except Exception:
        # The admin page shows the outcome; an unforeseen engine fault is one, not a 500.
        logger.exception("workspace model test failed unexpectedly")
        outcome = _model_test_outcome(
            WorkspaceError("internal_error", "the model test failed unexpectedly", 500), started)
    with tx(conn):
        audit.record(conn, actor=admin, action="model.tested", target_type="model",
                     target_id=str(outcome.get("model") or ""), ip=auth.client_ip(request),
                     details={"ok": outcome["ok"], "error": outcome.get("error", ""),
                              "route": outcome.get("route") or "",
                              "locality": outcome.get("locality") or ""})
    return ws_json(outcome)
