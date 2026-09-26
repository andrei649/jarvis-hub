"""H677 — one lane per chat: a chat's turns run in order, different chats in parallel.

A sequential poll loop (Telegram) used to await each turn before reading the next update,
so one owner's slow answer held every other chat for as long as it took — and a turn
waiting on its session's lease (up to 180 s) held them all that long too. A channel now
hands each turn to its chat's lane: the lane runs its turns one after another (a chat
still reads in the order it wrote), lanes run side by side up to ``max_active`` turns at
once, and the poll loop goes straight back to reading.

A lane never stalls on a previous turn's failure; :meth:`drain` gives what is still
queued a bounded time to finish when the channel stops, and names what it abandoned.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Hashable

logger = logging.getLogger("jarvis.channels.lanes")

DEFAULT_MAX_ACTIVE = 8


class ChatLanes:
    def __init__(self, *, max_active: int = DEFAULT_MAX_ACTIVE, name: str = "channel") -> None:
        self._tails: dict[Hashable, asyncio.Task] = {}
        self._live: set[asyncio.Task] = set()
        self._active = asyncio.Semaphore(max(1, int(max_active)))
        self._name = name

    @property
    def busy(self) -> int:
        """Lanes with a turn running or queued."""
        return len(self._tails)

    def submit(self, key: Hashable, turn: Callable[[], Awaitable[object]]) -> asyncio.Task:
        """Queue *turn* on *key*'s lane; returns at once. The turn starts when every
        earlier turn of that lane has ended (however it ended) and a slot is free."""
        before = self._tails.get(key)

        async def run() -> None:
            if before is not None:
                await asyncio.wait({before})           # its outcome is its own; never raises
            async with self._active:
                try:
                    await turn()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("%s: a turn failed in its chat lane", self._name, exc_info=True)

        task = asyncio.ensure_future(run())
        self._tails[key] = task
        self._live.add(task)
        task.add_done_callback(self._live.discard)
        task.add_done_callback(lambda done, k=key: self._tails.get(k) is done and self._tails.pop(k, None))
        return task

    async def settle(self) -> None:
        """Wait for every turn queued so far, in every lane (for work that belongs to no
        one chat but must come after what was already said)."""
        live = list(self._live)
        if live:
            await asyncio.wait(live)

    async def drain(self, budget: float) -> bool:
        """Wait at most *budget* seconds for every lane to finish; True when they all did.
        A lane still running after that is cancelled and named."""
        live = list(self._live)
        if not live:
            return True
        _done, pending = await asyncio.wait(live, timeout=budget)
        for task in pending:
            task.cancel()
        if pending:
            logger.warning("%s: %d chat lane(s) still running after %.1fs at stop; abandoned",
                           self._name, len(pending), budget)
        return not pending


__all__ = ["DEFAULT_MAX_ACTIVE", "ChatLanes"]
