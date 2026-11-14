"""Governed owner restart: persist intent, commit completion, then stop once.

The command and approved executor never invoke the stopper. Only a separate
post-DONE phase may consume a durable physical claim after checking live floors.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import stat
import uuid
from types import SimpleNamespace

from . import backup, hub_restart, hub_update, hub_update_apply
from .autonomy import irreversible
from .autonomy.restart_records import KIND, PREVIEW, TITLE, request_payload, valid_requester
from .command_source import source_for_dispatch
from .restart_runtime import runtime_for

logger = logging.getLogger("jarvis.hub_restart_apply")
BOOT_ID = uuid.uuid4().hex
DRAIN_SECONDS = 30.0


def held_here(task=None) -> str | None:
    try:
        return None if hub_restart.available() else "hub_applies_restart"
    except Exception:
        return "hub_applies_restart"


def _bound(orch):
    worker = getattr(orch, "autonomy", None)
    queue = getattr(worker, "queue", None)
    if (queue is None or getattr(orch, "autonomy_queue", None) is not queue
            or getattr(queue, "mediation_mode", None) != "enforce"):
        return None, None
    return worker, queue


def recipient_current(orch, recipient) -> bool:
    """Current live bot, paired owner and exact private DM; no transport effect."""
    try:
        chat, sender, bot = recipient.chat_id, recipient.sender_id, recipient.bot_id
        if (any(type(value) is not int or value <= 0 for value in (chat, sender, bot))
                or chat != sender):
            return False
        adapter = orch.channels.get("telegram")
        generation = getattr(adapter, "_owner_once_generation", None)
        if (adapter is None or getattr(adapter, "_running", False) is not True
                or not generation or getattr(adapter, "_verified_bot_generation", None) != generation
                or type(getattr(adapter, "_bot_id", None)) is not int or adapter._bot_id != bot):
            return False
        pairing = getattr(orch, "sender_pairing", None)
        if pairing is None or pairing.is_allowed("telegram", str(sender)) is not True:
            return False
        principal = orch._channel_principal("telegram", str(sender), chat, "private")
        return (principal.admin is True and principal.scope == "dm"
                and principal.channel == "telegram" and principal.sender == str(sender)
                and principal.chat == str(chat))
    except Exception:
        return False


def _update_state_present() -> bool:
    """Any persisted update marker blocks restart; never parse the UI projection.

    The permissive updater UI reader maps malformed/unreadable state to None.
    Restart needs only absence, so avoid reading contents altogether. Errors or
    a directory replacement cannot prove absence and fail closed in _conflict.
    This is not an interprocess exclusion lock.
    """
    directory = hub_update_apply.state_dir()
    try:
        before = directory.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISDIR(before.st_mode)
            or getattr(before, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise OSError("update state directory unavailable")
    try:
        (directory / "current.json").lstat()
    except FileNotFoundError:
        after = directory.lstat()
        fields = ("st_dev", "st_ino", "st_mode", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise OSError("update state directory changed") from None
        return False
    return True


def _conflict(own_action=None) -> str | None:
    try:
        if held_here():
            return "restart_unavailable"
        if _update_state_present():
            return "update_in_progress"
        if backup.boot_restore_due() or backup.restore_in_progress():
            return "restore_pending"
        with hub_update._LOCK:
            if own_action is not None and (
                    hub_update._ACTIONS.get(own_action["id"]) is not own_action
                    or own_action.get("status") != "running"):
                return "action_changed"
            if any(record.get("status") == "running" and record is not own_action
                   for record in hub_update._ACTIONS.values()):
                return "action_running"
        return None
    except Exception:
        return "state_unavailable"


async def _owned_enqueue(orch, payload):
    task = asyncio.create_task(asyncio.to_thread(
        irreversible.enqueue, orch, KIND, title=TITLE, payload=payload, preview=PREVIEW))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A queue transaction in a thread may already have committed. Own its
        # outcome before allowing another caller to interpret cancellation.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with contextlib.suppress(BaseException):
            task.result()
        raise


async def request_restart(orch, *, principal, source) -> dict:
    """Queue one human card from the live original command, without arming it."""
    try:
        if source is None or source_for_dispatch(text="/restart", principal=principal, orch=orch) is not source:
            return {"refused": "original_owner_dm_required"}
        from .action_origin import bind_action_origin, current_action_origin, reset_action_origin
        from .autonomy.approval_grouping import current_model_producer

        origin = current_action_origin()
        if origin not in {"inbound", "generated"} or current_model_producer() is not None:
            return {"refused": "original_owner_dm_required"}
        worker, queue = _bound(orch)
        if worker is None:
            return {"refused": "signed_queue_required"}
        conflict = _conflict()
        if conflict:
            return {"refused": conflict}
        requester = {"provider_key": source.provider_id, "bot_id": source.bot_id,
                     "update_id": source.update_id, "message_id": source.message_id,
                     "chat_id": source.chat_id, "sender_id": source.sender_id,
                     "inbox_id": source.inbox_id}
        if not valid_requester(requester) or not recipient_current(orch, SimpleNamespace(**requester)):
            return {"refused": "recipient_changed"}
        payload = request_payload(requester)
        ticket = queue.issue_restart_source(orch=orch, principal=principal, source=source,
                                            title=TITLE, request_payload=payload)
        if ticket is None:
            return {"refused": "source_attestation_refused"}
        payload["source_ticket"] = ticket.as_dict()
        # This exact original human control command constructs only a fixed
        # restart intent. Classify that intent as manual, not model-derived
        # channel content, only after live source/owner checks and attestation.
        # Generic worker/Kernel taint rules and tier-3 human approval stay intact.
        token = bind_action_origin("manual") if origin == "inbound" else None
        try:
            return await _owned_enqueue(orch, payload)
        finally:
            if token is not None:
                reset_action_origin(token)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("restart intake unavailable", exc_info=True)
        return {"refused": "restart_intake_unavailable"}


def _kernel_current(orch, task, *, worker, queue, policy, check) -> bool:
    from .kernel import Action, Verdict, kernel_enabled

    def current():
        try:
            return (kernel_enabled() and orch.autonomy is worker and worker.queue is queue
                    and orch.autonomy_queue is queue and worker.policy is policy
                    and queue.mediation_mode == "enforce" and not worker._halted()
                    and not worker._halted("owner")
                    and not (task.mediation_scope and worker._halted(task.mediation_scope))
                    and check() is True)
        except Exception:
            return False

    try:
        if not current():
            return False
        action = Action(kind=KIND, agent="owner", title=task.title,
                        payload={**task.payload, "approved_task_id": task.id},
                        scope=task.mediation_scope or "global", origin=task.origin)
        decision = worker.kernel_dispatch_current(
            action, approval_check=lambda actual: actual == action and current())
        return decision.verdict is Verdict.GRANT and current()
    except Exception:
        return False


async def apply_approved(task, orch) -> dict:
    """Create the signed arm intent only; the worker must commit DONE next."""
    try:
        worker, queue = _bound(orch)
        if (worker is None or task.kind != KIND or task.agent != "owner"
                or task.decision not in ("accept", "approve")
                or str(task.decided_by or "").strip().lower() in irreversible.MACHINE_DECIDERS):
            return {"status": "refused", "reason": "human_decision_required"}
        if _conflict():
            return {"status": "refused", "reason": "restart_conflict"}
        requester = task.payload.get("requester")
        if not valid_requester(requester):
            return {"status": "refused", "reason": "payload_changed"}
        recipient = SimpleNamespace(**requester)
        fingerprint = queue.execution_fingerprint(task)
        def check():
            return (recipient_current(orch, recipient) and _conflict() is None
                    and queue.validate_mediated_execution(task, fingerprint) is True)
        if not _kernel_current(orch, task, worker=worker, queue=queue, policy=worker.policy, check=check):
            return {"status": "refused", "reason": "authority_changed"}
        arm = queue.arm_restart(task, BOOT_ID)
        if arm is None:
            return {"status": "refused", "reason": "restart_arm_refused"}
        return {"status": "ok", "phase": "armed", "intent_digest": arm.intent_digest}
    except Exception:
        logger.warning("restart arming refused", exc_info=True)
        return {"status": "refused", "reason": "restart_arm_unavailable"}


async def after_completion(orch, task_id: int, intent_digest: str) -> dict:
    """Consume a committed restart once, with admission closed through the effect."""
    worker, queue = _bound(orch)
    if worker is None:
        return {"status": "refused"}
    runtime = runtime_for(orch)
    claim = record = token = None
    effect_started = requested = False
    outcome = "refused"
    try:
        verified = queue.validate_restart_completion(task_id, intent_digest)
        task = queue.get(task_id)
        if verified is None or task is None or verified.boot_id != BOOT_ID:
            return {"status": "refused"}
        policy = worker.policy

        def current():
            return (queue.validate_restart_completion(task_id, intent_digest) == verified
                    and recipient_current(orch, verified) and _conflict(record) is None)

        if not _kernel_current(orch, task, worker=worker, queue=queue, policy=policy, check=current):
            return {"status": "refused"}
        claim = queue.claim_restart_physical(task_id, intent_digest, BOOT_ID)
        if claim is None:
            return {"status": "refused"}
        record = hub_update._new_action("restart")
        if record is None:
            return {"status": "refused"}
        token = runtime.close_admission()
        if token is None:
            return {"status": "refused"}
        if not await runtime.wait_idle(token, DRAIN_SECONDS, orch.restart_work_pending):
            return {"status": "refused"}
        if not _kernel_current(orch, task, worker=worker, queue=queue, policy=policy, check=current):
            return {"status": "refused"}
        # No await between this last authority check and the stopper. The signed
        # physical claim was committed before any possible stop; it is never retried.
        effect_started = True
        requested = hub_restart.request("approved owner restart") is True
        outcome = "requested" if requested else "refused"
        return {"status": outcome}
    except asyncio.CancelledError:
        outcome = "unknown" if effect_started else "refused"
        raise
    except Exception:
        outcome = "unknown" if effect_started else "refused"
        logger.warning("restart completion phase unavailable", exc_info=True)
        return {"status": outcome}
    finally:
        if claim is not None:
            with contextlib.suppress(Exception):
                queue.finish_restart_physical(claim, outcome)
        else:
            with contextlib.suppress(Exception):
                queue.refuse_restart_physical(task_id, intent_digest, BOOT_ID)
        stopping_or_unknown = requested or (effect_started and outcome == "unknown")
        if token is not None and not stopping_or_unknown:
            runtime.reopen(token)
        if record is not None and not stopping_or_unknown:
            hub_update._finish(record, "failed", {"status": outcome})
        # A requested stop keeps both admission and the local sibling-action
        # reservation closed until this process exits. It is not complete yet.


async def after_boot(orch) -> None:
    """Recover only metadata, then let the notifier judge a different boot."""
    try:
        # Historical cleanup records only that an old process can no longer
        # spend an unclaimed intent. It must also run when execution is disabled;
        # the notifier and physical path retain their independent live floors.
        worker = getattr(orch, "autonomy", None)
        queue = getattr(worker, "queue", None)
        if queue is None or getattr(orch, "autonomy_queue", None) is not queue:
            return
        queue.recover_restart_attempts(BOOT_ID)
        from .restart_notice import notify_completed_restart

        await notify_completed_restart(orch, boot_id=BOOT_ID)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("restart startup notice unavailable", exc_info=True)
