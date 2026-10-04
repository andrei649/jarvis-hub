"""Native owner-once text denial uses the delivered card and durable human CAS."""

import asyncio

import pytest

from tests.test_h485_owner_once_actuation import (
    _owner_runtime,
    _wait_for_offer,
    runtime,  # noqa: F401
)
from tests.test_h485_owner_once_queue import queue  # noqa: F401


def _reply(*, text="/deny Use staging", chat_id=99, user_id=99, reply_id=17,
           message_id=81, edited=False, **extra):
    message = {
        "message_id": message_id,
        "from": {"id": user_id},
        "chat": {"id": chat_id, "type": "private"},
        "text": text,
        "reply_to_message": {"message_id": reply_id},
        **extra,
    }
    return {"edited_message" if edited else "message": message}


async def _drain(channel):
    for _ in range(100):
        if not channel._owner_once_denial_fast:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("owner-once denial dispatch did not settle")


@pytest.mark.asyncio
async def test_actual_owner_once_text_denial_resumes_occupied_native_tool_with_reason(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        assert not finished.is_set() and spawns == []
        await channel._handle_update(_reply())
        await asyncio.wait_for(invocation, 0.75)
        await _drain(channel)
        task = queue.get(answers[0]["task_id"])
        assert task.status == "rejected" and task.decision == "owner-deny"
        assert task.human_decision["action"] == "reject"
        assert task.human_decision["reply_reason"] == "Use staging"
        assert answers[0]["reason"] == "owner_denied"
        assert answers[0]["approval_outcome"] == "denied"
        assert answers[0]["denial_reason"] == "Use staging"
        assert not queue.verify_owner_once_terminal_approval(task.id, check=lambda _: True)
        assert spawns == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text,expected_raw,expected_normalized", [
    ("/deny", None, None),
    ("/deny 🧪" * 1, "🧪", "🧪"),
    ("/deny Use\tstaging", "Use\tstaging", "Use staging"),
    ("/deny " + "🧪" * 280, "🧪" * 280, "🧪" * 280),
])
async def test_owner_text_reason_is_bounded_metadata_only(
    runtime, monkeypatch, tmp_path, text, expected_raw, expected_normalized,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update(_reply(text=text))
        await asyncio.wait_for(invocation, 2)
        task = queue.get(answers[0]["task_id"])
        human = task.human_decision
        assert human["reason"] == expected_normalized
        assert (human.get("reply_reason") == expected_raw if expected_raw is not None
                else "reply_reason" not in human)
        assert (answers[0].get("denial_reason") == expected_raw if expected_raw is not None
                else "denial_reason" not in answers[0])
        assert task.status == "rejected" and spawns == []


@pytest.mark.asyncio
async def test_overlong_owner_reason_keeps_offer_for_later_valid_denial(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        prompt = next(iter(channel.on_owner_once_callback.__self__._pending.values()))
        await channel._handle_update(_reply(text="/deny " + "x" * 281))
        await _drain(channel)
        assert queue.get(prompt.offer.task_id).status == "blocked"
        assert queue.get(prompt.offer.task_id).human_decision is None
        assert not finished.is_set()
        await channel._handle_update(_reply(text="/deny valid", message_id=82))
        await asyncio.wait_for(invocation, 2)
        assert answers[0]["denial_reason"] == "valid"
        assert queue.get(prompt.offer.task_id).human_decision["reply_reason"] == "valid"
        assert spawns == []


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    _reply(reply_id=999),
    _reply(user_id=98),
    _reply(chat_id=100),
    _reply(reply_to_message=None),
    _reply(edited=True),
    _reply(forward_origin={"type": "user"}),
    _reply(photo=[{"file_id": "synthetic"}]),
])
async def test_untrusted_owner_text_reply_never_uses_offer_or_enters_model(
    runtime, monkeypatch, tmp_path, message,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, _invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        prompt = next(iter(channel.on_owner_once_callback.__self__._pending.values()))
        await channel._handle_update(message)
        await _drain(channel)
        await asyncio.sleep(0.02)
        assert queue.get(prompt.offer.task_id).status == "blocked"
        assert queue.get(prompt.offer.task_id).human_decision is None
        assert not finished.is_set() and answers == [] and spawns == []


@pytest.mark.asyncio
async def test_stale_owner_card_reply_after_button_rejection_is_not_model_turn(
    runtime, monkeypatch, tmp_path,
):
    from tests.test_h485_owner_once_actuation import _callback

    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({"callback_query": _callback(_cards, "r")})
        await asyncio.wait_for(invocation, 2)
        task_id = answers[0]["task_id"]
        await channel._handle_update(_reply(text="/deny stale"))
        await _drain(channel)
        task = queue.get(task_id)
        assert task.human_decision["reason"] is None
        assert "reply_reason" not in task.human_decision
        bound = queue._conn.execute(
            "SELECT denial_metadata_mac,denial_snapshot_sha256 "
            "FROM task_owner_once WHERE task_id=?", (task_id,),
        ).fetchone()
        assert bound["denial_metadata_mac"] is None
        assert queue.smart_terminal_denial(task_id, bound["denial_snapshot_sha256"]) is not None
        assert "denial_reason" not in answers[0]
        assert len(answers) == 1 and spawns == []


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_drift", [False, True])
async def test_committed_reason_survives_timeout_before_callback_publication(
    queue,
    monkeypatch,
    policy_drift,
):
    import threading

    from agents.core.autonomy import owner_once
    from tests.test_h485_owner_once_prompts import _runtime

    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, _cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True,
                                                       timeout=0.3))
        await asyncio.wait_for(sent.wait(), 1)
        await asyncio.sleep(0)
        committed = threading.Event()
        release = threading.Event()
        original = queue.reject_owner_once

        def pause_after_commit(*args, **kwargs):
            result = original(*args, **kwargs)
            if result:
                committed.set()
                assert release.wait(2), "test barrier was not released"
            return result

        monkeypatch.setattr(queue, "reject_owner_once", pause_after_commit)
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever)
        thread.start()
        try:
            dispatched = asyncio.run_coroutine_threadsafe(
                channel._handle_update(_reply(text="/deny Delayed human choice")), loop,
            )
            assert await asyncio.to_thread(committed.wait, 1), "the real CAS must commit"
            durable = queue.get(task_id)
            assert durable.status == "rejected"
            assert durable.human_decision["reply_reason"] == "Delayed human choice"
            if policy_drift:
                queue.mediation_mode = "hold"
            observed = await asyncio.wait_for(pending, 1)
            assert type(observed) is owner_once.OwnerOnceWaitOutcome
            assert observed.state == "timeout", "publication must still be behind the barrier"
            assert prompts.consume_outcome_detail(observed, queue.get(task_id)) == (
                "denied", "Delayed human choice",
            )
        finally:
            release.set()
            await asyncio.wait_for(asyncio.wrap_future(dispatched), 2)

            async def drain():
                for _ in range(100):
                    if not channel._owner_once_denial_fast:
                        return
                    await asyncio.sleep(0.01)

            drained = asyncio.run_coroutine_threadsafe(drain(), loop)
            await asyncio.wait_for(asyncio.wrap_future(drained), 2)
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 1)
            loop.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["extra", "mismatch", "too_long", "wrong_id"])
