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

import asyncio
import contextlib
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
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
    "remind": {"type", "message", "channel", "urgent", "media_ids"},
    "ask": {"type", "prompt", "agent", "deliver", "urgent"},
    "brief": {"type", "kind", "urgent"},
    "task": {"type", "kind", "title", "payload", "risk_tier"},
}
# Quiet hours (Hermes absorption 4e): a job's message that would land in the owner's
# night is held and delivered when the night ends; an ``urgent`` one may still go, but it
# spends the same daily interrupt budget every other night-time push spends (MOONSHOT §5:
# at most a handful of urgent pushes a day). Held messages are bounded per job — the
# newest are kept — and the flush runs every few minutes on the same scheduler.
MAX_HELD_PER_JOB = 20
HELD_FLUSH_MINUTES = 5
HELD_FLUSH_JOB_ID = "jobs-held-flush"
QUIET_START_SETTING = "ambient.quiet_hours_start"
QUIET_END_SETTING = "ambient.quiet_hours_end"
DEFAULT_QUIET_START = 22
DEFAULT_QUIET_END = 7


def setting_hour(orch, key: str, default: int) -> int:
    """An hour-of-day setting, modulo 24, or *default* when it is not a number that has
    one (an infinity, NaN, text, a list): quiet hours then keep their defaults."""
    get_setting = getattr(orch, "get_setting", None)
    try:
        value = get_setting(key, default) if callable(get_setting) else default
        return int(value) % 24
    except (TypeError, ValueError, OverflowError):
        return default


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

    options: dict = field(default_factory=dict)
    attempts: int = 0
    last_delivery_status: str | None = None

    @property
    def runnable(self) -> bool:
        return (self.enabled and not self.paused_reason
                and (not self.options.get("repeat") or self.attempts < self.options["repeat"])
                and not (is_one_shot(self.cron) and self.attempts >= 1))   # H450: a one-shot runs once

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
            "options": dict(self.options),
            "attempts": self.attempts,
            "last_delivery_status": self.last_delivery_status,
            "one_shot": is_one_shot(self.cron),
            "run_at": run_at(self.cron).isoformat() if is_one_shot(self.cron) else None,
        }


