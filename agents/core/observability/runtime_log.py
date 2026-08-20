"""runtime_log.py — structured per-cycle run-log for the coordinator/heartbeat/
night-shift supervisor loop (H23-tail productionization).

``AutonomyCoordinator.loop()`` is the existing single supervisor tick: it already
runs the autonomy worker, the observer/reflector/curator passes, and the
night-window gate every cycle. ``RuntimeRunLog`` makes that tick *observable* —
one bounded JSON line per cycle, append-only, so an operator or the morning
brief can tail ``logs/runtime.jsonl`` and see the loop is alive without
scraping application logs. ``read_runtime_health()`` is the consumer side of
that contract: it reads a bounded tail of the same file and reduces it to the
handful of booleans/counters the brief renders. A small state file persists the cycle counter
across process restarts, so a crash-and-recover is provable (the counter
keeps climbing) rather than silently resetting to zero.

Values are booleans/counters/short strings only — never task payloads,
prompts, or credentials — so this is safe to leave on by default.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

_MAX_KEYS = 20
_MAX_KEY_CHARS = 64
_MAX_STR_CHARS = 300
_MAX_ERROR_CHARS = 500
_MAX_LIST_ITEMS = 10


def _bounded_value(value: object) -> object:
    if isinstance(value, str):
        return value[:_MAX_STR_CHARS]
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [_bounded_value(item) for item in value[:_MAX_LIST_ITEMS]]
    if isinstance(value, dict):
        return _bounded_dict(value)
    return str(value)[:_MAX_STR_CHARS]


def _bounded_dict(value: object) -> dict:
    """Cap key/item count and string length so a run-log line can never balloon
    or leak an unexpectedly large/structured value into an append-only file."""
    if not isinstance(value, dict):
        return {"value": _bounded_value(value)}
    result: dict = {}
    for key, val in list(value.items())[:_MAX_KEYS]:
        if not isinstance(key, str):
            continue
        result[key[:_MAX_KEY_CHARS]] = _bounded_value(val)
    return result


@dataclass(frozen=True)
class RuntimeCycleRecord:
    cycle: int
    started_at: float
    duration_s: float
    ok: bool
    heartbeat: dict
    coordinator: dict
    night_shift: dict
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "started_at": self.started_at,
            "duration_s": round(self.duration_s, 3),
            "ok": self.ok,
            "heartbeat": self.heartbeat,
            "coordinator": self.coordinator,
            "night_shift": self.night_shift,
            "error": self.error,
        }


class RuntimeRunLog:
    """Append-only JSONL cycle log + a small persisted cycle-counter state file.

    Both files are written with a temp-file-then-``replace`` so a crash mid-write
    never corrupts the state a restarted process reloads. An unparseable state
    file is moved aside to ``<name>.corrupt-<epoch>`` rather than overwritten in
    place, so the evidence of *why* the counter reset survives the reset.
    """

    def __init__(self, *, log_path: Path | str, state_path: Path | str, clock=time.time) -> None:
        self._log_path = Path(log_path)
        self._state_path = Path(state_path)
        self._clock = clock
        self._cycle = 0
        self._load_state()

    def _load_state(self) -> None:
        try:
            raw_text = self._state_path.read_text(encoding="utf-8")
        except OSError:
            self._cycle = 0
            return
        try:
            raw = json.loads(raw_text)
        except ValueError:
            self._quarantine_corrupt_state()
            self._cycle = 0
            return
        cycle = raw.get("cycle") if isinstance(raw, dict) else None
        if isinstance(cycle, int) and not isinstance(cycle, bool) and cycle >= 0:
            self._cycle = cycle
        else:
            self._cycle = 0

    def _quarantine_corrupt_state(self) -> None:
        """Move an unparseable state file aside instead of discarding it silently —
        a corrupt cycle-counter file is itself a signal worth keeping for forensics.
        Best-effort: falling back to cycle 0 must succeed even if the rename fails."""
        quarantine = self._state_path.with_name(f"{self._state_path.name}.corrupt-{int(self._clock())}")
        with contextlib.suppress(OSError):
            self._state_path.replace(quarantine)

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"cycle": self._cycle, "last_run_at": self._clock()}, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        tmp.replace(self._state_path)

    @property
    def cycle(self) -> int:
        return self._cycle

    def record_cycle(
        self,
        *,
        heartbeat: dict,
        coordinator: dict,
        night_shift: dict,
        ok: bool,
        error: str = "",
        started_at: float | None = None,
    ) -> RuntimeCycleRecord:
        start = started_at if started_at is not None else self._clock()
        self._cycle += 1
        record = RuntimeCycleRecord(
            cycle=self._cycle,
            started_at=start,
            duration_s=max(0.0, self._clock() - start),
            ok=bool(ok),
            heartbeat=_bounded_dict(heartbeat),
            coordinator=_bounded_dict(coordinator),
            night_shift=_bounded_dict(night_shift),
            error=str(error)[:_MAX_ERROR_CHARS],
        )
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
        self._save_state()
        return record


# --- consumer side -----------------------------------------------------------
#
# The run-log grows one line per cycle for as long as the runtime is up, so the
# reader never loads the whole file: it seeks to the last ``_TAIL_BYTES`` and
# drops the (possibly partial) first line. That keeps the morning brief's cost
# constant no matter how long the supervisor has been running.

DEFAULT_LOG_PATH = "logs/runtime.jsonl"
DEFAULT_STATE_PATH = "logs/runtime_state.json"


def default_log_path() -> Path:
    """The run-log path producers write and consumers read.

    Single source of truth on purpose: the morning brief reads whatever file
    the coordinator writes, so a ``JARVIS_RUNTIME_LOG`` override must move both
    ends together or the brief silently reports a runtime that isn't there.
    """
    return Path(os.environ.get("JARVIS_RUNTIME_LOG", DEFAULT_LOG_PATH))


_TAIL_BYTES = 256 * 1024
_STALE_AFTER_S = 15 * 60
_HEALTH_WINDOW_S = 24 * 3600


def _read_tail_lines(path: Path, *, max_bytes: int = _TAIL_BYTES) -> list[str]:
    """Last whole lines of *path*, bounded. Returns [] for a missing/unreadable file."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            chunk = fh.read()
    except OSError:
        return []
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # the first line was cut mid-way by the seek
    return lines


