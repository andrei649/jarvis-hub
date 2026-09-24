"""todo_tool.py — the agent keeps a visible checklist of what it is doing (H315).

Hermes' ``todo`` manages the session's task checklist and always answers with the whole
current list, so the model re-reads its own plan every time it changes it. That is a
steering mechanism: it holds a weaker model to a multi-step plan. Nerva had no
model-maintained plan at all — heartbeat checklists, the notes store's ``todo`` block and
the operator's planners are all written by someone else.

``todo`` is a session-scoped ToolRPC tool:

* items are ``{id, content, status}``, status one of :data:`STATUSES`;
* a call with ``todos`` replaces the list; with ``merge=true`` it updates items by id
  (only the fields sent) and appends new ones; a call with no ``todos`` reads it;
* every call answers with the whole list and its counts, and the tool loop never swaps
  that answer for a "same as call N" stub (``agent_runtime._ALWAYS_RESTATED``);
* it is bounded — :data:`MAX_ITEMS` items, :data:`MAX_CONTENT` characters of one printable
  line each, at most one item in progress, :data:`MAX_SESSIONS` plans kept — and every
  refusal is a named reason with a sentence the model can act on. A refused call changes
  nothing.

Ungated and offered in every posture (``tool_profiles.SESSION_LOCAL_TOOLS``): its only
effect is the calling session's own list. The owner sees the plan — the point of the
row: intent before the approval card. A write leaves a ``todo_updated`` event in the
tool trail (ids and statuses, never the text), the plans are read back through
``GET /sessions/todo`` and ``/sessions/{id}/todo``, ``nerva todo`` and the Decision
Inbox, and a memory purge forgets every one of them. In memory on purpose: a plan is
the state of work in flight, not a record, and it resets with the process.
"""

from __future__ import annotations

import logging
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

logger = logging.getLogger("jarvis.todo_tool")

TOOL_NAME = "todo"
CAPABILITY_ID = "tool:todo"
STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed", "cancelled")
MAX_ITEMS = 50
MAX_CONTENT = 200
MAX_ID = 64
MAX_SESSION_ID = 128
MAX_SESSIONS = 256
#: A raw string this many times over its cap is refused before it is cleaned, so a
#: runaway argument costs a length check, not a character walk.
_RAW_SLACK = 4

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "maxItems": MAX_ITEMS,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": MAX_ID},
                    "content": {"type": "string", "minLength": 1, "maxLength": MAX_CONTENT},
                    "status": {"type": "string", "enum": list(STATUSES)},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        "merge": {"type": "boolean"},
    },
    "additionalProperties": False,
}

DESCRIPTION = (
    "Your checklist for this conversation. Call it with no arguments to read the list. "
    "Send todos to replace the list, or todos with merge=true to update items by id (only "
    "the fields you send) and add new ones. An item is {id, content, status}; status is "
    "pending, in_progress, completed or cancelled, and only one item may be in_progress. "
    "Every call returns the whole list. Plan multi-step work here, keep it current as you "
    "go, and re-read it before the next step. The owner can see this list."
)


