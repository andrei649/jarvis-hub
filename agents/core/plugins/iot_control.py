import logging
from ..http_client import PluginHTTPClient
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.iot")


class IoTControlPlugin:
    def __init__(self, client_id: str = "", secret: str = "", device_id: str = ""):
        self.client_id = client_id.strip()
        self.secret = secret.strip()
        self.device_id = device_id.strip()
        self.client = PluginHTTPClient.for_plugin("iot")

    @resilient_call(
        max_retries=2,
        timeout=10.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:iot",
        circuit_breaker_threshold=3,
        metrics_agent_id="ultron",
        metrics_backend="tuya.com",
    )
    async def toggle_switch(self, state: bool) -> dict:
        """Toggles smart IoT sockets. Fallbacks to mock LAN sync if unconfigured."""
        if not self.client_id or not self.device_id:
            logger.warning("Tuya Client ID or Device ID missing — running in local mock LAN loop")
            return {"status": "mock_toggled", "device": self.device_id, "state": "ON" if state else "OFF", "_mock": True}

        # Simulate Tuya API post request (restricted domain access verification)
        url = f"https://openapi.tuya.com/v1.0/devices/{self.device_id}/commands"
        headers = {
            "client_id": self.client_id,
            "sign": "MOCK_SIGNATURE",
            "t": "1700000000000",
            "Content-Type": "application/json",
        }
        payload = {
            "commands": [{"code": "switch_1", "value": state}]
        }
        resp = await self.client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return {"status": "toggled", "device": self.device_id, "state": "ON" if state else "OFF"}

    async def close(self):
        await self.client.close()
