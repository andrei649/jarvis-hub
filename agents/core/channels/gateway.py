"""
gateway.py — Unified Gateway for all channels.
Single entry point for incoming messages, regardless of source channel.
Provides consistent message routing, rate limiting, and channel health.
"""

import logging
import time
from typing import Any, Callable, Optional

from ..action_origin import origin_for_channel
from ..log_safe import log_safe

logger = logging.getLogger("jarvis.gateway")


class Gateway:
    """
    Unified message gateway. All channels (web, voice, telegram) route
    incoming messages through this single entry point before reaching
    the orchestrator. Provides rate limiting, message logging, and
    channel health tracking.
    """

    def __init__(self, handler: Optional[Callable] = None, pairing: Any = None):
        self.handler = handler
        # H12.19 — optional inbound sender-pairing gate. When set (and pairing is
        # enabled), unknown senders are held for approval instead of reaching the
        # handler. None → unchanged behavior.
        self.pairing = pairing
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
        logger.info("Gateway: channel '%s' registered", log_safe(channel_id))

    def unregister_channel(self, channel_id: str):
        self._channels.pop(channel_id, None)
        self._rate_limits.pop(channel_id, None)
        logger.info("Gateway: channel '%s' unregistered", log_safe(channel_id))

    async def route(self, text: str, channel: str = "web", **kwargs) -> Optional[str]:
        if channel not in self._channels:
            self.register_channel(channel)

        if not self._check_rate_limit(channel):
            logger.warning("Gateway: rate limit exceeded for channel '%s'", log_safe(channel))
            return "Rate limit exceeded. Please wait before sending another message."

        # H12.19 — inbound sender pairing. A `sender` identity (set by the channel)
        # that isn't allowed is held for owner approval; the message never reaches
        # the handler. No pairing gate or no sender → routes as before.
        sender = kwargs.get("sender")
        if self.pairing is not None and sender is not None:
            try:
                decision = self.pairing.gate_inbound(channel, str(sender),
                                                      code=kwargs.get("pairing_code"))
            except Exception:
                logger.warning("Gateway: pairing gate error — allowing", exc_info=True)
                decision = {"allowed": True}
            if not decision.get("allowed", True):
                logger.info("Gateway: held unpaired sender on '%s' (status=%s)",
                            log_safe(channel), decision.get('status'))
                return decision.get("message") or None

        self._channels[channel]["message_count"] += 1
        self._channels[channel]["last_activity"] = time.time()

        if not self.handler:
            logger.error("Gateway: no handler registered")
            return None

        try:
            kwargs.setdefault("origin", origin_for_channel(channel))
            result = await self.handler(text, channel=channel, **kwargs)
            self._channels[channel]["last_activity"] = time.time()
            return result
        except Exception as e:
            self._channels[channel]["error_count"] += 1
            logger.error("Gateway: handler error on channel '%s': %s", log_safe(channel), e)
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
