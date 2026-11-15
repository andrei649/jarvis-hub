"""One fixed, keyed Telegram owner-DM notice after a verified restart intent."""

from __future__ import annotations

import asyncio
from importlib import import_module

from .autonomy.mode import normalize_mode
from .autonomy.restart_records import NoticeClaim, VerifiedRestart, valid_boot
from .channels.delivery_ledger import valid_delivery_key

NOTICE_TEXT = "Nerva is back online."
MAX_NOTICES = 32


async def _finish_owned(queue, claim: NoticeClaim, outcome: str) -> bool:
    """Finish an acquired notice claim even if the awaiting boot task is cancelled."""
    worker = asyncio.create_task(asyncio.to_thread(queue.finish_restart_notice, claim, outcome))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    try:
        result = worker.result() is True
    except Exception:
        result = False
    if cancelled:
        raise asyncio.CancelledError
    return result


async def _claim_owned(queue, verified: VerifiedRestart, boot_id: str, live):
    """Own the SQLite claim through cancellation; an acquired claim becomes unknown."""
    worker = asyncio.create_task(asyncio.to_thread(
        queue.claim_restart_notice, verified.task_id, verified.intent_digest,
        boot_id, live_check=live))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    try:
        claim = worker.result()
    except Exception:
        if cancelled:
            raise asyncio.CancelledError from None
        raise
    if cancelled or asyncio.current_task().cancelling():
        if type(claim) is NoticeClaim:
            await _finish_owned(queue, claim, "unknown")
        raise asyncio.CancelledError
    return claim


async def notify_completed_restart(orch, *, boot_id: str) -> dict[str, int | str]:
    """Attempt each eligible verified notice once; never infer transport success.

    The queue owns signed completion and one-use notice claims. A missing signer,
    ledger, channel or live recipient withholds transport. Nothing here can stop
    the hub or use task-supplied message text.
    """
    counts: dict[str, int | str] = {"status": "ok", "listed": 0, "sent": 0,
                                    "withheld": 0, "unknown": 0}
    if not valid_boot(boot_id):
        counts["status"] = "unavailable"
        return counts
    queue = getattr(orch, "autonomy_queue", None)
    worker = getattr(orch, "autonomy", None)
    policy = getattr(worker, "policy", None)
    manager = getattr(orch, "channel_manager", None)
    if (queue is None or worker is None or policy is None
            or getattr(worker, "queue", None) is not queue
            or not callable(getattr(manager, "send", None))):
        counts["status"] = "unavailable"
        return counts
    try:
        hub_restart_apply = import_module("agents.core.hub_restart_apply")
        def control_current(scope: str = "") -> bool:
            try:
                global_mode, global_known = normalize_mode(policy.mode)
                effective_mode, effective_known = normalize_mode(policy.effective_mode("owner"))
                return (orch.autonomy is worker and orch.autonomy_queue is queue
                        and worker.queue is queue and worker.policy is policy
                        and orch.channel_manager is manager
                        and queue.mediation_mode == "enforce"
                        and global_known and global_mode != "off"
                        and effective_known and effective_mode != "off"
                        and worker._halted() is False and worker._halted("owner") is False
                        and (not scope or worker._halted(scope) is False))
            except Exception:
                return False

        def live(verified: VerifiedRestart, scope: str) -> bool:
            try:
                return (control_current(scope)
                        and hub_restart_apply.recipient_current(orch, verified) is True)
            except Exception:
                return False

        if not control_current():
            counts["status"] = "unavailable"
            return counts
        found = await asyncio.to_thread(queue.list_restart_notices, boot_id, limit=MAX_NOTICES)
    except asyncio.CancelledError:
        raise
    except Exception:
        counts["status"] = "unavailable"
        return counts
    if type(found) is not tuple or len(found) > MAX_NOTICES:
        counts["status"] = "unavailable"
        return counts
    counts["listed"] = len(found)
    for offered in found:
        if type(offered) is not VerifiedRestart or offered.boot_id == boot_id:
            counts["withheld"] += 1
            continue
        try:
            task = await asyncio.to_thread(queue.get, offered.task_id)
            scope = task.mediation_scope
            if (task.id != offered.task_id or task.kind != "hub.restart"
                    or type(scope) is not str or not 1 <= len(scope) <= 128):
                raise ValueError("invalid restart task scope")
        except asyncio.CancelledError:
            raise
        except Exception:
            counts["withheld"] += 1
            continue
        def recipient_live(verified, bound_scope=scope):
            return live(verified, bound_scope)
        if not recipient_live(offered):
            counts["withheld"] += 1
            continue
        try:
            verified = await asyncio.to_thread(
                queue.validate_restart_completion, offered.task_id,
                offered.intent_digest, for_notification=True)
            if (type(verified) is not VerifiedRestart or verified != offered
                    or not recipient_live(verified)):
                counts["withheld"] += 1
                continue
            claim = await _claim_owned(queue, verified, boot_id, recipient_live)
        except asyncio.CancelledError:
            raise
        except Exception:
            counts["unknown"] += 1
            continue
        if claim is None:
            counts["withheld"] += 1
            continue
        outcome = "unknown"
        try:
            if (type(claim) is NoticeClaim and claim.restart == verified
                    and valid_delivery_key(claim.delivery_key)
                    and claim.delivery_key is not None and recipient_live(verified)
                    and not asyncio.current_task().cancelling()):
                sent = await manager.send(
                    "telegram", NOTICE_TEXT, chat_id=verified.chat_id,
                    plain=True, voice=False, delivery_key=claim.delivery_key)
                if sent is True:
                    outcome = "sent"
        except asyncio.CancelledError:
            await _finish_owned(queue, claim, "unknown")
            raise
        except Exception:
            outcome = "unknown"
        finished = await _finish_owned(queue, claim, outcome)
        if outcome == "sent" and finished:
            counts["sent"] += 1
        else:
            counts["unknown"] += 1
    if counts["unknown"]:
        counts["status"] = "partial"
    return counts


__all__ = ["NOTICE_TEXT", "notify_completed_restart"]
