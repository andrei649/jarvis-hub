"""An explicit scheduled reasoning rung reaches cloud wire or refuses local HTTP."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.autonomy.jobs import JobRunner, JobStore, validate_action, validate_options
from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.llm.reasoning_effort import LADDER, ReasoningEffortRefused
from agents.core.llm.request_context import job_reasoning_scope, required_job_reasoning


def test_store_validates_canonical_reasoning_for_model_ask(tmp_path):
    for level in LADDER:
        assert validate_options({'reasoning_effort': level})['reasoning_effort'] == level
    for invalid in (None, '', 'LOW', 'disabled', True, 1, []):
        with pytest.raises(ValueError):
            validate_options({'reasoning_effort': invalid})
    assert validate_action({'type': 'remind', 'message': 'hi'}, {'reasoning_effort': 'low'})
    with pytest.raises(ValueError):
        validate_options({'reasoning_effort': 'low', 'no_agent': True,
                          'script': 'x.py'}, check_scripts=False)


@pytest.mark.asyncio
async def test_nested_absent_job_scope_preserves_required_marker_and_revocation():
    gate = asyncio.Event()

    async def late():
        with job_reasoning_scope(None):
            await gate.wait()
            return required_job_reasoning()

    with job_reasoning_scope('low'):
        assert required_job_reasoning() == 'low'
        with job_reasoning_scope(None):
            assert required_job_reasoning() == 'low'
        task = asyncio.create_task(late())
    gate.set()
    with pytest.raises(ReasoningEffortRefused):
        await task
    assert required_job_reasoning() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('backend_type', [LMStudioBackend, OllamaBackend])
@pytest.mark.parametrize('method', ['generate', 'generate_tool_turn', 'generate_stream'])
async def test_local_explicit_pin_refuses_before_generation_http(backend_type, method):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'},
                                                       'finish_reason': 'stop'}]})

    backend = backend_type(base_url='http://127.0.0.1:1234')
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                       base_url='http://127.0.0.1:1234')
    kwargs = {'model': 'local-model', 'messages': [], 'tools': []} if method == 'generate_tool_turn' else {
        'model': 'local-model', 'prompt': 'hi'}
    if method == 'generate_stream':
        kwargs['on_token'] = lambda text: None
    try:
        with job_reasoning_scope('low'), pytest.raises(ReasoningEffortRefused):
            await getattr(backend, method)(**kwargs)
        assert seen == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_unpinned_local_still_sends_and_job_scope_reaches_cloud_wire(tmp_path, monkeypatch):
    from agents.core.llm.anthropic import ClaudeBackend

    local_seen = []

    def local_handler(request):
        local_seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'local answer'},
                                                       'finish_reason': 'stop'}]})

    local = LMStudioBackend(base_url='http://127.0.0.1:1234')
    await local.client.aclose()
    local.client = httpx.AsyncClient(transport=httpx.MockTransport(local_handler),
                                     base_url='http://127.0.0.1:1234')
    cloud_seen = []

    def cloud_handler(request):
        cloud_seen.append(json.loads(request.content))
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'cloud answer'}],
                                         'stop_reason': 'end_turn'})

    cloud = ClaudeBackend('fixture', reasoning_effort='high')
    await cloud.client.aclose()
    cloud.client = httpx.AsyncClient(transport=httpx.MockTransport(cloud_handler),
                                     base_url='https://fixture.invalid')
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    settings_db.init_db(force=True)
    store = JobStore(tmp_path / 'jobs.db')

    async def detailed(prompt, **kwargs):
        return await cloud.generate(model='claude-sonnet-4-6', prompt=prompt), None

    try:
        with job_reasoning_scope(None):
            assert await local.generate(model='local-model', prompt='hi') == 'local answer'
        assert len(local_seen) == 1
        job = store.create(name='reasoning', schedule_text='0 9 * * *',
                           action={'type': 'ask', 'prompt': 'hi', 'deliver': False},
                           options={'reasoning_effort': 'low'})
        runner = JobRunner(store, orch=SimpleNamespace(process_detailed=detailed), scheduler=lambda: None)
        await runner._ask(job, job.action)
        assert cloud_seen[0]['output_config']['effort'] == 'low'
        assert cloud.reasoning_effort == 'high'
    finally:
        store.close()
        await local.client.aclose()
        await cloud.client.aclose()


@pytest.mark.asyncio
async def test_scheduled_local_route_refuses_without_selection_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    settings_db.init_db(force=True)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'unexpected'}}]})

    backend = LMStudioBackend(base_url='http://127.0.0.1:1234')
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                       base_url='http://127.0.0.1:1234')
    store = JobStore(tmp_path / 'jobs.db')

    async def detailed(prompt, **kwargs):
        # Represents an already prepared local route: no router selection runs here.
        return await backend.generate(model='m', prompt=prompt), None

    try:
        job = store.create(name='local', schedule_text='0 9 * * *',
                           action={'type': 'ask', 'prompt': 'hi', 'deliver': False},
                           options={'reasoning_effort': 'low'})
        runner = JobRunner(store, orch=SimpleNamespace(process_detailed=detailed), scheduler=lambda: None)
        with pytest.raises(ReasoningEffortRefused):
            await runner._ask(job, job.action)
        assert seen == []
    finally:
        store.close()
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_expired_scheduled_child_cannot_send_local_http():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'unexpected'}}]})

    backend = LMStudioBackend(base_url='http://127.0.0.1:1234')
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                       base_url='http://127.0.0.1:1234')
    gate = asyncio.Event()

    async def late():
        await gate.wait()
        return await backend.generate(model='m', prompt='hi')

    try:
        with job_reasoning_scope('low'):
            task = asyncio.create_task(late())
        gate.set()
        with pytest.raises(ReasoningEffortRefused):
            await task
        assert seen == []
    finally:
        gate.set()
        await backend.client.aclose()
