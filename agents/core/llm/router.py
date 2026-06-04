"""
router.py — Auto-detect which LLM backend is available.
Tries LM Studio first (GPU), falls back to Ollama (CPU).
"""

import logging
from typing import Optional

import httpx
from .base import LLMBackend, LMStudioBackend, OllamaBackend

logger = logging.getLogger("jarvis.llm.router")


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
        await self._close_backend(self._backend)  # BUG-7: close the prior backend's pool before re-detect
        self._backend = None
        self._detected_model = None
        if await self._check("http://localhost:1234/v1/models"):
            self._backend = LMStudioBackend()
            self._backend_name = "lm-studio"
            self._detected_model = await self._fetch_loaded_model(
                "http://localhost:1234/v1/models", "lmstudio")
            logger.info("LLM backend online: lm-studio (:1234), loaded model=%s",
                        self._detected_model or "unknown")
            return
        if await self._check("http://localhost:11434/api/tags"):
            self._backend = OllamaBackend()
            self._backend_name = "ollama"
            self._detected_model = await self._fetch_loaded_model(
                "http://localhost:11434/api/tags", "ollama")
            logger.info("LLM backend online: ollama (:11434), loaded model=%s",
                        self._detected_model or "unknown")
            return
        self._backend_name = "none"
        logger.warning("No LLM backend detected — start LM Studio (:1234) or Ollama (:11434)")

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

    @property
    def active_model(self) -> Optional[str]:
        """Name of the local model currently selected as active, if any."""
        return self._detected_model

    def set_active_model(self, model: str) -> None:
        """Override the active local model name on the live router.

        Subclasses that track a separate `_local_model` should override this to
        keep their routing state in sync."""
        self._detected_model = model

    async def refresh_active_model(self) -> Optional[str]:
        """Re-fetch the model currently loaded in the live backend and adopt it.

        Called after a model is loaded/unloaded (e.g. via LMStudioController) so
        routing and the runtime state agents report reflect the real loaded
        model immediately, without a restart. No-op if no backend is up."""
        if self._backend is None:
            return None
        if self._backend_name == "lm-studio":
            model = await self._fetch_loaded_model("http://localhost:1234/v1/models", "lmstudio")
        elif self._backend_name == "ollama":
            model = await self._fetch_loaded_model("http://localhost:11434/api/tags", "ollama")
        else:
            model = None
        if model:
            self.set_active_model(model)
            logger.info("Active model refreshed: %s", model)
        return model

    async def aclose(self) -> None:
        """Close the active backend's HTTP client pool (BUG-7)."""
        await self._close_backend(self._backend)
        self._backend = None

    @staticmethod
    async def _close_backend(backend) -> None:
        if backend is None:
            return
        closer = getattr(backend, "aclose", None) or getattr(backend, "close", None)
        if closer:
            try:
                await closer()
            except Exception:
                # Best-effort close — the backend is being discarded anyway.
                pass
