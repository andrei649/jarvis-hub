"""Shared history is bounded by actual specialist dispatch contracts."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "max_tokens,route,reserve",
    [(2048, "local-deep", 2048), (0, "local", None), (0, "cloud-compatible", 8192)],
)
async def test_actual_specialist_budget_not_router_default(max_tokens, route, reserve):
    from agents.core.route_compaction import planning_scope, prepare_route

    backend = SimpleNamespace(context_window=lambda model: 16384)
    router = SimpleNamespace(
        active_model="irrelevant-128k",
        select_backend=lambda agent, prompt: (backend, "specialist", route),
    )
    with planning_scope("session"):
        record = await prepare_route(router, "athena", "full prompt", max_tokens, 0.2, "session")
        assert record.model == "specialist" and record.window.tokens == 16384
        assert record.output_reserve == reserve
        assert record.input_budget == 16384 - (reserve or 0)
        assert record.backend is backend


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 0, -1, "8192", float("nan")])
async def test_invalid_actual_metadata_refuses(value):
    from agents.core.route_compaction import RouteRefused, planning_scope, prepare_route

    backend = SimpleNamespace(context_window=lambda model: value)
    router = SimpleNamespace(select_backend=lambda *args: (backend, "specialist", "local"))
    with planning_scope("s"), pytest.raises(RouteRefused):
        await prepare_route(router, "a", "p", 1024, 0, "s")


@pytest.mark.asyncio
async def test_impossible_finite_reserve_refuses_not_one_token():
    from agents.core.route_compaction import RouteRefused, planning_scope, prepare_route

    backend = SimpleNamespace(context_window=lambda model: 8192)
    router = SimpleNamespace(select_backend=lambda *args: (backend, "specialist", "local"))
    with planning_scope("s"), pytest.raises(RouteRefused):
        await prepare_route(router, "a", "p", 8192, 0, "s")


@pytest.mark.asyncio
async def test_selected_ollama_resolves_its_own_num_ctx(monkeypatch):
    from agents.core.llm.base import OllamaBackend
    from agents.core.route_compaction import planning_scope, prepare_route

    backend = OllamaBackend.__new__(OllamaBackend)
    seen = []

    async def resolve(model):
        seen.append(model)
        return 4096

    monkeypatch.setattr(backend, "context_window", lambda model: None)
    monkeypatch.setattr(backend, "resolve_context_window", resolve)
    router = SimpleNamespace(
        _backend=object(), select_backend=lambda *args: (backend, "actual", "ollama")
    )
    with planning_scope("s"):
        result = await prepare_route(router, "a", "p", 1024, 0, "s")
        assert result.input_budget == 3072 and seen == ["actual"]


@pytest.mark.asyncio
async def test_prepared_route_rechecks_policy_and_revokes_on_exit():
    from agents.core.route_compaction import RouteRefused, planning_scope, prepare_route

    backend = SimpleNamespace(context_window=lambda model: 8192)
    selected = [backend, "first", "local"]
    router = SimpleNamespace(select_backend=lambda *args: tuple(selected))
    with planning_scope("s"):
        record = await prepare_route(router, "a", "p", 1024, 0, "s")
        record.check(router, "a", "p", "s")
        selected[1] = "changed"
        with pytest.raises(RouteRefused):
            record.check(router, "a", "p", "s")
    with pytest.raises(RouteRefused):
        record.check(router, "a", "p", "s")


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [16384, None])
async def test_agent_executes_prepared_route_and_refuses_changed_policy(monkeypatch, window):
    from agents.core.agent import Agent
    from agents.core.route_compaction import RouteRefused, planning_scope, prepare_route

    calls = []

    class Backend:
        def context_window(self, model):
            return window

        async def generate(self, **kwargs):
            calls.append(kwargs)
            return "done"

    backend = Backend()
    selected = [backend, "actual", "local"]
    router = SimpleNamespace(select_backend=lambda *args: tuple(selected), model_manager=None)
    agent = Agent("jarvis", {}, router)
    agent.soul = {"content": "identity"}
    monkeypatch.setattr(agent, "_gen_params", lambda route: (1024, 0))
    monkeypatch.setattr(
        agent, "_ensure_resident", __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
    )
    original_generate = agent.generate_response

    async def checked_generate(**kwargs):
        assert kwargs["effective_window"].tokens == window
        return await original_generate(**kwargs)

    monkeypatch.setattr(agent, "generate_response", checked_generate)
    context = {"session_id": "s"}
    prompt = agent.build_prompt("hello", context)
    with planning_scope("s"):
        prepared = await prepare_route(router, "jarvis", prompt, 1024, 0, "s")
        assert await agent.process("hello", context, prepared=prepared) == "done"
        assert calls[0]["model"] == "actual"
        selected[1] = "changed"
        with pytest.raises(RouteRefused):
            await agent.process("hello", context, prepared=prepared)
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_shared_plan_replans_tighter_final_route_and_publishes_once():
    from agents.core.route_compaction import HistoryStage, plan_shared, planning_scope

    large = SimpleNamespace(context_window=lambda model: 128000)
    small = SimpleNamespace(context_window=lambda model: 8000)
    router = SimpleNamespace(
        select_backend=lambda agent, prompt: (
            (large, "large", "local") if len(prompt) > 1000 else (small, "small", "local")
        )
    )
    budgets = []
    published = []

    async def build(history):
        return {"a": (history, 0)}

    async def stage(budget, routes):
        budgets.append(budget)
        return HistoryStage("short", lambda: published.append(budget))

    with planning_scope("s"):
        plan = await plan_shared(
            "x" * 2000, router, build, stage, lambda aid, route: (1024, 0), "s"
        )
        assert len(budgets) == 2 and budgets[1] < budgets[0]
        assert plan.routes["a"].model == "small" and len(published) == 1


@pytest.mark.asyncio
async def test_unstable_route_never_publishes():
    from agents.core.route_compaction import HistoryStage, RouteRefused, plan_shared, planning_scope

    backends = [
        SimpleNamespace(context_window=lambda model: 8000),
        SimpleNamespace(context_window=lambda model: 8000),
    ]
    calls = []

    def choose(*args):
        calls.append(1)
        return backends[len(calls) % 2], "m", "local"

    router = SimpleNamespace(select_backend=choose)
    published = []

    async def build(history):
        return {"a": (history, 0)}

    async def stage(budget, routes):
        return HistoryStage("short", lambda: published.append(1))

    with planning_scope("s"), pytest.raises(RouteRefused):
        await plan_shared("short", router, build, stage, lambda aid, route: (1024, 0), "s")
    assert not published


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("mode", ["finite", "auto", "cas-failure", "history-race"])
async def test_actual_orchestrator_compacts_for_specialist_routes(
    tmp_path, monkeypatch, stream, mode
):
    from unittest.mock import AsyncMock

    from agents.core.agent import Agent
    from agents.core.checkpoint import CheckpointManager
    from agents.core.config import JarvisConfig
    from agents.core.llm.base import LLMBackend
    from agents.core.llm.tokenizer import estimate_tokens
    from agents.core.memory import persistence
    from agents.core.orchestrator import Orchestrator, _active_session

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    orch = Orchestrator(JarvisConfig())
    orch.checkpoints = CheckpointManager(str(tmp_path / "cp.db"))
    orch.checkpoints.initialize()
    orch.memory.set_checkpoint_manager(orch.checkpoints)
    orch.checkpoints.create_session_record("s")
    orch._session_id_default = "s"
    token = _active_session.set("s")
    settings = {
        "memory.context_compression": True,
        "memory.context_window": 20,
        "memory.compression_max_tokens": 12000,
        "memory.compaction_protect_last": 1,
    }
    orch.get_setting = lambda key, default=None: settings.get(key, default)
    for n in range(12):
        await orch.memory.add_turn("s", "user", f"turn{n} " + "historical data " * 180)
    calls = []

    class Backend(LLMBackend):
        def context_window(self, model):
            return 4096 if model == "small" else 8192

        async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
            calls.append((model, estimate_tokens(prompt) + estimate_tokens(system), max_tokens))
            from agents.core.llm.tool_protocol import TokenUsage
            from agents.core.llm.usage_context import report_text_usage

            report_text_usage(
                TokenUsage(input_tokens=2000 if model == "small" else 3000, cache_read=50)
            )
            return "answer"

    backend = Backend()
    orch.llm_router = SimpleNamespace(
        active_model="llama-3.1-128k",
        _backend=object(),
        model_manager=None,
        select_backend=lambda aid, prompt: (
            backend,
            "small" if aid == "athena" else "larger",
            "local",
        ),
    )
    for aid in ("athena", "stark"):
        agent = Agent(aid, {}, orch.llm_router)
        agent.soul = {"content": "identity"}
        agent._checkpoint_manager = orch.checkpoints
        agent._gen_params = lambda route: (0 if mode == "auto" else 512, 0)
        orch.agents[aid] = agent
    orch._recall_block = AsyncMock(return_value="")
    orch._gather_plugin_data = AsyncMock(return_value={})
    orch._complete_llm_turn = AsyncMock()
    orch._dispatch_command = AsyncMock(return_value=None)
    orch._chat_control_enabled = lambda: False
    orch.router.classify = AsyncMock(
        return_value=SimpleNamespace(
            target_agents=["athena", "stark"], context={}, is_general=True, confidence=1
        )
    )
    orch._route_candidates = lambda intent: ["athena", "stark"]
    if mode == "cas-failure":
        monkeypatch.setattr(orch.checkpoints, "commit_clock", lambda *args: None)
    if mode == "history-race":
        from agents.core.context_compressor import ContextCompressor

        original = ContextCompressor.compact
        changed = []

        async def concurrent_write(compressor, *args, **kwargs):
            result = await original(compressor, *args, **kwargs)
            if not changed:
                changed.append(True)
                await orch.memory.add_turn("s", "user", "concurrent retained turn")
            return result

        monkeypatch.setattr(ContextCompressor, "compact", concurrent_write)
    try:
        if mode in {"cas-failure", "history-race"} and not stream:
            from agents.core.conversation_clock import CompactionClockRefused

            with pytest.raises(CompactionClockRefused):
                await orch._call_agents_parallel(["athena", "stark"], "now", {})
        elif stream:
            await orch.handle_input_stream("now", channel="web", session_id="s")
        else:
            await orch._call_agents_parallel(["athena", "stark"], "now", {})
        if mode in {"cas-failure", "history-race"}:
            assert not calls and orch.checkpoints.clock_snapshot("s").revision == 0
        else:
            assert {c[0] for c in calls} == {"small", "larger"}
            assert all(
                used + reserve <= (4096 if model == "small" else 8192)
                for model, used, reserve in calls
            )
            if mode == "auto":
                assert all(
                    reserve == 0 and used <= int(0.85 * (4096 if model == "small" else 8192))
                    for model, used, reserve in calls
                )
            assert orch.checkpoints.clock_snapshot("s").revision == 1
            assert orch._managed_route_anchors[("s", "athena")].tokens == 2050
            assert orch._managed_route_anchors[("s", "stark")].tokens == 3050
    finally:
        _active_session.reset(token)
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_usage_anchor_requires_route_session_generation_and_prefix():
    from collections import OrderedDict

    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.route_compaction import (
        planning_scope,
        prepare_route,
        remember_usage,
        trusted_anchor,
    )

    backend = SimpleNamespace(context_window=lambda model: 16000)
    router = SimpleNamespace(select_backend=lambda *args: (backend, "model", "local"))
    store = OrderedDict()
    rows = [{"role": "user", "content": "before"}]
    with planning_scope("s"):
        route = await prepare_route(router, "a", "p", 1024, 0, "s")
        remember_usage(store, "s", "a", route, rows, "generation", TokenUsage(input_tokens=9000))
        anchor = trusted_anchor(
            store, "s", {"a": route}, rows + [{"role": "user", "content": "next"}], "generation"
        )
        assert anchor.prompt_tokens == 9000 and anchor.covers == 1
        assert trusted_anchor(store, "other", {"a": route}, rows, "generation") is None
        assert trusted_anchor(store, "s", {"a": route}, rows, "new-generation") is None
        assert (
            trusted_anchor(
                store, "s", {"a": route}, [{"role": "user", "content": "changed"}], "generation"
            )
            is None
        )
        router.select_backend = lambda *args: (backend, "other-model", "local")
        other = await prepare_route(router, "a", "p", 1024, 0, "s")
        assert trusted_anchor(store, "s", {"a": other}, rows, "generation") is None


@pytest.mark.asyncio
async def test_window_shrinking_after_plan_refuses_before_execution():
    from agents.core.route_compaction import RouteRefused, planning_scope, prepare_route

    size = [8192]
    backend = SimpleNamespace(context_window=lambda model: size[0])
    router = SimpleNamespace(select_backend=lambda *args: (backend, "model", "local"))
    with planning_scope("s"):
        record = await prepare_route(router, "a", "p", 1024, 0, "s")
        size[0] = 4096
        with pytest.raises(RouteRefused):
            record.check(router, "a", "p", "s")


@pytest.mark.asyncio
async def test_responses_reserves_actual_product_output_ceiling():
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.route_compaction import planning_scope, prepare_route

    backend = ResponsesBackend.__new__(ResponsesBackend)
    router = SimpleNamespace(select_backend=lambda *args: (backend, "gpt-4.1", "cloud-compatible"))
    with planning_scope("s"):
        route = await prepare_route(router, "a", "p", 100000, 0, "s")
        assert route.max_tokens == 100000 and route.output_reserve == 32768


@pytest.mark.asyncio
async def test_unknown_capacity_stays_estimated_and_async_metadata_refuses():
    from agents.core.route_compaction import RouteRefused, planning_scope, prepare_route

    backend = SimpleNamespace()
    router = SimpleNamespace(select_backend=lambda *args: (backend, "uncatalogued-model", "local"))
    with planning_scope("s"):
        result = await prepare_route(router, "a", "p", 1024, 0, "s")
        assert result.estimated_window and result.window.tokens is None
        assert result.capacity == 32000

        async def invalid(model):
            return 8192

        backend.context_window = invalid
        with pytest.raises(RouteRefused):
            await prepare_route(router, "a", "p", 1024, 0, "s")


@pytest.mark.asyncio
async def test_expired_planner_cannot_publish_delayed_compaction():
    import asyncio

    from agents.core.route_compaction import HistoryStage, RouteRefused, plan_shared, planning_scope

    backend = SimpleNamespace(context_window=lambda model: 8000)
    router = SimpleNamespace(select_backend=lambda *args: (backend, "model", "local"))
    ready, release = asyncio.Event(), asyncio.Event()
    published = []

    async def build(history):
        return {"a": (history, 0)}

    async def stage(budget, routes):
        ready.set()
        await release.wait()
        return HistoryStage("short", lambda: published.append(True))

    with planning_scope("s"):
        child = asyncio.create_task(
            plan_shared("short", router, build, stage, lambda aid, route: (1024, 0), "s")
        )
        await ready.wait()
    release.set()
    with pytest.raises(RouteRefused):
        await child
    assert not published


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_wrapper_lifetime_preserves_unmanaged_children(managed, stream):
    import asyncio

    from agents.core.orchestrator import Orchestrator
    from agents.core.route_compaction import RouteRefused

    orch = Orchestrator.__new__(Orchestrator)
    orch._session_id_default = "s"
    orch.get_setting = lambda *args: managed
    release = asyncio.Event()
    children = []

    async def dispatch(text):
        if stream:
            return await orch._handle_input_stream(text, session_id="s")
        return await orch._call_agents_parallel([], text, {})

    async def inner(*args, **kwargs):
        text = args[0] if stream else args[1]
        if text == "parent":

            async def child():
                await release.wait()
                return await dispatch("child")

            children.append(asyncio.create_task(child()))
        return text

    if stream:
        orch._handle_input_stream_prepared = inner
    else:
        orch._call_agents_parallel_prepared = inner
    assert await dispatch("parent") == "parent"
    release.set()
    if managed:
        with pytest.raises(RouteRefused):
            await children[0]
    else:
        assert await children[0] == "child"


@pytest.mark.asyncio
async def test_actual_unmanaged_agent_child_keeps_legacy_dispatch(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from agents.core.agent import Agent
    from agents.core.config import JarvisConfig
    from agents.core.llm.base import LLMBackend
    from agents.core.memory import persistence
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    orch = Orchestrator(JarvisConfig())
    orch._session_id_default = "s"
    orch.get_setting = lambda key, default=None: (
        False if key == "memory.context_compression" else default
    )
    release = asyncio.Event()
    children = []
    calls = []

    class Backend(LLMBackend):
        async def generate(self, model, prompt, **kwargs):
            calls.append(prompt)
            if "PARENT_FIXTURE_TOKEN" in prompt:

                async def child():
                    await release.wait()
                    return await orch._call_agents_parallel(["jarvis"], "child", {})

                children.append(asyncio.create_task(child()))
            return "answer"

    backend = Backend()
    orch.llm_router = SimpleNamespace(
        select_backend=lambda *args: (backend, "fixture", "local"), model_manager=None
    )
    agent = Agent("jarvis", {}, orch.llm_router)
    agent.soul = {"content": "identity"}
    agent._gen_params = lambda route: (128, 0)
    orch.agents = {"jarvis": agent}
    orch._recall_block = AsyncMock(return_value="")
    assert await orch._call_agents_parallel(["jarvis"], "PARENT_FIXTURE_TOKEN", {}) == {
        "jarvis": "answer"
    }
    release.set()
    assert await children[0] == {"jarvis": "answer"}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unknown_generation_never_creates_trusted_usage_anchor():
    from collections import OrderedDict

    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.route_compaction import (
        planning_scope,
        prepare_route,
        remember_usage,
        trusted_anchor,
    )

    backend = SimpleNamespace(context_window=lambda model: 8000)
    router = SimpleNamespace(select_backend=lambda *args: (backend, "model", "local"))
    store = OrderedDict()
    rows = [{"role": "user", "content": "same bytes"}]
    with planning_scope("s"):
        route = await prepare_route(router, "a", "p", 1024, 0, "s")
        remember_usage(store, "s", "a", route, rows, "", TokenUsage(input_tokens=3000))
        assert not store
        assert trusted_anchor(store, "s", {"a": route}, rows, "") is None


@pytest.mark.asyncio
async def test_known_auto_tool_capacity_is_reserved_without_changing_provider_auto():
    from agents.core.route_compaction import HistoryStage, plan_shared, planning_scope

    backend = SimpleNamespace(context_window=lambda model: 8192, supports_tools=True)
    router = SimpleNamespace(select_backend=lambda *args: (backend, "actual", "local"))
    budgets = []

    async def build(history):
        return {"jarvis": ("prompt", 0, "input", True)}

    async def stage(budget, routes):
        budgets.append(budget)
        return HistoryStage("", lambda: None)

    with planning_scope("s"):
        plan = await plan_shared("", router, build, stage, lambda *args: (0, 0), "s")
        route = plan.routes["jarvis"]
        assert route.max_tokens == 0 and route.output_reserve is None
        assert route.tool_output_reserve == 2048
        assert budgets == [int(0.85 * (8192 - 2048))]
