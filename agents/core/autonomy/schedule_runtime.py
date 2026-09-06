"""schedule_runtime.py — what makes a work run continue without being asked.

The supervisor advances a run one step when someone ticks it. This module decides
*when* that happens, so a goal approved on Tuesday is still being worked at 3am on
Thursday. It is the difference between an agent you drive and a company that
keeps going.

Waking is not a licence, so the rules are about restraint, not throughput:

* **Never wake a run that should not be running.** A terminal run, a stopping one,
  and a run whose budget is spent are all skipped without a tick. Waking them
  would burn the supervisor's own failure streak against a wall.
* **A blocked run does not get poked.** It is waiting on the owner's decision;
  ticking it changes nothing and adds noise. It becomes due again only once the
  decision lands and something resumes it.
* **Night hours are quiet hours for attention, not for work.** During the night
  window a run may still take steps, but a step that would interrupt the owner is
  deferred to the morning. This mirrors `is_night_window` in the existing worker
  rather than inventing a second notion of night.
* **One run at a time by default.** ``max_concurrent`` bounds how many runs the
  scheduler is willing to advance per sweep, so enabling company mode on a box
  with ten open goals does not mean ten simultaneous agents.
* **Nothing here retries.** A tick that failed is the supervisor's business; the
  scheduler simply comes back at the next interval. A scheduler with its own retry
  loop would multiply the supervisor's failure budget behind its back.
* **Sweeps are idempotent and stateless.** Everything the scheduler needs is in
  the ledger, so a restart resumes correctly and two sweeps in a row cannot
  double-spend a step (the ledger's budget is the real bound).

Default-off with the rest of company mode: ``ScheduleConfig.enabled`` is ``False``
and the caller checks ``JARVIS_COMPANY_MODE`` before constructing one.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from agents.core.autonomy.work_runs import TERMINAL_STATUSES

logger = logging.getLogger("jarvis.schedule_runtime")

FLAG = "JARVIS_COMPANY_MODE"

# Why a run was not advanced this sweep. Every skip is reported: a silently
# skipped run looks identical to one that had nothing to do.
SKIP_REASONS = (
    "terminal",        # already finished; a record, not a resource
    "stopping",        # a stop is in flight — the supervisor closes it out
    "blocked",         # waiting on the owner; poking it changes nothing
    "budget_spent",    # a limit is already out
    "not_due",         # its interval has not elapsed
    "at_capacity",     # max_concurrent reached this sweep
)


@dataclass(frozen=True)
class ScheduleConfig:
    enabled: bool = False
    # Seconds between ticks for one run. The default is deliberately unhurried:
    # a work run is measured in hours, and a tighter loop mostly buys wasted
    # model calls against an approval that has not arrived yet.
    interval_seconds: float = 300.0
    max_concurrent: int = 1
    # Local hours during which a step that would interrupt the owner is deferred.
    # Work continues; only the interruption waits.
    night_start: int = 23
    night_end: int = 6

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        for hour in (self.night_start, self.night_end):
            if not 0 <= int(hour) <= 23:
                raise ValueError("night window hours must be 0-23")


@dataclass(frozen=True)
class SweepEntry:
    run_id: str
    ticked: bool
    reason: str = ""
    outcome: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "ticked": self.ticked,
            "reason": self.reason, "outcome": self.outcome,
        }


@dataclass(frozen=True)
class SweepResult:
    entries: tuple[SweepEntry, ...]
    at: float

    @property
    def ticked(self) -> tuple[str, ...]:
        return tuple(e.run_id for e in self.entries if e.ticked)

    @property
    def skipped(self) -> dict[str, str]:
        return {e.run_id: e.reason for e in self.entries if not e.ticked}

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "ticked": list(self.ticked),
            "skipped": self.skipped,
            "entries": [e.as_dict() for e in self.entries],
        }


def is_night(hour: int, *, start: int, end: int) -> bool:
    """True inside the night window, which may wrap past midnight."""
    hour, start, end = int(hour) % 24, int(start) % 24, int(end) % 24
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class ScheduleRuntime:
    """Decides which runs to advance, and ticks them through the supervisor.

    ``tick`` is the supervisor's own ``tick(run_id)``. ``clock`` and ``local_hour``
    are injectable so night-window behaviour is testable without waiting for 3am.
    """

    def __init__(
        self,
        ledger: Any,
        *,
        tick: Callable[[str], Any],
        config: ScheduleConfig | None = None,
        clock: Callable[[], float] = time.time,
        local_hour: Callable[[], int] | None = None,
    ) -> None:
        self._ledger = ledger
        self._tick = tick
        self.config = config or ScheduleConfig()
        self._clock = clock
        self._local_hour = local_hour or (lambda: time.localtime().tm_hour)
        # Last tick per run. In memory: after a restart every run is due again,
        # which is the safe direction — a missed tick costs a delay, an extra one
        # costs a step the ledger's budget already bounds.
        self._last: dict[str, float] = {}

    # ── the sweep ────────────────────────────────────────────────────────

    def due(self, run: Any, *, now: float) -> str:
        """``""`` when the run should be advanced, else the skip reason."""
        status = str(getattr(run, "status", ""))
        if status in TERMINAL_STATUSES:
            return "terminal"
        if status == "stopping":
            return "stopping"
        if status == "blocked":
            return "blocked"
        try:
            if self._ledger.budget_state(run.id)["exceeded"]:
                return "budget_spent"
        except Exception:
            logger.debug("scheduler could not read a budget", exc_info=True)
            return "budget_spent"
        last = self._last.get(run.id)
        if last is not None and (now - last) < self.config.interval_seconds:
            return "not_due"
        return ""

    def quiet_hours(self) -> bool:
        """True when a step that would interrupt the owner should wait.

        Work does not stop at night — only the interruption does. The supervisor
        is told through :meth:`interruptions_allowed` so the decision lives in one
        place rather than being re-derived per planner.
        """
        return is_night(
            self._local_hour(),
            start=self.config.night_start,
            end=self.config.night_end,
        )

    def interruptions_allowed(self) -> bool:
        return not self.quiet_hours()

    async def sweep(self) -> SweepResult:
        """One pass over the open runs. Idempotent; safe to call from a timer."""
        now = float(self._clock())
        if not self.config.enabled:
            return SweepResult((), now)

        try:
            runs = self._ledger.list_runs(active_only=True, limit=100)
        except Exception:
            logger.warning("scheduler could not list runs", exc_info=True)
            return SweepResult((), now)

        entries: list[SweepEntry] = []
        advanced = 0
        for run in runs:
            reason = self.due(run, now=now)
            if reason:
                entries.append(SweepEntry(run.id, False, reason))
                continue
            if advanced >= self.config.max_concurrent:
                # Not an error: the next sweep picks it up. Reported so a run that
                # never advances is visible rather than mysteriously idle.
                entries.append(SweepEntry(run.id, False, "at_capacity"))
                continue
            entries.append(await self._advance(run.id, now))
            advanced += 1
        return SweepResult(tuple(entries), now)

    async def _advance(self, run_id: str, now: float) -> SweepEntry:
        """Tick one run. A failed tick is recorded, never retried here."""
        self._last[run_id] = now
        try:
            result = self._tick(run_id)
            if hasattr(result, "__await__"):
                result = await result
        except Exception as exc:
            logger.warning("scheduler tick failed for %s", run_id, exc_info=True)
            return SweepEntry(run_id, True, "tick_failed", exc.__class__.__name__)
        return SweepEntry(run_id, True, "", str(getattr(result, "outcome", "") or ""))

    # ── observability ────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """What the scheduler is doing, for the HUD and the brief."""
        now = float(self._clock())
        try:
            runs = self._ledger.list_runs(active_only=True, limit=100)
        except Exception:
            runs = []
        return {
            "enabled": self.config.enabled,
            "interval_seconds": self.config.interval_seconds,
            "max_concurrent": self.config.max_concurrent,
            "quiet_hours": self.quiet_hours(),
            "night_window": [self.config.night_start, self.config.night_end],
            "open_runs": len(runs),
            "due": [run.id for run in runs if not self.due(run, now=now)],
            "waiting": {
                run.id: reason
                for run in runs
                if (reason := self.due(run, now=now))
            },
        }


def next_due_at(last_tick: float | None, *, interval: float, now: float) -> float:
    """When a run becomes due again. A run never ticked is due immediately."""
    if last_tick is None:
        return now
    return float(last_tick) + float(interval)


def sweep_summary(results: Sequence[SweepResult]) -> dict[str, Any]:
    """Roll several sweeps into counts — for the morning brief."""
    ticked = 0
    skips: dict[str, int] = {}
    for result in results:
        ticked += len(result.ticked)
        for reason in result.skipped.values():
            skips[reason] = skips.get(reason, 0) + 1
    return {"sweeps": len(results), "ticked": ticked, "skipped": skips}


__all__ = [
    "FLAG",
    "SKIP_REASONS",
    "ScheduleConfig",
    "ScheduleRuntime",
    "SweepEntry",
    "SweepResult",
    "is_night",
    "next_due_at",
    "sweep_summary",
]
