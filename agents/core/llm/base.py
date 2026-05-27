"""
base.py — Abstract LLM backend interface with streaming support.
Supports LM Studio (OpenAI-compatible API) and Ollama.
"""

import json
from abc import ABC, abstractmethod
from typing import Callable, Optional

import httpx


class LLMBackend(ABC):
    @abstractmethod
    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        ...

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        full = await self.generate(model, prompt, system, max_tokens, temperature)
        if on_token:
            on_token(full)
        return full


class LMStudioBackend(LLMBackend):
    """LM Studio local server (GPU-accelerated on Windows)."""

    def __init__(self, base_url: str = "http://localhost:1234"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=300.0)

    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            resp = await self.client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content", "")
            if not content:
                content = msg.get("reasoning_content", "")
            return content
        except Exception as e:
            return f"[LM Studio error: {e}]"

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        full = ""
        try:
            async with self.client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "") or delta.get("reasoning_content", "")
                            if content:
                                full += content
                                if on_token:
                                    on_token(content)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            full = f"[LM Studio stream error: {e}]"
        return full


class OllamaBackend(LLMBackend):
    """Ollama local server."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        try:
            resp = await self.client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
        except Exception as e:
            return f"[Ollama error: {e}]"

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        full = ""
        try:
            async with self.client.stream("POST", "/api/generate", json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            content = data.get("response", "")
                            if content:
                                full += content
                                if on_token:
                                    on_token(content)
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            full = f"[Ollama stream error: {e}]"
        return full
