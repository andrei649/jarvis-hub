"""retention.py — data-retention sweeps (H23.10, H262).

Prunes user data older than a configured TTL. The sweep is **off by default**
(``retention.enabled``) and a TTL of ``0`` means "keep forever", so nothing is
ever surprise-deleted. The lifecycle sweep (``agents/core/lifecycle_sweep.py``, H262)
runs the enabled sweeps at most every ``retention.min_interval_hours``.

Four data classes are handled:
  * **conversations** — deleted only by the lifecycle sweep, and only an archived,
    unpinned session idle past the horizon, through H218's backup-first
    ``session_archive.delete_session`` (its rows, transcript, compaction archive,
    checklist and note together). The database clock decides, never a file mtime. A
    transcript with no session row (an orphan) is counted, no longer deleted (H262:
    a narrowing — the old mtime glob deleted it without a backup). Here only the
    compaction archives no live transcript or session row claims are pruned (H427).
  * **audit log** — pruned through ``AuditLogger.prune_before`` so the Merkle
    hash-chain is re-anchored and stays verifiable.
  * **Howard private ingestion** — the raw ``ingestion/`` drop and derived
    ``archive/`` are pruned as coherent roots by newest mtime. Their TTL is 0
    (keep forever) by default even when retention is enabled.
  * **binary attachments** — unpinned ones past ``artifact_ttl_days``.

H262 — the approved horizon. How far back each class is deleted (:func:`horizons`, in
days; infinity deletes nothing) is never deeper than the last horizon a human approved
(the ``retention_approved`` state row in checkpoints.db): the sweep deletes at the wider
of the two (:func:`effective_horizons`), and with no approval at all it deletes nothing.
The snapshot is stored per class (``{"horizons", "values"}``). A direct write that narrows a
class (a PUT, an import, a reset, an undo, ``nerva config set``) lowers it to the narrower
of the two (:func:`lower_approval`), so a later re-deepening needs a new approval; only a
human's accept (:func:`apply_approved`) ever raises it. A chat is deleted only once it has
been archived at least :data:`DELETE_GRACE_DAYS` days.

H262 — the write side. A write of the settings that would make retention delete deeper
than the approved horizon (:func:`needs_approval`) is never applied on one click: the
settings route sends it to the approval queue's irreversible tier as ``settings.retention``
(``agents/core/autonomy/irreversible.py``), an import or an undo that would do it is
refused, a reset keeps those keys, ``nerva config set`` refuses it. A human's accept runs
:func:`apply_approved`: the values, then the approved snapshot, then an audit row.

H262 — VACUUM. :func:`vacuum_audit` compacts audit.db after a deleting prune from
outside the protected ``security/audit.py``: its own connection, holding the logger's
``_lock`` so this process's ``log()`` waits rather than meeting a locked database. The
residual risk: another process's ``AuditLogger`` (the coordinator's) has SQLite's 5 s
busy timeout and does not catch a locked database, so a VACUUM longer than that can
lose one of its rows; the first-class ``AuditLogger.vacuum()`` is a protected edit.

Completes the data-rights set: backup (#302) → export (#303) → forget (#306 +
AUD-2) → **retention**.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import shutil
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from agents.core.ingestion.lifecycle import PRIVATE_INGESTION_ROOTS
from agents.core.paths import data_path, data_root
from agents.core.session_files import (
    NON_SESSION_STEMS,
    is_session_stem,
    looks_like_session_snapshot,
)

logger = logging.getLogger("jarvis.retention")

# Top-level files that are NOT conversation transcripts — never pruned as sessions.
# Shared with data_purge and memory.persistence (agents/core/session_files.py) so
# the three call sites cannot drift apart again.
_NON_SESSION_JSONL: frozenset[str] = NON_SESSION_STEMS

_DAY = 86400

# Kept as an explicit public set so the lifecycle parity guard can fail loudly
# if export, retention, and forget ever drift apart again.
RETENTION_PRIVATE_DIRS: tuple[str, ...] = PRIVATE_INGESTION_ROOTS


def orphan_transcripts(root: Path, known_ids: Iterable[str]) -> int:
    """H262 — how many top-level session transcripts have no session row: a
    ``<sid>.jsonl`` log, or a ``<sid>.json`` that is a session snapshot. Counted for the
    report, never deleted here (no backup-first path covers a session without a row)."""
    if not root.is_dir():
        return 0
    known = set(known_ids)
    stems = {jl.stem for jl in root.glob("*.jsonl") if is_session_stem(jl.stem)}
    stems |= {js.stem for js in root.glob("*.json")
              if is_session_stem(js.stem) and looks_like_session_snapshot(js)}
    return len(stems - known)


def purge_orphan_compaction_archives(root: Path, cutoff: float, *, live_ids: Iterable[str] = ()) -> int:
    """H427 — a compaction archive no session claims (no top-level transcript, no id in
    ``live_ids`` — the session rows) goes once it is older than ``cutoff``. A deleted
    session's own archive goes with it in ``session_archive.delete_session``."""
    from agents.core.memory.precompress import TranscriptArchive

    archive = TranscriptArchive(root / "compaction_archive")
    if not archive.root.is_dir():
        return 0
    live = {archive.path_for(sid).name for sid in live_ids}
    live |= {archive.path_for(jl.stem).name for jl in root.glob("*.jsonl")}
    removed = 0
    for path in archive.root.glob("*.jsonl"):
        if path.name not in live and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def purge_old_audit(ttl_days: int, audit_logger, now: Optional[float] = None) -> dict:
    """Prune audit rows older than *ttl_days* via the chain-preserving prune.
    ``ttl_days <= 0`` (or no logger) is a no-op."""
    report = {"deleted": 0, "ttl_days": ttl_days}
    if ttl_days <= 0 or audit_logger is None:
        return report
    now = now if now is not None else time.time()
    report["deleted"] = audit_logger.prune_before(now - ttl_days * _DAY)
    return report


