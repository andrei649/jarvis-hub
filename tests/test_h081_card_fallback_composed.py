"""A real clarification turn must not repeat an uncertain/accepted native card."""

import asyncio

import pytest

from agents.core.channels import delivery_ledger
from tests.test_pending_input_native_transport import finish, native_host
from tests.test_pending_input_runtime import incoming


@pytest.mark.asyncio
@pytest.mark.parametrize('ledger_available', [False, True])
@pytest.mark.parametrize('failure', ['missing_ack', 'binding_refused'])
async def test_real_turn_does_not_repeat_native_prompt(tmp_path, monkeypatch, ledger_available, failure):
    store = delivery_ledger.ReliabilityStore(tmp_path / 'receipts.sqlite')
    monkeypatch.setattr(delivery_ledger, 'store', lambda: store if ledger_available else None)
    orch, _cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(
        tmp_path, receipt='701' if failure == 'missing_ack' else 701)
    runtime = orch._pending_input_service()
    if failure == 'binding_refused':
        monkeypatch.setattr(runtime.cards, 'bind', lambda *_args, **_kwargs: False)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        # Let the callback finish and enter either the old wait or the refusal path.
        for _ in range(3):
            await asyncio.sleep(0)
        prompt_posts = [body for method, body in requests
                        if method == 'sendMessage' and 'Choose a route' in body.get('text', '')]
        assert len(prompt_posts) == 1
        assert 'reply_markup' in prompt_posts[0]
        assert await asyncio.wait_for(task, 1) == 'Finished'
        assert answers[0][0]['result']['reason'] == 'prompt_delivery_failed'
        assert not runtime._card_tokens
    finally:
        await finish(orch, channel, task)
        store.close()


@pytest.mark.asyncio
async def test_real_preflight_refusal_keeps_plain_prompt_usable(tmp_path, monkeypatch):
    store = delivery_ledger.ReliabilityStore(tmp_path / 'receipts.sqlite')
    monkeypatch.setattr(delivery_ledger, 'store', lambda: store)
    orch, _cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    channel._pending_callback_generation = None
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        prompt_posts = [body for method, body in requests
                        if method == 'sendMessage' and 'Choose a route' in body.get('text', '')]
        assert len(prompt_posts) == 1 and 'reply_markup' not in prompt_posts[0]
        assert not task.done()
        assert await incoming(gateway, '2', message_thread_id=8) == ''
        assert await asyncio.wait_for(task, 1) == 'Finished'
        assert answers[0][0]['result']['user_response'] == 'Remote'
    finally:
        await finish(orch, channel, task)
        store.close()


@pytest.mark.asyncio
async def test_post_ack_ledger_failure_cannot_turn_into_plain_fallback(tmp_path, monkeypatch):
    store = delivery_ledger.ReliabilityStore(tmp_path / 'receipts.sqlite')
    monkeypatch.setattr(delivery_ledger, 'store', lambda: store)
    original = delivery_ledger.Delivery.finished
    calls = 0

    def fail_first_finish(delivery, ok, outcome=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError('receipt persistence failed after platform ACK')
        return original(delivery, ok, outcome)

    monkeypatch.setattr(delivery_ledger.Delivery, 'finished', fail_first_finish)
    orch, _cap, gateway, _server, _ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        assert await asyncio.wait_for(task, 1) == 'Finished'
        prompt_posts = [body for method, body in requests
                        if method == 'sendMessage' and 'Choose a route' in body.get('text', '')]
        assert len(prompt_posts) == 1 and 'reply_markup' in prompt_posts[0]
        assert answers[0][0]['result']['reason'] == 'prompt_delivery_failed'
        assert not orch._pending_input_service()._card_tokens
    finally:
        await finish(orch, channel, task)
        store.close()