def read_runtime_health(
    log_path: Path | str,
    *,
    now: float | None = None,
    stale_after_s: float = _STALE_AFTER_S,
    window_s: float = _HEALTH_WINDOW_S,
) -> dict:
    """Reduce the run-log tail to the loop-health summary the morning brief renders.

    Never raises and never blocks on a missing file: a runtime that was never
    started is reported as ``{"present": False}`` rather than as a failure, so
    the brief can simply omit the section. ``stale`` is the load-bearing field —
    a supervisor that died without writing anything leaves a *fresh-looking* last
    line, and only the age of that line reveals the loop is no longer ticking.
    """
    now = time.time() if now is None else float(now)
    lines = _read_tail_lines(Path(log_path))
    if not lines:
        return {"present": False}

    cycles = 0
    failures = 0
    respawns = 0
    last_cycle: dict | None = None
    cutoff = now - window_s

    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # a torn line is not a reason to lose the rest of the tail
        if not isinstance(entry, dict):
            continue
        event = entry.get("supervisor_event")
        if event is not None:
            at = entry.get("at")
            if event == "respawned" and isinstance(at, (int, float)) and at >= cutoff:
                respawns += 1
            continue
        if not isinstance(entry.get("cycle"), int):
            continue
        last_cycle = entry
        started_at = entry.get("started_at")
        if isinstance(started_at, (int, float)) and started_at >= cutoff:
            cycles += 1
            if entry.get("ok") is not True:
                failures += 1

    if last_cycle is None:
        # Supervisor events only (spawned, never completed a cycle yet).
        return {"present": True, "cycles_seen": 0, "respawns": respawns}

    started_at = last_cycle.get("started_at")
    age_s = round(now - started_at, 1) if isinstance(started_at, (int, float)) else None
    return {
        "present": True,
        "cycle": last_cycle.get("cycle"),
        "last_ok": last_cycle.get("ok") is True,
        "last_error": str(last_cycle.get("error") or "")[:_MAX_ERROR_CHARS],
        "age_s": age_s,
        "stale": age_s is None or age_s > stale_after_s,
        "cycles_seen": cycles,
        "failures": failures,
        "respawns": respawns,
    }
