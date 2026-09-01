"""
openrouter.py — H20.2 OpenRouter adapter + `/model` hot-swap.

One OpenRouter key → hundreds of models behind one OpenAI-compatible endpoint,
as a drop-in `LLMBackend` over the existing hybrid router. `parse_model_command`
powers a chat/admin ``/model <id>`` hot-swap. The live network call is the host
seam; the adapter + parser are offline-testable with an injectable client.
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import LLMBackend, cloud_cap, strip_thinking
from .egress import llm_async_client

logger = logging.getLogger("jarvis.llm.openrouter")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterBackend(LLMBackend):
    """OpenAI-compatible OpenRouter backend (bearer-auth)."""

    def __init__(self, api_key: str = "", base_url: str = OPENROUTER_BASE, client=None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.client = client or llm_async_client("openrouter", base_url=base_url, timeout=120.0)

    async def aclose(self):
        try:
            await self.client.aclose()
        except Exception:  # pragma: no cover - best-effort
            pass

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "max_tokens": cloud_cap(max_tokens), "temperature": temperature, "stream": False,
        }
        try:
            resp = await self.client.post("/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            content = (data["choices"][0]["message"].get("content", "") or "")
            return strip_thinking(content)
        except Exception as e:
            logger.warning("OpenRouter generate failed: %s", e)
            return "[OpenRouter error]"


def parse_model_command(text: str) -> Optional[dict]:
    """Parse a hot-swap command.

    ``/model <id>`` → ``{"model": id}``; bare ``/model`` → ``{"list": True}``;
    anything else → ``None`` (not a model command).
    """
    t = (text or "").strip()
    if not t.lower().startswith("/model"):
        return None
    rest = t[len("/model"):].strip()
    if not rest:
        return {"list": True}
    return {"model": rest.split()[0]}
