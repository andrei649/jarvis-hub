"""Owner chat request for the existing irreversible hub.update approval card.

This command never runs an updater or restarts the hub. The approval queue may
refuse intake under strict mediation; that refusal is reported without fallback.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress

from . import hub_update_apply
from .channels.outbound_safety import sanitize_text

_CHAT_CHANNELS = frozenset({"web", "telegram", "discord", "slack", "matrix"})
_REQUEST_LOCK = threading.Lock()
_WITHHELD = "A reply could not be checked before sending, so it was withheld."
_STATUS_UNAVAILABLE = "Update status unavailable; check the local update status before retrying."
_TASK_STATES = {
    "proposed": "waiting for human approval",
    "blocked": "waiting for human approval",
    "approved": "approved; waiting to run",
    "running": "recorded as running",
    "failed": "recorded as failed",
    "rejected": "rejected",
    "deferred": "deferred",
    "quarantined": "quarantined",
    "expired": "expired",
}
_PHASES = {
    "started": "preparing",
    "backed_up": "backup complete",
    "fast_forwarded": "applying",
    "dependencies_installed": "applying",
    "restarting": "restart requested; final verification unavailable",
    "verifying": "checking the new boot",
    "rolling_back": "rolling back",
    "rolled_back_restarting": "rollback restart requested; final verification unavailable",
}
_RESULTS = {
    "verified": "verified",
    "failed": "failed",
    "refused": "refused",
    "rolled_back": "rolled back",
    "rollback_incomplete": "operator attention needed: rollback incomplete",
    "rollback_failed": "operator attention needed: rollback failed",
}
_REFUSALS = {
    "no_trust_configured": "Update request refused: no trusted update target is configured.",
    "dirty_tree": "Update request refused: the checkout has uncommitted changes.",
    "not_a_git_checkout": "Update request refused: this install is not a Git checkout.",
    "container": "Update request refused: this install is a container.",
    "restart_manual": "Update request refused: this hub cannot restart itself safely.",
    "update_in_progress": "Update request refused: an update is already pending or running (in progress).",
    "up_to_date": "Update request refused: the local target is already up to date.",
    "target_unknown": "Update request refused: no local update target is known; check update status.",
    "approval_queue_unavailable": "Update request refused: the approval queue is unavailable.",
    "approval_queue_refused": "Update request refused: the approval queue did not admit the card.",
}


def _request(orch):
    # A repeat while the first card waits is not another request. Query the
    # underlying queue strictly: irreversible.pending() intentionally turns a
    # failed read into [], which is unsafe for this dedupe decision.
    worker = getattr(orch, "autonomy", None)
    lister = getattr(getattr(worker, "queue", None), "pending_decisions", None)
    if not callable(lister):
        raise hub_update_apply.UpdateRefused("approval_queue_unavailable")
    try:
        pending = lister(kind="hub.update", limit=1)
    except Exception as exc:
        raise hub_update_apply.UpdateRefused("approval_queue_unavailable") from exc
    if not isinstance(pending, list):
        raise hub_update_apply.UpdateRefused("approval_queue_unavailable")
    # Fast UX check only. The durable queue's transactional singleton remains
    # authoritative across hub processes and covers later approval states.
    if pending:
        return {"existing": True}
    return hub_update_apply.request_apply(orch, None, "refuse", requested_by="owner (chat /update)")


async def _complete_worker(orch):
    worker = asyncio.create_task(asyncio.to_thread(_request, orch))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # A thread may have queued the card already; keep single-flight held
        # until its outcome is known, then propagate cancellation unchanged.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(BaseException):
            worker.result()
        raise


def _record_label(record) -> str | None:
    from .update_progress import ProgressRecord

    if (type(record) is not ProgressRecord or record.kind not in {"update", "rollback"}
            or record.task_id is not None and (
                type(record.task_id) is not int or not 0 < record.task_id <= (1 << 63) - 1)):
        return None
    if record.result is not None:
        return _RESULTS.get(record.result)
    return _PHASES.get(record.phase)


def _status_text(task, snapshot) -> str | None:
    from .update_progress import ProgressSnapshot

    if type(snapshot) is not ProgressSnapshot:
        return None
    if snapshot.current is not None and _record_label(snapshot.current) is None:
        return None
    if snapshot.last is not None and _record_label(snapshot.last) is None:
        return None
    if task is None:
        record = snapshot.current or snapshot.last
        if record is None:
            return "No update activity is recorded."
        label = _record_label(record)
        prefix = "Recorded update status" if snapshot.current is record else "Last recorded operation"
        return f"{prefix}: {label}."
    if (type(task.id) is not int or not 0 < task.id <= (1 << 63) - 1
            or task.kind != "hub.update" or task.agent != "owner"
            or task.status not in {*_TASK_STATES, "done"}):
        return None
    prefix = f"Recorded update status for card #{task.id}: "
    if task.status in {"running", "done"}:
        # A different in-flight operation takes precedence over an older
        # matching receipt; the old success cannot describe this latest card.
        records = ((snapshot.current,) if snapshot.current is not None
                   else (snapshot.last,))
        record = next((item for item in records if item is not None
                       and item.kind == "update" and item.task_id == task.id), None)
        if task.status == "done" and (record is None or record.result is None):
            return prefix + "final verification unavailable."
        if record is not None:
            return prefix + _record_label(record) + "."
    return prefix + _TASK_STATES[task.status] + "."


async def _status(orch) -> str:
    from . import update_progress

    worker = getattr(orch, "autonomy", None)
    queue = getattr(worker, "queue", None)
    if (queue is None or getattr(orch, "autonomy_queue", None) is not queue
            or not callable(getattr(queue, "list", None))):
        return _STATUS_UNAVAILABLE
    try:
        tasks = await asyncio.to_thread(queue.list, kind="hub.update", limit=1)
        if type(tasks) is not list or len(tasks) > 1:
            return _STATUS_UNAVAILABLE
        snapshot = await asyncio.to_thread(update_progress.read_progress_snapshot)
        if (getattr(orch, "autonomy", None) is not worker
                or getattr(orch, "autonomy_queue", None) is not queue
                or getattr(worker, "queue", None) is not queue):
            return _STATUS_UNAVAILABLE
        reply = _status_text(tasks[0] if tasks else None, snapshot)
        if reply is None:
            return _STATUS_UNAVAILABLE
        clean = sanitize_text(reply)
        return clean if len(clean) <= 512 else _STATUS_UNAVAILABLE
    except asyncio.CancelledError:
        raise
    except Exception:
        return _STATUS_UNAVAILABLE


async def update_command(ctx) -> str:
    """Ask a human to approve the locally verified update target."""
    if not ctx.principal.admin:
        return "Only the owner can request a hub update."
    if ctx.principal.channel not in _CHAT_CHANNELS:
        return "The update request is available from owner chat only."
    args = ctx.args.strip()
    if args == "status":
        return await _status(ctx.orch)
    if args:
        return "Usage: /update | /update status."
    if not _REQUEST_LOCK.acquire(blocking=False):
        return "An update request is already being prepared. Check pending approvals before retrying."
    try:
        try:
            result = await _complete_worker(ctx.orch)
        except hub_update_apply.UpdateRefused as exc:
            return _REFUSALS.get(exc.code, "Update request refused by existing policy.")
        except asyncio.CancelledError:
            raise
        except Exception:
            return "Update request outcome is uncertain. Check pending approvals before retrying."
        if not isinstance(result, dict):
            return "Update request outcome is uncertain. Check pending approvals before retrying."
        if result.get("existing") is True:
            return "A hub update approval is already pending. Review it before requesting another."
        pending = result.get("pending")
        if type(pending) is not int or pending <= 0:
            return "Update request outcome is uncertain. Check pending approvals before retrying."
        raw = (f"Update approval card #{pending} queued. A human must approve the "
               "irreversible hub.update action. This command only queued the card.")
        try:
            clean = sanitize_text(raw)
        except Exception:
            return _WITHHELD
        return clean if clean != _WITHHELD and len(clean) <= 512 else _WITHHELD
    finally:
        _REQUEST_LOCK.release()


__all__ = ["update_command"]
