"""work_runs.py — the durable ledger a company-mode work run is made of.

Nerva's night shift already runs *tasks*. A **work run** is the unit above that:
one owner-approved goal, worked continuously across many turns, sessions and
reboots, with every step it took and every claim it makes written down.

This module is the ledger only. It plans nothing, decides nothing and actuates
nothing — the supervisor drives it, the verifier and judge grade it, and the
privileged effects still leave through the task queue and the Action Kernel.

Governance (MOONSHOT §5):

* **A run cannot start itself.** ``open_run`` requires a ``GoalSpec`` whose
  ``approved_by`` ref is set — i.e. a goal the owner accepted. An unapproved
  goal raises :class:`WorkRunError`; there is no "provisional" mode.
* **The ledger never widens authority.** It records steps that other governed
  paths already took: a step carries the durable ``task_id`` of the queue row
  that did the work, so "the run did X" is always traceable to an approved task.
  ``delegated_execution_only`` in the contract registry means exactly this.
* **Claims are separated from evidence.** A step records what was attempted and
  what came back; whether the run actually achieved its goal is a *verdict*,
  written only by the verifier/judge through :meth:`WorkRunLedger.record_verdict`.
  Nothing in this module can mark a run ``succeeded`` on its own say-so.
* **Budgets are hard.** Steps, seconds (minus bounded proven approval waits) and owner-visible interrupts
  are capped by the goal's budget; the ledger refuses the step that would exceed
  one and marks the run ``exhausted`` rather than quietly continuing.
* **A stop is honoured immediately.** ``request_stop`` is a one-way door: a
  stopping run accepts no further steps, whatever else is in flight.
* **A barrier parks, it never grants (H464).** A run waiting on real async work
  — a process, a trigger, a wall-clock time — carries a ``barrier`` the scheduler
  and supervisor read to skip it without spending a step. Setting and clearing
  one are *events* (``run_events``), never steps, so parking costs no budget; the
  column is outside the fingerprint, so parking is not tampering; and any move to
  ``stopping`` or a terminal status clears it in the same write, so a stop always
  wins. Validation and probing live in :mod:`agents.core.autonomy.run_barriers`;
  this module only stores, and re-checks the bounds under its own lock.

Runtime flag: ``JARVIS_COMPANY_MODE`` (default off). Off, nothing in this module
is constructed by the runtime; the ledger itself stays usable in tests and in a
future opt-in, which is why it reads the flag but never *enforces* on it — a
disabled feature that silently half-works is worse than one that is simply off,
so the supervisor owns the flag check and this module owns the invariants.

Persistence: SQLite WAL at ``data_path('work_runs.db')`` (never CWD), one
``threading.Lock`` per store, a strict status transition table, schema versioned
through ``persistence.migrations``. Every row carries a canonical-JSON SHA-256
fingerprint, so a hand-edited row is detectable on read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.core.paths import data_path
from agents.core.persistence.migrations import apply_migrations, column_adder

logger = logging.getLogger("jarvis.work_runs")

KIND = "work.run"
FLAG = "JARVIS_COMPANY_MODE"

_DEFAULT_DB = "work_runs.db"

# ── vocabulary ───────────────────────────────────────────────────────────────

RUN_STATUSES = (
    "planning",    # the goal is open, no step has been taken yet
    "working",     # at least one step has been recorded
    "blocked",     # waiting on the owner (a durable ask is outstanding)
    "stopping",    # a stop was requested; no further step is accepted
    "succeeded",   # the judge accepted the run against its goal
    "failed",      # the judge rejected it, or a step failed terminally
    "exhausted",   # a budget ran out before a verdict
    "stopped",     # the owner stopped it
)

# Strict transition table. Terminal states have no outgoing edges: a finished run
# is a record, never a resource to reopen — a follow-on is a new run on a new goal.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "planning": frozenset({"working", "blocked", "stopping", "exhausted", "failed", "stopped"}),
    "working": frozenset({"blocked", "stopping", "succeeded", "failed", "exhausted", "stopped"}),
    "blocked": frozenset({"working", "stopping", "failed", "exhausted", "stopped"}),
    "stopping": frozenset({"stopped", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "exhausted": frozenset(),
    "stopped": frozenset(),
}

TERMINAL_STATUSES = frozenset(
    status for status, onward in _TRANSITIONS.items() if not onward
)

# The terminal statuses in a fixed order, plus the two queries that select around
# them, written out as whole literals. Interpolating the placeholders would be safe
# — every value is a module constant and each is still bound as a parameter — but a
# query assembled from an f-string reads exactly like an injectable one, to a human
# and to the SAST gate alike. The guard below keeps the literals in step, so adding
# a terminal status fails at import rather than silently widening what "active"
# means.
_TERMINAL_ORDER: tuple[str, ...] = tuple(sorted(TERMINAL_STATUSES))
_SQL_OPEN_FOR_GOAL = (
    "SELECT id FROM runs WHERE goal_id = ? "
    "AND status NOT IN (?, ?, ?, ?) LIMIT 1"
)
_SQL_ACTIVE_RUNS = (
    "SELECT * FROM runs WHERE status NOT IN (?, ?, ?, ?) "
    "ORDER BY updated_at DESC LIMIT ?"
)
if _SQL_OPEN_FOR_GOAL.count("?") != len(_TERMINAL_ORDER) + 1:
    raise RuntimeError(
        "work-run terminal statuses changed; update the placeholders in the queries above"
    )

STEP_OUTCOMES = ("ok", "failed", "refused", "queued")

# A verdict may only be written by these roles, and only one verdict per role
# per run: the verifier says whether the evidence holds, the judge says whether
# the goal was met. Neither role may write the other's verdict.
VERDICT_ROLES = ("verifier", "judge")

_MAX_TEXT = 2_000
_MAX_SUMMARY = 500

# H464 — what a run may be parked on. The validation and the probes live in
# run_barriers.py; the ledger keeps the vocabulary and the hard bounds so it can
# re-check them under its own lock rather than trusting its caller.
BARRIER_KINDS = ("pid", "trigger", "deadline")
MAX_BARRIERS_PER_RUN = 50            # barrier.set events per run, then refuse
_MAX_BARRIER_BYTES = 2_048
_PARKABLE = frozenset({"planning", "working"})
BARRIER_SOURCES = ("planner", "judge", "hub")
BARRIER_CLEAR_REASONS = (
    "elapsed", "exited", "pid_reused", "ns_mismatch", "fired", "vanished", "cap",
    "probe_error", "owner", "replaced", "budget_spent",
)
BARRIER_CLEARED_BY = ("check", "owner", "ledger", "scheduler")


def _exceeded(run: WorkRun, moment: float, *, credit: float = 0.0) -> str | None:
    """The FIRST spent limit — steps, then seconds, then deadline, then interrupts.

    A free function so a caller already holding the lock can ask without
    re-entering ``get`` (the lock is not re-entrant)."""
    if run.steps_used >= run.budget.max_steps:
        return "steps"
    if max(0.0, run.seconds_used(moment) - credit) >= run.budget.max_seconds:
        return "seconds"
    if run.deadline_at and moment >= run.deadline_at:
        return "deadline"
    if run.interrupts_used > run.budget.max_interrupts:
        return "interrupts"
    return None


class WorkRunError(RuntimeError):
    """A refusal from the ledger. ``reason`` is a bounded, public code."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "work_run_refused")
        super().__init__(self.reason)


