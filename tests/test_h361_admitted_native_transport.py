"""Synthetic physical-send accounting and authority checks for native dialects."""
import asyncio
import json
import multiprocessing
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import fields, replace
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.kernel import Verdict
from agents.core.llm.data_handling import physical_request_scope
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.providers.admitted_profiles import (
    AdmittedProviderProfile,
    prepare_admitted_profile,
)
from agents.core.llm.providers.hook_runtime import ProviderHookRuntimeError
from agents.core.llm.providers.native_transport import (
    _attempt_scope,
    native_admitted_client,
    native_post,
)
from agents.core.llm.providers.packages import ProviderPackageError, ProviderPackageStore
from agents.core.llm.providers.selected_runtime import AUTH_MARKER, construction_scope
from agents.core.llm.quota import ProviderRateLimited
from agents.core.observability.egress_monitor import EgressMonitor
from agents.core.turn_usage import turn_usage_scope
from tests.test_h361_provider_install_service import owner

CASES = (
    ('anthropic', 'anthropic_messages', 'https://api.anthropic.com/v1', '/messages', 'x-api-key'),
    ('gemini', 'gemini_generate_content', 'https://generativelanguage.googleapis.com/v1beta',
     '/models/m:generateContent', 'x-goog-api-key'),
    ('deepinfra-chat', 'chat_completions', 'https://api.deepinfra.com/v1/openai',
     '/chat/completions', 'authorization'),
    ('openai-responses', 'responses', 'https://api.openai.com/v1', '/responses', 'authorization'),
    ('xai-responses', 'responses', 'https://api.x.ai/v1', '/responses', 'authorization'),
    ('openai-compatible', 'chat_completions', 'https://synthetic.invalid/v1',
     '/chat/completions', 'authorization'),
)


@pytest.fixture(autouse=True)
def selected_test_environment(tmp_path, monkeypatch):
    from agents.core.llm import data_handling
    from agents.core.llm.providers import selected_runtime

    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(selected_runtime, 'resolve_and_validate',
                        lambda host, mode: (['93.184.216.34'], None))
    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'x' * 32)


