"""retention.py — data-retention sweeps (H23.10).

Prunes user data older than a configured TTL. The sweep is **off by default**
(``retention.enabled``) and a TTL of ``0`` means "keep forever", so nothing is
ever surprise-deleted; a daily scheduler job runs the enabled sweeps.

Three data classes are handled:
  * **conversation transcripts** — the session ``<sid>.json`` / ``<sid>.jsonl``
    files under the data root, deleted by last-activity mtime. Only confirmed
    sessions (validated id, denylisting the non-conversation journals) are
    eligible, so config JSON like ``notes.json`` is never touched.
  * **audit log** — pruned through ``AuditLogger.prune_before`` so the Merkle
    hash-chain is re-anchored and stays verifiable.
  * **Howard private ingestion** — the raw ``ingestion/`` drop and derived
    ``archive/`` are pruned as coherent roots by newest mtime. Their TTL is 0
    (keep forever) by default even when retention is enabled.

Completes the data-rights set: backup (#302) → export (#303) → forget (#306 +
AUD-2) → **retention**.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from agents.core.ingestion.lifecycle import PRIVATE_INGESTION_ROOTS
from agents.core.paths import data_root
from agents.core.session_files import NON_SESSION_STEMS
from agents.core.validation import is_valid_session_id

logger = logging.getLogger("jarvis.retention")

# Top-level files that are NOT conversation transcripts — never pruned as sessions.
# Shared with data_purge and memory.persistence (agents/core/session_files.py) so
# the three call sites cannot drift apart again.
_NON_SESSION_JSONL: frozenset[str] = NON_SESSION_STEMS

_DAY = 86400

# Kept as an explicit public set so the lifecycle parity guard can fail loudly
# if export, retention, and forget ever drift apart again.
RETENTION_PRIVATE_DIRS: tuple[str, ...] = PRIVATE_INGESTION_ROOTS


def purge_old_conversations(ttl_days: int, root: Optional[Path] = None,
                            now: Optional[float] = None) -> dict:
    """Delete conversation transcripts whose last activity is older than *ttl_days*.

    A session is identified by a top-level ``<sid>.jsonl`` (validated id, not on the
    denylist); its ``.json`` snapshot is removed with it. Age is the newest mtime of
    the pair, so an active session is never pruned. ``ttl_days <= 0`` is a no-op.
    """
    report: dict = {"deleted": [], "ttl_days": ttl_days}
    if ttl_days <= 0:
        return report
    root = root or data_root()
    if not root.exists():
        return report
    now = now if now is not None else time.time()
    cutoff = now - ttl_days * _DAY

    stems = {
        jl.stem for jl in root.glob("*.jsonl")
        if jl.stem not in _NON_SESSION_JSONL and is_valid_session_id(jl.stem)
    }
    for sid in sorted(stems):
        paths = [p for p in (root / f"{sid}.jsonl", root / f"{sid}.json") if p.exists()]
        if not paths:
            continue
        if max(p.stat().st_mtime for p in paths) < cutoff:
            for p in paths:
                p.unlink()
            report["deleted"].append(sid)
    return report


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
                                now: Optional[float] = None) -> dict:
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
        report["live_ingestion"] = clear_live_ingestion()
    return report


def run_retention(get_setting: Callable, audit_logger=None, root: Optional[Path] = None,
                  now: Optional[float] = None) -> dict:
    """Run the configured retention sweeps. No-op unless ``retention.enabled``.

    *get_setting* is the orchestrator's ``get_setting(key, default)`` accessor.
    Blocking (file + SQLite I/O) — the scheduler offloads it off the event loop.
    """
    if not get_setting("retention.enabled", False):
        return {"enabled": False}
    conv_ttl = int(get_setting("retention.conversation_ttl_days", 0) or 0)
    audit_ttl = int(get_setting("retention.audit_ttl_days", 0) or 0)
    ingestion_ttl = int(get_setting("retention.ingestion_ttl_days", 0) or 0)
    conv = purge_old_conversations(conv_ttl, root=root, now=now)
    audit = purge_old_audit(audit_ttl, audit_logger, now=now)
    ingestion = purge_old_private_ingestion(ingestion_ttl, root=root, now=now)
    logger.info("retention sweep: %d conversation(s), %d audit row(s), %d ingestion root(s) pruned",
                len(conv["deleted"]), audit["deleted"], len(ingestion["deleted"]))
    return {"enabled": True, "conversations": conv, "audit": audit,
            "private_ingestion": ingestion}
