"""Opt-in API-key Responses backend, fixed to non-reasoning GPT-4.1 models."""

import asyncio
import json

import httpx

from .base import LLMBackend, _emit, cloud_cap
from .egress import llm_async_client
from .provider_errors import note_provider_failure, read_error_head
from .provider_request import (
    apply_profile_request,
    compatible_parameters,
    prepare_profile_messages,
    profile_headers,
    profile_reasoning_config,
    require_profile_base,
    require_profile_kind,
)
from .providers import DEFAULT_REGISTRY
from .providers.admitted_profiles import (
    AdmittedProviderProfile,
    _PreparedProfile,
    prepare_admitted_profile,
)
from .providers.native_transport import AdmittedClientMixin, native_admitted_client, native_stream
from .repetition_guard import RepetitionStreamGuard
from .request_context import current_session, ensure_reasoning_active
from .responses_dialect import (
    MAX_BYTES,
    MAX_TEXT,
    ResponsesRefused,
    encoded,
    input_items,
    parse_response,
)
from .tool_protocol import ToolTurn
from .usage_context import report_text_usage

ENDPOINT = "https://api.openai.com/v1/responses"
MODELS = frozenset({"gpt-4.1", "gpt-4.1-2025-04-14"})
ERROR = "[OpenAI Responses error: request could not be completed]"
MAX_STREAM = 8 * 1024 * 1024
MAX_EVENT = 1024 * 1024
MAX_EVENTS = 10000
TIMEOUT = 120