async def test_tampered_durable_reason_is_not_relayed_or_accepted(
    queue, mutation,
):
    import json

    from tests.test_h485_owner_once_prompts import _runtime

    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, _cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        await asyncio.sleep(0)
        await channel._handle_update(_reply(text="/deny Original"))
        observed = await asyncio.wait_for(pending, 1)
        bound = queue._conn.execute(
            "SELECT denial_snapshot_sha256 FROM task_owner_once WHERE task_id=?", (task_id,),
        ).fetchone()
        assert queue.smart_terminal_denial(task_id, bound[0]) is not None
        human = dict(queue.get(task_id).human_decision)
        if mutation == "extra":
            human["untrusted"] = "Original"
        elif mutation == "mismatch":
            human["reason"] = "Changed"
        elif mutation == "too_long":
            human["reply_reason"] = "a" * 281
        else:
            human["id"] = "f" * 32
        with queue._lock:
            queue._conn.execute(
                "UPDATE tasks SET human_decision=? WHERE id=?",
                (json.dumps(human), task_id),
            )
            queue._conn.commit()
        assert queue.smart_terminal_denial(task_id, bound[0]) is None
        assert prompts.consume_outcome_detail(observed, queue.get(task_id)) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["text", "button"])
async def test_actual_toolrpc_does_not_attribute_coherently_forged_owner_reason(
    runtime, monkeypatch, tmp_path, choice,
):
    import json

    from tests.test_h485_owner_once_actuation import _callback

    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, channel, _sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        prompts = worker._owner_once_prompts
        consume = prompts.consume_outcome_detail

        def corrupt_after_real_cas(outcome, task):
            human = dict(queue.get(task.id).human_decision)
            assert human["action"] == "reject" and human["by"] == "owner_once"
            human["reason"] = "Fabricated"
            human["reply_reason"] = "Fabricated"
            with queue._lock:
                queue._conn.execute(
                    "UPDATE tasks SET human_decision=? WHERE id=?",
                    (json.dumps(human), task.id),
                )
                queue._conn.commit()
            return consume(outcome, queue.get(task.id))

        monkeypatch.setattr(prompts, "consume_outcome_detail", corrupt_after_real_cas)
        if choice == "text":
            await channel._handle_update(_reply(text="/deny Original"))
        else:
            await channel._handle_update({"callback_query": _callback(cards, "r")})
        await asyncio.wait_for(invocation, 2)
        assert len(answers) == 1 and spawns == []
        assert answers[0].get("denial_reason") != "Fabricated"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "missing_mac", "malformed_mac", "forged_mac", "changed_card",
])
async def test_denial_metadata_requires_exact_durable_mac_binding(queue, mutation):
    from tests.test_h485_owner_once_prompts import _runtime

    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, _cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        await asyncio.sleep(0)
        await channel._handle_update(_reply(text="/deny Original"))
        observed = await asyncio.wait_for(pending, 1)
        with queue._lock:
            bound = queue._conn.execute(
                "SELECT denial_snapshot_sha256,denial_metadata_mac FROM task_owner_once "
                "WHERE task_id=?", (task_id,),
            ).fetchone()
            assert type(bound["denial_metadata_mac"]) is str
            assert queue._smart_terminal_denial_locked(
                task_id, bound["denial_snapshot_sha256"],
            ) is not None
            if mutation == "missing_mac":
                queue._conn.execute(
                    "UPDATE task_owner_once SET denial_metadata_mac=NULL WHERE task_id=?",
                    (task_id,),
                )
            elif mutation == "malformed_mac":
                queue._conn.execute(
                    "UPDATE task_owner_once SET denial_metadata_mac=? WHERE task_id=?",
                    ("not-a-mac", task_id),
                )
            elif mutation == "forged_mac":
                queue._conn.execute(
                    "UPDATE task_owner_once SET denial_metadata_mac=? WHERE task_id=?",
                    ("0" * 64, task_id),
                )
            else:
                queue._conn.execute(
                    "UPDATE task_owner_once SET message_id=message_id+1 WHERE task_id=?",
                    (task_id,),
                )
            queue._conn.commit()
        assert queue.smart_terminal_denial(task_id, bound["denial_snapshot_sha256"]) is None
        assert prompts.consume_outcome_detail(observed, queue.get(task_id)) == (None, None)


