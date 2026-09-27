"""Authenticated local vision routes bind actual HTTPX dispatch, entirely offline."""
import base64
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from agents.core.llm import vision_policy, vlm
from agents.core.llm.egress import llm_async_client
from agents.core.routers import multimodal

PNG = base64.b64encode(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')).decode()


def rig(monkeypatch, *, config=None, text='Save at (12, 34)', hook=None, cleanup=None):
    config = config or vlm.VLMConfig('lmstudio', 'http://127.0.0.1:1234/v1', 'vision', '', True)
    current, built, sent = [config], [], []
    native = vlm.VLMBackend
    async def offline_native(transport, request):
        return handle(request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', offline_native)
    def handle(request):
        sent.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': text}}]})
    def factory(**kwargs):
        actual = llm_async_client('vlm', base_url=kwargs['base_url'], auth=httpx.Auth(), trust_env=False,
            transport=httpx.MockTransport(handle), event_hooks={'request': [hook] if hook else []})
        backend = native(client=actual, **kwargs)
        close = backend.aclose
        async def closing():
            await close()
            if cleanup:
                cleanup(current)
        backend.aclose = closing
        built.append(backend)
        return backend
    monkeypatch.setattr(vlm, 'resolve_vlm_config', lambda: current[0])
    monkeypatch.setattr(vlm, 'VLMBackend', factory)
    return SimpleNamespace(config=config, current=current, built=built, sent=sent)


async def invoke(route, **kwargs):
    if route == 'describe':
        return await multimodal.vlm_describe(multimodal.VLMDescribeBody(prompt='what is open?', images=['data:image/png;base64,'+PNG], **kwargs))
    return await multimodal.screen_reflex(multimodal.ScreenReflexBody(image_base64=PNG, question='what is open?', **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['describe', 'screen'])
@pytest.mark.parametrize('backend,policy', [('lmstudio','local'), ('custom','unknown')])
async def test_actual_local_dispatch_reports_policy_and_closes(monkeypatch, route, backend, policy):
    config = vlm.VLMConfig(backend, 'http://127.0.0.1:1234/v1', 'vision', '', True)
    state = rig(monkeypatch, config=config)
    response = await invoke(route)
    body = json.loads(response.body)
    assert response.status_code == 200 and body['ok'] is True
    assert body['data_policy'] == policy and bool(body['warning']) is (policy == 'unknown')
    assert body['data_policy_note']
    assert len(state.sent) == 1 and state.built[0].client.is_closed
    assert state.built[0]._composer_auth is True
    if route == 'screen':
        assert body['generated'] is True


@pytest.mark.asyncio
async def test_status_is_pure_and_exposes_only_sanitized_origin(monkeypatch):
    config = vlm.VLMConfig('custom', 'http://user:private-password@localhost:1234/private/path?private-query=x#fragment', 'vision', 'private-key', True)
    monkeypatch.setattr(vlm, 'resolve_vlm_config', lambda: config)
    monkeypatch.setattr(vlm, 'VLMBackend', lambda **kw: pytest.fail('status constructed client'))
    response = await multimodal.vlm_status()
    body = json.loads(response.body)
    assert body['reachable'] is None and body['configured'] is True
    assert body['base_url'] == 'http://localhost:1234'
    assert body['data_policy'] == 'unknown' and body['warning']
    assert not any(secret in response.body.decode() for secret in ('private-password','private-query','private-key','private/path','fragment'))


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['describe', 'screen'])
async def test_remote_refuses_before_any_construction_even_with_owner(monkeypatch, route):
    rig(monkeypatch, config=vlm.VLMConfig('custom', 'https://remote.invalid/v1', 'vision', '', False))
    monkeypatch.setattr(vlm, 'VLMBackend', lambda **kw: pytest.fail('remote client constructed'))
    response = await invoke(route)
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['describe', 'screen'])
@pytest.mark.parametrize('change', ['key','url','model','policy','proxy','selector'])
async def test_fresh_configuration_or_wire_change_refuses_before_io(monkeypatch, route, change):
    state = None
    async def mutate(request):
        if change == 'key':
            state.current[0] = replace(state.config, api_key='private-rotated-key')
        elif change == 'url':
            state.current[0] = replace(state.config, base_url='https://private-remote.invalid/v1', is_local=False)
        elif change == 'model':
            state.current[0] = replace(state.config, model='changed-model')
        elif change == 'policy':
            state.current[0] = replace(state.config, backend='custom')
        elif change == 'proxy':
            state.built[0].client._mounts = {httpx._utils.URLPattern('http://'):
                                           httpx.AsyncHTTPTransport(proxy='http://private-proxy.invalid:8888')}
        else:
            client = state.built[0].client
            client._transport_for_url = lambda url: client._transport
    state = rig(monkeypatch, hook=mutate)
    response = await invoke(route)
    body = json.loads(response.body)
    assert response.status_code == 409 and body['ok'] is False
    assert state.sent == [] and state.built[0].client.is_closed
    assert 'private-' not in response.body.decode()
    if route == 'screen':
        assert body['generated'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['describe','screen'])
async def test_change_during_awaited_cleanup_revokes_returned_answer(monkeypatch, route):
    state = rig(monkeypatch, cleanup=lambda current: current.__setitem__(0, replace(current[0], api_key='private-after-close')))
    response = await invoke(route)
    body = json.loads(response.body)
    assert response.status_code == 409 and body['ok'] is False
    assert len(state.sent) == 1 and state.built[0].client.is_closed
    assert 'answer' not in body and 'response' not in body and 'private-after-close' not in response.body.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['', '   ', '[VLM error]'])
