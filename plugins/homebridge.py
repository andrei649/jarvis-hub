"""
Homebridge Plugin — Smart home control via Homebridge HTTP API.
Requires: HOMEBRIDGE_URL in .env (default: http://localhost:8581)
Permission scope: read-write
"""

import logging
import os
from typing import Optional

from core.permission_gate import PermissionGate

logger = logging.getLogger("plugins.homebridge")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class HomebridgePlugin:
    def __init__(self, permission_gate: PermissionGate):
        self._base_url = None
        self._client = None
        self._pin = None
        self.permission_gate = permission_gate

    async def start(self, url: Optional[str] = None, pin: Optional[str] = None) -> bool:
        if not HTTPX_AVAILABLE:
            logger.error("httpx not installed")
            return False
        self._base_url = (url or os.getenv("HOMEBRIDGE_URL", "http://localhost:8581")).rstrip("/")
        self._pin = pin or os.getenv("HOMEBRIDGE_PIN", "")
        self._client = httpx.AsyncClient()
        logger.info(f"Homebridge bridge started ({self._base_url})")
        return True

    async def get_accessories(self) -> list[dict]:
        if not self._client:
            return []
        try:
            resp = await self._client.get(
                f"{self._base_url}/api/accessories",
                headers={"Authorization": self._pin} if self._pin else {},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Homebridge get accessories error: {e}")
            return []

    async def set_characteristic(
        self, accessory_id: int, characteristic: str, value
    ) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.put(
                f"{self._base_url}/api/accessories/{accessory_id}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self._pin,
                } if self._pin else {"Content-Type": "application/json"},
                json={"characteristic_type": characteristic, "value": value},
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Homebridge set error: {e}")
            return False

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None


def create(permission_gate: PermissionGate) -> HomebridgePlugin:
    return HomebridgePlugin(permission_gate)
