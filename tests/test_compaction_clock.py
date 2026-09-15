from datetime import UTC, datetime

from agents.core.checkpoint import CheckpointManager
from agents.core.conversation_clock import with_clock


def store(tmp_path):
    manager = CheckpointManager(str(tmp_path / 'clock.db'))
    manager.initialize()
    manager.create_session_record('a')
    manager._conn.execute("UPDATE sessions SET started_at='2026-09-01T12:00:00+00:00' WHERE id='a'")
    manager._conn.commit()
    return manager


def test_clock_snapshot_freezes_until_cas_commit_and_survives_restart(tmp_path):
    manager = store(tmp_path)
    first = manager.clock_snapshot('a')
    assert first.revision == 0
    assert first.rebuilt_at == first.started_at
    later = datetime(2026, 9, 3, 12, tzinfo=UTC)
    committed = manager.commit_clock(first, 'summary', now=later)
    assert committed.revision == 1
    assert manager.commit_clock(first, 'stale', now=later) is None
    assert manager.clock_snapshot('a') == committed
    manager.close()
    manager = CheckpointManager(str(tmp_path / 'clock.db'))
    manager.initialize()
    assert manager.clock_snapshot('a') == committed
    assert 'September 03' in with_clock('soul', committed.started_at, committed.rebuilt_at)
    assert 'Today' not in with_clock('soul', first.started_at, first.rebuilt_at)
    manager.close()


def test_missing_corrupt_and_closed_clock_are_unknown(tmp_path):
    manager = store(tmp_path)
    assert manager.clock_snapshot('missing') is None
    manager._conn.execute("UPDATE sessions SET started_at='bad' WHERE id='a'")
    manager._conn.commit()
    assert manager.clock_snapshot('a') is None
    manager.close()
    assert manager.clock_snapshot('a') is None


