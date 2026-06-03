"""
json_store.py — shared base for JSON-file-backed stores (audit A3/Q1).

Captures the load / atomic-save / lock boilerplate that ~13 stores re-implemented.
Subclasses keep their own in-memory attribute(s) and override two tiny hooks:

    class WidgetStore(JsonStore):
        def _serialize(self) -> Any:        return self._widgets
        def _deserialize(self, raw) -> None: self._widgets = raw if isinstance(raw, dict) else {}

The base provides ``self.path`` and ``self._lock`` (a ``threading.Lock`` — these
stores are touched from sync code and async handlers alike) and atomic writes via
a temp file + ``replace``. Corrupt/missing files deserialize from ``{}`` so a bad
file never crashes startup.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, path: "str | Path | None") -> None:
        # path=None → in-memory only (load/save become no-ops); useful for stores
        # whose persistence is opt-in (e.g. tests, ephemeral runtime state).
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._load()

    # ── hooks (override in subclasses) ────────────────────────────────────────

    def _serialize(self) -> Any:
        """Return the JSON-serializable snapshot to persist."""
        return getattr(self, "_data", {})

    def _deserialize(self, raw: Any) -> None:
        """Populate in-memory state from parsed JSON (``{}`` if file missing/corrupt)."""
        self._data = raw if isinstance(raw, dict) else {}

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        raw: Any = {}
        if self.path is not None and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
        self._deserialize(raw)

    def _save(self) -> None:
        if self.path is None:
            return  # in-memory mode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._serialize(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)  # atomic