class ResponsesBackend(AdmittedClientMixin, LLMBackend):
    supports_tools = True
    endpoint = ENDPOINT
    error = ERROR

    def _accept_completion(self):
        """Provider-specific lifetime check after transport close."""

    def _parse_response(self, value, model):
        return parse_response(value)

    def __init__(self, api_key, *, retention="in_memory", transport=None, profile=None, model=None):
        if not isinstance(retention, str) or retention not in {"in_memory", "24h"}:
            raise ResponsesRefused()
        self.api_key = api_key
        self.retention = retention
        self.profile = profile or DEFAULT_REGISTRY.get("openai-responses")
        require_profile_kind(self.profile, "openai-responses", "responses")
        require_profile_base(self.profile, ENDPOINT.rsplit("/", 1)[0])
        if isinstance(self.profile, AdmittedProviderProfile):
            if (model not in MODELS
                    or transport is not None and type(transport) is not httpx.MockTransport):
                raise ResponsesRefused()
            self.client = native_admitted_client(
                self.profile, api_key, model or self.profile.fallback_models[0],
                timeout=TIMEOUT, inner=transport)
        else:
            self.client = llm_async_client(
                "openai-responses", timeout=TIMEOUT, transport=transport,
                follow_redirects=False, trust_env=False)

    def context_window(self, model):
        return 1047576 if model in MODELS else None

    def _payload(self, model, messages, max_tokens, temperature, tools=(), *, profile=None):
        from .provider_replay import KEY

        profile = profile or self.profile
        if not isinstance(model, str) or model not in MODELS:
            raise ResponsesRefused()
        if any(type(row) is dict and KEY in row for row in messages):
            raise ResponsesRefused()
        payload = {
            "model": model,

            "input": input_items(prepare_profile_messages(profile, messages)),

            "store": False,
            "max_output_tokens": min(cloud_cap(max_tokens), 32768),
            "temperature": temperature,
            "prompt_cache_retention": self.retention,
        }

        apply_profile_request(
            profile, payload, cap_key="max_output_tokens",
            context={"reasoning_config": profile_reasoning_config(profile, model)},
        )
        payload.update(compatible_parameters(profile, model, None))

        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                    "strict": False,
                }
                for t in tools
            ]
            payload["tool_choice"] = "auto"
        encoded(payload)
        return payload


    async def _prepared_payload(self, model, messages, max_tokens, temperature, tools=()):
        if not isinstance(model, str) or model not in MODELS:
            raise ResponsesRefused()
        profile = await prepare_admitted_profile(
            self.profile, model=model, messages=messages,
            reasoning_config=profile_reasoning_config(self.profile, model),
            session_id=current_session() or None,
        )
        return self._payload(model, messages, max_tokens, temperature, tools,
                             profile=profile), profile

    def _headers(self, profile=None):
        return profile_headers(profile or self.profile, {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        })

    async def _request(self, payload, *, profile=None):
        if isinstance(self.profile, AdmittedProviderProfile) and not isinstance(
                profile, _PreparedProfile):
            raise ResponsesRefused()
        async with asyncio.timeout(TIMEOUT):
            ensure_reasoning_active()
            async with native_stream(self.profile, profile, self.client,
                "POST", self.endpoint, headers=self._headers(profile), content=encoded(payload)
            ) as response:
                if response.is_error:
                    await read_error_head(response)
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ResponsesRefused()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise ResponsesRefused()
                    data.extend(chunk)
                return self._parse_response(json.loads(data), payload["model"])

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        payload, profile = await self._prepared_payload(
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens,
            temperature,
        )
        try:
            turn = await self._request(payload, profile=profile)
            if turn.tool_calls:
                raise ResponsesRefused()
        except Exception as exc:
            note_provider_failure(self.profile.id, model, exc)
            return self.error
        report_text_usage(turn.usage)
        return self._finalize_cloud(turn.content)

    async def generate_tool_turn(self, model, messages, tools, max_tokens=1024, temperature=0.7):
        payload, profile = await self._prepared_payload(
            model, messages, max_tokens, temperature, tools)
        try:
            return await self._request(payload, profile=profile)
        except Exception as exc:
            note_provider_failure(self.profile.id, model, exc)
            return ToolTurn(content=self.error)

    async def generate_stream(
        self, model, prompt, system="", max_tokens=1024, temperature=0.7, on_token=None
    ):
        payload, profile = await self._prepared_payload(
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens,
            temperature,
        )
        payload["stream"] = True
        full, total, events = "", 0, 0
        guard = RepetitionStreamGuard()   # H393: never paint a loop live
        buffer = bytearray()
        terminal = None
        try:
            async with asyncio.timeout(TIMEOUT):
                ensure_reasoning_active()
                async with native_stream(self.profile, profile, self.client,
                    "POST", self.endpoint, headers=self._headers(profile), content=encoded(payload)
                ) as response:
                    response.raise_for_status()
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise ResponsesRefused()
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_STREAM:
                            raise ResponsesRefused()
                        buffer.extend(chunk)
                        # SSE permits CRLF; normalize only complete line endings.
                        while b"\n\n" in buffer or b"\r\n\r\n" in buffer:
                            candidates = [
                                (buffer.find(sep), sep)
                                for sep in (b"\n\n", b"\r\n\r\n")
                                if sep in buffer
                            ]
                            end, separator = min(candidates)
                            block = bytes(buffer[:end])
                            del buffer[: end + len(separator)]
                            events += 1
                            if len(block) > MAX_EVENT or events > MAX_EVENTS:
                                raise ResponsesRefused()
                            lines = [
                                line[5:].lstrip(b" ")
                                for line in block.splitlines()
                                if line.startswith(b"data:")
                            ]
                            if not lines:
                                continue
                            event = json.loads(b"\n".join(lines))
                            if not isinstance(event, dict) or terminal is not None:
                                raise ResponsesRefused()
                            kind = event.get("type")
                            if kind in {"response.output_text.delta", "response.refusal.delta"}:
                                delta = event.get("delta")
                                if (
                                    not isinstance(delta, str)
                                    or len((full + delta).encode("utf-8")) > MAX_TEXT
                                ):
                                    raise ResponsesRefused()
                                full += delta
                                if on_token:
                                    await _emit(on_token, guard.feed(delta))
                            elif kind == "response.completed":
                                turn = self._parse_response(event.get("response"), model)
                                if turn.tool_calls or turn.content != full:
                                    raise ResponsesRefused()
                                terminal = turn
                            elif kind in {"error", "response.failed", "response.incomplete"}:
                                raise ResponsesRefused()
                        if len(buffer) > MAX_EVENT:
                            raise ResponsesRefused()
            self._accept_completion()
        except Exception as exc:
            note_provider_failure(self.profile.id, model, exc)
            return self.error
        if terminal is None or buffer.strip():
            return self.error
        # Accept only a bounded, fully closed stream; contradictory trailers and
        # close failures cannot publish usage for a rejected attempt.
        report_text_usage(terminal.usage)
        answer = self._finalize_cloud(full)
        if on_token:   # H393: withheld text reaches the bubble iff the answer is kept
            await _emit(on_token, guard.release(answer))
        return answer

    async def aclose(self):
        await self.client.aclose()
