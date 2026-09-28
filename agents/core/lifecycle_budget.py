"""H677 — warm up before accepting work, and give every shutdown wait a short budget.

Two halves of one discipline: the hub never makes the owner's first message race a cold
model, and it never lets one wedged step use up the service manager's stop budget.

- **Warm-up gate** (:func:`gate_warmup`, run by the web lifespan before the channels
  start). The local model's warm-up used to be fire-and-forget, so a message that arrived
  right after boot raced the cold load. Now the lifespan waits for it — at most
  ``system.startup_warmup_timeout_seconds`` (default 20 s; 0 = do not wait). On expiry it
  says so and opens anyway; the warm-up finishes in the background. :data:`WARMUP` holds
  the state (``off``/``warming``/``ready``/``cold``/``failed``), which ``GET /api/status`` and
  ``/readyz`` report and every turn served while it is still ``warming`` carries.
- **Shutdown budgets** (:func:`bounded`, :func:`wait_task`). Every teardown wait — a
  channel's stop, a cancelled background task, a plugin or backend close — gets a short
  explicit budget. An overrun is logged by name and the next step runs; a step that
  ignores cancellation is abandoned, never awaited forever.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import Any

logger = logging.getLogger("jarvis.lifecycle")

WARMUP_SETTING = "system.startup_warmup_timeout_seconds"
DEFAULT_WARMUP_TIMEOUT = 20.0
MAX_WARMUP_TIMEOUT = 300.0
#: Per-channel stop, per cancelled background task, per plugin/backend close step.
CHANNEL_STOP_BUDGET = 3.0
TASK_CANCEL_BUDGET = 2.0
CLOSE_STEP_BUDGET = 3.0


def warmup_timeout(value: Any) -> float:
    """The configured warm-up wait in seconds: a finite number clamped to 0..300, else
    the default (a bad setting never disables the gate by accident, nor makes it hang)."""
    if isinstance(value, bool):
        return DEFAULT_WARMUP_TIMEOUT
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_WARMUP_TIMEOUT
    if seconds != seconds or seconds in (float("inf"), float("-inf")):
        return DEFAULT_WARMUP_TIMEOUT
    return min(max(0.0, seconds), MAX_WARMUP_TIMEOUT)


class WarmupState:
    """Where the boot warm-up stands. ``off`` until one starts (none configured, or a
    cloud backend that needs none)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = "off"
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.gate_expired = False
        self._task: asyncio.Future | None = None

    @property
    def warming(self) -> bool:
        return self.phase == "warming"

    def track(self, task: asyncio.Future) -> None:
        self._task = task
        self.phase = "warming"
        self.started_at = time.time()
        self.finished_at = None
        self.gate_expired = False
        if task.done():
            self._settle(task)
        else:
            task.add_done_callback(self._settle)

    def _settle(self, task: asyncio.Future) -> None:
        if task is not self._task:
            return                                  # a later warm-up owns the state now
        self.finished_at = time.time()
        if task.cancelled() or task.exception() is not None:
            self.phase = "failed"
        else:
            # LLMRouter.warm_up answers False when nothing local was up to warm (or the
            # load did not complete): nothing is left warming, but nothing is warm either.
            self.phase = "ready" if task.result() is not False else "cold"

    def snapshot(self) -> dict:
        waited = None
        if self.started_at is not None:
            waited = round((self.finished_at or time.time()) - self.started_at, 3)
        return {"phase": self.phase, "warming": self.warming, "gate_expired": self.gate_expired,
                "seconds": waited}


WARMUP = WarmupState()


async def gate_warmup(task: asyncio.Future | None, timeout: float, *, state: WarmupState = WARMUP) -> dict:
    """Wait for the boot warm-up, at most *timeout* seconds, then open either way."""
    if task is None:
        state.reset()
        return state.snapshot()
    state.track(task)
    if timeout > 0 and not task.done():
        # asyncio.wait (unlike wait_for) never cancels what it waits on: the gate
        # expiring leaves the warm-up running.
        done, _pending = await asyncio.wait({task}, timeout=timeout)
        if not done:
            state.gate_expired = True
            logger.warning(
                "the local model is still warming up after %.0fs; accepting work now — turns "
                "served before it finishes are marked warming (%s)", timeout, WARMUP_SETTING)
    if state.phase == "failed":
        logger.warning("the local model warm-up failed; the first turn will load it cold")
    return state.snapshot()


def _abandon(task: asyncio.Future) -> None:
    task.cancel()
    # Retrieve a late exception so an abandoned step never logs "never retrieved".
    task.add_done_callback(lambda t: t.cancelled() or t.exception())


async def bounded(step: Awaitable, budget: float, what: str) -> bool:
    """Run one shutdown *step* for at most *budget* seconds. True when it finished; on an
    overrun or an error it is logged by name and False comes back — never raised, never
    awaited past the budget (a step that ignores cancellation is abandoned)."""
    task = asyncio.ensure_future(step)
    done, _pending = await asyncio.wait({task}, timeout=budget)
    if not done:
        _abandon(task)
        logger.warning("shutdown: %s did not finish within %.1fs; moving on", what, budget)
        return False
    if task.cancelled():
        return False
    error = task.exception()
    if error is not None:
        logger.warning("shutdown: %s failed: %s: %s", what, type(error).__name__, error)
        return False
    return True


async def wait_task(task: asyncio.Future, budget: float, what: str) -> bool:
    """Cancel a background *task* and wait at most *budget* seconds for it to stop."""
    if task.done():
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Error stopping %s: %s", what, task.exception())
        return True
    task.cancel()
    done, _pending = await asyncio.wait({task}, timeout=budget)
    if not done:
        logger.warning("shutdown: %s did not stop within %.1fs of being cancelled; moving on", what, budget)
        return False
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Error stopping %s: %s", what, task.exception())
    return True


__all__ = [
    "CHANNEL_STOP_BUDGET", "CLOSE_STEP_BUDGET", "DEFAULT_WARMUP_TIMEOUT", "TASK_CANCEL_BUDGET", "WARMUP",
    "WARMUP_SETTING", "WarmupState", "bounded", "gate_warmup", "wait_task", "warmup_timeout",
]
