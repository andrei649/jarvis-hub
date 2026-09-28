"""todo_tool.py — the agent keeps a visible checklist of what it is doing (H315).

Hermes' ``todo`` manages the session's task checklist and always answers with the whole
current list, so the model re-reads its own plan every time it changes it. That is a
steering mechanism: it holds a weaker model to a multi-step plan. Nerva had no
model-maintained plan at all — heartbeat checklists, the notes store's ``todo`` block and
the operator's planners are all written by someone else.

``todo`` is a session-scoped ToolRPC tool:

* items are ``{id, content, status}``, status one of :data:`STATUSES`, and an optional
  ``parent``: the id of the item it sits under (H666). The list stays flat, so merge-by-id
  keeps working; ``todo_tree`` draws it as a tree that loses nothing;
* a call with ``todos`` replaces the list; with ``merge=true`` it updates items by id
  (only the fields sent) and appends new ones; a call with no ``todos`` reads it;
* every call answers with the whole list and its counts. The tool loop never swaps that
  answer for a "same as call N" stub and never counts it as a repeat or against a
  per-tool cap (``agent_runtime._ALWAYS_RESTATED``). It never cuts it either: the list is
  bounded below any result budget (:data:`MAX_PLAN_BYTES`) and pinned whole in
  ``tool_result_store.PINNED_THRESHOLDS``;
* it is bounded — :data:`MAX_ITEMS` items, :data:`MAX_CONTENT` characters of one printable
  line each, :data:`MAX_PLAN_BYTES` in all, at most one item in progress,
  :data:`MAX_SESSIONS` plans kept — and every refusal is a named reason with a sentence
  the model can act on. A refused call changes nothing.

Whose plan it is (the H315 review). A turn that binds no session of its own runs on the
shared default session, the HUD's, and so do a widget visitor, a webhook, a job and a
subagent. The plan kept there is the owner's: a turn on it that is not the owner's is
refused ``todo_shared_session`` and is never read the plan, and the tool is not offered
to it (``tool_profiles.SESSION_SCOPED_TOOLS``). A turn on a session of its own (a chat of
its own, an explicit session) keeps its own plan, whoever it is.

Where its text came from. Each item records the posture of the turn that wrote its text
(``by``) and whether that turn was untrusted (``tainted``: an inbound channel, or a turn
that had already read untrusted content). A call that answers with a tainted item says
so, and the loop fences the answer as DATA and raises the reading turn's taint. A plan
therefore cannot carry an injected instruction into a later, clean turn as the tool's own
words.

The tool is offered like any ungated tool, and to an inbound guest through
``llm.guest_tools`` (default echo, time and todo). The owner sees the plan, which is the
point of the row: intent before the approval card. A write leaves a ``todo_updated``
event in the tool trail (positions and statuses, never ids or text). The plans are read
back through ``GET /sessions/todo`` and ``/sessions/{id}/todo``, ``nerva todo`` and the
Decision Inbox, and a memory purge forgets every one of them.

It is kept in memory on purpose: a plan is the state of work in flight, not a record,
and it resets with the process. A turn already running when a purge starts can still
write its plan afterwards, just as it still saves its reply.
"""

from __future__ import annotations

import json
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
#: The whole list, as the tool answers it (JSON, UTF-8), fits under the smallest
#: per-result budget the loop gives a tool (8,000 bytes), with room for the envelope.
MAX_PLAN_BYTES = 7_000
#: A raw string this many times over its cap is refused before it is cleaned, so a
#: runaway argument costs a length check, not a character walk.
_RAW_SLACK = 4
#: A character keeps at most this many combining marks; the rest of a stack is dropped.
_MAX_MARKS = 3
#: Letters and symbols that render as nothing: the Hangul fillers and the braille blank.
_BLANK = frozenset("ᅟᅠㅤﾠ⠀")
_ARG_FIELDS = frozenset({"todos", "merge"})
_ITEM_FIELDS = frozenset({"id", "content", "status", "parent"})
SHARED_SESSION_DETAIL = (
    "this turn runs on the owner's shared conversation, where only the owner's own turns "
    "keep a list: plan in your reply instead"
)

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
                    "parent": {"type": "string", "maxLength": MAX_ID},
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
    "Your checklist for this conversation. Send todos to replace the list, or todos with "
    "merge=true to update items by id (only the fields you send) and add new ones; call it "
    "with no arguments to read it. An item is {id, content, status}; status is pending, "
    "in_progress, completed or cancelled, and only one item may be in_progress. Every call "
    "returns the whole list, so an update is also a read. Plan multi-step work here and keep "
    "it current: mark the item you start in_progress and mark it completed when it is done. "
    "To nest a subtask, give it parent: the id of the item it belongs under (an empty parent "
    "moves it back to the top). The owner can see this list."
)


