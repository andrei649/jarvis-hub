"""Owner HTTP workflow and non-echo surface for named endpoints."""
import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core.llm import custom_endpoints as metadata
from tests.test_h367_custom_endpoint_service import service as service_fixture

HEADERS = {'X-Admin-Token': 'synthetic-custom-owner'}
PATH = '/api/admin/llm/custom-endpoints'


@pytest.fixture
def client(service_fixture, monkeypatch):
    from agents import web
    from agents.core.routers import autonomy, custom_endpoints

    svc, _, _ = service_fixture
    orch = SimpleNamespace(custom_endpoint_service=svc, llm_router=None)
    monkeypatch.setattr(web, '_admin_configured', lambda: True)
    monkeypatch.setattr(web, '_admin_credential_ok', lambda token: token == HEADERS['X-Admin-Token'])
    monkeypatch.setattr(autonomy, 'get_orch', lambda: orch)
    monkeypatch.setattr(custom_endpoints, 'get_orch', lambda: orch)
    return TestClient(web.app)


def test_owner_full_metadata_flow_and_no_ambient_activation(client):
    assert client.get(PATH).status_code == 401
    body = {'key': 'one', 'name': 'One', 'base_url': 'http://127.0.0.1:1234/v1',
            'model': 'm', 'auth_type': 'none', 'data_policy': 'local'}
    created = client.post(PATH, json=body, headers=HEADERS)
    assert created.status_code == 200
    assert created.json()['identity'] == 'custom:one'
    assert metadata.read_choice().active_key is None
    listing = client.get(PATH, headers=HEADERS).json()
    assert len(listing['endpoints']) == 1
    assert listing['active'] is None
    renamed = client.put(PATH + '/one', json={'name': 'New', 'expected_revision': 1},
                         headers=HEADERS)
    assert renamed.status_code == 200
    assert renamed.json()['identity'] == 'custom:one'
    active = client.put(PATH + '/one/activate',
        json={'expected_revision': 2, 'expected_choice_epoch': listing['choice_epoch'],
              'acknowledge_unknown_price': True}, headers=HEADERS)
    assert active.status_code == 200
    assert active.json()['active'] == 'custom:one'
    removed = client.request('DELETE', PATH + '/one',
        json={'expected_revision': 2}, headers=HEADERS)
    assert removed.status_code == 200
    assert client.get(PATH, headers=HEADERS).json()['endpoints'] == []


def test_secret_body_and_validation_error_never_echo(client):
    body = {'key': 'one', 'name': 'One', 'base_url': 'https://example.invalid/v1',
            'model': 'm', 'auth_type': 'bearer', 'data_policy': 'unknown',
            'grant_destination': True}
    assert client.post(PATH, json=body, headers=HEADERS).status_code == 200
    secret = 'synthetic-custom-secret-abc'
    bad = client.put(PATH + '/one/credential', json={'secret': secret, 'unknown': secret},
                     headers=HEADERS)
    assert bad.status_code == 422 and secret not in bad.text
    saved = client.put(PATH + '/one/credential', json={'secret': secret}, headers=HEADERS)
    assert saved.status_code == 200 and secret not in saved.text
    status = client.get(PATH + '/one/credential', headers=HEADERS)
    assert status.json() == {'configured': True, 'generation': 1}
    assert secret not in client.get(PATH, headers=HEADERS).text
    deleted = client.delete(PATH + '/one/credential', headers=HEADERS)
    assert deleted.status_code == 200 and secret not in deleted.text


def test_public_api_activation_needs_exact_destination_grant(client):
    body = {'key': 'hosted', 'name': 'Hosted', 'base_url': 'https://endpoint.invalid/v1',
            'model': 'm', 'auth_type': 'none', 'data_policy': 'unknown',
            'grant_destination': True}
    assert client.post(PATH, json=body, headers=HEADERS).status_code == 200
    activation = {'expected_revision': 1,
                  'expected_choice_epoch': metadata.read_choice().epoch,
                  'acknowledge_unknown_price': True, 'acknowledge_data_policy': True}
    denied = client.put(PATH + '/hosted/activate', json=activation, headers=HEADERS)
    assert denied.status_code == 409
    assert metadata.read_choice().active_key is None
    allowed = client.put(PATH + '/hosted/activate',
                         json={**activation, 'grant_destination': True}, headers=HEADERS)
    assert allowed.status_code == 200
    assert allowed.json()['active'] == 'custom:hosted'


@pytest.mark.asyncio
async def test_cancelled_offloaded_mutation_drains_and_refreshes_before_unwind(monkeypatch):
    from agents.core.routers import custom_endpoints as routes

    entered, release = threading.Event(), threading.Event()
    events = []

    def worker(*_args):
        entered.set()
        release.wait(5)
        events.append('committed')
        return {'ok': True}

    async def refresh(_request):
        events.append('refreshed')

    monkeypatch.setattr(routes, '_sync', worker)
    monkeypatch.setattr(routes, '_refresh', refresh)
    task = asyncio.create_task(routes._call(object(), 'rename', {}, refresh=True))
    assert await asyncio.to_thread(entered.wait, 3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ['committed', 'refreshed']
