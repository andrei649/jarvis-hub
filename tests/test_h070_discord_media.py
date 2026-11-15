"""Owner-DM files leave only through the approved channel.reply task."""

from __future__ import annotations

import asyncio
import contextvars
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("discord")

from agents.core.channel_inbox import ChannelInboxStore
from agents.core.channel_reply import ChannelReplyBroker
from agents.core.channels import delivery_ledger, media_delivery
from agents.core.channels.discord import DiscordChannel, discord
from agents.core.channels.discord_media import DiscordMediaPermit, bind_permit, current_permit
from agents.core.channels.manager import ChannelManager


class _DM:
    def __init__(self, recipient=7, channel_id=123, send=None):
        self.id = channel_id
        self.recipient = SimpleNamespace(id=recipient)
        self.send = send or AsyncMock(return_value=SimpleNamespace(id=99))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    root.mkdir()
    file = root / "chart.png"
    file.write_bytes(b"safe output")
    monkeypatch.setattr(media_delivery, "allowed_roots", lambda: [root.resolve()])
    monkeypatch.setattr(discord, "DMChannel", _DM)
    dm = _DM()
    channel = DiscordChannel("offline")
    channel._running = True
    channel._client = SimpleNamespace(is_ready=lambda: True, get_channel=lambda _: dm)
    manager = ChannelManager()
    manager.register(channel)
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound("discord", "show chart", sender="7",
                                    metadata={"channel_id": "123"})
    queued = []

    def enqueue(_agent, _kind, _title, **kwargs):
        queued.append(kwargs)
        return 17

    owner = [True]
    broker = ChannelReplyBroker(inbox=inbox, enqueue=enqueue, channel_manager=manager,
                                discord_media_owner=lambda sender, cid: owner[0]
                                and sender == "7" and cid == "123")
    return SimpleNamespace(file=file, dm=dm, channel=channel, inbox=inbox, inbound=inbound,
                           queued=queued, owner=owner, broker=broker)


def _request(rig):
    result = rig.broker.request_for_message(
        rig.inbound["id"], f"Here is the chart.\nMEDIA: {rig.file}", channel="discord")
    assert result["ok"] and result["queued"]
    return rig.queued[-1]["payload"]


@pytest.mark.asyncio
async def test_approved_broker_manager_adapter_sends_one_file_to_owner_dm(rig, monkeypatch):
    sent_files = []

    class File:
        def __init__(self, fp, *, filename):
            sent_files.append((filename, fp.read()))

        def close(self):
            pass

    monkeypatch.setattr(discord, "File", File)
    payload = _request(rig)
    assert rig.queued[0]["autonomy_level"] == "ask"
    assert payload["text"] == "Here is the chart."
    assert payload["attachments"][0]["sha256"]
    outcome = await rig.broker.execute(SimpleNamespace(id=17, payload=payload))
    assert outcome["status"] == "ok"
    assert rig.dm.send.await_count == 2
    assert rig.dm.send.await_args_list[0].args == ("Here is the chart.",)
    assert sent_files == [("chart.png", b"safe output")]
    assert rig.dm.send.await_args_list[1].kwargs["file"]
    assert rig.inbox.messages(rig.inbound["thread_id"])[-1]["reply_to"] == rig.inbound["id"]


@pytest.mark.asyncio
async def test_direct_send_and_revoked_owner_cannot_attach(rig, monkeypatch):
    resolve = Mock(side_effect=AssertionError("direct send reached disk"))
    monkeypatch.setattr(media_delivery, "resolve", resolve)
    assert await rig.channel.send(f"literal\nMEDIA: {rig.file}", channel_id="123")
    assert rig.dm.send.await_count == 1
    assert rig.dm.send.await_args.args[0].startswith("literal\nMEDIA:")
    assert not await rig.channel.send("oops", channel_id="123", attachments=())
    assert rig.dm.send.await_count == 1
    rig.owner[0] = False
    assert rig.broker.request_for_message(
        rig.inbound["id"], f"Here\nMEDIA: {rig.file}", channel="discord")["ok"] is False
    resolve.assert_not_called()


@pytest.mark.asyncio
async def test_changed_file_or_target_or_owner_blocks_before_any_send(rig):
    payload = _request(rig)
    rig.file.write_bytes(b"changed")
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["reason"] == "attachment_changed"
    rig.file.write_bytes(b"safe output")
    changed_name = {**payload, "attachments": [{**payload["attachments"][0], "name": "other.png"}]}
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=changed_name)))["reason"] == "attachment_changed"
    redirected = {**payload, "reply": {"channel_id": "456"}}
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=redirected)))["reason"] == "inbound_binding_changed"
    rig.owner[0] = False
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["status"] == "blocked"
    rig.dm.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_or_other_dm_recipient_cannot_receive_approved_file(rig):
    payload = _request(rig)
    rig.channel._client.get_channel = lambda _: SimpleNamespace(id=123, send=AsyncMock())
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["status"] == "blocked"
    rig.channel._client.get_channel = lambda _: _DM(recipient=8)
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["status"] == "blocked"
    rig.dm.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_between_text_and_file_prevents_file_send(rig):
    payload = _request(rig)

    async def send(*args, **kwargs):
        rig.channel._running = False
        return SimpleNamespace(id=99)

    rig.dm.send = AsyncMock(side_effect=send)
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["status"] == "failed"
    assert rig.dm.send.await_count == 1


