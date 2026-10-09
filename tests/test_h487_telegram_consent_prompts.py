"""Private reusable-consent registration with real Telegram delivery/callback seams."""

import asyncio
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from agents.core.approval_outcomes import (
    ApprovalTurnContext,
    bind_approval_turn,
    close_approval_turn,
)
from agents.core.autonomy.consent_ledger import ConsentCategory
from agents.core.autonomy.consent_prompts import ConsentPrompts
from agents.core.autonomy.consent_types import ConsentOffer
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.telegram import TelegramChannel


def _task():
    return SimpleNamespace(
        id=41, created_at="birth", agent="jarvis", kind="toolrpc.terminal_run",
        title="Run terminal", payload={"tool": "terminal_run", "args": {
            "target": "local-host", "command": "git reset --hard",
        }}, risk_tier=3, autonomy_level="ask", origin="generated",
        kernel_intake_id=None, status="blocked", approval_deadline_at=None,
    )


class _Queue:
    def __init__(self):
        self.task = _task()
        self.tasks = {41: self.task}
        self.revision = "a" * 64
        self.members = (41,)

    def get(self, task_id):
        return self.tasks.get(task_id)

    def pending_consent_offer(self, task_id):
        task = self.get(task_id)
        if task is None or task.status != "blocked":
            return None
        members = self.members if task_id == self.task.id else (task_id,)
        return ConsentOffer(task_id, self.revision, members,
                            (ConsentCategory("terminal.warning.git_reset"),))


class _Worker:
    def __init__(self, queue):
        self.queue = queue
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def apply_consent_decision(self, task_id, revision, *, choice, actor):
        self.entered.set()
        await self.release.wait()
        if not actor.live() or revision != self.queue.revision:
            return None
        self.calls.append((task_id, revision, choice, actor.principal_key))
        self.queue.task.status = "rejected" if choice == "deny" else "approved"
        return SimpleNamespace(tasks=(self.queue.task,))


@pytest.fixture
async def runtime():
    sent, acks = [], []

    def transport(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("/sendMessage"):
            sent.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 17}})
        acks.append(payload)
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    channel._lanes = ChatLanes(name="reusable-consent-real-chat")
    queue = _Queue()
    worker = _Worker(queue)
    owner = [True]
    orch = SimpleNamespace(autonomy=worker, channels={"telegram": channel})
    coordinator = SimpleNamespace(
        _orch=orch, _owner_settings=lambda: {"autonomy.owner_chat_id": 99,
                                             "autonomy.owner_user_ids": [99]},
        _callback_is_owner=lambda chat_id, user_id: owner[0] and chat_id == user_id == 99,
    )
    prompts = ConsentPrompts(coordinator)
    prompts.install(channel)
    try:
        yield SimpleNamespace(prompts=prompts, channel=channel, queue=queue, worker=worker,
                              sent=sent, acks=acks, owner=owner)
    finally:
        worker.release.set()
        await channel.stop()


def _callback(runtime, *, nonce=None, choice="s", chat_id=99, user_id=99, message_id=17):
    if nonce is None:
        nonce = runtime.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":")[1]
    return {"id": "tap", "data": f"autc:{nonce}:{choice}", "from": {"id": user_id},
            "message": {"message_id": message_id, "chat": {"id": chat_id}}}


@pytest.mark.asyncio
async def test_same_chat_request_commits_before_ack_while_origin_is_blocked(runtime):
    completed = asyncio.Event()
    result = []

    async def handler(_text, **_kwargs):
        turn = ApprovalTurnContext("s", "i", '["telegram","99","99"]', "turn", lambda *_: True)
        token = bind_approval_turn(turn)
        try:
            assert runtime.prompts.register_invocation(41, check=lambda: True)
            result.append(await runtime.prompts.request(41, check=lambda: True))
            completed.set()
        finally:
            runtime.prompts.release_invocation(41)
            close_approval_turn(turn, token)

    runtime.channel.handler = handler
    await runtime.channel._deliver_turn(99, 99, "run")
    for _ in range(100):
        if runtime.sent:
            break
        await asyncio.sleep(0.01)
    assert runtime.sent and not completed.is_set()
    await runtime.channel._handle_update({"callback_query": _callback(runtime)})
    await asyncio.wait_for(runtime.worker.entered.wait(), 1)
    assert not runtime.acks and not completed.is_set()
    runtime.worker.release.set()
    await asyncio.wait_for(completed.wait(), 1)
    await asyncio.gather(*tuple(runtime.channel._consent_fast.values()))
    assert result[0] is not None
    assert runtime.worker.calls == [(41, "a" * 64, "session", '["telegram","99","99"]')]
    assert runtime.acks[0]["text"] == "OK: session"


