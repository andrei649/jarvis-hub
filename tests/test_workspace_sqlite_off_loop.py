"""NWS-13: a real SQLite writer must not freeze other async Workspace work."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest
from fastapi import APIRouter

from agents.core.routers import workspace_auth, workspace_chat
from agents.core.workspace import auth, retrieval
from agents.core.workspace import db as workspace_db
from tests.support.workspace_fixtures import (  # noqa: F401
    DEFAULT_PASSWORD,
    db,
    make_app,
    seed_company,
    seed_org,
    ws,
)
from tests.test_workspace_assistant_helpers import seed_doc


async def test_real_write_lock_does_not_block_unrelated_request(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    seed.close()
    entered = threading.Event()
    release = threading.Event()
    real_reserve = auth.reserve_login_attempt

    def reserve(*args, **kwargs):
        entered.set()
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(auth, "reserve_login_attempt", reserve)
    heartbeat = APIRouter()

    @heartbeat.get("/heartbeat")
    async def ping():
        return {"ok": True}

    holder = workspace_db.connect()
    holder.execute("BEGIN IMMEDIATE")

    def unlock():
        release.wait(timeout=2.0)
        holder.execute("ROLLBACK")

    unlocker = threading.Thread(target=unlock)
    unlocker.start()
    try:
        app = make_app(workspace_auth.router, heartbeat)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            started = time.monotonic()
            login = asyncio.create_task(client.post("/api/workspace/login",
                headers={"Origin": "http://testserver"},
                json={"email": company.member_a.email, "password": "wrong-password"}))
            assert await asyncio.to_thread(entered.wait, 1.5)
            pinged = await client.get("/heartbeat")
            assert pinged.json() == {"ok": True}
            assert time.monotonic() - started < 1.0, "SQLite's busy wait stalled the event loop"
            release.set()
            assert (await login).status_code == 401
    finally:
        release.set()
        unlocker.join(timeout=2)
        holder.close()


async def test_cancelled_offload_drains_worker_before_connection_closes(ws):
    from agents.core.workspace.http import offload

    conn = workspace_db.connect()
    seed_org(conn)
    holder = workspace_db.connect()
    holder.execute("BEGIN IMMEDIATE")
    started = threading.Event()

    def write():
        started.set()
        with workspace_db.tx(conn):
            conn.execute("UPDATE org SET name = 'after cancellation'")

    task = asyncio.create_task(offload(write))
    try:
        assert await asyncio.to_thread(started.wait, 1.5)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done(), "the request connection could close while its worker uses it"
        holder.execute("ROLLBACK")
        with pytest.raises(asyncio.CancelledError):
            await task
        conn.close()
        check = workspace_db.connect()
        try:
            assert check.execute("SELECT name FROM org").fetchone()[0] == "after cancellation"
        finally:
            check.close()
    finally:
        if holder.in_transaction:
            holder.execute("ROLLBACK")
        holder.close()
        if not task.done():
            await task
        conn.close()


async def test_offloaded_transaction_exception_rolls_back(ws):
    from agents.core.workspace.http import offload

    conn = workspace_db.connect()
    seed_org(conn)
    before = conn.execute("SELECT name FROM org").fetchone()[0]

    def fail():
        with workspace_db.tx(conn):
            conn.execute("UPDATE org SET name = 'must rollback'")
            raise ValueError("sentinel")

    try:
        with pytest.raises(ValueError, match="sentinel"):
            await offload(fail)
        assert not conn.in_transaction
        assert conn.execute("SELECT name FROM org").fetchone()[0] == before
    finally:
        conn.close()


async def test_chat_fts_runs_in_worker_and_preserves_citations(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    document_id = seed_doc(seed, department_id=company.dept_a, title="Concediu",
                           text="Concediul anual este de 21 de zile lucrătoare.")
    seed.close()
    loop_thread = threading.get_ident()
    search_threads = []
    real_search = retrieval.search

    def search(*args, **kwargs):
        search_threads.append(threading.get_ident())
        return real_search(*args, **kwargs)

    monkeypatch.setattr(retrieval, "search", search)
    transport = httpx.ASGITransport(app=make_app(workspace_auth.router, workspace_chat.router))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        origin = {"Origin": "http://testserver"}
        signed_in = await client.post("/api/workspace/login", headers=origin,
                                      json={"email": company.member_a.email,
                                            "password": DEFAULT_PASSWORD})
        assert signed_in.status_code == 200, signed_in.text
        headers = {**origin, "X-CSRF-Token": signed_in.json()["csrf_token"]}
        conversation = await client.post("/api/workspace/conversations", headers=headers,
                                         json={"department_id": company.dept_a})
        assert conversation.status_code == 201, conversation.text
        answer = await client.post(
            f"/api/workspace/conversations/{conversation.json()['id']}/messages",
            headers=headers, json={"content": "Câte zile de concediu anual avem?"})
        assert answer.status_code == 201, answer.text
        citations = answer.json()["assistant_message"]["citations"]
        assert any(citation["document_id"] == document_id for citation in citations)
    assert search_threads and all(thread != loop_thread for thread in search_threads)
