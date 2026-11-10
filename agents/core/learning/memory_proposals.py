"""memory_proposals.py — H443: memory writes the post-turn review holds for the owner.

Hermes's ``memory.write_approval``: with the gate on, the background review's memory
writes are staged instead of committed, and land only when the owner says so. Here a
held write is one **proposal**: the review pass's facts (``{"target": "user"|"memory",
"text": …}`` rows, the same two rings the model's ``memory`` tool writes), kept in a
durable ledger (``<data>/learning/memory_proposals.json``) with **one** approval card in
the action-approval queue bound to it. The card names counts only, never a fact: the
queue's list is readable with a user token, the ledger's text only by an admin
(``GET /api/memory/proposals``).

One gate decides a proposal, whichever door the decision came through
(``/api/actions/{id}/decide``, ``/api/memory/proposals/{id}/decide``, a group reject, a
card that expired): :meth:`MemoryProposalStore.settle` reads the **card's own status from
the queue** under one lock and

* ``approved``  → the proposal is marked ``applying`` (saved), each fact is put in its
  ring and its outcome saved, then the proposal is ``applied``. A ring put is idempotent
  (a fact already in the ring changes nothing), so a hub that stopped between the two
  saves resumes the same proposal at its next start and no fact lands twice;
* ``rejected`` / ``expired`` → the proposal is closed and nothing is written;
* a card that is gone (the queue was reset) → the proposal gets a new card;
* pending longer than :data:`PENDING_TTL_S` → expired, its card withdrawn.

The same ledger keeps the **clean conversations**: the sessions a review may write memory
from on its own. A reply written from untrusted content (a message from outside, a
guest's turn, web text, a flagged recall, an attached file) stays in the conversation and
a later review replays it, so what is tracked is the opposite of a taint mark — a positive
list, which fails closed:

* a session is **admitted** (with the time) only at the start of a turn that is not
  untrusted and finds the conversation empty: it was watched from its first turn;
* any untrusted turn **revokes** it, before that turn's content joins the conversation
  where the turn is untrusted from its start, and before its reply is stored otherwise;
* a review treats the conversation as clean only while its session is on the list **and**
  every turn it replays is dated at or after the admission (a turn restored from disk, or
  with no readable time, predates the watch).

Everything else is not clean, with nothing to remember about it: a conversation older
than the ledger, one copied or continued from another (``/undo``, a continuation, a
rewind into a new session), one whose admission was dropped at :data:`MAX_CLEAN_SESSIONS`,
and every conversation when the ledger file is missing or cannot be read (an unreadable
file is moved aside, ``.unreadable-<time>``, and an empty ledger started). A conversation
that is not clean never becomes clean again unless it is emptied. Its reviews hold their
memory writes for the owner.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..persistence import JsonStore

logger = logging.getLogger("jarvis.learning.memory_proposals")

CARD_TOOL = "memory.write_proposal"
STATUS_PENDING = "pending"
STATUS_APPLYING = "applying"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"
#: The review's names for the two rings are the memory tool's (``memory_tool.TARGETS``).
TARGETS: dict[str, str] = {"memory": "core", "user": "user_core"}
TARGET_LABELS: dict[str, str] = {"memory": "agent notes", "user": "user profile"}
#: Proposals waiting for the owner at once; past it a new one is refused (never an old
#: one dropped to make room).
MAX_PENDING = 50
#: Decided proposals kept for the owner to read back; the oldest go first.
MAX_DECIDED = 200
MAX_OPERATIONS = 12
#: A proposal nobody decided is closed after this long.
PENDING_TTL_S = 14 * 86400.0
#: Clean conversations tracked at once; the oldest admission is dropped first (and that
#: conversation is then not clean).
MAX_CLEAN_SESSIONS = 4096
SETTING_CATEGORY, SETTING_KEY = "memory", "write_approval"
SETTING = f"{SETTING_CATEGORY}.{SETTING_KEY}"

#: An op outcome that will not change on a retry.
_FINAL = frozenset({"added", "duplicate", "blocked", "refused", "memory_off"})


def write_approval_required() -> bool:
    """Whether ``memory.write_approval`` is on, read from the settings store itself (not a
    cached copy), failing closed: only a stored ``false`` — or no row, the shipped default
    — is off. A store that cannot be read, or a value that is not a boolean, is on.
    Blocking (one SQLite read): callers run it off the event loop."""
    try:
        from ..settings_db import read_setting

        found, value = read_setting(SETTING_CATEGORY, SETTING_KEY)
    except Exception:
        logger.warning("memory.write_approval could not be read; memory writes are held for approval",
                       exc_info=True)
        return True
    if not found:
        return False
    return value is not False


def set_write_approval(enabled: bool, *, audit: Any, actor: str = "owner") -> dict:
    """The owner turns the gate on or off (``POST /api/memory/approval``). Turning it on
    stands even when the intent log cannot record it; turning it **off** lets the review
    write on its own again, so it is recorded first and refused when it cannot be.
    Blocking: run off the event loop."""
    from ..settings_db import put_category, read_setting

    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    found, value = read_setting(SETTING_CATEGORY, SETTING_KEY)
    was = found and value is not False
    metadata = {"enabled": enabled, "was": was}
    why = "the owner switched memory write approval " + ("on" if enabled else "off")
    recorder = getattr(audit, "record", None)
    audited = False
    if not enabled:
        if not callable(recorder):
            raise RuntimeError("the intent log is not available; the gate stays as it is")
        recorder(actor=actor, action="memory.write_approval", why=why, cause="", metadata=metadata)
        audited = True
    put_category(SETTING_CATEGORY, {SETTING_KEY: enabled})
    if enabled and callable(recorder):
        try:
            recorder(actor=actor, action="memory.write_approval", why=why, cause="", metadata=metadata)
            audited = True
        except Exception:
            logger.warning("memory write approval: the intent log could not record it", exc_info=True)
    return {"enabled": enabled, "changed": was != enabled, "audited": audited}


def clean_operations(operations: Any) -> list[dict]:
    """The proposal's rows as they are stored: a known target and one line of text each,
    no repeats. Anything else is dropped; an empty list means nothing to propose."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for op in operations if isinstance(operations, (list, tuple)) else []:
        if not isinstance(op, dict):
            continue
        target = str(op.get("target") or "")
        text = " ".join(str(op.get("text") or "").split())
        if target not in TARGETS or not text or (target, text) in seen:
            continue
        seen.add((target, text))
        out.append({"target": target, "text": text})
        if len(out) >= MAX_OPERATIONS:
            break
    return out


