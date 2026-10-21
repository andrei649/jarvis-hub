"""Helpers shared by the assistant (S3) route suites; this module holds no tests itself.

``chat_client()`` is a TestClient over a minimal app with the auth and chat routers;
``seed_doc`` writes a ready document with one chunk straight into the database (the
FTS triggers index it), so a test controls exactly what retrieval can find;
``parse_sse`` turns a streamed body into ``(event, data)`` pairs, pings included.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth, workspace_chat
from agents.core.workspace import db as workspace_db
from tests.support.workspace_fixtures import authed, make_app

SSE_ACCEPT = {"Accept": "text/event-stream"}


def chat_app() -> FastAPI:
    """An app with ``workspace_auth`` (login) and ``workspace_chat``."""
    return make_app(workspace_auth.router, workspace_chat.router)


def chat_client() -> TestClient:
    return TestClient(chat_app())


def seed_doc(conn: sqlite3.Connection, *, department_id: int | None, title: str, text: str,
             visibility: str = "department", uploader_id: int | None = None,
             status: str = "ready", page: int | None = None) -> int:
    """A ready document with a single chunk holding *text*; returns its id."""
    stamp = workspace_db.now()
    with workspace_db.tx(conn):
        document_id = int(conn.execute(
            "INSERT INTO documents (department_id, visibility, title, filename, mime, size_bytes, "
            "sha256, uploader_id, status, chunk_count, char_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'text/plain', ?, ?, ?, ?, 1, ?, ?, ?)",
            (department_id, visibility, title, f"{title}.txt", len(text), "0" * 64, uploader_id,
             status, len(text), stamp, stamp),
        ).lastrowid)
        conn.execute("INSERT INTO chunks (document_id, ord, page, text) VALUES (?, 0, ?, ?)",
                     (document_id, page, text))
    return document_id


def new_conversation(client: TestClient, csrf: str, department_id: int,
                     title: str | None = None) -> int:
    """``POST /conversations``; returns the new id."""
    body: dict[str, Any] = {"department_id": department_id}
    if title is not None:
        body["title"] = title
    response = client.post("/api/workspace/conversations", json=body,
                           headers=authed(client, csrf))
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def ask(client: TestClient, csrf: str, conversation_id: int, content: str) -> httpx.Response:
    """The JSON mode of ``POST /conversations/{id}/messages``."""
    return client.post(f"/api/workspace/conversations/{conversation_id}/messages",
                       json={"content": content}, headers=authed(client, csrf))


def ask_stream(client: TestClient, csrf: str, conversation_id: int,
               content: str) -> tuple[httpx.Response, str]:
    """The SSE mode, read to the end; returns the response and its whole body."""
    with client.stream("POST", f"/api/workspace/conversations/{conversation_id}/messages",
                       json={"content": content},
                       headers={**authed(client, csrf), **SSE_ACCEPT}) as response:
        body = "".join(response.iter_text())
    return response, body


def parse_sse(body: str) -> list[tuple[str, Any]]:
    """``[(event, data), …]`` of an SSE body; a comment frame reads as ``("ping", text)``."""
    events: list[tuple[str, Any]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        if block.startswith(":"):
            events.append(("ping", block[1:].strip()))
            continue
        event, data = "message", None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((event, data))
    return events


def message_row(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    assert row is not None
    return row


def audit_actions(conn: sqlite3.Connection, action: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM audit WHERE action = ? ORDER BY id", (action,)).fetchall()


def live_answers() -> dict[int, tuple[int, float]]:
    """The router's registry of answers in flight: id → (conversation id, created_at)."""
    return workspace_chat._LIVE_ANSWERS
