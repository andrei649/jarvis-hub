"""skill_history.py — 0.58: a version-history ledger for installed skills.

The marketplace registry keeps **one row per skill** (``name PRIMARY KEY`` /
``INSERT OR REPLACE``), so once a skill is upgraded the prior version is gone from
the registry — there's nothing a *rollback* could target. This ledger is the
missing **version-history schema**: an append-only, bounded, corrupt-safe JSON log
of each ``publish`` / ``install`` / ``uninstall`` event, from which the **active**
version and the **rollback target** (the version a downgrade would restore) can be
derived.

Opt-in / default-off — nothing records unless a caller (the marketplace install
flow, a later wave) wires a ledger, so the default path is byte-for-byte unchanged.

Event shape (JSON-safe)::

    {id, name, version, action, at, meta}

``action`` is conventionally ``publish`` | ``install`` | ``uninstall`` (only
``publish``/``install`` establish a present version; ``uninstall`` is recorded for
the audit trail).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from agents.core.paths import data_path

_DEFAULT_FILE = data_path("skills") / "history.json"
_DEFAULT_MAX_KEEP = 5_000
_PRESENT = ("publish", "install")   # actions that establish a live version


class SkillHistory:
    """Bounded, atomically-written JSON ledger of skill version events."""

    def __init__(self, path: Path | str | None = None, *, max_keep: int = _DEFAULT_MAX_KEEP) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_keep = max(1, int(max_keep))

    # ── persistence (mirrors the 0.34/0.37/0.46 stores) ───────────────────────
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

    # ── api ────────────────────────────────────────────────────────────────────
    def record(self, name: str, version: str, action: str, *, now: float,
               meta: dict | None = None) -> dict:
        """Append a version event. ``now`` is the caller's clock (injectable)."""
        if not str(name).strip():
            raise ValueError("name is required")
        if not str(version).strip():
            raise ValueError("version is required")
        item = {
            "id": "sh-" + uuid.uuid4().hex[:12],
            "name": str(name),
            "version": str(version),
            "action": str(action),
            "at": float(now),
            "meta": dict(meta) if isinstance(meta, dict) else {},
        }
        items = self._read()
        items.append(item)
        if len(items) > self._max_keep:
            items.sort(key=lambda r: float(r.get("at", 0)))
            items = items[-self._max_keep:]
        self._write_atomic(items)
        return dict(item)

    def history(self, name: str | None = None) -> list[dict]:
        """Events (optionally for one skill), newest-first."""
        items = [dict(r) for r in self._read() if name is None or r.get("name") == name]
        items.sort(key=lambda r: float(r.get("at", 0)), reverse=True)
        return items

    def _present_versions(self, name: str) -> list[str]:
        """Distinct versions a skill has *been at* (publish/install), newest-first
        by event time, de-duplicated keeping the most recent occurrence's order."""
        ordered: list[str] = []
        for ev in self.history(name):                  # newest-first
            if ev.get("action") in _PRESENT:
                v = ev.get("version")
                if v and v not in ordered:
                    ordered.append(v)
        return ordered

    def current_version(self, name: str) -> str | None:
        """The skill's active version — the most recent publish/install."""
        versions = self._present_versions(name)
        return versions[0] if versions else None

    def rollback_target(self, name: str) -> str | None:
        """The version a rollback would restore: the distinct version present
        immediately before the current one. ``None`` if there's no prior version."""
        versions = self._present_versions(name)
        return versions[1] if len(versions) > 1 else None

    def versions(self, name: str) -> list[str]:
        """All distinct present versions for a skill, newest-first."""
        return self._present_versions(name)

    def stats(self) -> dict:
        """Total events + distinct skills + per-action counts."""
        items = self._read()
        by_action: dict[str, int] = {}
        names: set[str] = set()
        for r in items:
            by_action[r.get("action", "?")] = by_action.get(r.get("action", "?"), 0) + 1
            if r.get("name"):
                names.add(r["name"])
        return {"total": len(items), "skills": len(names), "by_action": by_action}
