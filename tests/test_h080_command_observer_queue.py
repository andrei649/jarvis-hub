"""Command dispatch respects the observer bus's captured loop and admission cap."""
import asyncio

import pytest

from agents.core.commands import CommandRegistry, Principal, SlashCommand
from agents.core.extensions import events


@pytest.mark.asyncio
async def test_command_burst_cannot_queue_unbounded_observers_on_a_paused_target_loop(monkeypatch):
    target = asyncio.new_event_loop()
    seen = []

    class Runtime:
        def observers(self, event):
            return ('watcher',) if event == 'command.started' else ()

        async def observe(self, extension_id, event, payload):
            seen.append((asyncio.get_running_loop(), payload))

    bus = events.ExtensionEventBus(runtime=Runtime(), loop=target, max_pending=2)
    monkeypatch.setattr(events, 'EXTENSION_EVENTS', bus)
    registry = CommandRegistry()
    registry.register(SlashCommand('probe', 'dispatch admission', lambda ctx: 'answered'))
    try:
        for _ in range(100):
            outcome = await registry.dispatch('/probe private arguments', orch=None,
                                              principal=Principal(admin=True))
            assert outcome.reply == 'answered' and outcome.status == 'answered'
        assert seen == []
        assert len(target._ready) == 2, 'only admitted deliveries may queue callbacks'
        assert bus.dropped == 98

        def flush():
            target.run_until_complete(asyncio.sleep(0))
            target.run_until_complete(bus.drain(timeout=1))

        await asyncio.to_thread(flush)
        assert len(seen) == 2
        assert all(loop is target and payload['command'] == 'probe' for loop, payload in seen)
        assert 'private' not in str([payload for _, payload in seen])
    finally:
        await bus.drain(timeout=1)
        target.close()
