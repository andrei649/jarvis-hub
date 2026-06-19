"""
whatsapp_bridge.py — WhatsApp local bridge plugin.

Local-only WhatsApp bridge for Frigga.
Family data NEVER leaves the LAN.
Bridge connects to a local WhatsApp Web instance running on the Pi 5.
"""

import logging

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.whatsapp")


class WhatsAppBridgePlugin:
    def __init__(self, bridge_url: str = "http://192.168.1.100:3000"):
        self.bridge_url = bridge_url
        self.client = PluginHTTPClient.for_plugin("whatsapp")

    async def send_message(self, to: str, message: str) -> bool:
        try:
            resp = await self.client.post(
                f"{self.bridge_url}/send",
                json={"to": to, "message": message},
            )
            resp.raise_for_status()
            logger.info(f"WhatsApp message sent to {to}")
            return True
        except Exception as e:
            logger.warning(f"WhatsApp send error (bridge may be offline): {e}")
            return False

    async def send_media(self, to: str, media_url: str,
                         caption: str = "") -> bool:
        try:
            resp = await self.client.post(
                f"{self.bridge_url}/send-media",
                json={"to": to, "mediaUrl": media_url, "caption": caption},
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"WhatsApp media error: {e}")
            return False

    async def get_status(self) -> dict:
        try:
            resp = await self.client.get(f"{self.bridge_url}/status", timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {"connected": False, "error": "Bridge offline"}

    async def send_manual_entry(self, to: str, message: str) -> str:
        """Fallback: log message for manual sending when bridge is offline."""
        log_line = f"[MANUAL WHATSAPP] To: {to} | Message: {message}"
        logger.info(log_line)
        return log_line

    async def close(self):
        await self.client.close()
