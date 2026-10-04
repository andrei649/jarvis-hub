"""Native reusable-consent Telegram denial is bound to a delivered card and real owner turn."""

import asyncio

import pytest

from tests.test_h487_telegram_consent_integration import _telegram, consent_runtime  # noqa: F401


def _reply(*, text="/deny Use staging", chat_id=-500, user_id=42, reply_id=17,
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


@pytest.mark.asyncio
async def test_native_denial_reaches_waiting_real_tool_without_occupying_chat_lane(
    consent_runtime, monkeypatch,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "synthetic owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        task = runtime.q.list()[0]
        assert task.status == "blocked" and task.human_decision is None
        assert not h.finished.is_set()
        await h.channel._handle_update(_reply(reply_id=17))
        await asyncio.wait_for(h.finished.wait(), 0.75)
        decided = runtime.q.get(task.id)
        assert decided.status == "rejected"
        assert decided.human_decision["action"] == "deny"
        assert decided.human_decision["reply_reason"] == "Use staging"
        assert h.replies[0]["reason"] == "owner_denied"
        assert h.replies[0]["denial_reason"] == "Use staging"
        assert h.effects == []
    finally:
        await h.channel.stop()


async def _drain(h):
    for _ in range(100):
        if not h.channel._consent_denial_fast:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("native denial task did not finish")


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    _reply(reply_id=999),
    _reply(user_id=99),
    _reply(chat_id=-501),
    _reply(text="/deny unrelated", reply_id=0),
    _reply(text="/deny old", edited=True),
    _reply(text="/deny forwarded", forward_origin={"type": "user"}),
    _reply(text="/deny attachment", photo=[{"file_id": "synthetic"}]),
])
async def test_invalid_or_untrusted_denial_never_selects_an_offer_or_model(
    consent_runtime, monkeypatch, message,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        task = runtime.q.list()[0]
        await h.channel._handle_update(message)
        await _drain(h)
        await asyncio.sleep(0.02)
        assert runtime.q.get(task.id).status == "blocked"
        assert runtime.q.get(task.id).human_decision is None
        assert len(runtime.q.list()) == 1
        assert h.effects == []
        assert not h.finished.is_set()
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [None, "🧪" * 280])
async def test_exact_denial_reason_boundary(consent_runtime, monkeypatch, reason):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        text = "/deny" if reason is None else "/deny " + reason
        await h.channel._handle_update(_reply(text=text))
        await asyncio.wait_for(h.finished.wait(), 1)
        task = runtime.q.list()[0]
        assert task.status == "rejected" and task.human_decision["action"] == "deny"
        assert (task.human_decision.get("reply_reason") == reason if reason is not None
                else "reply_reason" not in task.human_decision)
        assert (h.replies[0].get("denial_reason") == reason if reason is not None
                else "denial_reason" not in h.replies[0])
        assert h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_overlong_denial_does_not_consume_card(consent_runtime, monkeypatch):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        task = runtime.q.list()[0]
        await h.channel._handle_update(_reply(text="/deny " + "a" * 281))
        await _drain(h)
        assert runtime.q.get(task.id).status == "blocked"
        assert runtime.q.get(task.id).human_decision is None
        assert len(runtime.q.list()) == 1 and h.effects == []
        await h.channel._handle_update(_reply(text="/deny valid", message_id=82))
        await asyncio.wait_for(h.finished.wait(), 1)
        assert runtime.q.get(task.id).human_decision["reply_reason"] == "valid"
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["owner", "generation", "source", "deadline", "arrival", "hook"])
async def test_native_denial_refuses_revoked_exact_registration(consent_runtime, monkeypatch, drift):
    from agents.core.channels.telegram import _Page

    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        task = runtime.q.list()[0]
        prompt = next(iter(runtime.worker._consent_prompts._pending.values()))
        page = None
        if drift == "owner":
            h.settings["autonomy.owner_user_ids"] = [99]
        elif drift == "generation":
            h.channel._owner_once_generation = "other-generation"
        elif drift == "source":
            prompt.source._closed = True
        elif drift == "deadline":
            prompt.deadline = 0.0
        elif drift == "arrival":
            page = _Page(None, None, None, prompt.deadline + 0.01)
        else:
            h.channel.on_consent_denial_reply = lambda *args, **kwargs: None
        await h.channel._handle_update(_reply(), page)
        await _drain(h)
        assert runtime.q.get(task.id).status == "blocked"
        assert runtime.q.get(task.id).human_decision is None
        assert h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_direct_hook_call_is_not_native_dispatch(consent_runtime, monkeypatch):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        task = runtime.q.list()[0]
        result = await runtime.worker._consent_prompts.denial_reply(
            "forged", chat_id=-500, user_id=42, message_id=81,
            reply_to_message_id=17, received_at=__import__("time").monotonic(),
        )
        assert result is None
        assert runtime.q.get(task.id).human_decision is None
        assert h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_native_arrival_ignores_general_reason_clock_and_telegram_date(
    consent_runtime, monkeypatch,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        h.channel.decision_reason_clock = lambda: -1_000_000.0
        page = h.channel._page_received()
        assert page.native_at is not None and page.now == -1_000_000.0
        update = _reply(text="/deny native", date=1)
        await h.channel._handle_update(update, page)
        await asyncio.wait_for(h.finished.wait(), 1)
        assert runtime.q.list()[0].human_decision["reply_reason"] == "native"
        assert h.replies[0]["denial_reason"] == "native"
        assert h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("button_choice", ["session", "deny"])
async def test_callback_and_text_denial_arbitrate_one_durable_offer(
    consent_runtime, monkeypatch, button_choice,
):
    from tests.test_h487_telegram_consent_integration import _tap

    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        card = h.cards[0]
        task_id = runtime.q.list()[0].id
        await h.channel._handle_update(_reply(text="/deny text"))
        await h.channel._handle_update(_tap(card, button_choice, message_id=17))
        await asyncio.wait_for(h.finished.wait(), 1)
        await _drain(h)
        if h.channel._consent_fast:
            await asyncio.gather(*tuple(h.channel._consent_fast.values()))
        task = runtime.q.get(task_id)
        assert len(runtime.q.list()) == 1
        assert task.human_decision["action"] in {"deny", button_choice}
        if task.human_decision["action"] == "deny":
            assert task.status == "rejected" and h.effects == []
            assert task.human_decision.get("reply_reason") in (None, "text")
        else:
            assert task.status == "done" and len(h.effects) == 1
            assert "reply_reason" not in task.human_decision
        assert len(h.replies) == 1
        await runtime.worker.tick()
        assert len(h.effects) <= 1
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_stale_text_after_committed_button_is_not_forwarded(
    consent_runtime, monkeypatch,
):
    from tests.test_h487_telegram_consent_integration import _tap

    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        card = h.cards[0]
        task_id = runtime.q.list()[0].id
        await h.channel._handle_update(_tap(card, "deny", message_id=17))
        await asyncio.wait_for(h.finished.wait(), 1)
        await h.channel._handle_update(_reply(text="/deny stale"))
        await _drain(h)
        assert len(runtime.q.list()) == 1
        task = runtime.q.get(task_id)
        assert task.status == "rejected" and "reply_reason" not in task.human_decision
        assert len(h.replies) == 1 and h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_replaced_public_denial_hook_cannot_impersonate_registration(
    consent_runtime, monkeypatch,
):
    from unittest.mock import AsyncMock

    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        task_id = runtime.q.list()[0].id
        impostor = AsyncMock(return_value="accepted")
        h.channel.on_consent_denial_reply = impostor
        await h.channel._handle_update(_reply())
        await _drain(h)
        impostor.assert_not_awaited()
        assert runtime.q.get(task_id).human_decision is None
        assert h.cards[-1]["text"] == "Not applied."
        assert h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["deadline", "owner", "hook", "source"])
