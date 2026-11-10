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

Everything else is not clean: a conversation older than the ledger, one copied or
continued from another (``/undo``, a continuation, a rewind into a new session), one whose
admission was dropped at :data:`MAX_CLEAN_SESSIONS`, and every conversation when the
ledger file is missing or cannot be read (an unreadable file is moved aside,
``.unreadable-<time>``, and an empty ledger started). A conversation that is not clean
never becomes clean again unless it is emptied. Its reviews hold their memory writes for
the owner.

"Not proven clean" and "known unclean" are two different things, and only the second
taints a turn's **actions** (:func:`hits_trust`). A revocation records *why*, durably,
per session (``{sid: {reason, at}}``, one of :data:`REVOKE_REASONS`): a conversation
revoked only because it read an owner conversation the ledger never watched
(:data:`RECALLED_UNPROVEN`) is unproven, every other reason is known unclean. A
conversation the ledger never saw (older than it, or its record dropped at
:data:`MAX_REVOKED_SESSIONS`) is unproven unless the caller's own evidence says otherwise
(an import or continuation, a channel conversation, a taint mark on the record): an
upgraded install's whole history is the owner's own, and reading it gates only the
automatic memory writes, never the actions.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar, Token
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
#: Why a conversation left (or never joined) the clean list. Every reason but
#: :data:`RECALLED_UNPROVEN` makes it known unclean.
RECALLED_UNPROVEN = "recalled_unproven"
REVOKE_REASONS = frozenset({"inbound", "observed", "guest", "foreign_import", "web_or_file_or_image",
                            "flagged_recall", "undecidable", RECALLED_UNPROVEN})
#: Revocation reasons kept at once (ids and a word each). Generous; a record dropped past
#: it reads as never seen (unproven unless the caller's evidence says otherwise), never as
#: unclean, and a known-unclean record is dropped only after every unproven one.
MAX_REVOKED_SESSIONS = 100_000
#: A session's standing, worst last.
TRUST_CLEAN, TRUST_UNPROVEN, TRUST_UNCLEAN = "clean", "unproven", "unclean"
_TRUST_RANK = {TRUST_CLEAN: 0, TRUST_UNPROVEN: 1, TRUST_UNCLEAN: 2}
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


_SESSION_KEYS = ("session_id", "session")
_NESTED_KEYS = ("payload", "metadata", "properties")


def hit_session(hit: Any, _depth: int = 0) -> str | None:
    """H443 — the conversation a recalled or searched hit was taken from, when it names
    one (``session_id`` or ``session``, on the hit or in its payload / metadata /
    properties), else None (a hit that is not conversation text: a fact, a document)."""
    if _depth > 3:
        return None
    if not isinstance(hit, dict):
        payload = getattr(hit, "payload", None)
        return hit_session(payload, _depth + 1) if isinstance(payload, dict) else None
    for key in _SESSION_KEYS:
        value = hit.get(key)
        if isinstance(value, str) and value:
            return value
    for key in _NESTED_KEYS:
        found = hit_session(hit.get(key), _depth + 1) if isinstance(hit.get(key), dict) else None
        if found:
            return found
    return None


def hits_trust(hits: Any, trust: Callable[[str], str] | None) -> str:
    """H443 — the worst standing among the conversations *hits* were taken from
    (:data:`TRUST_CLEAN` when none names one). *trust* is ``session_id -> standing``
    (:meth:`MemoryProposalStore.session_trust` with the hub's evidence); None (no ledger)
    reads every named conversation as unproven. A check that fails reads as unclean.
    Only :data:`TRUST_UNCLEAN` taints the turn's actions; :data:`TRUST_UNPROVEN` holds its
    conversation's automatic memory writes (:func:`note_unproven_read`)."""
    worst = TRUST_CLEAN
    seen: set[str] = set()
    for hit in hits or []:
        sid = hit_session(hit)
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        try:
            standing = TRUST_UNPROVEN if trust is None else trust(sid)
        except Exception:
            standing = TRUST_UNCLEAN
        if standing not in _TRUST_RANK:
            standing = TRUST_UNCLEAN
        if _TRUST_RANK[standing] > _TRUST_RANK[worst]:
            worst = standing
            if worst == TRUST_UNCLEAN:
                break
    return worst


