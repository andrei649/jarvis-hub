"""H067 Slack cards and fast pending ingress, entirely offline."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from agents.core.channels.slack import SlackChannel
from tests.test_slack_socket_mode import SDKResponse, envelope, sdk  # noqa: F401


@pytest.fixture(autouse=True)
def no_batch(monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")


def keyboard():
    return {"inline_keyboard": [[{"text": "Yes", "callback_data": "h067:abcdefghijklmnop:0:c0"}]]}


@pytest.mark.parametrize("label,prefix", [
    ("1. " + "Remote destination " * 8 + "(Recommended)", "1. "),
    ("✓ 2. " + "Local route " * 10, "✓ 2. "),
])
def test_long_choice_labels_keep_prefix_and_callback_when_clipped(label, prefix):
    markup = keyboard()
    markup["inline_keyboard"][0][0]["text"] = label
    blocks = SlackChannel._pending_blocks("Choose", markup)
    assert blocks is not None
    button = blocks[-1]["elements"][0]
    assert button["text"]["text"].startswith(prefix)
    assert button["text"]["text"].endswith("…")
    assert len(button["text"]["text"]) == 75
    assert button["value"] == "h067:abcdefghijklmnop:0:c0"


def action(*, team="T1", user="U1", channel="D1", ts="101.000001", thread=None,
           data="h067:abcdefghijklmnop:0:c0"):
    message = {"user": "UBOT", "ts": ts}
    if thread is not None:
        message["thread_ts"] = thread
    return SimpleNamespace(type="interactive", envelope_id="envelope-action", payload={
        "type": "block_actions", "team": {"id": team}, "user": {"id": user},
        "container": {"type": "message", "channel_id": channel, "message_ts": ts},
        "channel": {"id": channel}, "message": message,
        "actions": [{"type": "button", "action_id": "h067_pending", "value": data}],
    })


@pytest.mark.asyncio
async def test_card_uses_final_chunk_and_requires_exact_slack_receipt(sdk):
    channel = SlackChannel("bot", app_token="app")
    await channel.start()
    web = sdk.sockets[0].web_client
    web.chat_postMessage = lambda **kwargs: (web.posts.append(kwargs) or SDKResponse({
        "ok": True, "channel": "D1", "ts": "101.000001"}))
    try:
        receipt = await channel.send_pending_card("x" * 40001, reply_markup=keyboard(),
                                                  slack_channel="D1", thread_ts="99.000001")
        assert receipt == {"channel": "slack", "target": "D1", "message_id": "101.000001",
                           "thread_id": "99.000001", "team_id": "T1"}
        assert len(web.posts) == 2
        assert "blocks" not in web.posts[0]
        assert web.posts[1]["blocks"][-1]["type"] == "actions"
        web.chat_postMessage = lambda **kwargs: SDKResponse({
            "ok": True, "channel": "D2", "ts": "101.000001"})
        assert await channel.send_pending_card("ask", reply_markup=keyboard(),
                                               slack_channel="D1") is None
        web.chat_postMessage = lambda **kwargs: SDKResponse({
            "ok": True, "channel": "D1", "ts": True})
        assert await channel.send_pending_card("ask", reply_markup=keyboard(),
                                               slack_channel="D1") is None
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_pending_reply_bypasses_blocked_dispatch_and_false_routes_normal(sdk):
    entered, release, pending = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []

    async def handler(text, **kwargs):
        seen.append(text)
        if text == "first":
            entered.set()
            await release.wait()

    async def reply(text, **kwargs):
        if text == "answer":
            assert kwargs == {"channel": "slack", "sender": "T1:U1",
                              "slack_channel": "D1", "thread_ts": None}
            pending.set()
            return True
        return False

    pairing = SimpleNamespace(is_allowed=lambda channel, sender: (channel, sender) == ("slack", "T1:U1"))
    channel = SlackChannel("bot", handler, app_token="app", pairing=pairing,
                           pending_reply_handler=reply)
    await channel.start()
    client = sdk.sockets[0]
    try:
        client.emit(envelope(event={"text": "first"}))
        await asyncio.wait_for(entered.wait(), 1)
        client.emit(envelope("Ev2", event={"text": "answer"}))
        await asyncio.wait_for(pending.wait(), 1)
        assert seen == ["first"]
        client.emit(envelope("Ev3", event={"text": "ordinary"}))
        release.set()
        for _ in range(30):
            if seen == ["first", "ordinary"]:
                break
            await asyncio.sleep(0.01)
        assert seen == ["first", "ordinary"]
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_authenticated_button_is_acknowledged_then_applied_without_model(sdk):
    seen = []
    applied = asyncio.Event()

    async def callback(value, **kwargs):
        assert kwargs == {"channel": "slack"}
        seen.append(value)
        applied.set()
        return SimpleNamespace(applied=True, status="updated", prompt_id="p",
                               markup=keyboard())

    pairing = SimpleNamespace(is_allowed=lambda channel, sender: (channel, sender) == ("slack", "T1:U1"))
    channel = SlackChannel("bot", app_token="app", pairing=pairing,
                           pending_callback_handler=callback)
    await channel.start()
    client = sdk.sockets[0]
    edits = []
    client.web_client.chat_update = lambda **kwargs: (edits.append(kwargs) or SDKResponse({"ok": True}))
    try:
        client.emit(action())
        await asyncio.wait_for(applied.wait(), 1)
        for _ in range(10):
            if edits:
                break
            await asyncio.sleep(0.01)
        assert client.acks == ["envelope-action"]
        assert seen == [{"channel": "slack", "target": "D1", "message_id": "101.000001",
                         "thread_id": None, "team_id": "T1", "sender": "T1:U1",
                         "data": "h067:abcdefghijklmnop:0:c0"}]
        assert edits[0]["channel"] == "D1" and edits[0]["ts"] == "101.000001"
        assert edits[0]["blocks"][-1]["type"] == "actions"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_callback_rejects_cross_team_or_mismatched_message(sdk):
    seen = []

    async def callback(value, **kwargs):
        seen.append(value)

    pairing = SimpleNamespace(is_allowed=lambda channel, sender: True)
    channel = SlackChannel("bot", app_token="app", pairing=pairing,
                           pending_callback_handler=callback)
    await channel.start()
    try:
        sdk.sockets[0].emit(action(team="T2"))
        bad = action()
        bad.payload["message"]["ts"] = "102.000001"
        sdk.sockets[0].emit(bad)
        await asyncio.sleep(0)
        assert seen == []
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_stop_cancels_owned_callback_and_stale_generation_cannot_edit(sdk):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def callback(value, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    pairing = SimpleNamespace(is_allowed=lambda channel, sender: True)
    channel = SlackChannel("bot", app_token="app", pairing=pairing,
                           pending_callback_handler=callback)
    await channel.start()
    client = sdk.sockets[0]
    client.emit(action())
    await asyncio.wait_for(entered.wait(), 1)
    await channel.stop()
    assert cancelled.is_set() and not channel._pending_fast
    assert channel._pending_fast_reserved == 0


@pytest.mark.asyncio
async def test_card_accepts_real_slack_response_mapping_without_network(sdk):
    responses = pytest.importorskip("slack_sdk.web.slack_response")
    channel = SlackChannel("bot", app_token="app")
    await channel.start()
    web = sdk.sockets[0].web_client

    def post(**kwargs):
        return responses.SlackResponse(
            client=web, http_verb="POST", api_url="https://slack.invalid/chat.postMessage",
            req_args=kwargs, data={"ok": True, "channel": "D1", "ts": "102.000001"},
            headers={}, status_code=200)

    web.chat_postMessage = post
    try:
        assert await channel.send_pending_card("Ask", reply_markup=keyboard(),
                                               slack_channel="D1") == {
            "channel": "slack", "target": "D1", "message_id": "102.000001",
            "thread_id": None, "team_id": "T1"}
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_button_bypasses_busy_dispatch_but_rechecks_pairing(sdk):
    entered, release, applied = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []
    allowed = True

    async def handler(text, **kwargs):
        entered.set()
        await release.wait()

    async def callback(value, **kwargs):
        seen.append(value)
        applied.set()
        return SimpleNamespace(applied=False)

    def paired(channel, sender):
        return allowed and (channel, sender) == ("slack", "T1:U1")

    channel = SlackChannel("bot", handler, app_token="app",
                           pairing=SimpleNamespace(is_allowed=paired),
                           pending_callback_handler=callback)
    await channel.start()
    client = sdk.sockets[0]
    try:
        client.emit(envelope())
        await asyncio.wait_for(entered.wait(), 1)
        client.emit(action())
        await asyncio.wait_for(applied.wait(), 1)
        assert len(seen) == 1
        allowed = False
        client.emit(action())
        await asyncio.sleep(0)
        assert len(seen) == 1
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_inflight_send_cannot_bind_receipt_after_generation_changes(sdk):
    channel = SlackChannel("bot", app_token="app")
    await channel.start()
    entered, release = threading.Event(), threading.Event()

    def post(**kwargs):
        entered.set()
        release.wait(timeout=2)
        return SDKResponse({"ok": True, "channel": "D1", "ts": "103.000001"})

    sdk.sockets[0].web_client.chat_postMessage = post
    sending = asyncio.create_task(channel.send_pending_card("Ask", reply_markup=keyboard(),
                                                            slack_channel="D1"))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        channel._pending_callback_generation = object()
        release.set()
        assert await asyncio.wait_for(sending, 1) is None
    finally:
        release.set()
        await channel.stop()
