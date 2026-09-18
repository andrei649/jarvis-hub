"""Ordinary Claude calls must request caching without changing response semantics."""

import json

import httpx
import pytest

from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.usage_context import text_usage_scope

USAGE = {'input_tokens': 10, 'output_tokens': 3,
         'cache_read_input_tokens': 80, 'cache_creation_input_tokens': 20}


def reply():
    return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'answer'}],
                                    'usage': dict(USAGE)})


def stream_reply(*, complete=True, error=False):
    events = [
        {'type': 'message_start', 'message': {'usage': dict(USAGE)}},
        {'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'private'}},
        {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'answer'}},
        {'type': 'message_delta', 'usage': {'output_tokens': 3}},
    ]
    if error:
        events.append({'type': 'error', 'error': {'type': 'overloaded_error'}})
    if complete:
        events.append({'type': 'message_stop'})
    return httpx.Response(200, text=''.join('data: '+json.dumps(e)+'\n\n' for e in events),
                          headers={'content-type': 'text/event-stream'})


async def backend_with(handler, **kwargs):
    backend = ClaudeBackend('fixture-key', **kwargs)
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return backend


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['generate', 'generate_stream'])
async def test_nonempty_system_is_cache_marked_on_actual_request(method):
    requests, callbacks, usage = [], [], []
    def handler(request):
        requests.append(request)
        return stream_reply() if method == 'generate_stream' else reply()
    backend = await backend_with(handler)
    try:
        kwargs = {'on_token': callbacks.append} if method == 'generate_stream' else {}
        with text_usage_scope(usage.append):
            result = await getattr(backend, method)(model='model-x', prompt='question',
                system='stable system\nexact bytes', max_tokens=4096, **kwargs)
        body = json.loads(requests[0].content)
        assert body['system'] == [{'type': 'text', 'text': 'stable system\nexact bytes',
                                   'cache_control': {'type': 'ephemeral'}}]
        assert body['messages'] == [{'role': 'user', 'content': 'question'}]
        assert result == 'answer'
        assert callbacks == (['answer'] if method == 'generate_stream' else [])
        assert len(usage) == 1 and usage[0].cache_read == 80 and usage[0].cache_write == 20
        assert usage[0].input_tokens == 10 and usage[0].output_tokens == 3
        assert requests[0].headers['anthropic-version'] == '2023-06-01'
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['generate', 'generate_stream'])
async def test_empty_system_keeps_existing_wire_shape(method):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return stream_reply() if method == 'generate_stream' else reply()
    backend = await backend_with(handler)
    try:
        await getattr(backend, method)(model='model-x', prompt='question', system='')
        assert bodies[0]['system'] == ''
        assert 'cache_control' not in json.dumps(bodies[0])
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_text_auth_retry_reuses_identical_cache_body():
    from agents.core.llm.auth_rotation import AuthProfilePool

    requests, usage = [], []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={'error': 'fixture'}) if len(requests) == 1 else reply()
    pool = AuthProfilePool(['fixture-one', 'fixture-two'], provider='anthropic')
    backend = await backend_with(handler, auth_pool=pool)
    try:
        with text_usage_scope(usage.append):
            result = await backend.generate(model='model-x', prompt='question', system='stable')
        assert result == 'answer' and len(requests) == 2
        assert requests[0].content == requests[1].content
        assert json.loads(requests[0].content)['system'][0]['cache_control'] == {'type': 'ephemeral'}
        assert [r.headers['x-api-key'] for r in requests] == ['fixture-one', 'fixture-two']
        assert requests[0].headers['anthropic-version'] == requests[1].headers['anthropic-version']
        assert len(usage) == 1 and usage[0].cache_read == 80
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['generate', 'generate_stream'])
async def test_cache_marking_preserves_reasoning_and_sampling_rules(method):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return stream_reply() if method == 'generate_stream' else reply()
    backend = await backend_with(handler, reasoning_effort='high')
    try:
        await getattr(backend, method)(model='claude-fable-5-1', prompt='question',
                                      system='stable', max_tokens=4096, temperature=0.4)
        body = bodies[0]
        assert body['system'][0]['cache_control'] == {'type': 'ephemeral'}
        assert body['output_config']['effort'] == 'high'
        assert body['thinking'] == {'type': 'adaptive'}
        assert 'temperature' not in body
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['generate', 'generate_stream'])
async def test_cache_marking_does_not_bypass_reasoning_refusal(method):
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused

    backend = await backend_with(lambda request: pytest.fail('refused request sent'),
                                 reasoning_effort='minimal')
    try:
        with pytest.raises(ReasoningEffortRefused):
            await getattr(backend, method)(model='claude-fable-5-1', prompt='question', system='stable')
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('complete,error', [(False, False), (True, True)])
async def test_incomplete_or_error_stream_does_not_publish_cache_usage(complete, error):
    bodies, callbacks, usage = [], [], []
    def handler(request):
        bodies.append(json.loads(request.content))
        return stream_reply(complete=complete, error=error)
    backend = await backend_with(handler)
    try:
        with text_usage_scope(usage.append):
            result = await backend.generate_stream(model='model-x', prompt='question', system='stable',
                                                   on_token=callbacks.append)
        assert result == 'answer' and callbacks == ['answer']
        assert bodies[0]['system'][0]['cache_control'] == {'type': 'ephemeral'}
        assert usage == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_stream_http_error_keeps_existing_no_retry_and_rotation_behavior():
    from agents.core.llm.auth_rotation import AuthProfilePool

    requests, callbacks, usage = [], [], []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={'error': 'fixture'})
    pool = AuthProfilePool(['fixture-one', 'fixture-two'], provider='anthropic')
    backend = await backend_with(handler, auth_pool=pool)
    try:
        with text_usage_scope(usage.append):
            result = await backend.generate_stream(model='model-x', prompt='question', system='stable',
                                                   on_token=callbacks.append)
        assert 'stream error' in result and len(requests) == 1
        assert json.loads(requests[0].content)['system'][0]['cache_control'] == {'type': 'ephemeral'}
        assert pool.current_key() == 'fixture-two'
        assert callbacks == [] and usage == []
    finally:
        await backend.aclose()
