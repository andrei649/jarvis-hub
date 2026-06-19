"""
base.py — Abstract channel adapter interface.

Each channel (voice, web, telegram) implements send/receive
and registers with the orchestrator for routing.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional


class ChannelAdapter(ABC):
    def __init__(self, channel_id: str, handler: Optional[Callable] = None):
        self.channel_id = channel_id
        self.handler = handler
        self._running = False

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