def test_clock_commit_failure_does_not_advance(tmp_path):
    manager = store(tmp_path)
    first = manager.clock_snapshot('a')
    manager._conn.execute("CREATE TRIGGER deny_clock BEFORE UPDATE ON session_clock BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    assert manager.commit_clock(first, 'summary') is None
    assert manager.clock_snapshot('a') == first
    manager.close()


async def test_actual_agent_uses_durable_rebuild_not_wall_time(tmp_path):
    from agents.core.agent import Agent
    manager = store(tmp_path)
    agent = Agent('jarvis', {})
    agent._checkpoint_manager = manager
    seen = []

    class Backend:
        async def generate(self, **kwargs):
            seen.append(kwargs['system'])
            return 'ok'

    async def run():
        return await agent.generate_response(Backend(), 'm', 'hi', 'soul', 10, 0, session_id='a')
    assert await run() == 'ok'
    assert "Today's date" not in seen[-1]
    manager.commit_clock(manager.clock_snapshot('a'), 'accepted', now=datetime(2026, 9, 3, 12, tzinfo=UTC))
    assert await run() == 'ok'
    assert 'September 03' in seen[-1]
    assert 'September 15' not in seen[-1]
    manager.close()


async def test_explicit_request_snapshot_remains_frozen_after_other_commit(tmp_path):
    from agents.core.agent import Agent
    manager = store(tmp_path)
    before = manager.clock_snapshot('a')
    manager.commit_clock(before, 'other', now=datetime(2026, 9, 3, 12, tzinfo=UTC))
    agent = Agent('jarvis', {})
    agent._checkpoint_manager = manager
    class Backend:
        async def generate(self, **kwargs):
            assert "Today's date" not in kwargs['system']
            return 'ok'
    assert await agent.generate_response(Backend(), 'm', 'hi', 'soul', 10, 0,
                                         session_id='a', clock_snapshot=before) == 'ok'
    manager.close()


def history_stub(manager, compressed=True):
    from types import SimpleNamespace

    from agents.core.context_compressor import CompactionPolicy
    async def history(*args):
        return [{'role': 'user', 'content': 'original'}]
    stub = SimpleNamespace(session_id='a', checkpoints=manager,
        get_setting=lambda key, default=None: True if key == 'memory.context_compression' else default,
        memory=SimpleNamespace(get_history=history), _compaction_model=lambda: 'local',
        _compaction_policy=lambda: CompactionPolicy(), _usage_anchor=lambda n: None)
    return stub


async def test_history_compaction_commits_before_publishing(tmp_path, monkeypatch):
    from agents.core.context_compressor import ContextCompressor
    from agents.core.conversation_clock import prompt_clock
    from agents.core.orchestrator import Orchestrator
    manager = store(tmp_path)
    async def compact(*args, **kwargs):
        return {'compressed': True, 'summary': 'digest', 'covered': 1, 'kept': [], 'kept_first': []}
    monkeypatch.setattr(ContextCompressor, 'compact', compact)
    assert await Orchestrator._history_for_prompt(history_stub(manager), 10) == 'digest'
    assert manager.clock_snapshot('a').revision == 1
    assert prompt_clock.get() == manager.clock_snapshot('a')
    manager.close()


async def test_history_refused_commit_keeps_uncompressed_and_old_clock(tmp_path, monkeypatch):
    from agents.core.context_compressor import ContextCompressor
    from agents.core.conversation_clock import prompt_clock
    from agents.core.orchestrator import Orchestrator
    manager = store(tmp_path)
    first = manager.clock_snapshot('a')
    monkeypatch.setattr(manager, 'commit_clock', lambda *a, **k: None)
    async def compact(*args, **kwargs):
        return {'compressed': True, 'summary': 'unaccepted', 'covered': 1, 'kept': [], 'kept_first': []}
    monkeypatch.setattr(ContextCompressor, 'compact', compact)
    import pytest

    from agents.core.conversation_clock import CompactionClockRefused
    with pytest.raises(CompactionClockRefused):
        await Orchestrator._history_for_prompt(history_stub(manager), 10)
    assert prompt_clock.get() == first
    manager.close()


def test_legacy_z_timestamp_can_commit_and_recreated_session_is_fresh(tmp_path):
    manager = store(tmp_path)
    manager._conn.execute("UPDATE sessions SET started_at='2026-09-01T12:00:00Z' WHERE id='a'")
    manager._conn.commit()
    first = manager.clock_snapshot('a')
    assert manager.commit_clock(first, 'accepted') is not None
    manager._conn.execute("DELETE FROM sessions WHERE id='a'")
    manager._conn.commit()
    manager.create_session_record('a')
    fresh = manager.clock_snapshot('a')
    assert fresh.revision == 0
    assert fresh.rebuilt_at == fresh.started_at
    assert manager.commit_clock(first, 'stale') is None
    manager.close()


async def test_history_noop_and_cancellation_do_not_advance(tmp_path, monkeypatch):
    import asyncio

    import pytest

    from agents.core.context_compressor import ContextCompressor
    from agents.core.orchestrator import Orchestrator
    manager = store(tmp_path)
    first = manager.clock_snapshot('a')
    async def noop(self, turns, **kwargs):
        return {'compressed': False, 'summary': '', 'kept': turns}
    monkeypatch.setattr(ContextCompressor, 'compact', noop)
    assert await Orchestrator._history_for_prompt(history_stub(manager), 10) == '[user]: original'
    assert manager.clock_snapshot('a') == first
    entered = asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(ContextCompressor, 'compact', blocked)
    task = asyncio.create_task(Orchestrator._history_for_prompt(history_stub(manager), 10))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.clock_snapshot('a') == first
    manager.close()


async def test_racing_history_commits_publish_only_cas_winner(tmp_path, monkeypatch):
    import asyncio

    from agents.core.context_compressor import ContextCompressor
    from agents.core.orchestrator import Orchestrator
    manager = store(tmp_path)
    count = 0
    both = asyncio.Event()
    async def compact(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            both.set()
        await both.wait()
        return {'compressed': True, 'summary': 'accepted', 'covered': 1, 'kept': [], 'kept_first': []}
    monkeypatch.setattr(ContextCompressor, 'compact', compact)
    results = await asyncio.gather(*(Orchestrator._history_for_prompt(history_stub(manager), 10) for _ in range(2)), return_exceptions=True)
    from agents.core.conversation_clock import CompactionClockRefused
    assert results.count('accepted') == 1
    assert sum(isinstance(result, CompactionClockRefused) for result in results) == 1
    assert manager.clock_snapshot('a').revision == 1
    manager.close()


def test_two_connections_cannot_commit_same_revision(tmp_path):
    manager = store(tmp_path)
    other = CheckpointManager(str(tmp_path / 'clock.db'))
    other.initialize()
    first = manager.clock_snapshot('a')
    assert other.clock_snapshot('a') == first
    assert manager.commit_clock(first, 'first') is not None
    assert other.commit_clock(first, 'second') is None
    assert other.clock_snapshot('a').revision == 1
    manager.close()
    other.close()


async def test_unknown_store_preserves_legacy_compaction_without_clock(tmp_path, monkeypatch):
    from agents.core.context_compressor import ContextCompressor
    from agents.core.conversation_clock import prompt_clock
    from agents.core.orchestrator import Orchestrator
    async def compact(*args, **kwargs):
        return {'compressed': True, 'summary': 'digest', 'covered': 1, 'kept': [], 'kept_first': []}
    monkeypatch.setattr(ContextCompressor, 'compact', compact)
    assert await Orchestrator._history_for_prompt(history_stub(None), 10) == 'digest'
    assert prompt_clock.get() is None


def test_existing_database_migration_preserves_session_birth(tmp_path):
    import sqlite3
    path = str(tmp_path / 'legacy.db')
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY, agent_id TEXT, started_at TEXT, ended_at TEXT, turn_count INTEGER, summary TEXT, metadata TEXT)')
    connection.execute("INSERT INTO sessions VALUES ('old',NULL,'2026-09-01T12:00:00+00:00',NULL,1,NULL,'{}')")
    connection.commit()
    connection.close()
    manager = CheckpointManager(path)
    manager.initialize()
    assert manager.clock_snapshot('old').revision == 0
    assert manager.clock_snapshot('old').started_at.day == 1
    manager.create_session_record('new')
    assert manager.clock_snapshot('new').revision == 0
    assert manager.clock_snapshot('new').started_at != manager.clock_snapshot('old').started_at
    manager.close()


async def test_concurrent_agent_requests_keep_distinct_snapshot_and_scope(tmp_path):
    import asyncio

    from agents.core.agent import Agent
    from agents.core.conversation_clock import active_clock
    manager = store(tmp_path)
    manager.create_session_record('b')
    agent = Agent('jarvis', {})
    agent._checkpoint_manager = manager
    seen = []
    class Backend:
        async def generate(self, **kwargs):
            snapshot = active_clock().snapshot
            await asyncio.sleep(0)
            assert active_clock().snapshot is snapshot
            seen.append((snapshot.session_id, kwargs['system']))
            return 'ok'
    await asyncio.gather(*(agent.generate_response(Backend(), 'm', 'hi', 'soul', 10, 0, session_id=sid) for sid in ['a', 'b']))
    assert {sid for sid, _ in seen} == {'a', 'b'}
    assert all("Today's date" not in system for _, system in seen)
    assert active_clock() is None
    manager.close()


async def test_captured_snapshot_survives_closed_store_without_new_clock(tmp_path):
    from agents.core.agent import Agent
    manager = store(tmp_path)
    before = manager.clock_snapshot('a')
    manager.close()
    agent = Agent('jarvis', {})
    agent._checkpoint_manager = manager
    class Backend:
        async def generate(self, **kwargs):
            assert 'September 01' in kwargs['system']
            assert "Today's date" not in kwargs['system']
            return 'ok'
    assert await agent.generate_response(Backend(), 'm', 'hi', 'soul', 10, 0, session_id='a', clock_snapshot=before) == 'ok'


async def test_late_child_cannot_commit_after_actual_agent_returns(tmp_path):
    import asyncio

    from agents.core.agent import Agent
    from agents.core.agent_runtime import AgentToolRuntime
    manager = store(tmp_path)
    before = manager.clock_snapshot('a')
    gate = asyncio.Event()
    runtime = AgentToolRuntime(object(), enabled=lambda: True, context_budget_tokens=lambda: 2400)
    tasks = []
    class Backend:
        async def generate(self, **kwargs):
            async def late():
                await gate.wait()
                messages = [{'role': 'system', 'content': kwargs['system']},
                            {'role': 'tool', 'content': 'x' * 20000}]
                return await runtime._compact_context(messages, set(), model='m', max_tokens=10,
                                                      agent_id='jarvis', event_sink=None)
            tasks.append(asyncio.create_task(late()))
            return 'answer'
    agent = Agent('jarvis', {})
    agent._checkpoint_manager = manager
    assert await agent.generate_response(Backend(), 'm', 'hi', 'soul', 10, 0, session_id='a') == 'answer'
    gate.set()
    assert await tasks[0] is False
    assert manager.clock_snapshot('a') == before
    manager.close()


async def test_failed_commit_stops_actual_text_stream_and_process_callers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agents.core.context_compressor import ContextCompressor
    from agents.core.orchestrator import Orchestrator
    manager = store(tmp_path)
    original = manager.clock_snapshot('a')
    calls = []
    async def compact(*args, **kwargs):
        return {'compressed': True, 'summary': 'fits', 'covered': 1, 'kept': [], 'kept_first': []}
    monkeypatch.setattr(ContextCompressor, 'compact', compact)
    monkeypatch.setattr(manager, 'commit_clock', lambda *a, **k: None)
    stub = history_stub(manager)
    async def huge(*args):
        return [{'role': 'user', 'content': 'x' * 100000}]
    stub.memory.get_history = huge
    async def turn(*args, **kwargs):
        history = await Orchestrator._history_for_prompt(stub, 10)
        calls.append(history)  # cannot reach model dispatch
        return 'wrong'
    owner = SimpleNamespace(_handle_input=turn, _handle_input_stream=turn,
                            _call_agents_parallel=turn, agents={'jarvis': object()})
    text = await Orchestrator.handle_input(owner, 'hello')
    stream = await Orchestrator.handle_input_stream(owner, 'hello')
    process = await Orchestrator.process(owner, 'hello')
    assert text == stream == process
    assert 'context' in text.lower() and len(text) < 200
    assert not calls
    assert manager.clock_snapshot('a') == original
    manager.close()


async def test_direct_agent_preserves_creator_metadata(tmp_path):
    from agents.core.agent import Agent
    manager = store(tmp_path)
    agent = Agent('friday', {})
    agent._checkpoint_manager = manager
    class Backend:
        async def generate(self, **kwargs):
            return 'ok'
    await agent.generate_response(Backend(), 'm', 'hello', 'soul', 10, 0, session_id='fresh')
    assert manager._conn.execute("SELECT agent_id FROM sessions WHERE id='fresh'").fetchone()[0] == 'friday'
    manager.close()


async def test_child_updated_snapshot_still_revokes_and_sibling_is_isolated(tmp_path):
    import asyncio

    from agents.core.agent import Agent
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.conversation_clock import active_clock
    manager = store(tmp_path)
    initial = manager.clock_snapshot('a')
    committed = asyncio.Event()
    after_return = asyncio.Event()
    tasks = []
    runtime = AgentToolRuntime(object(), enabled=lambda: True, context_budget_tokens=lambda: 2400)
    class Backend:
        async def generate(self, **kwargs):
            async def compact():
                rows = [{'role': 'system', 'content': kwargs['system']}, {'role': 'tool', 'content': 'x' * 20000}]
                return await runtime._compact_context(rows, set(), model='m', max_tokens=10,
                                                      agent_id='jarvis', event_sink=None)
            async def child():
                assert await compact()
                assert active_clock().snapshot.revision == 1
                committed.set()
                await after_return.wait()
                assert not await compact()
            tasks.append(asyncio.create_task(child()))
            await committed.wait()
            assert active_clock().snapshot == initial
            return 'answer'
    agent = Agent('jarvis', {})
    agent._checkpoint_manager = manager
    assert await agent.generate_response(Backend(), 'm', 'hi', 'soul', 10, 0, session_id='a') == 'answer'
    after_return.set()
    await tasks[0]
    assert manager.clock_snapshot('a').revision == 1
    manager.close()


async def test_unmanaged_agent_late_child_retains_legacy_generation():
    import asyncio

    from agents.core.agent import Agent
    gate = asyncio.Event()
    tasks = []
    agent = Agent('jarvis', {})
    class ChildBackend:
        async def generate(self, **kwargs):
            return 'child answer'
    class ParentBackend:
        async def generate(self, **kwargs):
            async def late():
                await gate.wait()
                return await agent.generate_response(ChildBackend(), 'm', 'child', 'soul', 10, 0, session_id='a')
            tasks.append(asyncio.create_task(late()))
            return 'parent answer'
    assert await agent.generate_response(ParentBackend(), 'm', 'parent', 'soul', 10, 0, session_id='a') == 'parent answer'
    gate.set()
    assert await tasks[0] == 'child answer'


async def test_closed_managed_ancestry_cannot_mint_unmanaged_scope(tmp_path):
    import asyncio

    import pytest

    from agents.core.agent import Agent
    from agents.core.conversation_clock import CompactionClockRefused
    manager = store(tmp_path)
    owner = Agent('jarvis', {})
    owner._checkpoint_manager = manager
    child = Agent('friday', {})
    gate = asyncio.Event()
    tasks = []
    class ChildBackend:
        async def generate(self, **kwargs):
            raise AssertionError('expired inherited request must not dispatch')
    class ParentBackend:
        async def generate(self, **kwargs):
            async def late():
                await gate.wait()
                return await child.generate_response(ChildBackend(), 'm', 'child', 'soul', 10, 0, session_id='a')
            tasks.append(asyncio.create_task(late()))
            return 'parent'
    assert await owner.generate_response(ParentBackend(), 'm', 'parent', 'soul', 10, 0, session_id='a') == 'parent'
    gate.set()
    with pytest.raises(CompactionClockRefused):
        await tasks[0]
    manager.close()
