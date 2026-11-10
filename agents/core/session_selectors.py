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


_LINEAGE_SQL = "SELECT session_id, parent_id FROM session_continuations ORDER BY created_at, rowid"


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
    children: dict[str, list[str]] = {}         # a session → the sessions continued from it, oldest first
    for member, parent in lineage:
        children.setdefault(parent, []).append(member)
    born = {member: index for index, (member, _parent) in enumerate(lineage)}
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
            numbered = meta.get("title_source") == "lineage"
            archived = meta.get("archived_at")
            if archived is not None and not isinstance(archived, str):
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise SessionSelectionError("store_unavailable", 503) from exc
        rows.append({"id": sid, "title": title, "archived": archived is not None, "numbered": numbered,
                     "activity": activity, "started": start})
    known = {row["id"] for row in rows}
    for row in rows:
        row["tip"] = _newest_leaf(row["id"], children, born, known)
    return rows


def _newest_leaf(sid: str, children: dict[str, list[str]], born: dict[str, int], known: set[str]) -> str:
    """The newest session that continues ``sid`` and that nobody continued yet (``sid``
    itself when nobody continued it): where a conversation named through ``sid`` now is.
    Only sessions the caller may see count."""
    best, stack, seen = None, [sid], {sid}
    while stack:
        current = stack.pop()
        kids = [kid for kid in children.get(current, ()) if kid in known and kid not in seen]
        if not kids and current != sid and (best is None or born.get(current, -1) > born.get(best, -1)):
            best = current
        seen.update(kids)
        stack.extend(kids)
    return best or sid


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


def _by_title(checkpoints, rows: list[dict], selector: str, *, exact_only: bool = False) -> list[dict]:
    """The sessions a name stands for (case and spacing folded).

    H440: a name opens the conversation where it now is — every session carrying exactly
    that title stands for the newest session continued from it that nobody continued yet
    (itself, when nobody continued it). That holds for any member's name, a numbered part's
    too. Exact bearers win: a separate chat that only looks alike (``hello (2)``, another
    conversation's ``hello #2``) is never picked for ``hello``. Two different sessions
    reached this way are an ambiguity, and are reported as one.

    Only when nobody carries the name any more — the conversation's first part was renamed —
    do its numbered parts (``<name> #N``, written by the continuation store) stand for it;
    within one conversation the newest of them is taken."""
    from .session_titles import lineage_base

    by_id = {row["id"]: row for row in rows}

    def tips(found: list[dict]) -> list[dict]:
        picked = {row["tip"]: by_id.get(row["tip"], row) for row in found}
        return list(picked.values())

    wanted = _fold(selector)
    exact = [row for row in rows if row["title"] and _fold(row["title"]) == wanted]
    if exact or exact_only:
        return tips(exact)
    parts = tips([row for row in rows if row["numbered"] and _fold(lineage_base(row["title"])) == wanted])
    roots = {_root_of(checkpoints, row["id"]) for row in parts}
    if len(parts) > 1 and len(roots) == 1:
        return [max(parts, key=lambda row: (row["started"], row["activity"], row["id"]))]
    return parts


def _root_of(checkpoints, sid: str) -> str:
    members = getattr(checkpoints, "lineage_members", None)
    found = members(sid) if callable(members) else []
    return found[0] if found else sid


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
    # An exact title is a name; only then is the selector read as the start of an id (a
    # chat titled "notes" must stay reachable although some id starts with "notes").
    matches = _by_title(checkpoints, rows, selector, exact_only=True)
    if not matches:
        matches = [row for row in rows if row["id"].startswith(selector)]
    if not matches:
        matches = _by_title(checkpoints, rows, selector)
    return _one(matches)
