"""Prepared signed hooks reach the one leased physical native transport."""
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from agents.core.kernel import Decision, Verdict
from agents.core.llm.providers import DEFAULT_REGISTRY
from agents.core.llm.providers.admitted_profiles import AdmittedProviderProfile
from agents.core.llm.providers.hook_runtime import ProviderHookRuntimeError
from agents.core.llm.providers.native_transport import native_admitted_client
from agents.core.llm.providers.packages import ProviderPackageStore
from tests.test_h361_signed_native_integration import setup as signed_setup
from tests.test_openai_responses import completed as openai_completed
from tests.test_xai_responses import completed as xai_completed

CASES = (
    ('anthropic', 'anthropic', 'anthropic_messages', 'https://api.anthropic.com/v1', 'claude-sonnet-4-5'),
    ('gemini', 'gemini', 'gemini_generate_content',
     'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.5-flash'),
    ('deepinfra', 'deepinfra-chat', 'chat_completions', 'https://api.deepinfra.com/v1/openai', 'm'),
    ('openai-responses', 'openai-responses', 'responses', 'https://api.openai.com/v1', 'gpt-4.1'),
    ('xai', 'xai-responses', 'responses', 'https://api.x.ai/v1', 'grok-4.6'),
)


def response(kind, path):
    if kind == 'anthropic':
        if path == 'stream':
            return httpx.Response(200, text=(
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\n'
                'data: {"type":"message_stop"}\n\n'))
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'ok'}],
                                         'stop_reason': 'end_turn'})
    if kind == 'gemini':
        data = {'candidates': [{'content': {'parts': [{'text': 'ok'}]}, 'finishReason': 'STOP'}]}
        return (httpx.Response(200, text='data: ' + json.dumps(data) + '\n\n')
                if path == 'stream' else httpx.Response(200, json=data))
    if kind == 'deepinfra':
        data = {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}
        return (httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=(
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n')) if path == 'stream' else httpx.Response(200, json=data))
    data = xai_completed('ok') if kind == 'xai' else openai_completed('ok')
    if path == 'stream':
        return httpx.Response(200, text='data: ' + json.dumps({
            'type': 'response.output_text.delta', 'delta': 'ok'}) + '\n\n'
            'data: ' + json.dumps({'type': 'response.completed', 'response': data}) + '\n\n')
    return httpx.Response(200, json=data)


def setup_backend(tmp_path, monkeypatch, case, path):
    native, kind, mode, base, model = case
    signed = replace(DEFAULT_REGISTRY.get(native), id='signed-' + native,
                     backend_kind=kind, api_mode=mode, default_base_url=base,
                     fallback_models=(model,), default_max_tokens=64,
                     reasoning_declarations=None)
    store = object.__new__(ProviderPackageStore)
    store._lock_path = tmp_path / 'registry.lock'
    store._root_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    actions = []
    store.authorizer = lambda action: (actions.append(action) or Decision(Verdict.GRANT, tier=3))
    calls = []

    class Runtime:
        packages = store

        async def evaluate(self, provider_id, **kwargs):
            calls.append((provider_id, kwargs))
            messages = json.loads(json.dumps(kwargs['messages']))
            for row in messages:
                if row.get('role') == 'user' and type(row.get('content')) is str:
                    row['content'] += ' [sealed]'
            declared = signed.supported_reasoning_efforts(kwargs['model'])
            return {'prepared_messages': messages, 'extra_body': {},
                    'api_kwargs': {'extra_body': {}, 'kwargs': {}}, 'max_tokens': 64,
                    'reasoning_vocabulary': list(declared) if declared is not None else None}

        @asynccontextmanager
        async def dispatch_lease(self, provider_id, *, package_hash, home):
            async with store.dispatch_lease(provider_id, expected_hash=package_hash, home=home):
                yield

    profile = AdmittedProviderProfile.from_record(
        SimpleNamespace(profile=signed, package_hash='f' * 64, home='synthetic-home'), Runtime())
    store._require_runnable_locked = lambda *_: SimpleNamespace(
        provider_id=profile.id, artifact_id='a' * 32, package_hash=profile._package_hash,
        source='user', home=profile._home, profile=signed)
    seen = []

    def handler(request):
        seen.append(request)
        return response(native, path)

    def synthetic_client(profile, credential, model, **kwargs):
        kwargs.pop('inner', None)
        return native_admitted_client(profile, credential, model,
                                      inner=httpx.MockTransport(handler), **kwargs)

    module = __import__('agents.core.llm.' + ('responses' if native == 'openai-responses' else native),
                        fromlist=['native_admitted_client'])
    monkeypatch.setattr(module, 'native_admitted_client', synthetic_client)
    if native == 'anthropic':
        from agents.core.llm.anthropic import ClaudeBackend
        backend = ClaudeBackend('host-secret', model=model, profile=profile)
    elif native == 'gemini':
        from agents.core.llm.gemini import GeminiBackend
        backend = GeminiBackend('host-secret', model=model, profile=profile)
    elif native == 'deepinfra':
        from agents.core.llm.deepinfra import DeepInfraBackend
        backend = DeepInfraBackend('host-secret', base_url=base, profile=profile, model=model)
    elif native == 'openai-responses':
        from agents.core.llm.responses import ResponsesBackend
        backend = ResponsesBackend('host-secret', profile=profile, model=model)
    else:
        from agents.core.llm.xai import XAIBackend
        backend = XAIBackend('host-secret', profile=profile, model=model)
    return backend, model, calls, seen, actions


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('path', ['text', 'tool', 'stream'])
async def test_admitted_native_text_tool_stream_use_signed_hook_and_physical_lease(tmp_path, monkeypatch, case, path):
    backend, model, calls, seen, actions = setup_backend(tmp_path, monkeypatch, case, path)
    try:
        if path == 'text':
            result = await backend.generate(model, 'hello')
        elif path == 'tool':
            if case[0] == 'xai':
                from agents.core.llm.provider_replay import replay_scope
                with replay_scope():
                    result = await backend.generate_tool_turn(
                        model, [{'role': 'user', 'content': 'hello'}], [])
            else:
                result = await backend.generate_tool_turn(
                    model, [{'role': 'user', 'content': 'hello'}], [])
            result = result.content
        else:
            result = await backend.generate_stream(model, 'hello')
        assert result == 'ok'
        assert len(seen) == len(calls) == len(actions) == 1
        assert actions[0].kind == 'plugin.egress'
        assert 'host-secret' not in repr(calls)
    finally:
        if hasattr(backend, 'aclose'):
            await backend.aclose()
        elif hasattr(backend, 'close'):
            await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
async def test_trusted_signed_registry_constructs_native_guarded_backend(tmp_path, monkeypatch, case):
    native, kind, mode, base, model = case
    profile = replace(DEFAULT_REGISTRY.get(native), id='signed-addon',
                      display_name='Signed native fixture', aliases=('signed-alias',),
                      backend_kind=kind, api_mode=mode, default_base_url=base,
                      fallback_models=(model,), default_max_tokens=64,
                      capabilities=frozenset({'chat', 'cloud'}),
                      reasoning_declarations=None, is_user_defined=True)
    seen = []

    def synthetic_client(profile, credential, model, **kwargs):
        kwargs.pop('inner', None)
        return native_admitted_client(profile, credential, model,
            inner=httpx.MockTransport(lambda request: seen.append(request) or response(native, 'text')),
            **kwargs)

    module = __import__('agents.core.llm.' + ('responses' if native == 'openai-responses' else native),
                        fromlist=['native_admitted_client'])
    monkeypatch.setattr(module, 'native_admitted_client', synthetic_client)
    backend, _, runner, actions, owners, _ = signed_setup(
        tmp_path, monkeypatch, profile_override=profile, model=model)
    try:
        assert await backend.generate(model, 'hello') == 'ok'
        assert len(seen) == len(runner.commands) == 1
        assert owners and any(action.kind == 'plugin.egress' for action in actions)
    finally:
        if hasattr(backend, 'aclose'):
            await backend.aclose()
        elif hasattr(backend, 'close'):
            await backend.close()


@pytest.mark.asyncio
async def test_signed_owner_approval_and_real_kernel_authorize_native_egress(tmp_path, monkeypatch):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.capability_manifests import manifest_for_action
    from agents.core.kernel import authorize
    from agents.core.llm.providers.install_service import ProviderInstallService

    native, kind, mode, base, model = CASES[0]
    profile = replace(DEFAULT_REGISTRY.get(native), id='signed-addon',
                      display_name='Signed native fixture', aliases=('signed-alias',),
                      backend_kind=kind, api_mode=mode, default_base_url=base,
                      fallback_models=(model,), default_max_tokens=64,
                      capabilities=frozenset({'chat', 'cloud'}),
                      reasoning_declarations=None, is_user_defined=True)
    seen = []

    def synthetic_client(profile, credential, model, **kwargs):
        kwargs.pop('inner', None)
        return native_admitted_client(profile, credential, model,
            inner=httpx.MockTransport(lambda request: seen.append(request) or response(native, 'text')),
            **kwargs)

    monkeypatch.setattr('agents.core.llm.anthropic.native_admitted_client', synthetic_client)
    backend, packages, runner, actions, owners, _ = signed_setup(
        tmp_path, monkeypatch, profile_override=profile, model=model)

    verdicts = []

    policy = AutonomyPolicy()

    def bound_kernel(action, *, approval_check):
        actions.append(action)
        decision = authorize(action, policy=policy, approval_check=approval_check)
        verdicts.append((action.kind, decision.verdict, decision.reason))
        return decision

    service = ProviderInstallService(
        root=tmp_path, signing=packages.signing, profile=None,
        kernel=lambda: bound_kernel, enabled=lambda: True, home='synthetic-home')
    service_store = service._store()
    backend.profile._hook_runtime.packages = service_store
    try:
        with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
            await backend.client.post(
                base + '/messages', headers={'x-api-key': 'synthetic-host-key'},
                json={'model': model, 'messages': [{'role': 'user', 'content': 'no hook preparation'}]})
        assert not seen and not runner.commands
        assert owners and await backend.generate(model, 'hello') == 'ok', verdicts
        assert len(runner.commands) == len(seen) == 1
        egress = [action for action in actions if action.kind == 'plugin.egress']
        assert len(egress) == 1
        assert all(key in egress[0].payload for key in
                   manifest_for_action('plugin.egress').inputs['required'])
        assert egress[0].payload['request_sha256'] == hashlib.sha256(seen[0].content).hexdigest()
        assert 'synthetic-host-key' not in repr(egress[0])
        assert 'hello' not in repr(egress[0])
        # The exact previously granted Action is no longer a receipt outside the send.
        assert service_store.authorizer(egress[0]).verdict is Verdict.DENY
        async with service_store.dispatch_lease(
                'signed-addon', expected_hash=egress[0].payload['package_hash'],
                home='synthetic-home'):
            # A live package lease alone cannot bless a fabricated egress Action.
            assert service_store.authorizer(egress[0]).verdict is Verdict.DENY
        for field, changed in [('url', 'https://elsewhere.invalid/v1/messages'),
                               ('model', 'other'), ('package_hash', '0' * 64),
                               ('receipt_id', '0' * 32)]:
            forged = deepcopy(egress[0])
            forged.payload[field] = changed
            assert service_store.authorizer(forged).verdict is Verdict.DENY
        policy.mode = 'ask'
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate(model, 'again')
        assert len(seen) == 1 and verdicts[-1][1] is Verdict.QUEUE
        policy.mode = 'auto'
        await service_store.revoke_async('signed-addon')
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate(model, 'revoked')
        assert len(seen) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('mutation', [
    'transport', 'mount', 'redirect', 'selector', 'inner', 'request_hook', 'response_hook'])
async def test_native_adapter_refuses_changed_client_route(tmp_path, monkeypatch, case, mutation):
    backend, _, _, seen, _ = setup_backend(tmp_path, monkeypatch, case, 'text')
    client = backend._client
    if mutation == 'transport':
        client._transport = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200))
    elif mutation == 'mount':
        client._mounts[object()] = httpx.MockTransport(
            lambda req: seen.append(req) or httpx.Response(200))
    elif mutation == 'redirect':
        client.follow_redirects = True
    elif mutation == 'selector':
        client._transport_for_url = lambda url: client._transport
    elif mutation == 'request_hook':
        client.event_hooks['request'].pop()
    elif mutation == 'response_hook':
        client.event_hooks['response'].clear()
    else:
        client._transport.inner = object()
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        _ = backend.client
    assert seen == []


@pytest.mark.asyncio
async def test_admitted_gemini_cache_binding_and_auth_pool_refuse(tmp_path, monkeypatch):
    from agents.core.llm.auth_rotation import AuthLease
    from agents.core.llm.gemini_context import GeminiRequestBinding
    from agents.core.llm.provider_request import ProfileRequestRefused

    backend, _, _, seen, _ = setup_backend(tmp_path, monkeypatch, CASES[1], 'text')
    binding = GeminiRequestBinding(
        lease=AuthLease(profile_id='fixture', api_key='host-secret'),
        cache_name='cachedContents/ungarded')
    with (pytest.raises(ProfileRequestRefused, match='cache client is unavailable'),
          backend.request_scope(binding)):
        pass
    backend.auth_pool = object()
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        _ = backend.client
    assert seen == []
    await backend._client.aclose()
