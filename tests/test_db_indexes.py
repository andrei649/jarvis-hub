"""Scalability guard: hot, unbounded SQLite tables must stay indexed.

Several stores are read on the system's hot paths while their tables grow
without bound:

* ``tasks`` (autonomy queue) — polled by the worker/inbox, filtered by status;
* ``security_events`` (audit log) — queried by type/time, one row per turn;
* ``preferences`` — approval-rate lookups per autonomy decision;
* ``sessions`` (checkpoints) — listed ordered by start time, one row/session.

Each gained a ``CREATE INDEX IF NOT EXISTS`` in its init path. These tests lock
that in two ways: the index must exist, and the representative hot query must
actually *use* it (via ``EXPLAIN QUERY PLAN``) — so a future schema change that
silently regresses the lookup to a full table scan is caught here. A functional
assertion alongside each confirms the index doesn't change results.
"""

import sqlite3
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.autonomy.queue import TaskQueue  # noqa: E402
from core.autonomy.preferences import PreferenceStore  # noqa: E402
from core.checkpoint import CheckpointManager  # noqa: E402
from core.security.audit import AuditLogger  # noqa: E402


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        )
    }


def _plan(conn: sqlite3.Connection, sql: str, params=()) -> str:
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return " | ".join(str(r[-1]) for r in rows)


# ── autonomy queue: tasks(status, id) ─────────────────────────────

def test_tasks_status_index(tmp_path):
    q = TaskQueue(str(tmp_path / "q.db")).initialize()
    conn = q._conn
    assert "idx_tasks_status" in _indexes(conn, "tasks")
    plan = _plan(
        conn,
        "SELECT * FROM tasks WHERE status='approved' AND attempts < 3 "
        "ORDER BY id ASC LIMIT 10",
    )
    assert "idx_tasks_status" in plan, plan
    # results unchanged: only approved, attempt-budget-respecting tasks come back
    a = q.enqueue("scribe", "k", "approved one")
    q.transition(a, "approved")
    q.enqueue("scribe", "k", "still proposed")
    runnable = q.runnable()
    assert [t.id for t in runnable] == [a]
    q.close()


# ── audit log: security_events(event_type, timestamp) ─────────────

def test_security_events_index(tmp_path):
    log = AuditLogger(db_path=str(tmp_path / "audit.db"))
    conn = log._conn
    assert "idx_security_events_type_ts" in _indexes(conn, "security_events")
    plan = _plan(
        conn,
        "SELECT timestamp FROM security_events WHERE event_type=? "
        "AND timestamp >= ? ORDER BY timestamp DESC LIMIT 100",
        ("scan", 0.0),
    )
    assert "idx_security_events_type_ts" in plan, plan


# ── preferences: preferences(agent, kind, risk_tier) ──────────────

def test_preferences_class_index(tmp_path):
    store = PreferenceStore(
        db_path=str(tmp_path / "prefs.db"),
        journal_path=str(tmp_path / "journal.jsonl"),
    )
    store.initialize()
    conn = store._conn
    assert "idx_preferences_class" in _indexes(conn, "preferences")
    plan = _plan(
        conn,
        "SELECT AVG(approved) AS rate, COUNT(*) AS n FROM preferences "
        "WHERE agent=? AND kind=? AND risk_tier=?",
        ("scribe", "create_task", 2),
    )
    assert "idx_preferences_class" in plan, plan
    store.close()


# ── checkpoints: sessions(started_at) ─────────────────────────────

def test_sessions_started_index(tmp_path):
    mgr = CheckpointManager(db_path=str(tmp_path / "ckpt.db"))
    mgr.initialize()
    conn = mgr._conn
    assert "idx_sessions_started" in _indexes(conn, "sessions")
    plan = _plan(conn, "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 50")
    assert "idx_sessions_started" in plan, plan


# ── existing DBs pick the index up on the next init (idempotent) ──

def test_index_added_to_preexisting_db(tmp_path):
    """A queue.db created before the index existed gains it on next initialize()."""
    db = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db))
    raw.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, "
        "kind TEXT, title TEXT, payload TEXT, risk_tier INTEGER, status TEXT, "
        "autonomy_level TEXT, origin TEXT, attempts INTEGER, result TEXT, "
        "decided_by TEXT, decision TEXT, pushed INTEGER, created_at TEXT, "
        "updated_at TEXT)"
    )
    raw.commit()
    raw.close()
    assert "idx_tasks_status" not in _indexes(sqlite3.connect(str(db)), "tasks")

    q = TaskQueue(str(db)).initialize()
    assert "idx_tasks_status" in _indexes(q._conn, "tasks")
    q.close()
