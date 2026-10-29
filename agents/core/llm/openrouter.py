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

The H388 developer-role selector is adapted from Hermes Agent 59b2aeef6c7a.
MIT License
Copyright (c) 2025 Nous Research
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, Optional

from ..log_safe import log_safe
from .base import LLMBackend, ThinkingStreamFilter, _emit, cloud_cap
from .egress import llm_async_client
from .provider_errors import note_provider_failure
from .provider_routing import SETTINGS_KEYS, build_provider_block
from .providers.admitted_profiles import AdmittedProviderProfile
from .providers.hook_runtime import ProviderHookRuntimeError
from .repetition_guard import RepetitionStreamGuard
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


def _openrouter_instruction_messages(model: str, messages: list[dict]) -> list[dict]:
    """Use the OpenAI developer role for OpenRouter's GPT-5/Codex models.

    Adapted from Hermes Agent ``agent/transports/chat_completions.py`` at
    59b2aeef6c7a (MIT). This is limited to OpenRouter's ``openai/`` model ids;
    a custom OpenAI-compatible endpoint has no declared role semantics.
    """
    name = (model or "").lower()
    openai_model = name.removeprefix("openai/") if name.startswith("openai/") else ""
    supports_developer = any(
        openai_model == family or openai_model.startswith((family + "-", family + "."))
        for family in ("gpt-5", "codex")
    )
    if supports_developer and messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        return [{**messages[0], "role": "developer"}, *messages[1:]]
    return messages


