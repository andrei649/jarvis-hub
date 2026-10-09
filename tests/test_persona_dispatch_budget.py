"""A committed persona refresh must fit the prepared dispatch before model I/O."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.core.agent import Agent
from agents.core.checkpoint import CheckpointManager
from agents.core.config import JarvisConfig
from agents.core.conversation_clock import CONTEXT_REFUSED_REPLY
from agents.core.llm.base import LLMBackend, cloud_cap
from agents.core.llm.gemini_context import GeminiRequestBinding
from agents.core.llm.tokenizer import estimate_tokens
from agents.core.memory import persistence
from agents.core.orchestrator import Orchestrator
from agents.core.security.guardrails import GuardedCacheMaterial, GuardrailsEngine
from agents.core.security.types import RedactionMode
from tests.test_orchestrator_gemini_cache import _FakeCache, _RecordingGemini

SHORT_SOUL = "You are a careful assistant.\n"
SHORT_IDENTITY = "# Contract\nState verified facts plainly.\n"
LONG_SOUL = "You are a careful assistant who states verified facts plainly.\n" * 260
LONG_IDENTITY = "# Contract\n" + "- State verified facts plainly.\n" * 100


class _RecordingBackend(LLMBackend):
    def __init__(self):
        self.calls = []

    def context_window(self, model):
        return 4096

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.calls.append(("text", model, prompt, system, max_tokens))
        return "answer"

    async def generate_stream(
        self, model, prompt, system="", max_tokens=1024, temperature=0.7,
        on_token=None, on_activity=None,
    ):
        self.calls.append(("stream", model, prompt, system, max_tokens))
        if on_token is not None:
            result = on_token("answer")
            if hasattr(result, "__await__"):
                await result
        return "answer"


async def _case(tmp_path, monkeypatch, mode):
    from agents.core.context_compressor import ContextCompressor

    monkeypatch.setenv("JARVIS_APP_ROOT", str(tmp_path / "app"))
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    monkeypatch.delenv("JARVIS_SOUL_MAX_CHARS", raising=False)
    root = tmp_path / "app" / "agents"
    soul_path = root / "athena" / "SOUL.md"
    identity_path = root / "_identity" / "IDENTITY.local.md"
    soul_path.parent.mkdir(parents=True)
    identity_path.parent.mkdir(parents=True)
    soul_path.write_text(SHORT_SOUL, encoding="utf-8")
    identity_path.write_text(SHORT_IDENTITY, encoding="utf-8")

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    config_path = Path(__file__).resolve().parents[1] / "agents" / "_system" / "agents.yaml"
    orch = Orchestrator(JarvisConfig(str(config_path)))
    orch.checkpoints = CheckpointManager(str(tmp_path / "cp.db"))
    orch.checkpoints.initialize()
    orch.memory.set_checkpoint_manager(orch.checkpoints)
    orch.checkpoints.create_session_record("s")
    orch._session_id_default = "s"
    settings = {
        "memory.context_compression": True,
        "memory.context_window": 20,
        "memory.compression_max_tokens": 12000,
        "memory.compaction_protect_last": 1,
    }
    orch.get_setting = lambda key, default=None: settings.get(key, default)
    for n in range(12):
        await orch.memory.add_turn("s", "user", f"turn{n} " + "historical data " * 180)

    backend = _RecordingBackend()
    orch.llm_router = SimpleNamespace(
        active_model="irrelevant-large-model", _backend=object(), model_manager=None,
        select_backend=lambda aid, prompt: (backend, "small", "local"),
    )
    agent = Agent("athena", {}, orch.llm_router)
    assert agent.soul["content"] == SHORT_SOUL
    assert agent.identity["content"] == SHORT_IDENTITY.strip()
    agent._checkpoint_manager = orch.checkpoints
    agent._gen_params = lambda route: (512, 0)
    orch.agents["athena"] = agent
    orch._recall_block = AsyncMock(return_value="")
    orch._gather_plugin_data = AsyncMock(return_value={})
    orch._complete_llm_turn = AsyncMock()
    orch._dispatch_command = AsyncMock(return_value=None)
    orch._chat_control_enabled = lambda: False
    orch.router.classify = AsyncMock(return_value=SimpleNamespace(
        target_agents=["athena"], context={}, is_general=True, confidence=1,
    ))
    orch._route_candidates = lambda intent: ["athena"]
    execution_saves = []
    original_save = orch.checkpoints.save_agent_execution

    def record_execution(*args):
        execution_saves.append(args)
        return original_save(*args)

    monkeypatch.setattr(orch.checkpoints, "save_agent_execution", record_execution)
    if mode == "grown":
        soul_path.write_text(LONG_SOUL, encoding="utf-8")
        identity_path.write_text(LONG_IDENTITY, encoding="utf-8")
    elif mode == "bounded":
        soul_path.write_text(SHORT_SOUL + "Keep replies concise.\n", encoding="utf-8")
        identity_path.write_text(SHORT_IDENTITY + "- Cite uncertainty.\n", encoding="utf-8")
    elif mode == "cas":
        soul_path.write_text(LONG_SOUL, encoding="utf-8")
        identity_path.write_text(LONG_IDENTITY, encoding="utf-8")
        monkeypatch.setattr(orch.checkpoints, "commit_clock", lambda *args: None)
    elif mode == "history-race":
        soul_path.write_text(LONG_SOUL, encoding="utf-8")
        identity_path.write_text(LONG_IDENTITY, encoding="utf-8")
        original_compact = ContextCompressor.compact
        changed = []

        async def concurrent_write(compressor, *args, **kwargs):
            result = await original_compact(compressor, *args, **kwargs)
            if not changed:
                changed.append(True)
                await orch.memory.add_turn("s", "user", "concurrent retained turn")
            return result

        monkeypatch.setattr(ContextCompressor, "compact", concurrent_write)
    else:
        raise AssertionError(mode)
    return orch, agent, backend, execution_saves


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["text", "sse"])
@pytest.mark.parametrize("mode", ["grown", "bounded", "cas", "history-race"])
async def test_prepared_dispatch_uses_committed_persona_without_oversized_request(
    tmp_path, monkeypatch, stream, mode,
):
    orch, agent, backend, execution_saves = await _case(tmp_path, monkeypatch, mode)
    streamed = []
    try:
        if stream:
            reply = await orch.handle_input_stream(
                "now", channel="web", session_id="s", agent_override="athena",
                on_token=streamed.append,
            )
        else:
            reply = await orch.handle_input(
                "now", channel="web", session_id="s", agent_override="athena",
            )
        revision = orch.checkpoints.clock_snapshot("s").revision
        if mode == "grown":
            assert revision == 1, "the new persona is published after a real accepted fold"
            assert agent.soul["content"] == LONG_SOUL
            assert agent.identity["content"] == LONG_IDENTITY.strip()
            assert estimate_tokens(agent.system_prompt()) > int(0.85 * (4096 - 512))
            assert reply == CONTEXT_REFUSED_REPLY
            assert backend.calls == []
            assert execution_saves == []
            assert orch.checkpoints.load("athena", "s") is None
            assert "answer" not in streamed
        elif mode == "bounded":
            assert revision == 1
            assert agent.soul["content"].endswith("Keep replies concise.\n")
            assert agent.identity["content"].endswith("- Cite uncertainty.")
            assert reply == "answer" and len(backend.calls) == 1
            assert backend.calls[0][3].startswith(agent.system_prompt())
            assert len(execution_saves) == (0 if stream else 1)
        else:
            assert reply == CONTEXT_REFUSED_REPLY
            assert revision == 0
            assert agent.soul["content"] == SHORT_SOUL
            assert agent.identity["content"] == SHORT_IDENTITY.strip()
            assert backend.calls == [] and execution_saves == []
    finally:
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_grown_persona_refuses_before_gemini_lease_or_cache_side_effects(tmp_path, monkeypatch):
    orch, agent, _local, execution_saves = await _case(tmp_path, monkeypatch, "grown")
    backend = _RecordingGemini()
    backend.context_window = lambda model: 4096

    async def offline_stream(model, prompt, system="", max_tokens=1024, temperature=0.7,
                             on_token=None, on_activity=None):
        backend.calls.append({"model": model, "prompt": prompt, "system": system})
        if on_token is not None:
            on_token("gemini answer")
        return "gemini answer"

    backend.generate_stream = offline_stream
    orch.llm_router.select_backend = lambda aid, prompt: (backend, "gemini-test", "cloud")
    agent.llm_router = orch.llm_router
    cache = _FakeCache()
    orch.context_cache = cache
    orch.security = GuardrailsEngine(backend=None, mode=RedactionMode.WARN)
    try:
        reply = await orch.handle_input_stream(
            "now", channel="web", session_id="s", agent_override="athena",
        )
        await asyncio.gather(*tuple(orch._cache_tasks))
        assert orch.checkpoints.clock_snapshot("s").revision == 1
        assert agent.soul["content"] == LONG_SOUL
        assert agent.identity["content"] == LONG_IDENTITY.strip()
        assert (backend.lease_calls, len(cache.acquire_calls), len(cache.create_calls),
                len(backend.calls)) == (0, 0, 0, 0)
        assert reply == CONTEXT_REFUSED_REPLY
        assert cache.acquire_calls == [] and cache.create_calls == []
        assert backend.calls == [] and execution_saves == []
    finally:
        orch.checkpoints.close()


async def _gemini_case(tmp_path, monkeypatch, binding_factory=None):
    orch, agent, _local, execution_saves = await _case(tmp_path, monkeypatch, "bounded")
    backend = _RecordingGemini()
    backend.context_window = lambda model: 4096

    async def offline_stream(model, prompt, system="", max_tokens=1024, temperature=0.7,
                             on_token=None, on_activity=None):
        backend.calls.append({"model": model, "prompt": prompt, "system": system,
                              "binding": backend.current_binding()})
        if on_token is not None:
            on_token("gemini answer")
        return "gemini answer"

    backend.generate_stream = offline_stream
    orch.llm_router.select_backend = lambda aid, prompt: (backend, "gemini-test", "cloud")
    agent.llm_router = orch.llm_router
    cache = _FakeCache(binding_factory)
    orch.context_cache = cache
    orch.security = GuardrailsEngine(backend=None, mode=RedactionMode.WARN)
    return orch, agent, backend, cache, execution_saves


@pytest.mark.asyncio
async def test_bounded_committed_persona_dispatches_with_a_cache_binding(tmp_path, monkeypatch):
    def binding(kwargs):
        return GeminiRequestBinding(
            lease=kwargs["lease"], session_id=kwargs["session_id"],
            cache_name="cachedContents/accepted", cached_prefix_count=1,
        )

    orch, agent, backend, cache, saves = await _gemini_case(tmp_path, monkeypatch, binding)
    try:
        reply = await orch.handle_input_stream(
            "now", channel="web", session_id="s", agent_override="athena",
        )
        assert orch.checkpoints.clock_snapshot("s").revision == 1
        assert agent.soul["content"].endswith("Keep replies concise.\n")
        assert reply == "gemini answer"
        assert len(cache.acquire_calls) == len(backend.calls) == 1
        assert backend.calls[0]["binding"].cache_name == "cachedContents/accepted"
        assert cache.create_calls == [] and saves == []
    finally:
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_oversized_guarded_cache_material_refuses_before_cache_lookup(tmp_path, monkeypatch):
    orch, _agent, backend, cache, saves = await _gemini_case(tmp_path, monkeypatch)
    prepare = orch.security.prepare_cache_material

    def oversized_material(system, history):
        material = prepare(system, history)
        return GuardedCacheMaterial(
            system_instruction=material.system_instruction,
            history=("verified history " * 1800, *material.history),
            policy_fingerprint=material.policy_fingerprint,
        )

    monkeypatch.setattr(orch.security, "prepare_cache_material", oversized_material)
    try:
        reply = await orch.handle_input_stream(
            "now", channel="web", session_id="s", agent_override="athena",
        )
        assert orch.checkpoints.clock_snapshot("s").revision == 1
        assert reply == CONTEXT_REFUSED_REPLY
        assert backend.lease_calls == 1
        assert cache.acquire_calls == cache.create_calls == backend.calls == saves == []
    finally:
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_bound_cache_prefix_plus_rebuilt_tail_refuses_before_model(tmp_path, monkeypatch):
    def binding(kwargs):
        assert len(kwargs["history"]) >= 1
        return GeminiRequestBinding(
            lease=kwargs["lease"], session_id=kwargs["session_id"],
            cache_name="cachedContents/expanded", cached_prefix_count=1,
        )

    orch, _agent, backend, cache, saves = await _gemini_case(tmp_path, monkeypatch, binding)
    prepare = orch.security.prepare_cache_material

    def enlarged_prefix(system, history):
        material = prepare(system, history)
        limit = int(0.85 * (4096 - cloud_cap(512)))
        fixed = estimate_tokens(material.system_instruction) + sum(
            estimate_tokens(part) for part in material.history[1:]
        )
        low, high = 0, 1000
        while low < high:
            mid = (low + high + 1) // 2
            if fixed + estimate_tokens(material.history[0] + " verified detail" * mid) <= limit:
                low = mid
            else:
                high = mid - 1
        prefix = material.history[0] + " verified detail" * low
        assert low > 0 and fixed + estimate_tokens(prefix) <= limit
        return GuardedCacheMaterial(
            system_instruction=material.system_instruction,
            history=(prefix, *material.history[1:]),
            policy_fingerprint=material.policy_fingerprint,
        )

    monkeypatch.setattr(orch.security, "prepare_cache_material", enlarged_prefix)
    try:
        reply = await orch.handle_input_stream(
            "now", channel="web", session_id="s", agent_override="athena",
        )
        assert orch.checkpoints.clock_snapshot("s").revision == 1
        assert reply == CONTEXT_REFUSED_REPLY
        assert backend.lease_calls == 1
        assert len(cache.acquire_calls) == 1
        assert cache.create_calls == backend.calls == saves == []
    finally:
        orch.checkpoints.close()