async def test_delayed_native_denial_rechecks_live_guards_at_queue_cas(
    consent_runtime, monkeypatch, revocation,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.worker.apply_consent_decision

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime.worker, "apply_consent_decision", delayed)
    try:
        await h.channel._deliver_turn(-500, 42, "owner request")
        await asyncio.wait_for(h.ready.wait(), 2)
        task_id = runtime.q.list()[0].id
        prompt = next(iter(runtime.worker._consent_prompts._pending.values()))
        await h.channel._handle_update(_reply())
        await asyncio.wait_for(entered.wait(), 1)
        if revocation == "deadline":
            prompt.deadline = 0.0
        elif revocation == "owner":
            h.settings["autonomy.owner_user_ids"] = [99]
        elif revocation == "hook":
            h.channel.on_consent_denial_reply = None
        else:
            prompt.source._closed = True
        release.set()
        await _drain(h)
        task = runtime.q.get(task_id)
        assert task.status == "blocked" and task.human_decision is None
        assert h.effects == []
    finally:
        release.set()
        await h.channel.stop()


@pytest.mark.asyncio
async def test_superseded_delivered_card_reply_cannot_choose_new_offer(
    consent_runtime, monkeypatch,
):
    from tests.test_h487_consent_runtime_integration import ask

    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        first = await ask(runtime)
        assert await runtime.worker.notifier(first) is True
        old_revision = runtime.q.pending_consent_offer(first.id).revision
        second = await ask(runtime)
        assert runtime.q.pending_consent_offer(first.id).revision != old_revision
        await h.channel._handle_update(_reply(text="/deny old card", reply_id=17))
        await _drain(h)
        assert all(runtime.q.get(task.id).status == "blocked"
                   and runtime.q.get(task.id).human_decision is None
                   for task in (first, second))
        assert len(runtime.q.list()) == 2 and h.effects == []
    finally:
        await h.channel.stop()
