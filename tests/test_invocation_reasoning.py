import asyncio

import pytest


def test_scope_absent_none_and_nested_default():
    from agents.core.llm.request_context import reasoning_scope, selected_reasoning
    assert selected_reasoning('high') == 'high'
    with reasoning_scope(None):
        assert selected_reasoning('high') == 'high'
    with reasoning_scope('none'):
        assert selected_reasoning('high') == 'none'
        with reasoning_scope('low'):
            assert selected_reasoning('high') == 'low'
        assert selected_reasoning('high') == 'none'
    assert selected_reasoning('high') == 'high'


@pytest.mark.parametrize('bad', ['', 'HIGH', 'off', 1, True, [], {}])
def test_scope_rejects_noncanonical_values(bad):
    from agents.core.llm.request_context import reasoning_scope
    with pytest.raises(ValueError), reasoning_scope(bad):
        pass


async def test_explicit_scope_revokes_late_children_but_absence_does_not():
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope, selected_reasoning
    for effort in [None, 'low']:
        gate = asyncio.Event()
        async def late(gate=gate):
            await gate.wait()
            return selected_reasoning('high')
        with reasoning_scope(effort):
            task = asyncio.create_task(late())
        gate.set()
        if effort is None:
            assert await task == 'high'
        else:
            with pytest.raises(ReasoningEffortRefused):
                await task


async def test_concurrent_overrides_do_not_mutate_shared_default():
    from agents.core.llm.request_context import reasoning_scope, selected_reasoning
    async def run(value):
        with reasoning_scope(value):
            await asyncio.sleep(0)
            return selected_reasoning('high')
    assert await asyncio.gather(run('none'), run('low'), run(None)) == ['none', 'low', 'high']


@pytest.mark.parametrize('vocabulary', ['declared', 'empty', 'unknown'])
@pytest.mark.parametrize('vendor', ['compatible', 'openrouter', 'gemini', 'anthropic'])
@pytest.mark.parametrize('method', ['generate', 'generate_stream', 'generate_tool_turn'])
async def test_actual_provider_calls_use_override_without_mutating_backend(vendor, method, vocabulary):
    import json

    import httpx

    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.gemini import GeminiBackend
    from agents.core.llm.openrouter import OpenRouterBackend
    from agents.core.llm.providers import ProviderProfile
    from agents.core.llm.request_context import reasoning_scope
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        if vendor == 'anthropic':
            if method == 'generate_stream':
                return httpx.Response(200, text='data: {"type":"message_stop"}\n\n')
            return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'ok'}], 'stop_reason': 'end_turn'})
        if vendor == 'gemini':
            body = {'candidates': [{'content': {'parts': [{'text': 'ok'}]}, 'finishReason': 'STOP'}]}
            return httpx.Response(200, text='data: '+json.dumps(body)+'\n\n') if method == 'generate_stream' else httpx.Response(200, json=body)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='https://fixture.invalid')
    if vendor == 'anthropic':
        model = 'invocation-unknown' if vocabulary == 'unknown' else 'claude-sonnet-4-6'
        backend = ClaudeBackend('fixture', reasoning_effort='high', effort_overrides={model: []} if vocabulary == 'empty' else None)
    elif vendor == 'gemini':
        model = 'invocation-unknown' if vocabulary == 'unknown' else 'gemini-3-flash-preview'
        backend = GeminiBackend('fixture', reasoning_effort='high', effort_declarations={model: []} if vocabulary == 'empty' else None)
    else:
        profile = ProviderProfile(vendor, vendor, 'openai-compatible', capabilities={'reasoning-effort'})
        backend, model = OpenRouterBackend(client=client, profile=profile, reasoning_effort='high',
                                           effort_declarations=({'m': ['low', 'high']} if vocabulary == 'declared' else {'m': []} if vocabulary == 'empty' else {})), 'm'
    if backend.client is not client:
        await backend.client.aclose()
        backend.client = client
    kwargs = {'model': model, 'max_tokens': 4096}
    kwargs.update({'messages': [], 'tools': []} if method == 'generate_tool_turn' else {'prompt': 'hi'})
    if method == 'generate_stream':
        kwargs['on_token'] = lambda text: None
    try:
        with reasoning_scope('low'):
            await getattr(backend, method)(**kwargs)
        assert len(seen) == 1
        payload = seen[0]
        if vocabulary != 'declared':
            assert 'thinking' not in payload
            assert 'effort' not in payload.get('output_config', {})
            assert 'reasoning' not in payload and 'reasoning_effort' not in payload
            assert 'thinkingConfig' not in payload.get('generationConfig', {})
        elif vendor == 'anthropic':
            assert payload['output_config']['effort'] == 'low'
        elif vendor == 'gemini':
            assert payload['generationConfig']['thinkingConfig']['thinkingLevel'] == 'low'
        elif vendor == 'openrouter':
            assert payload['reasoning'] == {'effort': 'low'}
        else:
            assert payload['reasoning_effort'] == 'low'
        assert backend.reasoning_effort == 'high'
    finally:
        await client.aclose()


