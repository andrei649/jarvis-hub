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

import contextlib
import logging
import math
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from agents.core.ingestion.lifecycle import PRIVATE_INGESTION_ROOTS
from agents.core.paths import data_root
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
#: set is the approval queue's (phase B); the sweep never deletes deeper than approved.
RETENTION_KEYS: tuple[str, ...] = (
    "retention.enabled", "retention.conversation_ttl_days", "retention.audit_ttl_days",
    "retention.ingestion_ttl_days", "retention.artifact_ttl_days", "memory.auto_archive_days",
)
#: The data classes, in report order.
DATA_CLASSES: tuple[str, ...] = ("conversations", "audit", "ingestion", "artifacts")
#: The checkpoints.db state row holding ``{"values": {RETENTION_KEYS…}}`` a human approved.
APPROVED_STATE = "retention_approved"
_MAX_TTL_DAYS = 36500


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


def approved_horizons(checkpoints: Any) -> Optional[dict[str, float]]:
    """The approved horizons from the ``retention_approved`` state row; None when there is
    none, the store cannot answer or the row is not ``{"values": {...}}`` (fail closed:
    the sweep then deletes nothing)."""
    reader = getattr(checkpoints, "get_state", None)
    if not callable(reader):
        return None
    state = reader(APPROVED_STATE)
    values = state.get("value", {}).get("values") if isinstance(state, dict) else None
    return horizons(values) if isinstance(values, dict) else None


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