class OpenRouterBackend(LLMBackend):
    """OpenAI-compatible OpenRouter backend (bearer-auth)."""

    # OpenRouter speaks the runtime's dialect natively (Hermes absorption, wave 0.1).
    supports_tools = True

    def __init__(self, api_key: str = "", base_url: str = OPENROUTER_BASE, client=None, *, profile=None, reasoning_effort="", effort_declarations=None, provider_routing=None, model=None) -> None:
        from .provider_request import profile_with_declarations, require_profile_kind
        from .providers import DEFAULT_REGISTRY
        from .providers.admitted_profiles import AdmittedProviderProfile
        self.profile = (profile if isinstance(profile, AdmittedProviderProfile)
                        or profile is not None and profile.id.startswith('custom:') else
                        profile_with_declarations(
                            profile or DEFAULT_REGISTRY.get("openrouter"), effort_declarations))
        require_profile_kind(self.profile, "openai-compatible", "chat_completions")
        if profile is not None and base_url == OPENROUTER_BASE:
            base_url = self.profile.default_base_url or base_url
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
        admitted = isinstance(self.profile, AdmittedProviderProfile)
        custom = self.profile.id.startswith('custom:')
        if custom:
            from .providers.custom_runtime import CustomEndpointRuntime

            runtime = getattr(getattr(client, '_transport', None), 'runtime', None)
            if (type(runtime) is not CustomEndpointRuntime or runtime.profile is not self.profile
                    or api_key or client is None):
                raise ProviderHookRuntimeError('custom_egress_unavailable')
        if admitted and client is not None:
            raise ProviderHookRuntimeError('native_egress_unavailable')
        if admitted:
            from .providers.native_transport import native_admitted_client
            self.client = native_admitted_client(self.profile, api_key,
                                                 model or self.profile.fallback_models[0])
        else:
            self.client = client or llm_async_client(self.profile.id, base_url=base_url,
                                                     timeout=120.0)

    def _send_client(self):
        custom = getattr(self, '_custom_endpoint_runtime', None)
        if custom is not None:
            from .providers.custom_runtime import require_custom_client
            return require_custom_client(self.client, custom)
        if self.profile.id.startswith('custom:'):
            raise ProviderHookRuntimeError('custom_egress_unavailable')
        if isinstance(self.profile, AdmittedProviderProfile):
            from .providers.native_transport import require_native_client
            return require_native_client(self.client, self.profile)
        return self.client

    @staticmethod
    def _block_from(knobs) -> dict | None:
        return build_provider_block(**knobs) if knobs else None

    def _current_block(self) -> dict | None:
        source = self._provider_routing
        return self._block_from(source() if callable(source) else source)

    @property
    def provider_block(self) -> dict | None:
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

    def _shape(self, payload: dict, block: dict | None, *, profile=None) -> dict:
        """Add the per-request extras: reasoning / cache parameters, a delegated child's
        ``extra_body`` (H681, never over a key the hub owns), then routing."""
        from .provider_request import (
            apply_profile_request,
            compatible_parameters,
            prepare_profile_messages,
            profile_reasoning_config,
        )
        from .request_context import merge_extra_body, reconcile_payload
        profile = self.profile if profile is None else profile
        from .providers.admitted_profiles import AdmittedProviderProfile
        maximum = 512 * 1024 if isinstance(self.profile, AdmittedProviderProfile) else 256 * 1024
        payload["messages"] = prepare_profile_messages(profile, payload["messages"], maximum=maximum)
        reasoning_config = profile_reasoning_config(
            profile, payload["model"], self.reasoning_effort,
            supports_wire="reasoning-effort" in profile.capabilities)
        apply_profile_request(profile, payload,
                              context={"reasoning_config": reasoning_config})
        payload.update(compatible_parameters(profile, payload["model"], self.reasoning_effort))
        merge_extra_body(payload)
        reconcile_payload(payload)
        if self.profile.id == "openrouter":
            payload["messages"] = _openrouter_instruction_messages(payload["model"], payload["messages"])
        if block:
            payload["provider"] = block
        return payload

    async def _shape_async(self, payload: dict, block: dict | None):
        from .provider_request import profile_reasoning_config
        from .providers.admitted_profiles import prepare_admitted_profile

        configuration = profile_reasoning_config(
            self.profile, payload['model'], self.reasoning_effort,
            supports_wire='reasoning-effort' in self.profile.capabilities)
        profile = await prepare_admitted_profile(
            self.profile, model=payload['model'], messages=payload['messages'],
            reasoning_config=configuration)
        self._shape(payload, block, profile=profile)
        return profile

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
        from .provider_request import profile_headers

        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return profile_headers(self.profile, h)

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

        prepared = await self._shape_async(payload, block)
        try:
            if isinstance(self.profile, AdmittedProviderProfile):
                from .providers.native_transport import native_post
                resp = await native_post(self.profile, prepared, self._send_client(),
                                         '/chat/completions', headers=self._headers(), json=payload)
            else:
                resp = await self._send_client().post("/chat/completions", json=payload, headers=self._headers())
            self._explain_routing_refusal(resp, block)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            content = (choice["message"].get("content", "") or "")
            answer = self._finalize_cloud(content, choice.get("finish_reason"), model)
            if self.profile.backend_kind == "openai-compatible":
                report_text_usage(compatible_usage(data))
            return answer
        except ProviderHookRuntimeError:
            raise
        except Exception as e:
            logger.warning("OpenRouter generate failed: %s", e)
            note_provider_failure(self.profile.id, model, e)
            return _ERROR

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] | None = None,
        on_activity: Callable[[], None] | None = None,
    ) -> str:
        # The ordinary OpenRouter path retains its established buffered behavior.
        if not isinstance(self.profile, AdmittedProviderProfile):
            return await super().generate_stream(
                model, prompt, system, max_tokens, temperature, on_token, on_activity)

        from .providers.native_transport import native_stream

        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "max_tokens": cloud_cap(max_tokens), "temperature": temperature,
            "stream": True,
        }
        try:
            block = await self._provider_block_now()
        except _RoutingUnavailable:
            return _ERROR
        prepared = await self._shape_async(payload, block)
        filter_ = ThinkingStreamFilter()
        repeat = RepetitionStreamGuard()
        emitted = ""
        finish = None
        completed = False
        usage = None
        try:
            async with asyncio.timeout(120):
                async with native_stream(
                    self.profile, prepared, self._send_client(), "POST",
                    "/chat/completions", headers=self._headers(), json=payload,
                ) as response:
                    response.raise_for_status()
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise ValueError("invalid compatible stream type")
                    pending = b""
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > 512_000:
                            raise ValueError("compatible stream too large")
                        pending += chunk
                        if len(pending) > 65_536 and b"\n" not in pending:
                            raise ValueError("compatible stream frame too large")
                        while b"\n" in pending:
                            raw, pending = pending.split(b"\n", 1)
                            if len(raw) > 65_536:
                                raise ValueError("compatible stream frame too large")
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
                                raise ValueError("invalid compatible stream event")
                            if "usage" in frame:
                                usage = compatible_usage(frame)
                            choices = frame.get("choices") or []
                            if not choices:
                                continue
                            choice = choices[0]
                            if not isinstance(choice, dict) or choice.get("refusal"):
                                raise ValueError("invalid compatible stream choice")
                            if choice.get("finish_reason"):
                                finish = choice["finish_reason"]
                            delta = choice.get("delta") or {}
                            if not isinstance(delta, dict) or delta.get("refusal"):
                                raise ValueError("invalid compatible stream delta")
                            part = delta.get("content") or ""
                            if not isinstance(part, str):
                                raise ValueError("invalid compatible stream content")
                            safe = filter_.feed(part)
                            if safe:
                                emitted += safe
                                if on_token is not None:
                                    await _emit(on_token, repeat.feed(safe))
                        if completed:
                            break
                    if not completed or finish not in {"stop", "length"}:
                        raise ValueError("incomplete compatible stream")
            remainder = filter_.flush()
            if remainder:
                emitted += remainder
                if on_token is not None:
                    await _emit(on_token, repeat.feed(remainder))
            if usage is not None:
                report_text_usage(usage)
            answer = self._finalize_cloud(emitted, finish, model)
            if on_token is not None:
                await _emit(on_token, repeat.release(answer))
            return answer
        except ProviderHookRuntimeError:
            raise
        except Exception as exc:
            logger.warning("OpenRouter stream failed: %s", log_safe(exc, 200))
            note_provider_failure(self.profile.id, model, exc)
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
        prepared = await self._shape_async(payload, block)
        try:
            if isinstance(self.profile, AdmittedProviderProfile):
                from .providers.native_transport import native_post
                resp = await native_post(self.profile, prepared, self._send_client(),
                                         '/chat/completions', headers=self._headers(), json=payload)
            else:
                resp = await self._send_client().post("/chat/completions", json=payload, headers=self._headers())
            self._explain_routing_refusal(resp, block)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            message = choice.get("message") or {}
            return ToolTurn(
                content=self._finalize_cloud(
                    message.get("content", "") or "", choice.get("finish_reason"), model
                ),
                tool_calls=parse_openai_tool_calls(message.get("tool_calls") or []),
                finish_reason=choice.get("finish_reason"),
                usage=(compatible_usage(data) if self.profile.backend_kind == "openai-compatible"
                       else TokenUsage()),
            )
        except ProviderHookRuntimeError:
            raise
        except Exception as e:
            logger.warning("OpenRouter tool turn failed: %s", e)
            note_provider_failure(self.profile.id, model, e)
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
