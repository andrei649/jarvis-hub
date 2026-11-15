"""Restart admission blocks new effects while owned work can finish naturally."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.core.commands import SlashCommand, build_default_registry
from agents.core.orchestrator import Orchestrator
from agents.core.restart_runtime import runtime_for


@pytest.mark.asyncio
async def test_closed_ingress_never_enters_pending_or_model():
    orch = Orchestrator.__new__(Orchestrator)
    entered = []

    async def admitted(*args, **kwargs):
        entered.append(args)

    orch._channel_handler_admitted = admitted
    runtime = runtime_for(orch)
    token = runtime.close_admission()
    reply = await orch.channel_handler('hello', 'telegram')
    assert 'restart' in reply
    assert not entered
    assert runtime.snapshot()['active'] == 0
    assert runtime.reopen(token)
    await orch.channel_handler('hello', 'telegram')
    assert len(entered) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('text,channel', [('/pause', 'telegram'), ('/resume', 'telegram'),
                                         ('/stop', 'telegram'), ('!resume', 'slack'),
                                         ('/nerva resume', 'slack')])
async def test_builtin_recovery_reaches_original_access_gate(text, channel):
    orch = Orchestrator.__new__(Orchestrator)
    orch.commands = build_default_registry()
    runtime = runtime_for(orch)
    runtime.close_admission()

    async def admitted(*args, **kwargs):
        assert kwargs['sender'] == 'guest'
        assert runtime.snapshot()['active'] > 0
        async with orch.turn_lease('control') as held:
            assert held
        return 'original access gate still judges this sender'

    orch._channel_handler_admitted = admitted
    assert await orch.channel_handler(text, channel, sender='guest') == (
        'original access gate still judges this sender')
    assert runtime.snapshot()['active'] == 0


@pytest.mark.asyncio
async def test_replacement_named_pause_does_not_gain_control_admission():
    orch = Orchestrator.__new__(Orchestrator)
    orch.commands = build_default_registry()
    orch.commands.unregister(orch.commands.get('pause'))
    orch.commands.register(SlashCommand('pause', 'not builtin', lambda ctx: 'unsafe'))
    runtime_for(orch).close_admission()
    assert 'restart' in await orch.channel_handler('/pause')


@pytest.mark.asyncio
async def test_waiting_standalone_turn_rechecks_after_lock():
    orch = Orchestrator.__new__(Orchestrator)
    orch._turn_lease_max_wait = 1
    lock = asyncio.Lock()
    await lock.acquire()
    orch._turn_leases = {'session': lock}
    started = asyncio.Event()

    async def queued():
        started.set()
        async with orch.turn_lease('session') as held:
            return held

    task = asyncio.create_task(queued())
    await started.wait()
    await asyncio.sleep(0)
    runtime = runtime_for(orch)
    runtime.close_admission()
    lock.release()
    assert await task is False
    assert not lock.locked()
    assert runtime.snapshot()['active'] == 0


@pytest.mark.asyncio
async def test_live_ingress_can_complete_nested_turn_after_closure():
    orch = Orchestrator.__new__(Orchestrator)
    runtime = runtime_for(orch)
    started, finish = asyncio.Event(), asyncio.Event()

    async def admitted(*args, **kwargs):
        started.set()
        await finish.wait()
        async with orch.turn_lease('nested') as held:
            assert held
        return 'done'

    orch._channel_handler_admitted = admitted
    task = asyncio.create_task(orch.channel_handler('hello'))
    await started.wait()
    runtime.close_admission()
    assert runtime.snapshot()['active'] > 0
    finish.set()
    assert await task == 'done'
    assert runtime.snapshot()['active'] == 0


@pytest.mark.asyncio
async def test_cancelled_ingress_releases_admission():
    orch = Orchestrator.__new__(Orchestrator)
    started = asyncio.Event()

    async def admitted(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    orch._channel_handler_admitted = admitted
    task = asyncio.create_task(orch.channel_handler('hello'))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime_for(orch).snapshot()['active'] == 0


def test_census_uses_running_queue_and_all_loaded_lane_probes():
    orch = Orchestrator.__new__(Orchestrator)
    usage = {'running': 0, 'queued': 1}
    orch.channel_manager = SimpleNamespace(channels={
        'first': SimpleNamespace(), 'second': SimpleNamespace(lane_usage=lambda: usage)})
    assert orch.restart_work_pending()
    usage['queued'] = 0
    seen = []
    orch.autonomy_queue = SimpleNamespace(list=lambda **kw: seen.append(kw) or [])
    assert not orch.restart_work_pending()
    assert seen == [{'status': 'running', 'limit': 1}]
    usage['running'] = 'unknown'
    with pytest.raises(ValueError):
        orch.restart_work_pending()


@pytest.mark.asyncio
async def test_actual_telegram_recovery_preserves_owner_gate(tmp_path, monkeypatch):
    from agents.core import estop, settings_db
    from tests.test_h058_slash_access import GUEST_ID, OWNER_ID, _Hub

    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    monkeypatch.setattr(settings_db, '_wal_set', False)
    calls = []
    monkeypatch.setattr(estop, 'disengage', lambda: calls.append('resume') or True)
    hub = _Hub(tmp_path)
    runtime_for(hub.orch).close_admission()
    try:
        guest = await hub.say('/resume', user=GUEST_ID)
        assert 'owner' in guest.lower()
        assert calls == []
        owner = await hub.say('/resume', user=OWNER_ID)
        assert 'lifted' in owner.lower()
        assert calls == ['resume']
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_inherited_session_context_is_counted_and_not_drain_authority():
    orch = Orchestrator.__new__(Orchestrator)
    runtime = runtime_for(orch)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def child():
        async with orch.turn_lease('shared') as held:
            assert held
            entered.set()
            await finish.wait()

    async with orch.turn_lease('shared') as held:
        assert held
        task = asyncio.create_task(child())
        await entered.wait()
    assert runtime.snapshot()['active'] == 1
    runtime.close_admission()
    finish.set()
    await task
    assert runtime.snapshot()['active'] == 0
    async with orch.turn_lease('shared') as held:
        assert not held


@pytest.mark.asyncio
async def test_real_parallel_model_path_explicitly_binds_both_child_tasks():
    from tests.test_reasoning_timeout import _Agent, _orch

    class Agent(_Agent):
        async def process(self, text, context):
            async with orch.turn_lease('tool-continuation') as held:
                return 'finished' if held else 'wrongly refused'

    orch = _orch(agents={'jarvis': Agent()})
    runtime = runtime_for(orch)
    lease = runtime.acquire('subagent')
    try:
        with lease.bind():
            runtime.close_admission()
            result = await orch._call_agents_parallel(['jarvis'], 'finish admitted work', {})
            assert result == {'jarvis': 'finished'}
    finally:
        lease.release()
    assert runtime.snapshot()['active'] == 0
