"""Delivered owner-once waits preserve their actual ending without granting execution."""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from dataclasses import replace

import pytest

from agents.core.approval_outcomes import close_approval_turn, current_approval_turn
from agents.core.autonomy import owner_once
from tests.test_h485_owner_once_actuation import (
    _callback as terminal_callback,
)
from tests.test_h485_owner_once_actuation import (
    _owner_runtime,
    _wait_for_offer,
    runtime,  # noqa: F401
)
from tests.test_h485_owner_once_prompts import _callback, _runtime
from tests.test_h485_owner_once_queue import _denied, queue  # noqa: F401


async def test_delivered_hard_expiry_returns_observational_timeout(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        result = await prompts.request(task_id, digest, check=lambda: True, timeout=0.02)
        assert sent.is_set()
        assert type(result) is owner_once.OwnerOnceWaitOutcome
        assert result.state == 'timeout'
        forged_task = replace(queue.get(task_id), decided_by='owner_once',
                              decision='owner-deny',
                              human_decision={'action': 'reject', 'by': 'owner_once',
                                              'id': 'forged'})
        assert prompts.consume_outcome(result, forged_task) == 'timeout'
        assert queue.get(task_id).status == 'rejected'
        assert not channel.owner_once_pending(_callback(cards))


async def test_delivered_source_withdrawal_returns_promptly(queue):
    async with _runtime(queue) as (prompts, _channel, task_id, digest, sent, _cards, _acks, auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        auth[0] = False
        result = await asyncio.wait_for(pending, 0.5)
        assert type(result) is owner_once.OwnerOnceWaitOutcome
        assert result.state == 'withdrawn'
        assert prompts.consume_outcome(result, queue.get(task_id)) == 'withdrawn'
        assert queue.get(task_id).status == 'rejected'


async def test_authenticated_committed_deny_is_distinct_and_forged_result_is_rejected(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        await channel._handle_update({'callback_query': _callback(cards, choice='r')})
        result = await asyncio.wait_for(pending, 1)
        task = queue.get(task_id)
        assert type(result) is owner_once.OwnerOnceWaitOutcome
        assert result.state == 'denied'
        assert task.status == 'rejected' and task.human_decision['action'] == 'reject'
        assert task.human_decision['id'] == result.decision_id
        assert prompts.consume_outcome(replace(result, decision_id='0' * 32), task) is None
        assert prompts.consume_outcome(replace(result, nonce='f' * 32), task) is None
        turn = current_approval_turn()
        later_id, later_digest, later_token = _denied(queue, turn)
        later_offer = None
        try:
            later_offer = queue.offer_owner_once(
                later_id, later_digest, turn=turn, live_check=lambda: True)
            assert later_offer is not None
            forged_later = replace(result, task_id=later_id, nonce=later_offer.nonce)
            assert prompts.consume_outcome(forged_later, queue.get(later_id)) is None
        finally:
            if later_offer is not None:
                queue.revoke_owner_once(later_offer)
            close_approval_turn(turn, later_token)
        assert prompts.consume_outcome(result, task) == 'denied'


async def test_pre_delivery_failure_still_returns_none(queue):
    async with _runtime(queue) as (prompts, channel, task_id, digest, _sent, _cards, _acks, _auth):
        async def undelivered(_chat_id, _card):
            raise RuntimeError('synthetic delivery failure')

        channel.send_owner_once_card = undelivered
        assert await prompts.request(task_id, digest, check=lambda: True) is None
        assert queue.get(task_id).status == 'rejected'


async def test_genuine_origin_cancellation_still_propagates(queue):
    async with _runtime(queue) as (prompts, _channel, task_id, digest, sent, _cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert queue.get(task_id).status == 'rejected'


async def test_committed_deny_survives_delayed_wake_without_forging_claim(queue, monkeypatch):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        original = prompts._wake

        def delayed(prompt, result):
            if type(result) is owner_once.OwnerOnceWaitOutcome and result.state == 'denied':
                failed = Future()
                asyncio.get_running_loop().call_later(0.1, failed.set_result, False)
                return failed
            return original(prompt, result)

        monkeypatch.setattr(prompts, '_wake', delayed)
        cb = _callback(cards, choice='r')
        callback = asyncio.create_task(prompts.callback(cb['data'].split(':')[1], 'deny',
                                                        chat_id=99, user_id=99, message_id=17))
        result = await asyncio.wait_for(pending, 0.5)
        assert type(result) is owner_once.OwnerOnceWaitOutcome
        assert result.state == 'denied'
        assert prompts.consume_outcome(result, queue.get(task_id)) == 'denied'
        await callback
        assert queue.get(task_id).human_decision['action'] == 'reject'


async def test_committed_accept_with_failed_handoff_returns_held_without_claim(queue, monkeypatch):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        original = prompts._wake

        def undeliverable(prompt, result):
            if type(result) is owner_once.OwnerOnceClaim:
                failed = Future()
                failed.set_result(False)
                return failed
            return original(prompt, result)

        monkeypatch.setattr(prompts, '_wake', undeliverable)
        cb = _callback(cards)
        assert await prompts.callback(cb['data'].split(':')[1], 'once',
                                      chat_id=99, user_id=99, message_id=17) is None
        result = await asyncio.wait_for(pending, 1)
        assert type(result) is owner_once.OwnerOnceWaitOutcome
        assert result.state == 'held'
        assert prompts.consume_outcome(result, queue.get(task_id)) == 'held'
        assert not queue.verify_owner_once_terminal_approval(task_id, check=lambda _receipt: True)


async def test_real_terminal_delivered_timeout_has_distinct_handback(runtime, monkeypatch, tmp_path):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, _channel, _sandbox, delivered, _finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        from datetime import datetime, timedelta

        from agents.core.autonomy import owner_once_prompts

        # The mock's delivered event fires before sendMessage returns. Wait for
        # the durable receipt so this tests expiry of a delivered owner wait.
        acknowledged = asyncio.Event()
        mark_delivered = queue.mark_owner_once_delivered

        def capture_ack(*args, **kwargs):
            result = mark_delivered(*args, **kwargs)
            if result:
                acknowledged.set()
            return result

        monkeypatch.setattr(queue, 'mark_owner_once_delivered', capture_ack)
        await _wait_for_offer(delivered, asyncio.Event(), answers)
        await asyncio.wait_for(acknowledged.wait(), 2)
        assert not invocation.done()
        [prompt] = worker._owner_once_prompts._pending.values()
        expired_at = datetime.fromisoformat(prompt.offer.deadline_at) + timedelta(microseconds=1)

        # Move only this request's wall clock beyond its recorded deadline;
        # the real request loop, outcome validator and terminal handback run.
        class ExpiredDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return expired_at

        monkeypatch.setattr(owner_once_prompts, 'datetime', ExpiredDateTime)
        await asyncio.wait_for(invocation, 2)
        assert answers[0]['reason'] == 'approval_timed_out'
        assert answers[0]['approval_outcome'] == 'expired_unanswered'
        assert answers[0]['guardian']['consecutive_denials'] == 1
        assert spawns == [] and queue.get(answers[0]['task_id']).human_decision is None


async def test_real_terminal_withdrawal_has_distinct_handback(runtime, monkeypatch, tmp_path):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, _channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        owners['autonomy.owner_user_ids'] = [98]
        await asyncio.wait_for(invocation, 1)
        assert answers[0]['reason'] == 'approval_withdrawn'
        assert answers[0]['approval_outcome'] == 'withdrawn'
        assert answers[0]['guardian']['consecutive_denials'] == 1
        assert spawns == [] and queue.get(answers[0]['task_id']).human_decision is None


async def test_real_terminal_owner_deny_has_distinct_handback(runtime, monkeypatch, tmp_path):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({'callback_query': terminal_callback(cards, 'r')})
        await asyncio.wait_for(invocation, 2)
        assert answers[0]['reason'] == 'owner_denied'
        assert answers[0]['approval_outcome'] == 'denied'
        assert answers[0]['guardian']['consecutive_denials'] == 1
        task = queue.get(answers[0]['task_id'])
        assert task.status == 'rejected' and task.human_decision['action'] == 'reject'
        assert spawns == []


async def test_forged_observational_denial_cannot_change_terminal_provenance(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, _channel, _sandbox, _delivered, _finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        prompts = worker._owner_once_prompts
        from agents.core.autonomy import terminal_review

        reviewed_status = []
        original_review = terminal_review.review_terminal_task

        async def inspect_review(*args, **kwargs):
            answer = await original_review(*args, **kwargs)
            reviewed_status.append(queue.get(kwargs['task_id']).status)
            return answer

        monkeypatch.setattr(terminal_review, 'review_terminal_task', inspect_review)

        async def forged(task_id, _digest, *, check, timeout=120):
            return owner_once.OwnerOnceWaitOutcome('denied', task_id, 'f' * 32, 'f' * 32)

        monkeypatch.setattr(prompts, 'request', forged)
        await asyncio.wait_for(invocation, 2)
        assert answers[0]['reason'] == 'guardian_denied'
        assert 'approval_outcome' not in answers[0]
        assert reviewed_status == ['rejected']
        task = queue.get(answers[0]['task_id'])
        assert task.status == 'rejected' and task.human_decision is None
        assert spawns == []


async def test_real_terminal_accepted_but_unhanded_claim_is_held_without_effect(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, channel, _sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        prompts = worker._owner_once_prompts
        original = prompts._wake

        def undeliverable(prompt, result):
            if type(result) is owner_once.OwnerOnceClaim:
                failed = Future()
                failed.set_result(False)
                return failed
            return original(prompt, result)

        monkeypatch.setattr(prompts, '_wake', undeliverable)
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({'callback_query': terminal_callback(cards)})
        await asyncio.wait_for(invocation, 2)
        assert answers[0]['reason'] == 'terminal_execution_held'
        assert answers[0]['approval_outcome'] == 'approved'
        assert answers[0]['guardian']['consecutive_denials'] == 1
        task = queue.get(answers[0]['task_id'])
        assert task.status == 'rejected'
        assert not queue.verify_owner_once_terminal_approval(task.id, check=lambda _receipt: True)
        assert spawns == []


async def test_cross_loop_committed_deny_outlives_delayed_wake_and_source_withdrawal(
    queue, monkeypatch,
):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, auth):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever)
        thread.start()
        pending = asyncio.run_coroutine_threadsafe(
            prompts.request(task_id, digest, check=lambda: True), loop)
        try:
            await asyncio.wait_for(sent.wait(), 2)
            ready = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop)
            await asyncio.wait_for(asyncio.wrap_future(ready), 1)
            entered = asyncio.Event()
            original = prompts._wake

            def delayed(prompt, result):
                if type(result) is owner_once.OwnerOnceWaitOutcome and result.state == 'denied':
                    withheld = Future()
                    entered.set()
                    asyncio.get_running_loop().call_later(0.1, withheld.set_result, False)
                    return withheld
                return original(prompt, result)

            monkeypatch.setattr(prompts, '_wake', delayed)
            cb = _callback(cards, choice='r')
            callback = asyncio.create_task(prompts.callback(
                cb['data'].split(':')[1], 'deny', chat_id=99, user_id=99, message_id=17))
            await asyncio.wait_for(entered.wait(), 1)
            auth[0] = False
            result = await asyncio.wait_for(asyncio.wrap_future(pending), 1)
            assert type(result) is owner_once.OwnerOnceWaitOutcome
            assert result.state == 'denied'
            assert prompts.consume_outcome(result, queue.get(task_id)) == 'denied'
            await callback
            assert queue.get(task_id).human_decision['action'] == 'reject'
        finally:
            if not pending.done():
                pending.cancel()
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 1)
            loop.close()


async def test_durable_owner_deny_precedes_callback_publication_at_deadline(queue, monkeypatch):
    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True,
                                                       timeout=0.3))
        await asyncio.wait_for(sent.wait(), 1)
        cb = _callback(cards, choice='r')
        assert channel.owner_once_pending(cb)
        committed = threading.Event()
        release = threading.Event()
        reject = queue.reject_owner_once

        def pause_after_commit(*args, **kwargs):
            result = reject(*args, **kwargs)
            if result:
                committed.set()
                assert release.wait(2), 'test barrier was not released'
            return result

        monkeypatch.setattr(queue, 'reject_owner_once', pause_after_commit)
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever)
        thread.start()
        callback = asyncio.run_coroutine_threadsafe(
            prompts.callback(cb['data'].split(':')[1], 'deny',
                             chat_id=99, user_id=99, message_id=17), loop)
        try:
            assert await asyncio.to_thread(committed.wait, 1), 'real queue CAS must commit'
            task = queue.get(task_id)
            assert task.status == 'rejected' and task.decided_by == 'owner_once'
            assert task.human_decision['action'] == 'reject'
            observed = await asyncio.wait_for(pending, 1)
            assert type(observed) is owner_once.OwnerOnceWaitOutcome
            assert observed.state == 'timeout', 'publication remains behind the barrier'
            assert prompts.consume_outcome(observed, queue.get(task_id)) == 'denied'
        finally:
            release.set()
            await asyncio.wait_for(asyncio.wrap_future(callback), 2)
            if not pending.done():
                pending.cancel()
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 1)
            loop.close()
