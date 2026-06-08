"""
hybrid_router.py — Multi-factor LLM router with model tiering.

Decides per-request which backend and model to use based on:
1. Token budget (context length)
2. Agent policy (local-only / cloud-only / claude / auto)
3. Backend availability (graceful degradation)
4. Howard special case: uses Ollama with fine-tuned model
5. Heavy agents (Vision, Steve) → Claude API via Anthropic
6. Deep-think agents → second LM Studio model slot (DDR5, async-only)
7. Complexity-based escalation → auto agents with heavy/complex prompts
   routed to deep slot (controlled by JARVIS_AUTO_DEEP env flag)

Tier layout (LM Studio multi-model):
  Slot 1 (VRAM, fast):  DEFAULT_LOCAL_MODEL  — interactive agents, voice
  Slot 2 (DDR5, deep):  DEFAULT_DEEP_MODEL   — frigga, hephaestus, hercules
                                                + auto agents w/ heavy prompts
  Ollama (VRAM/RAM):    HOWARD_OLLAMA_MODEL  — Howard fine-tuned

Set JARVIS_DEEP_MODEL env var to override the deep-slot model name.
Set JARVIS_AUTO_DEEP=0 to disable complexity-based escalation.
"""

import logging
import os
from typing import Callable, Optional

from .base import LLMBackend, LMStudioBackend, OllamaBackend
from .router import LLMRouter
from .tokenizer import estimate_tokens

logger = logging.getLogger("jarvis.llm.hybrid")

# Token thresholds
LOCAL_MAX_TOKENS = 8_000
FLASH_MAX_TOKENS = 128_000

# H7.5 — Complexity-based escalation thresholds and keywords.
# Prompts exceeding HEAVY_TOKEN_THRESHOLD tokens OR containing any keyword
# from HEAVY_KEYWORDS are considered "heavy" and routed to the deep local slot
# for auto-policy agents (when JARVIS_AUTO_DEEP is enabled).
HEAVY_TOKEN_THRESHOLD = 2_000

# Bilingual RO/EN keyword set — matched case-insensitively as substrings.
HEAVY_KEYWORDS: frozenset[str] = frozenset({
    # Romanian
    "analiz",       # analiză / analizare / analizez
    "raionament",   # raționament (diacritic-free variant)
    "raționament",  # raționament (with diacritic)
    "strategi",     # strategie / strategică / strategic
    "corelare",     # corelare
    "planific",     # planificare / planific
    "sintez",       # sinteză / sintetizare
    "demonstr",     # demonstrare / demonstrez
    "deduc",        # deducție / deduc
    # English
    "analys",       # analysis / analyse / analyzes
    "analyz",       # analyze / analyzed
    "rationament",  # alias without diacritic
    "reasoning",
    "strategy",
    "strateg",      # strategic / strategize
    "correlat",     # correlate / correlation
    "planning",
    "synthes",      # synthesis / synthesize
    "demonstrat",   # demonstrate / demonstration
    "deduct",       # deduction / deduct
})

# Feature flag: set JARVIS_AUTO_DEEP=0 or JARVIS_AUTO_DEEP=false to disable.
# Default is ON (complexity-based escalation active).
AUTO_DEEP_ENABLED: bool = os.environ.get("JARVIS_AUTO_DEEP", "1") not in ("0", "false", "False")

# Agent policy constants
POLICY_LOCAL = "local"
POLICY_CLOUD = "cloud"
POLICY_CLAUDE = "claude"
POLICY_AUTO = "auto"

# Which agents are local-only / cloud-only / claude
LOCAL_ONLY_AGENTS = {"frigga", "ultron", "howard"}
CLOUD_ONLY_AGENTS = {"athena"}
CLAUDE_AGENTS = {"vision", "steve"}

# Agents routed to the deep-think model slot (LM Studio slot 2, DDR5).
# These accept high latency in exchange for deeper reasoning.
DEEP_THINK_AGENTS = {"frigga", "hephaestus", "hercules"}


def is_heavy_request(prompt: str, *, token_threshold: int = HEAVY_TOKEN_THRESHOLD) -> bool:
    """Return True if a prompt is considered heavy/complex.

    A prompt is heavy when:
    - Its estimated token count exceeds *token_threshold* (default HEAVY_TOKEN_THRESHOLD), OR
    - It contains at least one keyword from HEAVY_KEYWORDS (case-insensitive substring match).

    This drives complexity-based escalation in select_backend() for POLICY_AUTO agents.
    Note: get_model() is NOT escalated because it has no prompt argument.
    """
    if estimate_tokens(prompt) > token_threshold:
        return True
    lower = prompt.lower()
    return any(kw in lower for kw in HEAVY_KEYWORDS)


