"""The scheduler while the audit key is not the trail's (review OPS2-08, T-GAP-1).

Before the fix, a hub started with another ``JARVIS_AUDIT_KEY`` (or without its key file)
logged two full tracebacks every 30 s — ``runs_started`` and ``approvals_expired`` each
ending in ``AuditKeyMismatch`` from ``audit.record`` — for as long as the key stayed wrong.
Now the steps that sign audit rows pause: no run is claimed, no approval expires or fails,
nothing is written; the pause is one WARNING when it begins and one INFO line when the
service's key is back, and the first tick after that catches up. The steps that sign
nothing (pending messages, interrupted documents, housekeeping) keep running.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import approvals, audit, db, reports, scheduler
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    freeze_clock,
    ws,
)
from tests.test_workspace_reports_support import cast  # noqa: F401  (fixture)

BUCHAREST = ZoneInfo("Europe/Bucharest")
START = datetime(2026, 10, 17, 13, 0, tzinfo=BUCHAREST).timestamp()
DUE = datetime(2026, 10, 18, 8, 0, tzinfo=BUCHAREST).timestamp()
EXPIRED = START + approvals.APPROVAL_TTL_SECONDS
OTHER_KEY = "b" * 64
LOGGERS = ("nerva.workspace.scheduler", "nerva.workspace.audit", "nerva.workspace.reports",
           "nerva.workspace.approvals")


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


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG)
    for name in LOGGERS:
        caplog.set_level(logging.DEBUG, logger=name)
    return caplog


def _seed(conn, cast) -> dict:
    """A due daily report, a pending approval past its TTL, a stale executing one, a stuck
    run and a pending assistant message from long ago."""
    report_id = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Zilnic", "instructions": "Rezumă vânzările.",
        "schedule": {"kind": "daily", "time": "08:00"}})
    manual = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Manual", "instructions": "Rezumă.",
        "schedule": {"kind": "manual"}})
    with db.tx(conn):
        stuck = reports.create_run(conn, manual, trigger="manual", triggered_by=None)
        conn.execute("UPDATE report_runs SET status = 'running', started_at = ? WHERE id = ?",
                     (START, stuck))
        conversation = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 't', ?, ?)", (cast.member_a.id, cast.dept_a, START, START)).lastrowid
        message = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, status, created_at) "
            "VALUES (?, 'assistant', '', 'pending', ?)", (conversation, START)).lastrowid
        for status, decided_at in (("pending", None), ("executing", START)):
            conn.execute(
                "INSERT INTO approvals (kind, department_id, requester_id, summary, payload_json, "
                "status, decided_by, decided_at, created_at, expires_at) "
                "VALUES ('report.share_company', ?, ?, 's', '{}', ?, ?, ?, ?, ?)",
                (cast.dept_a, cast.member_a.id, status, cast.admin.id if decided_at else None,
                 decided_at, START, EXPIRED))
    return {"report": report_id, "stuck": stuck, "message": message}


def _state(conn) -> dict:
    return {
        "audit": conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
        "runs": [tuple(row) for row in conn.execute(
            "SELECT id, status FROM report_runs ORDER BY id")],
        "approvals": [row[0] for row in conn.execute("SELECT status FROM approvals ORDER BY id")],
        "next_run": [row[0] for row in conn.execute("SELECT next_run_at FROM reports ORDER BY id")],
        "notifications": conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
    }


def _break_key(ws, monkeypatch, how: str) -> None:
    key_file = ws.key_dir / audit.KEY_FILE
    if how == "mismatch":
        monkeypatch.setenv(audit.ENV_AUDIT_KEY, OTHER_KEY)   # e.g. a rebuild with fresh keys
    elif how == "missing":
        key_file.rename(key_file.with_name("moved-away.key"))
    else:   # unreadable: an empty key file
        key_file.rename(key_file.with_name("moved-away.key"))
        key_file.write_bytes(b"")


def _restore_key(ws, monkeypatch) -> None:
    monkeypatch.delenv(audit.ENV_AUDIT_KEY, raising=False)
    moved = ws.key_dir / "moved-away.key"
    if moved.exists():
        moved.replace(ws.key_dir / audit.KEY_FILE)


def _scheduler_records(logs, level: int) -> list[logging.LogRecord]:
    return [record for record in logs.records
            if record.name == "nerva.workspace.scheduler" and record.levelno == level]


def _assert_no_traceback(logs) -> None:
    assert [record for record in logs.records if record.exc_info] == []
    assert "Traceback" not in logs.text
    assert [r.getMessage() for r in logs.records if r.levelno >= logging.ERROR] == []


@pytest.mark.parametrize("how", ["mismatch", "missing", "unreadable"])
async def test_a_wrong_key_pauses_the_audited_steps_quietly_and_they_catch_up(
        conn, cast, clock, spawned, ws, monkeypatch, logs, how):
    seeded = _seed(conn, cast)
    _break_key(ws, monkeypatch, how)
    before = _state(conn)
    assert audit.key_check(conn) == how
    hub = scheduler.WorkspaceScheduler()
    logs.clear()

    summaries = []
    for at in (EXPIRED, EXPIRED + 30, EXPIRED + 60):   # three ticks, everything due
        clock.current = at
        summaries.append(await hub.tick(now=at))

    assert _state(conn) == before, "nothing is claimed, expired, failed or audited"
    assert spawned == []
    _assert_no_traceback(logs)
    for summary in summaries:
        assert summary["paused"] == list(scheduler.AUDITED_STEPS)
        assert summary["errors"] == [] and summary["audit_key"] == how
        assert all(step not in summary for step in scheduler.AUDITED_STEPS)
        assert "deleted" in summary
    assert summaries[0]["messages_interrupted"] == 1, "steps that sign nothing still run"
    assert conn.execute("SELECT status FROM messages WHERE id = ?",
                        (seeded["message"],)).fetchone()[0] == "error"
    [warning] = _scheduler_records(logs, logging.WARNING)
    text = warning.getMessage()
    assert "paused" in text and "nerva-run -m agents.core.workspace check" in text
    assert OTHER_KEY not in logs.text, "the key itself is never logged"
    assert _scheduler_records(logs, logging.INFO) == []

    _restore_key(ws, monkeypatch)                       # the remedy: the service's key is back
    logs.clear()
    clock.current = EXPIRED + 90
    caught_up = await hub.tick(now=EXPIRED + 90)
    assert caught_up["paused"] == [] and caught_up["errors"] == []
    assert caught_up["audit_key"] == "ok"
    [run_id] = caught_up["runs_started"]
    assert spawned == [run_id]
    assert (caught_up["approvals_expired"], caught_up["approvals_interrupted"]) == (1, 1)
    assert caught_up["runs_interrupted"] == 1
    assert sorted(_state(conn)["approvals"]) == ["expired", "failed"]
    [resumed] = _scheduler_records(logs, logging.INFO)
    assert "resumed" in resumed.getMessage()
    assert _scheduler_records(logs, logging.WARNING) == []
    assert audit.verify_chain(conn)["ok"] is True

    logs.clear()
    clock.current = EXPIRED + 120
    await hub.tick(now=EXPIRED + 120)
    assert _scheduler_records(logs, logging.INFO) == []
    assert _scheduler_records(logs, logging.WARNING) == []


async def test_each_change_of_the_key_state_is_logged_once(conn, cast, clock, spawned, ws,
                                                          monkeypatch, logs):
    _seed(conn, cast)
    hub = scheduler.WorkspaceScheduler()
    _break_key(ws, monkeypatch, "mismatch")
    logs.clear()
    await hub.tick(now=START)
    await hub.tick(now=START + 30)
    _restore_key(ws, monkeypatch)
    _break_key(ws, monkeypatch, "missing")               # another state: logged again
    await hub.tick(now=START + 60)
    await hub.tick(now=START + 90)
    warnings = [record.getMessage() for record in _scheduler_records(logs, logging.WARNING)]
    assert len(warnings) == 2
    assert "not the one the audit trail was written with" in warnings[0]
    assert "no audit key" in warnings[1]
    _assert_no_traceback(logs)


async def test_a_key_swapped_between_the_check_and_a_step_pauses_the_rest_of_the_tick(
        conn, cast, clock, spawned, ws, monkeypatch, logs):
    """The pre-check said ok, then a step met the key error: no traceback, nothing written."""
    _seed(conn, cast)
    before = _state(conn)
    monkeypatch.setenv(audit.ENV_AUDIT_KEY, OTHER_KEY)
    monkeypatch.setattr(audit, "key_check", lambda conn_: "ok")
    logs.clear()
    clock.current = EXPIRED
    summary = await scheduler.WorkspaceScheduler().tick(now=EXPIRED)
    assert summary["errors"] == [] and summary["audit_key"] == "mismatch"
    assert summary["paused"] == list(scheduler.AUDITED_STEPS)
    assert _state(conn) == before and spawned == []
    assert [record for record in logs.records if record.exc_info] == []
    [warning] = _scheduler_records(logs, logging.WARNING)
    assert "paused" in warning.getMessage()
    assert _scheduler_records(logs, logging.ERROR) == []


async def test_an_empty_trail_is_never_paused(ws, clock, spawned, logs):
    """A fresh install has no rows to protect: the first audited write makes the key."""
    connection = db.connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0
    finally:
        connection.close()
    summary = await scheduler.WorkspaceScheduler().tick(now=START)
    assert summary["paused"] == [] and summary["audit_key"] == "ok"
    assert summary["errors"] == []
    assert _scheduler_records(logs, logging.WARNING) == []
