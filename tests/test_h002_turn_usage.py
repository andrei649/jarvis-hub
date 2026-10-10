"""Request-owned inference usage never guesses a bill from a displayed answer."""

import asyncio

import httpx
import pytest

from agents.core.llm.egress import llm_async_client
from agents.core.llm.tool_protocol import TokenUsage
from agents.core.llm.usage_context import report_text_usage
from agents.core.turn_usage import model_usage_scope, turn_usage_scope


async def _send(provider="openrouter", *, url="https://openrouter.ai/api/v1/chat/completions",
                model="claude-sonnet-5", route="cloud"):
    client = llm_async_client(provider, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True})))
    try:
        with model_usage_scope(model=model, route=route):
            await client.post(url, json={"model": model})
            report_text_usage(TokenUsage(input_tokens=10, output_tokens=5,
                                         counts_complete=True))
    finally:
        await client.aclose()


def test_zero_without_generation_and_unknown_uninstrumented_generation():
    with turn_usage_scope() as collector:
        assert collector.snapshot()["api_calls"] == 0
        assert collector.snapshot()["usage_basis"] == "measured_zero"
        with model_usage_scope(model="fake", route="cloud"):
            pass
        value = collector.snapshot()
        assert value["api_calls"] is None
        assert value["input_tokens"] is None
        assert value["estimated_cost_usd"] is None
        assert value["usage_basis"] == value["cost_basis"] == "unknown"


@pytest.mark.asyncio
async def test_actual_accepted_http_dispatch_correlates_provider_usage_and_exact_price():
    with turn_usage_scope() as collector:
        await _send()
        value = collector.snapshot()
    assert value["schema"] == "nerva.turn.usage.v1"
    assert value["api_calls"] == 1
    assert (value["provider"], value["model"]) == ("openrouter", "claude-sonnet-5")
    assert (value["input_tokens"], value["output_tokens"]) == (10, 5)
    assert value["usage_basis"] == "provider_complete"
    assert value["cost_basis"] == "price_table"
    assert value["estimated_cost_usd"] == pytest.approx((10 * 2 + 5 * 10) / 1_000_000)
    assert len(value["breakdown"]) == 1
    assert value["price_verified_at"] == "2026-08-18"


@pytest.mark.asyncio
async def test_retry_without_first_usage_makes_totals_unknown():
    with turn_usage_scope() as collector:
        client = llm_async_client("openrouter", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True})))
        try:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions", json={})
                await client.post("https://openrouter.ai/api/v1/chat/completions", json={})
                report_text_usage(TokenUsage(input_tokens=10, output_tokens=5,
                                             counts_complete=True))
        finally:
            await client.aclose()
        value = collector.snapshot()
    assert value["api_calls"] == 2
    assert value["input_tokens"] is None
    assert value["estimated_cost_usd"] is None
    assert value["usage_basis"] == "unknown"


@pytest.mark.asyncio
async def test_uncertified_and_duplicate_usage_never_mints_totals():
    with turn_usage_scope() as collector:
        client = llm_async_client("openrouter", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True})))
        try:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions", json={})
                report_text_usage(TokenUsage(input_tokens=1, output_tokens=2,
                                             counts_complete=False))
                report_text_usage(TokenUsage(input_tokens=9000, output_tokens=9000,
                                             counts_complete=True))
        finally:
            await client.aclose()
        value = collector.snapshot()
    assert value["api_calls"] == 1
    assert value["input_tokens"] is None and value["output_tokens"] is None


@pytest.mark.asyncio
async def test_local_alias_on_remote_compatible_endpoint_is_not_zero_price():
    with turn_usage_scope() as collector:
        await _send("lm-studio", url="https://compatible.example/v1/chat/completions",
                    model="local", route="cloud-compatible")
        value = collector.snapshot()
    assert value["api_calls"] == 1
    assert value["cost_basis"] == "unknown"
    assert value["estimated_cost_usd"] is None


@pytest.mark.asyncio
async def test_cache_write_without_exact_premium_is_unpriced():
    with turn_usage_scope() as collector:
        client = llm_async_client("anthropic", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={})))
        try:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://api.anthropic.com/v1/messages", json={})
                report_text_usage(TokenUsage(input_tokens=5, output_tokens=2, cache_write=10,
                                             counts_complete=True))
        finally:
            await client.aclose()
        value = collector.snapshot()
    assert value["input_tokens"] == 15
    assert value["estimated_cost_usd"] is None
    assert value["cost_basis"] == "unknown"