class TodoError(ValueError):
    """A refused write: a machine reason and a sentence the model can act on."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ── cleaning ─────────────────────────────────────────────────────────────────

def _one_line(value: str) -> str:
    """Printable, one line, NFC. Control and format characters go (a zero-width joiner, a
    bidi override or an invisible tag would make what the owner reads differ from what
    was written), every run of whitespace becomes one space, and a character keeps at
    most :data:`_MAX_MARKS` combining marks. NFC comes after the drop, so "e", a joiner
    and an accent end up as the same "é" as the precomposed one."""
    kept = "".join(
        " " if char.isspace() else char
        for char in value
        if char.isspace() or unicodedata.category(char)[0] != "C"
    )
    out: list[str] = []
    marks = 0
    for char in unicodedata.normalize("NFC", kept):
        if unicodedata.category(char) in ("Mn", "Me"):
            marks += 1
            if marks > _MAX_MARKS:
                continue
        else:
            marks = 0
        out.append(char)
    return " ".join("".join(out).split())


def _visible(text: str) -> bool:
    """Something a reader would see: a letter, digit, punctuation or symbol that is not
    one of the characters that render blank. Combining marks alone are not."""
    return any(unicodedata.category(char)[0] in "LNPS" and char not in _BLANK for char in text)


def _clean_id(raw: Any) -> str:
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = str(raw)
    if not isinstance(raw, str) or len(raw) > MAX_ID * _RAW_SLACK:
        raise TodoError("todo_bad_id", f"every item needs an id: text of 1 to {MAX_ID} characters")
    clean = _one_line(raw)
    if not _visible(clean) or len(clean) > MAX_ID:
        raise TodoError("todo_bad_id", f"every item needs an id: text of 1 to {MAX_ID} characters")
    return clean


def _clean_content(raw: Any, item_id: str) -> str:
    if raw is None:
        raise TodoError("todo_content_required", f"item {item_id!r} is new, so it needs content")
    if not isinstance(raw, str):
        raise TodoError("todo_content_required", f"item {item_id!r}: content is text")
    if len(raw) > MAX_CONTENT * _RAW_SLACK:
        raise TodoError(
            "todo_content_too_long",
            f"item {item_id!r}: content is one line of at most {MAX_CONTENT} characters, and this "
            f"one is {len(raw):,} characters before cleaning",
        )
    clean = _one_line(raw)
    if not _visible(clean):
        raise TodoError("todo_content_required", f"item {item_id!r}: content cannot be blank")
    if len(clean) > MAX_CONTENT:
        raise TodoError("todo_content_too_long",
                        f"item {item_id!r}: content is one line of at most {MAX_CONTENT} characters")
    return clean


def _clean_parent(raw: Any, item_id: str) -> str | None:
    """The id of the item this one sits under (H666), cleaned like an id. Text that is
    empty or only whitespace is none, as Hermes clears it. It need not name an item in
    the list: a parent that is missing, the item itself or part of a cycle is drawn at
    the top (``todo_tree``), never refused and never lost."""
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        return _clean_id(raw)
    except TodoError:
        raise TodoError("todo_bad_parent",
                        f"item {item_id!r}: parent is the id of another item (text of 1 to {MAX_ID} "
                        "characters), or empty for none") from None


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


def model_items(todos: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The items as the tool answers them: what the model wrote, nothing it did not. An
    item with no parent answers without the key."""
    out = []
    for item in todos:
        row = {"id": item["id"], "content": item["content"], "status": item["status"]}
        if item.get("parent") is not None:
            row["parent"] = item["parent"]
        out.append(row)
    return out


def plan_bytes(todos: list[Mapping[str, Any]]) -> int:
    """The size of a list as the tool answers it, the way the loop measures a result."""
    return len(json.dumps(model_items(todos), ensure_ascii=False).encode("utf-8"))


# ── the store ────────────────────────────────────────────────────────────────

