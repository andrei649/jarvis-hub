"""inbox_tools.py — G10 / H559: the owner's inbox and approvals over Nerva's MCP server.

An MCP client the owner has authorised can:

* ``conversations_list`` — the owner's own recent conversations (title, start, turns);
* ``conversation_read`` — one of those conversations, read-only;
* ``approvals_list`` — the pending approval cards, the same projection as
  ``GET /autonomy/approvals`` (what the HUD Decision Inbox and ``nerva approvals list`` show);
* ``approval_respond`` — approve or deny one card.

Security model (each point is enforced here, not by the client):

* **Owner only.** Every tool needs the transport to vouch that the caller is the owner
  (``transport_owner(True)`` around the request in ``routers/mcp.py``): an admin credential, or the fresh-box
  localhost posture exactly as ``admin_guard`` decides it, or — with OAuth on — a token
  minted with the ``mcp:owner`` scope (only ``POST /api/mcp/token``, itself admin-guarded,
  can mint one). A user token, a guest token or an OAuth token without that scope gets
  nothing: not the list, not a title, not a card.
* **One decision path.** ``approval_respond`` calls the very handler behind
  ``POST /autonomy/tasks/{id}/decision`` (HUD and ``nerva approvals accept|reject``):
  same ``apply_decision``, same ``decided_by``, same queue transition (a card answered
  once cannot be answered again — the queue's state machine refuses the second
  transition), same worker audit row. Nothing here writes to the queue itself.
* **Read-only server.** ``approval_respond`` is the one write. It is listed and callable
  only while the MCP write surface is on (``JARVIS_MCP_ROUTE_TOOLS`` and
  ``JARVIS_MCP_MUTATING_TOOLS``; the hardened profile forces it off), re-checked at call
  time.
* **Strict input.** A card id is a positive integer (or its decimal string); the decision
  is ``approve`` or ``deny``; the reason is the HUD's bounded reason. The card must be in
  the pending list at call time.
* **Irreversible cards are not approved over MCP.** Denying one is allowed (it stops
  something); approving one is refused with a pointer to the HUD or ``nerva approvals``.
* **Audited.** Every answer writes a durable ``authorized`` row through the hub's audit
  sink before the decision runs (no sink, no answer), then its outcome; reads are recorded
  best-effort, refusals at most once a minute per caller, tool and outcome (with a count of
  the ones folded in). Rows carry ids and tool names, never conversation text.
* **Text is data.** Conversation turns, titles and card titles/payloads come back inside
  the hub's ``<<UNTRUSTED ...>>`` fence with invisible characters removed and injection
  flags named; only hub-controlled card fields (id, kind, tier, ...) are plain.
* **The owner's own conversations.** Only a conversation the hub's trust ledger holds as
  clean (``Orchestrator.session_trust``) is listed or readable. A guest speaking in the
  shared HUD conversation, an inbound message, a web page, file or image read, a flagged
  recall, an import, a channel (``ch_…``) or API-key (``oai-…``) conversation, and a
  conversation older than the ledger all hide it. A read never resumes or activates it.

Not here (H558 residual): per-identity MCP tokens for other household members. A token is
the owner's or it reaches none of these tools.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("jarvis.mcp.inbox")

#: The OAuth scope that marks an MCP bearer token as the owner's.
OWNER_SCOPE = "mcp:owner"

CONVERSATIONS_LIST = "conversations_list"
CONVERSATION_READ = "conversation_read"
APPROVALS_LIST = "approvals_list"
APPROVAL_RESPOND = "approval_respond"
INBOX_TOOL_NAMES = (CONVERSATIONS_LIST, CONVERSATION_READ, APPROVALS_LIST, APPROVAL_RESPOND)
READ_TOOL_NAMES = (CONVERSATIONS_LIST, CONVERSATION_READ, APPROVALS_LIST)

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50
DEFAULT_TURN_LIMIT = 50
MAX_TURN_LIMIT = 200
MAX_TURN_CHARS = 20_000
#: conversations_list stops scanning the session store after this many rows.
MAX_SCAN_ROWS = 2_000
#: Refusal audit rows: one per (caller, tool, outcome) per window, a bounded key table.
REFUSAL_AUDIT_WINDOW_S = 60.0
REFUSAL_AUDIT_KEYS = 512

#: Decision word over MCP → the action the HUD/CLI decision route takes.
DECISIONS = {"approve": "accept", "deny": "reject"}

_CARD_ID_RE = re.compile(r"^[1-9][0-9]{0,17}$")
#: Session prefixes that are never the owner's own conversation: channel doors and
#: OpenAI-compatible API keys (a key may be a guest's).
_NOT_OWNER_PREFIXES = ("ch_", "oai-")


#: The transport's verdict for the request in flight (``routers/mcp.py`` sets it around
#: ``JarvisMCPServer.handle``). Per task: a concurrent request never sees another's.
_TRANSPORT_OWNER: ContextVar[bool] = ContextVar("nerva_mcp_transport_owner", default=False)


@contextmanager
def transport_owner(owner: bool) -> Iterator[None]:
    """Mark the MCP request in flight as the owner's (or not) for the inbox tools."""
    token = _TRANSPORT_OWNER.set(owner is True)
    try:
        yield
    finally:
        _TRANSPORT_OWNER.reset(token)


