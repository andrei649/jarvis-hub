"""A committed skill reload during Telegram's startup menu POST is not lost."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from agents.core import maintenance_commands
from agents.core.channels import polling_claims
from agents.core.channels.manager import ChannelManager
from agents.core.channels.telegram import TelegramChannel, _bot_api_only
from agents.web import _telegram_command_menus
from tests.test_h084_reload_skills import _command, _write_skill, cast  # noqa: F401


@pytest.fixture
async def starting_menu(cast, monkeypatch, tmp_path):
    """Use real adapter.start through manager.start_all and block its owner POST."""
    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    cast.orch.get_setting = lambda key, default=None: (
        "4242" if key == "autonomy.owner_chat_id" else default)
    cast.orch._command_name_taken = lambda word: cast.orch.commands.get(word) is not None
    acquire = polling_claims.acquire_telegram_claim
    monkeypatch.setattr(
        polling_claims, "acquire_telegram_claim",
        lambda token: acquire(token, root=tmp_path / "claim-root"),
    )

    posts = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def receive(request):
        assert request.url.host == "api.telegram.org"
        assert request.url.path.endswith("/setMyCommands")
        body = json.loads(request.content)
        posts.append(body)
        if body.get("scope", {}).get("chat_id") == 4242 and not entered.is_set():
            entered.set()
            await release.wait()
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("12345:offline-v43-startup")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(
        transport=httpx.MockTransport(receive), event_hooks={"request": [_bot_api_only]})
    channel._get_me = AsyncMock(return_value={"id": 424242, "username": "offline_bot"})
    channel._resume_offset = Mock()

    async def poll():
        await asyncio.Event().wait()

    channel._poll_loop = poll
    channel.command_menu = lambda: _telegram_command_menus(cast.orch)
    manager = ChannelManager()
    manager.register(channel)
    cast.orch.channel_manager = manager

    startup = asyncio.create_task(manager.start_all())
    try:
        yield SimpleNamespace(cast=cast, channel=channel, manager=manager,
                              posts=posts, entered=entered, release=release,
                              startup=startup)
    finally:
        release.set()
        if not startup.done():
            await asyncio.gather(startup, return_exceptions=True)
        await manager.stop_all()


async def test_reload_committed_during_startup_owner_post_is_published(starting_menu):
    rig = starting_menu
    try:
        await asyncio.wait_for(rig.entered.wait(), 3)
        # Startup has already projected the old registry and is blocked in the real
        # setMyCommands owner POST. Commit a new skill while that request is in flight.
        assert maintenance_commands._RELOAD_LOCK.acquire(blocking=False)
        maintenance_commands._RELOAD_LOCK.release()
        _write_skill(rig.cast.root, "beta", "Beta")
        reload_task = asyncio.create_task(_command(rig.cast, "/reload_skills"))
        async with asyncio.timeout(3):
            while rig.cast.live.get_skill("Beta") is None:
                await asyncio.sleep(0)
        assert not rig.startup.done()
        rig.release.set()
        result = await asyncio.wait_for(reload_task, 5)
        assert result.status == "answered"
        await asyncio.wait_for(rig.startup, 5)

        owner_posts = [body for body in rig.posts
                       if body.get("scope", {}).get("chat_id") == 4242]
        assert owner_posts
        assert "beta" in {row["command"] for row in owner_posts[-1]["commands"]}
        # The default menu is a guest projection even though beta is owner-private.
        for body in rig.posts:
            if "scope" not in body:
                assert "beta" not in {row["command"] for row in body["commands"]}
    finally:
        rig.release.set()
