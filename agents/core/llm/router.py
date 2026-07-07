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
        # O26-P0.5 (F5): every model id the live backend reported as servable,
        # refreshed by the same fetches that detect the active model. Routing
        # decisions that name a SPECIFIC model (the deep slot) consult this so
        # a one-model box is never routed to a model that isn't there.
        self._served_models: set = set()
        # /admin → llm.backend_type / llm.lm_studio_url / llm.ollama_url. Resolved
        # from settings before detect() (subclasses set these); defaults preserve
        # the original hardcoded behavior.
        self.backend_type: str = "auto"           # auto | lm-studio | ollama
        self.lm_studio_url: str = "http://localhost:1234"
        self.ollama_url: str = "http://localhost:11434"

    async def detect(self):
        """Try LM Studio (GPU) first, fall back to Ollama.

        On success, also capture the model actually loaded in the backend so the
        system uses the real loaded model rather than a hard-coded name.

        Honors `backend_type` (/admin): "lm-studio"/"ollama" pin a single backend;
        "auto" (default) probes LM Studio then Ollama. URLs come from `lm_studio_url`
        / `ollama_url`."""
        await self._close_backend(self._backend)  # BUG-7: close the prior backend's pool before re-detect
        self._backend = None
        self._detected_model = None
        lm_url = (self.lm_studio_url or "http://localhost:1234").rstrip("/")
        ol_url = (self.ollama_url or "http://localhost:11434").rstrip("/")
        bt = self.backend_type or "auto"
        if bt in ("auto", "lm-studio") and await self._check(f"{lm_url}/v1/models"):
            self._backend = LMStudioBackend(base_url=lm_url)
            self._backend_name = "lm-studio"
            self._detected_model = await self._fetch_loaded_model(
                f"{lm_url}/v1/models", "lmstudio")
            logger.info("LLM backend online: lm-studio (%s), loaded model=%s",
                        lm_url, self._detected_model or "unknown")
            return
        if bt in ("auto", "ollama") and await self._check(f"{ol_url}/api/tags"):
            self._backend = OllamaBackend(base_url=ol_url)
            self._backend_name = "ollama"
            self._detected_model = await self._fetch_loaded_model(
                f"{ol_url}/api/tags", "ollama")
            logger.info("LLM backend online: ollama (%s), loaded model=%s",
                        ol_url, self._detected_model or "unknown")
            return
        self._backend_name = "none"
        logger.warning("No LLM backend detected (backend_type=%s) — start LM Studio (%s) or Ollama (%s)",
                       bt, lm_url, ol_url)

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
                    self._served_models = {
                        i.get("id") for i in items if i.get("id")}  # O26-P0.5
                    return items[0].get("id") if items else None
                items = data.get("models") or []
                self._served_models = {
                    i.get("name") for i in items if i.get("name")}  # O26-P0.5
                return items[0].get("name") if items else None
        except Exception:
            return None

    @property
    def backend(self) -> LLMBackend:
        if self._backend is None:
            raise RuntimeError("No LLM backend available. Start LM Studio or Ollama.")
        return self._backend

    @property
    def local_backend(self) -> LLMBackend:
        """The detected LOCAL backend only — fail-closed, never a cloud fallback.

        Unlike ``backend`` (which HybridRouter overrides to prefer cloud when
        keys are configured), this accessor is the strict-local contract used by
        privacy-sensitive paths (e.g. the H20 background review, which embeds
        raw conversation content): no local backend ⇒ RuntimeError ⇒ the caller
        skips, nothing egresses."""
        if self._backend is None:
            raise RuntimeError("No local LLM backend available (strict-local path).")
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
            lm_url = (self.lm_studio_url or "http://localhost:1234").rstrip("/")
            model = await self._fetch_loaded_model(f"{lm_url}/v1/models", "lmstudio")
        elif self._backend_name == "ollama":
            ol_url = (self.ollama_url or "http://localhost:11434").rstrip("/")
            model = await self._fetch_loaded_model(f"{ol_url}/api/tags", "ollama")
        else:
            model = None
        if model:
            self.set_active_model(model)
            logger.info("Active model refreshed: %s", model)
        return model

    async def warm_up(self) -> bool:
        """Preload the detected local model so the first turn skips cold-load.

        Sends a minimal generation (and, on Ollama, pins the model resident) to
        the live local backend for the model auto-detected in detect(). Cloud
        backends need no warming. Best-effort: returns False (never raises) when
        no local backend/model is up, so it is safe to fire-and-forget at
        startup."""
        if self._backend is None or not self._detected_model:
            return False
        try:
            ok = await self._backend.warm_up(self._detected_model)
            if ok:
                logger.info("Warmed up local model: %s", self._detected_model)
            else:
                logger.debug("Warm-up of %s did not complete", self._detected_model)
            return ok
        except Exception:
            return False

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
