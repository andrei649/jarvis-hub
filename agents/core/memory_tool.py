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
  fact (replace or remove one first). H422: each ring also has its character budget
  (Hermes's 2200 for the agent notes, 1375 for the user profile: ``core_block.CHAR_BUDGETS``,
  measured on what the ring holds: ``core_block.stored_chars``, the figure ``GET
  /api/memory`` reports), and a write that would take a ring past it is refused with the
  ring's usage and its limit, so a ring the tool wrote renders whole. That refusal, and a
  full ring's, carries the ring's ``current_entries`` (Hermes's: the entries as the prompt
  shows them, a flagged one as its [BLOCKED] stub, at most :data:`LISTING_MAX_CHARS`), so
  the model can pick what to replace or remove; the prompt's section headers carry each
  ring's usage too (``core_block.usage_figure``). The ring itself
  refuses the other writers the same way (``CoreMemory.put`` raises
  ``CoreMemoryOverBudget`` past the budget, the cap or :data:`MAX_FACT_CHARS`, and nothing
  rotates out; the post-turn review and the daily reflection log it and record it with
  :func:`note_ring_refusal`); the block's own cut stays as the backstop for a ring saved
  before the budget or edited by hand. The budget is checked on the batch's final state,
  so an add listed before the remove that makes room is kept (H423); a turn that keeps
  hitting a full ring gets a terminal refusal after :data:`FULL_ATTEMPTS_PER_TURN` tries,
  so it stops retrying (the refusal sticks: the tool itself refuses every later write of
  that turn; its ``"terminal": true`` is a hint to the model, which the runtime does not
  read);
* a write holds each ring's cross-process file lock (``<ring>.json.lock``, taken by
  ``CoreMemory`` itself, so the post-turn review, the reflection and a forget take it
  too) and rereads the rings from disk under it, so another writer's save is planned
  over, never written back over (H423). The wait runs off the event loop. Every ring
  save records the sha256 of the bytes it wrote beside the ring (``<ring>.json.sha256``)
  under that lock; a file whose bytes no longer match was edited by hand, and the call
  is refused: the file is copied to a named ``.bak`` and, when it reads back exactly, the
  edit becomes the ring's contents (``memory_drift``); an edit that would lose a fact
  (invalid JSON, a repeated fact, over the cap) blocks writes to that ring until it is
  fixed (``memory_drift_unreadable``);
* only the owner's own turns at the operator surface write: the tool is offered to no
  other posture (``tool_profiles.OWNER_OPERATOR_TOOLS``), and a turn that has read
  untrusted content (an inbound message, web content, a tainted recall) is refused, so an
  injected instruction cannot make itself permanent;
* every write appends an intent-log record (``memory.write``: the actor, what changed,
  per target and action — never the text, nor a hash of it, because the intent log
  survives "forget me" and a short fact is guessed back from its hash) carrying an undo
  ref. A write whose record cannot be saved is put back, and the put-back is recorded
  (``memory.write_reverted``): the intent log may keep the failed record and save it with
  its next one. The ring's previous contents are kept under that ref in a purgeable store
  beside the rings (:class:`UndoStore`), so a forget deletes them too. :func:`undo`
  restores a write while nothing has changed since, and is recorded the same way;
  ``POST /api/memory/core/undo`` is the owner's door;
* H422: :func:`store_sizes` says what each ring holds on disk (``GET /api/memory``) and
  :func:`reset` erases one ring or both for good, recorded as ``memory.reset``
  (``POST /api/memory/reset``, ``nerva memory reset``);
* a write leaves a ``memory_updated`` row in the tool trail (targets and actions, never
  text); a call that changes nothing leaves none;
* in safe mode (H490) memory reads as switched off: the tool refuses and says so;
* H422: the owner's own switch, ``memory.core_enabled`` (:data:`SWITCH_SETTING`), takes the
  curated memory out of every prompt and makes this tool refuse, whatever the product
  posture says (the wave-1 postures force ``cognition.memory_enabled`` on, never this row).
  Off, the post-turn review and the daily reflection put nothing in the rings either.
  Only ``POST /api/memory/switch`` (``nerva memory off|on``) writes it; the rings stay on
  disk while it is off.

The prompt's core block is frozen per session (it keeps the prompt cache), so a write
reaches the system prompt at the next session; the tool answers with both rings as they
now are, so the model works from them at once.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from .learning.core_block import CHAR_BUDGETS

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
#: Failed at-capacity attempts one model turn may make before the tool refuses for good.
FULL_ATTEMPTS_PER_TURN = 3
#: Turns whose at-capacity failures are counted; the oldest is forgotten first.
_FULL_TURNS_KEEP = 256
#: How long a write waits for another process's lock on a ring file.
LOCK_TIMEOUT_S = 5.0
#: H422 — the most characters of entries a refusal lists (:func:`current_entries`). A ring
#: the hub keeps (at most 20 facts, each shown in at most 300 characters) always fits whole.
LISTING_MAX_CHARS = 6_000
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
    "recorded and the owner can undo it. Each target has a character budget (memory "
    f"{CHAR_BUDGETS['memory']:,}, user {CHAR_BUDGETS['user']:,}), and your prompt's [core memory] and "
    "[user profile] headers show how full each one was when this conversation's memory was loaded. "
    "A write that would go past the budget, or past a full target's fact limit, is refused with the "
    "target's usage and its current_entries, so keep facts short, and replace or remove stale ones "
    "(merge two related facts into one) before adding."
)
OFF_DESCRIPTION = DESCRIPTION + (" Memory is switched off on this hub (the owner's memory switch, or cognition "
                                  "memory), so every call is refused.")

