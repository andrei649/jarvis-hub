"""Real manager/handler refusal distinctions; auth dependency is not exercised here."""
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from agents.core.memory import persistence
from agents.core.memory.manager import MemoryManager
from agents.core.routers import sessions
from agents.core.session_continuation import ContinuationStore
from tests.test_session_continuation import SEED, manager


def request(sid):
    async def receive():
        return {'type': 'http.request', 'body': json.dumps({'session_id': sid}).encode()}
    return Request({'type': 'http', 'method': 'POST', 'path': '/sessions/resume', 'headers': []}, receive)


@pytest.mark.asyncio
async def test_missing_requested_session_is_exact_named_404(tmp_path, monkeypatch):
    folder = tmp_path / 'memory'
    folder.mkdir()
    monkeypatch.setattr(persistence, 'MEMORY_DIR', folder)
    cp = manager(tmp_path / 'cp.db')
    try:
        memory = MemoryManager()
        memory.set_checkpoint_manager(cp)
        orch = SimpleNamespace(memory=memory, checkpoints=cp, session_id='live')
        monkeypatch.setattr(sessions, 'get_orch', lambda: orch)
        result = await sessions.resume_session(request('gone'))
        assert result.status_code == 404
        assert json.loads(result.body) == {'error': "session 'gone' not found"}
        assert orch.session_id == 'live'
    finally:
        cp.close()


@pytest.mark.asyncio
async def test_existing_continuation_with_corrupt_history_is_preserved_conflict(tmp_path, monkeypatch):
    folder = tmp_path / 'memory'
    folder.mkdir()
    monkeypatch.setattr(persistence, 'MEMORY_DIR', folder)
    cp = manager(tmp_path / 'cp.db')
    try:
        cp.create_session_record('source')
        child = ContinuationStore(cp).create(
            'source', '00000000-0000-4000-8000-000000000001', SEED, cp.clock_snapshot('source'))['session_id']
        (folder / f'{child}.json').write_text('{broken')
        memory = MemoryManager()
        memory.set_checkpoint_manager(cp)
        orch = SimpleNamespace(memory=memory, checkpoints=cp, session_id='live')
        monkeypatch.setattr(sessions, 'get_orch', lambda: orch)
        result = await sessions.resume_session(request(child))
        assert result.status_code == 409
        assert json.loads(result.body) == {'error': 'invalid_history'}
        assert orch.session_id == 'live'
    finally:
        cp.close()
