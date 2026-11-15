"""Governed direct command through real SSE runner; no LLM/server/network."""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from agents import web
from agents.core import session_transition as transition
from agents.core.commands import Principal
from agents.core.orchestrator import Orchestrator


class CommandOrch:
    def __init__(self, mode='success'):
        self.session_id = self._session_id_default = 'global-existing'
        self.mode = mode
        self.memory = SimpleNamespace()
        self.created = 0

    @asynccontextmanager
    async def turn_lease(self, session_id=None):
        yield self.mode != 'busy'

    async def _slash_access_denial(self, command):
        return None

    async def new_session(self, requested):
        if self.mode == 'failed':
            raise OSError('fixture unavailable')
        self.created += 1
        self.session_id = 'global-existing' if self.mode == 'same' else 'fresh-session'
        return self.session_id

    async def handle_input_stream(self, message, **kwargs):
        result = await Orchestrator._direct_session_command(self, message, 'web', None)
        if self.mode == 'concurrent':
            self.session_id = 'another-global'
        return result


async def events(orch, *, admin=True, message='/new', refused=None):
    return [json.loads(chunk.removeprefix('data: ').strip())
            async for chunk in web._chat_event_stream(orch, message, 'jarvis', None,
                principal=Principal(channel='web', admin=admin), refused=refused)]


@pytest.mark.asyncio
async def test_successful_governed_new_has_exact_marker(monkeypatch):
    from agents.core import session_loops
    monkeypatch.setattr(session_loops, 'migrate_session', lambda *args: None)
    orch = CommandOrch()
    final = (await events(orch))[-1]
    assert final['session_id'] == 'fresh-session'
    assert final['session_transition'] == {'command': 'new', 'session_id': 'fresh-session'}
    assert orch.created == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,admin', [('success', False), ('busy', True), ('failed', True), ('same', True), ('concurrent', True)])
async def test_refused_or_unconfirmed_new_has_no_proof(monkeypatch, mode, admin):
    from agents.core import session_loops
    monkeypatch.setattr(session_loops, 'migrate_session', lambda *args: None)
    orch = CommandOrch(mode)
    final = (await events(orch, admin=admin))[-1]
    assert 'session_transition' not in final
    if not admin or mode == 'busy':
        assert orch.created == 0
    # Existing global ID differs from the mobile's gone ID but is not creation proof.
    assert final['session_id'] != 'gone'


@pytest.mark.asyncio
async def test_failure_after_new_session_does_not_publish_partial_success(monkeypatch):
    from agents.core import session_loops
    def fail(*args):
        raise ValueError('migration failed')
    monkeypatch.setattr(session_loops, 'migrate_session', fail)
    orch = CommandOrch()
    final = (await events(orch))[-1]
    assert orch.created == 1
    assert 'session_transition' not in final


@pytest.mark.asyncio
async def test_early_busy_refusal_has_no_proof():
    orch = CommandOrch()
    final = (await events(orch, refused='busy'))[-1]
    assert orch.created == 0
    assert 'session_transition' not in final


@pytest.mark.asyncio
async def test_reset_does_not_earn_new_marker(monkeypatch):
    from agents.core import session_loops
    monkeypatch.setattr(session_loops, 'migrate_session', lambda *args: None)
    final = (await events(CommandOrch(), message='/reset'))[-1]
    assert 'session_transition' not in final


def test_invalid_ids_and_closed_scope_cannot_record_proof():
    sink, token = transition.open_session_transition()
    try:
        transition.record_new_session('old', 'invalid/id')
        assert sink.finish('invalid/id') is None
        transition.record_new_session('old', 'fresh')
        assert sink.finish('fresh') is None
    finally:
        transition.reset_session_transition(token)


@pytest.mark.asyncio
async def test_concurrent_streams_do_not_share_creation_proof(monkeypatch):
    import asyncio

    from agents.core import session_loops
    monkeypatch.setattr(session_loops, 'migrate_session', lambda *args: None)
    good, refused = await asyncio.gather(events(CommandOrch()), events(CommandOrch(), admin=False))
    assert good[-1]['session_transition']['session_id'] == 'fresh-session'
    assert 'session_transition' not in refused[-1]
