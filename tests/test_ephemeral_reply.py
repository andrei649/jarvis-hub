"""H067 temporary notices: delivery acknowledgements, deletion and shutdown."""

import asyncio

import httpx
import pytest

from agents.core.channels.ephemeral import EphemeralDeletes, EphemeralReply, ephemeral_ttl
from agents.core.channels.telegram import TelegramChannel


def test_notice_is_text_and_default_retains_it():
    notice = EphemeralReply("Session unchanged.")
    assert isinstance(notice, str) and notice.text == "Session unchanged."
    assert ephemeral_ttl(notice) == 0
    assert ephemeral_ttl(notice, default=30) == 30
    assert ephemeral_ttl(EphemeralReply("notice", 0), default=30) == 0
    assert ephemeral_ttl("ordinary reply", default=30) == 0


@pytest.mark.parametrize("ttl", [True, -1, 1.5, "30", float("inf"), float("nan")])
def test_explicit_invalid_ttl_is_rejected(ttl):
    with pytest.raises(ValueError):
        EphemeralReply("notice", ttl)


@pytest.mark.parametrize("ttl", [True, -1, "30", float("inf"), None])
def test_invalid_setting_retains_notice(ttl):
    assert ephemeral_ttl(EphemeralReply("notice"), default=ttl) == 0


@pytest.mark.asyncio
async def test_owned_delayed_delete_capacity_and_actual_outcome():
    release = asyncio.Event()
    entered = asyncio.Event()
    completed = asyncio.Event()
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        entered.set()
        await release.wait()

    async def delete():
        completed.set()
        return True

    tasks = EphemeralDeletes(max_pending=1, sleep=sleep)
    assert not tasks.schedule(0, delete)
    assert tasks.schedule(7, delete)
    assert not tasks.schedule(7, delete)
    await asyncio.wait_for(entered.wait(), 1)
    assert sleeps == [7] and not completed.is_set()
    release.set()
    await asyncio.wait_for(completed.wait(), 1)
    await asyncio.sleep(0)
    assert tasks.deleted_count == 1 and tasks.failed_count == 0
    assert await tasks.aclose()
    assert not tasks.schedule(7, delete)


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_failed_delete_is_never_counted_as_success(raises):
    called = asyncio.Event()

    async def sleep(_delay):
        pass

    async def delete():
        called.set()
        if raises:
            raise RuntimeError("synthetic deletion failure")
        return False

    tasks = EphemeralDeletes(sleep=sleep)
    assert tasks.schedule(1, delete)
    await asyncio.wait_for(called.wait(), 1)
    await asyncio.sleep(0)
    assert tasks.deleted_count == 0 and tasks.failed_count == 1
    assert await tasks.aclose()


@pytest.mark.asyncio
async def test_shutdown_cancels_waiting_notice_without_deletion():
    entered = asyncio.Event()
    deleted = []

    async def sleep(_delay):
        entered.set()
        await asyncio.Event().wait()

    async def delete():
        deleted.append(True)
        return True

    tasks = EphemeralDeletes(sleep=sleep)
    assert tasks.schedule(1, delete)
    await asyncio.wait_for(entered.wait(), 1)
    assert await tasks.aclose()
    assert not deleted and tasks.pending_count == 0


@pytest.mark.asyncio
async def test_shutdown_retains_cancellation_resistant_task_with_bounded_wait():
    entered, release = asyncio.Event(), asyncio.Event()
    deleted = []

    async def sleep(_delay):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()

    async def delete():
        deleted.append(True)
        return True

    tasks = EphemeralDeletes(sleep=sleep)
    assert tasks.schedule(1, delete)
    await asyncio.wait_for(entered.wait(), 1)
    assert not await tasks.aclose(timeout=0)
    assert tasks.pending_count == 1
    release.set()
    assert await tasks.aclose()
    assert not deleted


@pytest.mark.asyncio
async def test_inflight_delete_after_shutdown_is_owned_but_not_reported_as_success():
    entered, release = asyncio.Event(), asyncio.Event()

    async def sleep(_delay):
        pass

    async def delete():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return True

    tasks = EphemeralDeletes(sleep=sleep)
    assert tasks.schedule(1, delete)
    await asyncio.wait_for(entered.wait(), 1)
    try:
        assert not await tasks.aclose(timeout=0)
        assert tasks.pending_count == 1
        release.set()
        for _ in range(5):
            await asyncio.sleep(0)
        assert tasks.pending_count == 0
        assert tasks.deleted_count == 0
        assert tasks.abandoned_count == 1
    finally:
        release.set()
        await tasks.aclose()


class Delivery:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.deleted = asyncio.Event()

    async def __call__(self, request):
        import json

        body = json.loads(request.content)
        method = request.url.path.rsplit("/", 1)[-1]
        self.requests.append((method, body))
        if method == "deleteMessage":
            self.deleted.set()
            return httpx.Response(200, json={"ok": True, "result": True})
        status, payload = next(self.responses)
        return httpx.Response(status, json=payload)


