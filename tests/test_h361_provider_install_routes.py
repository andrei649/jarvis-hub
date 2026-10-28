"""Production HTTP owner boundary, private synthetic packages only."""
import asyncio
import fcntl
import os
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.core.llm.providers.packages import _profile_payload
from tests.test_h361_provider_install_service import owner, service, staged

HEADERS = {'X-Admin-Token': 'synthetic-install-owner'}
PATH = '/api/llm/provider-packages'


@pytest.fixture
def client(service, monkeypatch):
    from agents import web
    from agents.core.routers import autonomy, models_llm
    svc, _, _, _ = service
    orch = SimpleNamespace(provider_install_service=svc)
    monkeypatch.setenv('JARVIS_PROVIDER_PLUGINS', '1')
    monkeypatch.setattr(web, '_admin_configured', lambda: True)
    monkeypatch.setattr(web, '_admin_credential_ok', lambda token: token == HEADERS['X-Admin-Token'])
    monkeypatch.setattr(models_llm, 'get_orch', lambda: orch)
    monkeypatch.setattr(autonomy, 'get_orch', lambda: orch)
    return TestClient(web.app)


def stage_body(service):
    _, profile, hooks, _ = service
    data = _profile_payload(profile)
    return {'candidate': 'addon', 'source': 'user', 'profile': data, 'hooks': list(hooks)}


def test_http_stage_pending_decision_and_promotion_recheck_exact_owner_scope(client, service):
    _, _, _, actions = service
    assert client.post(PATH+'/stage', json=stage_body(service)).status_code == 401
    staged = client.post(PATH+'/stage', headers=HEADERS, json=stage_body(service))
    assert staged.status_code == 200
    artifact = staged.json()
    assert 'members' not in artifact and 'profile' not in artifact
    offer = client.post(PATH+'/'+artifact['artifact_id']+'/propose', headers=HEADERS).json()
    decision = {'artifact_id': artifact['artifact_id'], 'package_hash': artifact['package_hash'],
                'approved': True, 'permanent': True}
    route = PATH+'/proposals/'+offer['proposal_id']
    assert client.post(route+'/promote', headers=HEADERS).status_code == 409
    assert client.post(route+'/decision', headers=HEADERS,
                       json={**decision, 'actor': 'owner'}).status_code == 422
    assert client.post(route+'/decision', headers=HEADERS,
                       json={**decision, 'package_hash': '0'*64}).status_code == 409
    assert actions == []
    assert client.post(route+'/decision', headers=HEADERS, json=decision).status_code == 200
    assert client.post(route+'/promote', headers=HEADERS).status_code == 200
    assert [a.payload['phase'] for a in actions] == ['promote']
    assert client.post(PATH+'/synthetic-addon/revoke', headers=HEADERS).status_code == 200


def test_server_candidate_reference_cannot_escape_and_disabled_status_is_lazy(client, service, monkeypatch):
    svc, _, _, _ = service
    body = stage_body(service)
    assert client.post(PATH+'/stage', headers=HEADERS,
                       json={**body, 'candidate': '../addon'}).status_code == 422
    assert not (svc.root/'packages').exists()
    monkeypatch.delenv('JARVIS_PROVIDER_PLUGINS')
    assert client.get(PATH+'/status', headers=HEADERS).json()['enabled'] is False
    assert client.post(PATH+'/stage', headers=HEADERS, json=body).status_code == 409
    assert not (svc.root/'packages').exists()


def test_live_owner_recheck_refuses_replaced_orchestrator_even_after_request_guard(client, service, monkeypatch):
    from agents.core.routers import autonomy
    monkeypatch.setattr(autonomy, 'get_orch', lambda: SimpleNamespace())
    assert client.post(PATH+'/stage', headers=HEADERS, json=stage_body(service)).status_code == 409
    assert not (service[0].root/'packages').exists()