def purge_old_private_ingestion(ttl_days: int, root: Optional[Path] = None,
                                now: Optional[float] = None,
                                live_pipeline=None) -> dict:
    """Prune stale raw imports and derived Howard archives as coherent roots.

    Age is the newest mtime anywhere in each root, so a recently refreshed
    archive is never partially dismantled. A symlink makes that root fail
    closed: retention never follows it or deletes an external target.
    """
    report: dict[str, object] = {"deleted": [], "failed": [], "ttl_days": ttl_days}
    if ttl_days <= 0:
        return report
    root = root or data_root()
    now = now if now is not None else time.time()
    cutoff = now - ttl_days * _DAY

    deleted: list[str] = report["deleted"]  # type: ignore[assignment]
    failed: list[dict[str, str]] = report["failed"]  # type: ignore[assignment]
    for name in RETENTION_PRIVATE_DIRS:
        private_root = root / name
        if not private_root.exists() and not private_root.is_symlink():
            continue
        if private_root.is_symlink() or not private_root.is_dir():
            failed.append({"root": name, "reason": "unsafe_root"})
            continue

        newest = private_root.stat().st_mtime
        unsafe_link = False
        for item in private_root.rglob("*"):
            if item.is_symlink():
                unsafe_link = True
                break
            try:
                newest = max(newest, item.stat().st_mtime)
            except OSError:
                failed.append({"root": name, "reason": "stat_failed"})
                unsafe_link = True
                break
        if unsafe_link:
            if not any(entry.get("root") == name for entry in failed):
                failed.append({"root": name, "reason": "symlink_refused"})
            continue
        if newest < cutoff:
            try:
                shutil.rmtree(private_root)
                deleted.append(name)
            except OSError:
                failed.append({"root": name, "reason": "delete_failed"})
    if deleted:
        # The process-wide Howard reader and embedding LRU otherwise outlive the
        # filesystem TTL and keep serving text the retention policy just pruned.
        from agents.core.ingestion.pipeline import clear_live_ingestion
        report["live_ingestion"] = clear_live_ingestion(live_pipeline)
    return report