async def test_describe_empty_or_error_sentinel_is_never_success(monkeypatch, text):
    state = rig(monkeypatch, text=text)
    response = await invoke('describe')
    body = json.loads(response.body)
    assert response.status_code == 502 and body['ok'] is False
    assert 'response' not in body and state.built[0].client.is_closed


@pytest.mark.asyncio
async def test_explicit_model_remains_frozen_while_default_changes(monkeypatch):
    state = None
    async def default_changed(request):
        state.current[0] = replace(state.config, model='new-default')
    state = rig(monkeypatch, hook=default_changed)
    response = await invoke('describe', model='chosen-model')
    assert response.status_code == 200
    assert json.loads(response.body)['model'] == 'chosen-model'
    assert json.loads(state.sent[0].content)['model'] == 'chosen-model'


@pytest.mark.asyncio
async def test_grounding_still_uses_pure_core(monkeypatch):
    rig(monkeypatch)
    response = await invoke('screen', mode='ground')
    assert json.loads(response.body)['elements'] == [{'label':'Save','x':12,'y':34,'source':'vlm'}]


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['describe','screen'])
async def test_entry_configuration_drift_closes_without_dispatch(monkeypatch, route):
    state = rig(monkeypatch)
    factory = vlm.VLMBackend
    def changed(**kwargs):
        backend = factory(**kwargs)
        state.current[0] = replace(state.config, api_key='private-construction-rotation')
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', changed)
    response = await invoke(route)
    assert response.status_code == 409 and state.sent == []
    assert state.built[0].client.is_closed
    assert 'private-construction-rotation' not in response.body.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['describe','screen'])
async def test_invalid_wire_identity_is_unavailable_before_construction(monkeypatch, route):
    config = vlm.VLMConfig('lmstudio', 'http://private-user:private-password@localhost:invalid-port/v1', 'vision', '', True)
    monkeypatch.setattr(vlm, 'resolve_vlm_config', lambda: config)
    monkeypatch.setattr(vlm, 'VLMBackend', lambda **kw: pytest.fail('invalid config constructed client'))
    response = await invoke(route)
    assert response.status_code == 503 and 'private-' not in response.body.decode()
    assert json.loads((await multimodal.vlm_status()).body)['configured'] is False


@pytest.mark.asyncio
async def test_unreadable_configuration_is_bounded_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError('private settings recovery detail')
    monkeypatch.setattr(vlm, 'resolve_vlm_config', unavailable)
    status = await multimodal.vlm_status()
    assert json.loads(status.body)['configured'] is False and 'private' not in status.body.decode()
    for route in ('describe','screen'):
        response = await invoke(route)
        assert response.status_code == 503 and 'private' not in response.body.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['describe','screen'])
async def test_inference_error_is_bounded_and_owned_client_closes(monkeypatch, route):
    state = rig(monkeypatch)
    def failed(request):
        raise RuntimeError('private-image-provider-detail')
    factory = vlm.VLMBackend
    def broken(**kwargs):
        backend = factory(**kwargs)
        backend.client._transport = httpx.MockTransport(failed)
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', broken)
    response = await invoke(route)
    body = json.loads(response.body)
    assert body['ok'] is False and 'private-image-provider-detail' not in response.body.decode()
    assert state.built[0].client.is_closed
    if route == 'describe':
        assert response.status_code == 502
    else:
        assert body['generated'] is False


def test_vision_routes_remain_user_guarded():
    from agents.core.routers._deps import user_guard
    for path in ('/api/vlm/status','/api/vlm/describe','/api/screen/reflex'):
        route = next(route for route in multimodal.router.routes if getattr(route, 'path', '') == path)
        assert any(dep.call is user_guard for dep in route.dependant.dependencies)