def current_transport_owner() -> bool:
    return _TRANSPORT_OWNER.get() is True


class InboxRefusal(Exception):
    """A tool call refused before (or instead of) any effect. The message is safe to show."""


# ── input validation ─────────────────────────────────────────────────────────

def parse_card_id(value: Any) -> int:
    """A positive integer, or its plain decimal string. Anything else is refused."""
    if isinstance(value, bool):
        raise InboxRefusal("invalid card id")
    if isinstance(value, int):
        if 0 < value < 10 ** 18:
            return value
        raise InboxRefusal("invalid card id")
    if isinstance(value, str) and _CARD_ID_RE.fullmatch(value):
        return int(value)
    raise InboxRefusal("invalid card id")


def parse_decision(value: Any) -> str:
    if not isinstance(value, str) or value not in DECISIONS:
        raise InboxRefusal("decision must be 'approve' or 'deny'")
    return value


def parse_reason(value: Any) -> str | None:
    from agents.core.autonomy.decision_reasons import normalize_reason

    try:
        return normalize_reason(value)
    except ValueError as exc:
        raise InboxRefusal(str(exc)) from None


def parse_limit(value: Any, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise InboxRefusal(f"limit must be an integer from 1 to {maximum}")
    return value


def parse_session_id(value: Any) -> str:
    from agents.core.validation import is_valid_session_id

    if not is_valid_session_id(value):
        raise InboxRefusal("invalid session_id")
    return value


# ── descriptors ──────────────────────────────────────────────────────────────

_DESCRIPTORS: dict[str, dict] = {
    CONVERSATIONS_LIST: {
        "description": "The owner's own recent conversations (newest first): id, title, "
                       "start time, turn count. Read-only. Owner token required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST_LIMIT,
                          "default": DEFAULT_LIST_LIMIT},
            },
            "additionalProperties": False,
        },
    },
    CONVERSATION_READ: {
        "description": "Read one of the owner's own conversations (the last turns). "
                       "Read-only: it does not resume or switch the conversation. "
                       "Owner token required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "From conversations_list."},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TURN_LIMIT,
                          "default": DEFAULT_TURN_LIMIT},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
    },
    APPROVALS_LIST: {
        "description": "Pending approval cards (the HUD Decision Inbox / `nerva approvals "
                       "list`): id, kind, title, risk tier, reversible. Owner token required.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    APPROVAL_RESPOND: {
        "description": "Approve or deny one pending approval card, through the same decision "
                       "path as the HUD and `nerva approvals`. Irreversible cards can only be "
                       "denied here. Owner token required; refused while the MCP server is "
                       "read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer", "minimum": 1,
                            "description": "The card id from approvals_list."},
                "decision": {"type": "string", "enum": sorted(DECISIONS)},
                "reason": {"type": "string", "maxLength": 280,
                           "description": "Optional note kept with the decision."},
            },
            "required": ["card_id", "decision"],
            "additionalProperties": False,
        },
    },
}


