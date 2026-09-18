"""Actual xAI routing and invocation-owned stateless tool transcript."""
import json

import httpx
import pytest


def completed(answer='done', *, calls=(), reasoning=False):
    rows = []
    if reasoning:
        rows.append({'type': 'reasoning', 'id': 'reason-one', 'status': 'completed',
                     'summary': [], 'encrypted_content': 'fixture-ciphertext'})
    if answer:
        rows.append({'type': 'message', 'id': 'message-one', 'status': 'completed',
                     'role': 'assistant', 'content': [{'type': 'output_text', 'text': answer}]})
    rows.extend(calls)
    return {'status': 'completed', 'output': rows,
            'usage': {'input_tokens': 100, 'input_tokens_details': {'cached_tokens': 60},
                      'output_tokens': 7, 'output_tokens_details': {'reasoning_tokens': 3}}}


def call(n=1):
    return {'type': 'function_call', 'id': f'item-{n}', 'status': 'completed',
            'call_id': f'call-{n}', 'name': 'echo', 'arguments': '{"value":"hi"}'}


@pytest.mark.asyncio
@pytest.mark.parametrize('gated', [False, True])
async def test_actual_runtime_preserves_ciphertext_and_tool_ids(gated):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.xai import XAIBackend
    from agents.core.tool_rpc import ToolRPCServer
    handled, enqueued, requests = [], [], []
    def enqueue(*args, **kwargs):
        enqueued.append(args)
        return 17
    server = ToolRPCServer(enqueue=enqueue)
    async def echo(args):
        handled.append(args)
        return {'echo': args['value']}
    server.register_tool('echo', echo, gated=gated,
                         input_schema={'type': 'object', 'properties': {'value': {'type': 'string'}}})
    first = completed('', calls=[call()], reasoning=True)
    def handler(req):
        assert str(req.url) == 'https://api.x.ai/v1/responses'
        requests.append(json.loads(req.content))
        return httpx.Response(200, json=first if len(requests) == 1 else completed())
    backend = XAIBackend('fixture', transport=httpx.MockTransport(handler), reasoning_effort='low')
    try:
        result = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id='trusted-athena', backend=backend, model='grok-4.6', prompt='echo hi')
        assert requests[0]['reasoning'] == {'effort': 'low'}
        assert requests[0]['include'] == ['reasoning.encrypted_content']
        assert requests[0]['store'] is False
        assert 'prompt_cache_retention' not in requests[0]
        if gated:
            assert enqueued and not handled and len(requests) == 1
        else:
            assert result == 'done' and handled == [{'value': 'hi'}]
            assert requests[1]['input'][2:4] == first['output']
            assert requests[1]['input'][4]['call_id'] == 'call-1'
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['calls', 'context'])
async def test_runtime_refuses_state_truncation_before_tool_execution(boundary):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.xai import XAIBackend
    from agents.core.tool_rpc import ToolRPCServer
    handled, requests = [], []
    server = ToolRPCServer()
    async def echo(args):
        handled.append(args)
        return 'ok'
    server.register_tool('echo', echo, gated=False)
    response = completed('', calls=[call(), call(2)] if boundary == 'calls' else [call()], reasoning=True)
    if boundary == 'context':
        response['output'][0]['encrypted_content'] = 'x' * 510000
    backend = XAIBackend('fixture', transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(200, json=response)))
    try:
        await AgentToolRuntime(server, enabled=lambda: True, max_tool_calls_per_turn=1).run(
            agent_id='trusted-athena', backend=backend, model='grok-4.6', prompt='go')
        assert len(requests) == 1 and not handled
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['lost', 'projection', 'model', 'backend', 'session', 'reorder'])
async def test_replay_cannot_cross_identity_or_lose_native_state(mutation):
    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.request_context import session_scope
    from agents.core.llm.responses_dialect import ResponsesRefused
    from agents.core.llm.xai import XAIBackend
    requests = []
    transport = httpx.MockTransport(lambda req: requests.append(req) or httpx.Response(
        200, json=completed('', calls=[call()], reasoning=True)))
    backend, other = XAIBackend('fixture', transport=transport), XAIBackend('other', transport=transport)
    try:
        with session_scope('one'), replay_scope():
            first = await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'hi'}], [])
            msg = first.as_assistant_message()
            history = [msg, {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'ok'}]
            target, model = backend, 'grok-4.6'
            if mutation == 'lost':
                msg.pop('_provider_replay')
            if mutation == 'projection':
                msg['content'] = 'changed'
            if mutation == 'model':
                model = 'grok-4.5'
            if mutation == 'backend':
                target = other
            if mutation == 'reorder':
                history.reverse()
            with session_scope('two' if mutation == 'session' else 'one'), pytest.raises(ResponsesRefused):
                await target.generate_tool_turn(model, history, [])
            assert len(requests) == 1
    finally:
        await backend.aclose()
        await other.aclose()


