"""Durable, owner-acknowledgeable scheduled-job failures."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

MAX_ERROR = 512
REDACTION_UNAVAILABLE = "[diagnostic unavailable]"
_SPACE = re.compile(r"\s+")


def safe_diagnostic(value: object, *, broker=None) -> str:
    """Redact before any incident, run row, or pause reason persists an error."""
    try:
        from agents.core.log_tail import _redactor

        raw = str(value)
        if len(raw) > 8192:
            return REDACTION_UNAVAILABLE
        redacted = _redactor()(raw)
        if broker is not None:
            redacted = broker.redact(redacted)
        return _SPACE.sub(" ", redacted).strip()[:MAX_ERROR]
    except Exception:
        return REDACTION_UNAVAILABLE


def _view(row) -> dict:
    return {key: row[key] for key in (
        "id", "job_id", "state", "first_seen", "last_seen", "occurrences",
        "failure_count", "error_code", "safe_error", "acknowledged_at",
    )}


class JobIncidents:
    def __init__(self, store) -> None:
        self.store = store
        with store._lock:
            store._conn.execute("""CREATE TABLE IF NOT EXISTS job_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                signature TEXT NOT NULL, state TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                occurrences INTEGER NOT NULL, failure_count INTEGER NOT NULL,
                error_code TEXT NOT NULL, safe_error TEXT NOT NULL,
                acknowledged_at TEXT, UNIQUE(job_id, signature))""")
            store._conn.execute("CREATE INDEX IF NOT EXISTS job_incidents_state ON job_incidents(state,id)")
            store._conn.execute("CREATE INDEX IF NOT EXISTS job_incidents_job ON job_incidents(job_id,id)")
            store._conn.commit()

    def observe_failure_locked(self, conn, job_id: str, error_code: str,
                               error: object, failure_count: int) -> dict:
        """Caller owns BEGIN IMMEDIATE and the shared lock; call once per committed run."""
        # The caller prepared these bounded safe strings before entering SQLite.
        safe_error = str(error)[:MAX_ERROR]
        code = str(error_code)[:80]
        normalized = _SPACE.sub(" ", safe_error).casefold()
        signature = hashlib.sha256((code + "\0" + normalized).encode()).hexdigest()
        now = datetime.now(UTC).isoformat()
        conn.execute("""INSERT INTO job_incidents
            (job_id,signature,state,first_seen,last_seen,occurrences,failure_count,error_code,safe_error)
            VALUES (?,?,'detected',?,?,1,?,?,?)
            ON CONFLICT(job_id,signature) DO UPDATE SET
                last_seen=excluded.last_seen, occurrences=job_incidents.occurrences+1,
                failure_count=excluded.failure_count, safe_error=excluded.safe_error""",
            (job_id, signature, now, now, failure_count, code, safe_error))
        return _view(conn.execute(
            "SELECT * FROM job_incidents WHERE job_id=? AND signature=?",
            (job_id, signature)).fetchone())

    def list(self, job_id: str | None = None, state: str | None = None,
             limit: int = 100) -> list[dict]:
        if state is not None and state not in {"detected", "alerted", "closed"}:
            raise ValueError("invalid incident state")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("incident limit must be 1-100")
        where, args = [], []
        if job_id is not None:
            where.append("job_id=?")
            args.append(str(job_id))
        if state is not None:
            where.append("state=?")
            args.append(state)
        sql = "SELECT * FROM job_incidents" + (" WHERE " + " AND ".join(where) if where else "")
        with self.store._lock:
            rows = self.store._conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [_view(row) for row in rows]

    def ack(self, incident_id: int) -> dict | None:
        if type(incident_id) is not int or incident_id <= 0:
            return None
        with self.store._lock:
            conn = self.store._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("""UPDATE job_incidents SET state='closed',
                    acknowledged_at=COALESCE(acknowledged_at,?) WHERE id=?""",
                    (datetime.now(UTC).isoformat(), incident_id))
                row = conn.execute("SELECT * FROM job_incidents WHERE id=?", (incident_id,)).fetchone()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _view(row) if row else None
