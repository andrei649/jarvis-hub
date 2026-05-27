"""
router.py — Auto-detect which LLM backend is available.
Tries LM Studio first (GPU), falls back to Ollama (CPU).
"""

import httpx
from .base import LLMBackend, LMStudioBackend, OllamaBackend


class LLMRouter:
    """Auto-detect and route to the best available LLM backend."""

    def __init__(self):
        self._backend: LLMBackend = None
        self._backend_name: str = "none"

    async def detect(self):
        """Try LM Studio (GPU) first, fall back to Ollama."""
        if await self._check("http://localhost:1234/v1/models"):
            self._backend = LMStudioBackend()
            self._backend_name = "lm-studio"
            return
        if await self._check("http://localhost:11434/api/tags"):
            self._backend = OllamaBackend()
            self._backend_name = "ollama"
            return
        self._backend_name = "none"

    async def _check(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                resp = await c.get(url)
                return resp.status_code == 200
        except Exception:
            return False

    @property
    def backend(self) -> LLMBackend:
        if self._backend is None:
            raise RuntimeError("No LLM backend available. Start LM Studio or Ollama.")
        return self._backend

    @property
    def name(self) -> str:
        return self._backend_name
