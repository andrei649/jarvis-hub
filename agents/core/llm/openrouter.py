"""
openrouter.py — H20.2 OpenRouter adapter + `/model` hot-swap.

One OpenRouter key → hundreds of models behind one OpenAI-compatible endpoint,
as a drop-in `LLMBackend` over the existing hybrid router. `parse_model_command`
powers a chat/admin ``/model <id>`` hot-swap. The live network call is the host
seam; the adapter + parser are offline-testable with an injectable client.

H583 — with the openrouter profile each request also carries OpenRouter's
``provider`` object (see ``provider_routing``), steering which upstream provider may
serve it; the llm settings ``openrouter_*`` rows feed it through ``HybridRouter``.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Optional

from .base import LLMBackend, cloud_cap, strip_thinking
from .egress import llm_async_client
from .provider_routing import build_provider_block
from .tool_dialects import compatible_usage
from .tool_protocol import TokenUsage, ToolSpec, ToolTurn, parse_openai_tool_calls
from .usage_context import report_text_usage

logger = logging.getLogger("jarvis.llm.openrouter")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterBackend(LLMBackend):
    """OpenAI-compatible OpenRouter backend (bearer-auth)."""

    # OpenRouter speaks the runtime's dialect natively (Hermes absorption, wave 0.1).
    supports_tools = True

    def __init__(self, api_key: str = "", base_url: str = OPENROUTER_BASE, client=None, *, profile=None, reasoning_effort="", effort_declarations=None, provider_routing=None) -> None:
        from .provider_request import profile_with_declarations
        from .providers import DEFAULT_REGISTRY
        self.profile = profile_with_declarations(
            profile or DEFAULT_REGISTRY.get("openrouter"), effort_declarations,
        )
        self.reasoning_effort = reasoning_effort
        # H583 — OpenRouter's `provider` object (sort/only/ignore/order/
        # require_parameters/data_collection), validated once here so a bad knob
        # refuses the backend instead of widening routing. Only the openrouter
        # profile carries it: a custom OpenAI-compatible server does not know it.
        self.provider_block = None
        if provider_routing and self.profile.id == "openrouter":
            self.provider_block = build_provider_block(**provider_routing)
        self.api_key = api_key
        self.base_url = base_url
        self.client = client or llm_async_client("openrouter", base_url=base_url, timeout=120.0)

    async def aclose(self):
        try:
            await self.client.aclose()
        except Exception:  # pragma: no cover - best-effort
            pass

    def _shape(self, payload: dict) -> dict:
        """Add the per-request extras: reasoning / cache parameters, then routing."""
        from .provider_request import compatible_parameters
        payload.update(compatible_parameters(self.profile, payload["model"], self.reasoning_effort))
        if self.provider_block:
            # A fresh copy per request: the payload is handed to a transport (and to
            # test doubles) that may keep or mutate it.
            payload["provider"] = copy.deepcopy(self.provider_block)
        return payload

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
        self._shape(payload)
        try:
            resp = await self.client.post("/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            content = (data["choices"][0]["message"].get("content", "") or "")
            answer = strip_thinking(content)
            if self.profile.backend_kind == "openai-compatible":
                report_text_usage(compatible_usage(data))
            return answer
        except Exception as e:
            logger.warning("OpenRouter generate failed: %s", e)
            return "[OpenRouter error]"

    async def generate_tool_turn(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> ToolTurn:
        """One tool-enabled turn; every provider call crosses `parse_openai_tool_calls`."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = [tool.as_openai() for tool in tools]
            payload["tool_choice"] = "auto"
        self._shape(payload)
        try:
            resp = await self.client.post("/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            message = choice.get("message") or {}
            return ToolTurn(
                content=strip_thinking(message.get("content", "") or ""),
                tool_calls=parse_openai_tool_calls(message.get("tool_calls") or []),
                finish_reason=choice.get("finish_reason"),
                usage=(compatible_usage(data) if self.profile.backend_kind == "openai-compatible"
                       else TokenUsage()),
            )
        except Exception as e:
            logger.warning("OpenRouter tool turn failed: %s", e)
            return ToolTurn(content="[OpenRouter error]")


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
