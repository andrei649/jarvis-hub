"""H673 anchor publication and observation lifetimes."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from agents.core.llm.tool_protocol import TokenUsage


def _route():
    return SimpleNamespace(identity=object(), model="model")


def test_managed_store_is_eager_on_a_real_orchestrator(tmp_path, monkeypatch):
    from agents.core.config import JarvisConfig
    from agents.core.memory import conversation, persistence
    from agents.core.orchestrator import Orchestrator
    from agents.core.route_compaction import ManagedAnchorStore

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    orch = Orchestrator(JarvisConfig())
    assert isinstance(orch._managed_route_anchors, ManagedAnchorStore)


@pytest.mark.asyncio
async def test_fresh_nonstream_usage_has_no_anchor_sink_warning(tmp_path, monkeypatch, caplog):
    from agents.core.agent import Agent
    from agents.core.config import JarvisConfig
    from agents.core.llm.base import LLMBackend
    from agents.core.llm.usage_context import report_text_usage
    from agents.core.memory import conversation, persistence
    from agents.core.orchestrator import Orchestrator, _active_session

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)

    class Backend(LLMBackend):
        async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
            report_text_usage(TokenUsage(input_tokens=37, output_tokens=5))
            return "answer"

    orch = Orchestrator(JarvisConfig())
    backend = Backend()
    orch.llm_router = SimpleNamespace(
        select_backend=lambda aid, prompt: (backend, "model", "local"),
        model_manager=None,
    )
    agent = Agent("jarvis", {}, orch.llm_router)
    agent.soul = {"content": "identity"}
    orch.agents["jarvis"] = agent
    orch.get_setting = lambda key, default=None: (
        False if key == "memory.context_compression" else default
    )
    token = _active_session.set("fresh")
    try:
        with caplog.at_level("WARNING"):
            answer = await orch._call_agents_parallel(["jarvis"], "hello", {})
    finally:
        _active_session.reset(token)
    assert answer == {"jarvis": "answer"}
    assert orch._last_reported_usage["jarvis"].input_tokens == 37
    assert orch._last_reported_usage["jarvis"].output_tokens == 5
    assert "usage sink failed" not in caplog.text
    assert "tool loop usage sink failed" not in caplog.text
    assert len(orch._managed_route_anchors) == 0
    assert not hasattr(orch, "_context_anchor")


def test_managed_store_replaces_by_session_and_stays_bounded():
    from agents.core.route_compaction import ManagedAnchorStore, remember_usage, trusted_anchor

    store = ManagedAnchorStore()
    route = _route()
    rows = [{"role": "user", "content": "first"}]
    for index in range(300):
        remember_usage(store, f"s{index}", "agent", route, rows, "generation", TokenUsage(input_tokens=index + 1))
    assert len(store) == 256
    assert ("s0", "agent") not in store
    assert trusted_anchor(store, "s299", {"agent": route}, rows, "generation").prompt_tokens == 300
    assert trusted_anchor(store, "s298", {"agent": route}, rows, "generation").prompt_tokens == 299
    remember_usage(store, "s299", "agent", route, rows, "generation", TokenUsage(input_tokens=91))
    assert trusted_anchor(store, "s299", {"agent": route}, rows, "generation").prompt_tokens == 91
    assert trusted_anchor(store, "s299", {"agent": route}, rows, "other-generation") is None
    assert trusted_anchor(store, "s299", {"agent": route}, [{"role": "user", "content": "changed"}], "generation") is None


def test_managed_store_serializes_whole_writer_and_reader_operations():
    from agents.core.route_compaction import ManagedAnchorStore, remember_usage, trusted_anchor

    store = ManagedAnchorStore()
    route = _route()
    rows = [{"role": "user", "content": "first"}]
    started = Event()

    def write():
        started.set()
        remember_usage(store, "s", "agent", route, rows, "generation", TokenUsage(input_tokens=17))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.lock:
            future = pool.submit(write)
            assert started.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.05)
        future.result(timeout=2)
        started.clear()

        def read():
            started.set()
            return trusted_anchor(store, "s", {"agent": route}, rows, "generation")

        with store.lock:
            future = pool.submit(read)
            assert started.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.05)
        assert future.result(timeout=2).prompt_tokens == 17


@pytest.mark.asyncio
async def test_closed_observer_cannot_publish_late_managed_usage():
    from agents.core.llm.usage_context import observer_scope
    from agents.core.route_compaction import ManagedAnchorStore, remember_usage

    store = ManagedAnchorStore()
    route = _route()
    release = asyncio.Event()

    async def late(observer):
        await release.wait()
        observer(TokenUsage(input_tokens=99))

    with observer_scope(lambda usage: remember_usage(
        store, "s", "agent", route, [], "generation", usage
    )) as observer:
        task = asyncio.create_task(late(observer))
    release.set()
    await task
    assert len(store) == 0
