"""Persist scheduler outcomes without retaining arguments, return data or exceptions."""

import logging
import threading

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
)

logger = logging.getLogger(__name__)


def _returned_status(value) -> str:
    if not isinstance(value, dict):
        return "ok"
    explicit = value.get("_scheduler_status")
    if explicit in {"failed", "skipped"}:
        return explicit
    # These are the existing native job contracts, not arbitrary error-text matching.
    if value.get("reason") in {"probe_failed", "scan_failed", "living_memory_failed"}:
        return "failed"
    reprojection = value.get("reprojection")
    if isinstance(reprojection, dict) and reprojection.get("reason") == "reprojection_failed":
        return "failed"
    decay = value.get("decay")
    if isinstance(decay, dict) and decay.get("reason") == "decay_failed":
        return "failed"
    skipped = value.get("skipped")
    if skipped is True or (isinstance(skipped, str) and skipped and value.get("ok") is False):
        return "skipped"
    return "failed" if value.get("ok") is False else "ok"


def install_scheduler_health(scheduler, store) -> None:
    """Install once per scheduler; recording failures must not affect job execution."""
    if getattr(scheduler, "_nerva_health_listener", None) is not None:
        return
    pending = set()
    overflow = False
    lock = threading.Lock()

    def persist(event):
        nonlocal overflow
        statuses = {EVENT_JOB_ERROR: "failed", EVENT_JOB_MISSED: "missed",
                    EVENT_JOB_MAX_INSTANCES: "max_instances"}
        try:
            status = statuses.get(event.code) or _returned_status(getattr(event, "retval", None))
            if status == "skipped":
                return
            store.record_scheduler_result(str(event.job_id), status)
            pending.discard(event.job_id)
            scheduler._nerva_health_error = bool(pending) or overflow
        except Exception:
            if len(pending) < 256:
                pending.add(event.job_id)
            else:
                overflow = True
            scheduler._nerva_health_error = True
            logger.warning("Scheduler health outcome could not be persisted")

    def record(event):
        with lock:
            persist(event)

    scheduler.add_listener(record, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES)
    scheduler._nerva_health_listener = record
    scheduler._nerva_health_error = False
