"""
gemini_cache.py — Gemini Context Caching via REST cachedContents API.
Manages creation, extension, and deletion of cached content for session history.
Cache mappings are persisted in the SQLite settings DB (category "cache")
via direct INSERT OR REPLACE to bypass put_category's update-only constraint.
"""

import hashlib
import json
import logging
from typing import Optional

import httpx

from core.settings_db import get_conn

logger = logging.getLogger("jarvis.gemini.cache")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TTL_SECONDS = 3600


class ContextCache:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
        self._cache_map: dict[str, dict] = {}
        self._load_persisted()

    def _load_persisted(self):
        try:
            conn = get_conn()
            row = conn.execute(
                "SELECT value FROM settings WHERE category='cache' AND key='entries'"
            ).fetchone()
            conn.close()
            if row:
                self._cache_map = json.loads(row["value"])
                logger.info(f"Loaded {len(self._cache_map)} cache entries from DB")
        except Exception:
            self._cache_map = {}

    def _save_persisted(self):
        try:
            conn = get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO settings (category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
                ("cache", "entries", json.dumps(self._cache_map), "Cache entries", "json", "[]"),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to persist cache map: {e}")

    @staticmethod
    def cache_key(system_instruction: str, model: str) -> str:
        raw = f"{system_instruction}|{model}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def create_or_extend(
        self,
        session_id: str,
        system_instruction: str,
        history: list[dict],
        model: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> Optional[str]:
        existing = self._cache_map.get(session_id)
        if existing:
            result = await self._extend(existing["cache_name"], ttl_seconds)
            if result is None:
                del self._cache_map[session_id]
                self._save_persisted()
                return await self._create(session_id, system_instruction, history, model, ttl_seconds)
            return result
        return await self._create(session_id, system_instruction, history, model, ttl_seconds)

    async def _create(
        self, session_id: str, system_instruction: str,
        history: list[dict], model: str, ttl: int,
    ) -> Optional[str]:
        url = f"{GEMINI_API_BASE}/cachedContents?key={self.api_key}"
        payload = {
            "model": f"models/{model}",
            "contents": history,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "ttl": f"{ttl}s",
        }
        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            cache_name = data.get("name", "")
            if cache_name:
                self._cache_map[session_id] = {
                    "cache_name": cache_name,
                    "model": model,
                    "contents_count": len(history),
                }
                self._save_persisted()
                logger.info(f"Created cache {cache_name} for session {session_id}")
            return cache_name or None
        except Exception as e:
            logger.warning(f"Failed to create cache for {session_id}: {e}")
            return None

    async def _extend(self, cache_name: str, ttl: int) -> Optional[str]:
        url = f"{GEMINI_API_BASE}/{cache_name}?key={self.api_key}"
        payload = {"ttl": f"{ttl}s"}
        try:
            resp = await self.client.patch(url, json=payload)
            resp.raise_for_status()
            logger.info(f"Extended TTL for {cache_name}")
            return cache_name
        except Exception as e:
            logger.warning(f"Failed to extend cache {cache_name}: {e}")
            return None

    async def delete(self, cache_name: str) -> bool:
        url = f"{GEMINI_API_BASE}/{cache_name}?key={self.api_key}"
        try:
            resp = await self.client.delete(url)
            resp.raise_for_status()
            for sid, entry in list(self._cache_map.items()):
                if entry["cache_name"] == cache_name:
                    del self._cache_map[sid]
            self._save_persisted()
            return True
        except Exception as e:
            logger.warning(f"Failed to delete cache {cache_name}: {e}")
            return False

    def get_cache_info(self, session_id: str) -> Optional[dict]:
        return self._cache_map.get(session_id)

    def count_entries(self) -> int:
        return len(self._cache_map)

    async def close(self):
        await self.client.aclose()