@pytest.mark.asyncio
async def test_concurrent_requests_and_late_copied_task_cannot_cross_receipts():
    gate = asyncio.Event()
    late = None

    async def one(model):
        nonlocal late
        with turn_usage_scope() as collector:
            async def child():
                await gate.wait()
                await _send(model=model)
            if model == "claude-sonnet-5":
                late = asyncio.create_task(child())
            await _send(model=model)
            frozen = collector.snapshot()
        return collector, frozen

    (first, frozen), (second, other) = await asyncio.gather(
        one("claude-sonnet-5"), one("gemini-2.5-flash"))
    gate.set()
    await late
    assert frozen["api_calls"] == other["api_calls"] == 1
    assert first.snapshot() == frozen
    assert second.snapshot() == other


@pytest.mark.asyncio
async def test_borrowed_task_context_cannot_consume_another_tasks_pending_usage():
    with turn_usage_scope() as collector:
        client = llm_async_client("openrouter", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={})))
        try:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions", json={})
                await asyncio.create_task(asyncio.to_thread(
                    report_text_usage, TokenUsage(input_tokens=20, output_tokens=2,
                                                   counts_complete=True)))
                assert collector.snapshot()["input_tokens"] is None
                report_text_usage(TokenUsage(input_tokens=1, output_tokens=2,
                                             counts_complete=True))
        finally:
            await client.aclose()
        assert collector.snapshot()["input_tokens"] == 1


@pytest.mark.asyncio
async def test_unscoped_owned_generation_is_counted_with_unknown_model_and_price():
    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            await client.post("https://openrouter.ai/api/v1/chat/completions",
                              json={"model": "claude-sonnet-5"})
            report_text_usage(TokenUsage(input_tokens=3, output_tokens=4,
                                         counts_complete=True))
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] == 1
    assert (value["input_tokens"], value["output_tokens"]) == (3, 4)
    assert value["model"] is None
    assert value["estimated_cost_usd"] is None


@pytest.mark.asyncio
async def test_control_requests_and_embedding_are_not_generation():
    client = llm_async_client("gemini", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            await client.get("https://generativelanguage.googleapis.com/v1beta/models")
            await client.post("https://generativelanguage.googleapis.com/v1beta/cachedContents",
                              json={"model": "gemini-2.5-pro"})
            await client.post("https://generativelanguage.googleapis.com/v1beta/models/embedding-001:embedContent",
                              json={"content": {}})
            assert collector.snapshot()["api_calls"] == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unknown_post_after_known_generation_in_one_scope_withholds_numeric_totals():
    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  json={"model": "claude-sonnet-5"})
                report_text_usage(TokenUsage(input_tokens=4, output_tokens=3,
                                             counts_complete=True))
                await client.post("https://openrouter.ai/api/v1/new-generation-endpoint",
                                  json={"model": "claude-sonnet-5"})
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] is None
    assert value["input_tokens"] is None
    assert value["estimated_cost_usd"] is None
    assert value["usage_basis"] == value["cost_basis"] == "unknown"


@pytest.mark.asyncio
async def test_known_control_posts_inside_generation_scope_do_not_poison_known_call():
    client = llm_async_client("ollama", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    gemini = llm_async_client("gemini", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="local", route="local"):
                await client.post("http://localhost:11434/api/chat", json={"model": "local"})
                report_text_usage(TokenUsage(input_tokens=4, output_tokens=3,
                                             counts_complete=True))
                await client.post("http://localhost:11434/api/show", json={"model": "local"})
                await client.post("http://localhost:11434/api/embeddings",
                                  json={"model": "local"})
                await gemini.post("https://generativelanguage.googleapis.com/v1beta/cachedContents",
                                  json={"model": "local"})
                await gemini.post("https://generativelanguage.googleapis.com/v1beta/models/embedding-001:embedContent",
                                  json={"content": {}})
            value = collector.snapshot()
    finally:
        await client.aclose()
        await gemini.aclose()
    assert value["api_calls"] == 1
    assert (value["input_tokens"], value["output_tokens"]) == (4, 3)
    assert value["usage_basis"] == "provider_complete"


@pytest.mark.asyncio
async def test_inherited_closed_model_scope_still_counts_known_send_without_provenance():
    go = asyncio.Event()
    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))

    async def late_send():
        await go.wait()
        await client.post("https://openrouter.ai/api/v1/chat/completions",
                          json={"model": "claude-sonnet-5"})
        report_text_usage(TokenUsage(input_tokens=2, output_tokens=1,
                                     counts_complete=True))

    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                child = asyncio.create_task(late_send())
            go.set()
            await child
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] is None
    assert value["breakdown"][0]["api_calls"] == 1
    assert value["model"] is None
    assert value["estimated_cost_usd"] is None
    assert value["usage_basis"] == "unknown"  # closed scope had no accepted send


