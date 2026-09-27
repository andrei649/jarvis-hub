"""Composer policy uses the actual native wire, offline only."""
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from agents.core.commands import Principal
from agents.core.llm import vision_policy as vp
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client


@pytest.mark.asyncio
@pytest.mark.parametrize('key,scheme', [('', 'Basic'), ('synthetic-key', 'Bearer')])
async def test_composer_url_auth_precedence_and_warning(key, scheme):
    config = vlm.VLMConfig('custom', 'https://user:password@synthetic.invalid/v1?token=private', 'vision', key, False)
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'image'}}]})
    client = llm_async_client('vlm', base_url=config.base_url, transport=httpx.MockTransport(handle), auth=httpx.Auth())
    backend = vlm.VLMBackend(config.base_url, key, client=client, composer_auth=True)
    try:
        with vp.composer_request_scope(config, backend, resolve_config=lambda: config, remote_ack=True, principal=Principal(channel='web', admin=False)):
            assert await backend.generate_vision_checked('vision', 'question') == 'image'
        assert seen[0].headers['authorization'].split()[0] == scheme
        assert str(seen[0].url) == vp.describe(config).request_url
        assert vp.describe(config).warning
    finally:
        await backend.aclose()

@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['key', 'config_url', 'model', 'client_url', 'adapter_url', 'client_header'])
async def test_config_or_wire_change_before_physical_send_dispatches_nothing(change):
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', '', True)
    current = [config]
    seen = []

    async def mutate(request):
        if change == 'key':
            current[0] = replace(config, api_key='new-key')
        elif change == 'config_url':
            current[0] = replace(config, base_url='https://changed.invalid/v1', is_local=False)
        elif change == 'model':
            current[0] = replace(config, model='new-model')
        elif change == 'client_url':
            backend.client.base_url = 'https://changed.invalid/v1'
        elif change == 'adapter_url':
            backend.base_url = 'https://changed.invalid/v1'
        else:
            backend.client.headers['Authorization'] = 'Bearer unexpected'
    client = llm_async_client('vlm', base_url=config.base_url, auth=httpx.Auth(), event_hooks={'request': [mutate]}, transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)))
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)
    try:
        with pytest.raises(vp.VisionDestinationChanged), vp.composer_request_scope(config, backend, resolve_config=lambda: current[0], remote_ack=False, principal=Principal(channel='web')):
            await backend.generate_vision_checked('vision', 'question')
        assert not seen
    finally:
        await backend.aclose()

def test_request_identity_changes_and_pure_policy():
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', '', True)
    initial = vp.describe(config)
    assert initial.policy == 'local' and (not initial.warning)
    assert vp.describe(replace(config, base_url='https://synthetic.invalid/v1', is_local=False)).policy == 'unknown'
    assert vp.describe(replace(config, backend='custom')).policy == 'unknown'
    assert initial.binding != vp.describe(replace(config, api_key='changed')).binding
    assert 'password' not in repr(vp.describe(replace(config, base_url='https://user:password@synthetic.invalid/v1', is_local=False)))

def test_remote_ack_cannot_be_replaced_by_ambient_owner_or_provider_grant():
    config = vlm.VLMConfig('custom', 'https://synthetic.invalid/v1', 'vision', '', False)
    with pytest.raises(vp.VisionRemoteAckRequired), vp.composer_request_scope(config, SimpleNamespace(), resolve_config=lambda: config, remote_ack=False, principal=Principal(channel='web', admin=True)):
        pytest.fail('entered scope without acknowledgment')
    with pytest.raises(vp.VisionPolicyUnavailable), vp.composer_request_scope(config, SimpleNamespace(), resolve_config=lambda: config, remote_ack=True, principal=Principal(channel='internal', admin=True)):
        pytest.fail('unattended scope accepted')

