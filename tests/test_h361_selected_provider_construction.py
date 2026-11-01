"""Six signed dialects construct with a marker, never the encrypted key."""
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.llm.backend_factory import construct_selected_backend
from agents.core.llm.data_handling import physical_request_scope
from agents.core.llm.providers.selected_runtime import AUTH_MARKER
from tests.test_h361_admitted_native_bridge import response
from tests.test_h361_provider_install_kernel import _bind_real_kernel
from tests.test_h361_provider_install_service import owner, service


@pytest.mark.parametrize(('kind', 'mode'), [
    ('openai-compatible', 'chat_completions'),
    ('deepinfra-chat', 'chat_completions'),
    ('openai-responses', 'responses'),
    ('xai-responses', 'responses'),
    ('gemini', 'gemini_generate_content'),
    ('anthropic', 'anthropic_messages'),
])
def test_selected_backend_keeps_only_marker_and_signed_model(
        service, tmp_path, monkeypatch, kind, mode):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    svc, profile, hooks, _ = service
    svc, _, _, _ = _bind_real_kernel(service, tmp_path)
    svc.audit = SimpleNamespace(log=lambda _event: None)
    profile = replace(profile, backend_kind=kind, api_mode=mode, auth_type='bearer',
                      fallback_models=('synthetic-model',))
    artifact = svc.stage('addon', profile=profile, hooks=hooks, source='user', actor=owner())
    offer = svc.propose(artifact['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=artifact['artifact_id'],
               package_hash=artifact['package_hash'], approved=True, permanent=True,
               actor=owner())
    svc.promote(offer['proposal_id'], actor=owner())
    key = 'synthetic-key-never-in-backend'
    svc.put_credential('synthetic-addon', artifact['package_hash'], key, actor=owner())
    from agents.core.llm.provider_selection import current_revision
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
                        expected_revision=current_revision(), acknowledge_unknown_price=True,
                        acknowledge_data_policy=True, actor=owner())
    runtime = svc.selected_runtime()
    backend = construct_selected_backend(runtime)
    assert backend.profile is runtime.profile
    assert backend.api_key == AUTH_MARKER
    assert backend.client._transport.selected is runtime
    assert key not in str(vars(backend))
    from agents.core.llm.backend_factory import BackendUnavailable, construct_backend
    from agents.core.llm.providers.hook_runtime import ProviderHookRuntimeError
    from agents.core.llm.providers.native_transport import native_admitted_client

    with pytest.raises(BackendUnavailable):
        construct_backend('synthetic-addon', registry=runtime.registry,
                          model='synthetic-model', api_key=key)
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        native_admitted_client(runtime.profile, key, 'synthetic-model',
                               inner=httpx.MockTransport(lambda _: httpx.Response(200)))


@pytest.mark.asyncio
@pytest.mark.parametrize(('kind', 'mode', 'native'), [
    ('openai-compatible', 'chat_completions', 'deepinfra'),
    ('deepinfra-chat', 'chat_completions', 'deepinfra'),
    ('openai-responses', 'responses', 'openai-responses'),
    ('xai-responses', 'responses', 'xai'),
    ('gemini', 'gemini_generate_content', 'gemini'),
    ('anthropic', 'anthropic_messages', 'anthropic'),
])
async def test_selected_signed_worker_reaches_one_pinned_wire_attempt(
        service, tmp_path, monkeypatch, kind, mode, native):
    from agents.core.llm import data_handling, provider_selection
    from agents.core.llm.providers import lifecycle_gates, selected_runtime
    from agents.core.llm.providers.admitted_profiles import prepare_admitted_profile
    from agents.core.llm.providers.hook_runtime import ProviderHookRuntimeError
    from agents.core.llm.providers.native_transport import native_stream
    from agents.core.llm.providers.packages import ProviderPackageError

    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(selected_runtime, 'resolve_and_validate',
                        lambda host, mode: (['93.184.216.34'], None))
    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'x' * 32)
    svc, profile, hooks, _ = service
    svc, _, _, seen = _bind_real_kernel(service, tmp_path)
    svc.audit = SimpleNamespace(log=lambda _event: None)
    profile = replace(profile, backend_kind=kind, api_mode=mode, auth_type='bearer',
                      fallback_models=('synthetic-model',))
    artifact = svc.stage('addon', profile=profile, hooks=hooks, source='user', actor=owner())
    offer = svc.propose(artifact['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=artifact['artifact_id'],
               package_hash=artifact['package_hash'], approved=True, permanent=True,
               actor=owner())
    svc.promote(offer['proposal_id'], actor=owner())
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-wire-secret', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
                        expected_revision=provider_selection.current_revision(),
                        acknowledge_unknown_price=True, acknowledge_data_policy=True,
                        actor=owner())
    runtime = svc.selected_runtime()
    backend = construct_selected_backend(runtime)
    router = SimpleNamespace(_data_handling_used={})
    runtime.bind_backend(backend, router)
    wire = []

    def handler(request):
        wire.append((str(request.url), request.headers.get('host'),
                     request.headers.get('authorization') or request.headers.get('x-api-key')
                     or request.headers.get('x-goog-api-key'),
                     request.extensions.get('sni_hostname')))
        if kind == 'openai-compatible':
            return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
        return response(native, 'text')

    backend.client._transport.inner = httpx.MockTransport(handler)
    try:
        with physical_request_scope(lambda: None):
            assert await backend.generate('synthetic-model', 'hello') == 'ok'
        assert len(wire) == 1
        assert wire[0][0].startswith('https://93.184.216.34/v1/')
        assert wire[0][1] == 'synthetic.invalid'
        assert wire[0][2] in {'synthetic-wire-secret', 'Bearer synthetic-wire-secret'}
        assert wire[0][3] == 'synthetic.invalid'
        assert sum(action.kind == 'plugin.egress' for action, _ in seen) == 1
        if kind == 'openai-compatible':
            prepared = await prepare_admitted_profile(
                backend.profile, model='synthetic-model',
                messages=[{'role': 'user', 'content': 'held body'}])
            with physical_request_scope(lambda: None):
                async with native_stream(
                        backend.profile, prepared, backend.client, 'POST',
                        '/chat/completions',
                        headers={'Authorization': 'Bearer ' + AUTH_MARKER},
                        json={'model': 'synthetic-model', 'messages': []}) as held:
                    assert held.status_code == 200
                    with pytest.raises(ProviderPackageError, match='lifecycle lease busy'):
                        svc.put_credential('synthetic-addon', artifact['package_hash'],
                                           'replacement-synthetic-key', actor=owner())
                    await lifecycle_gates.drain(svc.root, 'synthetic-addon')
                assert len(wire) == 2
            svc.put_credential('synthetic-addon', artifact['package_hash'],
                               'replacement-synthetic-key', actor=owner())
            with physical_request_scope(lambda: None), pytest.raises(
                    ProviderHookRuntimeError, match='native_egress_unavailable'):
                await backend.generate('synthetic-model', 'stale key')
            assert len(wire) == 2
    finally:
        await backend.client.aclose()
