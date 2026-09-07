"""jobs.py — owner-scheduled jobs (Hermes absorption, wave 2).

Nerva already parsed "every weekday at 7" into a cron expression (`nl_schedule.py`) —
and threw the result away: the only caller was a preview route. It had every other piece
of a scheduler (approval tiers, an interrupt budget, the kill switch, the audit chain) and
no place where the owner could arm a job of their own without editing the repo and
restarting. This module is that place.

A job is a schedule plus one of four actions:

  * ``remind`` — a fixed message to the owner's channel. No model.
  * ``ask``    — a prompt to one agent through the same one-shot path the nightly
                 reflection uses (`Orchestrator.process`), with a **notepad** the job keeps
                 between runs so a daily job reports what changed, not the same three things
                 every morning. The reply is delivered to the owner.
  * ``brief``  — the morning brief or evening retro, on the owner's own time.
  * ``task``   — a governed task enqueued through the autonomy queue, where the policy
                 decides act / notify / ask exactly as for any other task. A job can never
                 skip that queue: this is the one capability where the governance stack is
                 the product, not overhead.

Every attempt is recorded. Three consecutive failures pause the job itself and raise one
incident instead of paging the owner at 03:00 forever. The kill switch pauses every job.
Frequency is bounded (one firing per five minutes at most), the store is bounded (50 jobs,
200 runs each), and every text is length-capped.

Pure and offline-testable: SQLite + WAL like `missions.py`, no orchestrator at import time,
the scheduler and the orchestrator injected as callables.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.core.paths import data_path

from .nl_schedule import parse_schedule

logger = logging.getLogger("jarvis.autonomy.jobs")

MAX_JOBS = 50
MAX_NAME = 80
MAX_TEXT = 2_000
MAX_NOTEPAD = 4_096
MAX_RUNS_KEPT = 200
MAX_FAILURES = 3
MAX_FIRES_PER_DAY = 288  # one firing per five minutes, at most
ACTION_TYPES = ("remind", "ask", "brief", "task")
_ACTION_KEYS = {
    "remind": {"type", "message", "channel"},
    "ask": {"type", "prompt", "agent", "deliver"},
    "brief": {"type", "kind"},
    "task": {"type", "kind", "title", "payload", "risk_tier"},
}
_CRON_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun")

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ── values ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    schedule_text: str
    cron: str
    action: dict
    enabled: bool = True
    blueprint: str | None = None
    created_at: str = ""
    updated_at: str = ""
    last_run_at: str | None = None
    last_status: str | None = None
    last_summary: str = ""
    consecutive_failures: int = 0
    notepad: str = ""
    paused_reason: str | None = None

    @property
    def runnable(self) -> bool:
        return self.enabled and not self.paused_reason

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "schedule_text": self.schedule_text,
            "cron": self.cron,
            "action": dict(self.action),
            "enabled": self.enabled,
            "blueprint": self.blueprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_summary": self.last_summary,
            "consecutive_failures": self.consecutive_failures,
            "notepad": self.notepad,
            "paused_reason": self.paused_reason,
            "runnable": self.runnable,
        }


@dataclass(frozen=True)
class JobRun:
    id: int
    job_id: str
    started_at: str
    finished_at: str
    status: str
    summary: str = ""
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
        }


# ── schedules ────────────────────────────────────────────────────────────────


def _field_values(field: str, low: int, high: int) -> int:
    """How many distinct values a cron field matches (approximate, never zero)."""
    total = 0
    for token in field.split(","):
        token = token.strip()
        step = 1
        if "/" in token:
            token, raw_step = token.split("/", 1)
            step = max(1, int(raw_step)) if raw_step.isdigit() else 1
        if token in ("*", ""):
            span = high - low + 1
        elif "-" in token:
            a, b = token.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"bad cron field {field!r}")
            span = max(0, int(b) - int(a) + 1)
        elif token.isdigit():
            span = 1
        else:
            raise ValueError(f"bad cron field {field!r}")
        total += max(1, -(-span // step))
    return max(1, total)


def fires_per_day(cron: str) -> float:
    match = _CRON_RE.match(cron)
    if not match:
        raise ValueError("a cron expression has five fields")
    minute, hour = match.group(1), match.group(2)
    return float(_field_values(minute, 0, 59) * _field_values(hour, 0, 23))


def resolve_schedule(text: str) -> tuple[str, str]:
    """Plain words or a raw five-field cron → (cron, description). Raises ValueError."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("say when — e.g. 'every weekday at 7' or '0 7 * * 1-5'")
    if _CRON_RE.match(raw) and not re.search(r"[A-Za-z]{3,}", raw):
        cron, description = raw, f"cron {raw}"
    else:
        parsed = parse_schedule(raw)
        if not parsed.get("ok"):
            raise ValueError(parsed.get("error") or "could not understand the schedule")
        cron, description = parsed["cron"], parsed["description"]
    try:
        rate = fires_per_day(cron)
    except ValueError as exc:
        raise ValueError(f"invalid cron {cron!r}: {exc}") from None
    if rate > MAX_FIRES_PER_DAY:
        raise ValueError(
            f"that fires ~{rate:.0f}× a day; the floor is once every five minutes"
        )
    return cron, description


