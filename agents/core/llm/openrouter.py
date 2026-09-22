"""
openrouter.py — H20.2 OpenRouter adapter + `/model` hot-swap.

One OpenRouter key → hundreds of models behind one OpenAI-compatible endpoint,
as a drop-in `LLMBackend` over the existing hybrid router. `parse_model_command`
powers a chat/admin ``/model <id>`` hot-swap. The live network call is the host
seam; the adapter + parser are offline-testable with an injectable client.

H583 — with the openrouter profile each request also carries OpenRouter's
``provider`` object (see ``provider_routing``), steering which upstream provider may
serve it. ``HybridRouter`` hands the backend a reader of the llm settings
``openrouter_*`` rows, and the object is rebuilt from it before **every** request:
an owner's change through the HUD or ``nerva config set`` governs the next request,
not the next ``detect()``. A row that no longer validates refuses that request —
nothing is sent — rather than dropping the knob and widening routing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from ..log_safe import log_safe
from .base import LLMBackend, cloud_cap, strip_thinking
from .egress import llm_async_client
from .provider_routing import SETTINGS_KEYS, build_provider_block
from .tool_dialects import compatible_usage
from .tool_protocol import TokenUsage, ToolSpec, ToolTurn, parse_openai_tool_calls
from .usage_context import report_text_usage

logger = logging.getLogger("jarvis.llm.openrouter")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_ERROR = "[OpenRouter error]"
# OpenRouter answers "no upstream provider satisfies this request" with a 404 (data
# policy, allow-list, required parameters) or a 400 (a routing object it rejects).
_ROUTING_REFUSAL_STATUSES = (400, 404)
_ROUTING_SETTINGS = " / ".join(
    f"llm.{SETTINGS_KEYS[name]}"
    for name in ("data_collection", "only", "ignore", "require_parameters")
)


class _RoutingUnavailable(Exception):
    """The provider object for this request could not be built; nothing is sent."""


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
        # require_parameters/data_collection). `provider_routing` is the knob dict,
        # or a zero-argument reader returning it (the router passes one over the
        # llm settings rows) that is re-read before every request. Validated here as
        # well, so a bad knob refuses the backend instead of widening routing. Only
        # the openrouter profile carries it: a custom OpenAI-compatible server does
        # not know the object.
        self._provider_routing = provider_routing if self.profile.id == "openrouter" else None
        self._current_block()  # raises ProviderRoutingInvalid on a bad knob
        self.api_key = api_key
        self.base_url = base_url
        self.client = client or llm_async_client("openrouter", base_url=base_url, timeout=120.0)

    @staticmethod
    def _block_from(knobs) -> dict | None:
        # A new dict (and new lists) per call, so a transport or test double that
        # keeps or mutates one request's payload cannot reach the next one's.
        return build_provider_block(**knobs) if knobs else None

    def _current_block(self) -> dict | None:
        source = self._provider_routing
        return self._block_from(source() if callable(source) else source)

    @property
    def provider_block(self) -> dict | None:
        """The ``provider`` object the next request would carry; ``None`` = none sent.

        Raises ``ProviderRoutingInvalid`` when a knob is invalid.
        """
        return self._current_block()

    async def _provider_block_now(self) -> dict | None:
        """Resolve the object for one request, off the event loop when it reads settings.

        Fails closed: when the knobs cannot be read or no longer validate, raise
        ``_RoutingUnavailable`` so the caller sends nothing — never the request
        without the owner's constraints.
        """
        source = self._provider_routing
        if source is None:
            return None
        try:
            knobs = await asyncio.to_thread(source) if callable(source) else source
            return self._block_from(knobs)
        except Exception as exc:
            logger.error(
                "OpenRouter request refused before sending — provider routing (llm.openrouter_*) "
                "is unusable: %s", log_safe(exc, 300))
            raise _RoutingUnavailable() from exc

    async def aclose(self):
        try:
            await self.client.aclose()
        except Exception:  # pragma: no cover - best-effort
            pass

    def _shape(self, payload: dict, block: dict | None) -> dict:
        """Add the per-request extras: reasoning / cache parameters, then routing."""
        from .provider_request import compatible_parameters
        payload.update(compatible_parameters(self.profile, payload["model"], self.reasoning_effort))
        if block:
            payload["provider"] = block
        return payload

    @staticmethod
    def _explain_routing_refusal(resp, block: dict | None) -> None:
        """Name the owner's knobs when OpenRouter refuses a request that carried them.

        With ``data_collection`` seeded ``deny``, a model served only by upstreams that
        collect data answers 404 "No endpoints found matching your data policy"; the
        generic failure line would not point at the setting that caused it.
        """
        if not block or getattr(resp, "status_code", 0) not in _ROUTING_REFUSAL_STATUSES:
            return
        try:
            error = resp.json().get("error")
            detail = error.get("message", "") if isinstance(error, dict) else str(error or "")
        except Exception:
            detail = getattr(resp, "text", "")
        logger.warning(
            "OpenRouter refused the request (HTTP %s: %s) under provider routing %s — if no "
            "upstream provider satisfies it, loosen %s",
            resp.status_code, log_safe(detail, 200),
            log_safe(json.dumps(block, sort_keys=True), 300), _ROUTING_SETTINGS)

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
            block = await self._provider_block_now()
        except _RoutingUnavailable:
            return _ERROR
        self._shape(payload, block)
        try:
            resp = await self.client.post("/chat/completions", json=payload, headers=self._headers())
            self._explain_routing_refusal(resp, block)
            resp.raise_for_status()
            data = resp.json()
            content = (data["choices"][0]["message"].get("content", "") or "")
            answer = strip_thinking(content)
            if self.profile.backend_kind == "openai-compatible":
                report_text_usage(compatible_usage(data))
            return answer
        except Exception as e:
            logger.warning("OpenRouter generate failed: %s", e)
            return _ERROR

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
        try:
            block = await self._provider_block_now()
        except _RoutingUnavailable:
            return ToolTurn(content=_ERROR)
        self._shape(payload, block)
        try:
            resp = await self.client.post("/chat/completions", json=payload, headers=self._headers())
            self._explain_routing_refusal(resp, block)
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
            return ToolTurn(content=_ERROR)


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
