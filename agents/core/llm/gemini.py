"""
gemini.py — Google Gemini API backend with streaming and thinking mode.
Uses direct httpx calls (no SDK dependency). Supports Flash (fast/cheap)
and Pro (heavy) model families.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Iterator

import httpx

from .reasoning_effort import ReasoningEffortRefused
from .auth_rotation import AuthLease, is_rotatable_status
from .base import LLMBackend, _emit, cloud_cap
from .egress import llm_async_client
from .gemini_context import CachedContentRejected, GeminiRequestBinding
from .provider_errors import GEMINI_DEGRADED_REPLY, log_provider_failure
from .tool_dialects import (
    gemini_usage,
    GEMINI_FINISH_REASONS,
    gemini_contents,
    gemini_function_declarations,
    gemini_text,
    gemini_tool_calls,
    normalize_finish_reason,
    remember_thought_signatures,
)
from .tool_protocol import TokenUsage, ToolSpec, ToolTurn, parse_openai_tool_calls
from .usage_context import report_text_usage


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

logger = logging.getLogger("jarvis.llm.gemini")


def _stream_terminal_usage(data: Any) -> TokenUsage | None:
    """Accept only a supported terminal response's own complete measurement."""
    if not isinstance(data, dict) or "error" in data:
        return None
    candidates = data.get("candidates")
    feedback = data.get("promptFeedback")
    block = feedback.get("blockReason") if isinstance(feedback, dict) else None
    blocked = block in {"SAFETY", "OTHER", "BLOCKLIST", "PROHIBITED_CONTENT", "IMAGE_SAFETY"} if isinstance(block, str) else False
    if block is not None:
        if not blocked or candidates not in (None, []):
            return None
    elif not (isinstance(candidates, list) and len(candidates) == 1
              and isinstance(candidates[0], dict)
              and isinstance(candidates[0].get("finishReason"), str)
              and candidates[0]["finishReason"] in GEMINI_FINISH_REASONS):
        return None
    usage = data.get("usageMetadata")
    if not isinstance(usage, dict):
        return None
    for key in ("promptTokenCount", "candidatesTokenCount"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            return None
    thoughts = usage.get("thoughtsTokenCount", 0)
    if type(thoughts) is not int or thoughts < 0:
        return None
    if blocked and (usage["candidatesTokenCount"] or thoughts):
        return None
    return gemini_usage(data)


class GeminiBackend(LLMBackend):
    # Tool calls travel as functionCall / functionResponse parts; the translation lives
    # in tool_dialects (Hermes absorption, wave 0.1).
    supports_tools = True

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", auth_pool=None, reasoning_effort="", effort_declarations=None):
        from .providers import DEFAULT_REGISTRY
        from .provider_request import GEMINI_LEVELS, profile_with_declarations
        self.profile = profile_with_declarations(
            DEFAULT_REGISTRY.get("gemini"), effort_declarations, defaults=GEMINI_LEVELS,
        )
        self.reasoning_effort = reasoning_effort
        self.api_key = api_key
        self.model = model
        self.auth_pool = auth_pool
        self.client = llm_async_client("gemini", timeout=120.0)
        self._request_binding: ContextVar[GeminiRequestBinding | None] = ContextVar(
            f"gemini_request_binding_{id(self)}",
            default=None,
        )
        # Thinking models sign the function calls they make and refuse a replayed call
        # without its signature. The runtime's OpenAI-shaped history has nowhere to carry
        # it, so it is kept here, keyed by call id, bounded, for the life of the backend.
        self._thought_signatures: dict[str, str] = {}

    def acquire_lease(self) -> AuthLease:
        """Capture the credential used by one request attempt."""
        if self.auth_pool is not None:
            lease = self.auth_pool.lease()
            if lease is not None:
                return lease
        if self.api_key:
            return AuthLease(profile_id="gemini-single", api_key=self.api_key)
        raise RuntimeError("Gemini provider unavailable")

    @contextmanager
    def request_scope(
        self,
        binding: GeminiRequestBinding,
    ) -> Iterator[GeminiRequestBinding]:
        token = self._request_binding.set(binding)
        try:
            yield binding
        finally:
            self._request_binding.reset(token)

    def current_binding(self) -> GeminiRequestBinding | None:
        return self._request_binding.get()

    def _capture_binding(self) -> GeminiRequestBinding:
        binding = self.current_binding()
        if binding is not None:
            return binding
        return GeminiRequestBinding(lease=self.acquire_lease())

    def _build_url(self, model: str, *, streaming: bool = False) -> str:
        action = "streamGenerateContent" if streaming else "generateContent"
        suffix = "?alt=sse" if streaming else ""
        return f"{GEMINI_API_BASE}/models/{model}:{action}{suffix}"

    def _fit_effort(self, payload, model):
        level, reason = self.profile.clamp_reasoning_effort(model, self.reasoning_effort)
        if reason == "below-minimum":
            raise ReasoningEffortRefused()
        if level is not None:
            config = payload["generationConfig"]
            if model in {"gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"}:
                # Product effort targets inside Google's documented budget ranges.
                budget = min({"low": 1024, "medium": 4096, "high": 8192}.get(level, 1024),
                             config["maxOutputTokens"] - 1)
                floor = 128 if model == "gemini-2.5-pro" else 512
                if budget >= floor:
                    config["thinkingConfig"] = {"thinkingBudget": budget}
                else:
                    raise ReasoningEffortRefused()
            elif level in {"minimal", "low", "medium", "high"}:
                config["thinkingConfig"] = {"thinkingLevel": level}
        return payload

    def _build_payload(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> dict:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": cloud_cap(max_tokens),
                "temperature": temperature,
            },
        }
        binding = self.current_binding()
        if binding is not None and binding.cache_name:
            payload["cachedContent"] = binding.cache_name
        elif system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return self._fit_effort(payload, model or self.model)

    def _extract_text(self, data: dict) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        texts = [p.get("text", "") for p in parts]
        return "".join(texts)

    def _next_auth_binding(self, binding: GeminiRequestBinding) -> GeminiRequestBinding:
        """Rotate auth without carrying a cache created under the old credential."""
        lease = self.acquire_lease()
        return binding.without_cache(lease=lease)

    def _report_success(self, binding: GeminiRequestBinding) -> None:
        if self.auth_pool is not None:
            self.auth_pool.report_success(binding.lease.profile_id)

    def _rotate_after_failure(
        self,
        binding: GeminiRequestBinding,
        exc: httpx.HTTPStatusError,
        *,
        attempt: int,
        attempts: int,
    ) -> GeminiRequestBinding | None:
        if self.auth_pool is None or not is_rotatable_status(exc.response.status_code):
            return None
        self.auth_pool.report_failure(binding.lease.profile_id)
        if attempt + 1 >= attempts:
            return None
        return self._next_auth_binding(binding)

    async def _generate_once(
        self,
        *,
        binding: GeminiRequestBinding,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        with self.request_scope(binding):
            payload = self._build_payload(prompt, system, max_tokens, temperature, model=model)
            response = await self.client.post(
                self._build_url(model),
                headers={"x-goog-api-key": binding.lease.api_key},
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if binding.cache_name and exc.response.status_code in {400, 404}:
                    raise CachedContentRejected(exc.response.status_code) from None
                raise
            data = response.json()
            text = self._extract_text(data)
            report_text_usage(gemini_usage(data))
            return text

    async def _request_with_cache_retry(
        self,
        *,
        binding: GeminiRequestBinding,
        operation: Callable[[GeminiRequestBinding], Awaitable[str]],
    ) -> str:
        """Retry a provider-rejected cached request once without cached content."""
        try:
            return await operation(binding)
        except CachedContentRejected:
            if binding.invalidate_cache is not None:
                try:
                    await binding.invalidate_cache()
                except Exception as exc:
                    log_provider_failure(
                        logger,
                        provider="Gemini",
                        operation="cache invalidation",
                        exc=exc,
                    )
            return await operation(binding.without_cache())

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        actual_model = model if model and "/" not in model else self.model
        try:
            binding = self._capture_binding()
        except Exception as exc:
            log_provider_failure(
                logger,
                provider="Gemini",
                operation="generate",
                exc=exc,
            )
            return GEMINI_DEGRADED_REPLY

        attempts = max(1, self.auth_pool.size if self.auth_pool is not None else 1)
        for attempt in range(attempts):
            try:
                text = await self._request_with_cache_retry(
                    binding=binding,
                    operation=lambda request_binding: self._generate_once(
                        binding=request_binding,
                        model=actual_model,
                        prompt=prompt,
                        system=system,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
                self._report_success(binding)
                return self._finalize_cloud(text)
            except ReasoningEffortRefused:
                raise
            except httpx.HTTPStatusError as exc:
                log_provider_failure(
                    logger,
                    provider="Gemini",
                    operation="generate",
                    exc=exc,
                )
                next_binding = self._rotate_after_failure(
                    binding,
                    exc,
                    attempt=attempt,
                    attempts=attempts,
                )
                if next_binding is None:
                    return GEMINI_DEGRADED_REPLY
                binding = next_binding
            except Exception as exc:
                log_provider_failure(
                    logger,
                    provider="Gemini",
                    operation="generate",
                    exc=exc,
                )
                return GEMINI_DEGRADED_REPLY
        return GEMINI_DEGRADED_REPLY

    def _build_tool_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int,
        temperature: float,
        model: str | None = None,
    ) -> dict[str, Any]:
        system, contents = gemini_contents(messages, thought_signatures=self._thought_signatures)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": cloud_cap(max_tokens),
                "temperature": temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        declarations = gemini_function_declarations(tools)
        if declarations:
            payload["tools"] = [{"functionDeclarations": declarations}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        return self._fit_effort(payload, model or self.model)

    def _tool_turn_from_response(self, data: Any) -> ToolTurn:
        usage = gemini_usage(data)
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            feedback = data.get("promptFeedback") if isinstance(data, dict) else None
            blocked = isinstance(feedback, dict) and bool(feedback.get("blockReason"))
            return ToolTurn(content="", finish_reason="content_filter" if blocked else None, usage=usage)
        candidate = candidates[0]
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        raw_calls, signatures = gemini_tool_calls(parts)
        remember_thought_signatures(self._thought_signatures, signatures)
        return ToolTurn(
            content=self._finalize_cloud(gemini_text(parts)),
            usage=usage,
            tool_calls=parse_openai_tool_calls(raw_calls),
            finish_reason=normalize_finish_reason(
                GEMINI_FINISH_REASONS, candidate.get("finishReason")
            ),
        )

    async def generate_tool_turn(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> ToolTurn:
        """One tool-enabled turn; every functionCall part crosses `parse_openai_tool_calls`.

        A tool turn never binds cached content: the API refuses `tools` and
        `systemInstruction` next to `cachedContent`, so the bound cache (if any) is dropped
        for this request only and the auth lease is kept.
        """
        actual_model = model if model and "/" not in model else self.model
        try:
            binding = self._capture_binding().without_cache()
        except Exception as exc:
            log_provider_failure(logger, provider="Gemini", operation="tool turn", exc=exc)
            return ToolTurn(content=GEMINI_DEGRADED_REPLY)
        payload = self._build_tool_payload(messages, tools, max_tokens, temperature, model=actual_model)

        attempts = max(1, self.auth_pool.size if self.auth_pool is not None else 1)
        for attempt in range(attempts):
            try:
                response = await self.client.post(
                    self._build_url(actual_model),
                    headers={"x-goog-api-key": binding.lease.api_key},
                    json=payload,
                )
                response.raise_for_status()
                turn = self._tool_turn_from_response(response.json())
                self._report_success(binding)
                return turn
            except ReasoningEffortRefused:
                raise
            except httpx.HTTPStatusError as exc:
                log_provider_failure(logger, provider="Gemini", operation="tool turn", exc=exc)
                next_binding = self._rotate_after_failure(
                    binding,
                    exc,
                    attempt=attempt,
                    attempts=attempts,
                )
                if next_binding is None:
                    return ToolTurn(content=GEMINI_DEGRADED_REPLY)
                binding = next_binding
            except Exception as exc:
                log_provider_failure(logger, provider="Gemini", operation="tool turn", exc=exc)
                return ToolTurn(content=GEMINI_DEGRADED_REPLY)
        return ToolTurn(content=GEMINI_DEGRADED_REPLY)

    async def _stream_once(
        self,
        *,
        binding: GeminiRequestBinding,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        on_token: Callable[[str], None] | None,
    ) -> str:
        full = ""
        pending_usage = None
        invalid_usage = False
        exhausted = False
        response_id = None
        with self.request_scope(binding):
            payload = self._build_payload(prompt, system, max_tokens, temperature, model=model)
            async with self.client.stream(
                "POST",
                self._build_url(model, streaming=True),
                headers={"x-goog-api-key": binding.lease.api_key},
                json=payload,
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if binding.cache_name and exc.response.status_code in {400, 404}:
                        raise CachedContentRejected(exc.response.status_code) from None
                    raise
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        if line.strip() and (not line.startswith((":", "event:", "id:", "retry:"))
                                             or (line.startswith("event:") and line[6:].strip() == "error")):
                            invalid_usage = True
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        invalid_usage = True
                        continue
                    pending_usage = _stream_terminal_usage(data)
                    if not isinstance(data, dict) or "error" in data:
                        invalid_usage = True
                    candidates = data.get("candidates") if isinstance(data, dict) else None
                    if isinstance(candidates, list):
                        if len(candidates) > 1:
                            invalid_usage = True
                        # Candidate identity can span separate singleton frames.
                        # This request supports only the default candidate zero.
                        for candidate in candidates:
                            if isinstance(candidate, dict) and "index" in candidate:
                                index = candidate["index"]
                                if type(index) is not int or index != 0:
                                    invalid_usage = True
                    if isinstance(data, dict) and "responseId" in data:
                        current_id = data["responseId"]
                        if not isinstance(current_id, str) or not current_id or (response_id is not None and response_id != current_id):
                            invalid_usage = True
                        response_id = current_id
                    text = self._extract_text(data)
                    if text:
                        full += text
                        if on_token:
                            await _emit(on_token, text)
                else:
                    exhausted = True
        # EOF and successful context-manager close are both required. A later frame
        # replaces eligibility; an earlier snapshot is never a final-count fallback.
        if exhausted and not invalid_usage and pending_usage is not None:
            report_text_usage(pending_usage)
        return full

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        actual_model = model if model and "/" not in model else self.model
        try:
            binding = self._capture_binding()
        except Exception as exc:
            log_provider_failure(
                logger,
                provider="Gemini",
                operation="stream",
                exc=exc,
            )
            return GEMINI_DEGRADED_REPLY

        attempts = max(1, self.auth_pool.size if self.auth_pool is not None else 1)
        for attempt in range(attempts):
            try:
                text = await self._request_with_cache_retry(
                    binding=binding,
                    operation=lambda request_binding: self._stream_once(
                        binding=request_binding,
                        model=actual_model,
                        prompt=prompt,
                        system=system,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        on_token=on_token,
                    ),
                )
                self._report_success(binding)
                return self._finalize_cloud(text)
            except ReasoningEffortRefused:
                raise
            except httpx.HTTPStatusError as exc:
                log_provider_failure(
                    logger,
                    provider="Gemini",
                    operation="stream",
                    exc=exc,
                )
                next_binding = self._rotate_after_failure(
                    binding,
                    exc,
                    attempt=attempt,
                    attempts=attempts,
                )
                if next_binding is None:
                    return GEMINI_DEGRADED_REPLY
                binding = next_binding
            except Exception as exc:
                log_provider_failure(
                    logger,
                    provider="Gemini",
                    operation="stream",
                    exc=exc,
                )
                return GEMINI_DEGRADED_REPLY
        return GEMINI_DEGRADED_REPLY

    async def close(self) -> None:
        await self.client.aclose()
