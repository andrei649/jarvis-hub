"""Accepted Gemini replies carry conservative category availability into meters."""

import json

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.orchestrator import _billable_from_usage, _sum_usage
from agents.core.tool_rpc import ToolRPCServer
from tests.test_gemini_stream_usage import invoke, terminal
from tests.test_text_usage_propagation import agent_for, backend_for

COMPLETE = {
    "promptTokenCount": 123, "candidatesTokenCount": 14,
    "thoughtsTokenCount": 3, "toolUsePromptTokenCount": 0,
}


def _answer(metadata):
    return {"candidates": [{"content": {"parts": [{"text": "answer"}]},
                            "finishReason": "STOP"}], "usageMetadata": metadata}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,expected,complete",
    [
        ({**COMPLETE, "totalTokenCount": 140}, (123, 17), True),
        (dict.fromkeys(COMPLETE, 0), (0, 0), True),
        (COMPLETE, (123, 17), True),
        ({"promptTokenCount": 123, "candidatesTokenCount": 14,
          "toolUsePromptTokenCount": 0}, (123, 14), False),
        ({**COMPLETE, "toolUsePromptTokenCount": 9}, (123, 17), False),
        ({"promptTokenCount": 123, "candidatesTokenCount": 14,
          "thoughtsTokenCount": 3}, (123, 17), False),
        ({**COMPLETE, "totalTokenCount": 999}, (123, 17), False),
        ({"promptTokenCount": 123}, (123, 0), False),
        ({}, (0, 0), False),
    ],
    ids=["consistent-total", "all-zero", "absent-total", "missing-thoughts",
         "positive-tool-use", "unknown-tool-use", "contradictory-total",
         "core-partial", "unavailable"],
)
async def test_accepted_text_forwards_mapped_counts_and_availability(metadata, expected, complete):
    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=_answer(metadata))

    backend = await backend_for("gemini", handler)
    events = []
    try:
        answer = await agent_for().generate_response(
            backend, "model", "hello", "", 128, .2, usage_sink=events.append,
        )
        assert answer == "answer" and len(sent) == 1
        assert "generateContent" in sent[0][0]
        assert len(events) == 1
        assert (events[0].input_tokens, events[0].output_tokens) == expected
        assert events[0].counts_complete is complete
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,expected,complete",
    [
        ({**COMPLETE, "totalTokenCount": 140}, (123, 17), True),
        (dict.fromkeys(COMPLETE, 0), (0, 0), True),
        ({"promptTokenCount": 123, "candidatesTokenCount": 14,
          "toolUsePromptTokenCount": 0}, (123, 14), False),
        ({**COMPLETE, "toolUsePromptTokenCount": 9}, (123, 17), False),
        ({**COMPLETE, "totalTokenCount": 999}, (123, 17), False),
        ({}, (0, 0), False),
    ],
    ids=["consistent-total", "all-zero", "missing-thoughts",
         "positive-tool-use", "contradictory-total", "unavailable"],
)
async def test_structured_runtime_forwards_availability(metadata, expected, complete):
    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=_answer(metadata))

    backend = await backend_for("gemini", handler)
    server = ToolRPCServer()
    server.register_tool("unused", lambda args: pytest.fail("unexpected tool execution"),
                         input_schema={"type": "object", "properties": {}})
    events = []
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="model", prompt="hello",
            usage_sink=events.append,
        )
        assert answer == "answer" and len(sent) == 1
        assert "generateContent" in sent[0][0] and sent[0][1]["tools"]
        assert len(events) == 1
        assert (events[0].input_tokens, events[0].output_tokens) == expected
        assert events[0].counts_complete is complete
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,expected,complete,empty",
    [
        ({**COMPLETE, "totalTokenCount": 140}, (123, 17), True, False),
        (dict.fromkeys(COMPLETE, 0), (0, 0), True, True),
        ({"promptTokenCount": 123, "candidatesTokenCount": 14,
          "toolUsePromptTokenCount": 0}, (123, 14), False, False),
        ({**COMPLETE, "toolUsePromptTokenCount": 9}, (123, 17), False, False),
        ({"promptTokenCount": 123, "candidatesTokenCount": 14,
          "thoughtsTokenCount": 3}, (123, 17), False, False),
        ({**COMPLETE, "totalTokenCount": 999}, (123, 17), False, False),
    ],
    ids=["consistent-total", "all-zero", "missing-thoughts", "positive-tool-use",
         "unknown-tool-use", "contradictory-total"],
)
async def test_accepted_terminal_stream_preserves_availability(metadata, expected, complete, empty):
    row = terminal(empty=empty)
    row["usageMetadata"] = metadata
    answer, events, tokens, sent = await invoke([row])
    assert answer == "".join(tokens) == ("" if empty else "answer")
    assert len(sent) == len(events) == 1
    assert (events[0].input_tokens, events[0].output_tokens) == expected
    assert events[0].counts_complete is complete


@pytest.mark.asyncio
async def test_blocked_prompt_keeps_partial_observation_without_claiming_complete():
    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={
            "promptFeedback": {"blockReason": "SAFETY"},
            "usageMetadata": {"promptTokenCount": 123, "candidatesTokenCount": 0,
                              "thoughtsTokenCount": 0},
        })

    backend = await backend_for("gemini", handler)
    events = []
    try:
        turn = await backend.generate_tool_turn("model", [{"role": "user", "content": "hello"}], [])
        assert turn.content == "" and turn.finish_reason == "content_filter"
        assert len(sent) == 1 and "generateContent" in sent[0][0]
        AgentToolRuntime._report_usage(events.append, turn)
        assert len(events) == 1
        assert (events[0].input_tokens, events[0].output_tokens) == (123, 0)
        assert events[0].counts_complete is False
        assert _billable_from_usage(events[0]) is None
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_later_unavailable_tool_reply_marks_aggregate_incomplete():
    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        if len(sent) == 1:
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"functionCall": {
                    "name": "echo", "args": {"value": "hi"},
                }}]}, "finishReason": "STOP"}],
                "usageMetadata": COMPLETE,
            })
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "answer"}]},
                            "finishReason": "STOP"}],
        })

    backend = await backend_for("gemini", handler)
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
        assert answer == "answer" and len(sent) == 2
        assert all("generateContent" in path for path, _ in sent)
        assert [event.counts_complete for event in events] == [True, False]
        aggregate = _sum_usage(*events)
        assert (aggregate.input_tokens, aggregate.output_tokens) == (123, 17)
        assert aggregate.counts_complete is False
        assert _billable_from_usage(aggregate) is None
    finally:
        await backend.client.aclose()
