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


# H452 — the eight failure types, checked in this order over the error code and the
# redacted diagnostic (Hermes cron/incidents.py keyword classes, word-bounded here).
FAILURE_TYPES = ("rate_limit", "timeout", "auth", "delivery", "config", "script", "agent", "unknown")
_FAILURE_RULES = (
    ("rate_limit", re.compile(r"\b429\b|rate[ _-]?limit|usage limit|quota", re.IGNORECASE)),
    ("timeout", re.compile(r"timeout|timed out|deadline", re.IGNORECASE)),
    ("auth", re.compile(r"\b40[13]\b|unauthori[sz]ed|authenticat|\bauth\b|forbidden|credential|api key",
                        re.IGNORECASE)),
    ("delivery", re.compile(r"\bdeliver(?:y|ed|ing)?\b|channel", re.IGNORECASE)),
    ("config", re.compile(r"config|validation|invalid|unsupported|must be|required|guard|blocked|refus|settings",
                          re.IGNORECASE)),
    ("script", re.compile(r"script|no_agent|terminal|stdout", re.IGNORECASE)),
    ("agent", re.compile(r"\bagent\b|model|provider|inference|backend|llm", re.IGNORECASE)),
)


def classify_failure(error_code: object, error: object) -> str:
    """One of :data:`FAILURE_TYPES` for a failure's code and redacted diagnostic."""
    text = f"{error_code} {error}"[:2 * MAX_ERROR]
    for name, rule in _FAILURE_RULES:
        if rule.search(text):
            return name
    return "unknown"


def _view(row) -> dict:
    return {key: row[key] for key in (
        "id", "job_id", "state", "failure_type", "first_seen", "last_seen", "occurrences",
        "failure_count", "error_code", "safe_error", "acknowledged_at", "alerted_at",
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
            columns = {row[1] for row in store._conn.execute("PRAGMA table_info(job_incidents)")}
            if "failure_type" not in columns:
                store._conn.execute("ALTER TABLE job_incidents ADD COLUMN failure_type TEXT NOT NULL "
                                    "DEFAULT 'unknown'")
            if "alerted_at" not in columns:
                store._conn.execute("ALTER TABLE job_incidents ADD COLUMN alerted_at TEXT")
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
        kind = classify_failure(code, safe_error)
        # A closed signature stays closed (terminal); only a new error text opens a new one.
        conn.execute("""INSERT INTO job_incidents
            (job_id,signature,state,first_seen,last_seen,occurrences,failure_count,error_code,safe_error,
             failure_type)
            VALUES (?,?,'detected',?,?,1,?,?,?,?)
            ON CONFLICT(job_id,signature) DO UPDATE SET
                last_seen=excluded.last_seen, occurrences=job_incidents.occurrences+1,
                failure_count=excluded.failure_count, safe_error=excluded.safe_error,
                failure_type=excluded.failure_type""",
            (job_id, signature, now, now, failure_count, code, safe_error, kind))
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
        sql = "SELECT * FROM job_incidents" + (" WHERE " + " AND ".join(where) if where else "")  # nosec B608 - clauses are fixed literals; values bound
        with self.store._lock:
            rows = self.store._conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [_view(row) for row in rows]

    def claim_alert(self, job_id: str) -> dict | None:
        """detected -> alerted for the job's newest incident, at most once per signature.

        Returns the incident when this caller should alert the owner, or None when that
        signature already alerted or was closed (alert once; closed is terminal).
        """
        with self.store._lock:
            conn = self.store._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM job_incidents WHERE job_id=? ORDER BY last_seen DESC, id DESC "
                                   "LIMIT 1", (str(job_id),)).fetchone()
                claimed = None
                if row is not None and row["state"] == "detected":
                    conn.execute("UPDATE job_incidents SET state='alerted', alerted_at=? "
                                 "WHERE id=? AND state='detected'", (datetime.now(UTC).isoformat(), row["id"]))
                    claimed = conn.execute("SELECT * FROM job_incidents WHERE id=?", (row["id"],)).fetchone()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _view(claimed) if claimed is not None else None

    def release_alert(self, incident_id: int) -> None:
        """alerted -> detected when the alert could not be delivered, so a later one may try."""
        with self.store._lock:
            self.store._conn.execute("UPDATE job_incidents SET state='detected', alerted_at=NULL "
                                     "WHERE id=? AND state='alerted'", (int(incident_id),))
            self.store._conn.commit()

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
