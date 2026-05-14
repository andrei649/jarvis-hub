"""
WhatsApp Bridge Plugin — WhatsApp messaging via Meta Cloud API.
Gated: only usable by Frigga agent.
Requires: WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN in .env
Permission scope: read-write
"""

import logging
import os
from typing import Optional

from core.permission_gate import PermissionGate

logger = logging.getLogger("plugins.whatsapp")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

API_BASE = "https://graph.facebook.com/v18.0"


class WhatsAppBridge:
    def __init__(self, permission_gate: PermissionGate):
        self._phone_number_id = None
        self._access_token = None
        self._client = None
        self.permission_gate = permission_gate

    async def start(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> bool:
        if not HTTPX_AVAILABLE:
            logger.error("httpx not installed")
            return False
        self._phone_number_id = phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self._access_token = access_token or os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        if not self._phone_number_id or not self._access_token:
            logger.error("WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN must be set")
            return False
        self._client = httpx.AsyncClient()
        logger.info("WhatsApp bridge started (Frigga only)")
        return True

    async def send_message(self, to: str, text: str) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.post(
                f"{API_BASE}/{self._phone_number_id}/messages",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text[:4096]},
                },
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"WhatsApp send error: {e}")
            return False

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None


def create(permission_gate: PermissionGate) -> WhatsAppBridge:
    return WhatsAppBridge(permission_gate)