@pytest.mark.asyncio
async def test_local_zero_needs_local_host_provider_and_positive_route():
    with turn_usage_scope() as collector:
        await _send("lm-studio", url="http://127.0.0.1:1234/v1/chat/completions",
                    model="local", route="local")
        value = collector.snapshot()
    assert value["api_calls"] == 1
    assert value["estimated_cost_usd"] == 0
    assert value["cost_basis"] == "local_zero"
    with turn_usage_scope() as collector:
        await _send("lm-studio", url="http://127.0.0.1:1234/v1/chat/completions",
                    model="local", route="unrecognized")
        value = collector.snapshot()
    assert value["estimated_cost_usd"] is None
    assert value["cost_basis"] == "unknown"


@pytest.mark.asyncio
async def test_wire_model_mismatch_does_not_price_display_model():
    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  json={"model": "unknown-proxy-model"})
                report_text_usage(TokenUsage(input_tokens=3, output_tokens=4,
                                             counts_complete=True))
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] == 1
    assert value["estimated_cost_usd"] is None
    assert value["model"] is None


@pytest.mark.asyncio
async def test_gemini_pro_over_200k_has_unknown_unsupported_tier_price():
    client = llm_async_client("gemini", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="gemini-2.5-pro", route="cloud"):
                await client.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
                                  json={"contents": []})
                report_text_usage(TokenUsage(input_tokens=200_001, output_tokens=10,
                                             counts_complete=True))
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] == 1
    assert value["input_tokens"] == 200_001
    assert value["estimated_cost_usd"] is None
    assert value["cost_basis"] == "unknown"


@pytest.mark.asyncio
async def test_protocol_refusal_has_zero_accepted_calls_and_no_transport_send():
    from agents.core.llm.host_protocol import HostProtocolRefused

    seen = []
    client = llm_async_client("anthropic", transport=httpx.MockTransport(
        lambda request: (seen.append(request), httpx.Response(200, json={}))[1]))
    try:
        with turn_usage_scope() as collector:
            with pytest.raises(HostProtocolRefused), model_usage_scope(
                    model="claude-sonnet-5", route="cloud"):
                await client.post("https://api.openai.com/v1/messages",
                                  json={"model": "claude-sonnet-5"})
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert not seen
    assert value["api_calls"] is None
    assert value["usage_basis"] == "unknown"


@pytest.mark.asyncio
async def test_nested_model_scopes_share_dispatch_evidence_in_real_agent_tool_loop():
    from agents.core.agent import Agent
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.tool_protocol import ToolTurn
    from agents.core.tool_rpc import ToolRPCServer

    class Backend:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            await client.post("https://openrouter.ai/api/v1/chat/completions",
                              json={"model": kwargs["model"]})
            return ToolTurn(content="done", usage=TokenUsage(
                input_tokens=3, output_tokens=2, counts_complete=True))

    server = ToolRPCServer()
    server.register_tool("echo", lambda args: args)
    agent = Agent.__new__(Agent)
    agent.id = "jarvis"
    agent._checkpoint_manager = None
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
    agent.tool_event_sink = lambda event: None
    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                assert await agent.generate_response(
                    Backend(), "claude-sonnet-5", "hello", "", 128, .2) == "done"
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] == 1
    assert (value["input_tokens"], value["output_tokens"]) == (3, 2)
    assert value["usage_basis"] == "provider_complete"


