# LLM backends: LM Studio (GPU) + Ollama (fallback) + Gemini (cloud) + Claude (heavy agents)
from .gemini import GeminiBackend
from .anthropic import ClaudeBackend
from .hybrid_router import HybridRouter
from .tokenizer import estimate_tokens
from .base import LMStudioBackend, OllamaBackend