def _turn_time(value: Any) -> float | None:
    """A stored turn's ISO timestamp as epoch seconds, or None when it cannot be read."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


class MemoryProposalStore(JsonStore):
    """The ledger of held memory writes and of the conversations watched clean from their
    first turn."""

    def __init__(self, path: str | Path | None = None, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._apply_lock = threading.Lock()
        self._card_lock = threading.Lock()
        self._items: dict[str, dict] = {}
        self._clean: dict[str, float] = {}
        #: The clean list as an admission is saving it (shown only once it is on disk),
        #: and the sessions a revocation is taking off it meanwhile.
        self._saving_clean: dict[str, float] | None = None
        self._revoking: set[str] = set()
        super().__init__(path)

    # ── persistence ──────────────────────────────────────────────────────────

    def _serialize(self):
        clean = self._saving_clean if self._saving_clean is not None else self._clean
        return {"proposals": self._items, "clean_sessions": clean}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        items = raw.get("proposals")
        self._items = {str(k): v for k, v in items.items() if isinstance(v, dict)} if isinstance(items, dict) else {}
        clean = raw.get("clean_sessions")
        self._clean = ({str(k): float(v) for k, v in clean.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)}
                       if isinstance(clean, dict) else {})

    def _load(self) -> None:
        import json

        if self.path is None or not self.path.exists():
            # No ledger: nothing is held and no conversation is known to be clean.
            self._deserialize({})
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("proposals"), dict) \
                    or not isinstance(raw.get("clean_sessions"), dict):
                raise ValueError("not a memory proposal ledger")
        except Exception:
            aside = self.path.with_name(f"{self.path.name}.unreadable-{int(self._now())}")
            logger.warning("memory proposals: %s cannot be read; moved to %s and an empty ledger started "
                           "(no earlier conversation is treated as clean)", self.path, aside.name, exc_info=True)
            try:
                self.path.replace(aside)
            except OSError:
                logger.warning("memory proposals: the unreadable ledger could not be moved aside", exc_info=True)
            self._deserialize({})
            return
        self._deserialize(raw)

    # ── the conversations watched clean from their first turn ────────────────

    def admit(self, session_id: str) -> bool:
        """Put *session_id* on the clean list, dated now: the caller is a turn that is not
        untrusted and found the conversation empty. Saved before it returns; True when it
        is new. An admission that cannot be saved raises and is not kept (the session is
        then not clean, here or after a restart)."""
        sid = str(session_id or "")
        if not sid:
            return False
        with self._lock:
            if sid in self._clean:
                return False
            # Saved first, shown after: a reader (which takes no lock, see is_clean) never
            # sees an admission the ledger does not hold.
            candidate = {**self._clean, sid: self._now()}
            while len(candidate) > MAX_CLEAN_SESSIONS:
                candidate.pop(min(candidate, key=candidate.__getitem__))
            current, self._saving_clean = self._clean, candidate
            try:
                self._save()
            finally:
                self._saving_clean = None
            if sid in self._revoking:
                # A revocation of this session ran while this was saving: it wins, and
                # saves next (it is waiting for this lock).
                return False
            if self._clean is current:
                self._clean = candidate
            else:
                # Another session was revoked meanwhile (its save is next): keep that.
                self._clean = {**self._clean, sid: candidate[sid]}
            return True

    def revoke(self, session_id: str) -> bool:
        """Take *session_id* off the clean list: a turn of it is untrusted. Saved before
        it returns; True when it was on the list. A revocation that cannot be saved raises
        and still holds in this process (the stricter side), and is written with the
        ledger's next save."""
        sid = str(session_id or "")
        saving = self._saving_clean
        if sid not in self._clean and not (saving is not None and sid in saving):
            return False
        # Shown first (the stricter side holds at once, with no lock a turn would wait
        # on), saved after. An admission of the same session that is being saved right
        # now is told not to show itself.
        self._revoking.add(sid)
        self._clean = {key: value for key, value in self._clean.items() if key != sid}
        try:
            with self._lock:
                if sid in self._clean:
                    self._clean = {key: value for key, value in self._clean.items() if key != sid}
                self._save()
                return True
        finally:
            self._revoking.discard(sid)

    def is_clean(self, session_id: str) -> bool:
        """Read on the event loop at every turn: one dict lookup, no lock (a save in
        another thread holds the store's lock across its disk write)."""
        return str(session_id or "") in self._clean

    def session_clean(self, session_id: str, turns: Any = None) -> bool:
        """Whether a review may treat *session_id*'s conversation as clean: it is on the
        list and every one of *turns* (history rows with ``timestamp``) is dated at or
        after its admission. A turn with no readable time is not. Takes no lock."""
        admitted = self._clean.get(str(session_id or ""))
        if admitted is None:
            return False
        for turn in turns or []:
            stamp = _turn_time(turn.get("timestamp") if isinstance(turn, dict) else None)
            if stamp is None or stamp < admitted:
                return False
        return True

    # ── proposals ────────────────────────────────────────────────────────────

    def propose(self, operations: Any, *, origin: str, session_id: str, reason: str,
                tainted: bool = False) -> dict | None:
        """Record a held write. Returns the record (an identical pending one when there is
        one), or None when there is nothing to hold or :data:`MAX_PENDING` are waiting.
        Saved before it returns; a record that cannot be saved raises and is not kept."""
        ops = clean_operations(operations)
        if not ops:
            return None
        with self._lock:
            pending = [rec for rec in self._items.values() if rec.get("status") == STATUS_PENDING]
            for rec in pending:
                if [(o.get("target"), o.get("text")) for o in rec.get("operations") or []] == \
                        [(o["target"], o["text"]) for o in ops]:
                    return _copy(rec)
            if len(pending) >= MAX_PENDING:
                return None
            pid = f"mp-{uuid.uuid4().hex[:12]}"
            rec = {"id": pid, "origin": str(origin or "background_review")[:64],
                   "session_id": str(session_id or "")[:200], "reason": str(reason or "")[:64],
                   "tainted": bool(tainted), "operations": ops, "status": STATUS_PENDING,
                   "ts": self._now()}
            self._items[pid] = rec
            self._trim_locked()
            try:
                self._save()
            except Exception:
                self._items.pop(pid, None)
                raise
            return _copy(rec)

    def _trim_locked(self) -> None:
        decided = sorted((rec for rec in self._items.values()
                          if rec.get("status") not in (STATUS_PENDING, STATUS_APPLYING)),
                         key=lambda rec: rec.get("decided_ts") or rec.get("ts") or 0.0)
        for rec in decided[:max(0, len(decided) - MAX_DECIDED)]:
            self._items.pop(rec["id"], None)

    def get(self, proposal_id: str) -> dict | None:
        with self._lock:
            rec = self._items.get(str(proposal_id or ""))
            return _copy(rec) if rec else None

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            out = [_copy(rec) for rec in self._items.values() if status is None or rec.get("status") == status]
        return sorted(out, key=lambda rec: rec.get("ts", 0.0))

    def pending_texts(self) -> set[tuple[str, str]]:
        """``(target, text)`` of every fact already waiting for the owner."""
        with self._lock:
            return {(op.get("target"), op.get("text")) for rec in self._items.values()
                    if rec.get("status") in (STATUS_PENDING, STATUS_APPLYING)
                    for op in rec.get("operations") or []}

    def stats(self) -> dict:
        with self._lock:
            counts: dict[str, int] = {}
            for rec in self._items.values():
                counts[str(rec.get("status"))] = counts.get(str(rec.get("status")), 0) + 1
            return {"by_status": counts, "pending": counts.get(STATUS_PENDING, 0),
                    "clean_sessions": len(self._clean)}

    def _mark(self, proposal_id: str, status: str, **fields) -> dict | None:
        with self._lock:
            rec = self._items.get(proposal_id)
            if rec is None:
                return None
            before = dict(rec)
            rec["status"] = status
            if status not in (STATUS_PENDING, STATUS_APPLYING):
                rec["decided_ts"] = self._now()
            rec.update(fields)
            try:
                self._save()
            except Exception:
                rec.clear()
                rec.update(before)
                raise
            return _copy(rec)

    def _set_outcome(self, proposal_id: str, index: int, outcome: str) -> None:
        with self._lock:
            rec = self._items.get(proposal_id)
            if rec is None:
                return
            op = rec["operations"][index]
            before = op.get("outcome")
            op["outcome"] = outcome
            try:
                self._save()
            except Exception:
                if before is None:
                    op.pop("outcome", None)
                else:
                    op["outcome"] = before
                raise

    # ── the approval card (one per proposal, bound to it) ────────────────────

    def queue_card(self, proposal_id: str, queue: Any, *, agent: str = "", summary: str = "") -> str | None:
        """Queue the proposal's one approval card and bind it. The card carries the
        proposal id and counts, never a fact. A proposal whose card is still in the queue
        gets no second one; one whose card is gone gets a new one."""
        if queue is None:
            return None
        with self._card_lock:
            rec = self.get(proposal_id)
            if rec is None or rec.get("status") != STATUS_PENDING:
                return None
            if rec.get("card") and _card(queue, rec["card"]) is not None:
                return rec["card"]
            counts: dict[str, int] = {}
            for op in rec["operations"]:
                counts[op["target"]] = counts.get(op["target"], 0) + 1
            item = queue.request({
                "tool": CARD_TOOL, "agent": agent or rec.get("origin") or "background_review",
                "summary": summary or card_summary(rec),
                "args": {"proposal_id": proposal_id, "writes": len(rec["operations"]), "targets": counts,
                         "tainted": bool(rec.get("tainted")), "reason": rec.get("reason", "")}})
            card = str((item or {}).get("id") or "")
            if not card:
                return None
            try:
                bound = self._mark(proposal_id, STATUS_PENDING, card=card)
            except Exception:
                bound = None
            if bound is None or bound.get("card") != card:
                _withdraw(queue, card, "unbound")
                return None
            return card

    # ── the one gate ─────────────────────────────────────────────────────────

    def decide(self, proposal_id: str, approved: bool, queue: Any, apply: Callable[[dict, Callable], dict],
               *, by: str = "admin", reason: str | None = None) -> dict:
        """The owner's decision by proposal id: it decides the proposal's own card in the
        queue, then :meth:`settle` reads that card back. A proposal with no card in the
        queue is not decided (there is nothing the owner's decision would be recorded on)."""
        rec = self.get(proposal_id)
        if rec is None:
            return {"ok": False, "reason": "unknown_proposal"}
        if rec.get("status") not in (STATUS_PENDING, STATUS_APPLYING) or (
                rec.get("status") == STATUS_APPLYING and not approved):
            # Decided already — an approved write that is still landing cannot be rejected.
            return {"ok": False, "reason": f"not_pending:{rec.get('status')}", "proposal": public(rec)}
        if rec.get("status") == STATUS_PENDING:
            card = rec.get("card") or self.queue_card(proposal_id, queue)
            if not card or _card(queue, card) is None:
                card = self.queue_card(proposal_id, queue)
            if not card:
                return {"ok": False, "reason": "approval_queue_unavailable"}
            try:
                queue.decide(card, bool(approved), by=by, reason=reason)
            except ValueError as exc:
                return {"ok": False, "reason": "bad_reason", "detail": str(exc)}
        return self.settle_one(proposal_id, queue, apply)

    def settle_one(self, proposal_id: str, queue: Any, apply: Callable[[dict, Callable], dict]) -> dict:
        """Bring one proposal to what its card says. Blocking (ring file locks, saves)."""
        with self._apply_lock:
            rec = self.get(proposal_id)
            if rec is None:
                return {"ok": False, "reason": "unknown_proposal"}
            status = rec.get("status")
            if status == STATUS_PENDING:
                item = _card(queue, rec.get("card"))
                if item is None or item.get("tool") != CARD_TOOL \
                        or (item.get("args") or {}).get("proposal_id") != proposal_id:
                    return {"ok": False, "reason": "card_missing", "proposal": public(rec)}
                card_status = str(item.get("status") or "")
                if card_status == "pending":
                    return {"ok": False, "reason": "card_not_decided", "proposal": public(rec)}
                if card_status != "approved":
                    closed = STATUS_EXPIRED if card_status == "expired" else STATUS_REJECTED
                    rec = self._mark(proposal_id, closed)
                    return {"ok": True, "applied": False, "status": closed, "proposal": public(rec)}
                rec = self._mark(proposal_id, STATUS_APPLYING)
            elif status != STATUS_APPLYING:
                return {"ok": False, "reason": f"not_pending:{status}", "proposal": public(rec)}
            return self._apply_locked(rec, apply)

    def _apply_locked(self, rec: dict, apply: Callable[[dict, Callable], dict]) -> dict:
        pid = rec["id"]
        try:
            apply(rec, lambda index, outcome: self._set_outcome(pid, index, outcome))
        except Exception:
            logger.warning("memory proposal %s: apply stopped; it stays approved and is retried", pid,
                           exc_info=True)
        rec = self.get(pid) or rec
        outcomes = [op.get("outcome") for op in rec["operations"]]
        if any(outcome not in _FINAL for outcome in outcomes):
            # A ring was locked or could not be saved: approved, not yet written.
            return {"ok": False, "reason": "apply_incomplete", "status": STATUS_APPLYING,
                    "proposal": public(rec)}
        landed = sum(1 for outcome in outcomes if outcome in ("added", "duplicate"))
        final = STATUS_APPLIED if landed else STATUS_FAILED
        rec = self._mark(pid, final)
        return {"ok": bool(landed), "applied": bool(landed), "status": final,
                "written": sum(1 for outcome in outcomes if outcome == "added"),
                "proposal": public(rec)}

    def settle(self, queue: Any, apply: Callable[[dict, Callable], dict]) -> dict:
        """Bring every open proposal to what its card says: at start-up (a hub that
        stopped between an approval and its write), after a decision that came through a
        door of the queue's own (a group reject), and before the ledger is listed.
        Blocking. Never raises."""
        out = {"applied": 0, "closed": 0, "requeued": 0, "waiting": 0}
        try:
            open_ids = [rec["id"] for rec in self.list() if rec.get("status") in (STATUS_PENDING, STATUS_APPLYING)]
        except Exception:
            logger.warning("memory proposals: the ledger could not be read", exc_info=True)
            return out
        for pid in open_ids:
            try:
                rec = self.get(pid)
                if rec is None:
                    continue
                if rec.get("status") == STATUS_PENDING:
                    if self._now() - float(rec.get("ts") or 0.0) > PENDING_TTL_S:
                        with self._apply_lock:
                            live = self.get(pid)
                            item = _card(queue, (live or {}).get("card"))
                            if live and live.get("status") == STATUS_PENDING \
                                    and (item is None or item.get("status") == "pending"):
                                if item is not None:
                                    _withdraw(queue, live["card"], "expired")
                                self._mark(pid, STATUS_EXPIRED)
                                out["closed"] += 1
                                continue
                    if queue is not None and _card(queue, rec.get("card")) is None:
                        if self.queue_card(pid, queue):
                            out["requeued"] += 1
                        continue
                result = self.settle_one(pid, queue, apply)
                if result.get("applied"):
                    out["applied"] += 1
                elif result.get("status") in (STATUS_REJECTED, STATUS_EXPIRED, STATUS_FAILED):
                    out["closed"] += 1
                else:
                    out["waiting"] += 1
            except Exception:
                logger.warning("memory proposal %s could not be settled", pid, exc_info=True)
        return out

    def clear_memory(self) -> int:
        """A forget: drop every proposal from the live store (their text is the owner's
        data), so an approval given afterwards finds nothing to write, and the clean list
        with them (a conversation is admitted again only once it is empty). In memory only:
        the forget's own sweep erases the file, after its backup. A card left in the queue
        names a proposal that is gone, and deciding it writes nothing."""
        self._clean = {}
        with self._apply_lock, self._lock:
            count = len(self._items)
            self._items = {}
            self._clean = {}
        return count


