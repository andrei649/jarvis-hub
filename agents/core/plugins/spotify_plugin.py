"""
spotify_plugin.py — Spotify control plugin.

Playback control and playlist management for Jerome.
Uses the Spotify Web API with OAuth token.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger("jarvis.plugins.spotify")


class SpotifyPlugin:
    def __init__(self, access_token: str = "", refresh_token: str = "",
                 client_id: str = "", client_secret: str = ""):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_base = "https://api.spotify.com/v1"
        self.client = httpx.AsyncClient(timeout=15.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def get_playback(self) -> Optional[dict]:
        try:
            resp = await self.client.get(
                f"{self.api_base}/me/player",
                headers=self._headers(),
            )
            if resp.status_code == 204:
                return {"is_playing": False, "device": None}
            resp.raise_for_status()
            data = resp.json()
            item = data.get("item", {})
            return {
                "is_playing": data.get("is_playing", False),
                "device": data.get("device", {}).get("name", "unknown"),
                "track": item.get("name", ""),
                "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                "progress_ms": data.get("progress_ms", 0),
                "duration_ms": item.get("duration_ms", 0),
            }
        except Exception as e:
            logger.warning(f"Spotify playback error: {e}")
            return None

    async def play(self, device_id: str = "", context_uri: str = "") -> bool:
        try:
            url = f"{self.api_base}/me/player/play"
            params = {}
            if device_id:
                params["device_id"] = device_id
            body = {}
            if context_uri:
                body["context_uri"] = context_uri
            resp = await self.client.put(url, headers=self._headers(),
                                         params=params, json=body)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Spotify play error: {e}")
            return False

    async def pause(self) -> bool:
        try:
            resp = await self.client.put(
                f"{self.api_base}/me/player/pause",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Spotify pause error: {e}")
            return False

    async def next_track(self) -> bool:
        try:
            resp = await self.client.post(
                f"{self.api_base}/me/player/next",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Spotify next error: {e}")
            return False

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.api_base}/search",
                headers=self._headers(),
                params={"q": query, "type": "track,playlist", "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            tracks = data.get("tracks", {}).get("items", [])
            return [
                {
                    "name": t["name"],
                    "artist": ", ".join(a["name"] for a in t["artists"]),
                    "uri": t["uri"],
                    "duration_ms": t.get("duration_ms", 0),
                }
                for t in tracks
            ]
        except Exception as e:
            logger.warning(f"Spotify search error: {e}")
            return []

    async def get_devices(self) -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.api_base}/me/player/devices",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("devices", [])
        except Exception as e:
            logger.warning(f"Spotify devices error: {e}")
            return []

    async def close(self):
        await self.client.aclose()
