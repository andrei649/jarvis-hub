"""Per-session key/value rows for adopted Hermes state (``loop:<session>``, H460/H578).

Hermes keeps ``/loop`` state in SessionDB ``state_meta``; Nerva keeps the same rows in one
small JSON file under the data root (``sessions/session_meta.json``), written atomically.
``session_loops`` installs it into the compat layer (``hermes_compat.goals``).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path

_MAX_ROWS = 512
_MAX_ROW_BYTES = 64_000


class SessionMetaStore:
    """``get_meta`` / ``set_meta`` / ``list_meta_prefix`` over one JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("session meta store is not an object")
        return {str(k): v for k, v in data.items() if isinstance(v, str)}

    def _write(self, rows: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".session_meta.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            return self._read().get(str(key))

    def set_meta(self, key: str, value: str) -> None:
        if not isinstance(value, str) or len(value.encode("utf-8")) > _MAX_ROW_BYTES:
            raise ValueError("session meta value must be a bounded string")
        with self._lock:
            rows = self._read()
            rows[str(key)] = value
            if len(rows) > _MAX_ROWS:
                # Cleared and finished rows go first; an active row is never evicted.
                for stale in [k for k, v in rows.items() if '"status": "active"' not in v][
                        :len(rows) - _MAX_ROWS]:
                    rows.pop(stale, None)
            self._write(rows)

    def list_meta_prefix(self, prefix: str) -> list[tuple[str, str]]:
        with self._lock:
            return sorted((k, v) for k, v in self._read().items() if k.startswith(prefix))


def default_store() -> SessionMetaStore:
    from agents.core.paths import data_path

    return SessionMetaStore(data_path("sessions", "session_meta.json"))
