"""
oauth.py — OAuth2 helper for token lifecycle management.
Supports Google (Gmail, Calendar) and Spotify token refresh.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("jarvis.oauth")

TOKEN_DIR = Path(__file__).resolve().parent.parent.parent.parent / "memory_logs" / "tokens"
TOKEN_DIR.mkdir(parents=True, exist_ok=True)


def _token_path(service: str) -> Path:
    return TOKEN_DIR / f"{service}_token.json"


def save_token(service: str, data: dict):
    data["_saved_at"] = time.time()
    _token_path(service).write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info(f"Token saved for {service}")


def load_token(service: str) -> Optional[dict]:
    path = _token_path(service)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


GOOGLE_CLIENT_ID = ""
GOOGLE_CLIENT_SECRET = ""
SPOTIFY_CLIENT_ID = ""
SPOTIFY_CLIENT_SECRET = ""
REDIRECT_URI = "http://127.0.0.1:8080/api/oauth/callback"


def init_from_env():
    import os
    global GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    global SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")


def get_google_auth_url(service: str = "gmail") -> str:
    scope_map = {
        "gmail": "https://www.googleapis.com/auth/gmail.modify",
        "calendar": "https://www.googleapis.com/auth/calendar",
    }
    scope = scope_map.get(service, scope_map["gmail"])
    return (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state=google:{service}"
    )


def get_spotify_auth_url() -> str:
    scope = "user-read-playback-state user-modify-playback-state playlist-read-private"
    return (
        f"https://accounts.spotify.com/authorize"
        f"?client_id={SPOTIFY_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state=spotify"
    )


async def exchange_google_code(code: str) -> Optional[dict]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if resp.is_success:
            data = resp.json()
            save_token("google", data)
            return data
        logger.error(f"Google token exchange failed: {resp.text}")
        return None


async def exchange_spotify_code(code: str) -> Optional[dict]:
    auth = httpx.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            auth=auth,
        )
        if resp.is_success:
            data = resp.json()
            save_token("spotify", data)
            return data
        logger.error(f"Spotify token exchange failed: {resp.text}")
        return None


async def refresh_google_token() -> Optional[str]:
    token_data = load_token("google")
    if not token_data or "refresh_token" not in token_data:
        logger.warning("No Google refresh token available")
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "refresh_token": token_data["refresh_token"],
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
        )
        if resp.is_success:
            data = resp.json()
            merged = {**token_data, **data}
            save_token("google", merged)
            return data.get("access_token", "")
        logger.error(f"Google token refresh failed: {resp.text}")
        return None


async def refresh_spotify_token() -> Optional[str]:
    token_data = load_token("spotify")
    if not token_data or "refresh_token" not in token_data:
        logger.warning("No Spotify refresh token available")
        return None
    auth = httpx.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "refresh_token": token_data["refresh_token"],
                "grant_type": "refresh_token",
            },
            auth=auth,
        )
        if resp.is_success:
            data = resp.json()
            merged = {**token_data, **data}
            save_token("spotify", merged)
            return data.get("access_token", "")
        logger.error(f"Spotify token refresh failed: {resp.text}")
        return None