def _dow_for_apscheduler(field: str) -> str:
    """cron's day-of-week (0/7 = Sunday) → APScheduler's names, which count Monday as 0."""
    if field.strip() in ("*", "?"):
        return "*"
    out = []
    for token in field.split(","):
        token = token.strip()
        step = ""
        if "/" in token:
            token, step = token.split("/", 1)
            step = f"/{step}"
        if "-" in token:
            a, b = token.split("-", 1)
            out.append(f"{_DOW_NAMES[int(a)]}-{_DOW_NAMES[int(b)]}{step}")
        elif token.isdigit():
            out.append(f"{_DOW_NAMES[int(token)]}{step}")
        else:
            out.append(token + step)
    return ",".join(out)


def cron_kwargs(cron: str) -> dict[str, str]:
    match = _CRON_RE.match(cron)
    if not match:
        raise ValueError("a cron expression has five fields")
    minute, hour, day, month, dow = match.groups()
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": _dow_for_apscheduler(dow),
    }


# ── actions ──────────────────────────────────────────────────────────────────


def validate_action(action: Any) -> list[str]:
    """Named reasons an action is not acceptable; empty when it is."""
    if not isinstance(action, dict):
        return ["action must be an object"]
    kind = action.get("type")
    if kind not in ACTION_TYPES:
        return [f"action.type must be one of {', '.join(ACTION_TYPES)}"]
    errors = [f"unknown action key {key!r}" for key in sorted(set(action) - _ACTION_KEYS[kind])]

    def _text(key: str, *, required: bool) -> None:
        value = action.get(key)
        if value is None or value == "":
            if required:
                errors.append(f"action.{key} is required")
            return
        if not isinstance(value, str):
            errors.append(f"action.{key} must be text")
        elif len(value) > MAX_TEXT:
            errors.append(f"action.{key} is longer than {MAX_TEXT} characters")

    if kind == "remind":
        _text("message", required=True)
        _text("channel", required=False)
    elif kind == "ask":
        _text("prompt", required=True)
        _text("agent", required=False)
        if "deliver" in action and not isinstance(action["deliver"], bool):
            errors.append("action.deliver must be true or false")
    elif kind == "brief":
        if action.get("kind") not in ("morning", "evening"):
            errors.append("action.kind must be morning or evening")
    else:
        _text("kind", required=True)
        _text("title", required=True)
        payload = action.get("payload", {})
        if payload is not None and not isinstance(payload, dict):
            errors.append("action.payload must be an object")
        tier = action.get("risk_tier")
        if tier is not None and (isinstance(tier, bool) or not isinstance(tier, int) or not 0 <= tier <= 3):
            errors.append("action.risk_tier must be 0-3")
    return errors


# ── blueprints ───────────────────────────────────────────────────────────────

