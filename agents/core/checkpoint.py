"""
checkpoint.py — Agent execution checkpointing with SQLite.
Saves agent execution state for crash recovery and resume.
Also tracks agent stats for promotion/demotion and structured sessions.
"""

import contextlib
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.checkpoint")

CHECKPOINT_DIR = data_path("checkpoints")


class CheckpointManager:
    #: H218 — a session's archived stamp, read from its metadata only when the JSON is valid.
    _ARCHIVED_SQL = "(CASE WHEN json_valid(metadata) THEN json_extract(metadata, '$.archived_at') END)"
    #: H262 — its pin, the same way.
    _PINNED_SQL = "(CASE WHEN json_valid(metadata) THEN json_extract(metadata, '$.pinned_at') END)"
    #: H262 review — when an owner last kept it (an unarchive, a resume), the same way.
    _KEPT_SQL = "(CASE WHEN json_valid(metadata) THEN json_extract(metadata, '$.kept_at') END)"
    #: H262 review — a session's last activity: its last turn (``ended_at``, else
    #: ``started_at``), or the owner's later keep. The archiver and retention measure idle
    #: time from it, so an unarchived or resumed chat is idle again only from then.
    _ACTIVITY_SQL = ("MAX(COALESCE(ended_at, started_at), "
                     f"COALESCE({_KEPT_SQL}, COALESCE(ended_at, started_at)))")
    #: H262 review — how long another process waits for the database's write lock (a
    #: VACUUM holds it for its whole run) before a write fails.
    BUSY_TIMEOUT_S = 30

    def __init__(self, db_path: str = None):
        if db_path is None:
            CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
            db_path = str(CHECKPOINT_DIR / "checkpoints.db")
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # Guard concurrent access when called via asyncio.to_thread (H7.2)
        self._lock = threading.Lock()

    def initialize(self):
        # check_same_thread=False: save/load run via asyncio.to_thread (H7.2),
        # so the connection is touched from pool worker threads; a threading.Lock
        # serializes access. WAL + synchronous=NORMAL keeps the per-turn commit
        # cheap (~36x faster in-bench) without losing durability.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=self.BUSY_TIMEOUT_S)
        # H262 review: the hub and the coordinator share this file; a write from the one
        # that is not vacuuming waits for the VACUUM instead of being dropped after 5 s.
        self._conn.execute(f"PRAGMA busy_timeout={int(self.BUSY_TIMEOUT_S * 1000)}")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                state TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(agent_id, session_id)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_stats (
                agent_id TEXT PRIMARY KEY,
                total_calls INTEGER DEFAULT 0,
                success_calls INTEGER DEFAULT 0,
                failure_calls INTEGER DEFAULT 0,
                avg_latency REAL DEFAULT 0.0,
                last_status TEXT DEFAULT 'unknown',
                last_error TEXT,
                demoted INTEGER DEFAULT 0,
                promoted_from TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                agent_id TEXT,
                started_at TEXT,
                ended_at TEXT,
                turn_count INTEGER DEFAULT 0,
                summary TEXT,
                metadata TEXT DEFAULT '{}'
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS session_clock (
                session_id TEXT PRIMARY KEY,
                birth_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                rebuilt_at TEXT NOT NULL,
                compaction_sha256 TEXT NOT NULL DEFAULT ''
            )
        """)
        # H262 — one row per maintenance job: when it last claimed a run (a compare-and-set
        # both processes on this data root share) and what it keeps between runs.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_state (
                name TEXT PRIMARY KEY,
                last_run_at REAL,
                value TEXT DEFAULT '{}'
            )
        """)
        from .session_continuation import initialize
        initialize(self._conn)
        # list_sessions() orders by started_at and the table grows one row per
        # session; index started_at so the ordered scan stays cheap as history
        # accumulates.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at)"
        )
        self._conn.commit()
        logger.info(f"Checkpoint DB initialized: {self.db_path}")

    def save(self, orchestrator) -> bool:
        if not self._conn:
            return False
        try:
            state = {
                "session_id": orchestrator.session_id,
                "agent_ids": list(orchestrator.agents.keys()),
                "channel_ids": list(orchestrator.channels.keys()),
                "llm_backend": orchestrator.llm_router.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO checkpoints (agent_id, session_id, state, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("orchestrator", orchestrator.session_id, "running",
                     json.dumps(state, ensure_ascii=False), state["timestamp"]),
                )
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning(f"Checkpoint save failed: {e}")
            return False

    def load(self, agent_id: str, session_id: str) -> Optional[dict]:
        if not self._conn:
            return None
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT state, data FROM checkpoints WHERE agent_id=? AND session_id=?",
                    (agent_id, session_id),
                )
                row = cursor.fetchone()
            if row:
                return {"state": row[0], **json.loads(row[1])}
        except Exception as e:
            logger.warning(f"Checkpoint load failed: {e}")
        return None

    def restore(self, orchestrator) -> bool:
        if not self._conn:
            return False
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT data FROM checkpoints WHERE agent_id='orchestrator' ORDER BY rowid DESC LIMIT 1"
                )
                row = cursor.fetchone()
            if row:
                state = json.loads(row[0])
                orchestrator.session_id = state.get("session_id", orchestrator.session_id)
                logger.info(f"Restored from checkpoint: session={orchestrator.session_id}")
                return True
        except Exception as e:
            logger.warning(f"Checkpoint restore failed: {e}")
        return False

    def save_agent_execution(self, agent_id: str, session_id: str, prompt: str):
        if not self._conn:
            return
        try:
            data = json.dumps({"prompt": prompt, "timestamp": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO checkpoints (agent_id, session_id, state, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    (agent_id, session_id, "executing", data, datetime.now(timezone.utc).isoformat()),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Agent checkpoint save failed: {e}")

    def clear_agent_checkpoint(self, agent_id: str, session_id: str):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "DELETE FROM checkpoints WHERE agent_id=? AND session_id=?",
                    (agent_id, session_id),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Checkpoint clear failed: {e}")

    def record_call(self, agent_id: str, success: bool, latency: float = 0.0, error: str = None):
        if not self._conn:
            return
        try:
            now = datetime.now(timezone.utc).isoformat()
            succ = 1 if success else 0
            fail = 0 if success else 1
            status = "success" if success else "failure"
            with self._lock:
                self._conn.execute("""
                    INSERT INTO agent_stats (agent_id, total_calls, success_calls, failure_calls,
                        avg_latency, last_status, last_error, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        total_calls = total_calls + 1,
                        success_calls = success_calls + ?,
                        failure_calls = failure_calls + ?,
                        avg_latency = (avg_latency * total_calls + ?) / (total_calls + 1),
                        last_status = ?,
                        last_error = ?,
                        updated_at = ?
                """, (agent_id, 1, succ, fail, latency, status, error, now, now,
                      succ, fail, latency, status, error, now))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to record call for {agent_id}: {e}")

    def get_agent_stats(self, agent_id: str) -> dict:
        if not self._conn:
            return {}
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT * FROM agent_stats WHERE agent_id=?", (agent_id,)
                )
                columns = [d[0] for d in cursor.description]
                row = cursor.fetchone()
            if row:
                return dict(zip(columns, row))
        except Exception as e:
            logger.warning(f"Failed to get stats for {agent_id}: {e}")
        return {}

    def get_all_agent_stats(self) -> dict[str, dict]:
        if not self._conn:
            return {}
        try:
            with self._lock:
                cursor = self._conn.execute("SELECT * FROM agent_stats")
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
            return {row[0]: dict(zip(columns, row)) for row in rows}
        except Exception as e:
            logger.warning(f"Failed to get all agent stats: {e}")
        return {}

    def create_session_record(self, session_id: str, agent_id: str = None, metadata: dict = None):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute("""
                    INSERT OR IGNORE INTO sessions (id, agent_id, started_at, turn_count, metadata)
                    VALUES (?, ?, ?, 0, ?)
                """, (session_id, agent_id, datetime.now(timezone.utc).isoformat(),
                      json.dumps(metadata or {}, ensure_ascii=False)))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to create session record: {e}")

    def session_title(self, session_id: str) -> dict:
        """H413 — ``{"title", "source"}`` from the session row's metadata (empty strings
        when there is none, the row is missing or its metadata is unreadable)."""
        empty = {"title": "", "source": ""}
        if not self._conn:
            return empty
        try:
            with self._lock:
                row = self._conn.execute("SELECT metadata FROM sessions WHERE id=?", (session_id,)).fetchone()
            meta = json.loads(row[0] or "{}") if row else {}
        except Exception:
            return empty
        if not isinstance(meta, dict) or not isinstance(meta.get("title"), str):
            return empty
        return {"title": meta["title"], "source": str(meta.get("title_source") or "")}

    def set_session_title(self, session_id: str, title: str, source: str, *,
                          replace: tuple[str, ...] = ()) -> bool:
        """H413 — write the title when the session has none, or its current title came
        from one of ``replace`` (compare-and-set: a newer title is never overwritten).
        Whether it was written. A first title creates a missing row; a replacing write
        (the model's upgrade, after the reply) never does, so a session deleted in
        between stays deleted."""
        if not self._conn or not isinstance(title, str) or not title:
            return False
        try:
            with self._lock:
                row = self._conn.execute("SELECT metadata FROM sessions WHERE id=?", (session_id,)).fetchone()
                if row is None:
                    if replace:
                        return False
                    self._conn.execute(
                        "INSERT OR IGNORE INTO sessions (id, started_at, turn_count, metadata) VALUES (?, ?, 0, '{}')",
                        (session_id, datetime.now(timezone.utc).isoformat()))
                    meta = {}
                else:
                    try:
                        meta = json.loads(row[0] or "{}")
                    except ValueError:
                        meta = {}
                    if not isinstance(meta, dict):
                        meta = {}
                titled = isinstance(meta.get("title"), str) and bool(meta["title"])
                if titled and str(meta.get("title_source") or "") not in replace:
                    return False
                meta.update({"title": title, "title_source": source})
                self._conn.execute("UPDATE sessions SET metadata=? WHERE id=?",
                                   (json.dumps(meta, ensure_ascii=False), session_id))
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning(f"Failed to set session title: {e}")
            return False

    def session_row(self, session_id: str) -> dict | None:
        """H218 — one session's row, or None."""
        if not self._conn:
            return None
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
            columns = [d[0] for d in cursor.description]
            row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None

    def _set_stamp(self, session_id: str, key: str, on: bool, at: str | None) -> bool | None:
        """Stamp (or clear) one ISO timestamp ``key`` in a session's metadata. Whether the
        session exists; a session is never created by stamping it. None when the store
        could not answer (no connection, a database error): that is not a missing session."""
        return self._set_stamps(session_id, {key: (at or datetime.now(timezone.utc).isoformat()) if on else None})

    def _set_stamps(self, session_id: str, stamps: dict) -> bool | None:
        """Set (a value) or clear (None) several metadata stamps in one write; see ``_set_stamp``."""
        if not self._conn:
            return None
        try:
            with self._lock:
                row = self._conn.execute("SELECT metadata FROM sessions WHERE id=?", (session_id,)).fetchone()
                if row is None:
                    return False
                try:
                    meta = json.loads(row[0] or "{}")
                except ValueError:
                    meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                for key, value in stamps.items():
                    if value is None:
                        meta.pop(key, None)
                    else:
                        meta[key] = value
                self._conn.execute("UPDATE sessions SET metadata=? WHERE id=?",
                                   (json.dumps(meta, ensure_ascii=False), session_id))
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning(f"Failed to stamp session {sorted(stamps)}: {e}")
            return None

    def set_archived(self, session_id: str, archived: bool, *, at: str | None = None) -> bool | None:
        """H218 — stamp (or clear) ``archived_at`` in a session's metadata (see ``_set_stamp``)."""
        return self._set_stamp(session_id, "archived_at", archived, at)

    def unarchive(self, session_id: str, *, at: str | None = None) -> bool | None:
        """H262 review — the owner keeps a chat (the unarchive and resume routes): clear
        ``archived_at`` and stamp ``kept_at`` in one write, so the archiver measures its idle
        time from now and does not archive it again for another ``auto_archive_days``."""
        return self._set_stamps(session_id, {"archived_at": None,
                                             "kept_at": at or datetime.now(timezone.utc).isoformat()})

    def set_pinned(self, session_id: str, pinned: bool, *, at: str | None = None) -> bool | None:
        """H262 — stamp (or clear) ``pinned_at``: a pinned chat is never auto-archived and
        never deleted by retention. Archiving and resuming leave the pin as it is."""
        return self._set_stamp(session_id, "pinned_at", pinned, at)

    def stale_sessions(self, before: str, *, limit: int = 500) -> list[str]:
        """H218 — unarchived, unpinned (H262) sessions whose last activity (``ended_at``,
        else ``started_at``; H262 review: or a later ``kept_at``) is older than the ISO
        timestamp ``before``, oldest first."""
        if not self._conn:
            return []
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id FROM sessions WHERE {self._ARCHIVED_SQL} IS NULL AND {self._PINNED_SQL} IS NULL"  # nosec B608 - fixed SQL fragments
                f" AND {self._ACTIVITY_SQL} IS NOT NULL AND {self._ACTIVITY_SQL} < ?"
                f" ORDER BY {self._ACTIVITY_SQL} LIMIT ?", (before, limit)).fetchall()
        return [r[0] for r in rows]

    #: H262 — what retention may delete: archived, unpinned, archived at or before the
    #: first ``?`` (H262 review: the grace — a chat stays in the Archived view at least
    #: ``retention.DELETE_GRACE_DAYS``, so one archived in this sweep never qualifies) and
    #: idle since before the second ``?``.
    _EXPIRED_WHERE = (f"{_ARCHIVED_SQL} IS NOT NULL AND {_PINNED_SQL} IS NULL AND {_ARCHIVED_SQL} <= ?"
                      f" AND {_ACTIVITY_SQL} IS NOT NULL AND {_ACTIVITY_SQL} < ?")

    @staticmethod
    def _grace_cutoff(archived_before: str | None) -> str:
        """The latest archive stamp retention may delete: the one given, else now less
        ``retention.DELETE_GRACE_DAYS``."""
        if archived_before is not None:
            return archived_before
        from datetime import timedelta

        from .retention import DELETE_GRACE_DAYS
        return (datetime.now(timezone.utc) - timedelta(days=DELETE_GRACE_DAYS)).isoformat()

    def expired_sessions(self, before: str, *, archived_before: str | None = None, limit: int = 500) -> list[str]:
        """H262 — archived, unpinned sessions idle since before the ISO timestamp ``before``
        and archived at or before ``archived_before`` (default: the grace before now),
        newest first: a continued chat is newer than the one it continues, so it comes
        before its parent (whose delete it would otherwise refuse)."""
        if not self._conn:
            return []
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id FROM sessions WHERE {self._EXPIRED_WHERE}"  # nosec B608 - fixed SQL fragments
                f" ORDER BY {self._ACTIVITY_SQL} DESC LIMIT ?",
                (self._grace_cutoff(archived_before), before, limit)).fetchall()
        return [r[0] for r in rows]

    def is_expired(self, session_id: str, before: str, *, archived_before: str | None = None) -> bool:
        """H262 — whether one session is still what ``expired_sessions`` found: the check a
        delete repeats while it holds the turn lease (a turn, an unarchive or a pin in
        between keeps the chat). The row delete repeats it once more, in SQL
        (``delete_session_rows(expired=…)``)."""
        if not self._conn:
            return False
        with self._lock:
            row = self._conn.execute(
                f"SELECT 1 FROM sessions WHERE id=? AND {self._EXPIRED_WHERE}",  # nosec B608 - fixed SQL fragments
                (session_id, self._grace_cutoff(archived_before), before)).fetchone()
        return row is not None


    def session_ids(self) -> set[str]:
        """H262 — every session id this store has a row for."""
        if not self._conn:
            return set()
        with self._lock:
            return {r[0] for r in self._conn.execute("SELECT id FROM sessions").fetchall()}

    # ── H262 — the maintenance state rows ────────────────────────
    def claim_sweep(self, name: str, now: float, min_interval_s: float) -> bool | None:
        """Claim the maintenance job ``name`` when its last claim is at least
        ``min_interval_s`` old (or none, or one more than ``min_interval_s`` in the future:
        the clock went back). One statement, so of two processes sharing this database
        exactly one claims it — H262 review: a claim only slightly ahead of ``now`` is the
        other process's, whose clock read came later but committed first, never a skew.
        True when claimed, False when not due, None when the store could not answer."""
        if not self._conn:
            return None
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "INSERT INTO maintenance_state (name, last_run_at, value) VALUES (?, ?, '{}') "
                    "ON CONFLICT(name) DO UPDATE SET last_run_at=excluded.last_run_at "
                    "WHERE maintenance_state.last_run_at IS NULL OR maintenance_state.last_run_at <= ? "
                    "OR maintenance_state.last_run_at > ?",
                    (name, now, now - min_interval_s, now + min_interval_s))
                self._conn.commit()
            return cursor.rowcount == 1
        except sqlite3.Error as e:
            logger.warning(f"Failed to claim the {name} run: {e}")
            return None

    def get_state(self, name: str) -> dict | None:
        """``{"last_run_at", "value"}`` of one maintenance row; None when there is none or
        the store could not answer. A value that does not parse reads as ``{}``."""
        if not self._conn:
            return None
        try:
            with self._lock:
                row = self._conn.execute("SELECT last_run_at, value FROM maintenance_state WHERE name=?",
                                         (name,)).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            value = json.loads(row[1] or "{}")
        except ValueError:
            value = {}
        return {"last_run_at": row[0], "value": value if isinstance(value, dict) else {}}

    def put_state(self, name: str, value: dict) -> bool | None:
        """Write one maintenance row's value (its claim is kept); None when the store
        could not answer."""
        if not self._conn:
            return None
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO maintenance_state (name, last_run_at, value) VALUES (?, NULL, ?) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (name, json.dumps(value, ensure_ascii=False, default=str)))
                self._conn.commit()
            return True
        except sqlite3.Error as e:
            logger.warning(f"Failed to write the {name} state: {e}")
            return None

    def vacuum(self) -> bool:
        """H262 — give the pages a prune freed back to the disk, then empty the write-ahead
        log. Whether it ran; another connection busy past the timeout is a False.

        VACUUM holds the write lock for its whole run. Only the process that runs the
        lifecycle sweep calls this (the hub, or a coordinator with no hub running: see
        ``lifecycle_sweep``), and every CheckpointManager connection waits up to
        ``BUSY_TIMEOUT_S`` (30 s) for the lock. The residual: a VACUUM longer than 30 s (a
        database of several GB, a slow disk) still makes the other process's write fail,
        and its writers log that and drop the write."""
        if not self._conn:
            return False
        try:
            with self._lock:
                if self._conn.in_transaction:
                    self._conn.commit()
                self._conn.execute("VACUUM")
                with contextlib.suppress(sqlite3.Error):
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True
        except sqlite3.Error as e:
            logger.warning(f"checkpoints.db VACUUM failed: {e}")
            return False

    # H218 — every table that keeps a row under a session's id: its name in a backup,
    # the key column, and whether there can be several. The continuation seed holds the
    # carried turns; the history binding would refuse a later session with the same id.
    _SESSION_TABLES = (("checkpoints", "checkpoints", "session_id", True),
                       ("session_clock", "clock", "session_id", False),
                       ("session_continuations", "continuation", "session_id", False),
                       ("session_history_instances", "history_instance", "session_id", False),
                       ("sessions", "session", "id", False))

    def session_rows_for_backup(self, session_id: str) -> dict:
        """H218 — everything this store keeps about one session, for the backup a
        permanent delete takes first, and the chats continued from it (``continued_by``)."""
        out: dict = {name: [] if many else None for _table, name, _key, many in self._SESSION_TABLES}
        out["continued_by"] = []
        if not self._conn:
            return out
        with self._lock:
            for table, name, key, many in self._SESSION_TABLES:
                cursor = self._conn.execute(f"SELECT * FROM {table} WHERE {key}=?", (session_id,))  # nosec B608 - fixed table names
                columns = [d[0] for d in cursor.description]
                rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
                out[name] = rows if many else (rows[0] if rows else None)
            out["continued_by"] = [r[0] for r in self._conn.execute(
                "SELECT session_id FROM session_continuations WHERE parent_id=?", (session_id,)).fetchall()]
        return out

    def delete_session_rows(self, session_id: str, *, expired: tuple[str, str] | None = None) -> dict | None:
        """H218 — remove one session's rows (see ``_SESSION_TABLES``). The freed pages are
        zeroed and the write-ahead log emptied, so the rows are not left readable in the
        database files — the same erasure ``data_purge._purge_db`` does for a forget.

        H262 review — ``expired`` (``(before, archived_before)``, retention's delete): the
        session row goes first, and only while it is still expired (``_EXPIRED_WHERE``), in
        the same transaction as the rest. A pin, an unarchive or a resume that landed since
        any earlier check matches nothing: everything is rolled back and None returned."""
        counts = {table: 0 for table, _name, _key, _many in self._SESSION_TABLES}
        if not self._conn:
            return counts if expired is None else None
        with self._lock:
            secure = self._conn.execute("PRAGMA secure_delete").fetchone()[0]
            self._conn.execute("PRAGMA secure_delete = ON")
            try:
                tables = self._SESSION_TABLES
                if expired is not None:
                    before, archived_before = expired
                    counts["sessions"] = self._conn.execute(
                        f"DELETE FROM sessions WHERE id=? AND {self._EXPIRED_WHERE}",  # nosec B608 - fixed SQL fragments
                        (session_id, archived_before, before)).rowcount
                    if counts["sessions"] != 1:
                        self._conn.rollback()
                        return None
                    tables = tuple(t for t in tables if t[0] != "sessions")
                for table, _name, key, _many in tables:
                    counts[table] = self._conn.execute(f"DELETE FROM {table} WHERE {key}=?", (session_id,)).rowcount  # nosec B608 - fixed table names
                self._conn.commit()
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    logger.warning("session rows deleted, but the write-ahead log could not be emptied", exc_info=True)
            finally:
                if not secure:
                    self._conn.execute("PRAGMA secure_delete = OFF")
        return counts

    def session_started_at(self, session_id: str) -> str | None:
        """Read the durable birth date; old/missing rows remain unknown."""
        if not self._conn:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT started_at FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        return row[0] if row else None

    def clock_snapshot(self, session_id: str):
        """Read/seed an immutable clock from an existing durable session birth."""
        from .conversation_clock import ClockSnapshot, parse_started_at
        if not self._conn:
            return None
        try:
            with self._lock, self._conn:
                from .session_continuation import identity
                current = identity(self._conn, session_id)
                if current is None:
                    return None
                birth, instance = current
                self._conn.execute(
                    "INSERT INTO session_clock(session_id, birth_at, rebuilt_at, instance_id) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET birth_at=excluded.birth_at, "
                    "rebuilt_at=excluded.rebuilt_at, revision=0, compaction_sha256='', instance_id=excluded.instance_id "
                    "WHERE session_clock.birth_at != excluded.birth_at OR session_clock.instance_id != excluded.instance_id",
                    (session_id, birth.isoformat(), birth.isoformat(), instance),
                )
                revision, rebuilt = self._conn.execute(
                    "SELECT revision, rebuilt_at FROM session_clock WHERE session_id=?", (session_id,),
                ).fetchone()
                rebuilt = parse_started_at(rebuilt)
                if rebuilt is None or type(revision) is not int or revision < 0:
                    return None
                return ClockSnapshot(session_id, birth, rebuilt, revision, instance)
        except Exception:
            logger.warning("session clock unavailable", exc_info=True)
            return None

    def commit_clock(self, snapshot, compaction: str, *, now=None):
        """CAS accepted compaction identity and clock together; no async publication gap."""
        import hashlib

        from .conversation_clock import ClockSnapshot
        if not self._conn or not isinstance(snapshot, ClockSnapshot):
            return None
        moment = now or datetime.now(timezone.utc)
        # A wall-clock correction must not move an accepted rebuild backwards.
        if moment.astimezone() < snapshot.rebuilt_at.astimezone():
            moment = snapshot.rebuilt_at
        try:
            with self._lock, self._conn:
                from .session_continuation import identity
                current = identity(self._conn, snapshot.session_id)
                if current != (snapshot.started_at, snapshot.instance_id):
                    return None
                cursor = self._conn.execute(
                    "UPDATE session_clock SET revision=revision+1, rebuilt_at=?, compaction_sha256=? "
                    "WHERE session_id=? AND revision=? AND rebuilt_at=? "
                    "AND instance_id=? AND EXISTS (SELECT 1 FROM sessions WHERE id=? AND instance_id=?)",
                    (moment.isoformat(), hashlib.sha256(compaction.encode()).hexdigest(),
                     snapshot.session_id, snapshot.revision, snapshot.rebuilt_at.isoformat(),
                     snapshot.instance_id, snapshot.session_id, snapshot.instance_id),
                )
                if cursor.rowcount != 1:
                    return None
                return ClockSnapshot(snapshot.session_id, snapshot.started_at, moment, snapshot.revision + 1, snapshot.instance_id)
        except Exception:
            logger.warning("compaction clock commit refused", exc_info=True)
            return None

    def update_session(self, session_id: str, turn_count: int = None, summary: str = None):
        if not self._conn:
            return
        try:
            updates = ["ended_at=?"]
            params = [datetime.now(timezone.utc).isoformat()]
            if turn_count is not None:
                updates.append("turn_count=?")
                params.append(turn_count)
            if summary is not None:
                updates.append("summary=?")
                params.append(summary)
            params.append(session_id)
            with self._lock:
                self._conn.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id=?", params)
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update session: {e}")


    def get_sessions(self, limit: int = 20, *, archived: bool | None = None) -> list[dict]:
        """The newest sessions; ``archived`` True lists only archived ones, False only
        the others, None (the default, for existing callers) all of them."""
        if not self._conn:
            return []
        where = ""
        if archived is True:
            where = f" WHERE {self._ARCHIVED_SQL} IS NOT NULL"
        elif archived is False:
            where = f" WHERE {self._ARCHIVED_SQL} IS NULL"
        try:
            with self._lock:
                cursor = self._conn.execute(
                    f"SELECT * FROM sessions{where} ORDER BY started_at DESC LIMIT ?", (limit,)  # nosec B608 - fixed SQL fragments
                )
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.warning(f"Failed to get sessions: {e}")
        return []

    def info(self) -> dict:
        if not self._conn:
            return {"status": "unavailable"}
        try:
            with self._lock:
                cp_count = self._conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
                agent_count = self._conn.execute("SELECT COUNT(*) FROM agent_stats").fetchone()[0]
                session_count = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            return {
                "status": "active",
                "checkpoints": cp_count,
                "agents_tracked": agent_count,
                "sessions_recorded": session_count,
            }
        except Exception:
            return {"status": "error"}

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