@pytest.mark.asyncio
async def test_gathered_tool_child_can_register_but_copied_context_sibling_cannot_use_offer(runtime):
    registered = asyncio.Event()
    sibling_done = asyncio.Event()
    completed = asyncio.Event()
    results = []

    async def handler(_text, **_kwargs):
        turn = ApprovalTurnContext("s", "i", '["telegram","99","99"]', "turn", lambda *_: True)
        token = bind_approval_turn(turn)

        async def actual_tool_call():
            assert runtime.prompts.register_invocation(41, check=lambda: True)
            registered.set()
            results.append(await runtime.prompts.request(41, check=lambda: True))

        async def unrelated_sibling():
            await registered.wait()
            assert await runtime.prompts.request(41, check=lambda: True) is None
            sibling_done.set()

        try:
            await asyncio.gather(actual_tool_call(), unrelated_sibling())
            completed.set()
        finally:
            runtime.prompts.release_invocation(41)
            close_approval_turn(turn, token)

    runtime.channel.handler = handler
    await runtime.channel._deliver_turn(99, 99, "run")
    await asyncio.wait_for(sibling_done.wait(), 1)
    for _ in range(100):
        if runtime.sent:
            break
        await asyncio.sleep(0.01)
    assert runtime.sent and not completed.is_set()
    runtime.worker.release.set()
    await runtime.channel._handle_update({"callback_query": _callback(runtime)})
    await asyncio.wait_for(completed.wait(), 1)
    assert results[0] is not None and len(runtime.worker.calls) == 1


@pytest.mark.asyncio
async def test_gathered_child_refuses_click_as_soon_as_origin_parent_is_cancelled(runtime):
    children = []

    async def handler(_text, **_kwargs):
        turn = ApprovalTurnContext("s", "i", '["telegram","99","99"]', "turn", lambda *_: True)
        token = bind_approval_turn(turn)

        async def tool_call():
            assert runtime.prompts.register_invocation(41, check=lambda: True)
            try:
                await runtime.prompts.request(41, check=lambda: True)
            finally:
                runtime.prompts.release_invocation(41)

        child = asyncio.create_task(tool_call())
        children.append(child)
        try:
            await asyncio.shield(child)
        finally:
            close_approval_turn(turn, token)

    runtime.channel.handler = handler
    await runtime.channel._deliver_turn(99, 99, "run")
    for _ in range(100):
        if runtime.sent:
            break
        await asyncio.sleep(0.01)
    assert runtime.sent and children
    cb = _callback(runtime)
    parent = runtime.channel._lanes._tails[99]
    parent.cancel()
    assert not runtime.prompts.pending(cb), "parent cancellation revokes inherited source immediately"
    await runtime.channel._handle_update({"callback_query": cb})
    assert runtime.acks[-1]["text"] == "Not applied."
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert not runtime.prompts.pending(cb), "closed parent never reauthorizes child"
    children[0].cancel()
    await asyncio.gather(*children, return_exceptions=True)
    assert not runtime.worker.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidate", ["cancel_child", "expire_prompt"])
async def test_gathered_request_cancellation_or_expiry_refuses_while_parent_live(runtime, invalidate):
    children = []
    parent_release = asyncio.Event()

    async def handler(_text, **_kwargs):
        turn = ApprovalTurnContext("s", "i", '["telegram","99","99"]', "turn", lambda *_: True)
        token = bind_approval_turn(turn)

        async def tool_call():
            assert runtime.prompts.register_invocation(41, check=lambda: True)
            try:
                await runtime.prompts.request(41, check=lambda: True)
            finally:
                runtime.prompts.release_invocation(41)

        child = asyncio.create_task(tool_call())
        children.append(child)
        try:
            try:
                await asyncio.shield(child)
            except asyncio.CancelledError:
                await parent_release.wait()
        finally:
            close_approval_turn(turn, token)

    runtime.channel.handler = handler
    await runtime.channel._deliver_turn(99, 99, "run")
    for _ in range(100):
        if runtime.sent:
            break
        await asyncio.sleep(0.01)
    assert runtime.sent and children
    cb = _callback(runtime)
    if invalidate == "cancel_child":
        children[0].cancel()
    else:
        next(iter(runtime.prompts._pending.values())).deadline = 0
    assert not runtime.prompts.pending(cb)
    await runtime.channel._handle_update({"callback_query": cb})
    assert runtime.acks[-1]["text"] == "Not applied."
    assert not runtime.worker.calls
    children[0].cancel()
    await asyncio.gather(*children, return_exceptions=True)
    parent_release.set()


