"""budget.py — kernel scheduler primitives (K3, folds H23.1).

The OWASP *unbounded-consumption* guards that were missing (design spec §6): a per-task
**token + wall-time + recursion-depth** ledger, and a **loop-wide circuit breaker** that
trips on a runaway (the same action repeating past a threshold in a window). The kernel's
``authorize`` consults these at the single front door; when no ledger/detector is supplied
the gate is **inert** (K1 behavior preserved). The same ledger now exposes named dimensions
for existing budgets (``InterruptBudget`` <=4/day, mission step caps, payment mandate caps),
so callers can share one kernel-readable view without replacing the legacy gates that
already own those semantics.
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
class BudgetDimension:
    """Named usage/cap pair surfaced through the shared K3 ledger."""
    name: str
    used: float = 0.0
    limit: float | None = None
    unit: str = ""
    enforced: bool = True
    metadata: dict = field(default_factory=dict)


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
    dimensions: dict[str, BudgetDimension] = field(default_factory=dict)

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

    def register_dimension(self, name: str, *, limit: float | None = None,
                           used: float = 0.0, unit: str = "",
                           enforced: bool = True,
                           metadata: dict | None = None) -> BudgetDimension:
        """Register or replace a named budget dimension."""
        dimension = BudgetDimension(
            name=str(name),
            used=max(0.0, float(used)),
            limit=None if limit is None else float(limit),
            unit=str(unit or ""),
            enforced=bool(enforced),
            metadata=dict(metadata or {}),
        )
        self.dimensions[dimension.name] = dimension
        return dimension

    def set_dimension_usage(self, name: str, used: float, *,
                            limit: float | None = None, unit: str = "",
                            enforced: bool = True,
                            metadata: dict | None = None) -> BudgetDimension:
        """Set current usage for a named budget dimension.

        Existing dimensions keep their limit unless a new one is supplied.
        """
        key = str(name)
        dimension = self.dimensions.get(key)
        if dimension is None:
            return self.register_dimension(
                key, limit=limit, used=used, unit=unit,
                enforced=enforced, metadata=metadata,
            )
        dimension.used = max(0.0, float(used))
        if limit is not None:
            dimension.limit = float(limit)
        if unit:
            dimension.unit = str(unit)
        dimension.enforced = bool(enforced)
        if metadata is not None:
            dimension.metadata = dict(metadata)
        return dimension

    def add_dimension_usage(self, name: str, amount: float = 1.0) -> BudgetDimension:
        """Accrue usage against a named budget dimension."""
        key = str(name)
        dimension = self.dimensions.get(key)
        if dimension is None:
            dimension = self.register_dimension(key)
        dimension.used += max(0.0, float(amount))
        return dimension

    @staticmethod
    def _display_number(value: float | None) -> float | int | None:
        if value is None:
            return None
        return int(value) if float(value).is_integer() else value

    def dimension_status(self, name: str) -> dict:
        """Return a stable status dict for one named dimension."""
        dimension = self.dimensions[str(name)]
        remaining = None
        if dimension.limit is not None:
            remaining = max(0.0, dimension.limit - dimension.used)
        return {
            "name": dimension.name,
            "used": self._display_number(dimension.used),
            "limit": self._display_number(dimension.limit),
            "remaining": self._display_number(remaining),
            "unit": dimension.unit,
            "enforced": dimension.enforced,
            "metadata": dict(dimension.metadata),
        }

    def dimensions_status(self) -> dict[str, dict]:
        """Return status for all named dimensions, keyed by name."""
        return {name: self.dimension_status(name) for name in sorted(self.dimensions)}

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
        for dimension in self.dimensions.values():
            if (dimension.enforced and dimension.limit is not None
                    and dimension.used > dimension.limit):
                used = self._display_number(dimension.used)
                limit = self._display_number(dimension.limit)
                return f"{dimension.name} budget exceeded ({used} > {limit})"
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

    def status(self) -> dict:
        """Operability snapshot (mirrors ``KillSwitch.status``) for the admin endpoint."""
        return {
            "tripped": self._tripped,
            "max_repeats": self.max_repeats,
            "window_seconds": self.window_seconds,
            "recent_events": len(self._events),
        }

    def reset(self) -> None:
        self._tripped = False
        self._events.clear()
