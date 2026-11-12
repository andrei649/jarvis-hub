"""
base.py — Abstract channel adapter interface.

Each channel (voice, web, telegram) implements send/receive
and registers with the orchestrator for routing.
"""

import functools
import inspect
import logging
from abc import ABC, abstractmethod
from typing import Callable, ClassVar, Optional

from .descriptor import ChannelDescriptor
from .reconnect import ChannelHealth

logger = logging.getLogger("jarvis.channels")


def _outbound_safe(send):
    """H069: *send* with the transport gate in front of it — the agent's silence token is
    not sent (and counts as delivered), every other text is sanitized first
    (:mod:`.outbound_safety`)."""

    @functools.wraps(send)
    async def safe_send(self, message, *args, **kwargs):
        from . import outbound_safety

        if outbound_safety.is_silence(message):
            logger.info("Channel %s: the reply was the agent's silence token; nothing sent",
                        getattr(self, "channel_id", "?"))
            return True
        return await send(self, outbound_safety.sanitize_outbound(message), *args, **kwargs)

    safe_send.__outbound_safe__ = True
    return safe_send


class ChannelAdapter(ABC):
    #: What this channel can display and how much of it (Hermes absorption 4a). The
    #: default is the honest minimum — plain text, no cap, no edits — so an adapter that
    #: declares nothing is rendered conservatively rather than assumed capable.
    descriptor: ClassVar[ChannelDescriptor] = ChannelDescriptor()

    def __init_subclass__(cls, **kwargs):
        # H069: every adapter's own ``send`` passes the outbound gate, whoever calls it
        # (the manager, a job, the adapter itself). A synchronous test double is left as
        # it is: wrapping it would turn its bool into a coroutine.
        super().__init_subclass__(**kwargs)
        send = cls.__dict__.get("send")
        if (send is not None and inspect.iscoroutinefunction(send)
                and not getattr(send, "__outbound_safe__", False)):
            cls.send = _outbound_safe(send)

    def __init__(self, channel_id: str, handler: Optional[Callable] = None):
        self.channel_id = channel_id
        self.handler = handler
        self._running = False

    @property
    def health(self) -> ChannelHealth:
        """H100: what the status surface says about this channel's connection (created on
        first use, so an adapter built without ``__init__`` still has one)."""
        health = self.__dict__.get("_health")
        if health is None:
            health = self.__dict__["_health"] = ChannelHealth()
        return health

    def health_snapshot(self) -> dict:
        """Connection health for ``GET /status``: state, error kind, failures in a row,
        seconds to the next retry, the fatal reason. Kinds and counts only."""
        row = self.health.snapshot()
        if row["state"] == "idle" and getattr(self, "_running", False):
            row["state"] = "running"
        return row

    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...

    @abstractmethod
    async def send(self, message: str, **kwargs) -> bool:
        ...

    async def receive(self, text: str, **kwargs):
        if self.handler:
            return await self.handler(text, channel=self.channel_id, **kwargs)
        return None
