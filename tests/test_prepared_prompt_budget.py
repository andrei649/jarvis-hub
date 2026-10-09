"""The prepared dispatch budget is checked against the bytes sent to generation."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.agent import Agent
from agents.core.conversation_clock import ClockSnapshot, render_snapshot
from agents.core.llm.tokenizer import estimate_tokens
from agents.core.route_compaction import RouteRefused, planning_scope, prepare_route


class Backend:
    def __init__(self, capacity=4096):
        self.capacity = capacity
        self.calls = []

    def context_window(self, _model):
        return self.capacity

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return "answer"


def router_for(backend):
    return SimpleNamespace(
        select_backend=lambda _agent, _prompt: (backend, "fixture", "local"),
        model_manager=None,
    )


async def prepared_for(router, prompt="question", *, max_tokens=512):
    return await prepare_route(router, "jarvis", prompt, max_tokens, 0, "s")


@pytest.mark.asyncio
async def test_budget_counts_canonical_history_and_cache_floor_without_double_counting_system():
    backend = Backend()
    router = router_for(backend)
    with planning_scope("s"):
        route = await prepared_for(router, "old context " * 1200)
        ceiling = int(0.85 * route.input_budget)
        assert estimate_tokens(route.prompt) > ceiling
        with pytest.raises(RouteRefused):
            route.check_budget("short cache tail", "")

        short_route = await prepared_for(router)
        short_route.check_budget("question", "small system", cached_input_tokens=0)
        system = "long but accepted identity " * 350
        cache_floor = ceiling - estimate_tokens("question") - 30
        assert estimate_tokens(system) + estimate_tokens("question") < ceiling
        assert cache_floor + estimate_tokens("question") < ceiling
        assert cache_floor + estimate_tokens("question") + estimate_tokens(system) > ceiling
        short_route.check_budget("question", system, cached_input_tokens=cache_floor)
        with pytest.raises(RouteRefused):
            short_route.check_budget("question", "small system", cached_input_tokens=ceiling)
        with pytest.raises(RouteRefused):
            short_route.check_budget("new unplanned material " * 1800, "small system")
        with pytest.raises(RouteRefused):
            short_route.check_budget("question", "small system", tools=[{"description": "schema " * 5000}])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"prompt": 7, "system": "system"},
        {"prompt": "question", "system": None},
        {"prompt": "question", "system": "system", "cached_input_tokens": True},
        {"prompt": "question", "system": "system", "cached_input_tokens": -1},
        {"prompt": "question", "system": "system", "tools": [object()]},
    ],
)
async def test_budget_refuses_invalid_inputs(kwargs):
    backend = Backend()
    with planning_scope("s"):
        route = await prepared_for(router_for(backend))
        with pytest.raises(RouteRefused):
            route.check_budget(**kwargs)


@pytest.mark.asyncio
async def test_generate_response_checks_clock_rendered_system_and_sends_same_string():
    from datetime import UTC, datetime

    backend = Backend(capacity=2048)
    router = router_for(backend)
    agent = Agent("jarvis", {}, router)
    clock = ClockSnapshot("s", datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 9, tzinfo=UTC), 1)
    with planning_scope("s"):
        route = await prepared_for(router, max_tokens=256)
        ceiling = int(0.85 * route.input_budget)
        system = ""
        while estimate_tokens(system) + estimate_tokens(route.prompt) < ceiling - 10:
            system += "ordinary system text "
        assert estimate_tokens(system) + estimate_tokens(route.prompt) < ceiling
        assert estimate_tokens(render_snapshot(system, clock)) + estimate_tokens(route.prompt) > ceiling

        with pytest.raises(RouteRefused):
            await agent.generate_response(
                backend, "fixture", route.prompt, system, 256, 0,
                session_id="s", clock_snapshot=clock, prepared_route=route,
            )
        assert backend.calls == []

        short = "short system"
        assert await agent.generate_response(
            backend, "fixture", route.prompt, short, 256, 0,
            session_id="s", clock_snapshot=clock, prepared_route=route,
        ) == "answer"
        assert backend.calls[0]["system"] == render_snapshot(short, clock)


@pytest.mark.asyncio
async def test_process_refuses_oversized_fresh_system_before_residency_or_checkpoint(monkeypatch):
    backend = Backend()
    router = router_for(backend)
    agent = Agent("jarvis", {}, router)
    agent.soul = {"content": "a much longer refreshed identity " * 2500}
    checkpoint_calls = []
    agent._checkpoint_manager = SimpleNamespace(
        save_agent_execution=lambda *args: checkpoint_calls.append(args),
        record_call=lambda *args, **kwargs: checkpoint_calls.append((args, kwargs)),
        clear_agent_checkpoint=lambda *args: checkpoint_calls.append(("cleared", args)),
    )
    residency_calls = []

    async def ensure(*args):
        residency_calls.append(args)

    monkeypatch.setattr(agent, "_ensure_resident", ensure)
    context = {"session_id": "s", "_clock_snapshot": None}
    prompt = agent.build_prompt("hello", context)
    with planning_scope("s"):
        route = await prepared_for(router, prompt)
        with pytest.raises(RouteRefused):
            await agent.process("hello", context, prepared=route)
    assert backend.calls == []
    assert residency_calls == []
    assert checkpoint_calls == []
    assert agent._failures == 0


@pytest.mark.asyncio
async def test_process_rechecks_schema_after_residency_before_new_checkpoint(monkeypatch):
    backend = Backend()
    router = router_for(backend)
    agent = Agent("jarvis", {}, router)
    agent.soul = {"content": "short persona"}
    schemas = []
    agent.tool_runtime = SimpleNamespace(
        _server=SimpleNamespace(tools=lambda: list(schemas)),
        can_run=lambda *_args, **_kwargs: False,
    )
    checkpoint_calls = []
    agent._checkpoint_manager = SimpleNamespace(
        save_agent_execution=lambda *args: checkpoint_calls.append(args),
        record_call=lambda *args, **kwargs: checkpoint_calls.append((args, kwargs)),
        clear_agent_checkpoint=lambda *args: checkpoint_calls.append(("cleared", args)),
    )

    async def ensure(*args):
        await asyncio.sleep(0)
        schemas.append({"description": "expanded live schema " * 4000})

    monkeypatch.setattr(agent, "_ensure_resident", ensure)
    context = {"session_id": "s", "_clock_snapshot": None}
    prompt = agent.build_prompt("hello", context)
    with planning_scope("s"):
        route = await prepared_for(router, prompt)
        with pytest.raises(RouteRefused):
            await agent.process("hello", context, prepared=route)
    assert backend.calls == []
    assert checkpoint_calls == []
    assert agent._failures == 0


@pytest.mark.asyncio
async def test_parallel_budget_refusal_preserves_peer_settlement(tmp_path, monkeypatch):
    """One specialist's refusal must not abandon another active specialist."""
    from agents.core.config import JarvisConfig
    from agents.core.memory import persistence
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    orch = Orchestrator(JarvisConfig())
    orch._session_id_default = "s"
    orch._resolve_session("s")
    orch.get_setting = lambda key, default=None: True if key == "memory.context_compression" else default
    orch._agent_call_timeout = lambda **_kwargs: (10, "flat")

    refused = asyncio.Event()
    release_peer = asyncio.Event()
    peer_finished = []
    reject = Agent("athena", {}, router_for(Backend()))
    peer = Agent("stark", {}, router_for(Backend()))

    async def refuse(*_args, **_kwargs):
        refused.set()
        raise RouteRefused()

    async def complete(*_args, **_kwargs):
        await release_peer.wait()
        peer_finished.append(True)
        return "peer answer"

    reject.process = refuse
    peer.process = complete
    orch.agents = {"athena": reject, "stark": peer}
    plan = SimpleNamespace(
        history="", routes={
            "athena": SimpleNamespace(route="local", model="fixture"),
            "stark": SimpleNamespace(route="local", model="fixture"),
        },
        prompts={"athena": ("prompt", 0, "a"), "stark": ("prompt", 0, "b")},
    )
    task = asyncio.create_task(
        orch._call_agents_parallel_prepared(["athena", "stark"], "hello", {}, prepared_plan=plan)
    )
    try:
        await asyncio.wait_for(refused.wait(), 2)
        await asyncio.sleep(0)
        assert not task.done(), "parallel gather must still wait for the peer"
        release_peer.set()
        result = await asyncio.wait_for(task, 2)
        from agents.core.conversation_clock import CONTEXT_REFUSED_REPLY

        assert result == {"athena": CONTEXT_REFUSED_REPLY, "stark": "peer answer"}
        assert peer_finished == [True]
        assert reject._failures == 0
    finally:
        release_peer.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