def _load(raw: Any) -> dict[str, Any]:
    """A stored JSON object, or an empty one. A corrupt detail blob must not make
    a step unreadable: the outcome is the fact that matters, and losing the whole
    row to a bad blob would lose it."""
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _text(value: Any, field_name: str, *, max_chars: int = _MAX_TEXT, required: bool = True) -> str:
    out = str(value or "").strip()
    if required and not out:
        raise WorkRunError(f"missing_{field_name}")
    return out[:max_chars]


@dataclass(frozen=True)
class Budget:
    """What one run may spend before the ledger stops it.

    ``max_interrupts`` is the owner's attention, not a machine resource: it is the
    number of times this run may reach past the digest and interrupt a person.
    Zero means the run may never interrupt — it can still block and wait.
    """

    max_steps: int = 50
    max_seconds: float = 8 * 3600.0
    max_interrupts: int = 2

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise WorkRunError("invalid_max_steps")
        if self.max_seconds <= 0:
            raise WorkRunError("invalid_max_seconds")
        if self.max_interrupts < 0:
            raise WorkRunError("invalid_max_interrupts")

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_seconds": self.max_seconds,
            "max_interrupts": self.max_interrupts,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> Budget:
        raw = dict(payload or {})
        return cls(
            max_steps=int(raw.get("max_steps", 50)),
            max_seconds=float(raw.get("max_seconds", 8 * 3600.0)),
            max_interrupts=int(raw.get("max_interrupts", 2)),
        )


@dataclass(frozen=True)
class WorkRun:
    """One owner-approved goal being worked. Immutable; the ledger returns copies."""

    id: str
    goal_id: str
    title: str
    status: str
    approved_by: str
    budget: Budget
    steps_used: int = 0
    interrupts_used: int = 0
    started_at: float = 0.0
    updated_at: float = 0.0
    deadline_at: float = 0.0
    stop_reason: str = ""
    fingerprint: str = ""
    # H464: what the run is parked on, or None. Deliberately NOT in identity():
    # parking and un-parking are ordinary life, and fingerprinting them would make
    # every set or clear read as a hand-edited row.
    barrier: dict[str, Any] | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def seconds_used(self, now: float) -> float:
        return max(0.0, float(now) - self.started_at)

    def identity(self) -> dict[str, Any]:
        """The fields the fingerprint covers — what a tamper must not change."""
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "title": self.title,
            "approved_by": self.approved_by,
            "budget": self.budget.as_dict(),
            "started_at": self.started_at,
            "deadline_at": self.deadline_at,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.identity(),
            "status": self.status,
            "steps_used": self.steps_used,
            "interrupts_used": self.interrupts_used,
            "updated_at": self.updated_at,
            "stop_reason": self.stop_reason,
            "fingerprint": self.fingerprint,
            "barrier": dict(self.barrier) if self.barrier else None,
        }


@dataclass(frozen=True)
class Step:
    """One thing the run did, and the durable task that was authorised to do it."""

    seq: int
    run_id: str
    kind: str
    summary: str
    outcome: str
    task_id: int | None
    interrupted: bool
    at: float
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "run_id": self.run_id,
            "kind": self.kind,
            "summary": self.summary,
            "outcome": self.outcome,
            "task_id": self.task_id,
            "interrupted": self.interrupted,
            "at": self.at,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class ExpiryAskSettlement:
    settled: bool
    first_settlement: bool
    resumed: bool
    note: str


@dataclass(frozen=True)
class Verdict:
    """A graded judgement about a run, written by the verifier or the judge."""

    run_id: str
    role: str
    passed: bool
    reason: str
    evidence: tuple[str, ...]
    at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "passed": self.passed,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "at": self.at,
        }


# ── schema ───────────────────────────────────────────────────────────────────

