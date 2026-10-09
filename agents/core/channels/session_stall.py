"""Pure, bounded notification policy for pending session stalls.

``begin`` marks an eligible inbound episode. Only ``progress`` supplies the
activity clock; callers must report processing start, token/tool activity, and
completion using the active episode token. Delivery is delegated to the owner.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic

_MAX_EPISODES = 4096
_SEND_TIMEOUT_SECONDS = 10.0
_MAX_PENDING_SENDS = 4096
_MAX_KEY_LENGTH = 1024
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Episode:
    token: int
    last_progress: float | None = None
    version: int = 0
    notified: bool = False


class StallWatcher:
    """Track pending episodes without storing inbound content or delivery data."""

    def __init__(self, clock: Callable[[], float] = monotonic):
        self._clock = clock
        self._episodes: dict[str, _Episode] = {}
        self._next_token = 0
        self._check_lock = asyncio.Lock()
        self._closed = False
        # A cancellation-resistant notifier remains owned here until it exits.
        # A second send for the same key is suppressed while it is outstanding.
        self._send_tasks: dict[str, asyncio.Task[bool]] = {}

    def begin(self, key: str) -> int:
        """Replace a pending episode; arrival alone is not activity."""
        if self._closed:
            raise RuntimeError("stall watcher is closed")
        if type(key) is not str:
            raise TypeError("stall key must be a string")
        if not key.strip() or len(key) > _MAX_KEY_LENGTH:
            raise ValueError("stall key must be nonempty and at most 1024 characters")
        if key not in self._episodes and len(self._episodes) >= _MAX_EPISODES:
            raise OverflowError("too many pending stall episodes")
        self._next_token += 1
        self._episodes[key] = _Episode(self._next_token)
        return self._next_token

    def matches(self, key: str, token: int) -> bool:
        """Return whether a pending episode still has this exact token."""
        if self._closed or type(key) is not str or type(token) is not int:
            return False
        episode = self._episodes.get(key)
        return episode is not None and episode.token == token

    def progress(self, key: str, token: int) -> bool:
        """Record actual processing progress and rearm the notice latch."""
        if not self.matches(key, token):
            return False
        episode = self._episodes[key]
        now = self._now()
        if now is None or (episode.last_progress is not None and now < episode.last_progress):
            return False
        episode.last_progress = now
        episode.version += 1
        episode.notified = False
        return True

    def finish(self, key: str, token: int) -> bool:
        """Drain only the matching pending episode."""
        if not self.matches(key, token):
            return False
        del self._episodes[key]
        return True

    def is_due(self, key: str, token: int, timeout: float) -> bool:
        """Fresh, read-only eligibility check for the owner delivery callback."""
        threshold = self._finite(timeout)
        if threshold is None or threshold <= 0 or not self.matches(key, token):
            return False
        episode = self._episodes[key]
        if episode.notified or episode.last_progress is None:
            return False
        now = self._now()
        if now is None:
            return False
        idle = now - episode.last_progress
        return math.isfinite(idle) and idle >= threshold

    @property
    def pending_send_count(self) -> int:
        """Number of owned notifier tasks, including cancellation-resistant ones."""
        for key, task in list(self._send_tasks.items()):
            if task.done():
                self._settle_send(key, task)
        return len(self._send_tasks)

    async def check(
        self,
        timeout: float,
        notify: Callable[[str, int, float], Awaitable[bool]],
    ) -> int:
        """Attempt due notices in order, counting successful deliveries.

        Failed, false, or timed-out sends remain eligible for the next check.
        Overlapping checks serialize, and task cancellation propagates.
        """
        if self._closed:
            return 0
        async with self._check_lock:
            if self._closed:
                return 0
            threshold = self._finite(timeout)
            if threshold is None:
                return 0
            if threshold <= 0:
                for episode in self._episodes.values():
                    episode.notified = False
                return 0

            sent = 0
            # Snapshot identities, then re-read activity immediately before each
            # callback. Earlier callbacks may await while siblings recover/drain.
            for key, token in [(key, episode.token) for key, episode in self._episodes.items()]:
                if not self.is_due(key, token, threshold) or self._send_active(key):
                    continue
                now = self._now()
                episode = self._episodes[key]
                if now is None or episode.last_progress is None:
                    continue
                idle = now - episode.last_progress
                if idle < threshold or not math.isfinite(idle):
                    continue
                version = episode.version
                try:
                    task = asyncio.create_task(
                        self._deliver_if_due(key, token, episode, version, threshold, idle, notify)
                    )
                except Exception as exc:
                    logger.debug("stall notifier task could not start (%s)", type(exc).__name__)
                    continue
                self._send_tasks[key] = task
                task.add_done_callback(lambda done, route=key: self._settle_send(route, done))
                try:
                    done, _pending = await asyncio.wait({task}, timeout=_SEND_TIMEOUT_SECONDS)
                except asyncio.CancelledError:
                    task.cancel()
                    logger.warning(
                        "stall notification check canceled; retaining send until it settles"
                    )
                    raise
                if not done:
                    task.cancel()
                    logger.warning(
                        "stall notification send exceeded %.1fs; retaining task",
                        _SEND_TIMEOUT_SECONDS,
                    )
                    continue
                if task.cancelled():
                    logger.debug("stall notifier canceled itself")
                    continue
                try:
                    delivered = task.result()
                except Exception as exc:
                    logger.debug("stall notifier failed (%s)", type(exc).__name__)
                    continue
                if delivered is True:
                    sent += 1
                    current = self._episodes.get(key)
                    if current is episode and current.version == version:
                        current.notified = True
            return sent

    async def close(self, timeout: float = 2.0) -> int:
        """Stop eligibility and give owned notifier tasks a bounded exit window.

        A notifier that ignores cancellation remains tracked until its done
        callback consumes the result. The returned count reports such survivors.
        """
        if type(timeout) not in (int, float):
            raise TypeError("close timeout must be a finite nonnegative number")
        try:
            budget = float(timeout)
        except OverflowError:
            raise ValueError("close timeout must be finite") from None
        if not math.isfinite(budget) or budget < 0:
            raise ValueError("close timeout must be finite and nonnegative")

        self._closed = True
        self._episodes.clear()
        tasks = set(self._send_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks and budget > 0:
            await asyncio.wait(tasks, timeout=budget)
        remaining = self.pending_send_count
        if remaining:
            logger.warning("stall watcher closed with %d notifier task(s) still running", remaining)
        return remaining

    async def _deliver_if_due(
        self,
        key: str,
        token: int,
        episode: _Episode,
        version: int,
        timeout: float,
        idle: float,
        notify: Callable[[str, int, float], Awaitable[bool]],
    ) -> bool:
        # Task scheduling yields. A newer progress event may land after the
        # outer check but before notify first runs.
        current = self._episodes.get(key)
        if current is not episode or current.version != version:
            return False
        if not self.is_due(key, token, timeout):
            return False
        return await notify(key, token, idle)

    def _send_active(self, key: str) -> bool:
        task = self._send_tasks.get(key)
        if task is None:
            return len(self._send_tasks) >= _MAX_PENDING_SENDS
        if task.done():
            self._settle_send(key, task)
            return False
        return True

    def _settle_send(self, key: str, task: asyncio.Task[bool]) -> None:
        if self._send_tasks.get(key) is task:
            del self._send_tasks[key]
        if not task.cancelled():
            error = task.exception()  # consume late errors from timed-out sends
            if error is not None:
                logger.debug("stall notification send ended with %s", type(error).__name__)

    def _now(self) -> float | None:
        try:
            return self._finite(self._clock())
        except Exception:
            return None

    @staticmethod
    def _finite(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None
