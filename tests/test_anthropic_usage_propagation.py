"""Anthropic category availability survives accepted text, tool, and stream replies."""

import json

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.orchestrator import _billable_from_usage, _sum_usage
from agents.core.tool_rpc import ToolRPCServer
from tests.test_stream_token_usage import frames, invoke
from tests.test_text_usage_propagation import agent_for, backend_for

COMPLETE = {
    "input_tokens": 23, "output_tokens": 17,
    "cache_read_input_tokens": 90, "cache_creation_input_tokens": 10,
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected,complete",
    [
        (COMPLETE, (23, 17, 90, 10), True),
        (dict.fromkeys(COMPLETE, 0), (0, 0, 0, 0), True),
        ({"input_tokens": 23, "output_tokens": 17}, (23, 17, 0, 0), False),
        ({**COMPLETE, "cache_read_input_tokens": None}, (23, 17, 0, 10), False),
        ({"output_tokens": 17}, (0, 17, 0, 0), False),
        ({}, (0, 0, 0, 0), False),
    ],
    ids=["all-four", "all-zero", "optional-absent", "optional-null", "required-absent", "unavailable"],
)
async def test_accepted_text_preserves_answer_and_category_availability(raw, expected, complete):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer"}], "usage": raw,
        })

    backend = await backend_for("anthropic", handler)
    events = []
    try:
        answer = await agent_for().generate_response(
            backend, "model", "hello", "", 128, .2, usage_sink=events.append,
        )
        assert answer == "answer" and len(requests) == 1
        assert requests[0][0].endswith("/messages")
        assert len(events) == 1
        usage = events[0]
        assert (usage.input_tokens, usage.output_tokens, usage.cache_read, usage.cache_write) == expected
        assert usage.counts_complete is complete
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected,complete",
    [
        (COMPLETE, (23, 17, 90, 10), True),
        (dict.fromkeys(COMPLETE, 0), (0, 0, 0, 0), True),
        ({"input_tokens": 23, "output_tokens": 17}, (23, 17, 0, 0), False),
        ({"input_tokens": 23, "output_tokens": 17, "cache_read_input_tokens": 90},
         (23, 17, 90, 0), False),
        ({}, (0, 0, 0, 0), False),
    ],
    ids=["all-four", "all-zero", "optional-absent", "cache-write-absent", "unavailable"],
)
async def test_structured_runtime_forwards_category_availability(raw, expected, complete):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer"}], "usage": raw,
        })

    backend = await backend_for("anthropic", handler)
    server = ToolRPCServer()
    server.register_tool("unused", lambda args: pytest.fail("unexpected tool execution"),
                         input_schema={"type": "object", "properties": {}})
    events = []
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="model", prompt="hello",
            usage_sink=events.append,
        )
        assert answer == "answer" and len(requests) == 1
        assert requests[0][0].endswith("/messages") and requests[0][1]["tools"]
        assert len(events) == 1
        usage = events[0]
        assert (usage.input_tokens, usage.output_tokens, usage.cache_read, usage.cache_write) == expected
        assert usage.counts_complete is complete
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,final,expected,complete",
    [
        (COMPLETE, {"output_tokens": 17}, (23, 17, 90, 10), True),
        (dict.fromkeys(COMPLETE, 0), {"output_tokens": 0}, (0, 0, 0, 0), True),
        ({"input_tokens": 23, "output_tokens": 1}, {"output_tokens": 17}, (23, 17, 0, 0), False),
        ({"output_tokens": 1, "cache_read_input_tokens": 90,
          "cache_creation_input_tokens": 10}, {"output_tokens": 17}, (0, 17, 90, 10), False),
        (COMPLETE, {"output_tokens": 17, "input_tokens": "23",
                    "cache_read_input_tokens": True, "cache_creation_input_tokens": None},
         (0, 17, 0, 0), False),
    ],
    ids=["all-four", "all-zero", "optional-absent", "input-absent", "late-invalid-replaces"],
)
async def test_valid_terminal_output_reports_category_availability(start, final, expected, complete):
    rows = frames("anthropic")
    rows[0]["message"]["usage"] = start
    rows[-2]["usage"] = final
    answer, events, tokens, sent = await invoke("anthropic", rows)
    assert answer == "".join(tokens) == "answer"
    assert len(sent) == len(events) == 1
    usage = events[0]
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read, usage.cache_write) == expected
    assert usage.counts_complete is complete


@pytest.mark.asyncio
async def test_later_unavailable_tool_response_marks_observed_aggregate_incomplete():
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        if len(requests) == 1:
            return httpx.Response(200, json={
                "content": [{"type": "tool_use", "id": "call-one", "name": "echo",
                             "input": {"value": "hi"}}],
                "stop_reason": "tool_use", "usage": COMPLETE,
            })
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer"}],
        })

    backend = await backend_for("anthropic", handler)
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args["value"]}

    server.register_tool("echo", echo)
    events = []
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="model", prompt="hello",
            usage_sink=events.append,
        )
        assert answer == "answer" and len(requests) == 2
        assert all(path.endswith("/messages") for path, _ in requests)
        assert [event.counts_complete for event in events] == [True, False]
        aggregate = _sum_usage(*events)
        assert (aggregate.input_tokens, aggregate.output_tokens,
                aggregate.cache_read, aggregate.cache_write) == (23, 17, 90, 10)
        assert aggregate.counts_complete is False
        assert _billable_from_usage(aggregate) is None
    finally:
        await backend.aclose()