@pytest.mark.asyncio
async def test_nested_replay_scope_cannot_shed_parent_lifetime():
    import asyncio

    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.responses_dialect import ResponsesRefused
    from agents.core.llm.xai import XAIBackend
    requests, ready, go = [], asyncio.Event(), asyncio.Event()
    backend = XAIBackend('fixture', transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(200, json=completed())))
    async def child():
        with replay_scope():
            ready.set()
            await go.wait()
            return await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'hi'}], [])
    try:
        with replay_scope():
            task = asyncio.create_task(child())
            await ready.wait()
        go.set()
        with pytest.raises(ResponsesRefused):
            await task
        assert requests == []
    finally:
        go.set()
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('model,effort,expected', [
    ('grok-4.6', 'ultra', 'xhigh'), ('grok-4.6', 'medium', 'medium'),
    ('grok-4.5', 'xhigh', 'high'), ('grok-4.5', 'low', 'low'),
    ('grok-4.6', '', None), ('grok-4.5', '', None),
])
@pytest.mark.parametrize('mode', ['text', 'stream', 'tools'])
async def test_actual_wire_effort_and_usage(model, effort, expected, mode):
    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.usage_context import text_usage_scope
    from agents.core.llm.xai import XAIBackend
    requests, usage, tokens = [], [], []
    def handler(req):
        requests.append(json.loads(req.content))
        response = completed()
        if mode == 'stream':
            events = [{'type': 'response.output_text.delta', 'delta': 'done'},
                      {'type': 'response.completed', 'response': response}]
            return httpx.Response(200, content=''.join('data: '+json.dumps(e)+'\n\n' for e in events))
        return httpx.Response(200, json=response)
    backend = XAIBackend('fixture', transport=httpx.MockTransport(handler), reasoning_effort=effort)
    try:
        with replay_scope(), text_usage_scope(usage.append):
            if mode == 'tools':
                result = await backend.generate_tool_turn(model, [{'role': 'user', 'content': 'hi'}], [])
                assert result.content == 'done' and result.usage.output_tokens == 7
            elif mode == 'stream':
                assert await backend.generate_stream(model, 'hi', on_token=tokens.append) == 'done'
                assert tokens == ['done']
            else:
                assert await backend.generate(model, 'hi') == 'done'
        assert requests[0].get('reasoning') == ({'effort': expected} if expected else None)
        assert 'reasoning_effort' not in requests[0] and 'prompt_cache_key' not in requests[0]
        if mode != 'tools':
            assert len(usage) == 1 and usage[0].output_tokens == 7 and usage[0].cache_read == 60
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('effort', ['none', 'minimal'])
async def test_below_minimum_and_empty_declaration(effort):
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.xai import XAIBackend
    requests = []
    transport = httpx.MockTransport(lambda req: requests.append(req) or httpx.Response(200, json=completed()))
    backend = XAIBackend('fixture', transport=transport, reasoning_effort=effort)
    empty = XAIBackend('fixture', transport=transport, reasoning_effort=effort,
                       effort_declarations={'grok-4.6': []})
    try:
        with pytest.raises(ReasoningEffortRefused):
            await backend.generate('grok-4.6', 'hi')
        assert not requests
        assert await empty.generate('grok-4.6', 'hi') == 'done'
        assert 'reasoning' not in json.loads(requests[0].content)
    finally:
        await backend.aclose()
        await empty.aclose()


