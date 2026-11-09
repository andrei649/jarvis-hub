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


_ALL_ROWS_SQL = "SELECT id,started_at,ended_at,metadata FROM sessions"
_NATIVE_ROWS_SQL = ("SELECT id,started_at,ended_at,metadata FROM sessions "
                    "WHERE id NOT IN (SELECT session_id FROM session_imports)")


def _rows(checkpoints, *, native_only: bool = False) -> list[dict]:
    conn = getattr(checkpoints, "_conn", None)
    if conn is None:
        raise SessionSelectionError("store_unavailable", 503)
    try:
        with checkpoints._lock:
            cursor = conn.execute(   # two fixed statements; nothing is interpolated
                _NATIVE_ROWS_SQL if native_only else _ALL_ROWS_SQL)
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


def _newest_members(checkpoints, ids: set[str]) -> dict[str, str]:
    """H440 — for each lineage root in ``ids``, its newest continuation."""
    tips = getattr(checkpoints, "lineage_tips", None)
    found = tips(sorted(ids)) if callable(tips) else {}
    return {root: tip["resume_id"] for root, tip in found.items()}


def _by_title(checkpoints, rows: list[dict], selector: str) -> list[dict]:
    """Rows titled ``selector`` (case and spacing folded). H440: a lineage's root stands
    for its newest member — resuming a conversation by name opens where it now is — while
    a member's own ``base #N`` title is that member."""
    normalized = " ".join(selector.split()).casefold()
    matches = [row for row in rows if " ".join(row["title"].split()).casefold() == normalized]
    if not matches:
        return []
    newest = _newest_members(checkpoints, {row["id"] for row in matches})
    by_id = {row["id"]: row for row in rows}
    picked = {}
    for row in matches:
        member = by_id.get(newest.get(row["id"], row["id"]), row)
        picked[member["id"]] = member
    return list(picked.values())


def _one(matches: list[dict]) -> str:
    if not matches:
        raise SessionSelectionError("session_not_found", 404)
    if len(matches) > 1:
        candidates = [{"id": row["id"], "title": row["title"][:80]} for row in
                      sorted(matches, key=lambda row: (row["activity"], row["id"]), reverse=True)[:8]]
        raise SessionSelectionError("ambiguous_selector", 409, candidates)
    return matches[0]["id"]


def resolve_title(checkpoints, title: str, *, native_only: bool = False) -> str:
    """H440 — the one session a title names: the newest member of its lineage.
    ``native_only`` leaves imported and derived sessions out, as a guest's list does."""
    if not isinstance(title, str) or not 0 < len(title) <= 128 or not title.strip():
        raise SessionSelectionError("invalid_selector", 400)
    return _one(_by_title(checkpoints, _rows(checkpoints, native_only=native_only), title))


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
        matches = _by_title(checkpoints, rows, selector)
    return _one(matches)
