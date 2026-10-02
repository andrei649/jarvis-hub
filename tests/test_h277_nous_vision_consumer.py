"""Actual Nous account/catalog/image integration through the owner-facing composer."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import settings_db
from agents.core.llm import model_roles, nous_auth, nous_models, vlm
from agents.core.llm.egress import llm_async_client
from agents.core.llm.nous_credentials import NousAuthStore
from agents.core.secrets import SecretStore
from tests.test_composer_vision import DESCRIBE, PNG, STATUS
from tests.test_h277_nous_auth import _jwt
from tests.test_h277_nous_credentials import KEY


@pytest.fixture
def route(monkeypatch, tmp_path):
    nous_models.clear_cache()
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    monkeypatch.setattr(settings_db, '_wal_set', False)
    for name in ('JARVIS_ROLE_VISION_MODEL', 'JARVIS_ROLE_VISION_BASE_URL', 'JARVIS_ROLE_VISION_KEY',
                 'JARVIS_ROLE_VISION_PROFILE', 'JARVIS_VLM_BACKEND', 'JARVIS_VLM_MODEL', 'JARVIS_VLM_KEY',
                 'JARVIS_VLM_URL', 'JARVIS_NOUS_INFERENCE_BASE_URL', 'JARVIS_NOUS_PORTAL_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('JARVIS_ROLE_VISION_PROVIDER', 'nous')
    monkeypatch.setenv('JARVIS_NOUS_CLIENT_ID', 'nerva-test-public-client')
    monkeypatch.setenv('JARVIS_NOUS_ANTHROPIC_WIRE', 'chat')
    monkeypatch.setenv('JARVIS_ROLE_VISION_EMPTY_RETRIES', '0')
    monkeypatch.setenv('JARVIS_USER_TOKEN', 'image-test')
    monkeypatch.setattr(web, 'USER_TOKEN', 'image-test')
    monkeypatch.setattr(web.app, 'dependency_overrides', {})
    store = NousAuthStore(tmp_path / 'nous.sqlite3', cipher=SecretStore(tmp_path / 'cipher', key=KEY))
    token = _jwt(int(time.time()) + 3600)
    with store.transaction() as state:
        state.update(access_token=token, refresh_token='private-refresh', scope='inference:invoke',
                     portal_base_url='https://portal.nousresearch.com', client_id='nerva-test-public-client')
    monkeypatch.setattr(nous_auth, 'NousAuthStore', lambda: store)
    monkeypatch.setattr(nous_models, 'data_path', lambda *parts: tmp_path.joinpath(*parts))
    result = SimpleNamespace(store=store, token=token, metadata=[], inference=[], model='anthropic/claude-sonnet-4-6',
                             late=None, catalog_failure=False)
    def respond(request):
        if request.method == 'GET':
            result.metadata.append(request)
            if request.url.path == '/api/oauth/account':
                assert request.headers['Authorization'] == 'Bearer ' + token
                return httpx.Response(200, json={'paid_service_access': {'allowed': True}})
            assert request.url.path == '/api/nous/recommended-models'
            assert 'Authorization' not in request.headers
            if result.catalog_failure:
                return httpx.Response(503)
            return httpx.Response(200, json={'paidRecommendedVisionModel': {'modelName': result.model}})
        result.inference.append(request)
        if request.url.path.endswith('/messages'):
            return httpx.Response(200, json={'type': 'message', 'role': 'assistant', 'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': 'The picture is clear.'}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'The picture is clear.'}}]})
    monkeypatch.setattr(nous_models, '_transport_factory', lambda: httpx.MockTransport(respond))
    def factory(provider, **kwargs):
        client = llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs)
        async def late(request):
            if result.late:
                result.late(request)
        client.event_hooks['request'].append(late)
        return client
    monkeypatch.setattr(vlm, 'llm_async_client', factory)
    result.client = TestClient(web.app, headers={'X-User-Token': 'image-test'})
    yield result
    nous_models.clear_cache()


def body(route):
    status = route.client.get(STATUS).json()
    assert status['configured'], status
    assert status['backend'] == 'nous' and status['reachable'] is None
    assert route.token not in str(status) and 'private-refresh' not in str(status)
    return {'prompt': 'Describe this', 'images': [PNG], 'remote_ack': True,
            'expected_destination': status['destination'], 'expected_binding': status['binding']}


@pytest.mark.parametrize('mode,path', [('chat', '/chat/completions'), ('native', '/messages'), ('auto', '/chat/completions')])
def test_actual_account_recommendation_and_image_send(route, monkeypatch, mode, path):
    monkeypatch.setenv('JARVIS_NOUS_ANTHROPIC_WIRE', mode)
    approved = body(route)
    assert len(route.metadata) == 1 and not route.inference
    response = route.client.post(DESCRIBE, json=approved)
    assert response.status_code == 200, response.text
    assert response.json()['response'] == 'The picture is clear.'
    assert len(route.metadata) == 1 and len(route.inference) == 1
    assert str(route.inference[0].url) == 'https://inference-api.nousresearch.com/v1' + path
    assert route.inference[0].headers['Authorization'] == 'Bearer ' + route.token
    assert json.loads(route.inference[0].content)['model'] == route.model


def test_role_and_video_status_are_truthful_without_network(route):
    body(route)
    count = len(route.metadata)
    role = model_roles.resolve('vision')
    assert role.configured and role.provider_id == 'nous'
    assert role.model == route.model and role.data_policy == 'unknown'
    assert role.source['model'] == 'nous_recommendation'
    assert route.token not in repr(role)
    video = model_roles.resolve_video_route()
    assert not video.role.configured and video.role.reason == 'video_vision_provider_unsupported'
    assert len(route.metadata) == count and not route.inference


@pytest.mark.parametrize('name,value,reason', [
    ('JARVIS_ROLE_VISION_PROFILE', '../invalid', 'vlm_profile_invalid'),
    ('JARVIS_ROLE_VISION_KEY', 'unrelated-key', 'vlm_key_conflict'),
])
def test_invalid_account_settings_produce_role_refusal(route, monkeypatch, name, value, reason):
    monkeypatch.setenv(name, value)
    role = model_roles.resolve('vision')
    assert not role.configured and role.reason == reason
    assert not route.metadata and not route.inference


def test_no_remote_confirmation_means_no_image_request(route):
    approved = body(route)
    approved['remote_ack'] = False
    assert route.client.post(DESCRIBE, json=approved).status_code == 403
    assert not route.inference


@pytest.mark.parametrize('change', ['logout', 'token', 'profile', 'wire', 'model'])
def test_changed_selection_refuses_without_implicit_discovery(route, monkeypatch, change):
    approved = body(route)
    if change == 'logout':
        nous_auth.NousAuthService().logout()
    elif change == 'token':
        with route.store.transaction() as state:
            state['access_token'] = _jwt(int(time.time()) + 7200)
    else:
        monkeypatch.setenv({'profile': 'JARVIS_ROLE_VISION_PROFILE', 'wire': 'JARVIS_NOUS_ANTHROPIC_WIRE',
                           'model': 'JARVIS_ROLE_VISION_MODEL'}[change],
                          {'profile': 'other', 'wire': 'native', 'model': 'other/vision'}[change])
    response = route.client.post(DESCRIBE, json=approved)
    assert response.status_code in {409, 503}, response.text
    assert len(route.metadata) == 1 and not route.inference


def test_refresh_changes_model_and_binding_before_next_send(route):
    approved = body(route)
    route.model = 'vendor/new-vision'
    status = route.client.get(STATUS, params={'refresh_catalog': 'true'}).json()
    assert status['configured'] and status['model'] == route.model
    assert status['binding'] != approved['expected_binding']
    assert route.client.post(DESCRIBE, json=approved).status_code == 409
    assert len(route.metadata) == 3 and not route.inference


def test_explicit_model_needs_no_recommendation(route, monkeypatch):
    monkeypatch.setenv('JARVIS_ROLE_VISION_MODEL', 'vendor/pinned')
    assert route.client.post(DESCRIBE, json=body(route)).status_code == 200
    assert not route.metadata and len(route.inference) == 1


def test_explicit_loopback_account_endpoint_reports_and_uses_actual_locality(route, monkeypatch):
    monkeypatch.setenv('JARVIS_NOUS_INFERENCE_BASE_URL', 'http://127.0.0.1:1234/v1')
    monkeypatch.setenv('JARVIS_ROLE_VISION_MODEL', 'vendor/pinned')
    approved = body(route)
    status = route.client.get(STATUS).json()
    assert status['local'] is True and status['data_policy'] == 'unknown'
    assert model_roles.resolve('vision').local is True
    approved['remote_ack'] = False
    response = route.client.post(DESCRIBE, json=approved)
    assert response.status_code == 200, response.text
    assert str(route.inference[0].url) == 'http://127.0.0.1:1234/v1/chat/completions'
    assert not route.metadata


def test_late_logout_prevents_actual_image_transport(route):
    approved = body(route)
    route.late = lambda request: nous_auth.NousAuthService().logout()
    assert route.client.post(DESCRIBE, json=approved).status_code == 409
    assert not route.inference


@pytest.mark.asyncio
@pytest.mark.parametrize('consumer', ['describe', 'screen', 'telegram'])
async def test_nous_does_not_enable_remote_local_only_consumers(route, consumer):
    from agents.core.channels.media_reader import InboundImageReader
    from tests.test_h513_interactive_local_vision import invoke
    body(route)
    if consumer == 'telegram':
        assert InboundImageReader.from_env().refusal().reason == 'local_vlm_not_proven_local'
    else:
        assert (await invoke(consumer)).status_code == 503
    assert not route.inference
