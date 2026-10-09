"""
executor.py — Task executor registry (H6 follow-up).

Maps a task's `kind` to a concrete handler so the autonomy worker actually does
work instead of no-op'ing. Handlers are async callables `handler(task) -> dict`.
Dispatch is by longest matching kind-prefix, with an optional fallback.

The registry is decoupled from the orchestrator: web.py/orchestrator register
handlers backed by plugins (websearch, gmail, …) or the LLM pipeline. Keeping
dispatch pure makes it unit-testable offline.
"""

from __future__ import annotations

if __name__ != "agents.core.autonomy.executor":
    raise ImportError("TaskExecutor authority must be imported as agents.core.autonomy.executor")

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from .queue import TaskQueue

logger = logging.getLogger("jarvis.autonomy.executor")

Handler = Callable[[object], Awaitable[dict]]

#: The reason key on the executor's refusal when its execution guard said why it declined.
GUARD_REASON_KEY = "guard_reason"


class ExecutionGuardDeclined(Exception):
    """An execution guard declining for a reason it can name (review round 6, item 6).

    A guard returns True to allow, or False / raises anything else when it cannot allow
    — machinery, recorded as a failure of the capability. A guard whose GATE declined
    before any attempt (a feature switched off, a configuration or approval that changed,
    the kernel denying) raises this with the gate's reason instead: the executor's
    refusal carries it as ``guard_reason``, and the autonomy worker records nothing when
    the reason is a refusal of the task's kind."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TaskExecutor:
    def __init__(
        self,
        fallback: Optional[Handler] = None,
        max_wall_seconds: Optional[float] = None,
        budget_ledger=None,
        execution_guard=None,
    ):
        self._handlers: dict[str, Handler] = {}
        self.fallback = fallback
        # K3 (OWASP unbounded-consumption): a per-task wall-time budget. None = unbounded
        # (the default → byte-identical behavior); set via JARVIS_TASK_MAX_SECONDS at the
        # worker. A task that overruns is cancelled and returns a clean failed result.
        self.max_wall_seconds = max_wall_seconds
        self.budget_ledger = budget_ledger
        self.execution_guard = execution_guard

    def register(self, prefix: str, handler: Handler) -> "TaskExecutor":
        """Register a handler for any task kind starting with `prefix`."""
        self._handlers[prefix.lower()] = handler
        return self

    def _prefix_for(self, kind: str) -> Optional[str]:
        kind = (kind or "").lower()
        best: Optional[str] = None
        for prefix in self._handlers:
            if kind == prefix or kind.startswith(prefix):
                if best is None or len(prefix) > len(best):
                    best = prefix
        return best

    def resolve(self, kind: str) -> Optional[Handler]:
        best = self._prefix_for(kind)
        return self._handlers[best] if best is not None else self.fallback

    def handles(self, kind: str) -> bool:
        """Whether a handler registered for *kind* (not the generic fallback) runs it.

        The autonomy worker records a capability outcome only for a task a registered
        handler ran: a kind that falls through to the fallback (the LLM pipeline) did
        not exercise the capability its manifest names (review round 5, item 9)."""
        return self._prefix_for(kind) is not None

    async def execute(self, task) -> dict:
        # The guard and handler must observe the same detached bytes.  Without
        # this snapshot, a caller can mutate the original Task after the
        # synchronous guard returns but before an async handler reads it.
        dispatch_task = task
        if self.execution_guard is not None:
            dispatch_task = TaskQueue.detach_execution_task(task)
            if dispatch_task is None:
                return {
                    "status": "refused",
                    "reason": "mediation_execution_context_required",
                }
        if self.execution_guard is not None:
            guard_reason = None
            try:
                allowed = self.execution_guard(dispatch_task) is True
            except ExecutionGuardDeclined as declined:
                allowed = False
                if isinstance(declined.reason, str) and declined.reason:
                    guard_reason = declined.reason
            except Exception:
                allowed = False
            if not allowed:
                refused = {
                    "status": "refused",
                    "reason": "mediation_execution_context_required",
                }
                if guard_reason is not None:
                    refused[GUARD_REASON_KEY] = guard_reason
                return refused
        handler = self.resolve(getattr(dispatch_task, "kind", ""))
        if handler is None:
            return {
                "status": "noop",
                "note": f"no handler for kind={getattr(dispatch_task, 'kind', '?')}",
            }
        # A consented handler needs its own exact task binding. wait_for creates
        # a child Task, and an inherited ContextVar alone cannot authorize it.
        from .consent_execution import authorize_consent_handler, consent_scope_present

        if self.max_wall_seconds is not None or consent_scope_present():
            handler_task = asyncio.create_task(handler(dispatch_task))
            authorized = authorize_consent_handler(self, dispatch_task, handler_task)
            if authorized is False:
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
                return {"status": "refused", "reason": "mediation_execution_context_required"}
            try:
                if self.max_wall_seconds is None:
                    result = await handler_task
                else:
                    result = await asyncio.wait_for(handler_task, timeout=self.max_wall_seconds)
            except TimeoutError:
                logger.warning(
                    "task wall-time budget exceeded (kind=%s, %.0fs)",
                    getattr(dispatch_task, "kind", "?"),
                    self.max_wall_seconds,
                )
                return {
                    "status": "failed",
                    "reason": "wall_time_budget_exceeded",
                    "budget_seconds": self.max_wall_seconds,
                }
        else:
            result = await handler(dispatch_task)
        result = result if isinstance(result, dict) else {"status": "ok", "output": result}
        self._record_tokens(result)
        return result

    def _record_tokens(self, result: dict) -> None:
        if self.budget_ledger is None or "tokens_used" not in result:
            return
        try:
            self.budget_ledger.add_tokens(result["tokens_used"])
        except (TypeError, ValueError):
            logger.debug("task token usage was not numeric: %r", result.get("tokens_used"))
