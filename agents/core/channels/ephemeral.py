"""H067 str-compatible system notices and owned, bounded best-effort deletion.

Adapted from Hermes gateway/platforms/base.py at59b2aeef6c7a (MIT).
See docs/hermes/licenses/hermes-pending-input-MIT.txt.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable


def _valid_ttl(value: object) -> bool:
    if type(value) is not int or value < 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class EphemeralReply(str):
    """A delivered system notice; None uses the configured TTL, zero retains it."""

    ttl_seconds: int | None

    def __new__(cls, text: str, ttl_seconds: int | None = None):
        if not isinstance(text, str):
            raise ValueError("A system notice must be text")
        if ttl_seconds is not None and not _valid_ttl(ttl_seconds):
            raise ValueError("A system notice TTL must be a nonnegative integer")
        instance = super().__new__(cls, text)
        instance.ttl_seconds = ttl_seconds
        return instance

    @property
    def text(self) -> str:
        return str.__str__(self)


def ephemeral_ttl(message: object, *, default=0) -> int:
    if not isinstance(message, EphemeralReply):
        return 0
    value = default if message.ttl_seconds is None else message.ttl_seconds
    return value if _valid_ttl(value) else 0


class EphemeralDeletes:
    """Own deletion callbacks supplied only after a transport's successful send.

    Scheduling acceptance is separate from actual deletion. Capacity failure,
    unsupported deletion, shutdown and failures retain the delivered notice.
    No message text, credentials or arbitrary inbound message IDs are stored.
    """

    def __init__(self, *, max_pending: int = 1024, sleep=asyncio.sleep):
        if type(max_pending) is not int or max_pending <= 0 or not callable(sleep):
            raise ValueError("Invalid ephemeral deletion configuration")
        self._max_pending = max_pending
        self._sleep = sleep
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self.deleted_count = 0
        self.failed_count = 0
        self.abandoned_count = 0

    @property
    def pending_count(self) -> int:
        return sum(not task.done() for task in self._tasks)

    def schedule(self, ttl_seconds: int, delete: Callable[[], Awaitable[bool]]) -> bool:
        if (
            self._closed
            or not _valid_ttl(ttl_seconds)
            or ttl_seconds == 0
            or not callable(delete)
            or self.pending_count >= self._max_pending
        ):
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False

        async def run():
            try:
                await self._sleep(max(1, ttl_seconds))
                if self._closed:
                    return
                result = await delete()
                if self._closed:
                    # An already-started transport request may resist cancellation.
                    # Its late outcome is not a successful shutdown-time deletion.
                    self.abandoned_count += 1
                elif result is True:
                    self.deleted_count += 1
                else:
                    self.failed_count += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self.failed_count += 1

        task = loop.create_task(run(), name="ephemeral-notice-delete")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def aclose(self, *, timeout: float = 2) -> bool:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError("Invalid ephemeral deletion drain budget")
        self._closed = True
        pending = {task for task in self._tasks if not task.done()}
        for task in pending:
            task.cancel()
        current = asyncio.current_task()
        waiting = pending - {current}
        if waiting:
            await asyncio.wait(waiting, timeout=timeout)
        self._tasks.difference_update(task for task in tuple(self._tasks) if task.done())
        return self.pending_count == 0
