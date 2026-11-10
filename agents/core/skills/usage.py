"""
usage.py — skill usage telemetry + provenance (H20.5 live wave, H354, H349).

Sidecar JsonStore (runtime data root, never the repo `skills/` tree) tracking
per-skill counters, provenance, the owner's pin and lifecycle state. The curator reads the
derived latest-activity timestamp to decide active → stale → archived
transitions; only **agent-created, unpinned** skills are ever curatable.

**Identity (H349, second review).** A row is its skill's *name*; nothing about where the
skill's folder lives is recorded, so moving the skills folder, restoring a backup under
another path or user, or a volume that is away for a start changes no row. The sidecar
never destroys or resets a row because of what it fails to see: a skill that is not
registered now keeps its row exactly as it is (it simply cannot be newly pinned, and is
not counted as installed). A row ends only through an explicit removal act —
:meth:`SkillUsageStore.forget` (batch delete, reject from review, uninstall) or
:meth:`SkillUsageStore.retire` (curator archive, journey forget: a tombstone bound to the
removed bytes' fingerprint) — and is replaced by a fresh one in exactly two cases, both
decided by the bytes and never by absence or path: a creation path made a new skill under
the name whose bytes are not the ones the row last saw, or bytes other than a tombstone's
register under its name.

Pattern adapted from hermes-agent `tools/skill_usage.py` (Nous Research, MIT)
— see LICENSES/THIRD_PARTY.md — rebuilt on jarvis's JsonStore (single-process
atomic persistence) instead of hermes's cross-process fcntl/msvcrt locking.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.core.persistence import JsonStore

logger = logging.getLogger("jarvis.skills.usage")

STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"
_VALID_STATES = (STATE_ACTIVE, STATE_STALE, STATE_ARCHIVED)

ORIGIN_AGENT = "agent"          # made by the agent, and its folder carries no install record
ORIGIN_IMPORT = "import"        # installed from hermes/openclaw/github/marketplace/a local install
ORIGIN_BUNDLED = "bundled"      # shipped with Nerva
# H349 — installed, with no install record and no agent marker: the owner's own skill, or
# one placed in the skills folder by hand. Authorship is not inferred (Hermes: "provenance
# is declared, never inferred"), so this only says no install record was found.
ORIGIN_LOCAL = "local"
# H349 — a row no loaded skill was ever classified for (a counter bumped under a name the
# loader never registered, or no usable sidecar). It used to read "bundled", which claimed
# a skill ships with Nerva on no evidence.
ORIGIN_UNKNOWN = "unknown"
_ORIGINS = (ORIGIN_AGENT, ORIGIN_IMPORT, ORIGIN_BUNDLED, ORIGIN_LOCAL, ORIGIN_UNKNOWN)

# H349 (review m3) — who wrote an agent-made skill, as Hermes's write origin tells them
# apart: the background review and the learning loop are the agent's own initiative (the
# curator manages those); a skill the model wrote with its skill tools inside a turn was
# asked for in that turn and is never auto-curated. A row from before the field has none
# and is curated as it always was.
WRITE_BACKGROUND = "background_review"
WRITE_LEARNING = "learning"
WRITE_TOOL = "assistant_tool"
_WRITE_ORIGINS = (WRITE_BACKGROUND, WRITE_LEARNING, WRITE_TOOL)

#: Where an import can come from (review m2): the local installs the migration importer
#: reads (``importer.MIGRATION_SOURCES``) and the two upstream catalogs. Anything else an
#: install record names is shown only when it has the shape of a GitHub repository name.
KNOWN_SOURCES = ("hermes", "openclaw", "claude-code")
SOURCE_MARKETPLACE = "marketplace"       # only the marketplace installer's own marker says so
_RESERVED_SOURCES = (SOURCE_MARKETPLACE, "bundled", "agent", "local", "unknown", "import", "nerva", "owner")
_REPO_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,38}")
_TOKEN_PREFIX_RE = re.compile(r"(?i)^(gh[pousr]_|github_pat_|sk-|xox[a-z]-|glpat-|akia)")
_ALNUM_RUN_RE = re.compile(r"[A-Za-z0-9]{20,}")

#: How long a counter bump waits for a removal that holds the store lock before it gives up.
BUMP_WAIT_SECONDS = 0.25

#: How many ``<sidecar>.corrupt-<time>`` copies are kept beside the sidecar (review m3).
CORRUPT_COPIES_KEPT = 3

_COUNTERS = ("use_count", "view_count", "patch_count", "switch_on_count")
_STAMPS = ("created_at", "last_used_at", "last_viewed_at", "last_patched_at", "last_switched_on_at",
           "restored_at", "archived_at")
#: Fields every row carries; the rest (``switch_on_count``, ``last_switched_on_at``,
#: ``restored_at``) appear when their event first happens.
_OPTIONAL = ("switch_on_count", "last_switched_on_at", "restored_at")
_BUMP_KEYS = {"use": ("use_count", "last_used_at"),
              "view": ("view_count", "last_viewed_at"),
              "patch": ("patch_count", "last_patched_at"),
              # A recorded switch-on restarts the idle clock: a switched-off skill records
              # no use, and the curator must not count that time as neglect.
              "switch_on": ("switch_on_count", "last_switched_on_at")}


class PinRefused(Exception):
    """A pin the sidecar refused. ``reason``: ``not_found`` (no skill of this name is
    installed and registered now) or ``not_pinnable`` (it ships with Nerva: nothing ages
    it out or deletes it)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def latest_activity_at(record: dict) -> datetime | None:
    """Newest use/view/patch/switch-on/restore timestamp (creation intentionally excluded).

    A restore counts (review M2): a skill the owner moved back out of the archive starts
    its idle clock again, or the next pass would archive it once more."""
    latest = None
    for key in ("last_used_at", "last_viewed_at", "last_patched_at", "last_switched_on_at", "restored_at"):
        dt = _parse_iso(record.get(key))
        if dt is not None and (latest is None or dt > latest):
            latest = dt
    return latest