@pytest.mark.parametrize('vendor', ['anthropic', 'gemini'])
async def test_expired_override_cannot_retry_prebuilt_payload(vendor):
    import httpx

    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.auth_rotation import AuthProfilePool
    from agents.core.llm.gemini import GeminiBackend
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(401, json={'error': {'message': 'fixture'}})
    pool = AuthProfilePool(['first-key', 'second-key'], vendor)
    if vendor == 'anthropic':
        backend, model = ClaudeBackend('fixture', auth_pool=pool, reasoning_effort='high'), 'claude-sonnet-4-6'
    else:
        backend, model = GeminiBackend('fixture', auth_pool=pool, reasoning_effort='high'), 'gemini-3-flash-preview'
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with reasoning_scope('low'):
            task = asyncio.create_task(backend.generate_tool_turn(model=model, messages=[], tools=[], max_tokens=4096))
            await entered.wait()
        release.set()
        with pytest.raises(ReasoningEffortRefused):
            await task
        assert len(calls) == 1
    finally:
        release.set()
        await backend.client.aclose()


async def test_closed_override_cannot_be_cleared_by_late_absent_scope():
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope, selected_reasoning
    gate = asyncio.Event()
    async def late():
        await gate.wait()
        with reasoning_scope(None):
            return selected_reasoning('high')
    with reasoning_scope('low'):
        task = asyncio.create_task(late())
    gate.set()
    with pytest.raises(ReasoningEffortRefused):
        await task


def test_exception_restores_parent_override():
    from agents.core.llm.request_context import reasoning_scope, selected_reasoning
    with reasoning_scope('low'):
        with pytest.raises(RuntimeError), reasoning_scope('none'):
            raise RuntimeError('fixture')
        assert selected_reasoning('high') == 'low'
    assert selected_reasoning('high') == 'high'


@pytest.mark.parametrize('args', [['--help'], ['chat', '--help'], ['completion', 'bash']])
def test_cli_starts_without_site_packages(args):
    import subprocess
    import sys
    from pathlib import Path
    result = subprocess.run([sys.executable, '-S', 'scripts/nerva.py', *args],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout


def test_cli_choices_match_runtime_ladder():
    import argparse

    from agents.cli.nerva import build_parser
    from agents.core.llm.reasoning_effort import LADDER
    parser = build_parser()
    verbs = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    reasoning = next(action for action in verbs.choices['chat']._actions if action.dest == 'reasoning')
    assert tuple(reasoning.choices) == LADDER


async def test_null_child_entered_while_active_cannot_outlive_explicit_ancestor():
    import httpx

    from agents.core.llm.openrouter import OpenRouterBackend
    from agents.core.llm.providers import ProviderProfile
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope, selected_reasoning
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='https://fixture.invalid') as client:
        backend = OpenRouterBackend(client=client, profile=ProviderProfile('compatible', 'fixture',
            'openai-compatible', capabilities={'reasoning-effort'}), reasoning_effort='high',
            effort_declarations={'m': ['low', 'high']})
        entered, resume = asyncio.Event(), asyncio.Event()
        async def child():
            with reasoning_scope(None):
                assert selected_reasoning('high') == 'high'
                entered.set()
                await resume.wait()
                return await backend.generate('m', 'hello')
        with reasoning_scope('low'):
            task = asyncio.create_task(child())
            await entered.wait()
        resume.set()
        with pytest.raises(ReasoningEffortRefused):
            await task
        assert not calls
        assert backend.reasoning_effort == 'high'
