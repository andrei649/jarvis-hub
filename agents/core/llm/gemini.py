"""
gemini.py — Google Gemini API backend with streaming and thinking mode.
Uses direct httpx calls (no SDK dependency). Supports Flash (fast/cheap)
and Pro (heavy) model families.
"""

import json
from typing import Callable, Optional

import httpx

from .base import LLMBackend


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=120.0)

    def _build_url(self, streaming: bool = False) -> str:
        action = "streamGenerateContent" if streaming else "generateContent"
        return f"{GEMINI_API_BASE}/models/{self.model}:{action}?key={self.api_key}"

    def _build_payload(self, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> dict:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload

    def _extract_text(self, data: dict) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        texts = [p.get("text", "") for p in parts]
        return "".join(texts)

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        actual_model = model if model and "/" not in model else self.model
        payload = self._build_payload(prompt, system, max_tokens, temperature)
        url = f"{GEMINI_API_BASE}/models/{actual_model}:generateContent?key={self.api_key}"
        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            return self._extract_text(resp.json())
        except Exception as e:
            return f"[Gemini error: {e}]"

    async def generate_stream(self, model: str, prompt: str, system: str = "",
                              max_tokens: int = 1024, temperature: float = 0.7,
                              on_token: Callable[[str], None] = None) -> str:
        actual_model = model if model and "/" not in model else self.model
        payload = self._build_payload(prompt, system, max_tokens, temperature)
        url = f"{GEMINI_API_BASE}/models/{actual_model}:streamGenerateContent?key={self.api_key}&alt=sse"
        full = ""
        try:
            async with self.client.stream("POST", url, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                            text = self._extract_text(data)
                            if text:
                                full += text
                                if on_token:
                                    on_token(text)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            full = f"[Gemini stream error: {e}]"
        return full

    async def close(self):
        await self.client.aclose()
