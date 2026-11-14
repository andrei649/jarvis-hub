"""A copied Telegram group-help command passes the real addressing/access gates."""
from types import SimpleNamespace

import pytest

from agents.core import slash_access
from agents.core.channels.group_policy import ANSWER, DROP, GroupPolicy, gate_message
from agents.core.channels.manager import ChannelManager
from agents.core.channels.telegram import TelegramChannel
from agents.core.commands import Principal, build_default_registry


@pytest.mark.asyncio
async def test_copied_guest_help_command_addresses_verified_bot_without_widening_access(monkeypatch):
    monkeypatch.setattr(slash_access, '_policy', lambda: {})
    channel = TelegramChannel(token='offline')
    manager = ChannelManager()
    manager.register(channel)
    registry = build_default_registry()
    orch = SimpleNamespace(commands=registry, channel_manager=manager)
    principal = Principal(channel='telegram', sender='42', chat='-1001', scope='group')
    channel._running = True
    channel._bot_id = 999
    channel._bot_username = 'nerva_bot'
    channel._owner_once_generation = 'verified-test-generation'
    channel._verified_bot_generation = channel._owner_once_generation
    try:
        outcome = await registry.dispatch('/help', orch=orch, principal=principal)
        assert outcome.status == 'answered'
        commands = [line.split()[0] for line in outcome.reply.splitlines() if line.startswith('/')]
        assert set(commands) == {'/help@nerva_bot', '/whoami@nerva_bot'}
        decision = gate_message(GroupPolicy(), chat_type='supergroup', chat_id=-1001,
                                text=commands[0], bot_id=999, bot_username='nerva_bot')
        assert decision.action == ANSWER
        copied = await registry.dispatch(decision.text, orch=orch, principal=principal)
        assert copied.status == 'answered'
        denied = await registry.dispatch('/pause@nerva_bot', orch=orch, principal=principal)
        assert denied.status == 'refused'
        assert gate_message(GroupPolicy(), chat_type='supergroup', chat_id=-1001,
                            text='/help@another_bot', bot_id=999,
                            bot_username='nerva_bot').action == DROP
    finally:
        channel._running = False
        await channel.client.aclose()
