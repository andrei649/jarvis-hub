"""
iteration_budget.py — H20.x Per-agent iteration budget (consume/refund counter).

Thread-safe counter that caps how many loop iterations (LLM calls, sub-agent
spawns, pipeline steps) a single actor may burn. `refund()` gives an iteration
back — e.g. for programmatic tool-calling steps that shouldn't eat the budget.

Ported from hermes-agent `agent/iteration_budget.py` (Nous Research, MIT) and
adapted to jarvis conventions; see LICENSES/THIRD_PARTY.md.
"""

from __future__ import annotations

import threading


class IterationBudget:
    """Thread-safe iteration counter for an agent or manager.

    Each actor (orchestrator turn loop, sub-agent manager, pipeline) holds its
    own budget. `consume()` returns False once the cap is reached — the caller
    stops instead of looping forever (OWASP unbounded-consumption, cf. K3).
    """

    def __init__(self, max_total: int):
        self.max_total = max(0, int(max_total))
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Try to consume one iteration. Returns True if allowed."""
        with self._lock:
            if self._used >= self.max_total:
                return False
            self._used += 1
            return True

    def refund(self) -> None:
        """Give back one iteration (e.g. for zero-cost bookkeeping turns)."""
        with self._lock:
            if self._used > 0:
                self._used -= 1

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_total - self._used)

    def status(self) -> dict:
        with self._lock:
            return {"max_total": self.max_total, "used": self._used,
                    "remaining": max(0, self.max_total - self._used)}


__all__ = ["IterationBudget"]
