"""
gateway.py — Unified Gateway for all channels.
Single entry point for incoming messages, regardless of source channel.
Provides consistent message routing, rate limiting, and channel health.
"""

import asyncio
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("jarvis.gateway")


class Gateway:
    """
    Unified message gateway. All channels (web, voice, telegram) route
    incoming messages through this single entry point before reaching
    the orchestrator. Provides rate limiting, message logging, and
    channel health tracking.
    """

    def __init__(self, handler: Optional[Callable] = None):
        self.handler = handler
        self._channels: dict[str, dict] = {}
        self._rate_limits: dict[str, list[float]] = {}
        self._max_rate = 10
        self._window = 60.0

    def register_channel(self, channel_id: str, metadata: dict = None):
        self._channels[channel_id] = {
            "id": channel_id,
            "registered_at": time.time(),
            "last_activity": time.time(),
            "message_count": 0,
            "error_count": 0,
            "status": "active",
            **(metadata or {}),
        }
        logger.info(f"Gateway: channel '{channel_id}' registered")

    def unregister_channel(self, channel_id: str):
        self._channels.pop(channel_id, None)
        self._rate_limits.pop(channel_id, None)
        logger.info(f"Gateway: channel '{channel_id}' unregistered")

    async def route(self, text: str, channel: str = "web", **kwargs) -> Optional[str]:
        if channel not in self._channels:
            self.register_channel(channel)

        if not self._check_rate_limit(channel):
            logger.warning(f"Gateway: rate limit exceeded for channel '{channel}'")
            return "Rate limit exceeded. Please wait before sending another message."

        self._channels[channel]["message_count"] += 1
        self._channels[channel]["last_activity"] = time.time()

        if not self.handler:
            logger.error("Gateway: no handler registered")
            return None

        try:
            result = await self.handler(text, channel=channel, **kwargs)
            self._channels[channel]["last_activity"] = time.time()
            return result
        except Exception as e:
            self._channels[channel]["error_count"] += 1
            logger.error(f"Gateway: handler error on channel '{channel}': {e}")
            return None

    def _check_rate_limit(self, channel: str) -> bool:
        now = time.time()
        if channel not in self._rate_limits:
            self._rate_limits[channel] = []
        self._rate_limits[channel] = [
            t for t in self._rate_limits[channel] if now - t < self._window
        ]
        if len(self._rate_limits[channel]) >= self._max_rate:
            return False
        self._rate_limits[channel].append(now)
        return True

    def get_channel_info(self, channel_id: str = None) -> dict:
        if channel_id:
            return self._channels.get(channel_id, {})
        return dict(self._channels)

    def get_summary(self) -> dict:
        return {
            "channels": list(self._channels.keys()),
            "total_messages": sum(c["message_count"] for c in self._channels.values()),
            "total_errors": sum(c["error_count"] for c in self._channels.values()),
            "active_channels": sum(1 for c in self._channels.values() if c["status"] == "active"),
        }

    def set_rate_limit(self, max_per_minute: int):
        self._max_rate = max_per_minute
