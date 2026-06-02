"""WorkflowStore — persist user-defined Pipeline definitions as JSON (H9.1)."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from .pipeline import Pipeline

_DEFAULT_DIR = Path("memory_logs/workflows")


class WorkflowStore:
    """CRUD store for user-defined workflow pipelines.

    Each pipeline is saved as <id>.json under *path*.
    All writes are atomic (write to a tmp file, then rename).
    """

    def __init__(self, path: Optional[Path | str] = None) -> None:
        self._dir = Path(path) if path is not None else _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── internal helpers ──────────────────────────────────────────

    def _file(self, pipeline_id: str) -> Path:
        # Sanitise: only allow alphanumerics, hyphens and underscores.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pipeline_id)
        return self._dir / f"{safe}.json"

    def _write_atomic(self, path: Path, data: dict) -> None:
        """Write *data* as JSON to *path* atomically."""
        dir_ = path.parent
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ── public API ────────────────────────────────────────────────

    def list(self) -> list[dict]:
        """Return all stored pipeline dicts, sorted by name."""
        result = []
        for f in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                result.append(data)
            except Exception:
                pass
        return result

    def get(self, pipeline_id: str) -> Optional[dict]:
        """Return the stored dict for *pipeline_id*, or None if absent."""
        path = self._file(pipeline_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save(self, data: dict) -> dict:
        """Create or update a pipeline.

        *data* must be a valid pipeline dict (validated via Pipeline.from_dict).
        Adds/updates a ``_saved_at`` timestamp.
        Raises ``ValueError`` if the dict is invalid or the DAG has cycles.
        """
        # Validate — Pipeline.from_dict calls execution_batches() internally.
        pipeline = Pipeline.from_dict(data)
        out = pipeline.to_dict()
        out["_saved_at"] = time.time()
        self._write_atomic(self._file(pipeline.id), out)
        return out

    def delete(self, pipeline_id: str) -> bool:
        """Delete the pipeline file. Returns True if deleted, False if not found."""
        path = self._file(pipeline_id)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False