def _count(value: Any) -> int:
    """A stored counter as a non-negative int; anything else counts as zero."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _word(value: Any, allowed: tuple[str, ...]) -> bool:
    """Whether ``value`` is one of ``allowed``. The type is checked first: a list or a
    dict from a damaged file is never hashed or compared (review M3)."""
    return isinstance(value, str) and value in allowed


def _pin_blocks(rec: Any) -> bool:
    """Whether a row stops automation (the curator, an agent's delete). Only an exact
    ``false`` or no flag at all reads as "not pinned" here: a flag that is not a bool is
    left alone by automation, which is the stricter side for these readers."""
    if not isinstance(rec, dict):
        return False
    flag = rec.get("pinned")
    return not (flag is False or flag is None)


def _repair(rec: dict) -> bool:
    """Bring one stored row to the shapes the readers rely on (review M3), in place, and
    say whether anything stored was wrong. Never raises, whatever JSON the row holds.

    A field the row does not have yet is filled in and is not damage (a row from an
    earlier release). A field with the wrong type or an unknown word is: counters that are
    not non-negative ints restart at zero, so a later bump counts again instead of
    failing; an origin, state, source or write origin that is not a known word reads as
    unknown / active / empty; a timestamp that is not text is dropped. ``agent_created``
    is the sticky agent marker: a row from before it existed takes it from its ``agent``
    origin, and anything that is not exactly ``true`` or ``false`` is not agent-made (the
    stricter side for the curator, which then never touches the skill). ``pinned`` is kept
    as stored: each reader decides (:func:`_pin_blocks`, ``is_pinned``)."""
    damaged = False
    origin = rec.get("origin")
    if "agent_created" not in rec:
        rec["agent_created"] = isinstance(origin, str) and origin == ORIGIN_AGENT
    elif not isinstance(rec["agent_created"], bool):
        rec["agent_created"], damaged = False, True
    if not _word(origin, _ORIGINS):
        damaged = damaged or "origin" in rec
        rec["origin"] = ORIGIN_UNKNOWN
    if "state" not in rec:
        rec["state"] = STATE_ACTIVE
    elif not _word(rec["state"], _VALID_STATES):
        rec["state"], damaged = STATE_ACTIVE, True
    for key in _COUNTERS:
        if key not in rec:
            if key not in _OPTIONAL:
                rec[key] = 0
        elif isinstance(rec[key], bool) or not isinstance(rec[key], int) or rec[key] < 0:
            rec[key], damaged = 0, True
    for key in _STAMPS:
        if key not in rec:
            if key not in _OPTIONAL:
                rec[key] = None
        elif rec[key] is not None and not (isinstance(rec[key], str) and rec[key]):
            rec[key], damaged = None, True
    source = rec.get("source", "")
    if not isinstance(source, str):
        damaged = True
    rec["source"] = _stored_source(source) if rec["origin"] == ORIGIN_IMPORT else ""
    write_origin = rec.get("write_origin", "")
    if write_origin != "" and not _word(write_origin, _WRITE_ORIGINS):
        damaged = True
        write_origin = ""
    rec["write_origin"] = write_origin
    fingerprint = rec.get("fingerprint", "")
    if not isinstance(fingerprint, str):
        fingerprint, damaged = "", True
    rec["fingerprint"] = fingerprint
    if "pinned" not in rec:
        rec["pinned"] = False
    if "restore_pending" in rec and rec["restore_pending"] is not True:
        damaged = damaged or rec["restore_pending"] is not False
        del rec["restore_pending"]
    # An earlier build of this change recorded the folder's absolute path. Identity is the
    # name; the path is dropped, not kept.
    rec.pop("folder", None)
    return damaged


class _Removal:
    """What :meth:`SkillUsageStore.removal` hands the caller while it holds the lock."""

    def __init__(self, store: SkillUsageStore, blocked: list[str]) -> None:
        self._store = store
        self.blocked = blocked

    def forget(self, name: str) -> bool:
        return self._store.forget(name)

    def retire(self, name: str, fingerprint: str | None = "") -> bool:
        return self._store.retire(name, fingerprint)


class SkillUsageStore(JsonStore):
    """Per-skill telemetry: counters, provenance, pin flag, lifecycle state.

    Writers and removals take the store lock. Reads (``get``, ``list``, ``is_pinned``,
    ``pin_blocks``, ``curatable``, ``stats``, :func:`usage_summary`) take no lock: they
    copy one row, or the row table, in a single step, so a request handler on the event
    loop never waits behind a removal that holds the lock across a folder move (review
    m2). The check that decides a removal is made inside the lock (:meth:`removal`)."""

    def __init__(self, path: str | Path | None = None) -> None:
        # The names a loader has registered in this process (or a creator vouched for):
        # what "installed now" means to :meth:`pin` and :meth:`stats`. Not persisted — a
        # row on disk says what a skill was, not that it is installed.
        self._registered: set[str] = set()
        self._synced = False                    # whether a loader has reported every skill
        self._items: dict[str, dict] = {}
        super().__init__(path)
        # Re-entrant: a removal holds the lock across its folder move, and the reload that
        # follows reaches the store again on the same thread (review M4).
        self._lock = threading.RLock()

    # ── persistence ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Read the sidecar. Nothing in the file can stop the store from loading, and
        nothing is silently thrown away (review M3):

        - a file that is not JSON, not an object, or whose ``skills`` is not an object is
          moved to ``<name>.corrupt-<time>`` beside it and the store starts empty;
        - a file that parses but holds rows that are not records, or fields of the wrong
          shape, is copied there once, the bad rows dropped and the bad fields repaired
          (:func:`_repair`), and the repaired file saved, so the next start finds nothing
          to repair and makes no second copy.

        A warning names both files, never their contents. At most
        :data:`CORRUPT_COPIES_KEPT` copies are kept."""
        self._items = {}
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("skills", {}), dict):
                raise ValueError("not a skill usage sidecar")
            items, dropped, repaired = self._parse(raw)
        except Exception as exc:        # RecursionError, UnicodeError, OSError, … : any of them
            kept = self._set_aside(move=True)
            logger.warning("the skill usage sidecar %s could not be read (%s); it was %s and the hub starts "
                           "with no pins, agent markers or counters", self.path.name, type(exc).__name__,
                           f"kept as {kept.name}" if kept else "left in place (it could not be moved)")
            return
        self._items = items
        if not dropped and not repaired:
            return
        kept = self._set_aside(move=False)
        logger.warning("the skill usage sidecar %s held %d row(s) that are not records (dropped) and %d row(s) "
                       "with malformed fields (repaired)%s", self.path.name, dropped, repaired,
                       f"; the file as it was is kept as {kept.name}" if kept else
                       "; no copy could be made, so the file is left as it is")
        if kept is not None:
            try:
                self._save()
            except Exception:
                logger.warning("the repaired skill usage sidecar %s could not be saved", self.path.name,
                               exc_info=True)

    @staticmethod
    def _parse(raw: Any) -> tuple[dict[str, dict], int, int]:
        """The usable rows of a parsed sidecar, how many entries were dropped because they
        are not records, and how many rows had a field repaired."""
        items = raw.get("skills", {}) if isinstance(raw, dict) else {}
        items = items if isinstance(items, dict) else {}
        out: dict[str, dict] = {}
        dropped = repaired = 0
        for name, rec in items.items():
            if not isinstance(rec, dict):
                dropped += 1
                continue
            repaired += 1 if _repair(rec) else 0
            out[str(name)] = rec
        return out, dropped, repaired

    def _deserialize(self, raw) -> None:
        self._items = self._parse(raw)[0]

    def _set_aside(self, *, move: bool) -> Path | None:
        """Keep the sidecar as it is under ``<name>.corrupt-<time>`` (moved, or copied),
        and prune older copies down to :data:`CORRUPT_COPIES_KEPT`."""
        if self.path is None:
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            if move:
                os.replace(self.path, dest)
            else:
                shutil.copyfile(self.path, dest)
        except OSError:
            logger.error("the skill usage sidecar %s could not be set aside", self.path.name, exc_info=True)
            return None
        try:
            copies = sorted(self.path.parent.glob(f"{self.path.name}.corrupt-*"), key=lambda p: p.name)
            for old in copies[:-CORRUPT_COPIES_KEPT]:
                old.unlink(missing_ok=True)
        except OSError:
            logger.warning("older copies of the skill usage sidecar could not be pruned", exc_info=True)
        return dest

    def _serialize(self):
        return {"skills": self._items}

    @staticmethod
    def _fresh() -> dict:
        return {
            "origin": ORIGIN_UNKNOWN, "source": "", "agent_created": False, "write_origin": "",
            "created_at": _now_iso(), "fingerprint": "",
            "use_count": 0, "view_count": 0, "patch_count": 0,
            "last_used_at": None, "last_viewed_at": None, "last_patched_at": None,
            "pinned": False, "state": STATE_ACTIVE, "archived_at": None,
        }

    def _rec(self, name: str) -> dict:
        rec = self._items.get(name)
        if isinstance(rec, dict):
            return rec
        self._items[name] = rec = self._fresh()
        return rec

    def _snapshot(self, names) -> dict[str, dict | None]:
        return {str(n): (dict(row) if isinstance(row := self._items.get(str(n)), dict) else None) for n in names}

    def _restore(self, before: dict[str, dict | None]) -> None:
        """Put rows back as they were before a write that did not reach the disk, so what
        this process answers never differs from what the file holds."""
        for name, row in before.items():
            if row is None:
                self._items.pop(name, None)
            else:
                self._items[name] = row

    def _commit(self, before: dict[str, dict | None]) -> None:
        try:
            self._save()
        except BaseException:
            self._restore(before)
            raise

    # ── creation ──────────────────────────────────────────────────────────────────

    def start(self, name: str, *, agent_created: bool = False, write_origin: str = "",
              origin: str | None = None) -> dict:
        """Open a fresh row for ``name`` unconditionally and vouch that the skill is
        installed. For a caller that holds no loader (tests, tools); the loader's own
        creation paths go through :meth:`reconcile_origins` with ``created`` instead,
        which keeps the row when the bytes are the ones it knew."""
        key = str(name)
        with self._lock:
            before = self._snapshot([key])
            rec = self._fresh()
            rec["agent_created"] = agent_created is True
            rec["write_origin"] = write_origin if agent_created is True and _word(write_origin, _WRITE_ORIGINS) else ""
            rec["origin"] = origin if _word(origin, _ORIGINS) else (
                ORIGIN_AGENT if agent_created is True else ORIGIN_UNKNOWN)
            self._items[key] = rec
            self._commit(before)
            self._registered.add(key)
            return dict(rec)

    def note_created(self, name: str, origin: str = ORIGIN_AGENT) -> dict:
        """Record a new skill and its provenance at creation time. ``agent`` sets the
        sticky agent marker (written by the agent's own initiative, so curatable)."""
        agent = origin == ORIGIN_AGENT
        return self.start(name, agent_created=agent, write_origin=WRITE_LEARNING if agent else "", origin=origin)

    def mark_agent_created(self, name: str, write_origin: str = "") -> dict:
        """Set the sticky agent marker on ``name``'s row, with who wrote the skill. The
        only writer of the marker besides :meth:`start`; nothing but an explicit removal
        clears it."""
        key = str(name)
        with self._lock:
            before = self._snapshot([key])
            rec = self._rec(key)
            rec["agent_created"] = True
            rec["write_origin"] = write_origin if _word(write_origin, _WRITE_ORIGINS) else ""
            if rec.get("origin") in (ORIGIN_LOCAL, ORIGIN_UNKNOWN):
                rec["origin"] = ORIGIN_AGENT
            self._commit(before)
            return dict(rec)

    # ── provenance ────────────────────────────────────────────────────────────────

    def reconcile_origins(self, observed: dict[str, tuple], *, full: bool = False) -> list[str]:
        """H349 — record where each registered skill came from, as its folder shows it.

        ``observed`` maps a registered skill's name to ``(origin, source[, fingerprint[,
        created]])``: ``bundled`` (it ships with Nerva), or ``import`` with the source its
        install record names, or ``(None, "")`` when the folder carries no install record;
        then the row reads ``agent`` when the skill carries the agent marker and ``local``
        otherwise. ``agent_created`` is never changed here: an install record beside an
        agent-made skill is shown next to the marker, it does not replace it.

        The row of a name is that skill's row, wherever its folder lives. It is replaced
        by a fresh one only on evidence in the bytes, in two cases:

        - ``created``: a creation path just made this skill (generation, a batch create,
          an install into a new folder) and its fingerprint is not the one the row last
          saw. Whatever held the name before is not this skill, so nothing of it — pin,
          agent marker, origin, counters — is inherited. The same bytes are the same
          skill and keep the row.
        - a tombstone (an explicit removal happened) under which other bytes register. The
          same bytes are a restore: the state comes back and the idle clock restarts
          (``restored_at``, and ``restore_pending`` until the curator's next pass settles
          it on its own clock), so the curator does not archive it again at once. A tombstone
          from before fingerprints were kept cannot be compared: its counters stay, the
          agent marker does not.

        Names that are not in ``observed`` are never touched (second review, B2): a skill
        that is not seen — its folder moved, missing, unreadable, on a volume that is away
        — keeps its row exactly as it is. ``full`` only says ``observed`` is every
        registered skill, which is what "installed now" then means to :meth:`pin` and
        :meth:`stats`. One lock, one write, only when a row changed; the names whose row
        changed come back. A failed write leaves every row as it was and raises."""
        changed: list[str] = []
        with self._lock:
            names = [str(n) for n in observed]
            before = self._snapshot(names)
            for raw_name, seen in observed.items():
                name = str(raw_name)
                origin, source = seen[0], seen[1]
                fingerprint = seen[2] if len(seen) > 2 and isinstance(seen[2], str) else ""
                created = bool(seen[3]) if len(seen) > 3 else False
                rec = self._items.get(name)
                was = dict(rec) if isinstance(rec, dict) else None
                if not isinstance(rec, dict):
                    rec = self._fresh()
                elif rec.get("state") == STATE_ARCHIVED:
                    known = rec.get("fingerprint") or ""
                    if known and fingerprint and fingerprint != known:
                        rec = self._fresh()                                  # other bytes after a removal
                    elif known and not fingerprint:
                        pass                    # these bytes could not be read: nothing is decided
                    else:
                        rec["state"], rec["archived_at"], rec["restored_at"] = STATE_ACTIVE, None, _now_iso()
                        rec["restore_pending"] = True        # until the curator's next pass sees it
                        if not known:
                            rec["agent_created"], rec["write_origin"] = False, ""
                elif created and (not fingerprint or rec.get("fingerprint") != fingerprint):
                    rec = self._fresh()                                      # a new skill took the name
                self._items[name] = rec
                if fingerprint:
                    rec["fingerprint"] = fingerprint
                if origin == ORIGIN_BUNDLED:
                    rec["origin"], rec["source"] = ORIGIN_BUNDLED, ""
                elif origin == ORIGIN_IMPORT:
                    rec["origin"], rec["source"] = ORIGIN_IMPORT, _stored_source(source)
                else:
                    rec["origin"] = ORIGIN_AGENT if rec.get("agent_created") is True else ORIGIN_LOCAL
                    rec["source"] = ""
                if rec != was:
                    changed.append(name)
            if changed:
                self._commit(before)
            if full:
                self._registered = set(names)
                self._synced = True
            else:
                self._registered.update(names)
        return changed

    def settle_restore(self, name: str, when: str) -> None:
        """The curator saw the restored skill ``name`` at ``when`` (its own clock): the
        idle clock restarts there. Until then the row carries ``restore_pending`` and the
        curator leaves the skill alone, so a restore is never undone by the pass that
        follows it, whatever clock the pass runs on."""
        key = str(name)
        with self._lock:
            rec = self._items.get(key)
            if not isinstance(rec, dict):
                return
            before = self._snapshot([key])
            rec["restored_at"] = when if isinstance(when, str) and when else _now_iso()
            rec.pop("restore_pending", None)
            self._commit(before)

    def unregister(self, name: str) -> None:
        """``name`` is not a registered skill right now (its folder is not there). Only
        what "installed now" means changes; the row is not touched."""
        with self._lock:
            self._registered.discard(str(name))

    # ── counters, pin, lifecycle ──────────────────────────────────────────────────

    def bump(self, name: str, kind: str) -> None:
        """Best-effort counter bump — a broken sidecar never breaks the call."""
        keys = _BUMP_KEYS.get(kind)
        if keys is None or not name:
            return
        count_key, ts_key = keys
        # A skill runs on the event loop, and a removal may hold the lock across a folder
        # move (review m2): wait for it only briefly. A counter that is not counted is the
        # best-effort contract; a stalled loop is not.
        if not self._lock.acquire(timeout=BUMP_WAIT_SECONDS):
            logger.debug("usage bump skipped for %s/%s: the sidecar is busy with a removal", name, kind)
            return
        try:
            rec = self._rec(str(name))
            rec[count_key] = _count(rec.get(count_key)) + 1
            rec[ts_key] = _now_iso()
            if rec.get("state") == STATE_STALE:
                rec["state"] = STATE_ACTIVE      # activity reactivates
            self._save()
        except Exception:
            logger.debug("usage bump skipped for %s/%s", name, kind, exc_info=True)
        finally:
            self._lock.release()

    def pin(self, name: str, pinned: bool = True) -> dict:
        """H349 — pin or unpin one skill; the only writer of ``pinned``.

        Checked here, under the lock every writer of the row and every removal takes, so
        no caller can pin what the route would refuse. A pin needs a skill that is
        installed now: a name the loader has not registered in this process (never
        installed, removed, archived, away, or a row a counter made) is
        :class:`PinRefused` ``not_found`` — and the row is left exactly as it is; a skill
        that ships with Nerva is ``not_pinnable``, since nothing ages it out or deletes
        it. Unpinning any row is allowed. The stored flag is always a bool. The answer
        carries ``changed``; a write that fails leaves the row as it was and raises."""
        key = str(name)
        with self._lock:
            rec = self._items.get(key)
            if not isinstance(rec, dict):
                raise PinRefused("not_found", f"no installed skill named {key!r}")
            if pinned:
                if (key not in self._registered or rec.get("state") == STATE_ARCHIVED
                        or not _word(rec.get("origin"), _ORIGINS) or rec.get("origin") == ORIGIN_UNKNOWN):
                    raise PinRefused("not_found", f"no installed skill named {key!r}")
                if rec.get("origin") == ORIGIN_BUNDLED:
                    raise PinRefused("not_pinnable", f"{key!r} ships with Nerva: nothing ages it out or "
                                     "deletes it, so there is nothing to pin")
            changed = rec.get("pinned") is not bool(pinned)
            if changed:
                before = self._snapshot([key])
                rec["pinned"] = bool(pinned)
                self._commit(before)
            return {**rec, "changed": changed}

    def is_pinned(self, name: str) -> bool:
        """Whether the owner's pin is set, as shown: only an exact ``true``."""
        rec = self._items.get(str(name))
        return isinstance(rec, dict) and rec.get("pinned") is True

    def pin_blocks(self, name: str) -> bool:
        """Whether automation must leave the skill alone: pinned, or a pin flag that
        cannot be read as "not pinned" (the stricter side for the curator and an agent's
        delete; the owner's own removals do not ask)."""
        return _pin_blocks(self._items.get(str(name)))

    def set_state(self, name: str, state: str) -> dict | None:
        if not _word(state, _VALID_STATES):
            return None
        with self._lock:
            rec = self._rec(str(name))
            rec["state"] = state
            rec["archived_at"] = (rec.get("archived_at") or _now_iso()) if state == STATE_ARCHIVED else None
            self._save()
            return dict(rec)

    # ── removal: the only acts that end a row ─────────────────────────────────────

    def forget(self, name: str) -> bool:
        """An explicit removal for good (a batch delete, an uninstall, a reject from
        review): the row goes with the skill — pin, agent marker, origin and counters.
        They described that skill; one that takes the name later starts from zero. Never
        called because a skill was merely not seen."""
        key = str(name)
        with self._lock:
            self._registered.discard(key)
            if key not in self._items:
                return False
            before = self._snapshot([key])
            del self._items[key]
            self._commit(before)
            return True

    def retire(self, name: str, fingerprint: str | None = "") -> bool:
        """An explicit removal into an archive the owner can move back (the curator's
        archive, the journey's forget): the row becomes a tombstone. State ``archived``
        and ``archived_at`` say so; the pin is cleared (nothing is installed to protect);
        the counters, the origin and the agent marker stay, bound to the fingerprint of
        the removed bytes — ``fingerprint`` when given, else the one the row last saw.
        Only those bytes registering again get them back (:meth:`reconcile_origins`)."""
        key = str(name)
        with self._lock:
            self._registered.discard(key)
            rec = self._items.get(key)
            if not isinstance(rec, dict):
                return False
            before = self._snapshot([key])
            rec["state"], rec["archived_at"] = STATE_ARCHIVED, _now_iso()
            rec["pinned"] = False
            if isinstance(fingerprint, str) and fingerprint:
                rec["fingerprint"] = fingerprint
            self._commit(before)
            return True

    @contextmanager
    def removal(self, names, *, respect_pins: bool) -> Iterator[_Removal]:
        """Hold the lock every pin write takes while a caller removes skills (review M4).

        ``blocked`` lists the names a pin protects when ``respect_pins`` (automation: the
        curator, an agent's batch; the journey's forget); the caller removes nothing
        then. Otherwise it moves the folders and calls ``forget`` / ``retire`` on what it
        removed, all before a pin can land: a pin asked for meanwhile waits, and is then
        answered against a skill that is no longer installed. Readers do not wait."""
        with self._lock:
            blocked = [str(n) for n in names if respect_pins and _pin_blocks(self._items.get(str(n)))]
            yield _Removal(self, blocked)

    # ── reads (no lock: see the class docstring) ──────────────────────────────────

    def get(self, name: str) -> dict | None:
        rec = self._items.get(name)
        return dict(rec) if isinstance(rec, dict) and rec else None

    def list(self) -> dict:
        return {k: dict(v) for k, v in list(self._items.items()) if isinstance(v, dict)}

    def curatable(self, name: str) -> bool:
        """Only what the agent made on its own initiative, unpinned and not archived, may
        be curated. Every doubt reads as "leave it alone": the marker must be exactly
        true, the write origin must not be a turn's tool call (Hermes: a skill the user
        asked a foreground agent for is theirs), the pin flag must read as not pinned, and
        a skill that ships with Nerva is never curated."""
        rec = self.get(str(name))
        return bool(rec is not None
                    and rec.get("agent_created") is True
                    and rec.get("write_origin") != WRITE_TOOL
                    and rec.get("origin") != ORIGIN_BUNDLED
                    and not _pin_blocks(rec)
                    and rec.get("state", STATE_ACTIVE) in (STATE_ACTIVE, STATE_STALE))

    def stats(self) -> dict:
        """Counts over the sidecar. ``total`` is the installed skills' rows: once a loader
        has reported its skills, the rows of the ones registered now; before that, every
        row that is not a tombstone. ``not_installed`` counts the rows kept for skills
        that are not registered now (away, moved, removed by hand) — kept, not counted."""
        registered, synced = set(self._registered), self._synced
        by_state, by_origin, total, absent = {}, {}, 0, 0
        for name, r in self.list().items():
            state = r.get("state") if _word(r.get("state"), _VALID_STATES) else "?"
            by_state[state] = by_state.get(state, 0) + 1
            if state == STATE_ARCHIVED:
                continue
            if synced and name not in registered:
                absent += 1
                continue
            total += 1
            origin = r.get("origin") if _word(r.get("origin"), _ORIGINS) else "?"
            by_origin[origin] = by_origin.get(origin, 0) + 1
        return {"total": total, "by_state": by_state, "by_origin": by_origin, "not_installed": absent}

    def summary(self, name: str) -> dict:
        """The owner-facing counters of one skill (see :func:`usage_summary`)."""
        return usage_summary(self, name)