@pytest.mark.asyncio
async def test_replayed_same_usage_object_does_not_consume_later_dispatch():
    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    first = TokenUsage(input_tokens=3, output_tokens=2, counts_complete=True)
    second = TokenUsage(input_tokens=7, output_tokens=4, counts_complete=True)
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  json={"model": "claude-sonnet-5"})
                report_text_usage(first)
                await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  json={"model": "claude-sonnet-5"})
                report_text_usage(first)
                report_text_usage(second)
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] == 2
    assert value["input_tokens"] == 10
    assert value["output_tokens"] == 6


@pytest.mark.asyncio
async def test_legacy_text_publication_then_empty_tool_default_does_not_poison_usage():
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.tool_protocol import ToolTurn

    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  json={"model": "claude-sonnet-5"})
                report_text_usage(TokenUsage(input_tokens=3, output_tokens=2,
                                             counts_complete=True))
                AgentToolRuntime._report_usage(None, ToolTurn(content="done"))
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert value["api_calls"] == 1
    assert (value["input_tokens"], value["output_tokens"]) == (3, 2)
    assert value["usage_basis"] == "provider_complete"


@pytest.mark.asyncio
async def test_settled_tool_runtime_stop_is_published_only_by_owner_and_detaches_background():
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.tool_rpc import ToolRPCServer
    from agents.core.turn_stops import record_runtime_stop, turn_stops_scope
    from agents.core.turn_usage import detached_turn_usage

    class Backend:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            pytest.fail("the no-tools stop must happen before backend generation")

    runtime = AgentToolRuntime(ToolRPCServer(), enabled=lambda: True)
    with turn_stops_scope() as stops:
        result = await runtime.run_result(agent_id="jarvis", backend=Backend(),
                                          model="model", prompt="hello", system="")
        assert result.exit_reason == "no_tools"
        assert stops.snapshot() == ["no_tools"]
        with detached_turn_usage():
            record_runtime_stop("deadline")
        assert stops.snapshot() == ["no_tools"]


@pytest.mark.asyncio
async def test_internal_pair_and_pending_caps_fail_unknown_without_growth():
    from agents.core.turn_usage import _MAX_PAIRS, _MAX_PENDING
    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={})))
    try:
        with turn_usage_scope() as collector:
            for index in range(_MAX_PAIRS + 2):
                model = f"unique-{index}"
                with model_usage_scope(model=model, route="cloud"):
                    await client.post("https://openrouter.ai/api/v1/chat/completions",
                                      json={"model": model})
                    report_text_usage(TokenUsage(input_tokens=1, output_tokens=1,
                                                 counts_complete=True))
            assert len(collector._pairs) <= _MAX_PAIRS
            assert collector.snapshot()["usage_basis"] == "unknown"
        with turn_usage_scope() as collector:
            async def send(index):
                model = "claude-sonnet-5"
                with model_usage_scope(model=model, route="cloud"):
                    await client.post("https://openrouter.ai/api/v1/chat/completions",
                                      json={"model": model})
                    await asyncio.sleep(0)
            await asyncio.gather(*(send(i) for i in range(_MAX_PENDING + 2)))
            assert len(collector._pending) <= _MAX_PENDING
            assert collector.snapshot()["usage_basis"] == "unknown"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_caller_request_hook_runs_before_accounting_and_redirect_retries_count():
    seen = []

    def transport(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(307, headers={"location": "https://openrouter.ai/api/v1/chat/completions"})
        return httpx.Response(200, json={})

    async def caller_hook(request):
        request.headers["x-test-hook"] = "ran"

    client = llm_async_client("openrouter", transport=httpx.MockTransport(transport),
                              follow_redirects=True, event_hooks={"request": [caller_hook]})
    try:
        with turn_usage_scope() as collector:
            with model_usage_scope(model="claude-sonnet-5", route="cloud"):
                await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  json={"model": "claude-sonnet-5"})
                report_text_usage(TokenUsage(input_tokens=2, output_tokens=1,
                                             counts_complete=True))
            value = collector.snapshot()
    finally:
        await client.aclose()
    assert len(seen) == 2
    assert all(request.headers["x-test-hook"] == "ran" for request in seen)
    assert value["api_calls"] == 2
    assert value["input_tokens"] is None  # the 307 attempt has no certified usage
