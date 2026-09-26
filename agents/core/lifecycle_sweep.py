"""lifecycle_sweep.py — H262: one sweep for the data lifecycle, in a fixed order.

Hermes archives idle chats, prunes old ones and compacts its database in one maintenance
pass gated by a minimum interval. Nerva's pieces ran as two nightly jobs on two clocks
(the 03:30 retention glob by file mtime, the 03:40 archiver by the database); here they
are one hourly job (``data-retention-sweep``) that runs at most every
``retention.min_interval_hours``:

1. **Nothing to do** — ``memory.auto_archive_days`` 0 and ``retention.enabled`` off: the
   sweep is skipped and claims nothing.
2. **The claim** — ``CheckpointManager.claim_sweep``: one compare-and-set statement on
   checkpoints.db, which the hub and the coordinator share, so of two processes exactly
   one runs the sweep per interval. A store that cannot answer skips it (fail closed); a
   sweep that crashes keeps its claim, and the next one waits out the interval.
3. **Archive** (reversible, needs no approval) — idle chats older than
   ``memory.auto_archive_days`` are stamped archived; a pinned chat, and every chat a
   channel or the hub is on (``Orchestrator.live_session_ids``), never is.
4. **Retention** (only when ``retention.enabled``) — at the wider of the settings' and the
   last approved horizon (``retention.effective_horizons``; no approval yet: nothing is
   deleted, ``awaiting_approval``):
   a. archived, unpinned chats idle past the horizon (the database clock, never a file
      mtime), newest first, each through H218's backup-first delete under its turn lease
      (``session_archive.delete_expired``). A refusal is a skip with its reason; the
      backups this sweep wrote are all kept until the next prune;
   b. compaction archives no transcript or session row claims; orphan transcripts are
      counted, not deleted;
   c. audit rows, private ingestion and attachments past their effective TTL.
5. **VACUUM** — each database a phase deleted rows from joins ``vacuum_pending``; when
   ``retention.vacuum_after_prune`` is on and ``retention.min_vacuum_interval_days`` have
   passed since the last one, each pending database is compacted (checkpoints.db,
   audit.db, artifacts.db). One that could not be stays pending for the next due sweep.
6. The report is kept in the ``lifecycle_sweep`` state row and logged in one line.

Not closed here: there is no cross-process turn lease, so a coordinator turn on an
archived, expired chat can still race the hub's delete (the in-lease re-check narrows it).
"""
from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agents.core import retention, session_archive
from agents.core.paths import data_root

logger = logging.getLogger("jarvis.lifecycle_sweep")

#: The checkpoints.db state row: ``{last_vacuum_at, vacuum_pending, last_report}``.
SWEEP_STATE = "lifecycle_sweep"
#: How many expired chats one sweep deletes at most; the report says when more remain.
BATCH = 500
_DAY = 86400
_SKIPPED = {"_scheduler_status": "skipped"}


def _int_setting(orch: Any, key: str, default: int, low: int, high: int) -> int:
    raw = orch.get_setting(key, default)
    if isinstance(raw, bool):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return value if low <= value <= high else default


def _vacuum_checkpoints(orch: Any, root: Path) -> str | None:
    return None if orch.checkpoints.vacuum() else "vacuum_failed"


def _vacuum_audit(orch: Any, root: Path) -> str | None:
    return retention.vacuum_audit(getattr(orch, "audit", None))


def _vacuum_artifacts(orch: Any, root: Path) -> str | None:
    from agents.core.artifact_store import BinaryArtifactStore

    try:
        BinaryArtifactStore(root).vacuum()
    except ValueError as exc:                 # artifact_store_busy, unsafe_artifact_store
        return str(exc)
    except sqlite3.Error as exc:
        logger.warning("artifacts.db VACUUM failed: %s", exc)
        return "vacuum_failed"
    return None


#: Each database the sweep may compact, in order: the name in ``vacuum_pending`` → how.
_VACUUMS = {"checkpoints": _vacuum_checkpoints, "audit": _vacuum_audit, "artifacts": _vacuum_artifacts}


def _days_or_none(value: float) -> int | None:
    return None if math.isinf(value) else int(value)


async def _delete_expired(orch: Any, candidates: list[str], before: str, conv: dict) -> None:
    """Delete each candidate; a refusal is a skip with its reason. A parent met before its
    continued child (its last turn is newer) is tried once more after the child is gone."""
    pending = candidates
    for attempt in range(2):
        retry: list[str] = []
        for sid in pending:
            try:
                await session_archive.delete_expired(orch, sid, before)
            except session_archive.SessionDeleteError as exc:
                conv["skipped"][sid] = exc.reason
                if exc.reason == "has_continuations":
                    retry.append(sid)
                continue
            except Exception as exc:          # one chat's failure never stops the sweep
                logger.warning("lifecycle sweep: deleting a chat failed (%s)", type(exc).__name__)
                conv["skipped"][sid] = "delete_failed"
                continue
            conv["deleted"].append(sid)
            conv["skipped"].pop(sid, None)
        if not retry or not conv["deleted"] or attempt:
            return
        pending = retry


