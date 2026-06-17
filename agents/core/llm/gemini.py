"""
gemini.py — Google Gemini API backend with streaming and thinking mode.
Uses direct httpx calls (no SDK dependency). Supports Flash (fast/cheap)
and Pro (heavy) model families.
"""

import json
from typing import Callable

import httpx

from .auth_rotation import is_rotatable_status
from .base import LLMBackend, cloud_cap


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", auth_pool=None):
        self.api_key = api_key
        self.model = model
        # H12.20 — optional multi-key auth pool (see ClaudeBackend). None → unchanged.
        self.auth_pool = auth_pool
        self.client = httpx.AsyncClient(timeout=120.0)
        self._use_cache = ""

    def _active_key(self) -> str:
        if self.auth_pool is not None:
            return self.auth_pool.current_key() or self.api_key
        return self.api_key

    def _build_url(self, streaming: bool = False) -> str:
        action = "streamGenerateContent" if streaming else "generateContent"
        return f"{GEMINI_API_BASE}/models/{self.model}:{action}?key={self._active_key()}"

    def _build_payload(self, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> dict:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": cloud_cap(max_tokens),
                "temperature": temperature,
            },
        }
        use_cache = getattr(self, '_use_cache', '')
        if use_cache:
            payload["cachedContent"] = use_cache
        elif system:
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
        # Try each healthy auth profile once; fail over on rotatable errors (H12.20).
        attempts = self.auth_pool.size if self.auth_pool else 1
        last_err = ""
        for _ in range(max(1, attempts)):
            key = self._active_key()
            url = f"{GEMINI_API_BASE}/models/{actual_model}:generateContent?key={key}"
            try:
                resp = await self.client.post(url, json=payload)
                resp.raise_for_status()
                if self.auth_pool is not None:
                    self.auth_pool.report_success(key)
                return self._extract_text(resp.json())
            except httpx.HTTPStatusError as e:
                last_err = str(e)
                if self.auth_pool is not None and is_rotatable_status(e.response.status_code) and self.auth_pool.size > 1:
                    self.auth_pool.report_failure(key)
                    continue   # fail over to the next key
                return f"[Gemini error: {e}]"
            except Exception as e:
                return f"[Gemini error: {e}]"
        return f"[Gemini error: all auth profiles exhausted: {last_err}]"

    async def generate_stream(self, model: str, prompt: str, system: str = "",
                              max_tokens: int = 1024, temperature: float = 0.7,
                              on_token: Callable[[str], None] = None) -> str:
        actual_model = model if model and "/" not in model else self.model
        payload = self._build_payload(prompt, system, max_tokens, temperature)
        stream_key = self._active_key()
        url = f"{GEMINI_API_BASE}/models/{actual_model}:streamGenerateContent?key={stream_key}&alt=sse"
        full = ""
        try:
            async with self.client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
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
        except httpx.HTTPStatusError as e:
            # Rotatable error → cool this key down so the next call fails over (H12.20).
            if self.auth_pool is not None and is_rotatable_status(e.response.status_code):
                self.auth_pool.report_failure(stream_key)
            full = f"[Gemini stream error: {e}]"
        except Exception as e:
            full = f"[Gemini stream error: {e}]"
        return full

    async def close(self):
        await self.client.aclose()
