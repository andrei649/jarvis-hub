"""H117 — a burst of messages is one turn.

Telegram splits a long message into several (4,096 characters each), an album arrives as one
update per photo, and people send a photo and then "what is this?". Each piece used to become
its own turn: three fragments, three answers, the first two about half a question. Hermes
batches them, and so does Nerva:

- **The window.** Turns from the same sender in the same chat that arrive within
  :data:`WINDOW_SECONDS` of each other (Hermes' ``_busy_text_debounce_seconds``, 0.35 s) are
  held and merged, in arrival order, into one turn. Waiting never grows past
  :data:`HARD_CAP_SECONDS` from the first piece (Hermes' hard cap, 1.0 s), so a sender who keeps
  typing still gets an answer.
- **What is merged.** Whatever the channel would have handed the orchestrator for each piece:
  a text fragment, or what an attachment was read as (a photo's description, a voice note's
  transcript, its caption). So a split message, an album and a photo-then-question are each one
  turn.
- **Scanned whole.** The merged text is what the gateway receives, so its prompt-injection scan
  runs on the whole message, not on fragments an attacker could split a payload across.
- **Per chat, in order.** Pieces are keyed by (chat, sender); a flush hands the merged turn over
  before anything later from that chat is processed.

Telegram's poll loop drives a :class:`Coalescer` directly; Discord and Slack, whose messages
arrive as events, use :class:`AsyncBatcher`, which flushes each batch from its own timer.
``JARVIS_INBOUND_BATCH_MS`` / ``JARVIS_INBOUND_BATCH_MAX_MS`` set the window and the cap for
every channel; a window of 0 turns batching off (each piece is its own turn at once).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("jarvis.channels.batching")

WINDOW_SECONDS = 0.35
HARD_CAP_SECONDS = 1.0
MAX_PARTS = 32
SEPARATOR = "\n"


@dataclass
class Pending:
    """The pieces held for one (chat, sender)."""

    parts: list[str] = field(default_factory=list)
    first: float = 0.0
    last: float = 0.0

    @property
    def text(self) -> str:
        return SEPARATOR.join(p for p in self.parts if p)


class Coalescer:
    """Holds turn pieces per key until their window closes or the hard cap is reached."""

    def __init__(self, window: float = WINDOW_SECONDS, hard_cap: float = HARD_CAP_SECONDS, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.window = max(0.0, float(window))
        self.hard_cap = max(self.window, float(hard_cap))
        self._clock = clock
        self._pending: dict[Hashable, Pending] = {}

    @property
    def enabled(self) -> bool:
        return self.window > 0

    def now(self) -> float:
        return self._clock()

    def add(self, key: Hashable, text: str, *, now: float | None = None) -> bool:
        """Hold ``text`` under ``key``. True when the key's batch is now full and must flush."""
        now = self.now() if now is None else now
        held = self._pending.get(key)
        if held is None:
            held = self._pending[key] = Pending(first=now)
        held.parts.append(str(text or ""))
        held.last = now
        return len(held.parts) >= MAX_PARTS

    def deadline(self, key: Hashable) -> float | None:
        held = self._pending.get(key)
        if held is None:
            return None
        return min(held.last + self.window, held.first + self.hard_cap)

    def due(self, now: float | None = None) -> list[Hashable]:
        """The keys whose window has closed or whose hard cap is reached, oldest first."""
        now = self.now() if now is None else now
        ready = [(held.first, key) for key, held in self._pending.items() if now >= self.deadline(key)]
        return [key for _, key in sorted(ready, key=lambda item: item[0])]

    def wait(self, now: float | None = None) -> float | None:
        """Seconds until the earliest batch is due (0 when one already is), ``None`` when idle."""
        if not self._pending:
            return None
        now = self.now() if now is None else now
        return max(0.0, min(self.deadline(key) for key in self._pending) - now)

    def pop(self, key: Hashable) -> Pending | None:
        return self._pending.pop(key, None)

    def held_keys(self) -> list[Hashable]:
        """Every held key, oldest batch first."""
        return [key for key, _ in sorted(self._pending.items(), key=lambda item: item[1].first)]

    def __len__(self) -> int:
        return len(self._pending)


def configured() -> tuple[float, float]:
    """The owner's window and hard cap in seconds (``JARVIS_INBOUND_BATCH_MS`` /
    ``JARVIS_INBOUND_BATCH_MAX_MS``); a malformed or negative value keeps the default."""
    from ..env_config import env_int

    window_ms = env_int("JARVIS_INBOUND_BATCH_MS", int(WINDOW_SECONDS * 1000), minimum=0)
    cap_ms = env_int("JARVIS_INBOUND_BATCH_MAX_MS", int(HARD_CAP_SECONDS * 1000), minimum=0)
    return window_ms / 1000.0, cap_ms / 1000.0


class AsyncBatcher:
    """Batching for channels whose messages arrive as events: each (conversation, sender)
    batch is flushed by its own timer and delivered in order, one at a time per key."""

    def __init__(self, deliver: Callable[[Hashable, str, dict], Awaitable[Any]],
                 window: float = WINDOW_SECONDS, hard_cap: float = HARD_CAP_SECONDS, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._deliver = deliver
        self._batch = Coalescer(window, hard_cap, clock=clock)
        self._meta: dict[Hashable, dict] = {}
        self._timers: dict[Hashable, asyncio.Task] = {}
        self._locks: dict[Hashable, asyncio.Lock] = {}

    @property
    def enabled(self) -> bool:
        return self._batch.enabled

    def __len__(self) -> int:
        return len(self._batch)

    async def submit(self, key: Hashable, text: str, **meta: Any) -> Any:
        """Hold one piece; the batch is delivered when its window closes. With batching off
        the piece is delivered at once and the delivery's answer returned."""
        if not self._batch.enabled:
            return await self._deliver(key, text, dict(meta))
        self._meta.setdefault(key, dict(meta))        # the first piece says where it goes
        if self._batch.add(key, text):
            await self.flush(key)
            return
        if key not in self._timers:                   # a flush always takes its timer away
            self._timers[key] = asyncio.create_task(self._timer(key))

    async def _timer(self, key: Hashable) -> None:
        while True:
            deadline = self._batch.deadline(key)
            if deadline is None:
                return
            delay = deadline - self._batch.now()
            if delay <= 0:
                break
            await asyncio.sleep(delay)
        try:
            await self.flush(key, from_timer=True)
        except Exception:
            logger.warning("a batched inbound turn failed", exc_info=True)

    async def flush(self, key: Hashable, *, from_timer: bool = False) -> None:
        """Deliver ``key``'s held pieces now, as one turn."""
        held = self._batch.pop(key)
        meta = self._meta.pop(key, {})
        timer = self._timers.pop(key, None)
        if timer is not None and not from_timer and not timer.done():
            timer.cancel()
        if held is None or not held.text:
            return
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            await self._deliver(key, held.text, meta)

    async def drain(self) -> None:
        """Deliver everything held now."""
        for key in self._batch.held_keys():
            await self.flush(key)

    def discard(self) -> int:
        """Drop everything held and stop its timers (a channel shutting down, whose own
        queue of undelivered events is discarded the same way). The number of batches dropped."""
        keys = self._batch.held_keys()
        for key in keys:
            self._batch.pop(key)
            self._meta.pop(key, None)
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        return len(keys)


__all__ = ["AsyncBatcher", "Coalescer", "HARD_CAP_SECONDS", "MAX_PARTS", "Pending", "SEPARATOR",
           "WINDOW_SECONDS", "configured"]