def client_for(tmp_path, case, handler):
    """Real signed owner/Kernel/Vault selection; only DNS and HTTP are synthetic."""
    from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
    from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
    from agents.core.llm.provider_selection import current_revision
    from agents.core.llm.providers.install_service import ProviderInstallService
    from tests.test_h361_provider_hook_runtime import IMAGE, SimulatedSealedRunner
    from tests.test_h361_provider_install_kernel import _bind_real_kernel
    from tests.test_h361_provider_install_service import owner

    kind, mode, base, suffix, auth = case
    identity = 'admitted-' + kind
    root = tmp_path / ('selected-' + kind)
    signing = ManagedSigningKeyStore(root / 'signing')
    signing.provision(key_id='synthetic-transport', version=1, key=b'x' * 32)
    service = ProviderInstallService(
        root=root / 'service', signing=signing,
        profile=AcquisitionSandboxProfile(image=IMAGE, uid=os.getuid(), gid=os.getgid()),
        kernel=lambda: None, enabled=lambda: True, home='synthetic-home',
        runner=SimulatedSealedRunner(), audit=SimpleNamespace(log=lambda _event: None))
    service, _orch, _kill, _seen = _bind_real_kernel((service, None, None, None), root)
    source = service.incoming('user') / 'addon'
    source.mkdir(parents=True)
    (source / 'provider.json').write_text(json.dumps(
        {'schema_version': 1, 'id': identity, 'aliases': []}))
    hooks = ('prepare_messages', 'build_extra_body', 'build_api_kwargs_extras')
    (source / 'main.py').write_text(
        'def register_provider():\n    return ' + repr({'id': identity, 'hooks': list(hooks)}) + '\n'
        'def prepare_messages(messages):\n    return messages\n'
        'def build_extra_body(**kwargs):\n    return {}\n'
        'def build_api_kwargs_extras(**kwargs):\n    return {}, {}\n')
    profile = ProviderProfile(identity, 'Native fixture', kind, api_mode=mode,
        auth_type='bearer', default_base_url=base,
        capabilities=frozenset({'chat', 'cloud'}), fallback_models=('m',),
        default_max_tokens=64, is_user_defined=True)
    artifact = service.stage('addon', profile=profile, hooks=hooks, source='user', actor=owner())
    offer = service.propose(artifact['artifact_id'], actor=owner())
    service.decide(offer['proposal_id'], artifact_id=artifact['artifact_id'],
                   package_hash=artifact['package_hash'], approved=True, permanent=True,
                   actor=owner())
    service.promote(offer['proposal_id'], actor=owner())
    service.put_credential(identity, artifact['package_hash'], 'host-secret', actor=owner())
    service.select_provider(identity, artifact['package_hash'], 'm',
        expected_revision=current_revision(), acknowledge_unknown_price=True,
        acknowledge_data_policy=True, actor=owner())
    runtime = service.selected_runtime()
    fake_backend = SimpleNamespace(profile=runtime.profile, _selected_provider_runtime=runtime)
    runtime.bind_backend(fake_backend, SimpleNamespace(_data_handling_used={}))
    with construction_scope(runtime):
        client = native_admitted_client(runtime.profile, AUTH_MARKER, 'm',
                                        inner=httpx.MockTransport(handler))
    calls = []
    store = runtime.profile._hook_runtime.packages
    authorize = store.authorizer

    def record_action(action):
        if action.kind == 'plugin.egress':
            calls.append(action)
        return authorize(action)

    store.authorizer = record_action
    client._selected_test_service = service
    headers = {auth: AUTH_MARKER if auth != 'authorization' else 'Bearer ' + AUTH_MARKER}
    return client, base + suffix, headers, calls


def _hold_selected_leases(db_path, root, provider, conn):
    from pathlib import Path

    from agents.core import settings_db
    from agents.core.llm.providers import lifecycle_gates, selection_gates

    settings_db.DB_PATH = Path(db_path)
    selection = selection_gates.acquire_shared(db_path)
    lifecycle = lifecycle_gates.acquire(root, provider, exclusive=False)
    try:
        conn.send('held')
        conn.recv()
    finally:
        lifecycle.close()
        selection.close()
        conn.close()


async def prepared_post(client, url, headers, body):
    profile = client._transport.profile
    prepared = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'signed fixture'}])
    with physical_request_scope(lambda: None):
        return await native_post(profile, prepared, client, url, headers=headers, json=body)


async def prepared_open_stream(client, url, headers, body):
    profile = client._transport.profile
    prepared = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'signed stream fixture'}])
    with physical_request_scope(lambda: None), _attempt_scope(
            profile, prepared, client, 'POST', url, headers=headers, json_body=body):
        request = client.build_request('POST', url, headers=headers, json=body)
        return await client.send(request, stream=True)


class BlockingBody(httpx.AsyncByteStream):
    def __init__(self):
        self.entered = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        self.entered.set()
        await asyncio.Future()
        yield b''

    async def aclose(self):
        self.closed = True


class FiniteBody(httpx.AsyncByteStream):
    def __init__(self, *, fail=False):
        self.fail = fail
        self.closed = False

    async def __aiter__(self):
        yield b'first'
        if self.fail:
            raise RuntimeError('synthetic body failure')
        yield b'second'

    async def aclose(self):
        self.closed = True


class CrossLoopBody(httpx.AsyncByteStream):
    def __init__(self):
        self.entered = threading.Event()
        self.closed = threading.Event()

    async def __aiter__(self):
        self.entered.set()
        await asyncio.Future()
        yield b''

    async def aclose(self):
        self.closed.set()


