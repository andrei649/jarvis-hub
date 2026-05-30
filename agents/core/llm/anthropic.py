"""
anthropic.py — Anthropic Claude API backend with streaming support.
Uses Anthropic Messages API directly via httpx (no SDK dependency).
"""

import json
from typing import Callable, Optional

import httpx

from .base import LLMBackend

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=120.0)

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _build_messages(self, prompt: str, system: str = "") -> list[dict]:
        return [{"role": "user", "content": prompt}]

    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        model = model or self.model
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": self._build_messages(prompt, system),
        }
        try:
            resp = await self.client.post(
                f"{ANTHROPIC_API_BASE}/messages",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("content"):
                return "".join(
                    block.get("text", "")
                    for block in data["content"]
                    if block.get("type") == "text"
                )
            return ""
        except Exception as e:
            return f"[Claude API error: {e}]"

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        model = model or self.model
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": self._build_messages(prompt, system),
            "stream": True,
        }
        full = ""
        try:
            async with self.client.stream(
                "POST",
                f"{ANTHROPIC_API_BASE}/messages",
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                            event_type = data.get("type", "")
                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                text = delta.get("text", "")
                                if text:
                                    full += text
                                    if on_token:
                                        on_token(text)
                            elif event_type == "message_stop":
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            full = f"[Claude API stream error: {e}]"
        return full
