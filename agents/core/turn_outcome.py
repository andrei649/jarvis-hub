"""Request-owned outcome for one completed orchestrator turn.

The context variable carries a mutable collector across the orchestrator's
copied task contexts. Only its first wrapper may publish, and closing it makes
late child writes inert. No last-turn value is retained on an orchestrator.
"""

from __future__ import annotations

import functools
import math
import time
from contextvars import ContextVar


class TurnOutcomeCollector:
    def __init__(self) -> None:
        self._claimed = False
        self._closed = False
        self._latency_ms: int | None = None

    def claim(self) -> bool:
        if self._closed or self._claimed:
            return False
        self._claimed = True
        return True

    def publish(self, latency_ms: int) -> bool:
        if (self._closed or not self._claimed or self._latency_ms is not None
                or type(latency_ms) is not int or latency_ms < 0):
            return False
        self._latency_ms = latency_ms
        return True

    def close(self) -> dict[str, int] | None:
        self._closed = True
        return None if self._latency_ms is None else {"latency_ms": self._latency_ms}


_current: ContextVar[TurnOutcomeCollector | None] = ContextVar("turn_outcome", default=None)


def open_turn_outcome() -> tuple[TurnOutcomeCollector, object]:
    sink = TurnOutcomeCollector()
    return sink, _current.set(sink)


def reset_turn_outcome(token: object) -> None:
    _current.reset(token)


def record_turn_latency(latency_ms: int) -> bool:
    """Publish one already measured duration; useful to non-wrapper callers."""
    sink = _current.get()
    return bool(sink and sink.claim() and sink.publish(latency_ms))


def measure_turn_latency(fn):
    """Time one public orchestrator call through its cleanup, on normal return only."""
    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        sink = _current.get()
        if sink is None or not sink.claim():
            return await fn(*args, **kwargs)
        started = time.perf_counter()
        result = await fn(*args, **kwargs)
        elapsed = (time.perf_counter() - started) * 1000
        if math.isfinite(elapsed):
            sink.publish(max(0, round(elapsed)))
        return result

    return wrapped
