"""
discord.py — Discord channel adapter for Jarvis.

Port of OpenJarvis's Discord channel to pure Python.
Uses discord.py for message handling.
"""

import asyncio
import logging
from typing import Optional

from .base import ChannelAdapter
from .descriptor import DIALECT_MARKDOWN, ChannelDescriptor
from .render import render_outbound

logger = logging.getLogger("jarvis.channels.discord")

#: Discord's cap on one message; it renders Markdown itself, so text is only chunked.
DISCORD_MAX_MESSAGE_LENGTH = 2_000

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False


class DiscordChannel(ChannelAdapter):
    descriptor = ChannelDescriptor(
        dialect=DIALECT_MARKDOWN,
        max_message_length=DISCORD_MAX_MESSAGE_LENGTH,
        supports_edit=True,
        supports_media=True,
        supports_threads=True,
    )

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
            await self._handle_message(message)

        self._running = True
        # discord.py 2.x: Client.loop is the MISSING sentinel until start() runs,
        # so `self._client.loop.create_task` raises AttributeError. Schedule on the
        # running loop instead, and keep the task so stop() can cancel it.
        self._start_task = asyncio.create_task(self._client.start(self.token))

    async def _handle_message(self, message) -> None:
        """Route one inbound Discord message through the handler.

        Lives outside the ``on_message`` closure so the inbound path can be driven
        without a live client. The sender is threaded as ``message.author.id`` — the
        stable Discord identity, unlike the display name — so the gateway's pairing
        gate can hold a stranger; before this the handler saw no sender at all and
        pairing could never apply to Discord. Nothing else about the author is
        observed or logged. (Hermes absorption 5b)
        """
        if self._client is not None and message.author == self._client.user:
            return
        if not self.handler:
            return
        # The orchestrator queues a governed channel.reply. Echoing its return
        # value here would bypass approval (and duplicate an approved delivery).
        await self.handler(
            message.content, channel="discord", sender=str(message.author.id),
            channel_id=str(message.channel.id),
        )

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
        try:
            if channel_id:
                channel = self._client.get_channel(int(channel_id))
                if channel:
                    for piece in render_outbound(str(message or ""), self.descriptor):
                        await channel.send(piece)
                    return True
        except Exception:
            logger.warning("Discord reply transport failed", exc_info=True)
        return False
