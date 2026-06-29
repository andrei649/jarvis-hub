"""pending_queue.py — 0.34: a durable **pending-run queue** with bounded retry.

The engine executes a pipeline *now* (`WorkflowEngine.run`) and `run_store.py` persists
the *history* of completed runs. The missing 0.34 piece is the other direction: a place to
**enqueue** workflow runs that must survive a restart, and **retry** a failed run a bounded
number of times with exponential backoff before it's parked as ``dead``.

Design mirrors :class:`WorkflowRunStore` — a single bounded, atomically-written JSON array,
corrupt/missing-file-safe — and is **opt-in**: nothing enqueues or drains unless a caller
wires it, so the default path is byte-for-byte unchanged. The live drain (engine
``drain(queue, resolve)``) is a thin, also-opt-in helper; binding it into the autonomy
coordinator's tick is a deliberate, separate follow-up.

Item shape (JSON-safe)::

    {id, pipeline_id, input, status, attempts, max_attempts,
     enqueued_at, next_at, last_error}

Status: ``pending`` (runnable once ``next_at`` ≤ now) · ``done`` · ``dead`` (retries
exhausted). A ``fail`` under the attempt cap re-schedules (stays ``pending``, ``next_at``
pushed out by the backoff); at the cap it flips to ``dead``.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from agents.core.paths import data_path

_DEFAULT_FILE = data_path("workflows") / "pending.json"
_DEFAULT_MAX_KEEP = 500
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_BASE = 60.0   # seconds; next_at = now + base * 2**(attempts-1), capped
_BACKOFF_CAP = 3600.0


def _backoff(attempts: int, base: float = _DEFAULT_BACKOFF_BASE) -> float:
    """Exponential backoff for the *attempts*-th failure (1-based), capped."""
    return min(_BACKOFF_CAP, base * (2 ** max(0, attempts - 1)))


class WorkflowPendingQueue:
    """Bounded, atomically-written JSON queue of pending workflow runs (with retry)."""

    def __init__(self, path: Path | str | None = None, *, max_keep: int = _DEFAULT_MAX_KEEP,
                 backoff_base: float = _DEFAULT_BACKOFF_BASE) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_keep = max(1, int(max_keep))
        self._backoff_base = max(0.0, float(backoff_base))

    # ── persistence (mirrors WorkflowRunStore) ───────────────────────────────
    def _read(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return []
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    def _write_atomic(self, items: list[dict]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(items, fh, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # ── api ──────────────────────────────────────────────────────────────────
    def enqueue(self, pipeline_id: str, input: str = "", *, now: float,
                max_attempts: int = _DEFAULT_MAX_ATTEMPTS) -> dict:
        """Add a pending run. ``now`` is the caller's clock (kept injectable for tests)."""
        if not str(pipeline_id).strip():
            raise ValueError("pipeline_id is required")
        item = {
            "id": "wf-" + uuid.uuid4().hex[:12],
            "pipeline_id": str(pipeline_id),
            "input": str(input or ""),
            "status": "pending",
            "attempts": 0,
            "max_attempts": max(1, int(max_attempts)),
            "enqueued_at": float(now),
            "next_at": float(now),
            "last_error": None,
        }
        items = self._read()
        items.append(item)
        # prune oldest *terminal* items first so a flood can't evict live work:
        # sort terminal-then-oldest to the front (evicted), live + newest to the back
        # (kept by the [-max_keep:] tail).
        if len(items) > self._max_keep:
            items.sort(key=lambda r: (r.get("status") not in ("done", "dead"), r.get("enqueued_at", 0)))
            items = items[-self._max_keep:]
        self._write_atomic(items)
        return dict(item)

    def due(self, now: float) -> list[dict]:
        """Pending items whose ``next_at`` ≤ *now*, oldest-enqueued first."""
        items = [r for r in self._read()
                 if r.get("status") == "pending" and float(r.get("next_at", 0)) <= float(now)]
        items.sort(key=lambda r: float(r.get("enqueued_at", 0)))
        return items

    def _update(self, item_id: str, mutate) -> dict | None:
        items = self._read()
        hit = None
        for r in items:
            if r.get("id") == item_id:
                mutate(r)
                hit = dict(r)
                break
        if hit is not None:
            self._write_atomic(items)
        return hit

    def complete(self, item_id: str) -> dict | None:
        """Mark a run done (retained as history until pruned)."""
        return self._update(item_id, lambda r: r.update(status="done", last_error=None))

    def fail(self, item_id: str, error: str, *, now: float) -> dict | None:
        """Record a failure: retry with backoff under the cap, else park as ``dead``."""
        def _m(r):
            r["attempts"] = int(r.get("attempts", 0)) + 1
            r["last_error"] = (str(error) or "failed")[:500]
            if r["attempts"] >= int(r.get("max_attempts", _DEFAULT_MAX_ATTEMPTS)):
                r["status"] = "dead"
            else:
                r["status"] = "pending"
                r["next_at"] = float(now) + _backoff(r["attempts"], self._backoff_base)
        return self._update(item_id, _m)

    def list(self, status: str | None = None) -> list[dict]:
        items = self._read()
        if status:
            items = [r for r in items if r.get("status") == status]
        items.sort(key=lambda r: float(r.get("enqueued_at", 0)))
        return items

    def stats(self) -> dict:
        items = self._read()
        out = {"pending": 0, "done": 0, "dead": 0, "total": len(items)}
        for r in items:
            s = r.get("status")
            if s in out:
                out[s] += 1
        return out
