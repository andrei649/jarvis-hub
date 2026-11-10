"""
usage.py — skill usage telemetry + provenance (H20.5 live wave).

Sidecar JsonStore (runtime data root, never the repo `skills/` tree) tracking
per-skill counters, provenance and lifecycle state. The curator reads the
derived latest-activity timestamp to decide active → stale → archived
transitions; only **agent-created, unpinned** skills are ever curatable.

Pattern adapted from hermes-agent `tools/skill_usage.py` (Nous Research, MIT)
— see LICENSES/THIRD_PARTY.md — rebuilt on jarvis's JsonStore (single-process
atomic persistence) instead of hermes's cross-process fcntl/msvcrt locking.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.core.persistence import JsonStore

logger = logging.getLogger("jarvis.skills.usage")

STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"
_VALID_STATES = {STATE_ACTIVE, STATE_STALE, STATE_ARCHIVED}

ORIGIN_AGENT = "agent"          # created by the agent (learning loop / [learn:])
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
_SOURCE_MAX = 64
_SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.:@/+-]*")


class PinRefused(Exception):
    """A pin the sidecar refused. ``reason``: ``not_found`` (no installed skill has this
    row) or ``not_pinnable`` (it ships with Nerva: nothing ages it out or deletes it)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason

_BUMP_KEYS = {"use": ("use_count", "last_used_at"),
              "view": ("view_count", "last_viewed_at"),
              "patch": ("patch_count", "last_patched_at"),
              # A recorded switch-on restarts the idle clock: a switched-off skill records
              # no use, and the curator must not count that time as neglect.
              "switch_on": ("switch_on_count", "last_switched_on_at")}


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


class SkillUsageStore(JsonStore):
    """Per-skill telemetry: counters, provenance, pin flag, lifecycle state."""

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"skills": self._items}

    def _deserialize(self, raw) -> None:
        items = raw.get("skills", {}) if isinstance(raw, dict) else {}
        self._items = items if isinstance(items, dict) else {}

    def _rec(self, name: str) -> dict:
        rec = self._items.get(name)
        if isinstance(rec, dict):
            return rec
        # A row that is not a record (a hand-edited or damaged sidecar) is replaced.
        self._items[name] = rec = self._fresh()
        return rec

    @staticmethod
    def _fresh() -> dict:
        return {
            "origin": ORIGIN_UNKNOWN, "source": "", "created_at": _now_iso(),
            "use_count": 0, "view_count": 0, "patch_count": 0,
            "last_used_at": None, "last_viewed_at": None, "last_patched_at": None,
            "pinned": False, "state": STATE_ACTIVE,
        }

    def _restore(self, before: dict[str, dict | None]) -> None:
        """Put rows back as they were before a write that did not reach the disk, so what
        this process answers never differs from what the file holds."""
        for name, row in before.items():
            if row is None:
                self._items.pop(name, None)
            else:
                self._items[name] = row

    def note_created(self, name: str, origin: str = ORIGIN_AGENT) -> dict:
        """Record provenance at creation time (the only trusted origin signal)."""
        with self._lock:
            rec = self._rec(str(name))
            rec["origin"] = origin
            rec["source"] = ""
            rec["created_at"] = _now_iso()
            self._save()
            return dict(rec)

    def reconcile_origins(self, observed: dict[str, tuple[str | None, str]]) -> list[str]:
        """H349 — record where each registered skill came from, as its folder shows it.

        ``observed`` maps a registered skill's name to ``(origin, source)``: ``bundled``
        (it ships with Nerva), or ``import`` with the source its install record names, or
        ``(None, "")`` when the folder carries no install record. With no record the row
        keeps ``agent`` (the creation-time marker, the only signal for it) and otherwise
        reads ``local``: a ``bundled``/``import`` left by a skill that used to hold the
        name does not describe the one installed now. An install record always wins over
        a stored ``agent``, so an imported skill that took an agent skill's name is never
        curated as agent-made. One lock, one write, and only when a row changed; the
        names whose origin or source changed come back. A write that fails leaves every
        row as it was and raises."""
        changed: list[str] = []
        with self._lock:
            before = {str(name): (dict(row) if isinstance(row := self._items.get(str(name)), dict) else None)
                      for name in observed}
            for name, (origin, source) in observed.items():
                rec = self._rec(str(name))
                if origin == ORIGIN_BUNDLED:
                    new_origin, new_source = ORIGIN_BUNDLED, ""
                elif origin == ORIGIN_IMPORT:
                    new_origin, new_source = ORIGIN_IMPORT, clean_source(source)
                elif rec.get("origin") == ORIGIN_AGENT:
                    new_origin, new_source = ORIGIN_AGENT, ""
                else:
                    new_origin, new_source = ORIGIN_LOCAL, ""
                if rec.get("origin") != new_origin or (rec.get("source") or "") != new_source:
                    rec["origin"], rec["source"] = new_origin, new_source
                    changed.append(str(name))
            if changed:
                try:
                    self._save()
                except BaseException:
                    self._restore(before)
                    raise
        return changed

    def bump(self, name: str, kind: str) -> None:
        """Best-effort counter bump — a broken sidecar never breaks the call."""
        keys = _BUMP_KEYS.get(kind)
        if keys is None or not name:
            return
        count_key, ts_key = keys
        try:
            with self._lock:
                rec = self._rec(str(name))
                rec[count_key] = int(rec.get(count_key) or 0) + 1
                rec[ts_key] = _now_iso()
                if rec.get("state") == STATE_STALE:
                    rec["state"] = STATE_ACTIVE      # activity reactivates
                self._save()
        except Exception:
            logger.debug("usage bump skipped for %s/%s", name, kind, exc_info=True)

    def pin(self, name: str, pinned: bool = True) -> dict:
        """H349 — pin or unpin one skill; the only writer of ``pinned``.

        Checked here, under the lock every writer of the row takes, so no caller can pin
        what the route would refuse: a name with no row, or with a row no registered
        skill was ever classified for (a counter bumped under a name that is not an
        installed skill), is no installed skill (:class:`PinRefused` ``not_found``; the
        loader records an origin when it registers a skill), and a skill that ships with
        Nerva is not pinned (``not_pinnable``), since nothing ages it out or deletes it.
        Unpinning any row is allowed. The answer carries ``changed``; a write that fails
        leaves the row as it was and raises."""
        key = str(name)
        with self._lock:
            rec = self._items.get(key)
            if not isinstance(rec, dict) or (pinned and rec.get("origin") in (None, "", ORIGIN_UNKNOWN)):
                raise PinRefused("not_found", f"no installed skill named {key!r}")
            if pinned and rec.get("origin") == ORIGIN_BUNDLED:
                raise PinRefused("not_pinnable", f"{key!r} ships with Nerva: nothing ages it out or "
                                 "deletes it, so there is nothing to pin")
            changed = bool(rec.get("pinned")) != bool(pinned)
            if changed:
                before = {key: dict(rec)}
                rec["pinned"] = bool(pinned)
                try:
                    self._save()
                except BaseException:
                    self._restore(before)
                    raise
            return {**rec, "changed": changed}

    def is_pinned(self, name: str) -> bool:
        with self._lock:
            rec = self._items.get(str(name))
            return isinstance(rec, dict) and bool(rec.get("pinned"))

    def set_state(self, name: str, state: str) -> dict | None:
        if state not in _VALID_STATES:
            return None
        with self._lock:
            rec = self._rec(str(name))
            rec["state"] = state
            self._save()
            return dict(rec)

    def get(self, name: str) -> dict | None:
        with self._lock:
            rec = self._items.get(name)
            return dict(rec) if isinstance(rec, dict) and rec else None

    def list(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._items.items() if isinstance(v, dict)}

    def curatable(self, name: str) -> bool:
        """Only agent-created, unpinned, non-archived skills may be curated."""
        rec = self.get(name)
        return bool(rec and rec.get("origin") == ORIGIN_AGENT
                    and not rec.get("pinned")
                    and rec.get("state") != STATE_ARCHIVED)

    def stats(self) -> dict:
        with self._lock:
            by_state, by_origin = {}, {}
            for r in self._items.values():
                if not isinstance(r, dict):
                    continue
                by_state[r.get("state", "?")] = by_state.get(r.get("state", "?"), 0) + 1
                by_origin[r.get("origin", "?")] = by_origin.get(r.get("origin", "?"), 0) + 1
            return {"total": len(self._items), "by_state": by_state, "by_origin": by_origin}

    def summary(self, name: str) -> dict:
        """The owner-facing counters of one skill (see :func:`usage_summary`)."""
        return usage_summary(self, name)


