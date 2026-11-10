"""
usage.py — skill usage telemetry + provenance (H20.5 live wave, H354, H349).

Sidecar JsonStore (runtime data root, never the repo `skills/` tree) tracking
per-skill counters, provenance, the owner's pin and lifecycle state. The curator reads the
derived latest-activity timestamp to decide active → stale → archived
transitions; only **agent-created, unpinned** skills are ever curatable.

One row belongs to one skill (H349 review M1). A row is made when the loader registers a
skill and retired when the skill goes: :meth:`SkillUsageStore.forget` drops it (a skill
that is gone for good), :meth:`SkillUsageStore.retire` leaves a tombstone (a skill moved to
an archive the owner can move back: state, counters and the agent marker are kept for the
same bytes, the pin is not). A skill that later takes the name starts from a fresh row, so
it never inherits a pin, an agent marker, an origin or a counter.

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
_VALID_STATES = {STATE_ACTIVE, STATE_STALE, STATE_ARCHIVED}

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
_ORIGINS = {ORIGIN_AGENT, ORIGIN_IMPORT, ORIGIN_BUNDLED, ORIGIN_LOCAL, ORIGIN_UNKNOWN}

# H349 (review m3) — who wrote an agent-made skill, as Hermes's write origin tells them
# apart: the background review and the learning loop are the agent's own initiative (the
# curator manages those); a skill the model wrote with its skill tools inside a turn was
# asked for in that turn and is never auto-curated.
WRITE_BACKGROUND = "background_review"
WRITE_LEARNING = "learning"
WRITE_TOOL = "assistant_tool"
_WRITE_ORIGINS = {WRITE_BACKGROUND, WRITE_LEARNING, WRITE_TOOL}

#: Where an import can come from (review m2): the local installs the migration importer
#: reads (``importer.MIGRATION_SOURCES``) and the two upstream catalogs. Anything else an
#: install record names is shown only when it is a bare repository name.
KNOWN_SOURCES = ("hermes", "openclaw", "claude-code")
SOURCE_MARKETPLACE = "marketplace"       # only the marketplace installer's own marker says so
_RESERVED_SOURCES = {SOURCE_MARKETPLACE, "bundled", "agent", "local", "unknown", "import", "nerva", "owner"}
_REPO_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")

_COUNTERS = ("use_count", "view_count", "patch_count", "switch_on_count")
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
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def latest_activity_at(record: dict) -> datetime | None:
    """Newest use/view/patch/switch-on timestamp (creation intentionally excluded)."""
    latest = None
    for key in ("last_used_at", "last_viewed_at", "last_patched_at", "last_switched_on_at"):
        dt = _parse_iso(record.get(key))
        if dt is not None and (latest is None or dt > latest):
            latest = dt
    return latest


def _count(value: Any) -> int:
    """A stored counter as a non-negative int; anything else counts as zero."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _pin_blocks(rec: Any) -> bool:
    """Whether a row stops automation (the curator, an agent's delete). Only an exact
    ``false`` or no flag at all reads as "not pinned" here: a flag that is not a bool is
    left alone by automation, which is the stricter side for these readers."""
    return isinstance(rec, dict) and rec.get("pinned") not in (False, None)


