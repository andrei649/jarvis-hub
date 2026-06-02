import logging

from ..http_client import PluginHTTPClient
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.weather")


class WeatherPlugin:
    def __init__(self):
        self.client = PluginHTTPClient.for_plugin("weather")

    @resilient_call(
        max_retries=2,
        timeout=10.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:weather",
        circuit_breaker_threshold=3,
        metrics_agent_id="weather",
        metrics_backend="wttr.in",
    )
    async def get_weather(self, location: str = "") -> str:
        url = f"https://wttr.in/{location.strip() or ''}?format=%l:+%t,+%C,+%h+humidity,+%w+wind"
        resp = await self.client.get(url)
        resp.raise_for_status()
        text = resp.text.strip()
        return text if text else f"Weather data unavailable for '{location or 'current location'}'."

    @resilient_call(
        max_retries=2,
        timeout=10.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:weather",
        circuit_breaker_threshold=3,
        metrics_agent_id="weather",
        metrics_backend="wttr.in",
    )
    async def get_forecast(self, location: str = "", days: int = 3) -> str:
        url = f"https://wttr.in/{location.strip() or ''}?format=%l:+%t,+%C&m"
        resp = await self.client.get(url)
        resp.raise_for_status()
        text = resp.text.strip()
        return text if text else f"Forecast unavailable for '{location or 'current location'}'."

    async def close(self):
        await self.client.close()
