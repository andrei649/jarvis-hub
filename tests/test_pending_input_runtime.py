"""H067 actual ToolRPC clarification and gateway interception before turn leases."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels.ephemeral import EphemeralReply
from agents.core.channels.gateway import Gateway
from agents.core.channels.pending_input_runtime import register_clarify_tool
from agents.core.native_human_wait import runtime_human_wait_scope
from agents.core.tool_rpc import ToolRPCServer
from tests.test_session_lifecycle_integration import host


def runtime_host(tmp_path, *, delivered=True):
    orch, captured, _ = host(tmp_path, {"channels.pending_inputs_enabled": True})
    ready = asyncio.Event()
    pairing = SimpleNamespace(allowed=True)
    pairing.is_allowed = lambda _channel, _sender: pairing.allowed
    pairing.gate_inbound = lambda _channel, _sender, **kw: {"allowed": pairing.allowed}
    orch.channels = {"telegram": SimpleNamespace(_pairing=pairing)}
    original = orch.channel_manager.send

    async def send(channel, response, **kwargs):
        await original(channel, response, **kwargs)
        if isinstance(response, EphemeralReply) and "Choose" in response:
            ready.set()
            return delivered
        return True

    orch.channel_manager.send = send
    server = ToolRPCServer()
    assert register_clarify_tool(server, orch)
    gateway = Gateway(orch.channel_handler, pairing=pairing)
    answers = []

    async def model(text, channel="voice", **kwargs):
        captured["sessions"].append(orch.session_id)
        if text == "ask":
            with runtime_human_wait_scope() as credit:
                captured["credit"] = credit
                answer = await server.handle(
                    {
                        "tool": "clarify",
                        "args": {
                            "question": "Choose a route",
                            "choices": ["Local", "Remote"],
                        },
                    }
                )
                answers.append((answer, credit.seconds()))
        return "Finished"

    orch.handle_input = model
    return orch, captured, gateway, server, ready, pairing, answers


async def incoming(gateway, text="ask", **kwargs):
    return await gateway.route(text, channel="telegram", chat_id=123, sender="42", **kwargs)


@pytest.mark.asyncio
async def test_model_waiting_on_tool_is_resumed_before_its_session_lease(tmp_path, monkeypatch):
    import agents.core.native_human_wait as human_wait

    clock = {"now": 1000.0}
    monkeypatch.setattr(human_wait, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    orch, cap, gateway, server, ready, _pairing, answers = runtime_host(tmp_path)
    model_turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert not model_turn.done()
        clock["now"] += 5
        assert cap["credit"].seconds() == 5
        assert await asyncio.wait_for(incoming(gateway, "2", message_thread_id=8), 1) == ""
        assert await asyncio.wait_for(model_turn, 1) == "Finished"
        assert len(cap["sessions"]) == 1
        assert answers[0][0]["result"]["user_response"] == "Remote"
        assert answers[0][0]["result"]["choices_offered"] == ["Local", "Remote"]
        assert answers[0][1] == 5
        assert server.declares_untrusted_output("clarify")
        assert cap["sent"][0][2]["message_thread_id"] == 8
    finally:
        orch._pending_input_service().close()
        model_turn.cancel()
        await asyncio.gather(model_turn, return_exceptions=True)


@pytest.mark.asyncio
async def test_invalid_selection_keeps_prompt_and_adds_no_model_turn(tmp_path):
    orch, cap, gateway, _server, ready, _pairing, answers = runtime_host(tmp_path)
    turn = asyncio.create_task(incoming(gateway))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        retry = await incoming(gateway, "9")
        assert isinstance(retry, EphemeralReply)
        assert not turn.done() and len(cap["sessions"]) == 1
        assert await incoming(gateway, "Local") == ""
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Local"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
async def test_cross_sender_or_topic_reply_never_answers_the_prompt(tmp_path):
    orch, cap, gateway, _server, ready, _pairing, answers = runtime_host(tmp_path)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        await gateway.route("2", channel="telegram", chat_id=123, sender="99", message_thread_id=9)
        await incoming(gateway, "2", message_thread_id=9)
        assert not turn.done() and not answers
        assert await incoming(gateway, "1", message_thread_id=8) == ""
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Local"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_delivery_does_not_wait_or_earn_credit(tmp_path):
    orch, _cap, gateway, _server, _ready, _pairing, answers = runtime_host(
        tmp_path, delivered=False
    )
    await asyncio.wait_for(incoming(gateway), 1)
    assert answers[0][0]["result"]["reason"] == "prompt_delivery_failed"
    assert answers[0][1] == 0
    from agents.core.channels.pending_input_runtime import pending_key
    from agents.core.channels.session import SessionSource

    key = pending_key(SessionSource(channel="telegram", thread_id="123", sender="42"))
    assert orch._pending_input_service().inputs.pending(key) is None
    orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_failed_delivery_retires_only_its_prompt_when_waiter_never_starts(tmp_path):
    from agents.core.channels.pending_input_runtime import pending_key
    from agents.core.channels.session import SessionSource

    orch, _cap, _gateway, server, _ready, _pairing, _answers = runtime_host(
        tmp_path, delivered=False
    )
    runtime = orch._pending_input_service()
    source = SessionSource(channel="telegram", thread_id="123", sender="42")
    key = pending_key(source)
    first = runtime.inputs.register_clarify(key, "Existing", ["A", "B"])
    with runtime.bind(source, {"chat_id": 123}):
        result = await server.handle({"tool": "clarify", "args": {"question": "Choose a route"}})
    assert result["result"]["reason"] == "prompt_delivery_failed"
    assert runtime.inputs.pending(key).id == first.id
    assert runtime.inputs.resolve(first.id, key, "A")
    assert runtime.inputs.pending(key) is None
    runtime.close()


@pytest.mark.asyncio
async def test_pairing_revoked_during_wait_and_shutdown_resume_without_answer(tmp_path):
    orch, _cap, gateway, _server, ready, pairing, answers = runtime_host(tmp_path)
    turn = asyncio.create_task(incoming(gateway))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        pairing.allowed = False
        assert await incoming(gateway, "1") is None
        await asyncio.wait_for(turn, 1.5)
        assert answers[0][0]["result"]["reason"] == "prompt_binding_lost"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
async def test_model_context_absent_or_closed_cannot_prompt(tmp_path):
    orch, cap, _gateway, server, _ready, _pairing, _answers = runtime_host(tmp_path)
    response = await server.handle({"tool": "clarify", "args": {"question": "Choose a route"}})
    assert response["result"]["reason"] == "clarify_context_unavailable"
    assert not cap["sent"]
    orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_shutdown_releases_a_delivered_wait_without_resurrecting_it(tmp_path):
    orch, _cap, gateway, server, ready, _pairing, answers = runtime_host(tmp_path)
    turn = asyncio.create_task(incoming(gateway))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        orch._pending_input_service().close()
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["reason"] == "clarify_cancelled_or_timed_out"
        result = await server.handle({"tool": "clarify", "args": {"question": "Choose again"}})
        assert result["result"]["reason"] == "clarify_context_unavailable"
    finally:
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
async def test_detached_child_of_closed_turn_cannot_create_a_new_prompt(tmp_path):
    from agents.core.channels.session import SessionSource

    orch, cap, _gateway, server, _ready, _pairing, _answers = runtime_host(tmp_path)
    runtime = orch._pending_input_service()
    gate = asyncio.Event()

    async def child():
        await gate.wait()
        return await server.handle({"tool": "clarify", "args": {"question": "Choose later"}})

    with runtime.bind(
        SessionSource(channel="telegram", thread_id="123", sender="42"), {"chat_id": 123}
    ):
        task = asyncio.create_task(child())
    gate.set()
    result = await asyncio.wait_for(task, 1)
    assert result["result"]["reason"] == "clarify_context_unavailable"
    assert not cap["sent"]
    runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("choices", [["", "B"], ["(Recommended)", "B"]])
async def test_empty_display_choice_is_rejected_without_delivery(tmp_path, choices):
    from agents.core.channels.session import SessionSource

    orch, cap, _gateway, server, _ready, _pairing, _answers = runtime_host(tmp_path)
    runtime = orch._pending_input_service()
    with runtime.bind(
        SessionSource(channel="telegram", thread_id="123", sender="42"), {"chat_id": 123}
    ):
        result = await asyncio.wait_for(
            server.handle(
                {"tool": "clarify", "args": {"question": "Choose a route", "choices": choices}}
            ),
            1,
        )
    assert result["result"]["reason"] == "invalid_clarify_args"
    assert not cap["sent"]
    runtime.close()


def test_default_off_does_not_change_registered_tool_list(tmp_path):
    orch, _cap, _ = host(tmp_path)
    server = ToolRPCServer()
    assert not register_clarify_tool(server, orch)
    assert not server.allows("clarify")
    assert not register_clarify_tool(server, SimpleNamespace())
