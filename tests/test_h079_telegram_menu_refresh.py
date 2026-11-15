"""Offline V43 Telegram menu refresh task ownership and fencing."""

import asyncio

import httpx
import pytest

from agents.core.channels.polling_claims import acquire_telegram_claim
from agents.core.channels.telegram import TelegramChannel


def _menu(name="one", owner=77):
    return ([{"command": "help", "description": "h"}],
            (owner, [{"command": name, "description": "owner"}]))


async def _running(tmp_path, handler, *, menu=None):
    channel = TelegramChannel("offline-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    channel._running = True
    channel._owner_once_generation = "generation-1"
    channel._verified_bot_generation = "generation-1"
    channel._poll_claim = acquire_telegram_claim("offline-token", root=tmp_path / "install")
    channel.command_menu = menu or (lambda: _menu())
    return channel


@pytest.mark.asyncio
async def test_refresh_requires_running_verified_claim_and_guard(tmp_path):
    channel = await _running(tmp_path, lambda _req: httpx.Response(200))
    try:
        channel._verified_bot_generation = None
        assert channel.request_command_menu_refresh(guard=lambda: True) is None
        channel._verified_bot_generation = "generation-1"
        assert channel.request_command_menu_refresh(guard=None) is None
        channel._running = False
        assert channel.request_command_menu_refresh(guard=lambda: True) is None
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_repeated_refreshes_coalesce_to_latest_projection(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    posts = []
    current = {"name": "one"}

    async def handler(request):
        body = __import__("json").loads(request.content)
        posts.append(body)
        if len(posts) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(200)

    channel = await _running(tmp_path, handler, menu=lambda: _menu(current["name"]))
    try:
        task = channel.request_command_menu_refresh(guard=lambda: True)
        assert task is not None
        await asyncio.wait_for(entered.wait(), 1)
        current["name"] = "two"
        assert channel.request_command_menu_refresh(guard=lambda: True) is task
        release.set()
        assert await asyncio.wait_for(task, 1) is True
        owner_names = [body["commands"][0]["command"] for body in posts if "scope" in body]
        assert owner_names[-1] == "two"
        assert sum("scope" not in body for body in posts) == 2
        assert all(body["commands"] == [{"command": "help", "description": "h"}]
                   for body in posts if "scope" not in body)
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_direct_startup_publication_and_refresh_do_not_interleave(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    posts = []

    async def handler(request):
        posts.append(__import__("json").loads(request.content))
        if len(posts) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(200)

    channel = await _running(tmp_path, handler)
    try:
        startup = asyncio.create_task(channel.publish_command_menu())
        await asyncio.wait_for(entered.wait(), 1)
        refresh = channel.request_command_menu_refresh(guard=lambda: True)
        assert refresh is not None
        await asyncio.sleep(0)
        assert len(posts) == 1
        release.set()
        assert await asyncio.wait_for(startup, 1) is True
        assert await asyncio.wait_for(refresh, 1) is True
        assert ["scope" in row for row in posts] == [False, True, False, True]
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_owner_reprojected_and_guard_checked_before_owner_post(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    owner = {"chat": 77}
    guard = {"ok": True}
    posts = []
    projections = []

    def menu():
        projections.append(owner["chat"])
        return _menu(owner=owner["chat"])

    async def handler(request):
        posts.append(__import__("json").loads(request.content))
        if len(posts) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(200)

    channel = await _running(tmp_path, handler, menu=menu)
    try:
        task = channel.request_command_menu_refresh(guard=lambda: guard["ok"])
        await asyncio.wait_for(entered.wait(), 1)
        owner["chat"] = 88
        release.set()
        assert await asyncio.wait_for(task, 1) is True
        assert posts[1]["scope"]["chat_id"] == 88

        posts.clear()
        projections.clear()
        entered.clear()
        release.clear()
        task = channel.request_command_menu_refresh(guard=lambda: guard["ok"])
        await asyncio.wait_for(entered.wait(), 1)
        guard["ok"] = False
        release.set()
        assert await asyncio.wait_for(task, 1) is False
        assert len(posts) == 1
        assert projections == [88]  # retired source cannot project private menu
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_cancelled_stop_retains_request_client_and_claim_until_settled(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        entered.set()
        await release.wait()
        return httpx.Response(200)

    channel = await _running(tmp_path, handler)
    claim = channel._poll_claim
    try:
        refresh = channel.request_command_menu_refresh(guard=lambda: True)
        await asyncio.wait_for(entered.wait(), 1)
        stopping = asyncio.create_task(channel.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert channel._poll_claim is claim
        assert not channel.client.is_closed
        assert not refresh.done()
        assert channel.request_command_menu_refresh(guard=lambda: True) is None
        release.set()
        await asyncio.wait_for(refresh, 1)
        await channel.stop()
        assert channel._poll_claim is None and channel.client.is_closed
    finally:
        release.set()
        if channel._poll_claim is not None:
            await channel.stop()


@pytest.mark.asyncio
async def test_generation_change_blocks_second_post(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    posts = []

    async def handler(request):
        posts.append(__import__("json").loads(request.content))
        entered.set()
        await release.wait()
        return httpx.Response(200)

    channel = await _running(tmp_path, handler)
    try:
        task = channel.request_command_menu_refresh(guard=lambda: True)
        await asyncio.wait_for(entered.wait(), 1)
        channel._verified_bot_generation = "new-generation"
        release.set()
        assert await asyncio.wait_for(task, 1) is False
        assert len(posts) == 1 and "scope" not in posts[0]
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_newer_guard_gets_a_pass_after_prior_epoch_guard_expires(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    posts = []
    old_guard = {"current": True}

    async def handler(request):
        posts.append(__import__("json").loads(request.content))
        if len(posts) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(200)

    channel = await _running(tmp_path, handler)
    try:
        task = channel.request_command_menu_refresh(guard=lambda: old_guard["current"])
        await asyncio.wait_for(entered.wait(), 1)
        old_guard["current"] = False
        assert channel.request_command_menu_refresh(guard=lambda: True) is task
        release.set()
        assert await asyncio.wait_for(task, 1) is True
        assert ["scope" in body for body in posts] == [False, False, True]
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_failed_post_does_not_retry_without_new_request(tmp_path):
    posts = []

    def handler(request):
        posts.append(__import__("json").loads(request.content))
        return httpx.Response(500)

    channel = await _running(tmp_path, handler)
    try:
        task = channel.request_command_menu_refresh(guard=lambda: True)
        assert await asyncio.wait_for(task, 1) is False
        assert len(posts) == 2  # existing behavior attempts both scopes once
        await asyncio.sleep(0)
        assert len(posts) == 2
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_minimal_new_object_creates_publication_lock_lazily():
    channel = TelegramChannel.__new__(TelegramChannel)
    channel.api_base = "https://api.telegram.org/botfixture"
    channel.command_menu = lambda: _menu()
    posts = []

    async def post(_url, **kwargs):
        posts.append(kwargs["json"])
        return httpx.Response(200)

    channel._post = post
    assert await channel.publish_command_menu() is True
    assert len(posts) == 2
