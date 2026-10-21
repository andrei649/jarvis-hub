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

#: H288: the shipped wall-clock budget for one queued in-process task. Finite and below the
#: 3600 s stuck-running reaper TTL, so a hung handler is cancelled and recorded as a failed
#: task long before the reaper has to reclaim the row.
TASK_MAX_SECONDS_SETTING = "autonomy.task_max_seconds"
DEFAULT_TASK_MAX_SECONDS = 1800
MAX_TASK_MAX_SECONDS = 86_400


def resolve_task_budget(get_setting: Optional[Callable[..., object]]) -> float:
    """The per-task wall-time budget: a positive ``JARVIS_TASK_MAX_SECONDS`` wins, then the
    validated ``autonomy.task_max_seconds`` setting, then the finite default. Never None."""
    from ..env_config import env_float

    override = env_float("JARVIS_TASK_MAX_SECONDS", 0.0, minimum=0.0)
    if override > 0:
        return float(override)
    value = None
    if callable(get_setting):
        try:
            value = get_setting(TASK_MAX_SECONDS_SETTING, DEFAULT_TASK_MAX_SECONDS)
        except Exception:
            logger.warning("%s could not be read; using the default", TASK_MAX_SECONDS_SETTING)
    if type(value) is int and 1 <= value <= MAX_TASK_MAX_SECONDS:
        return float(value)
    return float(DEFAULT_TASK_MAX_SECONDS)


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
        # for a bare executor; the shipped worker always passes ``resolve_task_budget(...)``
        # (H288: finite by default). A task that overruns is cancelled and returns a clean
        # failed result.
        self.max_wall_seconds = max_wall_seconds
        self.budget_ledger = budget_ledger
        self.execution_guard = execution_guard
        # H288 review: prefixes whose handler enforces its own owner-set runtime cap (the
        # Kanban worker's per-card ``max_runtime_seconds``). The global budget must not cut
        # them short and pre-empt their own timeout outcome.
        self._self_bounded: set[str] = set()

    def register(self, prefix: str, handler: Handler, *, self_bounded: bool = False) -> "TaskExecutor":
        """Register a handler for any task kind starting with `prefix`.

        ``self_bounded=True`` declares that the handler bounds its own runtime, so the
        executor's ``max_wall_seconds`` does not apply to the kinds it runs."""
        key = prefix.lower()
        self._handlers[key] = handler
        if self_bounded:
            self._self_bounded.add(key)
        else:
            self._self_bounded.discard(key)
        return self

    def budget_for(self, kind: str) -> Optional[float]:
        """The wall-time budget applied to *kind*: None when a self-bounded handler runs it
        (it enforces its own cap), otherwise ``max_wall_seconds``."""
        prefix = self._prefix_for(kind)
        if prefix is not None and prefix in self._self_bounded:
            return None
        return self.max_wall_seconds

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

        budget = self.budget_for(getattr(dispatch_task, "kind", ""))
        if budget is not None or consent_scope_present():
            handler_task = asyncio.create_task(handler(dispatch_task))
            authorized = authorize_consent_handler(self, dispatch_task, handler_task)
            if authorized is False:
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
                return {"status": "refused", "reason": "mediation_execution_context_required"}
            try:
                if budget is None:
                    result = await handler_task
                else:
                    result = await asyncio.wait_for(handler_task, timeout=budget)
            except TimeoutError:
                if budget is None:
                    raise  # the handler's own timeout, not the executor's budget
                logger.warning(
                    "task wall-time budget exceeded (kind=%s, %.0fs)",
                    getattr(dispatch_task, "kind", "?"),
                    budget,
                )
                return {
                    "status": "failed",
                    "reason": "wall_time_budget_exceeded",
                    "budget_seconds": budget,
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
