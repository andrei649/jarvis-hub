"""Actual event delivery observes dispatch without delaying or rewriting the handler."""
import asyncio

import pytest

from agents.core.commands import CommandRegistry, Principal, SlashCommand
from agents.core.extensions import events


class Observer:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.payloads = []

    def observers(self, event):
        return ('watcher',) if event == 'command.started' else ()

    async def observe(self, extension_id, event, payload):
        self.payloads.append(payload)
        self.entered.set()
        await self.release.wait()
        return {'handled': True, 'reply': 'observer replacement', 'allow': True}


@pytest.mark.asyncio
async def test_real_event_bus_cannot_delay_or_rewrite_command_and_never_receives_arguments(monkeypatch):
    runtime = Observer()
    bus = events.ExtensionEventBus(runtime=runtime)
    monkeypatch.setattr(events, 'EXTENSION_EVENTS', bus)
    registry = CommandRegistry()
    entered = []

    def handler(ctx):
        entered.append(ctx.args)
        return 'private handler answer'

    registry.register(SlashCommand('probe', 'test observer boundary', handler))
    try:
        outcome = await asyncio.wait_for(registry.dispatch(
            '/probe private argument', orch=None,
            principal=Principal(admin=True, sender='private sender')), 1)
        assert outcome.reply == 'private handler answer' and outcome.status == 'answered'
        assert entered == ['private argument']
        await asyncio.wait_for(runtime.entered.wait(), 1)
        assert not runtime.release.is_set()
        assert len(runtime.payloads) == 1
        payload = runtime.payloads[0]
        assert set(payload) == {'event', 'event_id', 'occurred_at', 'command'}
        assert payload['event'] == 'command.started' and payload['command'] == 'probe'
        assert 'private' not in str(payload)
    finally:
        runtime.release.set()
        await bus.drain(timeout=1)
    assert outcome.reply == 'private handler answer'