class TodoStore:
    """One list per session. Past ``max_sessions`` the plan the agent least recently
    wrote or read is dropped."""

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
        todos = [{key: value for key, value in item.items() if key != "turn"}
                 for item in (plan or {}).get("todos", ())]
        return {
            "session_id": session_id,
            "todos": todos,
            "counts": counts(todos),
            "updated_at": (plan or {}).get("updated_at"),
            "agent": (plan or {}).get("agent", ""),
            "posture": (plan or {}).get("posture", ""),
        }

    def read(self, session_id: str, *, touch: bool = False) -> dict[str, Any]:
        """The session's plan. ``touch`` (the agent's own read) keeps it from being the
        one dropped next; the owner's reads do not."""
        with self._lock:
            plan = self._plans.get(session_id) if isinstance(session_id, str) else None
            if touch and plan is not None:
                self._plans.move_to_end(session_id)
            return self._view(str(session_id or ""), plan)

    def write(
        self,
        session_id: str,
        todos: Any,
        merge: Any = False,
        *,
        agent: str = "",
        posture: str = "",
        tainted: bool = False,
    ) -> dict[str, Any]:
        """Replace or merge, then answer with the whole list: :meth:`apply` without a turn."""
        return self.apply(session_id, todos, merge, agent=agent, posture=posture, tainted=tainted)[0]

    def apply(
        self,
        session_id: str,
        todos: Any,
        merge: Any = False,
        *,
        agent: str = "",
        posture: str = "",
        tainted: bool = False,
        turn: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Replace, merge or (``todos`` None) read, as the tool does: ``(view, foreign)``.

        Nothing is half-applied: the new list is built on a copy and stored only when
        every item passed. An item new to the list records ``posture``, ``tainted`` and
        ``turn`` as its own. A rewrite of its text records the writer, and keeps any taint
        it had: its id came from whoever wrote it first. A status set by an untrusted
        turn taints the item too, so the next clean turn knows who moved it. ``foreign``
        says the list holds a tainted item that this ``turn`` did not write (an earlier
        turn's, or a script's): the answer must be read as DATA. The plan's labels (when,
        which agent, whose turn) move only when the list actually changed, and an empty
        list is no plan: its slot is freed."""
        sid = self._session(session_id)
        if todos is None:
            with self._lock:
                plan = self._plans.get(sid)
                if plan is not None:
                    self._plans.move_to_end(sid)
                return self._view(sid, plan), _foreign(plan, turn)
        if not isinstance(merge, bool):
            raise TodoError("todo_bad_merge", "merge is true or false")
        if not isinstance(todos, list):
            raise TodoError("todo_bad_list", "todos is a list of {id, content, status} items")
        if len(todos) > MAX_ITEMS:
            raise TodoError("todo_too_many", f"a list holds at most {MAX_ITEMS} items")
        by = str(posture or "")[:32]
        taint = bool(tainted)
        with self._lock:
            current = self._plans.get(sid)
            before = [dict(item) for item in current["todos"]] if current else []
            items = [dict(item) for item in before] if merge else []
            by_id = {item["id"]: item for item in items}
            prior_by_id = {item["id"]: item for item in before}
            seen: set[str] = set()
            wrote_text = not merge
            for raw in todos:
                if not isinstance(raw, Mapping):
                    raise TodoError("todo_bad_item", "each item is an object {id, content, status}")
                unknown = sorted(str(key) for key in raw if key not in _ITEM_FIELDS)
                if unknown:
                    raise TodoError("todo_unknown_field",
                                    f"an item has id, content, status and parent only, not {unknown[0]!r}")
                item_id = _clean_id(raw.get("id"))
                if item_id in seen:
                    raise TodoError("todo_duplicate_id", f"id {item_id!r} appears twice in one call")
                seen.add(item_id)
                target = by_id.get(item_id) if merge else None
                parent = raw.get("parent")
                if target is None:
                    status = raw.get("status")
                    item = {
                        "id": item_id,
                        "content": _clean_content(raw.get("content"), item_id),
                        "status": _clean_status("pending" if status is None else status, item_id),
                        "by": by,
                        "tainted": taint,
                        "turn": turn,
                    }
                    if parent is not None and (above := _clean_parent(parent, item_id)) is not None:
                        item["parent"] = above
                    prior = None if merge else prior_by_id.get(item_id)
                    if prior is not None and prior["content"] == item["content"]:
                        # A replace that re-sends an item's text unchanged is no rewrite of it,
                        # as a merge is not (review-H315e n2): the item stays its writer's, with
                        # its taint; a status or place moved by an untrusted turn taints it.
                        item["by"], item["turn"] = prior.get("by", ""), prior.get("turn")
                        item["tainted"] = bool(prior.get("tainted"))
                        moved_it = (item["status"] != prior["status"]
                                    or item.get("parent") != prior.get("parent"))
                        if taint and moved_it and not item["tainted"]:
                            item["tainted"], item["turn"] = True, turn
                    elif prior is not None and prior.get("tainted"):
                        # A rewrite of a tainted item's text keeps the taint, as a merge's
                        # does (review-H315f n3): the rewriter owns the text, not a clean slate.
                        item["tainted"] = True
                    items.append(item)
                    by_id[item_id] = item
                    wrote_text = True
                    continue
                if raw.get("content") is not None:
                    text = _clean_content(raw.get("content"), item_id)
                    # The same text again is no write (H315 third review): the item stays
                    # whoever wrote it, so another turn cannot make it its own by re-sending it.
                    if text != target["content"]:
                        target["content"] = text
                        target["by"] = by
                        target["tainted"] = bool(target.get("tainted")) or taint
                        target["turn"] = turn
                        wrote_text = True
                moved = False
                if parent is not None:
                    # Where an item sits is the writer's word too, and it costs bytes: a move
                    # is checked against the cap and taints the item like a status does.
                    above = _clean_parent(parent, item_id)
                    if above != target.get("parent"):
                        if above is None:
                            target.pop("parent", None)
                        else:
                            target["parent"] = above
                        moved = wrote_text = True
                if raw.get("status") is not None:
                    status = _clean_status(raw.get("status"), item_id)
                    # Re-sending the current status moves nothing, as in a replace
                    # (review-H315f n3): only a change is the writer's word.
                    if status != target["status"]:
                        target["status"] = status
                        moved = True
                if moved and taint and not target.get("tainted"):
                    target["tainted"] = True
                    target["turn"] = turn
            if len(items) > MAX_ITEMS:
                raise TodoError("todo_too_many", f"a list holds at most {MAX_ITEMS} items")
            if sum(item["status"] == "in_progress" for item in items) > 1:
                raise TodoError(
                    "todo_one_in_progress",
                    "only one item can be in_progress at a time: mark the current one "
                    "completed (or back to pending) first",
                )
            # The cap is on what the list says. A merge that moves statuses only never
            # crosses it: a status is at most a few bytes longer, and the budget has room.
            size = plan_bytes(items)
            if wrote_text and size > MAX_PLAN_BYTES:
                raise TodoError(
                    "todo_plan_too_long",
                    f"the whole list is at most {MAX_PLAN_BYTES:,} bytes and this one would be "
                    f"{size:,}: shorten the items or drop the finished ones",
                )
            if not items:
                self._plans.pop(sid, None)
                return self._view(sid, None), False
            if current is not None and _public(items) == _public(before):
                plan = {**current, "todos": items}          # nothing changed: the labels stay
            else:
                plan = {"todos": items, "updated_at": time.time(),
                        "agent": str(agent or "")[:64], "posture": by}
            self._plans[sid] = plan
            self._plans.move_to_end(sid)
            while len(self._plans) > self._max:
                self._plans.popitem(last=False)
            return self._view(sid, plan), _foreign(plan, turn)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """The plans, most recently written or read by the agent first."""
        bound = max(1, min(int(limit), self._max))
        with self._lock:
            rows = list(self._plans.items())[-bound:]
            return [self._view(sid, plan) for sid, plan in reversed(rows)]

    def forget(self, session_id: str) -> bool:
        """H218 — drop one session's plan (a permanent session delete). Whether there was one."""
        with self._lock:
            return self._plans.pop(str(session_id or ""), None) is not None

    def clear(self) -> int:
        """Forget every plan (a memory purge). Returns how many there were."""
        with self._lock:
            dropped = len(self._plans)
            self._plans.clear()
            return dropped


