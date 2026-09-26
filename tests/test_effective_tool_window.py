"""Actual ordinary tool turns honor immutable configured/cached capacity."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.core import agent_runtime
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.tool_result_store import ToolResultStore
from tests.test_tool_loop_result_spill import _Backend, _run, _server


def resolve_effective_window(backend, model):
    from agents.core.llm.effective_window import resolve_effective_window as resolve
    return resolve(backend, model)


@pytest.mark.parametrize('value', [4096, None])
def test_metadata_snapshot(value):
    calls = []
    backend = SimpleNamespace(context_window=lambda model: calls.append(model) or value)
    snapshot = resolve_effective_window(backend, 'm')
    assert snapshot.valid and snapshot.tokens == value
    assert calls == ['m']


@pytest.mark.parametrize('value', [False, True, 0, -1, '4096', 4096.0, []])
def test_invalid_metadata(value):
    assert not resolve_effective_window(SimpleNamespace(context_window=lambda _: value), 'm').valid


def test_missing_metadata():
    assert resolve_effective_window(object(), 'm').tokens is None


def test_throwing_and_async_metadata():
    def broken(model):
        raise RuntimeError('metadata failed')
    async def asynchronous(model):
        return 4096
    for reader in (broken, asynchronous):
        assert not resolve_effective_window(SimpleNamespace(context_window=reader), 'm').valid


@pytest.fixture(autouse=True)
def deterministic_tokens(monkeypatch):
    monkeypatch.setattr(agent_runtime, 'estimate_messages',
                        lambda messages: sum(len(str(m.get('content', ''))) for m in messages) // 4)


@pytest.mark.asyncio
async def test_loaded_window_spills_before_next_turn(tmp_path):
    backend = _Backend(1)
    backend.context_window = lambda _: 4096
    runtime = AgentToolRuntime(_server(30000), enabled=lambda: True,
                               max_result_bytes=50000, result_store=ToolResultStore(tmp_path))
    assert await _run(runtime, backend, model='llama3.1:8b') == 'done'
    assert agent_runtime.estimate_messages(backend.calls[-1]) < 4096 - 256
    assert list(tmp_path.glob('*.json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('reserve,prompt', [(4000, 'hello'), (256, 'x' * 20000)])
async def test_impossible_initial_request_never_generates(tmp_path, reserve, prompt):
    backend = _Backend(0)
    backend.context_window = lambda _: 4096
    runtime = AgentToolRuntime(_server(1), enabled=lambda: True)
    result = await runtime.run(agent_id='nerva', backend=backend, model='llama3.1:8b',
                               prompt=prompt, max_tokens=reserve)
    assert result == agent_runtime._CONTEXT_REPLY
    assert backend.calls == []


@pytest.mark.asyncio
async def test_concurrent_windows_and_owner_override(tmp_path):
    runtime = AgentToolRuntime(_server(30000), enabled=lambda: True, max_result_bytes=50000,
                               context_window_tokens=lambda: 128000,
                               context_budget_tokens=lambda: 128000,
                               result_store=ToolResultStore(tmp_path))
    small, large = _Backend(1), _Backend(1)
    small.context_window = lambda _: 4096
    large.context_window = lambda _: 65536
    assert await asyncio.gather(_run(runtime, small), _run(runtime, large)) == ['done', 'done']
    assert agent_runtime.estimate_messages(small.calls[-1]) < 4096
    assert agent_runtime.estimate_messages(large.calls[-1]) > 4096


@pytest.mark.asyncio
async def test_actual_agent_process_keeps_guard_and_raw_metadata(tmp_path):
    from agents.core.agent import Agent
    from agents.core.security.guardrails import GuardrailsEngine
    backend = _Backend(1)
    reads = []
    backend.context_window = lambda model: reads.append(model) or 4096
    router = SimpleNamespace(model_manager=None, select_backend=lambda *_: (backend, 'llama3.1:8b', 'local-fast'))
    agent = Agent('athena', {'name': 'Athena'}, router)
    agent.guardrails = GuardrailsEngine(scanners=[])
    agent._gen_params = lambda _: (256, 0.2)
    agent.tool_runtime = AgentToolRuntime(_server(30000), enabled=lambda: True,
                                        result_store=ToolResultStore(tmp_path))
    assert await agent.process('fetch', {}) == 'done'
    assert reads == ['llama3.1:8b']
    assert agent.guardrails.stats()['counters']['scanned'] > 0
    assert agent_runtime.estimate_messages(backend.calls[-1]) < 4096
    assert list(tmp_path.glob('*.json'))


@pytest.mark.asyncio
async def test_actual_orchestrator_forwards_raw_window_through_guard(tmp_path):
    from agents.core.agent import Agent
    from agents.core.security.guardrails import GuardrailsEngine
    from tests.test_agent_runtime_v2 import _streamed_orchestrator_for
    backend = _Backend(1)
    # A real agent's whole prompt (persona plus the shared contract, ~2.1K tokens) rides
    # along, so the window leaves it room; a 30,000-character result still cannot fit.
    backend.context_window = lambda _: 8192
    agent = Agent('jarvis', {'name': 'Jarvis'})
    agent.tool_runtime = AgentToolRuntime(_server(30000), enabled=lambda: True,
                                        result_store=ToolResultStore(tmp_path))
    orch, _, _, _ = _streamed_orchestrator_for(agent, backend)
    orch.security = GuardrailsEngine(scanners=[])
    assert await orch.handle_input_stream('fetch', channel='web', on_token=lambda _: None,
                                          session_id='window-test') == 'done'
    assert orch.security.stats()['counters']['scanned'] > 0
    assert agent_runtime.estimate_messages(backend.calls[-1]) < 8192
    assert list(tmp_path.glob('*.json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [False, '4096', -1])
async def test_invalid_metadata_never_generates(value):
    backend = _Backend(0)
    backend.context_window = lambda _: value
    result = await _run(AgentToolRuntime(_server(1), enabled=lambda: True), backend)
    assert result == agent_runtime._WINDOW_REPLY
    assert backend.calls == []


@pytest.mark.asyncio
async def test_auto_reserve_and_snapshot_survive_metadata_change():
    backend = _Backend(1)
    snapshots = []
    backend.context_window = lambda _: snapshots.append(1) or (4096 if len(snapshots) == 1 else 1)
    original = backend.generate_tool_turn
    reserves = []
    async def generate(**kwargs):
        reserves.append(kwargs['max_tokens'])
        return await original(**kwargs)
    backend.generate_tool_turn = generate
    runtime = AgentToolRuntime(_server(1), enabled=lambda: True)
    assert await runtime.run(agent_id='nerva', backend=backend, model='m', prompt='fetch', max_tokens=0) == 'done'
    assert reserves == [1024, 1024]
    assert len(snapshots) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('size', [100, 60000])
async def test_file_read_never_respills_under_loaded_window(tmp_path, size):
    backend = _Backend(1, tool='file_read')
    backend.context_window = lambda _: 4096
    runtime = AgentToolRuntime(_server(size, name='file_read'), enabled=lambda: True,
                               result_store=ToolResultStore(tmp_path))
    assert await _run(runtime, backend) == 'done'
    assert not list(tmp_path.glob('*.json'))
    assert agent_runtime.estimate_messages(backend.calls[-1]) < 4096


def test_throwing_metadata_property_is_invalid():
    class Backend:
        @property
        def context_window(self):
            raise RuntimeError('unavailable')
    assert not resolve_effective_window(Backend(), 'm').valid


@pytest.mark.asyncio
async def test_tool_call_arguments_count_toward_known_transcript():
    from agents.core.llm.tool_protocol import ToolCall, ToolTurn
    backend = _Backend(0)
    backend.context_window = lambda _: 4096
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ToolTurn(tool_calls=(ToolCall('one', 'blob', '{"n":"' + 'x' * 30000 + '"}', {'n': 1}),))
        return ToolTurn(content='done')
    backend.generate_tool_turn = generate
    runtime = AgentToolRuntime(_server(1), enabled=lambda: True)
    assert await _run(runtime, backend) == agent_runtime._CONTEXT_REPLY
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_large_tool_schema_refuses_before_first_request():
    server = _server(1)
    metadata = server.tools()
    metadata[0]['description'] = 'variable words ' * 8000
    server.tools = lambda: metadata
    backend = _Backend(0)
    backend.context_window = lambda _: 4096
    assert await _run(AgentToolRuntime(server, enabled=lambda: True), backend) == agent_runtime._CONTEXT_REPLY
    assert not backend.calls


def test_owner_cap_can_tighten_but_never_expand_known_window():
    runtime = AgentToolRuntime(_server(1), enabled=lambda: True, context_budget_tokens=lambda: 50,
                               context_window_tokens=lambda: 100000)
    assert runtime._context_budget('m', 256, 4096) == 50
    assert runtime._context_budget('m', 4000, 4096) == 0
    assert runtime._result_budget(4096, 4096) == agent_runtime.budget_for_context_window(4096)


@pytest.mark.asyncio
async def test_opaque_direct_runtime_wrapper_has_only_estimated_fallback():
    from agents.core.security.guardrails import GuardrailsEngine
    raw = _Backend(0)
    raw.context_window = lambda _: (_ for _ in ()).throw(AssertionError('must not unwrap'))
    wrapped = GuardrailsEngine(backend=raw, scanners=[])
    snapshot = resolve_effective_window(wrapped, 'm')
    assert snapshot.valid and snapshot.tokens is None
    assert await _run(AgentToolRuntime(_server(1), enabled=lambda: True), wrapped) == 'done'
