"""runtime_log.py — structured per-cycle run-log for the coordinator/heartbeat/
night-shift supervisor loop (H23-tail productionization).

``AutonomyCoordinator.loop()`` is the existing single supervisor tick: it already
runs the autonomy worker, the observer/reflector/curator passes, and the
night-window gate every cycle. ``RuntimeRunLog`` makes that tick *observable* —
one bounded JSON line per cycle, append-only, so an operator or the morning
brief can tail ``logs/runtime.jsonl`` and see the loop is alive without
scraping application logs. A small state file persists the cycle counter
across process restarts, so a crash-and-recover is provable (the counter
keeps climbing) rather than silently resetting to zero.

Values are booleans/counters/short strings only — never task payloads,
prompts, or credentials — so this is safe to leave on by default.
"""

from __future__ import annotations

import json
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
    never corrupts the state a restarted process reloads.
    """

    def __init__(self, *, log_path: Path | str, state_path: Path | str, clock=time.time) -> None:
        self._log_path = Path(log_path)
        self._state_path = Path(state_path)
        self._clock = clock
        self._cycle = 0
        self._load_state()

    def _load_state(self) -> None:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._cycle = 0
            return
        cycle = raw.get("cycle") if isinstance(raw, dict) else None
        if isinstance(cycle, int) and not isinstance(cycle, bool) and cycle >= 0:
            self._cycle = cycle
        else:
            self._cycle = 0

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