class BlockedCloseBody(httpx.AsyncByteStream):
    def __init__(self):
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()
        self.close_done = False

    async def __aiter__(self):
        yield b'unused'

    async def aclose(self):
        self.close_started.set()
        await self.release_close.wait()
        self.close_done = True


class LoopAffineBody(CrossLoopBody):
    def __init__(self):
        super().__init__()
        self.origin = asyncio.get_running_loop()

    async def aclose(self):
        assert asyncio.get_running_loop() is self.origin, 'wrong event loop for underlying close'
        await super().aclose()


class FailingCloseBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'unused'

    async def aclose(self):
        raise RuntimeError('synthetic close failure')


@pytest.mark.asyncio
async def test_native_direct_and_changed_or_replayed_attempts_refuse_before_transport(tmp_path):
    seen = []
    client, url, headers, actions = client_for(
        tmp_path, CASES[0], lambda request: seen.append(request) or httpx.Response(200))
    body = {'model': 'm', 'messages': [{'role': 'user', 'content': 'prepared'}]}
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        await client.post(url, headers=headers, json=body)
    assert not seen and not actions

    profile = client._transport.profile
    prepared = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'prepared'}])
    with physical_request_scope(lambda: None), _attempt_scope(
            profile, prepared, client, 'POST', url, headers=headers, json_body=body):
        with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
            await client.post(url, headers=headers, json={**body, 'messages': []})
        with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
            await asyncio.create_task(client.post(url, headers=headers, json=body))
        assert (await client.post(url, headers=headers, json=body)).status_code == 200
        with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
            await client.post(url, headers=headers, json=body)
    assert len(seen) == len(actions) == 1
    with physical_request_scope(lambda: None):
        assert (await native_post(profile, prepared, client, url,
                                  headers=headers, json=body)).status_code == 200
    assert len(seen) == len(actions) == 2
    newest = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'newer batch'}])
    with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
        await native_post(profile, prepared, client, url, headers=headers, json=body)
    with physical_request_scope(lambda: None):
        assert (await native_post(profile, newest, client, url,
                                  headers=headers, json=body)).status_code == 200
    assert len(seen) == len(actions) == 3
    assert (await prepared_post(client, url, headers, body)).status_code == 200
    assert len(seen) == len(actions) == 4
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
async def test_native_guard_records_one_physical_attempt_per_dialect(tmp_path, case, monkeypatch):
    from agents.core.llm import egress
    monitor = EgressMonitor()
    monkeypatch.setattr(egress, 'EGRESS_MONITOR', monitor)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'ok': True})

    client, url, headers, actions = client_for(tmp_path, case, handler)
    with turn_usage_scope() as usage:
        response = await prepared_post(client, url, headers, {'model': 'm'})
    assert usage.snapshot()['api_calls'] == 1
    assert response.status_code == 200
    assert len(seen) == 1
    assert len(actions) == 1 and actions[0].kind == 'plugin.egress'
    rows = monitor.snapshot('llm:admitted-' + case[0])['recent']
    assert len(rows) == 1 and rows[0]['allowed'] is True
    assert 'host-secret' not in repr(response) and 'host-secret' not in repr(seen)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
async def test_selected_retry_prepares_a_fresh_ticket_and_counts_each_wire_attempt(tmp_path, case):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(200, json={'ok': True})

    client, url, headers, actions = client_for(tmp_path, case, handler)
    with turn_usage_scope() as usage:
        first = await prepared_post(client, url, headers, {'model': 'm'})
        assert first.status_code == 503
        second = await prepared_post(client, url, headers, {'model': 'm'})
        assert second.status_code == 200
    assert len(seen) == len(actions) == usage.snapshot()['api_calls'] == 2
    assert all(action.kind == 'plugin.egress' for action in actions)
    assert all('host-secret' not in repr(action) for action in actions)
    await client.aclose()


