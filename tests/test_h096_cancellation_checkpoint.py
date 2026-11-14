"""Unrouted IMAP messages must survive cancellation and a fresh adapter."""

import asyncio
import threading

import pytest

from agents.core.channels.email import EmailSeenStore
from tests.test_h096_email_channel import FakeIMAP, _channel, _raw


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_route", "before_worker_return"])
async def test_cancelled_batch_does_not_checkpoint_an_unrouted_message(tmp_path, phase):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({1: _raw(body="baseline"), 2: _raw(body="not delivered")})
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    channel._seen_store().set(key, "7", 1)
    entered = asyncio.Event()
    worker_entered, worker_release = threading.Event(), threading.Event()
    deliveries = []

    def fetch():
        batch = channel._fetch_new(mailbox)
        if phase == "before_worker_return":
            worker_entered.set()
            assert worker_release.wait(5)
        return batch

    async def route(item, _budget):
        entered.set()
        await asyncio.Event().wait()
        deliveries.append(item["uid"])

    channel._imap_fetch = fetch
    channel._route = route
    poll = asyncio.create_task(channel._check_imap())
    try:
        if phase == "before_route":
            await asyncio.wait_for(entered.wait(), 1)
        else:
            assert await asyncio.to_thread(worker_entered.wait, 1)
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        worker_release.set()
        await asyncio.wait_for(channel.stop(), 2)
        assert deliveries == []
        restarted = _channel(tmp_path)
        batch = restarted._fetch_new(mailbox)
        assert [item["uid"] for item in getattr(batch, "messages", batch)] == [2]
    finally:
        worker_release.set()
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        await asyncio.wait_for(channel.stop(), 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("earlier_failure", [False, True])
async def test_cancelled_route_commits_only_safe_prefix_and_preserves_earlier_gap(
        tmp_path, earlier_failure):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({uid: _raw(body=str(uid)) for uid in range(1, 5)})
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    channel._seen_store().set(key, "7", 1)
    entered = asyncio.Event()
    deliveries = []

    async def route(item, _budget):
        if item["uid"] == 2 and earlier_failure:
            raise RuntimeError("deliberate routing refusal")
        if item["uid"] == 4:
            entered.set()
            await asyncio.Event().wait()
        deliveries.append(item["uid"])

    channel._imap_fetch = lambda: channel._fetch_new(mailbox)
    channel._route = route
    poll = asyncio.create_task(channel._check_imap())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        await channel.stop()
        assert deliveries == ([3] if earlier_failure else [2, 3])
        restarted = _channel(tmp_path)
        batch = restarted._fetch_new(mailbox)
        pending = [item["uid"] for item in getattr(batch, "messages", batch)]
        assert pending == ([2, 3, 4] if earlier_failure else [4])
    finally:
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_failed_cancel_checkpoint_preserves_cancellation_and_retryable_mail(
        tmp_path, monkeypatch, caplog):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({uid: _raw(body=str(uid)) for uid in range(1, 4)})
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    store = channel._seen_store()
    store.set(key, "7", 1)
    entered = asyncio.Event()

    async def route(item, _budget):
        if item["uid"] == 3:
            entered.set()
            await asyncio.Event().wait()

    def fail_save():
        raise OSError("PRIVATE_CHECKPOINT_FAILURE")

    channel._imap_fetch = lambda: channel._fetch_new(mailbox)
    channel._route = route
    poll = asyncio.create_task(channel._check_imap())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        monkeypatch.setattr(store, "_save", fail_save)
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        assert store.get(key)["last_uid"] == 1
        assert "Email watermark commit failed during cancellation" in caplog.text
        assert "PRIVATE_CHECKPOINT_FAILURE" not in caplog.text
        restarted = _channel(tmp_path)
        batch = restarted._fetch_new(mailbox)
        assert [item["uid"] for item in getattr(batch, "messages", batch)] == [2, 3]
    finally:
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        await channel.stop()
