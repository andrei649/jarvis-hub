"""runtime_state.py — crash-safe persisted state for the Always-On runtime.

One small JSON document under the data root records everything the coordinator
needs to resume after any exit — clean stop, crash, or kill -9:

    boot_id             increments on every coordinator boot (restart forensics)
    cycle               monotonic cycle counter across restarts
    last_cycle_ts       ISO timestamp of the newest completed cycle
    last_status         "clean" | "degraded" | "error" of that cycle
    consecutive_clean   clean-cycle streak (resets on any non-clean cycle)

Writes are atomic (tmp file + `os.replace`) so a crash mid-save leaves the
previous state intact rather than a half-written file. A corrupt file is moved
aside (`state.json.corrupt-<epoch>`) and replaced with defaults — the runtime
must boot from anything; losing a counter is recoverable, refusing to start is
not. Stdlib-only, unit-testable offline.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("jarvis.autonomy.runtime")

STATE_VERSION = 1


def default_state_path() -> Path:
    """`$JARVIS_RUNTIME_STATE`, else `<data root>/runtime/state.json`."""
    env = os.environ.get("JARVIS_RUNTIME_STATE", "").strip()
    if env:
        return Path(env).expanduser()
    from agents.core.paths import data_path

    return Path(data_path("runtime", "state.json"))


def _defaults() -> dict:
    return {
        "version": STATE_VERSION,
        "boot_id": 0,
        "cycle": 0,
        "last_cycle_ts": None,
        "last_status": None,
        "consecutive_clean": 0,
        "updated_at": None,
    }


class RuntimeStateStore:
    def __init__(self, path: Path | str | None = None):
        self.path = default_state_path() if path is None else Path(path)

    def load(self) -> dict:
        """Read state; defaults on missing, quarantine-and-default on corrupt."""
        state = _defaults()
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return state
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("state root is not an object")
        except ValueError:
            quarantine = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            try:
                os.replace(self.path, quarantine)
                logger.warning("runtime state was corrupt — moved to %s", quarantine)
            except OSError:
                logger.warning("runtime state was corrupt and could not be quarantined")
            return state
        for key in state:
            if key in data:
                state[key] = data[key]
        # Untrusted-on-disk hygiene: the counters must be usable ints.
        for key in ("boot_id", "cycle", "consecutive_clean"):
            try:
                state[key] = max(0, int(state[key]))
            except (TypeError, ValueError):
                state[key] = 0
        return state

    def save(self, state: dict) -> None:
        """Atomic write; never raises (a lost save costs a counter, not the loop)."""
        state = dict(state)
        state["version"] = STATE_VERSION
        state["updated_at"] = time.time()
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(state, ensure_ascii=False, separators=(",", ":"), default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError:
            logger.debug("runtime state save failed", exc_info=True)