def _v1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id              TEXT PRIMARY KEY,
            goal_id         TEXT NOT NULL,
            title           TEXT NOT NULL,
            status          TEXT NOT NULL,
            approved_by     TEXT NOT NULL,
            budget          TEXT NOT NULL,
            steps_used      INTEGER NOT NULL DEFAULT 0,
            interrupts_used INTEGER NOT NULL DEFAULT 0,
            started_at      REAL NOT NULL,
            updated_at      REAL NOT NULL,
            deadline_at     REAL NOT NULL,
            stop_reason     TEXT NOT NULL DEFAULT '',
            fingerprint     TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS runs_status ON runs (status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS runs_goal ON runs (goal_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS steps (
            seq         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT NOT NULL,
            kind        TEXT NOT NULL,
            summary     TEXT NOT NULL,
            outcome     TEXT NOT NULL,
            task_id     INTEGER,
            interrupted INTEGER NOT NULL DEFAULT 0,
            at          REAL NOT NULL,
            detail      TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS steps_run ON steps (run_id, seq)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS verdicts (
            run_id   TEXT NOT NULL,
            role     TEXT NOT NULL,
            passed   INTEGER NOT NULL,
            reason   TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '[]',
            at       REAL NOT NULL,
            PRIMARY KEY (run_id, role)
        )
        """
    )


def _v2(conn: sqlite3.Connection) -> None:
    """H464 — the barrier column, the event log that audits it, and the processes a
    run may wait on. Idempotent against a DB that already carries any of them."""
    column_adder("runs", "barrier", "TEXT NOT NULL DEFAULT ''")(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_events (
            seq    INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            kind   TEXT NOT NULL,
            at     REAL NOT NULL,
            detail TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS run_events_run ON run_events (run_id, seq)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_procs (
            run_id TEXT NOT NULL,
            pid    INTEGER NOT NULL,
            start  TEXT NOT NULL,
            ns     TEXT NOT NULL,
            boot   TEXT NOT NULL,
            label  TEXT NOT NULL DEFAULT '',
            at     REAL NOT NULL,
            PRIMARY KEY (run_id, pid, start)
        )
        """
    )


def _v3(conn: sqlite3.Connection) -> None:
    # Private causal marker, outside owner authority/fingerprint bytes.
    column_adder("runs", "approval_block_seq", "INTEGER")(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS steps_task_ask ON steps (task_id, outcome, seq)")


def _v4(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS approval_wait_epochs (
        run_id TEXT NOT NULL, marker INTEGER NOT NULL, metadata TEXT NOT NULL,
        PRIMARY KEY(run_id, marker))""")


MIGRATIONS = [_v1, _v2, _v3, _v4]


# ── the ledger ───────────────────────────────────────────────────────────────

class WorkRunLedger:
    """The durable record of every company-mode run.

    ``clock`` is injectable so budget and deadline behaviour is testable without
    sleeping. Nothing here reads the environment: the caller owns the flag.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path) if path is not None else data_path(_DEFAULT_DB)
        self._clock = clock
        self._approval_task_reader = None
        self._lock = threading.Lock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        apply_migrations(self._conn, MIGRATIONS, name="work_runs")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _now(self) -> float:
        return float(self._clock())

    def bind_approval_task_reader(self, reader: Callable[[int], Any] | None) -> None:
        """Internal runtime seam; absent proof retains wall-time budgeting."""
        if reader is not None and not callable(reader):
            raise TypeError("approval task reader must be callable")
        self._approval_task_reader = reader

    def _approval_tasks(self, run_id: str, *, extra: int | None = None) -> dict:
        # Never hold the ledger lock while entering another SQLite store.
        reader = self._approval_task_reader
        if reader is None:
            return {}
        with self._lock:
            ids = {r[0] for r in self._conn.execute(
                "SELECT task_id FROM steps WHERE run_id=? AND task_id IS NOT NULL LIMIT 1000",
                (run_id,)).fetchall()}
        if extra is not None:
            ids.add(extra)
        tasks = {'_observed': {}}
        for tid in ids:
            observed = self._now()
            try:
                tasks[tid] = reader(tid)
                tasks['_observed'][tid] = observed
            except Exception:
                tasks[tid] = None
        return tasks

    @staticmethod
    def _wait_identity(task: Any) -> tuple[str, str] | None:
        from .queue import Task
        if type(task) is not Task:
            return None
        try:
            # Decision and execution bookkeeping change after the original intent.
            fields = ('id', 'agent', 'kind', 'title', 'payload', 'risk_tier',
                      'autonomy_level', 'attention_mode', 'origin', 'created_at',
                      'mediation_enqueue_id', 'mediation_enqueue_revision',
                      'mediation_scope', 'mediation_policy_revision', 'mediation_receipt',
                      'mediation_task_sha256', 'kernel_intake_id', 'kernel_intake_evidence',
                      'approval_deadline_at')
            intent = json.dumps({k: getattr(task, k) for k in fields}, sort_keys=True,
                                separators=(',', ':'), allow_nan=False)
            birth = json.dumps([task.id, task.created_at, task.mediation_enqueue_id,
                                task.mediation_receipt], sort_keys=True, allow_nan=False)
            return hashlib.sha256(birth.encode()).hexdigest(), hashlib.sha256(intent.encode()).hexdigest()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _wait_timestamp(stamp: Any) -> float | None:
        from .queue import normalize_approval_deadline
        try:
            normalized = normalize_approval_deadline(stamp)
            return datetime.fromisoformat(normalized).timestamp() if normalized else None
        except (ValueError, TypeError, OverflowError):
            return None

    @staticmethod
    def _wait_encode(meta: dict) -> str:
        payload = dict(meta)
        payload.pop('checksum', None)
        payload['checksum'] = _fingerprint(payload)
        return _canonical(payload)

    @staticmethod
    def _wait_decode(blob: str) -> dict:
        meta = json.loads(blob)
        if not isinstance(meta, dict):
            raise ValueError('invalid wait metadata')
        checksum = meta.pop('checksum', None)
        if checksum != _fingerprint(meta):
            raise ValueError('corrupt wait metadata')
        return meta

    def _wait_credit_locked(self, run: WorkRun, now: float, tasks: dict) -> float:
        """Refresh bounded union windows in the caller's settlement transaction."""
        if self._approval_task_reader is None or not math.isfinite(now) or now < run.started_at:
            return 0.0
        run_row = self._conn.execute('SELECT approval_block_seq FROM runs WHERE id=?', (run.id,)).fetchone()
        marker = run_row[0]
        rows = self._conn.execute('SELECT * FROM approval_wait_epochs WHERE run_id=? ORDER BY marker',
                                  (run.id,)).fetchall()
        windows = []
        seen = set()
        for row in rows:
            seen.add(row['marker'])
            try:
                meta = self._wait_decode(row['metadata'])
                start, last = meta['start'], meta['last']
                if (type(start) not in (int, float) or type(last) not in (int, float)
                        or not math.isfinite(start) or not math.isfinite(last)
                        or not run.started_at <= start <= last <= start + 360
                        or type(meta['closed']) is not bool or not isinstance(meta['sources'], list)
                        or not 1 <= len(meta['sources']) <= 1000):
                    raise ValueError('invalid wait metadata')
                intervals = []
                active = False
                for source in meta['sources']:
                    step = self._conn.execute('SELECT * FROM steps WHERE run_id=? AND seq=?',
                                              (run.id, source['seq'])).fetchone()
                    if (type(source['seq']) is not int or type(source['task']) is not int
                            or step is None or step['seq'] < row['marker'] or step['task_id'] != source['task']
                            or not start <= source['start'] <= source['last'] <= last
                            or not all(isinstance(source[k], str) and len(source[k]) == 64
                                       for k in ('birth', 'intent'))
                            or (source.get('deadline') is not None and
                                (type(source['deadline']) not in (int, float)
                                 or not math.isfinite(source['deadline'])
                                 or source['deadline'] < source['start']))):
                        raise ValueError('invalid wait source')
                    end = source['end']
                    if end is not None and (type(end) not in (int, float) or not math.isfinite(end)
                                            or not source['start'] <= end <= start + 360):
                        raise ValueError('invalid wait end')
                    if end is None:
                        task = tasks.get(source['task'])
                        identity = self._wait_identity(task)
                        metadata = getattr(task, 'human_decision', None)
                        stamp = None
                        if identity and identity[0] == source['birth']:
                            if getattr(task, 'status', '') == 'expired':
                                stamp = self._wait_timestamp(task.expired_at)
                            elif isinstance(metadata, dict) and metadata.get('action') in {'accept', 'reject', 'edit', 'defer'}:
                                stamp = self._wait_timestamp(metadata.get('first_at'))
                        if stamp is not None and identity == (source['birth'], source['intent']):
                            end = max(source['start'], min(stamp, now, start + 360,
                                                          source.get('deadline') or start + 360))
                        elif (not meta['closed'] and marker == row['marker'] and run.status == 'blocked'
                              and not run.stop_reason and not run.barrier and now >= last
                              and identity == (source['birth'], source['intent'])
                              and getattr(task, 'status', '') == 'blocked'
                              and getattr(task, 'autonomy_level', '') == 'ask'
                              and step['outcome'] == 'queued'):
                            deadline = self._wait_timestamp(task.approval_deadline_at)
                            observed = tasks.get('_observed', {}).get(source['task'], source['last'])
                            end_at = min(now, observed, start + 360, deadline if deadline is not None else now)
                            source['last'] = max(source['start'], end_at)
                            if (deadline is not None and now >= deadline) or now >= start + 360:
                                end = source['last']
                            else:
                                active = True
                        else:
                            end = source['last']
                        source['end'] = end
                    intervals.append((source['start'], min(now, end if end is not None else source['last'])))
                meta['last'] = max(last, max(s['last'] for s in meta['sources']))
                meta['observed'] = max(meta.get('observed', last), now)
                meta['closed'] = meta['closed'] or not active
                self._conn.execute('UPDATE approval_wait_epochs SET metadata=? WHERE run_id=? AND marker=?',
                                   (self._wait_encode(meta), run.id, row['marker']))
                windows.extend(intervals)
            except (ValueError, TypeError, KeyError, OverflowError):
                # Persistently disable corrupt epochs: later reads cannot reopen them.
                continue
        if (marker is not None and run.status == 'blocked' and not run.stop_reason and not run.barrier):
            if marker not in seen:
                sources = []
                for step in self._conn.execute("SELECT * FROM steps WHERE run_id=? AND seq>=? AND outcome='queued' LIMIT 1000",
                                               (run.id, marker)).fetchall():
                    task = tasks.get(step['task_id'])
                    identity = self._wait_identity(task)
                    if (identity and task.status == 'blocked' and task.autonomy_level == 'ask'
                            and math.isfinite(step['at']) and run.started_at <= step['at'] <= now
                            and not task.human_decision
                            and (task.approval_deadline_at is None or
                                 (self._wait_timestamp(task.approval_deadline_at) is not None
                                  and self._wait_timestamp(task.approval_deadline_at) > now))):
                        # New windows begin only at actual enqueue, not retrospective reads.
                        if step['at'] != now:
                            continue
                        sources.append({"seq": step['seq'], "task": step['task_id'], "birth": identity[0],
                                            "intent": identity[1], "start": now, "last": now, "end": None,
                                            "deadline": self._wait_timestamp(task.approval_deadline_at)})
                if sources:
                    meta = {"start": now, "last": now, "observed": now, "closed": False, "sources": sources}
                    self._conn.execute('INSERT INTO approval_wait_epochs VALUES(?,?,?)',
                                       (run.id, marker, self._wait_encode(meta)))
            else:
                # Attach newly queued sources to an existing open union without renewing its cap.
                existing = self._conn.execute('SELECT metadata FROM approval_wait_epochs WHERE run_id=? AND marker=?',
                                              (run.id, marker)).fetchone()
                try:
                    meta = self._wait_decode(existing[0])
                    if not meta['closed'] and meta['start'] <= now < meta['start'] + 360:
                        known = {s['seq'] for s in meta['sources']}
                        for step in self._conn.execute("SELECT * FROM steps WHERE run_id=? AND seq>=? AND outcome='queued' AND at=? LIMIT 1000",
                                                       (run.id, marker, now)).fetchall():
                            task = tasks.get(step['task_id'])
                            identity = self._wait_identity(task)
                            if (step['seq'] not in known and identity and task.status == 'blocked'
                                    and task.autonomy_level == 'ask' and not task.human_decision
                            and (task.approval_deadline_at is None or
                                 (self._wait_timestamp(task.approval_deadline_at) is not None
                                  and self._wait_timestamp(task.approval_deadline_at) > now))):
                                meta['sources'].append({"seq": step['seq'], "task": step['task_id'], "birth": identity[0],
                                                           "intent": identity[1], "start": now, "last": now, "end": None,
                                            "deadline": self._wait_timestamp(task.approval_deadline_at)})
                        self._conn.execute('UPDATE approval_wait_epochs SET metadata=? WHERE run_id=? AND marker=?',
                                           (self._wait_encode(meta), run.id, marker))
                except (ValueError, KeyError, TypeError):
                    logger.debug("invalid approval wait epoch; no source attached")
        total = 0.0
        end = run.started_at
        for left, right in sorted(windows):
            if right > max(left, end):
                total += right - max(left, end)
            end = max(end, right)
        return min(run.seconds_used(now), total)

    def _budget_moment_locked(self, run: WorkRun, now: float) -> float:
        # Clock rollback never turns previously observed elapsed time into fresh budget.
        moment = max(now, run.updated_at) if math.isfinite(now) else float('inf')
        for row in self._conn.execute('SELECT metadata FROM approval_wait_epochs WHERE run_id=?', (run.id,)):
            try:
                observed = self._wait_decode(row[0]).get('observed')
                if type(observed) in (int, float) and math.isfinite(observed):
                    moment = max(moment, observed)
            except (ValueError, AttributeError):
                continue
        return moment

    def _close_waits_locked(self, run_id: str, now: float) -> None:
        for row in self._conn.execute('SELECT marker,metadata FROM approval_wait_epochs WHERE run_id=?', (run_id,)).fetchall():
            try:
                meta = self._wait_decode(row['metadata'])
                for source in meta['sources']:
                    if source['end'] is None:
                        source['end'] = max(source['start'], min(source['last'], now))
                meta['closed'] = True
                self._conn.execute('UPDATE approval_wait_epochs SET metadata=? WHERE run_id=? AND marker=?',
                                   (self._wait_encode(meta), run_id, row['marker']))
            except (ValueError, KeyError, TypeError):
                continue

    # ── opening a run ────────────────────────────────────────────────────

    def open_run(
        self,
        goal: Any,
        *,
        budget: Budget | Mapping[str, Any] | None = None,
        deadline_at: float | None = None,
    ) -> WorkRun:
        """Open a run for an OWNER-APPROVED goal.

        ``goal`` is a :class:`agents.core.cognitive_ledger.GoalSpec` (or anything
        exposing ``goal_id``, ``title`` and an ``approved_by`` ref). A goal with
        no approval ref is refused: the ledger is where an approved decision
        becomes durable work, never where work invents its own approval.
        """
        approved_by = getattr(goal, "approved_by", None)
        if approved_by is None:
            raise WorkRunError("goal_not_approved")
        goal_id = _text(getattr(goal, "goal_id", ""), "goal_id", max_chars=128)
        title = _text(getattr(goal, "title", ""), "title", max_chars=_MAX_SUMMARY)
        now = self._now()
        deadline = float(
            deadline_at if deadline_at is not None else getattr(goal, "deadline_at", 0.0) or 0.0
        )
        if deadline and deadline <= now:
            raise WorkRunError("deadline_in_the_past")
        limits = budget if isinstance(budget, Budget) else Budget.from_dict(budget)
        run = WorkRun(
            id=uuid.uuid4().hex[:16],
            goal_id=goal_id,
            title=title,
            status="planning",
            approved_by=str(getattr(approved_by, "key", approved_by))[:256],
            budget=limits,
            started_at=now,
            updated_at=now,
            deadline_at=deadline,
        )
        run = WorkRun(**{**run.__dict__, "fingerprint": _fingerprint(run.identity())})
        with self._lock:
            if self._open_for_goal(goal_id) is not None:
                raise WorkRunError("run_already_open_for_goal")
            self._conn.execute(
                """INSERT INTO runs (id, goal_id, title, status, approved_by, budget,
                       steps_used, interrupts_used, started_at, updated_at, deadline_at,
                       stop_reason, fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, '', ?)""",
                (
                    run.id, run.goal_id, run.title, run.status, run.approved_by,
                    _canonical(run.budget.as_dict()), run.started_at, run.updated_at,
                    run.deadline_at, run.fingerprint,
                ),
            )
            self._conn.commit()
        logger.info("work run opened: %s for goal %s", run.id, run.goal_id)
        return run

    def _open_for_goal(self, goal_id: str) -> str | None:
        row = self._conn.execute(
            _SQL_OPEN_FOR_GOAL, (goal_id, *_TERMINAL_ORDER)
        ).fetchone()
        return row["id"] if row is not None else None

    # ── reading ──────────────────────────────────────────────────────────

    def get(self, run_id: str) -> WorkRun | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row is not None else None

    def list_runs(self, *, active_only: bool = False, limit: int = 100) -> list[WorkRun]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            if active_only:
                rows = self._conn.execute(
                    _SQL_ACTIVE_RUNS, (*_TERMINAL_ORDER, limit)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM runs ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def steps(self, run_id: str, *, limit: int = 500) -> list[Step]:
        limit = max(1, min(int(limit), 5000))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY seq LIMIT ?", (run_id, limit)
            ).fetchall()
        return [self._row_to_step(row) for row in rows]

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> Step:
        return Step(
            seq=row["seq"], run_id=row["run_id"], kind=row["kind"], summary=row["summary"],
            outcome=row["outcome"], task_id=row["task_id"],
            interrupted=bool(row["interrupted"]), at=row["at"],
            detail=_load(row["detail"]),
        )

    def verdicts(self, run_id: str) -> list[Verdict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM verdicts WHERE run_id = ? ORDER BY role", (run_id,)
            ).fetchall()
        return [
            Verdict(
                run_id=row["run_id"], role=row["role"], passed=bool(row["passed"]),
                reason=row["reason"], evidence=tuple(json.loads(row["evidence"] or "[]")),
                at=row["at"],
            )
            for row in rows
        ]

    def tampered(self, run_id: str) -> bool:
        """True when a run row no longer matches the fingerprint it was written with."""
        run = self.get(run_id)
        if run is None:
            return False
        return _fingerprint(run.identity()) != run.fingerprint

    def _row_to_run(self, row: sqlite3.Row) -> WorkRun:
        return WorkRun(
            id=row["id"], goal_id=row["goal_id"], title=row["title"], status=row["status"],
            approved_by=row["approved_by"], budget=Budget.from_dict(json.loads(row["budget"])),
            steps_used=row["steps_used"], interrupts_used=row["interrupts_used"],
            started_at=row["started_at"], updated_at=row["updated_at"],
            deadline_at=row["deadline_at"], stop_reason=row["stop_reason"],
            fingerprint=row["fingerprint"],
            # A corrupt blob reads as "not parked": the safe direction, since a
            # barrier only ever suppresses work.
            barrier=_load(row["barrier"]) or None,
        )

    # ── budget ───────────────────────────────────────────────────────────

    def budget_state(self, run_id: str, *, now: float | None = None) -> dict[str, Any]:
        """What is left, and which limit (if any) is already spent.

        ``exceeded`` names the FIRST limit that is out — steps, then seconds, then
        deadline, then interrupts — so a caller reports one honest reason rather
        than a list.
        """
        tasks = self._approval_tasks(run_id)
        moment = self._now() if now is None else float(now)
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                moment = self._now() if now is None else float(now)
                run = self._run_locked(run_id)
                credit = self._wait_credit_locked(run, moment, tasks)
                budget_moment = self._budget_moment_locked(run, moment)
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        used_seconds = max(0.0, run.seconds_used(budget_moment) - credit)
        exceeded = _exceeded(run, budget_moment, credit=credit)
        return {
            "run_id": run.id,
            "steps_used": run.steps_used,
            "steps_left": max(0, run.budget.max_steps - run.steps_used),
            "seconds_used": used_seconds,
            "wall_seconds_used": run.seconds_used(moment),
            "human_wait_seconds": credit,
            "seconds_left": max(0.0, run.budget.max_seconds - used_seconds),
            "interrupts_used": run.interrupts_used,
            "interrupts_left": max(0, run.budget.max_interrupts - run.interrupts_used),
            "deadline_at": run.deadline_at,
            "exceeded": exceeded,
        }

    # ── stepping ─────────────────────────────────────────────────────────

    def record_step(
        self,
        run_id: str,
        *,
        kind: str,
        summary: str,
        outcome: str,
        task_id: int | None = None,
        interrupted: bool = False,
        detail: Mapping[str, Any] | None = None,
    ) -> Step:
        """Record one step the run took. Refuses if a budget is already spent.

        ``task_id`` is the durable queue row that carried out the effect. A step
        with a privileged ``outcome`` and no task id is still recorded — the
        ledger does not police the caller's honesty here — but the supervisor
        supplies it, and the report renders "no approved task" plainly rather
        than implying authorisation the run never had.
        """
        outcome = str(outcome or "").strip().lower()
        if outcome not in STEP_OUTCOMES:
            raise WorkRunError("invalid_outcome")
        kind = _text(kind, "kind", max_chars=64)
        summary = _text(summary, "summary", max_chars=_MAX_SUMMARY)
        tasks = self._approval_tasks(run_id, extra=task_id)
        now = self._now()
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                now = self._now()
                row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
                if row is None:
                    raise WorkRunError("unknown_run")
                run = self._row_to_run(row)
                if run.terminal:
                    raise WorkRunError(f"run_{run.status}")
                if run.status == "stopping":
                    raise WorkRunError("run_stopping")
                credit = self._wait_credit_locked(run, now, tasks)
                budget_moment = self._budget_moment_locked(run, now)
                used_seconds = max(0.0, run.seconds_used(budget_moment) - credit)
                if run.steps_used >= run.budget.max_steps:
                    self._transition_locked(run, "exhausted", now, stop_reason="budget:steps")
                    raise WorkRunError("budget_exhausted:steps")
                if used_seconds >= run.budget.max_seconds:
                    self._transition_locked(run, "exhausted", now, stop_reason="budget:seconds")
                    raise WorkRunError("budget_exhausted:seconds")
                if run.deadline_at and budget_moment >= run.deadline_at:
                    self._transition_locked(run, "exhausted", now, stop_reason="budget:deadline")
                    raise WorkRunError("budget_exhausted:deadline")
                interrupts = run.interrupts_used + (1 if interrupted else 0)
                if interrupts > run.budget.max_interrupts:
                    if run.status == "blocked":
                        self._close_waits_locked(run_id, now)
                        # This is a negative authority hold in the same state, not
                        # a new approval epoch or a widened transition table.
                        self._conn.execute(
                            "UPDATE runs SET stop_reason='budget:interrupts', approval_block_seq=NULL, "
                            "updated_at=? WHERE id=?", (now, run_id),
                        )
                        self._conn.commit()
                    else:
                        self._transition_locked(run, "blocked", now, stop_reason="budget:interrupts")
                    raise WorkRunError("budget_exhausted:interrupts")

                cur = self._conn.execute(
                    """INSERT INTO steps (run_id, kind, summary, outcome, task_id, interrupted,
                           at, detail)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, kind, summary, outcome, task_id, 1 if interrupted else 0, now,
                        _canonical(dict(detail or {})),
                    ),
                )
                next_status = "blocked" if outcome == "queued" else "working"
                self._conn.execute(
                    """UPDATE runs SET steps_used = steps_used + 1, interrupts_used = ?,
                           status = ?, updated_at = ?, approval_block_seq = CASE
                               WHEN ? != 'blocked' THEN NULL
                               WHEN status != 'blocked' THEN ? ELSE approval_block_seq END WHERE id = ?""",
                    (interrupts, next_status, now, next_status, cur.lastrowid, run_id),
                )
                self._wait_credit_locked(self._run_locked(run_id), now, tasks)
                self._conn.commit()
                seq = cur.lastrowid
            except BaseException:
                self._conn.rollback()
                raise
        return Step(
            seq=seq, run_id=run_id, kind=kind, summary=summary, outcome=outcome,
            task_id=task_id, interrupted=interrupted, at=now, detail=dict(detail or {}),
        )

    def outstanding_asks(self, run_id: str, *, limit: int = 100) -> list[Step]:
        """The steps still waiting on a decision, oldest first.

        This *is* the durable ask list. A separate table of pending requests would
        be a second copy of a fact the ledger already holds — the queued step and
        its durable task id — and two copies of one fact drift, which here would
        mean a run blocked on an ask nobody can find, or an ask reconciled twice.
        """
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steps WHERE run_id = ? AND outcome = 'queued' "
                "ORDER BY seq LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def run_waiting_on(self, task_id: int) -> str | None:
        """The run blocked on this durable task, if any.

        Lets a decision reconcile the moment it is made rather than on the next
        sweep: the difference between "Nerva carried on the instant you tapped
        approve" and "some time in the next twenty minutes".
        """
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id FROM steps WHERE task_id = ? AND outcome = 'queued' "
                "ORDER BY seq LIMIT 1",
                (int(task_id),),
            ).fetchone()
        return row["run_id"] if row is not None else None

    def pending_asks_for_task(self, task_id: int, *, limit: int = 100) -> list[Step]:
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
            return []
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steps WHERE task_id = ? AND outcome = 'queued' ORDER BY seq LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def settle_expired_ask(self, run_id: str, seq: int, *, task_id: int,
                           expired_at: str) -> ExpiryAskSettlement:
        """Close one exact source and conditionally resume its approval epoch atomically.

        Replaying a settled receipt never spends a second resume. Unmarked legacy
        blocks stay held; the marker is causal evidence, not an inferred approval.
        """
        from .queue import normalize_approval_deadline

        if (not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0
                or not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0):
            raise WorkRunError("expiry_source_mismatch")
        try:
            stamp = normalize_approval_deadline(expired_at)
        except ValueError as exc:
            raise WorkRunError("invalid_expiry_receipt") from exc
        if stamp is None or stamp != expired_at:
            raise WorkRunError("invalid_expiry_receipt")
        receipt = {"task_id": task_id, "expired_at": stamp}
        tasks = self._approval_tasks(run_id)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM steps WHERE run_id = ? AND seq = ?", (run_id, seq)
                ).fetchone()
                run_row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
                if row is None or run_row is None or row["task_id"] != task_id:
                    raise WorkRunError("expiry_source_mismatch")
                detail = dict(_load(row["detail"]))
                if row["outcome"] != "queued":
                    if (row["outcome"] == "failed" and detail.get("resolution") == "expired_unanswered"
                            and detail.get("approval_expiry") == receipt):
                        self._conn.commit()
                        return ExpiryAskSettlement(True, False, False, "already settled")
                    raise WorkRunError("expiry_receipt_mismatch")
                detail.update(resolution="expired_unanswered", reason="approval deadline elapsed unanswered",
                              decided_by="system", by_machine=True, approval_expiry=receipt)
                detail.pop("human_reason", None)
                now = self._now()
                credit = self._wait_credit_locked(self._row_to_run(run_row), now, tasks)
                self._conn.execute(
                    "UPDATE steps SET outcome='failed', detail=?, at=? WHERE run_id=? AND seq=?",
                    (_canonical(detail), now, run_id, seq),
                )
                run = self._row_to_run(run_row)
                marker = run_row["approval_block_seq"]
                outstanding = self._conn.execute(
                    "SELECT 1 FROM steps WHERE run_id=? AND outcome='queued' LIMIT 1", (run_id,)
                ).fetchone()
                resume = (run.status == "blocked" and marker is not None and seq >= marker
                          and not outstanding and not run.barrier and not run.stop_reason
                          and _exceeded(run, self._budget_moment_locked(run, now), credit=credit) is None)
                if resume:
                    self._transition_locked(run, "working", now, commit=False)
                else:
                    self._conn.execute("UPDATE runs SET updated_at=? WHERE id=?", (now, run_id))
                self._conn.commit()
                return ExpiryAskSettlement(True, True, bool(resume), "every ask answered" if resume else "run held")
            except BaseException:
                self._conn.rollback()
                raise

    def resolve_step(
        self,
        run_id: str,
        seq: int,
        *,
        outcome: str,
        detail: Mapping[str, Any] | None = None,
    ) -> Step:
        """Close an outstanding ask by rewriting the queued step in place.

        Deliberately NOT a new step: the budget was spent when the action was
        arranged, and appending a second row would charge one action twice and
        report a run as busier than it was. The step keeps its ``seq``, so the
        ledger still reads as one row per thing the run did.

        Only a ``queued`` step can be resolved, and only once — a decision that
        can be applied twice is a decision that can resume a run twice. The
        resolution never moves the run itself; :meth:`resume` does that, so the
        caller cannot accidentally unblock a run that has since been stopped.
        """
        if outcome not in STEP_OUTCOMES or outcome == "queued":
            raise WorkRunError("bad_resolution")
        tasks = self._approval_tasks(run_id)
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT * FROM steps WHERE run_id = ? AND seq = ?", (run_id, int(seq))
                ).fetchone()
                if row is None:
                    raise WorkRunError("unknown_step")
                if row["outcome"] != "queued":
                    # Already answered. Re-applying would let one decision spend a
                    # second resume, which is exactly the double-unblock this guards.
                    raise WorkRunError("step_not_outstanding")
                self._wait_credit_locked(self._run_locked(run_id), self._now(), tasks)
                merged = dict(_load(row["detail"]))
                merged.update(dict(detail or {}))
                now = self._now()
                self._conn.execute(
                    "UPDATE steps SET outcome = ?, detail = ?, at = ? WHERE run_id = ? AND seq = ?",
                    (outcome, _canonical(merged), now, run_id, int(seq)),
                )
                self._conn.execute(
                    "UPDATE runs SET updated_at = ? WHERE id = ?", (now, run_id)
                )
                self._conn.commit()
                row = self._conn.execute(
                    "SELECT * FROM steps WHERE run_id = ? AND seq = ?", (run_id, int(seq))
                ).fetchone()
            except BaseException:
                self._conn.rollback()
                raise
        return self._row_to_step(row)

    def resume(self, run_id: str) -> WorkRun:
        """Move a blocked run back to working — after its outstanding ask resolved."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise WorkRunError("unknown_run")
            run = self._row_to_run(row)
            if run.status != "blocked":
                raise WorkRunError("run_not_blocked")
            return self._transition_locked(run, "working", self._now())

    def resume_after_asks(self, run_id: str, *, answered_seqs: list[int]) -> WorkRun:
        """Reconciler-only resume; manual resume retains its original contract."""
        tasks = self._approval_tasks(run_id)
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                run = self._run_locked(run_id)
                marker = self._conn.execute('SELECT approval_block_seq FROM runs WHERE id=?', (run_id,)).fetchone()[0]
                now = self._now()
                credit = self._wait_credit_locked(run, now, tasks)
                eligible = False
                if marker is not None and len(answered_seqs) <= 1000:
                    eligible = any(type(seq) is int and self._conn.execute(
                        "SELECT 1 FROM steps WHERE run_id=? AND seq=? AND seq>=? AND outcome!='queued'",
                        (run_id, seq, marker)).fetchone() for seq in answered_seqs)
                if (run.status != 'blocked' or marker is None or not eligible
                        or run.stop_reason or run.barrier
                        or self._conn.execute("SELECT 1 FROM steps WHERE run_id=? AND outcome='queued' LIMIT 1", (run_id,)).fetchone()
                        or _exceeded(run, self._budget_moment_locked(run, now), credit=credit)):
                    raise WorkRunError('approval_resume_held')
                result = self._transition_locked(run, 'working', now, commit=False)
                self._conn.commit()
                return result
            except BaseException:
                self._conn.rollback()
                raise

    # ── stopping and finishing ───────────────────────────────────────────

    def request_stop(self, run_id: str, *, reason: str = "owner") -> WorkRun:
        """One-way door: the run accepts no further step from this moment.

        A run that has not started yet, or one already stopping, settles straight
        to ``stopped``; a working run goes to ``stopping`` so an in-flight step
        can unwind and the supervisor can close it out.
        """
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise WorkRunError("unknown_run")
            run = self._row_to_run(row)
            if run.terminal:
                raise WorkRunError(f"run_{run.status}")
            now = self._now()
            detail = _text(reason, "reason", max_chars=200, required=False) or "owner"
            if run.status == "stopping":
                return self._transition_locked(run, "stopped", now, stop_reason=detail)
            return self._transition_locked(run, "stopping", now, stop_reason=detail)

    def settle_stop(self, run_id: str) -> WorkRun:
        """Close out a stopping run once its in-flight work has unwound."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise WorkRunError("unknown_run")
            run = self._row_to_run(row)
            if run.status != "stopping":
                raise WorkRunError("run_not_stopping")
            return self._transition_locked(run, "stopped", self._now())

    def record_verdict(
        self,
        run_id: str,
        *,
        role: str,
        passed: bool,
        reason: str = "",
        evidence: tuple[str, ...] | list[str] = (),
    ) -> Verdict:
        """Write the verifier's or the judge's verdict, and settle the run on the judge's.

        Only the judge decides ``succeeded``/``failed``: the verifier's pass is a
        statement about the evidence, not about the goal. A judge pass on a run
        the verifier failed is refused — a run cannot be graded good on evidence
        that did not hold.
        """
        role = str(role or "").strip().lower()
        if role not in VERDICT_ROLES:
            raise WorkRunError("invalid_verdict_role")
        detail = _text(reason, "reason", max_chars=_MAX_SUMMARY, required=False)
        rows = tuple(str(item)[:_MAX_SUMMARY] for item in (evidence or ()))
        now = self._now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise WorkRunError("unknown_run")
            run = self._row_to_run(row)
            if run.terminal:
                raise WorkRunError(f"run_{run.status}")
            existing = self._conn.execute(
                "SELECT role FROM verdicts WHERE run_id = ? AND role = ?", (run_id, role)
            ).fetchone()
            if existing is not None:
                raise WorkRunError("verdict_already_recorded")
            if role == "judge" and passed:
                verifier = self._conn.execute(
                    "SELECT passed FROM verdicts WHERE run_id = ? AND role = 'verifier'",
                    (run_id,),
                ).fetchone()
                if verifier is None:
                    raise WorkRunError("verifier_verdict_missing")
                if not verifier["passed"]:
                    raise WorkRunError("verifier_failed")
            self._conn.execute(
                """INSERT INTO verdicts (run_id, role, passed, reason, evidence, at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, role, 1 if passed else 0, detail, _canonical(list(rows)), now),
            )
            if role == "judge":
                self._transition_locked(
                    run, "succeeded" if passed else "failed", now, commit=False
                )
            self._conn.commit()
        return Verdict(
            run_id=run_id, role=role, passed=bool(passed), reason=detail,
            evidence=rows, at=now,
        )

    # ── barriers (H464) ──────────────────────────────────────────────────

    def set_barrier(self, run_id: str, record: Mapping[str, Any]) -> WorkRun:
        """Park a run: store the barrier and log ``barrier.set``. Never a step.

        ``record`` comes from :class:`RunBarriers`, which validates it; the bounds
        are re-checked here under the lock anyway, so the ledger alone never holds
        a barrier on a run that may not be parked, one without a future end, or
        more of them than a run is allowed. A barrier already in place is logged
        as ``replaced`` first, so the audit never loses one.
        """
        payload = dict(record or {})
        encoded = _canonical(payload)
        if len(encoded.encode("utf-8")) > _MAX_BARRIER_BYTES:
            raise WorkRunError("barrier_too_large")
        barrier_id = str(payload.get("id") or "")
        if not barrier_id or not isinstance(payload.get("id"), str):
            raise WorkRunError("malformed_barrier")
        if payload.get("kind") not in BARRIER_KINDS:
            raise WorkRunError("unknown_kind")
        tasks = self._approval_tasks(run_id)
        now = self._now()
        try:
            cap_at = float(payload.get("cap_at"))
        except (TypeError, ValueError):
            raise WorkRunError("malformed_barrier") from None
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                now = self._now()
                run = self._run_locked(run_id)
                if run.status not in _PARKABLE:
                    raise WorkRunError("run_not_parkable")
                if _exceeded(run, self._budget_moment_locked(run, now), credit=self._wait_credit_locked(run, now, tasks)):
                    raise WorkRunError("budget_spent")
                if not cap_at > now:
                    raise WorkRunError("no_time_left")
                if self._set_count_locked(run_id) >= MAX_BARRIERS_PER_RUN:
                    raise WorkRunError("barrier_limit")
                if run.barrier:
                    self._event_locked(run_id, "barrier.cleared", now, {
                        "id": run.barrier.get("id"), "why": "replaced", "by": "ledger",
                    })
                self._conn.execute("UPDATE runs SET barrier = ? WHERE id = ?", (encoded, run_id))
                event = {
                    key: payload.get(key)
                    for key in ("id", "kind", "target", "cap_at", "source", "reason")
                }
                if payload.get("kind") == "pid":
                    # Which process, not just which number: an owner's clear binds this
                    # process, never a later one on a reused pid (H464 review N5).
                    event["start"] = str(payload.get("start") or "")
                self._event_locked(run_id, "barrier.set", now, event)
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        logger.info("run %s parked on %s (%s) by %s", run_id, payload.get("kind"),
                    payload.get("target"), payload.get("source"))
        return WorkRun(**{**run.__dict__, "barrier": payload})

    def clear_barrier(
        self,
        run_id: str,
        *,
        why: str,
        by: str,
        expect_id: str | None = None,
    ) -> WorkRun:
        """Un-park a run and log ``barrier.cleared``. A no-op when nothing is set.

        ``expect_id`` makes it a compare-and-clear: a background check that read
        barrier A must never erase barrier B set in the meantime, nor undo an
        owner's action it raced with.
        """
        return self.clear_barrier_if(run_id, why=why, by=by, expect_id=expect_id)[1]

    def clear_barrier_if(
        self,
        run_id: str,
        *,
        why: str,
        by: str,
        expect_id: str | None = None,
    ) -> tuple[bool, WorkRun]:
        """:meth:`clear_barrier`, also saying whether THIS call cleared anything.

        The run's state afterwards cannot say that: a barrier another caller already
        cleared reads the same as one this call cleared, and a newer barrier left in
        place reads as "still waiting". Whoever reports a clear (the owner's route)
        reports this flag, never the post-state (H464 review F8).
        """
        if (why not in BARRIER_CLEAR_REASONS and not str(why).startswith("run_")) or (
            by not in BARRIER_CLEARED_BY
        ):
            raise WorkRunError("invalid_clear")
        now = self._now()
        with self._lock:
            run = self._run_locked(run_id)
            current = run.barrier
            if not current or (expect_id is not None and current.get("id") != expect_id):
                return False, run
            self._conn.execute("UPDATE runs SET barrier = '' WHERE id = ?", (run_id,))
            self._event_locked(run_id, "barrier.cleared", now,
                               {"id": current.get("id"), "why": why, "by": by})
            self._conn.commit()
        logger.info("run %s barrier cleared: %s by %s", run_id, why, by)
        return True, WorkRun(**{**run.__dict__, "barrier": None})

    def owner_cleared(self, run_id: str) -> list[dict[str, Any]]:
        """The waits the owner let this run go from, oldest first: ``{kind, target}``
        (plus a pid's ``start`` token, when recorded) as each one's ``barrier.set``
        event recorded it. Read from the append-only
        audit, so an owner's "stop waiting" outlives a restart (H464 review F3)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, detail FROM run_events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        sets: dict[Any, dict[str, Any]] = {}
        out: list[dict[str, Any]] = []
        for row in rows:
            detail = _load(row["detail"])
            if row["kind"] == "barrier.set":
                sets[detail.get("id")] = detail
            elif row["kind"] == "barrier.cleared" and detail.get("by") == "owner":
                origin = sets.get(detail.get("id"))
                if origin is not None:
                    entry = {"kind": origin.get("kind"), "target": origin.get("target")}
                    if "start" in origin:
                        entry["start"] = origin.get("start")
                    out.append(entry)
        return out

    def now(self) -> float:
        """The ledger's clock — what a report compares a barrier's end against, so
        it reads the same time the ledger stamped the barrier with."""
        return self._now()

    def barrier_set_count(self, run_id: str, *, source: str | None = None) -> int:
        """How many barriers this run has ever been parked on (by ``source``)."""
        with self._lock:
            if source is None:
                return self._set_count_locked(run_id)
            rows = self._conn.execute(
                "SELECT detail FROM run_events WHERE run_id = ? AND kind = 'barrier.set'",
                (run_id,),
            ).fetchall()
        return sum(1 for row in rows if _load(row["detail"]).get("source") == source)

    def events(self, run_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """The run's barrier audit, newest first. Append-only: there is no API to
        rewrite or delete an event."""
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY seq DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [
            {"seq": row["seq"], "kind": row["kind"], "at": row["at"],
             "detail": _load(row["detail"])}
            for row in rows
        ]

    def add_process(self, run_id: str, record: Mapping[str, Any]) -> None:
        """Store a process the hub spawned for this run. Storage only — the
        refusals (who may be registered, how many) live in RunBarriers."""
        with self._lock:
            self._run_locked(run_id)
            self._conn.execute(
                """INSERT OR IGNORE INTO run_procs (run_id, pid, start, ns, boot, label, at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, int(record["pid"]), str(record.get("start") or ""),
                    str(record.get("ns") or ""), str(record.get("boot") or ""),
                    str(record.get("label") or "")[:200], self._now(),
                ),
            )
            self._conn.commit()

    def processes(self, run_id: str) -> list[dict[str, Any]]:
        """The processes registered for this run, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM run_procs WHERE run_id = ? ORDER BY at, pid", (run_id,)
            ).fetchall()
        return [
            {"pid": row["pid"], "start": row["start"], "ns": row["ns"], "boot": row["boot"],
             "label": row["label"], "at": row["at"]}
            for row in rows
        ]

    def _run_locked(self, run_id: str) -> WorkRun:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise WorkRunError("unknown_run")
        return self._row_to_run(row)

    def _set_count_locked(self, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id = ? AND kind = 'barrier.set'",
            (run_id,),
        ).fetchone()
        return int(row[0])

    def _event_locked(
        self, run_id: str, kind: str, now: float, detail: Mapping[str, Any]
    ) -> None:
        self._conn.execute(
            "INSERT INTO run_events (run_id, kind, at, detail) VALUES (?, ?, ?, ?)",
            (run_id, kind, now, _canonical(dict(detail))),
        )

    # ── internals ────────────────────────────────────────────────────────

    def _transition_locked(
        self,
        run: WorkRun,
        new_status: str,
        now: float,
        *,
        stop_reason: str = "",
        commit: bool = True,
    ) -> WorkRun:
        """Move a run along the transition table. Caller holds the lock."""
        allowed = _TRANSITIONS.get(run.status, frozenset())
        if new_status not in allowed:
            raise WorkRunError(f"illegal_transition:{run.status}->{new_status}")
        reason = stop_reason or run.stop_reason
        barrier = run.barrier
        if barrier and (new_status == "stopping" or new_status in TERMINAL_STATUSES):
            # H464: stop always wins. A stopping or finished run never reads as
            # "waiting on …", so the barrier goes in the same write as the move.
            self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ?, stop_reason = ?, barrier = '' "
                "WHERE id = ?",
                (new_status, now, reason, run.id),
            )
            self._event_locked(run.id, "barrier.cleared", now, {
                "id": barrier.get("id"), "why": f"run_{new_status}", "by": "ledger",
            })
            barrier = None
        else:
            self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ?, stop_reason = ? WHERE id = ?",
                (new_status, now, reason, run.id),
            )
        self._close_waits_locked(run.id, now)
        self._conn.execute("UPDATE runs SET approval_block_seq=NULL WHERE id=?", (run.id,))
        if commit:
            self._conn.commit()
        return WorkRun(
            **{**run.__dict__, "status": new_status, "updated_at": now, "stop_reason": reason,
               "barrier": barrier}
        )

    # ── reporting ────────────────────────────────────────────────────────

    def snapshot(self, run_id: str, *, step_limit: int = 100) -> dict[str, Any]:
        """Everything a report or a HUD needs about one run, in one read."""
        run = self.get(run_id)
        if run is None:
            raise WorkRunError("unknown_run")
        steps = self.steps(run_id, limit=step_limit)
        return {
            "run": run.as_dict(),
            "budget": self.budget_state(run_id),
            "steps": [step.as_dict() for step in steps],
            "verdicts": [verdict.as_dict() for verdict in self.verdicts(run_id)],
            "tampered": self.tampered(run_id),
            # H464: the barrier audit. Events are not steps, so they never count
            # toward budget or toward the unauthorised list below.
            "events": self.events(run_id),
            # A run is only "authorised throughout" when every step that changed
            # something names the durable task that was approved to change it.
            "unauthorised_steps": [
                step.seq for step in steps if step.outcome == "ok" and step.task_id is None
            ],
        }


__all__ = [
    "BARRIER_KINDS",
    "FLAG",
    "KIND",
    "MAX_BARRIERS_PER_RUN",
    "MIGRATIONS",
    "RUN_STATUSES",
    "STEP_OUTCOMES",
    "ExpiryAskSettlement",
    "TERMINAL_STATUSES",
    "VERDICT_ROLES",
    "Budget",
    "Step",
    "Verdict",
    "WorkRun",
    "WorkRunError",
    "WorkRunLedger",
]
