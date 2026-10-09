"""Partial Anthropic prompt categories cannot replace a complete context anchor."""

import json
from collections import OrderedDict
from types import SimpleNamespace

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.context_compressor import CompactionPolicy, ContextCompressor
from agents.core.orchestrator import Orchestrator, _sum_usage
from agents.core.route_compaction import remember_usage, trusted_anchor
from agents.core.tool_rpc import ToolRPCServer
from tests.test_stream_token_usage import Stream, frames
from tests.test_text_usage_propagation import agent_for, backend_for
from tests.test_usage_counter_accounting import _record

HIGH = {
    "input_tokens": 9_000, "output_tokens": 17,
    "cache_read_input_tokens": 19_000, "cache_creation_input_tokens": 0,
}
PARTIAL = {
    "input_tokens": 23, "output_tokens": 17,
    "cache_read_input_tokens": 90,
}


def _orch(covers):
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = covers
    return orch


@pytest.mark.asyncio
async def test_actual_text_observations_retain_high_anchor_and_compaction_decision(monkeypatch):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        raw = HIGH if len(requests) == 1 else PARTIAL
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer"}], "usage": raw,
        })

    backend = await backend_for("anthropic", handler)
    orch = _orch(10)
    observations = []

    def observe(usage):
        observations.append(usage)
        orch._record_context_anchor("jarvis", usage)

    try:
        assert await agent_for().generate_response(
            backend, "model", "hello", "", 128, .2, usage_sink=observe,
        ) == "answer"
        assert len(requests) == len(observations) == 1
        assert requests[0][0].endswith("/messages")
        assert orch._usage_anchor(10).prompt_tokens == 28_000

        assert await agent_for().generate_response(
            backend, "model", "hello again", "", 128, .2, usage_sink=observe,
        ) == "answer"
        assert len(requests) == len(observations) == 2
        assert (observations[1].input_tokens, observations[1].cache_read,
                observations[1].cache_write) == (23, 90, 0)
        # The prior complete single-request count includes hidden system/tool input.
        assert orch._context_anchor["jarvis"] == (28_000, 10)
        assert orch._usage_anchor(10).prompt_tokens == 28_000

        metadata, charge = _record(observations[1], monkeypatch, last_prompt=1)
        assert metadata["usage_source"] == "estimate"
        assert metadata["input_tokens"] >= 113 and metadata["output_tokens"] >= 17
        assert metadata["cached_tokens"] == 0 and metadata["cache_hit"] is False
        assert charge[0][1:3] == (metadata["input_tokens"], metadata["output_tokens"])

        rows = [{"role": "user", "content": "x" * 400} for _ in range(10)]
        compressor = ContextCompressor()
        policy = CompactionPolicy()
        plain = await compressor.compact(rows, model="llama-3-8b", policy=policy)
        assert plain["tier"] == "none"
        anchored = await compressor.compact(
            rows, model="llama-3-8b", policy=policy, anchor=orch._usage_anchor(10),
        )
        assert anchored["tier"] == "summarize"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_partial_text_observation_cannot_create_initial_anchor():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer"}], "usage": PARTIAL,
        })

    backend = await backend_for("anthropic", handler)
    orch = _orch(1)
    try:
        assert await agent_for().generate_response(
            backend, "model", "hello", "", 128, .2,
            usage_sink=lambda usage: orch._record_context_anchor("jarvis", usage),
        ) == "answer"
        assert len(requests) == 1
        assert orch._context_anchor == {} and orch._usage_anchor(1) is None
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_actual_tool_loop_keeps_managed_anchor_prefix_and_route_identity():
    rows = [{"role": "user", "content": "before"}]
    route = SimpleNamespace(identity=object(), model="claude-test")
    store = OrderedDict()
    requests, observations = [], []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        if len(requests) == 1:
            return httpx.Response(200, json={
                "content": [{"type": "tool_use", "id": "call-one", "name": "echo",
                             "input": {"value": "hi"}}],
                "stop_reason": "tool_use", "usage": HIGH,
            })
        rows.append({"role": "user", "content": "later"})
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer"}], "usage": PARTIAL,
        })

    backend = await backend_for("anthropic", handler)
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args["value"]}

    server.register_tool("echo", echo)

    def observe(usage):
        observations.append(usage)
        remember_usage(store, "s", "jarvis", route, rows, "instance", usage)

    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="jarvis", backend=backend, model="model", prompt="hello",
            usage_sink=observe,
        )
        assert answer == "answer" and len(requests) == len(observations) == 2
        assert all(path.endswith("/messages") and body["tools"] for path, body in requests)
        aggregate = _sum_usage(*observations)
        assert aggregate.counts_complete is False
        saved = store[("s", "jarvis")]
        assert saved.owner is route.identity and saved.model == route.model
        assert (saved.tokens, saved.count) == (28_000, 1)
        anchor = trusted_anchor(store, "s", {"jarvis": route}, rows, "instance")
        assert (anchor.prompt_tokens, anchor.covers) == (28_000, 1)
        assert trusted_anchor(store, "s", {"jarvis": route}, rows, "other") is None
        changed = [{"role": "user", "content": "changed"}, *rows[1:]]
        assert trusted_anchor(store, "s", {"jarvis": route}, changed, "instance") is None
        # A multi-request sum cannot itself describe a single request prefix.
        assert getattr(aggregate, "prompt_counts_complete", None) is False
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_accepted_terminal_stream_partial_prompt_keeps_prior_anchor():
    requests = []

    def handler(request):
        requests.append(request)
        rows = frames("anthropic")
        rows[0]["message"]["usage"] = HIGH if len(requests) == 1 else PARTIAL
        rows[-2]["usage"] = {"output_tokens": 17}
        return httpx.Response(200, stream=Stream("anthropic", rows))

    backend = await backend_for("anthropic", handler)
    orch = _orch(2)
    observations, tokens = [], []

    def observe(usage):
        observations.append(usage)
        orch._record_context_anchor("jarvis", usage)

    try:
        for _ in range(2):
            assert await agent_for().generate_response(
                backend, "model", "hello", "", 128, .2,
                on_token=tokens.append, usage_sink=observe,
            ) == "answer"
        assert len(requests) == len(observations) == 2 and tokens == ["answer", "answer"]
        assert (observations[0].input_tokens + observations[0].cache_read
                + observations[0].cache_write) == 28_000
        assert (observations[1].input_tokens + observations[1].cache_read
                + observations[1].cache_write) == 113
        assert orch._context_anchor["jarvis"] == (28_000, 2)
    finally:
        await backend.aclose()
