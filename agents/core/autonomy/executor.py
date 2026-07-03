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

import asyncio
import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.autonomy.executor")

Handler = Callable[[object], Awaitable[dict]]


class TaskExecutor:
    def __init__(self, fallback: Optional[Handler] = None,
                 max_wall_seconds: Optional[float] = None,
                 budget_ledger=None):
        self._handlers: dict[str, Handler] = {}
        self.fallback = fallback
        # K3 (OWASP unbounded-consumption): a per-task wall-time budget. None = unbounded
        # (the default → byte-identical behavior); set via JARVIS_TASK_MAX_SECONDS at the
        # worker. A task that overruns is cancelled and returns a clean failed result.
        self.max_wall_seconds = max_wall_seconds
        self.budget_ledger = budget_ledger

    def register(self, prefix: str, handler: Handler) -> "TaskExecutor":
        """Register a handler for any task kind starting with `prefix`."""
        self._handlers[prefix.lower()] = handler
        return self

    def resolve(self, kind: str) -> Optional[Handler]:
        kind = (kind or "").lower()
        best: Optional[str] = None
        for prefix in self._handlers:
            if kind == prefix or kind.startswith(prefix):
                if best is None or len(prefix) > len(best):
                    best = prefix
        return self._handlers[best] if best is not None else self.fallback

    async def execute(self, task) -> dict:
        handler = self.resolve(getattr(task, "kind", ""))
        if handler is None:
            return {"status": "noop", "note": f"no handler for kind={getattr(task, 'kind', '?')}"}
        if self.max_wall_seconds is not None:
            try:
                result = await asyncio.wait_for(handler(task), timeout=self.max_wall_seconds)
            except TimeoutError:
                logger.warning("task wall-time budget exceeded (kind=%s, %.0fs)",
                               getattr(task, "kind", "?"), self.max_wall_seconds)
                return {"status": "failed", "reason": "wall_time_budget_exceeded",
                        "budget_seconds": self.max_wall_seconds}
        else:
            result = await handler(task)
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
