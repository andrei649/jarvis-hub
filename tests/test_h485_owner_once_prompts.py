"""Real queue and Telegram delivery bind a reply to one live origin."""

import asyncio
import json
import threading
from concurrent.futures import Future
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from agents.core.approval_outcomes import close_approval_turn
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.telegram import TelegramChannel
from agents.core.owner_once_context import (
    OwnerReplySource,
    bind_owner_reply_source,
    close_owner_reply_source,
)
from tests.test_h485_owner_once_queue import _denied, _turn, queue  # noqa: F401


@asynccontextmanager
async def _runtime(queue):
    from agents.core.autonomy.owner_once_prompts import OwnerOncePrompts

    delivered = asyncio.Event()
    cards, acknowledgements = [], []

    def transport(request):
        payload = json.loads(request.content)
        if request.url.path.endswith('/sendMessage'):
            cards.append(payload)
            delivered.set()
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 17}})
        acknowledgements.append(payload)
        return httpx.Response(200, json={'ok': True})

    channel = TelegramChannel('test-token')
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    authorized = [True]
    worker = SimpleNamespace(queue=queue)
    orch = SimpleNamespace(channels={'telegram': channel}, autonomy=worker)
    coordinator = SimpleNamespace(
        _orch=orch,
        _callback_is_owner=lambda chat_id, user_id: authorized[0] and chat_id == user_id == 99,
    )
    prompts = OwnerOncePrompts(coordinator)
    prompts.install(channel)
    turn = _turn()
    task_id, digest, turn_token = _denied(queue, turn)
    source = OwnerReplySource(channel, channel._owner_once_generation, 99, 99,
                              asyncio.current_task())
    source_token = bind_owner_reply_source(source)
    try:
        yield prompts, channel, task_id, digest, delivered, cards, acknowledgements, authorized
    finally:
        await channel.stop()
        close_owner_reply_source(source, source_token)
        close_approval_turn(turn, turn_token)


def _callback(cards, *, choice='a', message_id=17, user_id=99):
    nonce = cards[-1]['reply_markup']['inline_keyboard'][0][0]['callback_data'].split(':')[1]
    return {'id': 'tap', 'data': f'aut1:{nonce}:{choice}', 'from': {'id': user_id},
            'message': {'message_id': message_id, 'chat': {'id': 99}}}


