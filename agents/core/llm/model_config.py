"""Shared LLM model-name defaults and env overrides.

AUD-14 wants model names to live in one place instead of being scattered
through routing code. This module is intentionally tiny and side-effect-free:
it reads overrides at call time through env_config and never probes backends.
"""

from __future__ import annotations

from ..env_config import env_str

DEFAULT_LOCAL_MODEL = "qwen3:7b"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"
DEFAULT_GEMINI_FLASH_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_PRO_MODEL = "gemini-2.5-pro"
DEFAULT_DEEP_MODEL = "deepseek-r1-distill-qwen-32b"

HOWARD_OLLAMA_MODEL = "howard-lora-qwen-14b"
HOWARD_OLLAMA_URL = "http://localhost:11434"
HOWARD_FALLBACK_MODEL = "google/gemma-4-26b-a4b"


def deep_model_name() -> str:
    """Configured deep-slot model, falling back to the shipped default."""
    return env_str("JARVIS_DEEP_MODEL", "").strip() or DEFAULT_DEEP_MODEL


def deep_model_override_configured() -> bool:
    """True when the owner explicitly pinned the deep-slot model via env."""
    return bool(env_str("JARVIS_DEEP_MODEL", "").strip())
