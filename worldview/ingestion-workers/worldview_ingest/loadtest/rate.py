"""Deterministic, drift-free rate scheduler for the load-test rig (ticket H19.1.6).

Pure: the schedule is a function of ``(target_rate, duration_s, tick_s)`` only — no
clock is read here. The async runner reads a clock to *pace* the ticks, but HOW MANY
messages each tick carries is decided by this pure planner, so the count logic is
fully unit-testable.

Drift-free counting
-------------------
Naively sending ``round(rate * tick_s)`` messages per tick accumulates rounding error
(e.g. 2.5 msg/tick -> 2 every tick loses 20%). Instead we track the CUMULATIVE target
``floor(rate * elapsed)`` and emit the delta since the previous tick. Over the whole
run this emits exactly ``floor(rate * duration_s)`` messages with the per-tick counts
differing by at most one — even pacing with zero long-run drift.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from math import floor, isfinite


@dataclass(frozen=True)
class Tick:
    """One scheduled tick: ``index`` ticks in, due at ``t_offset`` s, carrying ``count`` msgs.

    ``t_offset`` is the offset (seconds) from the run start at which this tick should
    fire; the async runner adds it to its start instant. ``cumulative`` is the total
    number of messages scheduled up to and including this tick (handy for assertions).
    """

    index: int
    t_offset: float
    count: int
    cumulative: int


@dataclass(frozen=True)
class RateSchedule:
    """A drift-free send plan for ``target_rate`` msg/s over ``duration_s`` seconds.

    The run is divided into ``ceil(duration_s / tick_s)`` ticks of width ``tick_s``
    (the final tick is truncated to the duration). Each tick's ``count`` is the delta
    of the cumulative ``floor(rate * elapsed)`` target, so the totals never drift.
    """

    target_rate: float
    duration_s: float
    tick_s: float

    def __post_init__(self) -> None:
        if not (isfinite(self.target_rate) and self.target_rate >= 0):
            raise ValueError(f"target_rate must be a finite >= 0, got {self.target_rate}")
        if not (isfinite(self.duration_s) and self.duration_s >= 0):
            raise ValueError(f"duration_s must be a finite >= 0, got {self.duration_s}")
        if not (isfinite(self.tick_s) and self.tick_s > 0):
            raise ValueError(f"tick_s must be a finite > 0, got {self.tick_s}")

    @property
    def total_messages(self) -> int:
        """Exact total messages over the whole run: ``floor(rate * duration_s)``."""
        return floor(self.target_rate * self.duration_s)

    def __iter__(self) -> Iterator[Tick]:
        """Yield the per-tick plan, in order, with drift-free counts.

        The tick at ``index`` fires at ``t_offset = (index + 1) * tick_s`` (clamped to
        ``duration_s``) — i.e. messages for the interval ending at that offset are sent
        at its end. ``count`` is the increase in ``floor(rate * t_offset)`` since the
        previous tick, so summing all counts equals :attr:`total_messages`.
        """
        if self.duration_s <= 0 or self.target_rate <= 0:
            return
        emitted = 0
        index = 0
        elapsed = 0.0
        while elapsed < self.duration_s - 1e-9:
            next_elapsed = min((index + 1) * self.tick_s, self.duration_s)
            target = floor(self.target_rate * next_elapsed)
            count = target - emitted
            emitted = target
            yield Tick(
                index=index,
                t_offset=next_elapsed,
                count=count,
                cumulative=emitted,
            )
            elapsed = next_elapsed
            index += 1


def plan(target_rate: float, duration_s: float, tick_s: float = 1.0) -> list[Tick]:
    """Materialize the full :class:`RateSchedule` into a list of :class:`Tick`."""
    return list(RateSchedule(target_rate=target_rate, duration_s=duration_s, tick_s=tick_s))
