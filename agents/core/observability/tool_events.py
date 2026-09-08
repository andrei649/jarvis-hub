"""tool_events.py — the tool loop's own trail, kept somewhere the owner can read it.

``AgentToolRuntime`` emits a typed event at every step it takes: ``tool_requested``,
``tool_started``, ``tool_result`` / ``tool_failed``, the loop breakers
(``tool_loop_repeated``, ``tool_loop_failing``, ``tool_cap_reached``), the profile
decision (``tool_profile``) and — since the Hermes absorption 5a fence —
``tool_result_untrusted`` whenever a result is wrapped as DATA and the turn is
tainted. Every one of them went nowhere: ``_emit`` returns immediately when no sink
is passed, and ``Agent.generate_response``, the only production caller of ``run``,
never passed one. So the fence worked and left no trace, and the owner-verification
packet asked its reader to check "the timeline" for an event that had no destination.

This is that destination. One in-process, thread-safe, bounded ring buffer, read back
through ``GET /api/admin/tool-events`` and ``nerva tools``.

In memory on purpose. This is live observability, not the durable record — the signed
audit log is that — so it resets on restart and can never grow without bound. The
events the runtime emits already carry only bounded identifiers, machine reasons and
counts, never a tool's arguments and never its result; :func:`_bounded` re-applies
those limits here rather than trusting them, because a future emitter that forgets is
a leak into a surface the owner reads casually.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any

#: Events kept. A busy turn emits a handful per tool call, so this is roughly the last
#: few dozen turns — enough to answer "what did it just do", short of a log file.
MAX_EVENTS = 500
#: Per-event limits, re-applied here rather than trusted from the emitter.
MAX_KEYS = 16
MAX_VALUE_CHARS = 256
MAX_LIST_ITEMS = 8


def _bounded_value(value: Any) -> Any:
    """One event field, cut to a size a casual reader can take in.

    Scalars pass through; a string is cut; a list becomes a short list of cut strings;
    anything else becomes its type name rather than a repr, because a repr is exactly
    how a tool's arguments would leak into a surface that promises not to carry them.
    """
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_VALUE_CHARS]
    if isinstance(value, (list, tuple)):
        return [str(item)[:MAX_VALUE_CHARS] for item in list(value)[:MAX_LIST_ITEMS]]
    return type(value).__name__


def _bounded(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {"event": "malformed", "kind": type(event).__name__}
    out: dict[str, Any] = {}
    for key, value in list(event.items())[:MAX_KEYS]:
        out[str(key)[:MAX_VALUE_CHARS]] = _bounded_value(value)
    return out


class ToolEventLog:
    """Bounded, thread-safe. The runtime hands events over from a worker thread."""

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_events)))
        self._counts: Counter[str] = Counter()
        self._seq = 0
        self._lock = threading.Lock()

    def record(self, event: Any) -> None:
        """Append one event. Never raises: an observability sink that can break a turn
        is worse than a missing line (the runtime swallows a raising sink, but it also
        stops using it, so this must simply not raise)."""
        try:
            row = _bounded(event)
        except Exception:
            row = {"event": "malformed"}
        with self._lock:
            self._seq += 1
            row["seq"] = self._seq
            row["at"] = datetime.now(UTC).isoformat()
            self._events.append(row)
            self._counts[str(row.get("event", "unknown"))] += 1

    def snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        """The most recent events, newest last (reading order for a trail)."""
        bound = max(1, min(int(limit or 1), MAX_EVENTS))
        with self._lock:
            rows = list(self._events)[-bound:]
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        """Per-event-name totals since boot. Monotonic: they survive ring eviction, so
        "did the fence ever fire" has an answer even after the buffer has turned over."""
        with self._lock:
            return dict(self._counts)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._counts.clear()
            self._seq = 0


#: The process-wide log. One per process, like the egress monitor next door.
TOOL_EVENTS = ToolEventLog()