# Howard's dedicated Ollama model
HOWARD_OLLAMA_MODEL = "howard-lora-qwen-14b"
HOWARD_OLLAMA_URL = "http://localhost:11434"

# Agents that should use Ollama instead of LM Studio
OLLAMA_PREFERRED_AGENTS = {"howard"}

# Default model names per tier
DEFAULT_LOCAL_MODEL = "qwen3:7b"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"
# Deep-slot model: loaded by LM Studio in slot 2, runs on DDR5.
# Override via JARVIS_DEEP_MODEL env var.
DEFAULT_DEEP_MODEL = os.environ.get(
    "JARVIS_DEEP_MODEL", "deepseek-r1-distill-qwen-32b"
)


class HybridRouter(LLMRouter):
    def __init__(self, gemini_api_key: str = "", anthropic_api_key: str = ""):
        super().__init__()
        self.gemini_api_key = gemini_api_key
        self.anthropic_api_key = anthropic_api_key
        self._gemini_backend: Optional[LLMBackend] = None
        self._claude_backend: Optional[LLMBackend] = None
        self._local_available = False
        self._cloud_available = False
        self._claude_available = False
        self._ollama_backend: Optional[OllamaBackend] = None
        self._ollama_available = False
        self._local_model = DEFAULT_LOCAL_MODEL
        # Resolved in detect(): Claude model from /admin config (settings_db);
        # local model prefers the real model loaded in the live backend.
        self._claude_model = DEFAULT_CLAUDE_MODEL

    @staticmethod
    def _admin_setting(key: str, default):
        """Read an `llm` setting from /admin config (settings_db), safely."""
        try:
            from ..settings_db import get_value
            val = get_value("llm", key, default)
            return val if val else default
        except Exception:
            return default

    async def detect(self):
        await super().detect()
        self._local_available = self._backend is not None
        # Use the real model loaded in the live backend; fall back to the /admin
        # default, then the hard-coded default. ("live with the real LLM loaded".)
        self._local_model = (
            self._detected_model
            or self._admin_setting("default_model", DEFAULT_LOCAL_MODEL)
        )
        self._cloud_available = bool(self.gemini_api_key)
        if self._cloud_available:
            from .gemini import GeminiBackend
            self._gemini_backend = GeminiBackend(api_key=self.gemini_api_key)

        # Claude model is admin-configurable (/admin → llm.claude_model).
        self._claude_model = self._admin_setting("claude_model", DEFAULT_CLAUDE_MODEL)
        self._claude_available = bool(self.anthropic_api_key)
        if self._claude_available:
            from .anthropic import ClaudeBackend
            self._claude_backend = ClaudeBackend(api_key=self.anthropic_api_key, model=self._claude_model)
            logger.info(f"Claude API available ({self._claude_model})")
        else:
            logger.warning("ANTHROPIC_API_KEY not set — Claude tiering disabled, heavy agents will fall back")

        self._ollama_backend = OllamaBackend(base_url=HOWARD_OLLAMA_URL)
        self._ollama_available = await self._check(f"{HOWARD_OLLAMA_URL}/api/tags")
        if self._ollama_available:
            logger.info(f"Ollama available for Howard ({HOWARD_OLLAMA_MODEL})")
        else:
            logger.warning("Ollama not available — Howard will fall back to default backend")

    def get_agent_policy(self, agent_id: str) -> str:
        if agent_id in LOCAL_ONLY_AGENTS:
            return POLICY_LOCAL
        if agent_id in CLAUDE_AGENTS:
            return POLICY_CLAUDE
        if agent_id in CLOUD_ONLY_AGENTS:
            return POLICY_CLOUD
        return POLICY_AUTO

    def select_backend(self, agent_id: str, prompt: str) -> tuple[LLMBackend, str, str]:
        """Select backend, model, and route name for a given agent.

        Returns: (backend, model_name, route_name)
        """
        # Howard special case: use Ollama with fine-tuned model
        if agent_id == "howard":
            backend, route = self._select_howard_backend()
            model = HOWARD_OLLAMA_MODEL if self._ollama_available else self._local_model
            return backend, model, route

        # Deep-think agents: same LM Studio backend, different model slot (DDR5).
        # Only when local is available; falls through to normal routing otherwise.
        if agent_id in DEEP_THINK_AGENTS and self._local_available:
            return self._backend, DEFAULT_DEEP_MODEL, "local-deep"

        policy = self.get_agent_policy(agent_id)
        token_count = estimate_tokens(prompt)

        if policy == POLICY_LOCAL:
            if self._local_available:
                return self._backend, self._local_model, "local"
            logger.warning(f"Local backend unavailable for {agent_id} (policy=local), falling back to cloud")
            if self._cloud_available:
                return self._gemini_backend, "gemini-2.5-flash", "cloud-fallback"
            raise RuntimeError(f"No LLM backend available for {agent_id}")

        if policy == POLICY_CLAUDE:
            if self._claude_available:
                return self._claude_backend, self._claude_model, "claude"
            logger.warning(f"Claude unavailable for {agent_id}, falling back to cloud")
            if self._cloud_available:
                return self._gemini_backend, "gemini-2.5-flash", "cloud-fallback"
            if self._local_available:
                logger.warning(f"No cloud backend for {agent_id}, falling back to local")
                return self._backend, self._local_model, "local-fallback"
            raise RuntimeError(f"No LLM backend available for {agent_id}")

        if policy == POLICY_CLOUD:
            if self._cloud_available:
                return self._gemini_backend, "gemini-2.5-flash", "cloud"
            logger.warning(f"Cloud backend unavailable for {agent_id} (policy=cloud), falling back to local")
            if self._local_available:
                return self._backend, self._local_model, "local-fallback"
            raise RuntimeError(f"No LLM backend available for {agent_id}")

        # POLICY_AUTO: prefer Claude for heavy agents, local for light
        if agent_id in CLAUDE_AGENTS and self._claude_available:
            if token_count > LOCAL_MAX_TOKENS:
                return self._claude_backend, self._claude_model, "claude"
            return self._claude_backend, DEFAULT_CLAUDE_MODEL, "claude"

        # Default: local first, cloud if context too big.
        # H7.5 — Complexity escalation: heavy prompts for auto-policy agents
        # are routed to the deep local slot (DDR5) when AUTO_DEEP_ENABLED.
        # This only applies here (token_count <= LOCAL_MAX_TOKENS path) because
        # oversized prompts already spill to cloud via the branches below.
        if token_count <= LOCAL_MAX_TOKENS and self._local_available:
            if AUTO_DEEP_ENABLED and is_heavy_request(prompt):
                logger.debug(
                    "Complexity escalation: routing %s to deep slot (local-deep)", agent_id
                )
                return self._backend, DEFAULT_DEEP_MODEL, "local-deep"
            return self._backend, self._local_model, "local"
        if token_count <= FLASH_MAX_TOKENS and self._cloud_available:
            return self._gemini_backend, "gemini-2.5-flash", "cloud-flash"
        if self._cloud_available:
            return self._gemini_backend, "gemini-2.5-pro", "cloud-pro"

        if self._local_available:
            logger.warning("Cloud unavailable, falling back to local (context may be truncated)")
            return self._backend, self._local_model, "local-fallback"

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

    def set_active_model(self, model: str) -> None:
        """Switch the active local model used for `local` routing tiers.

        Updates both the auto-detected name (base class) and `_local_model`,
        which drives select_backend()/get_model() for POLICY_AUTO/local agents."""
        super().set_active_model(model)
        self._local_model = model

    def get_howard_model(self) -> str:
        return HOWARD_OLLAMA_MODEL if self._ollama_available else "google/gemma-4-26b-a4b"

    def get_model(self, agent_id: str) -> str:
        """Return the appropriate model name for this agent."""
        if agent_id == "howard":
            return HOWARD_OLLAMA_MODEL if self._ollama_available else self._local_model
        if agent_id in CLAUDE_AGENTS and self._claude_available:
            return self._claude_model
        if agent_id in DEEP_THINK_AGENTS and self._local_available:
            return DEFAULT_DEEP_MODEL
        return self._local_model

    @property
    def backend(self) -> LLMBackend:
        if not self._local_available and not self._cloud_available:
            raise RuntimeError("No LLM backend available. Start LM Studio/Ollama or configure GEMINI_API_KEY.")
        return self._claude_backend or self._backend or self._gemini_backend

    @property
    def name(self) -> str:
        parts = []
        if self._local_available:
            parts.append(self._backend_name)
        if self._ollama_available:
            parts.append("ollama-howard")
        if self._claude_available:
            parts.append("claude")
        if self._cloud_available:
            parts.append("gemini")
        return "+".join(parts) if parts else "none"

    def get_route_name(self, agent_id: str, prompt: str) -> str:
        _, _, route = self.select_backend(agent_id, prompt)
        return route

    async def aclose(self) -> None:
        """Close every backend's HTTP client pool (BUG-7).

        The base class only closes the local LM Studio / Ollama backend; the
        hybrid router also owns Gemini, Claude and the Howard/Ollama backends,
        each holding a pooled httpx.AsyncClient. Best-effort: `_close_backend`
        swallows per-backend errors so shutdown never raises.
        """
        await super().aclose()
        for attr in ("_gemini_backend", "_claude_backend", "_ollama_backend"):
            backend = getattr(self, attr, None)
            if backend is not None:
                await self._close_backend(backend)
                setattr(self, attr, None)
