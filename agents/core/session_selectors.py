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


_LINEAGE_SQL = "SELECT session_id, root_id FROM session_continuations ORDER BY created_at, rowid"


def _rows(checkpoints, *, native_only: bool = False) -> list[dict]:
    conn = getattr(checkpoints, "_conn", None)
    if conn is None:
        raise SessionSelectionError("store_unavailable", 503)
    try:
        with checkpoints._lock:
            cursor = conn.execute(   # two fixed statements; nothing is interpolated
                _NATIVE_ROWS_SQL if native_only else _ALL_ROWS_SQL)
            values = cursor.fetchall()
            lineage = conn.execute(_LINEAGE_SQL).fetchall()
    except Exception as exc:
        raise SessionSelectionError("store_unavailable", 503) from exc
    roots = dict(lineage)                       # member → the root of its lineage
    tips = {root: member for member, root in lineage}     # root → its newest member (oldest first)
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
        root = roots.get(sid, sid)
        rows.append({"id": sid, "title": title, "archived": archived is not None,
                     "activity": activity, "started": start, "root": root, "tip": tips.get(root, root)})
    return rows


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


def _by_title(checkpoints, rows: list[dict], selector: str) -> list[dict]:
    """The sessions a name stands for (case and spacing folded).

    H440: a numbered name (``Trip plan #2``) that some session carries is that session. Any
    other name is a conversation's: every session titled so, or titled ``<name> #N``, is
    traced to the root of its lineage and stands for that lineage's newest member — so the
    name still opens the conversation where it now is after the root was renamed, or after
    a renamed member was continued. Several conversations under the very same title stay
    ambiguous; a name whose other bearers are only numbered variants (separate chats opened
    with the same words are ``hello`` and ``hello #2``) opens the newest of them, as
    Hermes' numbered titles do."""
    from .session_titles import lineage_base

    wanted = _fold(selector)
    exact = [row for row in rows if row["title"] and _fold(row["title"]) == wanted]
    if exact and _fold(lineage_base(selector)) != wanted:
        return exact
    by_id = {row["id"]: row for row in rows}
    picked: dict[str, dict] = {}
    for row in rows:
        if row["title"] and _fold(lineage_base(row["title"])) == wanted:
            member = by_id.get(row["tip"]) or by_id.get(row["root"]) or row
            picked[member["id"]] = member
    members = list(picked.values())
    if len(members) > 1 and len({row["root"] for row in exact}) <= 1:
        return [max(members, key=lambda row: (row["activity"], row["started"], row["id"]))]
    return members


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
