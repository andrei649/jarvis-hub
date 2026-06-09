"""
turn_context.py — per-request transient cognition state (H21.0).

Async-context-local (``contextvars``), mirroring the BUG-5 fix: each request
binds its own ``TurnContext`` so concurrent turns never clobber each other's
state on a shared instance. Submodules (affect, honesty, memory, learning) read
and write their per-turn scratch here instead of touching the orchestrator.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Optional

_current: "contextvars.ContextVar[Optional[TurnContext]]" = contextvars.ContextVar(
    "cognition_turn", default=None
)


class TurnContext:
    """Transient state for a single turn (request)."""

    def __init__(self, session_id: str = "", agent: str = "", user: str = "") -> None:
        self.session_id = session_id
        self.agent = agent
        self.user = user
        self._scratch: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._scratch[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._scratch.get(key, default)

    def snapshot(self) -> dict:
        return {"session_id": self.session_id, "agent": self.agent,
                "user": self.user, "scratch": dict(self._scratch)}

    @classmethod
    def current(cls) -> "Optional[TurnContext]":
        return _current.get()

    @classmethod
    @contextlib.contextmanager
    def bind(cls, ctx: "TurnContext"):
        """Bind *ctx* as the current turn for the duration of the block."""
        token = _current.set(ctx)
        try:
            yield ctx
        finally:
            _current.reset(token)
