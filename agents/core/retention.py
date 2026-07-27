"""retention.py — data-retention sweeps (H23.10).

Prunes user data older than a configured TTL. The sweep is **off by default**
(``retention.enabled``) and a TTL of ``0`` means "keep forever", so nothing is
ever surprise-deleted; a daily scheduler job runs the enabled sweeps.

Two data classes are handled:
  * **conversation transcripts** — the session ``<sid>.json`` / ``<sid>.jsonl``
    files under the data root, deleted by last-activity mtime. Only confirmed
    sessions (validated id, denylisting the non-conversation journals) are
    eligible, so config JSON like ``notes.json`` is never touched.
  * **audit log** — pruned through ``AuditLogger.prune_before`` so the Merkle
    hash-chain is re-anchored and stays verifiable.

Completes the data-rights set: backup (#302) → export (#303) → forget (#306 +
AUD-2) → **retention**.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from agents.core.paths import data_root
from agents.core.session_files import NON_SESSION_STEMS
from agents.core.validation import is_valid_session_id

logger = logging.getLogger("jarvis.retention")

# Top-level files that are NOT conversation transcripts — never pruned as sessions.
# Shared with data_purge and memory.persistence (agents/core/session_files.py) so
# the three call sites cannot drift apart again.
_NON_SESSION_JSONL: frozenset[str] = NON_SESSION_STEMS

_DAY = 86400


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
    conv = purge_old_conversations(conv_ttl, root=root, now=now)
    audit = purge_old_audit(audit_ttl, audit_logger, now=now)
    logger.info("retention sweep: %d conversation(s), %d audit row(s) pruned",
                len(conv["deleted"]), audit["deleted"])
    return {"enabled": True, "conversations": conv, "audit": audit}
