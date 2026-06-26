"""feedback_store.py — H23.21 design-partner feedback + NPS (first-party, local).

A small SQLite table for in-app feedback: NPS scores, free-text comments, bug reports.
Like ``analytics_store``, this is **first-party and local** — feedback never leaves the
machine; the owner reviews it via ``GET /api/feedback/summary``. WAL + a single
lock-guarded connection, mirroring the other stores.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.feedback")

DEFAULT_DB = data_path("feedback.db")
KINDS = ("nps", "comment", "bug")
_MAX_MSG = 4000


class _DB:
    conn: sqlite3.Connection | None = None
    path: str | None = None


_db = _DB()
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def initialize(db_path: str | None = None) -> sqlite3.Connection:
    """Open (or reopen) the feedback DB and ensure the schema. Idempotent."""
    with _lock:
        if _db.conn is not None and (db_path is None or db_path == _db.path):
            return _db.conn
        if _db.conn is not None:
            _db.conn.close()
            _db.conn = None
        path = db_path or str(DEFAULT_DB)
        if path != ":memory:":
            DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                kind       TEXT NOT NULL,
                score      INTEGER,
                message    TEXT,
                session_id TEXT
            )
            """
        )
        conn.commit()
        _db.conn, _db.path = conn, path
        return _db.conn


def _require() -> sqlite3.Connection:
    return _db.conn if _db.conn is not None else initialize()


def close() -> None:
    with _lock:
        if _db.conn is not None:
            _db.conn.close()
            _db.conn = None
            _db.path = None


def record(kind: str, *, score=None, message=None, session_id=None, ts=None) -> int:
    """Persist one feedback item (single INSERT). Returns the row id. Values are bounded:
    unknown kinds degrade to ``comment``, score clamps to 0–10, message is truncated."""
    kind = kind if kind in KINDS else "comment"
    if score is not None:
        try:
            score = max(0, min(10, int(score)))
        except (TypeError, ValueError):
            score = None
    msg = str(message)[:_MAX_MSG] if message else None
    sid = str(session_id)[:128] if session_id else None
    conn = _require()
    with _lock:
        cur = conn.execute(
            "INSERT INTO feedback (ts, kind, score, message, session_id) VALUES (?, ?, ?, ?, ?)",
            (ts or _now_iso(), kind, score, msg, sid),
        )
        conn.commit()
        return cur.lastrowid


def summary(recent_limit: int = 20) -> dict:
    """NPS + per-kind counts + the most recent items.

    NPS = %promoters (9–10) − %detractors (0–6) over scored ``nps`` rows; ``None`` until
    at least one NPS response exists (we never fabricate a score)."""
    conn = _require()
    with _lock:
        scores = [r["score"] for r in conn.execute(
            "SELECT score FROM feedback WHERE kind='nps' AND score IS NOT NULL").fetchall()]
        counts = conn.execute("SELECT kind, COUNT(*) AS n FROM feedback GROUP BY kind").fetchall()
        recent = conn.execute(
            "SELECT ts, kind, score, message FROM feedback ORDER BY id DESC LIMIT ?",
            (int(recent_limit),),
        ).fetchall()
    n = len(scores)
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    nps = round((promoters - detractors) / n * 100) if n else None
    return {
        "nps": nps,
        "responses": n,
        "promoters": promoters,
        "detractors": detractors,
        "by_kind": {r["kind"]: r["n"] for r in counts},
        "recent": [dict(r) for r in recent],
    }
