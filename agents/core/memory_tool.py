"""memory_tool.py — the model writes its own memory during a turn, visibly and undoably (H314).

Hermes's ``memory`` tool adds, replaces and removes entries in the two stores it injects
into every prompt: the agent's notes and the user profile. Nerva has both, the
LivingMemory ``core`` and ``user_core`` rings rendered by ``render_core_block``, but the
model could only reach them indirectly: the post-turn review (off by default) wrote up to
a few facts per turn, with no audit record. ``memory`` is the direct write:

* one call carries ``operations``, each ``{action, target, text, old_text}``: ``add`` a
  fact, ``replace`` the one fact ``old_text`` matches with ``text``, or ``remove`` it.
  ``target`` is ``memory`` (the agent's notes) or ``user`` (the user profile). A call with
  no operations reads both rings;
* the call is atomic: every operation is checked against a working copy first, and one
  refusal changes nothing. A ring is written by compare-and-set, so a forget (or another
  write) that ran in between wins and the call is refused, never written over it;
* every fact is one line of at most :data:`MAX_FACT_CHARS` characters (the core block's
  own cut), free of control and invisible characters, and scanned for injection with the
  normalised scanner; a full ring refuses an add instead of silently dropping the oldest
  fact (replace or remove one first);
* only the owner's own turns at the operator surface write: the tool is offered to no
  other posture (``tool_profiles.OWNER_OPERATOR_TOOLS``), and a turn that has read
  untrusted content (an inbound message, web content, a tainted recall) is refused, so an
  injected instruction cannot make itself permanent;
* every write appends an intent-log record (``memory.write``: the actor, what changed,
  per target and action, and a hash of each fact — never the text, because the intent
  log survives "forget me") carrying an undo ref. The ring's previous contents are kept
  under that ref in a purgeable store beside the rings (:class:`UndoStore`), so a forget
  deletes them too. :func:`undo` restores a write while nothing has changed since, and is
  recorded the same way; ``POST /api/memory/core/undo`` is the owner's door;
* a write leaves a ``memory_updated`` row in the tool trail (targets, actions and counts,
  never text);
* in safe mode (H490) memory reads as switched off: the tool refuses and says so.

The prompt's core block is frozen per session (it keeps the prompt cache), so a write
reaches the system prompt at the next session; the tool answers with both rings as they
now are, so the model works from them at once.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.memory_tool")

TOOL_NAME = "memory"
CAPABILITY_ID = "tool:memory"
ACTIONS: tuple[str, ...] = ("add", "replace", "remove")
#: The model's names for the two rings, and the LivingMemory attribute each one is.
TARGETS: dict[str, str] = {"memory": "core", "user": "user_core"}
MAX_OPERATIONS = 8
MAX_FACT_CHARS = 300
#: Undo refs kept; the oldest is dropped first.
UNDO_KEEP = 50
_ARG_FIELDS = frozenset({"operations"})
_OP_FIELDS = frozenset({"action", "target", "text", "old_text"})

_OPERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "target": {"type": "string", "enum": list(TARGETS)},
        "text": {"type": "string", "minLength": 1, "maxLength": MAX_FACT_CHARS},
        "old_text": {"type": "string", "minLength": 1, "maxLength": MAX_FACT_CHARS},
    },
    "required": ["action", "target"],
    "additionalProperties": False,
}

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operations": {"type": "array", "maxItems": MAX_OPERATIONS, "items": _OPERATION_SCHEMA},
    },
    "additionalProperties": False,
}

DESCRIPTION = (
    "Your long-term memory, kept across conversations: target memory holds your own notes "
    "(facts about the environment, conventions, lessons), target user holds what you know "
    "about the user (preferences, how they like to work). Send operations: add a fact (text), "
    "replace the one fact old_text matches with text, or remove the one fact old_text matches. "
    "Each fact is one short line. Save what will still matter next time; do not save what "
    "belongs to this task only. A call with no operations reads both. Every change is "
    "recorded and the owner can undo it."
)
OFF_DESCRIPTION = DESCRIPTION + " Memory is switched off on this hub (cognition memory), so every call is refused."


class MemoryToolError(ValueError):
    """A refused call: a named reason and a sentence the model can act on."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ── the facts ────────────────────────────────────────────────────────────────

def _clean_text(raw: Any, index: int, field: str) -> str:
    if not isinstance(raw, str):
        raise MemoryToolError("memory_bad_text", f"operation {index}: {field} must be text")
    if len(raw) > MAX_FACT_CHARS * 4:
        raise MemoryToolError("memory_text_too_long",
                              f"operation {index}: {field} is over {MAX_FACT_CHARS} characters")
    text = " ".join(raw.split())
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cn") for ch in text):
        raise MemoryToolError("memory_bad_text",
                              f"operation {index}: {field} holds a control or invisible character")
    if not text:
        raise MemoryToolError("memory_bad_text", f"operation {index}: {field} is empty")
    if len(text) > MAX_FACT_CHARS:
        raise MemoryToolError("memory_text_too_long",
                              f"operation {index}: {field} is over {MAX_FACT_CHARS} characters")
    return text


