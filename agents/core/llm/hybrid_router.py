"""
hybrid_router.py — Multi-factor LLM router.

Decides per-request which backend to use based on:
1. Token budget (context length)
2. Agent policy (local-only / cloud-only / auto)
3. Backend availability (graceful degradation)
4. Howard special case: uses Ollama with fine-tuned model

Howard's fine-tuned model runs on Ollama alongside LM Studio.
All other agents use LM Studio (Gemma 4).
"""

import logging
from typing import Callable, Optional

from .base import LLMBackend, LMStudioBackend, OllamaBackend
from .router import LLMRouter
from .tokenizer import estimate_tokens

logger = logging.getLogger("jarvis.llm.hybrid")

# Token thresholds
LOCAL_MAX_TOKENS = 8_000
FLASH_MAX_TOKENS = 128_000

# Agent policy constants
POLICY_LOCAL = "local"
POLICY_CLOUD = "cloud"
POLICY_AUTO = "auto"

# Which agents are local-only / cloud-only
LOCAL_ONLY_AGENTS = {"frigga", "ultron", "howard"}
CLOUD_ONLY_AGENTS = {"vision", "athena"}

# Howard's dedicated Ollama model
HOWARD_OLLAMA_MODEL = "howard-lora-qwen-14b"
HOWARD_OLLAMA_URL = "http://localhost:11434"

# Agents that should use Ollama instead of LM Studio
OLLAMA_PREFERRED_AGENTS = {"howard"}


class HybridRouter(LLMRouter):
    def __init__(self, gemini_api_key: str = ""):
        super().__init__()
        self.gemini_api_key = gemini_api_key
        self._gemini_backend: Optional[LLMBackend] = None
        self._local_available = False
        self._cloud_available = False
        self._ollama_backend: Optional[OllamaBackend] = None
        self._ollama_available = False

    async def detect(self):
        await super().detect()
        self._local_available = self._backend is not None
        self._cloud_available = bool(self.gemini_api_key)
        if self._cloud_available:
            from .gemini import GeminiBackend
            self._gemini_backend = GeminiBackend(api_key=self.gemini_api_key)

        self._ollama_backend = OllamaBackend(base_url=HOWARD_OLLAMA_URL)
        self._ollama_available = await self._check(f"{HOWARD_OLLAMA_URL}/api/tags")
        if self._ollama_available:
            logger.info(f"Ollama available for Howard ({HOWARD_OLLAMA_MODEL})")
        else:
            logger.warning("Ollama not available — Howard will fall back to default backend")

    def get_agent_policy(self, agent_id: str) -> str:
        if agent_id in LOCAL_ONLY_AGENTS:
            return POLICY_LOCAL
        if agent_id in CLOUD_ONLY_AGENTS:
            return POLICY_CLOUD
        return POLICY_AUTO

    def select_backend(self, agent_id: str, prompt: str) -> tuple[LLMBackend, str]:
        # Howard special case: use Ollama with fine-tuned model
        if agent_id == "howard":
            return self._select_howard_backend()

        policy = self.get_agent_policy(agent_id)
        token_count = estimate_tokens(prompt)

        if policy == POLICY_LOCAL:
            if self._local_available:
                return self._backend, "local"
            logger.warning(f"Local backend unavailable for {agent_id} (policy=local), falling back to cloud")
            if self._cloud_available:
                return self._gemini_backend, "cloud-fallback"
            raise RuntimeError(f"No LLM backend available for {agent_id}")

        if policy == POLICY_CLOUD:
            if self._cloud_available:
                return self._gemini_backend, "cloud"
            logger.warning(f"Cloud backend unavailable for {agent_id} (policy=cloud), falling back to local")
            if self._local_available:
                return self._backend, "local-fallback"
            raise RuntimeError(f"No LLM backend available for {agent_id}")

        # POLICY_AUTO
        if token_count <= LOCAL_MAX_TOKENS and self._local_available:
            return self._backend, "local"
        if token_count <= FLASH_MAX_TOKENS and self._cloud_available:
            return self._gemini_backend, "cloud-flash"
        if self._cloud_available:
            return self._gemini_backend, "cloud-pro"

        if self._local_available:
            logger.warning("Cloud unavailable, falling back to local (context may be truncated)")
            return self._backend, "local-fallback"

        raise RuntimeError("No LLM backend available")

    def _select_howard_backend(self) -> tuple[LLMBackend, str]:
        """Select backend for Howard: prefer Ollama with fine-tuned model,
        fall back to main LM Studio backend."""
        if self._ollama_available:
            return self._ollama_backend, "ollama-howard"
        if self._local_available:
            logger.warning("Ollama unavailable for Howard, falling back to LM Studio")
            return self._backend, "local-fallback"
        if self._cloud_available:
            logger.warning("All local backends unavailable for Howard, falling back to cloud")
            return self._gemini_backend, "cloud-fallback"
        raise RuntimeError(f"No LLM backend available for howard")

    def get_howard_model(self) -> str:
        return HOWARD_OLLAMA_MODEL if self._ollama_available else "google/gemma-4-26b-a4b"

    @property
    def backend(self) -> LLMBackend:
        if not self._local_available and not self._cloud_available:
            raise RuntimeError("No LLM backend available. Start LM Studio/Ollama or configure GEMINI_API_KEY.")
        return self._backend or self._gemini_backend

    @property
    def name(self) -> str:
        parts = []
        if self._local_available:
            parts.append(self._backend_name)
        if self._ollama_available:
            parts.append("ollama-howard")
        if self._cloud_available:
            parts.append("gemini")
        return "+".join(parts) if parts else "none"

    def get_route_name(self, agent_id: str, prompt: str) -> str:
        _, route = self.select_backend(agent_id, prompt)
        return route