def _repair(rec: dict) -> dict:
    """Bring one stored row to the shapes the readers rely on (review M3), in place.

    Counters that are not non-negative ints restart at zero, so a later bump counts again
    instead of failing; an origin, state, source or write origin that is not one of the
    known words reads as unknown / active / empty. ``agent_created`` is the sticky agent
    marker: a row from before it existed takes it from its ``agent`` origin, and anything
    that is not exactly ``true`` is not agent-made (the stricter side for the curator,
    which then never touches the skill). ``pinned`` is kept as stored: each reader decides
    (:func:`_pin_blocks`, :meth:`SkillUsageStore.is_pinned`)."""
    for key in _COUNTERS:
        if key in rec or key != "switch_on_count":
            rec[key] = _count(rec.get(key))
    origin = rec.get("origin")
    if "agent_created" not in rec:
        rec["agent_created"] = origin == ORIGIN_AGENT
    else:
        rec["agent_created"] = rec["agent_created"] is True
    rec["origin"] = origin if isinstance(origin, str) and origin in _ORIGINS else ORIGIN_UNKNOWN
    rec["state"] = rec.get("state") if rec.get("state") in _VALID_STATES else STATE_ACTIVE
    rec["source"] = _stored_source(rec.get("source")) if rec["origin"] == ORIGIN_IMPORT else ""
    rec["write_origin"] = rec.get("write_origin") if rec.get("write_origin") in _WRITE_ORIGINS else ""
    for key in ("folder", "fingerprint"):
        rec[key] = rec.get(key) if isinstance(rec.get(key), str) else ""
    for key in ("last_used_at", "last_viewed_at", "last_patched_at", "created_at", "archived_at"):
        rec[key] = rec.get(key) if isinstance(rec.get(key), str) and rec.get(key) else None
    if "pinned" not in rec:
        rec["pinned"] = False
    return rec


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
    """Per-skill telemetry: counters, provenance, pin flag, lifecycle state."""

    def __init__(self, path: str | Path | None = None) -> None:
        # The names a loader has registered in this process (or a creator vouched for):
        # what "installed now" means to :meth:`pin`. Not persisted — a row on disk says
        # what a skill was, not that it is installed.
        self._registered: set[str] = set()
        super().__init__(path)
        # Re-entrant: a removal holds the lock across its folder move, and the reload that
        # follows reaches the store again on the same thread (review M4).
        self._lock = threading.RLock()

    # ── persistence ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Read the sidecar; a file that does not parse is set aside, never silently
        replaced (review M3): it is moved to ``<name>.corrupt-<time>`` beside it, a warning
        names both files (never the contents), and the store starts empty."""
        raw: Any = {}
        if self.path is not None and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or not isinstance(raw.get("skills", {}), dict):
                    raise ValueError("not a skill usage sidecar")
            except Exception as exc:
                kept = self._set_aside(move=True)
                logger.warning("the skill usage sidecar %s could not be read (%s); it was %s and the hub starts "
                               "with no pins, agent markers or counters", self.path.name, type(exc).__name__,
                               f"kept as {kept.name}" if kept else "left in place (it could not be moved)")
                raw = {}
        self._deserialize(raw)

    def _set_aside(self, *, move: bool) -> Path | None:
        if self.path is None:
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            if move:
                os.replace(self.path, dest)
            else:
                shutil.copyfile(self.path, dest)
            return dest
        except OSError:
            logger.error("the skill usage sidecar %s could not be set aside", self.path.name, exc_info=True)
            return None

    def _serialize(self):
        return {"skills": self._items}

    def _deserialize(self, raw) -> None:
        items = raw.get("skills", {}) if isinstance(raw, dict) else {}
        items = items if isinstance(items, dict) else {}
        bad = sorted(str(name) for name, rec in items.items() if not isinstance(rec, dict))
        if bad:
            kept = self._set_aside(move=False)
            logger.warning("the skill usage sidecar %s holds %d row(s) that are not records; they are dropped%s",
                           self.path.name if self.path else "(memory)", len(bad),
                           f" (the file as it was is kept as {kept.name})" if kept else "")
        self._items = {str(name): _repair(rec) for name, rec in items.items() if isinstance(rec, dict)}

    @staticmethod
    def _fresh() -> dict:
        return {
            "origin": ORIGIN_UNKNOWN, "source": "", "agent_created": False, "write_origin": "",
            "created_at": _now_iso(), "folder": "", "fingerprint": "",
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
        """A new skill took ``name``: its row starts fresh, whatever an earlier holder of
        the name left (pin, agent marker, origin, counters, tombstone). ``agent_created``
        is the sticky marker only this call sets; ``write_origin`` says who wrote it."""
        key = str(name)
        with self._lock:
            before = self._snapshot([key])
            rec = self._fresh()
            rec["agent_created"] = agent_created is True
            rec["write_origin"] = write_origin if agent_created is True and write_origin in _WRITE_ORIGINS else ""
            rec["origin"] = origin if origin in _ORIGINS else (ORIGIN_AGENT if agent_created is True else ORIGIN_UNKNOWN)
            self._items[key] = rec
            self._commit(before)
            self._registered.add(key)
            return dict(rec)

    def note_created(self, name: str, origin: str = ORIGIN_AGENT) -> dict:
        """Record a new skill and its provenance at creation time. ``agent`` sets the
        sticky agent marker (written by the agent's own initiative, so curatable)."""
        agent = origin == ORIGIN_AGENT
        return self.start(name, agent_created=agent, write_origin=WRITE_LEARNING if agent else "", origin=origin)

    # ── provenance ────────────────────────────────────────────────────────────────

    def reconcile_origins(self, observed: dict[str, tuple], *, full: bool = False,
                          present: Any = (), sweep_unplaced: bool = True) -> list[str]:
        """H349 — record where each registered skill came from, as its folder shows it.

        ``observed`` maps a registered skill's name to ``(origin, source[, folder[,
        fingerprint]])``: ``bundled`` (it ships with Nerva), or ``import`` with the source
        its install record names, or ``(None, "")`` when the folder carries no install
        record; then the row reads ``agent`` when the skill carries the agent marker and
        ``local`` otherwise. ``agent_created`` is never changed here: an install record
        beside an agent-made skill is shown next to the marker, it does not replace it.

        The row must be this skill's (review M1). A row recorded for another folder, or a
        tombstone whose bytes are not the ones registering now, belonged to an earlier
        holder of the name and is replaced by a fresh row; a tombstone with the same
        fingerprint is a restore, and gets its state back.

        ``full`` says ``observed`` is every registered skill: rows of skills that are
        gone are then retired. A row whose recorded folder no longer exists (while its
        parent does) is forgotten; a row with no recorded folder that is neither
        registered, nor in ``present`` (installed but not loaded), nor a tombstone loses
        its pin and agent marker (skipped with ``sweep_unplaced`` false, when the owner's
        skills were not read at all). One lock, one write, only when something changed;
        the names whose row changed come back. A failed write leaves every row as it was
        and raises."""
        changed: list[str] = []
        with self._lock:
            names = [str(n) for n in observed]
            before = self._snapshot(list(self._items) if full else names)
            for raw_name, seen in observed.items():
                name = str(raw_name)
                origin, source = seen[0], seen[1]
                folder = str(seen[2]) if len(seen) > 2 and seen[2] else ""
                fingerprint = str(seen[3]) if len(seen) > 3 and seen[3] else ""
                rec = self._items.get(name)
                was = dict(rec) if isinstance(rec, dict) else None
                if not isinstance(rec, dict):
                    rec = self._fresh()
                elif rec.get("state") == STATE_ARCHIVED:
                    if fingerprint and rec.get("fingerprint") == fingerprint:
                        rec["state"], rec["archived_at"] = STATE_ACTIVE, None      # the same bytes came back
                    else:
                        rec = self._fresh()
                elif folder and rec.get("folder") and rec["folder"] != folder:
                    rec = self._fresh()
                self._items[name] = rec
                if folder:
                    rec["folder"] = folder
                rec["fingerprint"] = ""
                if origin == ORIGIN_BUNDLED:
                    rec["origin"], rec["source"] = ORIGIN_BUNDLED, ""
                elif origin == ORIGIN_IMPORT:
                    rec["origin"], rec["source"] = ORIGIN_IMPORT, _stored_source(source)
                else:
                    rec["origin"] = ORIGIN_AGENT if rec.get("agent_created") is True else ORIGIN_LOCAL
                    rec["source"] = ""
                if rec != was:
                    changed.append(name)
            if full:
                kept = {str(n) for n in present}
                for name in [n for n in self._items if n not in observed]:
                    rec = self._items[name]
                    if rec.get("state") == STATE_ARCHIVED or name in kept:
                        continue
                    folder = rec.get("folder") or ""
                    if folder:
                        path = Path(folder)
                        try:
                            gone = path.parent.is_dir() and not path.exists()
                        except OSError:
                            gone = False
                        if gone:
                            del self._items[name]
                            changed.append(name)
                    elif sweep_unplaced and (rec.get("pinned") is not False or rec.get("agent_created")):
                        rec["pinned"], rec["agent_created"], rec["write_origin"] = False, False, ""
                        if rec.get("origin") == ORIGIN_AGENT:
                            rec["origin"] = ORIGIN_UNKNOWN
                        changed.append(name)
            if changed:
                self._commit(before)
            if full:
                self._registered = set(names)
            else:
                self._registered.update(names)
        return changed

    # ── counters, pin, lifecycle ──────────────────────────────────────────────────

    def bump(self, name: str, kind: str) -> None:
        """Best-effort counter bump — a broken sidecar never breaks the call."""
        keys = _BUMP_KEYS.get(kind)
        if keys is None or not name:
            return
        count_key, ts_key = keys
        try:
            with self._lock:
                rec = self._rec(str(name))
                rec[count_key] = _count(rec.get(count_key)) + 1
                rec[ts_key] = _now_iso()
                if rec.get("state") == STATE_STALE:
                    rec["state"] = STATE_ACTIVE      # activity reactivates
                self._save()
        except Exception:
            logger.debug("usage bump skipped for %s/%s", name, kind, exc_info=True)

    def pin(self, name: str, pinned: bool = True) -> dict:
        """H349 — pin or unpin one skill; the only writer of ``pinned``.

        Checked here, under the lock every writer of the row and every removal takes, so
        no caller can pin what the route would refuse. A pin needs a skill that is
        installed now: a name the loader has not registered in this process (never
        installed, removed, archived, or a row a counter made) is :class:`PinRefused`
        ``not_found``; a skill that ships with Nerva is ``not_pinnable``, since nothing
        ages it out or deletes it. Unpinning any row is allowed. The stored flag is always
        a bool. The answer carries ``changed``; a write that fails leaves the row as it
        was and raises."""
        key = str(name)
        with self._lock:
            rec = self._items.get(key)
            if not isinstance(rec, dict):
                raise PinRefused("not_found", f"no installed skill named {key!r}")
            if pinned:
                if (key not in self._registered or rec.get("state") == STATE_ARCHIVED
                        or rec.get("origin") in (None, "", ORIGIN_UNKNOWN)):
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
        with self._lock:
            rec = self._items.get(str(name))
            return isinstance(rec, dict) and rec.get("pinned") is True

    def pin_blocks(self, name: str) -> bool:
        """Whether automation must leave the skill alone: pinned, or a pin flag that
        cannot be read as "not pinned" (the stricter side for the curator and an agent's
        delete; the owner's own removals do not ask)."""
        with self._lock:
            return _pin_blocks(self._items.get(str(name)))

    def set_state(self, name: str, state: str) -> dict | None:
        if state not in _VALID_STATES:
            return None
        with self._lock:
            rec = self._rec(str(name))
            rec["state"] = state
            rec["archived_at"] = (rec.get("archived_at") or _now_iso()) if state == STATE_ARCHIVED else None
            self._save()
            return dict(rec)

    # ── removal ───────────────────────────────────────────────────────────────────

    def forget(self, name: str) -> bool:
        """The skill is gone for good (uninstalled, rejected from review, removed by
        hand): its row goes with it — pin, agent marker, origin and counters. They
        described that skill; one that takes the name later starts from zero."""
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
        """The skill's folder moved to an archive the owner can move back (the curator's
        archive, a batch delete's backup): its row becomes a tombstone. State
        ``archived`` and ``archived_at`` say so; the pin is cleared (nothing is installed
        to protect); the counters, the origin and the agent marker stay, bound to
        ``fingerprint`` — only the same bytes registering again get them back
        (:meth:`reconcile_origins`), anything else under the name starts fresh."""
        key = str(name)
        with self._lock:
            self._registered.discard(key)
            rec = self._items.get(key)
            if not isinstance(rec, dict):
                return False
            before = self._snapshot([key])
            rec["state"], rec["archived_at"] = STATE_ARCHIVED, _now_iso()
            rec["pinned"] = False
            rec["fingerprint"] = fingerprint if isinstance(fingerprint, str) else ""
            self._commit(before)
            return True

    @contextmanager
    def removal(self, names, *, respect_pins: bool) -> Iterator[_Removal]:
        """Hold the lock every pin write takes while a caller removes skills (review M4).

        ``blocked`` lists the names a pin protects when ``respect_pins`` (automation: the
        curator, an agent's batch; the journey's forget); the caller removes nothing
        then. Otherwise it moves the folders and calls ``forget`` / ``retire`` on what it
        removed, all before a pin can land: a pin asked for meanwhile waits, and is then
        answered against a skill that is no longer installed."""
        with self._lock:
            blocked = [str(n) for n in names if respect_pins and _pin_blocks(self._items.get(str(n)))]
            yield _Removal(self, blocked)

    # ── reads ─────────────────────────────────────────────────────────────────────

    def get(self, name: str) -> dict | None:
        with self._lock:
            rec = self._items.get(name)
            return dict(rec) if isinstance(rec, dict) and rec else None

    def list(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._items.items() if isinstance(v, dict)}

    def curatable(self, name: str) -> bool:
        """Only what the agent made on its own initiative, unpinned and not archived, may
        be curated. Every doubt reads as "leave it alone": the marker must be exactly
        true, the write origin must not be a turn's tool call (Hermes: a skill the user
        asked a foreground agent for is theirs), the pin flag must read as not pinned, and
        a skill that ships with Nerva is never curated."""
        with self._lock:
            rec = self._items.get(str(name))
            return bool(isinstance(rec, dict)
                        and rec.get("agent_created") is True
                        and rec.get("write_origin") != WRITE_TOOL
                        and rec.get("origin") != ORIGIN_BUNDLED
                        and not _pin_blocks(rec)
                        and rec.get("state", STATE_ACTIVE) in (STATE_ACTIVE, STATE_STALE))

    def stats(self) -> dict:
        """Counts over the sidecar. ``total`` is the installed skills' rows; a tombstone
        of an archived skill is counted under ``by_state`` only."""
        with self._lock:
            by_state, by_origin, total = {}, {}, 0
            for r in self._items.values():
                if not isinstance(r, dict):
                    continue
                state = str(r.get("state") or "?")
                by_state[state] = by_state.get(state, 0) + 1
                if state == STATE_ARCHIVED:
                    continue
                total += 1
                origin = str(r.get("origin") or "?")
                by_origin[origin] = by_origin.get(origin, 0) + 1
            return {"total": total, "by_state": by_state, "by_origin": by_origin}

    def summary(self, name: str) -> dict:
        """The owner-facing counters of one skill (see :func:`usage_summary`)."""
        return usage_summary(self, name)


def clean_source(value: Any) -> str:
    """The label of where an import came from, as an install record inside the skill's
    folder names it, or ``""`` (review m2). That file can be edited by hand and the label
    is shown to every user of ``GET /skills``, so only a known source
    (:data:`KNOWN_SOURCES`) or a bare repository name is accepted: letters, digits,
    ``_ . -``, at most 64 characters. Never a URL, a path, ``:`` or ``@``; and never a
    word Nerva uses for its own labels (``marketplace`` is said only by the marketplace
    installer's marker, see ``loader.origin_evidence``)."""
    text = value.strip() if isinstance(value, str) else ""
    if text in KNOWN_SOURCES:
        return text
    if not text or not _REPO_NAME_RE.fullmatch(text) or ".." in text or text.lower() in _RESERVED_SOURCES:
        return ""
    return text


def _stored_source(value: Any) -> str:
    """A source as the sidecar keeps it: :func:`clean_source`, or the marketplace word the
    loader passes when the installer's own marker said so."""
    return SOURCE_MARKETPLACE if value == SOURCE_MARKETPLACE else clean_source(value)


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
        return str(value) if value else None

    origin = rec.get("origin") if rec.get("origin") in _ORIGINS else ORIGIN_UNKNOWN
    agent = rec.get("agent_created") is True
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
        "write_origin": rec.get("write_origin") if agent and rec.get("write_origin") in _WRITE_ORIGINS else "",
        "state": rec.get("state") if rec.get("state") in _VALID_STATES else STATE_ACTIVE,
        "pinned": rec.get("pinned") is True,
        "pinnable": bool(rec) and origin not in (ORIGIN_BUNDLED, ORIGIN_UNKNOWN)
                    and rec.get("state") != STATE_ARCHIVED,
    }


__all__ = ["SkillUsageStore", "latest_activity_at", "usage_summary",
           "STATE_ACTIVE", "STATE_STALE", "STATE_ARCHIVED",
           "ORIGIN_AGENT", "ORIGIN_IMPORT", "ORIGIN_BUNDLED", "ORIGIN_LOCAL", "ORIGIN_UNKNOWN",
           "WRITE_BACKGROUND", "WRITE_LEARNING", "WRITE_TOOL", "KNOWN_SOURCES", "SOURCE_MARKETPLACE",
           "PinRefused", "clean_source"]