@pytest.mark.asyncio
async def test_unsolicited_owner_card_binds_actual_event_and_rejects_wrong_receipt(runtime):
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    wrong = _callback(runtime, message_id=18)
    await runtime.channel._handle_update({"callback_query": wrong})
    assert runtime.acks[-1]["text"] == "Not applied."
    assert not runtime.worker.calls
    runtime.worker.release.set()
    await runtime.channel._handle_update({"callback_query": _callback(runtime, choice="a")})
    await asyncio.gather(*tuple(runtime.channel._consent_fast.values()))
    assert runtime.worker.calls == [(41, "a" * 64, "always", '["telegram","99","99"]')]
    assert runtime.acks[-1]["text"] == "OK: always"
    await runtime.channel._handle_update({"callback_query": _callback(runtime, choice="a")})
    assert runtime.acks[-1]["text"] == "Not applied."


@pytest.mark.asyncio
async def test_duplicate_unsolicited_notify_uses_one_verified_card(runtime):
    first, second = await asyncio.gather(
        runtime.prompts.notify(runtime.queue.task, runtime.channel, 99),
        runtime.prompts.notify(runtime.queue.task, runtime.channel, 99),
    )
    assert first and second
    assert len(runtime.sent) == 1
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    assert len(runtime.sent) == 1


@pytest.mark.asyncio
async def test_changed_offer_requires_fresh_card_and_revoked_owner_cannot_click(runtime):
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    old = _callback(runtime)
    runtime.queue.revision = "b" * 64
    runtime.queue.members = (41, 42)
    await runtime.channel._handle_update({"callback_query": old})
    assert runtime.acks[-1]["text"] == "Not applied."
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    fresh = _callback(runtime)
    assert fresh["data"] != old["data"]
    assert "Pending identical requests in this offer: 2" in runtime.sent[-1]["text"]
    runtime.owner[0] = False
    await runtime.channel._handle_update({"callback_query": fresh})
    assert runtime.acks[-1]["text"] == "Not applied."
    assert not runtime.worker.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["sender", "chat", "generation", "hook", "expiry"])
async def test_post_delivery_identity_or_lifetime_change_refuses(runtime, defect):
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    cb = _callback(runtime)
    if defect == "sender":
        cb["from"]["id"] = 98
    elif defect == "chat":
        cb["message"]["chat"]["id"] = 98
    elif defect == "generation":
        runtime.channel._owner_once_generation = uuid4().hex
    elif defect == "hook":
        runtime.channel.consent_pending = lambda _cb: True
    else:
        next(iter(runtime.prompts._pending.values())).deadline = 0
    await runtime.channel._handle_update({"callback_query": cb})
    await asyncio.gather(*tuple(runtime.channel._consent_fast.values()))
    assert runtime.acks[-1]["text"] == "Not applied."
    assert runtime.queue.task.status == "blocked" and not runtime.worker.calls


@pytest.mark.asyncio
async def test_failed_native_delivery_registers_no_clickable_prompt(runtime):
    await runtime.channel.client.aclose()
    acknowledgements = []

    def failed(request):
        if request.url.path.endswith("/answerCallbackQuery"):
            acknowledgements.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    runtime.channel.client = httpx.AsyncClient(transport=httpx.MockTransport(
        failed,
    ))
    assert not await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    assert not runtime.prompts._pending
    await runtime.channel._handle_update({"callback_query": _callback(runtime, nonce="a" * 32)})
    assert acknowledgements[-1]["text"] == "Not applied."
    assert not runtime.worker.calls


@pytest.mark.asyncio
async def test_concurrent_duplicate_click_has_one_commit(runtime):
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    cb = _callback(runtime)
    await runtime.channel._handle_update({"callback_query": cb})
    await asyncio.wait_for(runtime.worker.entered.wait(), 1)
    await runtime.channel._handle_update({"callback_query": cb})
    assert runtime.acks[-1]["text"] == "Not applied."
    runtime.worker.release.set()
    await asyncio.gather(*tuple(runtime.channel._consent_fast.values()))
    assert len(runtime.worker.calls) == 1
    assert [ack["text"] for ack in runtime.acks].count("OK: session") == 1


