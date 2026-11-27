"""H067 completion via real gateway, signed delivery and durable conversation."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.test_h011_rollback_conversation import context  # noqa: F401
from tests.test_pending_input_runtime import incoming, runtime_host
from tests.test_session_command_kernel import governed  # noqa: F401
from tests.test_session_command_runtime import command_host


@pytest.mark.asyncio
async def test_registered_clarify_tool_uses_new_runtime_after_same_instance_close(tmp_path):
    orch, _, gateway, _, ready, _, answers = runtime_host(tmp_path)
    prior = orch._pending_input_service()
    prior.close()
    turn = asyncio.create_task(incoming(gateway))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert orch._pending_input_service() is not prior
        assert await incoming(gateway, "2") == ""
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Remote"
        assert prior.closed and not prior._delivered
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_second", [False, True])
async def test_batch_clarify_keeps_completed_answers_and_stops_after_timeout(tmp_path, stop_second):
    orch, _, gateway, server, ready, _, answers = runtime_host(tmp_path)
    original = server.handle

    async def handle(request, *args, **kwargs):
        request = {**request, "args": {"questions": [
            {"id": "route", "question": "Choose a route", "choices": [{"label": "Local"}, "Remote"]},
            {"id": "tag", "question": "Choose a tag", "choices": ["Blue", "Green"], "multi_select": True},
            {"id": "memo", "question": "Choose a note"},
        ]}}
        return await original(request, *args, **kwargs)

    server.handle = handle
    orch._runtime_settings["agent.clarify_timeout"] = 0.04 if stop_second else 1
    turn = asyncio.create_task(incoming(gateway))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await incoming(gateway, "2") == ""
        for _ in range(100):
            await asyncio.sleep(0)
            delivered = list(orch._pending_input_service()._delivered)
            if delivered:
                prompt = orch._pending_input_service().inputs._active.get(delivered[0])
                if prompt is not None and prompt.question == "Choose a tag":
                    break
        assert prompt.question == "Choose a tag"
        if not stop_second:
            assert await incoming(gateway, "1,2") == ""
            for _ in range(100):
                await asyncio.sleep(0)
                delivered = list(orch._pending_input_service()._delivered)
                prompt = orch._pending_input_service().inputs._active.get(delivered[0]) if delivered else None
                if prompt is not None and prompt.question == "Choose a note":
                    break
            assert await incoming(gateway, "my note") == ""
        await asyncio.wait_for(turn, 1)
        result = answers[0][0]["result"]
        assert result["ok"] and result["responses"][0]["id"] == "route"
        assert result["responses"][0]["user_response"] == "Remote"
        assert result["responses"][0]["choices_offered"] == ["Local", "Remote"]
        if stop_second:
            assert result["timed_out"] is True
            assert result["responses"][1]["user_response"] == result["responses"][2]["user_response"] == ""
            assert len(orch._pending_input_service()._delivered) == 0
        else:
            assert result["responses"][1]["user_response"] == ["Blue", "Green"]
            assert result["responses"][2]["user_response"] == "my note"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


def test_flatten_unwraps_label_first():
    """Unmodified donor assertion from tests/tools/test_clarify_tool.py (MIT)."""
    from agents.core.channels.clarify_protocol import _flatten_choice

    assert _flatten_choice({"label": "Short", "description": "Long"}) == "Short"


@pytest.mark.parametrize("questions", [None, "bad", [False], [{"question": " "}], ["Q"] * 6,
                                       [{"question": "Q", "choices": "bad"}]])
def test_donor_batch_validation_refuses_invalid_questions(questions):
    from agents.core.channels.clarify_protocol import _normalize_questions

    normalized, error = _normalize_questions(questions)
    assert normalized is None and error


def test_donor_batch_stable_ids_choice_cap_and_recommendation():
    from agents.core.channels.clarify_protocol import _normalize_questions

    normalized, error = _normalize_questions([
        {"id": "owner-label", "question": " Q ", "choices": [{"description": " A "}, "B", "C", "D", "E"]},
        {"question": "memo", "multi_select": True},
    ])
    assert not error and [entry["qid"] for entry in normalized] == ["q0", "q1"]
    assert normalized[0]["id"] == "owner-label"
    assert normalized[0]["choices"] == ["A (Recommended)", "B", "C", "D"]
    assert normalized[0]["choices_offered"] == ["A", "B", "C", "D"]
    assert not normalized[1]["multi_select"]


@pytest.mark.asyncio
async def test_stopping_channels_cannot_recreate_a_pending_runtime(tmp_path):
    from unittest.mock import AsyncMock

    orch, _, _, server, _, _, _ = runtime_host(tmp_path)
    prior = orch._pending_input_service()
    orch.heartbeat_scheduler = SimpleNamespace(stop=lambda: None)
    orch.plugin_manager = SimpleNamespace(close_all=AsyncMock())
    orch.channel_manager.stop_all = AsyncMock()
    await orch.stop_channels()
    assert prior.closed
    assert orch._pending_input_service() is None
    result = await server.handle({"tool": "clarify", "args": {"question": "Choose"}})
    assert result["result"]["ok"] is False
    assert orch._pending_inputs is prior


@pytest.mark.asyncio
async def test_same_instance_channel_restart_reopens_route_without_losing_history(tmp_path, context, monkeypatch):
    from unittest.mock import AsyncMock

    from tests.test_session_command_runtime import message

    monkeypatch.setenv("JARVIS_TESTING", "1")
    orch, _, gateway, _, _, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    sid = orch._channel_sessions[base]
    history = await orch.memory.get_history(sid)
    prior = orch._channel_lifecycle
    orch.heartbeat_scheduler = SimpleNamespace(stop=lambda: None, start=lambda _orch: None)
    orch.plugin_manager = SimpleNamespace(close_all=AsyncMock())
    orch.channel_manager.stop_all = AsyncMock()
    orch.channel_manager.start_all = AsyncMock()
    orch._settings_watcher_loop = AsyncMock()
    orch._autonomy = SimpleNamespace(wire=lambda: None, loop=AsyncMock())
    orch._scheduler = SimpleNamespace(schedule_all=lambda: None)
    orch.oracle_bridge = None
    orch.components = SimpleNamespace(summary=lambda: {})
    await orch.stop_channels()
    await orch.start_channels()
    try:
        assert await message(gateway, "next") == "reply"
        assert orch._channel_lifecycle is not prior and prior.closed
        assert orch._channel_sessions[base] == sid
        assert (await orch.memory.get_history(sid))[:len(history)] == history
    finally:
        await orch.stop_channels()


@pytest.mark.asyncio
async def test_other_explains_typed_fallback_even_if_edit_and_instruction_send_fail(tmp_path, monkeypatch):
    import httpx

    from tests.test_pending_input_native_transport import (
        applied_tap,
        finish,
        keyboard,
        native_host,
        tap,
    )

    orch, _, gateway, _, ready, _, answers, channel, requests = await native_host(tmp_path)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        original = channel.client.post

        async def post(url, **kwargs):
            if url.endswith(("/editMessageReplyMarkup", "/sendMessage")):
                return httpx.Response(400, json={"ok": False}, request=httpx.Request("POST", url))
            return await original(url, **kwargs)

        monkeypatch.setattr(channel.client, "post", post)
        await applied_tap(channel, tap(keyboard(requests)[-2][0]["callback_data"]))
        assert any(method == "answerCallbackQuery" and "Type your answer" in body["text"]
                   for method, body in requests)
        assert await incoming(gateway, "my route", message_thread_id=8) == ""
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "my route"
    finally:
        await finish(orch, channel, turn)


@pytest.mark.asyncio
async def test_telegram_restart_reopens_http_and_owned_deletion_lifecycle(monkeypatch):
    from unittest.mock import AsyncMock

    from agents.core.channels.telegram import TelegramChannel

    channel = TelegramChannel(token="synthetic")
    await channel.stop()
    old_client = channel.client
    monkeypatch.setattr(channel, "_get_me", AsyncMock(return_value={"id": 1, "username": "synthetic"}))
    monkeypatch.setattr(channel, "_poll_loop", AsyncMock())
    try:
        await channel.start()
        assert not channel.client.is_closed and channel.client is not old_client
        assert not channel._ephemeral_deletes._closed
    finally:
        await channel.stop()
