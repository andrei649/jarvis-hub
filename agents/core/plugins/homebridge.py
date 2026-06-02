"""
homebridge.py — Homebridge Smart Home plugin.

Controls smart home accessories via Homebridge REST API.
Agents served: jarvis, ultron (home automation).
Data scope: LOCAL_ONLY — no data leaves the local network.
"""

import logging
from typing import Optional

import httpx

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.homebridge")


class HomebridgePlugin:
    def __init__(self, bridge_url: str = "http://192.168.1.100:8581", api_token: str = ""):
        self.bridge_url = bridge_url.rstrip("/")
        self.api_token = api_token
        self.api_base = f"{self.bridge_url}/api"
        self.client = PluginHTTPClient.for_plugin("homebridge")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def get_accessories(self) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.api_base}/accessories",
                headers=self._headers(),
                timeout=8.0,
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.warning(f"Homebridge not reachable at {self.bridge_url}")
            return []
        except Exception as e:
            logger.error(f"Homebridge accessories error: {e}")
            return []

    async def get_accessory(self, accessory_id: str) -> Optional[dict]:
        try:
            resp = await self.client.get(
                f"{self.api_base}/accessories/{accessory_id}",
                headers=self._headers(),
                timeout=8.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Homebridge accessory {accessory_id} error: {e}")
            return None

    async def set_characteristic(
        self,
        accessory_id: str,
        characteristic_id: int,
        value,
        service_id: Optional[int] = None,
    ) -> bool:
        try:
            body = {
                "characteristicId": characteristic_id,
                "value": value,
            }
            if service_id:
                body["serviceId"] = service_id

            resp = await self.client.put(
                f"{self.api_base}/accessories/{accessory_id}",
                headers=self._headers(),
                json=body,
                timeout=8.0,
            )
            resp.raise_for_status()
            logger.info(f"Homebridge set {accessory_id}:{characteristic_id} = {value}")
            return True
        except Exception as e:
            logger.error(f"Homebridge set error: {e}")
            return False

    async def turn_on(self, accessory_id: str) -> bool:
        return await self.set_characteristic(accessory_id, characteristic_id=1, value=True)

    async def turn_off(self, accessory_id: str) -> bool:
        return await self.set_characteristic(accessory_id, characteristic_id=1, value=False)

    async def set_brightness(self, accessory_id: str, brightness: int) -> bool:
        brightness = max(0, min(100, brightness))
        return await self.set_characteristic(accessory_id, characteristic_id=2, value=brightness)

    async def get_bridge_status(self) -> dict:
        try:
            resp = await self.client.get(
                f"{self.api_base}/status",
                headers=self._headers(),
                timeout=8.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Homebridge status error: {e}")
            return {"error": str(e), "reachable": False}

    async def close(self):
        await self.client.close()
