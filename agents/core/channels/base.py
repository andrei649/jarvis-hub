"""
base.py — Abstract channel adapter interface.

Each channel (voice, web, telegram) implements send/receive
and registers with the orchestrator for routing.
"""

from abc import ABC, abstractmethod
from typing import Callable, ClassVar, Optional

from .descriptor import ChannelDescriptor
from .reconnect import ChannelHealth


class ChannelAdapter(ABC):
    #: What this channel can display and how much of it (Hermes absorption 4a). The
    #: default is the honest minimum — plain text, no cap, no edits — so an adapter that
    #: declares nothing is rendered conservatively rather than assumed capable.
    descriptor: ClassVar[ChannelDescriptor] = ChannelDescriptor()

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