def _copy(rec: dict) -> dict:
    out = dict(rec)
    out["operations"] = [dict(op) for op in rec.get("operations") or []]
    return out


def _card(queue: Any, card: Any) -> dict | None:
    getter = getattr(queue, "get", None)
    if not card or not callable(getter):
        return None
    try:
        item = getter(card)
    except Exception:
        return None
    return item if isinstance(item, dict) else None


def _withdraw(queue: Any, card: Any, by: str) -> None:
    decide = getattr(queue, "decide", None)
    if not card or not callable(decide):
        return
    try:
        decide(card, False, by=by)
    except Exception:
        logger.debug("memory proposal card %s not withdrawn", card, exc_info=True)


def card_summary(rec: dict) -> str:
    """The card's one line: who proposes how many writes, and why they wait. No fact."""
    count = len(rec.get("operations") or [])
    who = "/refine" if rec.get("origin") == "refine" else "Background review"
    line = f"{who} proposes {count} memory write{'s' if count != 1 else ''}"
    if rec.get("tainted"):
        line += " from a conversation that read untrusted content or was not watched from its start"
    return line + " (read them in Long-Term Memory before deciding)"


def public(rec: dict | None) -> dict | None:
    """A proposal as the admin routes show it."""
    if rec is None:
        return None
    return {"id": rec.get("id"), "origin": rec.get("origin"), "session_id": rec.get("session_id"),
            "reason": rec.get("reason"), "tainted": bool(rec.get("tainted")), "status": rec.get("status"),
            "ts": rec.get("ts"), "decided_ts": rec.get("decided_ts"), "card": rec.get("card"),
            "operations": [{"target": op.get("target"), "text": op.get("text"),
                            **({"outcome": op["outcome"]} if op.get("outcome") else {})}
                           for op in rec.get("operations") or []]}


