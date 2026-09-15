from types import SimpleNamespace

from agents.core.checkpoint import CheckpointManager
from agents.core.conversation_clock import parse_started_at


def test_session_birth_survives_restart_and_duplicate_create(tmp_path):
    path = str(tmp_path / 'checkpoints.db')
    manager = CheckpointManager(path)
    manager.initialize()
    manager.create_session_record('one')
    first = manager.session_started_at('one')
    manager.close()
    manager = CheckpointManager(path)
    manager.initialize()
    manager.create_session_record('one')
    assert manager.session_started_at('one') == first
    assert parse_started_at(first) is not None
    assert manager.session_started_at('absent') is None
    manager.close()


def test_orchestrator_birth_reads_existing_record_without_reset(tmp_path):
    from agents.core.orchestrator import Orchestrator
    manager = CheckpointManager(str(tmp_path / 'checkpoints.db'))
    manager.initialize()
    manager.create_session_record('one')
    manager._conn.execute("UPDATE sessions SET started_at='2026-09-01T12:00:00+00:00' WHERE id='one'")
    manager._conn.commit()
    stub = SimpleNamespace(session_id='one', checkpoints=manager, _session_born={})
    assert Orchestrator._session_birth(stub).day == 1
    stub._session_born = {}
    assert Orchestrator._session_birth(stub).day == 1
    manager.close()


async def test_agent_response_clock_and_session_scope_are_isolated(tmp_path):
    import asyncio

    from agents.core.agent import Agent
    from agents.core.llm.request_context import current_session

    manager = CheckpointManager(str(tmp_path / 'checkpoints.db'))
    manager.initialize()
    agent = Agent('jarvis', {})
    agent._checkpoint_manager = manager
    seen = []

    class Backend:
        async def generate(self, **kwargs):
            await asyncio.sleep(0)
            seen.append((current_session(), kwargs['system']))
            return 'ok'

    async def run(sid):
        return await agent.generate_response(backend=Backend(), model='m', prompt='hi',
                                            system='soul', max_tokens=10, temperature=0,
                                            session_id=sid)
    await asyncio.gather(run('a'), run('b'))
    assert {sid for sid, _ in seen} == {'a', 'b'}
    assert all('Conversation started:' in system for _, system in seen)
    assert current_session() is None
    manager.close()
