"""Metadata-only camera health projection and mandatory retention scheduler."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from typing import Any

from .vault import CameraEventVault, CameraSweepReport

_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SOURCE_STATES = frozenset({"online", "offline", "degraded", "disabled", "unavailable"})


def _time(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("camera scheduler clock must be finite")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("camera scheduler clock must be finite")
    return result


def _public_timestamp(value: Any) -> float | None:
    try:
        return _time(value)
    except ValueError:
        return None


class CameraRetentionScheduler:
    """A small domain scheduler; camera TTLs never depend on general-retention settings."""

    def __init__(
        self,
        *,
        vault: CameraEventVault,
        clock: Callable[[], float] = time.time,
        interval_seconds: int = 300,
    ) -> None:
        if not isinstance(vault, CameraEventVault):
            raise ValueError("camera retention scheduler requires CameraEventVault")
        if not callable(clock):
            raise ValueError("camera retention scheduler clock must be callable")
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, int)
            or not 1 <= interval_seconds <= 900
        ):
            raise ValueError("camera retention interval must be between 1 and 900 seconds")
        self._vault = vault
        self._clock = clock
        self._interval = interval_seconds
        self._next_sweep_at = _time(clock()) + interval_seconds

    def run_due(self, *, now: float | None = None) -> CameraSweepReport | None:
        current = _time(self._clock() if now is None else now)
        if current < self._next_sweep_at:
            return None
        report = self._vault.sweep(now=current)
        self._next_sweep_at = current + self._interval
        return report

    def to_public(self) -> dict[str, float | str]:
        return {"status": "scheduled", "next_sweep_at": self._next_sweep_at}


class CameraHealthMonitor:
    """Combine source and encrypted-storage health without transport or path details."""

    def __init__(self, *, source: Any, vault: CameraEventVault) -> None:
        if not callable(getattr(source, "health", None)):
            raise ValueError("camera health source must provide health")
        if not isinstance(vault, CameraEventVault):
            raise ValueError("camera health monitor requires CameraEventVault")
        self._source = source
        self._vault = vault

    def snapshot(self) -> dict[str, Any]:
        try:
            source = self._source.health()
            state = source.status if source.status in _SOURCE_STATES else "unavailable"
            error = source.last_error
            safe_error = (
                error
                if isinstance(error, str) and _SAFE_ERROR.fullmatch(error) is not None
                else "source_error" if error else None
            )
            source_public = {
                "status": state,
                "camera_count": max(0, min(int(source.camera_count), 128)),
                "last_success_at": _public_timestamp(source.last_success_at),
                "last_error": safe_error,
            }
        except Exception:
            source_public = {
                "status": "unavailable",
                "camera_count": 0,
                "last_success_at": None,
                "last_error": "source_error",
            }
        storage = self._vault.health()
        if storage["status"] == "unavailable":
            status = "unavailable"
        elif source_public["status"] == "online":
            status = "healthy"
        else:
            status = "degraded"
        return {"status": status, "source": source_public, "storage": storage}


__all__ = ["CameraHealthMonitor", "CameraRetentionScheduler"]