def clean_source(value: Any) -> str:
    """The label of where an import came from, as an install record inside the skill's
    folder names it, or ``""`` (review m2). That file can be edited by hand and the label
    is shown to every user of ``GET /skills``, so only a known source
    (:data:`KNOWN_SOURCES`) or something shaped like a GitHub repository name is accepted:
    letters, digits, ``_ . -``, at most 39 characters. Never a URL, a path, ``:`` or
    ``@``; never a word Nerva uses for its own labels (``marketplace`` is said only by the
    marketplace installer's marker, see ``loader.origin_evidence``); and never something
    shaped like a credential (a known token prefix, or a long unbroken run of letters and
    digits such as a hex digest or base64)."""
    text = value.strip() if isinstance(value, str) else ""
    if text in KNOWN_SOURCES:
        return text
    if not text or not _REPO_NAME_RE.fullmatch(text) or ".." in text or text.lower() in _RESERVED_SOURCES:
        return ""
    if _TOKEN_PREFIX_RE.match(text):
        return ""
    for run in _ALNUM_RUN_RE.findall(text):
        mixed_case = sum(c.isupper() for c in run) >= 4 and sum(c.islower() for c in run) >= 4
        if any(c.isdigit() for c in run) or mixed_case:
            return ""
    return text


def _stored_source(value: Any) -> str:
    """A source as the sidecar keeps it: :func:`clean_source`, or the marketplace word the
    loader passes when the installer's own marker said so."""
    if isinstance(value, str) and value == SOURCE_MARKETPLACE:
        return SOURCE_MARKETPLACE
    return clean_source(value)