def clean_source(value: Any) -> str:
    """The short label of where an import came from (``hermes``, ``marketplace``,
    ``owner/repo``), or ``""``. It is read from a file inside the skill's folder, so it is
    display text only: one short line of plain characters."""
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > _SOURCE_MAX or not _SOURCE_RE.fullmatch(text):
        return ""
    return text


def usage_summary(store: Any, name: str) -> dict:
    """H354 — the counters the owner reads: how often a skill ran, was viewed and was
    patched, and when last; plus provenance, lifecycle state and the pin.

    Read-only: ``store.get`` never creates a row, so listing a skill leaves the sidecar
    exactly as it was. Zeros (origin ``unknown``, state ``active``) for a skill the sidecar
    never saw, and for no usable store at all (the orchestrator's learning init failed, or
    a test double stands in) — a counter the owner asked for must never fail the listing.

    H349 — ``origin`` is what the loader recorded when it registered the skill
    (``bundled``, ``import`` with its ``source``, ``agent``, ``local``); ``pinnable`` is
    whether :meth:`SkillUsageStore.pin` would take a pin (an origin was recorded and the
    skill does not ship with Nerva).
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

    def _count(key: str) -> int:
        try:
            return int(rec.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    def _when(key: str) -> str | None:
        value = rec.get(key)
        return str(value) if value else None

    origin = str(rec.get("origin") or ORIGIN_UNKNOWN)
    return {
        "use_count": _count("use_count"),
        "view_count": _count("view_count"),
        "patch_count": _count("patch_count"),
        "last_used_at": _when("last_used_at"),
        "last_viewed_at": _when("last_viewed_at"),
        "last_patched_at": _when("last_patched_at"),
        "origin": origin,
        "source": clean_source(rec.get("source")) if origin == ORIGIN_IMPORT else "",
        "state": str(rec.get("state") or STATE_ACTIVE),
        "pinned": bool(rec.get("pinned")),
        "pinnable": bool(rec) and origin not in (ORIGIN_BUNDLED, ORIGIN_UNKNOWN),
    }


__all__ = ["SkillUsageStore", "latest_activity_at", "usage_summary",
           "STATE_ACTIVE", "STATE_STALE", "STATE_ARCHIVED",
           "ORIGIN_AGENT", "ORIGIN_IMPORT", "ORIGIN_BUNDLED", "ORIGIN_LOCAL", "ORIGIN_UNKNOWN",
           "PinRefused", "clean_source"]
