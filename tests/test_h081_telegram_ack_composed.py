"""Unconfirmed Telegram acknowledgements reach durable and turn-level fences."""
from __future__ import annotations

import httpx
import pytest

from agents.core.channels import delivery_ledger, outbound_safety
from agents.core.channels.manager import ChannelManager
from agents.core.channels.telegram import TelegramChannel
from tests.test_telegram_streaming import _orchestrator


@pytest.fixture
def ack_store(tmp_path, monkeypatch):
    store = delivery_ledger.ReliabilityStore(tmp_path / 'delivery.sqlite')
    monkeypatch.setattr(delivery_ledger, 'store', lambda: store)
    monkeypatch.setattr(outbound_safety, '_known_redactor', None)
    try:
        yield store
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('plain', [False, True])
async def test_actual_adapter_missing_ack_is_unknown_and_key_blocks_replay(ack_store, plain):
    calls = []

    async def transport(request):
        calls.append(request.url.path.rsplit('/', 1)[-1])
        return httpx.Response(200, json={'ok': True, 'result': {}})

    channel = TelegramChannel(token='test-token')
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    manager = ChannelManager()
    manager.register(channel)
    try:
        assert await manager.send('telegram', 'delivery probe', chat_id=42, plain=plain,
                                  voice=False, delivery_key='ack:composed') is False
        assert ack_store.recent(1)[0]['state'] == 'unknown'
        assert await manager.send('telegram', 'delivery probe', chat_id=42, plain=plain,
                                  voice=False, delivery_key='ack:composed') is False
        assert calls == ['sendMessage']
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_later_unconfirmed_chunk_is_partial_and_never_replayed(ack_store):
    calls = []

    async def transport(request):
        calls.append(request.url.path.rsplit('/', 1)[-1])
        body = {'ok': True, 'result': {'message_id': 9}} if len(calls) == 1 else {'ok': True}
        return httpx.Response(200, json=body)

    channel = TelegramChannel(token='test-token')
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    manager = ChannelManager()
    manager.register(channel)
    try:
        text = 'word ' * 2500
        assert await manager.send('telegram', text, chat_id=42, plain=True,
                                  voice=False, delivery_key='ack:partial') is False
        assert ack_store.recent(1)[0]['state'] == 'partial'
        assert await manager.send('telegram', text, chat_id=42, plain=True,
                                  voice=False, delivery_key='ack:partial') is False
        assert calls == ['sendMessage', 'sendMessage']
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['malformed', 'timeout', 'server'])
async def test_real_draft_uncertainty_never_falls_back_to_whole_turn(ack_store, monkeypatch, failure):
    calls = []

    async def transport(request):
        calls.append(request.url.path.rsplit('/', 1)[-1])
        if failure == 'timeout':
            raise httpx.ReadTimeout('response unavailable', request=request)
        if failure == 'server':
            return httpx.Response(503, json={'ok': False})
        return httpx.Response(200, json={'ok': True, 'result': {}})

    async def forbidden(*args, **kwargs):
        pytest.fail('uncertain draft reached post-delivery media or voice')

    channel = TelegramChannel(token='test-token')
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(channel, '_after_reply', forbidden)
    monkeypatch.setattr(channel, '_deliver_media', forbidden)
    orch, captured = _orchestrator(channel)
    try:
        assert await orch.channel_handler('hello', channel='telegram', chat_id='42', sender='42') == 'streamed reply'
        assert captured['sent'] == []
        assert calls == ['sendMessage']
    finally:
        await channel.client.aclose()