def _scan(text: str, index: int) -> None:
    from .security.quarantine import detect_injection_normalized

    if detect_injection_normalized(text):
        raise MemoryToolError("memory_injection_flagged",
                              f"operation {index}: the text reads like an instruction to a model; "
                              "save facts, not instructions")


def _match(facts: list[str], old_text: str, index: int) -> int:
    hits = [pos for pos, fact in enumerate(facts) if old_text in fact]
    if not hits:
        raise MemoryToolError("memory_no_match", f"operation {index}: no saved fact contains old_text")
    if len(hits) > 1:
        raise MemoryToolError("memory_ambiguous",
                              f"operation {index}: {len(hits)} saved facts contain old_text; quote more of one")
    return hits[0]


def plan(operations: Any, rings: Mapping[str, list[str]], cap: Mapping[str, int]) -> tuple[dict, list[dict]]:
    """The rings after *operations*, checked in full before anything is written, and one
    row per applied operation (``action``, ``target``, ``fact_sha256``). Raises
    :class:`MemoryToolError`; an add that is already saved is recorded as ``unchanged``."""
    if not isinstance(operations, list):
        raise MemoryToolError("memory_bad_operations", "operations must be a list")
    if len(operations) > MAX_OPERATIONS:
        raise MemoryToolError("memory_too_many_operations", f"at most {MAX_OPERATIONS} operations a call")
    after = {target: list(facts) for target, facts in rings.items()}
    rows: list[dict] = []
    for index, op in enumerate(operations, 1):
        if not isinstance(op, Mapping):
            raise MemoryToolError("memory_bad_operations", f"operation {index} must be an object")
        unknown = sorted(str(key) for key in op if key not in _OP_FIELDS)
        if unknown:
            raise MemoryToolError("memory_unknown_field", f"operation {index}: unknown field {unknown[0]!r}")
        action, target = op.get("action"), op.get("target")
        if action not in ACTIONS:
            raise MemoryToolError("memory_bad_action", f"operation {index}: action is one of {', '.join(ACTIONS)}")
        if target not in after:
            raise MemoryToolError("memory_bad_target",
                                  f"operation {index}: target is one of {', '.join(sorted(after))}")
        facts = after[target]
        text = _clean_text(op.get("text"), index, "text") if action != "remove" else None
        old = _clean_text(op.get("old_text"), index, "old_text") if action != "add" else None
        if action == "remove" and op.get("text") is not None:
            raise MemoryToolError("memory_unknown_field", f"operation {index}: remove takes old_text only")
        if action == "add" and op.get("old_text") is not None:
            raise MemoryToolError("memory_unknown_field", f"operation {index}: add takes text only")
        if text is not None:
            _scan(text, index)
        if action == "add":
            if text in facts:
                rows.append({"action": "unchanged", "target": target, "fact_sha256": _sha(text)})
                continue
            if len(facts) >= cap[target]:
                raise MemoryToolError("memory_full",
                                      f"operation {index}: {target} holds its {cap[target]} facts; "
                                      "replace or remove one first")
            facts.append(text)
        else:
            pos = _match(facts, old, index)
            if action == "remove":
                rows.append({"action": "remove", "target": target, "fact_sha256": _sha(facts.pop(pos))})
                continue
            if text != facts[pos] and text in facts:
                raise MemoryToolError("memory_duplicate", f"operation {index}: that fact is already saved")
            facts[pos] = text
        rows.append({"action": action, "target": target, "fact_sha256": _sha(text)})
    return after, rows


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ring_sha(facts: list[str]) -> str:
    return _sha(json.dumps(facts, ensure_ascii=False))


# ── undo ─────────────────────────────────────────────────────────────────────

