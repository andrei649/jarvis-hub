"""kernel/metrics.py — in-process tally of ``kernel.authorize`` decisions (observability).

Mirrors ``observability/egress_monitor``: a single thread-safe, in-memory instance the
kernel records **every** decision into (via ``_emit_audit``, the universal decision exit),
read by ``GET /api/metrics/kernel``. In-memory only — it resets on restart; the durable
record is the IntentLog audit chain, not this. Naturally **inert when the kernel is off**:
brokers/routes only call ``authorize`` when ``JARVIS_ACTION_KERNEL`` is set, so nothing is
tallied otherwise.

Now that Gate-K routes every privileged action through ``authorize``, this is the single
place to see what the kernel is doing — how many actions it granted / queued / denied, per
kind, plus the recent denials (with reasons) so a halt / runaway / over-budget is visible.
"""

from __future__ import annotations

import threading
from collections import deque

_VERDICTS = ("grant", "deny", "queue")
_MAX_DENIALS = 200


class KernelMetrics:
    """Monotonic per-kind decision counters + a bounded ring of recent denials."""

    def __init__(self, max_denials: int = _MAX_DENIALS) -> None:
        self._lock = threading.Lock()
        self._by_kind: dict[str, dict[str, int]] = {}
        self._totals: dict[str, int] = dict.fromkeys(_VERDICTS, 0)
        self._denials: deque[dict] = deque(maxlen=max_denials)

    def record(self, kind: str, verdict: str, reason: str = "") -> None:
        """Tally one decision. Never raises — observability must not break the gate."""
        v = str(verdict)
        if v not in self._totals:
            return
        kind = kind or "unknown"
        with self._lock:
            row = self._by_kind.get(kind)
            if row is None:
                row = self._by_kind[kind] = dict.fromkeys(_VERDICTS, 0)
            row[v] += 1
            self._totals[v] += 1
            if v == "deny":
                self._denials.append({"kind": kind, "reason": reason or ""})

    def snapshot(self, recent: int = 50) -> dict:
        """Per-kind + overall tallies, deny-rate, and the newest-first recent denials."""
        with self._lock:
            total = sum(self._totals.values())
            return {
                "total": total,
                "by_verdict": dict(self._totals),
                "by_kind": {k: dict(v) for k, v in sorted(self._by_kind.items())},
                "deny_rate": round(self._totals["deny"] / total, 4) if total else 0.0,
                "recent_denials": list(reversed(self._denials))[:max(0, recent)],
            }

    def reset(self) -> None:
        """Clear all state (restart-equivalent; used by tests for isolation)."""
        with self._lock:
            self._by_kind.clear()
            self._totals = dict.fromkeys(_VERDICTS, 0)
            self._denials.clear()


# Module-level singleton shared by the kernel (writer) and the metrics endpoint (reader).
KERNEL_METRICS = KernelMetrics()