def run_retention(get_setting: Callable, audit_logger=None, root: Optional[Path] = None,
                  now: Optional[float] = None, ingestion_pipeline=None,
                  ttls: Optional[dict] = None) -> dict:
    """Run the audit, private-ingestion and attachment sweeps. No-op unless
    ``retention.enabled``. Conversations are the lifecycle sweep's (H262), never here.

    *get_setting* is the orchestrator's ``get_setting(key, default)`` accessor. *ttls*
    (``{"audit", "ingestion", "artifacts"}`` in days, 0 = keep) replaces the settings'
    TTLs: the lifecycle sweep passes the approved, effective ones.
    Blocking (file + SQLite I/O) — the scheduler offloads it off the event loop.
    """
    if not get_setting("retention.enabled", False):
        return {"enabled": False}
    if ttls is None:
        ttls = {"audit": _days(get_setting("retention.audit_ttl_days", 0)),
                "ingestion": _days(get_setting("retention.ingestion_ttl_days", 0)),
                "artifacts": _days(get_setting("retention.artifact_ttl_days", 0))}
    from .artifact_store import BinaryArtifactStore
    artifacts = BinaryArtifactStore(root).retain(int(ttls.get("artifacts") or 0), now=now)
    audit = purge_old_audit(int(ttls.get("audit") or 0), audit_logger, now=now)
    ingestion = purge_old_private_ingestion(
        int(ttls.get("ingestion") or 0), root=root, now=now, live_pipeline=ingestion_pipeline
    )
    logger.info("retention sweep: %d audit row(s), %d ingestion root(s), %d attachment(s) pruned",
                audit["deleted"], len(ingestion["deleted"]), len(artifacts["deleted"]))
    return {"enabled": True, "audit": audit, "private_ingestion": ingestion, "artifacts": artifacts}


# ── H262 — the horizon a human approved ───────────────────────────────────────

#: The settings that decide what retention deletes. A write that deepens a horizon they
#: set waits for the approval queue (:func:`needs_approval`); the sweep never deletes
#: deeper than approved.
RETENTION_KEYS: tuple[str, ...] = (
    "retention.enabled", "retention.conversation_ttl_days", "retention.audit_ttl_days",
    "retention.ingestion_ttl_days", "retention.artifact_ttl_days", "memory.auto_archive_days",
)
#: The data classes, in report order.
DATA_CLASSES: tuple[str, ...] = ("conversations", "audit", "ingestion", "artifacts")
#: The checkpoints.db state row holding what a human approved: ``{"horizons": {class: days
#: or None for kept forever}, "values": {RETENTION_KEYS…}}`` (an older row holds only the
#: values; its horizons are computed from them).
APPROVED_STATE = "retention_approved"
_MAX_TTL_DAYS = 36500
#: H262 review — a chat is deleted only once it has been archived at least this many days,
#: so it always sits in the Archived view for a week first and a chat archived in a sweep
#: is never deleted in the same one (``CheckpointManager._EXPIRED_WHERE``).
DELETE_GRACE_DAYS = 7


def _days(value: Any, high: int = _MAX_TTL_DAYS) -> int:
    """A stored day count as its readers use it: a whole number within ``0..high``,
    anything else (a bool, a fraction's text, a negative, too big) 0 — keep forever."""
    if isinstance(value, bool):
        return 0
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return days if 0 < days <= high else 0


