"""
usage.py — skill usage telemetry + provenance (H20.5 live wave).

Sidecar JsonStore (runtime data root, never the repo `skills/` tree) tracking
per-skill counters, provenance and lifecycle state. The curator reads the
derived latest-activity timestamp to decide active → stale → archived
transitions; only **agent-created, unpinned** skills are ever curatable.

Pattern adapted from hermes-agent `tools/skill_usage.py` (Nous Research, MIT)
— see LICENSES/THIRD_PARTY.md — rebuilt on jarvis's JsonStore (single-process
atomic persistence) instead of hermes's cross-process fcntl/msvcrt locking.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agents.core.persistence import JsonStore

logger = logging.getLogger("jarvis.skills.usage")

STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"
_VALID_STATES = {STATE_ACTIVE, STATE_STALE, STATE_ARCHIVED}

ORIGIN_AGENT = "agent"          # created by the agent (learning loop / [learn:])
ORIGIN_IMPORT = "import"        # installed from hermes/openclaw/marketplace
ORIGIN_BUNDLED = "bundled"      # shipped with the repo (default for untracked)

_BUMP_KEYS = {"use": ("use_count", "last_used_at"),
              "view": ("view_count", "last_viewed_at"),
              "patch": ("patch_count", "last_patched_at")}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def latest_activity_at(record: dict) -> Optional[datetime]:
    """Newest use/view/patch timestamp (creation intentionally excluded)."""
    latest = None
    for key in ("last_used_at", "last_viewed_at", "last_patched_at"):
        dt = _parse_iso(record.get(key))
        if dt is not None and (latest is None or dt > latest):
            latest = dt
    return latest


class SkillUsageStore(JsonStore):
    """Per-skill telemetry: counters, provenance, pin flag, lifecycle state."""

    def __init__(self, path: "str | Path | None" = None) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"skills": self._items}

    def _deserialize(self, raw) -> None:
        items = raw.get("skills", {}) if isinstance(raw, dict) else {}
        self._items = items if isinstance(items, dict) else {}

    def _rec(self, name: str) -> dict:
        return self._items.setdefault(name, {
            "origin": ORIGIN_BUNDLED, "created_at": _now_iso(),
            "use_count": 0, "view_count": 0, "patch_count": 0,
            "last_used_at": None, "last_viewed_at": None, "last_patched_at": None,
            "pinned": False, "state": STATE_ACTIVE,
        })

    def note_created(self, name: str, origin: str = ORIGIN_AGENT) -> dict:
        """Record provenance at creation time (the only trusted origin signal)."""
        with self._lock:
            rec = self._rec(str(name))
            rec["origin"] = origin
            rec["created_at"] = _now_iso()
            self._save()
            return dict(rec)

    def bump(self, name: str, kind: str) -> None:
        """Best-effort counter bump — a broken sidecar never breaks the call."""
        keys = _BUMP_KEYS.get(kind)
        if keys is None or not name:
            return
        count_key, ts_key = keys
        try:
            with self._lock:
                rec = self._rec(str(name))
                rec[count_key] = int(rec.get(count_key) or 0) + 1
                rec[ts_key] = _now_iso()
                if rec.get("state") == STATE_STALE:
                    rec["state"] = STATE_ACTIVE      # activity reactivates
                self._save()
        except Exception:
            logger.debug("usage bump skipped for %s/%s", name, kind, exc_info=True)

    def pin(self, name: str, pinned: bool = True) -> Optional[dict]:
        with self._lock:
            rec = self._rec(str(name))
            rec["pinned"] = bool(pinned)
            self._save()
            return dict(rec)

    def set_state(self, name: str, state: str) -> Optional[dict]:
        if state not in _VALID_STATES:
            return None
        with self._lock:
            rec = self._rec(str(name))
            rec["state"] = state
            self._save()
            return dict(rec)

    def get(self, name: str) -> Optional[dict]:
        with self._lock:
            rec = self._items.get(name)
            return dict(rec) if rec else None

    def list(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._items.items()}

    def curatable(self, name: str) -> bool:
        """Only agent-created, unpinned, non-archived skills may be curated."""
        rec = self.get(name)
        return bool(rec and rec.get("origin") == ORIGIN_AGENT
                    and not rec.get("pinned")
                    and rec.get("state") != STATE_ARCHIVED)

    def stats(self) -> dict:
        with self._lock:
            by_state, by_origin = {}, {}
            for r in self._items.values():
                by_state[r.get("state", "?")] = by_state.get(r.get("state", "?"), 0) + 1
                by_origin[r.get("origin", "?")] = by_origin.get(r.get("origin", "?"), 0) + 1
            return {"total": len(self._items), "by_state": by_state, "by_origin": by_origin}


__all__ = ["SkillUsageStore", "latest_activity_at",
           "STATE_ACTIVE", "STATE_STALE", "STATE_ARCHIVED",
           "ORIGIN_AGENT", "ORIGIN_IMPORT", "ORIGIN_BUNDLED"]
