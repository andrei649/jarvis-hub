"""missions.py — Mission Workspaces (roadmap 0.32).

A long-running, *persistent* unit of agent work: a goal, an ordered plan of
steps, an explicit budget (max steps / wall-clock seconds), a pause/resume-able
state machine, an on-disk artifacts directory, and an append-only event log that
serves as the mission's audit trail. Where the autonomy ``TaskQueue`` (queue.py)
tracks individual proposed/approved *tasks*, a Mission is the workspace that a
minutes-to-hours effort lives in — it can span many turns and survive restarts.

Design mirrors ``TaskQueue``: SQLite + WAL, a serialising lock, frozen-ish
dataclasses, a strict transition table, terminal states with no exits. Pure and
offline-testable — no orchestrator, LLM, or network at import or call time.

    planned ─▶ active ⇄ paused
                 │  ╰────────────╮
                 ▼               ▼
              done / failed / cancelled   (terminal)

Budget is a hard bound (anti-runaway): finishing a step charges ``steps_used``;
once it would exceed ``max_steps`` the mission auto-fails instead of running on.
``max_seconds`` is wall-clock from ``started_at`` and is reported by
``budget_status`` so a caller (or the HUD) can halt a mission that overruns.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.autonomy.missions")

DEFAULT_DB = data_path("missions.db")
_ARTIFACT_ROOT = data_path("missions")

DEFAULT_MAX_STEPS = 20
DEFAULT_MAX_SECONDS = 3600


class MissionStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


TERMINAL = {MissionStatus.DONE, MissionStatus.FAILED, MissionStatus.CANCELLED}

_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
    MissionStatus.PLANNED: {MissionStatus.ACTIVE, MissionStatus.CANCELLED},
    MissionStatus.ACTIVE: {MissionStatus.PAUSED, MissionStatus.DONE,
                           MissionStatus.FAILED, MissionStatus.CANCELLED},
    MissionStatus.PAUSED: {MissionStatus.ACTIVE, MissionStatus.CANCELLED, MissionStatus.FAILED},
    MissionStatus.DONE: set(),
    MissionStatus.FAILED: set(),
    MissionStatus.CANCELLED: set(),
}


class MissionError(Exception):
    """Illegal mission state transition or unknown mission/step."""


class BudgetExceeded(MissionError):
    """A step would push the mission past its step budget."""


@dataclass
class Mission:
    id: int
    title: str
    goal: str
    status: str
    plan: list[dict]          # [{idx, title, status, result, started_at, ended_at}]
    max_steps: int
    max_seconds: int
    steps_used: int
    started_at: Optional[str]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class MissionEvent:
    mission_id: int
    ts: str
    event: str
    detail: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class MissionStore:
    def __init__(self, db_path: Optional[str] = None, artifact_root: Optional[str] = None,
                 *, ledger=None):
        if db_path is None:
            DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(DEFAULT_DB)
        self.db_path = db_path
        self._artifact_root = Path(artifact_root) if artifact_root else _ARTIFACT_ROOT
        self._ledger = ledger
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────
    def initialize(self) -> "MissionStore":
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                goal TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'planned',
                plan TEXT NOT NULL DEFAULT '[]',
                max_steps INTEGER NOT NULL DEFAULT 20,
                max_seconds INTEGER NOT NULL DEFAULT 3600,
                steps_used INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                event TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            )
        """)
        # The list view filters by status; the audit trail reads events by
        # mission. Index both so they stay O(log n) as the tables grow.
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mission_events_mid ON mission_events(mission_id, id)")
        self._conn.commit()
        return self

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _sync_budget_dimension(self, mission: Mission) -> None:
        if self._ledger is None:
            return
        setter = getattr(self._ledger, "set_dimension_usage", None)
        if setter is None:
            return
        setter(
            "mission.steps",
            mission.steps_used,
            limit=mission.max_steps,
            unit="steps",
            enforced=False,
            metadata={"mission_id": mission.id, "status": mission.status},
        )

    # ── writes ────────────────────────────────────────────────────
    def create(self, title: str, goal: str = "", plan: Optional[list[str]] = None,
               max_steps: int = DEFAULT_MAX_STEPS, max_seconds: int = DEFAULT_MAX_SECONDS) -> Mission:
        title = (title or "").strip()
        if not title:
            raise MissionError("mission title required")
        steps = [
            {"idx": i, "title": str(s), "status": StepStatus.PENDING.value,
             "result": None, "started_at": None, "ended_at": None}
            for i, s in enumerate(plan or [])
        ]
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO missions (title, goal, status, plan, max_steps, max_seconds,
                       steps_used, started_at, created_at, updated_at)
                   VALUES (?, ?, 'planned', ?, ?, ?, 0, NULL, ?, ?)""",
                (title, goal or "", json.dumps(steps, ensure_ascii=False),
                 max(1, int(max_steps)), max(1, int(max_seconds)), now, now),
            )
            mid = cur.lastrowid
            self._conn.commit()
        self._event(mid, "created", title)
        return self.get(mid)

    def _set_status(self, mission_id: int, new_status: MissionStatus, *, detail: str = "",
                    extra_sets: Optional[dict] = None) -> Mission:
        m = self.get(mission_id)
        if m is None:
            raise MissionError(f"mission {mission_id} not found")
        cur = MissionStatus(m.status)
        new_status = MissionStatus(new_status)
        if new_status not in _TRANSITIONS.get(cur, set()):
            raise MissionError(
                f"illegal transition {cur.value} → {new_status.value} (mission {mission_id})")
        sets = ["status=?", "updated_at=?"]
        params: list = [new_status.value, _now()]
        for col, val in (extra_sets or {}).items():
            sets.append(f"{col}=?"); params.append(val)
        params.append(mission_id)
        with self._lock:
            self._conn.execute(f"UPDATE missions SET {', '.join(sets)} WHERE id=?", params)
            self._conn.commit()
        self._event(mission_id, new_status.value, detail)
        return self.get(mission_id)

    def start(self, mission_id: int) -> Mission:
        # Stamp started_at only on the first activation, so max_seconds measures
        # from the real start (a later resume must not reset the clock).
        m = self.get(mission_id)
        extra = {} if (m and m.started_at) else {"started_at": _now()}
        return self._set_status(mission_id, MissionStatus.ACTIVE, detail="started", extra_sets=extra)

    def pause(self, mission_id: int) -> Mission:
        return self._set_status(mission_id, MissionStatus.PAUSED, detail="paused")

    def resume(self, mission_id: int) -> Mission:
        return self._set_status(mission_id, MissionStatus.ACTIVE, detail="resumed")

    def complete(self, mission_id: int) -> Mission:
        return self._set_status(mission_id, MissionStatus.DONE, detail="completed")

    def fail(self, mission_id: int, reason: str = "") -> Mission:
        return self._set_status(mission_id, MissionStatus.FAILED, detail=reason or "failed")

    def cancel(self, mission_id: int) -> Mission:
        return self._set_status(mission_id, MissionStatus.CANCELLED, detail="cancelled")

    def finish_step(self, mission_id: int, idx: int, status: str = "done",
                    result: Optional[str] = None) -> Mission:
        """Mark a plan step terminal and charge the step budget.

        Only valid while the mission is ACTIVE. Charging ``steps_used`` past
        ``max_steps`` auto-fails the mission (BudgetExceeded) rather than letting
        it run unbounded.
        """
        m = self.get(mission_id)
        if m is None:
            raise MissionError(f"mission {mission_id} not found")
        if MissionStatus(m.status) != MissionStatus.ACTIVE:
            raise MissionError(f"mission {mission_id} not active (is {m.status})")
        if idx < 0 or idx >= len(m.plan):
            raise MissionError(f"step {idx} out of range for mission {mission_id}")
        try:
            step_status = StepStatus(status)
        except ValueError:
            raise MissionError(f"invalid step status: {status}")

        plan = m.plan
        plan[idx] = {**plan[idx], "status": step_status.value, "result": result,
                     "ended_at": _now(),
                     "started_at": plan[idx].get("started_at") or _now()}
        new_used = m.steps_used + 1
        with self._lock:
            self._conn.execute(
                "UPDATE missions SET plan=?, steps_used=?, updated_at=? WHERE id=?",
                (json.dumps(plan, ensure_ascii=False), new_used, _now(), mission_id),
            )
            self._conn.commit()
        self._event(mission_id, "step", f"#{idx} {step_status.value}")
        if new_used >= m.max_steps:
            # Budget spent — fail closed. The step result is preserved above.
            self.fail(mission_id, reason=f"step budget exhausted ({new_used}/{m.max_steps})")
            raise BudgetExceeded(
                f"mission {mission_id} hit step budget {m.max_steps}")
        return self.get(mission_id)

    def add_artifact(self, mission_id: int, name: str, content: str) -> str:
        """Persist a text artifact under the mission's workspace dir; return its path.

        The filename is reduced to a safe basename (``[A-Za-z0-9._-]`` only, so a
        path separator can never survive) and written *inside* the per-mission
        directory — there is no way for ``name`` to escape the workspace.
        """
        if self.get(mission_id) is None:
            raise MissionError(f"mission {mission_id} not found")
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name or "").strip("._") or "artifact"
        mission_dir = (self._artifact_root / str(mission_id))
        mission_dir.mkdir(parents=True, exist_ok=True)
        path = mission_dir / safe
        path.write_text(content or "", encoding="utf-8")
        self._event(mission_id, "artifact", safe)
        return str(path)

    def _event(self, mission_id: int, event: str, detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO mission_events (mission_id, ts, event, detail) VALUES (?, ?, ?, ?)",
                (mission_id, _now(), event, (detail or "")[:500]),
            )
            self._conn.commit()

    # ── reads ─────────────────────────────────────────────────────
    def get(self, mission_id: int) -> Optional[Mission]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        mission = _row_to_mission(row) if row else None
        if mission is not None:
            self._sync_budget_dimension(mission)
        return mission

    def list(self, status: Optional[str] = None, limit: int = 100) -> list[Mission]:
        clause, params = "", []
        if status:
            clause = "WHERE status=?"; params.append(status)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM missions {clause} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        missions = [_row_to_mission(r) for r in rows]
        for mission in missions:
            self._sync_budget_dimension(mission)
        return missions

    def events(self, mission_id: int, limit: int = 200) -> list[MissionEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mission_events WHERE mission_id=? ORDER BY id ASC LIMIT ?",
                (mission_id, limit),
            ).fetchall()
        return [MissionEvent(mission_id=r["mission_id"], ts=r["ts"],
                             event=r["event"], detail=r["detail"]) for r in rows]

    def budget_status(self, mission_id: int) -> Optional[dict]:
        m = self.get(mission_id)
        if m is None:
            return None
        elapsed = None
        if m.started_at:
            started = _iso_to_epoch(m.started_at)
            if started is not None:
                elapsed = round(_now_epoch() - started, 1)
        return {
            "max_steps": m.max_steps,
            "steps_used": m.steps_used,
            "steps_remaining": max(0, m.max_steps - m.steps_used),
            "max_seconds": m.max_seconds,
            "elapsed_seconds": elapsed,
            "over_time": (elapsed is not None and elapsed > m.max_seconds),
        }


# ── helpers ───────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso_to_epoch(value: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None


def _row_to_mission(row: sqlite3.Row) -> Mission:
    return Mission(
        id=row["id"], title=row["title"], goal=row["goal"], status=row["status"],
        plan=json.loads(row["plan"] or "[]"),
        max_steps=row["max_steps"], max_seconds=row["max_seconds"],
        steps_used=row["steps_used"], started_at=row["started_at"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )
