"""
router.py — Auto-detect which LLM backend is available.
Tries LM Studio first (GPU), falls back to Ollama (CPU).
"""

from typing import Optional

import httpx
from .base import LLMBackend, LMStudioBackend, OllamaBackend


class LLMRouter:
    """Auto-detect and route to the best available LLM backend."""

    def __init__(self):
        self._backend: LLMBackend = None
        self._backend_name: str = "none"
        # Name of the model actually loaded in the live backend (auto-detected in
        # detect()). None until detected / when no backend is up.
        self._detected_model: Optional[str] = None

    async def detect(self):
        """Try LM Studio (GPU) first, fall back to Ollama.

        On success, also capture the model actually loaded in the backend so the
        system uses the real loaded model rather than a hard-coded name."""
        self._detected_model = None
        if await self._check("http://localhost:1234/v1/models"):
            self._backend = LMStudioBackend()
            self._backend_name = "lm-studio"
            self._detected_model = await self._fetch_loaded_model(
                "http://localhost:1234/v1/models", "lmstudio")
            return
        if await self._check("http://localhost:11434/api/tags"):
            self._backend = OllamaBackend()
            self._backend_name = "ollama"
            self._detected_model = await self._fetch_loaded_model(
                "http://localhost:11434/api/tags", "ollama")
            return
        self._backend_name = "none"

    async def _check(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                resp = await c.get(url)
                return resp.status_code == 200
        except Exception:
            return False

    async def _fetch_loaded_model(self, url: str, kind: str) -> Optional[str]:
        """Return the first model id loaded in the live backend, or None.

        LM Studio: GET /v1/models -> {"data": [{"id": ...}]}
        Ollama:    GET /api/tags  -> {"models": [{"name": ...}]}
        """
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                resp = await c.get(url)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                if kind == "lmstudio":
                    items = data.get("data") or []
                    return items[0].get("id") if items else None
                items = data.get("models") or []
                return items[0].get("name") if items else None
        except Exception:
            return None

    @property
    def backend(self) -> LLMBackend:
        if self._backend is None:
            raise RuntimeError("No LLM backend available. Start LM Studio or Ollama.")
        return self._backend

    @property
    def name(self) -> str:
        return self._backend_name
