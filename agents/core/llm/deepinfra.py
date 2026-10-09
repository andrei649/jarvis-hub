"""Explicit DeepInfra chat-completions backend for the selected main route."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..log_safe import log_safe
from .base import LLMBackend, ThinkingStreamFilter, _emit, cloud_cap, strip_thinking
from .data_handling import DataHandlingRefused
from .direct_transport import require_direct_async_transport
from .egress import llm_async_client
from .provider_errors import note_provider_failure
from .provider_request import compatible_parameters, profile_with_declarations
from .providers import DEFAULT_REGISTRY
from .request_context import merge_extra_body, reconcile_payload
from .tool_dialects import compatible_usage
from .tool_protocol import ToolSpec, ToolTurn, parse_openai_tool_calls
from .usage_context import report_text_usage
from .vision_deepinfra import DEEPINFRA_VISION_BASE
from .vision_openrouter import _validated_base

logger = logging.getLogger("jarvis.llm.deepinfra")
# Existing generic backend-failure marker; never return a vendor error body to chat.
_FAILURE = "[VLM error]"
_expected_request: ContextVar[dict | None] = ContextVar("deepinfra_main_request", default=None)


def validated_main_base(raw: str) -> str:
    """Accept only DeepInfra's known compatible chat base, then canonicalize it."""
    if not isinstance(raw, str):
        raise ValueError("invalid DeepInfra main destination")
    try:
        _base, local, origin = _validated_base(raw)
        parts = urlsplit(raw)
        if (local or origin != ("https", "api.deepinfra.com", 443)
                or parts.netloc.lower() not in {"api.deepinfra.com", "api.deepinfra.com:443"}
                or parts.path not in {"/v1/openai", "/v1/openai/"}):
            raise ValueError
    except ValueError:
        raise ValueError("invalid DeepInfra main destination") from None
    return DEEPINFRA_VISION_BASE