@pytest.mark.asyncio
async def test_native_egress_action_matches_manifest_and_real_kernel_refusals(tmp_path):
    from copy import deepcopy

    from agents.core.action_origin import bind_action_origin, reset_action_origin
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.capability_manifests import manifest_for_action
    from agents.core.kernel import authorize

    seen = []
    client, url, headers, actions = client_for(
        tmp_path, CASES[0], lambda request: (seen.append(request) or httpx.Response(200)))
    def owner_bound_authorize(action):
        actions.append(action)
        snapshot = deepcopy(action)
        return authorize(action, policy=AutonomyPolicy(mode='ask'),
                         approval_check=lambda candidate: candidate == snapshot)

    store = client._transport.profile._hook_runtime.packages
    original_authorizer = store.authorizer
    store.authorizer = lambda action: (owner_bound_authorize(action)
                                       if action.kind == 'plugin.egress'
                                       else original_authorizer(action))
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        await prepared_post(client, url, headers, {'model': 'm'})
    assert not seen
    assert len(actions) == 1
    action = actions[0]
    required = manifest_for_action('plugin.egress').inputs['required']
    assert all(key in action.payload for key in required)
    assert action.payload['plugin'] == client._transport.profile.id
    assert action.payload['url'] == url
    assert action.payload['risk_tier'] == 3
    for field, changed in [('schema', 'forged'), ('receipt_id', 'bad'),
                           ('url', 'https://elsewhere.invalid/v1/messages')]:
        forged = replace(action, payload={**action.payload, field: changed})
        assert authorize(forged, policy=AutonomyPolicy(),
                         approval_check=lambda candidate, expected=forged:
                             candidate == expected).verdict is Verdict.QUEUE
    store.authorizer = lambda action: (
        actions.append(action) or authorize(action, policy=AutonomyPolicy(),
                                            kill_switch=SimpleNamespace(is_halted=lambda scope: True))
        if action.kind == 'plugin.egress' else original_authorizer(action))
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        await prepared_post(client, url, headers, {'model': 'm'})
    assert not seen and len(actions) == 2
    store.authorizer = lambda action: (
        actions.append(action) or authorize(action, policy=AutonomyPolicy(),
                                            approval_check=lambda candidate: candidate == action)
        if action.kind == 'plugin.egress' else original_authorizer(action))
    token = bind_action_origin('inbound')
    try:
        with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
            await prepared_post(client, url, headers, {'model': 'm'})
    finally:
        reset_action_origin(token)
    assert not seen and len(actions) == 3 and actions[-1].origin == 'inbound'
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['path', 'query', 'auth', 'model', 'redirect', 'timeout'])
async def test_native_guard_refuses_mutations_and_counts_ambiguous_attempt(tmp_path, mutation, monkeypatch):
    from agents.core.llm import egress
    monitor = EgressMonitor()
    monkeypatch.setattr(egress, 'EGRESS_MONITOR', monitor)
    seen = []

    def handler(request):
        seen.append(request)
        if mutation == 'timeout':
            raise httpx.ReadTimeout('synthetic after entry')
        if mutation == 'redirect':
            return httpx.Response(302, headers={'Location': 'https://elsewhere.invalid/'})
        return httpx.Response(200)

    client, url, headers, actions = client_for(tmp_path, CASES[0], handler)
    body = {'model': 'm'}
    if mutation == 'path':
        url += '/alternate'
    if mutation == 'query':
        url += '?alt=1'
    if mutation == 'auth':
        headers['x-api-key'] = 'different'
    if mutation == 'model':
        body['model'] = 'different'
    with turn_usage_scope() as usage:
        if mutation in {'path', 'query', 'auth', 'model', 'redirect'}:
            with pytest.raises(ProviderHookRuntimeError):
                await prepared_post(client, url, headers, body)
        else:
            with pytest.raises(httpx.ReadTimeout):
                await prepared_post(client, url, headers, body)
    assert usage.snapshot()['api_calls'] == int(mutation in {'redirect', 'timeout'})
    assert len(seen) == int(mutation in {'redirect', 'timeout'})
    assert len(actions) == int(mutation in {'redirect', 'timeout'})
    rows = monitor.snapshot('llm:admitted-anthropic')['recent']
    assert len(rows) == 1
    assert rows[0]['allowed'] is (mutation in {'redirect', 'timeout'})
    assert ('possibly sent' in rows[0]['reason']) is (mutation in {'redirect', 'timeout'})
    await client.aclose()