@dataclass(frozen=True)
class HeldDelivery:
    """A job's message waiting for the owner's quiet hours to end."""

    id: int
    job_id: str
    text: str
    channel: str | None
    created_at: str

    def as_dict(self) -> dict:
        return {
            "id": self.id, "job_id": self.job_id, "channel": self.channel,
            "created_at": self.created_at, "chars": len(self.text),
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


#: A one-shot (H450) is stored in the cron column as this prefix and a UTC ISO time.
ONE_SHOT_PREFIX = "@at "
ONE_SHOT_SPENT = "one-shot already ran"


def is_one_shot(cron: object) -> bool:
    """A run-once job (``@at <UTC ISO>``), not a cron cadence."""
    return isinstance(cron, str) and cron.startswith(ONE_SHOT_PREFIX)


def run_at(cron: object) -> datetime | None:
    """When a one-shot runs (aware, UTC), or None for a cron. Raises ValueError on a
    malformed one-shot."""
    if not is_one_shot(cron):
        return None
    value = datetime.fromisoformat(str(cron)[len(ONE_SHOT_PREFIX):])
    if value.tzinfo is None:
        raise ValueError("a one-shot time carries its zone")
    return value.astimezone(UTC)


def schedule_trigger(cron: str, timezone):
    """The APScheduler trigger a stored schedule means: a date for a one-shot, else a cron."""
    if is_one_shot(cron):
        from apscheduler.triggers.date import DateTrigger

        return DateTrigger(run_date=run_at(cron), timezone=timezone)
    from apscheduler.triggers.cron import CronTrigger

    return CronTrigger(**cron_kwargs(cron), timezone=timezone)


def fires_per_day(cron: str) -> float:
    if is_one_shot(cron):
        run_at(cron)
        return 1.0
    match = _CRON_RE.match(cron)
    if not match:
        raise ValueError("a cron expression has five fields")
    minute, hour = match.group(1), match.group(2)
    return float(_field_values(minute, 0, 59) * _field_values(hour, 0, 23))


def resolve_schedule(text: str, *, now: datetime | None = None, zone=None) -> tuple[str, str]:
    """Plain words or a raw five-field cron → (cron, description). Raises ValueError.

    A one-shot (H450: ``in 30m``, ``2026-10-01 09:00``, ``tomorrow at 9``) comes back as
    ``@at <UTC ISO>``; *now* and *zone* anchor it (the clock and the local zone by default).
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("say when — e.g. 'every weekday at 7' or '0 7 * * 1-5'")
    if _CRON_RE.match(raw) and not re.search(r"[A-Za-z]{3,}", raw):
        cron, description = raw, f"cron {raw}"
    else:
        parsed = parse_schedule(raw, now=now, zone=zone)
        if not parsed.get("ok"):
            raise ValueError(parsed.get("error") or "could not understand the schedule")
        if parsed.get("at"):
            return ONE_SHOT_PREFIX + parsed["at"], parsed["description"]
        cron, description = parsed["cron"], parsed["description"]
    try:
        rate = fires_per_day(cron)
    except ValueError as exc:
        raise ValueError(f"invalid cron {cron!r}: {exc}") from None
    if rate > MAX_FIRES_PER_DAY:
        raise ValueError(
            f"that fires ~{rate:.0f}× a day; the floor is once every five minutes"
        )
    from apscheduler.triggers.cron import CronTrigger

    CronTrigger(**cron_kwargs(cron), timezone=UTC)
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
            out.append(f"{_dow_name(a)}-{_dow_name(b)}{step}")
        elif token.isdigit():
            out.append(f"{_dow_name(token)}{step}")
        else:
            out.append(token + step)
    return ",".join(out)


def _dow_name(token: str) -> str:
    text = token.strip().lower()
    if text in _DOW_NAMES:
        return text
    if not text.isdigit() or not 0 <= int(text) <= 7:
        raise ValueError(f"day-of-week must be 0-7 or a name, not {token!r}")
    return _DOW_NAMES[int(text)]


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


def validate_action(action: Any, options: dict | None = None) -> list[str]:
    """Named reasons an action is not acceptable; empty when it is."""
    if not isinstance(action, dict):
        return ["action must be an object"]
    kind = action.get("type")
    if options and "enabled_toolsets" in options and kind != "ask":
        return ["enabled_toolsets requires a model-bearing ask action"]
    if options and ("model" in options or "provider" in options) and kind != "ask":
        return ["model/provider pins require an ask action"]
    if options and (options.get("script") or (options.get("monitor_script") or options.get("monitor_url"))) and kind != "ask":
        return ["script options require an ask action"]
    if kind not in ACTION_TYPES:
        return [f"action.type must be one of {', '.join(ACTION_TYPES)}"]
    errors = [f"unknown action key {key!r}" for key in sorted(set(action) - _ACTION_KEYS[kind])]
    from .jobs_media import validate_media
    errors.extend(validate_media(action, options))

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

    if "urgent" in action and not isinstance(action["urgent"], bool):
        errors.append("action.urgent must be true or false")
    if kind == "remind":
        _text("message", required=True)
        _text("channel", required=False)
    elif kind == "ask":
        _text("prompt", required=not bool((options or {}).get("no_agent")))
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


_REPEAT_FOREVER = {"", "forever", "unlimited", "always", "infinite", "∞", "mereu", "la nesfârșit",
                   "la nesfarsit", "pentru totdeauna"}
_REPEAT_WORDS = {"once": 1, "o dată": 1, "o data": 1, "one time": 1, "twice": 2, "de două ori": 2,
                 "de doua ori": 2}
_REPEAT_COUNT = re.compile(r"^(?:x\s*(\d+)|(\d+)\s*(?:x|times?)?|de\s+(\d+)\s+ori)$")


def normalize_repeat(value: Any) -> int | None:
    """``forever | once | 1x | N | "3 times" | "de 3 ori"`` → attempts (1-10000), or None
    for unlimited. Anything else raises ValueError (H450)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = " ".join(value.strip().lower().split())
        if text in _REPEAT_FOREVER:
            return None
        if text in _REPEAT_WORDS:
            return _REPEAT_WORDS[text]
        match = _REPEAT_COUNT.match(text)
        if not match:
            raise ValueError(f"repeat must be forever, once, Nx or a count, not {value!r}")
        value = int(next(g for g in match.groups() if g))
    if type(value) is not int or not 1 <= value <= 10000:
        raise ValueError("repeat must be null or an integer from 1 to 10000 attempts")
    return value


def validate_options(options: Any, *, check_scripts: bool = True, url_screen=None) -> dict:
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    from ..llm.job_selection import validate_pins
    validate_pins(options)
    unknown = set(options) - {"repeat", "deliver", "script", "no_agent", "monitor_script", "monitor_url", "model", "provider", "workdir", "enabled_toolsets"}
    if unknown:
        raise ValueError(f"unsupported job options: {', '.join(sorted(unknown))}")
    if 'enabled_toolsets' in options:
        from ..job_toolsets import validate
        validate(options['enabled_toolsets'])
        if options.get('no_agent') is True:
            raise ValueError('enabled_toolsets requires a model-bearing ask action')
    if 'workdir' in options:
        if not options.get('script') or options.get('no_agent') is not True or options.get('monitor_script') or options.get('monitor_url'):
            raise ValueError('workdir requires script with no_agent true')
        from .jobs_workdir import validate_workdir
        options = {**options, 'workdir': validate_workdir(options['workdir'])}
    if 'monitor_url' in options:
        if any(options.get(key) for key in ('script', 'monitor_script', 'no_agent')):
            raise ValueError('URL monitor excludes other sources and no_agent')
        if not callable(url_screen):
            raise ValueError('URL monitor screening is unavailable')
        url_screen(options['monitor_url'])
    if 'no_agent' in options and type(options['no_agent']) is not bool:
        raise ValueError('no_agent must be true or false')
    if options.get('no_agent') and not options.get('script'):
        raise ValueError('no_agent requires a script')
    if options.get('monitor_script') and (options.get('script') or options.get('no_agent')):
        raise ValueError('monitor_script excludes script and no_agent')
    for source_key in ('script', 'monitor_script'):
        if source_key not in options:
            continue
        source = options[source_key]
        if not isinstance(source, str) or not source or len(source) > 1024:
            raise ValueError('script must name a bounded Python file')
        if check_scripts:
            from .jobs_scripts import script_problem
            problem = script_problem(source)
            if problem:
                raise ValueError(problem)
    if "repeat" in options:
        options = {**options, "repeat": normalize_repeat(options["repeat"])}
    if "deliver" in options:
        targets = options["deliver"]
        if not isinstance(targets, list) or len(targets) > 8 or any(
            not isinstance(t, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", t) for t in targets
        ) or len(set(targets)) != len(targets):
            raise ValueError("deliver must list up to 8 unique configured channel names")
    return json.loads(json.dumps(options))


# A first run is skipped when the first slot is nearer than two minutes, or than a
# quarter of the cadence: "every 12 hours" armed 45 minutes before its noon slot waits
# for it instead of running twice within the hour.
FIRST_RUN_SLOT_MARGIN_S = 120
FIRST_RUN_SLOT_SHARE = 0.25


def _cron_values(field: str, low: int, high: int) -> set[int] | None:
    """The values one cron field fires on, or None when it cannot be read."""
    values: set[int] = set()
    for part in field.split(","):
        base, slash, step = part.partition("/")
        try:
            every = int(step) if slash else 1
            if base == "*":
                start, end = low, high
            elif "-" in base:
                first, last = base.split("-", 1)
                start, end = int(first), int(last)
            else:
                start = int(base)
                end = high if slash else start
        except ValueError:
            return None
        if every < 1 or not low <= start <= end <= high:
            return None
        values.update(range(start, end + 1, every))
    return values


def _is_step_set(values: set[int], low: int, high: int) -> bool:
    """``values`` is what ``*/N`` fires on, for some N."""
    return any(values == set(range(low, high + 1, n)) for n in range(1, high - low + 2))


def is_interval_cron(cron: str) -> bool:
    """A clock-free cadence — every N minutes, hourly, every N hours — not a calendar slot.

    What the cron fires on decides, not how it is written: '0 0-23/2' and '0 0,12'
    are '0 */2' and '0 */12'. Every hour with one minute or the minutes of a '*/N',
    or one minute in the hours of a '*/N', and nothing restricting the day, month or
    weekday. "every weekday at 8:00", "every day at 7", two times of day ('0 9,21')
    and '*/5 */2' (every five minutes, but only in even hours) are calendar schedules.
    """
    fields = (cron or "").split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        return False
    minutes, hours = _cron_values(fields[0], 0, 59), _cron_values(fields[1], 0, 23)
    if not minutes or not hours:
        return False
    one_minute = len(minutes) == 1
    if len(hours) == 24:
        return one_minute or _is_step_set(minutes, 0, 59)
    return one_minute and len(hours) > 1 and _is_step_set(hours, 0, 23)


def first_run_margin(slot_gap: float | None) -> float:
    """How near the first slot may be before a first run would only repeat it."""
    return max(FIRST_RUN_SLOT_MARGIN_S, (slot_gap or 0.0) * FIRST_RUN_SLOT_SHARE)


def first_run_policy(job, *, quiet: bool = False, seconds_to_slot: float | None = None,
                     slot_gap: float | None = None) -> tuple[bool, str]:
    """Whether a job's first run belongs now, by default, and why (H687).

    Hermes' ``/loop`` is an interval, and its first wakeup fires at once
    (LoopManager.set: next_due_at=now); a Hermes cron job waits for its first
    computed run. So only an agent-instruction job — ask, brief or task, or a script
    or monitor source — on an interval cadence runs before its first slot.
    - A calendar schedule waits: a morning brief armed in the evening must not
      deliver now, and a weekday job armed on Saturday must not run on Saturday.
    - A reminder waits: '/remind every weekday at 7 | stand-up' delivered the moment
      it is armed is noise.
    - A repeat-limited job waits: the first run would spend one of its few attempts
      and could leave the slot the owner scheduled unserved (critic note 15).
    - Nothing runs during quiet hours: the output would be held and delivered after
      the next fresh run's.
    - Nothing runs when the first slot is near (first_run_margin): that slot is the
      first run.
    Checked when the job is armed and again when the queued run comes to run.
    """
    if is_one_shot(job.cron):
        return False, "one-shot"
    options = job.options or {}
    if options.get("repeat"):
        return False, "repeat-limited"
    source = options.get("script") or options.get("monitor_script") or options.get("monitor_url")
    if not source and (job.action or {}).get("type") not in ("ask", "brief", "task"):
        return False, "reminder"
    if not is_interval_cron(job.cron):
        return False, "calendar"
    if quiet:
        return False, "quiet hours"
    if seconds_to_slot is not None and seconds_to_slot < first_run_margin(slot_gap):
        return False, "slot"
    return True, "interval"


def first_run_decision(job, *, explicit: bool | None = None, quiet: bool = False,
                       seconds_to_slot: float | None = None, slot_gap: float | None = None) -> tuple[bool, str]:
    """Whether a new job fires once now, before its first slot, and why (H687).

    A paused or disabled job never does. ``explicit`` (the create call's
    ``first_run``) overrides first_run_policy either way; otherwise the policy decides.
    """
    if not job.runnable:
        return False, "not runnable"
    if is_one_shot(job.cron):
        # H450: never early, even when asked — it would spend the only run and leave the
        # time the owner chose unserved.
        return False, "one-shot"
    if explicit is not None:
        return bool(explicit), "asked" if explicit else "opted out"
    return first_run_policy(job, quiet=quiet, seconds_to_slot=seconds_to_slot, slot_gap=slot_gap)


_FIRST_RUN_NOTES = {
    "quiet hours": " (quiet hours now, so no first run)",
    "slot": " (its first slot is near, so that slot is the first run)",
}


def arm_confirmation(job, first_run: dict | None, *, why: str = "", scheduler_alive: bool = True) -> str:
    """The one wording every creation surface uses for what happens next."""
    if is_one_shot(job.cron):
        text = f"{job.schedule_text}: runs once at {run_at(job.cron):%Y-%m-%d %H:%M} UTC"
        if not scheduler_alive:
            text += " — the scheduler is not running, so nothing fires until it is"
        return text
    cadence = f"{job.schedule_text} ({job.cron})"
    if first_run:
        # Without a scheduler nothing drains the queue: the run is queued, not "now".
        text = f"first run {'now' if scheduler_alive else 'queued'}, then {cadence}"
    elif why.startswith("not queued"):
        text = f"first run {why}; {cadence}, on its cadence"
    else:
        text = f"{cadence}, on its cadence{_FIRST_RUN_NOTES.get(why, '')}"
    if not scheduler_alive:
        text += " — the scheduler is not running, so nothing fires until it is"
    return text


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


from .jobs_blueprints import extend_catalog, validate_params

extend_catalog(BLUEPRINTS)


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
    values = validate_params(spec, params)
    schedule_text = str(params.get("schedule_text") or spec["schedule_text"])
    action = dict(spec["action"])
    if spec.get("template"):
        key = "message" if action["type"] == "remind" else "prompt"
        action[key] = action[key].format_map(values)
        return str(spec["title"]), schedule_text, action
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

_JOB_COLUMNS = (
    "id", "name", "schedule_text", "cron", "action", "enabled", "blueprint", "created_at",
    "updated_at", "last_run_at", "last_status", "last_summary", "consecutive_failures",
    "notepad", "paused_reason", "options", "attempts", "last_delivery_status",
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
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(jobs)")}
            if "options" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN options TEXT NOT NULL DEFAULT '{}'")
            if "attempts" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            if "last_delivery_status" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN last_delivery_status TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS job_runs_job ON job_runs(job_id, id)")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS job_held (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    text TEXT NOT NULL, channel TEXT, created_at TEXT NOT NULL
                )"""
            )
            self._conn.execute("CREATE TABLE IF NOT EXISTS job_ticks (job_id TEXT PRIMARY KEY, slot TEXT NOT NULL)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS scheduler_results "
                "(job_id TEXT PRIMARY KEY, status TEXT NOT NULL, recorded_at TEXT NOT NULL)"
            )
            self._conn.commit()
        from .jobs_scripts import ScriptAttempts
        self.script_attempts = ScriptAttempts(self)
        from .jobs_dispatch import ManualDispatch
        self.dispatch = ManualDispatch(self)


    def record_scheduler_result(self, job_id: str, status: str) -> None:
        """Keep only bounded, structured native execution outcomes, never payloads."""
        if not isinstance(job_id, str) or not job_id or len(job_id) > 200:
            raise ValueError("invalid scheduler job id")
        if status not in {"ok", "pending", "failed", "missed", "max_instances"}:
            raise ValueError("invalid scheduler result status")
        with self._lock:
            self._conn.execute(
                "INSERT INTO scheduler_results VALUES (?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, recorded_at=excluded.recorded_at",
                (job_id, status, datetime.now(UTC).isoformat()),
            )
            self._conn.execute(
                "DELETE FROM scheduler_results WHERE job_id IN "
                "(SELECT job_id FROM scheduler_results ORDER BY recorded_at DESC, job_id LIMIT -1 OFFSET 256)"
            )
            self._conn.commit()

    def scheduler_results(self) -> dict[str, dict]:
        with self._lock:
            rows = self._conn.execute("SELECT job_id, status, recorded_at FROM scheduler_results").fetchall()
        return {row["job_id"]: {"status": row["status"], "recorded_at": row["recorded_at"]} for row in rows}

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
            options=json.loads(row["options"]) if isinstance(json.loads(row["options"]), dict) else {},
            attempts=int(row["attempts"]),
            last_delivery_status=row["last_delivery_status"],
        )

    def create(
        self,
        *,
        name: str,
        schedule_text: str,
        action: Mapping[str, Any],
        blueprint: str | None = None,
        options: dict | None = None,
    ) -> Job:
        options = validate_options(options if options is not None else {}, url_screen=getattr(self, 'url_screen', None))
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("a job needs a name")
        if len(name) > MAX_NAME:
            raise ValueError(f"the name is longer than {MAX_NAME} characters")
        errors = validate_action(action, options)
        if errors:
            raise ValueError("; ".join(errors))
        cron, _description = resolve_schedule(schedule_text, zone=self._schedule_zone())
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if count >= MAX_JOBS:
                raise ValueError(f"the store holds {MAX_JOBS} jobs; delete one first")
            job_id = secrets.token_hex(6)
            now = utc_now()
            self._conn.execute(
                """INSERT INTO jobs (id, name, schedule_text, cron, action, enabled, blueprint,
                       created_at, updated_at, options) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                (job_id, name, str(schedule_text).strip(), cron, json.dumps(dict(action), ensure_ascii=False),
                 blueprint, now, now, json.dumps(options)),
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
        """Update only named mutable columns; never replay a stale job snapshot.

        SQLite serializes each UPDATE across independent connections. Reservations own
        the attempts column exclusively, so a notepad/status/config write cannot undo one.
        """
        allowed = set(_JOB_COLUMNS) - {"id", "created_at", "attempts"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"unknown or immutable job fields {unknown}")
        values = dict(fields)
        for key in ("action", "options"):
            if key in values:
                values[key] = json.dumps(dict(values[key]), ensure_ascii=False)
        if "enabled" in values:
            values["enabled"] = int(bool(values["enabled"]))
        if "notepad" in values:
            values["notepad"] = str(values["notepad"] or "")[:MAX_NOTEPAD]
        if "last_summary" in values:
            values["last_summary"] = str(values["last_summary"] or "")[:MAX_TEXT]
        if "consecutive_failures" in values:
            values["consecutive_failures"] = int(values["consecutive_failures"])
        values["updated_at"] = utc_now()
        # Column identifiers come exclusively from the fixed allowlist above; data is bound.
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",  # nosec B608
                (*values.values(), str(job_id)),
            )
            self._conn.commit()
            if cursor.rowcount == 0:
                raise KeyError(job_id)
        updated = self.get(job_id)
        if updated is None:
            raise KeyError(job_id)
        return updated

    def edit(
        self,
        job_id: str,
        *,
        name: str | None = None,
        schedule_text: str | None = None,
        action: Mapping[str, Any] | None = None,
        options: dict | None = None,
    ) -> Job:
        """Change what an existing job *is*, under the same rules that created it.

        Deliberately not ``update``. ``update`` is the internal field setter the runner
        uses to record outcomes, and it trusts its caller: it does not trim a name, does
        not run :func:`validate_action`, and — the trap — writes ``schedule_text`` without
        touching ``cron``. An owner-facing edit that went through it would show the new
        schedule everywhere while the job kept firing on the old one. So the cron is always
        re-derived from the text here, exactly as ``create`` derives it.

        Only owner-authored configuration is editable. Run history, failure counts
        and ``paused_reason`` are outcomes, not settings: an edit must not silently resume a
        paused job or forgive its failures — ``resume`` is the verb for that.
        """
        current = self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        if name is None and schedule_text is None and action is None and options is None:
            raise ValueError("an edit needs a name, a schedule or an action")

        fields: dict[str, Any] = {}
        if options is not None:
            fields["options"] = validate_options(options, url_screen=getattr(self, "url_screen", None))
        if name is not None:
            cleaned = " ".join(str(name).split())
            if not cleaned:
                raise ValueError("a job needs a name")
            if len(cleaned) > MAX_NAME:
                raise ValueError(f"the name is longer than {MAX_NAME} characters")
            fields["name"] = cleaned
        if action is not None or options is not None:
            errors = validate_action(action if action is not None else current.action,
                                     fields.get('options', current.options))
            if errors:
                raise ValueError("; ".join(errors))
            if action is not None:
                fields["action"] = dict(action)
        if schedule_text is not None:
            text = str(schedule_text).strip()
            if not text:
                raise ValueError("a job needs a schedule")
            cron, _description = resolve_schedule(text, zone=self._schedule_zone())
            fields["schedule_text"] = text
            fields["cron"] = cron
        job = self.update(job_id, **fields)
        if is_one_shot(job.cron) and job.cron != current.cron:
            # H450: a one-shot given a new time is a new run, whatever the old one spent.
            job = self._reset_attempts(job_id)
        return job

    def _reset_attempts(self, job_id: str) -> Job:
        with self._lock:
            self._conn.execute("UPDATE jobs SET attempts = 0 WHERE id = ?", (job_id,))
            self._conn.commit()
        job = self.get(job_id)
        if job is None:  # pragma: no cover — deleted between the two statements
            raise KeyError(job_id)
        return job

    def _schedule_zone(self):
        """The zone a one-shot said in words is anchored to: the scheduler's, once a
        runner has bound it (``schedule_zone``), else the local one."""
        zone = getattr(self, "schedule_zone", None)
        return zone() if callable(zone) else None

    def claim_tick(self, job_id: str, slot: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO job_ticks(job_id, slot) VALUES (?, ?) ON CONFLICT(job_id) "
                "DO UPDATE SET slot=excluded.slot WHERE job_ticks.slot < excluded.slot", (job_id, slot))
            self._conn.commit()
            return cursor.rowcount == 1

    def reserve_attempt(self, job_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE jobs SET attempts = attempts + 1 WHERE id = ? AND "
                "(json_extract(options, '$.repeat') IS NULL OR attempts < json_extract(options, '$.repeat')) "
                "AND (cron NOT LIKE '@at %' OR attempts < 1)",
                (job_id,),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def delete(self, job_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM jobs WHERE id = ?", (str(job_id),))
            self._conn.execute("DELETE FROM job_runs WHERE job_id = ?", (str(job_id),))
            self._conn.execute("DELETE FROM job_held WHERE job_id = ?", (str(job_id),))
            self._conn.execute("DELETE FROM job_ticks WHERE job_id = ?", (str(job_id),))
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
                       SELECT id FROM job_script_attempts WHERE state NOT IN ('done','failed'))
                       AND id NOT IN (SELECT run_id FROM job_requests WHERE status='waiting' AND run_id IS NOT NULL)
                       AND id NOT IN (
                       SELECT id FROM job_runs WHERE job_id = ? ORDER BY id DESC LIMIT ?)""",
                (str(job_id), str(job_id), MAX_RUNS_KEPT),
            )
            self._conn.commit()
        return JobRun(run_id, str(job_id), started_at, finished_at, status, summary, error)

    # held deliveries (quiet hours) ---------------------------------------

    def hold(self, job_id: str, text: str, channel: str | None) -> int:
        """Keep *text* for delivery after quiet hours; the newest MAX_HELD_PER_JOB stay."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO job_held (job_id, text, channel, created_at) VALUES (?, ?, ?, ?)",
                (str(job_id), str(text or "")[:MAX_TEXT], channel, utc_now()),
            )
            held_id = int(cursor.lastrowid)
            self._conn.execute(
                """DELETE FROM job_held WHERE job_id = ? AND id NOT IN (
                       SELECT id FROM job_held WHERE job_id = ? ORDER BY id DESC LIMIT ?)""",
                (str(job_id), str(job_id), MAX_HELD_PER_JOB),
            )
            self._conn.commit()
        return held_id

    def held(self, limit: int = 100) -> list[HeldDelivery]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_held ORDER BY id ASC LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        return [HeldDelivery(int(r["id"]), r["job_id"], r["text"], r["channel"], r["created_at"]) for r in rows]

    def held_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM job_held").fetchone()
        return int(row["n"]) if row else 0

    def release(self, held_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM job_held WHERE id = ?", (int(held_id),))
            self._conn.commit()
        return cursor.rowcount > 0

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
        quiet: Callable[[], bool] | None = None,
    ) -> None:
        self.store = store
        # H450: one-shots said in words are anchored to the scheduler's zone.
        self.store.schedule_zone = self.scheduler_timezone
        self._orch = orch
        self._scheduler = scheduler
        self._now = now
        # Test seam; production reads the ambient quiet-hours window per call.
        self._quiet = quiet
        from .jobs_scripts import ScriptRuntime
        self._script_runtime = ScriptRuntime(self)
        from .jobs_media import ScheduledMedia
        self.media = ScheduledMedia(self)

    def bind_scripts(self, *, submit, get, find):
        self._script_runtime.bind(submit=submit, get=get, find=find)

    def bind_url_monitor(self, adapter):
        self._script_runtime.url_adapter = adapter
        self.store.url_screen = adapter.screen
        self.register_scripts()

    async def reconcile_scripts(self):
        return await self._script_runtime.reconcile()

    def register_scripts(self):
        sched = self._scheduler()
        if sched is not None:
            sched.add_job(self.reconcile_scripts, 'interval', seconds=30,
                          id='jobs-script-completion', replace_existing=True,
                          misfire_grace_time=300, max_instances=1)

    # scheduler --------------------------------------------------------------

    def scheduler_timezone(self):
        """Use the configured scheduler zone, or the same local default as APScheduler."""
        from apscheduler.util import astimezone
        from tzlocal import get_localzone

        sched = self._scheduler()
        return astimezone(getattr(sched, "timezone", None) or get_localzone())

    def scheduler_alive(self) -> bool:
        sched = self._scheduler()
        return sched is not None and bool(getattr(sched, "running", False))

    def register(self, job: Job) -> bool:
        sched = self._scheduler()
        if sched is None:
            return False
        if is_one_shot(job.cron):
            sched.add_job(self.fire, "date", args=[job.id], id=f"job-{job.id}", replace_existing=True,
                          misfire_grace_time=300, run_date=run_at(job.cron))
            return True
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

    def request_run(self, job_id: str) -> dict:
        receipt = self.store.dispatch.enqueue(job_id)
        self.register_manual()
        return receipt

    async def drain_manual(self):
        await self.store.dispatch.drain(self)

    def register_manual(self):
        sched = self._scheduler()
        if sched is not None:
            if any(getattr(job, 'id', None) == 'jobs-manual-dispatch' for job in sched.get_jobs()):
                return
            sched.add_job(self.drain_manual, 'interval', seconds=5,
                          id='jobs-manual-dispatch', replace_existing=True,
                          misfire_grace_time=300, max_instances=1)

    def register_all(self) -> int:
        self.register_manual()
        registered = 0
        for job in self.store.list():
            if job.runnable and self.register(job):
                registered += 1
        self.register_flush()
        if any((j.options.get('script') or (j.options.get('monitor_script') or j.options.get('monitor_url'))) for j in self.store.list()) or self.store.script_attempts.rows():
            self.register_scripts()
        return registered

    def register_flush(self) -> bool:
        """The periodic pass that delivers held messages once quiet hours end."""
        sched = self._scheduler()
        if sched is None:
            return False
        sched.add_job(
            self.flush_held,
            "interval",
            minutes=HELD_FLUSH_MINUTES,
            id=HELD_FLUSH_JOB_ID,
            replace_existing=True,
            misfire_grace_time=300,
        )
        return True

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
            "timezone": str(self.scheduler_timezone()),
            "registered": self.registered_ids(),
            "jobs": len(jobs),
            "runnable": sum(1 for job in jobs if job.runnable),
            "paused": sum(1 for job in jobs if job.paused_reason),
            "held": self.store.held_count(),
            "quiet_hours": self.quiet_hours(),
        }

    def doctor(self) -> dict:
        from .jobs_health import inspect_jobs

        return inspect_jobs(self)

    async def tick(self, now: datetime | None = None) -> list[JobRun]:
        """Fallback ticker; never competes with the running APScheduler. No catch-up burst."""
        if self.scheduler_alive():
            raise ValueError("scheduler is running; manual tick would compete with it")
        await self.reconcile_scripts()
        await self.drain_manual()
        timezone = self.scheduler_timezone()
        now = (now or datetime.now(UTC)).astimezone(timezone)
        slot = now.replace(second=0, microsecond=0)
        runs = []
        for job in self.store.list():
            if not job.runnable:
                continue
            due = schedule_trigger(job.cron, timezone).get_next_fire_time(None, slot)
            # A one-shot's time need not fall on a minute: it is due in the minute it is in.
            if due is not None and due.replace(second=0, microsecond=0) == slot \
                    and self.store.claim_tick(job.id, slot.astimezone(UTC).isoformat()):
                runs.append(await self.fire(job.id))
        return runs

    # lifecycle --------------------------------------------------------------

    def _toolset_names(self, options):
        from ..job_toolsets import resolve
        if options is not None and not isinstance(options, dict):
            raise ValueError("options must be an object")
        return resolve((options or {}).get('enabled_toolsets'), getattr(self._orch, 'tool_rpc', None))

    def create(self, **kwargs: Any) -> Job:
        return self.arm(**kwargs)[0]

    def arm(self, *, first_run: bool | None = None, **kwargs: Any) -> tuple[Job, dict | None, str]:
        """Create and schedule a job and, when first_run_decision agrees, queue a first run now.

        The first run is a dispatch request drained by _fire_once under the shared job
        gate like a cron slot: origin 'first_run' when the policy chose it, which the
        drain checks against first_run_policy again (first_run_due), or
        'first_run_asked' when the create call asked for it. The emergency stop, pause
        (pausing cancels it; the drain re-checks), validation, the repeat reservation
        and the quiet-hours hold all apply. ``first_run`` is a creation-time choice,
        never a stored option. Returns the job, the request's receipt (None when none
        was queued) and the confirmation every surface prints.
        """
        self._toolset_names(kwargs.get('options'))
        binding = self.media.prepare(kwargs.get("action") or {}, kwargs.get("options"))
        job = self.store.create(**kwargs)
        self.media.bind(job, binding)
        if job.options.get('script') or (job.options.get('monitor_script') or job.options.get('monitor_url')):
            self.register_scripts()
        self.register(job)
        timing = self.slot_timing(job) or (None, None)
        fire, why = first_run_decision(job, explicit=first_run, quiet=self.quiet_hours(),
                                       seconds_to_slot=timing[0], slot_gap=timing[1])
        receipt = None
        if fire:
            try:
                receipt = self.store.dispatch.enqueue(job.id, origin="first_run_asked" if first_run else "first_run")
                self.register_manual()
            except (ValueError, sqlite3.Error) as exc:
                # The job is armed either way; a refused first run must not read as a
                # refused job (a retry would arm a duplicate).
                logger.warning("job %s: first run not queued: %s", job.id, exc)
                receipt, why = None, f"not queued ({exc})"
        return job, receipt, arm_confirmation(job, receipt, why=why, scheduler_alive=self.scheduler_alive())

    def slot_timing(self, job: Job, now: datetime | None = None) -> tuple[float, float | None] | None:
        """Seconds until the job's next cron slot and from it to the one after, in the
        scheduler's timezone, or None when the cron cannot be read. A one-shot has no slot
        after its own."""
        try:
            timezone = self.scheduler_timezone()
            current = (now or datetime.now(UTC)).astimezone(timezone)
            trigger = schedule_trigger(job.cron, timezone)
            due = trigger.get_next_fire_time(None, current)
            after = trigger.get_next_fire_time(due, due) if due is not None else None
        except Exception:
            return None
        if due is None:
            return None
        return (due - current).total_seconds(), (None if after is None else (after - due).total_seconds())

    def first_run_due(self, job_id: str) -> tuple[bool, str]:
        """first_run_policy again, when a queued first run comes to run (H687).

        The request is durable: it can wait for a scheduler that was down, or outlive
        an edit, and by then the job may be a calendar schedule, a reminder or
        repeat-limited, quiet hours may have begun, or its first slot may be near. Pause
        is left to _fire_once, which records the skip as it does for a cron slot; a
        first run the owner asked for ('first_run_asked') is not checked here.
        """
        job = self.store.get(job_id)
        if job is None:
            return False, "job deleted"
        timing = self.slot_timing(job) or (None, None)
        return first_run_policy(job, quiet=self.quiet_hours(), seconds_to_slot=timing[0], slot_gap=timing[1])

    def edit(self, job_id: str, **fields: Any) -> Job:
        """Apply an owner's edit and make the scheduler agree with it.

        Re-registering is the half that makes an edit real: ``add_job`` with
        ``replace_existing`` rebuilds the trigger from the new cron, so a rescheduled job
        stops firing on its old times. A job that is not runnable (paused, or disabled) is
        unregistered instead — editing a paused job must leave it paused, and leaving a
        stale trigger armed for it would resume it by accident.
        """
        from .jobs_dispatch import identity

        current = self.store.get(job_id)
        if current is None:
            raise KeyError(job_id)
        before = identity(current)
        self._toolset_names(fields["options"] if fields.get("options") is not None else current.options)
        binding = None
        if fields.get("action") is not None:
            options = fields["options"] if fields.get("options") is not None else current.options
            binding = self.media.prepare(fields["action"], options)
        job = self.store.edit(job_id, **fields)
        if fields.get("action") is not None:
            self.media.bind(job, binding)
        if job.options.get('script') or (job.options.get('monitor_script') or job.options.get('monitor_url')):
            self.register_scripts()
        if job.runnable:
            self.register(job)
        else:
            self.unregister(job_id)
        # H687 — a first run still queued was promised for the job as armed. An edit to
        # what runs (action or options) would have the claim drop it, so it is queued
        # again for the edited job; a rename or a new schedule leaves it as it is. Either
        # way the drain checks the edited job against the first-run policy.
        if identity(job) != before:
            self._requeue_first_run(job)
        return job

    def _requeue_first_run(self, job: Job) -> None:
        for origin in ("first_run", "first_run_asked"):
            if not self.store.dispatch.cancel_queued(job.id, origin=origin,
                                                     reason="configuration changed before the first run"):
                continue
            if not job.runnable:
                continue
            try:
                self.store.dispatch.enqueue(job.id, origin=origin)
                self.register_manual()
            except (ValueError, sqlite3.Error) as exc:
                # The edit is saved either way; only its first run is lost.
                logger.warning("job %s: first run not queued again after the edit: %s", job.id, exc)

    def pause(self, job_id: str, reason: str) -> Job:
        job = self.store.pause(job_id, reason)
        self.unregister(job_id)
        self.store.dispatch.cancel_queued(job_id, origin=("first_run", "first_run_asked"),
                                          reason="job paused before its first run")
        return job

    def resume(self, job_id: str) -> Job:
        job = self.store.resume(job_id)
        self.register(job)
        return job

    def delete(self, job_id: str) -> bool:
        self.unregister(job_id)
        removed = self.store.delete(job_id)
        if removed:
            self.media.remove(job_id)
        return removed

    # firing -----------------------------------------------------------------

    async def fire(self, job_id: str, *, force: bool = False) -> JobRun:
        """The shared cross-process cron/manual execution gate."""
        while True:
            with self.store.dispatch.gate(job_id) as acquired:
                if acquired:
                    return await self._fire_once(job_id, force=force)
            # Hash collisions may serialize unrelated jobs, but never discard cron
            # firings. Cancellation remains interruptible without holding a lock.
            await asyncio.sleep(0.05)

    async def _fire_once(self, job_id: str, *, force: bool = False, expected_identity: str | None = None) -> JobRun:
        """Execute only while the caller holds the shared job gate."""
        from agents.core import estop

        started = utc_now()
        job = self.store.get(job_id)
        if job is None:
            return JobRun(0, job_id, started, started, STATUS_SKIPPED, "job no longer exists")
        if expected_identity is not None:
            from .jobs_dispatch import identity
            if identity(job) != expected_identity:
                return self.store.record_run(job_id, started_at=started, finished_at=utc_now(),
                                             status=STATUS_SKIPPED, summary="configuration changed after request claim")
        if not force and not job.runnable:
            spent = is_one_shot(job.cron) and job.attempts >= 1
            return self.store.record_run(
                job_id, started_at=started, finished_at=utc_now(), status=STATUS_SKIPPED,
                summary=ONE_SHOT_SPENT if spent else f"paused: {job.paused_reason or 'disabled'}",
            )
        if estop.check_paused(f"job:{job_id}", logger):
            return self.store.record_run(
                job_id, started_at=started, finished_at=utc_now(), status=STATUS_SKIPPED,
                summary="emergency stop engaged",
            )
        try:
            validate_options(job.options, check_scripts=False, url_screen=getattr(self.store, "url_screen", None))
            errors = validate_action(job.action, job.options)
            if errors:
                raise ValueError('; '.join(errors))
        except ValueError as exc:
            return self._failed(job, started, exc)
        if is_one_shot(job.cron) and not self.store.reserve_attempt(job_id):
            # H450: the one run is reserved before any executor, script ones included.
            self.unregister(job_id)
            return self.store.record_run(job_id, started_at=started, finished_at=utc_now(),
                                         status=STATUS_SKIPPED, summary=ONE_SHOT_SPENT)
        if job.options.get('script') or (job.options.get('monitor_script') or job.options.get('monitor_url')):
            return await self._script_runtime.fire(job, started)
        if not is_one_shot(job.cron) and not self.store.reserve_attempt(job_id):
            self.unregister(job_id)
            return self.store.record_run(job_id, started_at=started, finished_at=utc_now(),
                                         status=STATUS_SKIPPED, summary="repeat limit exhausted")
        from .jobs_gates import JobSuppressed
        try:
            summary, notepad = await self._execute(job)
        except JobSuppressed as suppressed:
            summary, notepad = f"Suppressed: {suppressed.reason}", suppressed.notepad
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
            updated = self.store.update(job.id, **fields)
            if not updated.runnable:
                self.unregister(job.id)
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
        urgent = action.get("urgent") is True
        if kind == "remind":
            delivered = await self._deliver(
                str(action.get("message", "")), action.get("channel"), job=job, urgent=urgent,
            )
            if job.options.get("deliver") == []:
                return str(action.get("message", ""))[:MAX_TEXT], None
            return f"reminder {delivered}", None
        if kind == "brief":
            text = await self._brief(str(action.get("kind", "morning")))
            delivered = await self._deliver(text, None, job=job, urgent=urgent)
            if job.options.get("deliver") == []:
                return text[:MAX_TEXT], None
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
        from ..job_toolsets import toolset_scope
        from ..llm.job_selection import SelectionError, selection_scope
        with toolset_scope(self._toolset_names(job.options)), selection_scope(job.options) as selection:
            if selection is not None:
                router = getattr(self._orch, "llm_router", None)
                if not callable(getattr(router, "select_backend", None)):
                    raise SelectionError("job pins require the governed model router")
                router.select_backend(str(action.get("agent") or "jarvis"), prompt)
            reply = await process(prompt, agent=str(action.get("agent") or "jarvis"), channel="job")
        reply = str(reply or "").strip()
        if not reply:
            raise RuntimeError("the agent returned no answer (no model backend, or a degraded reply)")
        from .jobs_gates import JobSuppressed, is_silent_response
        if is_silent_response(reply):
            raise JobSuppressed("model_silent", notepad=reply[:MAX_NOTEPAD])
        summary = reply[:MAX_TEXT]
        if action.get("deliver", True):
            delivered = await self._deliver(reply, None, job=job, urgent=action.get("urgent") is True)
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

    # quiet hours ------------------------------------------------------------

    def quiet_hours(self) -> bool:
        """True while a job's message should wait rather than wake the owner."""
        if self._quiet is not None:
            try:
                return bool(self._quiet())
            except Exception:
                return False
        from .schedule_runtime import is_night

        return is_night(
            time.localtime(self._now()).tm_hour,
            start=setting_hour(self._orch, QUIET_START_SETTING, DEFAULT_QUIET_START),
            end=setting_hour(self._orch, QUIET_END_SETTING, DEFAULT_QUIET_END),
        )

    def _spend_interrupt(self, job: Job) -> bool:
        """One unit of the owner's daily interrupt budget, or False when there is none left
        (or no budget at all — an urgent push with nothing to account for it waits)."""
        autonomy = getattr(self._orch, "autonomy", None)
        budget = getattr(autonomy, "budget", None)
        consume = getattr(budget, "consume", None)
        if not callable(consume):
            return False
        try:
            return bool(consume(delivery_id=f"job-{job.id}-{int(self._now())}", channel_class="job"))
        except Exception:
            logger.warning("job interrupt budget could not be consulted; holding", exc_info=True)
            return False

    async def flush_held(self) -> int:
        """Deliver held messages once quiet hours are over. Returns how many went out;
        the first refusal stops the pass so nothing is delivered out of order."""
        from agents.core import estop

        if self.quiet_hours() or estop.check_paused("jobs-held-flush", logger):
            return 0
        delivered = await self.media.flush_held()
        for item in self.store.held():
            try:
                fragment = await self._send_tracked(item.text, item.channel, item.job_id)
            except Exception as exc:
                logger.warning("held job message could not be delivered: %s", exc)
                break
            self.store.release(item.id)
            now = utc_now()
            self.store.record_run(
                item.job_id, started_at=now, finished_at=now, status=STATUS_OK,
                summary=f"{fragment} from hold (held since {item.created_at})",
            )
            delivered += 1
        return delivered

    async def _deliver(self, text: str, channel: str | None, *, job: Job | None = None,
                       urgent: bool = False) -> str:
        """Send *text* to the owner, or hold it through quiet hours; returns a summary
        fragment, raises when it cannot send."""
        if job is not None and "media_ids" in job.action:
            return await self.media.deliver(job, text)
        if job is not None and "deliver" in job.options:
            targets = job.options["deliver"]
            if not targets:
                return "kept in run history (delivery disabled)"
            channels = getattr(self._orch, "channels", None) or {}
            missing = [target for target in targets if target not in channels]
            if missing:
                with contextlib.suppress(KeyError):
                    self.store.update(job.id, last_delivery_status=STATUS_FAILED)
                raise RuntimeError(f"delivery channels are not connected: {', '.join(missing)}")
            scoped = replace(job, options={k: v for k, v in job.options.items() if k != "deliver"})
            return "; ".join([await self._deliver(text, target, job=scoped, urgent=urgent) for target in targets])
        if job is not None and self.quiet_hours():
            if urgent and self._spend_interrupt(job):
                fragment = await self._send_tracked(text, channel, job.id if job else None)
                return f"{fragment} (urgent, during quiet hours)"
            self.store.hold(job.id, text, channel)
            if urgent:
                return "held until quiet hours end (interrupt budget spent)"
            return "held until quiet hours end"
        return await self._send_tracked(text, channel, job.id if job else None)

    async def _send_tracked(self, text: str, channel: str | None, job_id: str | None) -> str:
        try:
            result = await self._send(text, channel)
        except Exception:
            if job_id is not None:
                with contextlib.suppress(KeyError):
                    self.store.update(job_id, last_delivery_status=STATUS_FAILED)
            raise
        if job_id is not None:
            with contextlib.suppress(KeyError):
                self.store.update(job_id, last_delivery_status=STATUS_OK)
        return result

    async def _send(self, text: str, channel: str | None) -> str:
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
