"""The workspace scheduler tick (spec §9): scheduled reports, sweeps and housekeeping.

Every test drives :meth:`WorkspaceScheduler.tick` with an explicit ``now`` (and a frozen
``db.now``), never by sleeping: due reports are claimed exactly once even by racing
ticks, schedules advance in the report's zone, stale approvals/runs/messages are
failed, old rows are deleted, and one failing step never stops the others.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import approvals, config, db, reports, scheduler
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    freeze_clock,
    ws,
)
from tests.test_workspace_reports_support import (  # noqa: F401  (fixtures)
    cast,
    drain,
    seed_document,
)

BUCHAREST = ZoneInfo("Europe/Bucharest")
START = datetime(2026, 10, 17, 13, 0, tzinfo=BUCHAREST).timestamp()
DUE = datetime(2026, 10, 18, 8, 0, tzinfo=BUCHAREST).timestamp()
DAY = 86400


@pytest.fixture
def clock(ws, monkeypatch):
    return freeze_clock(monkeypatch, START)


@pytest.fixture
def conn(clock):
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def spawned(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(reports, "spawn_run", calls.append)
    return calls


def _daily(conn, cast, **over):
    body = {"department_id": cast.dept_a, "name": "Zilnic",
            "instructions": "Rezumă vânzările din Nord.",
            "schedule": {"kind": "daily", "time": "08:00"}, **over}
    return reports.create_report(conn, cast.member_a, body)


def _runs(conn):
    return conn.execute("SELECT * FROM report_runs ORDER BY id").fetchall()


def _next_run(conn, report_id):
    return conn.execute("SELECT next_run_at FROM reports WHERE id = ?", (report_id,)).fetchone()[0]


async def _tick(at, clock=None):
    if clock is not None:
        clock.current = at
    return await scheduler.WorkspaceScheduler().tick(now=at)


# ── scheduled reports ────────────────────────────────────────────────────────────────

async def test_a_due_report_is_started_once_and_rescheduled(conn, cast, clock, spawned):
    report_id = _daily(conn, cast)
    assert _next_run(conn, report_id) == DUE
    early = await _tick(DUE - 1, clock)
    assert early["runs_started"] == [] and early["errors"] == []
    summary = await _tick(DUE, clock)
    [run] = _runs(conn)
    assert summary["runs_started"] == [run["id"]] and spawned == [run["id"]]
    assert (run["trigger"], run["triggered_by"], run["status"]) == ("schedule", None, "queued")
    assert _next_run(conn, report_id) == DUE + DAY
    assert (await _tick(DUE, clock))["runs_started"] == []
    assert len(_runs(conn)) == 1
    started = conn.execute("SELECT actor_user_id, actor_email FROM audit "
                           "WHERE action = 'report.run_started'").fetchone()
    assert tuple(started) == (None, "scheduler")


async def test_racing_ticks_claim_a_due_report_once(conn, cast, clock, spawned):
    _daily(conn, cast)
    _daily(conn, cast, name="Al doilea")
    clock.current = DUE
    summaries = await asyncio.gather(*(scheduler.WorkspaceScheduler().tick(now=DUE)
                                       for _ in range(4)))
    started = [run_id for summary in summaries for run_id in summary["runs_started"]]
    assert len(started) == 2 and len(set(started)) == 2
    assert len(_runs(conn)) == 2 and sorted(spawned) == sorted(started)


async def test_a_missed_schedule_runs_once_then_continues_from_now(conn, cast, clock, spawned):
    report_id = _daily(conn, cast)
    later = DUE + 3 * DAY + 3600
    await _tick(later, clock)
    assert len(_runs(conn)) == 1
    assert _next_run(conn, report_id) == DUE + 4 * DAY


async def test_weekly_reports_skip_to_their_weekday(conn, cast, clock, spawned):
    report_id = _daily(conn, cast, schedule={"kind": "weekly", "time": "08:00", "weekday": 0})
    monday = datetime(2026, 10, 19, 8, 0, tzinfo=BUCHAREST).timestamp()
    assert _next_run(conn, report_id) == monday
    await _tick(monday, clock)
    assert _next_run(conn, report_id) == datetime(2026, 10, 26, 8, 0, tzinfo=BUCHAREST).timestamp()


async def test_manual_inactive_and_archived_reports_are_never_started(conn, cast, clock, spawned):
    manual = _daily(conn, cast, schedule={"kind": "manual"})
    archived = _daily(conn, cast, name="Arhivat")
    paused = _daily(conn, cast, name="Oprit")
    conn.execute("UPDATE reports SET next_run_at = ? WHERE id = ?", (DUE, manual))
    conn.execute("UPDATE reports SET active = 0 WHERE id = ?", (paused,))
    conn.execute("UPDATE departments SET archived = 1 WHERE id = ?", (cast.dept_a,))
    assert (await _tick(DUE + 60, clock))["runs_started"] == []
    conn.execute("UPDATE departments SET archived = 0 WHERE id = ?", (cast.dept_a,))
    summary = await _tick(DUE + 60, clock)
    assert [r["report_id"] for r in _runs(conn)] == [archived] and len(summary["runs_started"]) == 1


async def test_an_unloadable_zone_fails_the_run_and_retries_a_day_later(conn, cast, clock, spawned):
    report_id = _daily(conn, cast)
    conn.execute("UPDATE reports SET timezone = 'Nowhere/Atlantis' WHERE id = ?", (report_id,))
    summary = await _tick(DUE, clock)
    [run] = _runs(conn)
    assert summary["runs_started"] == [] and spawned == []
    assert (run["status"], run["error_code"]) == ("failed", "timezone_unavailable")
    assert _next_run(conn, report_id) == DUE + DAY
    kinds = [r[0] for r in conn.execute("SELECT kind FROM notifications WHERE user_id = ?",
                                        (cast.member_a.id,))]
    assert kinds == ["report.run_failed"]


async def test_a_scheduled_run_executes_on_the_loop(conn, cast, clock):
    seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id, title="Nord",
                  chunks=["Vânzările din Nord au crescut."])
    _daily(conn, cast)
    await _tick(DUE, clock)
    await drain()
    [run] = _runs(conn)
    assert run["status"] == "succeeded" and run["content_md"].endswith("[1]")


# ── sweeps ───────────────────────────────────────────────────────────────────────────

async def test_stale_approvals_runs_and_messages_are_closed(conn, cast, clock, spawned):
    report_id = _daily(conn, cast, schedule={"kind": "manual"})
    with db.tx(conn):
        stuck_run = reports.create_run(conn, report_id, trigger="manual", triggered_by=None)
        conn.execute("UPDATE report_runs SET status = 'running', started_at = ? WHERE id = ?",
                     (START, stuck_run))
        conversation = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 't', ?, ?)", (cast.member_a.id, cast.dept_a, START, START)).lastrowid
        old_message = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, status, created_at) "
            "VALUES (?, 'assistant', '', 'pending', ?)", (conversation, START)).lastrowid
        new_message = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, status, created_at) "
            "VALUES (?, 'assistant', '', 'pending', ?)", (conversation, START + 600)).lastrowid
        for status, decided_at in (("pending", None), ("executing", START)):
            conn.execute(
                "INSERT INTO approvals (kind, department_id, requester_id, summary, payload_json, "
                "status, decided_by, decided_at, created_at, expires_at) "
                "VALUES ('report.share_company', ?, ?, 's', '{}', ?, ?, ?, ?, ?)",
                (cast.dept_a, cast.member_a.id, status, cast.admin.id if decided_at else None,
                 decided_at, START, START + approvals.APPROVAL_TTL_SECONDS))
    at = START + 900
    summary = await _tick(at, clock)
    assert (summary["runs_interrupted"], summary["messages_interrupted"]) == (1, 1)
    assert (summary["approvals_interrupted"], summary["approvals_expired"]) == (1, 0)
    statuses = dict(conn.execute("SELECT id, status FROM messages"))
    assert statuses == {old_message: "error", new_message: "pending"}
    assert conn.execute("SELECT error_code FROM messages WHERE id = ?",
                        (old_message,)).fetchone()[0] == "interrupted"
    assert conn.execute("SELECT error_code FROM report_runs").fetchone()[0] == "interrupted"
    expired = await _tick(START + approvals.APPROVAL_TTL_SECONDS, clock)
    assert expired["approvals_expired"] == 1
    assert sorted(r[0] for r in conn.execute("SELECT status FROM approvals")) == ["expired",
                                                                                  "failed"]


async def test_housekeeping_deletes_only_what_is_past_retention(conn, cast, clock, spawned):
    now = START + 100 * DAY
    idle = config.session_idle_seconds()
    with db.tx(conn):
        conn.executemany("INSERT INTO login_attempts (ip, email, ok, kind, ts) "
                         "VALUES ('1.1.1.1', 'a@b.ro', 0, 'login', ?)",
                         [(now - DAY,), (now - DAY + 1,)])
        conn.executemany(
            "INSERT INTO invites (token_hash, user_id, purpose, created_at, expires_at) "
            "VALUES (?, ?, 'invite', ?, ?)",
            [("old", cast.member_a.id, now - 20 * DAY, now - 7 * DAY),
             ("recent", cast.member_a.id, now - 9 * DAY, now - 7 * DAY + 1)])
        sessions = [("revoked-old", now - 6 * DAY, now + DAY, now - 7 * DAY),
                    ("revoked-new", now - 6 * DAY, now + DAY, now - 6 * DAY),
                    ("expired-old", now - 7 * DAY - idle, now - 7 * DAY, None),
                    ("idle-old", now - 7 * DAY - idle, now + DAY, None),
                    ("live", now - 60, now + DAY, None)]
        conn.executemany(
            "INSERT INTO sessions (id_hash, user_id, csrf_token, created_at, last_seen_at, "
            "expires_at, revoked_at) VALUES (?, ?, 'c', ?, ?, ?, ?)",
            [(name, cast.member_a.id, now - 30 * DAY, seen, expires, revoked)
             for name, seen, expires, revoked in sessions])
        conn.executemany(
            "INSERT INTO notifications (user_id, kind, title, created_at, read_at) "
            "VALUES (?, 'k', ?, ?, ?)",
            [(cast.member_a.id, "read-old", now - 200 * DAY, now - 90 * DAY),
             (cast.member_a.id, "read-new", now - 200 * DAY, now - 89 * DAY),
             (cast.member_a.id, "unread-old", now - 200 * DAY, None)])
    summary = await _tick(now, clock)
    assert summary["deleted"] == {"login_attempts": 1, "invites": 1, "sessions": 3,
                                  "notifications": 1}
    assert [r[0] for r in conn.execute("SELECT token_hash FROM invites")] == ["recent"]
    assert sorted(r[0] for r in conn.execute("SELECT id_hash FROM sessions")) == ["live",
                                                                                 "revoked-new"]
    assert sorted(r[0] for r in conn.execute("SELECT title FROM notifications")) == [
        "read-new", "unread-old"]


async def test_one_failing_step_does_not_stop_the_others(conn, cast, clock, spawned, monkeypatch,
                                                         caplog):
    def broken(conn_, now):
        raise RuntimeError("sweep bug")

    monkeypatch.setattr(approvals, "expire_due", broken)
    with caplog.at_level(logging.ERROR, logger="nerva.workspace.scheduler"):
        summary = await _tick(START, clock)
    assert summary["errors"] == ["approvals_expired"] and "deleted" in summary
    assert "approvals_expired" not in summary
    assert "workspace scheduler step approvals_expired failed" in caplog.text


async def test_a_disabled_workspace_is_never_touched(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    assert await scheduler.WorkspaceScheduler().tick(now=START) == {"skipped": "workspace_disabled"}
    assert not db.db_path().exists()


# ── the loop ─────────────────────────────────────────────────────────────────────────

async def test_start_ticks_until_stopped_and_survives_a_bad_tick(ws, monkeypatch, caplog):
    loop = scheduler.WorkspaceScheduler(interval_seconds=0)
    ticks: list[int] = []
    enough = asyncio.Event()

    async def tick(now=None):
        ticks.append(len(ticks))
        if len(ticks) == 1:
            raise RuntimeError("first tick fails")
        if len(ticks) >= 3:
            enough.set()
        return {}

    monkeypatch.setattr(loop, "tick", tick)
    with caplog.at_level(logging.ERROR, logger="nerva.workspace.scheduler"):
        loop.start()
        loop.start()
        assert loop.running
        await asyncio.wait_for(enough.wait(), timeout=5)
        await loop.stop()
    assert not loop.running and len(ticks) >= 3
    assert "workspace scheduler tick failed" in caplog.text
    await loop.stop()


async def test_background_start_respects_the_flag_and_stop_interrupts_runs(conn, cast, clock,
                                                                           monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_SCHEDULER", "0")
    scheduler.start_background()
    assert scheduler._scheduler is None
    monkeypatch.setenv("NERVA_WORKSPACE_SCHEDULER", "1")
    monkeypatch.setattr(scheduler.WorkspaceScheduler, "tick", lambda self, now=None: asyncio.sleep(0))
    scheduler.start_background()
    assert scheduler._scheduler is not None and scheduler._scheduler.running
    report_id = _daily(conn, cast, schedule={"kind": "manual"})
    run_id = reports.start_manual_run(conn, cast.member_a, report_id)
    blocker = asyncio.Event()

    async def wait_forever(run_id_):
        await blocker.wait()

    monkeypatch.setattr(reports, "_execute", wait_forever)
    reports.spawn_run(run_id)
    await asyncio.sleep(0)
    await scheduler.stop_background()
    assert scheduler._scheduler is None and not reports._TASKS
    run = conn.execute("SELECT status, error_code FROM report_runs WHERE id = ?", (run_id,)).fetchone()
    assert tuple(run) == ("failed", "interrupted")
    await scheduler.stop_background()
    assert json.loads(conn.execute("SELECT details_json FROM audit WHERE action = "
                                   "'report.run_failed'").fetchone()[0])["error_code"] == "interrupted"