@pytest.mark.asyncio
async def test_native_guard_cancellation_after_transport_entry_releases_lease(tmp_path, monkeypatch):
    from agents.core.llm import egress
    monitor = EgressMonitor()
    monkeypatch.setattr(egress, 'EGRESS_MONITOR', monitor)
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Future()

    client, url, headers, _ = client_for(tmp_path, CASES[0], handler)
    with turn_usage_scope() as usage:
        task = asyncio.create_task(prepared_post(client, url, headers, {'model': 'm'}))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert usage.snapshot()['api_calls'] == 1
    rows = monitor.snapshot('llm:admitted-anthropic')['recent']
    assert len(rows) == 1 and rows[0]['allowed'] is True
    assert 'possibly sent' in rows[0]['reason']
    await client.aclose()


@pytest.mark.asyncio
async def test_native_guard_async_revoke_cancels_inflight_and_blocks_later_send(tmp_path):
    entered = asyncio.Event()
    seen = []

    async def handler(request):
        seen.append(request)
        entered.set()
        await asyncio.Future()

    client, url, headers, _ = client_for(tmp_path, CASES[0], handler)
    store = client._transport.profile._hook_runtime.packages
    first = asyncio.create_task(prepared_post(client, url, headers, {'model': 'm'}))
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(store.revoke_async('admitted-anthropic'), 1)
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
        await prepared_post(client, url, headers, {'model': 'm'})
    assert len(seen) == 1
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('alias_root', [False, True])
async def test_revoke_stops_transferred_body_reader_after_headers(tmp_path, alias_root):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    body = BlockingBody()
    seen = []
    client, url, headers, actions = client_for(
        tmp_path, CASES[0], lambda request: seen.append(request) or
        httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    assert response.status_code == 200 and len(seen) == len(actions) == 1

    async def consume():
        async for _ in response.aiter_bytes():
            pass

    reader = asyncio.create_task(consume())
    await asyncio.wait_for(body.entered.wait(), 1)
    if not alias_root:
        from agents.core.llm.providers.selection_gates import SelectionBusy
        with pytest.raises(SelectionBusy):
            client._selected_test_service.clear_selection(
                expected_revision=client._transport.selected.selection.revision,
                actor=__import__('tests.test_h361_provider_install_service',
                                 fromlist=['owner']).owner())
    store = client._transport.profile._hook_runtime.packages
    revoker = store
    if alias_root:
        revoker = object.__new__(ProviderPackageStore)
        revoker._root_identity = store._root_identity
        revoker.revoke = store.revoke
    await asyncio.wait_for(revoker.revoke_async('admitted-anthropic'), 1)
    assert reader.done() and body.closed
    with pytest.raises(asyncio.CancelledError):
        await reader
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
        await prepared_post(client, url, headers, {'model': 'm'})
    assert len(seen) == len(actions) == 1
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['normal', 'error', 'cancel'])
async def test_tracked_body_cleans_up_on_completion_error_or_cancel(tmp_path, mode):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    body = BlockingBody() if mode == 'cancel' else FiniteBody(fail=mode == 'error')
    client, url, headers, actions = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    with turn_usage_scope() as usage:
        response = await prepared_open_stream(client, url, headers, {'model': 'm'})
        if mode == 'normal':
            assert await response.aread() == b'firstsecond'
        elif mode == 'error':
            with pytest.raises(RuntimeError, match='synthetic body failure'):
                await response.aread()
        else:
            reader = asyncio.create_task(response.aread())
            await asyncio.wait_for(body.entered.wait(), 1)
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader
    assert usage.snapshot()['api_calls'] == 1
    assert body.closed and len(actions) == 1
    store = client._transport.profile._hook_runtime.packages
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    await client.aclose()