@pytest.mark.asyncio
async def test_permit_cannot_escape_its_task_or_scope(rig):
    permit = DiscordMediaPermit(
        task=asyncio.current_task(), adapter=rig.channel, channel_id=123, sender_id=7,
        reply_task_id=17, files=(), owner_allowed=lambda *_: True)
    copied = None
    with bind_permit(permit):
        copied = contextvars.copy_context()
        assert permit.current(rig.channel, 123, permit.files)
        async def inherited():
            return permit.current(rig.channel, 123, permit.files)

        assert await asyncio.create_task(inherited()) is False
    assert not permit.current(rig.channel, 123, permit.files)
    assert copied.run(current_permit) is permit
    assert not copied.run(permit.current, rig.channel, 123, permit.files)
    with pytest.raises(RuntimeError, match="already used"), bind_permit(permit):
        pass


@pytest.mark.asyncio
async def test_sdk_filename_redacts_known_credentials(rig, monkeypatch):
    secret = "verylongfakevalue321"
    monkeypatch.setenv("JARVIS_DISCORD_TEST_API_KEY", secret)
    rig.file.rename(rig.file.with_name("chart-" + secret + ".png"))
    rig.file = rig.file.with_name("chart-" + secret + ".png")
    filenames = []

    class File:
        def __init__(self, fp, *, filename):
            filenames.append(filename)

        def close(self):
            pass

    monkeypatch.setattr(discord, "File", File)
    payload = _request(rig)
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["status"] == "ok"
    assert len(filenames) == 1 and secret not in filenames[0]


@pytest.mark.asyncio
async def test_approved_reply_deduplicates_and_failed_file_is_recorded_partial(rig, tmp_path,
                                                                              monkeypatch):
    store = delivery_ledger.ReliabilityStore(tmp_path / "deliveries.db")
    monkeypatch.setattr(delivery_ledger, "store", lambda: store)
    try:
        payload = _request(rig)
        task = SimpleNamespace(id=17, payload=payload)
        assert (await rig.broker.execute(task))["status"] == "ok"
        assert (await rig.broker.execute(task))["status"] == "ok"
        assert rig.dm.send.await_count == 2
        rows = store.recent(10, channel="discord")
        keys = [row[0] for row in store._conn.execute("SELECT key FROM deliveries").fetchall()]
        assert len([key for key in keys if key.startswith("media:discord:")]) == 1
        assert len([row for row in rows if row["state"] == "sent"]) == 2

        # A new approved task whose file send fails leaves an honest partial reply.
        rig.dm.send.reset_mock()
        rig.dm.send.side_effect = [SimpleNamespace(id=100), RuntimeError("offline")]
        task = SimpleNamespace(id=18, payload=payload)
        assert (await rig.broker.execute(task))["status"] == "failed"
        assert rig.dm.send.await_count == 2
        rows = store.recent(10, channel="discord")
        assert any(row["state"] == "partial" for row in rows)
        assert ("channel.reply:18", "partial") in store._conn.execute(
            "SELECT key, state FROM deliveries").fetchall()
    finally:
        store.close()


def test_kernel_denial_refuses_attachment_before_queue(rig, monkeypatch):
    from agents.core.kernel import Decision, Verdict

    monkeypatch.setattr("agents.core.kernel.kernel_enabled", lambda: True)
    denied = ChannelReplyBroker(
        inbox=rig.inbox, enqueue=lambda *_a, **_k: pytest.fail("queued after denial"),
        channel_manager=rig.broker._channel_manager,
        discord_media_owner=rig.broker._discord_media_owner,
        kernel=lambda _action: Decision(Verdict.DENY, reason="policy_denied"))
    result = denied.request_for_message(rig.inbound["id"],
                                        f"Here\nMEDIA: {rig.file}", channel="discord")
    assert result["reason"] == "policy_denied"


@pytest.mark.asyncio
async def test_two_approved_names_with_identical_bytes_each_send_once(rig, tmp_path, monkeypatch):
    second = rig.file.with_name("chart-copy.png")
    second.write_bytes(rig.file.read_bytes())
    store = delivery_ledger.ReliabilityStore(tmp_path / "deliveries-two.db")
    monkeypatch.setattr(delivery_ledger, "store", lambda: store)
    names = []

    class File:
        def __init__(self, fp, *, filename):
            names.append(filename)

        def close(self):
            pass

    monkeypatch.setattr(discord, "File", File)
    try:
        result = rig.broker.request_for_message(
            rig.inbound["id"], f"Two charts\nMEDIA: {rig.file}\nMEDIA: {second}",
            channel="discord")
        assert result["queued"]
        task = SimpleNamespace(id=17, payload=rig.queued[-1]["payload"])
        assert (await rig.broker.execute(task))["status"] == "ok"
        assert (await rig.broker.execute(task))["status"] == "ok"
        assert names == ["chart.png", "chart-copy.png"]
        assert rig.dm.send.await_count == 3
        keys = [row[0] for row in store._conn.execute("SELECT key FROM deliveries").fetchall()]
        assert len([key for key in keys if key.startswith("media:discord:")]) == 2
    finally:
        store.close()
