"""run_store.py — 0.34: persist workflow RUN history so it survives a restart.

The engine keeps recent runs in an in-memory ring (`deque`); this optionally mirrors
them to disk as a single **capped** JSON array, so the visual run-history overlay
isn't empty after a restart. **Opt-in**: the engine attaches a store only when
``JARVIS_WORKFLOW_PERSIST`` is set, so the default path is byte-for-byte unchanged.

The store is bounded (``max_keep``, oldest pruned on write) and written atomically
(temp file + ``os.replace``), mirroring :class:`WorkflowStore`.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from agents.core.paths import data_path

_DEFAULT_FILE = data_path("workflows") / "runs.json"
_DEFAULT_MAX_KEEP = 200


class WorkflowRunStore:
    """Bounded, atomically-written JSON store of recent workflow run records."""

    def __init__(self, path: Path | str | None = None, *, max_keep: int = _DEFAULT_MAX_KEEP) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_keep = max(1, int(max_keep))

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return []
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    def _write_atomic(self, runs: list[dict]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(runs, fh, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def record(self, run: dict) -> None:
        """Append a run record, keeping only the most recent ``max_keep`` (oldest pruned)."""
        runs = self._read()
        runs.append(dict(run))
        if len(runs) > self._max_keep:
            runs = runs[-self._max_keep:]
        self._write_atomic(runs)

    def all(self) -> list[dict]:
        """Chronological (oldest-first) — used to seed the engine's in-memory ring."""
        return self._read()

    def list(self, limit: int = 20) -> list[dict]:
        """Most-recent-first, capped at *limit* (matches ``WorkflowEngine.recent``)."""
        runs = self._read()
        runs.reverse()
        return runs[:max(1, int(limit))]