# ── the backend: what the tools read and the one thing they write ───────────

@dataclass
class InboxBackend:
    """The hub seams the tools use; ``web.py`` binds the live ones, tests bind fakes.

    ``list_conversations(limit)`` and ``read_conversation(session_id, limit)`` return
    owner-only data (the filter lives in :func:`owner_conversation`). ``list_approvals()``
    returns the ``GET /autonomy/approvals`` payload. ``decide(task_id, action, reason)``
    is the ``POST /autonomy/tasks/{id}/decision`` handler and returns
    ``(status_code, payload)``.
    """

    list_conversations: Callable[[int], Awaitable[list[dict]]]
    read_conversation: Callable[[str, int], Awaitable[dict]]
    list_approvals: Callable[[], Awaitable[dict]]
    decide: Callable[[int, str, str | None], Awaitable[tuple[int, Any]]]


class InboxTools:
    """The four owner tools, dispatched by :class:`JarvisMCPServer`."""

    def __init__(
        self,
        backend: InboxBackend,
        *,
        writes_enabled: Callable[[], bool],
        auditor: Any = None,
    ) -> None:
        self.backend = backend
        self.writes_enabled = writes_enabled
        self.auditor = auditor
        # Refusal rows coalesced per (caller, tool, outcome): first row written, later
        # ones in the window counted and reported on the next row (review m4).
        self._refusals: dict[tuple[str, str, str], list] = {}

    # -- surface --

    def _writes_on(self) -> bool:
        try:
            return bool(self.writes_enabled())
        except Exception:
            return False

    def names(self) -> tuple[str, ...]:
        return INBOX_TOOL_NAMES if self._writes_on() else READ_TOOL_NAMES

    def handles(self, name: str) -> bool:
        return name in INBOX_TOOL_NAMES

    def descriptors(self) -> list[dict]:
        out = []
        for name in self.names():
            spec = _DESCRIPTORS[name]
            descriptor = {"name": name, "description": spec["description"],
                          "inputSchema": spec["inputSchema"]}
            if name == APPROVAL_RESPOND:
                descriptor["mutating"] = True
            else:
                descriptor["annotations"] = {"readOnlyHint": True}
            out.append(descriptor)
        return out

    def inventory(self) -> list[dict]:
        rows = []
        for name in self.names():
            write = name == APPROVAL_RESPOND
            rows.append({
                "name": name,
                "tool_class": "owner_inbox",
                "persistent_state": write,
                "direct_route_mutation": write,
                "state_effects": ["approval_decision"] if write else [],
                "authority_boundary": (
                    "owner identity from the transport; the HUD/CLI decision handler "
                    "(apply_decision) with its single-use queue transition; irreversible "
                    "cards deny-only" if write else
                    "owner identity from the transport; owner's own conversations only"
                ),
                "identity_posture": "owner (admin credential or mcp:owner OAuth scope)",
                "audit_posture": ("durable authorization row required before the decision"
                                  if write else "best-effort read row, no content"),
                "retention_posture": "approval queue" if write else "no state written",
                "kernel_posture": (
                    "the decision is the owner's answer to a card the kernel already "
                    "queued; the accepted action keeps its own execution gates"
                    if write else "not applicable to read-only dispatch"),
                "governance": "governed",
                "controls": (["owner_required", "read_only_server_refused",
                              "card_id_validated", "pending_card_required",
                              "irreversible_deny_only", "audit_preflight_required",
                              "hud_decision_handler"] if write else
                             ["owner_required", "owner_conversations_only"]),
            })
        return rows

    # -- audit --

    def _refused(self, caller: str, tool: str, outcome: str, detail: str = "") -> None:
        """A refusal row, at most one per caller, tool and outcome a minute; the
        refusals in between are counted and carried on the next row written."""
        key = (caller, tool, outcome)
        now = time.monotonic()
        slot = self._refusals.get(key)
        if slot is not None and now - slot[0] < REFUSAL_AUDIT_WINDOW_S:
            slot[1] += 1
            return
        suppressed = slot[1] if slot is not None else 0
        if slot is None and len(self._refusals) >= REFUSAL_AUDIT_KEYS:
            # Bounded: forget the oldest window (its count is lost, its first row stands).
            del self._refusals[min(self._refusals, key=lambda k: self._refusals[k][0])]
        self._refusals[key] = [now, 0]
        extra = f" suppressed={suppressed}" if suppressed else ""
        self._audit(tool, outcome, f"{detail}{extra}".strip())

    def _audit(self, tool: str, outcome: str, detail: str = "", *, required: bool = False) -> None:
        if self.auditor is None or not callable(getattr(self.auditor, "log", None)):
            if required:
                raise InboxRefusal("audit sink is unavailable")
            return
        try:
            from agents.core.security.types import SecurityEvent, SecurityEventType

            self.auditor.log(SecurityEvent(
                event_type=SecurityEventType.AUDIT_LOG,
                timestamp=time.time(),
                findings=[],
                content_preview=f"mcp owner tool {tool} {detail}".strip()[:100],
                action_taken=f"mcp {tool} ({outcome})",
            ))
        except Exception:
            logger.warning("audit log failed for MCP owner tool %s", tool, exc_info=True)
            if required:
                raise InboxRefusal("audit sink rejected the authorization row") from None

    # -- dispatch --

    async def call(self, name: str, arguments: dict | None, *, owner: bool,
                   caller: str = "unknown") -> Any:
        """Run one tool and return its JSON payload, or raise :class:`InboxRefusal`.

        *caller* is an opaque key for the presented credential (never logged); it only
        groups refusal audit rows. Text that people or models wrote (turns, titles, card
        titles and payloads) comes back fenced as data, invisible characters removed.
        """
        arguments = arguments if isinstance(arguments, dict) else {}
        if not owner:
            self._refused(caller, name, "refused-identity")
            raise InboxRefusal(f"{name} requires the owner's MCP credential")
        allowed = set(_DESCRIPTORS[name]["inputSchema"].get("properties", {}))
        unknown = sorted(k for k in arguments if k not in allowed)
        if unknown:
            raise InboxRefusal(f"unknown argument(s): {', '.join(unknown)}")
        if name == CONVERSATIONS_LIST:
            limit = parse_limit(arguments.get("limit"), DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)
            rows = await self.backend.list_conversations(limit)
            self._audit(name, "ok", f"count={len(rows)}")
            return {"conversations": [_public_conversation(r) for r in rows[:limit]
                                      if isinstance(r, dict)], "untrusted": True}
        if name == CONVERSATION_READ:
            sid = parse_session_id(arguments.get("session_id"))
            limit = parse_limit(arguments.get("limit"), DEFAULT_TURN_LIMIT, MAX_TURN_LIMIT)
            result = await self.backend.read_conversation(sid, limit)
            self._audit(name, "ok", f"session={sid}")
            return _public_transcript(result)
        if name == APPROVALS_LIST:
            payload = await self.backend.list_approvals()
            self._audit(name, "ok")
            return _public_approvals(payload)
        if name == APPROVAL_RESPOND:
            return await self._respond(arguments, caller)
        raise InboxRefusal(f"unknown tool: {name}")

    async def _respond(self, arguments: dict, caller: str = "unknown") -> Any:
        if not self._writes_on():
            self._refused(caller, APPROVAL_RESPOND, "refused-read-only")
            raise InboxRefusal("the MCP server is read-only: approval_respond is not available "
                               "(JARVIS_MCP_ROUTE_TOOLS and JARVIS_MCP_MUTATING_TOOLS)")
        try:
            card_id = parse_card_id(arguments.get("card_id"))
            decision = parse_decision(arguments.get("decision"))
            reason = parse_reason(arguments.get("reason"))
        except InboxRefusal:
            self._refused(caller, APPROVAL_RESPOND, "refused-input")
            raise
        detail = f"card={card_id} decision={decision}"
        listing = await self.backend.list_approvals()
        pending = listing.get("pending") if isinstance(listing, dict) else None
        if not isinstance(pending, list):
            raise InboxRefusal("the approval queue is unavailable")
        card = next((c for c in pending if isinstance(c, dict) and c.get("id") == card_id), None)
        if card is None:
            self._refused(caller, APPROVAL_RESPOND, "refused-unknown-card", detail)
            raise InboxRefusal(f"card {card_id} is not pending (unknown, or already answered)")
        if decision == "approve" and card.get("reversible") is not True:
            self._refused(caller, APPROVAL_RESPOND, "refused-irreversible", detail)
            raise InboxRefusal(
                f"card {card_id} is irreversible: approve it in the HUD or with "
                f"`nerva approvals accept {card_id}`; it can be denied here")
        # The authorization row must land before the decision runs (no sink, no answer).
        self._audit(APPROVAL_RESPOND, "authorized", detail, required=True)
        try:
            status, payload = await self.backend.decide(card_id, DECISIONS[decision], reason)
        except Exception:
            self._audit(APPROVAL_RESPOND, "error", detail)
            raise
        if status >= 400:
            self._audit(APPROVAL_RESPOND, "refused-queue", detail)
            error = payload.get("error") if isinstance(payload, dict) else None
            raise InboxRefusal(f"card {card_id} was not answered: {error or 'decision refused'}")
        self._audit(APPROVAL_RESPOND, "ok", detail)
        task = payload.get("task") if isinstance(payload, dict) else None
        return {"ok": True, "task": _public_card(task) if isinstance(task, dict) else None,
                "untrusted": True}