def _public(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Items as anyone reads them: the turn that last wrote each one is bookkeeping."""
    return [{key: value for key, value in item.items() if key != "turn"} for item in items]


def _foreign(plan: Mapping[str, Any] | None, turn: str | None) -> bool:
    """Whether the plan holds a tainted item that ``turn`` did not write."""
    return any(item.get("tainted") and (turn is None or item.get("turn") != turn)
               for item in (plan or {}).get("todos", ()))


#: The process-wide store the live tool, the routes and the purge share.
TODOS = TodoStore()


# ── the tool ─────────────────────────────────────────────────────────────────

def _record_event(view: Mapping[str, Any], *, merge: bool) -> None:
    """A write leaves a trail row the owner can read: where the items stand, never what
    they say or what the model called them (an id is free text too). ``TOOL_EVENTS``
    cuts the lists to its own bound; ``total`` and ``current`` (the position of the item
    in progress) carry what that cut would hide."""
    from agents.core.observability.tool_events import TOOL_EVENTS
    from agents.core.tool_rpc import current_tool_actor

    todos = view["todos"]
    current = next((pos for pos, item in enumerate(todos, 1) if item["status"] == "in_progress"), None)
    TOOL_EVENTS.record({
        "event": "todo_updated",
        "tool": TOOL_NAME,
        "agent_id": current_tool_actor(),
        "session": view["session_id"],
        "merge": merge,
        "statuses": [item["status"] for item in todos],
        "current": current,
        "total": len(todos),
    })


def _turn_origin() -> str:
    from agents.core.action_origin import current_action_origin

    return current_action_origin()


def register_todo_tool(
    server: Any,
    *,
    session_id: Callable[[], str],
    store: TodoStore | None = None,
    posture: Callable[[], str] | None = None,
    shared_session: Callable[[], bool] | None = None,
    origin: Callable[[], str] = _turn_origin,
) -> str:
    """Expose ``todo`` on a ToolRPC server (ungated). Every getter is read per call, so
    the list is always the turn in flight's own: ``session_id`` names it, ``posture``
    says whose turn it is, ``shared_session`` whether the turn is on the owner's shared
    session (a getter that fails counts as yes), and ``origin`` whether the turn is
    untrusted (a getter that fails counts as untrusted). With no ``store`` the call reads
    :data:`TODOS` at call time, the one the routes serve."""
    from agents.core.security.taint import is_untrusted_source

    def _target() -> TodoStore:
        return store if store is not None else TODOS

    def _shared() -> bool:
        if shared_session is None:
            return False
        try:
            return bool(shared_session())
        except Exception:
            logger.warning("todo: the shared-session flag failed; counted as shared", exc_info=True)
            return True

    def _untrusted() -> bool:
        try:
            return is_untrusted_source(origin())
        except Exception:
            logger.warning("todo: the turn origin failed; counted as untrusted", exc_info=True)
            return True

    async def _handle(args: dict) -> dict:
        from agents.core.tool_rpc import current_tool_actor, current_tool_turn

        unknown = sorted(str(key) for key in args if key not in _ARG_FIELDS)
        if unknown:
            return {"ok": False, "reason": "todo_unknown_field",
                    "detail": f"todo takes todos and merge only, not {unknown[0]!r}"}
        where = ""
        if posture is not None:
            try:
                where = str(posture() or "")
            except Exception:
                where = ""
        if _shared() and not where.endswith("/owner"):
            return {"ok": False, "reason": "todo_shared_session", "detail": SHARED_SESSION_DETAIL}
        try:
            sid = session_id()
        except Exception:
            logger.warning("todo: the session getter failed", exc_info=True)
            sid = ""
        todos = args.get("todos")
        merge = args.get("merge")
        merge = False if merge is None else merge   # an explicit null is "not sent"
        # Text is untrusted to the owner when an untrusted turn wrote it, or a turn that is
        # not the owner's: a household member or a guest on a session they share with the
        # owner, a background job.
        untrusted = _untrusted() or not where.endswith("/owner")
        try:
            view, foreign = _target().apply(sid, todos, merge, agent=current_tool_actor(), posture=where,
                                            tainted=untrusted, turn=current_tool_turn())
        except TodoError as exc:
            return {"ok": False, "reason": exc.reason, "detail": exc.detail}
        if todos is not None:
            _record_event(view, merge=merge is True)
        reply: dict[str, Any] = {"ok": True, "todos": model_items(view["todos"]), "counts": view["counts"]}
        if foreign:
            # The loop fences it as DATA and taints the reading turn. An item this very turn
            # wrote is not a reason: its text is the model's own argument, already in the
            # transcript, and fencing it would tell the model not to follow its own plan.
            reply["tainted"] = True
        return reply

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
    "MAX_PLAN_BYTES", "MAX_SESSIONS", "SHARED_SESSION_DETAIL", "STATUSES", "TODOS", "TOOL_NAME",
    "TodoError", "TodoStore", "counts", "model_items", "plan_bytes", "register_todo_tool",
]