@pytest.mark.asyncio
async def test_actual_router_selection_and_local_policy(monkeypatch):
    from unittest.mock import AsyncMock

    from agents.core.llm.hybrid_router import HybridRouter, LocalBackendUnavailableError
    from agents.core.llm.providers import DEFAULT_REGISTRY
    from agents.core.llm.router import LLMRouter
    from agents.core.settings_db import DEFAULTS
    settings = {'compatible_provider': 'xai', 'compatible_model': 'grok-4.6', 'reasoning_effort': 'low'}
    assert DEFAULT_REGISTRY.get('xai').auth_env == 'XAI_API_KEY'
    assert any(r['key'] == 'compatible_provider' and 'xai' in r['opts'] for r in DEFAULTS)
    monkeypatch.setenv('XAI_API_KEY', 'fixture')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://must-not-use.invalid')
    monkeypatch.setattr(LLMRouter, 'detect', AsyncMock())
    monkeypatch.setattr(HybridRouter, '_check', AsyncMock(return_value=False))
    monkeypatch.setattr(HybridRouter, '_admin_setting', staticmethod(lambda k, d: settings.get(k, d)))
    router = HybridRouter()
    await router.detect()
    try:
        backend, model, route = router.select_backend('athena', '')
        assert backend.profile.id == 'xai' and model == 'grok-4.6' and route == 'cloud-compatible'
        requests = []
        await backend.client.aclose()
        backend.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: requests.append(req) or httpx.Response(200, json=completed())))
        assert await backend.generate(model, 'hi') == 'done'
        assert str(requests[0].url) == 'https://api.x.ai/v1/responses'
        with pytest.raises(LocalBackendUnavailableError):
            router.select_backend('frigga', '')
    finally:
        await router.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['grok-4', 'grok-4.6-latest', 'grok-4.20-multi-agent', [], None])
async def test_unknown_or_malformed_model_never_dispatches(model):
    from agents.core.llm.responses_dialect import ResponsesRefused
    from agents.core.llm.xai import XAIBackend
    requests = []
    backend = XAIBackend('fixture', transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(200, json=completed())))
    try:
        with pytest.raises(ResponsesRefused):
            await backend.generate(model, 'hi')
        assert not requests
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['missing_cipher', 'plaintext', 'oversize', 'duplicate', 'incomplete', 'hosted'])
async def test_malformed_opaque_response_never_publishes_or_executes(mutation):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.xai import XAIBackend
    from agents.core.tool_rpc import ToolRPCServer
    response = completed('', calls=[call()], reasoning=True)
    row = response['output'][0]
    if mutation == 'missing_cipher':
        row.pop('encrypted_content')
    elif mutation == 'plaintext':
        row['summary'] = [{'type': 'summary_text', 'text': 'must never retain'}]
        row.pop('encrypted_content')
    elif mutation == 'oversize':
        row['encrypted_content'] = 'x' * (512 * 1024 + 1)
    elif mutation == 'duplicate':
        response['output'].append(dict(row))
    elif mutation == 'incomplete':
        row['status'] = 'in_progress'
    else:
        row['type'] = 'web_search_call'
    handled, usage = [], []
    server = ToolRPCServer()
    async def echo(args):
        handled.append(args)
    server.register_tool('echo', echo, gated=False)
    backend = XAIBackend('fixture', transport=httpx.MockTransport(lambda req: httpx.Response(200, json=response)))
    try:
        result = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id='trusted-athena', backend=backend, model='grok-4.6', prompt='go', usage_sink=usage.append)
        assert result.startswith('[xAI Responses error:') and not handled and not usage
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_concurrent_runtime_loops_keep_native_items_separate():
    import asyncio

    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.xai import XAIBackend
    from agents.core.tool_rpc import ToolRPCServer
    first_ready, requests = asyncio.Event(), []
    server = ToolRPCServer()
    async def echo(args):
        await asyncio.sleep(0)
        return args
    server.register_tool('echo', echo, gated=False)
    async def handler(req):
        payload = json.loads(req.content)
        label = payload['input'][1]['content']
        requests.append(payload)
        if len(payload['input']) == 2:
            response = completed('', calls=[call()], reasoning=True)
            response['output'][0]['encrypted_content'] = 'cipher-'+label
            if label == 'A':
                first_ready.set()
                await asyncio.sleep(0)
            else:
                await first_ready.wait()
            return httpx.Response(200, json=response)
        assert payload['input'][2]['encrypted_content'] == 'cipher-'+label
        return httpx.Response(200, json=completed(label))
    backend = XAIBackend('fixture', transport=httpx.MockTransport(handler))
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    try:
        results = await asyncio.gather(*[runtime.run(agent_id='trusted-athena', backend=backend,
            model='grok-4.6', prompt=label) for label in ['A', 'B']])
        assert results == ['A', 'B'] and len(requests) == 4
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_cancelled_runtime_revokes_late_adapter_child():
    import asyncio

    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.responses_dialect import ResponsesRefused
    from agents.core.llm.xai import XAIBackend
    from agents.core.tool_rpc import ToolRPCServer
    ready, release, late, requests = asyncio.Event(), asyncio.Event(), [], []
    server = ToolRPCServer()
    async def echo(args):
        return args
    server.register_tool('echo', echo, gated=False)
    backend = XAIBackend('fixture', transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(200, json=completed())))
    original = backend.generate_tool_turn
    async def interrupted(*args, **kwargs):
        async def child():
            await release.wait()
            return await original(*args, **kwargs)
        late.append(asyncio.create_task(child()))
        ready.set()
        await asyncio.Event().wait()
    backend.generate_tool_turn = interrupted
    run = asyncio.create_task(AgentToolRuntime(server, enabled=lambda: True).run(
        agent_id='trusted-athena', backend=backend, model='grok-4.6', prompt='hi'))
    try:
        await ready.wait()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        release.set()
        with pytest.raises(ResponsesRefused):
            await late[0]
        assert not requests
    finally:
        release.set()
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('nested_null', [False, True])
async def test_expired_invocation_override_prevents_xai_http(nested_null):
    import asyncio
    from contextlib import nullcontext

    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope
    from agents.core.llm.xai import XAIBackend
    ready, go, requests = asyncio.Event(), asyncio.Event(), []
    backend = XAIBackend('fixture', effort_declarations={'grok-4.6': []}, transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(200, json=completed())))
    async def child():
        with reasoning_scope(None) if nested_null else nullcontext():
            ready.set()
            await go.wait()
            return await backend.generate('grok-4.6', 'hi')
    try:
        with reasoning_scope('low'):
            task = asyncio.create_task(child())
            await ready.wait()
        go.set()
        with pytest.raises(ReasoningEffortRefused):
            await task
        assert not requests
    finally:
        go.set()
        await backend.aclose()


