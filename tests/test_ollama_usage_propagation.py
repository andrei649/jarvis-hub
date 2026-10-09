"""Observed Ollama counter availability reaches text, stream, and tool meters."""

import json

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.orchestrator import _billable_from_usage, _sum_usage
from agents.core.tool_rpc import ToolRPCServer
from tests.test_stream_token_usage import invoke
from tests.test_text_usage_propagation import agent_for, backend_for


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "counters,expected,complete",
    [
        ({"prompt_eval_count": 100_000}, (100_000, 0), False),
        ({"eval_count": 17}, (0, 17), False),
        ({}, (0, 0), False),
        ({"prompt_eval_count": 0, "eval_count": 0}, (0, 0), True),
        ({"prompt_eval_count": 123, "eval_count": 17}, (123, 17), True),
    ],
    ids=["input-only", "output-only", "unavailable", "valid-zero", "complete"],
)
async def test_accepted_generate_reports_counter_availability(counters, expected, complete):
    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        # Successful non-stream JSON has never required a done marker.
        return httpx.Response(200, json={"response": "answer", **counters})

    backend = await backend_for("ollama", handler)
    events = []
    try:
        answer = await agent_for().generate_response(
            backend, "local", "hello", "", 128, .2, usage_sink=events.append,
        )
        assert answer == "answer"
        assert len(events) == 1
        assert (events[0].input_tokens, events[0].output_tokens) == expected
        assert events[0].counts_complete is complete
        assert sent[0][0] == "/api/generate" and sent[0][1]["stream"] is False
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "counters,expected,complete",
    [
        ({"prompt_eval_count": 100_000}, (100_000, 0), False),
        ({}, (0, 0), False),
        ({"prompt_eval_count": 0, "eval_count": 0}, (0, 0), True),
        ({"prompt_eval_count": 123, "eval_count": 17}, (123, 17), True),
    ],
    ids=["input-only", "unavailable", "valid-zero", "complete"],
)
async def test_accepted_chat_runtime_forwards_counter_availability(counters, expected, complete):
    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={
            # The /api/chat tool route likewise accepts a successful JSON reply without done.
            "message": {"content": "answer"}, "done_reason": "stop", **counters,
        })

    backend = await backend_for("ollama", handler)
    events = []
    server = ToolRPCServer()
    server.register_tool("unused", lambda args: pytest.fail("unexpected tool execution"),
                         input_schema={"type": "object", "properties": {}})
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="local", prompt="hello",
            usage_sink=events.append,
        )
        assert answer == "answer"
        assert len(events) == 1
        assert (events[0].input_tokens, events[0].output_tokens) == expected
        assert events[0].counts_complete is complete
        assert sent[0][0] == "/api/chat" and sent[0][1]["stream"] is False
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "counters,expected,complete",
    [
        ({"prompt_eval_count": 100_000}, (100_000, 0), False),
        ({"eval_count": 17}, (0, 17), False),
        ({}, (0, 0), False),
        ({"prompt_eval_count": 0, "eval_count": 0}, (0, 0), True),
        ({"prompt_eval_count": 123, "eval_count": 17}, (123, 17), True),
    ],
    ids=["input-only", "output-only", "unavailable", "valid-zero", "complete"],
)
async def test_literal_terminal_stream_reports_counter_availability(counters, expected, complete):
    rows = [{"response": "answer", "done": False}, {"done": True, **counters}]
    answer, events, tokens, sent = await invoke("ollama", rows)
    assert answer == "answer" and tokens == ["answer"]
    assert len(events) == 1
    assert (events[0].input_tokens, events[0].output_tokens) == expected
    assert events[0].counts_complete is complete
    assert sent[0]["stream"] is True


@pytest.mark.asyncio
async def test_later_unavailable_ollama_tool_response_marks_aggregate_incomplete():
    sent = []

    def handler(request):
        assert request.url.path == "/api/chat"
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(200, json={
                "message": {"content": "", "tool_calls": [{
                    "id": "call-one", "type": "function",
                    "function": {"name": "echo", "arguments": {"value": "hi"}},
                }]},
                "done": True, "done_reason": "stop",
                "prompt_eval_count": 100_000, "eval_count": 7,
            })
        return httpx.Response(200, json={
            "message": {"content": "answer"}, "done": True, "done_reason": "stop",
        })

    backend = await backend_for("ollama", handler)
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args["value"]}

    server.register_tool("echo", echo)
    events = []
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="local", prompt="hello",
            usage_sink=events.append,
        )
        assert answer == "answer" and len(sent) == 2
        assert [event.counts_complete for event in events] == [True, False]
        aggregate = _sum_usage(*events)
        assert (aggregate.input_tokens, aggregate.output_tokens) == (100_000, 7)
        assert aggregate.counts_complete is False
        assert _billable_from_usage(aggregate) is None
    finally:
        await backend.aclose()
