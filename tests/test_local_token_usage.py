"""Local provider measurements reach the existing usage and context contracts."""
import asyncio
import json

import httpx
import pytest

from agents.core.llm import tool_dialects
from agents.core.llm.base import LMStudioBackend, OllamaBackend


def normalize(provider, value):
    helper = getattr(tool_dialects, provider + '_usage')
    return helper(value)


def response(provider, input_count=123, output_count=17, *, calls=False):
    message = {'content': '' if calls else 'answer'}
    if calls:
        message['tool_calls'] = [{'id': 'call-one', 'type': 'function',
            'function': {'name': 'lookup', 'arguments': {} if provider == 'ollama' else '{}'}}]
    if provider == 'ollama':
        return {'message': message, 'done': True, 'done_reason': 'stop',
                'prompt_eval_count': input_count, 'eval_count': output_count,
                'prompt_eval_cached_count': 100}
    return {'choices': [{'message': message, 'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': input_count, 'completion_tokens': output_count,
                      'total_tokens': 9999, 'prompt_tokens_details': {'cached_tokens': 100}}}


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
@pytest.mark.parametrize('bad', [None, True, False, -1, '123', 1.5, float('inf'), {}, []])
def test_invalid_count_preserves_valid_sibling(provider, bad):
    usage = normalize(provider, response(provider, bad, 17))
    assert usage.input_tokens == 0 and usage.output_tokens == 17
    assert usage.reported


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
@pytest.mark.parametrize('value', [{}, None, [], {'usage': []}])
def test_missing_usage_remains_unreported(provider, value):
    assert not normalize(provider, value).reported


@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
def test_total_prompt_count_is_not_inflated_by_cache_or_total(provider):
    usage = normalize(provider, response(provider))
    assert usage.input_tokens == 123 and usage.output_tokens == 17
    assert usage.cache_read == usage.cache_write == 0
    assert not normalize(provider, response(provider, 0, 0)).reported


async def backend_for(provider, handler):
    backend = OllamaBackend() if provider == 'ollama' else LMStudioBackend()
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(base_url='http://localhost', transport=httpx.MockTransport(handler))
    return backend


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
@pytest.mark.parametrize('calls', [True, False])
async def test_backend_preserves_answer_and_tool_calls_with_usage(provider, calls):
    sent = []
    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=response(provider, calls=calls))
    backend = await backend_for(provider, handler)
    try:
        turn = await backend.generate_tool_turn('model', [{'role': 'user', 'content': 'hello'}], [])
        assert turn.usage.input_tokens == 123 and turn.usage.output_tokens == 17
        assert turn.content == ('' if calls else 'answer')
        assert [call.name for call in turn.tool_calls] == (['lookup'] if calls else [])
        assert turn.finish_reason == ('tool_calls' if provider == 'lmstudio' and calls else 'stop')
        assert sent[0]['stream'] is False
        assert 'usage' not in sent[0] and 'stream_options' not in sent[0]
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
async def test_concurrent_backend_measurements_feed_isolated_anchors(provider):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.orchestrator import Orchestrator
    async def handler(req):
        model = json.loads(req.content)['model']
        await asyncio.sleep(0)
        return httpx.Response(200, json=response(provider, int(model), 17))
    backend = await backend_for(provider, handler)
    try:
        one, two = await asyncio.gather(*[
            backend.generate_tool_turn(str(size), [{'role': 'user', 'content': 'hello'}], [])
            for size in (9000, 1234)])
        sessions = []
        for turn in (one, two):
            orch = Orchestrator.__new__(Orchestrator)
            orch._context_anchor = {}
            orch._ctx_turns_at_build = 6
            AgentToolRuntime._report_usage(lambda usage, session=orch: session._record_context_anchor('jarvis', usage), turn)
            sessions.append(orch)
        assert sessions[0]._usage_anchor(6).prompt_tokens == 9000
        assert sessions[1]._usage_anchor(6).prompt_tokens == 1234
        # The second request replaces context pressure; billing separately sums events.
        events = []
        def sink(usage):
            events.append(usage.input_tokens)
            sessions[0]._record_context_anchor('jarvis', usage)
        AgentToolRuntime._report_usage(sink, one)
        AgentToolRuntime._report_usage(sink, two)
        assert sum(events) == 10234
        assert sessions[0]._context_anchor['jarvis'] == (1234, 6)
        empty = await backend.generate_tool_turn('0', [], [])
        AgentToolRuntime._report_usage(sink, empty)
        assert sessions[0]._context_anchor['jarvis'] == (1234, 6)
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
async def test_actual_runtime_delivers_backend_measurement_to_sink(provider):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.tool_rpc import ToolRPCServer
    backend = await backend_for(provider, lambda req: httpx.Response(200, json=response(provider)))
    events = []
    server = ToolRPCServer()
    server.register_tool('unused', lambda args: pytest.fail('unexpected tool execution'),
                         input_schema={'type': 'object', 'properties': {}})
    try:
        answer = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id='jarvis', backend=backend, model='local', prompt='hello',
            system='Local assistant', max_tokens=128, temperature=.2, usage_sink=events.append)
        assert answer == 'answer'
        assert [(u.input_tokens, u.output_tokens) for u in events] == [(123, 17)]
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['ollama', 'lmstudio'])
async def test_malformed_backend_usage_does_not_degrade_valid_answer(provider):
    backend = await backend_for(provider, lambda req: httpx.Response(
        200, json=response(provider, {'untrusted': 12}, False)))
    try:
        turn = await backend.generate_tool_turn('local', [], [])
        assert turn.content == 'answer' and not turn.usage.reported
    finally:
        await backend.aclose()
