"""timeline.py — unified "Today in Jarvis" feed (P1 proof-gap G1).

Fuses what Jarvis *did* (autonomy tasks that reached ``done``) with what it
*learned* (new / updated memory facts & preferences) into one timestamp-ordered
feed. Before this, ``autonomy/digest.py`` (task recap) and ``memory/digest.py``
(learnings) were **separate** — nothing showed "did *and* learned" as a single
chronological story, so theme 0.38's "Today in Jarvis" had no backing surface.

Pure builder over injected data (a ``TaskQueue`` + already-read memory rows), so
it unit-tests offline with no async, network, or real store — the same discipline
as ``observability/north_star.py``. Reuses existing rows: **no new capture, no
schema, no behaviour change.**
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from agents.core.autonomy.followups import build_caring_followups

_DAY_SECONDS = 86_400


def _ts_epoch(value) -> float | None:
    """Epoch seconds for an ISO / SQLite timestamp; naive stamps are read as UTC.

    Handles both the autonomy queue's tz-aware ISO (``…+00:00``) and the memory
    store's SQLite ``datetime('now')`` form (``'YYYY-MM-DD HH:MM:SS'``, naive UTC).
    Returns None when unparseable.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def build_unified_digest(queue, memory_entries=None, *, now=None, days=1, limit=50) -> dict:
    """One timestamp-ordered feed of done-tasks + new memory facts in the window.

    Parameters
    ----------
    queue:
        An autonomy ``TaskQueue`` (or None). Source of completed actions
        (``status="done"``, windowed by ``updated_at`` — when the action finished).
    memory_entries:
        An iterable of memory-store row dicts (or None) — typically
        ``MemoryStore.get_all()`` flattened. Each carries
        ``category`` / ``key`` / ``value`` / ``updated_at``. A *learning* is
        windowed by ``updated_at`` (when the fact was recorded or changed).
    now, days:
        Trailing-window reference epoch (default ``time.time()``) and length
        (default 1 = "today"); clamped to ≥1 day.
    limit:
        Max items returned (newest first). ``counts`` reflects the full in-window
        set, not the truncated list.

    Returns a JSON-safe dict: ``period`` / ``days`` / ``generated_at`` /
    ``counts`` / ``items``. Every item carries ``ts`` / ``epoch`` / ``kind``
    (``action`` | ``learning``) plus its kind-specific fields.
    """
    days = max(1, int(days))
    now = time.time() if now is None else float(now)
    cutoff = now - days * _DAY_SECONDS

    items: list[dict] = []

    # ── what Jarvis *did* (completed autonomy actions) ──────────────────────
    if queue is not None:
        try:
            done = queue.list(status="done", limit=500)
        except Exception:
            done = []
        for t in done:
            ep = _ts_epoch(getattr(t, "updated_at", None))
            if ep is not None and ep < cutoff:
                continue
            items.append({
                "ts": getattr(t, "updated_at", None),
                "epoch": ep,
                "kind": "action",
                "title": getattr(t, "title", None),
                "id": getattr(t, "id", None),
                "tier": getattr(t, "risk_tier", None),
                "agent": getattr(t, "agent_id", None) or getattr(t, "agent", None),
            })

    # ── what Jarvis *learned* (new / updated facts & preferences) ───────────
    for e in (memory_entries or []):
        ts = e.get("updated_at") or e.get("created_at")
        ep = _ts_epoch(ts)
        if ep is not None and ep < cutoff:
            continue
        items.append({
            "ts": ts,
            "epoch": ep,
            "kind": "learning",
            "category": e.get("category"),
            "key": e.get("key"),
            "value": e.get("value"),
        })

    for f in build_caring_followups(queue, memory_entries, now=now, days=days, limit=500):
        items.append({
            "ts": f.get("ts"),
            "epoch": f.get("epoch"),
            "kind": "followup",
            "reason": f.get("kind"),
            "source": f.get("source"),
            "title": f.get("title"),
            "detail": f.get("detail"),
            "id": f.get("id"),
            "category": f.get("category"),
            "key": f.get("key"),
        })

    # Newest first. Unparseable timestamps (epoch None) sink to the bottom but are
    # never dropped — a real row with a bad stamp still shows (honesty over tidiness).
    items.sort(key=lambda it: (it["epoch"] is not None, it["epoch"] or 0.0), reverse=True)

    actions = sum(1 for it in items if it["kind"] == "action")
    learnings = sum(1 for it in items if it["kind"] == "learning")
    followups = sum(1 for it in items if it["kind"] == "followup")
    counts = {"actions": actions, "learnings": learnings, "total": len(items)}
    if followups:
        counts["followups"] = followups
    return {
        "period": "today" if days == 1 else f"{days}d",
        "days": days,
        "generated_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
        "counts": counts,
        "items": items[:limit],
    }
