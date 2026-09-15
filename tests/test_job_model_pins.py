"""Request-local job selection must never mutate shared router settings."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.core.autonomy.jobs import validate_action, validate_options
from agents.core.llm.job_selection import (
    SelectionError,
    current_selection,
    scoped_backend,
    selection_scope,
)


def test_pins_are_validated_and_only_apply_to_model_jobs():
    assert validate_options({'model': 'org/model:tag', 'provider': 'ollama'})['model'] == 'org/model:tag'
    for value in ('', 'bad\nmodel', 'x' * 257, True):
        with pytest.raises(ValueError):
            validate_options({'model': value})
    with pytest.raises(ValueError):
        validate_options({'provider': 'https://example.test'})
    assert validate_action({'type': 'remind', 'text': 'hi'}, {'model': 'x'})
    with pytest.raises(ValueError):
        validate_options({'script': 'x.py', 'no_agent': True, 'model': 'x'}, check_scripts=False)


@pytest.mark.asyncio
async def test_closed_inherited_task_cannot_start_call():
    ready = asyncio.Event()
    backend = SimpleNamespace(generate=AsyncMock(return_value='answer'))
    async def late():
        await ready.wait()
        with pytest.raises(SelectionError):
            await wrapped.generate(model='m')
    with selection_scope({'model': 'm'}):
        wrapped = scoped_backend(backend, 'm')
        task = asyncio.create_task(late())
        assert await wrapped.generate(model='m') == 'answer'
    ready.set()
    await task
    assert backend.generate.await_count == 1
    assert current_selection() is None


@pytest.mark.asyncio
async def test_concurrent_scopes_and_chat_remain_separate():
    async def request(model):
        with selection_scope({'model': model}):
            await asyncio.sleep(0)
            assert current_selection().model == model
        assert current_selection() is None
    await asyncio.gather(request('one'), request('two'))
    assert current_selection() is None

from agents.core.llm.hybrid_router import HybridRouter


def router_fixture():
    router = HybridRouter.__new__(HybridRouter)
    router._backend = SimpleNamespace(generate=AsyncMock(return_value='local'), context_window=lambda model:8192)
    router._backend_name = 'lm-studio'
    router._local_available = True
    router._local_model = 'local-default'
    router._ollama_backend = SimpleNamespace(generate=AsyncMock(return_value='ollama'))
    router._ollama_available = True
    router._gemini_backend = SimpleNamespace(generate=AsyncMock(return_value='cloud'))
    router._gemini_model = 'gemini-default'
    router._compatible_backend = None
    router._select_backend_inner = lambda agent, prompt: (router._backend, router._local_model, 'local')
    router._enforce_approved_models = lambda *args: None
    return router


@pytest.mark.asyncio
async def test_model_pin_reaches_actual_backend_without_mutation():
    router = router_fixture()
    with selection_scope({'model': 'custom', 'provider': 'lm-studio'}):
        backend, model, route = router.select_backend('jarvis', 'hello')
        assert model == 'custom'
        assert await backend.generate(model=model) == 'local'
    assert router._local_model == 'local-default'
    assert router.select_backend('jarvis', 'hello')[1] == 'local-default'


def test_explicit_provider_never_silently_falls_back():
    router = router_fixture()
    with selection_scope({'provider': 'gemini'}), pytest.raises(SelectionError):
        router.select_backend('frigga', 'hello')
    router._ollama_available = False
    with selection_scope({'provider': 'ollama'}), pytest.raises(SelectionError):
        router.select_backend('jarvis', 'hello')


def test_approved_models_still_enforced():
    router = router_fixture()
    def refuse(*args):
        raise RuntimeError('unapproved')
    router._enforce_approved_models = refuse
    with selection_scope({'model': 'forbidden'}), pytest.raises(RuntimeError, match='unapproved'):
        router.select_backend('jarvis', 'hello')


@pytest.mark.asyncio
async def test_auxiliary_compression_cannot_escape_pin():
    from agents.core.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    backend = SimpleNamespace(generate=AsyncMock(return_value='summary'))
    orch.llm_router = SimpleNamespace(local_backend=backend, active_model='default')
    orch.get_setting = lambda key, default: default
    summarize = orch._compression_summarizer()
    with selection_scope({'model': 'pinned'}), pytest.raises(SelectionError):
        await summarize('history')
    backend.generate.assert_not_called()
    assert await summarize('history') == 'summary'


@pytest.mark.asyncio
async def test_cancel_closes_captured_backend():
    backend = SimpleNamespace(generate=AsyncMock(return_value='answer'))
    captured = []
    async def request():
        with selection_scope({'model': 'm'}):
            captured.append(scoped_backend(backend, 'm'))
            await asyncio.Event().wait()
    task = asyncio.create_task(request())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(SelectionError):
        await captured[0].generate(model='m')
    backend.generate.assert_not_called()


@pytest.mark.asyncio
async def test_persisted_jobs_reach_real_ask_scope_and_identity(tmp_path):
    from agents.core.autonomy.jobs import JobRunner, JobStore
    from agents.core.autonomy.jobs_dispatch import identity
    path = tmp_path / 'jobs.db'
    store = JobStore(path)
    first = store.create(name='first', schedule_text='every day at 9:00',
                         action={'type':'ask', 'prompt':'first', 'deliver':False},
                         options={'model':'one', 'provider':'lm-studio'})
    second = store.create(name='second', schedule_text='every day at 9:00',
                          action={'type':'ask', 'prompt':'second', 'deliver':False},
                          options={'model':'two', 'provider':'lm-studio'})
    reopened = JobStore(path)
    assert reopened.get(first.id).options == first.options
    previous = identity(first)
    changed = reopened.update(first.id, options={'model':'changed', 'provider':'lm-studio'})
    assert identity(changed) != previous
    router = router_fixture()
    async def process(prompt, **kwargs):
        await asyncio.sleep(0)
        backend, model, _ = router.select_backend('jarvis', prompt)
        await backend.generate(model=model)
        return model
    runner = JobRunner(reopened, orch=SimpleNamespace(process=process, llm_router=router), scheduler=lambda:None)
    answers = await asyncio.gather(runner._ask(first, first.action), runner._ask(second, second.action), process('ordinary chat'))
    assert [a[0] for a in answers[:2]] == ['one', 'two']
    assert answers[2] == 'local-default'
    assert current_selection() is None
    assert router.select_backend('jarvis','chat')[1] == 'local-default'


@pytest.mark.parametrize('method', ['generate', 'generate_stream', 'generate_tool_turn'])
@pytest.mark.asyncio
async def test_all_backend_entrypoints_reject_changed_model_and_closed_scope(method):
    raw = SimpleNamespace(**{method: AsyncMock(return_value='ok')})
    with selection_scope({'model':'m'}):
        backend = scoped_backend(raw, 'm')
        with pytest.raises(SelectionError, match='changed'):
            await getattr(backend, method)(model='other')
        assert await getattr(backend, method)(model='m') == 'ok'
    with pytest.raises(SelectionError, match='closed'):
        await getattr(backend, method)(model='m')
    assert getattr(raw, method).await_count == 1


@pytest.mark.parametrize('agent', ['frigga', 'ultron', 'hestia'])
def test_real_local_policy_rejects_cloud_pins(agent):
    router = router_fixture()
    router._select_backend_inner = HybridRouter._select_backend_inner.__get__(router)
    router._deep_model_available = lambda: False
    with selection_scope({'provider':'gemini'}), pytest.raises(SelectionError):
        router.select_backend(agent, 'hello')


@pytest.mark.parametrize('provider,route', [('gemini','cloud-flash'), ('anthropic','claude'), ('openrouter','cloud-compatible')])
@pytest.mark.asyncio
async def test_permitted_cloud_provider_pin_is_exact(provider, route):
    router = router_fixture()
    raw = SimpleNamespace(generate=AsyncMock(return_value='cloud'), profile=SimpleNamespace(id=provider), context_window=lambda model:8192)
    router._select_backend_inner = lambda *args: (raw, 'original', route)
    if provider == 'openrouter':
        router._compatible_backend = raw
        router._compatible_model = 'original'
    with selection_scope({'model':'selected', 'provider':provider}):
        backend, model, selected_route = router.select_backend('jarvis', 'hello')
        assert model == 'selected' and selected_route == route
        assert await backend.generate(model=model) == 'cloud'
    raw.generate.assert_awaited_once_with(model='selected')


@pytest.mark.asyncio
async def test_actual_agent_generation_uses_scoped_backend():
    from agents.core.agent import Agent
    router = router_fixture()
    agent = Agent.__new__(Agent)
    agent.id = 'jarvis'
    agent.tool_runtime = None
    agent.config = {}
    agent._checkpoint_manager = None
    with selection_scope({'model':'selected'}):
        backend, model, _ = router.select_backend('jarvis', 'hello')
        assert await agent.generate_response(backend, model, 'hello', '', 128, 0.2) == 'local'
    assert router._backend.generate.await_args.kwargs['model'] == 'selected'


def test_howard_ollama_route_is_not_misidentified_as_cloud():
    router = router_fixture()
    router._select_backend_inner = HybridRouter._select_backend_inner.__get__(router)
    with selection_scope({'provider':'gemini'}), pytest.raises(SelectionError):
        router.select_backend('howard', 'private history')
    with selection_scope({'provider':'ollama'}):
        _, _, route = router.select_backend('howard', 'private history')
        assert route == 'ollama-howard'


@pytest.mark.asyncio
async def test_optional_recall_embedding_cannot_escape_pin():
    from agents.core.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.get_setting = lambda key, default: True if key == 'memory.recall_enabled' else default
    orch.memory = SimpleNamespace(recall=AsyncMock(return_value=[]))
    orch._living_memory_rerank_hits = lambda hits: hits
    with selection_scope({'model':'completion-model'}):
        assert await orch._recall_block('private prompt') == ''
    orch.memory.recall.assert_not_called()
    await orch._recall_block("ordinary unpinned prompt")
    orch.memory.recall.assert_awaited_once_with("ordinary unpinned prompt", top_k=5)


def test_changed_model_cancels_persisted_manual_receipt(tmp_path):
    from agents.core.autonomy.jobs import JobStore
    from agents.core.autonomy.jobs_dispatch import ManualDispatch
    path = tmp_path / 'jobs.db'
    store = JobStore(path)
    job = store.create(name='pinned', schedule_text='every day at 9:00',
                       action={'type':'ask', 'prompt':'hello'}, options={'model':'first'})
    dispatch = ManualDispatch(store)
    receipt = dispatch.enqueue(job.id)
    reopened = JobStore(path)
    reopened.update(job.id, options={'model':'replacement'})
    resumed = ManualDispatch(reopened)
    assert not resumed.claim(receipt['id'])
    assert resumed.get(receipt['id'])['status'] == 'cancelled'


def test_changed_local_model_requires_loaded_window():
    router = router_fixture()
    del router._backend.context_window
    with selection_scope({'model':'unknown-smaller'}), pytest.raises(SelectionError, match='window'):
        router.select_backend('jarvis','hello')


def test_pin_drives_history_and_tool_budgets():
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.orchestrator import Orchestrator
    router = router_fixture()
    router._backend.context_window = lambda model: 4096
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch.get_setting = lambda key, default: default
    runtime = AgentToolRuntime.__new__(AgentToolRuntime)
    runtime._context_budget_tokens = lambda: 100000
    runtime._context_window_tokens = lambda: 100000
    with selection_scope({'model':'small-local'}):
        router.select_backend('jarvis','hello')
        assert orch._compaction_model() == 'small-local'
        assert runtime._context_budget('small-local',1024) <= 4096 - 1024
        assert runtime._result_budget(4096) == runtime._result_budget(100000)
        runtime._max_result_bytes = 100000
        runtime._result_thresholds = lambda: {'blob':100000}
        runtime._server = SimpleNamespace()
        budget = runtime._result_budget(4096)
        assert runtime._result_threshold('blob', budget) <= budget.per_result_bytes


@pytest.mark.asyncio
async def test_completion_cap_and_oversized_prompt_respect_pinned_window():
    from agents.core.agent import Agent
    router = router_fixture()
    router._backend.context_window = lambda model: 4096
    agent = Agent.__new__(Agent)
    agent.id = 'jarvis'
    agent.tool_runtime = None
    agent._checkpoint_manager = None
    agent.config = {}
    with selection_scope({'model':'small'}):
        backend, model, _ = router.select_backend('jarvis','hello')
        await agent.generate_response(backend, model, 'hello', '', 100000, 0.2)
        assert router._backend.generate.await_args.kwargs['max_tokens'] == 1024
        with pytest.raises(SelectionError, match='prompt exceeds'):
            await agent.generate_response(backend, model, 'words ' * 20000, '', 100000, 0.2)
    assert router._backend.generate.await_count == 1


@pytest.mark.asyncio
async def test_history_compaction_receives_pinned_bound_without_another_turn_anchor(monkeypatch):
    from agents.core.context_compressor import ContextCompressor
    from agents.core.orchestrator import Orchestrator
    router = router_fixture()
    router._backend.context_window = lambda model:4096
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch._session_id_default = 'job-test'
    orch.get_setting = lambda key, default: True if key == 'memory.context_compression' else default
    orch.memory = SimpleNamespace(get_history=AsyncMock(return_value=[{'role':'user', 'content':'history'}]))
    orch._usage_anchor = lambda count: object()
    async def compact(self, turns, **kwargs):
        assert kwargs['model'] == 'small-local'
        assert kwargs['policy'].window('small-local') == 4096
        assert kwargs['anchor'] is None
        return {'compressed':False, 'kept':turns}
    monkeypatch.setattr(ContextCompressor, 'compact', compact)
    with selection_scope({'model':'small-local'}):
        router.select_backend('jarvis','hello')
        assert 'history' in await orch._history_for_prompt(6)


def test_cloud_model_change_requires_existing_window_family():
    router = router_fixture()
    router._select_backend_inner = lambda *args: (router._gemini_backend, 'gemini-2.5-flash', 'cloud-flash')
    with selection_scope({'model':'unknown-private-model', 'provider':'gemini'}), pytest.raises(SelectionError, match='window'):
        router.select_backend('jarvis','hello')
    with selection_scope({'model':'gemini-2.5-pro', 'provider':'gemini'}):
        _, model, _ = router.select_backend('jarvis','hello')
        assert model == 'gemini-2.5-pro'


@pytest.mark.asyncio
async def test_real_ollama_configured_context_bounds_changed_model():
    from agents.core.llm.base import OllamaBackend
    from agents.core.llm.job_selection import selected_window
    router = router_fixture()
    backend = OllamaBackend(num_ctx=4096)
    try:
        router._backend = backend
        router._backend_name = 'ollama'
        with selection_scope({'model':'custom-small', 'provider':'ollama'}):
            _, model, _ = router.select_backend('jarvis','hello')
            assert selected_window(model) == 4096
    finally:
        await backend.aclose()