async def _retention(orch: Any, checkpoints: Any, root: Path, now: float, deleted_from: set[str]) -> dict | str:
    from agents.core.env_config import env_int

    current = retention.horizons(retention.current_values(orch.get_setting))
    approved = await asyncio.to_thread(retention.approved_horizons, checkpoints)
    effective = retention.effective_horizons(current, approved)
    if effective is None:
        return "awaiting_approval"
    out: dict[str, Any] = {"horizons": {name: _days_or_none(days) for name, days in effective.items()}}
    conv: dict[str, Any] = {"deleted": [], "skipped": {}, "remaining": False, "backups_pruned": []}
    conv_days = effective["conversations"]
    if not math.isinf(conv_days):
        before = (datetime.fromtimestamp(now, UTC) - timedelta(days=conv_days)).isoformat()
        candidates = await asyncio.to_thread(checkpoints.expired_sessions, before, limit=BATCH)
        conv["remaining"] = len(candidates) >= BATCH
        await _delete_expired(orch, candidates, before, conv)
        if conv["deleted"]:
            deleted_from.add("checkpoints")
            # Keep every backup this sweep wrote, on top of the usual few.
            keep = env_int("JARVIS_SESSION_BACKUP_KEEP", session_archive.BACKUP_KEEP_DEFAULT, minimum=1)
            conv["backups_pruned"] = await asyncio.to_thread(
                session_archive.prune_backups, session_archive.default_backup_dir(), keep + len(conv["deleted"]))
    out["conversations"] = conv
    known = await asyncio.to_thread(checkpoints.session_ids)
    out["orphans"] = await asyncio.to_thread(retention.orphan_transcripts, root, known)
    out["compaction_archives_deleted"] = 0 if math.isinf(conv_days) else await asyncio.to_thread(
        retention.purge_orphan_compaction_archives, root, now - conv_days * _DAY, live_ids=known)
    watcher = getattr(orch, "ingestion_watcher", None)
    ttls = {name: _days_or_none(effective[name]) or 0 for name in ("audit", "ingestion", "artifacts")}
    swept = await asyncio.to_thread(
        retention.run_retention, orch.get_setting, getattr(orch, "audit", None), root=root, now=now,
        ingestion_pipeline=getattr(watcher, "pipeline", None), ttls=ttls)
    for name in ("audit", "private_ingestion", "artifacts"):
        out[name] = swept.get(name, {})
    if out["audit"].get("deleted"):
        deleted_from.add("audit")
    if out["artifacts"].get("deleted"):
        deleted_from.add("artifacts")
    return out


async def _vacuum(orch: Any, root: Path, now: float, state: dict, deleted_from: set[str]) -> tuple[dict, Any]:
    last = state.get("last_vacuum_at")
    last = last if isinstance(last, (int, float)) and not isinstance(last, bool) else None
    earlier = state.get("vacuum_pending")
    wanted = deleted_from | (set(earlier) if isinstance(earlier, list) else set())
    pending = [name for name in _VACUUMS if name in wanted]
    out: dict[str, Any] = {"done": [], "pending": pending, "failed": {}}
    interval = _int_setting(orch, "retention.min_vacuum_interval_days", 30, 0, 365) * _DAY
    switched_on = orch.get_setting("retention.vacuum_after_prune", True) is True
    if not (switched_on and pending and (last is None or now - last >= interval)):
        return out, last
    for name in pending:
        reason = await asyncio.to_thread(_VACUUMS[name], orch, root)
        if reason is None:
            out["done"].append(name)
        else:
            out["failed"][name] = reason
    out["pending"] = [name for name in pending if name not in out["done"]]
    return out, (now if out["done"] else last)


async def run_sweep(orch: Any, *, now: float | None = None, root: Path | None = None) -> dict:
    """Run the lifecycle sweep once, if it is due (see the module docstring); the report,
    or ``{"_scheduler_status": "skipped"}`` with the reason."""
    now = time.time() if now is None else now
    days = session_archive.auto_archive_days(orch.get_setting(session_archive.SETTING_AUTO_DAYS, 0))
    enabled = orch.get_setting("retention.enabled", False) is True
    if not days and not enabled:
        return dict(_SKIPPED)
    checkpoints = getattr(orch, "checkpoints", None)
    claim = getattr(checkpoints, "claim_sweep", None)
    interval = _int_setting(orch, "retention.min_interval_hours", 24, 1, 720) * 3600
    claimed = await asyncio.to_thread(claim, SWEEP_STATE, now, interval) if callable(claim) else None
    if claimed is None:
        return {**_SKIPPED, "reason": "state_unavailable"}
    if not claimed:
        return {**_SKIPPED, "reason": "not_due"}
    state = (await asyncio.to_thread(checkpoints.get_state, SWEEP_STATE) or {}).get("value") or {}
    root = Path(root) if root is not None else data_root()
    report: dict[str, Any] = {"archived": [], "retention": "off"}
    if days:
        report["archived"] = await asyncio.to_thread(
            session_archive.run_auto_archive, checkpoints, days,
            active=session_archive.live_session_ids(orch), now=datetime.fromtimestamp(now, UTC))
    deleted_from: set[str] = set()
    if enabled:
        report["retention"] = await _retention(orch, checkpoints, root, now, deleted_from)
    report["vacuum"], last_vacuum = await _vacuum(orch, root, now, state, deleted_from)
    await asyncio.to_thread(checkpoints.put_state, SWEEP_STATE, {
        "last_vacuum_at": last_vacuum, "vacuum_pending": report["vacuum"]["pending"], "last_report": report})
    swept = report["retention"] if isinstance(report["retention"], dict) else {}
    logger.info("lifecycle sweep: %d archived, retention %s, %d chat(s) deleted, vacuumed %s",
                len(report["archived"]), "on" if swept else report["retention"],
                len(swept.get("conversations", {}).get("deleted", [])), report["vacuum"]["done"] or "nothing")
    return report


__all__ = ["BATCH", "SWEEP_STATE", "run_sweep"]