#: H422 — the owner's switch for the curated memory (the core block in the prompt and this
#: tool): a settings row of its own that no product posture sets, written only by its route.
SWITCH_CATEGORY = "memory"
SWITCH_KEY = "core_enabled"
SWITCH_SETTING = f"{SWITCH_CATEGORY}.{SWITCH_KEY}"


def switched_on(get_setting: Any) -> bool:
    """H422 — the owner's memory switch as the runtime settings hold it. A caller with no
    settings at all (a bare test double) reads the shipped default, on; a settings read that
    fails reads off, so an owner's ``off`` is never lost to an error."""
    if not callable(get_setting):
        return True
    try:
        return get_setting(SWITCH_SETTING, True) is not False
    except Exception:
        logger.warning("memory: the owner's memory switch could not be read; memory stays out", exc_info=True)
        return False


def set_switch(enabled: bool, *, audit: Any, actor: str = "owner") -> dict:
    """H422 — the owner turns the curated memory on or off (Hermes's ``memory off``: the
    stores stay, the prompt stops carrying them). Writes :data:`SWITCH_SETTING` and records
    ``memory.switch`` in the intent log (the new and the old value, never a fact). The
    write stands when the record cannot be saved (an ``off`` must never wait on the log);
    ``audited`` says so. Blocking: the caller runs it off the event loop."""
    from .settings_db import get_value, put_category

    if not isinstance(enabled, bool):
        raise MemoryToolError("memory_bad_switch", "enabled must be true or false")
    was = get_value(SWITCH_CATEGORY, SWITCH_KEY, True) is not False
    put_category(SWITCH_CATEGORY, {SWITCH_KEY: enabled})
    audited = True
    try:
        _record(audit, actor, "memory.switch",
                "the owner switched the curated memory " + ("on" if enabled else "off"), "",
                {"enabled": enabled, "was": was})
    except Exception:
        logger.warning("memory switch: the intent log could not record it", exc_info=True)
        audited = False
    return {"enabled": enabled, "changed": was != enabled, "audited": audited}


