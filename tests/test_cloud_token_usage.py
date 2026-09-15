"""Cloud usage survives structured turns without double counting detail fields."""
import asyncio
import json

import httpx
import pytest

from agents.core.llm import tool_dialects
from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.providers import ProviderProfile


def response(provider, input_count=123, output_count=17, *, calls=False):
    if provider == 'gemini':
        parts = [{'functionCall': {'name': 'lookup', 'args': {}}}] if calls else [{'text': 'answer'}]
        return {'candidates': [{'content': {'parts': parts}, 'finishReason': 'STOP'}],
                'usageMetadata': {'promptTokenCount': input_count, 'candidatesTokenCount': output_count,
                                  'thoughtsTokenCount': 3, 'cachedContentTokenCount': 100,
                                  'totalTokenCount': 99999, 'toolUsePromptTokenCount': 888}}
    message = {'content': '' if calls else 'answer'}
    if calls:
        message['tool_calls'] = [{'id': 'call-one', 'type': 'function',
                                  'function': {'name': 'lookup', 'arguments': '{}'}}]
    return {'choices': [{'message': message, 'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': input_count, 'completion_tokens': output_count,
                      'total_tokens': 99999, 'completion_tokens_details': {'reasoning_tokens': 3},
                      'prompt_tokens_details': {'cached_tokens': 100, 'cache_write_tokens': 20}}}


def normalize(provider, data):
    return getattr(tool_dialects, provider + '_usage')(data)


@pytest.mark.parametrize('provider', ['gemini', 'compatible'])
@pytest.mark.parametrize('bad', [None, True, False, -1, '123', 1.5, float('inf'), {}, []])
def test_bad_input_preserves_output(provider, bad):
    usage = normalize(provider, response(provider, bad))
    assert usage.input_tokens == 0
    assert usage.output_tokens == (20 if provider == 'gemini' else 17)


@pytest.mark.parametrize('provider', ['gemini', 'compatible'])
@pytest.mark.parametrize('data', [None, [], {}, {'usage': [], 'usageMetadata': []}])
def test_missing_metadata_unreported(provider, data):
    assert not normalize(provider, data).reported


@pytest.mark.parametrize('provider', ['gemini', 'compatible'])
def test_totals_and_details_are_not_counted_twice(provider):
    from agents.core.orchestrator import Orchestrator, _billable_from_usage
    usage = normalize(provider, response(provider))
    expected_output = 20 if provider == 'gemini' else 17
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read, usage.cache_write) == (123, expected_output, 0, 0)
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    orch._record_context_anchor('jarvis', usage)
    assert orch._usage_anchor(6).prompt_tokens == 123
    assert _billable_from_usage(usage) == (123, expected_output, 0)


@pytest.mark.parametrize('bad', [True, -4, '17', None, {}, 1.5])
def test_gemini_bad_candidates_preserves_thoughts(bad):
    assert normalize('gemini', response('gemini', 123, bad)).output_tokens == 3


async def backend_for(provider, handler, profile=None):
    if provider == 'gemini':
        backend = GeminiBackend(api_key='test')
        await backend.client.aclose()
        backend.client = httpx.AsyncClient(base_url='https://provider.test', transport=httpx.MockTransport(handler))
        return backend
    client = httpx.AsyncClient(base_url='https://provider.test', transport=httpx.MockTransport(handler))
    return OpenRouterBackend(client=client, profile=profile)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['gemini', 'compatible'])
@pytest.mark.parametrize('calls', [False, True])
async def test_backend_preserves_usage_content_and_tools(provider, calls):
    sent = []
    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=response(provider, calls=calls))
    backend = await backend_for(provider, handler)
    try:
        turn = await backend.generate_tool_turn('model', [{'role': 'user', 'content': 'hello'}], [])
        assert turn.usage.input_tokens == 123
        assert turn.usage.output_tokens == (20 if provider == 'gemini' else 17)
        assert turn.content == ('' if calls else 'answer')
        assert [call.name for call in turn.tool_calls] == (['lookup'] if calls else [])
        assert all(key not in sent[0] for key in ('usage', 'stream_options', 'usageMetadata'))
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected', [('openai-compatible', 123), ('unknown', 0)])
async def test_explicit_wire_profile_controls_usage(kind, expected):
    backend = await backend_for('compatible', lambda req: httpx.Response(200, json=response('compatible')),
        ProviderProfile(id='custom', display_name='Custom', backend_kind=kind))
    try:
        turn = await backend.generate_tool_turn('model', [], [])
        assert turn.content == 'answer' and turn.usage.input_tokens == expected
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_gemini_blocked_prompt_keeps_usage():
    data = {'promptFeedback': {'blockReason': 'SAFETY'}, 'usageMetadata': {'promptTokenCount': 123}}
    backend = await backend_for('gemini', lambda req: httpx.Response(200, json=data))
    try:
        turn = await backend.generate_tool_turn('model', [], [])
        assert turn.content == '' and turn.finish_reason == 'content_filter'
        assert turn.usage.input_tokens == 123
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['gemini', 'compatible'])
async def test_actual_runtime_sink_and_concurrent_turns(provider):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.tool_rpc import ToolRPCServer
    async def handler(req):
        data = json.loads(req.content)
        count = 9000 if '9000' in str(data) else 123
        await asyncio.sleep(0)
        return httpx.Response(200, json=response(provider, count))
    backend = await backend_for(provider, handler)
    server = ToolRPCServer()
    server.register_tool('unused', lambda args: pytest.fail('unexpected tool execution'),
                         input_schema={'type': 'object', 'properties': {}})
    async def run(prompt):
        events = []
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id='jarvis', backend=backend, model='model', prompt=prompt,
            system='Assistant', max_tokens=128, temperature=.2, usage_sink=events.append)
        return answer, events
    try:
        first, second = await asyncio.gather(run('9000'), run('123'))
        assert first[0] == second[0] == 'answer'
        assert [u.input_tokens for u in first[1]] == [9000]
        assert [u.input_tokens for u in second[1]] == [123]
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize('bad', [True, -4, '17', None, {}, 1.5])
def test_gemini_bad_thoughts_preserves_candidates(bad):
    data = response('gemini')
    data['usageMetadata']['thoughtsTokenCount'] = bad
    assert normalize('gemini', data).output_tokens == 17


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['gemini', 'compatible'])
async def test_malformed_usage_does_not_discard_answer(provider):
    data = response(provider)
    data['usageMetadata' if provider == 'gemini' else 'usage'] = ['invalid']
    backend = await backend_for(provider, lambda req: httpx.Response(200, json=data))
    try:
        turn = await backend.generate_tool_turn('model', [], [])
        assert turn.content == 'answer' and not turn.usage.reported
    finally:
        await backend.client.aclose()
