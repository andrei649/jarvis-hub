"""Autonomy → IntentLog audit sink.

`AutonomyWorker` and `RemediationRunner` both call ``audit.log(event, fields)``
with a plain event string and a flat dict. `AuditLogger.log()` (the guardrails
DB) takes a `SecurityEvent`, so those calls could never have worked against it —
and in production `audit` was left `None`, so the whole autonomy lifecycle
(auto-approve, push, decision, execute, fail) was never recorded anywhere.

This adapter maps that call shape onto :class:`IntentLog`, which is the right
sink for it on two counts:

* it is **always HMAC-signed** with an out-of-tree key, so an action record can't
  be forged by write access to the log alone — unlike the guardrails audit DB,
  whose rows are plain sha256 unless ``JARVIS_AUDIT_KEY`` is set;
* it already models *intent* (``why``/``cause``), which is exactly what an action
  record needs: not just "a task executed" but which task, whose decision, and
  why it was allowed.

Never raises: both call sites treat auditing as best-effort, and a failed audit
write must not abort an action that policy already authorized.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("jarvis.autonomy.audit")

# Fields lifted out of the payload into first-class record slots.
_ACTOR_KEYS = ("agent", "service")
_WHY_KEYS = ("detail", "reason", "status")


def _jsonable(value: Any) -> Any:
    """Coerce a value into something IntentLog can hash deterministically."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


class ActionAuditSink:
    """``log(event, fields)`` → one signed :class:`IntentLog` record."""

    def __init__(self, intent_log, *, default_actor: str = "autonomy") -> None:
        self._intent_log = intent_log
        self._default_actor = default_actor

    def log(self, event: str, fields: dict | None = None) -> dict | None:
        if self._intent_log is None:
            return None
        fields = dict(fields or {})
        actor = self._default_actor
        for key in _ACTOR_KEYS:
            if fields.get(key):
                actor = str(fields[key])
                break
        why = ""
        for key in _WHY_KEYS:
            if fields.get(key):
                why = str(fields[key])
                break
        task_id = fields.get("task_id")
        cause = f"task:{task_id}" if task_id is not None else str(fields.get("kind") or "")
        metadata = {k: _jsonable(v) for k, v in fields.items()}
        try:
            return self._intent_log.record(
                actor=actor, action=str(event), why=why, cause=cause, metadata=metadata,
            )
        except Exception:
            logger.warning("action audit record failed for '%s'", event, exc_info=True)
            return None

    # Read side, so callers can verify without reaching past the adapter.
    def verify(self) -> dict:
        if self._intent_log is None:
            return {"ok": True, "bad_seq": None, "n": 0}
        return self._intent_log.verify()

    def count(self) -> int:
        if self._intent_log is None:
            return 0
        return len(self._intent_log.list(limit=10_000))