def as_trust(check: Callable[[str], Any] | None) -> Callable[[str], str] | None:
    """A standing check from either a standing check or a clean-list check
    (``session_id -> bool``: True is clean, False only unproven — not being on the list
    is no evidence of anything)."""
    if check is None:
        return None

    def trust(session_id: str) -> str:
        answer = check(session_id)
        if answer is True:
            return TRUST_CLEAN
        if answer is False:
            return TRUST_UNPROVEN
        return answer

    return trust


def hits_from_unclean(hits: Any, check: Callable[[str], Any] | None) -> bool:
    """Whether any hit comes from a conversation known to be unclean (:func:`hits_trust`)."""
    return hits_trust(hits, as_trust(check)) == TRUST_UNCLEAN


#: H443 — this turn read text from a conversation that is not proven clean. A mutable
#: holder bound at the turn's start, so a tool handler running in a copy of the turn's
#: context (a task, a thread) still reaches it.
_UNPROVEN_READS: ContextVar[list | None] = ContextVar("nerva_h443_unproven_reads", default=None)


def open_unproven_reads() -> Token:
    """Bind a fresh holder for the turn about to run; reset with :func:`close_unproven_reads`."""
    return _UNPROVEN_READS.set([])


def close_unproven_reads(token: Token) -> None:
    _UNPROVEN_READS.reset(token)


def note_unproven_read() -> None:
    """The turn in flight read text from an unproven owner conversation (nothing when no
    turn is bound: a route, a script)."""
    holder = _UNPROVEN_READS.get()
    if holder is not None and not holder:
        holder.append(True)


