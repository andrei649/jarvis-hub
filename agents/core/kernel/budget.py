"""budget.py — kernel scheduler primitives (K3, folds H23.1).

The OWASP *unbounded-consumption* guards that were missing (design spec §6): a per-task
**token + wall-time + recursion-depth** ledger, and a **loop-wide circuit breaker** that
trips on a runaway (the same action repeating past a threshold in a window). The kernel's
``authorize`` consults these at the single front door; when no ledger/detector is supplied
the gate is **inert** (K1 behavior preserved). Unifying the *existing* budgets
(``InterruptBudget`` ≤4/day, mission step/time caps, payment caps) into this one object is
a later K3 slice — this adds the three limits that did not exist anywhere yet.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetLimits:
    """Per-task ceilings. ``None`` = unlimited for that dimension."""
    max_tokens: int | None = None
    max_wall_seconds: float | None = None
    max_depth: int | None = None


@dataclass
class BudgetLedger:
    """Mutable running usage for one task, checked against its :class:`BudgetLimits`.

    The ledger is the *mutable* counterpart to the frozen per-action ``Budget`` descriptor
    — usage accrues across a task's steps, so it can't live on a frozen value.
    """
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    tokens_used: int = 0
    depth: int = 0
    started_at: float | None = None

    def start(self, now: float | None = None) -> None:
        """Mark the wall-clock start (idempotent — first call wins)."""
        if self.started_at is None:
            self.started_at = time.time() if now is None else now

    def add_tokens(self, n: int) -> None:
        self.tokens_used += max(0, int(n))

    def enter(self) -> None:
        self.depth += 1

    def leave(self) -> None:
        if self.depth > 0:
            self.depth -= 1

    def exceeded(self, now: float | None = None) -> str | None:
        """Return a human reason for the first breached limit, else None."""
        lim = self.limits
        if lim.max_tokens is not None and self.tokens_used > lim.max_tokens:
            return f"token budget exceeded ({self.tokens_used} > {lim.max_tokens})"
        if lim.max_depth is not None and self.depth > lim.max_depth:
            return f"recursion depth exceeded ({self.depth} > {lim.max_depth})"
        if lim.max_wall_seconds is not None and self.started_at is not None:
            now = time.time() if now is None else now
            elapsed = now - self.started_at
            if elapsed > lim.max_wall_seconds:
                return f"wall-time budget exceeded ({elapsed:.1f}s > {lim.max_wall_seconds}s)"
        return None


@dataclass
class LoopDetector:
    """Loop-wide circuit breaker. If the same action *signature* is recorded more than
    ``max_repeats`` times within ``window_seconds``, the breaker **trips** (opens) and
    stays open until :meth:`reset` — so a runaway loop is halted at the front door rather
    than spinning. (Per-plugin breakers already exist in ``resilience.py``; this is the
    loop-wide one the audit/H23.1 flagged as missing.)
    """
    max_repeats: int = 10
    window_seconds: float = 60.0
    _events: deque = field(default_factory=deque)
    _tripped: bool = False

    def record(self, signature: str, now: float | None = None) -> bool:
        """Record one action. Returns True while healthy, False once the breaker is open
        (including every call after it trips)."""
        if self._tripped:
            return False
        now = time.time() if now is None else now
        self._events.append((signature, now))
        cutoff = now - self.window_seconds
        while self._events and self._events[0][1] < cutoff:
            self._events.popleft()
        if sum(1 for s, _ in self._events if s == signature) > self.max_repeats:
            self._tripped = True
            return False
        return True

    @property
    def tripped(self) -> bool:
        return self._tripped

    def reset(self) -> None:
        self._tripped = False
        self._events.clear()