def horizons(values: dict) -> dict[str, float]:
    """How far back each data class is deleted, in days (``math.inf``: nothing is).

    Off unless ``retention.enabled``. A chat is deleted only once archived, so its
    horizon is the wider of its TTL and ``memory.auto_archive_days`` and needs both."""
    from .session_archive import MAX_AUTO_DAYS

    inf = math.inf
    if values.get("retention.enabled") is not True:
        return dict.fromkeys(DATA_CLASSES, inf)
    conv = _days(values.get("retention.conversation_ttl_days"))
    archive = _days(values.get("memory.auto_archive_days"), MAX_AUTO_DAYS)
    out: dict[str, float] = {"conversations": max(conv, archive) if conv and archive else inf}
    for name, key in (("audit", "retention.audit_ttl_days"), ("ingestion", "retention.ingestion_ttl_days"),
                      ("artifacts", "retention.artifact_ttl_days")):
        out[name] = _days(values.get(key)) or inf
    return out


def effective_horizons(current: dict, approved: Optional[dict]) -> Optional[dict[str, float]]:
    """The horizon the sweep deletes at: per class the wider of the current settings'
    and the approved one, so deletion is never deeper than a human approved. None (delete
    nothing) with no approval."""
    if approved is None:
        return None
    return {name: max(current.get(name, math.inf), approved.get(name, math.inf)) for name in DATA_CLASSES}


def widening(new: dict, approved: Optional[dict]) -> list[str]:
    """The classes whose horizon ``new`` deepens past ``approved`` (no approval: every
    class ``new`` deletes at all)."""
    base = approved or {}
    return [name for name in DATA_CLASSES if new.get(name, math.inf) < base.get(name, math.inf)]


def current_values(get_setting: Callable) -> dict:
    """The RETENTION_KEYS as the settings hold them now."""
    return {key: get_setting(key, None) for key in RETENTION_KEYS}


def _stored_horizons(shown: Any) -> Optional[dict[str, float]]:
    """``{class: days or None}`` as stored, read back as horizons; None when it is not that."""
    if not isinstance(shown, dict):
        return None
    out: dict[str, float] = {}
    for name in DATA_CLASSES:
        days = shown.get(name, None)
        if days is None:
            out[name] = math.inf
        elif isinstance(days, bool) or not isinstance(days, (int, float)) or not 0 < days <= _MAX_TTL_DAYS:
            return None
        else:
            out[name] = float(days)
    return out


def snapshot_horizons(value: Any) -> Optional[dict[str, float]]:
    """The approved horizons an ``APPROVED_STATE`` value holds: its ``horizons``, else (an
    older row) the horizons of its ``values``; None when it holds neither."""
    if not isinstance(value, dict):
        return None
    if "horizons" in value:
        return _stored_horizons(value["horizons"])
    values = value.get("values")
    return horizons(values) if isinstance(values, dict) else None


def approved_horizons(checkpoints: Any) -> Optional[dict[str, float]]:
    """The approved horizons from the ``retention_approved`` state row; None when there is
    none, the store cannot answer or the row holds no horizons (fail closed: the sweep
    then deletes nothing)."""
    reader = getattr(checkpoints, "get_state", None)
    if not callable(reader):
        return None
    state = reader(APPROVED_STATE)
    return snapshot_horizons(state.get("value")) if isinstance(state, dict) else None


def lowered(approved: dict[str, float], found: dict[str, float]) -> dict[str, float]:
    """Per class the narrower (deletes less: more days) of the approved and ``found``."""
    return {name: max(approved.get(name, math.inf), found.get(name, math.inf)) for name in DATA_CLASSES}


def lower_approval(checkpoints: Any, stored: Optional[dict] = None) -> bool:
    """H262 review — after a direct, ungated write of RETENTION_KEYS (a PUT, an import, a
    reset, a reseed, an undo): lower the approved snapshot, when there is one, per class
    to the narrower of it and what the settings now hold (``stored``, default: read
    them). A human's narrowing is a decision too, so deepening again later needs a new
    approval. Never widens: only :func:`apply_approved` does. Whether it changed."""
    reader, writer = getattr(checkpoints, "get_state", None), getattr(checkpoints, "put_state", None)
    if not callable(reader) or not callable(writer):
        return False
    state = reader(APPROVED_STATE)
    value = state.get("value") if isinstance(state, dict) else None
    approved = snapshot_horizons(value)
    if approved is None:
        return False
    new = lowered(approved, horizons(stored if stored is not None else stored_values()))
    if new == approved:
        return False
    return writer(APPROVED_STATE, {**value, "horizons": days_shown(new), "narrowed_at": time.time()}) is True