@pytest.mark.asyncio
async def test_client_close_releases_unread_response_body(tmp_path):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    body = BlockingBody()
    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    store = client._transport.profile._hook_runtime.packages
    assert _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    await client.aclose()
    assert body.closed
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    with pytest.raises(ProviderPackageError):
        await response.aread()


@pytest.mark.asyncio
async def test_owner_routes_check_live_actor_before_draining_selected_body(tmp_path, monkeypatch):
    from agents.core.routers import models_llm, provider_credentials, provider_selection

    body = BlockingBody()
    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda _request: httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    service = client._selected_test_service
    revision = client._transport.selected.selection.revision
    monkeypatch.setattr(models_llm, '_provider_install_context',
                        lambda _request: (service, owner(lambda: False)))
    refused_clear = await provider_selection._call(
        object(), 'clear_selection', {'expected_revision': revision})
    refused_key = await provider_credentials._call(
        object(), 'delete_credential', 'admitted-anthropic',
        client._transport.profile._package_hash)
    assert refused_clear.status_code == refused_key.status_code == 409
    assert not body.closed
    monkeypatch.setattr(models_llm, '_provider_install_context',
                        lambda _request: (service, owner()))
    cleared = await provider_selection._call(
        object(), 'clear_selection', {'expected_revision': revision})
    assert cleared.status_code == 200 and body.closed
    with pytest.raises(ProviderPackageError):
        await response.aread()
    await client.aclose()


def test_cross_process_body_leases_refuse_all_owner_mutations_without_partial_state(tmp_path):
    from agents.core.llm import provider_selection
    from agents.core.llm.providers.lifecycle_gates import LifecycleBusy
    from agents.core.llm.providers.selection_gates import SelectionBusy

    client, _url, _headers, _ = client_for(
        tmp_path, CASES[0], lambda _request: httpx.Response(200))
    service = client._selected_test_service
    revision = provider_selection.current_revision()
    target = ('admitted-anthropic', client._transport.profile._package_hash)
    ctx = multiprocessing.get_context('spawn')
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_hold_selected_leases,
                          args=(str(settings_db.DB_PATH), str(service.root), target[0], child))
    process.start()
    try:
        assert parent.poll(5) and parent.recv() == 'held'
        with pytest.raises(LifecycleBusy):
            service.put_credential(*target, 'rotated-key', actor=owner())
        with pytest.raises(LifecycleBusy):
            service.revoke(target[0], actor=owner())
        with pytest.raises(SelectionBusy):
            service.clear_selection(expected_revision=revision, actor=owner())
        assert service.credential_status(*target, actor=owner())['generation'] == 1
        assert provider_selection.current_revision() == revision
        assert service._store().require_runnable(target[0], expected_hash=target[1],
                                                home=service.home)
    finally:
        parent.send('release')
        process.join(5)
        assert process.exitcode == 0


@pytest.mark.asyncio
async def test_client_close_stops_active_reader_before_unregistration(tmp_path):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    body = BlockingBody()
    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    reader = asyncio.create_task(response.aread())
    await asyncio.wait_for(body.entered.wait(), 1)
    store = client._transport.profile._hook_runtime.packages
    await asyncio.wait_for(client.aclose(), 1)
    assert reader.done() and body.closed
    with pytest.raises(asyncio.CancelledError):
        await reader
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')


