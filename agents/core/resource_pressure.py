"""H161 — warn when the box is running out of memory or disk.

Hermes ranks five conditions and shows only the worst one the owner has not
dismissed: ``disk_critical`` > ``memory_critical`` > ``oom_restart_suspected`` >
``disk_elevated`` > ``memory_elevated``. This module is that watch, apart from the
autonomy observer (whose samples stop with autonomy off or ESTOP engaged):

- **Thresholds** are the observer's (85 % elevated, 95 % critical, for memory and for
  every watched volume — ``/`` and the data home's).
- **Hysteresis.** A condition is raised at once; it clears — or steps down from
  critical to elevated — only after :data:`RECOVERY_SAMPLES` samples in a row under
  its line by :data:`RECOVERY_MARGIN` points, so a flapping reading does not clear and
  re-raise it. A sample that could not be read changes nothing.
- **A suspected OOM restart.** A small state file in the data home holds the boot id,
  the last memory level and a clean-shutdown mark. A start on the same boot, after a
  run that ended without that mark while memory was elevated or critical, is
  suspected to be a restart after the kernel's OOM killer (or a crash under memory
  pressure) — "suspected", because nothing here can read the kernel's log.
- **Dismissal** is per condition and per boot: it lasts through a restart on the same
  boot, a new boot re-arms it, and so does the condition's recovery (a new episode is
  a new warning).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.pressure")

CONDITIONS = ("disk_critical", "memory_critical", "oom_restart_suspected", "disk_elevated", "memory_elevated")
DEFAULT_THRESHOLDS = {"ram_warn": 85.0, "ram_critical": 95.0, "disk_warn": 85.0, "disk_critical": 95.0}
RECOVERY_SAMPLES = 3
RECOVERY_MARGIN = 5.0
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
STATE_FILE = "resource_pressure.json"
LEVEL_NAMES = {1: "elevated", 2: "critical"}


@dataclass(frozen=True)
class Sample:
    memory: float | None
    disks: dict[str, float] = field(default_factory=dict)


def _psutil():
    try:
        import psutil
    except ImportError:
        return None
    return psutil


def _boot_time() -> float | None:
    ps = _psutil()
    try:
        return float(ps.boot_time()) if ps is not None else None
    except Exception:
        return None


def current_boot_id() -> str:
    """The kernel's boot id, else one derived from the boot time, else ``unknown``."""
    try:
        text = BOOT_ID_PATH.read_text(encoding="ascii").strip()
        if text:
            return text
    except OSError:
        pass
    booted = _boot_time()
    return f"boot-{int(booted)}" if booted is not None else "unknown"


def take_sample(paths: list[str]) -> Sample:
    """Memory percent and each distinct watched path's disk percent, as psutil sees them."""
    ps = _psutil()
    if ps is None:
        return Sample(memory=None, disks={})
    try:
        memory = float(ps.virtual_memory().percent)
    except Exception:
        memory = None
    disks: dict[str, float] = {}
    for path in paths:
        if path in disks:
            continue
        try:
            disks[path] = float(ps.disk_usage(path).percent)
        except Exception:
            logger.debug("disk probe failed for %s", path, exc_info=True)
    return Sample(memory=memory, disks=disks)


class _Held:
    """One resource's raised level, with the samples counted toward its recovery."""

    def __init__(self) -> None:
        self.level = 0
        self.quiet = 0
        self.since: float | None = None

    def update(self, value: float, warn: float, critical: float, now: float) -> bool:
        """Fold one reading in; True when the level changed."""
        raw = 2 if value >= critical else 1 if value >= warn else 0
        if raw >= self.level:
            changed = raw != self.level
            if changed:
                self.since = now
            self.level, self.quiet = raw, 0
            return changed
        calm = value + RECOVERY_MARGIN
        settled = 2 if calm >= critical else 1 if calm >= warn else 0
        if settled >= self.level:
            self.quiet = 0                  # under the line, but not by the margin
            return False
        self.quiet += 1
        if self.quiet < RECOVERY_SAMPLES:
            return False
        self.level, self.quiet = settled, 0
        self.since = now
        return True


