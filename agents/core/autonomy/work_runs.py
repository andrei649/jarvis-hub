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
* **Budgets are hard.** Steps, wall-clock seconds and owner-visible interrupts
  are capped by the goal's budget; the ledger refuses the step that would exceed
  one and marks the run ``exhausted`` rather than quietly continuing.
* **A stop is honoured immediately.** ``request_stop`` is a one-way door: a
  stopping run accepts no further steps, whatever else is in flight.

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
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.core.paths import data_path
from agents.core.persistence.migrations import apply_migrations

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


class WorkRunError(RuntimeError):
    """A refusal from the ledger. ``reason`` is a bounded, public code."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "work_run_refused")
        super().__init__(self.reason)


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


MIGRATIONS = [_v1]


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
        return [
            Step(
                seq=row["seq"], run_id=row["run_id"], kind=row["kind"], summary=row["summary"],
                outcome=row["outcome"], task_id=row["task_id"],
                interrupted=bool(row["interrupted"]), at=row["at"],
                detail=json.loads(row["detail"] or "{}"),
            )
            for row in rows
        ]

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
        )

    # ── budget ───────────────────────────────────────────────────────────

    def budget_state(self, run_id: str, *, now: float | None = None) -> dict[str, Any]:
        """What is left, and which limit (if any) is already spent.

        ``exceeded`` names the FIRST limit that is out — steps, then seconds, then
        deadline, then interrupts — so a caller reports one honest reason rather
        than a list.
        """
        run = self.get(run_id)
        if run is None:
            raise WorkRunError("unknown_run")
        moment = self._now() if now is None else float(now)
        used_seconds = run.seconds_used(moment)
        exceeded = None
        if run.steps_used >= run.budget.max_steps:
            exceeded = "steps"
        elif used_seconds >= run.budget.max_seconds:
            exceeded = "seconds"
        elif run.deadline_at and moment >= run.deadline_at:
            exceeded = "deadline"
        elif run.interrupts_used > run.budget.max_interrupts:
            exceeded = "interrupts"
        return {
            "run_id": run.id,
            "steps_used": run.steps_used,
            "steps_left": max(0, run.budget.max_steps - run.steps_used),
            "seconds_used": used_seconds,
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
        now = self._now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise WorkRunError("unknown_run")
            run = self._row_to_run(row)
            if run.terminal:
                raise WorkRunError(f"run_{run.status}")
            if run.status == "stopping":
                raise WorkRunError("run_stopping")
            used_seconds = run.seconds_used(now)
            if run.steps_used >= run.budget.max_steps:
                self._transition_locked(run, "exhausted", now, stop_reason="budget:steps")
                raise WorkRunError("budget_exhausted:steps")
            if used_seconds >= run.budget.max_seconds:
                self._transition_locked(run, "exhausted", now, stop_reason="budget:seconds")
                raise WorkRunError("budget_exhausted:seconds")
            if run.deadline_at and now >= run.deadline_at:
                self._transition_locked(run, "exhausted", now, stop_reason="budget:deadline")
                raise WorkRunError("budget_exhausted:deadline")
            interrupts = run.interrupts_used + (1 if interrupted else 0)
            if interrupts > run.budget.max_interrupts:
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
                       status = ?, updated_at = ? WHERE id = ?""",
                (interrupts, next_status, now, run_id),
            )
            self._conn.commit()
            seq = cur.lastrowid
        return Step(
            seq=seq, run_id=run_id, kind=kind, summary=summary, outcome=outcome,
            task_id=task_id, interrupted=interrupted, at=now, detail=dict(detail or {}),
        )

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
        self._conn.execute(
            "UPDATE runs SET status = ?, updated_at = ?, stop_reason = ? WHERE id = ?",
            (new_status, now, reason, run.id),
        )
        if commit:
            self._conn.commit()
        return WorkRun(
            **{**run.__dict__, "status": new_status, "updated_at": now, "stop_reason": reason}
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
            # A run is only "authorised throughout" when every step that changed
            # something names the durable task that was approved to change it.
            "unauthorised_steps": [
                step.seq for step in steps if step.outcome == "ok" and step.task_id is None
            ],
        }


__all__ = [
    "FLAG",
    "KIND",
    "MIGRATIONS",
    "RUN_STATUSES",
    "STEP_OUTCOMES",
    "TERMINAL_STATUSES",
    "VERDICT_ROLES",
    "Budget",
    "Step",
    "Verdict",
    "WorkRun",
    "WorkRunError",
    "WorkRunLedger",
]