@pytest.mark.asyncio
async def test_concurrent_reader_finalizers_do_not_wait_on_each_other(tmp_path):
    body = BlockingBody()
    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    stream = response.stream._stream

    async def consume():
        async for _ in stream:
            pass

    readers = [asyncio.create_task(consume()) for _ in range(2)]
    await asyncio.wait_for(body.entered.wait(), 1)
    for _ in range(100):
        if len(stream.inner.tasks) == 2:
            break
        await asyncio.sleep(0.001)
    assert len(stream.inner.tasks) == 2
    for reader in readers:
        reader.cancel()
    results = await asyncio.wait_for(asyncio.gather(*readers, return_exceptions=True), 1)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert body.closed
    await client.aclose()


@pytest.mark.asyncio
async def test_external_close_and_revoke_drain_concurrent_finalizers(tmp_path):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    body = BlockingBody()
    client, url, headers, actions = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    stream = response.stream._stream

    async def consume():
        async for _ in stream:
            pass

    readers = [asyncio.create_task(consume()) for _ in range(2)]
    await asyncio.wait_for(body.entered.wait(), 1)
    for _ in range(100):
        if len(stream.inner.tasks) == 2:
            break
        await asyncio.sleep(0.001)
    assert len(stream.inner.tasks) == 2
    store = client._transport.profile._hook_runtime.packages
    await asyncio.wait_for(asyncio.gather(
        asyncio.create_task(client.aclose()),
        asyncio.create_task(store.revoke_async('admitted-anthropic'))), 1)
    results = await asyncio.gather(*readers, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert body.closed and len(actions) == 1 and not stream.inner.tasks
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')


@pytest.mark.asyncio
async def test_revoke_between_headers_and_first_body_read_refuses_reader(tmp_path):
    body = BlockingBody()
    seen = []
    client, url, headers, actions = client_for(
        tmp_path, CASES[0], lambda request: seen.append(request) or
        httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    store = client._transport.profile._hook_runtime.packages
    await asyncio.wait_for(store.revoke_async('admitted-anthropic'), 1)
    with pytest.raises(ProviderPackageError):
        await response.aread()
    assert len(seen) == len(actions) == 1 and not body.entered.is_set()
    await client.aclose()
    assert body.closed


@pytest.mark.asyncio
async def test_revoke_waits_for_unread_body_close_completion(tmp_path):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    body = BlockedCloseBody()
    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    store = client._transport.profile._hook_runtime.packages
    revoker = asyncio.create_task(store.revoke_async('admitted-anthropic'))
    try:
        await asyncio.wait_for(body.close_started.wait(), 1)
        assert not revoker.done() and not body.close_done
        assert _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    finally:
        body.release_close.set()
    await asyncio.wait_for(revoker, 1)
    assert body.close_done
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    with pytest.raises(ProviderPackageError):
        await response.aread()
    await client.aclose()


@pytest.mark.asyncio
async def test_cancelled_revoke_drains_unread_close_before_return(tmp_path):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    body = BlockedCloseBody()
    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    await prepared_open_stream(client, url, headers, {'model': 'm'})
    store = client._transport.profile._hook_runtime.packages
    revoker = asyncio.create_task(store.revoke_async('admitted-anthropic'))
    await asyncio.wait_for(body.close_started.wait(), 1)
    revoker.cancel()
    await asyncio.sleep(0)
    assert not revoker.done() and not body.close_done
    body.release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(revoker, 1)
    assert body.close_done
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    await client.aclose()


@pytest.mark.asyncio
async def test_revoke_surfaces_failed_underlying_close(tmp_path):
    from agents.core.llm.providers.packages import _DISPATCH_READERS

    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=FailingCloseBody()))
    await prepared_open_stream(client, url, headers, {'model': 'm'})
    store = client._transport.profile._hook_runtime.packages
    with pytest.raises(RuntimeError, match='synthetic close failure'):
        await asyncio.wait_for(store.revoke_async('admitted-anthropic'), 1)
    with pytest.raises(ProviderPackageError):
        store.require_runnable('admitted-anthropic', home='synthetic-home')
    assert _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    with pytest.raises(RuntimeError, match='synthetic close failure'):
        await client.aclose()


