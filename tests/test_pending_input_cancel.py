"""Explicit cancellation releases a delivered clarification outside busy lanes."""

import asyncio

import pytest

from tests.support.waiting import until
from tests.test_pending_input_ingress import transport, update
from tests.test_pending_input_runtime import incoming, runtime_host
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