class DeepInfraBackend(LLMBackend):
    """One physical DeepInfra identity; no OpenRouter routing object or key."""

    supports_tools = True

    def __init__(self, api_key: str, base_url: str = DEEPINFRA_VISION_BASE,
                 client=None, *, reasoning_effort="", effort_declarations=None) -> None:
        base = validated_main_base(base_url)
        if (not isinstance(api_key, str) or not api_key or len(api_key) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in api_key)):
            raise ValueError("invalid DeepInfra main key")
        self.profile = profile_with_declarations(
            DEFAULT_REGISTRY.get("deepinfra"), effort_declarations)
        self.api_key = api_key
        self.base_url = base
        self.reasoning_effort = reasoning_effort
        self.client = client or llm_async_client(
            "deepinfra", base_url=base, timeout=120.0, trust_env=False)
        if isinstance(self.client, httpx.AsyncClient):
            hooks = self.client.event_hooks["request"]
            if not hooks or not getattr(hooks[-1], "_nerva_egress_recorder", False):
                raise ValueError("DeepInfra main egress guard unavailable")
            hooks.insert(-1, self._check_request)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _check_request(self, request: httpx.Request) -> None:
        expected = _expected_request.get()
        if expected is None:
            raise DataHandlingRefused("DeepInfra physical request is unbound")
        require_direct_async_transport(self.client, request.url)
        try:
            def unique_pairs(pairs):
                row = {}
                for key, value in pairs:
                    if key in row:
                        raise ValueError("duplicate DeepInfra request field")
                    row[key] = value
                return row

            body = json.loads(request.content, object_pairs_hook=unique_pairs)
        except (ValueError, httpx.RequestNotRead):
            body = None
        if (request.method != "POST" or str(request.url) != expected["url"]
                or request.headers.get("Authorization") != expected["authorization"]
                or request.headers.get("Cookie") or request.headers.get("Proxy-Authorization")
                or body != expected["body"] or not isinstance(body, dict)
                or "provider" in body):
            raise DataHandlingRefused("DeepInfra physical request changed")

    def _shape(self, payload: dict) -> dict:
        payload.update(compatible_parameters(self.profile, payload["model"], self.reasoning_effort))
        merge_extra_body(payload)
        reconcile_payload(payload)
        # DeepInfra's compatible schema has no OpenRouter upstream-provider object.
        if "provider" in payload:
            raise ValueError("foreign provider routing is not supported")
        return payload

    async def _send(self, payload: dict) -> dict:
        url = validated_main_base(self.base_url) + "/chat/completions"
        require_direct_async_transport(self.client, url)
        hooks = self.client.event_hooks["request"]
        if (len(hooks) < 2 or hooks[-2] != self._check_request
                or not getattr(hooks[-1], "_nerva_egress_recorder", False)):
            raise DataHandlingRefused("DeepInfra physical guard changed")
        shaped = self._shape(payload)
        expected = {"url": url, "authorization": f"Bearer {self.api_key}",
                    "body": json.loads(json.dumps(shaped))}
        token = _expected_request.set(expected)
        try:
            response = await self.client.post(
                "/chat/completions", json=shaped,
                headers={"Content-Type": "application/json", "Authorization": expected["authorization"]},
            )
        finally:
            _expected_request.reset(token)
        response.raise_for_status()
        if len(response.content) > 512_000:
            raise ValueError("DeepInfra response too large")
        data = response.json()
        if type(data) is not dict or type(data.get("choices")) is not list or not data["choices"]:
            raise ValueError("invalid DeepInfra response")
        return data

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "max_tokens": cloud_cap(max_tokens), "temperature": temperature,
            "stream": False,
        }
        try:
            data = await self._send(payload)
            content = data["choices"][0]["message"].get("content", "") or ""
            if not isinstance(content, str):
                raise ValueError("invalid DeepInfra answer")
            report_text_usage(compatible_usage(data))
            return strip_thinking(content)
        except Exception as exc:
            logger.warning("DeepInfra main request failed: %s", log_safe(exc, 200))
            note_provider_failure("deepinfra", model, exc)
            return _FAILURE

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] | None = None,
        on_activity: Callable[[], None] | None = None,
    ) -> str:
        """Consume one native SSE response under the same physical request guards."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "max_tokens": cloud_cap(max_tokens), "temperature": temperature,
            "stream": True,
        }
        emitted = ""
        filter_ = ThinkingStreamFilter()
        finish = None
        completed = False
        usage = None
        try:
            url = validated_main_base(self.base_url) + "/chat/completions"
            require_direct_async_transport(self.client, url)
            hooks = self.client.event_hooks["request"]
            if (len(hooks) < 2 or hooks[-2] != self._check_request
                    or not getattr(hooks[-1], "_nerva_egress_recorder", False)):
                raise DataHandlingRefused("DeepInfra physical guard changed")
            shaped = self._shape(payload)
            expected = {"url": url, "authorization": f"Bearer {self.api_key}",
                        "body": json.loads(json.dumps(shaped))}
            token = _expected_request.set(expected)
            try:
                async with asyncio.timeout(120):
                    async with self.client.stream(
                        "POST", "/chat/completions", json=shaped,
                        headers={"Content-Type": "application/json",
                                 "Authorization": expected["authorization"]},
                    ) as response:
                        response.raise_for_status()
                        if "text/event-stream" not in response.headers.get("content-type", ""):
                            raise ValueError("invalid DeepInfra stream type")
                        pending = b""
                        total = 0
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > 512_000:
                                raise ValueError("DeepInfra stream too large")
                            pending += chunk
                            if len(pending) > 65_536 and b"\n" not in pending:
                                raise ValueError("DeepInfra stream frame too large")
                            while b"\n" in pending:
                                raw, pending = pending.split(b"\n", 1)
                                if len(raw) > 65_536:
                                    raise ValueError("DeepInfra stream frame too large")
                                line = raw.rstrip(b"\r")
                                if not line.startswith(b"data:"):
                                    continue
                                if on_activity is not None:
                                    on_activity()
                                content = line[5:].strip()
                                if content == b"[DONE]":
                                    completed = True
                                    break
                                frame = json.loads(content)
                                if not isinstance(frame, dict) or frame.get("error") or frame.get("refusal"):
                                    raise ValueError("invalid DeepInfra stream event")
                                if "usage" in frame:
                                    usage = compatible_usage(frame)
                                choices = frame.get("choices") or []
                                if not choices:
                                    continue
                                choice = choices[0]
                                if not isinstance(choice, dict) or choice.get("refusal"):
                                    raise ValueError("invalid DeepInfra stream choice")
                                if choice.get("finish_reason"):
                                    finish = choice["finish_reason"]
                                delta = choice.get("delta") or {}
                                if not isinstance(delta, dict) or delta.get("refusal"):
                                    raise ValueError("invalid DeepInfra stream delta")
                                part = delta.get("content") or ""
                                if not isinstance(part, str):
                                    raise ValueError("invalid DeepInfra stream content")
                                safe = filter_.feed(part)
                                if safe:
                                    emitted += safe
                                    if on_token is not None:
                                        await _emit(on_token, safe)
                            if completed:
                                break
                        if not completed or finish not in {"stop", "length"}:
                            raise ValueError("incomplete DeepInfra stream")
            finally:
                _expected_request.reset(token)
            remainder = filter_.flush()
            if remainder:
                emitted += remainder
                if on_token is not None:
                    await _emit(on_token, remainder)
            if usage is not None:
                report_text_usage(usage)
            return strip_thinking(emitted)
        except Exception as exc:
            logger.warning("DeepInfra stream failed: %s", log_safe(exc, 200))
            note_provider_failure("deepinfra", model, exc)
            return _FAILURE

    async def generate_tool_turn(
        self, model: str, messages: list[dict[str, Any]], tools: list[ToolSpec],
        max_tokens: int = 1024, temperature: float = 0.7,
    ) -> ToolTurn:
        payload: dict[str, Any] = {
            "model": model, "messages": messages,
            "max_tokens": cloud_cap(max_tokens), "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = [tool.as_openai() for tool in tools]
            payload["tool_choice"] = "auto"
        try:
            data = await self._send(payload)
            choice = data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content", "") or ""
            if not isinstance(content, str):
                raise ValueError("invalid DeepInfra answer")
            return ToolTurn(
                content=strip_thinking(content),
                tool_calls=parse_openai_tool_calls(message.get("tool_calls") or []),
                finish_reason=choice.get("finish_reason"),
                usage=compatible_usage(data),
            )
        except Exception as exc:
            logger.warning("DeepInfra tool request failed: %s", log_safe(exc, 200))
            note_provider_failure("deepinfra", model, exc)
            return ToolTurn(content=_FAILURE)