@pytest.mark.asyncio
async def test_same_url_redirect_is_not_a_second_authorized_request():
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', '', True)
    seen = []

    def redirect(request):
        seen.append(request)
        return httpx.Response(307, headers={'Location': str(request.url)})
    client = llm_async_client('vlm', base_url=config.base_url, auth=httpx.Auth(), follow_redirects=True, transport=httpx.MockTransport(redirect))
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)
    try:
        with pytest.raises(vp.VisionDestinationChanged), vp.composer_request_scope(config, backend, resolve_config=lambda: config, remote_ack=False, principal=Principal(channel='web')):
            await backend.generate_vision_checked('vision', 'question')
        assert len(seen) == 1
    finally:
        await backend.aclose()

@pytest.mark.asyncio
async def test_waiting_send_rechecks_rotated_key_before_transport():
    import asyncio
    config = vlm.VLMConfig('custom', 'https://synthetic.invalid/v1', 'vision', 'old-key', False)
    current, seen = ([config], [])
    entered, release = (asyncio.Event(), asyncio.Event())

    async def wait(request):
        entered.set()
        await release.wait()
    client = llm_async_client('vlm', base_url=config.base_url, auth=httpx.Auth(), event_hooks={'request': [wait]}, transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)))
    backend = vlm.VLMBackend(config.base_url, config.api_key, client=client, composer_auth=True)

    async def generate():
        with vp.composer_request_scope(config, backend, resolve_config=lambda: current[0], remote_ack=True, principal=Principal(channel='web')):
            return await backend.generate_vision('vision', 'question')
    task = asyncio.create_task(generate())
    try:
        await entered.wait()
        current[0] = replace(config, api_key='new-key')
        release.set()
        with pytest.raises(vp.VisionDestinationChanged):
            await task
        assert not seen
    finally:
        release.set()
        await backend.aclose()

@pytest.mark.asyncio
async def test_selection_guard_cannot_be_overridden_by_remote_ack(monkeypatch):
    from agents.core.llm import selection_guards as sg
    config = vlm.VLMConfig('custom', 'https://synthetic.invalid/v1', 'gpt-4.1', '', False)
    monkeypatch.setattr(sg, '_cost_line', lambda: 1.0)
    client = llm_async_client('vlm', base_url=config.base_url, auth=httpx.Auth(), transport=httpx.MockTransport(lambda r: pytest.fail('selection-refused prompt sent')))
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)
    try:
        with pytest.raises(sg.SelectionRefused) as error, vp.composer_request_scope(config, backend, resolve_config=lambda: config, remote_ack=True, principal=Principal(channel='web', admin=True)):
            await backend.generate_vision_checked(config.model, 'question')
        assert error.value.payload()['needs'] == ['confirm_expensive']
    finally:
        await backend.aclose()

