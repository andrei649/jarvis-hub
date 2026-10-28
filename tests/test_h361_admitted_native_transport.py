"""Synthetic physical-send accounting and authority checks for native dialects."""
import asyncio
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import fields, replace
from types import SimpleNamespace

import httpx
import pytest

from agents.core.kernel import Decision, Verdict
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
from agents.core.llm.quota import ProviderRateLimited
from agents.core.observability.egress_monitor import EgressMonitor
from agents.core.turn_usage import turn_usage_scope

CASES = (
    ('anthropic', 'anthropic_messages', 'https://api.anthropic.com/v1', '/messages', 'x-api-key'),
    ('gemini', 'gemini_generate_content', 'https://generativelanguage.googleapis.com/v1beta',
     '/models/m:generateContent', 'x-goog-api-key'),
    ('deepinfra-chat', 'chat_completions', 'https://api.deepinfra.com/v1/openai',
     '/chat/completions', 'authorization'),
    ('openai-responses', 'responses', 'https://api.openai.com/v1', '/responses', 'authorization'),
    ('xai-responses', 'responses', 'https://api.x.ai/v1', '/responses', 'authorization'),
)


def client_for(tmp_path, case, handler):
    kind, mode, base, suffix, auth = case
    store = object.__new__(ProviderPackageStore)
    store._lock_path = tmp_path / 'registry.lock'
    store._root_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    store.revoked = False
    record = None

    def require_record(provider_id, expected_hash, home):
        if store.revoked:
            raise ProviderPackageError('revoked')
        return record

    store._require_runnable_locked = require_record

    def revoke(provider_id):
        with store._locked():
            store.revoked = True

    store.revoke = revoke
    calls = []
    store.authorizer = lambda action: (calls.append(action) or Decision(Verdict.GRANT, tier=3))

    class Runtime:
        packages = store

        async def evaluate(self, provider_id, **kwargs):
            return {'prepared_messages': kwargs['messages'], 'extra_body': {},
                    'api_kwargs': {'extra_body': {}, 'kwargs': {}}, 'max_tokens': 64,
                    'reasoning_vocabulary': None}

        @asynccontextmanager
        async def dispatch_lease(self, provider_id, *, package_hash, home):
            async with store.dispatch_lease(provider_id, expected_hash=package_hash, home=home):
                yield

    profile = AdmittedProviderProfile(
        id='admitted-' + kind, display_name='Native fixture', backend_kind=kind,
        api_mode=mode, auth_type='bearer', default_base_url=base,
        capabilities=frozenset({'chat', 'cloud'}), fallback_models=('m',),
        _hook_runtime=Runtime(), _package_hash='f' * 64,
    )
    record = SimpleNamespace(
        provider_id=profile.id, artifact_id='a' * 32, package_hash=profile._package_hash,
        source='bundled', home=profile._home,
        profile=ProviderProfile(**{field.name: getattr(profile, field.name)
                                   for field in fields(ProviderProfile)}))
    client = native_admitted_client(profile, 'host-secret', 'm', inner=httpx.MockTransport(handler))
    headers = {auth: 'host-secret' if auth != 'authorization' else 'Bearer host-secret'}
    return client, base + suffix, headers, calls


async def prepared_post(client, url, headers, body):
    profile = client._transport.profile
    prepared = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'signed fixture'}])
    return await native_post(profile, prepared, client, url, headers=headers, json=body)


async def prepared_open_stream(client, url, headers, body):
    profile = client._transport.profile
    prepared = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'signed stream fixture'}])
    with _attempt_scope(profile, prepared, client, 'POST', url, headers=headers, json_body=body):
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
    with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
        await client.post(url, headers=headers, json=body)
    assert not seen and not actions

    profile = client._transport.profile
    prepared = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'prepared'}])
    with _attempt_scope(profile, prepared, client, 'POST', url, headers=headers, json_body=body):
        with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
            await client.post(url, headers=headers, json={**body, 'messages': []})
        with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
            await asyncio.create_task(client.post(url, headers=headers, json=body))
        assert (await client.post(url, headers=headers, json=body)).status_code == 200
        with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
            await client.post(url, headers=headers, json=body)
    assert len(seen) == len(actions) == 1
    assert (await native_post(profile, prepared, client, url,
                              headers=headers, json=body)).status_code == 200
    assert len(seen) == len(actions) == 2
    newest = await prepare_admitted_profile(
        profile, model='m', messages=[{'role': 'user', 'content': 'newer batch'}])
    with pytest.raises(ProviderHookRuntimeError, match='native_preparation_unavailable'):
        await native_post(profile, prepared, client, url, headers=headers, json=body)
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

    client._transport.profile._hook_runtime.packages.authorizer = owner_bound_authorize
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
    client._transport.profile._hook_runtime.packages.authorizer = lambda action: (
        actions.append(action) or authorize(action, policy=AutonomyPolicy(),
                                            kill_switch=SimpleNamespace(is_halted=lambda scope: True)))
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        await prepared_post(client, url, headers, {'model': 'm'})
    assert not seen and len(actions) == 2
    client._transport.profile._hook_runtime.packages.authorizer = lambda action: (
        actions.append(action) or authorize(action, policy=AutonomyPolicy(),
                                            approval_check=lambda candidate: candidate == action))
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
    with pytest.raises(ProviderPackageError):
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
        other, other_url, other_headers, other_actions = client_for(
            tmp_path, CASES[1], lambda request: httpx.Response(200, json={'ok': True}))
        assert (await prepared_post(other, other_url, other_headers, {'model': 'm'})).status_code == 200
        assert len(other_actions) == 1
        await other.aclose()
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
    with pytest.raises(ProviderPackageError):
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
        if len(stream.tasks) == 2:
            break
        await asyncio.sleep(0.001)
    assert len(stream.tasks) == 2
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
        if len(stream.tasks) == 2:
            break
        await asyncio.sleep(0.001)
    assert len(stream.tasks) == 2
    store = client._transport.profile._hook_runtime.packages
    await asyncio.wait_for(asyncio.gather(
        asyncio.create_task(client.aclose()),
        asyncio.create_task(store.revoke_async('admitted-anthropic'))), 1)
    results = await asyncio.gather(*readers, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert body.closed and len(actions) == 1 and not stream.tasks
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
    assert store.revoked
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
