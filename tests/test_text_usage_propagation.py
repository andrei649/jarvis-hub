"""Complete text replies retain usage; streams keep their existing contracts."""
import asyncio
import json

import httpx
import pytest

from agents.core.agent import Agent
from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.usage_context import observer_scope, text_usage_scope

PROVIDERS = ['ollama', 'lmstudio', 'gemini', 'compatible', 'anthropic']


def response(provider):
    if provider == 'ollama':
        return {'response': 'answer', 'done': True, 'prompt_eval_count': 123, 'eval_count': 17}
    if provider == 'gemini':
        return {'candidates': [{'content': {'parts': [{'text': 'answer'}]}}],
                'usageMetadata': {'promptTokenCount': 123, 'candidatesTokenCount': 14, 'thoughtsTokenCount': 3}}
    if provider == 'anthropic':
        return {'content': [{'type': 'text', 'text': 'answer'}],
                'usage': {'input_tokens': 23, 'output_tokens': 17, 'cache_read_input_tokens': 90,
                          'cache_creation_input_tokens': 10}}
    return {'choices': [{'message': {'content': 'answer'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 123, 'completion_tokens': 17,
                      'prompt_tokens_details': {'cached_tokens': 100}}}


async def backend_for(provider, handler):
    constructors = {'ollama': OllamaBackend, 'lmstudio': LMStudioBackend,
                    'gemini': lambda: GeminiBackend(api_key='test'),
                    'compatible': OpenRouterBackend,
                    'anthropic': lambda: ClaudeBackend(api_key='test')}
    backend = constructors[provider]()
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(base_url='https://provider.test', transport=httpx.MockTransport(handler))
    return backend


def agent_for():
    agent = Agent.__new__(Agent)
    agent.id = 'jarvis'
    agent._checkpoint_manager = None
    agent.tool_runtime = None
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', PROVIDERS)
async def test_complete_text_reports_once_and_direct_background_call_is_silent(provider):
    requests, events = [], []
    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200, json=response(provider))
    backend = await backend_for(provider, handler)
    try:
        with observer_scope(events.append):
            assert await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2) == 'answer'
            assert await backend.generate('model', 'background or synthesis') == 'answer'
        assert len(events) == 1
        usage = events[0]
        assert usage.input_tokens + usage.cache_read + usage.cache_write == 123
        assert usage.output_tokens == 17
        assert all('usage' not in req and 'stream_options' not in req for req in requests)
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('malformed', [False, True])
async def test_failed_or_malformed_metadata_never_fabricates_usage(provider, malformed):
    data = response(provider)
    if provider == 'ollama':
        data['prompt_eval_count'], data['eval_count'] = {}, False
    else:
        data['usageMetadata' if provider == 'gemini' else 'usage'] = []
    backend = await backend_for(provider, lambda req: httpx.Response(200 if malformed else 500, json=data))
    events = []
    try:
        answer = await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2, usage_sink=events.append)
        assert events == []
        if malformed:
            assert answer == 'answer'
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_inherited_openrouter_stream_reports_once():
    backend = await backend_for('compatible', lambda req: httpx.Response(200, json=response('compatible')))
    events, tokens = [], []
    try:
        assert await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2,
            on_token=tokens.append, usage_sink=events.append) == 'answer'
        assert tokens == ['answer'] and len(events) == 1
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_lmstudio_retry_publishes_only_accepted_response():
    attempts = []
    def handler(req):
        attempts.append(req)
        return httpx.Response(400, json={'error': 'Model unloaded by user or API request.'}) if len(attempts) == 1 else httpx.Response(200, json=response('lmstudio'))
    backend = await backend_for('lmstudio', handler)
    events = []
    try:
        assert await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2, usage_sink=events.append) == 'answer'
        assert len(attempts) == 2 and len(events) == 1
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_gemini_cache_retry_publishes_only_accepted_response():
    from tests.test_gemini_request_context import _binding
    attempts = []
    def handler(req):
        attempts.append(json.loads(req.content))
        return httpx.Response(400, json={}) if len(attempts) == 1 else httpx.Response(200, json=response('gemini'))
    backend = await backend_for('gemini', handler)
    events = []
    try:
        with backend.request_scope(_binding(cache_name='cachedContents/rejected')):
            assert await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2, usage_sink=events.append) == 'answer'
        assert len(attempts) == 2 and len(events) == 1
        assert 'cachedContent' not in attempts[1]
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_undeclared_wire_profile_does_not_report():
    from agents.core.llm.providers import ProviderProfile
    backend = await backend_for('compatible', lambda req: httpx.Response(200, json=response('compatible')))
    backend.profile = ProviderProfile(id='custom', display_name='Custom', backend_kind='unknown')
    events = []
    try:
        with text_usage_scope(events.append):
            assert await backend.generate('model', 'hello') == 'answer'
        assert events == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_concurrent_agent_scopes_do_not_mix_backend_usage():
    async def handler(req):
        data = response('compatible')
        data['usage']['prompt_tokens'] = int(json.loads(req.content)['messages'][-1]['content'])
        await asyncio.sleep(0)
        return httpx.Response(200, json=data)
    backend = await backend_for('compatible', handler)
    async def run(count):
        events = []
        await agent_for().generate_response(backend, 'model', str(count), '', 128, .2, usage_sink=events.append)
        return [u.input_tokens for u in events]
    try:
        assert await asyncio.gather(run(1000), run(2000)) == [[1000], [2000]]
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('block_input', [True, False])
async def test_guardrails_preserve_blocking_and_complete_request_metering(block_input):
    from agents.core.security.guardrails import GuardrailsEngine, SecurityBlockError
    from agents.core.security.types import RedactionMode
    requests, events = [], []
    def handler(req):
        requests.append(req)
        return httpx.Response(200, json=response('compatible'))
    backend = await backend_for('compatible', handler)
    guard = GuardrailsEngine(backend, mode=RedactionMode.BLOCK)
    def block(text):
        raise SecurityBlockError('blocked')
    if block_input:
        guard._guard_input = block
    else:
        guard._guard_output = block
    try:
        with pytest.raises(SecurityBlockError):
            await agent_for().generate_response(guard, 'model', 'hello', '', 128, .2, usage_sink=events.append)
        # Output blocking does not undo a completed provider request's usage.
        assert len(events) == len(requests) == (0 if block_input else 1)
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_cancellation_before_complete_response_does_not_report():
    started = asyncio.Event()
    async def handler(req):
        started.set()
        await asyncio.Event().wait()
    backend = await backend_for('compatible', handler)
    events = []
    try:
        task = asyncio.create_task(agent_for().generate_response(backend, 'model', 'hello', '', 128, .2,
                                                                 usage_sink=events.append))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_reasoning_exhausted_ollama_response_still_has_reported_usage():
    from agents.core.llm.base import THINKING_EXHAUSTED_REPLY
    data = response('ollama')
    data.update(response='', thinking='private reasoning', done_reason='length')
    backend = await backend_for('ollama', lambda req: httpx.Response(200, json=data))
    events = []
    try:
        answer = await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2, usage_sink=events.append)
        assert answer == THINKING_EXHAUSTED_REPLY
        assert len(events) == 1 and events[0].output_tokens == 17
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_gemini_auth_retry_does_not_reuse_rejected_usage():
    from agents.core.llm.auth_rotation import AuthProfilePool
    attempts = []
    def handler(req):
        attempts.append(req.headers['x-goog-api-key'])
        data = response('gemini')
        if len(attempts) == 1:
            data['usageMetadata']['promptTokenCount'] = 9999
        return httpx.Response(429 if len(attempts) == 1 else 200, json=data)
    backend = await backend_for('gemini', handler)
    backend.auth_pool = AuthProfilePool(['old-key', 'new-key'], 'gemini')
    events = []
    try:
        assert await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2, usage_sink=events.append) == 'answer'
        assert attempts == ['old-key', 'new-key']
        assert [usage.input_tokens for usage in events] == [123]
    finally:
        await backend.client.aclose()
