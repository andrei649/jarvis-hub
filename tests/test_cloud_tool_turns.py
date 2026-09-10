"""Wave 0.1 of the Hermes absorption: tools stay alive on every backend that runs.

`supports_tools = True` used to exist exactly once in the repo — on `LMStudioBackend` — and
`AgentToolRuntime.can_run()` fails closed on that flag. The moment an agent routed to Claude,
Gemini, OpenRouter or even local Ollama, the model silently lost every governed tool and became
a chat model. These tests pin the fix: each backend declares the capability it actually has,
translates the runtime's one OpenAI-shaped dialect into its provider's own and back, funnels every
provider call through `parse_openai_tool_calls` (the single fail-closed boundary), and answers a
failure with a degraded `ToolTurn` instead of an exception.

Everything here is offline: fake clients and `httpx.MockTransport` only.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.anthropic import ANTHROPIC_API_BASE, ClaudeBackend
from agents.core.llm.auth_rotation import AuthProfilePool
from agents.core.llm.base import THINKING_EXHAUSTED_REPLY, OllamaBackend, is_degraded_reply
from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.provider_errors import GEMINI_DEGRADED_REPLY
from agents.core.llm.tool_dialects import (
    SYNTHETIC_ID_PREFIX,
    anthropic_messages,
    gemini_contents,
    gemini_schema,
    is_synthetic_id,
    normalize_finish_reason,
)
from agents.core.llm.tool_protocol import ToolCall, ToolSpec, ToolTurn
from agents.core.llm.vlm import VLMBackend
from agents.core.security.guardrails import GuardrailsEngine
from agents.core.tool_rpc import ToolRPCServer

ECHO = ToolSpec(
    name="echo",
    description="Echo one value.",
    input_schema={
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    },
)

# The exact shape `AgentToolRuntime._run_loop` builds after one executed call.
LOOP_MESSAGES = [
    {"role": "system", "content": "You are Nerva."},
    {"role": "user", "content": "echo hi"},
    {
        "role": "assistant",
        "content": "calling echo",
        "tool_calls": [
            {
                "id": "call-echo",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"value":"hi"}'},
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "call-echo",
        "content": '{"ok": true, "tool": "echo", "result": {"echo": "hi"}}',
    },
]


# ── shared fakes ─────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status
        request = httpx.Request("POST", "https://provider.test/")
        self._response = httpx.Response(status, request=request)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self._response.request,
                response=self._response,
            )

    def json(self) -> Any:
        return self._data


class _Client:
    """Records every POST and answers from a scripted queue (last one repeats)."""

    def __init__(self, *responses: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)

    async def post(self, url: str, json: Any = None, headers: Any = None) -> _Resp:
        self.calls.append({"url": url, "json": json, "headers": headers})
        response = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, _Resp):
            return response
        return _Resp(response)

    async def aclose(self) -> None:
        return None


class _KeyedClient:
    """Answers per API key so auth-pool failover is observable."""

    def __init__(self, header: str, statuses: dict[str, int], data: Any) -> None:
        self._header = header
        self._statuses = statuses
        self._data = data
        self.keys: list[str] = []

    async def post(self, url: str, json: Any = None, headers: Any = None) -> _Resp:
        key = headers[self._header]
        self.keys.append(key)
        return _Resp(self._data, self._statuses.get(key, 200))

    async def aclose(self) -> None:
        return None


def _openrouter(*responses: Any) -> tuple[OpenRouterBackend, _Client]:
    client = _Client(*responses)
    return OpenRouterBackend(api_key="sk-or-test", client=client), client


def _claude(*responses: Any, auth_pool=None) -> tuple[ClaudeBackend, _Client]:
    backend = ClaudeBackend.__new__(ClaudeBackend)
    backend.api_key = "sk-ant-test"
    backend.model = "claude-test"
    backend.auth_pool = auth_pool
    # H364 — the fixture bypasses __init__, so it has to mirror it: no effort
    # asked for, no overrides. "claude-test" is not a known family either, so
    # nothing is added to or removed from these payloads.
    backend.reasoning_effort = ""
    backend.effort_overrides = {}
    backend.client = _Client(*responses)
    return backend, backend.client


def _gemini(*responses: Any, auth_pool=None) -> tuple[GeminiBackend, _Client]:
    backend = GeminiBackend(api_key="gm-test", auth_pool=auth_pool)
    backend.client = _Client(*responses)
    return backend, backend.client


def _ollama(*responses: Any) -> tuple[OllamaBackend, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append({"path": request.url.path, "json": json.loads(request.content)})
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(response, Exception):
            raise response
        return httpx.Response(200, json=response, request=request)

    backend = OllamaBackend.__new__(OllamaBackend)
    backend.base_url = "http://ollama.test"
    backend.client = httpx.AsyncClient(
        base_url=backend.base_url, transport=httpx.MockTransport(handler)
    )
    return backend, requests


def _openai_choice(content: str = "", tool_calls: Any = None, finish: str = "stop") -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": finish}]}


def _claude_reply(*blocks: dict, stop_reason: str = "end_turn", usage: dict | None = None) -> dict:
    reply = {"content": list(blocks), "stop_reason": stop_reason}
    if usage is not None:
        reply["usage"] = usage
    return reply


def _gemini_reply(*parts: dict, finish: str = "STOP") -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}, "finishReason": finish}]}


def _ollama_reply(content: str = "", tool_calls: Any = None, done_reason: str = "stop") -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"message": message, "done": True, "done_reason": done_reason}


async def _turn(backend, messages=None, tools=(ECHO,), max_tokens: int = 256) -> ToolTurn:
    return await backend.generate_tool_turn(
        model="model-x",
        messages=messages if messages is not None else LOOP_MESSAGES,
        tools=list(tools),
        max_tokens=max_tokens,
        temperature=0.2,
    )


# ── the capability is declared where it exists — and only there ──────────────


def _backends() -> list[tuple[str, Any]]:
    return [
        ("openrouter", _openrouter(_openai_choice("x"))[0]),
        ("ollama", _ollama(_ollama_reply("x"))[0]),
        ("claude", _claude(_claude_reply())[0]),
        ("gemini", _gemini(_gemini_reply())[0]),
    ]


@pytest.mark.parametrize("name,backend", _backends(), ids=lambda value: value if isinstance(value, str) else "")
def test_every_running_backend_declares_tool_support(name, backend):
    assert backend.supports_tools is True, name


def test_vision_backend_stays_a_vision_backend():
    assert VLMBackend.supports_tools is False


@pytest.mark.parametrize("name,backend", _backends(), ids=lambda value: value if isinstance(value, str) else "")
def test_runtime_gate_opens_for_every_running_backend(name, backend):
    """`can_run` is the gate that used to close on every cloud route."""
    server = ToolRPCServer()
    server.register_tool("echo", lambda args: args)
    runtime = AgentToolRuntime(server, enabled=lambda: True)

    assert runtime.can_run(backend) is True, name
    # Guardrails wrap the backend on the real path and must forward the truth.
    assert GuardrailsEngine(backend).supports_tools is True, name


# ── OpenRouter: the OpenAI dialect, verbatim ─────────────────────────────────


@pytest.mark.asyncio
async def test_openrouter_sends_tools_and_parses_calls():
    backend, client = _openrouter(
        _openai_choice(
            "thinking <think>secret</think>done",
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"value": "hi"}'},
                }
            ],
            finish="tool_calls",
        )
    )

    turn = await _turn(backend, max_tokens=0)

    request = client.calls[0]
    assert request["url"] == "/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer sk-or-test"
    assert request["json"]["messages"] == LOOP_MESSAGES
    assert request["json"]["tools"] == [ECHO.as_openai()]
    assert request["json"]["tool_choice"] == "auto"
    assert request["json"]["max_tokens"] > 0  # auto → a concrete cloud ceiling
    assert request["json"]["stream"] is False
    assert turn.content == "thinking done"
    assert turn.finish_reason == "tool_calls"
    assert turn.tool_calls == (
        ToolCall(
            id="call_1",
            name="echo",
            raw_arguments='{"value": "hi"}',
            arguments={"value": "hi"},
        ),
    )


@pytest.mark.asyncio
async def test_openrouter_malformed_call_fails_closed_not_open():
    backend, _client = _openrouter(
        _openai_choice("", [{"id": "c", "type": "function", "function": {"name": "echo", "arguments": {"value": 1}}}])
    )

    turn = await _turn(backend)

    assert turn.tool_calls[0].parse_error == "arguments_not_string"
    assert turn.tool_calls[0].arguments is None


@pytest.mark.asyncio
async def test_openrouter_omits_tools_when_none_are_offered():
    backend, client = _openrouter(_openai_choice("plain"))

    turn = await _turn(backend, tools=())

    assert "tools" not in client.calls[0]["json"]
    assert "tool_choice" not in client.calls[0]["json"]
    assert turn == ToolTurn(content="plain", finish_reason="stop")


@pytest.mark.asyncio
async def test_openrouter_failure_is_a_degraded_turn_not_an_exception():
    backend, _client = _openrouter(RuntimeError("network down"))

    turn = await _turn(backend)

    assert turn.tool_calls == ()
    assert turn.content == "[OpenRouter error]"


# ── Ollama: /api/chat, object arguments, no ids ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_turn", [False, True], ids=["generate", "chat"])
@pytest.mark.parametrize("reasoning_fields", [
    {"thinking": "PRIVATE-REASONING"},
    {"reasoning_content": "PRIVATE-REASONING"},
    {"thinking": "", "reasoning_content": "PRIVATE-REASONING"},
], ids=["native", "proxy", "proxy-with-empty-native"])
async def test_ollama_exhausted_thinking_is_a_degraded_reply(
    tool_turn, reasoning_fields, caplog,
):
    """A length stop with only reasoning must not become a successful blank reply."""
    if tool_turn:
        payload = _ollama_reply(done_reason="length")
        payload["message"].update(reasoning_fields)
    else:
        payload = {"response": "", "done": True, "done_reason": "length", **reasoning_fields}
    backend, _requests = _ollama(payload)
    try:
        if tool_turn:
            turn = await _turn(backend)
            answer = turn.content
            assert turn.tool_calls == ()
            assert turn.finish_reason == "length"
        else:
            answer = await backend.generate("model-x", "A hard question")
    finally:
        await backend.client.aclose()

    assert answer == THINKING_EXHAUSTED_REPLY
    assert is_degraded_reply(answer)
    assert "PRIVATE-REASONING" not in answer
    assert "PRIVATE-REASONING" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_turn", [False, True], ids=["generate", "chat"])
@pytest.mark.parametrize("content,reasoning,finish,expected", [
    ("", None, "length", ""),
    ("", " \n\t", "length", ""),
    ("<think>PRIVATE-REASONING</think>Visible answer.", "PRIVATE-REASONING", "length", "Visible answer."),
    ("", "PRIVATE-REASONING", "stop", ""),
    ("", "PRIVATE-REASONING", None, ""),
], ids=["no-reasoning", "blank-reasoning", "visible-answer", "clean-stop", "missing-stop"])
async def test_ollama_nonexhausted_reply_behavior_is_preserved(
    tool_turn, content, reasoning, finish, expected,
):
    """The exhaustion guard must not expose reasoning or relabel another outcome."""
    if tool_turn:
        payload = _ollama_reply(content, done_reason=finish)
        payload["message"]["thinking"] = reasoning
    else:
        payload = {"response": content, "thinking": reasoning, "done": True, "done_reason": finish}
    backend, _requests = _ollama(payload)
    try:
        answer = (await _turn(backend)).content if tool_turn else await backend.generate("model-x", "Question")
    finally:
        await backend.client.aclose()

    assert answer == expected
    assert not is_degraded_reply(answer)
    assert "PRIVATE-REASONING" not in answer


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,parse_error", [
    ({"value": "hi"}, None),
    (["malformed"], "arguments_not_object"),
], ids=["valid-call", "malformed-call"])
async def test_ollama_tool_calls_are_not_replaced_by_exhausted_thinking(arguments, parse_error):
    payload = _ollama_reply("", [{"function": {"name": "echo", "arguments": arguments}}], "length")
    payload["message"]["thinking"] = "PRIVATE-REASONING"
    backend, _requests = _ollama(payload)
    try:
        turn = await _turn(backend)
    finally:
        await backend.client.aclose()

    assert turn.content == ""
    assert turn.finish_reason == "length"
    (call,) = turn.tool_calls
    assert call.name == "echo"
    assert call.parse_error == parse_error
    assert call.arguments == (arguments if parse_error is None else None)


@pytest.mark.asyncio
async def test_ollama_tool_turn_uses_chat_endpoint_and_translates_history():
    backend, requests = _ollama(
        _ollama_reply(
            "<think>plan</think>Let me check.",
            [{"function": {"name": "echo", "arguments": {"value": "hi"}}}],
        )
    )

    turn = await _turn(backend, max_tokens=0)

    request = requests[0]
    assert request["path"] == "/api/chat"
    body = request["json"]
    assert body["model"] == "model-x"
    assert body["stream"] is False
    assert body["tools"] == [ECHO.as_openai()]
    assert body["options"] == {"num_predict": -1, "temperature": 0.2}
    assert body["messages"][0] == {"role": "system", "content": "You are Nerva."}
    assert body["messages"][1] == {"role": "user", "content": "echo hi"}
    # OpenAI's JSON-string arguments become Ollama's object arguments on replay …
    assert body["messages"][2]["tool_calls"] == [
        {"id": "call-echo", "function": {"name": "echo", "arguments": {"value": "hi"}}}
    ]
    # … and the tool result names the function Ollama's template expects.
    assert body["messages"][3] == {
        "role": "tool",
        "content": LOOP_MESSAGES[3]["content"],
        "tool_name": "echo",
        "tool_call_id": "call-echo",
    }

    assert turn.content == "Let me check."
    assert turn.finish_reason == "stop"
    (call,) = turn.tool_calls
    assert is_synthetic_id(call.id)
    assert call.name == "echo"
    assert call.arguments == {"value": "hi"}
    assert call.parse_error is None


@pytest.mark.asyncio
async def test_ollama_keeps_provider_ids_and_rejects_malformed_calls():
    backend, _requests = _ollama(
        _ollama_reply(
            "",
            [
                {"id": "ollama-7", "function": {"name": "echo", "arguments": {"value": "a"}}},
                {"function": {"name": "echo", "arguments": ["not", "an", "object"]}},
                "garbage",
            ],
        )
    )

    turn = await _turn(backend)

    kept, malformed, garbage = turn.tool_calls
    assert kept.id == "ollama-7" and kept.arguments == {"value": "a"}
    assert malformed.parse_error == "arguments_not_object"
    assert garbage.parse_error == "call_not_object"


@pytest.mark.asyncio
async def test_ollama_tool_calls_that_are_not_a_list_fail_closed():
    backend, _requests = _ollama(_ollama_reply("", {"function": {"name": "echo"}}))

    turn = await _turn(backend)

    assert [call.parse_error for call in turn.tool_calls] == ["tool_calls_not_array"]


@pytest.mark.asyncio
async def test_ollama_unreachable_is_a_degraded_turn_not_an_exception():
    backend, _requests = _ollama(httpx.ConnectError("refused"))

    turn = await _turn(backend)

    assert turn.tool_calls == ()
    assert is_degraded_reply(turn.content)
    assert "Ollama" in turn.content


@pytest.mark.asyncio
async def test_ollama_runs_the_governed_loop_end_to_end():
    """The claim of the wave, on the local backend that used to be excluded."""
    handled = []
    server = ToolRPCServer()

    async def echo(args):
        handled.append(args)
        return {"echo": args["value"]}

    server.register_tool("echo", echo, description="Echo.", input_schema=ECHO.input_schema)
    backend, requests = _ollama(
        _ollama_reply("", [{"function": {"name": "echo", "arguments": {"value": "hi"}}}]),
        _ollama_reply("Echo completed"),
    )
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    assert runtime.can_run(backend) is True

    answer = await runtime.run(
        agent_id="nerva",
        backend=backend,
        model="model-x",
        prompt="echo hi",
        system="You are Nerva.",
        max_tokens=256,
        temperature=0.2,
    )

    assert answer == "Echo completed"
    assert handled == [{"value": "hi"}]
    second = requests[1]["json"]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["function"] == {"name": "echo", "arguments": {"value": "hi"}}
    assert second[-1]["role"] == "tool" and second[-1]["tool_name"] == "echo"
    assert json.loads(second[-1]["content"]) == {"ok": True, "tool": "echo", "result": {"echo": "hi"}}


# ── Claude: blocks in, blocks out ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_claude_translates_the_loop_into_messages_api_blocks():
    backend, client = _claude(
        _claude_reply(
            {"type": "text", "text": "Checking. "},
            {"type": "tool_use", "id": "toolu_01", "name": "echo", "input": {"value": "hi"}},
            {"type": "text", "text": "<think>x</think>Done."},
            stop_reason="tool_use",
        )
    )

    turn = await _turn(backend)

    request = client.calls[0]
    assert request["url"] == f"{ANTHROPIC_API_BASE}/messages"
    assert request["headers"]["x-api-key"] == "sk-ant-test"
    body = request["json"]
    assert body["model"] == "model-x"
    # H363: the two things that do not change between the turns of one session go
    # out as a marked cacheable prefix. The system prompt has to become a block to
    # carry the mark at all; the tool array takes one mark on its last entry,
    # because `cache_control` covers everything before it.
    assert body["system"] == [
        {"type": "text", "text": "You are Nerva.",
         "cache_control": {"type": "ephemeral"}},
    ]
    assert body["tools"] == [
        {"name": "echo", "description": "Echo one value.", "input_schema": ECHO.input_schema,
         "cache_control": {"type": "ephemeral"}}
    ]
    assert body["tool_choice"] == {"type": "auto"}
    assert body["messages"] == [
        {"role": "user", "content": "echo hi"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "calling echo"},
                {"type": "tool_use", "id": "call-echo", "name": "echo", "input": {"value": "hi"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-echo",
                    "content": LOOP_MESSAGES[3]["content"],
                }
            ],
        },
    ]

    assert turn.content == "Checking. Done."
    assert turn.finish_reason == "tool_calls"
    (call,) = turn.tool_calls
    assert call.id == "toolu_01" and call.name == "echo"
    assert call.arguments == {"value": "hi"}
    assert json.loads(call.raw_arguments) == {"value": "hi"}


@pytest.mark.asyncio
async def test_claude_merges_parallel_tool_results_into_one_user_turn():
    messages = LOOP_MESSAGES[:2] + [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "echo", "arguments": '{"value":"1"}'}},
                {"id": "b", "type": "function", "function": {"name": "echo", "arguments": "{malformed"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": "one"},
        {"role": "tool", "tool_call_id": "b", "content": "two"},
    ]
    backend, client = _claude(_claude_reply({"type": "text", "text": "ok"}))

    await _turn(backend, messages=messages)

    converted = client.calls[0]["json"]["messages"]
    assert [message["role"] for message in converted] == ["user", "assistant", "user"]
    # No empty text block (the API rejects them); malformed arguments replay as {}.
    assert converted[1]["content"] == [
        {"type": "tool_use", "id": "a", "name": "echo", "input": {"value": "1"}},
        {"type": "tool_use", "id": "b", "name": "echo", "input": {}},
    ]
    assert [block["tool_use_id"] for block in converted[2]["content"]] == ["a", "b"]


def test_claude_invalid_ids_are_replaced_consistently_on_both_sides():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "", "type": "function", "function": {"name": "echo", "arguments": "{}"}},
                {"id": "bad id!", "type": "function", "function": {"name": "echo", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "", "content": "r1"},
        {"role": "tool", "tool_call_id": "bad id!", "content": "r2"},
    ]

    _system, converted = anthropic_messages(messages)

    uses = [block["id"] for block in converted[1]["content"]]
    results = [block["tool_use_id"] for block in converted[2]["content"]]
    assert uses == results
    assert all(use and " " not in use and "!" not in use for use in uses)
    assert len(set(uses)) == 2


@pytest.mark.asyncio
async def test_claude_malformed_input_fails_closed():
    backend, _client = _claude(
        _claude_reply({"type": "tool_use", "id": "toolu_02", "name": "echo", "input": ["nope"]})
    )

    turn = await _turn(backend)

    assert turn.tool_calls[0].parse_error == "arguments_not_object"


@pytest.mark.asyncio
async def test_claude_tool_turn_fails_over_across_the_auth_pool():
    pool = AuthProfilePool(["k1", "k2"], "anthropic")
    backend, _client = _claude(auth_pool=pool)
    backend.client = _KeyedClient("x-api-key", {"k1": 429}, _claude_reply({"type": "text", "text": "hi"}))

    turn = await _turn(backend)

    assert turn.content == "hi"
    assert backend.client.keys == ["k1", "k2"]
    assert pool.current_key() == "k2"


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason,expected", [("end_turn", "stop"), ("max_tokens", "length")])
async def test_claude_stop_reasons_use_the_shared_vocabulary(stop_reason, expected):
    backend, _client = _claude(_claude_reply({"type": "text", "text": "t"}, stop_reason=stop_reason))

    turn = await _turn(backend)

    assert turn.finish_reason == expected


@pytest.mark.asyncio
async def test_claude_failure_is_a_degraded_turn_not_an_exception():
    backend, _client = _claude(_Resp({"error": "nope"}, status=500))

    turn = await _turn(backend)

    assert turn.tool_calls == ()
    assert turn.content.startswith("[Claude API error")


# ── Gemini: function declarations, function calls, thought signatures ───────


@pytest.mark.asyncio
async def test_gemini_translates_the_loop_into_contents_and_declarations():
    backend, client = _gemini(
        _gemini_reply(
            {"text": "Checking."},
            {"functionCall": {"name": "echo", "args": {"value": "hi"}}, "thoughtSignature": "sig-1"},
        )
    )

    turn = await _turn(backend)

    request = client.calls[0]
    assert request["url"].endswith("/models/model-x:generateContent")
    assert request["headers"] == {"x-goog-api-key": "gm-test"}
    body = request["json"]
    assert body["systemInstruction"] == {"parts": [{"text": "You are Nerva."}]}
    assert "cachedContent" not in body
    assert body["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "echo",
                    "description": "Echo one value.",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                }
            ]
        }
    ]
    assert body["toolConfig"] == {"functionCallingConfig": {"mode": "AUTO"}}
    # `call-echo` is not a synthetic id, so it is treated as provider-minted and echoed.
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "echo hi"}]},
        {
            "role": "model",
            "parts": [
                {"text": "calling echo"},
                {"functionCall": {"name": "echo", "args": {"value": "hi"}, "id": "call-echo"}},
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "echo",
                        "response": {"ok": True, "tool": "echo", "result": {"echo": "hi"}},
                        "id": "call-echo",
                    }
                }
            ],
        },
    ]

    assert turn.content == "Checking."
    assert turn.finish_reason == "stop"
    (call,) = turn.tool_calls
    assert is_synthetic_id(call.id) and call.name == "echo"
    assert call.arguments == {"value": "hi"}


@pytest.mark.asyncio
async def test_gemini_echoes_thought_signatures_on_the_next_turn():
    backend, client = _gemini(
        _gemini_reply({"functionCall": {"name": "echo", "args": {}}, "thoughtSignature": "sig-9"}),
        _gemini_reply({"text": "done"}),
    )

    first = await _turn(backend, messages=LOOP_MESSAGES[:2])
    (call,) = first.tool_calls
    follow_up = LOOP_MESSAGES[:2] + [
        {"role": "assistant", "content": "", "tool_calls": [call.as_openai()]},
        {"role": "tool", "tool_call_id": call.id, "content": "plain text result"},
    ]

    second = await _turn(backend, messages=follow_up)

    contents = client.calls[1]["json"]["contents"]
    assert contents[1]["parts"] == [
        {"functionCall": {"name": "echo", "args": {}}, "thoughtSignature": "sig-9"}
    ]
    # A synthesized id is never sent back; a non-JSON result is wrapped.
    assert contents[2]["parts"] == [
        {"functionResponse": {"name": "echo", "response": {"result": "plain text result"}}}
    ]
    assert second.content == "done"


@pytest.mark.asyncio
async def test_gemini_keeps_provider_ids_and_defaults_missing_args():
    backend, _client = _gemini(_gemini_reply({"functionCall": {"id": "fc-1", "name": "echo"}}))

    turn = await _turn(backend)

    (call,) = turn.tool_calls
    assert call.id == "fc-1"
    assert call.arguments == {}


def test_gemini_provider_ids_round_trip_into_function_responses():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "fc-1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "fc-1", "content": "r"},
    ]

    _system, contents = gemini_contents(messages)

    assert contents[1]["parts"][0]["functionCall"]["id"] == "fc-1"
    assert contents[2]["parts"][0]["functionResponse"]["id"] == "fc-1"


@pytest.mark.asyncio
async def test_gemini_malformed_args_fail_closed():
    backend, _client = _gemini(_gemini_reply({"functionCall": {"name": "echo", "args": "text"}}))

    turn = await _turn(backend)

    assert turn.tool_calls[0].parse_error == "arguments_not_object"


@pytest.mark.asyncio
async def test_gemini_tool_turn_never_binds_a_cache():
    """The API refuses tools alongside cachedContent — a tool turn must not send one."""
    from agents.core.llm.auth_rotation import AuthLease
    from agents.core.llm.gemini_context import GeminiRequestBinding

    backend, client = _gemini(_gemini_reply({"text": "ok"}))
    binding = GeminiRequestBinding(
        lease=AuthLease(profile_id="p", api_key="scoped-key"),
        cache_name="cachedContents/abc",
        cached_prefix_count=3,
    )

    with backend.request_scope(binding):
        turn = await _turn(backend)

    body = client.calls[0]["json"]
    assert "cachedContent" not in body
    assert body["systemInstruction"] == {"parts": [{"text": "You are Nerva."}]}
    assert client.calls[0]["headers"] == {"x-goog-api-key": "scoped-key"}
    assert turn.content == "ok"


@pytest.mark.asyncio
async def test_gemini_tool_turn_fails_over_across_the_auth_pool():
    pool = AuthProfilePool(["g1", "g2"], "gemini")
    backend, _client = _gemini(auth_pool=pool)
    backend.client = _KeyedClient("x-goog-api-key", {"g1": 429}, _gemini_reply({"text": "hi"}))

    turn = await _turn(backend)

    assert turn.content == "hi"
    assert backend.client.keys == ["g1", "g2"]


@pytest.mark.asyncio
async def test_gemini_blocked_prompt_is_a_filtered_empty_turn():
    backend, _client = _gemini({"promptFeedback": {"blockReason": "SAFETY"}})

    turn = await _turn(backend)

    assert turn == ToolTurn(content="", finish_reason="content_filter")


@pytest.mark.asyncio
async def test_gemini_failure_is_a_degraded_turn_not_an_exception():
    backend, _client = _gemini(_Resp({"error": "nope"}, status=500))

    turn = await _turn(backend)

    assert turn == ToolTurn(content=GEMINI_DEGRADED_REPLY)


def test_gemini_schema_speaks_the_openapi_subset_gemini_accepts():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "format": "uri", "description": "Where."},
            "mode": {"type": ["string", "null"], "const": "fast"},
            "count": {"type": "integer", "minimum": 1, "exclusiveMaximum": 9},
            "tags": {"type": "array", "items": {"type": "string", "enum": ["a", 1]}},
            "choice": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            "empty": {"type": "object", "properties": {}},
        },
        "required": ["path", "ghost"],
    }

    assert gemini_schema(schema) == {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Where."},
            "mode": {"type": "string", "nullable": True, "enum": ["fast"]},
            "count": {"type": "integer", "minimum": 1},
            "tags": {"type": "array", "items": {"type": "string", "enum": ["a", "1"]}},
            "choice": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            "empty": {"type": "object"},
        },
        "required": ["path"],
    }


@pytest.mark.asyncio
async def test_gemini_omits_parameters_for_argument_free_tools():
    backend, client = _gemini(_gemini_reply({"text": "ok"}))
    bare = ToolSpec(name="ping", description="Ping.")

    await _turn(backend, tools=(bare,))

    declarations = client.calls[0]["json"]["tools"][0]["functionDeclarations"]
    assert declarations == [{"name": "ping", "description": "Ping."}]


# ── the shared vocabulary ────────────────────────────────────────────────────


def test_finish_reasons_normalize_and_never_raise():
    anthropic = {"end_turn": "stop", "tool_use": "tool_calls"}
    assert normalize_finish_reason(anthropic, "tool_use") == "tool_calls"
    assert normalize_finish_reason(anthropic, "SOMETHING_NEW") == "something_new"
    assert normalize_finish_reason(anthropic, None) is None
    assert normalize_finish_reason(anthropic, 7) is None


def test_synthetic_ids_are_recognizable_and_unique():
    from agents.core.llm.tool_dialects import synthetic_call_id

    first, second = synthetic_call_id(), synthetic_call_id()
    assert first != second
    assert first.startswith(SYNTHETIC_ID_PREFIX) and is_synthetic_id(first)
    assert not is_synthetic_id("toolu_01")
    assert not is_synthetic_id(SimpleNamespace())


# ── what the turn actually cost, from the provider (H363) ────────────────────

@pytest.mark.asyncio
async def test_the_providers_own_token_counts_come_back_on_the_turn():
    """The meter estimated because nothing carried the real numbers out.

    An estimate is fine for a budget check and wrong for a bill — and the cost
    table has always priced a `cached` rate that no Claude route could earn,
    because no request ever asked for caching and no response was ever read for it.
    """
    backend, _client = _claude(_claude_reply(
        {"type": "text", "text": "done"},
        usage={"input_tokens": 120, "output_tokens": 40,
               "cache_read_input_tokens": 9_000, "cache_creation_input_tokens": 300},
    ))

    turn = await _turn(backend)

    assert turn.usage.reported is True
    assert turn.usage.as_dict() == {
        "input_tokens": 120, "output_tokens": 40,
        "cache_read": 9_000, "cache_write": 300,
    }


@pytest.mark.asyncio
async def test_a_reply_with_no_usage_reads_as_unreported_not_as_free():
    """Zero has to mean "the provider said nothing", so a caller can fall back."""
    backend, _client = _claude(_claude_reply({"type": "text", "text": "done"}))

    turn = await _turn(backend)

    assert turn.usage.reported is False
    assert turn.usage.as_dict() == {
        "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("hostile", [
    {"input_tokens": -5},
    {"input_tokens": "lots"},
    {"input_tokens": None},
    {"cache_read_input_tokens": 1e400},
    {"input_tokens": {"nested": 1}},
])
async def test_a_nonsense_usage_block_cannot_report_a_negative_bill(hostile):
    """A parsed response body is outside the box; the meter is downstream of it."""
    backend, _client = _claude(_claude_reply(
        {"type": "text", "text": "done"}, usage=hostile))

    turn = await _turn(backend)

    assert all(value >= 0 for value in turn.usage.as_dict().values())


@pytest.mark.asyncio
async def test_usage_that_is_not_a_mapping_is_ignored_rather_than_raising():
    backend, _client = _claude({"content": [{"type": "text", "text": "d"}],
                                "stop_reason": "end_turn", "usage": "nope"})

    turn = await _turn(backend)

    assert turn.usage.reported is False


@pytest.mark.asyncio
async def test_a_turn_with_no_tools_still_marks_the_system_prompt():
    """The system prompt is the big stable thing even when nothing is offered."""
    backend, client = _claude(_claude_reply({"type": "text", "text": "done"}))

    await backend.generate_tool_turn(
        model="model-x", messages=list(LOOP_MESSAGES), tools=[],
        max_tokens=64, temperature=0.0,
    )

    body = client.calls[0]["json"]
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "tools" not in body


# ── the meter finally hears the provider (H363) ──────────────────────────────

def test_a_cache_write_is_billed_as_input_and_never_reported_as_a_saving():
    """A write costs a premium over plain input. It is not a discount.

    Counting it as `cached` would report a saving on the one thing that costs
    MORE. The known cost of this choice is stated where it is made: the price
    table has no write rate, so the write is billed at the plain input rate and
    the bill reads slightly low — the safe direction.
    """
    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.orchestrator import _billable_from_usage

    billable, output, cached = _billable_from_usage(
        TokenUsage(input_tokens=100, output_tokens=20, cache_read=800, cache_write=400))

    assert billable == 1_300, "uncached + read + write is what the request sent"
    assert output == 20
    assert cached == 800, "only the read is discounted"


def test_nothing_reported_falls_back_rather_than_billing_zero():
    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.orchestrator import _billable_from_usage

    assert _billable_from_usage(None) is None
    assert _billable_from_usage(TokenUsage()) is None


def test_usage_sums_across_the_several_requests_one_answer_takes():
    """A tool loop is many requests. The turn cost the sum, not the last one."""
    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.orchestrator import _sum_usage

    running = None
    for _ in range(3):
        running = _sum_usage(running, TokenUsage(
            input_tokens=10, output_tokens=4, cache_read=90, cache_write=1))

    assert running.as_dict() == {
        "input_tokens": 30, "output_tokens": 12, "cache_read": 270, "cache_write": 3,
    }


@pytest.mark.asyncio
async def test_the_guardrail_wrapper_does_not_drop_the_usage_it_did_not_scan():
    """`dataclasses.replace` keeps it — but nothing said so until this test.

    The scan rewrites content and tool calls. If it ever rebuilt the turn instead,
    the meter would silently go back to estimating on every guarded route, which is
    every cloud route.
    """
    from agents.core.security.guardrails import GuardrailsEngine, bind_guardrails

    backend, _client = _claude(_claude_reply(
        {"type": "text", "text": "done"},
        usage={"input_tokens": 7, "output_tokens": 2, "cache_read_input_tokens": 70},
    ))
    guarded = bind_guardrails(GuardrailsEngine(backend=None), backend)

    turn = await guarded.generate_tool_turn(
        model="model-x", messages=list(LOOP_MESSAGES), tools=[ECHO],
        max_tokens=64, temperature=0.0,
    )

    assert turn.usage.as_dict() == {
        "input_tokens": 7, "output_tokens": 2, "cache_read": 70, "cache_write": 0,
    }