@pytest.mark.asyncio
async def test_wholly_nonopaque_runtime_retains_late_child_behavior():
    import asyncio

    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.tool_protocol import ToolTurn
    from agents.core.tool_rpc import ToolRPCServer
    go, children = asyncio.Event(), []
    server = ToolRPCServer()
    async def echo(args):
        return args
    server.register_tool('echo', echo, gated=False)
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    class Backend:
        async def generate_tool_turn(self, **kwargs):
            if kwargs['messages'][1]['content'] == 'parent':
                async def child():
                    await go.wait()
                    return await runtime.run(agent_id='trusted-athena', backend=self,
                        model='fixture', prompt='child')
                children.append(asyncio.create_task(child()))
            return ToolTurn(content='done')
    assert await runtime.run(agent_id='trusted-athena', backend=Backend(), model='fixture', prompt='parent') == 'done'
    go.set()
    assert await children[0] == 'done'


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['error', 'duplicate', 'missing', 'close'])
async def test_xai_stream_failure_never_reports_usage_or_retries(fault):
    from agents.core.llm.usage_context import text_usage_scope
    from agents.core.llm.xai import XAIBackend
    response = completed(reasoning=True)
    events = [{'type': 'response.output_text.delta', 'delta': 'done'}]
    if fault != 'missing':
        events.append({'type': 'response.completed', 'response': response})
    if fault == 'error':
        events.append({'type': 'error', 'error': {'message': 'fixture'}})
    if fault == 'duplicate':
        events.append(events[-1])
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for event in events:
                yield ('data: '+json.dumps(event)+'\n\n').encode()
        async def aclose(self):
            if fault == 'close':
                raise OSError('fixture close')
    requests, usage = [], []
    backend = XAIBackend('fixture', transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(200, stream=Stream())))
    try:
        with text_usage_scope(usage.append):
            result = await backend.generate_stream('grok-4.6', 'hi')
        assert 'error' in result.lower() and not usage and len(requests) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_opaque_envelope_not_serialized_and_whole_history_loss_refuses():
    from dataclasses import FrozenInstanceError

    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.responses_dialect import ResponsesRefused
    from agents.core.llm.xai import XAIBackend
    requests = []
    backend = XAIBackend('fixture', transport=httpx.MockTransport(lambda req: requests.append(req)
        or httpx.Response(200, json=completed('', calls=[call()], reasoning=True))))
    try:
        with replay_scope():
            turn = await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'hi'}], [])
            assert 'fixture-ciphertext' not in repr(turn)
            assert 'fixture-ciphertext' not in repr(turn.as_assistant_message())
            with pytest.raises(TypeError):
                json.dumps(turn.as_assistant_message())
            with pytest.raises(FrozenInstanceError):
                turn.provider_replay.items = b'changed'
            with pytest.raises(ResponsesRefused):
                await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'new'}], [])
        with replay_scope(), pytest.raises(ResponsesRefused):
            await backend.generate_tool_turn('grok-4.6', [turn.as_assistant_message(),
                {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'ok'}], [])
        assert len(requests) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_scope_expiring_during_provider_response_cannot_publish_usage():
    import asyncio

    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.usage_context import text_usage_scope
    from agents.core.llm.xai import XAIBackend
    ready, release, usage = asyncio.Event(), asyncio.Event(), []
    async def handler(req):
        ready.set()
        await release.wait()
        return httpx.Response(200, json=completed())
    backend = XAIBackend('fixture', transport=httpx.MockTransport(handler))
    try:
        with replay_scope(), text_usage_scope(usage.append):
            child = asyncio.create_task(backend.generate('grok-4.6', 'hi'))
            await ready.wait()
        release.set()
        result = await child
        assert 'error' in result.lower() and not usage
    finally:
        release.set()
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('omitted', ['id', 'status', 'both'])
async def test_official_schema_optional_item_fields_replay_unchanged(omitted):
    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.xai import XAIBackend
    # xAI's embedded OpenAPI: function required arguments/call_id/name/type;
    # reasoning required summary/type. Item id/status are optional.
    response = completed('working', calls=[call()], reasoning=True)
    for row in response['output']:
        for key in (['id', 'status'] if omitted == 'both' else [omitted]):
            row.pop(key)
    requests = []
    backend = XAIBackend('fixture', transport=httpx.MockTransport(lambda req: requests.append(json.loads(req.content))
        or httpx.Response(200, json=response if len(requests) == 1 else completed())))
    try:
        with replay_scope():
            turn = await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'hi'}], [])
            assert turn.tool_calls
            await backend.generate_tool_turn('grok-4.6', [turn.as_assistant_message(),
                {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'ok'}], [])
            assert requests[1]['input'][:3] == response['output']
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_ciphertext_replays_without_optional_plaintext_reasoning():
    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.xai import XAIBackend
    response = completed('', calls=[call()], reasoning=True)
    response['output'][0]['summary'] = [{'type': 'summary_text', 'text': 'private reasoning'}]
    response['output'][0]['content'] = [{'type': 'reasoning_text', 'text': 'private full reasoning'}]
    requests = []
    backend = XAIBackend('fixture', transport=httpx.MockTransport(lambda req: requests.append(json.loads(req.content))
        or httpx.Response(200, json=response if len(requests) == 1 else completed())))
    try:
        with replay_scope():
            turn = await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'hi'}], [])
            assert turn.tool_calls and 'private' not in repr(turn)
            await backend.generate_tool_turn('grok-4.6', [turn.as_assistant_message(),
                {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'ok'}], [])
        item = requests[1]['input'][0]
        assert item['encrypted_content'] == 'fixture-ciphertext'
        assert item['summary'] == [] and 'content' not in item
        assert 'private' not in json.dumps(requests)
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('status', None), ('id', None), ('arguments', {}), ('name', []), ('call_id', '')])
async def test_malformed_native_call_fields_never_execute(field, value):
    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.xai import XAIBackend
    row = call()
    row[field] = value
    backend = XAIBackend('fixture', transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=completed('', calls=[row], reasoning=True))))
    try:
        with replay_scope():
            turn = await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'hi'}], [])
        assert not turn.tool_calls and turn.provider_replay is None
        assert turn.content.startswith('[xAI Responses error:')
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_other_responses_provider_cannot_silently_drop_replay_state():
    from agents.core.llm.provider_replay import replay_scope
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.responses_dialect import ResponsesRefused
    from agents.core.llm.xai import XAIBackend
    requests = []
    transport = httpx.MockTransport(lambda req: requests.append(req) or httpx.Response(
        200, json=completed('', calls=[call()], reasoning=True)))
    backend, other = XAIBackend('fixture', transport=transport), ResponsesBackend('fixture', transport=transport)
    try:
        with replay_scope():
            turn = await backend.generate_tool_turn('grok-4.6', [{'role': 'user', 'content': 'hi'}], [])
            with pytest.raises(ResponsesRefused):
                await other.generate_tool_turn('gpt-4.1', [turn.as_assistant_message(),
                    {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'ok'}], [])
        assert len(requests) == 1
    finally:
        await backend.aclose()
        await other.aclose()
