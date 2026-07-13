"""Fail-closed SQLite state for H33 monitors, decisions, and ownership."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .contracts import AmbientDecision, AmbientEvent, MonitorDefinition

_SCHEMA_VERSION = 2
_MAX_ROWS = 100_000
_MAX_BYTES = 64 * 1024 * 1024
_JOURNAL_TTL = 30 * 24 * 60 * 60
_HEALTH_TTL = 7 * 24 * 60 * 60


class AmbientStoreError(RuntimeError):
    """Stable refusal when ambient safety state is unavailable or full."""


def _timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("ambient store timestamp must be finite")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("ambient store timestamp must be finite")
    return result


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AmbientStore:
    """Durable monitor state. Existing corruption is never replaced with an empty DB."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        max_rows: int = _MAX_ROWS,
        max_bytes: int = _MAX_BYTES,
    ) -> None:
        if not callable(clock):
            raise ValueError("ambient store clock must be callable")
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= _MAX_ROWS:
            raise ValueError("ambient row limit is invalid")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 4096 <= max_bytes <= _MAX_BYTES:
            raise ValueError("ambient byte limit is invalid")
        self.path = Path(path)
        self._clock = clock
        self._max_rows = max_rows
        self._max_bytes = max_bytes
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._reason = ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(str(self.path), timeout=5.0, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 1, _SCHEMA_VERSION}:
                raise sqlite3.DatabaseError("unsupported ambient schema")
            if version == 0:
                self._migrate(db)
            elif version == 1:
                self._migrate_v2(db)
            db.execute("SELECT monitor_id FROM monitors LIMIT 1").fetchall()
            self._db = db
            self.sweep()
        except (OSError, sqlite3.DatabaseError):
            try:
                if db is not None:
                    db.close()
            except (AttributeError, sqlite3.Error):
                pass
            self._db = None
            self._reason = "store_corrupt"

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE monitors (
                monitor_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                definition_hash TEXT NOT NULL,
                source TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE monitor_state (
                monitor_id TEXT PRIMARY KEY REFERENCES monitors(monitor_id) ON DELETE CASCADE,
                matched INTEGER NOT NULL DEFAULT 0,
                pending_since REAL,
                last_emit REAL,
                last_event_at REAL,
                field_hashes TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE event_dedupe (
                source TEXT NOT NULL,
                dedupe_hash TEXT NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY(source, dedupe_hash)
            );
            CREATE TABLE replay_tombstones (
                source TEXT NOT NULL,
                dedupe_hash TEXT NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY(source, dedupe_hash)
            );
            CREATE TABLE pending_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                dedupe_hash TEXT NOT NULL,
                payload TEXT NOT NULL,
                critical INTEGER NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE decisions (
                decision_id TEXT PRIMARY KEY,
                monitor_id TEXT NOT NULL,
                monitor_version INTEGER NOT NULL,
                monitor_hash TEXT NOT NULL,
                event_fingerprint TEXT NOT NULL,
                transition TEXT NOT NULL,
                matched INTEGER NOT NULL,
                reason TEXT NOT NULL,
                decided_at REAL NOT NULL,
                consent_generation INTEGER NOT NULL,
                rung TEXT NOT NULL DEFAULT 'monitor',
                attention_mode TEXT NOT NULL DEFAULT 'none',
                policy_reason TEXT NOT NULL DEFAULT 'policy_selected'
            );
            CREATE TABLE source_health (
                source TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                last_event_at REAL,
                last_error TEXT NOT NULL DEFAULT '',
                queued INTEGER NOT NULL DEFAULT 0,
                critical_backpressure INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            CREATE TABLE source_ownership (
                source TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                watermark TEXT NOT NULL,
                owner TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE registry_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                version INTEGER NOT NULL,
                definition_hash TEXT NOT NULL,
                actor_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            PRAGMA user_version=2;
            COMMIT;
            """
        )

    @staticmethod
    def _migrate_v2(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            ALTER TABLE decisions ADD COLUMN rung TEXT NOT NULL DEFAULT 'monitor';
            ALTER TABLE decisions ADD COLUMN attention_mode TEXT NOT NULL DEFAULT 'none';
            ALTER TABLE decisions ADD COLUMN policy_reason TEXT NOT NULL DEFAULT 'policy_selected';
            PRAGMA user_version=2;
            COMMIT;
            """
        )

    def _now(self) -> float:
        return _timestamp(self._clock())

    def _require(self) -> sqlite3.Connection:
        if self._db is None:
            raise AmbientStoreError(self._reason or "store_unavailable")
        return self._db

    def _size(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (
                self.path,
                Path(f"{self.path}-wal"),
                Path(f"{self.path}-shm"),
            )
            if candidate.exists()
        )

    def _row_count(self, db: sqlite3.Connection) -> int:
        row = db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM monitors) +
                (SELECT COUNT(*) FROM monitor_state) +
                (SELECT COUNT(*) FROM event_dedupe) +
                (SELECT COUNT(*) FROM replay_tombstones) +
                (SELECT COUNT(*) FROM pending_events) +
                (SELECT COUNT(*) FROM decisions) +
                (SELECT COUNT(*) FROM source_health) +
                (SELECT COUNT(*) FROM source_ownership) +
                (SELECT COUNT(*) FROM registry_audit)
            """
        ).fetchone()
        return int(row[0])

    def _guard_capacity(self, db: sqlite3.Connection) -> None:
        if self._row_count(db) >= self._max_rows or self._size() >= self._max_bytes:
            self._reason = "store_capacity_exceeded"
            raise AmbientStoreError(self._reason)

    def put_monitor(self, definition: MonitorDefinition, *, operation: str, actor: str) -> None:
        if not isinstance(definition, MonitorDefinition) or operation not in {"create", "update"}:
            raise ValueError("ambient monitor write is invalid")
        with self._lock:
            db = self._require()
            self._guard_capacity(db)
            now = self._now()
            encoded = json.dumps(definition.to_dict(), sort_keys=True, separators=(",", ":"))
            db.execute(
                """
                INSERT INTO monitors(monitor_id, version, definition_hash, source, payload, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id) DO UPDATE SET
                    version=excluded.version,
                    definition_hash=excluded.definition_hash,
                    source=excluded.source,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    definition.monitor_id,
                    definition.version,
                    definition.definition_hash,
                    definition.source,
                    encoded,
                    now,
                ),
            )
            if operation == "update":
                db.execute("DELETE FROM monitor_state WHERE monitor_id=?", (definition.monitor_id,))
            db.execute(
                """
                INSERT INTO registry_audit(
                    monitor_id, operation, version, definition_hash, actor_hash, created_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.monitor_id,
                    operation,
                    definition.version,
                    definition.definition_hash,
                    _hash(str(actor)),
                    now,
                ),
            )
            db.commit()

    def get_monitor(self, monitor_id: str) -> MonitorDefinition | None:
        with self._lock:
            db = self._require()
            row = db.execute("SELECT payload FROM monitors WHERE monitor_id=?", (monitor_id,)).fetchone()
        return MonitorDefinition.from_payload(json.loads(row["payload"])) if row else None

    def list_monitors(self) -> tuple[MonitorDefinition, ...]:
        with self._lock:
            db = self._require()
            rows = db.execute("SELECT payload FROM monitors ORDER BY monitor_id").fetchall()
        return tuple(MonitorDefinition.from_payload(json.loads(row["payload"])) for row in rows)

    def delete_monitor(self, monitor_id: str, *, actor: str) -> bool:
        with self._lock:
            db = self._require()
            row = db.execute(
                "SELECT version, definition_hash FROM monitors WHERE monitor_id=?", (monitor_id,)
            ).fetchone()
            if row is None:
                return False
            now = self._now()
            db.execute("DELETE FROM monitors WHERE monitor_id=?", (monitor_id,))
            db.execute(
                """
                INSERT INTO registry_audit(
                    monitor_id, operation, version, definition_hash, actor_hash, created_at
                ) VALUES(?, 'delete', ?, ?, ?, ?)
                """,
                (monitor_id, row["version"], row["definition_hash"], _hash(str(actor)), now),
            )
            db.commit()
            return True

    def audit(self, *, limit: int = 1_000) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1_000))
        with self._lock:
            db = self._require()
            rows = db.execute(
                """
                SELECT monitor_id, operation, version, definition_hash, created_at
                FROM registry_audit ORDER BY id ASC LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_event(self, event: AmbientEvent, *, ttl_seconds: float = 7 * 24 * 60 * 60) -> bool:
        if not isinstance(event, AmbientEvent):
            raise ValueError("ambient dedupe requires AmbientEvent")
        now = self._now()
        key = _hash(event.dedupe_key)
        with self._lock:
            db = self._require()
            db.execute(
                "DELETE FROM event_dedupe WHERE source=? AND dedupe_hash=? AND expires_at<=?",
                (event.source, key, now),
            )
            if db.execute(
                "SELECT 1 FROM replay_tombstones WHERE source=? AND dedupe_hash=? AND expires_at>?",
                (event.source, key, now),
            ).fetchone():
                return False
            try:
                db.execute(
                    "INSERT INTO event_dedupe(source, dedupe_hash, expires_at) VALUES(?, ?, ?)",
                    (event.source, key, now + ttl_seconds),
                )
                db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def purge_source(self, source: str, *, tombstone_ttl: float = 7 * 24 * 60 * 60) -> dict[str, int]:
        now = self._now()
        with self._lock:
            db = self._require()
            keys = [
                row["dedupe_hash"]
                for row in db.execute(
                    "SELECT dedupe_hash FROM event_dedupe WHERE source=?", (source,)
                ).fetchall()
            ]
            for key in keys:
                db.execute(
                    """
                    INSERT INTO replay_tombstones(source, dedupe_hash, expires_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(source, dedupe_hash) DO UPDATE SET expires_at=excluded.expires_at
                    """,
                    (source, key, now + tombstone_ttl),
                )
            monitor_ids = [
                row["monitor_id"]
                for row in db.execute(
                    "SELECT monitor_id FROM monitors WHERE source=?", (source,)
                ).fetchall()
            ]
            decisions = 0
            states = 0
            for monitor_id in monitor_ids:
                decisions += db.execute(
                    "DELETE FROM decisions WHERE monitor_id=?", (monitor_id,)
                ).rowcount
                states += db.execute(
                    "DELETE FROM monitor_state WHERE monitor_id=?", (monitor_id,)
                ).rowcount
            pending = db.execute("DELETE FROM pending_events WHERE source=?", (source,)).rowcount
            dedupe = db.execute("DELETE FROM event_dedupe WHERE source=?", (source,)).rowcount
            db.execute("DELETE FROM source_health WHERE source=?", (source,))
            db.commit()
            return {
                "decisions": decisions,
                "states": states,
                "pending": pending,
                "dedupe": dedupe,
                "tombstones": len(keys),
            }

    def add_pending(self, event: AmbientEvent) -> int:
        with self._lock:
            db = self._require()
            self._guard_capacity(db)
            cursor = db.execute(
                """
                INSERT INTO pending_events(source, dedupe_hash, payload, critical, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    event.source,
                    _hash(event.dedupe_key),
                    json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")),
                    int(event.critical),
                    self._now(),
                ),
            )
            db.commit()
            return int(cursor.lastrowid)

    def pending(self, *, limit: int = 100) -> list[tuple[int, AmbientEvent]]:
        bounded = max(1, min(int(limit), 100))
        with self._lock:
            db = self._require()
            rows = db.execute(
                "SELECT id, payload FROM pending_events ORDER BY id ASC LIMIT ?", (bounded,)
            ).fetchall()
        return [(int(row["id"]), AmbientEvent.from_dict(json.loads(row["payload"]))) for row in rows]

    def delete_pending(self, row_id: int) -> None:
        with self._lock:
            db = self._require()
            db.execute("DELETE FROM pending_events WHERE id=?", (int(row_id),))
            db.commit()

    def pending_count(self) -> int:
        with self._lock:
            db = self._require()
            return int(db.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0])

    def monitor_state(self, monitor_id: str) -> dict[str, Any]:
        with self._lock:
            db = self._require()
            row = db.execute("SELECT * FROM monitor_state WHERE monitor_id=?", (monitor_id,)).fetchone()
        if row is None:
            return {
                "matched": False,
                "pending_since": None,
                "last_emit": None,
                "last_event_at": None,
                "field_hashes": {},
            }
        return {
            "matched": bool(row["matched"]),
            "pending_since": row["pending_since"],
            "last_emit": row["last_emit"],
            "last_event_at": row["last_event_at"],
            "field_hashes": json.loads(row["field_hashes"]),
        }

    def save_monitor_state(self, monitor_id: str, state: dict[str, Any]) -> None:
        encoded_hashes = json.dumps(state.get("field_hashes", {}), sort_keys=True, separators=(",", ":"))
        with self._lock:
            db = self._require()
            db.execute(
                """
                INSERT INTO monitor_state(
                    monitor_id, matched, pending_since, last_emit, last_event_at, field_hashes
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id) DO UPDATE SET
                    matched=excluded.matched,
                    pending_since=excluded.pending_since,
                    last_emit=excluded.last_emit,
                    last_event_at=excluded.last_event_at,
                    field_hashes=excluded.field_hashes
                """,
                (
                    monitor_id,
                    int(bool(state.get("matched"))),
                    state.get("pending_since"),
                    state.get("last_emit"),
                    state.get("last_event_at"),
                    encoded_hashes,
                ),
            )
            db.commit()

    def append_decision(self, decision: AmbientDecision) -> None:
        with self._lock:
            db = self._require()
            self._guard_capacity(db)
            values = decision.to_dict()
            db.execute(
                """
                INSERT OR IGNORE INTO decisions(
                    decision_id, monitor_id, monitor_version, monitor_hash, event_fingerprint,
                    transition, matched, reason, decided_at, consent_generation
                    , rung, attention_mode, policy_reason
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["decision_id"],
                    values["monitor_id"],
                    values["monitor_version"],
                    values["monitor_hash"],
                    values["event_fingerprint"],
                    values["transition"],
                    int(values["matched"]),
                    values["reason"],
                    values["decided_at"],
                    values["consent_generation"],
                    values["rung"],
                    values["attention_mode"],
                    values["policy_reason"],
                ),
            )
            db.commit()

    def journal(self, *, limit: int = 1_000) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1_000))
        with self._lock:
            db = self._require()
            rows = db.execute(
                """
                SELECT decision_id, monitor_id, monitor_version, monitor_hash,
                       event_fingerprint, transition, matched, reason, decided_at,
                       consent_generation, rung, attention_mode, policy_reason
                FROM decisions ORDER BY decided_at ASC, decision_id ASC LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        output = [dict(row) for row in rows]
        for row in output:
            row["matched"] = bool(row["matched"])
        return output

    def update_source_health(
        self,
        source: str,
        *,
        status: str,
        last_event_at: float | None,
        last_error: str = "",
        queued: int = 0,
        critical_backpressure: int = 0,
    ) -> None:
        safe_error = last_error if last_error in {"", "queue_full", "adapter_failed"} else "source_error"
        with self._lock:
            db = self._require()
            db.execute(
                """
                INSERT INTO source_health(
                    source, status, last_event_at, last_error, queued,
                    critical_backpressure, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    status=excluded.status,
                    last_event_at=COALESCE(excluded.last_event_at, source_health.last_event_at),
                    last_error=excluded.last_error,
                    queued=excluded.queued,
                    critical_backpressure=excluded.critical_backpressure,
                    updated_at=excluded.updated_at
                """,
                (
                    source,
                    status,
                    last_event_at,
                    safe_error,
                    max(0, int(queued)),
                    max(0, int(critical_backpressure)),
                    self._now(),
                ),
            )
            db.commit()

    def source_health(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            db = self._require()
            rows = db.execute(
                """
                SELECT source, status, last_event_at, last_error, queued, critical_backpressure
                FROM source_health ORDER BY source
                """
            ).fetchall()
        output: dict[str, dict[str, Any]] = {}
        for row in rows:
            values = dict(row)
            source = str(values.pop("source"))
            output[source] = values
        return output

    def set_ownership(self, source: str, *, state: str, watermark: str, owner: str) -> None:
        if state not in {"legacy", "claiming", "ambient"}:
            raise ValueError("source ownership state is invalid")
        with self._lock:
            db = self._require()
            db.execute(
                """
                INSERT INTO source_ownership(source, state, watermark, owner, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    state=excluded.state, watermark=excluded.watermark,
                    owner=excluded.owner, updated_at=excluded.updated_at
                """,
                (source, state, str(watermark)[:512], owner, self._now()),
            )
            db.commit()

    def ownership(self, source: str) -> dict[str, Any]:
        with self._lock:
            db = self._require()
            row = db.execute("SELECT * FROM source_ownership WHERE source=?", (source,)).fetchone()
        if row is None:
            return {"source": source, "state": "legacy", "watermark": "", "owner": "legacy"}
        return {
            "source": row["source"],
            "state": row["state"],
            "watermark": row["watermark"],
            "owner": row["owner"],
            "updated_at": row["updated_at"],
        }

    def sweep(self) -> None:
        if self._db is None:
            return
        now = self._now()
        with self._lock:
            db = self._require()
            db.execute("DELETE FROM event_dedupe WHERE expires_at<=?", (now,))
            db.execute("DELETE FROM replay_tombstones WHERE expires_at<=?", (now,))
            db.execute("DELETE FROM decisions WHERE decided_at<?", (now - _JOURNAL_TTL,))
            db.execute("DELETE FROM source_health WHERE updated_at<?", (now - _HEALTH_TTL,))
            db.commit()

    def health(self) -> dict[str, Any]:
        if self._db is None:
            return {"status": "degraded", "reason": self._reason or "store_unavailable", "rows": 0, "bytes": self._size()}
        try:
            with self._lock:
                rows = self._row_count(self._require())
            size = self._size()
            status = "degraded" if self._reason else "ready"
            return {"status": status, "reason": self._reason, "rows": rows, "bytes": size}
        except (AmbientStoreError, OSError, sqlite3.Error):
            return {"status": "degraded", "reason": "store_unavailable", "rows": 0, "bytes": self._size()}

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None


__all__ = ["AmbientStore", "AmbientStoreError"]