class PressureMonitor:
    def __init__(self, state_path: Path | str, *, boot_id: str | None = None,
                 thresholds: dict | None = None, sampler: Callable[[], Sample] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.state_path = Path(state_path)
        self.boot_id = boot_id if boot_id is not None else current_boot_id()
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.sampler = sampler
        self.clock = clock
        self.memory = _Held()
        self.disk = _Held()
        self.memory_percent: float | None = None
        self.disks: dict[str, float] = {}
        self.dismissed: set[str] = set()
        self.oom: dict | None = None
        self.sampled_at: float | None = None
        # The route samples on a worker thread and the scheduler on another.
        self._lock = threading.RLock()

    # ── the state file ───────────────────────────────────────────────────────

    def _read_state(self) -> dict | None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return state if isinstance(state, dict) else None

    def _write_state(self, *, clean: bool = False) -> None:
        state = {"boot_id": self.boot_id, "clean_shutdown": clean, "memory_level": self.memory.level,
                 "dismissed": sorted(self.dismissed), "pid": os.getpid()}
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            logger.debug("could not write the pressure state file", exc_info=True)
            with contextlib.suppress(OSError):
                tmp.unlink()

    def start(self) -> None:
        """Read what the last run left, suspect an OOM restart if it says so, and mark
        this run as not (yet) cleanly stopped."""
        with self._lock:
            self._start()

    def _start(self) -> None:
        previous = self._read_state()
        if previous is not None and previous.get("boot_id") == self.boot_id:
            dismissed = previous.get("dismissed")
            if isinstance(dismissed, list):
                self.dismissed = {c for c in dismissed if c in CONDITIONS}
            level = previous.get("memory_level")
            if previous.get("clean_shutdown") is False and isinstance(level, int) and level in LEVEL_NAMES:
                self.oom = {"memory_level": LEVEL_NAMES[level], "since": self.clock()}
                logger.warning("the hub restarted on the same boot after a run that did not stop cleanly "
                               "while memory was %s: suspected out-of-memory restart", LEVEL_NAMES[level])
        self._write_state()

    def stop(self) -> None:
        """The clean-shutdown mark: the next start on this boot suspects nothing."""
        with self._lock:
            self._write_state(clean=True)

    # ── sampling ─────────────────────────────────────────────────────────────

    def observe(self, sample: Sample) -> None:
        with self._lock:
            self._observe(sample)

    def _observe(self, sample: Sample) -> None:
        now = self.clock()
        self.sampled_at = now
        t = self.thresholds
        before = self._active()
        memory_changed = False
        if sample.memory is not None:
            self.memory_percent = sample.memory
            memory_changed = self.memory.update(sample.memory, t["ram_warn"], t["ram_critical"], now)
        if sample.disks:
            self.disks = dict(sample.disks)
            self.disk.update(max(sample.disks.values()), t["disk_warn"], t["disk_critical"], now)
        cleared = before - self._active()
        if cleared & self.dismissed:
            self.dismissed -= cleared          # recovery re-arms: a new episode is a new warning
            self._write_state()
        elif memory_changed:
            self._write_state()

    def tick(self) -> dict:
        if self.sampler is not None:
            self.observe(self.sampler())
        return self.snapshot()

    def fresh(self, max_age: float) -> dict:
        """The snapshot, sampling first when the last sample is older than *max_age*."""
        if self.sampled_at is None or self.clock() - self.sampled_at >= max_age:
            return self.tick()
        return self.snapshot()

    # ── what is shown ────────────────────────────────────────────────────────

    def _active(self) -> set[str]:
        active = set()
        if self.memory.level:
            active.add(f"memory_{LEVEL_NAMES[self.memory.level]}")
        if self.disk.level:
            active.add(f"disk_{LEVEL_NAMES[self.disk.level]}")
        if self.oom is not None:
            active.add("oom_restart_suspected")
        return active

    def _entry(self, condition: str) -> dict[str, Any]:
        entry: dict[str, Any] = {"condition": condition, "dismissed": condition in self.dismissed}
        if condition == "oom_restart_suspected":
            return {**entry, "level": "suspected", **(self.oom or {})}
        held = self.memory if condition.startswith("memory") else self.disk
        entry.update(level=LEVEL_NAMES[held.level], since=held.since)
        if condition.startswith("memory"):
            entry["percent"] = self.memory_percent
            return entry
        near = self.thresholds["disk_warn"] - RECOVERY_MARGIN
        paths = [{"path": p, "percent": v} for p, v in sorted(self.disks.items(), key=lambda kv: -kv[1]) if v >= near]
        entry["percent"] = max(self.disks.values()) if self.disks else None
        entry["paths"] = paths
        return entry

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        active = self._active()
        conditions = [self._entry(c) for c in CONDITIONS if c in active]
        worst = next((c for c in conditions if not c["dismissed"]), None)
        return {"boot_id": self.boot_id, "conditions": conditions, "worst": worst, "sampled_at": self.sampled_at}

    def dismiss(self, condition: str, boot_id: str) -> bool:
        """Dismiss one condition for this boot; refused for another boot's page, an
        unknown condition, or one that is not raised."""
        with self._lock:
            if boot_id != self.boot_id or condition not in CONDITIONS or condition not in self._active():
                return False
            self.dismissed.add(condition)
            self._write_state()
            return True


_MONITOR: PressureMonitor | None = None


def watched_paths() -> list[str]:
    from .paths import data_root

    data = str(data_root())
    return [os.path.abspath(os.sep), data]


def monitor() -> PressureMonitor:
    """The process's one watch, over ``/`` and the data home's volume."""
    global _MONITOR
    if _MONITOR is None:
        from .paths import data_root

        _MONITOR = PressureMonitor(Path(data_root()) / STATE_FILE,
                                   sampler=lambda: take_sample(watched_paths()))
    return _MONITOR


__all__ = [
    "CONDITIONS", "DEFAULT_THRESHOLDS", "RECOVERY_MARGIN", "RECOVERY_SAMPLES", "PressureMonitor", "Sample",
    "current_boot_id", "monitor", "take_sample", "watched_paths",
]
