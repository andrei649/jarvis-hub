"""IMAP connect/login recognition expires without discarding the real worker."""

import asyncio
import imaplib
import threading
from unittest.mock import Mock

import pytest

from agents.core.channels import email
from agents.core.channels.manager import ChannelManager


async def _until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["constructor", "login"])
async def test_late_open_never_fetches_and_retains_worker_until_settled(tmp_path, monkeypatch, phase):
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Client:
        def __init__(self, *_args, **kwargs):
            calls.append(("constructor", kwargs["timeout"]))
            if phase == "constructor":
                entered.set()
                assert release.wait(5)

        def login(self, *_args):
            calls.append(("login",))
            if phase == "login":
                entered.set()
                assert release.wait(5)

        def logout(self):
            calls.append(("logout",))

    monkeypatch.setattr(email.imaplib, "IMAP4_SSL", Client)
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"},
                                 seen_store=email.EmailSeenStore(tmp_path / "seen.json"),
                                 connect_timeout_seconds=15)
    channel._connect_timeout_seconds = 0.5
    fetched = Mock(return_value=email.FetchBatch([], None, None, None, None))
    monkeypatch.setattr(channel, "_fetch_new", fetched)
    try:
        await channel.start()
        assert await asyncio.to_thread(entered.wait, 1)
        await _until(lambda: channel.health_snapshot()["error"] == "connect_timeout")
        assert channel.health_snapshot()["failures"] == 1
        assert channel._fetch_task is not None and channel.health_snapshot()["circuit"]["probe_active"]
        fetched.assert_not_called()
        release.set()
        await _until(lambda: channel._fetch_task is None)
        fetched.assert_not_called()
        if phase == "constructor":
            assert ("login",) not in calls
        else:
            assert ("logout",) in calls
        assert channel._seen_store()._data == {}
        assert channel.health_snapshot()["failures"] == 1
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("late_auth_error", [False, True])
async def test_worker_detected_timeout_first_still_records_one_failure(
        tmp_path, monkeypatch, late_auth_error):
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Client:
        def __init__(self, *_args, **_kwargs):
            entered.set()
            assert release.wait(5)
            if late_auth_error:
                raise imaplib.IMAP4.error("authentication failed")

        def login(self, *_args):
            calls.append("login")

        def logout(self):
            calls.append("logout")

    # Force the scheduler to observe the actual worker exception before its own
    # timeout branch. The worker still uses the real monotonic expiry check.
    original_wait = asyncio.wait

    async def worker_first(tasks, *args, **kwargs):
        if len(tasks) == 2 and any(isinstance(task, asyncio.Future) and not isinstance(task, asyncio.Task)
                                   for task in tasks):
            worker = next(task for task in tasks if isinstance(task, asyncio.Task))
            await original_wait({worker})
            return {worker}, set(tasks) - {worker}
        return await original_wait(tasks, *args, **kwargs)

    monkeypatch.setattr(email.imaplib, "IMAP4_SSL", Client)
    monkeypatch.setattr(email.asyncio, "wait", worker_first)
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"},
                                 seen_store=email.EmailSeenStore(tmp_path / "seen.json"),
                                 connect_timeout_seconds=15)
    channel._connect_timeout_seconds = 0.2
    fetch = Mock()
    monkeypatch.setattr(channel, "_fetch_new", fetch)
    try:
        await channel.start()
        assert await asyncio.to_thread(entered.wait, 1)
        await asyncio.sleep(0.25)
        release.set()
        await _until(lambda: channel.health_snapshot()["error"] == "connect_timeout")
        assert channel.health_snapshot()["failures"] == 1
        assert calls == ([] if late_auth_error else ["logout"])
        assert channel._fetch_task is None
        fetch.assert_not_called()
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_timely_login_allows_fetch_past_open_deadline(tmp_path, monkeypatch):
    fetch_entered, release_fetch = threading.Event(), threading.Event()
    calls = []

    class Client:
        def __init__(self, *_args, **_kwargs):
            calls.append("constructor")

        def login(self, *_args):
            calls.append("login")

        def logout(self):
            calls.append("logout")

    def fetch(_mail):
        calls.append("fetch")
        fetch_entered.set()
        assert release_fetch.wait(5)
        return email.FetchBatch([], None, None, None, None)

    monkeypatch.setattr(email.imaplib, "IMAP4_SSL", Client)
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"},
                                 seen_store=email.EmailSeenStore(tmp_path / "seen.json"),
                                 connect_timeout_seconds=15)
    channel._connect_timeout_seconds = 0.5
    monkeypatch.setattr(channel, "_fetch_new", fetch)
    try:
        await channel.start()
        assert await asyncio.to_thread(fetch_entered.wait, 1)
        await asyncio.sleep(0.55)
        assert channel.health_snapshot()["error"] != "connect_timeout"
        assert channel._fetch_task is not None
        release_fetch.set()
        await _until(lambda: channel.health_snapshot()["state"] == "healthy")
        assert calls == ["constructor", "login", "fetch", "logout"]
    finally:
        release_fetch.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_manager_bounded_stop_keeps_late_login_worker_and_refuses_restart(tmp_path, monkeypatch):
    from agents.core import lifecycle_budget

    entered, release = threading.Event(), threading.Event()

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def login(self, *_args):
            entered.set()
            assert release.wait(5)

        def logout(self):
            pass

    monkeypatch.setattr(email.imaplib, "IMAP4_SSL", Client)
    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.02)
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"},
                                 seen_store=email.EmailSeenStore(tmp_path / "seen.json"),
                                 connect_timeout_seconds=15)
    channel._connect_timeout_seconds = 0.5
    fetch = Mock()
    monkeypatch.setattr(channel, "_fetch_new", fetch)
    manager = ChannelManager()
    try:
        await channel.start()
        assert await asyncio.to_thread(entered.wait, 1)
        await _until(lambda: channel.health_snapshot()["error"] == "connect_timeout")
        assert not await manager._bounded_platform_stop("email", channel)
        await manager.wait_platform_cleanup("email")
        assert channel._fetch_task is not None and channel.health_snapshot()["circuit"]["probe_active"]
        with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
            await channel.start()
        fetch.assert_not_called()
        release.set()
        await asyncio.wait_for(channel.stop(), 2)
        assert not channel.health_snapshot()["circuit"]["probe_active"]
        fetch.assert_not_called()
    finally:
        release.set()
        await channel.stop()
        await manager.wait_platform_cleanup("email")


@pytest.mark.asyncio
async def test_login_refusal_keeps_existing_fatal_reprobe(tmp_path, monkeypatch):
    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def login(self, *_args):
            raise imaplib.IMAP4.error("authentication failed")

        def logout(self):
            pass

    monkeypatch.setattr(email.imaplib, "IMAP4_SSL", Client)
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"},
                                 seen_store=email.EmailSeenStore(tmp_path / "seen.json"),
                                 connect_timeout_seconds=15)
    try:
        await channel.start()
        await _until(lambda: channel.health_snapshot()["fatal"] == "unauthorized")
        assert channel.health_snapshot()["error"] == "unauthorized"
        assert channel.health_snapshot()["circuit"]["failures"] == 0
    finally:
        await channel.stop()
