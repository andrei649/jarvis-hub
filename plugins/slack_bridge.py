"""
Slack Bridge Plugin — Slack messaging via Bot token.
Requires: SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET in .env
Permission scope: read-write
"""

import logging
import os
from typing import Optional

from core.permission_gate import PermissionGate

logger = logging.getLogger("plugins.slack")

try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.errors import SlackApiError
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False


class SlackBridge:
    def __init__(self, permission_gate: PermissionGate):
        self._client = None
        self.permission_gate = permission_gate

    async def start(self, bot_token: Optional[str] = None) -> bool:
        if not SLACK_AVAILABLE:
            logger.error("slack-sdk not installed")
            return False
        token = bot_token or os.getenv("SLACK_BOT_TOKEN", "")
        if not token:
            logger.error("SLACK_BOT_TOKEN not set")
            return False
        try:
            self._client = AsyncWebClient(token=token)
            auth = await self._client.auth_test()
            logger.info(f"Slack bridge started (team: {auth.get('team', '?')})")
            return True
        except Exception as e:
            logger.error(f"Slack auth failed: {e}")
            return False

    async def send_message(self, channel: str, text: str) -> bool:
        if not self._client:
            return False
        try:
            await self._client.chat_postMessage(channel=channel, text=text[:4000])
            return True
        except SlackApiError as e:
            logger.error(f"Slack send error: {e}")
            return False

    async def list_channels(self) -> list[dict]:
        if not self._client:
            return []
        try:
            result = await self._client.conversations_list(types="public_channel,private_channel")
            return [
                {"id": c["id"], "name": c["name"], "member_count": c.get("num_members", 0)}
                for c in result.get("channels", [])
            ]
        except Exception as e:
            logger.error(f"Slack list channels error: {e}")
            return []

    async def stop(self):
        self._client = None


def create(permission_gate: PermissionGate) -> SlackBridge:
    return SlackBridge(permission_gate)
