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
- **A command is never a piece.** The command plane answers a turn that is the command alone, so
  a slash command (``/stop``, ``/status``) is a barrier: what the sender said before it goes
  first, then the command on its own, at once.

Telegram's poll loop drives a :class:`Coalescer` directly; Discord and Slack, whose messages
arrive as events, use :class:`AsyncBatcher`, which flushes each batch from its own timer and
holds its caller once :data:`MAX_PENDING` batches are on their way, so the channel's own bounded
ingress fills as it did before batching.
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

from ..commands import CommandRegistry

logger = logging.getLogger("jarvis.channels.batching")

WINDOW_SECONDS = 0.35
HARD_CAP_SECONDS = 1.0
MAX_PARTS = 32
MAX_PENDING = 16
SEPARATOR = "\n"


def is_command(text: str) -> bool:
    """A slash command, as the command plane parses it: never merged with other pieces."""
    return CommandRegistry.parse(text) is not None


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


@dataclass
class _KeyLock:
    """One key's delivery lock, and how many deliveries hold it or wait on it."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class AsyncBatcher:
    """Batching for channels whose messages arrive as events: each (conversation, sender)
    batch is flushed by its own timer and delivered in order, one at a time per key. At most
    ``max_pending`` batches are on their way (held, waiting on their key or being delivered)."""

    def __init__(self, deliver: Callable[[Hashable, str, dict], Awaitable[Any]],
                 window: float = WINDOW_SECONDS, hard_cap: float = HARD_CAP_SECONDS, *,
                 max_pending: int = MAX_PENDING,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._deliver = deliver
        self._batch = Coalescer(window, hard_cap, clock=clock)
        self._max_pending = max(1, int(max_pending))
        self._meta: dict[Hashable, dict] = {}
        self._timers: dict[Hashable, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()        # each timer, until its batch is delivered
        self._locks: dict[Hashable, _KeyLock] = {}
        self._generation = 0                          # one more on every discard()

    @property
    def enabled(self) -> bool:
        return self._batch.enabled

    def __len__(self) -> int:
        return len(self._batch)

    async def submit(self, key: Hashable, text: str, **meta: Any) -> Any:
        """Hold one piece; the batch is delivered when its window closes. With batching off
        the piece is delivered at once and the delivery's answer returned; so is a slash
        command, after what the sender said before it. A piece that would start a batch past
        ``max_pending`` waits for room: the caller is held, as the turn itself held it
        before batching."""
        if not self._batch.enabled:
            return await self._deliver(key, text, dict(meta))
        generation = self._generation
        if is_command(text):
            await self.flush(key)
            return await self._in_order(key, text, dict(meta), generation)
        while key not in self._timers and len(self._tasks) >= self._max_pending:
            await asyncio.wait(set(self._tasks), return_when=asyncio.FIRST_COMPLETED)
        if generation != self._generation:
            return                                    # discarded while it waited
        self._meta.setdefault(key, dict(meta))        # the first piece says where it goes
        if self._batch.add(key, text):
            await self.flush(key)
            return
        if key not in self._timers:                   # a flush always takes its timer away
            task = self._timers[key] = asyncio.create_task(self._timer(key))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

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
        generation = self._generation
        held = self._batch.pop(key)
        meta = self._meta.pop(key, {})
        timer = self._timers.pop(key, None)
        if timer is not None and not from_timer and not timer.done():
            timer.cancel()
        if held is None or not held.text:
            return
        await self._in_order(key, held.text, meta, generation)

    async def _in_order(self, key: Hashable, text: str, meta: dict, generation: int) -> Any:
        """Deliver under ``key``'s lock, so its turns never overlap. The lock is let go once
        nothing holds or waits on it; nothing is delivered after a discard()."""
        entry = self._locks.setdefault(key, _KeyLock())
        entry.users += 1
        try:
            async with entry.lock:
                if generation != self._generation:
                    return None
                return await self._deliver(key, text, meta)
        finally:
            entry.users -= 1
            if not entry.users:
                del self._locks[key]

    async def drain(self) -> None:
        """Deliver everything held now."""
        for key in self._batch.held_keys():
            await self.flush(key)

    def discard(self) -> int:
        """Drop everything held and cancel every batch on its way: a timer, a batch waiting
        behind its key's running turn, and that turn (a channel shutting down, whose own queue
        of undelivered events is discarded the same way). A piece or command still waiting
        for room or for its key is dropped when it wakes. The number of held batches dropped."""
        self._generation += 1
        keys = self._batch.held_keys()
        for key in keys:
            self._batch.pop(key)
            self._meta.pop(key, None)
        for task in list(self._tasks):
            task.cancel()
        self._timers.clear()
        return len(keys)


__all__ = ["AsyncBatcher", "Coalescer", "HARD_CAP_SECONDS", "MAX_PARTS", "MAX_PENDING", "Pending",
           "SEPARATOR", "WINDOW_SECONDS", "configured", "is_command"]
