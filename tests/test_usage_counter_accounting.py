"""Availability of compatible response counters reaches accounting without invented totals."""

import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.tool_protocol import TokenUsage, ToolTurn
from agents.core.orchestrator import Orchestrator, _billable_from_usage, _sum_usage
from agents.core.tool_rpc import ToolRPCServer


def _flagged(input_tokens=0, output_tokens=0, *, complete, cache_read=0, cache_write=0):
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read=cache_read,
        cache_write=cache_write,
        counts_complete=complete,
    )


def _record(usage, monkeypatch, *, prompt="hi", answer="ok", last_prompt=0):
    from agents.core import cost_tracker

    learning, charges = [], []
    monkeypatch.setattr(cost_tracker, "record", lambda *args, **kwargs: charges.append((args, kwargs)))
    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = {"jarvis": SimpleNamespace(config={"model": "configured"})}
    orch.learning = SimpleNamespace(record=lambda **kwargs: learning.append(kwargs))
    orch.bench = SimpleNamespace(record=lambda **kwargs: None)
    orch.get_setting = lambda *_: False
    orch._last_models = {"jarvis": "openai/gpt-4o-mini"}
    orch._last_routes = {"jarvis": "cloud"}
    orch._last_prompt_tokens = {"jarvis": last_prompt}
    orch._last_reported_usage = {"jarvis": usage}
    orch._record_interactions(prompt, {"jarvis": answer}, answer, route_name="cloud")
    return learning[0]["metadata"], charges[0]


def test_flagged_zero_is_observed_but_legacy_zero_stays_unreported():
    events = []
    AgentToolRuntime._report_usage(events.append, ToolTurn(usage=_flagged(complete=True)))
    AgentToolRuntime._report_usage(events.append, ToolTurn(usage=_flagged(complete=False)))
    AgentToolRuntime._report_usage(events.append, ToolTurn(usage=TokenUsage()))
    AgentToolRuntime._report_usage(events.append, ToolTurn(usage=TokenUsage(counts_complete="invalid")))
    assert [usage.counts_complete for usage in events] == [True, False]
    assert _billable_from_usage(events[0]) == (0, 0, 0)
    assert _billable_from_usage(events[1]) is None
    assert _billable_from_usage(TokenUsage()) is None


@pytest.mark.parametrize(
    "first,second,expected",
    [(True, True, True), (True, False, False), (False, True, False),
     (None, None, None), (True, None, False), (None, True, False)],
)
def test_aggregation_requires_every_observed_counter_pair(first, second, expected):
    running = _sum_usage(_flagged(20, 3, complete=first), _flagged(7, 5, complete=second))
    assert (running.input_tokens, running.output_tokens) == (27, 8)
    assert running.counts_complete is expected


@pytest.mark.parametrize(
    "known_input,known_output,last_prompt,expected_input,expected_output",
    [(100_000, 0, 7, 100_000, 1), (0, 17, 50, 50, 17), (100, 0, 1_000, 1_000, 1)],
)
def test_incomplete_counts_keep_estimate_and_known_lower_bounds(
    monkeypatch, known_input, known_output, last_prompt, expected_input, expected_output,
):
    metadata, charge = _record(
        _flagged(known_input, known_output, complete=False),
        monkeypatch,
        last_prompt=last_prompt,
    )
    assert metadata["usage_source"] == "estimate"
    assert metadata["input_tokens"] == expected_input
    assert metadata["output_tokens"] == expected_output
    assert metadata["cached_tokens"] == 0
    assert charge[0][1:3] == (expected_input, expected_output)


def test_complete_zero_is_a_provider_observation_but_legacy_zero_estimates(monkeypatch):
    from agents.core import orchestrator

    estimate = orchestrator.estimate_tokens
    estimates = []
    def count_estimate(value):
        estimates.append(value)
        return estimate(value)
    monkeypatch.setattr(orchestrator, "estimate_tokens", count_estimate)
    complete, _ = _record(_flagged(complete=True), monkeypatch)
    assert estimates == []
    legacy, _ = _record(TokenUsage(), monkeypatch)
    assert (complete["usage_source"], complete["input_tokens"], complete["output_tokens"]) == (
        "provider", 0, 0,
    )
    assert legacy["usage_source"] == "estimate"
    assert legacy["input_tokens"] > 0 and legacy["output_tokens"] > 0
    assert estimates


def test_incomplete_cache_counts_are_input_floor_without_a_discount(monkeypatch):
    metadata, charge = _record(
        _flagged(20, complete=False, cache_read=60, cache_write=40), monkeypatch,
    )
    assert metadata["usage_source"] == "estimate"
    assert metadata["input_tokens"] == 120
    assert metadata["cached_tokens"] == 0
    assert metadata["cache_hit"] is False
    assert charge[0][1:3] == (120, metadata["output_tokens"])


@pytest.mark.asyncio
async def test_partial_compatible_http_metadata_floors_cost_record_tokens(monkeypatch):
    data = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100_000}}
    client = httpx.AsyncClient(
        base_url="https://provider.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data)),
    )
    backend = OpenRouterBackend(client=client)
    try:
        turn = await backend.generate_tool_turn("model", [{"role": "user", "content": "hi"}], [])
        assert turn.content == "ok"
        metadata, charge = _record(turn.usage, monkeypatch)
        assert turn.usage.counts_complete is False
        assert metadata["usage_source"] == "estimate"
        assert metadata["input_tokens"] >= 100_000
        assert metadata["output_tokens"] > 0
        assert charge[0][1] >= 100_000
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_second_tool_request_without_usage_marks_aggregate_incomplete():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "content": "", "tool_calls": [{"id": "call-one", "type": "function",
                        "function": {"name": "echo", "arguments": '{"value":"hi"}'}}],
                }}],
                "usage": {"prompt_tokens": 100_000, "completion_tokens": 7},
            })
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "done"}}],
        })

    client = httpx.AsyncClient(base_url="https://provider.test", transport=httpx.MockTransport(handler))
    backend = OpenRouterBackend(client=client)
    server = ToolRPCServer()
    async def echo(args):
        return {"echo": args["value"]}
    server.register_tool("echo", echo)
    events = []
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="model", prompt="hi",
            usage_sink=events.append,
        )
        assert answer == "done" and len(sent) == 2
        assert len(events) == 2
        total = _sum_usage(events[0], events[1])
        assert total.input_tokens == 100_000 and total.output_tokens == 7
        assert total.counts_complete is False
        assert _billable_from_usage(total) is None
    finally:
        await backend.aclose()
