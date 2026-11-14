"""Slack native prompt outcomes use the real manager and an offline SDK."""

import asyncio
import threading

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.manager import ChannelManager
from agents.core.channels.slack import SlackChannel
from tests.test_pending_input_slack_transport import keyboard
from tests.test_slack_socket_mode import SDKResponse, sdk  # noqa: F401


async def rig(tmp_path, monkeypatch, sdk):
    store = delivery_ledger.ReliabilityStore(tmp_path / "slack-receipts.sqlite")
    monkeypatch.setattr(delivery_ledger, "store", lambda: store)
    channel = SlackChannel("bot", app_token="app")
    await channel.start()
    manager = ChannelManager()
    manager.register(channel)
    return manager, channel, sdk.sockets[0].web_client, store


def row(store):
    rows = store.recent(5)
    assert len(rows) == 1
    assert rows[0]["channel"] == "slack" and rows[0]["target"] == "D1"
    assert rows[0]["keyed"] is False
    assert "Private prompt" not in str(rows) and "Private choice" not in str(rows)
    assert "reply_markup" not in str(rows) and "101.000001" not in str(rows)
    return rows[0]


async def prompt(manager, message="Private prompt"):
    markup = keyboard()
    markup["inline_keyboard"][0][0]["text"] = "Private choice"
    return await manager.send_channel_prompt("slack", message, markup, slack_channel="D1")


@pytest.mark.asyncio
async def test_preflight_refusal_does_not_post_and_records_failed(tmp_path, monkeypatch, sdk):
    manager, channel, web, store = await rig(tmp_path, monkeypatch, sdk)
    try:
        channel._team_id = None
        assert await prompt(manager) is None
        assert web.posts == []
        assert row(store)["state"] == "failed"
    finally:
        await channel.stop()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,expected", [
    ({"ok": True, "channel": "D1", "ts": "101.000001"}, "sent"),
    ({"ok": True, "channel": "D2", "ts": "101.000001"}, "unknown"),
    ({"ok": True, "channel": "D1", "ts": True}, "unknown"),
    ({"ok": False, "channel": "D1", "ts": "101.000001"}, "unknown"),
    (None, "unknown"),
])
async def test_one_part_requires_exact_ack(tmp_path, monkeypatch, sdk, answer, expected):
    manager, channel, web, store = await rig(tmp_path, monkeypatch, sdk)

    def post(**kwargs):
        web.posts.append(kwargs)
        return SDKResponse(answer) if answer is not None else None

    web.chat_postMessage = post
    try:
        receipt = await prompt(manager)
        if expected == "sent":
            assert receipt == {"channel": "slack", "target": "D1", "message_id": "101.000001",
                               "thread_id": None, "team_id": "T1"}
        else:
            assert receipt is None
        assert len(web.posts) == 1
        assert row(store)["state"] == expected
    finally:
        await channel.stop()
        store.close()


@pytest.mark.asyncio
async def test_unexpected_sdk_exception_after_post_is_unknown(tmp_path, monkeypatch, sdk):
    manager, channel, web, store = await rig(tmp_path, monkeypatch, sdk)

    def post(**kwargs):
        web.posts.append(kwargs)
        raise RuntimeError("private SDK error body")

    web.chat_postMessage = post
    try:
        assert await prompt(manager) is None
        assert len(web.posts) == 1
        assert row(store)["state"] == "unknown"
        assert "private SDK error body" not in str(store.recent(1))
    finally:
        await channel.stop()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("later", ["malformed", "raises"])
async def test_verified_first_part_then_later_failure_is_partial(tmp_path, monkeypatch, sdk, later):
    manager, channel, web, store = await rig(tmp_path, monkeypatch, sdk)

    def post(**kwargs):
        web.posts.append(kwargs)
        if len(web.posts) == 1:
            return SDKResponse({"ok": True, "channel": "D1", "ts": "101.000001"})
        if later == "raises":
            raise RuntimeError("private SDK failure")
        return SDKResponse({"ok": True, "channel": "D1", "ts": True})

    web.chat_postMessage = post
    try:
        assert await prompt(manager, "x" * 40001) is None
        assert len(web.posts) == 2
        assert "blocks" not in web.posts[0] and "blocks" in web.posts[1]
        assert row(store)["state"] == "partial"
    finally:
        await channel.stop()
        store.close()


@pytest.mark.asyncio
async def test_valid_ack_followed_by_generation_change_is_partial(tmp_path, monkeypatch, sdk):
    manager, channel, web, store = await rig(tmp_path, monkeypatch, sdk)
    entered, release = threading.Event(), threading.Event()

    def post(**kwargs):
        web.posts.append(kwargs)
        entered.set()
        release.wait(timeout=2)
        return SDKResponse({"ok": True, "channel": "D1", "ts": "101.000001"})

    web.chat_postMessage = post
    task = asyncio.create_task(prompt(manager))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        channel._pending_callback_generation = object()
        release.set()
        assert await asyncio.wait_for(task, 1) is None
        assert row(store)["state"] == "partial"
    finally:
        release.set()
        await channel.stop()
        store.close()


@pytest.mark.asyncio
async def test_cancelled_sdk_wait_propagates_without_claiming_sent(tmp_path, monkeypatch, sdk):
    manager, channel, web, store = await rig(tmp_path, monkeypatch, sdk)
    entered, release = threading.Event(), threading.Event()

    def post(**kwargs):
        web.posts.append(kwargs)
        entered.set()
        release.wait(timeout=2)
        return SDKResponse({"ok": True, "channel": "D1", "ts": "101.000001"})

    web.chat_postMessage = post
    task = asyncio.create_task(prompt(manager))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert row(store)["state"] == "unknown"
    finally:
        release.set()
        await channel.stop()
        store.close()