def ack(message_id):
    return 200, {"ok": True, "result": {"message_id": message_id}}


async def adapter(monkeypatch, delivery, *, ttl=30):
    import agents.core.channels.telegram as telegram

    monkeypatch.setattr(telegram, "get_value", lambda category, key, default=None: ttl)
    channel = TelegramChannel("synthetic-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(delivery))
    release, entered = asyncio.Event(), asyncio.Event()

    async def sleep(_delay):
        entered.set()
        await release.wait()

    channel._ephemeral_deletes = EphemeralDeletes(sleep=sleep)
    return channel, release, entered


@pytest.mark.asyncio
@pytest.mark.parametrize("plain", [False, True])
async def test_telegram_deletes_exact_sent_message_preserving_topic_and_voice(monkeypatch, plain):
    delivery = Delivery([ack(321)])
    channel, release, entered = await adapter(monkeypatch, delivery)
    spoken = []

    async def after(*args, **kwargs):
        spoken.append(kwargs)

    monkeypatch.setattr(channel, "_after_reply", after)
    try:
        assert await channel.send(
            EphemeralReply("**Notice**"), chat_id=-42, message_thread_id=19, plain=plain
        )
        await asyncio.wait_for(entered.wait(), 1)
        assert delivery.requests[0][1]["message_thread_id"] == 19
        assert not spoken
        release.set()
        await asyncio.wait_for(delivery.deleted.wait(), 1)
        assert delivery.requests[-1] == ("deleteMessage", {"chat_id": -42, "message_id": 321})
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_telegram_plain_fallback_and_each_chunk_own_id(monkeypatch):
    delivery = Delivery([(400, {"ok": False}), ack(321), ack(322)])
    channel, release, _entered = await adapter(monkeypatch, delivery)
    try:
        assert await channel.send(EphemeralReply("x" * 5000, 2), chat_id=42)
        assert len(delivery.requests) == 3
        assert "parse_mode" not in delivery.requests[1][1]
        release.set()
        await asyncio.wait_for(delivery.deleted.wait(), 1)
        await asyncio.sleep(0)
        ids = [
            body["message_id"] for method, body in delivery.requests if method == "deleteMessage"
        ]
        assert ids == [321, 322]
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        (200, {"ok": False, "result": {"message_id": 321}}),
        ack(0),
        ack(True),
        (200, {"ok": True, "result": {"message_id": "321"}}),
        (403, {"ok": False}),
        (200, []),
    ],
)
async def test_no_delete_without_exact_positive_ack(monkeypatch, response):
    delivery = Delivery([response])
    channel, release, entered = await adapter(monkeypatch, delivery)
    try:
        assert not await channel.send(EphemeralReply("notice", 1), chat_id=42)
        release.set()
        await asyncio.sleep(0)
        assert not entered.is_set()
        assert not delivery.deleted.is_set()
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_default_zero_retains_notice_and_stop_closes_deletion_before_client(monkeypatch):
    delivery = Delivery([ack(1), ack(2)])
    channel, _release, entered = await adapter(monkeypatch, delivery, ttl=0)
    assert await channel.send(EphemeralReply("default notice"), chat_id=42)
    assert channel._ephemeral_deletes.pending_count == 0
    assert await channel.send(EphemeralReply("temporary notice", 1), chat_id=42)
    await asyncio.wait_for(entered.wait(), 1)
    await channel.stop()
    assert channel.client.is_closed and channel._ephemeral_deletes.pending_count == 0
    assert not delivery.deleted.is_set()


@pytest.mark.asyncio
async def test_telegram_reports_incomplete_inflight_delete_and_keeps_ownership(monkeypatch, caplog):
    import agents.core.channels.telegram as telegram

    entered, release = asyncio.Event(), asyncio.Event()

    class ResistantDelivery(Delivery):
        async def __call__(self, request):
            if request.url.path.endswith("/deleteMessage"):
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
            return await super().__call__(request)

    monkeypatch.setattr(telegram, "LANE_DRAIN_BUDGET", 0.01)
    delivery = ResistantDelivery([ack(1)])
    channel, wake, _ = await adapter(monkeypatch, delivery)
    assert await channel.send(EphemeralReply("notice", 1), chat_id=42)
    wake.set()
    await asyncio.wait_for(entered.wait(), 1)
    try:
        await channel.stop()
        assert channel.client.is_closed
        assert channel._ephemeral_deletes.pending_count == 1
        assert "did not finish within the shutdown budget" in caplog.text
        release.set()
        for _ in range(10):
            await asyncio.sleep(0)
        assert channel._ephemeral_deletes.pending_count == 0
        assert channel._ephemeral_deletes.deleted_count == 0
        assert channel._ephemeral_deletes.abandoned_count == 1
    finally:
        release.set()
        await channel._ephemeral_deletes.aclose()