@pytest.mark.asyncio
async def test_revoke_waits_for_reader_transferred_to_another_event_loop(tmp_path):
    body = LoopAffineBody()
    client, url, headers, actions = client_for(
        tmp_path, CASES[0], lambda request: httpx.Response(200, stream=body))
    response = await prepared_open_stream(client, url, headers, {'model': 'm'})
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    remote = asyncio.run_coroutine_threadsafe(response.aread(), loop)
    try:
        assert await asyncio.to_thread(body.entered.wait, 1)
        store = client._transport.profile._hook_runtime.packages
        await asyncio.wait_for(store.revoke_async('admitted-anthropic'), 1)
        assert remote.done() and body.closed.is_set() and len(actions) == 1
    finally:
        remote.cancel()
        loop.call_soon_threadsafe(loop.stop)
        await asyncio.to_thread(thread.join, 1)
        loop.close()
        await client.aclose()


@pytest.mark.asyncio
async def test_revoke_reconciles_body_registered_after_both_snapshots(tmp_path):
    from agents.core.llm.providers.packages import (
        _DISPATCH_GUARD,
        _DISPATCH_READERS,
        _DISPATCH_TASKS,
    )

    body = BlockingBody()
    handler_entered = asyncio.Event()
    snapshots_done = threading.Event()
    seen = []

    async def handler(request):
        seen.append(request)
        handler_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            assert await asyncio.to_thread(snapshots_done.wait, 1)
            return httpx.Response(200, stream=body)

    client, url, headers, actions = client_for(tmp_path, CASES[0], handler)
    store = client._transport.profile._hook_runtime.packages

    def revoke(provider_id):
        with _DISPATCH_GUARD:
            assert not _DISPATCH_READERS.get(store._root_identity, {}).get(provider_id)
        snapshots_done.set()
        with store._locked():
            deadline = time.monotonic() + 1
            while not body.entered.is_set() and time.monotonic() < deadline:
                time.sleep(0.001)
            assert body.entered.is_set()
            store.revoked = True

    store.revoke = revoke

    async def send_and_read():
        response = await prepared_open_stream(client, url, headers, {'model': 'm'})
        await response.aread()

    send = asyncio.create_task(send_and_read())
    await asyncio.wait_for(handler_entered.wait(), 1)
    await asyncio.wait_for(store.revoke_async('admitted-anthropic'), 1)
    assert snapshots_done.is_set() and body.closed and len(seen) == len(actions) == 1
    assert send.done()
    with pytest.raises(asyncio.CancelledError):
        await send
    assert not _DISPATCH_READERS.get(store._root_identity, {}).get('admitted-anthropic')
    assert not _DISPATCH_TASKS.get(store._root_identity, {}).get('admitted-anthropic')
    await client.aclose()


@pytest.mark.asyncio
async def test_native_quota_refusal_records_blocked_without_dispatch(tmp_path, monkeypatch):
    from agents.core.llm import egress, quota

    monitor = EgressMonitor()
    monkeypatch.setattr(egress, 'EGRESS_MONITOR', monitor)

    class Held:
        def blocked_until(self, *_args, **_kwargs):
            return time.time() + 60

    monkeypatch.setattr(quota, 'get_store', lambda: Held())
    seen = []
    client, url, headers, _ = client_for(
        tmp_path, CASES[0], lambda request: seen.append(request) or httpx.Response(200))
    with turn_usage_scope() as usage, pytest.raises(ProviderRateLimited):
        await prepared_post(client, url, headers, {'model': 'm'})
    assert seen == [] and usage.snapshot()['api_calls'] == 0
    rows = monitor.snapshot('llm:admitted-anthropic')['recent']
    assert len(rows) == 1 and rows[0]['allowed'] is False
    await client.aclose()
