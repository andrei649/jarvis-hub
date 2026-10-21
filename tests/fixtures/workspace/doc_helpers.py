"""HTTP and database helpers shared by the knowledge-base test modules.

``docs_client()`` is a TestClient over a minimal app with the auth and documents
routers; ``upload`` sends one raw-body upload the way the browser does; ``seed_document``
writes a ready document with chunks straight into the database, for tests about access
and retrieval that do not need the extraction pipeline.
"""

from __future__ import annotations

import sqlite3
from urllib.parse import urlencode

import httpx
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth, workspace_documents
from agents.core.workspace import db
from tests.support.workspace_fixtures import authed, make_app


def docs_client() -> TestClient:
    """A client for an app with ``workspace_auth`` and ``workspace_documents``."""
    return TestClient(make_app(workspace_auth.router, workspace_documents.router))


def upload_url(scope: int | str, filename: str, title: str | None = None) -> str:
    params: dict[str, str] = {"department_id": str(scope), "filename": filename}
    if title is not None:
        params["title"] = title
    return "/api/workspace/documents?" + urlencode(params)


def upload(client: TestClient, csrf: str, scope: int | str, filename: str, data: bytes, *,
           title: str | None = None) -> httpx.Response:
    """``POST /api/workspace/documents`` with *data* as the raw body."""
    return client.post(upload_url(scope, filename, title), content=data,
                       headers={**authed(client, csrf), "Content-Type": "application/octet-stream"})


def seed_document(conn: sqlite3.Connection, *, department_id: int | None, uploader_id: int | None,
                  title: str, chunks: list[str], visibility: str = "department",
                  status: str = "ready", filename: str | None = None,
                  pages: list[int | None] | None = None) -> int:
    """Insert a document and its chunks directly (indexed through the FTS triggers)."""
    stamp = db.now()
    with db.tx(conn):
        document_id = int(conn.execute(
            "INSERT INTO documents (department_id, visibility, title, filename, mime, size_bytes, "
            "sha256, uploader_id, status, chunk_count, char_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'text/plain', ?, ?, ?, ?, ?, ?, ?, ?)",
            (department_id, visibility, title, filename or f"{title}.txt",
             sum(len(c) for c in chunks), "0" * 64, uploader_id, status, len(chunks),
             sum(len(c) for c in chunks), stamp, stamp),
        ).lastrowid)
        conn.executemany(
            "INSERT INTO chunks (document_id, ord, page, text) VALUES (?, ?, ?, ?)",
            [(document_id, ord_, (pages or [None] * len(chunks))[ord_], text)
             for ord_, text in enumerate(chunks)],
        )
    return document_id
