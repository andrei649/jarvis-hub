"""Default-off composition root for the H33 ambient monitor framework."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents.core.memory.bitemporal import BiTemporalKG
from agents.core.memory.decay import DecayMemory
from agents.core.paths import data_path

from .engine import AmbientEngine
from .memory import AmbientSituationMemory
from .proposals import AmbientProposalSink
from .registry import MonitorRegistry
from .store import AmbientStore


@dataclass
class AmbientRuntime:
    enabled: bool
    status: str
    reason: str
    store: AmbientStore | None = None
    registry: MonitorRegistry | None = None
    engine: AmbientEngine | None = None
    memory: AmbientSituationMemory | None = None
    attention_ledger: object | None = None
    generation: int = 0
    orch_id: int = 0

    def close(self) -> None:
        if self.memory is not None:
            self.memory.close()
        if self.store is not None:
            self.store.close()


def _setting(orch: object | None, name: str, default: Any = None) -> Any:
    getter = getattr(orch, "get_setting", None)
    return getter(name, default) if callable(getter) else default


def _enabled(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("ambient.enabled must be boolean")
    return value


def _quiet_hours_provider(orch: object | None):
    timezone_name = str(_setting(orch, "general.timezone", "Europe/Bucharest"))
    try:
        owner_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        owner_timezone = ZoneInfo("UTC")
    start = _setting(orch, "ambient.quiet_hours_start", 22)
    end = _setting(orch, "ambient.quiet_hours_end", 7)
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23 for value in (start, end)):
        start, end = 22, 7

    def _quiet(timestamp: float) -> bool:
        hour = datetime.fromtimestamp(timestamp, tz=UTC).astimezone(owner_timezone).hour
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    return _quiet


def build_ambient_runtime(
    orch: object | None,
    *,
    root: str | Path | None = None,
) -> AmbientRuntime:
    orch_id = id(orch) if orch is not None else 0
    try:
        enabled = _enabled(_setting(orch, "ambient.enabled", False))
    except ValueError:
        return AmbientRuntime(False, "degraded", "ambient_config_invalid", orch_id=orch_id)
    if not enabled:
        return AmbientRuntime(False, "disabled", "ambient_disabled", orch_id=orch_id)
    generation = _setting(orch, "ambient.generation", 1)
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        return AmbientRuntime(False, "degraded", "ambient_config_invalid", orch_id=orch_id)
    runtime_root = Path(root) if root is not None else data_path("ambient")
    store = AmbientStore(runtime_root / "ambient.db")
    if store.health()["status"] != "ready":
        reason = str(store.health()["reason"])
        return AmbientRuntime(False, "degraded", reason, store=store, generation=generation, orch_id=orch_id)
    registry = MonitorRegistry(store, enabled=True)
    decay = getattr(orch, "decay", None) if orch is not None else None
    if not callable(getattr(decay, "add", None)):
        decay = DecayMemory(runtime_root / "decay.json")
    kg = getattr(orch, "bitemporal", None) if orch is not None else None
    if not callable(getattr(kg, "add_fact", None)):
        kg = BiTemporalKG(runtime_root / "situation_kg.json")
    memory = AmbientSituationMemory(
        runtime_root / "situations.db",
        decay=decay,
        kg=kg,
    )
    worker = getattr(orch, "autonomy", None) if orch is not None else None
    govern_enqueue = getattr(worker, "govern_enqueue", None)
    decision_sink = None
    if callable(govern_enqueue):
        decision_sink = AmbientProposalSink(
            govern_enqueue,
            generation_provider=lambda: generation,
            remember_sink=memory.remember,
        )
    engine = AmbientEngine(
        store=store,
        registry=registry,
        enabled=True,
        quiet_hours=_quiet_hours_provider(orch),
        decision_sink=decision_sink,
    )
    return AmbientRuntime(
        True,
        "ready",
        "",
        store=store,
        registry=registry,
        engine=engine,
        memory=memory,
        attention_ledger=getattr(orch, "attention_ledger", None) if orch is not None else None,
        generation=generation,
        orch_id=orch_id,
    )


__all__ = ["AmbientRuntime", "build_ambient_runtime"]