def lower_approval_offline(stored: Optional[dict] = None) -> bool:
    """:func:`lower_approval` for ``nerva config set``, which runs without the hub: the
    snapshot row of checkpoints.db, changed in place when it exists (the database is
    never created or migrated). Whether it changed."""
    path = data_path("checkpoints", "checkpoints.db")
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(str(path), timeout=30)
        try:
            with conn:
                row = conn.execute("SELECT value FROM maintenance_state WHERE name=?", (APPROVED_STATE,)).fetchone()
                value = json.loads(row[0] or "{}") if row else None
                approved = snapshot_horizons(value)
                if approved is None:
                    return False
                new = lowered(approved, horizons(stored if stored is not None else stored_values()))
                if new == approved:
                    return False
                conn.execute("UPDATE maintenance_state SET value=? WHERE name=?", (json.dumps(
                    {**value, "horizons": days_shown(new), "narrowed_at": time.time()}), APPROVED_STATE))
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        logger.warning("could not lower the approved retention snapshot", exc_info=True)
        return False
    return True


# ── H262 — VACUUM ─────────────────────────────────────────────────────────────

def vacuum_audit(audit_logger: Any) -> Optional[str]:
    """Compact audit.db after a deleting prune; None when done, else why not.

    Its own connection (a VACUUM runs outside a transaction), under the logger's
    ``_lock``, then the write-ahead log is emptied. Without that lock or database path
    (``security/audit.py`` changed) it refuses rather than race this process's writes."""
    lock, path = getattr(audit_logger, "_lock", None), getattr(audit_logger, "_db_path", None)
    if lock is None or not path:
        return "audit_vacuum_unavailable"
    with lock:
        conn = sqlite3.connect(str(path), timeout=30)
        try:
            conn.execute("VACUUM")
            with contextlib.suppress(sqlite3.Error):
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            logger.warning("audit.db VACUUM failed: %s", exc)
            return "vacuum_failed"
        finally:
            conn.close()
    return None


# ── H262 — the write side: a deeper horizon waits for a human ─────────────────

#: The approval-queue kind a deepening retention write is sent as (irreversible tier).
APPROVAL_KIND = "settings.retention"
#: The data classes each retention key moves; ``retention.enabled`` moves them all.
_KEY_CLASSES: dict[str, tuple[str, ...]] = {
    "retention.enabled": DATA_CLASSES,
    "retention.conversation_ttl_days": ("conversations",),
    "memory.auto_archive_days": ("conversations",),
    "retention.audit_ttl_days": ("audit",),
    "retention.ingestion_ttl_days": ("ingestion",),
    "retention.artifact_ttl_days": ("artifacts",),
}
#: How many chats a card counts at most (one sweep's batch); a count that reaches it is a
#: lower bound (``"more": True``, shown "500+").
_PREVIEW_CHATS = 500
#: What a card says for a class it cannot count (private ingestion roots, attachments).
NOT_COUNTED: dict[str, bool] = {"counted": False}
#: How long a card's title may be.
TITLE_MAX = 200
#: The names a person reads for the data classes.
_CLASS_LABELS = {"conversations": "chats", "audit": "audit", "ingestion": "ingestion", "artifacts": "attachments"}


def stored_values() -> dict:
    """The RETENTION_KEYS as the settings store holds them (no row yet: the default)."""
    from agents.core import settings_db

    out = {}
    for name in RETENTION_KEYS:
        cat, key = name.split(".", 1)
        out[name] = settings_db.get_value(cat, key, settings_db._SPEC[(cat, key)]["value"])
    return out