def usage_summary(store: Any, name: str) -> dict:
    """H354 — the counters the owner reads: how often a skill ran, was viewed and was
    patched, and when last; plus provenance, lifecycle state and the pin.

    Read-only: ``store.get`` never creates a row, so listing a skill leaves the sidecar
    exactly as it was. Zeros (origin ``unknown``, state ``active``) for a skill the sidecar
    never saw, and for no usable store at all (the orchestrator's learning init failed, or
    a test double stands in) — a counter the owner asked for must never fail the listing.

    H349 — ``origin`` is what the loader recorded when it registered the skill
    (``bundled``, ``import`` with its ``source``, ``agent``, ``local``). ``agent_created``
    is the sticky agent marker, shown beside an install record when both are true, and
    ``write_origin`` who wrote an agent-made skill. ``pinned`` is true only for an exact
    stored ``true``. ``pinnable`` is whether :meth:`SkillUsageStore.pin` would take a pin
    on this row (an origin was recorded and the skill does not ship with Nerva).
    """
    rec = None
    get = getattr(store, "get", None)
    if callable(get):
        try:
            rec = get(name)
        except Exception:
            logger.debug("usage read skipped for %s", name, exc_info=True)
    if not isinstance(rec, dict):
        rec = {}

    def _when(key: str) -> str | None:
        value = rec.get(key)
        return value if isinstance(value, str) and value else None

    origin = rec.get("origin") if _word(rec.get("origin"), _ORIGINS) else ORIGIN_UNKNOWN
    state = rec.get("state") if _word(rec.get("state"), _VALID_STATES) else STATE_ACTIVE
    agent = rec.get("agent_created") is True
    write_origin = rec.get("write_origin")
    return {
        "use_count": _count(rec.get("use_count")),
        "view_count": _count(rec.get("view_count")),
        "patch_count": _count(rec.get("patch_count")),
        "last_used_at": _when("last_used_at"),
        "last_viewed_at": _when("last_viewed_at"),
        "last_patched_at": _when("last_patched_at"),
        "origin": origin,
        "source": _stored_source(rec.get("source")) if origin == ORIGIN_IMPORT else "",
        "agent_created": agent,
        "write_origin": write_origin if agent and _word(write_origin, _WRITE_ORIGINS) else "",
        "state": state,
        "pinned": rec.get("pinned") is True,
        "pinnable": bool(rec) and origin not in (ORIGIN_BUNDLED, ORIGIN_UNKNOWN) and state != STATE_ARCHIVED,
    }


__all__ = ["SkillUsageStore", "latest_activity_at", "usage_summary",
           "STATE_ACTIVE", "STATE_STALE", "STATE_ARCHIVED",
           "ORIGIN_AGENT", "ORIGIN_IMPORT", "ORIGIN_BUNDLED", "ORIGIN_LOCAL", "ORIGIN_UNKNOWN",
           "WRITE_BACKGROUND", "WRITE_LEARNING", "WRITE_TOOL", "KNOWN_SOURCES", "SOURCE_MARKETPLACE",
           "CORRUPT_COPIES_KEPT", "PinRefused", "clean_source"]