class UndoStore:
    """The rings as they were before each write, by ref, beside the rings themselves so a
    forget deletes them with the rings (the intent log, which survives it, holds only the
    ref and hashes)."""

    def __init__(self, path: Path | None = None, keep: int = UNDO_KEEP) -> None:
        self._path = path
        self._keep = keep
        self._lock = threading.Lock()

    def path(self) -> Path:
        if self._path is not None:
            return self._path
        from .paths import data_path

        return data_path("cognition", "memory_undo.json")

    def _load(self) -> list[dict]:
        try:
            raw = json.loads(self.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []

    def put(self, entry: dict) -> None:
        from .persistence.json_store import atomic_write_json

        with self._lock:
            rows = [row for row in self._load() if row.get("ref") != entry["ref"]] + [entry]
            atomic_write_json(self.path(), rows[-self._keep:])

    def get(self, ref: str) -> dict | None:
        with self._lock:
            return next((row for row in self._load() if row.get("ref") == ref), None)

    def recent(self, limit: int = 20) -> list[dict]:
        """The newest undoable writes: ref, time and targets (never the text)."""
        with self._lock:
            rows = self._load()[-max(0, int(limit)):]
        return [{"ref": row.get("ref"), "ts": row.get("ts"), "targets": sorted(row.get("before") or {})}
                for row in reversed(rows)]

    def drop(self, ref: str) -> None:
        from .persistence.json_store import atomic_write_json

        with self._lock:
            rows = self._load()
            kept = [row for row in rows if row.get("ref") != ref]
            if len(kept) != len(rows):
                atomic_write_json(self.path(), kept)


UNDO = UndoStore()
_WRITE_LOCK = threading.Lock()


def _record(audit: Any, actor: str, action: str, why: str, ref: str, metadata: dict) -> None:
    """One intent-log record, or raise: a write is never made unrecorded."""
    if audit is None or not callable(getattr(audit, "record", None)):
        raise MemoryToolError("memory_audit_unavailable",
                              "memory writes are recorded in the intent log, which is not available")
    audit.record(actor=actor, action=action, why=why, cause=ref, metadata=metadata)


def _commit(living: Any, before: Mapping[str, list[str]], after: Mapping[str, list[str]]) -> None:
    """Write the changed rings by compare-and-set; restore the ones written when a later
    one fails, so the call is all or nothing."""
    written: list[str] = []
    for target in after:
        if after[target] == before[target]:
            continue
        ring = getattr(living, TARGETS[target])
        try:
            ok = ring.compare_and_set(before[target], after[target])
        except Exception:
            logger.warning("memory: the %s ring could not be written", target, exc_info=True)
            ok = False
        if not ok:
            for done in reversed(written):
                try:
                    getattr(living, TARGETS[done]).compare_and_set(after[done], before[done])
                except Exception:
                    logger.error("memory: the %s ring could not be restored after a failed write", done)
            raise MemoryToolError("memory_changed_meanwhile",
                                  "the memory changed while this call ran (a forget or another write); "
                                  "read it and try again")
        written.append(target)


def _revert(living: Any, written: Mapping[str, list[str]], original: Mapping[str, list[str]]) -> None:
    """Put back rings a committed write changed, when its record could not be made."""
    for target in written:
        if written[target] != original[target]:
            try:
                getattr(living, TARGETS[target]).compare_and_set(written[target], original[target])
            except Exception:
                logger.error("memory: the %s ring could not be restored after an unrecorded write", target)


def undo(ref: str, *, living: Any, audit: Any, actor: str = "owner", store: UndoStore | None = None) -> dict:
    """Restore the rings a write replaced, while nothing has changed them since."""
    store = UNDO if store is None else store
    entry = store.get(str(ref or ""))
    if entry is None:
        raise MemoryToolError("memory_undo_unknown", "no write with that ref is kept")
    if living is None:
        raise MemoryToolError("memory_disabled", "memory is switched off on this hub")
    with _WRITE_LOCK:
        now = {target: getattr(living, TARGETS[target]).list() for target in TARGETS}
        before = {t: list(entry["before"].get(t, now[t])) for t in TARGETS}
        for target, digest in (entry.get("after_sha256") or {}).items():
            if target in now and _ring_sha(now[target]) != digest:
                raise MemoryToolError("memory_changed_meanwhile",
                                      f"{target} changed after that write; it cannot be undone safely")
        _commit(living, now, before)
        try:
            _record(audit, actor, "memory.undo", "the owner undid a memory write", str(ref),
                    {"ref": str(ref), "targets": sorted(t for t in TARGETS if before[t] != now[t])})
        except BaseException:
            _revert(living, before, now)
            raise
        store.drop(str(ref))
    return {"ok": True, "ref": str(ref), "memory": before["memory"], "user": before["user"]}


# ── the tool ─────────────────────────────────────────────────────────────────

def _record_event(rows: list[dict]) -> None:
    from .observability.tool_events import TOOL_EVENTS
    from .tool_rpc import current_tool_actor

    TOOL_EVENTS.record({
        "event": "memory_updated",
        "tool": TOOL_NAME,
        "agent_id": current_tool_actor(),
        "targets": sorted({row["target"] for row in rows if row["action"] != "unchanged"}),
        "actions": [row["action"] for row in rows],
    })


def _turn_origin() -> str:
    from .action_origin import current_action_origin

    return current_action_origin()


def register_memory_tool(
    server: Any,
    *,
    living: Callable[[], Any],
    audit: Callable[[], Any],
    posture: Callable[[], str] | None = None,
    origin: Callable[[], str] = _turn_origin,
    store: UndoStore | None = None,
) -> str:
    """Expose ``memory`` on a ToolRPC server (ungated, audited, undoable). ``living``
    returns the LivingMemory module, or None when cognition memory is off; ``audit`` the
    intent log; ``posture`` the turn's posture key (only ``operator/owner`` writes);
    ``origin`` the turn's action origin (an untrusted one is refused). Every getter is
    read per call and a getter that fails refuses the call."""
    from .security.taint import is_untrusted_source

    def _living() -> Any:
        from . import safe_mode

        if safe_mode.enabled():
            # H490: no memory reaches a turn in safe mode, through the prompt or this tool.
            safe_mode.note("memory_injection")
            return None
        try:
            return living()
        except Exception:
            logger.warning("memory: the memory module could not be read", exc_info=True)
            return None

    def _refusal() -> dict | None:
        try:
            where = str(posture() if posture is not None else "")
            untrusted = is_untrusted_source(origin())
        except Exception:
            logger.warning("memory: the turn could not be placed; refused", exc_info=True)
            return {"ok": False, "reason": "memory_untrusted_turn", "detail": "this turn cannot write memory"}
        if where != "operator/owner":
            return {"ok": False, "reason": "memory_not_owner",
                    "detail": "only the owner's own turns write memory; say what to remember instead"}
        if untrusted:
            return {"ok": False, "reason": "memory_untrusted_turn",
                    "detail": "this turn read untrusted content (a message from outside, web text, "
                              "a flagged recall), so it cannot write memory; ask the owner to confirm "
                              "in a new message"}
        return None

    def schema_overrides() -> dict:
        return {} if _living() is not None else {"description": OFF_DESCRIPTION}

    async def _handle(args: dict) -> dict:
        from .tool_rpc import current_tool_actor

        unknown = sorted(str(key) for key in args if key not in _ARG_FIELDS)
        if unknown:
            return {"ok": False, "reason": "memory_unknown_field",
                    "detail": f"memory takes operations only, not {unknown[0]!r}"}
        mem = _living()
        if mem is None:
            return {"ok": False, "reason": "memory_disabled", "detail": "memory is switched off on this hub"}
        operations = args.get("operations")
        if not operations:
            return {"ok": True, "memory": mem.core.list(), "user": mem.user_core.list()}
        refusal = _refusal()
        if refusal is not None:
            return refusal
        undo_store = UNDO if store is None else store
        try:
            with _WRITE_LOCK:
                before = {target: getattr(mem, attr).list() for target, attr in TARGETS.items()}
                caps = {target: int(getattr(getattr(mem, attr), "cap", 20)) for target, attr in TARGETS.items()}
                after, rows = plan(operations, before, caps)
                changed = sorted(t for t in TARGETS if after[t] != before[t])
                ref = ""
                if changed:
                    ref = uuid.uuid4().hex[:16]
                    undo_store.put({"ref": ref, "ts": time.time(), "before": {t: before[t] for t in changed},
                                    "after_sha256": {t: _ring_sha(after[t]) for t in changed}})
                    try:
                        _commit(mem, before, after)
                    except BaseException:
                        undo_store.drop(ref)
                        raise
                    try:
                        _record(audit(), current_tool_actor(), "memory.write",
                                "the model changed its long-term memory", ref,
                                {"ref": ref, "targets": changed, "operations": rows})
                    except BaseException:
                        # A write is never kept unrecorded: put the rings back.
                        _revert(mem, after, before)
                        undo_store.drop(ref)
                        raise
        except MemoryToolError as exc:
            return {"ok": False, "reason": exc.reason, "detail": exc.detail}
        except Exception:
            logger.warning("memory: the write failed", exc_info=True)
            return {"ok": False, "reason": "memory_write_failed", "detail": "the memory could not be saved"}
        _record_event(rows)
        reply: dict[str, Any] = {"ok": True, "changed": changed, "memory": after["memory"], "user": after["user"]}
        if ref:
            reply["undo_ref"] = ref
            reply["note"] = "saved; your prompt shows it from the next conversation"
        return reply

    server.register_tool(
        TOOL_NAME,
        _handle,
        gated=False,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        capability_id=CAPABILITY_ID,
        schema_overrides=schema_overrides,
    )
    return TOOL_NAME


__all__ = [
    "ACTIONS", "CAPABILITY_ID", "DESCRIPTION", "INPUT_SCHEMA", "MAX_FACT_CHARS", "MAX_OPERATIONS",
    "MemoryToolError", "OFF_DESCRIPTION", "TARGETS", "TOOL_NAME", "UNDO", "UndoStore", "plan",
    "register_memory_tool", "undo",
]