def test_old_owner_once_table_migrates_nullable_denial_binding(tmp_path):
    import sqlite3

    from agents.core.autonomy.queue import TaskQueue

    db = tmp_path / "old-owner-once.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE task_owner_once (task_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO task_owner_once(task_id) VALUES (71)")
    queue = TaskQueue(str(db)).initialize()
    try:
        row = queue._conn.execute(
            "SELECT task_id,denial_metadata_mac FROM task_owner_once WHERE task_id=71",
        ).fetchone()
        assert row["task_id"] == 71 and row["denial_metadata_mac"] is None
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_unsigned_text_denial_fails_closed_but_reasonless_button_still_works(queue):
    from agents.core.autonomy.mediation import DetachedHMACSigner
    from tests.test_h485_owner_once_prompts import _callback, _runtime

    async with _runtime(queue) as (prompts, channel, task_id, digest, sent, cards, _acks, _auth):
        pending = asyncio.create_task(prompts.request(task_id, digest, check=lambda: True))
        await asyncio.wait_for(sent.wait(), 1)
        await asyncio.sleep(0)
        queue._mediation_signer = DetachedHMACSigner(None)
        await channel._handle_update(_reply(text="/deny Unsignable"))
        await _drain(channel)
        assert queue.get(task_id).status == "blocked" and not pending.done()
        await channel._handle_update({"callback_query": _callback(cards[:1], choice="r")})
        observed = await asyncio.wait_for(pending, 1)
        assert prompts.consume_outcome_detail(observed, queue.get(task_id)) == (
            "denied", None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("button_choice", ["a", "r"])
async def test_owner_button_and_text_denial_commit_at_most_one_choice(
    runtime, monkeypatch, tmp_path, button_choice,
):
    from tests.test_h485_owner_once_actuation import _callback

    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update(_reply(text="/deny text"))
        await channel._handle_update({"callback_query": _callback(cards, button_choice)})
        await asyncio.wait_for(invocation, 2)
        await _drain(channel)
        if channel._owner_once_fast:
            await asyncio.gather(*tuple(channel._owner_once_fast.values()))
        assert len(answers) == 1
        task = queue.get(answers[0]["task_id"])
        if task.decision == "owner-deny":
            assert answers[0]["reason"] == "owner_denied"
            assert task.status == "rejected" and spawns == []
            assert task.human_decision.get("reply_reason") in (None, "text")
            assert not queue.verify_owner_once_terminal_approval(task.id, check=lambda _: True)
        else:
            assert task.decision == "owner-once" and task.status == "done"
            assert queue.verify_owner_once_terminal_result(task.id)
            assert len(spawns) == 1 and "denial_reason" not in answers[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", [
    "owner", "source", "deadline", "generation", "hook", "fingerprint",
])
async def test_native_owner_denial_revalidates_after_selection_before_queue_cas(
    runtime, monkeypatch, tmp_path, revocation,
):
    runtime_queue = runtime[0]
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, owners, _env, _requests, _invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        prompt = next(iter(channel.on_owner_once_callback.__self__._pending.values()))
        original = queue.reject_owner_once
        entered = []

        def drift_then_cas(*args, **kwargs):
            entered.append(True)
            if revocation == "owner":
                owners["autonomy.owner_user_ids"] = [98]
            elif revocation == "source":
                prompt.source._closed = True
            elif revocation == "deadline":
                prompt.native_deadline = 0.0
            elif revocation == "generation":
                channel._owner_once_generation = "replacement"
            elif revocation == "hook":
                channel.on_owner_once_denial_reply = None
            else:
                with queue._lock:
                    queue._conn.execute(
                        "UPDATE tasks SET title='changed after card' WHERE id=?",
                        (prompt.offer.task_id,),
                    )
                    queue._conn.commit()
            return original(*args, **kwargs)

        monkeypatch.setattr(runtime_queue, "reject_owner_once", drift_then_cas)
        await channel._handle_update(_reply())
        await _drain(channel)
        assert entered, "selection must reach the real CAS before drift"
        assert queue.get(prompt.offer.task_id).human_decision is None
        assert spawns == []


