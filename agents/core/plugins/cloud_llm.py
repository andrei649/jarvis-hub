"""
cloud_llm.py — Cloud LLM fallback plugin.

Routes to Anthropic Claude or OpenAI GPT when local models
are insufficient for heavy reasoning tasks.
Only enabled for approved agents: jarvis, athena, stark, vision, veronica.
"""

import logging

from ..http_client import PluginHTTPClient, PluginTimeouts
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.cloud_llm")

APPROVED_AGENTS = ["jarvis", "athena", "stark", "vision", "veronica"]


class CloudLLMPlugin:
    def __init__(self, anthropic_key: str = "", openai_key: str = "", gemini_key: str = ""):
        self.anthropic_key = anthropic_key
        self.openai_key = openai_key
        self.gemini_key = gemini_key
        # Cloud LLM calls can be slow — use extended read timeout
        self.client = PluginHTTPClient.for_plugin(
            "cloud-llm",
            timeouts=PluginTimeouts(connect=5.0, read=120.0, total=120.0),
        )
        self._prefer = "anthropic" if anthropic_key else "gemini" if gemini_key else "openai" if openai_key else None

    async def generate(self, prompt: str, system: str = "",
                       model: str = "", agent_id: str = "",
                       max_tokens: int = 2048) -> str:
        if agent_id and agent_id not in APPROVED_AGENTS:
            logger.warning(f"Agent {agent_id} not approved for cloud LLM")
            return "[Cloud LLM denied: agent not approved]"

        try:
            if self._prefer == "anthropic":
                return await self._call_anthropic(prompt, system, model or "claude-sonnet-4-20250514", max_tokens)
            elif self._prefer == "openai":
                return await self._call_openai(prompt, system, model or "gpt-4o", max_tokens)
            elif self._prefer == "gemini":
                return await self._call_gemini(prompt, system, model or "gemini-2.5-flash", max_tokens)
            else:
                return "[Cloud LLM unavailable: no API key configured]"
        except Exception as e:
            logger.error(f"Cloud LLM error after retries: {e}")
            return f"[Cloud LLM error: {e}]"

    @resilient_call(
        max_retries=2,
        timeout=30.0,
        backoff_base=1.0,
        backoff_max=5.0,
        circuit_breaker_key="plugin:anthropic",
        circuit_breaker_threshold=3,
        metrics_agent_id="cloud-llm",
        metrics_backend="anthropic",
    )
    async def _call_anthropic(self, prompt: str, system: str,
                              model: str, max_tokens: int) -> str:
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

    @resilient_call(
        max_retries=2,
        timeout=30.0,
        backoff_base=1.0,
        backoff_max=5.0,
        circuit_breaker_key="plugin:gemini",
        circuit_breaker_threshold=3,
        metrics_agent_id="cloud-llm",
        metrics_backend="gemini",
    )
    async def _call_gemini(self, prompt: str, system: str,
                            model: str, max_tokens: int) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system}]} if system else None,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if not payload["systemInstruction"]:
            del payload["systemInstruction"]
        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        return ""

    @resilient_call(
        max_retries=2,
        timeout=30.0,
        backoff_base=1.0,
        backoff_max=5.0,
        circuit_breaker_key="plugin:openai",
        circuit_breaker_threshold=3,
        metrics_agent_id="cloud-llm",
        metrics_backend="openai",
    )
    async def _call_openai(self, prompt: str, system: str,
                           model: str, max_tokens: int) -> str:
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

    @property
    def available(self) -> bool:
        return bool(self.anthropic_key or self.openai_key or self.gemini_key)

    async def close(self):
        await self.client.close()