@pytest.mark.asyncio
async def test_wrong_payload_model_does_not_use_reviewed_model_grant():
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', '', True)
    client = llm_async_client('vlm', base_url=config.base_url, auth=httpx.Auth(), transport=httpx.MockTransport(lambda r: pytest.fail('wrong model sent')))
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)
    try:
        with pytest.raises(vp.VisionDestinationChanged), vp.composer_request_scope(config, backend, resolve_config=lambda: config, remote_ack=False, principal=Principal(channel='web')):
            await backend.generate_vision_checked('other-model', 'question')
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_concurrent_shared_client_scopes_and_closed_child_lifetime():
    import asyncio
    import contextvars

    from agents.core.llm.data_handling import DataHandlingRefused
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision-one', '', True)
    seen, entered = [], asyncio.Event()
    async def handle(request):
        import json
        seen.append(json.loads(request.content)['model'])
        if len(seen) == 2:
            entered.set()
        await entered.wait()
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
    client = llm_async_client('vlm', base_url=config.base_url, auth=httpx.Auth(), transport=httpx.MockTransport(handle))
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)
    async def turn(current):
        with vp.composer_request_scope(current, backend, resolve_config=lambda: current,
                                      remote_ack=False, principal=Principal(channel='web')):
            return await backend.generate_vision_checked(current.model, 'question')
    try:
        assert await asyncio.gather(turn(config), turn(replace(config, model='vision-two'))) == ['answer', 'answer']
        assert sorted(seen) == ['vision-one', 'vision-two']
        with vp.composer_request_scope(config, backend, resolve_config=lambda: config,
                                      remote_ack=False, principal=Principal(channel='web')):
            copied = contextvars.copy_context()
        async def late():
            await backend.generate_vision_checked(config.model, 'late question')
        task = copied.run(asyncio.create_task, late())
        with pytest.raises(DataHandlingRefused, match='closed'):
            await task
        assert len(seen) == 2
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_reused_prepared_request_and_delete_are_not_image_grants():
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', '', True)
    seen = []
    client = llm_async_client('vlm', base_url=config.base_url, auth=httpx.Auth(),
                              transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)))
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)
    try:
        request = client.build_request('POST', '/chat/completions', json={'model': config.model})
        with pytest.raises(vp.VisionDestinationChanged), vp.composer_request_scope(
            config, backend, resolve_config=lambda: config, remote_ack=False, principal=Principal(channel='web')
        ):
            await client.send(request)
            await client.send(request)
        assert len(seen) == 1
        with pytest.raises(vp.VisionDestinationChanged), vp.composer_request_scope(
            config, backend, resolve_config=lambda: config, remote_ack=False, principal=Principal(channel='web')
        ):
            await client.delete('/chat/completions')
        assert len(seen) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_owned_composer_ignores_environment_proxy_without_changing_legacy_default(monkeypatch):
    import httpcore
    for name in ('NO_PROXY', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.setenv(name, 'http://remote-proxy.invalid:8888')
    seen = []
    async def send(transport, request):
        seen.append(type(transport._pool))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'offline image'}}]})
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', send)
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', 'same-key', True)
    backend = vlm.VLMBackend(config.base_url, config.api_key, composer_auth=True)
    legacy = vlm.VLMBackend(config.base_url, config.api_key)
    try:
        with vp.composer_request_scope(config, backend, resolve_config=lambda: config,
                                      remote_ack=False, principal=Principal(channel='web')):
            assert await backend.generate_vision_checked(config.model, 'private image') == 'offline image'
        assert seen == [httpcore.AsyncConnectionPool]
        assert backend.client.timeout.read == legacy.client.timeout.read == 180
        assert backend.api_key == legacy.api_key == 'same-key'
        selected = legacy.client._transport_for_url(httpx.URL(vp.describe(config).request_url))
        assert type(selected._pool) is httpcore.AsyncHTTPProxy
    finally:
        await backend.aclose()
        await legacy.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['proxy', 'proxy_mount', 'class_selector', 'instance_selector', 'earlier_hook_mount'])
async def test_composer_refuses_selected_proxy_or_unknown_selector_before_io(monkeypatch, change):
    seen = []
    async def send(transport, request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'unsafe image'}}]})
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', send)
    config = vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', '', True)
    options = {'base_url': config.base_url, 'auth': httpx.Auth(), 'trust_env': False}
    if change == 'proxy':
        options['proxy'] = 'http://remote-proxy.invalid:8888'
    elif change == 'proxy_mount':
        options['mounts'] = {'http://': httpx.AsyncHTTPTransport(proxy='http://remote-proxy.invalid:8888')}
    else:
        options['transport'] = httpx.MockTransport(lambda r: seen.append(r) or
            httpx.Response(200, json={'choices': [{'message': {'content': 'unsafe image'}}]}))
    if change == 'class_selector':
        class CustomSelector(httpx.AsyncClient):
            def _transport_for_url(self, url):
                return self._transport
        actual = CustomSelector(**options)
    else:
        if change == 'earlier_hook_mount':
            async def mutate(request):
                actual._mounts = {httpx._utils.URLPattern('http://'):
                                 httpx.AsyncHTTPTransport(proxy='http://remote-proxy.invalid:8888')}
            options['event_hooks'] = {'request': [mutate]}
        actual = llm_async_client('vlm', **options)
        if change == 'instance_selector':
            actual._transport_for_url = lambda url: actual._transport
    backend = vlm.VLMBackend(config.base_url, client=actual, composer_auth=True)
    try:
        with pytest.raises(vp.VisionDestinationChanged), vp.composer_request_scope(
                config, backend, resolve_config=lambda: config, remote_ack=False, principal=Principal(channel='web')):
            await backend.generate_vision_checked(config.model, 'private image')
        assert seen == []
    finally:
        await backend.aclose()