# ── what leaves the hub: text marked as data (review m2) ─────────────────────

def _clean(value: Any) -> Any:
    """Every string inside *value* without invisible characters (TAG block, format and
    other zero-width characters, stray C0/C1 controls); newlines and tabs stay."""
    from agents.core.security.quarantine import strip_format_chars

    if isinstance(value, str):
        return strip_format_chars(value)
    if isinstance(value, dict):
        return {_clean(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _fenced(text: Any, source: str) -> str:
    """*text* inside the same four-line DATA fence the hub puts round tool results."""
    from agents.core.security.quarantine import fence_text

    return fence_text(_clean(text) if isinstance(text, str) else "", source=source)


def _flags(text: Any) -> list[str]:
    from agents.core.security.quarantine import fence_flags

    return fence_flags(_clean(text)) if isinstance(text, str) else []


def _public_conversation(row: dict) -> dict:
    out = {k: _clean(row.get(k)) for k in ("session_id", "title_source", "started_at",
                                           "ended_at", "turn_count")}
    out["title"] = _fenced(row.get("title") or "", "nerva.conversation_title")
    return out


def _public_transcript(result: Any) -> dict:
    if not isinstance(result, dict):
        raise InboxRefusal("conversation is unavailable")
    turns = []
    for turn in result.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        content = turn.get("content")
        row = {k: _clean(turn.get(k)) for k in ("role", "agent_id", "timestamp")}
        row["content"] = _fenced(content, "nerva.conversation")
        flags = _flags(content)
        if flags:
            row["injection_flags"] = flags
        if turn.get("truncated"):
            row["truncated"] = True
        turns.append(row)
    return {
        "session_id": _clean(result.get("session_id")),
        "title": _fenced(result.get("title") or "", "nerva.conversation_title"),
        "title_source": _clean(result.get("title_source")),
        "total_turns": result.get("total_turns"),
        "untrusted": True,
        "turns": turns,
    }


#: The structured card fields an MCP client gets as they are (hub-controlled values).
_CARD_FIELDS = ("id", "agent", "kind", "status", "risk_tier", "tier_name", "reversible",
                "reversibility", "origin", "created_at", "updated_at", "approval_mode",
                "capability_id", "decided_by", "decision")


def _public_card(card: dict) -> dict:
    import json as _json

    out = {k: _clean(card.get(k)) for k in _CARD_FIELDS if k in card}
    out["title"] = _fenced(card.get("title") or "", "nerva.approval_card")
    payload = card.get("payload")
    encoded = _json.dumps(payload, default=str, ensure_ascii=False) if payload is not None else ""
    out["payload"] = _fenced(encoded, "nerva.approval_card")
    flags = _flags(card.get("title")) + _flags(encoded)
    if flags:
        out["injection_flags"] = sorted(set(flags))
    return out


def _public_approvals(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise InboxRefusal("the approval queue is unavailable")
    pending = [_public_card(c) for c in payload.get("pending") or [] if isinstance(c, dict)]
    return {"pending": pending, "counts": _clean(payload.get("counts")),
            "mode": _clean(payload.get("mode")), "untrusted": True}


# ── the live backend over the orchestrator ──────────────────────────────────

def owner_conversation(orch: Any, session_id: str) -> bool:
    """Whether *session_id* is the owner's own conversation. Blocking (SQLite).

    Only a conversation the hub's trust ledger holds as clean (``Orchestrator.session_trust``
    == "clean": watched from its first turn and never touched by a guest, an inbound
    message, outside text or a flagged recall) qualifies. Fails closed: an unreadable
    origin or ledger, a missing check or any error is "no".
    """
    from agents.core.validation import is_valid_session_id

    if not is_valid_session_id(session_id) or session_id.startswith(_NOT_OWNER_PREFIXES):
        return False
    try:
        from agents.core.foreign_history import status

        checkpoints = getattr(orch, "checkpoints", None)
        if checkpoints is None or status(checkpoints, session_id).tainted:
            return False
        evidence = getattr(orch, "session_unclean_evidence", None)
        if not callable(evidence) or evidence(session_id):
            return False
        # Review M1: the hub's trust ledger is the authority. A guest's turn, an inbound
        # message, a web page or file read, a flagged recall: anything that took the
        # conversation off the clean list hides it; so does a conversation the ledger
        # never watched from its first turn ("unproven") and a ledger that cannot answer.
        trust = getattr(orch, "session_trust", None)
        if not callable(trust):
            return False
        return trust(session_id) == "clean"
    except Exception:
        return False


def _turn_row(turn: Any) -> dict | None:
    if not isinstance(turn, dict):
        return None
    content = turn.get("content")
    content = content if isinstance(content, str) else ""
    truncated = len(content) > MAX_TURN_CHARS
    row = {
        "role": turn.get("role") if isinstance(turn.get("role"), str) else "",
        "content": content[:MAX_TURN_CHARS],
        "agent_id": turn.get("agent_id") if isinstance(turn.get("agent_id"), str) else None,
        "timestamp": turn.get("timestamp") if isinstance(turn.get("timestamp"), (str, int, float)) else None,
    }
    if truncated:
        row["truncated"] = True
    return row


def build_orch_backend(get_orch: Callable[[], Any]) -> InboxBackend:
    """The live backend. ``get_orch`` is read per call (the hub rebinds it)."""

    def _orch():
        orch = get_orch()
        if orch is None:
            raise InboxRefusal("hub not initialized")
        return orch

    async def list_conversations(limit: int) -> list[dict]:
        from agents.core.session_titles import title_fields

        orch = _orch()
        checkpoints = getattr(orch, "checkpoints", None)
        if checkpoints is None:
            raise InboxRefusal("the conversation store is unavailable")
        # Review m3: the store has no offset, so widen the window page by page until
        # *limit* owner conversations are found, the store runs out, or the scan bound.
        out: list[dict] = []
        seen: set[str] = set()
        window = min(MAX_SCAN_ROWS, max(limit * 4, 50))
        while True:
            rows = await asyncio.to_thread(
                checkpoints.get_sessions, limit=window, archived=False,
                native_only=True, hide_continuations=True)
            for row in rows:
                sid = row.get("id") or row.get("session_id")
                if not isinstance(sid, str) or sid in seen:
                    continue
                seen.add(sid)
                if not await asyncio.to_thread(owner_conversation, orch, sid):
                    continue
                out.append({
                    "session_id": sid,
                    **title_fields(row.get("metadata")),
                    "started_at": row.get("started_at"),
                    "ended_at": row.get("ended_at"),
                    "turn_count": row.get("turn_count"),
                })
                if len(out) >= limit:
                    return out
            if len(rows) < window or window >= MAX_SCAN_ROWS:
                return out
            window = min(MAX_SCAN_ROWS, window * 2)

    async def read_conversation(session_id: str, limit: int) -> dict:
        from agents.core.session_titles import title_fields

        orch = _orch()
        if not await asyncio.to_thread(owner_conversation, orch, session_id):
            raise InboxRefusal("conversation not found")
        checkpoints = orch.checkpoints
        row = await asyncio.to_thread(checkpoints.session_row, session_id)
        memory = getattr(orch, "memory", None)
        conversation = getattr(memory, "conversation", None)
        loaded = session_id in (getattr(conversation, "sessions", None) or {})
        if row is None and not loaded:
            raise InboxRefusal("conversation not found")
        if loaded:
            try:
                turns = await memory.get_history(session_id)
            except Exception:
                raise InboxRefusal("conversation is unavailable") from None
        else:
            # Read the saved snapshot without loading it into the hub: a read never
            # resumes, activates or rewrites a conversation.
            from agents.core.memory.persistence import load_memory_snapshot

            snapshot = await asyncio.to_thread(load_memory_snapshot, session_id)
            if (not isinstance(snapshot, dict) or snapshot.get("rewound") is True
                    or isinstance(snapshot.get("foreign_history"), dict)):
                raise InboxRefusal("conversation is unavailable")
            turns = snapshot.get("turns") if snapshot.get("session_id") == session_id else []
            turns = turns if isinstance(turns, list) else []
        rows = [r for r in (_turn_row(t) for t in turns) if r is not None]
        return {
            "session_id": session_id,
            **title_fields((row or {}).get("metadata")),
            "total_turns": len(rows),
            "turns": rows[-limit:],
        }

    async def list_approvals() -> dict:
        from agents.core.mcp.route_tools import normalize_result
        from agents.core.routers.autonomy import autonomy_approvals

        _orch()
        raw = await autonomy_approvals()
        if getattr(raw, "status_code", 200) >= 400:
            raise InboxRefusal("the approval queue is unavailable")
        payload = normalize_result(raw)
        if not isinstance(payload, dict):
            raise InboxRefusal("the approval queue is unavailable")
        return {key: payload.get(key) for key in ("pending", "counts", "mode")}

    async def decide(task_id: int, action: str, reason: str | None) -> tuple[int, Any]:
        """``POST /autonomy/tasks/{id}/decision`` — the HUD's and the CLI's handler."""
        from agents.core.mcp.route_tools import normalize_result
        from agents.core.routers.autonomy import AutonomyDecisionBody, autonomy_decide

        _orch()
        raw = await autonomy_decide(task_id, AutonomyDecisionBody(action=action, reason=reason))
        return int(getattr(raw, "status_code", 200)), normalize_result(raw)

    return InboxBackend(list_conversations=list_conversations,
                        read_conversation=read_conversation,
                        list_approvals=list_approvals,
                        decide=decide)
