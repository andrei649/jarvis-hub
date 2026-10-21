"""Operating advice reaches generation and cache material exactly once."""

from types import SimpleNamespace

import pytest

from agents.core.agent import Agent
from agents.core.commands import Principal
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
from tests.test_h388_guidance_wiring import wired


class TextBackend:
    def __init__(self):
        self.requests = []

    async def generate(self, **kwargs):
        self.requests.append(kwargs)
        return "synthetic answer"

    async def generate_stream(self, **kwargs):
        self.requests.append(kwargs)
        kwargs["on_token"]("synthetic answer")
        return "synthetic answer"


def agent_for(monkeypatch, runtime, backend=None):
    monkeypatch.setattr(Agent, "_load_soul", lambda self: setattr(self, "soul", {"content": "PERSONA"}))
    monkeypatch.setattr(Agent, "_load_identity", lambda self: setattr(self, "identity", {"content": "AUTHORITY"}))
    router = SimpleNamespace(select_backend=lambda aid, prompt: (backend, "gpt-5", "local")) if backend else None
    agent = Agent("jarvis", {"name": "Jarvis", "model": "configured-model"}, router)
    agent.tool_runtime = runtime
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_actual_text_and_stream_generation_receive_authenticated_surface(monkeypatch, stream):
    runtime, _ = wired({"enabled": True})
    backend = TextBackend()
    agent = agent_for(monkeypatch, runtime)
    token = bind_turn_principal(Principal(channel="telegram", admin=True))
    emitted = []
    try:
        assert await agent.generate_response(backend, "gpt-5", "request", "AUTHORITY\nPERSONA", 128, 0.1,
            on_token=emitted.append if stream else None) == "synthetic answer"
    finally:
        reset_turn_principal(token)
    system = backend.requests[0]["system"]
    assert system.startswith("AUTHORITY\nPERSONA")
    assert "You are on Telegram" in system
    assert "# Tool-use enforcement" not in system and "session_search" not in system
    assert emitted == (["synthetic answer"] if stream else [])


@pytest.mark.asyncio
async def test_actual_synthesis_has_surface_guidance_without_claiming_tools(monkeypatch):
    runtime, _ = wired({"enabled": True})
    backend = TextBackend()
    agent = agent_for(monkeypatch, runtime, backend)
    token = bind_turn_principal(Principal(channel="telegram", admin=True))
    try:
        assert await agent.synthesize({"athena": "synthetic specialist result"}, None) == "synthetic answer"
    finally:
        reset_turn_principal(token)
    system = backend.requests[0]["system"]
    assert "AUTHORITY" in system and "PERSONA" in system
    assert "You are on Telegram" in system and "session_search" not in system
    assert "# Tool-use enforcement" not in system
    assert backend.requests[0]["model"] == "gpt-5"


@pytest.mark.asyncio
async def test_per_agent_guidance_override_is_live_and_independent(monkeypatch):
    runtime, values = wired({"enabled": True, "agents": {"jarvis": {"flags": {"platform_hint": False}}}})
    backend = TextBackend()
    agent = agent_for(monkeypatch, runtime)
    token = bind_turn_principal(Principal(channel="telegram", admin=True))
    try:
        await agent.generate_response(backend, "gpt-5", "request", "AUTHORITY", 128, 0.1)
        values["llm.operating_guidance"]["agents"]["jarvis"]["flags"]["platform_hint"] = True
        await agent.generate_response(backend, "gpt-5", "request", "AUTHORITY", 128, 0.1)
    finally:
        reset_turn_principal(token)
    assert "You are on Telegram" not in backend.requests[0]["system"]
    assert "You are on Telegram" in backend.requests[1]["system"]