class MemoryToolError(ValueError):
    """A refused call: a named reason and a sentence the model can act on."""

    def __init__(self, reason: str, detail: str, info: Mapping[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        #: H422 — fields the refusal carries besides its sentence (a budget's usage).
        self.info = dict(info or {})


# ── the facts ────────────────────────────────────────────────────────────────

def _clean_text(raw: Any, index: int, field: str) -> str:
    from .security.quarantine import strip_format_chars

    if not isinstance(raw, str):
        raise MemoryToolError("memory_bad_text", f"operation {index}: {field} must be text")
    if len(raw) > MAX_FACT_CHARS * 4:
        raise MemoryToolError("memory_text_too_long",
                              f"operation {index}: {field} is over {MAX_FACT_CHARS} characters")
    text = " ".join(raw.split())
    # The invisible characters the scanner deletes before it reads (variation selectors,
    # Hangul fillers, a blank braille cell) could carry a payload no one sees in the panel.
    if (any(unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cn", "Cs") for ch in text)
            or strip_format_chars(text) != text):
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
    # old_text is whitespace-normalised, and so is each fact, as the prompt shows it: a fact
    # another writer saved with a newline or a run of spaces can still be quoted.
    hits = [pos for pos, fact in enumerate(facts) if old_text in " ".join(fact.split())]
    if not hits:
        raise MemoryToolError("memory_no_match", f"operation {index}: no saved fact contains old_text")
    if len(hits) > 1:
        raise MemoryToolError("memory_ambiguous",
                              f"operation {index}: {len(hits)} saved facts contain old_text; quote more of one")
    return hits[0]


def usage(facts: list[str], target: str) -> str:
    """H422 — the characters ring *target* holds against its budget, Hermes's
    ``"1,234/2,200"`` (``core_block.stored_chars``, as ``GET /api/memory`` reports it)."""
    from .learning.core_block import stored_chars

    return f"{stored_chars(facts):,}/{CHAR_BUDGETS[target]:,}"


def current_entries(facts: list[str], target: str) -> dict:
    """H422 — ring *target*'s entries for a refusal that asks the model to make room
    (Hermes's ``current_entries``): in order, as the prompt shows them
    (``core_block.shown_entries``: one line, at most 300 characters, a flagged one as its
    [BLOCKED] stub), scanned with the normalised scanner the tool's own writes pass, so a
    refusal never carries text the prompt keeps out, nor text that would get the result
    fenced and the turn tainted (and with it the very write that makes room refused).
    Bounded: at most :data:`LISTING_MAX_CHARS` characters of entries; when the newest do
    not fit, ``current_entries_omitted`` counts them."""
    from .learning.core_block import shown_entries
    from .security.quarantine import detect_injection_normalized

    listed: list[str] = []
    used = 0
    entries = shown_entries(list(facts), target, detect_injection_normalized)
    for entry in entries:
        if used + len(entry) > LISTING_MAX_CHARS:
            break
        listed.append(entry)
        used += len(entry)
    out: dict[str, Any] = {"current_entries": listed}
    if len(listed) < len(entries):
        out["current_entries_omitted"] = len(entries) - len(listed)
    return out


def _check_budget(target: str, before: list[str], after: list[str], budget: int) -> None:
    """H422 — refuse a final state that takes ring *target* past its character *budget*
    (measured on what the ring holds, ``core_block.stored_chars``). A ring already over it
    (saved before the budget, or edited by hand) may still shrink: only a call that leaves
    it over the budget *and* larger than it was is refused."""
    from .learning.core_block import stored_chars

    now, then = stored_chars(before), stored_chars(after)
    if then <= budget or then <= now:
        return
    raise MemoryToolError(
        "memory_over_budget",
        f"{target} would take {then:,} of its {budget:,} characters after this call (it holds "
        f"{now:,}/{budget:,} now); replace or remove facts first (in this call or before it), or "
        "save a shorter fact; current_entries lists what it holds",
        {"target": target, "usage": f"{now:,}/{budget:,}", "chars": now, "chars_after": then,
         "char_budget": budget, **current_entries(before, target)})


def plan(operations: Any, rings: Mapping[str, list[str]], cap: Mapping[str, int],
         budgets: Mapping[str, int] | None = None) -> tuple[dict, list[dict]]:
    """The rings after *operations*, checked in full before anything is written, and one
    row per applied operation (``action``, ``target``: no digest of the fact, which the
    intent log would keep past a forget). Raises :class:`MemoryToolError`; an add that is
    already saved is recorded as ``unchanged``. H422: *budgets* are the rings' character
    budgets, by target (default ``core_block.CHAR_BUDGETS``)."""
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
                rows.append({"action": "unchanged", "target": target})
                continue
            facts.append(text)
        else:
            pos = _match(facts, old, index)
            if action == "remove":
                facts.pop(pos)
                rows.append({"action": "remove", "target": target})
                continue
            if text != facts[pos] and text in facts:
                raise MemoryToolError("memory_duplicate", f"operation {index}: that fact is already saved")
            facts[pos] = text
        rows.append({"action": action, "target": target})
    # H423: the budget holds for the batch's final state, so an add listed before the
    # remove that makes room for it is not refused.
    for target in sorted(after):
        if len(after[target]) > cap[target]:
            raise MemoryToolError("memory_full",
                                  f"{target} would hold {len(after[target])} facts after this call, over its "
                                  f"{cap[target]}; replace or remove one first (in this call or before it); "
                                  "current_entries lists what it holds",
                                  {"target": target, "entries": len(rings[target]), "cap": cap[target],
                                   "usage": usage(list(rings[target]), target) if target in CHAR_BUDGETS else "",
                                   **current_entries(list(rings[target]), target)})
    budgets = CHAR_BUDGETS if budgets is None else budgets
    for target in sorted(after):
        if target in budgets and after[target] != rings[target]:
            _check_budget(target, list(rings[target]), after[target], int(budgets[target]))
    return after, rows


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ring_sha(facts: list[str]) -> str:
    return _sha(json.dumps(facts, ensure_ascii=False))


def _moved(entry: Mapping, rings: Mapping[str, list[str]]) -> str | None:
    """The first ring that changed after *entry*'s write, or None while undo restores it."""
    for target, digest in (entry.get("after_sha256") or {}).items():
        if target in rings and _ring_sha(rings[target]) != digest:
            return target
    return None


# ── undo ─────────────────────────────────────────────────────────────────────

class UndoStore:
    """The rings as they were before each write, by ref, beside the rings themselves so a
    forget deletes them with the rings (the intent log, which survives it, holds only the
    ref, targets and actions)."""

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

    def recent(self, limit: int = 20, rings: Mapping[str, list[str]] | None = None) -> list[dict]:
        """The newest kept writes: ref, time and targets (never the text). Given the rings as
        they are now, only the writes :func:`undo` would still restore."""
        with self._lock:
            rows = self._load()
        if rings is not None:
            rows = [row for row in rows if _moved(row, rings) is None]
        rows = rows[-max(0, int(limit)):]
        return [{"ref": row.get("ref"), "ts": row.get("ts"), "targets": sorted(row.get("before") or {})}
                for row in reversed(rows)]

    def drop(self, ref: str) -> None:
        from .persistence.json_store import atomic_write_json

        with self._lock:
            rows = self._load()
            kept = [row for row in rows if row.get("ref") != ref]
            if len(kept) != len(rows):
                atomic_write_json(self.path(), kept)

    def clear(self) -> bool:
        """Drop every kept write (a forget): an undo must not write back what it erased.
        True when there was one to drop."""
        from .persistence.json_store import atomic_write_json

        with self._lock:
            if not self._load():
                return False
            atomic_write_json(self.path(), [])
            return True

    def holding(self, target: str) -> int:
        """H422 — how many kept writes hold an earlier copy of ring *target*."""
        with self._lock:
            return sum(1 for row in self._load() if target in (row.get("before") or {}))

    def drop_targets(self, targets: list[str]) -> int:
        """H422 — drop every kept write that holds an earlier copy of one of *targets* (a
        reset): no copy of the erased facts stays here, and none of those writes could be
        undone over the emptied ring anyway. The number dropped."""
        from .persistence.json_store import atomic_write_json

        wanted = set(targets)
        with self._lock:
            rows = self._load()
            kept = [row for row in rows if not wanted & set(row.get("before") or {})]
            if len(kept) != len(rows):
                atomic_write_json(self.path(), kept)
            return len(rows) - len(kept)


UNDO = UndoStore()
_WRITE_LOCK = threading.Lock()


# ── the files: a cross-process lock, a reread, and drift (H423) ──────────────

@contextmanager
def _ring_locks(living: Any) -> Iterator[None]:
    """Hold every ring's file lock (CoreMemory.locked, the lock every writer of the ring
    takes: the review, the reflection and a forget too), in path order so two writers
    never wait on each other crosswise; released whatever happens."""
    from .cognition.memory import CoreMemoryLocked

    rings = []
    for attr in TARGETS.values():
        ring = getattr(living, attr)
        lock_path = ring.lock_path() if callable(getattr(ring, "lock_path", None)) else None
        if lock_path is not None and callable(getattr(ring, "locked", None)):
            rings.append((str(lock_path), ring))
    with ExitStack() as stack:
        try:
            for _, ring in sorted(rings, key=lambda pair: pair[0]):
                stack.enter_context(ring.locked(timeout=LOCK_TIMEOUT_S))
        except CoreMemoryLocked:
            raise MemoryToolError("memory_locked",
                                  "another Nerva process is writing memory; try again in a moment") from None
        yield


def _settle(living: Any) -> None:
    """Under the ring locks: reread every ring from its file, so a plan starts from what
    is on disk. A hand edit refuses the call: it is copied to a ``.bak`` and, when it
    reads back exactly, taken as the ring (``memory_drift``); when it cannot be taken
    without dropping a fact (invalid JSON, a repeated fact, over the cap) nothing is
    written to that ring until the owner fixes the file (``memory_drift_unreadable``)."""
    from .cognition.memory import CoreMemoryDrift

    drifted: list[str] = []
    unreadable: list[str] = []
    for target, attr in TARGETS.items():
        ring = getattr(living, attr)
        if callable(getattr(ring, "sync_from_disk", None)):
            try:
                bak = ring.sync_from_disk()
            except CoreMemoryDrift as exc:
                where = f"; a copy is kept at {exc.bak}" if exc.bak else ""
                unreadable.append(f"{exc.path.name} ({target}) {exc.problem}{where}")
                continue
            if bak is not None:
                drifted.append(f"{bak} ({target})")
        elif callable(getattr(ring, "reload", None)):
            ring.reload()
    if unreadable:
        raise MemoryToolError("memory_drift_unreadable",
                              "a memory file was edited outside Nerva and cannot be read back without "
                              f"dropping facts: {'; '.join(unreadable)}; nothing is written to it until "
                              "the owner fixes the file, so tell the owner")
    if drifted:
        raise MemoryToolError("memory_drift",
                              "a memory file was edited outside Nerva, so nothing was written over it; "
                              f"the edit is kept as it is and copied to {'; '.join(drifted)}; "
                              "read memory again and retry")


def _read_rings(living: Any) -> None:
    """A read's reread (H423 review): each ring strictly, under its lock, so a hand edit
    that cannot be read back is reported (``memory_drift_unreadable``) instead of read as
    an empty ring; one that reads back exactly is taken, as a write would. A ring whose
    lock stays held is read without it (every save is atomic) and just as strictly: a file
    that does not read back exactly is reported the same way and the ring keeps its last
    good facts, never a lenient parse (H423 review)."""
    from .cognition.memory import CoreMemoryDrift, CoreMemoryLocked

    unreadable: list[str] = []
    for target, attr in TARGETS.items():
        ring = getattr(living, attr)
        if callable(getattr(ring, "sync_from_disk", None)):
            try:
                ring.sync_from_disk()
                continue
            except CoreMemoryDrift as exc:
                where = f"; a copy is kept at {exc.bak}" if exc.bak else ""
                unreadable.append(f"{exc.path.name} ({target}) {exc.problem}{where}")
                continue
            except CoreMemoryLocked:
                problem = ring.adopt_without_lock()
                if problem:
                    unreadable.append(f"{ring.path.name} ({target}) {problem}")
                continue
        if callable(getattr(ring, "reload", None)):
            ring.reload()
    if unreadable:
        raise MemoryToolError("memory_drift_unreadable",
                              "a memory file was edited outside Nerva and cannot be read back without "
                              f"dropping facts: {'; '.join(unreadable)}; tell the owner to fix the file")


def _record(audit: Any, actor: str, action: str, why: str, ref: str, metadata: dict) -> None:
    """One intent-log record, or raise: a write is never made unrecorded."""
    if audit is None or not callable(getattr(audit, "record", None)):
        raise MemoryToolError("memory_audit_unavailable",
                              "memory writes are recorded in the intent log, which is not available")
    audit.record(actor=actor, action=action, why=why, cause=ref, metadata=metadata)


def note_ring_refusal(audit: Any, actor: str, refused: Any) -> bool:
    """H422 — a background writer (the post-turn review, a /refine, the daily reflection)
    that a curated ring refused (``CoreMemoryOverBudget``: past its character budget, its
    cap or :data:`MAX_FACT_CHARS`). Logged with the ring's usage and limit, and recorded in
    the intent log as ``memory.write_refused`` (the ring, the limit and the sizes: never
    the fact, nor a hash of it). Best effort, since nothing was written: True when the
    record was saved."""
    logger.warning("memory: a %s fact was not kept: %s", actor, refused)
    if audit is None or not callable(getattr(audit, "record", None)):
        return False
    try:
        audit.record(actor=actor, action="memory.write_refused", why=str(refused), cause="",
                     metadata=refused.metadata())
    except Exception:
        logger.warning("memory: the refusal of a %s fact could not be recorded", actor, exc_info=True)
        return False
    return True


def _record_put_back(audit: Any, actor: str, action: str, ref: str, targets: list[str]) -> None:
    """Record that a change whose record failed was put back. The intent log appends a
    record before it saves it, so a failed save can still reach the disk with the next
    record; this one then follows it. Best effort: the caller raises the failure anyway."""
    if audit is None or not callable(getattr(audit, "record", None)):
        return
    try:
        audit.record(actor=actor, action=action, why="its record could not be saved, so it was put back",
                     cause=ref, metadata={"ref": ref, "targets": targets})
    except Exception:
        logger.warning("memory: the put-back of %s could not be recorded", ref, exc_info=True)


def _commit(living: Any, before: Mapping[str, list[str]], after: Mapping[str, list[str]]) -> None:
    """Write the changed rings by compare-and-set; restore the ones written when a later
    one fails, so the call is all or nothing."""
    from .cognition.memory import CoreMemoryDrift

    written: list[str] = []
    for target in after:
        if after[target] == before[target]:
            continue
        ring = getattr(living, TARGETS[target])
        saved = True
        try:
            ok = ring.compare_and_set(before[target], after[target])
        except CoreMemoryDrift as exc:
            # Hand-edited after the reread (an editor takes no lock): nothing written over it.
            _revert(living, {done: after[done] for done in reversed(written)}, before)
            raise MemoryToolError("memory_drift",
                                  f"{exc}; nothing was written over it; read memory again and retry") from None
        except Exception:
            logger.warning("memory: the %s ring could not be written", target, exc_info=True)
            ok = saved = False
        if not ok:
            _revert(living, {done: after[done] for done in reversed(written)}, before)
            if not saved:
                raise MemoryToolError("memory_write_failed", "the memory could not be saved")
            raise MemoryToolError("memory_changed_meanwhile",
                                  "the memory changed while this call ran (a forget or another write); "
                                  "read it and try again")
        written.append(target)


def _revert(living: Any, written: Mapping[str, list[str]], original: Mapping[str, list[str]]) -> list[str]:
    """Put back rings a write changed, when the call cannot keep it. The rings actually put
    back, sorted; a ring that could not be (another writer moved it in between, or it
    cannot be saved) is logged and its write stays."""
    restored: list[str] = []
    for target in written:
        if written[target] == original[target]:
            continue
        try:
            ok = getattr(living, TARGETS[target]).compare_and_set(written[target], original[target])
        except Exception:
            ok = False
        if ok:
            restored.append(target)
        else:
            logger.error("memory: the %s ring could not be put back; the write it holds stays", target)
    return sorted(restored)


def _write_recorded(living: Any, before: Mapping[str, list[str]], after: Mapping[str, list[str]],
                    rows: list[dict], *, sink: Any, actor: str, undo_store: UndoStore, why: str) -> str:
    """Under :data:`_WRITE_LOCK` and the ring locks, after :func:`_settle`: keep the changed
    rings' previous contents under a new undo ref, write the rings by compare-and-set, and
    record the write in the intent log (``memory.write``: the ref, the targets and one row
    per operation, never the text). A write whose record cannot be saved is put back. The
    undo ref. Every writer of a memory *write* goes through here: the model's ``memory``
    tool and the owner's change of one fact (:func:`owner_change`)."""
    changed = sorted(t for t in TARGETS if after[t] != before[t])
    ref = uuid.uuid4().hex[:16]
    undo_store.put({"ref": ref, "ts": time.time(), "before": {t: before[t] for t in changed},
                    "after_sha256": {t: _ring_sha(after[t]) for t in changed}})
    try:
        _commit(living, before, after)
    except BaseException:
        undo_store.drop(ref)
        raise
    try:
        _record(sink, actor, "memory.write", why, ref, {"ref": ref, "targets": changed, "operations": rows})
    except BaseException:
        # A write is never kept unrecorded: put the rings back.
        restored = _revert(living, after, before)
        if restored:
            _record_put_back(sink, actor, "memory.write_reverted", ref, restored)
        undo_store.drop(ref)
        raise
    return ref


def owner_change(living: Any, target: str, fact: str, text: str | None = None, *, audit: Any,
                 actor: str = "owner", store: UndoStore | None = None) -> dict:
    """H046 — the owner replaces (*text*) or removes (*text* None) the one fact of ring
    *target* that is exactly *fact* (``nerva journey edit|delete``, the HUD's TODAY card),
    held to every rule the model's own ``memory`` write is: the ring locks and the reread
    first (a hand edit refuses, ``memory_drift``), the new text one clean line of at most
    :data:`MAX_FACT_CHARS` characters scanned for injection, no duplicate, the ring's
    character budget, compare-and-set, an undo ref (``POST /api/memory/core/undo`` puts it
    back) and an intent-log record (``memory.write``, never the text). The fact is matched
    whole, never as a substring, so the fact the owner picked is the one changed. Raises
    :class:`MemoryToolError` (``memory_no_match`` when that fact is no longer saved). Runs
    in a worker thread: it waits for the ring files' locks."""
    if target not in TARGETS:
        raise MemoryToolError("memory_bad_target", f"target is one of {', '.join(TARGETS)}")
    if living is None:
        raise MemoryToolError("memory_unavailable", "this hub has no long-term memory module")
    store = UNDO if store is None else store
    with _WRITE_LOCK, _ring_locks(living):
        _settle(living)
        before = {t: getattr(living, attr).list() for t, attr in TARGETS.items()}
        facts = before[target]
        if fact not in facts:
            raise MemoryToolError("memory_no_match", f"that fact is no longer in the {STORE_LABELS[target]}; "
                                  "list it again")
        after = {t: list(v) for t, v in before.items()}
        position = facts.index(fact)
        if text is None:
            after[target].pop(position)
            rows = [{"action": "remove", "target": target}]
        else:
            new = _clean_text(text, 1, "text")
            _scan(new, 1)
            if new == fact:
                return {"ok": True, "changed": [], "target": target, "fact": fact}
            if new in facts:
                raise MemoryToolError("memory_duplicate", "that fact is already saved")
            after[target][position] = new
            rows = [{"action": "replace", "target": target}]
            if target in CHAR_BUDGETS:
                _check_budget(target, facts, after[target], int(CHAR_BUDGETS[target]))
        ref = _write_recorded(living, before, after, rows, sink=audit, actor=actor, undo_store=store,
                              why="the owner changed its long-term memory")
    return {"ok": True, "changed": [target], "target": target, "fact": None if text is None else after[target][position],
            "undo_ref": ref, "usage": usage(after[target], target)}


def undo(ref: str, *, living: Any, audit: Any, actor: str = "owner", store: UndoStore | None = None) -> dict:
    """Restore the rings a write replaced, while nothing has changed them since."""
    store = UNDO if store is None else store
    entry = store.get(str(ref or ""))
    if entry is None:
        raise MemoryToolError("memory_undo_unknown", "no write with that ref is kept")
    if living is None:
        raise MemoryToolError("memory_disabled", "memory is switched off on this hub")
    with _WRITE_LOCK, _ring_locks(living):
        _settle(living)
        now = {target: getattr(living, TARGETS[target]).list() for target in TARGETS}
        before = {t: list(entry["before"].get(t, now[t])) for t in TARGETS}
        moved = _moved(entry, now)
        if moved is not None:
            raise MemoryToolError("memory_changed_meanwhile",
                                  f"{moved} changed after that write; it cannot be undone safely")
        _commit(living, now, before)
        targets = sorted(t for t in TARGETS if before[t] != now[t])
        try:
            _record(audit, actor, "memory.undo", "the owner undid a memory write", str(ref),
                    {"ref": str(ref), "targets": targets})
        except BaseException:
            restored = _revert(living, before, now)
            if restored:
                _record_put_back(audit, actor, "memory.undo_reverted", str(ref), restored)
            raise
        store.drop(str(ref))
    return {"ok": True, "ref": str(ref), "memory": before["memory"], "user": before["user"]}


# ── H422: what the owner can see and erase ───────────────────────────────────

#: A reset's ``target`` → the rings it erases (Hermes's ``--target {all,memory,user}``).
RESET_TARGETS: dict[str, tuple[str, ...]] = {"all": ("memory", "user"), "memory": ("memory",), "user": ("user",)}
#: The word ``POST /api/memory/reset`` must carry, as ``POST /api/admin/forget`` needs ``FORGET``.
RESET_CONFIRM = "RESET"
#: Each ring in the owner's words.
STORE_LABELS: dict[str, str] = {"memory": "agent notes", "user": "user profile"}


def reset_targets(target: Any) -> tuple[str, ...]:
    """The rings *target* names; :class:`MemoryToolError` for anything else."""
    rings = RESET_TARGETS.get(target.strip().lower()) if isinstance(target, str) else None
    if rings is None:
        raise MemoryToolError("memory_bad_target", "target must be all, memory, or user")
    return rings


def _size(path: Any) -> int:
    try:
        return int(path.stat().st_size) if path is not None else 0
    except OSError:
        return 0


def store_sizes(living: Any, store: UndoStore | None = None) -> dict:
    """H422 — what a reset of each ring would erase, by target: its file and the bytes it
    holds on disk (0 when there is none, as Hermes's ``builtin_files``), its entries and
    cap, the hand-edit ``.bak`` copies kept beside it, and the kept writes that hold an
    earlier copy of it (a reset drops those too). Read-only; reread the rings first."""
    store = UNDO if store is None else store
    out: dict[str, dict] = {}
    for target, attr in TARGETS.items():
        ring = getattr(living, attr, None)
        path = getattr(ring, "path", None)
        copies = sorted(path.parent.glob(f"{path.name}.*.bak")) if isinstance(path, Path) else []
        out[target] = {
            "label": STORE_LABELS[target],
            "file": path.name if isinstance(path, Path) else None,
            "bytes": _size(path) if isinstance(path, Path) else 0,
            "entries": len(ring.list()) if callable(getattr(ring, "list", None)) else 0,
            "cap": int(getattr(ring, "cap", 0) or 0),
            "copies": len(copies),
            "copies_bytes": sum(_size(copy) for copy in copies),
            "undo_writes": store.holding(target),
        }
    return out


def reset(target: str, *, living: Any, audit: Any, actor: str = "owner", store: UndoStore | None = None) -> dict:
    """H422 — the owner erases the agent's notes, the user profile, or both (Hermes's
    ``memory reset``). Permanent, with no undo: each ring is emptied by its forget path
    (``CoreMemory.clear``: under the ring's file lock, its hand-edit ``.bak`` copies
    deleted too) and every kept write holding an earlier copy of it is dropped, so no copy
    of the erased facts stays beside the rings. Recorded in the intent log as
    ``memory.reset`` (targets and counts, never text); with no intent log nothing is
    erased. A ring that cannot be erased (its lock stays held, its file cannot be saved)
    is named in ``not_erased`` and ``ok`` is False; the others are erased.

    The prompt's frozen block is left alone: a conversation under way keeps its snapshot
    (the prefix cache), and the next one starts without the erased facts."""
    rings = reset_targets(target)
    if living is None:
        raise MemoryToolError("memory_unavailable", "this hub has no long-term memory module")
    if audit is None or not callable(getattr(audit, "record", None)):
        raise MemoryToolError("memory_audit_unavailable",
                              "a memory reset is recorded in the intent log, which is not available; "
                              "nothing was erased")
    store = UNDO if store is None else store
    erased: dict[str, int] = {}
    not_erased: list[str] = []
    with _WRITE_LOCK:
        for ring in rings:
            try:
                erased[ring] = int(getattr(living, TARGETS[ring]).clear())
            except Exception:
                logger.warning("memory reset: the %s ring could not be erased", ring, exc_info=True)
                not_erased.append(ring)
        dropped = store.drop_targets(sorted(erased))
    audited = True
    try:
        _record(audit, actor, "memory.reset", "the owner erased long-term memory", "",
                {"targets": sorted(erased), "erased": erased, "not_erased": not_erased,
                 "undo_dropped": dropped})
    except Exception:
        # The facts are gone either way (the owner asked for that); the reply says so.
        logger.warning("memory reset: the intent log could not record it", exc_info=True)
        audited = False
    return {"ok": not not_erased, "targets": list(rings), "erased": erased, "not_erased": not_erased,
            "undo_dropped": dropped, "audited": audited}


# ── the tool ─────────────────────────────────────────────────────────────────

def _record_event(rows: list[dict], changed: list[str]) -> None:
    from .observability.tool_events import TOOL_EVENTS
    from .tool_rpc import current_tool_actor

    TOOL_EVENTS.record({
        "event": "memory_updated",
        "tool": TOOL_NAME,
        "agent_id": current_tool_actor(),
        "targets": changed,
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
    switch: Callable[[], bool] | None = None,
) -> str:
    """Expose ``memory`` on a ToolRPC server (ungated, audited, undoable). ``living``
    returns the LivingMemory module, or None when cognition memory is off; ``audit`` the
    intent log; ``posture`` the turn's posture key (only ``operator/owner`` writes);
    ``origin`` the turn's action origin (an untrusted one is refused); ``switch`` the
    owner's memory switch (H422, :func:`switched_on`): off, the tool reads as switched off,
    whatever cognition memory says. Every getter is read per call and a getter that fails
    refuses the call."""
    from .security.taint import is_untrusted_source

    def _living() -> Any:
        from . import safe_mode

        if safe_mode.enabled():
            # H490: no memory reaches a turn in safe mode, through the prompt or this tool.
            safe_mode.note("memory_injection")
            return None
        if switch is not None:
            try:
                on = switch() is True
            except Exception:
                logger.warning("memory: the owner's memory switch could not be read; refused", exc_info=True)
                on = False
            if not on:
                return None              # H422: the owner switched the curated memory off
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

    # H423: failed at-capacity attempts per model turn; a turn that reaches the cap is
    # refused for good, so a model that cannot make room stops retrying. A script's calls
    # carry no turn and are not counted.
    full_turns: OrderedDict[str, int] = OrderedDict()
    full_lock = threading.Lock()

    def _terminal() -> dict:
        return {"ok": False, "reason": "memory_full_terminal", "terminal": True,
                "detail": f"memory stayed full through {FULL_ATTEMPTS_PER_TURN} attempts this turn; stop "
                          "writing memory now and tell the owner what you could not save"}

    def _full_capped(turn: str | None) -> bool:
        if not turn:
            return False
        with full_lock:
            return full_turns.get(turn, 0) >= FULL_ATTEMPTS_PER_TURN

    def _count_full(turn: str | None) -> bool:
        """Count one at-capacity refusal; True when the turn has now reached the cap."""
        if not turn:
            return False
        with full_lock:
            full_turns[turn] = full_turns.get(turn, 0) + 1
            full_turns.move_to_end(turn)
            while len(full_turns) > _FULL_TURNS_KEEP:
                full_turns.popitem(last=False)
            return full_turns[turn] >= FULL_ATTEMPTS_PER_TURN

    async def _handle(args: dict) -> dict:
        from .tool_rpc import current_tool_actor, current_tool_turn

        unknown = sorted(str(key) for key in args if key not in _ARG_FIELDS)
        if unknown:
            return {"ok": False, "reason": "memory_unknown_field",
                    "detail": f"memory takes operations only, not {unknown[0]!r}"}
        mem = _living()
        if mem is None:
            return {"ok": False, "reason": "memory_disabled", "detail": "memory is switched off on this hub"}
        operations = args.get("operations")
        if not operations:
            try:
                # A read rereads the files too (another process may have written them), in a
                # worker thread since that waits for the ring locks.
                await asyncio.to_thread(_read_rings, mem)
            except MemoryToolError as exc:
                return {"ok": False, "reason": exc.reason, "detail": exc.detail}
            return {"ok": True, "memory": mem.core.list(), "user": mem.user_core.list()}
        refusal = _refusal()
        if refusal is not None:
            return refusal
        turn = current_tool_turn()
        if _full_capped(turn):
            return _terminal()
        undo_store = UNDO if store is None else store

        def _write() -> tuple[dict, list[dict], list[str], str]:
            # Runs in a worker thread: waiting for another writer's ring lock (up to
            # LOCK_TIMEOUT_S) must not stall the event loop (H423).
            with _WRITE_LOCK, _ring_locks(mem):
                _settle(mem)
                before = {target: getattr(mem, attr).list() for target, attr in TARGETS.items()}
                caps = {target: int(getattr(getattr(mem, attr), "cap", 20)) for target, attr in TARGETS.items()}
                after, rows = plan(operations, before, caps)
                changed = sorted(t for t in TARGETS if after[t] != before[t])
                ref = ""
                if changed:
                    ref = _write_recorded(mem, before, after, rows, sink=audit(), actor=current_tool_actor(),
                                          undo_store=undo_store, why="the model changed its long-term memory")
                return after, rows, changed, ref

        try:
            after, rows, changed, ref = await asyncio.to_thread(_write)
        except MemoryToolError as exc:
            # H422: a ring over its character budget is as full as one at its fact cap.
            if exc.reason in ("memory_full", "memory_over_budget") and _count_full(turn):
                return _terminal()
            return {"ok": False, "reason": exc.reason, "detail": exc.detail, **exc.info}
        except Exception:
            logger.warning("memory: the write failed", exc_info=True)
            return {"ok": False, "reason": "memory_write_failed", "detail": "the memory could not be saved"}
        if changed:
            _record_event(rows, changed)
        reply: dict[str, Any] = {"ok": True, "changed": changed, "memory": after["memory"], "user": after["user"],
                                 "usage": {target: usage(after[target], target) for target in TARGETS}}
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
        # H399 — a write to the owner's memory file; never overlapped with another call.
        parallel_safe=False,
    )
    return TOOL_NAME


__all__ = [
    "ACTIONS", "CAPABILITY_ID", "DESCRIPTION", "FULL_ATTEMPTS_PER_TURN", "INPUT_SCHEMA", "LISTING_MAX_CHARS",
    "LOCK_TIMEOUT_S", "MAX_FACT_CHARS", "MAX_OPERATIONS",
    "MemoryToolError", "OFF_DESCRIPTION", "RESET_CONFIRM", "RESET_TARGETS", "STORE_LABELS", "SWITCH_CATEGORY",
    "SWITCH_KEY", "SWITCH_SETTING", "TARGETS", "TOOL_NAME", "UNDO", "UndoStore", "owner_change", "plan",
    "register_memory_tool",
    "current_entries", "note_ring_refusal", "reset", "reset_targets", "set_switch", "store_sizes", "switched_on",
    "undo", "usage",
]