def retention_part(changes: dict) -> dict[str, Any]:
    """The RETENTION_KEYS a ``{category: {key: value}}`` write carries, as ``{name: value}``."""
    return {f"{cat}.{key}": value for cat, values in changes.items() if isinstance(values, dict)
            for key, value in values.items() if f"{cat}.{key}" in RETENTION_KEYS}


def needs_approval(changes: dict, stored: dict, approved: Optional[dict], *, confirm: bool = False) -> list[str]:
    """The RETENTION_KEYS of ``changes`` (every one it carries, or none) a human must
    approve before they are written: the write leaves retention deleting deeper than the
    approved horizons ``approved`` (None: nothing approved yet) in some data class.

    By default the class must be one the write itself deepens against ``stored`` — an
    import, a reset, an undo, ``nerva config set``. ``confirm`` (the settings route) also
    counts a class already deeper than approved that a key of the write moves, so
    re-sending the stored values is how an owner confirms them."""
    part = retention_part(changes)
    if not part:
        return []
    after = horizons({**stored, **part})
    wide = widening(after, approved)
    if confirm:
        wide = [name for name in wide if any(name in _KEY_CLASSES[key] for key in part)]
    else:
        before = horizons(stored)
        wide = [name for name in wide if after[name] < before[name]]
    return sorted(part) if wide else []


def days_shown(found: dict[str, float]) -> dict[str, Optional[int]]:
    """Horizons as a person reads them: whole days, None for kept forever."""
    return {name: None if math.isinf(days) else int(days) for name, days in found.items()}


