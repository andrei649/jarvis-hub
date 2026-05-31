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

import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.autonomy.executor")

Handler = Callable[[object], Awaitable[dict]]


class TaskExecutor:
    def __init__(self, fallback: Optional[Handler] = None):
        self._handlers: dict[str, Handler] = {}
        self.fallback = fallback

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
        result = await handler(task)
        return result if isinstance(result, dict) else {"status": "ok", "output": result}
