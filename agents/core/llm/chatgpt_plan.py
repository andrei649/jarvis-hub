"""Owner web chat using a selected ChatGPT plan model on the public Responses API."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass

import httpx

from agents.core import chatgpt_connection
from agents.core.action_origin import DEFAULT_ACTION_ORIGIN, current_action_origin
from agents.core.chat_cloud_history import (
    check_cloud_call,
    check_physical_destination,
    web_turn_active,
)
from agents.core.tls_trust import verify_for
from agents.core.turn_usage import physical_transport_entry, record_dispatch

from . import data_handling
from .data_handling import DataHandlingRefused
from .egress import _record, llm_async_client, mark_custom_request
from .providers import DEFAULT_REGISTRY
from .responses import ENDPOINT, TIMEOUT, ResponsesBackend
from .responses_dialect import ResponsesRefused, encoded, parse_response, text

_PROVIDER = "chatgpt-plan"


@dataclass
class _Send:
    backend: ChatGPTPlanBackend
    task: asyncio.Task
    payload: dict
    body: bytes
    used: bool = False


_send: ContextVar[_Send | None] = ContextVar("chatgpt_plan_text_send", default=None)


class _PlanTransport(httpx.AsyncBaseTransport):
    """Present the credential only after policy hooks, to the exact prepared send."""

    def __init__(self, backend, inner):
        self.backend = backend
        self.inner = inner

    async def handle_async_request(self, request):
        try:
            send = _send.get()
            if (send is None or send.used or send.backend is not self.backend or send.task is not asyncio.current_task()
                    or request.method != "POST" or str(request.url) != ENDPOINT or request.content != send.body):
                raise DataHandlingRefused("ChatGPT plan request changed before dispatch")
            await data_handling.check_physical_request(request)
            self.backend._require_turn(self.backend.model)
            check_physical_destination(request)
            token = chatgpt_connection.access_for_chat(self.backend.model, self.backend.generation)
            wire = httpx.Request("POST", ENDPOINT, content=send.body, headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                "Accept": "text/event-stream", "Accept-Encoding": "identity",
            }, extensions={"timeout": request.extensions["timeout"]})
            send.used = True
        except Exception:
            _record(_PROVIDER, request, allowed=False, reason="plan request refused before transport")
            raise

        entry = physical_transport_entry(request)
        try:
            return await self.inner.handle_async_request(wire)
        finally:
            # Keep the token off the client-level request, response hooks and diagnostics.
            wire.headers.pop("authorization", None)
            _record(_PROVIDER, request, allowed=True)
            record_dispatch(_PROVIDER, request, entry=entry)

    async def aclose(self):
        await self.inner.aclose()


async def _account_at_transport(request):
    # This credential-owning transport records dispatch after its final local check.
    mark_custom_request(request)


class ChatGPTPlanBackend(ResponsesBackend):
    supports_tools = False
    error = "[OpenAI Responses error: ChatGPT plan request could not be completed]"

    def __init__(self, model, generation, *, transport=None):
        if not isinstance(model, str) or not model or not isinstance(generation, str) or not generation:
            raise ResponsesRefused()
        if transport is None:
            trust = verify_for(_PROVIDER, ENDPOINT)
            if trust is False:
                raise DataHandlingRefused("ChatGPT plan requires verified TLS")
            transport = httpx.AsyncHTTPTransport(verify=trust, trust_env=False, retries=0)
        elif type(transport) is not httpx.MockTransport:
            raise ResponsesRefused()
        self.model = model
        self.generation = generation
        self.profile = DEFAULT_REGISTRY.get(_PROVIDER)
        self._client = llm_async_client(
            _PROVIDER, transport=_PlanTransport(self, transport), timeout=TIMEOUT,
            follow_redirects=False, trust_env=False, event_hooks={"request": [_account_at_transport]},
        )

    @property
    def endpoint(self):
        return ENDPOINT

    def context_window(self, model):
        # The account catalog does not declare a context length.
        return None

    def _require_turn(self, model):
        from agents.core.orchestrator import current_principal

        principal = current_principal()
        if (not web_turn_active() or not data_handling.physical_request_guard_active()
                or principal is None or principal.channel != "web" or not principal.admin
                or current_action_origin() != DEFAULT_ACTION_ORIGIN or model != self.model):
            raise DataHandlingRefused("ChatGPT plan requires an owner web turn for the selected model")
        target = data_handling.resolve(None, self, model)
        check_cloud_call(target, model)

    async def _prepared_payload(self, model, messages, max_tokens, temperature, tools=()):
        send = _send.get()
        if send is None or send.backend is not self or send.task is not asyncio.current_task() or tools:
            raise DataHandlingRefused("ChatGPT plan requires a prepared text turn")
        return send.payload, self.profile

    def _headers(self, profile=None):
        return {"Content-Type": "application/json", "Accept": "text/event-stream", "Accept-Encoding": "identity"}

    def _parse_response(self, value, model):
        if not isinstance(value, dict) or value.get("model") != model:
            raise ResponsesRefused()
        output = value.get("output")
        if not isinstance(output, list) or len(output) > 256:
            raise ResponsesRefused()
        # Reasoning summaries and encrypted items are neither answer text nor replay state.
        visible = [row for row in output if not isinstance(row, dict) or row.get("type") != "reasoning"]
        return parse_response({**value, "output": visible})

    def _accept_completion(self):
        self._require_turn(self.model)
        send = _send.get()
        if send is None or not send.used:
            raise DataHandlingRefused("ChatGPT plan turn is no longer active")
        check_physical_destination(httpx.Request("POST", ENDPOINT, content=send.body))
        chatgpt_connection.access_for_chat(self.model, self.generation)

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        return await self.generate_stream(model, prompt, system, max_tokens, temperature)

    async def generate_stream(self, model, prompt, system="", max_tokens=1024, temperature=0.7, on_token=None):
        self._require_turn(model)
        payload = {"model": model, "instructions": text(system) or "You are Nerva.",
                   "input": [{"role": "user", "content": text(prompt)}], "store": False, "stream": True}
        binding = _send.set(_Send(self, asyncio.current_task(), payload, encoded(payload)))
        try:
            return await super().generate_stream(model, prompt, system, max_tokens, temperature, on_token)
        finally:
            _send.reset(binding)

    async def generate_tool_turn(self, model, messages, tools, max_tokens=1024, temperature=0.7):
        raise DataHandlingRefused("ChatGPT plan supports text chat only")
