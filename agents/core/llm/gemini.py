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
from typing import Awaitable, Callable, Iterator

import httpx

from .auth_rotation import AuthLease, is_rotatable_status
from .base import LLMBackend, cloud_cap
from .gemini_context import CachedContentRejected, GeminiRequestBinding
from .provider_errors import GEMINI_DEGRADED_REPLY, log_provider_failure


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

logger = logging.getLogger("jarvis.llm.gemini")


class GeminiBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", auth_pool=None):
        self.api_key = api_key
        self.model = model
        self.auth_pool = auth_pool
        self.client = httpx.AsyncClient(timeout=120.0)
        self._request_binding: ContextVar[GeminiRequestBinding | None] = ContextVar(
            f"gemini_request_binding_{id(self)}",
            default=None,
        )

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

    def _build_payload(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
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
        return payload

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
            payload = self._build_payload(prompt, system, max_tokens, temperature)
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
            return self._extract_text(response.json())

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
        with self.request_scope(binding):
            payload = self._build_payload(prompt, system, max_tokens, temperature)
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
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    text = self._extract_text(data)
                    if text:
                        full += text
                        if on_token:
                            on_token(text)
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
