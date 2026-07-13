"""Versioned owner-managed registry for declarative ambient monitors."""

from __future__ import annotations

from .contracts import MonitorDefinition
from .store import AmbientStore, AmbientStoreError

_MAX_MONITORS = 200


class MonitorRegistry:
    def __init__(self, store: AmbientStore, *, enabled: bool) -> None:
        if not isinstance(store, AmbientStore):
            raise ValueError("ambient store is required")
        if not isinstance(enabled, bool):
            raise ValueError("ambient registry enabled flag must be boolean")
        self._store = store
        self.enabled = enabled

    def create(self, definition: MonitorDefinition, *, actor: str) -> dict[str, object]:
        self._require_enabled()
        if self.get(definition.monitor_id) is not None:
            raise ValueError("monitor already exists")
        if len(self.list()) >= _MAX_MONITORS:
            raise ValueError("monitor registry is full")
        self._store.put_monitor(definition, operation="create", actor=actor)
        return {"status": "created", "monitor_id": definition.monitor_id, "version": definition.version, "definition_hash": definition.definition_hash}

    def update(self, definition: MonitorDefinition, *, actor: str) -> dict[str, object]:
        self._require_enabled()
        existing = self.get(definition.monitor_id)
        if existing is None:
            raise ValueError("monitor does not exist")
        if definition.version <= existing.version:
            raise ValueError("monitor version must increase")
        self._store.put_monitor(definition, operation="update", actor=actor)
        return {"status": "updated", "monitor_id": definition.monitor_id, "version": definition.version, "definition_hash": definition.definition_hash}

    def delete(self, monitor_id: str, *, actor: str) -> dict[str, object]:
        self._require_enabled()
        deleted = self._store.delete_monitor(monitor_id, actor=actor)
        return {"status": "deleted" if deleted else "missing", "monitor_id": monitor_id}

    def get(self, monitor_id: str) -> MonitorDefinition | None:
        try:
            return self._store.get_monitor(monitor_id)
        except AmbientStoreError:
            return None

    def list(self) -> tuple[MonitorDefinition, ...]:
        try:
            return self._store.list_monitors()
        except AmbientStoreError:
            return ()

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise AmbientStoreError("ambient_disabled")
        if self._store.health()["status"] != "ready":
            raise AmbientStoreError("ambient_store_unavailable")


__all__ = ["MonitorRegistry"]