BLUEPRINTS: dict[str, dict] = {
    "morning_brief": {
        "title": "Morning brief",
        "description": "What happened overnight and what needs you, from the task queue and memory.",
        "schedule_text": "every day at 7:00",
        "action": {"type": "brief", "kind": "morning"},
        "params": ["schedule_text"],
    },
    "evening_retro": {
        "title": "Evening retro",
        "description": "What was delivered today and what is still waiting on you.",
        "schedule_text": "every day at 20:00",
        "action": {"type": "brief", "kind": "evening"},
        "params": ["schedule_text"],
    },
    "reminder": {
        "title": "Reminder",
        "description": "A fixed message to you, on a schedule. No model is involved.",
        "schedule_text": "every day at 9:00",
        "action": {"type": "remind", "message": ""},
        "params": ["schedule_text", "message"],
    },
    "ask_agent": {
        "title": "Ask an agent on a schedule",
        "description": (
            "A prompt to one agent, on a schedule. The agent keeps a notepad between runs so it "
            "reports what changed, not the same three things every morning."
        ),
        "schedule_text": "every weekday at 8:00",
        "action": {"type": "ask", "prompt": "", "agent": "jarvis", "deliver": True},
        "params": ["schedule_text", "prompt", "agent"],
    },
    "inbox_watch": {
        "title": "Important mail watch",
        "description": (
            "Every two hours Friday checks the inbox for anything that needs you and reports "
            "only what is new since her last note."
        ),
        "schedule_text": "every 2 hours",
        "action": {
            "type": "ask",
            "prompt": (
                "Check my inbox for anything that needs me. Compare with your notes from last "
                "time and report only what is new or changed. If nothing needs me, say so in "
                "one line."
            ),
            "agent": "friday",
            "deliver": True,
        },
        "params": ["schedule_text"],
    },
}


def blueprint_catalog() -> list[dict]:
    return [
        {"id": bid, **{key: (dict(value) if isinstance(value, dict) else value) for key, value in spec.items()}}
        for bid, spec in BLUEPRINTS.items()
    ]


def instantiate_blueprint(blueprint_id: str, params: Mapping[str, Any] | None = None) -> tuple[str, str, dict]:
    """(name, schedule_text, action) for a blueprint plus the owner's parameters."""
    spec = BLUEPRINTS.get(str(blueprint_id or ""))
    if spec is None:
        raise ValueError(f"unknown blueprint {blueprint_id!r}")
    params = dict(params or {})
    unknown = sorted(set(params) - set(spec["params"]))
    if unknown:
        raise ValueError(f"blueprint {blueprint_id} takes {', '.join(spec['params'])}; not {', '.join(unknown)}")
    schedule_text = str(params.get("schedule_text") or spec["schedule_text"])
    action = dict(spec["action"])
    for key in spec["params"]:
        if key == "schedule_text":
            continue
        value = params.get(key)
        if value is not None and value != "":
            action[key] = value
    for key in ("message", "prompt"):
        if key in action and not str(action.get(key) or "").strip():
            raise ValueError(f"blueprint {blueprint_id} needs a {key}")
    return str(spec["title"]), schedule_text, action


# ── the store ────────────────────────────────────────────────────────────────

_UPDATE_SQL = (
    "UPDATE jobs SET name = ?, schedule_text = ?, cron = ?, action = ?, enabled = ?, "
    "blueprint = ?, updated_at = ?, last_run_at = ?, last_status = ?, last_summary = ?, "
    "consecutive_failures = ?, notepad = ?, paused_reason = ? WHERE id = ?"
)
_JOB_COLUMNS = (
    "id", "name", "schedule_text", "cron", "action", "enabled", "blueprint", "created_at",
    "updated_at", "last_run_at", "last_status", "last_summary", "consecutive_failures",
    "notepad", "paused_reason",
)


class JobStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path else data_path("autonomy", "jobs.db")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, schedule_text TEXT NOT NULL,
                    cron TEXT NOT NULL, action TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    blueprint TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_run_at TEXT, last_status TEXT, last_summary TEXT NOT NULL DEFAULT '',
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    notepad TEXT NOT NULL DEFAULT '', paused_reason TEXT
                )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT NOT NULL, status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', error TEXT
                )"""
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS job_runs_job ON job_runs(job_id, id)")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        try:
            action = json.loads(row["action"])
        except ValueError:
            action = {}
        return Job(
            id=row["id"],
            name=row["name"],
            schedule_text=row["schedule_text"],
            cron=row["cron"],
            action=action if isinstance(action, dict) else {},
            enabled=bool(row["enabled"]),
            blueprint=row["blueprint"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_run_at=row["last_run_at"],
            last_status=row["last_status"],
            last_summary=row["last_summary"] or "",
            consecutive_failures=int(row["consecutive_failures"] or 0),
            notepad=row["notepad"] or "",
            paused_reason=row["paused_reason"],
        )

    def create(
        self,
        *,
        name: str,
        schedule_text: str,
        action: Mapping[str, Any],
        blueprint: str | None = None,
    ) -> Job:
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("a job needs a name")
        if len(name) > MAX_NAME:
            raise ValueError(f"the name is longer than {MAX_NAME} characters")
        errors = validate_action(action)
        if errors:
            raise ValueError("; ".join(errors))
        cron, _description = resolve_schedule(schedule_text)
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if count >= MAX_JOBS:
                raise ValueError(f"the store holds {MAX_JOBS} jobs; delete one first")
            job_id = secrets.token_hex(6)
            now = utc_now()
            self._conn.execute(
                """INSERT INTO jobs (id, name, schedule_text, cron, action, enabled, blueprint,
                       created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (job_id, name, str(schedule_text).strip(), cron, json.dumps(dict(action), ensure_ascii=False),
                 blueprint, now, now),
            )
            self._conn.commit()
        job = self.get(job_id)
        if job is None:  # pragma: no cover — the row was just inserted under the lock
            raise RuntimeError("job vanished after insert")
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
        return self._row_to_job(row) if row else None

    def list(self) -> list[Job]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at, id").fetchall()
        return [self._row_to_job(row) for row in rows]

    def update(self, job_id: str, **fields: Any) -> Job:
        """Change a job's fields; one fixed statement, never SQL built from names."""
        unknown = sorted(set(fields) - set(_JOB_COLUMNS) - {"id"})
        if unknown:
            raise ValueError(f"unknown job fields {unknown}")
        current = self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        values = dict(fields)
        if "action" in values:
            values["action"] = dict(values["action"])
        if "enabled" in values:
            values["enabled"] = bool(values["enabled"])
        if "notepad" in values:
            values["notepad"] = str(values["notepad"] or "")[:MAX_NOTEPAD]
        if "last_summary" in values:
            values["last_summary"] = str(values["last_summary"] or "")[:MAX_TEXT]
        if "consecutive_failures" in values:
            values["consecutive_failures"] = int(values["consecutive_failures"])
        merged = replace(current, updated_at=utc_now(), **values)
        with self._lock:
            self._conn.execute(
                _UPDATE_SQL,
                (
                    merged.name, merged.schedule_text, merged.cron,
                    json.dumps(merged.action, ensure_ascii=False), 1 if merged.enabled else 0,
                    merged.blueprint, merged.updated_at, merged.last_run_at, merged.last_status,
                    merged.last_summary, merged.consecutive_failures, merged.notepad,
                    merged.paused_reason, merged.id,
                ),
            )
            self._conn.commit()
        return merged

    def delete(self, job_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM jobs WHERE id = ?", (str(job_id),))
            self._conn.execute("DELETE FROM job_runs WHERE job_id = ?", (str(job_id),))
            self._conn.commit()
        return cursor.rowcount > 0

    def pause(self, job_id: str, reason: str) -> Job:
        return self.update(job_id, paused_reason=str(reason or "paused")[:MAX_TEXT])

    def resume(self, job_id: str) -> Job:
        return self.update(job_id, paused_reason=None, consecutive_failures=0, enabled=True)

    def record_run(
        self,
        job_id: str,
        *,
        started_at: str,
        finished_at: str,
        status: str,
        summary: str = "",
        error: str | None = None,
    ) -> JobRun:
        summary = str(summary or "")[:MAX_TEXT]
        error = None if error is None else str(error)[:MAX_TEXT]
        with self._lock:
            cursor = self._conn.execute(
                """INSERT INTO job_runs (job_id, started_at, finished_at, status, summary, error)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(job_id), started_at, finished_at, status, summary, error),
            )
            run_id = int(cursor.lastrowid)
            self._conn.execute(
                """DELETE FROM job_runs WHERE job_id = ? AND id NOT IN (
                       SELECT id FROM job_runs WHERE job_id = ? ORDER BY id DESC LIMIT ?)""",
                (str(job_id), str(job_id), MAX_RUNS_KEPT),
            )
            self._conn.commit()
        return JobRun(run_id, str(job_id), started_at, finished_at, status, summary, error)

    def runs(self, job_id: str, limit: int = 20) -> list[JobRun]:
        limit = max(1, min(int(limit), MAX_RUNS_KEPT))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_runs WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                (str(job_id), limit),
            ).fetchall()
        return [
            JobRun(int(r["id"]), r["job_id"], r["started_at"], r["finished_at"], r["status"], r["summary"] or "", r["error"])
            for r in rows
        ]


# ── the runner ───────────────────────────────────────────────────────────────


class JobRunner:
    """Puts the store's runnable jobs on the scheduler and runs one when it fires."""

    def __init__(
        self,
        store: JobStore,
        *,
        orch: Any,
        scheduler: Callable[[], Any],
        now: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._orch = orch
        self._scheduler = scheduler
        self._now = now

    # scheduler --------------------------------------------------------------

    def scheduler_alive(self) -> bool:
        sched = self._scheduler()
        return sched is not None and bool(getattr(sched, "running", False))

    def register(self, job: Job) -> bool:
        sched = self._scheduler()
        if sched is None:
            return False
        sched.add_job(
            self.fire,
            "cron",
            args=[job.id],
            id=f"job-{job.id}",
            replace_existing=True,
            misfire_grace_time=300,
            **cron_kwargs(job.cron),
        )
        return True

    def unregister(self, job_id: str) -> None:
        sched = self._scheduler()
        if sched is None:
            return
        with contextlib.suppress(Exception):
            sched.remove_job(f"job-{job_id}")

    def register_all(self) -> int:
        registered = 0
        for job in self.store.list():
            if job.runnable and self.register(job):
                registered += 1
        return registered

    def registered_ids(self) -> list[str]:
        sched = self._scheduler()
        if sched is None:
            return []
        try:
            return sorted(
                str(job.id)[4:] for job in sched.get_jobs() if str(job.id).startswith("job-")
            )
        except Exception:
            return []

    def snapshot(self) -> dict:
        jobs = self.store.list()
        return {
            "alive": self.scheduler_alive(),
            "registered": self.registered_ids(),
            "jobs": len(jobs),
            "runnable": sum(1 for job in jobs if job.runnable),
            "paused": sum(1 for job in jobs if job.paused_reason),
        }

    # lifecycle --------------------------------------------------------------

    def create(self, **kwargs: Any) -> Job:
        job = self.store.create(**kwargs)
        self.register(job)
        return job

    def pause(self, job_id: str, reason: str) -> Job:
        job = self.store.pause(job_id, reason)
        self.unregister(job_id)
        return job

    def resume(self, job_id: str) -> Job:
        job = self.store.resume(job_id)
        self.register(job)
        return job

    def delete(self, job_id: str) -> bool:
        self.unregister(job_id)
        return self.store.delete(job_id)

    # firing -----------------------------------------------------------------

    async def fire(self, job_id: str, *, force: bool = False) -> JobRun:
        """Run one job now. Never raises; every outcome is a recorded run."""
        from agents.core import estop

        started = utc_now()
        job = self.store.get(job_id)
        if job is None:
            return JobRun(0, job_id, started, started, STATUS_SKIPPED, "job no longer exists")
        if not force and not job.runnable:
            return self.store.record_run(
                job_id, started_at=started, finished_at=utc_now(), status=STATUS_SKIPPED,
                summary=f"paused: {job.paused_reason or 'disabled'}",
            )
        if estop.check_paused(f"job:{job_id}", logger):
            return self.store.record_run(
                job_id, started_at=started, finished_at=utc_now(), status=STATUS_SKIPPED,
                summary="emergency stop engaged",
            )
        try:
            summary, notepad = await self._execute(job)
        except Exception as exc:
            return self._failed(job, started, exc)
        finished = utc_now()
        fields: dict[str, Any] = {
            "last_run_at": finished,
            "last_status": STATUS_OK,
            "last_summary": summary,
            "consecutive_failures": 0,
        }
        if notepad is not None:
            fields["notepad"] = notepad
        with contextlib.suppress(KeyError):  # deleted while running
            self.store.update(job.id, **fields)
        return self.store.record_run(job.id, started_at=started, finished_at=finished, status=STATUS_OK, summary=summary)

    def _failed(self, job: Job, started: str, exc: Exception) -> JobRun:
        finished = utc_now()
        error = f"{type(exc).__name__}: {exc}"[:MAX_TEXT]
        failures = job.consecutive_failures + 1
        fields: dict[str, Any] = {
            "last_run_at": finished,
            "last_status": STATUS_FAILED,
            "last_summary": error,
            "consecutive_failures": failures,
        }
        paused = failures >= MAX_FAILURES
        if paused:
            fields["paused_reason"] = f"{failures} consecutive failures; last: {error}"[:MAX_TEXT]
        with contextlib.suppress(KeyError):
            self.store.update(job.id, **fields)
        if paused:
            self.unregister(job.id)
            self._incident(job, error, failures)
        logger.warning("job %s failed (%d consecutive): %s", job.id, failures, error)
        return self.store.record_run(job.id, started_at=started, finished_at=finished, status=STATUS_FAILED, summary=error, error=error)

    def _incident(self, job: Job, error: str, failures: int) -> None:
        """One acknowledgeable incident when a job pauses itself — not one ping per failure."""
        try:
            from agents.core.autonomy.error_logger import persist_problem
            from agents.core.errors import ErrorCategory, ErrorLog, ErrorSeverity

            persist_problem(
                ErrorLog(
                    code="E_JOB_PAUSED",
                    message=f"job '{job.name}' paused itself after {failures} consecutive failures: {error}",
                    category=ErrorCategory.INTERNAL,
                    severity=ErrorSeverity.ERROR,
                    component=f"job:{job.id}",
                    timestamp=self._now(),
                    meta={"job_id": job.id, "failures": failures},
                )
            )
        except Exception:
            logger.warning("job incident could not be persisted", exc_info=True)
        logger.error("job '%s' paused itself after %d consecutive failures: %s", job.name, failures, error)

    # actions ----------------------------------------------------------------

    async def _execute(self, job: Job) -> tuple[str, str | None]:
        action = job.action
        kind = action.get("type")
        if kind == "remind":
            delivered = await self._deliver(str(action.get("message", "")), action.get("channel"))
            return f"reminder {delivered}", None
        if kind == "brief":
            text = await self._brief(str(action.get("kind", "morning")))
            delivered = await self._deliver(text, None)
            return f"{action.get('kind')} brief {delivered}", None
        if kind == "ask":
            return await self._ask(job, action)
        if kind == "task":
            return self._task(job, action), None
        raise ValueError(f"unknown action type {kind!r}")

    async def _ask(self, job: Job, action: Mapping[str, Any]) -> tuple[str, str]:
        prompt = str(action.get("prompt", ""))
        if job.notepad:
            prompt = (
                f"{prompt}\n\nYour notes from the last run of this job (compare, then report what "
                f"changed):\n{job.notepad}"
            )
        process = getattr(self._orch, "process", None)
        if not callable(process):
            raise RuntimeError("no model path is available for ask jobs")
        reply = await process(prompt, agent=str(action.get("agent") or "jarvis"), channel="job")
        reply = str(reply or "").strip()
        if not reply:
            raise RuntimeError("the agent returned no answer (no model backend, or a degraded reply)")
        summary = reply[:MAX_TEXT]
        if action.get("deliver", True):
            delivered = await self._deliver(reply, None)
            summary = f"[{delivered}] {summary}"[:MAX_TEXT]
        return summary, reply[:MAX_NOTEPAD]

    async def _brief(self, kind: str) -> str:
        from .digest import build_evening_retro, build_morning_brief

        queue = getattr(self._orch, "autonomy_queue", None)
        if queue is None:
            raise RuntimeError("no task queue is available for the brief")
        if kind == "evening":
            return build_evening_retro(queue)
        return build_morning_brief(queue)

    def _task(self, job: Job, action: Mapping[str, Any]) -> str:
        queue = getattr(self._orch, "autonomy_queue", None)
        if queue is None:
            raise RuntimeError("no task queue is available")
        tier = action.get("risk_tier")
        task_id = queue.enqueue(
            agent="jarvis",
            kind=str(action["kind"]),
            title=str(action["title"]),
            payload=dict(action.get("payload") or {}),
            risk_tier=int(tier) if tier is not None else 3,
            origin=f"job:{job.id}",
        )
        return f"queued task #{task_id} for the autonomy policy to decide"

    async def _deliver(self, text: str, channel: str | None) -> str:
        """Send *text* to the owner; returns a summary fragment, raises when it cannot."""
        import os

        channel = (channel or "telegram").strip().lower()
        channels = getattr(self._orch, "channels", None) or {}
        adapter = channels.get(channel)
        if adapter is None:
            raise RuntimeError(f"channel {channel!r} is not connected")
        if channel == "telegram":
            get_setting = getattr(self._orch, "get_setting", None)
            owner = os.environ.get("AUTONOMY_OWNER_CHAT_ID", "") or str(
                (get_setting("autonomy.owner_chat_id", "") if callable(get_setting) else "") or ""
            )
            if not owner.strip():
                raise RuntimeError("no owner chat is configured (autonomy.owner_chat_id)")
            ok = await adapter.send(text, chat_id=int(owner))
        else:
            ok = await adapter.send(text)
        if not ok:
            raise RuntimeError(f"{channel} refused the message")
        return f"delivered to {channel}"
