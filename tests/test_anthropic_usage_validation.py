"""Anthropic usage counts must be wire integers even when an answer is valid."""

import json

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_dialects import anthropic_usage
from agents.core.tool_rpc import ToolRPCServer
from tests.test_stream_token_usage import frames, invoke
from tests.test_text_usage_propagation import agent_for, backend_for

COUNTS = {
    "input_tokens": 23,
    "output_tokens": 17,
    "cache_read_input_tokens": 90,
    "cache_creation_input_tokens": 10,
}
FIELD = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}
EXPECTED = {"input_tokens": 23, "output_tokens": 17, "cache_read": 90, "cache_write": 10}


@pytest.mark.parametrize("field", FIELD)
@pytest.mark.parametrize("invalid", [True, "17", 1.5])
def test_invalid_wire_types_do_not_become_counts_or_erase_valid_siblings(field, invalid):
    counts = {**COUNTS, field: invalid}
    assert anthropic_usage({"usage": counts}).as_dict() == {**EXPECTED, FIELD[field]: 0}


@pytest.mark.parametrize("invalid", [None, -1, float("nan"), float("inf"), {}, []])
def test_invalid_and_negative_count_preserves_valid_siblings(invalid):
    counts = {**COUNTS, "input_tokens": invalid}
    assert anthropic_usage({"usage": counts}).as_dict() == {**EXPECTED, "input_tokens": 0}


def test_zero_valid_counts_missing_usage_and_non_mapping_are_distinct_inputs():
    assert anthropic_usage({"usage": dict.fromkeys(COUNTS, 0)}).as_dict() == dict.fromkeys(EXPECTED, 0)
    assert anthropic_usage({"usage": COUNTS}).as_dict() == EXPECTED
    assert anthropic_usage({"usage": []}).as_dict() == dict.fromkeys(EXPECTED, 0)
    assert anthropic_usage({}).as_dict() == dict.fromkeys(EXPECTED, 0)


@pytest.mark.asyncio
async def test_actual_claude_text_keeps_answer_with_valid_sibling_counts():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer"}],
            "usage": {**COUNTS, "input_tokens": True},
        })

    backend = await backend_for("anthropic", handler)
    events = []
    try:
        answer = await agent_for().generate_response(
            backend, "model", "hello", "", 128, .2, usage_sink=events.append
        )
        assert answer == "answer"
        assert len(requests) == len(events) == 1
        assert events[0].as_dict() == {**EXPECTED, "input_tokens": 0}
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_actual_claude_structured_turn_and_runtime_sink_keep_tool_calls():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "content": [
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "call-one", "name": "lookup", "input": {}},
            ],
            "stop_reason": "tool_use",
            "usage": {**COUNTS, "cache_creation_input_tokens": "10"},
        })

    backend = await backend_for("anthropic", handler)
    try:
        turn = await backend.generate_tool_turn(
            "model", [{"role": "user", "content": "hello"}], []
        )
        assert turn.content == "checking"
        assert [call.name for call in turn.tool_calls] == ["lookup"]
        assert turn.usage.as_dict() == {**EXPECTED, "cache_write": 0}

        # A text-only response takes the same structured parser into the runtime sink.
        async def text_handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                "content": [{"type": "text", "text": "answer"}],
                "usage": {**COUNTS, "cache_read_input_tokens": 1.5},
            })

        await backend.client.aclose()
        backend.client = httpx.AsyncClient(
            base_url="https://provider.test", transport=httpx.MockTransport(text_handler)
        )
        server = ToolRPCServer()
        server.register_tool(
            "unused", lambda args: pytest.fail("unexpected tool call"),
            input_schema={"type": "object", "properties": {}},
        )
        events = []
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="model", prompt="hello",
            system="Assistant", max_tokens=128, temperature=.2, usage_sink=events.append,
        )
        assert answer == "answer"
        assert len(requests) == 2 and len(events) == 1
        assert events[0].as_dict() == {**EXPECTED, "cache_read": 0}
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_completed_stream_late_malformed_counts_replace_earlier_snapshot():
    rows = frames("anthropic")
    rows[-2]["usage"].update(
        input_tokens="23", cache_read_input_tokens=True,
        cache_creation_input_tokens=1.5,
    )
    answer, events, tokens, sent = await invoke("anthropic", rows)
    assert answer == "".join(tokens) == "answer"
    assert len(sent) == len(events) == 1
    assert events[0].as_dict() == {
        "input_tokens": 0, "output_tokens": 17, "cache_read": 0, "cache_write": 0,
    }
