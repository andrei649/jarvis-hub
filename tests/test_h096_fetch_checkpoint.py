"""The IMAP worker proposes UIDs; only accepted routing decisions persist them."""

import asyncio

import pytest

from agents.core.channels.email import MAX_MESSAGE_BYTES, EmailSeenStore
from tests.test_h096_email_channel import FakeIMAP, _channel, _raw


def _state(channel):
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    return channel._seen_store().get(key)


@pytest.mark.asyncio
async def test_fetch_proposes_watermark_and_routing_commits_it(tmp_path):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({1: _raw(body="old")})
    first = channel._fetch_new(mailbox)
    assert first.messages == [] and first.baseline and _state(channel) is None
    channel._imap_fetch = lambda: first
    await channel._check_imap()
    assert _state(channel)["last_uid"] == 1

    mailbox.messages[2] = _raw(body="new")
    batch = channel._fetch_new(mailbox)
    assert [item["uid"] for item in batch.messages] == [2]
    assert batch.last_uid == 2 and _state(channel)["last_uid"] == 1
    routed = []

    async def route(item, _budget):
        routed.append(item["uid"])

    channel._route = route
    channel._imap_fetch = lambda: batch
    await channel._check_imap()
    assert routed == [2] and _state(channel)["last_uid"] == 2
    assert _channel(tmp_path)._fetch_new(mailbox).messages == []


@pytest.mark.asyncio
async def test_all_suppressed_batch_still_advances_and_uid_reset_waits_for_acceptance(tmp_path):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({1: _raw(body="old")})
    channel._seen_store().set(EmailSeenStore.key(channel.imap["host"], channel.imap["user"]), "7", 1)
    mailbox.messages[2] = _raw(body="oversized")
    mailbox.sizes[2] = MAX_MESSAGE_BYTES + 1
    batch = channel._fetch_new(mailbox)
    assert batch.messages == [] and batch.last_uid == 2
    assert _state(channel)["last_uid"] == 1
    channel._imap_fetch = lambda: batch
    await channel._check_imap()
    assert _state(channel)["last_uid"] == 2

    mailbox.validity = 8
    mailbox.messages[3] = _raw(body="new epoch history")
    reset = channel._fetch_new(mailbox)
    assert reset.baseline and reset.messages == []
    assert _state(channel) == {"uidvalidity": "7", "last_uid": 2}
    channel._imap_fetch = lambda: reset
    await channel._check_imap()
    assert _state(channel) == {"uidvalidity": "8", "last_uid": 3}


@pytest.mark.asyncio
async def test_stale_baseline_proposal_cannot_replace_newer_validity(tmp_path):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({1: _raw(body="old")}, validity=8)
    store = channel._seen_store()
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    store.set(key, "7", 1)
    proposal = channel._fetch_new(mailbox)
    assert proposal.baseline and proposal.previous_validity == "7"
    store.set(key, "9", 3)
    channel._imap_fetch = lambda: proposal
    with pytest.raises(RuntimeError, match="watermark changed"):
        await channel._check_imap()
    assert _state(channel) == {"uidvalidity": "9", "last_uid": 3}

    missing = _channel(tmp_path / "other")
    first = missing._fetch_new(mailbox)
    assert first.baseline and first.previous_validity is None
    other_key = EmailSeenStore.key(missing.imap["host"], missing.imap["user"])
    missing._seen_store().set(other_key, "8", 2)
    missing._imap_fetch = lambda: first
    with pytest.raises(RuntimeError, match="watermark changed"):
        await missing._check_imap()
    assert _state(missing) == {"uidvalidity": "8", "last_uid": 2}


@pytest.mark.asyncio
async def test_first_contact_without_uidnext_or_successful_search_does_not_infer_zero(tmp_path):
    channel = _channel(tmp_path)

    class UnreadableBaseline(FakeIMAP):
        def response(self, name):
            if name == "UIDNEXT":
                return "OK", [None]
            return super().response(name)

        def uid(self, command, *args):
            if command == "SEARCH" and args[-1] == "ALL":
                return "NO", [None]
            return super().uid(command, *args)

    mailbox = UnreadableBaseline({1: _raw(body="history")})
    proposal = channel._fetch_new(mailbox)
    assert proposal.messages == [] and proposal.last_uid is None
    channel._imap_fetch = lambda: proposal
    await channel._check_imap()
    assert _state(channel) is None

    mailbox.uid = FakeIMAP.uid.__get__(mailbox, UnreadableBaseline)
    retry = channel._fetch_new(mailbox)
    assert retry.baseline and retry.last_uid == 1
    channel._imap_fetch = lambda: retry
    await channel._check_imap()
    assert _state(channel) == {"uidvalidity": "7", "last_uid": 1}


def test_failed_store_save_rolls_back_in_memory_cursor(tmp_path, monkeypatch):
    channel = _channel(tmp_path)
    store = channel._seen_store()
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    store.set(key, "7", 1)
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(OSError, match="disk unavailable"):
        store.set(key, "7", 2)
    assert store.get(key) == {"uidvalidity": "7", "last_uid": 1}


@pytest.mark.asyncio
async def test_failed_cancel_checkpoint_keeps_cancellation_and_redacts_warning(tmp_path, monkeypatch, caplog):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({1: _raw(body="old"), 2: _raw(body="accepted"),
                        3: _raw(body="pending")})
    store = channel._seen_store()
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    store.set(key, "7", 1)
    channel._imap_fetch = lambda: channel._fetch_new(mailbox)
    entered = asyncio.Event()

    async def route(item, _budget):
        if item["uid"] == 2:
            return
        entered.set()
        await asyncio.Event().wait()

    channel._route = route
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("private disk canary")))
    poll = asyncio.create_task(channel._check_imap())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        assert store.get(key) == {"uidvalidity": "7", "last_uid": 1}
        assert "Email watermark commit failed during cancellation" in caplog.text
        assert "canary" not in caplog.text
    finally:
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_earlier", [False, True])
async def test_cancelled_route_commits_only_safe_prefix(tmp_path, fail_earlier):
    channel = _channel(tmp_path)
    mailbox = FakeIMAP({1: _raw(body="old"), 2: _raw(body="two"), 3: _raw(body="three")})
    key = EmailSeenStore.key(channel.imap["host"], channel.imap["user"])
    channel._seen_store().set(key, "7", 1)
    channel._imap_fetch = lambda: channel._fetch_new(mailbox)
    entered = asyncio.Event()

    async def route(item, _budget):
        if item["uid"] == 2:
            if fail_earlier:
                raise RuntimeError("route failed")
            return
        entered.set()
        await asyncio.Event().wait()

    channel._route = route
    poll = asyncio.create_task(channel._check_imap())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        assert _state(channel)["last_uid"] == (1 if fail_earlier else 2)
        assert [item["uid"] for item in _channel(tmp_path)._fetch_new(mailbox).messages] == (
            [2, 3] if fail_earlier else [3])
    finally:
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        await channel.stop()