@pytest.mark.asyncio
async def test_native_owner_arrival_uses_monotonic_page_not_reason_clock_or_telegram_date(
    runtime, monkeypatch, tmp_path,
):
    from agents.core.channels.telegram import _Page

    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        prompt = next(iter(channel.on_owner_once_callback.__self__._pending.values()))
        channel.decision_reason_clock = lambda: -1_000_000.0
        late_page = _Page(None, -1_000_000.0, 1.0, prompt.native_deadline + 0.01)
        await channel._handle_update(_reply(text="/deny too late", date=1), late_page)
        await _drain(channel)
        assert queue.get(prompt.offer.task_id).human_decision is None
        valid_page = channel._page_received()
        assert valid_page.now == -1_000_000.0
        await channel._handle_update(_reply(text="/deny current", message_id=82, date=1),
                                     valid_page)
        await asyncio.wait_for(invocation, 2)
        assert answers[0]["denial_reason"] == "current"
        assert spawns == []


@pytest.mark.asyncio
async def test_direct_owner_denial_hook_call_cannot_make_a_human_choice(
    runtime, monkeypatch, tmp_path,
):
    import time

    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, _invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        prompt = next(iter(worker._owner_once_prompts._pending.values()))
        result = await worker._owner_once_prompts.denial_reply(
            "forged", chat_id=99, user_id=99, message_id=81,
            reply_to_message_id=17, received_at=time.monotonic(),
        )
        assert result is None
        assert queue.get(prompt.offer.task_id).human_decision is None
        assert not finished.is_set() and answers == [] and spawns == []


@pytest.mark.asyncio
async def test_duplicate_cross_registry_card_id_is_not_selected(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, _invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        prompt = next(iter(channel.on_owner_once_callback.__self__._pending.values()))
        monkeypatch.setattr(channel, "_consent_denial_hook_live", lambda *_: True)
        monkeypatch.setattr(channel, "consent_denial_pending", lambda **_: True)
        await channel._handle_update(_reply())
        await _drain(channel)
        assert queue.get(prompt.offer.task_id).human_decision is None
        assert not finished.is_set() and answers == [] and spawns == []
