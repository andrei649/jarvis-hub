"""Cancellation seams after a Workspace transaction commits."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest
from fastapi import APIRouter

from agents.core.routers import (
    workspace_admin,
    workspace_approvals,
    workspace_auth,
    workspace_chat,
    workspace_reports,
)
from agents.core.workspace import (
    approvals,
    assistant,
    auth,
    effects_api,
    identity,
    llm,
    mailer,
    reports,
)
from agents.core.workspace import db as workspace_db
from agents.core.workspace.effects_api import EffectSpec, ValidatedRequest
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import DEFAULT_PASSWORD, db, make_app, seed_company, ws  # noqa: F401


async def _signed_in(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    origin = {"Origin": "http://testserver"}
    response = await client.post("/api/workspace/login", headers=origin,
                                 json={"email": email, "password": DEFAULT_PASSWORD})
    assert response.status_code == 200, response.text
    return {**origin, "X-CSRF-Token": response.json()["csrf_token"]}


def _ping() -> APIRouter:
    router = APIRouter()

    @router.get("/heartbeat")
    async def heartbeat():
        return {"ok": True}

    return router


async def test_invite_accept_write_lock_keeps_heartbeat_live_and_audits_once(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    with workspace_db.tx(seed):
        token, _ = auth.issue_invite(seed, company.member_a.id, purpose="reset",
                                     created_by=company.admin.id)
    seed.close()
    hashed = threading.Event()
    release = threading.Event()
    real_hash = identity.hash_password

    def hash_password(password):
        result = real_hash(password)
        hashed.set()
        return result

    monkeypatch.setattr(identity, "hash_password", hash_password)
    holder = workspace_db.connect()
    holder.execute("BEGIN IMMEDIATE")

    def unlock():
        release.wait(2)
        holder.execute("ROLLBACK")

    unlocker = threading.Thread(target=unlock)
    unlocker.start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_app(workspace_auth.router, _ping())),
            base_url="http://testserver",
        ) as client:
            started = time.monotonic()
            accept = asyncio.create_task(client.post("/api/workspace/invites/accept",
                headers={"Origin": "http://testserver"},
                json={"token": token, "password": "Noua-Parola-Sigura-7"}))
            assert await asyncio.to_thread(hashed.wait, 1.5)
            assert (await client.get("/heartbeat")).json() == {"ok": True}
            assert time.monotonic() - started < 1.0
            release.set()
            assert (await accept).status_code == 200
        check = db()
        try:
            actions = [row[0] for row in check.execute("SELECT action FROM audit")]
            assert actions.count("auth.password_changed") == 1
            assert check.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND "
                                 "revoked_at IS NULL", (company.member_a.id,)).fetchone()[0] == 1
        finally:
            check.close()
    finally:
        release.set()
        unlocker.join(timeout=3)
        holder.close()


async def test_failed_invite_attempt_is_recorded_off_loop(ws, monkeypatch):
    seed = db()
    seed_company(seed)
    seed.close()
    loop_thread = threading.get_ident()
    threads = []
    real_record = auth.record_attempt

    def record(*args, **kwargs):
        threads.append(threading.get_ident())
        return real_record(*args, **kwargs)

    monkeypatch.setattr(auth, "record_attempt", record)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(workspace_auth.router)),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/api/workspace/invites/accept",
            headers={"Origin": "http://testserver"},
            json={"token": "x" * 43, "password": "Noua-Parola-Sigura-7"})
    assert (response.status_code, response.json()["error"]) == (404, "invite_invalid")
    assert threads and all(thread != loop_thread for thread in threads)


async def test_cancelled_chat_prepare_settles_its_exact_turn(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    seed.close()
    entered = threading.Event()
    release = threading.Event()
    real_plan = assistant.plan_answer

    def plan(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(3)
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(assistant, "plan_answer", plan)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(workspace_auth.router, workspace_chat.router)),
        base_url="http://testserver",
    ) as client:
        headers = await _signed_in(client, company.member_a.email)
        made = await client.post("/api/workspace/conversations", headers=headers,
                                 json={"department_id": company.dept_a})
        conversation_id = made.json()["id"]
        ask = asyncio.create_task(client.post(
            f"/api/workspace/conversations/{conversation_id}/messages", headers=headers,
            json={"content": "First question"}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            ask.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await ask
            check = db()
            try:
                row = check.execute("SELECT id, status, error_code FROM messages WHERE "
                    "conversation_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
                    (conversation_id,)).fetchone()
                assert (row["status"], row["error_code"]) == ("error", "cancelled")
                assert row["id"] not in workspace_chat._LIVE_ANSWERS
            finally:
                check.close()
            again = await client.post(f"/api/workspace/conversations/{conversation_id}/messages",
                                      headers=headers, json={"content": "Second question"})
            assert again.status_code == 201, again.text
        finally:
            release.set()
            workspace_chat._LIVE_ANSWERS.clear()


async def test_cancelled_manual_queue_still_spawns_once_and_finishes(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    seed.close()
    entered = threading.Event()
    release = threading.Event()
    real_start = reports.start_manual_run
    real_spawn = reports.spawn_run
    spawned = []

    def start(*args, **kwargs):
        run_id = real_start(*args, **kwargs)
        entered.set()
        assert release.wait(3)
        return run_id

    def spawn(run_id):
        spawned.append(run_id)
        real_spawn(run_id)

    monkeypatch.setattr(reports, "start_manual_run", start)
    monkeypatch.setattr(reports, "spawn_run", spawn)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(workspace_auth.router, workspace_reports.router)),
        base_url="http://testserver",
    ) as client:
        headers = await _signed_in(client, company.member_a.email)
        made = await client.post("/api/workspace/reports", headers=headers,
            json={"department_id": company.dept_a, "name": "Queue probe",
                  "instructions": "Summarize", "schedule": {"kind": "manual"}})
        report_id = made.json()["id"]
        request = asyncio.create_task(client.post(f"/api/workspace/reports/{report_id}/run",
                                                   headers=headers))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            request.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert len(spawned) == 1
            if reports._TASKS:
                await asyncio.gather(*list(reports._TASKS), return_exceptions=True)
            check = db()
            try:
                row = check.execute("SELECT status FROM report_runs WHERE id = ?",
                                    (spawned[0],)).fetchone()
                assert row["status"] in {"failed", "succeeded"}
            finally:
                check.close()
        finally:
            release.set()


async def test_model_cancellation_write_does_not_stall_heartbeat(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    seed.close()
    started = asyncio.Event()

    async def wait_model(**kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(llm, "complete", wait_model)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(workspace_auth.router,
                                                   workspace_chat.router, _ping())),
        base_url="http://testserver",
    ) as client:
        headers = await _signed_in(client, company.member_a.email)
        made = await client.post("/api/workspace/conversations", headers=headers,
                                 json={"department_id": company.dept_a})
        conversation_id = made.json()["id"]
        request = asyncio.create_task(client.post(
            f"/api/workspace/conversations/{conversation_id}/messages", headers=headers,
            json={"content": "Cancel this answer"}))
        await asyncio.wait_for(started.wait(), 2)
        holder = workspace_db.connect()
        holder.execute("BEGIN IMMEDIATE")
        release = threading.Event()

        def unlock():
            release.wait(2)
            holder.execute("ROLLBACK")

        unlocker = threading.Thread(target=unlock)
        unlocker.start()
        try:
            began = time.monotonic()
            request.cancel()
            await asyncio.sleep(0)
            assert (await client.get("/heartbeat")).json() == {"ok": True}
            assert time.monotonic() - began < 1.0
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
        finally:
            release.set()
            unlocker.join(timeout=3)
            holder.close()
        check = db()
        try:
            row = check.execute("SELECT status, error_code FROM messages WHERE "
                                "conversation_id = ? AND role = 'assistant'",
                                (conversation_id,)).fetchone()
            assert (row["status"], row["error_code"]) == ("error", "cancelled")
        finally:
            check.close()


async def test_admin_smtp_configuration_is_read_in_worker(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    seed.close()
    loop_thread = threading.get_ident()
    threads = []
    real_configured = mailer.smtp_configured

    def configured(conn):
        threads.append(threading.get_ident())
        return real_configured(conn)

    monkeypatch.setattr(mailer, "smtp_configured", configured)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(workspace_auth.router, workspace_admin.router)),
        base_url="http://testserver",
    ) as client:
        headers = await _signed_in(client, company.admin.email)
        response = await client.post("/api/workspace/admin/users", headers=headers,
            json={"email": "new@acme.test", "name": "New User", "role": "member",
                  "department_ids": [company.dept_a], "send_email": True})
    assert response.status_code == 201, response.text
    assert response.json()["email_error"] == "smtp_not_configured"
    assert threads and all(thread != loop_thread for thread in threads)


async def test_cancelled_smtp_settings_waits_for_request_connection(ws, monkeypatch):
    seed = db()
    company = seed_company(seed)
    seed.close()
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    failures = []
    real_settings = mailer.smtp_settings

    def settings(conn):
        entered.set()
        release.wait(3)
        try:
            return real_settings(conn)
        except Exception as exc:
            failures.append(exc)
            raise
        finally:
            finished.set()

    monkeypatch.setattr(mailer, "smtp_settings", settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(workspace_auth.router,
                                                   workspace_approvals.router)),
        base_url="http://testserver",
    ) as client:
        headers = await _signed_in(client, company.admin.email)
        request = asyncio.create_task(client.put("/api/workspace/admin/smtp", headers=headers,
                                                 json={"host": ""}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            request.cancel()
            await asyncio.sleep(0.02)
            assert not request.done(), "request dependency may close its connection too early"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert await asyncio.to_thread(finished.wait, 2)
            assert failures == []
        finally:
            release.set()


@pytest.mark.parametrize("immediate", [True, False])
async def test_cancelled_approval_commit_finishes_effect_once(ws, monkeypatch, immediate):
    conn = db()
    company = seed_company(conn)
    kind = f"test.nws13.{immediate}"
    executions = []

    def validate(conn, requester, payload):
        return ValidatedRequest(department_id=company.dept_a, summary="Probe",
                                payload={"department_id": company.dept_a})

    async def execute(approval, requester, decider):
        executions.append(approval["id"])
        return {"done": True}

    monkeypatch.setitem(effects_api._REGISTRY, kind,
        EffectSpec(kind=kind, validate=validate, execute=execute,
                   decider_rule="admin" if immediate else "department"))
    entered = threading.Event()
    release = threading.Event()
    if immediate:
        real_create = approvals.create_request

        def create(*args, **kwargs):
            result = real_create(*args, **kwargs)
            entered.set()
            assert release.wait(3)
            return result

        monkeypatch.setattr(approvals, "create_request", create)
        task = asyncio.create_task(approvals.request(
            conn, company.admin, kind, {"department_id": company.dept_a}))
    else:
        approval_id, _ = approvals.create_request(
            conn, company.member_a, kind, {"department_id": company.dept_a})
        real_record = approvals.audit.record

        def record(*args, **kwargs):
            result = real_record(*args, **kwargs)
            if kwargs.get("action") == "approval.approved":
                entered.set()
                assert release.wait(3)
            return result

        monkeypatch.setattr(approvals.audit, "record", record)
        task = asyncio.create_task(approvals.decide(
            conn, company.approver_a, approval_id, decision="approve", note=""))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = conn.execute("SELECT id, status FROM approvals WHERE kind = ? ORDER BY id DESC",
                           (kind,)).fetchone()
        assert row["status"] == "approved"
        assert executions == [row["id"]]
        if not immediate:
            with pytest.raises(WorkspaceError) as caught:
                await approvals.decide(conn, company.approver_a, row["id"],
                                       decision="approve", note="")
            assert caught.value.code == "already_decided"
            assert executions == [row["id"]]
    finally:
        release.set()
        conn.close()


async def test_cancelled_approval_waits_for_effect_and_records_actual_outcome(ws, monkeypatch):
    conn = db()
    company = seed_company(conn)
    kind = "test.nws13.wait_for_effect"
    started = asyncio.Event()
    release = asyncio.Event()
    executions = []

    def validate(conn, requester, payload):
        return ValidatedRequest(department_id=company.dept_a, summary="Wait probe", payload={})

    async def execute(approval, requester, decider):
        executions.append(approval["id"])
        started.set()
        await release.wait()
        return {"sent": True}

    monkeypatch.setitem(effects_api._REGISTRY, kind,
        EffectSpec(kind=kind, validate=validate, execute=execute, decider_rule="admin"))
    task = asyncio.create_task(approvals.request(conn, company.admin, kind, {}))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "accepted effect was cancelled before its outcome was recorded"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = conn.execute("SELECT id, status, result_json FROM approvals WHERE kind = ?",
                           (kind,)).fetchone()
        assert row["status"] == "approved" and '"sent": true' in row["result_json"]
        assert executions == [row["id"]]
        assert conn.execute("SELECT COUNT(*) FROM audit WHERE action = 'approval.executed' "
                            "AND target_id = ?", (str(row["id"]),)).fetchone()[0] == 1
    finally:
        release.set()
        conn.close()