def _audit_rows_before(audit_logger: Any, cutoff: float) -> Optional[int]:
    """How many audit rows are older than ``cutoff``: a read-only connection of its own
    (``security/audit.py`` is protected and counts only every row); None when unknown."""
    path = getattr(audit_logger, "_db_path", None)
    if not path or not Path(path).is_file():
        return None
    try:
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute("SELECT COUNT(*) FROM security_events WHERE timestamp < ?", (cutoff,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else 0


def _counted(found: Optional[int], limit: Optional[int] = None) -> dict:
    """A card's count: ``{"count", "more"}`` — ``more`` when it reached the query's limit,
    so it is a lower bound; ``count`` None when the store could not say."""
    return {"count": found, "more": bool(limit is not None and found is not None and found >= limit)}


def approval_preview(values: dict, approved: Optional[dict], checkpoints: Any, audit_logger: Any,
                     *, now: Optional[float] = None) -> dict:
    """What the decision card shows: the horizons ``values`` sets and the approved ones (in
    days, None: kept forever), the classes it deepens, and what the new values would delete,
    per class (``{"count", "more"}``, or :data:`NOT_COUNTED`):

    * ``archived_chats`` — archived, unpinned, past the horizon and the grace: the next
      sweep deletes them;
    * ``chats_to_archive`` — not archived, unpinned, idle past the horizon (so past
      ``memory.auto_archive_days`` too): the next sweep archives them, and they are deleted
      once the grace (:data:`DELETE_GRACE_DAYS`) has passed;
    * ``audit_rows`` — older than the audit horizon;
    * ``ingestion``, ``attachments`` — not counted when their horizon is finite.

    A chat count stops at one sweep's batch (``more``: a lower bound)."""
    now = time.time() if now is None else now
    after = horizons(values)
    out: dict[str, Any] = {"horizons": days_shown(after), "approved": days_shown(approved) if approved is not None else None,
                           "widened": widening(after, approved), "would_delete": {}}
    gone = out["would_delete"]
    none = _counted(0)
    if math.isinf(after["conversations"]):
        gone["archived_chats"], gone["chats_to_archive"] = dict(none), dict(none)
    else:
        moment = datetime.fromtimestamp(now, UTC)
        before = (moment - timedelta(days=after["conversations"])).isoformat()
        grace = (moment - timedelta(days=DELETE_GRACE_DAYS)).isoformat()
        expired, stale = getattr(checkpoints, "expired_sessions", None), getattr(checkpoints, "stale_sessions", None)
        gone["archived_chats"] = _counted(len(expired(before, archived_before=grace, limit=_PREVIEW_CHATS))
                                          if callable(expired) else None, _PREVIEW_CHATS)
        gone["chats_to_archive"] = _counted(len(stale(before, limit=_PREVIEW_CHATS)) if callable(stale) else None,
                                            _PREVIEW_CHATS)
    gone["audit_rows"] = dict(none) if math.isinf(after["audit"]) else _counted(
        _audit_rows_before(audit_logger, now - after["audit"] * _DAY))
    for key, name in (("ingestion", "ingestion"), ("attachments", "artifacts")):
        gone[key] = dict(none) if math.isinf(after[name]) else dict(NOT_COUNTED)
    return out


def _title(after: dict[str, float], widened: list[str], part: dict[str, Any]) -> str:
    """The card's title, which every push surface shows: each class the accept deepens with
    its new horizon, then the keys the write carried; cut to :data:`TITLE_MAX`."""
    classes = ", ".join(f"{_CLASS_LABELS[name]} {int(after[name])}d" for name in DATA_CLASSES
                        if name in widened and not math.isinf(after[name]))
    head = "Retention: delete deeper" + (f" — {classes}" if classes else "")
    shown = ", ".join(f"{name}={json.dumps(value)}" for name, value in sorted(part.items()))
    title = f"{head} ({shown})"
    if len(title) > TITLE_MAX:
        room = TITLE_MAX - len(head) - len(" (…)")
        title = f"{head} ({shown[:max(room, 0)]}…)"
    return title[:TITLE_MAX]


def _widened_text(found: dict[str, float], widened: list[str]) -> str:
    return ", ".join(f"{_CLASS_LABELS[name]} {'kept forever' if math.isinf(found[name]) else f'{int(found[name])}d'}"
                     for name in DATA_CLASSES if name in widened) or "none"


def as_changes(part: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{name: value}`` as a ``{category: {key: value}}`` write."""
    values: dict[str, dict[str, Any]] = {}
    for name, value in part.items():
        cat, key = name.split(".", 1)
        values.setdefault(cat, {})[key] = value
    return values


def approval_request(changes: dict, stored: dict, approved: Optional[dict], checkpoints: Any,
                     audit_logger: Any) -> dict:
    """The ``title``, ``payload`` and ``preview`` of the task a gated write becomes. The
    payload keeps every retention setting as it was (``before``); an accept applies the
    values onto the settings as they are then, unless that ends deeper than the card's
    preview (:func:`apply_approved`). The title names every class the accept deepens."""
    part = retention_part(changes)
    preview = approval_preview({**stored, **part}, approved, checkpoints, audit_logger)
    after = horizons({**stored, **part})
    return {"title": _title(after, preview["widened"], part),
            "payload": {"values": as_changes(part), "before": dict(stored)},
            "preview": preview}


def approved_horizons_offline() -> Optional[dict[str, float]]:
    """The approved horizons read straight from checkpoints.db, read-only (it is never
    created or migrated) — for ``nerva config set``, which runs without the hub. None when
    there is no approval or the database cannot be read: nothing counts as approved."""
    path = data_path("checkpoints", "checkpoints.db")
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute("SELECT value FROM maintenance_state WHERE name=?", (APPROVED_STATE,)).fetchone()
        finally:
            conn.close()
        value = json.loads(row[0] or "{}") if row else None
    except (sqlite3.Error, ValueError):
        return None
    return snapshot_horizons(value)


def _refused(reason: str, **extra: Any) -> dict:
    return {"status": "refused", "reason": reason, **extra}


def _card_horizons(payload: dict) -> Optional[dict[str, float]]:
    """The new horizons the card showed (its preview); an older task without them: the
    horizons of its values over the state it recorded."""
    preview = payload.get("preview")
    shown = _stored_horizons(preview.get("horizons")) if isinstance(preview, dict) else None
    if shown is not None:
        return shown
    before, changes = payload.get("before"), payload.get("values")
    if not isinstance(before, dict) or not isinstance(changes, dict):
        return None
    return horizons({**before, **retention_part(changes)})


async def apply_approved(task: Any, orch: Any) -> dict:
    """Apply a ``settings.retention`` task a human accepted (``irreversible.execute`` has
    checked who decided): the values are validated again and merged onto the retention
    settings as they are now. That is refused (``changed_since_request``) only when some
    class would end deeper than the card showed for it; a harmless move of another
    retention key since the request (a narrowing, an unrelated key) keeps the card
    acceptable. Then the values are written and — last, so a failure in between leaves the
    sweep clamped to the old approval — the applied state's horizons, never deeper than the
    card's, become the approved snapshot, and a SETTINGS_CHANGE audit row names every class
    the accept deepened with its horizon."""
    from agents.core import settings_db

    payload = task.payload
    changes, before = payload.get("values"), payload.get("before")
    if not isinstance(changes, dict) or not changes or not isinstance(before, dict):
        return _refused("payload_invalid")
    for cat, values in changes.items():
        if not isinstance(values, dict) or not values:
            return _refused("payload_invalid")
        if any(f"{cat}.{key}" not in RETENTION_KEYS for key in values):
            return _refused("not_a_retention_setting")
        errors = settings_db.validate_category(cat, values)
        if errors:
            return _refused("invalid_settings", details=errors)
    checkpoints = getattr(orch, "checkpoints", None) if orch is not None else None
    put_state = getattr(checkpoints, "put_state", None)
    if not callable(put_state):
        return _refused("state_unavailable")
    card = _card_horizons(payload)
    if card is None:
        return _refused("payload_invalid")
    stored = await asyncio.to_thread(stored_values)
    merged = horizons({**stored, **retention_part(changes)})
    if any(merged[name] < card[name] for name in DATA_CLASSES):
        return _refused("changed_since_request")
    prior = await asyncio.to_thread(approved_horizons, checkpoints)
    for cat, values in changes.items():
        await asyncio.to_thread(settings_db.put_category, cat, dict(values))
    after = await asyncio.to_thread(stored_values)
    snapshot = lowered(card, horizons(after))            # never deeper than the card showed
    widened = widening(snapshot, prior)
    task_id = getattr(task, "id", None)
    decided_by = str(getattr(task, "decided_by", "") or "")
    recorded = await asyncio.to_thread(put_state, APPROVED_STATE, {
        "horizons": days_shown(snapshot), "values": after, "task_id": task_id, "approved_by": decided_by,
        "approved_at": time.time()})
    names = sorted(retention_part(changes))
    await _audit_approval(orch, names, after, task_id, decided_by, recorded is True,
                          _widened_text(snapshot, widened))
    if recorded is not True:
        return {"status": "failed", "reason": "approval_not_recorded", "written": names}
    return {"status": "ok", "kind": APPROVAL_KIND, "written": names, "horizons": days_shown(snapshot),
            "widened": widened}


async def _audit_approval(orch: Any, names: list[str], after: dict, task_id: Any, decided_by: str,
                          recorded: bool, widened: str = "") -> None:
    from agents.core.security.types import SecurityEvent, SecurityEventType

    audit = getattr(orch, "audit", None)
    if audit is None:
        return
    shown = " ".join(f"{name}={json.dumps(after.get(name))}" for name in names)
    try:
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=f"settings.retention approved (task {task_id} by {decided_by}): {names} · {shown}"
                            f" · deletes deeper: {widened}"
                            + ("" if recorded else " · the approved snapshot was not recorded"),
            action_taken="settings_retention_approved",
        ))
    except Exception:  # noqa: BLE001 — the write happened; a lost audit row is logged
        logger.warning("failed to audit the approved retention change (task %s)", task_id)

