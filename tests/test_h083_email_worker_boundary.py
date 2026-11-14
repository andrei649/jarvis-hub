"""An IMAP worker owns its lifecycle until the blocking fetch really returns."""

import asyncio
import threading

import pytest

from agents.core.channels import email


@pytest.fixture
def blocked_fetch(monkeypatch):
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"})
    entered, release = threading.Event(), threading.Event()
    calls = []

    def fetch():
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return []

    monkeypatch.setattr(channel, "_imap_fetch", fetch)
    return channel, entered, release, calls


@pytest.mark.asyncio
async def test_redundant_start_keeps_one_actual_imap_worker(blocked_fetch):
    channel, entered, release, calls = blocked_fetch
    tasks = set()
    try:
        await channel.start()
        original = channel._poll_task
        tasks.add(original)
        assert await asyncio.to_thread(entered.wait, 1)
        await channel.start()
        tasks.add(channel._poll_task)
        assert channel._poll_task is original
        assert len(calls) == 1
    finally:
        release.set()
        await channel.stop()
        for task in tasks:
            task.cancel()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)


@pytest.mark.asyncio
async def test_stop_waits_for_the_actual_blocking_fetch_before_reporting_done(blocked_fetch):
    channel, entered, release, calls = blocked_fetch
    stopping = None
    try:
        await channel.start()
        assert await asyncio.to_thread(entered.wait, 1)
        stopping = asyncio.create_task(channel.stop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not stopping.done()
        assert len(calls) == 1
        release.set()
        await asyncio.wait_for(stopping, 2)
        assert not channel._running
    finally:
        release.set()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
        await channel.stop()


def test_real_imap_constructor_gets_finite_socket_operation_timeout(monkeypatch):
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

        def login(self, *_args):
            pass

        def logout(self):
            pass

    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"})
    monkeypatch.setattr(email.imaplib, "IMAP4_SSL", Client)
    monkeypatch.setattr(channel, "_fetch_new",
                        lambda _mail: email.FetchBatch([], None, None, None, None))
    assert channel._imap_fetch().messages == []
    assert calls[0].get("timeout") == 15


@pytest.mark.asyncio
async def test_manager_budget_cannot_hide_a_still_running_imap_worker(blocked_fetch, monkeypatch):
    from agents.core import lifecycle_budget
    from agents.core.channels.manager import ChannelManager

    channel, entered, release, calls = blocked_fetch
    manager = ChannelManager()
    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.02)
    try:
        await channel.start()
        assert await asyncio.to_thread(entered.wait, 1)
        assert not await manager._bounded_platform_stop("email", channel)
        await manager.wait_platform_cleanup("email")
        with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
            await channel.start()
        assert len(calls) == 1
        release.set()
        await asyncio.wait_for(channel.stop(), 2)
        await channel.start()
        # A completed stop permits a new lifecycle, without overlapping workers.
        for _ in range(100):
            if len(calls) == 2:
                break
            await asyncio.sleep(0.001)
        assert len(calls) == 2
    finally:
        release.set()
        await channel.stop()
        await manager.wait_platform_cleanup("email")
