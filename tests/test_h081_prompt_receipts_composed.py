"""Actual Telegram card acknowledgments become metadata-only manager receipts."""

import httpx
import pytest

from agents.core.channels.manager import ChannelManager
from agents.core.channels.telegram import TelegramChannel
from tests.test_h081_telegram_ack_composed import ack_store  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected_id,state', [
    ('valid', 19, 'sent'), ('missing', None, 'unknown'),
    ('boolean', None, 'unknown'), ('refused', None, 'failed'),
    ('timeout', None, 'unknown'), ('later_missing', None, 'partial'),
    ('stale', None, 'partial'), ('not_running', None, 'failed'),
    ('bad_json', None, 'unknown'),
    ('unexpected', None, 'unknown'),
])
async def test_real_card_transport_preserves_native_ack_and_records_outcome(ack_store, kind, expected_id, state):
    requests = []

    async def transport(request):
        requests.append(request)
        if kind == 'timeout':
            raise httpx.ReadTimeout('response lost', request=request)
        if kind == 'unexpected':
            raise RuntimeError('unexpected failure after transport entered')
        if kind == 'refused':
            return httpx.Response(403, json={'ok': False, 'error_code': 403,
                                           'description': 'Forbidden: bot was blocked by the user'})
        if kind == 'bad_json':
            return httpx.Response(200, content=b'not JSON')
        if kind == 'later_missing':
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 19} if len(requests) == 1 else {}})
        if kind == 'stale':
            channel._running = False
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 19}})
        result = {'message_id': 19} if kind == 'valid' else {'message_id': True} if kind == 'boolean' else {}
        return httpx.Response(200, json={'ok': True, 'result': result})

    channel = TelegramChannel(token='test-token')
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = kind != 'not_running'
    channel._pending_callback_generation = object()
    manager = ChannelManager()
    manager.register(channel)
    try:
        receipt = await manager.send_pending_card(
            'telegram', 'word ' * 1000 if kind == 'later_missing' else 'Private card body',
            {'inline_keyboard': [[{'text': 'Choose', 'callback_data': 'private-binding-token'}]]},
            chat_id=42,
        )
        assert receipt == expected_id
        assert len(requests) == (2 if kind == 'later_missing' else 0 if kind == 'not_running' else 1)
        rows = ack_store.recent(50)
        assert len(rows) == 1
        assert rows[0]['state'] == state
        assert rows[0]['channel'] == 'telegram' and rows[0]['target'] == '42'
        assert 'Private card body' not in str(rows)
        assert 'private-binding-token' not in str(rows)
        assert rows[0]['keyed'] is False
    finally:
        await channel.client.aclose()
