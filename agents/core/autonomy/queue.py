"""
queue.py — Autonomy Loop & Self-Tasking Queue (H6.1).

SQLite-backed task queue with a strict state machine:

    proposed → approved → running → done | failed
       │          │
       │          └→ blocked  (needs a human decision)
       └→ blocked / rejected / deferred

Hard bounds (anti-AutoGPT, from the research): retry cap, no re-entry after a
terminal state, append-only audit via the security AuditLogger (wired by the
worker). See docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from agents.core.autonomy.mediation import (
    ZERO_HASH,
    DetachedHMACSigner,
    MediationEvent,
    MediationReceipt,
    ReceiptExpectation,
    canonical_digest,
    canonical_json,
    make_event,
    verify_event_chain,
    verify_receipt,
)
from agents.core.paths import data_path

logger = logging.getLogger("jarvis.autonomy.queue")

DEFAULT_DB = data_path("autonomy.db")
MAX_ATTEMPTS = 3
_DATABASE_INIT_LOCK = threading.Lock()


class TaskStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    QUARANTINED = "quarantined"


TERMINAL = {
    TaskStatus.DONE,
    TaskStatus.FAILED,
    TaskStatus.REJECTED,
    TaskStatus.QUARANTINED,
}

# Allowed transitions. Keys/values are TaskStatus.
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PROPOSED: {
        TaskStatus.APPROVED,
        TaskStatus.BLOCKED,
        TaskStatus.REJECTED,
        TaskStatus.DEFERRED,
    },
    TaskStatus.BLOCKED: {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.DEFERRED},
    TaskStatus.DEFERRED: {TaskStatus.APPROVED, TaskStatus.BLOCKED, TaskStatus.REJECTED},
    TaskStatus.APPROVED: {TaskStatus.RUNNING, TaskStatus.BLOCKED},
    TaskStatus.RUNNING: {
        TaskStatus.DONE,
        TaskStatus.FAILED,
        TaskStatus.APPROVED,
    },  # APPROVED = retry
    # terminal states have no outgoing transitions
    TaskStatus.DONE: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.REJECTED: set(),
    TaskStatus.QUARANTINED: set(),
}


class TaskQueueError(Exception):
    """Raised on an illegal state transition."""


@dataclass
class Task:
    id: int
    agent: str
    kind: str
    title: str
    payload: dict
    risk_tier: int
    status: str
    autonomy_level: str
    # Keyword-only default keeps direct pre-H33 Task construction compatible
    # while preserving the legacy queue behavior for unsolicited decisions.
    attention_mode: str = field(default="interrupt", kw_only=True)
    origin: str  # "manual" (user-curated) | "generated" (self-proposed) | "inbound"
    attempts: int
    result: Optional[dict]
    decided_by: Optional[str]
    decision: Optional[str]
    pushed: int  # 1 if a decision card has been pushed to the inbox
    created_at: str
    updated_at: str
    mediation_enqueue_id: Optional[str] = field(default=None, kw_only=True)
    mediation_enqueue_revision: Optional[int] = field(default=None, kw_only=True)
    mediation_scope: Optional[str] = field(default=None, kw_only=True)
    mediation_policy_revision: Optional[str] = field(default=None, kw_only=True)
    mediation_receipt: Optional[dict] = field(default=None, kw_only=True)
    mediation_task_sha256: Optional[str] = field(default=None, kw_only=True)
    mediation_execution_id: Optional[str] = field(default=None, kw_only=True)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


class TaskQueue:
    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        mediation_mode: str = "off",
        mediation_signer: DetachedHMACSigner | None = None,
        mediation_classifier: Callable[[str], object] | None = None,
        mediation_scope: str = "autonomy.queue",
        mediation_policy_revision: str = "v1",
        mediation_clock_ms: Callable[[], int] | None = None,
    ):
        if db_path is None:
            # Resolve at init (not module import) so a JARVIS_HOME set *after* this
            # module was imported is honored — pytest's conftest redirects
            # JARVIS_HOME to a temp dir, but a stale module-level binding pointed a
            # test's queue at the production autonomy.db, which is how test fixtures
            # reached the live Decision Inbox (2026-07-24 QA finding). Lazy resolution
            # makes the redirect effective regardless of import order.
            default = data_path("autonomy.db")
            default.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(default)
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # Guard concurrent access; the autonomy worker calls queue methods
        # from an asyncio task running on a thread-pool thread (H7.4).
        self._lock = threading.Lock()
        mode = str(mediation_mode or "").strip().lower()
        if mode not in {"off", "enforce", "hold"}:
            raise ValueError("mediation mode must be off, enforce, or hold")
        self.mediation_mode = mode
        self._mediation_signer = mediation_signer or DetachedHMACSigner(None)
        self._mediation_classifier = mediation_classifier
        self._mediation_scope = str(mediation_scope or "").strip()
        self._mediation_policy_revision = str(mediation_policy_revision or "").strip()
        self._mediation_clock_ms = mediation_clock_ms or (lambda: int(time.time() * 1000))

    # ── lifecycle ─────────────────────────────────────────────────
    def initialize(self) -> "TaskQueue":
        with _DATABASE_INIT_LOCK:
            try:
                return self._initialize_locked()
            except Exception:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
                raise

    def _initialize_locked(self) -> "TaskQueue":
        # check_same_thread=False: queue is accessed from asyncio.to_thread
        # helpers; the threading.Lock above serialises every operation.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=30000")
        # WAL + synchronous=NORMAL: the autonomy worker commits on every task
        # state transition in a continuous loop — keep those commits cheap.
        for attempt in range(300):
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 299:
                    raise
                time.sleep(0.05)
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Serialize schema discovery and migration across processes. A
        # module-level lock only protects threads in this interpreter; without
        # a database write lock, two workers can both observe a missing legacy
        # column and race the same ALTER TABLE.
        self._conn.execute("BEGIN IMMEDIATE")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                risk_tier INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'proposed',
                autonomy_level TEXT NOT NULL DEFAULT 'ask',
                attention_mode TEXT NOT NULL DEFAULT 'interrupt',
                origin TEXT NOT NULL DEFAULT 'generated',
                attempts INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                decided_by TEXT,
                decision TEXT,
                pushed INTEGER NOT NULL DEFAULT 0,
                mediation_enqueue_id TEXT,
                mediation_enqueue_revision INTEGER,
                mediation_scope TEXT,
                mediation_policy_revision TEXT,
                mediation_receipt TEXT,
                mediation_task_sha256 TEXT,
                mediation_execution_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # H33.2: old autonomy databases predate the ask/digest/interrupt split.
        # Preserve their previous push behavior while new ambient proposals set
        # the mode explicitly.
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "attention_mode" not in columns:
            self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN attention_mode TEXT NOT NULL DEFAULT 'interrupt'"
            )
        mediation_columns = {
            "mediation_enqueue_id": "TEXT",
            "mediation_enqueue_revision": "INTEGER",
            "mediation_scope": "TEXT",
            "mediation_policy_revision": "TEXT",
            "mediation_receipt": "TEXT",
            "mediation_task_sha256": "TEXT",
            "mediation_execution_id": "TEXT",
        }
        for name, column_type in mediation_columns.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {column_type}")
        # The worker polls runnable()/pending_decisions() and the inbox calls
        # list() in a continuous loop — all filtered by status — while the table
        # grows unboundedly as decided tasks accumulate. Index status so those
        # reads stay O(log n) instead of degrading to full scans at scale.
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, id)")
        self._conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_mediation_enqueue
               ON tasks(mediation_enqueue_id)
               WHERE mediation_enqueue_id IS NOT NULL"""
        )
        had_events_table = (
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_mediation_events'"
            ).fetchone()
            is not None
        )
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_mediation_events (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                version INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                task_id INTEGER NOT NULL,
                enqueue_id TEXT NOT NULL,
                receipt_id TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                occurred_at_ms INTEGER NOT NULL,
                previous_event_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                signature TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mediation_execution_id "
            "ON task_mediation_events(execution_id) WHERE execution_id != ''"
        )
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_mediation_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                last_sequence INTEGER NOT NULL,
                last_event_hash TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                integrity_broken INTEGER NOT NULL DEFAULT 0,
                signature TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS capability_outcomes (
                capability_id TEXT PRIMARY KEY,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                last_outcome_at TEXT NOT NULL
            )
        """)
        with self._lock:
            state = self._conn.execute("SELECT * FROM task_mediation_state WHERE id=1").fetchone()
            if state is None:
                mediated_tasks = self._conn.execute(
                    "SELECT 1 FROM tasks WHERE mediation_enqueue_id IS NOT NULL LIMIT 1"
                ).fetchone()
                event = self._conn.execute("SELECT 1 FROM task_mediation_events LIMIT 1").fetchone()
                self._initialize_mediation_state_locked(
                    broken=bool(had_events_table or mediated_tasks or event),
                    uninitialized=(
                        self.mediation_mode == "off"
                        and not had_events_table
                        and not mediated_tasks
                        and not event
                    ),
                )
            elif state["integrity_broken"] == 2 and self.mediation_mode in {"enforce", "hold"}:
                event = self._conn.execute("SELECT 1 FROM task_mediation_events LIMIT 1").fetchone()
                mediated_tasks = self._conn.execute(
                    "SELECT 1 FROM tasks WHERE mediation_enqueue_id IS NOT NULL LIMIT 1"
                ).fetchone()
                self._initialize_mediation_state_locked(
                    broken=bool(event or mediated_tasks), uninitialized=False
                )
        self._conn.commit()
        if self.mediation_mode in {"enforce", "hold"}:
            self.scan_unmediated_tasks()
        return self

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── B7 mediation evidence ────────────────────────────────────
    def _classification(self, kind: str) -> bool | None:
        """Return kernel classification, or ``None`` when classification failed."""

        if self.mediation_mode == "off":
            return False
        try:
            if not callable(self._mediation_classifier):
                return None
            value = self._mediation_classifier(str(kind))
            if isinstance(value, bool):
                return value
            if value is None:
                return None
            normalized = str(value).strip().lower()
            if normalized == "kernel":
                return True
            if normalized == "direct":
                return False
            return None
        except Exception:
            return None

    def _clock_ms(self) -> int:
        try:
            value = self._mediation_clock_ms()
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("invalid mediation clock")
            return value
        except Exception as exc:
            raise TaskQueueError("mediation clock unavailable") from exc

    @staticmethod
    def _mediation_state_payload(
        *, last_sequence: int, last_event_hash: str, event_count: int, integrity_broken: int
    ) -> dict[str, object]:
        return {
            "version": 1,
            "last_sequence": last_sequence,
            "last_event_hash": last_event_hash,
            "event_count": event_count,
            "integrity_broken": integrity_broken,
        }

    def _current_mediation_head_locked(self) -> tuple[int, str, int]:
        row = self._conn.execute(
            """SELECT sequence, event_hash,
                      (SELECT COUNT(*) FROM task_mediation_events) AS event_count
                 FROM task_mediation_events
                ORDER BY sequence DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return 0, ZERO_HASH, 0
        return int(row["sequence"]), str(row["event_hash"]), int(row["event_count"])

    def _initialize_mediation_state_locked(
        self, *, broken: bool, uninitialized: bool = False
    ) -> None:
        sequence, event_hash, count = self._current_mediation_head_locked()
        payload = self._mediation_state_payload(
            last_sequence=sequence,
            last_event_hash=event_hash,
            event_count=count,
            integrity_broken=0,
        )
        signature = (
            None
            if broken or uninitialized
            else self._mediation_signer.sign(canonical_json(payload))
        )
        self._conn.execute(
            """INSERT OR REPLACE INTO task_mediation_state
                   (id, version, last_sequence, last_event_hash, event_count,
                    integrity_broken, signature)
               VALUES (1, 1, ?, ?, ?, ?, ?)""",
            (
                sequence,
                event_hash,
                count,
                2 if uninitialized else (1 if broken or signature is None else 0),
                signature or "",
            ),
        )

    def _validated_mediation_snapshot_locked(
        self,
    ) -> tuple[tuple[int, int, str, int, str], list[dict[str, object]]] | None:
        """Authenticate the global head and reconcile all executable evidence."""

        rows = self._conn.execute(
            "SELECT * FROM task_mediation_events ORDER BY sequence"
        ).fetchall()
        state = self._conn.execute("SELECT * FROM task_mediation_state WHERE id=1").fetchone()
        task_rows = self._conn.execute(
            """SELECT id, mediation_enqueue_id, mediation_execution_id
                 FROM tasks WHERE mediation_enqueue_id IS NOT NULL"""
        ).fetchall()
        if state is None or int(state["integrity_broken"]) != 0 or int(state["version"]) != 1:
            return None

        fields = MediationEvent.__dataclass_fields__
        events = [{name: row[name] for name in fields} for row in rows]
        sequence = int(rows[-1]["sequence"]) if rows else 0
        event_hash = str(rows[-1]["event_hash"]) if rows else ZERO_HASH
        event_count = len(events)
        state_payload = self._mediation_state_payload(
            last_sequence=int(state["last_sequence"]),
            last_event_hash=str(state["last_event_hash"]),
            event_count=int(state["event_count"]),
            integrity_broken=int(state["integrity_broken"]),
        )
        if not (
            int(state["last_sequence"]) == sequence
            and str(state["last_event_hash"]) == event_hash
            and int(state["event_count"]) == event_count
            and self._mediation_signer.verify(canonical_json(state_payload), state["signature"])
        ):
            return None
        if events and not verify_event_chain(self._mediation_signer, events):
            return None

        task_by_id = {int(row["id"]): row for row in task_rows}
        authorized: dict[int, list[dict[str, object]]] = {}
        governed: dict[int, list[dict[str, object]]] = {}
        for event in events:
            if event["outcome"] == "authorized_enqueue":
                authorized.setdefault(int(event["task_id"]), []).append(event)
            elif event["outcome"] == "governed":
                governed.setdefault(int(event["task_id"]), []).append(event)
        for task_id, row in task_by_id.items():
            auth_events = authorized.get(task_id, [])
            if len(auth_events) != 1 or auth_events[0]["enqueue_id"] != row["mediation_enqueue_id"]:
                return None
            execution_id = row["mediation_execution_id"]
            run_events = governed.get(task_id, [])
            if execution_id:
                if (
                    len(run_events) != 1
                    or run_events[0]["execution_id"] != execution_id
                    or run_events[0]["enqueue_id"] != row["mediation_enqueue_id"]
                ):
                    return None
            elif run_events:
                return None
        if any(task_id not in task_by_id for task_id in authorized | governed):
            return None

        token = (1, sequence, event_hash, event_count, str(state["signature"]))
        return token, events

    def _update_mediation_state_locked(
        self, previous_state: tuple[int, int, str, int, str]
    ) -> None:
        sequence, event_hash, count = self._current_mediation_head_locked()
        payload = self._mediation_state_payload(
            last_sequence=sequence,
            last_event_hash=event_hash,
            event_count=count,
            integrity_broken=0,
        )
        signature = self._mediation_signer.sign(canonical_json(payload))
        if signature is None:
            raise TaskQueueError("could not seal mediation chain head")
        updated = self._conn.execute(
            """UPDATE task_mediation_state
                  SET version=1, last_sequence=?, last_event_hash=?, event_count=?,
                      integrity_broken=0, signature=?
                WHERE id=1 AND version=? AND last_sequence=?
                  AND last_event_hash=? AND event_count=?
                  AND integrity_broken=0 AND signature=?""",
            (sequence, event_hash, count, signature, *previous_state),
        )
        if updated.rowcount != 1:
            raise TaskQueueError("mediation chain head is unavailable")

    def _mark_mediation_integrity_broken_locked(self) -> None:
        sequence, event_hash, count = self._current_mediation_head_locked()
        self._conn.execute(
            """INSERT INTO task_mediation_state
                   (id, version, last_sequence, last_event_hash, event_count,
                    integrity_broken, signature)
               VALUES (1, 1, ?, ?, ?, 1, '')
               ON CONFLICT(id) DO UPDATE SET integrity_broken=1, signature=''""",
            (sequence, event_hash, count),
        )

    @staticmethod
    def _task_binding(
        *,
        agent: str,
        kind: str,
        title: str,
        origin: str,
        scope: str,
        payload: object,
        policy_revision: str,
        enqueue_revision: int,
    ) -> dict:
        return {
            "agent": agent,
            "kind": kind,
            "title": title,
            "origin": origin,
            "scope": scope,
            "payload": payload,
            "policy_revision": policy_revision,
            "enqueue_revision": enqueue_revision,
        }

    def _append_mediation_event_locked(
        self,
        *,
        outcome: str,
        task_id: int,
        enqueue_id: str,
        receipt: MediationReceipt | Mapping[str, object] | None,
        execution_id: str = "",
        verified_state: tuple[int, int, str, int, str] | None = None,
    ) -> MediationEvent:
        if verified_state is None:
            snapshot = self._validated_mediation_snapshot_locked()
            if snapshot is None:
                raise TaskQueueError("mediation chain head is invalid")
            verified_state = snapshot[0]
        _version, last_sequence, previous_hash, _count, _signature = verified_state
        sequence = last_sequence + 1
        event = make_event(
            self._mediation_signer,
            event_id=str(uuid.uuid4()),
            sequence=sequence,
            outcome=outcome,
            task_id=task_id,
            enqueue_id=enqueue_id,
            receipt=receipt,
            execution_id=execution_id,
            occurred_at_ms=self._clock_ms(),
            previous_event_hash=previous_hash,
        )
        if event is None:
            raise TaskQueueError("could not seal mediation evidence")
        value = event.to_dict()
        self._conn.execute(
            """INSERT INTO task_mediation_events
                   (sequence, event_id, version, outcome, task_id, enqueue_id,
                    receipt_id, receipt_sha256, execution_id, occurred_at_ms,
                    previous_event_hash, event_hash, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                value["sequence"],
                value["event_id"],
                value["version"],
                value["outcome"],
                value["task_id"],
                value["enqueue_id"],
                value["receipt_id"],
                value["receipt_sha256"],
                value["execution_id"],
                value["occurred_at_ms"],
                value["previous_event_hash"],
                value["event_hash"],
                value["signature"],
            ),
        )
        self._update_mediation_state_locked(verified_state)
        return event

    def mediation_events(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM task_mediation_events ORDER BY sequence"
            ).fetchall()
        fields = MediationEvent.__dataclass_fields__
        return [{name: row[name] for name in fields} for row in rows]

    def verified_mediation_stats(self) -> dict[str, int | bool]:
        counters: dict[str, int | bool] = {
            "valid": False,
            "authorized_enqueue": 0,
            "governed": 0,
            "refused_unmediated": 0,
            "ungoverned_detected": 0,
        }
        with self._lock:
            snapshot = self._validated_mediation_snapshot_locked()
        if snapshot is None:
            return counters
        _state, events = snapshot

        counters["valid"] = True
        for event in events:
            outcome = event["outcome"]
            if outcome in counters:
                counters[outcome] = int(counters[outcome]) + 1
        return counters

    # ── writes ────────────────────────────────────────────────────
    def enqueue(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict = None,
        risk_tier: int = 3,
        autonomy_level: str = "ask",
        origin: str = "generated",
        attention_mode: str = "interrupt",
    ) -> int:
        attention_mode = str(attention_mode or "").strip().lower()
        if attention_mode not in {"none", "digest", "interrupt"}:
            raise ValueError("attention mode is invalid")
        classification = self._classification(kind)
        if self.mediation_mode in {"enforce", "hold"} and classification is not False:
            enqueue_id = str(uuid.uuid4())
            message = (
                "mediation hold refuses classified enqueue"
                if self.mediation_mode == "hold"
                else "classified task requires mediation"
            )
            with self._lock:
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    self._append_mediation_event_locked(
                        outcome="refused_unmediated",
                        task_id=0,
                        enqueue_id=enqueue_id,
                        receipt=None,
                    )
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    try:
                        self._conn.execute("BEGIN IMMEDIATE")
                        self._mark_mediation_integrity_broken_locked()
                        self._conn.commit()
                    except Exception:
                        self._conn.rollback()
            raise TaskQueueError(message)
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO tasks (agent, kind, title, payload, risk_tier, status,
                       autonomy_level, attention_mode, origin, attempts, pushed,
                       created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, ?, 0, 0, ?, ?)""",
                (
                    agent,
                    kind,
                    title,
                    json.dumps(payload or {}, ensure_ascii=False),
                    int(risk_tier),
                    autonomy_level,
                    attention_mode,
                    origin,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return cur.lastrowid

    def enqueue_mediated(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict | None = None,
        *,
        receipt: MediationReceipt | Mapping[str, object],
        autonomy_level: str = "ask",
        origin: str = "generated",
        attention_mode: str = "interrupt",
    ) -> int:
        """Insert exact task bytes, receipt, and authorization event atomically."""

        if self.mediation_mode == "hold":
            raise TaskQueueError("mediation hold refuses classified enqueue")
        if self._classification(kind) is not True:
            raise TaskQueueError("classified mediation is unavailable")
        attention_mode = str(attention_mode or "").strip().lower()
        if attention_mode not in {"none", "digest", "interrupt"}:
            raise ValueError("attention mode is invalid")
        try:
            sealed = (
                receipt
                if isinstance(receipt, MediationReceipt)
                else MediationReceipt.from_dict(receipt)
            )
            body = payload or {}
            expectation = ReceiptExpectation(
                enqueue_id=sealed.enqueue_id,
                agent=agent,
                kind=kind,
                title=title,
                origin=origin,
                scope=self._mediation_scope,
                payload=body,
                policy_revision=self._mediation_policy_revision,
                enqueue_revision=sealed.enqueue_revision,
            )
            if not verify_receipt(
                self._mediation_signer,
                sealed,
                expected=expectation,
                now_ms=self._clock_ms(),
            ):
                raise TaskQueueError("invalid mediation receipt")
            binding = self._task_binding(
                agent=agent,
                kind=kind,
                title=title,
                origin=origin,
                scope=self._mediation_scope,
                payload=body,
                policy_revision=self._mediation_policy_revision,
                enqueue_revision=sealed.enqueue_revision,
            )
            task_sha256 = canonical_digest(binding)
            receipt_json = json.dumps(
                sealed.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            payload_json = json.dumps(body, ensure_ascii=False)
        except TaskQueueError:
            raise
        except Exception as exc:
            raise TaskQueueError("invalid mediation receipt") from exc

        now = _now()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                snapshot = self._validated_mediation_snapshot_locked()
                if snapshot is None:
                    raise TaskQueueError("mediation chain head is invalid")
                verified_state = snapshot[0]
                duplicate = self._conn.execute(
                    "SELECT 1 FROM tasks WHERE mediation_enqueue_id=?",
                    (sealed.enqueue_id,),
                ).fetchone()
                if duplicate:
                    raise TaskQueueError("invalid mediation receipt: enqueue replay")
                cur = self._conn.execute(
                    """INSERT INTO tasks
                           (agent, kind, title, payload, risk_tier, status,
                            autonomy_level, attention_mode, origin, attempts, pushed,
                            mediation_enqueue_id, mediation_enqueue_revision,
                            mediation_scope, mediation_policy_revision,
                            mediation_receipt, mediation_task_sha256,
                            created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, ?, 0, 0,
                               ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        agent,
                        kind,
                        title,
                        payload_json,
                        sealed.tier,
                        autonomy_level,
                        attention_mode,
                        origin,
                        sealed.enqueue_id,
                        sealed.enqueue_revision,
                        self._mediation_scope,
                        self._mediation_policy_revision,
                        receipt_json,
                        task_sha256,
                        now,
                        now,
                    ),
                )
                task_id = int(cur.lastrowid)
                self._append_mediation_event_locked(
                    outcome="authorized_enqueue",
                    task_id=task_id,
                    enqueue_id=sealed.enqueue_id,
                    receipt=sealed,
                    verified_state=verified_state,
                )
                self._conn.commit()
                return task_id
            except TaskQueueError:
                self._conn.rollback()
                raise
            except Exception as exc:
                self._conn.rollback()
                raise TaskQueueError("could not persist mediation evidence") from exc

    def _row_receipt_and_expectation(
        self, row: sqlite3.Row
    ) -> tuple[MediationReceipt, ReceiptExpectation, str]:
        receipt = MediationReceipt.from_dict(json.loads(row["mediation_receipt"]))
        payload = json.loads(row["payload"] or "{}")
        expectation = ReceiptExpectation(
            enqueue_id=row["mediation_enqueue_id"],
            agent=row["agent"],
            kind=row["kind"],
            title=row["title"],
            origin=row["origin"],
            scope=row["mediation_scope"],
            payload=payload,
            policy_revision=row["mediation_policy_revision"],
            enqueue_revision=row["mediation_enqueue_revision"],
        )
        task_sha256 = canonical_digest(
            self._task_binding(
                agent=expectation.agent,
                kind=expectation.kind,
                title=expectation.title,
                origin=expectation.origin,
                scope=expectation.scope,
                payload=expectation.payload,
                policy_revision=expectation.policy_revision,
                enqueue_revision=expectation.enqueue_revision,
            )
        )
        return receipt, expectation, task_sha256

    def _event_chain_valid_locked(self) -> bool:
        rows = self._conn.execute(
            "SELECT * FROM task_mediation_events ORDER BY sequence"
        ).fetchall()
        if not rows:
            return False
        fields = MediationEvent.__dataclass_fields__
        events = [{name: row[name] for name in fields} for row in rows]
        return verify_event_chain(self._mediation_signer, events)

    def _quarantine_locked(
        self,
        row: sqlite3.Row,
        *,
        verified_state: tuple[int, int, str, int, str] | None = None,
    ) -> None:
        enqueue_id = row["mediation_enqueue_id"] or str(uuid.uuid4())
        self._conn.execute(
            """UPDATE tasks
                  SET status='quarantined', mediation_execution_id=NULL, updated_at=?
                WHERE id=?""",
            (_now(), row["id"]),
        )
        try:
            self._append_mediation_event_locked(
                outcome="ungoverned_detected",
                task_id=int(row["id"]),
                enqueue_id=enqueue_id,
                receipt=None,
                verified_state=verified_state,
            )
        except Exception:
            # Quarantine is the authority boundary. A missing signer must never
            # keep a suspicious row executable merely because evidence degraded.
            self._mark_mediation_integrity_broken_locked()
            logger.exception("Could not persist B7 quarantine evidence")

    def claim_mediated(self, task_id: int, *, execution_id: str) -> Optional[Task]:
        """CAS an approved mediated row to running after persisted revalidation."""

        if self.mediation_mode != "enforce":
            return None
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                snapshot = self._validated_mediation_snapshot_locked()
                if snapshot is None:
                    self._conn.rollback()
                    return None
                verified_state = snapshot[0]
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None or row["status"] != TaskStatus.APPROVED.value:
                    self._conn.rollback()
                    return None
                if self._classification(row["kind"]) is not True:
                    self._quarantine_locked(row, verified_state=verified_state)
                    self._conn.commit()
                    return None
                try:
                    receipt, expectation, current_sha256 = self._row_receipt_and_expectation(row)
                    authorized = self._conn.execute(
                        """SELECT 1 FROM task_mediation_events
                           WHERE task_id=? AND enqueue_id=?
                             AND outcome='authorized_enqueue'
                           LIMIT 1""",
                        (task_id, expectation.enqueue_id),
                    ).fetchone()
                    valid = (
                        row["mediation_execution_id"] is None
                        and int(row["risk_tier"]) == receipt.tier
                        and expectation.scope == self._mediation_scope
                        and expectation.policy_revision == self._mediation_policy_revision
                        and authorized is not None
                        and current_sha256 == row["mediation_task_sha256"]
                        and self._event_chain_valid_locked()
                        and verify_receipt(
                            self._mediation_signer,
                            receipt,
                            expected=expectation,
                            now_ms=self._clock_ms(),
                        )
                    )
                except Exception:
                    valid = False
                if not valid:
                    self._quarantine_locked(row, verified_state=verified_state)
                    self._conn.commit()
                    return None
                changed = self._conn.execute(
                    """UPDATE tasks
                          SET status='running', mediation_execution_id=?, updated_at=?
                        WHERE id=? AND status='approved'
                          AND mediation_execution_id IS NULL""",
                    (execution_id, _now(), task_id),
                )
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return None
                self._append_mediation_event_locked(
                    outcome="governed",
                    task_id=task_id,
                    enqueue_id=expectation.enqueue_id,
                    receipt=receipt,
                    execution_id=execution_id,
                    verified_state=verified_state,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                return None
        return self.get(task_id)

    def scan_unmediated_tasks(self) -> list[int]:
        """Quarantine executable classified rows without a valid B7 binding."""

        if self.mediation_mode not in {"enforce", "hold"}:
            return []
        quarantined: list[int] = []
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM tasks
                   WHERE status IN ('proposed', 'approved', 'running')
                   ORDER BY id"""
            ).fetchall()
            for row in rows:
                classification = self._classification(row["kind"])
                if classification is False:
                    continue
                valid = False
                if classification is True and row["mediation_receipt"]:
                    try:
                        receipt, expectation, current_sha256 = self._row_receipt_and_expectation(
                            row
                        )
                        authorized = self._conn.execute(
                            """SELECT 1 FROM task_mediation_events
                               WHERE task_id=? AND enqueue_id=?
                                 AND outcome='authorized_enqueue'
                               LIMIT 1""",
                            (row["id"], expectation.enqueue_id),
                        ).fetchone()
                        valid = (
                            int(row["risk_tier"]) == receipt.tier
                            and expectation.scope == self._mediation_scope
                            and expectation.policy_revision == self._mediation_policy_revision
                            and current_sha256 == row["mediation_task_sha256"]
                            and authorized is not None
                            and self._event_chain_valid_locked()
                            and verify_receipt(
                                self._mediation_signer,
                                receipt,
                                expected=expectation,
                                now_ms=self._clock_ms(),
                            )
                        )
                    except Exception:
                        valid = False
                if valid:
                    continue
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    self._quarantine_locked(row)
                    self._conn.commit()
                    quarantined.append(int(row["id"]))
                except Exception:
                    self._conn.rollback()
                    # A write failure leaves the row untouched, but claim still
                    # independently denies it under enforce and hold never claims.
                    logger.exception("Could not quarantine unmediated task %s", row["id"])
        return quarantined

    def transition(
        self,
        task_id: int,
        new_status: TaskStatus,
        *,
        decided_by: str = None,
        decision: str = None,
        result: dict = None,
    ) -> Task:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            task = _row_to_task(row) if row else None
        if task is None:
            raise TaskQueueError(f"task {task_id} not found")
        cur_status = TaskStatus(task.status)
        new_status = TaskStatus(new_status)
        if new_status not in _TRANSITIONS.get(cur_status, set()):
            raise TaskQueueError(
                f"illegal transition {cur_status.value} → {new_status.value} (task {task_id})"
            )
        sets = ["status=?", "updated_at=?"]
        params: list = [new_status.value, _now()]
        if decided_by is not None:
            sets.append("decided_by=?")
            params.append(decided_by)
        if decision is not None:
            sets.append("decision=?")
            params.append(decision)
        if result is not None:
            sets.append("result=?")
            params.append(json.dumps(result, ensure_ascii=False))
        params.append(task_id)
        with self._lock:
            # Column names come from the fixed list above; all values stay parameterized.
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id=?",  # nosec B608
                params,
            )
            self._conn.commit()
        return self.get(task_id)

    def update_payload(self, task_id: int, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET payload=?, updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), _now(), task_id),
            )
            self._conn.commit()

    def update_payload_policy(
        self,
        task_id: int,
        payload: dict,
        *,
        risk_tier: int,
        autonomy_level: str,
    ) -> Task:
        """Atomically replace execution bytes and their durable policy result."""

        with self._lock:
            self._conn.execute(
                """UPDATE tasks
                      SET payload=?, risk_tier=?, autonomy_level=?, updated_at=?
                    WHERE id=?""",
                (
                    json.dumps(payload, ensure_ascii=False),
                    int(risk_tier),
                    autonomy_level,
                    _now(),
                    task_id,
                ),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskQueueError(f"task {task_id} not found")
        return _row_to_task(row)

    def increment_attempts(self, task_id: int) -> int:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET attempts = attempts + 1, updated_at=? WHERE id=?",
                (_now(), task_id),
            )
            self._conn.commit()
        return self.get(task_id).attempts

    def mark_pushed(self, task_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET pushed=1, updated_at=? WHERE id=?", (_now(), task_id)
            )
            self._conn.commit()

    def record_capability_outcome(self, capability_id: str, *, success: bool) -> None:
        """Durably add one real terminal execution outcome for a capability."""
        capability_id = str(capability_id or "").strip()
        if not capability_id:
            return
        succeeded, failed = (1, 0) if success else (0, 1)
        now = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO capability_outcomes
                       (capability_id, successes, failures, last_outcome_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(capability_id) DO UPDATE SET
                       successes = successes + excluded.successes,
                       failures = failures + excluded.failures,
                       last_outcome_at = excluded.last_outcome_at""",
                (capability_id, succeeded, failed, now),
            )
            self._conn.commit()

    # ── reads ─────────────────────────────────────────────────────
    def get(self, task_id: int) -> Optional[Task]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list(
        self, status: Optional[str] = None, origin: Optional[str] = None, limit: int = 100
    ) -> list[Task]:
        clauses, params = [], []
        if status:
            clauses.append("status=?")
            params.append(status)
        if origin:
            clauses.append("origin=?")
            params.append(origin)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                # `where` contains only the fixed status/origin clauses above.
                f"SELECT * FROM tasks {where} ORDER BY id DESC LIMIT ?",  # nosec B608
                params,
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def reap_stuck_running(self, ttl_seconds: float, *, now: Optional[float] = None) -> list[Task]:
        """Fail tasks stranded in RUNNING past ``ttl_seconds`` (crash mid-task).

        A worker crash between the RUNNING transition and the terminal one
        strands the task: ``runnable()`` selects APPROVED only, so nothing ever
        picks it back up. ``updated_at`` is stamped by the RUNNING transition
        (and again by ``increment_attempts`` moments later), so it is the
        run-start marker. In-process hangs are already bounded by the executor's
        wall-time budget — this reaper exists for dead processes.
        """
        ts = float(now) if now is not None else time.time()
        cutoff = datetime.fromtimestamp(
            ts - max(0.0, float(ttl_seconds)), tz=timezone.utc
        ).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status='running' AND updated_at < ? ORDER BY id ASC",
                (cutoff,),
            ).fetchall()
        reaped: list[Task] = []
        for task in (_row_to_task(r) for r in rows):
            reaped.append(
                self.transition(
                    task.id,
                    TaskStatus.FAILED,
                    result={
                        "error": "stuck_running_ttl",
                        "ttl_seconds": float(ttl_seconds),
                        "stuck_since": task.updated_at,
                    },
                )
            )
        return reaped

    def runnable(self, limit: int = 10, max_tier: Optional[int] = None) -> list[Task]:
        """Approved tasks that have not exhausted their retry budget.

        `max_tier` (optional) caps the risk tier — the night shift passes 1 to
        batch only reversible/read-only work.
        """
        clause = "status='approved' AND attempts < ?"
        params: list = [MAX_ATTEMPTS]
        if max_tier is not None:
            clause += " AND risk_tier <= ?"
            params.append(int(max_tier))
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                # `clause` contains only fixed retry/tier predicates.
                f"SELECT * FROM tasks WHERE {clause} ORDER BY id ASC LIMIT ?",  # nosec B608
                params,
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def pending_decisions(self, only_unpushed: bool = False, limit: int = 100) -> list[Task]:
        # O26-P0.7 (F3): a 'proposed' task also awaits a human decision
        # (PROPOSED -> APPROVED is a legal apply_decision transition) — before
        # this, broker-originated proposals never appeared in the decision
        # inbox (Telegram or HUD), only in the raw task list.
        clause = "status IN ('blocked','proposed')"
        if only_unpushed:
            clause += " AND pushed=0"
        with self._lock:
            rows = self._conn.execute(
                # `clause` is one of the two fixed pending-decision predicates.
                f"SELECT * FROM tasks WHERE {clause} ORDER BY id ASC LIMIT ?",  # nosec B608
                (limit,),
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def capability_outcome_stats(self, capability_id: str) -> dict:
        capability_id = str(capability_id or "").strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM capability_outcomes WHERE capability_id=?",
                (capability_id,),
            ).fetchone()
        return _outcome_stats(capability_id, row)

    def all_capability_outcome_stats(self) -> dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM capability_outcomes ORDER BY capability_id"
            ).fetchall()
        return {row["capability_id"]: _outcome_stats(row["capability_id"], row) for row in rows}


# ── helpers ───────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    """95% Wilson lower bound; small samples never look more certain than they are."""
    if total <= 0:
        return 0.0
    rate = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = rate + z2 / (2.0 * total)
    margin = z * math.sqrt((rate * (1.0 - rate) / total) + z2 / (4.0 * total * total))
    return max(0.0, min(1.0, (centre - margin) / denominator))


def _outcome_stats(capability_id: str, row) -> dict:
    successes = int(row["successes"]) if row is not None else 0
    failures = int(row["failures"]) if row is not None else 0
    total = successes + failures
    return {
        "capability_id": capability_id,
        "successes": successes,
        "failures": failures,
        "total": total,
        "success_rate": round(successes / total, 6) if total else 0.0,
        "confidence": round(_wilson_lower_bound(successes, total), 6),
        "last_outcome_at": row["last_outcome_at"] if row is not None else None,
    }


def _row_to_task(row: sqlite3.Row) -> Task:
    receipt = None
    if row["mediation_receipt"]:
        try:
            receipt = json.loads(row["mediation_receipt"])
        except (TypeError, ValueError, json.JSONDecodeError):
            receipt = None
    return Task(
        id=row["id"],
        agent=row["agent"],
        kind=row["kind"],
        title=row["title"],
        payload=json.loads(row["payload"] or "{}"),
        risk_tier=row["risk_tier"],
        status=row["status"],
        autonomy_level=row["autonomy_level"],
        attention_mode=row["attention_mode"],
        origin=row["origin"],
        attempts=row["attempts"],
        result=json.loads(row["result"]) if row["result"] else None,
        decided_by=row["decided_by"],
        decision=row["decision"],
        pushed=row["pushed"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        mediation_enqueue_id=row["mediation_enqueue_id"],
        mediation_enqueue_revision=row["mediation_enqueue_revision"],
        mediation_scope=row["mediation_scope"],
        mediation_policy_revision=row["mediation_policy_revision"],
        mediation_receipt=receipt,
        mediation_task_sha256=row["mediation_task_sha256"],
        mediation_execution_id=row["mediation_execution_id"],
    )