class TodoError(ValueError):
    """A refused write: a machine reason and a sentence the model can act on."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ── cleaning ─────────────────────────────────────────────────────────────────

def _one_line(value: str) -> str:
    """Printable, one line. Control and format characters go — a zero-width joiner, a
    bidi override or an invisible tag would make what the owner reads differ from what
    was written — and every run of whitespace becomes one space."""
    out = []
    for char in value:
        category = unicodedata.category(char)
        if char.isspace() or category in ("Zl", "Zp"):
            out.append(" ")
        elif category[0] != "C":
            out.append(char)
    return " ".join("".join(out).split())


def _clean_id(raw: Any) -> str:
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = str(raw)
    if not isinstance(raw, str) or len(raw) > MAX_ID * _RAW_SLACK:
        raise TodoError("todo_bad_id", f"every item needs an id: text of 1 to {MAX_ID} characters")
    clean = _one_line(raw)
    if not clean or len(clean) > MAX_ID:
        raise TodoError("todo_bad_id", f"every item needs an id: text of 1 to {MAX_ID} characters")
    return clean


def _clean_content(raw: Any, item_id: str) -> str:
    if raw is None:
        raise TodoError("todo_content_required", f"item {item_id!r} is new, so it needs content")
    if not isinstance(raw, str):
        raise TodoError("todo_content_required", f"item {item_id!r}: content is text")
    if len(raw) > MAX_CONTENT * _RAW_SLACK:
        raise TodoError("todo_content_too_long",
                        f"item {item_id!r}: content is one line of at most {MAX_CONTENT} characters")
    clean = _one_line(raw)
    if not clean:
        raise TodoError("todo_content_required", f"item {item_id!r}: content cannot be empty")
    if len(clean) > MAX_CONTENT:
        raise TodoError("todo_content_too_long",
                        f"item {item_id!r}: content is one line of at most {MAX_CONTENT} characters")
    return clean


def _clean_status(raw: Any, item_id: str) -> str:
    if raw not in STATUSES:
        raise TodoError("todo_bad_status",
                        f"item {item_id!r}: status is one of {', '.join(STATUSES)}")
    return raw


def counts(todos: list[Mapping[str, Any]]) -> dict[str, int]:
    out = dict.fromkeys(STATUSES, 0)
    for item in todos:
        out[item["status"]] += 1
    out["total"] = len(todos)
    return out


# ── the store ────────────────────────────────────────────────────────────────

class TodoStore:
    """One list per session, least recently written dropped past ``max_sessions``."""

    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self._plans: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max = max(1, int(max_sessions))
        self._lock = threading.Lock()

    @staticmethod
    def _session(session_id: Any) -> str:
        if not isinstance(session_id, str) or not session_id or len(session_id) > MAX_SESSION_ID:
            raise TodoError("todo_no_session", "this turn has no session to keep a list for")
        return session_id

    @staticmethod
    def _view(session_id: str, plan: Mapping[str, Any] | None) -> dict[str, Any]:
        todos = [dict(item) for item in (plan or {}).get("todos", ())]
        return {
            "session_id": session_id,
            "todos": todos,
            "counts": counts(todos),
            "updated_at": (plan or {}).get("updated_at"),
            "agent": (plan or {}).get("agent", ""),
            "posture": (plan or {}).get("posture", ""),
        }

    def read(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self._plans.get(session_id) if isinstance(session_id, str) else None
            return self._view(str(session_id or ""), plan)

    def write(
        self,
        session_id: str,
        todos: Any,
        merge: Any = False,
        *,
        agent: str = "",
        posture: str = "",
    ) -> dict[str, Any]:
        """Replace or merge, then answer with the whole list. Nothing is half-applied:
        the new list is built on a copy and stored only when every item passed."""
        sid = self._session(session_id)
        if todos is None:
            return self.read(sid)
        if not isinstance(merge, bool):
            raise TodoError("todo_bad_merge", "merge is true or false")
        if not isinstance(todos, list):
            raise TodoError("todo_bad_list", "todos is a list of {id, content, status} items")
        if len(todos) > MAX_ITEMS:
            raise TodoError("todo_too_many", f"a list holds at most {MAX_ITEMS} items")
        with self._lock:
            current = self._plans.get(sid)
            items = [dict(item) for item in current["todos"]] if merge and current else []
            by_id = {item["id"]: item for item in items}
            seen: set[str] = set()
            for raw in todos:
                if not isinstance(raw, Mapping):
                    raise TodoError("todo_bad_item", "each item is an object {id, content, status}")
                item_id = _clean_id(raw.get("id"))
                if item_id in seen:
                    raise TodoError("todo_duplicate_id", f"id {item_id!r} appears twice in one call")
                seen.add(item_id)
                target = by_id.get(item_id) if merge else None
                if target is None:
                    status = raw.get("status")
                    item = {
                        "id": item_id,
                        "content": _clean_content(raw.get("content"), item_id),
                        "status": _clean_status("pending" if status is None else status, item_id),
                    }
                    items.append(item)
                    by_id[item_id] = item
                    continue
                if raw.get("content") is not None:
                    target["content"] = _clean_content(raw.get("content"), item_id)
                if raw.get("status") is not None:
                    target["status"] = _clean_status(raw.get("status"), item_id)
            if len(items) > MAX_ITEMS:
                raise TodoError("todo_too_many", f"a list holds at most {MAX_ITEMS} items")
            if sum(item["status"] == "in_progress" for item in items) > 1:
                raise TodoError(
                    "todo_one_in_progress",
                    "only one item can be in_progress at a time: mark the current one "
                    "completed (or back to pending) first",
                )
            plan = {"todos": items, "updated_at": time.time(),
                    "agent": str(agent or "")[:64], "posture": str(posture or "")[:32]}
            self._plans[sid] = plan
            self._plans.move_to_end(sid)
            while len(self._plans) > self._max:
                self._plans.popitem(last=False)
            return self._view(sid, plan)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """The plans, most recently written first."""
        bound = max(1, min(int(limit), self._max))
        with self._lock:
            rows = list(self._plans.items())[-bound:]
            return [self._view(sid, plan) for sid, plan in reversed(rows)]

    def clear(self) -> int:
        """Forget every plan (a memory purge). Returns how many there were."""
        with self._lock:
            dropped = len(self._plans)
            self._plans.clear()
            return dropped


#: The process-wide store the live tool, the routes and the purge share.
TODOS = TodoStore()


# ── the tool ─────────────────────────────────────────────────────────────────

def _record_event(view: Mapping[str, Any], *, merge: bool) -> None:
    """A write leaves a trail row the owner can read: which items and where they stand,
    never what they say. ``TOOL_EVENTS`` cuts the lists to its own bound; ``total`` and
    ``current`` carry what that cut would hide."""
    from agents.core.observability.tool_events import TOOL_EVENTS
    from agents.core.tool_rpc import current_tool_actor

    todos = view["todos"]
    current = next((item["id"] for item in todos if item["status"] == "in_progress"), None)
    TOOL_EVENTS.record({
        "event": "todo_updated",
        "tool": TOOL_NAME,
        "agent_id": current_tool_actor(),
        "session": view["session_id"],
        "merge": merge,
        "ids": [item["id"] for item in todos],
        "statuses": [item["status"] for item in todos],
        "current": current,
        "total": len(todos),
    })


def register_todo_tool(
    server: Any,
    *,
    session_id: Callable[[], str],
    store: TodoStore | None = None,
    posture: Callable[[], str] | None = None,
) -> str:
    """Expose ``todo`` on a ToolRPC server (ungated). ``session_id`` and ``posture`` are
    read per call, so the list is always the turn in flight's own; with no ``store`` the
    call reads :data:`TODOS` at call time, the one the routes serve."""

    def _target() -> TodoStore:
        return store if store is not None else TODOS

    async def _handle(args: dict) -> dict:
        from agents.core.tool_rpc import current_tool_actor

        try:
            sid = session_id()
        except Exception:
            logger.warning("todo: the session getter failed", exc_info=True)
            sid = ""
        todos = args.get("todos")
        merge = args.get("merge")
        merge = False if merge is None else merge   # an explicit null is "not sent"
        where = ""
        if posture is not None:
            try:
                where = str(posture() or "")
            except Exception:
                where = ""
        try:
            view = _target().write(sid, todos, merge, agent=current_tool_actor(), posture=where)
        except TodoError as exc:
            return {"ok": False, "reason": exc.reason, "detail": exc.detail}
        if todos is not None:
            _record_event(view, merge=merge is True)
        return {"ok": True, "todos": view["todos"], "counts": view["counts"]}

    server.register_tool(
        TOOL_NAME,
        _handle,
        gated=False,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        capability_id=CAPABILITY_ID,
    )
    return TOOL_NAME


__all__ = [
    "CAPABILITY_ID", "DESCRIPTION", "INPUT_SCHEMA", "MAX_CONTENT", "MAX_ID", "MAX_ITEMS",
    "MAX_SESSIONS", "STATUSES", "TODOS", "TOOL_NAME", "TodoError", "TodoStore", "counts",
    "register_todo_tool",
]
