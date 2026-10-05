"""H067 pending answers through the actual Telegram poll/chat-lane path."""

import asyncio

import pytest

from agents.core.channels.batching import Coalescer
from agents.core.channels.ephemeral import EphemeralReply
from agents.core.channels.group_policy import GroupPolicy
from agents.core.channels.telegram import TelegramChannel
from tests.test_pending_input_runtime import incoming, runtime_host


def free_text_model(orch, cap, server, answers, *, gate=None, entered=None):
    async def model(text, channel="voice", **_kwargs):
        cap["sessions"].append(orch.session_id)
        if text == "ask":
            if entered:
                entered.set()
            if gate:
                await gate.wait()
            result = await server.handle({"tool": "clarify", "args": {"question": "Choose detail"}})
            answers.append((result, 0))
        return "Finished"

    orch.handle_input = model


def transport(orch, gateway, pairing):
    # Explicit production wiring; getattr lets the regression reproduce the old
    # queue/rate behavior before these opt-in hooks are implemented.
    gateway.pending_handler = getattr(orch, "channel_pending_handler", None)
    ch = TelegramChannel(token="synthetic", handler=gateway.route, pairing=pairing)
    ch.pending_reply_handler = getattr(gateway, "route_pending", None)
    ch._batch = Coalescer(0, 0)
    orch.channels["telegram"] = ch
    # This fixture exercises ingress and ToolRPC, with the same stub model and
    # memory as runtime_host; streaming draft delivery is tested separately.
    orch._begin_channel_draft = lambda *_args: None
    return ch


def update(text, *, uid=42, topic=8, **fields):
    message = {
        "message_id": 100,
        "from": {"id": uid},
        "chat": {"id": 123, "type": "private"},
        "text": text,
        "message_thread_id": topic,
        **fields,
    }
    return {"update_id": 100, "message": message}


@pytest.mark.asyncio
async def test_polling_answer_resumes_the_turn_holding_its_chat_lane(tmp_path):
    orch, cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    delivered = asyncio.Event()
    stop = asyncio.Event()
    page = 0

    async def pages(timeout=25):
        nonlocal page
        page += 1
        if page == 1:
            return [update("ask")]
        if page == 2:
            await ready.wait()
            return [update("2")]
        delivered.set()
        await stop.wait()
        ch._running = False
        return []

    ch._get_updates = pages
    ch._running = True
    poll = asyncio.create_task(ch._poll_loop())
    try:
        await asyncio.wait_for(delivered.wait(), 1)
        # The poll loop has handled the answer; it must not be queued behind ask.
        for _ in range(30):
            if answers:
                break
            await asyncio.sleep(0.01)
        assert answers, "answer is stuck behind the chat lane's waiting model turn"
        assert answers[0][0]["result"]["user_response"] == "Remote"
        stop.set()
        await asyncio.wait_for(poll, 1)
        assert len(cap["sessions"]) == 1
    finally:
        orch._pending_input_service().close()
        ready.set()
        stop.set()
        await asyncio.wait_for(poll, 2)
        await ch.client.aclose()


@pytest.mark.asyncio
async def test_exact_answer_bypasses_saturated_new_message_budget(tmp_path):
    orch, cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    gateway.set_rate_limit(1)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        result = await incoming(gateway, "2", message_thread_id=8)
        assert result == "", "pending reply was rejected by the new-message rate budget"
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Remote"
        assert len(cap["sessions"]) == 1
        assert "Rate limit" in await incoming(gateway, "ordinary", message_thread_id=8)
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["edited", "forwarded", "attachment"])
async def test_non_direct_input_cannot_resolve_even_after_normal_gateway_fallback(tmp_path, kind):
    orch, _cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    orch._turn_lease_max_wait = 0.01
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        bad = update("2")
        if kind == "edited":
            bad["edited_message"] = bad.pop("message")
        elif kind == "forwarded":
            bad["message"]["forward_origin"] = {"type": "user"}
        else:
            bad["message"]["photo"] = [{"file_id": "synthetic", "width": 1, "height": 1}]

            async def read(*_args):
                return "2", ""

            ch._read_attachment = read
        await asyncio.wait_for(ch._handle_update(bad), 1)
        for _ in range(3):
            await asyncio.sleep(0)
        assert not answers, "non-direct input resolved the pending question on fallback"
        assert not turn.done()
        await ch._handle_update(update("1"))
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Local"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
async def test_invalid_selection_is_not_batched_or_run_as_another_model_turn(tmp_path):
    orch, cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    ch._batch = Coalescer(0.35, 1)
    gateway.set_rate_limit(1)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        await ch._handle_update(update("9"))
        assert not ch._batch.held_keys()
        assert not answers and not turn.done()
        assert len(cap["sessions"]) == 1
        assert isinstance(cap["sent"][-1][1], EphemeralReply)
        assert cap["sent"][-1][2]["voice"] is False
        assert cap["sent"][-1][2]["message_thread_id"] == 8
        await ch._handle_update(update("1"))
        await asyncio.wait_for(turn, 1)
        assert len(cap["sessions"]) == 1
        assert answers[0][0]["result"]["user_response"] == "Local"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["topic", "sender", "observed_group", "dropped_group", "allowlist"]
)
async def test_transport_identity_and_group_policy_still_gate_pending_answers(tmp_path, kind):
    orch, _cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    orch._turn_lease_max_wait = 0.01
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        bad = update("2")
        if kind == "topic":
            bad["message"]["message_thread_id"] = 9
        elif kind == "sender":
            bad["message"]["from"]["id"] = 99
        elif kind == "allowlist":
            ch.allowed_users = [7]
        else:
            bad["message"]["chat"]["type"] = "supergroup"
            ch.group_policy = GroupPolicy(observe_mode=kind == "observed_group")
        await asyncio.wait_for(ch._handle_update(bad), 1)
        assert not turn.done() and not answers
        ch.allowed_users = []
        ch.group_policy = GroupPolicy()
        await ch._handle_update(update("1"))
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Local"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
async def test_revoked_or_failing_pairing_cannot_use_the_pending_only_hook(tmp_path):
    orch, _cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        pairing.allowed = False
        assert not await gateway.route_pending("2", chat_id=123, sender="42", message_thread_id=8)
        assert not answers

        def failed(*_args):
            raise OSError("synthetic store failure")

        pairing.is_allowed = failed
        assert not await gateway.route_pending("2", chat_id=123, sender="42", message_thread_id=8)
        await asyncio.wait_for(turn, 1.5)
        assert answers[0][0]["result"]["reason"] == "prompt_binding_lost"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
