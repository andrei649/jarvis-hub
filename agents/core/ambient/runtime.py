"""Default-off composition root for the H33 ambient monitor framework."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core.paths import data_path

from .engine import AmbientEngine
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
    generation: int = 0
    orch_id: int = 0

    def close(self) -> None:
        if self.store is not None:
            self.store.close()


def _setting(orch: object | None, name: str, default: Any = None) -> Any:
    getter = getattr(orch, "get_setting", None)
    return getter(name, default) if callable(getter) else default


def _enabled(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("ambient.enabled must be boolean")
    return value


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
    engine = AmbientEngine(store=store, registry=registry, enabled=True)
    return AmbientRuntime(
        True,
        "ready",
        "",
        store=store,
        registry=registry,
        engine=engine,
        generation=generation,
        orch_id=orch_id,
    )


__all__ = ["AmbientRuntime", "build_ambient_runtime"]
