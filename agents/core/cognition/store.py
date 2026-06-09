"""
store.py — durable cognition state base (H21.0).

A locked, keyed JSON store keyed by ``(agent, user)`` or ``session`` — durable
cognition state lives here, never as attributes on the shared orchestrator
instance. Built on the existing `JsonStore` (atomic writes, thread-safe).
"""

from __future__ import annotations

from typing import Any

from ..persistence import JsonStore


class KeyedStore(JsonStore):
    """Locked, keyed durable store for cognition submodules."""

    def _deserialize(self, raw) -> None:
        self._data = raw if isinstance(raw, dict) else {}

    def _serialize(self):
        return getattr(self, "_data", {})

    @staticmethod
    def key(*parts: str) -> str:
        """Compose a stable composite key, e.g. key(agent, user)."""
        return "::".join(str(p) for p in parts)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def delete(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            if existed:
                self._save()
            return existed

    def keys(self) -> "list[str]":
        with self._lock:
            return list(self._data.keys())
