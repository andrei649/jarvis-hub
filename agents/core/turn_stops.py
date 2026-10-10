"""Request-owned source-assigned stops, independent of final response wording.

An empty list is not a proof of success. Only the runtime's finite exit vocabulary
can add a stop; these observations never execute tools or decide approvals.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar

from .tool_loop_result import ToolLoopExitReason

STOP_REASONS = frozenset(
    reason.value for reason in ToolLoopExitReason
    if reason is not ToolLoopExitReason.MODEL_RESPONSE
) | {"thinking_exhausted", "generation_failed", "generation_refused", "continuation_refused"}


class TurnStops:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._reasons: set[str] = set()

    def record(self, reason: object) -> None:
        if not isinstance(reason, str) or reason not in STOP_REASONS:
            return
        with self._lock:
            if not self._closed:
                self._reasons.add(str(reason))

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def snapshot(self) -> list[str]:
        with self._lock:
            return sorted(self._reasons)


_CURRENT: ContextVar[TurnStops | None] = ContextVar("turn_runtime_stops", default=None)


@contextmanager
def turn_stops_scope():
    collector = TurnStops()
    token = _CURRENT.set(collector)
    try:
        yield collector
    finally:
        collector.close()
        _CURRENT.reset(token)


@contextmanager
def detached_turn_stops():
    token = _CURRENT.set(None)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def record_runtime_stop(reason: object) -> None:
    collector = _CURRENT.get()
    if collector is not None:
        collector.record(reason)
