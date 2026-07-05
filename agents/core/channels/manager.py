"""
manager.py — ChannelManager: the channel registry + per-channel I/O (CLN-2).

Extracted from the Orchestrator god-object so the "which channels exist and how we
start/stop/send on them" concern is decoupled from orchestration lifecycle. The
Orchestrator keeps a `channels` property that delegates here, so existing
`orch.channels[...]` access is unchanged.
"""

import logging

from .base import ChannelAdapter
from ..errors import E_CHANNEL_START_FAIL
from ..log import log_error

logger = logging.getLogger("jarvis.channels.manager")


class ChannelManager:
    def __init__(self):
        self.channels: dict[str, ChannelAdapter] = {}

    def register(self, channel: ChannelAdapter) -> None:
        self.channels[channel.channel_id] = channel
        logger.info(f"Channel registered: {channel.channel_id}")

    def get(self, channel_id: str):
        return self.channels.get(channel_id)

    async def start_all(self) -> None:
        for cid, ch in self.channels.items():
            try:
                await ch.start()
            except Exception as e:
                log_error(logger, E_CHANNEL_START_FAIL, name=cid, detail=str(e))

    async def stop_all(self) -> None:
        for cid, ch in self.channels.items():
            await ch.stop()

    async def send(self, channel: str, response, **kwargs) -> bool:
        """Dispatch a reply back out on its channel (no-op if not registered)."""
        ch = self.channels.get(channel)
        if not ch:
            return False
        if channel == "telegram":
            return bool(await ch.send(response, **kwargs))
        elif channel == "web":
            return bool(await ch.send(response, **kwargs))
        elif channel == "voice":
            return bool(await ch.send(response))
        return False
