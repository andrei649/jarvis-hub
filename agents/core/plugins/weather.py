import logging

import httpx

logger = logging.getLogger("jarvis.plugins.weather")


class WeatherPlugin:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_weather(self, location: str = "") -> str:
        url = f"https://wttr.in/{location.strip() or ''}?format=%l:+%t,+%C,+%h+humidity,+%w+wind"
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            text = resp.text.strip()
            return text if text else f"Weather data unavailable for '{location or 'current location'}'."
        except Exception as e:
            return f"Weather error: {e}"

    async def get_forecast(self, location: str = "", days: int = 3) -> str:
        url = f"https://wttr.in/{location.strip() or ''}?format=%l:+%t,+%C&m"
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            text = resp.text.strip()
            return text if text else f"Forecast unavailable for '{location or 'current location'}'."
        except Exception as e:
            return f"Forecast error: {e}"

    async def close(self):
        await self.client.aclose()
