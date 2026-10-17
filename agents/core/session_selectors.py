"""Owner-only, full-store resolution of a previously recorded local session."""

from __future__ import annotations

import json
from datetime import datetime

from .validation import is_valid_session_id


class SessionSelectionError(RuntimeError):
    def __init__(self, reason: str, status: int, candidates: list[dict] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.candidates = candidates or []


def _rows(checkpoints) -> list[dict]:
    conn = getattr(checkpoints, "_conn", None)
    if conn is None:
        raise SessionSelectionError("store_unavailable", 503)
    try:
        with checkpoints._lock:
            cursor = conn.execute("SELECT id,started_at,ended_at,metadata FROM sessions")
            values = cursor.fetchall()
    except Exception as exc:
        raise SessionSelectionError("store_unavailable", 503) from exc
    rows = []
    for sid, started, ended, raw in values:
        try:
            meta = json.loads(raw or "{}")
            if not is_valid_session_id(sid) or not isinstance(meta, dict):
                raise ValueError
            start = datetime.fromisoformat(started)
            activity = datetime.fromisoformat(ended) if ended else start
            if start.tzinfo is None or activity.tzinfo is None:
                raise ValueError
            title = meta.get("title", "")
            if not isinstance(title, str):
                raise ValueError
            archived = meta.get("archived_at")
            if archived is not None and not isinstance(archived, str):
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise SessionSelectionError("store_unavailable", 503) from exc
        rows.append({"id": sid, "title": title, "archived": archived is not None,
                     "activity": activity, "started": start})
    return rows


def resolve(checkpoints, selector: str, *, latest_mode: bool = False) -> str:
    """Return one ID; failure never loads history or changes an active session."""
    if not isinstance(selector, str) or not 0 < len(selector) <= 128 or not selector.strip():
        raise SessionSelectionError("invalid_selector", 400)
    rows = _rows(checkpoints)
    if not latest_mode:
        exact = next((row for row in rows if row["id"] == selector), None)
        if exact is not None:
            return exact["id"]
    if latest_mode or selector.casefold() == "latest":
        eligible = [row for row in rows if not row["archived"]]
        if not eligible:
            raise SessionSelectionError("session_not_found", 404)
        return max(eligible, key=lambda row: (row["activity"], row["started"], row["id"]))["id"]
    if selector.startswith("@"):
        raise SessionSelectionError("foreign_selector_requires_import", 422)
    matches = [row for row in rows if row["id"].startswith(selector)]
    if not matches:
        normalized = " ".join(selector.split()).casefold()
        matches = [row for row in rows if " ".join(row["title"].split()).casefold() == normalized]
    if not matches:
        raise SessionSelectionError("session_not_found", 404)
    if len(matches) > 1:
        candidates = [{"id": row["id"], "title": row["title"][:80]} for row in
                      sorted(matches, key=lambda row: (row["activity"], row["id"]), reverse=True)[:8]]
        raise SessionSelectionError("ambiguous_selector", 409, candidates)
    return matches[0]["id"]