async def test_delivered_exact_owner_callback_returns_one_private_claim(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        cb = _callback(cards)
        assert channel.owner_once_pending(cb)
        await channel._handle_update({'callback_query': cb})
        claim = await asyncio.wait_for(pending, 1)
        assert claim.task_id == task_id
        assert queue.get(task_id).decision == 'owner-once'
        assert queue.verify_owner_once_terminal_approval(task_id, check=lambda _receipt: True)
        assert not channel.owner_once_pending(cb)
        assert await prompts.callback(claim.nonce, 'once', chat_id=99, user_id=99,
                                      message_id=17) is None
        await asyncio.gather(*tuple(channel._owner_once_fast.values()))
        assert acks[0]['text'] == 'OK: once'


@pytest.mark.parametrize('field,value', [('message_id', 18), ('user_id', 98)])
async def test_wrong_owner_or_delivery_cannot_consume_prompt(queue, field, value):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        cb = _callback(cards, **{field: value})
        assert channel.owner_once_pending(cb) is False
        nonce = cb['data'].split(':')[1]
        assert await prompts.callback(nonce, 'once', chat_id=99,
                                      user_id=cb['from']['id'],
                                      message_id=cb['message']['message_id']) is None
        assert queue.get(task_id).status == 'blocked'
        await channel.stop()
        assert await asyncio.wait_for(pending, 1) is None
        assert queue.get(task_id).status == 'rejected'


async def test_real_waiting_chat_lane_consumes_only_registered_owner_reply(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, acks, _auth):
        completed = asyncio.Event()
        claims = []

        async def handler(_text, **_kwargs):
            claims.append(await prompts.request(task_id, digest, check=lambda: True))
            completed.set()

        channel.handler = handler
        channel._lanes = ChatLanes(name='owner-once-real-queue')
        await channel._deliver_turn(99, 99, 'run operation')
        await asyncio.wait_for(sent.wait(), 1)
        assert not completed.is_set()
        await channel._handle_update({'callback_query': _callback(cards)})
        await asyncio.wait_for(completed.wait(), 1)
        await asyncio.gather(*tuple(channel._owner_once_fast.values()))
        assert len(claims) == 1 and claims[0].task_id == task_id
        assert queue.get(task_id).decision == 'owner-once'
        assert acks[0]['text'] == 'OK: once'
        assert not prompts.claim_current(claims[0]), 'closed origin cannot authorize later dispatch'
        prompts.release_claim(claims[0])
        assert queue.get(task_id).status == 'rejected'


async def test_revocation_after_delivery_invalidates_reply_and_stop_settles_wait(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        auth[0] = False
        cb = _callback(cards)
        assert not channel.owner_once_pending(cb)
        assert await prompts.callback(cb['data'].split(':')[1], 'once', chat_id=99,
                                      user_id=99, message_id=17) is None
        await channel.stop()
        assert await asyncio.wait_for(pending, 1) is None
        assert queue.get(task_id).status == 'rejected'


async def test_owner_reject_wakes_only_after_exact_committed_decision(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        cb = _callback(cards, choice='r')
        await channel._handle_update({'callback_query': cb})
        assert await asyncio.wait_for(pending, 1) is None
        task = queue.get(task_id)
        assert task.status == 'rejected'
        assert task.human_decision['action'] == 'reject'
        await asyncio.gather(*tuple(channel._owner_once_fast.values()))
        assert acks[0]['text'] == 'OK: deny'


async def test_cancelling_origin_wait_revokes_offer_before_late_reply(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert queue.get(task_id).status == 'rejected'
        assert not channel.owner_once_pending(_callback(cards))


async def test_deadline_without_owner_reply_is_a_refusal(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        assert await prompts.request(task_id, digest, check=lambda: True, timeout=0.02) is None
        assert sent.is_set()
        assert queue.get(task_id).status == 'rejected'
        assert not channel.owner_once_pending(_callback(cards))


async def test_requested_cancellation_blocks_reply_before_waiter_cleanup(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        cb = _callback(cards)
        pending.cancel()
        try:
            assert channel.owner_once_pending(cb) is False
            assert await prompts.callback(cb['data'].split(':')[1], 'once', chat_id=99,
                                          user_id=99, message_id=17) is None
        finally:
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert queue.get(task_id).status == 'rejected'


async def test_stopping_generation_releases_accepted_claim_registry(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        cb = _callback(cards)
        await channel._handle_update({'callback_query': cb})
        claim = await asyncio.wait_for(pending, 1)
        assert prompts.claim_current(claim)
        await channel.stop()
        assert not prompts.claim_current(claim)
        assert prompts._claims == {}, 'stopped generations must release bounded registry capacity'


async def test_reply_refuses_a_stopped_request_loop_while_source_loop_stays_live(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever)
        thread.start()
        pending = asyncio.run_coroutine_threadsafe(
            prompts.request(task_id, digest, check=lambda: True), loop,
        )
        try:
            await asyncio.wait_for(sent.wait(), 2)
            # Barrier ensures the actual queue delivery binding is committed.
            ready = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop)
            await asyncio.wait_for(asyncio.wrap_future(ready), 1)
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 1)
            assert not thread.is_alive() and not loop.is_running()
            cb = _callback(cards)
            assert channel.owner_once_pending(cb) is False
            assert await prompts.callback(cb['data'].split(':')[1], 'once', chat_id=99,
                                          user_id=99, message_id=17) is None
            assert queue.get(task_id).status == 'blocked'
        finally:
            if not thread.is_alive():
                thread = threading.Thread(target=loop.run_forever)
                thread.start()
            pending.cancel()

            async def drain():
                tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
                await asyncio.gather(*tasks, return_exceptions=True)

            finished = asyncio.run_coroutine_threadsafe(drain(), loop)
            await asyncio.wait_for(asyncio.wrap_future(finished), 1)
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 1)
            loop.close()
        assert queue.get(task_id).status == 'rejected'


async def test_failed_waiter_delivery_revokes_accepted_grant_without_success_ack(queue, monkeypatch):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        cb = _callback(cards)
        original_wake = prompts._wake

        def undeliverable(prompt, result):
            # A stopped/closed request loop cannot confirm receipt. Keep the
            # actual queue CAS, then exercise the transport handoff failure.
            if result is not None:
                failed = Future()
                failed.set_result(False)
                return failed
            return original_wake(prompt, result)

        monkeypatch.setattr(prompts, '_wake', undeliverable)
        assert await prompts.callback(cb['data'].split(':')[1], 'once', chat_id=99,
                                      user_id=99, message_id=17) is None
        assert queue.get(task_id).status == 'rejected'
        assert not queue.verify_owner_once_terminal_approval(task_id, check=lambda _receipt: True)
        assert await asyncio.wait_for(pending, 1) is None