@pytest.mark.asyncio
async def test_agent_disable_override_does_not_disable_another_agent():
    from tests.test_h388_guidance_runtime import Backend, run
    runtime, _ = wired({"enabled": True, "agents": {"jarvis": {"enabled": False}}})
    backend = Backend()
    assert await run(runtime, backend) == "done"
    assert backend.requests[0]["messages"][0]["content"] == "IDENTITY AUTHORITY\nPERSONA"
    other = Backend()
    assert await runtime.run(agent_id="athena", backend=other, model="gpt-5", prompt="synthetic request",
        system="OTHER AUTHORITY", max_tokens=64, temperature=0.1) == "done"
    assert "# Finishing the job" in other.requests[0]["messages"][0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("managed_clock", [False, True])
async def test_stream_cache_and_real_agent_generation_share_one_prepared_prefix(monkeypatch, tmp_path, managed_clock):
    from agents.core.checkpoint import CheckpointManager
    from agents.core.conversation_clock import prompt_clock
    from agents.core.llm.gemini_context import GeminiRequestBinding
    from tests.test_orchestrator_gemini_cache import _FakeCache, _orchestrator

    runtime, values = wired({"enabled": True})
    values["llm.tool_loop_enabled"] = False

    def hit(kwargs):
        # A live edit while lookup yields belongs to the next turn. The leased
        # prefix in this turn must still match what real Agent generation sends.
        values["llm.operating_guidance"]["enabled"] = False
        return GeminiRequestBinding(lease=kwargs["lease"], session_id=kwargs["session_id"],
            cache_name="cachedContents/synthetic", cached_prefix_count=1)

    cache = _FakeCache(hit)
    orch, backend, _, _ = _orchestrator(("[user]: synthetic prior",), cache=cache, monkeypatch=monkeypatch)
    orch.agents = {"jarvis": agent_for(monkeypatch, runtime)}
    manager = None
    if managed_clock:
        manager = CheckpointManager(str(tmp_path / "clock.db"))
        manager.initialize()
        manager.create_session_record("synthetic-cache")
        orch.checkpoints = manager
        orch.agents["jarvis"].set_checkpoint_manager(manager)
    clock_token = prompt_clock.set(manager.clock_snapshot("synthetic-cache") if manager else None)
    token = bind_turn_principal(Principal(channel="telegram", admin=True))
    try:
        await orch._handle_input_stream("synthetic current", channel="telegram", session_id="synthetic-cache")
    finally:
        reset_turn_principal(token)
        prompt_clock.reset(clock_token)
        if manager:
            manager.close()
    assert len(cache.acquire_calls) == len(backend.calls) == 1
    prefix = cache.acquire_calls[0]["system_instruction"]
    assert "You are on Telegram" in prefix
    assert backend.calls[0]["system"] == prefix
    assert prefix.count("# Operating guidance scope") == 1
    assert backend.calls[0]["binding"].cache_name == "cachedContents/synthetic"


@pytest.mark.asyncio
async def test_prepared_tool_prefix_is_rebuilt_once_without_stripping_authority_text(monkeypatch):
    from tests.test_h388_guidance_runtime import Backend

    runtime, _ = wired({"enabled": True})
    agent = agent_for(monkeypatch, runtime)
    backend = Backend()
    base = "AUTHORITY\n# Operating guidance scope\nThis heading is part of the authority contract."
    token = bind_turn_principal(Principal(channel="telegram", admin=True))
    try:
        prepare = getattr(agent, "model_system_prompt", lambda backend, model, system: system)
        prefix = prepare(backend, "gpt-5", base)
        assert await agent.generate_response(backend, "gpt-5", "request", prefix, 128, 0.1) == "done"
    finally:
        reset_turn_principal(token)
    system = backend.requests[0]["messages"][0]["content"]
    assert system.startswith(base)
    assert system.count("# Operating guidance scope") == 2
    assert system.count("# Finishing the job") == 1


@pytest.mark.asyncio
async def test_guidance_budget_covers_the_largest_real_family_prefix():
    from agents.core.llm.tokenizer import estimate_messages
    from tests.test_h388_guidance_runtime import Backend, run

    runtime, _ = wired({"enabled": True})
    budget = runtime.guidance_budget_tokens("jarvis")
    assert budget > 0
    for model in ("gpt-5", "gemini-2.5", "claude-sonnet"):
        backend = Backend()
        await run(runtime, backend, model=model)
        system = backend.requests[0]["messages"][0]["content"]
        advice = system.removeprefix("IDENTITY AUTHORITY\nPERSONA\n\n")
        assert budget >= estimate_messages([{"role": "system", "content": advice}])
