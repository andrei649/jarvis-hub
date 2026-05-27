"""
cloud_llm.py — Cloud LLM fallback plugin.

Routes to Anthropic Claude or OpenAI GPT when local models
are insufficient for heavy reasoning tasks.
Only enabled for approved agents: jarvis, athena, stark, vision, veronica.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger("jarvis.plugins.cloud_llm")

APPROVED_AGENTS = ["jarvis", "athena", "stark", "vision", "veronica"]


class CloudLLMPlugin:
    def __init__(self, anthropic_key: str = "", openai_key: str = ""):
        self.anthropic_key = anthropic_key
        self.openai_key = openai_key
        self.client = httpx.AsyncClient(timeout=120.0)
        self._prefer = "anthropic" if anthropic_key else "openai" if openai_key else None

    async def generate(self, prompt: str, system: str = "",
                       model: str = "", agent_id: str = "",
                       max_tokens: int = 2048) -> str:
        if agent_id and agent_id not in APPROVED_AGENTS:
            logger.warning(f"Agent {agent_id} not approved for cloud LLM")
            return "[Cloud LLM denied: agent not approved]"

        if self._prefer == "anthropic":
            return await self._call_anthropic(prompt, system, model or "claude-sonnet-4-20250514", max_tokens)
        elif self._prefer == "openai":
            return await self._call_openai(prompt, system, model or "gpt-4o", max_tokens)
        else:
            return "[Cloud LLM unavailable: no API key configured]"

    async def _call_anthropic(self, prompt: str, system: str,
                              model: str, max_tokens: int) -> str:
        try:
            resp = await self.client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]
        except Exception as e:
            logger.error(f"Anthropic error: {e}")
            return f"[Anthropic error: {e}]"

    async def _call_openai(self, prompt: str, system: str,
                           model: str, max_tokens: int) -> str:
        try:
            resp = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            return f"[OpenAI error: {e}]"

    @property
    def available(self) -> bool:
        return bool(self.anthropic_key or self.openai_key)

    async def close(self):
        await self.client.aclose()
