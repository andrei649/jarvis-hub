"""
discord.py — Discord channel adapter for Jarvis.

Port of OpenJarvis's Discord channel to pure Python.
Uses discord.py for message handling.
"""

import asyncio
import logging
from typing import Optional

from .base import ChannelAdapter

logger = logging.getLogger("jarvis.channels.discord")

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False


class DiscordChannel(ChannelAdapter):
    def __init__(self, token: str = "", handler=None):
        super().__init__("discord", handler)
        self.token = token
        self._client: Optional[discord.Client] = None

    async def start(self):
        if not DISCORD_AVAILABLE:
            logger.warning("discord.py not installed — Discord channel unavailable")
            return
        if not self.token:
            logger.warning("No Discord token configured")
            return

        intents = discord.Intents.default()
        intents.message_content = True

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            logger.info(f"Discord bot connected as {self._client.user}")

        @self._client.event
        async def on_message(message):
            if message.author == self._client.user:
                return
            if self.handler:
                response = await self.handler(message.content, channel="discord")
                if response:
                    await message.channel.send(response)

        self._running = True
        # discord.py 2.x: Client.loop is the MISSING sentinel until start() runs,
        # so `self._client.loop.create_task` raises AttributeError. Schedule on the
        # running loop instead, and keep the task so stop() can cancel it.
        self._start_task = asyncio.create_task(self._client.start(self.token))

    async def stop(self):
        self._running = False
        if self._client:
            await self._client.close()
        task = getattr(self, "_start_task", None)
        if task is not None:
            task.cancel()

    async def send(self, message: str, **kwargs) -> bool:
        if not self._client or not self._client.is_ready():
            return False
        channel_id = kwargs.get("channel_id")
        if channel_id:
            channel = self._client.get_channel(int(channel_id))
            if channel:
                await channel.send(message)
                return True
        return False
