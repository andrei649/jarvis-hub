"""Canonical compatible counts retain whether both counters were supplied."""

import json

import httpx
import pytest

from agents.core.llm.tool_dialects import compatible_usage, lmstudio_usage
from agents.core.llm.tool_protocol import TokenUsage
from agents.core.llm.usage_context import observer_scope
from tests.test_text_usage_propagation import agent_for, backend_for, response

PARSERS = [lmstudio_usage, compatible_usage]
ZERO = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0}


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("prompt,completion", [(0, 0), (123, 17)])
def test_complete_canonical_pair_preserves_legacy_shape_and_nonzero_predicate(parser, prompt, completion):
    usage = parser({"usage": {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": 9999,
        "prompt_tokens_details": {"cached_tokens": 100},
    }})
    assert getattr(usage, "counts_complete", None) is True
    assert usage.as_dict() == {**ZERO, "input_tokens": prompt, "output_tokens": completion}
    assert usage.reported is bool(prompt or completion)
    assert list(usage.as_dict()) == list(ZERO)


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("field,bad,expected", [
    ("prompt_tokens", None, (0, 17)),
    ("prompt_tokens", True, (0, 17)),
    ("prompt_tokens", "123", (0, 17)),
    ("prompt_tokens", -1, (0, 17)),
    ("completion_tokens", None, (123, 0)),
    ("completion_tokens", 1.5, (123, 0)),
    ("completion_tokens", float("inf"), (123, 0)),
])
def test_incomplete_pair_preserves_only_valid_siblings(parser, field, bad, expected):
    raw = {"prompt_tokens": 123, "completion_tokens": 17}
    raw[field] = bad
    usage = parser({"usage": raw})
    assert getattr(usage, "counts_complete", None) is False
    assert (usage.input_tokens, usage.output_tokens) == expected
    assert usage.cache_read == usage.cache_write == 0
    assert usage.reported


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("raw", [{}, {"usage": None}, {"usage": []}, {"usage": {}}])
def test_absent_or_malformed_usage_is_explicitly_incomplete_but_not_reported(parser, raw):
    usage = parser(raw)
    assert getattr(usage, "counts_complete", None) is False
    assert usage.as_dict() == ZERO
    assert not usage.reported


def test_observer_forwards_flagged_zero_and_incomplete_but_not_legacy_zero_after_scope():
    events = []
    unavailable = lmstudio_usage({})
    complete_zero = lmstudio_usage({"usage": {"prompt_tokens": 0, "completion_tokens": 0}})
    with observer_scope(events.append) as observer:
        observer(unavailable)
        observer(complete_zero)
        observer(TokenUsage())
    observer(unavailable)
    assert [getattr(event, "counts_complete", None) for event in events] == [False, True]
    assert all(event.as_dict() == ZERO for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["lmstudio", "compatible"])
@pytest.mark.parametrize("usage_data,expected_counts,complete", [
    (None, ZERO, False),
    ({"prompt_tokens": 123}, {**ZERO, "input_tokens": 123}, False),
    ({"prompt_tokens": 0, "completion_tokens": 0}, ZERO, True),
])
async def test_actual_text_adapter_forwards_one_flagged_event(provider, usage_data, expected_counts, complete):
    requests = []
    data = response(provider)
    if usage_data is None:
        del data["usage"]
    else:
        data["usage"] = usage_data

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=data)

    backend = await backend_for(provider, handler)
    events = []
    try:
        assert await agent_for().generate_response(
            backend, "model", "hello", "", 128, .2, usage_sink=events.append
        ) == "answer"
        assert len(requests) == len(events) == 1
        assert events[0].as_dict() == expected_counts
        assert getattr(events[0], "counts_complete", None) is complete
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["lmstudio", "compatible"])
async def test_actual_tool_adapter_retains_answer_with_missing_usage(provider):
    data = response(provider)
    del data["usage"]
    backend = await backend_for(provider, lambda request: httpx.Response(200, json=data))
    try:
        turn = await backend.generate_tool_turn(
            "model", [{"role": "user", "content": "hello"}], []
        )
        assert turn.content == "answer" and turn.tool_calls == ()
        assert turn.usage.as_dict() == ZERO
        assert getattr(turn.usage, "counts_complete", None) is False
    finally:
        await backend.client.aclose()