async def test_pending_resolution_binds_actual_inbound_origin_and_principal(tmp_path):
    from agents.core.action_origin import current_action_origin
    from agents.core.orchestrator import current_principal

    orch, _cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        runtime = orch._pending_input_service()
        intercept = runtime.intercept
        captured = []

        def checked(source, text, **kwargs):
            captured.append((current_action_origin(), current_principal()))
            return intercept(source, text, **kwargs)

        runtime.intercept = checked
        assert await gateway.route_pending(
            "2",
            chat_id=123,
            sender="42",
            message_thread_id=8,
            origin="generated",
        )
        await asyncio.wait_for(turn, 1)
        assert len(captured) == 1 and captured[0][0] == "inbound"
        assert captured[0][1].channel == "telegram"
        assert captured[0][1].sender == "42"
        assert not captured[0][1].admin
        assert current_principal().sender is None
        assert answers[0][0]["result"]["user_response"] == "Remote"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["disabled", "closed", "detached"])
async def test_inactive_binding_cannot_bypass_the_model_rate_limit(tmp_path, state):
    orch, _cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        runtime = orch._pending_input_service()
        if state == "disabled":
            orch._runtime_settings["channels.pending_inputs_enabled"] = False
        elif state == "closed":
            runtime.close()
        else:
            next(iter(runtime._delivered.values())).active = False
        assert not await gateway.route_pending("2", chat_id=123, sender="42", message_thread_id=8)
        await asyncio.wait_for(turn, 1.5)
        assert not answers[0][0]["result"]["ok"]
    finally:
        orch.__dict__["_pending_inputs"].close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
async def test_rate_rejected_prose_leaves_the_existing_question_intact(tmp_path):
    orch, _cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    gateway.set_rate_limit(1)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert "Rate limit" in await incoming(gateway, "please reconsider", message_thread_id=8)
        assert not turn.done() and not answers
        assert await incoming(gateway, "1", message_thread_id=8) == ""
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Local"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
async def test_decision_reason_reply_takes_precedence_over_a_free_text_question(tmp_path):
    orch, cap, gateway, server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    free_text_model(orch, cap, server, answers)
    reasons = []
    ch.decision_reason_pending = lambda **kw: kw["reply_to_message_id"] == 999

    async def save_reason(text, **_kwargs):
        reasons.append(text)
        return True

    ch.on_decision_reason = save_reason
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        await ch._handle_update(
            update("Needs a smaller scope", reply_to_message={"message_id": 999})
        )
        assert reasons == ["Needs a smaller scope"]
        assert not answers and not turn.done()
        await ch._handle_update(update("actual clarification answer"))
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "actual clarification answer"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()


@pytest.mark.asyncio
async def test_ineligible_piece_narrows_the_entire_batch_after_prompt_delivery(tmp_path):
    orch, cap, gateway, server, ready, pairing, answers = runtime_host(tmp_path)
    ch = transport(orch, gateway, pairing)
    ch._batch = Coalescer(0.35, 1)
    orch._turn_lease_max_wait = 0.01
    gate, entered = asyncio.Event(), asyncio.Event()
    free_text_model(orch, cap, server, answers, gate=gate, entered=entered)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await ch._handle_update(update("held before delivery"))
        gate.set()
        await asyncio.wait_for(ready.wait(), 1)
        await ch._handle_update(update("forwarded piece", forward_origin={"type": "user"}))
        await ch._flush_turn((123, "42", 8))
        await ch._handle_update(update("direct answer"))
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "direct answer"
    finally:
        orch._pending_input_service().close()
        gate.set()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await ch.client.aclose()
