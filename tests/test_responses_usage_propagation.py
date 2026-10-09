"""Responses counter availability reaches accepted OpenAI and xAI calls."""

import json
from contextlib import nullcontext

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.provider_replay import replay_scope
from agents.core.llm.responses import ResponsesBackend
from agents.core.llm.xai import XAIBackend
from agents.core.orchestrator import _billable_from_usage, _sum_usage
from agents.core.tool_rpc import ToolRPCServer
from tests.test_openai_responses import Chunks, sse
from tests.test_text_usage_propagation import agent_for


def _response(usage, *, answer="answer", calls=(), reasoning=False):
    output = []
    if reasoning:
        output.append({"type": "reasoning", "id": "reason-one", "status": "completed",
                       "summary": [], "encrypted_content": "fixture-ciphertext"})
    if answer:
        output.append({"type": "message", "id": "message-one", "status": "completed",
                       "role": "assistant", "content": [{"type": "output_text", "text": answer}]})
    output.extend(calls)
    row = {"status": "completed", "output": output}
    if usage is not None:
        row["usage"] = usage
    return row


def _backend(provider, handler):
    transport = httpx.MockTransport(handler)
    return (ResponsesBackend("fixture", transport=transport) if provider == "openai"
            else XAIBackend("fixture", transport=transport))


def _scope(provider):
    return replay_scope() if provider == "xai" else nullcontext()


