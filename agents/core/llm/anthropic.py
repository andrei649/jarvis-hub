"""
anthropic.py — Anthropic Claude API backend with streaming support.
Uses Anthropic Messages API directly via httpx (no SDK dependency).
"""

import json
from typing import Callable

import httpx

from .auth_rotation import is_rotatable_status
from .base import LLMBackend, cloud_cap
from .model_config import DEFAULT_CLAUDE_MODEL

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = DEFAULT_CLAUDE_MODEL, auth_pool=None):
        self.api_key = api_key
        self.model = model
        # H12.20 — optional multi-key auth pool. When set, the active key is drawn
        # from the pool and a rotatable error (401/403/429) fails over to the next
        # healthy key. None → single-key behavior, unchanged.
        self.auth_pool = auth_pool
        self.client = httpx.AsyncClient(timeout=120.0)

    def _active_key(self) -> str:
        if self.auth_pool is not None:
            return self.auth_pool.current_key() or self.api_key
        return self.api_key

    def _headers(self) -> dict:
        return {
            "x-api-key": self._active_key(),
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
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "system": system,
            "messages": self._build_messages(prompt, system),
        }
        # Try each healthy auth profile once; fail over on rotatable errors (H12.20).
        attempts = self.auth_pool.size if self.auth_pool else 1
        last_err = ""
        for _ in range(max(1, attempts)):
            key = self._active_key()
            try:
                resp = await self.client.post(
                    f"{ANTHROPIC_API_BASE}/messages",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                if self.auth_pool is not None:
                    self.auth_pool.report_success(key)
                if data.get("content"):
                    return self._finalize_cloud("".join(
                        block.get("text", "")
                        for block in data["content"]
                        if block.get("type") == "text"
                    ))
                return ""
            except httpx.HTTPStatusError as e:
                last_err = str(e)
                status = e.response.status_code
                if self.auth_pool is not None and is_rotatable_status(status) and self.auth_pool.size > 1:
                    self.auth_pool.report_failure(key)
                    continue   # fail over to the next key
                return f"[Claude API error: {e}]"
            except Exception as e:
                return f"[Claude API error: {e}]"
        return f"[Claude API error: all auth profiles exhausted: {last_err}]"

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        model = model or self.model
        payload = {
            "model": model,
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "system": system,
            "messages": self._build_messages(prompt, system),
            "stream": True,
        }
        full = ""
        stream_key = self._active_key()
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
        except httpx.HTTPStatusError as e:
            # Rotatable error → cool this key down so the next call fails over (H12.20).
            if self.auth_pool is not None and is_rotatable_status(e.response.status_code):
                self.auth_pool.report_failure(stream_key)
            full = f"[Claude API stream error: {e}]"
        except Exception as e:
            full = f"[Claude API stream error: {e}]"
        return self._finalize_cloud(full)

    async def aclose(self):
        """Close the pooled httpx client (BUG-7)."""
        await self.client.aclose()
