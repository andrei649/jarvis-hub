"""
apple_health.py — Apple Health plugin.

Reads sleep, HRV, and activity data via a LAN companion bridge.
Agents served: hercules (fitness, sleep, nutrition).
Data scope: LOCAL_ONLY — health data never leaves the local network.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.apple_health")


class AppleHealthPlugin:
    def __init__(self, bridge_url: str = "http://192.168.1.100:8081"):
        self.bridge_url = bridge_url.rstrip("/")
        self.client = PluginHTTPClient.for_plugin("apple_health")

    async def get_sleep(self, days: int = 1) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.bridge_url}/health/sleep",
                params={"days": days},
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.warning(f"Apple Health bridge not reachable at {self.bridge_url}")
            return []
        except Exception as e:
            logger.error(f"Apple Health sleep error: {e}")
            return []

    async def get_hrv(self, days: int = 1) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.bridge_url}/health/hrv",
                params={"days": days},
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except (httpx.ConnectError, httpx.TimeoutException):
            return []
        except Exception as e:
            logger.error(f"Apple Health HRV error: {e}")
            return []

    async def get_activity(self, days: int = 1) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.bridge_url}/health/activity",
                params={"days": days},
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except (httpx.ConnectError, httpx.TimeoutException):
            return []
        except Exception as e:
            logger.error(f"Apple Health activity error: {e}")
            return []

    async def get_steps(self, days: int = 1) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.bridge_url}/health/steps",
                params={"days": days},
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except (httpx.ConnectError, httpx.TimeoutException):
            return []
        except Exception as e:
            logger.error(f"Apple Health steps error: {e}")
            return []

    async def get_workouts(self, days: int = 1) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.bridge_url}/health/workouts",
                params={"days": days},
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except (httpx.ConnectError, httpx.TimeoutException):
            return []
        except Exception as e:
            logger.error(f"Apple Health workouts error: {e}")
            return []

    async def get_summary(self, days: int = 1) -> dict:
        sleep = await self.get_sleep(days)
        hrv = await self.get_hrv(days)
        activity = await self.get_activity(days)
        steps = await self.get_steps(days)
        workouts = await self.get_workouts(days)

        return {
            "sleep": sleep,
            "hrv": hrv,
            "activity": activity,
            "steps": steps,
            "workouts": workouts,
            "days": days,
            "source": self.bridge_url,
        }

    async def close(self):
        await self.client.close()