def _counts(*, input_tokens=100, output_tokens=7, cached_tokens=60,
            cache_write_tokens=0, total_tokens=107):
    value = {"input_tokens": input_tokens, "output_tokens": output_tokens,
             "input_tokens_details": {"cached_tokens": cached_tokens,
                                      "cache_write_tokens": cache_write_tokens}}
    if total_tokens is not None:
        value["total_tokens"] = total_tokens
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("openai", "gpt-4.1"), ("xai", "grok-4.6")])
@pytest.mark.parametrize(
    "usage,expected,complete",
    [
        (_counts(), (40, 7, 60), True),
        (_counts(input_tokens=0, output_tokens=0, cached_tokens=0, total_tokens=0), (0, 0, 0), True),
        (_counts(total_tokens=None), (40, 7, 60), True),
        (_counts(cache_write_tokens=1), (40, 7, 60), False),
        ({"input_tokens": 100, "output_tokens": 7,
          "input_tokens_details": {"cached_tokens": 60}}, (40, 7, 60), False),
        (_counts(total_tokens=999), (40, 7, 60), False),
        ({"input_tokens": 100, "input_tokens_details": {"cached_tokens": 60,
          "cache_write_tokens": 0}}, (40, 0, 60), False),
        ({"output_tokens": 7}, (0, 7, 0), False),
        ({}, (0, 0, 0), False),
    ],
    ids=["complete", "all-zero", "absent-total", "positive-write", "unknown-write",
         "contradictory-total", "missing-output", "missing-input", "unavailable"],
)
async def test_accepted_text_preserves_numeric_split_and_availability(
    provider, model, usage, expected, complete,
):
    sent = []

    def handler(request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json=_response(usage))

    backend = _backend(provider, handler)
    events = []
    try:
        with _scope(provider):
            answer = await agent_for().generate_response(
                backend, model, "hello", "", 128, .2, usage_sink=events.append,
            )
        assert answer == "answer" and len(sent) == 1
        assert sent[0][0] == ("https://api.openai.com/v1/responses" if provider == "openai"
                              else "https://api.x.ai/v1/responses")
        assert len(events) == 1
        item = events[0]
        assert (item.input_tokens, item.output_tokens, item.cache_read) == expected
        assert item.cache_write == 0 and item.counts_complete is complete
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("openai", "gpt-4.1"), ("xai", "grok-4.6")])
@pytest.mark.parametrize(
    "usage,expected,complete",
    [
        (_counts(), (40, 7, 60), True),
        (_counts(input_tokens=0, output_tokens=0, cached_tokens=0, total_tokens=0), (0, 0, 0), True),
        ({"input_tokens": 100, "output_tokens": 7,
          "input_tokens_details": {"cached_tokens": 60}}, (40, 7, 60), False),
        (_counts(cache_write_tokens=5), (40, 7, 60), False),
        ({"input_tokens": 100}, (100, 0, 0), False),
        ({}, (0, 0, 0), False),
    ],
    ids=["complete", "all-zero", "unknown-write", "positive-write", "partial", "unavailable"],
)
async def test_structured_runtime_forwards_observation(provider, model, usage, expected, complete):
    sent = []

    def handler(request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json=_response(usage))

    backend = _backend(provider, handler)
    server = ToolRPCServer()
    server.register_tool("unused", lambda args: pytest.fail("unexpected tool execution"),
                         input_schema={"type": "object", "properties": {}})
    events = []
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="trusted-athena", backend=backend, model=model, prompt="hello",
            usage_sink=events.append,
        )
        assert answer == "answer" and len(sent) == 1
        assert sent[0][0].endswith("/responses") and sent[0][1]["tools"]
        assert len(events) == 1
        item = events[0]
        assert (item.input_tokens, item.output_tokens, item.cache_read) == expected
        assert item.cache_write == 0 and item.counts_complete is complete
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("openai", "gpt-4.1"), ("xai", "grok-4.6")])
@pytest.mark.parametrize(
    "usage,expected,complete",
    [
        (_counts(), (40, 7, 60), True),
        (_counts(input_tokens=0, output_tokens=0, cached_tokens=0, total_tokens=0), (0, 0, 0), True),
        ({"input_tokens": 100, "output_tokens": 7,
          "input_tokens_details": {"cached_tokens": 60}}, (40, 7, 60), False),
        (_counts(total_tokens=999), (40, 7, 60), False),
        ({}, (0, 0, 0), False),
    ],
    ids=["complete", "all-zero", "unknown-write", "contradictory-total", "unavailable"],
)
async def test_validated_terminal_stream_forwards_observation(provider, model, usage, expected, complete):
    sent = []

    def handler(request):
        sent.append((str(request.url), json.loads(request.content)))
        events = [
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.completed", "response": _response(usage)},
        ]
        return httpx.Response(200, stream=Chunks(sse(*events), width=3))

    backend = _backend(provider, handler)
    events, tokens = [], []
    try:
        with _scope(provider):
            answer = await agent_for().generate_response(
                backend, model, "hello", "", 128, .2,
                on_token=tokens.append, usage_sink=events.append,
            )
        assert answer == "answer" and tokens == ["answer"] and len(sent) == 1
        assert sent[0][0].endswith("/responses") and sent[0][1]["stream"] is True
        assert len(events) == 1
        item = events[0]
        assert (item.input_tokens, item.output_tokens, item.cache_read) == expected
        assert item.cache_write == 0 and item.counts_complete is complete
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("openai", "gpt-4.1"), ("xai", "grok-4.6")])
async def test_later_unavailable_tool_reply_makes_aggregate_incomplete(provider, model):
    sent = []

    def handler(request):
        sent.append((str(request.url), json.loads(request.content)))
        if len(sent) == 1:
            call = {"type": "function_call", "id": "item-one", "status": "completed",
                    "call_id": "call-one", "name": "echo",
                    "arguments": '{"value":"hi"}'}
            return httpx.Response(200, json=_response(
                _counts(), answer="", calls=[call], reasoning=provider == "xai",
            ))
        return httpx.Response(200, json=_response(None))

    backend = _backend(provider, handler)
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args["value"]}

    server.register_tool("echo", echo)
    events = []
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="trusted-athena", backend=backend, model=model, prompt="hello",
            usage_sink=events.append,
        )
        assert answer == "answer" and len(sent) == 2
        assert all(path.endswith("/responses") for path, _ in sent)
        assert sent[1][1]["input"][-1]["call_id"] == "call-one"
        if provider == "xai":
            assert sent[1][1]["input"][2]["encrypted_content"] == "fixture-ciphertext"
        assert [item.counts_complete for item in events] == [True, False]
        aggregate = _sum_usage(*events)
        assert (aggregate.input_tokens, aggregate.output_tokens, aggregate.cache_read) == (40, 7, 60)
        assert aggregate.counts_complete is False and _billable_from_usage(aggregate) is None
    finally:
        await backend.aclose()
