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
from agents.core.turn_usage import turn_usage_scope
from tests.test_openai_responses import completed as openai_completed
from tests.test_xai_responses import completed as xai_completed

CASES = (
    ('anthropic', 'anthropic', 'anthropic_messages', 'https://api.anthropic.com/v1', 'claude-sonnet-4-5'),
    ('gemini', 'gemini', 'gemini_generate_content',
     'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.5-flash'),
    ('deepinfra', 'deepinfra-chat', 'chat_completions', 'https://api.deepinfra.com/v1/openai', 'm'),
    ('openai-responses', 'openai-responses', 'responses', 'https://api.openai.com/v1', 'gpt-4.1'),
    ('xai', 'xai-responses', 'responses', 'https://api.x.ai/v1', 'grok-4.6'),
    ('openrouter', 'openai-compatible', 'chat_completions', 'https://synthetic.invalid/v1', 'synthetic-model'),
)


def response(kind, path):
    if kind == 'openrouter':
        return (httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=(
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n')) if path == 'stream' else httpx.Response(200, json={
                'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}))
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


def setup_backend(tmp_path, monkeypatch, case, path, *, identity=None):
    """Real signed owner, selection, Kernel and Vault; fake DNS/HTTP only."""
    import os

    from agents.core import settings_db
    from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
    from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
    from agents.core.llm import data_handling, provider_selection
    from agents.core.llm.backend_factory import construct_selected_backend
    from agents.core.llm.data_handling import physical_request_scope
    from agents.core.llm.providers import selected_runtime
    from agents.core.llm.providers.install_service import ProviderInstallService
    from tests.test_h361_provider_hook_runtime import IMAGE, SimulatedSealedRunner
    from tests.test_h361_provider_install_kernel import _bind_real_kernel
    from tests.test_h361_provider_install_service import owner

    native, kind, mode, base, model = case
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(selected_runtime, 'resolve_and_validate',
                        lambda host, mode: (['93.184.216.34'], None))
    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'x' * 32)
    signing = ManagedSigningKeyStore(tmp_path / 'signing')
    signing.provision(key_id='synthetic-bridge', version=1, key=b'x' * 32)
    runner = SimulatedSealedRunner()
    service = ProviderInstallService(root=tmp_path / 'service', signing=signing,
        profile=AcquisitionSandboxProfile(image=IMAGE, uid=os.getuid(), gid=os.getgid()),
        kernel=lambda: None, enabled=lambda: True, home='synthetic-home', runner=runner,
        audit=SimpleNamespace(log=lambda _event: None))
    service, orch, kill, kernel_actions = _bind_real_kernel((service, None, None, None), tmp_path)
    identity = identity or 'signed-' + native
    source = service.incoming('user') / 'addon'
    source.mkdir(parents=True)
    (source / 'provider.json').write_text(json.dumps(
        {'schema_version': 1, 'id': identity, 'aliases': []}))
    (source / 'helper.py').write_text("def marker():\n    return 'signed-worker'\n")
    hooks = ('prepare_messages', 'build_extra_body', 'build_api_kwargs_extras')
    (source / 'main.py').write_text(
        'from helper import marker\n'
        'def register_provider():\n    return ' + repr({'id': identity, 'hooks': list(hooks)}) + '\n'
        'def prepare_messages(messages):\n    return messages\n'
        'def build_extra_body(**kwargs):\n    return {"plugin_marker": marker()}\n'
        'def build_api_kwargs_extras(**kwargs):\n    return {}, {}\n')
    signed = replace(DEFAULT_REGISTRY.get(native), id=identity, display_name='Signed native fixture',
        aliases=(), backend_kind=kind, api_mode=mode, default_base_url=base,
        fallback_models=(model,), default_max_tokens=64, reasoning_declarations=None,
        auth_env=None, env_vars=(), base_url_env=None, auth_type='bearer',
        capabilities=frozenset({'chat', 'cloud'}), is_user_defined=True)
    artifact = service.stage('addon', profile=signed, hooks=hooks, source='user', actor=owner())
    offer = service.propose(artifact['artifact_id'], actor=owner())
    service.decide(offer['proposal_id'], artifact_id=artifact['artifact_id'],
                   package_hash=artifact['package_hash'], approved=True, permanent=True,
                   actor=owner())
    service.promote(offer['proposal_id'], actor=owner())
    service.put_credential(identity, artifact['package_hash'], 'host-secret', actor=owner())
    service.select_provider(identity, artifact['package_hash'], model,
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    runtime = service.selected_runtime()
    backend = construct_selected_backend(runtime)
    router = SimpleNamespace(_data_handling_used={})
    runtime.bind_backend(backend, router)
    wire = []

    def handler(request):
        wire.append(request)
        return response(native, path)

    backend.client._transport.inner = httpx.MockTransport(handler)
    # These adapter-level tests emulate the routed H513 scope. The physical
    # guard still rechecks exact selected consent and the current signed record.
    for method in ('generate', 'generate_tool_turn', 'generate_stream'):
        original = getattr(backend, method, None)
        if original is None:
            continue
        async def guarded(*args, _original=original, **kwargs):
            with physical_request_scope(lambda: None):
                return await _original(*args, **kwargs)
        setattr(backend, method, guarded)
    actions = [action for action, _decision in kernel_actions if action.kind == 'plugin.egress']
    store = runtime.profile._hook_runtime.packages
    authorize = store.authorizer
    def record_action(action):
        if action.kind == 'plugin.egress':
            actions.append(action)
        return authorize(action)
    store.authorizer = record_action
    backend._selected_test_service = service
    backend._selected_test_kernel = (orch, kill, kernel_actions)
    backend._selected_test_runner = runner
    backend._selected_test_source = source
    return backend, model, runner.commands, wire, actions


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


class HeldCompatibleSSE(httpx.AsyncByteStream):
    def __init__(self):
        self.first = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        self.first.set()
        yield b'data: {"choices":[{"delta":{"content":"hello world"}}]}\n\n'
        await self.release.wait()
        yield b'data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}]}\n\n'
        yield b'data: [DONE]\n\n'

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_selected_compatible_stream_delta_precedes_eof_and_holds_lease(tmp_path, monkeypatch, cancel):
    from agents.core.llm.providers.selection_gates import SelectionBusy
    from tests.test_h361_provider_install_service import owner

    backend, model, calls, wire, actions = setup_backend(tmp_path, monkeypatch, CASES[-1], 'stream')
    body = HeldCompatibleSSE()
    backend.client._transport.inner = httpx.MockTransport(
        lambda request: wire.append(request) or httpx.Response(
            200, headers={'content-type': 'text/event-stream'}, stream=body))
    tokens = []
    first_token = asyncio.Event()

    def on_token(token):
        tokens.append(token)
        first_token.set()

    try:
        with turn_usage_scope() as usage:
            task = asyncio.create_task(backend.generate_stream(model, 'hello', on_token=on_token))
            await asyncio.wait_for(first_token.wait(), 2)
            assert body.first.is_set() and not task.done() and not body.closed
            assert ''.join(tokens) and len(wire) == len(calls) == len(actions) == 1
            with pytest.raises(SelectionBusy):
                backend._selected_test_service.clear_selection(
                    expected_revision=backend._selected_provider_runtime.selection.revision,
                    actor=owner())
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
            else:
                body.release.set()
                assert await asyncio.wait_for(task, 2) == 'hello world!'
            assert usage.snapshot()['api_calls'] == 1
        await asyncio.wait_for(asyncio.gather(*(
            stream.close_task for stream in backend.client._transport._streams
            if stream.close_task is not None)), 2)
        assert body.closed and len(wire) == len(actions) == 1
    finally:
        body.release.set()
        await backend.aclose()


@pytest.mark.asyncio
async def test_selected_compatible_stream_retry_gets_fresh_preparation_and_one_count_each(tmp_path, monkeypatch):
    backend, model, calls, wire, actions = setup_backend(tmp_path, monkeypatch, CASES[-1], 'stream')
    try:
        with turn_usage_scope() as usage:
            assert await backend.generate_stream(model, 'first') == 'ok'
            assert await backend.generate_stream(model, 'retry') == 'ok'
            assert usage.snapshot()['api_calls'] == 2
        assert len(calls) == len(wire) == len(actions) == 2
        assert all(json.loads(req.content)['stream'] is True for req in wire)
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_selected_compatible_owner_quiesce_drains_active_stream_before_clear(tmp_path, monkeypatch):
    from agents.core.llm.providers import lifecycle_gates
    from tests.test_h361_provider_install_service import owner

    backend, model, calls, wire, actions = setup_backend(tmp_path, monkeypatch, CASES[-1], 'stream')
    body = HeldCompatibleSSE()
    backend.client._transport.inner = httpx.MockTransport(
        lambda request: wire.append(request) or httpx.Response(
            200, headers={'content-type': 'text/event-stream'}, stream=body))
    first_token = asyncio.Event()
    try:
        with turn_usage_scope() as usage:
            task = asyncio.create_task(backend.generate_stream(
                model, 'hello', on_token=lambda _: first_token.set()))
            await asyncio.wait_for(first_token.wait(), 2)
            service = backend._selected_test_service
            store = backend.profile._hook_runtime.packages
            await asyncio.wait_for(lifecycle_gates.quiesce(service.root, backend.profile.id, store), 2)
            with pytest.raises(asyncio.CancelledError):
                await task
            service.clear_selection(
                expected_revision=backend._selected_provider_runtime.selection.revision,
                actor=owner())
            with pytest.raises(ProviderHookRuntimeError):
                await backend.generate_stream(model, 'retry')
            assert usage.snapshot()['api_calls'] == 1
        assert body.closed and len(wire) == len(actions) == 1 and len(calls) == 2
    finally:
        body.release.set()
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
async def test_trusted_signed_registry_constructs_native_guarded_backend(tmp_path, monkeypatch, case):
    from tests.test_h361_provider_install_service import owner

    backend, model, calls, wire, actions = setup_backend(tmp_path, monkeypatch, case, 'text')
    try:
        runtime = backend._selected_provider_runtime
        assert runtime.service.selection_status(actor=owner())['status'] == 'selected'
        assert runtime.profile is backend.profile
        assert await backend.generate(model, 'hello') == 'ok'
        assert len(wire) == len(calls) == len(actions) == 1
        assert actions[0].kind == 'plugin.egress'
    finally:
        if hasattr(backend, 'aclose'):
            await backend.aclose()
        else:
            await backend.close()


@pytest.mark.asyncio
async def test_signed_owner_approval_and_real_kernel_authorize_native_egress(tmp_path, monkeypatch):
    from agents.core.capability_manifests import manifest_for_action
    from agents.core.kernel import Verdict

    case = CASES[0]
    backend, model, calls, wire, actions = setup_backend(tmp_path, monkeypatch, case, 'text')
    runtime = backend._selected_provider_runtime
    service_store = runtime.profile._hook_runtime.packages
    policy = backend._selected_test_kernel[0].autonomy.policy
    try:
        with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
            await backend.client.post(
                case[3] + '/messages', headers={'x-api-key': 'nerva-selected-host-credential'},
                json={'model': model, 'messages': [{'role': 'user', 'content': 'no hook preparation'}]})
        assert not wire and not calls
        assert await backend.generate(model, 'hello') == 'ok'
        assert len(calls) == len(wire) == 1
        assert len(actions) == 1
        egress = actions[0]
        assert all(key in egress.payload for key in
                   manifest_for_action('plugin.egress').inputs['required'])
        assert egress.payload['request_sha256'] == hashlib.sha256(wire[0].content).hexdigest()
        assert 'host-secret' not in repr(egress)
        assert 'hello' not in repr(egress)
        assert service_store.authorizer(egress).verdict is Verdict.DENY
        async with service_store.dispatch_lease(
                runtime.profile.id, expected_hash=egress.payload['package_hash'],
                home=runtime.service.home):
            assert service_store.authorizer(egress).verdict is Verdict.DENY
        for field, changed in [('url', 'https://elsewhere.invalid/v1/messages'),
                               ('model', 'other'), ('package_hash', '0' * 64),
                               ('receipt_id', '0' * 32)]:
            forged = deepcopy(egress)
            forged.payload[field] = changed
            assert service_store.authorizer(forged).verdict is Verdict.DENY
        policy.mode = 'ask'
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate(model, 'again')
        assert len(wire) == 1
        policy.mode = 'auto'
        await service_store.revoke_async(runtime.profile.id)
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate(model, 'revoked')
        assert len(wire) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('mutation', [
    'transport', 'mount', 'redirect', 'selector', 'inner', 'request_hook', 'response_hook'])
async def test_native_adapter_refuses_changed_client_route(tmp_path, monkeypatch, case, mutation):
    backend, _, _, seen, _ = setup_backend(tmp_path, monkeypatch, case, 'text')
    client = getattr(backend, '_client', None) or backend.client
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
        _ = backend._send_client() if case[0] == 'openrouter' else backend.client
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