def test_http_denial_is_hash_scoped_and_cannot_be_replayed(client, service):
    artifact = client.post(PATH+'/stage', headers=HEADERS,
                           json=stage_body(service)).json()
    offer = client.post(PATH+'/'+artifact['artifact_id']+'/propose', headers=HEADERS).json()
    route = PATH+'/proposals/'+offer['proposal_id']+'/decision'
    body = {'artifact_id': artifact['artifact_id'], 'package_hash': artifact['package_hash'],
            'approved': False, 'permanent': True}
    assert client.post(route, headers=HEADERS,
                       json={**body, 'package_hash': '0'*64}).status_code == 409
    assert client.post(route, headers=HEADERS, json=body).status_code == 200
    assert client.post(route, headers=HEADERS, json=body).status_code == 409
    assert client.post(PATH+'/proposals/'+offer['proposal_id']+'/promote',
                       headers=HEADERS).status_code == 409


@pytest.mark.asyncio
async def test_http_revoke_awaits_inflight_lease_and_committed_revocation(client, service):
    svc, _, _, _ = service
    preview = staged(service)
    offer = svc.propose(preview['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=preview['artifact_id'],
               package_hash=preview['package_hash'], approved=True,
               permanent=True, actor=owner())
    svc.promote(offer['proposal_id'], actor=owner())
    entered, release, sent = asyncio.Event(), asyncio.Event(), []

    async def physical_attempt():
        async with svc._store().dispatch_lease('synthetic-addon',
                                               expected_hash=preview['package_hash'],
                                               home=svc.home):
            entered.set()
            await release.wait()
            sent.append(True)

    task = asyncio.create_task(physical_attempt())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        from agents import web
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url='http://testserver') as http:
            response = await asyncio.wait_for(
                http.post(PATH+'/synthetic-addon/revoke', headers=HEADERS), timeout=5)
        assert response.status_code == 200
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sent == []
        assert svc._store().list_active(home=svc.home) == ()
    finally:
        release.set()
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_stage_lock_wait_does_not_block_unrelated_status(client, service):
    svc, _, _, _ = service
    lock_path = svc._store()._lock_path
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    released = threading.Event()
    release_guard = threading.Lock()

    def release_lock():
        with release_guard:
            if not released.is_set():
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                released.set()

    timer = threading.Timer(0.7, release_lock)
    timer.start()
    try:
        from agents import web
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url='http://testserver') as http:
            start = time.monotonic()
            stage_task = asyncio.create_task(
                http.post(PATH+'/stage', headers=HEADERS, json=stage_body(service)))

            async def status_request():
                response = await http.get(PATH+'/status', headers=HEADERS)
                return response, time.monotonic() - start

            status_task = asyncio.create_task(status_request())
            status, elapsed = await asyncio.wait_for(status_task, timeout=5)
            assert status.status_code == 200 and elapsed < 0.4
            assert (await asyncio.wait_for(stage_task, timeout=5)).status_code == 200
    finally:
        if not released.is_set():
            release_lock()
        timer.cancel()


@pytest.mark.asyncio
async def test_cancelled_revoke_request_waits_for_worker_commit(client, service, monkeypatch):
    from agents.core.llm.providers.packages import ProviderPackageStore

    svc, _, _, _ = service
    preview = staged(service)
    offer = svc.propose(preview['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=preview['artifact_id'],
               package_hash=preview['package_hash'], approved=True,
               permanent=True, actor=owner())
    svc.promote(offer['proposal_id'], actor=owner())
    entered, release = threading.Event(), threading.Event()
    original = ProviderPackageStore.revoke

    def paused_revoke(self, provider_id):
        entered.set()
        assert release.wait(timeout=5)
        return original(self, provider_id)

    monkeypatch.setattr(ProviderPackageStore, 'revoke', paused_revoke)
    from agents import web
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                 base_url='http://testserver') as http:
        request = asyncio.create_task(http.post(PATH+'/synthetic-addon/revoke', headers=HEADERS))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            request.cancel()
            await asyncio.sleep(0.05)
            assert not request.done()
            assert len(svc._store().list_active(home=svc.home)) == 1
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, timeout=5)
            assert svc._store().list_active(home=svc.home) == ()
        finally:
            release.set()
