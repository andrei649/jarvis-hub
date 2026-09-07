"""
slack.py — Slack channel adapter for Jarvis.

Port of OpenJarvis's Slack channel to pure Python.
Uses slack-sdk for message handling.
"""

import asyncio
import logging
from typing import Optional

from .base import ChannelAdapter
from .descriptor import DIALECT_SLACK_MRKDWN, ChannelDescriptor
from .render import render_outbound

logger = logging.getLogger("jarvis.channels.slack")

#: Slack's cap on the ``text`` of one chat.postMessage.
SLACK_MAX_MESSAGE_LENGTH = 40_000

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False


class SlackChannel(ChannelAdapter):
    descriptor = ChannelDescriptor(
        dialect=DIALECT_SLACK_MRKDWN,
        max_message_length=SLACK_MAX_MESSAGE_LENGTH,
        supports_edit=True,
        supports_media=True,
        supports_threads=True,
    )

    def __init__(self, token: str = "", handler=None):
        super().__init__("slack", handler)
        self.token = token
        self._client: Optional[WebClient] = None

    async def start(self):
        if not SLACK_AVAILABLE:
            logger.warning("slack-sdk not installed — Slack channel unavailable")
            return
        if not self.token:
            logger.warning("No Slack token configured")
            return
        self._client = WebClient(token=self.token)
        self._running = True
        logger.info("Slack channel ready")

    async def stop(self):
        self._running = False

    async def send(self, message: str, **kwargs) -> bool:
        if not self._client:
            return False
        channel = kwargs.get("channel")
        if not channel:
            logger.warning("No Slack channel specified")
            return False
        try:
            # Rendered to mrkdwn and chunked on the source (Hermes absorption 4d).
            # slack_sdk.WebClient is the blocking (urllib) client; run it in an
            # executor so a slow/unreachable Slack API can't freeze the event loop.
            loop = asyncio.get_running_loop()
            for piece in render_outbound(str(message or ""), self.descriptor):
                await loop.run_in_executor(
                    None, lambda text=piece: self._client.chat_postMessage(channel=channel, text=text)
                )
            return True
        except Exception as e:
            logger.error(f"Slack send error: {e}")
            return False

    async def receive_event(self, text: str, channel: str, **kwargs):
        if self.handler:
            return await self.handler(text, channel="slack", slack_channel=channel, **kwargs)
        return None