def turn_read_unproven() -> bool:
    return bool(_UNPROVEN_READS.get())


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
    first turn.

    Two files: the ledger itself (proposals, the clean list; small, rewritten whole) and,
    beside it, the reasons journal (``<ledger>.reasons.jsonl``): one appended line per
    recorded or dropped revocation reason, numbered, compacted once it is mostly stale.
    A new channel conversation's reason costs one line, never a rewrite of every reason.
    Every in-memory copy-and-swap of the clean list or the reasons happens under
    ``_swap_lock``, which is never held across a disk write."""

    def __init__(self, path: str | Path | None = None, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._apply_lock = threading.Lock()
        self._card_lock = threading.Lock()
        self._swap_lock = threading.Lock()
        self._journal_lock = threading.Lock()
        self._items: dict[str, dict] = {}
        self._clean: dict[str, float] = {}
        #: Why each revoked session is off the clean list: ``{sid: {"reason", "at", "seq"}}``.
        self._revoked: dict[str, dict] = {}
        self._seq = 0
        self._journal_lines = 0
        #: The journal may end in a partial line (a write that failed): the next write
        #: starts with a newline.
        self._journal_torn = False
        #: Reasons read from an older ledger that kept them inline, until the journal
        #: holds them (they are saved inline meanwhile).
        self._inline_reasons = False
        #: The reasons map passed the cap: trimmed off the event loop, by the next write.
        self._needs_trim = False
        #: Held writes refused because :data:`MAX_PENDING` were already waiting.
        self._dropped = 0
        #: The clean list as an admission is saving it (shown only once it is on disk),
        #: and the sessions a revocation is taking off it meanwhile.
        self._saving_clean: dict[str, float] | None = None
        self._revoking: set[str] = set()
        super().__init__(path)

    # ── persistence ──────────────────────────────────────────────────────────

    @property
    def journal_path(self) -> Path | None:
        return self.path.with_name(f"{self.path.name}.reasons.jsonl") if self.path is not None else None

    def _serialize(self):
        clean = self._saving_clean if self._saving_clean is not None else self._clean
        out = {"proposals": self._items, "clean_sessions": clean, "dropped_at_cap": self._dropped}
        if self._inline_reasons:
            out["revoked_sessions"] = {sid: {"reason": rec["reason"], "at": rec["at"]}
                                       for sid, rec in self._revoked.items()}
        return out

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        items = raw.get("proposals")
        self._items = {}
        for key, rec in (items.items() if isinstance(items, dict) else []):
            rec = _sane(str(key), rec)
            if rec is not None:
                self._items[str(key)] = rec
        dropped = raw.get("dropped_at_cap")
        self._dropped = dropped if type(dropped) is int and dropped >= 0 else 0
        clean = raw.get("clean_sessions")
        self._clean = ({str(k): float(v) for k, v in clean.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)}
                       if isinstance(clean, dict) else {})
        # An earlier ledger kept the reasons inline: read them, the journal follows.
        self._revoked = {}
        revoked = raw.get("revoked_sessions")
        self._inline_reasons = bool(revoked) and isinstance(revoked, dict)
        for key, rec in (revoked.items() if isinstance(revoked, dict) else []):
            self._apply_line({"s": str(key), "r": rec.get("reason") if isinstance(rec, dict) else None,
                              "t": rec.get("at") if isinstance(rec, dict) else None, "n": 0})

    def _apply_line(self, line: dict) -> None:
        sid = line.get("s")
        if not isinstance(sid, str) or not sid:
            return
        seq = line.get("n") if type(line.get("n")) is int else 0
        self._seq = max(self._seq, seq)
        if line.get("d"):
            self._revoked.pop(sid, None)
            return
        reason = line.get("r")
        at = line.get("t")
        if not isinstance(at, (int, float)) or isinstance(at, bool):
            at = 0.0
        # A damaged reason is the stricter one: known unclean, cause unknown.
        self._revoked[sid] = {"reason": reason if reason in REVOKE_REASONS else "undecidable",
                              "at": float(at), "seq": seq}

    def _load(self) -> None:
        import json

        if self.path is None or not self.path.exists():
            # No ledger: nothing is held and no conversation is known to be clean.
            self._deserialize({})
        else:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or not isinstance(raw.get("proposals"), dict) \
                        or not isinstance(raw.get("clean_sessions"), dict):
                    raise ValueError("not a memory proposal ledger")
            except Exception:
                aside = self.path.with_name(f"{self.path.name}.unreadable-{int(self._now())}")
                logger.warning("memory proposals: %s cannot be read; moved to %s and an empty ledger started "
                               "(no earlier conversation is treated as clean)", self.path, aside.name,
                               exc_info=True)
                try:
                    self.path.replace(aside)
                except OSError:
                    logger.warning("memory proposals: the unreadable ledger could not be moved aside",
                                   exc_info=True)
                raw = {}
            self._deserialize(raw)
        self._load_journal()
        self._trim_revoked()
        # A session with a reason is never clean, whatever the ledger says.
        for sid in self._revoked:
            self._clean.pop(sid, None)
        if self._inline_reasons and self.journal_path is not None:
            # An older ledger kept the reasons inline: they move into the journal now,
            # before any save of the ledger could drop them.
            try:
                self.compact()
                self._inline_reasons = False
            except OSError:
                logger.warning("memory proposals: inline reasons could not be moved to the journal; "
                               "they stay in the ledger", exc_info=True)

    def _load_journal(self) -> None:
        import json
        import os

        journal = self.journal_path
        if journal is None or not journal.exists():
            return
        try:
            data = journal.read_bytes()
        except OSError:
            logger.warning("memory proposals: the reasons journal cannot be read; recorded reasons are "
                           "not known (sessions read as never seen)", exc_info=True)
            return
        if data and not data.endswith(b"\n"):
            # A write cut short: its partial line is cut off, so the next append starts
            # on a line of its own (otherwise both would be one unreadable line).
            keep = data.rfind(b"\n") + 1
            try:
                with open(journal, "r+b") as fh:
                    fh.truncate(keep)
                    os.fsync(fh.fileno())
            except OSError:
                logger.warning("memory proposals: a torn journal tail could not be cut; the next line "
                               "starts on a new line", exc_info=True)
                self._journal_torn = True
            data = data[:keep]
        lines: list[dict] = []
        skipped = 0
        for raw_line in data.split(b"\n"):
            if not raw_line.strip():
                continue
            try:
                line = json.loads(raw_line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                skipped += 1
                continue
            if isinstance(line, dict):
                lines.append(line)
            else:
                skipped += 1
        if skipped:
            logger.warning("memory proposals: %d unreadable line(s) in the reasons journal were skipped "
                           "(those sessions read as never seen)", skipped)
        lines.sort(key=lambda line: line.get("n") if type(line.get("n")) is int else 0)
        for line in lines:
            self._apply_line(line)
        self._journal_lines = len(lines)

    def _append_journal(self, line: dict) -> None:
        """Append one numbered line to the reasons journal, flushed to disk. Blocking."""
        self._append_journal_lines([line])

    def _append_journal_lines(self, lines: list[dict]) -> None:
        """Append numbered lines to the reasons journal in one write, flushed to disk;
        a short write is continued, a failed one leaves the next write to start on a new
        line. Blocking."""
        import json
        import os

        journal = self.journal_path
        if journal is None or not lines:
            return
        data = "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines).encode("utf-8")
        with self._journal_lock:
            if self._journal_torn:
                data = b"\n" + data
            fd = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("the reasons journal accepted no bytes")
                    view = view[written:]
                os.fsync(fd)
                self._journal_torn = False
            except BaseException:
                self._journal_torn = True
                raise
            finally:
                os.close(fd)
            self._journal_lines += len(lines)
            if self._journal_lines > 2 * len(self._revoked) + 1024:
                self._compact_journal_locked()

    def _compact_journal_locked(self) -> None:
        """Rewrite the journal as the reasons stand (tmp, fsync, replace). Journal lock held."""
        import json
        import os

        journal = self.journal_path
        with self._swap_lock:
            snapshot = dict(self._revoked)
            seq = self._seq
        tmp = journal.with_name(journal.name + ".tmp")
        data = "".join(json.dumps({"s": sid, "r": rec["reason"], "t": rec["at"], "n": seq},
                                  separators=(",", ":")) + "\n" for sid, rec in snapshot.items()).encode("utf-8")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("the reasons journal accepted no bytes")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, journal)
        self._journal_torn = False
        self._journal_lines = len(snapshot)

    def compact(self) -> None:
        """Rewrite the reasons journal as it stands. Blocking."""
        if self.journal_path is None:
            return
        with self._journal_lock:
            self._compact_journal_locked()

    def _trim_order(self, revoked: dict) -> list[str]:
        """Past :data:`MAX_REVOKED_SESSIONS`, the records to drop — the ones whose loss
        costs least: unproven, then channel conversations (whose id the hub's own
        evidence still names: ``ch_…``), then the oldest — down to 95% of the cap, so the
        sort runs once per many new records."""
        if len(revoked) <= MAX_REVOKED_SESSIONS:
            return []
        target = MAX_REVOKED_SESSIONS - MAX_REVOKED_SESSIONS // 20
        order = sorted(revoked, key=lambda key: (revoked[key]["reason"] != RECALLED_UNPROVEN,
                                                 not key.startswith("ch_"), revoked[key]["at"]))
        return order[:len(revoked) - target]

    def _trim_revoked(self) -> None:
        """Trim at load (single-threaded). A dropped record reads as never seen."""
        for key in self._trim_order(self._revoked):
            self._revoked.pop(key, None)

    def _trim_if_needed(self) -> None:
        """Trim the reasons past the cap and write a drop line for each. Blocking: run by
        the writers, off the event loop. The sort runs on a copy, outside the swap lock."""
        if not self._needs_trim:
            return
        with self._swap_lock:
            snapshot = {sid: dict(rec) for sid, rec in self._revoked.items()}
            self._needs_trim = False
        victims = self._trim_order(snapshot)
        if not victims:
            return
        drops = []
        with self._swap_lock:
            for sid in victims:
                rec = self._revoked.get(sid)
                if rec is not None and rec.get("seq") == snapshot[sid].get("seq"):
                    self._revoked.pop(sid, None)
                    self._seq += 1
                    drops.append({"s": sid, "d": 1, "n": self._seq})
        try:
            self._append_journal_lines(drops)
        except OSError:
            logger.warning("memory proposals: drop lines for trimmed reasons could not be written",
                           exc_info=True)

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
            before = self._revoked.get(sid)
            if before is not None and before.get("reason") == "foreign_import":
                # A continuation or an import looks empty until its seed loads: it stays
                # off the list.
                return False
            # Saved first, shown after: a reader (which takes no lock, see is_clean) never
            # sees an admission the ledger does not hold. (A reason still in the journal
            # keeps it off the list after a restart until the drop below is written.)
            with self._swap_lock:
                candidate = {**self._clean, sid: self._now()}
                while len(candidate) > MAX_CLEAN_SESSIONS:
                    candidate.pop(min(candidate, key=candidate.__getitem__))
                self._saving_clean = candidate
            try:
                self._save()
            finally:
                self._saving_clean = None
            with self._swap_lock:
                if sid in self._revoking or self._revoked.get(sid) is not before:
                    # A revocation of this session ran while this was saving: it wins.
                    return False
                # The candidate as saved, less any session revoked meanwhile.
                self._clean = {key: value for key, value in candidate.items()
                               if key == sid or key in self._clean}
                drop = None
                if before is not None:
                    # An empty conversation starts over: the reason recorded for it goes.
                    self._revoked.pop(sid, None)
                    self._seq += 1
                    drop = {"s": sid, "d": 1, "n": self._seq}
        if drop is not None:
            try:
                self._append_journal(drop)
            except OSError:
                logger.warning("memory proposals: a dropped reason could not be written; the conversation "
                               "reads as not clean after a restart", exc_info=True)
        return True

    def _reason_changes(self, sid: str, reason: str) -> bool:
        """Whether recording *reason* for *sid* changes what is recorded: a first reason,
        or a known-unclean one over :data:`RECALLED_UNPROVEN` (never the other way)."""
        current = self._revoked.get(sid)
        if current is None:
            return True
        return current.get("reason") == RECALLED_UNPROVEN and reason != RECALLED_UNPROVEN

    def _record_reason_swapped(self, sid: str, reason: str) -> dict | None:
        """Record *reason* for *sid* in memory; the journal line to write, or None when
        nothing changed. Caller holds ``_swap_lock``."""
        if not self._reason_changes(sid, reason):
            return None
        self._seq += 1
        rec = {"reason": reason, "at": self._now(), "seq": self._seq}
        # In place: a reader's single lookup is safe without the lock; every writer and
        # every iteration (the journal's compaction) holds it.
        self._revoked[sid] = rec
        if len(self._revoked) > MAX_REVOKED_SESSIONS:
            self._needs_trim = True   # trimmed by the write that follows, off the event loop
        return {"s": sid, "r": reason, "t": rec["at"], "n": rec["seq"]}

    def _take_off(self, sid: str, reason: str) -> tuple[bool, dict | None]:
        """Off the clean list and *reason* recorded, in memory, at once: (was it on the
        list or being admitted, the journal line to write)."""
        with self._swap_lock:
            saving = self._saving_clean
            was_clean = sid in self._clean or (saving is not None and sid in saving)
            if was_clean:
                self._revoking.add(sid)
                self._clean = {key: value for key, value in self._clean.items() if key != sid}
            return was_clean, self._record_reason_swapped(sid, reason)

    def needs_revoke(self, session_id: str, reason: str) -> bool:
        """Whether :meth:`revoke` with *reason* would change anything (no lock, no save):
        the session is on the clean list, or the reason is new for it."""
        sid = str(session_id or "")
        if not sid:
            return False
        reason = reason if reason in REVOKE_REASONS else "undecidable"
        saving = self._saving_clean
        return (sid in self._clean or (saving is not None and sid in saving)
                or self._reason_changes(sid, reason))

    def flush(self) -> None:
        """Save the ledger as it stands. Blocking."""
        with self._lock:
            self._save()

    def revoked_reason(self, session_id: str) -> str | None:
        rec = self._revoked.get(str(session_id or ""))
        return rec.get("reason") if rec else None

    def session_trust(self, session_id: str, evidence: Callable[[str], bool] | None = None) -> str:
        """*session_id*'s standing: :data:`TRUST_CLEAN` while on the clean list;
        :data:`TRUST_UNCLEAN` when revoked for any reason but :data:`RECALLED_UNPROVEN`;
        otherwise (revoked only for reading an unproven conversation, or never seen by
        this ledger) :data:`TRUST_UNPROVEN`, unless *evidence* (``session_id -> bool``, the
        hub's own record: an import or continuation, a channel conversation) says it is
        unclean. Blocking only as far as *evidence* is."""
        sid = str(session_id or "")
        if sid in self._clean:
            return TRUST_CLEAN
        reason = self.revoked_reason(sid)
        if reason is not None and reason != RECALLED_UNPROVEN:
            return TRUST_UNCLEAN
        if evidence is not None and evidence(sid) is True:
            return TRUST_UNCLEAN
        return TRUST_UNPROVEN

    def revoke(self, session_id: str, reason: str = "undecidable") -> bool:
        """Take *session_id* off the clean list and record why (*reason*, one of
        :data:`REVOKE_REASONS`; anything else is ``undecidable``). A session that was never
        on the list is recorded too: its reason decides whether reading it taints a
        turn's actions. Shown at once (the stricter side), then written: the reason as one
        journal line, the ledger only when the session was on the clean list. True when
        anything changed. A write that fails raises; the revocation still holds in this
        process."""
        sid = str(session_id or "")
        if not sid:
            return False
        reason = reason if reason in REVOKE_REASONS else "undecidable"
        was_clean, line = self._take_off(sid, reason)
        self._write_taken_off(sid, was_clean, line)
        return was_clean or line is not None

    def forget_clean(self, session_id: str, reason: str = "foreign_import") -> tuple[bool, dict | None]:
        """Take *session_id* off the clean list and record *reason*, in memory only (no
        disk write: the caller may be on the event loop). Returns ``(was_clean, line)``;
        :meth:`write_forgotten` writes them."""
        sid = str(session_id or "")
        if not sid:
            return False, None
        reason = reason if reason in REVOKE_REASONS else "undecidable"
        return self._take_off(sid, reason)

    def write_forgotten(self, session_id: str, was_clean: bool, line: dict | None) -> None:
        """Write what :meth:`forget_clean` changed. Blocking: run it off the event loop."""
        self._write_taken_off(str(session_id or ""), was_clean, line)

    def _write_taken_off(self, sid: str, was_clean: bool, line: dict | None) -> None:
        """The journal line, then the ledger without the session — the ledger is saved
        whether or not the line could be written, so leaving the clean list holds on
        disk either way. The first failure is raised. Blocking."""
        failure: BaseException | None = None
        try:
            if line is not None:
                self._append_journal(line)
        except BaseException as exc:
            failure = exc
        try:
            if was_clean:
                with self._lock:
                    self._save()
        except BaseException as exc:
            failure = failure or exc
        finally:
            if was_clean:
                with self._swap_lock:
                    self._revoking.discard(sid)
        try:
            self._trim_if_needed()
        except Exception:
            logger.warning("memory proposals: the reasons could not be trimmed", exc_info=True)
        if failure is not None:
            raise failure

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
                # Counted and saved, so the owner is told how many were not kept.
                self._dropped += 1
                try:
                    self._save()
                except Exception:
                    logger.warning("memory proposals: the dropped count could not be saved", exc_info=True)
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
        """Counts only, never a fact: what the learning status and the HUD show."""
        with self._lock:
            counts: dict[str, int] = {}
            oldest = None
            for rec in self._items.values():
                counts[str(rec.get("status"))] = counts.get(str(rec.get("status")), 0) + 1
                if rec.get("status") in (STATUS_PENDING, STATUS_APPLYING):
                    ts = rec.get("ts")
                    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                        oldest = ts if oldest is None else min(oldest, ts)
            waiting = counts.get(STATUS_PENDING, 0) + counts.get(STATUS_APPLYING, 0)
            return {"by_status": counts, "pending": waiting, "max_pending": MAX_PENDING,
                    "oldest_pending_age_s": (max(0.0, round(self._now() - oldest, 1))
                                             if oldest is not None else None),
                    "dropped_at_cap": self._dropped, "clean_sessions": len(self._clean),
                    "revoked_sessions": len(self._revoked)}

    def is_full(self) -> bool:
        with self._lock:
            return sum(1 for rec in self._items.values() if rec.get("status") == STATUS_PENDING) >= MAX_PENDING

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

    def clear_memory(self, queue: Any = None) -> int:
        """A forget: drop every proposal from the live store (their text is the owner's
        data), so an approval given afterwards finds nothing to write, withdraw each open
        proposal's card from *queue* (the Decision Inbox), and drop the clean list with
        them (a conversation is admitted again only once it is empty). The store's file is
        left to the forget's own sweep, after its backup. Blocking (the queue's save):
        callers run it off the event loop."""
        with self._swap_lock:
            self._clean = {}
        with self._apply_lock, self._lock:
            count = len(self._items)
            cards = [rec.get("card") for rec in self._items.values()
                     if rec.get("status") in (STATUS_PENDING, STATUS_APPLYING) and rec.get("card")]
            self._items = {}
            with self._swap_lock:
                self._clean = {}
        for card in cards:
            item = _card(queue, card)
            if item is not None and item.get("status") == "pending":
                _withdraw(queue, card, "forgotten")
        return count


_KNOWN_STATUSES = frozenset({STATUS_PENDING, STATUS_APPLYING, STATUS_APPLIED, STATUS_REJECTED,
                              STATUS_EXPIRED, STATUS_FAILED})


def _sane(key: str, rec: Any) -> dict | None:
    """A stored proposal as the store uses it, or None. A hand-edited or damaged record is
    never trusted into a write: an operation that is not ``{target, text}`` is dropped
    (and marked, so the proposal can only fail, never apply part of what the owner saw);
    an unknown status is read as failed; nothing here raises."""
    if not isinstance(rec, dict):
        return None
    ops, damaged = [], False
    for op in rec.get("operations") if isinstance(rec.get("operations"), list) else []:
        if (isinstance(op, dict) and op.get("target") in TARGETS and isinstance(op.get("text"), str)
                and op["text"].strip()):
            ops.append(op)
        else:
            damaged = True
    if not isinstance(rec.get("operations"), list):
        damaged = True
    out = {**rec, "id": key, "operations": ops}
    open_or_unknown = out.get("status") in (STATUS_PENDING, STATUS_APPLYING) or out.get("status") not in _KNOWN_STATUSES
    if (damaged or not ops) and open_or_unknown or out.get("status") not in _KNOWN_STATUSES:
        # Never applied: a damaged open record is closed, and its card, decided or not,
        # writes nothing. A decided record keeps what it was.
        out["status"] = STATUS_FAILED
        out["reason"] = "damaged_record"
    return out


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
    if not isinstance(rec, dict):
        return None
    ops = rec.get("operations") if isinstance(rec.get("operations"), list) else []
    return {"id": rec.get("id"), "origin": rec.get("origin"), "session_id": rec.get("session_id"),
            "reason": rec.get("reason"), "tainted": bool(rec.get("tainted")), "status": rec.get("status"),
            "ts": rec.get("ts"), "decided_ts": rec.get("decided_ts"), "card": rec.get("card"),
            "operations": [{"target": op.get("target"), "text": op.get("text"),
                            **({"outcome": op["outcome"]} if op.get("outcome") else {})}
                           for op in ops if isinstance(op, dict)]}


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
