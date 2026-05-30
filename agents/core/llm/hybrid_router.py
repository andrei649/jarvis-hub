"""
hybrid_router.py — Multi-factor LLM router.

Decides per-request which backend to use based on:
1. Token budget (context length)
2. Agent policy (local-only / cloud-only / auto)
3. Backend availability (graceful degradation)
"""

import logging
from typing import Callable, Optional

from .base import LLMBackend
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
LOCAL_ONLY_AGENTS = {"frigga", "ultron"}
CLOUD_ONLY_AGENTS = {"vision", "athena"}


class HybridRouter(LLMRouter):
    def __init__(self, gemini_api_key: str = ""):
        super().__init__()
        self.gemini_api_key = gemini_api_key
        self._gemini_backend: Optional[LLMBackend] = None
        self._local_available = False
        self._cloud_available = False

    async def detect(self):
        await super().detect()
        self._local_available = self._backend is not None
        self._cloud_available = bool(self.gemini_api_key)
        if self._cloud_available:
            from .gemini import GeminiBackend
            self._gemini_backend = GeminiBackend(api_key=self.gemini_api_key)

    def get_agent_policy(self, agent_id: str) -> str:
        if agent_id in LOCAL_ONLY_AGENTS:
            return POLICY_LOCAL
        if agent_id in CLOUD_ONLY_AGENTS:
            return POLICY_CLOUD
        return POLICY_AUTO

    def select_backend(self, agent_id: str, prompt: str) -> tuple[LLMBackend, str]:
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
        if self._cloud_available:
            parts.append("gemini")
        return "+".join(parts) if parts else "none"

    def get_route_name(self, agent_id: str, prompt: str) -> str:
        _, route = self.select_backend(agent_id, prompt)
        return route
