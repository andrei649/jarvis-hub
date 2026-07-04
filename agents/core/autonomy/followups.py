"""Caring follow-up extraction for briefs and unified digests.

Builds from existing task queue rows and memory facts only. No new capture,
schema, or scheduler state: this is a read-only recomposition layer for the
companion charter's "care is behavior" rail.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

_DAY_SECONDS = 86_400
_OPEN_CONCERN_MARKERS = (
    "concern",
    "worry",
    "worried",
    "blocker",
    "blocked",
    "followup",
    "follow_up",
    "check in",
)
_UPCOMING_MARKERS = (
    "kg_date",
    "deadline",
    "due",
    "appointment",
    "calendar",
    "event",
    "date",
)


def _ts_epoch(value) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _inside_window(ts, *, now: float, days: int) -> bool:
    epoch = _ts_epoch(ts)
    return epoch is None or epoch >= now - max(1, int(days)) * _DAY_SECONDS


def _looks_like_open_concern(entry: dict) -> bool:
    haystack = " ".join(
        str(entry.get(k, "")).lower() for k in ("category", "key", "value")
    )
    return any(marker in haystack for marker in _OPEN_CONCERN_MARKERS)


def _looks_like_upcoming(entry: dict) -> bool:
    haystack = " ".join(
        str(entry.get(k, "")).lower() for k in ("category", "key", "value")
    )
    if any(marker in haystack for marker in _UPCOMING_MARKERS):
        return True
    return bool(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", haystack))


def build_caring_followups(
    queue=None,
    memory_entries=None,
    *,
    now=None,
    days: int = 1,
    limit: int = 8,
) -> list[dict]:
    """Return caring follow-up items from existing queue + memory rows."""
    now = time.time() if now is None else float(now)
    items: list[dict] = []

    if queue is not None:
        for status, reason in (("failed", "failed_task"), ("blocked", "blocked_task")):
            try:
                tasks = queue.list(status=status, limit=100)
            except Exception:
                tasks = []
            for task in tasks:
                ts = getattr(task, "updated_at", None)
                if not _inside_window(ts, now=now, days=days):
                    continue
                items.append({
                    "kind": reason,
                    "source": "task",
                    "title": getattr(task, "title", None) or f"Task #{getattr(task, 'id', '')}",
                    "detail": f"{status} autonomy task",
                    "id": getattr(task, "id", None),
                    "tier": getattr(task, "risk_tier", None),
                    "agent": getattr(task, "agent_id", None) or getattr(task, "agent", None),
                    "ts": ts,
                    "epoch": _ts_epoch(ts),
                })

    for entry in (memory_entries or []):
        ts = entry.get("updated_at") or entry.get("created_at")
        if not _inside_window(ts, now=now, days=days):
            continue
        reason = None
        if _looks_like_open_concern(entry):
            reason = "open_concern"
        elif _looks_like_upcoming(entry):
            reason = "upcoming_date"
        if reason is None:
            continue
        items.append({
            "kind": reason,
            "source": "memory",
            "title": str(entry.get("key") or entry.get("category") or reason).replace("_", " "),
            "detail": str(entry.get("value") or ""),
            "category": entry.get("category"),
            "key": entry.get("key"),
            "ts": ts,
            "epoch": _ts_epoch(ts),
        })

    items.sort(key=lambda it: (it["epoch"] is not None, it["epoch"] or 0.0), reverse=True)
    return items[:max(1, int(limit))]
