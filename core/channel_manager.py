import logging
from typing import Optional

logger = logging.getLogger("channel")


class ChannelManager:
    def __init__(self):
        self._handlers: dict[str, dict] = {}

    def register(self, channel: str, handler: dict):
        self._handlers[channel] = handler
        logger.info(f"Channel registered: {channel}")

    async def send(self, channel: str, agent_id: str, message: str) -> bool:
        handler = self._handlers.get(channel)
        if not handler:
            logger.warning(f"No handler for channel '{channel}'")
            return False
        try:
            send_fn = handler.get("send")
            if send_fn:
                await send_fn(agent_id, message)
                return True
        except Exception as e:
            logger.error(f"Channel send error ({channel}): {e}")
        return False

    async def receive(self, channel: str, agent_id: str) -> Optional[str]:
        handler = self._handlers.get(channel)
        if not handler:
            return None
        try:
            receive_fn = handler.get("receive")
            if receive_fn:
                return await receive_fn(agent_id)
        except Exception as e:
            logger.error(f"Channel receive error ({channel}): {e}")
        return None
