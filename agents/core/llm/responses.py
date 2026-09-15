"""Opt-in API-key Responses backend, fixed to non-reasoning GPT-4.1 models."""

import asyncio
import json

from .base import LLMBackend, _emit, cloud_cap
from .egress import llm_async_client
from .provider_request import compatible_parameters
from .providers import DEFAULT_REGISTRY
from .request_context import ensure_reasoning_active
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


class ResponsesBackend(LLMBackend):
    supports_tools = True

    def __init__(self, api_key, *, retention="in_memory", transport=None):
        if not isinstance(retention, str) or retention not in {"in_memory", "24h"}:
            raise ResponsesRefused()
        self.api_key = api_key
        self.retention = retention
        self.profile = DEFAULT_REGISTRY.get("openai-responses")
        self.client = llm_async_client(
            "openai-responses",
            timeout=TIMEOUT,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def context_window(self, model):
        return 1047576 if model in MODELS else None

    def _payload(self, model, messages, max_tokens, temperature, tools=()):
        if not isinstance(model, str) or model not in MODELS:
            raise ResponsesRefused()
        payload = {
            "model": model,
            "input": input_items(messages),
            "store": False,
            "max_output_tokens": min(cloud_cap(max_tokens), 32768),
            "temperature": temperature,
            "prompt_cache_retention": self.retention,
        }
        payload.update(compatible_parameters(self.profile, model, None))
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

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        }

    async def _request(self, payload):
        async with asyncio.timeout(TIMEOUT):
            ensure_reasoning_active()
            async with self.client.stream(
                "POST", ENDPOINT, headers=self._headers(), content=encoded(payload)
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ResponsesRefused()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise ResponsesRefused()
                    data.extend(chunk)
                return parse_response(json.loads(data))

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        payload = self._payload(
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens,
            temperature,
        )
        try:
            turn = await self._request(payload)
            if turn.tool_calls:
                raise ResponsesRefused()
        except Exception:
            return ERROR
        report_text_usage(turn.usage)
        return self._finalize_cloud(turn.content)

    async def generate_tool_turn(self, model, messages, tools, max_tokens=1024, temperature=0.7):
        payload = self._payload(model, messages, max_tokens, temperature, tools)
        try:
            return await self._request(payload)
        except Exception:
            return ToolTurn(content=ERROR)

    async def generate_stream(
        self, model, prompt, system="", max_tokens=1024, temperature=0.7, on_token=None
    ):
        payload = self._payload(
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens,
            temperature,
        )
        payload["stream"] = True
        full, total, events = "", 0, 0
        buffer = bytearray()
        terminal = None
        try:
            async with asyncio.timeout(TIMEOUT):
                ensure_reasoning_active()
                async with self.client.stream(
                    "POST", ENDPOINT, headers=self._headers(), content=encoded(payload)
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
                                    await _emit(on_token, delta)
                            elif kind == "response.completed":
                                turn = parse_response(event.get("response"))
                                if turn.tool_calls or turn.content != full:
                                    raise ResponsesRefused()
                                terminal = turn
                            elif kind in {"error", "response.failed", "response.incomplete"}:
                                raise ResponsesRefused()
                        if len(buffer) > MAX_EVENT:
                            raise ResponsesRefused()
        except Exception:
            return ERROR
        if terminal is None or buffer.strip():
            return ERROR
        # Accept only a bounded, fully closed stream; contradictory trailers and
        # close failures cannot publish usage for a rejected attempt.
        report_text_usage(terminal.usage)
        return self._finalize_cloud(full)

    async def aclose(self):
        await self.client.aclose()
