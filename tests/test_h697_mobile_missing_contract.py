"""In-process route tests with real session stores; no lifespan/server/provider starts."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI

from agents import web
from agents.core.memory import persistence
from agents.core.memory.manager import MemoryManager
from agents.core.session_continuation import ContinuationStore
from tests.test_session_continuation import SEED, manager


@pytest.fixture
def routed(tmp_path, monkeypatch):
    memory_dir = tmp_path / 'memory'
    memory_dir.mkdir()
    monkeypatch.setattr(persistence, 'MEMORY_DIR', memory_dir)
    cp = manager(tmp_path / 'checkpoints.db')
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    orch = SimpleNamespace(memory=memory, checkpoints=cp, session_id='default-live')
    monkeypatch.setattr(web, 'orch', orch)
    monkeypatch.setattr(web, 'submit_auth_event', lambda *a, **k: None)
    monkeypatch.setattr(web, '_user_credential_required', lambda: True)
    monkeypatch.setattr(web, '_user_credential_ok', lambda **kw: kw.get('user_supplied') == 'valid')
    async def never(*a, **k):
        pytest.fail('turn execution boundary reached after refusal')
    monkeypatch.setattr(web, '_busy_command_refusal', never)
    monkeypatch.setattr(web, '_chat_event_stream', never)
    app = FastAPI()
    app.add_api_route('/chat/stream', web.chat_stream, methods=['POST'], dependencies=[Depends(web._user_guard)])
    yield app, orch, memory_dir
    cp.close()


@pytest.mark.asyncio
async def test_exact_missing_session_is_preexecution_404(routed):
    app, orch, _ = routed
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        reply = await client.post('/chat/stream', headers={'X-User-Token': 'valid'},
                                  json={'message': 'do work', 'agent': 'jarvis', 'session_id': 'gone'})
    assert reply.status_code == 404
    assert reply.json() == {'error': 'session_not_found'}
    assert orch.session_id == 'default-live'
    assert 'gone' not in orch.memory.conversation.sessions


@pytest.mark.asyncio
async def test_auth_refusal_wins_over_missing_session(routed):
    app, orch, _ = routed
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        reply = await client.post('/chat/stream', headers={'X-User-Token': 'invalid'},
                                  json={'message': 'do work', 'session_id': 'gone'})
    assert reply.status_code == 401
    assert reply.json() == {'detail': 'user token required'}
    assert orch.session_id == 'default-live'


@pytest.mark.asyncio
async def test_existing_corrupt_history_is_not_a_missing_session(routed):
    app, orch, folder = routed
    cp = orch.checkpoints
    cp.create_session_record('source')
    child = ContinuationStore(cp).create('source', '00000000-0000-4000-8000-000000000001',
                                         SEED, cp.clock_snapshot('source'))['session_id']
    (folder / f'{child}.json').write_text('{broken')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        reply = await client.post('/chat/stream', headers={'X-User-Token': 'valid'},
                                  json={'message': 'do work', 'session_id': child})
    assert reply.status_code == 409
    assert reply.json() == {'error': 'invalid_history'}
    assert orch.session_id == 'default-live'


@pytest.mark.asyncio
async def test_network_authorization_403_does_not_become_missing(routed, monkeypatch):
    app, orch, _ = routed
    monkeypatch.setattr(web, '_user_credential_required', lambda: False)
    monkeypatch.setattr(web, '_real_client_host', lambda request: '192.0.2.1')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        reply = await client.post('/chat/stream', json={'message': 'do work', 'session_id': 'gone'})
    assert reply.status_code == 403
    assert 'user routes disabled' in reply.json()['detail']
    assert orch.session_id == 'default-live'


@pytest.mark.asyncio
async def test_initialization_503_is_not_missing_session(routed, monkeypatch):
    app, _, _ = routed
    monkeypatch.setattr(web, 'orch', None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        reply = await client.post('/chat/stream', headers={'X-User-Token': 'valid'},
                                  json={'message': 'do work', 'session_id': 'gone'})
    assert reply.status_code == 503
    assert reply.json() == {'error': 'not initialized'}
