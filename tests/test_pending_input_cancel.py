"""Explicit cancellation releases a delivered clarification outside busy lanes."""

import asyncio

import pytest

from tests.test_ntfy_inbound import until
from tests.test_pending_input_ingress import transport, update
from tests.test_pending_input_ntfy import cleanup_host, ntfy_host, queued_prompt
from tests.test_pending_input_runtime import incoming, runtime_host
from tests.test_pending_input_workspace_broker import prompt_broker  # noqa: F401
from tests.test_pending_input_workspace_runtime import waiting_prompt, workspace_host
from tests.test_session_command_kernel import governed  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/cancel", "!CANCEL"])
async def test_telegram_cancel_releases_occupied_chat_lane_without_new_turn(tmp_path, command):
    orch, cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    channel = transport(orch, gateway, pairing)
    gateway.set_rate_limit(1)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert not await gateway.route_pending(command, channel="telegram", chat_id=123,
                                               sender="99", message_thread_id=8)
        assert not await gateway.route_pending(command, channel="telegram", chat_id=123,
                                               sender="42", message_thread_id=9)
        assert not await gateway.route_pending("/cancel extra", channel="telegram", chat_id=123,
                                               sender="42", message_thread_id=8)
        assert not answers and not turn.done()
        runtime = orch._pending_input_service()
        first = next(iter(runtime.inputs._active.values()))
        neighbour = runtime.inputs.register_clarify(first.key, "Next question")
        await channel._handle_update(update(command))
        await until(lambda: answers)
        assert answers[0][0]["result"]["reason"] == "clarify_cancelled_or_timed_out"
        assert runtime.inputs.pending(first.key) is neighbour
        assert len(cap["sessions"]) == 1
        assert "Rate limit" in await incoming(gateway, "ordinary", message_thread_id=8)
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_choice_named_cancel_is_an_answer_not_a_cancellation(tmp_path):
    orch, cap, gateway, server, ready, pairing, answers = runtime_host(tmp_path)
    channel = transport(orch, gateway, pairing)
    handle = server.handle

    async def choices(request, *args, **kwargs):
        return await handle({**request, "args": {**request["args"], "choices": ["Cancel", "Continue"]}},
                            *args, **kwargs)

    server.handle = choices
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        await channel._handle_update(update("Cancel"))
        await until(lambda: answers)
        assert answers[0][0]["result"]["user_response"] == "Cancel"
        assert len(cap["sessions"]) == 1
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
async def test_workspace_cancel_releases_actual_rpc_and_retires_card(tmp_path, prompt_broker, channel):
    orch, cap, gateway, _server, _pairing, answers, adapter, _requests, meta = await workspace_host(
        tmp_path, prompt_broker, channel)
    _broker, queue, worker, *_ = prompt_broker
    gateway.set_rate_limit(1)
    turn = asyncio.create_task(gateway.route("ask", channel=channel, **meta))
    try:
        queued = await waiting_prompt(queue, turn)
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        assert (await worker.tick(task_id=queued.id))["done"] == 1
        await until(lambda: orch._pending_input_service()._delivered)
        assert await gateway.route_pending("/cancel", channel=channel, **meta)
        await until(lambda: answers)
        assert answers[0][0]["result"]["reason"] == "clarify_cancelled_or_timed_out"
        await asyncio.wait_for(turn, 1)
        assert len(cap["sessions"]) == 1
        assert not orch._pending_input_service().cards._cards
    finally:
        orch._pending_input_service().close()
        orch.channel_replies.close_pending_prompts()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await adapter.stop()


@pytest.mark.asyncio
async def test_ntfy_cancel_is_read_while_its_model_holds_serial_dispatch(tmp_path, prompt_broker):
    orch, cap, gateway, answers, channel, _requests, release, _broker, queue, worker = await ntfy_host(
        tmp_path, prompt_broker, answer="/cancel")
    gateway.set_rate_limit(1)
    try:
        await channel.start()
        await until(lambda: queue.list())
        queued = await queued_prompt(queue, orch)
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        assert (await worker.tick(task_id=queued.id))["done"] == 1
        await until(lambda: orch._pending_input_service()._delivered)
        release.set()
        await until(lambda: answers)
        assert answers[0][0]["result"]["reason"] == "clarify_cancelled_or_timed_out"
        assert len(cap["sessions"]) == 1
        assert channel._events.qsize() == 0
    finally:
        await cleanup_host(orch, channel)
