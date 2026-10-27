"""NWS-13: SQLite write transactions in async handlers run off the event loop.

A write route waits up to the 5 s busy timeout for the database lock. Run inline in an
``async def`` handler, that wait froze every other request of the process; these tests hold
the write lock from outside and prove that an unrelated request still answers at once, and
that the blocked write completes as soon as the lock is released.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

import httpx
import pytest
from fastapi import FastAPI

from agents.core.routers import workspace_auth, workspace_chat, workspace_documents
from agents.core.workspace import db as workspace_db
from agents.core.workspace import http as workspace_http  # noqa
from tests.fixtures.workspace.doc_helpers import docs_client, upload_url
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    db,
    login,
    make_app,
    seed_company,
    ws,
)


@pytest.fixture
def env(ws):
    conn = db()
    company = seed_company(conn)
    client = docs_client()
    yield conn, company, client
    conn.close()


def _holder() -> sqlite3.Connection:
    """A second connection that owns the write lock until it commits."""
    other = workspace_db.connect()
    other.execute("BEGIN IMMEDIATE")
    return other


def _app() -> FastAPI:
    app = make_app(workspace_auth.router, workspace_chat.router, workspace_documents.router)

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    return app


async def test_offload_runs_the_work_in_a_worker_thread():
    import threading
    main = threading.get_ident()
    assert await workspace_http.offload(threading.get_ident) != main


async def test_a_held_write_lock_does_not_block_an_unrelated_request(env):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    holder = _holder()
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                 cookies={c.name: c.value for c in client.cookies.jar},
                                 headers={"X-CSRF-Token": csrf,
                                          "Origin": "http://testserver"}) as http:
        blocked = asyncio.ensure_future(http.post(
            "/api/workspace/conversations", json={"department_id": company.dept_a}))
        await asyncio.sleep(0.3)  # the write is now waiting for the lock in its thread
        assert not blocked.done()
        started = time.monotonic()
        pings = [await http.get("/ping") for _ in range(20)]
        elapsed = time.monotonic() - started
        assert all(response.status_code == 200 for response in pings)
        assert elapsed < 1.0  # inline, the loop would have stalled for the 5 s busy timeout
        assert not blocked.done()
        holder.execute("COMMIT")
        holder.close()
        response = await asyncio.wait_for(blocked, 10)
    assert response.status_code == 201
    assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1


async def test_a_held_write_lock_does_not_block_an_upload_of_another_user(env):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    holder = _holder()
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                 cookies={c.name: c.value for c in client.cookies.jar},
                                 headers={"X-CSRF-Token": csrf,
                                          "Origin": "http://testserver"}) as http:
        blocked = asyncio.ensure_future(http.post(
            upload_url(company.dept_a, "blocat.txt"), content=b"Text de test " * 20))
        await asyncio.sleep(0.3)
        started = time.monotonic()
        assert (await http.get("/ping")).status_code == 200
        assert time.monotonic() - started < 1.0
        holder.execute("COMMIT")
        holder.close()
        response = await asyncio.wait_for(blocked, 10)
    assert response.status_code == 201