def apply_to_rings(living: Callable[[], Any], *, switched_on: Callable[[], bool],
                   detect: Callable[[str], list], audit: Callable[[], Any] | None = None
                   ) -> Callable[[dict, Callable], dict]:
    """The writer :meth:`MemoryProposalStore.settle` calls for an approved proposal: each
    fact goes through what a direct review write goes through — the owner's memory switch,
    the injection scan (again: the scanner may have learned since it was staged), the
    ring's own budget, cap and file lock — and its outcome is saved before the next one.
    A fact with a final outcome is not tried again."""
    def apply(rec: dict, note: Callable[[int, str], None]) -> dict:
        from ..cognition.memory import CoreMemoryOverBudget

        try:
            module = living() if switched_on() is True else None
        except Exception:
            logger.warning("memory proposal %s: memory could not be read", rec.get("id"), exc_info=True)
            module = None
        written: dict[str, int] = {}
        for index, op in enumerate(rec.get("operations") or []):
            if op.get("outcome") in _FINAL:
                continue
            ring = getattr(module, TARGETS.get(str(op.get("target")), ""), None) if module is not None else None
            if ring is None or not callable(getattr(ring, "put", None)):
                note(index, "memory_off")
                continue
            try:
                flagged = bool(detect(op["text"]))
            except Exception:
                flagged = True
            if flagged:
                note(index, "blocked")
                continue
            try:
                changed = ring.put(op["text"])
            except CoreMemoryOverBudget:
                note(index, "refused")
                continue
            # Anything else (a locked ring, a save that failed) leaves the fact untried:
            # the proposal stays approved and the next settle retries it.
            note(index, "added" if changed else "duplicate")
            if changed:
                written[op["target"]] = written.get(op["target"], 0) + 1
        sink = audit() if callable(audit) else None
        if written and callable(getattr(sink, "record", None)):
            try:
                sink.record(actor=str(rec.get("origin") or "background_review"), action="memory.write",
                            why="the owner approved a held memory write", cause=str(rec.get("id") or ""),
                            metadata={"proposal": rec.get("id"), "targets": written,
                                      "tainted": bool(rec.get("tainted"))})
            except Exception:
                logger.warning("memory proposal %s: the write could not be recorded", rec.get("id"), exc_info=True)
        return written

    return apply


__all__ = [
    "CARD_TOOL", "MAX_PENDING", "PENDING_TTL_S", "SETTING", "STATUS_APPLIED", "STATUS_APPLYING",
    "STATUS_EXPIRED", "STATUS_FAILED", "STATUS_PENDING", "STATUS_REJECTED", "TARGETS", "TARGET_LABELS",
    "MemoryProposalStore", "apply_to_rings", "card_summary", "clean_operations", "public",
    "set_write_approval", "write_approval_required",
]
