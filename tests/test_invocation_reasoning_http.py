import asyncio
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.cli.nerva import Context, main
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.reasoning_effort import LADDER


def setup_hub(monkeypatch):
    seen = []
    def provider(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}, 'finish_reason': 'stop'}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(provider), base_url='https://fixture.invalid')
    profile = ProviderProfile('compatible', 'fixture', 'openai-compatible', capabilities={'reasoning-effort'})
    backend = OpenRouterBackend(client=client, profile=profile, reasoning_effort='high', effort_declarations={'m': list(LADDER)})
    async def turn(message, **kwargs):
        return await backend.generate('m', message)
    async def stream(message, on_token, **kwargs):
        answer = await backend.generate_stream('m', message, on_token=on_token)
        return answer
    monkeypatch.setattr(web, 'orch', SimpleNamespace(notes=None, handle_input=turn, handle_input_stream=stream))
    return TestClient(web.app), client, backend, seen


@pytest.mark.parametrize('effort', LADDER)
def test_cli_to_actual_http_to_provider_payload(monkeypatch, effort):
    http, provider, backend, seen = setup_hub(monkeypatch)
    bodies = []
    class Hub:
        def post(self, path, body):
            bodies.append(body)
            response = http.post(path, json=body)
            assert response.status_code == 200
            return response.json()
    out = io.StringIO()
    ctx = Context(environ={}, out=out, err=io.StringIO(), client_factory=lambda env: Hub())
    try:
        assert main(['chat', 'hello', '--reasoning', effort], context=ctx) == 0
        assert bodies == [{'message': 'hello', 'reasoning': effort}]
        if effort == 'none':
            # Current compatible declarations exclude a disable rung: preserve H679 refusal.
            assert not seen
            assert 'error' in out.getvalue().lower()
        else:
            assert seen[0]['reasoning_effort'] == effort
        assert backend.reasoning_effort == 'high'
    finally:
        asyncio.run(provider.aclose())
        http.close()


@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('body', [{'message': 'hello'}, {'message': 'hello', 'reasoning': None}, {'message': 'hello', 'reasoning': 'none'}])
def test_http_and_sse_absence_null_and_explicit_none(monkeypatch, path, body):
    http, provider, backend, seen = setup_hub(monkeypatch)
    try:
        response = http.post(path, json=body)
        assert response.status_code == 200
        if body.get('reasoning') == 'none':
            assert not seen  # cannot fall back to configured high
        else:
            assert 'answer' in response.text
            assert seen[0]['reasoning_effort'] == 'high'
        assert backend.reasoning_effort == 'high'
    finally:
        asyncio.run(provider.aclose())
        http.close()


@pytest.mark.parametrize('bad', ['', 'HIGH', 'off', True, 0, [], {}, 'unlimited'])
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
def test_http_rejects_noncanonical_override_before_turn(monkeypatch, bad, path):
    http, provider, _, seen = setup_hub(monkeypatch)
    try:
        assert http.post(path, json={'message': 'hello', 'reasoning': bad}).status_code == 422
        assert not seen
    finally:
        asyncio.run(provider.aclose())
        http.close()


async def test_sse_scope_binds_inside_runner_and_revokes_inherited_child():
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import selected_reasoning
    gate = asyncio.Event()
    children = []
    async def stream(message, on_token, **kwargs):
        assert selected_reasoning('high') == 'low'
        async def child():
            await gate.wait()
            return selected_reasoning('high')
        children.append(asyncio.create_task(child()))
        await on_token('answer')
        return 'answer'
    orch = SimpleNamespace(handle_input_stream=stream)
    events = [event async for event in web._chat_event_stream(orch, 'hi', 'jarvis', None, reasoning='low')]
    assert any('answer' in event for event in events)
    assert selected_reasoning('high') == 'high'
    gate.set()
    with pytest.raises(ReasoningEffortRefused):
        await children[0]


async def test_sse_disconnect_revokes_override_and_preserves_outer_context():
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope, selected_reasoning
    entered, gate = asyncio.Event(), asyncio.Event()
    children = []
    async def stream(message, on_token, **kwargs):
        async def child():
            await gate.wait()
            return selected_reasoning('high')
        children.append(asyncio.create_task(child()))
        entered.set()
        await asyncio.Event().wait()
    orch = SimpleNamespace(handle_input_stream=stream)
    with reasoning_scope('medium'):
        events = web._chat_event_stream(orch, 'hi', 'jarvis', None, reasoning='low')
        await anext(events)
        await entered.wait()
        await events.aclose()
        assert selected_reasoning('high') == 'medium'
        gate.set()
        with pytest.raises(ReasoningEffortRefused):
            await children[0]
    assert selected_reasoning('high') == 'high'


@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
def test_http_explicit_none_disables_supported_anthropic_model(monkeypatch, path):
    from agents.core.llm.anthropic import ClaudeBackend
    seen = []
    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if payload.get('stream'):
            return httpx.Response(200, text='data: {"type":"message_stop"}\n\n')
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'ok'}]})
    backend = ClaudeBackend('fixture', reasoning_effort='high')
    asyncio.run(backend.client.aclose())
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async def turn(message, **kwargs):
        return await backend.generate('claude-opus-5', message, max_tokens=4096)
    async def stream(message, on_token, **kwargs):
        return await backend.generate_stream('claude-opus-5', message, max_tokens=4096, on_token=on_token)
    monkeypatch.setattr(web, 'orch', SimpleNamespace(notes=None, handle_input=turn, handle_input_stream=stream))
    try:
        response = TestClient(web.app).post(path, json={'message': 'hi', 'reasoning': 'none'})
        assert response.status_code == 200
        assert seen[0]['thinking'] == {'type': 'disabled'}
        assert seen[0]['output_config']['effort'] == 'high'
        assert backend.reasoning_effort == 'high'
    finally:
        asyncio.run(backend.client.aclose())


async def test_actual_concurrent_http_requests_share_backend_without_override_leak(monkeypatch):
    _, provider, backend, seen = setup_hub(monkeypatch)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='http://testserver') as client:
            replies = await asyncio.gather(*(client.post('/chat', json={'message': effort, 'reasoning': effort}) for effort in ['low', 'high']))
        assert all(reply.status_code == 200 for reply in replies)
        assert {payload['messages'][-1]['content']: payload['reasoning_effort'] for payload in seen} == {'low': 'low', 'high': 'high'}
        assert backend.reasoning_effort == 'high'
    finally:
        await provider.aclose()
