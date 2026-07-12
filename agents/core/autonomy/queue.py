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
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.autonomy.queue")

DEFAULT_DB = data_path("autonomy.db")
MAX_ATTEMPTS = 3


class TaskStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"
    DEFERRED = "deferred"


TERMINAL = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.REJECTED}

# Allowed transitions. Keys/values are TaskStatus.
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PROPOSED: {TaskStatus.APPROVED, TaskStatus.BLOCKED, TaskStatus.REJECTED, TaskStatus.DEFERRED},
    TaskStatus.BLOCKED: {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.DEFERRED},
    TaskStatus.DEFERRED: {TaskStatus.APPROVED, TaskStatus.BLOCKED, TaskStatus.REJECTED},
    TaskStatus.APPROVED: {TaskStatus.RUNNING, TaskStatus.BLOCKED},
    TaskStatus.RUNNING: {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.APPROVED},  # APPROVED = retry
    # terminal states have no outgoing transitions
    TaskStatus.DONE: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.REJECTED: set(),
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
    origin: str            # "manual" (user-curated) | "generated" (self-proposed) | "inbound"
    attempts: int
    result: Optional[dict]
    decided_by: Optional[str]
    decision: Optional[str]
    pushed: int            # 1 if a decision card has been pushed to the inbox
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


class TaskQueue:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(DEFAULT_DB)
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # Guard concurrent access; the autonomy worker calls queue methods
        # from an asyncio task running on a thread-pool thread (H7.4).
        self._lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────
    def initialize(self) -> "TaskQueue":
        # check_same_thread=False: queue is accessed from asyncio.to_thread
        # helpers; the threading.Lock above serialises every operation.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL + synchronous=NORMAL: the autonomy worker commits on every task
        # state transition in a continuous loop — keep those commits cheap.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
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
                origin TEXT NOT NULL DEFAULT 'generated',
                attempts INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                decided_by TEXT,
                decision TEXT,
                pushed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # The worker polls runnable()/pending_decisions() and the inbox calls
        # list() in a continuous loop — all filtered by status — while the table
        # grows unboundedly as decided tasks accumulate. Index status so those
        # reads stay O(log n) instead of degrading to full scans at scale.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, id)"
        )
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS capability_outcomes (
                capability_id TEXT PRIMARY KEY,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                last_outcome_at TEXT NOT NULL
            )
        """)
        self._conn.commit()
        return self

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── writes ────────────────────────────────────────────────────
    def enqueue(self, agent: str, kind: str, title: str, payload: dict = None,
                risk_tier: int = 3, autonomy_level: str = "ask",
                origin: str = "generated") -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO tasks (agent, kind, title, payload, risk_tier, status,
                       autonomy_level, origin, attempts, pushed, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, 0, 0, ?, ?)""",
                (agent, kind, title, json.dumps(payload or {}, ensure_ascii=False),
                 int(risk_tier), autonomy_level, origin, now, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def transition(self, task_id: int, new_status: TaskStatus, *,
                   decided_by: str = None, decision: str = None,
                   result: dict = None) -> Task:
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
            sets.append("decided_by=?"); params.append(decided_by)
        if decision is not None:
            sets.append("decision=?"); params.append(decision)
        if result is not None:
            sets.append("result=?"); params.append(json.dumps(result, ensure_ascii=False))
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

    def list(self, status: Optional[str] = None, origin: Optional[str] = None,
             limit: int = 100) -> list[Task]:
        clauses, params = [], []
        if status:
            clauses.append("status=?"); params.append(status)
        if origin:
            clauses.append("origin=?"); params.append(origin)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                # `where` contains only the fixed status/origin clauses above.
                f"SELECT * FROM tasks {where} ORDER BY id DESC LIMIT ?",  # nosec B608
                params,
            ).fetchall()
        return [_row_to_task(r) for r in rows]

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
    return Task(
        id=row["id"], agent=row["agent"], kind=row["kind"], title=row["title"],
        payload=json.loads(row["payload"] or "{}"),
        risk_tier=row["risk_tier"], status=row["status"],
        autonomy_level=row["autonomy_level"], origin=row["origin"],
        attempts=row["attempts"],
        result=json.loads(row["result"]) if row["result"] else None,
        decided_by=row["decided_by"], decision=row["decision"],
        pushed=row["pushed"], created_at=row["created_at"], updated_at=row["updated_at"],
    )