@pytest.mark.asyncio
async def test_stopping_generation_revokes_pending_card(runtime):
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    cb = _callback(runtime)
    old_generation = runtime.channel._owner_once_generation
    runtime.prompts.stop(old_generation)
    assert not runtime.prompts.pending(cb)
    await runtime.channel._handle_update({"callback_query": cb})
    assert runtime.acks[-1]["text"] == "Not applied."
    assert not runtime.worker.calls


@pytest.mark.asyncio
async def test_click_while_native_receipt_is_unresolved_cannot_reserve(runtime):
    sending, release = asyncio.Event(), asyncio.Event()
    acks = []

    async def transport(request):
        if request.url.path.endswith("/sendMessage"):
            sending.set()
            await release.wait()
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 17}})
        acks.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    await runtime.channel.client.aclose()
    runtime.channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    notifying = asyncio.create_task(
        runtime.prompts.notify(runtime.queue.task, runtime.channel, 99),
    )
    await asyncio.wait_for(sending.wait(), 1)
    nonce = next(iter(runtime.prompts._pending))
    cb = _callback(runtime, nonce=nonce)
    await runtime.channel._handle_update({"callback_query": cb})
    assert acks[-1]["text"] == "Not applied."
    assert not runtime.worker.calls
    release.set()
    assert await asyncio.wait_for(notifying, 1)
    runtime.worker.release.set()
    await runtime.channel._handle_update({"callback_query": cb})
    await asyncio.gather(*tuple(runtime.channel._consent_fast.values()))
    assert len(runtime.worker.calls) == 1 and acks[-1]["text"] == "OK: session"


@pytest.mark.asyncio
async def test_cancelled_origin_closes_prompt_before_late_click(runtime):
    async def handler(_text, **_kwargs):
        turn = ApprovalTurnContext("s", "i", '["telegram","99","99"]', "turn", lambda *_: True)
        token = bind_approval_turn(turn)
        try:
            assert runtime.prompts.register_invocation(41, check=lambda: True)
            await runtime.prompts.request(41, check=lambda: True)
        finally:
            runtime.prompts.release_invocation(41)
            close_approval_turn(turn, token)

    runtime.channel.handler = handler
    await runtime.channel._deliver_turn(99, 99, "run")
    for _ in range(100):
        if runtime.sent:
            break
        await asyncio.sleep(0.01)
    assert runtime.sent
    cb = _callback(runtime)
    lane_task = runtime.channel._lanes._tails[99]
    lane_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await lane_task
    assert not runtime.prompts.pending(cb)
    await runtime.channel._handle_update({"callback_query": cb})
    assert runtime.acks[-1]["text"] == "Not applied."
    assert not runtime.worker.calls


@pytest.mark.asyncio
async def test_full_fast_lane_refuses_promptly_without_spending_offer(runtime):
    assert await runtime.prompts.notify(runtime.queue.task, runtime.channel, 99)
    cb = _callback(runtime)
    sleepers = [asyncio.create_task(asyncio.sleep(100)) for _ in range(32)]
    runtime.channel._consent_fast.update({f"f{index}": task for index, task in enumerate(sleepers)})
    try:
        await asyncio.wait_for(runtime.channel._handle_update({"callback_query": cb}), 1)
        assert runtime.acks[-1]["text"] == "Not applied."
        assert runtime.prompts.pending(cb)
    finally:
        for task in sleepers:
            task.cancel()
        await asyncio.gather(*sleepers, return_exceptions=True)
        runtime.channel._consent_fast.clear()
    runtime.worker.release.set()
    await runtime.channel._handle_update({"callback_query": cb})
    await asyncio.gather(*tuple(runtime.channel._consent_fast.values()))
    assert len(runtime.worker.calls) == 1


@pytest.mark.asyncio
async def test_registry_caps_live_cards_and_prunes_expired_entries(runtime):
    for task_id in range(42, 74):
        task = copy.deepcopy(runtime.queue.task)
        task.id = task_id
        task.created_at = f"birth-{task_id}"
        runtime.queue.tasks[task_id] = task
    for task_id in range(41, 73):
        assert await runtime.prompts.notify(runtime.queue.get(task_id), runtime.channel, 99)
    assert len(runtime.prompts._pending) == 32
    assert not await runtime.prompts.notify(runtime.queue.get(73), runtime.channel, 99)
    oldest = next(iter(runtime.prompts._pending.values()))
    oldest.deadline = 0
    assert await runtime.prompts.notify(runtime.queue.get(73), runtime.channel, 99)
    assert len(runtime.prompts._pending) == 32
