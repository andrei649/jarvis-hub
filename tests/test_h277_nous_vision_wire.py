"""Native Nous image wire and reviewed-request enforcement, synthetic HTTP only."""

import base64
import json

import httpx
import pytest

from agents.core import settings_db
from agents.core.commands import Principal
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client
from agents.core.llm.vision_policy import composer_request_scope, describe
from tests.test_composer_vision import PNG

BASE = 'https://inference-api.nousresearch.com/v1'
MODEL = 'anthropic/claude-sonnet-4-6'


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    monkeypatch.setattr(settings_db, '_wal_set', False)
    monkeypatch.setenv('JARVIS_ROLE_VISION_EMPTY_RETRIES', '0')


async def send(monkeypatch, handler, *, wire='anthropic_messages', after=None):
    config = vlm.VLMConfig(backend='nous', base_url=BASE, model=MODEL,
                           api_key='synthetic-jwt', is_local=False, wire_mode=wire)
    def factory(provider, **kwargs):
        client = llm_async_client(provider, transport=httpx.MockTransport(handler), **kwargs)
        if after is not None:
            async def hook(request):
                after(request)
            client.event_hooks['request'].append(hook)
        return client
    monkeypatch.setattr(vlm, 'llm_async_client', factory)
    backend = vlm.VLMBackend(base_url=BASE, api_key=config.api_key, provider_id='nous',
                             composer_auth=True, wire_mode=wire)
    try:
        with composer_request_scope(config, backend, resolve_config=lambda: config,
                                    remote_ack=True, principal=Principal(channel='web', admin=False)):
            return await backend.generate_vision_checked(MODEL, 'Read this image',
                images=[base64.b64decode(PNG.partition(',')[2])], system='Be concise')
    finally:
        await backend.aclose()


def native(content=None, stop='end_turn'):
    return {'type': 'message', 'role': 'assistant', 'content': content if content is not None else [
        {'type': 'text', 'text': 'An image answer.'}], 'stop_reason': stop}


@pytest.mark.asyncio
@pytest.mark.parametrize('wire', ['chat_completions', 'anthropic_messages'])
async def test_actual_wire_payload_and_answer_are_protocol_correct(isolated, monkeypatch, wire):
    requests = []
    def respond(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload['model'] == MODEL
        assert request.headers['Authorization'] == 'Bearer synthetic-jwt'
        assert 'x-api-key' not in request.headers
        if wire == 'anthropic_messages':
            assert str(request.url) == BASE + '/messages'
            assert request.headers['anthropic-version'] == '2023-06-01'
            assert payload['system'] == 'Be concise'
            assert all(m['role'] != 'system' for m in payload['messages'])
            image = next(b for b in payload['messages'][0]['content'] if b['type'] == 'image')
            assert image['source']['type'] == 'base64'
            assert image['source']['media_type'] in {'image/png', 'image/jpeg'}
            assert base64.b64decode(image['source']['data'])
            return httpx.Response(200, json=native())
        assert str(request.url) == BASE + '/chat/completions'
        assert payload['messages'][0] == {'role': 'system', 'content': 'Be concise'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'An image answer.'}}]})
    assert await send(monkeypatch, respond, wire=wire) == 'An image answer.'
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('retry,expected', [('0', 1), ('1', 2)])
async def test_empty_native_response_obeys_owner_budget(isolated, monkeypatch, retry, expected):
    monkeypatch.setenv('JARVIS_ROLE_VISION_EMPTY_RETRIES', retry)
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=native([]) if len(requests) == 1 else native())
    result = await send(monkeypatch, respond)
    assert result == ('' if expected == 1 else 'An image answer.')
    assert len(requests) == expected
    if expected == 2:
        assert requests[0].content == requests[1].content


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['model', 'prompt', 'duplicate', 'path', 'auth', 'version'])
@pytest.mark.parametrize('retry', ['0', '1'])
async def test_late_request_mutation_never_reaches_transport(isolated, monkeypatch, mutation, retry):
    monkeypatch.setenv('JARVIS_ROLE_VISION_EMPTY_RETRIES', retry)
    requests = []
    def mutate(request):
        payload = json.loads(request.content)
        if mutation == 'model':
            payload['model'] = 'other/model'
        elif mutation == 'prompt':
            payload['messages'][0]['content'] = [{'type': 'text', 'text': 'different prompt'}]
        elif mutation == 'duplicate':
            request._content = b'{"model":"other",' + request.content[1:]
            return
        elif mutation == 'path':
            request.url = httpx.URL(BASE + '/chat/completions')
        elif mutation == 'auth':
            request.headers['x-api-key'] = 'ambient-key'
        else:
            request.headers['anthropic-version'] = '1900-01-01'
        request._content = json.dumps(payload).encode()
    from agents.core.llm.vision_policy import VisionDestinationChanged
    with pytest.raises(VisionDestinationChanged):
        await send(monkeypatch, lambda r: requests.append(r) or httpx.Response(200, json=native()), after=mutate)
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    native([{'type': 'tool_use', 'id': 'x', 'name': 'run', 'input': {}}], 'tool_use'),
    {'type': 'error', 'error': {'message': 'private'}},
    native([{'type': 'text', 'text': 'misleading'}, {'type': 'tool_use'}]),
])
async def test_native_alternate_outputs_are_terminal(isolated, monkeypatch, payload):
    calls = []
    monkeypatch.setenv('JARVIS_ROLE_VISION_EMPTY_RETRIES', '1')
    with pytest.raises(ValueError):
        await send(monkeypatch, lambda r: calls.append(r) or httpx.Response(200, json=payload))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_native_response_limit_applies_without_retry(isolated, monkeypatch):
    with pytest.raises(ValueError, match='response too large'):
        await send(monkeypatch, lambda r: httpx.Response(200, json=native([
            {'type': 'text', 'text': 'x' * (vlm.MAX_VISION_RESPONSE_BYTES + 1)}])))


def test_wire_mode_changes_reviewed_binding(isolated):
    from dataclasses import replace
    config = vlm.VLMConfig(backend='nous', base_url=BASE, model=MODEL,
                           api_key='synthetic-jwt', is_local=False, wire_mode='chat_completions')
    chat = describe(config)
    messages = describe(replace(config, wire_mode='anthropic_messages'))
    assert chat.binding != messages.binding
    assert chat.request_url == BASE + '/chat/completions'
    assert messages.request_url == BASE + '/messages'
