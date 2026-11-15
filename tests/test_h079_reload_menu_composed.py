"""Actual owner reload, live menu projection and retained Telegram publication."""
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
async def menu_cast(cast, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    cast.orch.get_setting = lambda key, default=None: (
        "4242" if key == "autonomy.owner_chat_id" else default)
    cast.orch._command_name_taken = lambda word: cast.orch.commands.get(word) is not None
    acquire = polling_claims.acquire_telegram_claim
    monkeypatch.setattr(polling_claims, "acquire_telegram_claim",
                        lambda token: acquire(token, root=tmp_path / "claim-root"))
    posts = []
    entered, release = asyncio.Event(), asyncio.Event()
    state = SimpleNamespace(block=False)

    async def receive(request):
        assert request.url.host == "api.telegram.org"
        assert request.url.path.endswith("/setMyCommands")
        posts.append(json.loads(request.content))
        if state.block:
            state.block = False
            entered.set()
            await release.wait()
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("12345:offline-v43-composed")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(receive),
                                       event_hooks={"request": [_bot_api_only]})
    channel._get_me = AsyncMock(return_value={"id": 424242, "username": "offline_bot"})
    channel._resume_offset = Mock()

    async def poll():
        await asyncio.Event().wait()

    channel._poll_loop = poll
    channel.command_menu = lambda: _telegram_command_menus(cast.orch)
    manager = ChannelManager()
    manager.register(channel)
    cast.orch.channel_manager = manager
    await channel.start()
    try:
        yield SimpleNamespace(cast=cast, channel=channel, manager=manager, posts=posts,
                              state=state, entered=entered, release=release)
    finally:
        release.set()
        await channel.stop()


def owner_commands(posts):
    scoped = [body for body in posts if body.get("scope", {}).get("chat_id") == 4242]
    assert scoped
    return {row["command"] for row in scoped[-1]["commands"]}


def assert_guest_safe(posts):
    for body in posts:
        if "scope" not in body:
            assert not {"alpha", "beta", "gamma"} & {
                row["command"] for row in body["commands"]}


async def test_committed_add_remove_updates_actual_owner_menu(menu_cast):
    rig = menu_cast
    assert "alpha" in owner_commands(rig.posts)
    _write_skill(rig.cast.root, "beta", "Beta")
    result = await _command(rig.cast, "/reload_skills")
    assert result.status == "answered"
    assert {"alpha", "beta"} <= owner_commands(rig.posts)
    (rig.cast.root / "beta" / "SKILL.md").unlink()
    (rig.cast.root / "beta").rmdir()
    await _command(rig.cast, "/reload_skills")
    assert "beta" not in owner_commands(rig.posts)
    assert_guest_safe(rig.posts)


async def test_second_commit_during_post_reaches_latest_projection(menu_cast):
    rig = menu_cast
    rig.state.block = True
    _write_skill(rig.cast.root, "beta", "Beta")
    first = asyncio.create_task(_command(rig.cast, "/reload_skills"))
    second = None
    try:
        await asyncio.wait_for(rig.entered.wait(), 3)
        assert maintenance_commands._RELOAD_LOCK.acquire(blocking=False)
        maintenance_commands._RELOAD_LOCK.release()
        _write_skill(rig.cast.root, "gamma", "Gamma")
        second = asyncio.create_task(_command(rig.cast, "/reload_skills"))
        async with asyncio.timeout(3):
            while rig.cast.live.get_skill("Gamma") is None:
                await asyncio.sleep(0)
        rig.release.set()
        await asyncio.gather(first, second)
        assert {"alpha", "beta", "gamma"} <= owner_commands(rig.posts)
        assert_guest_safe(rig.posts)
    finally:
        rig.release.set()
        await asyncio.gather(*(task for task in (first, second) if task),
                             return_exceptions=True)


async def test_cancelled_reload_caller_does_not_cancel_committed_menu(menu_cast):
    rig = menu_cast
    rig.state.block = True
    _write_skill(rig.cast.root, "beta", "Beta")
    command = asyncio.create_task(_command(rig.cast, "/reload_skills"))
    try:
        await asyncio.wait_for(rig.entered.wait(), 3)
        owned = rig.channel._menu_refresh_task
        command.cancel()
        with pytest.raises(asyncio.CancelledError):
            await command
        assert not owned.done() and rig.cast.live.get_skill("Beta") is not None
        assert rig.channel._poll_claim is not None and not rig.channel.client.is_closed
        rig.release.set()
        assert await asyncio.wait_for(asyncio.shield(owned), 3)
        assert "beta" in owner_commands(rig.posts)
        assert_guest_safe(rig.posts)
    finally:
        rig.release.set()
        await asyncio.gather(command, return_exceptions=True)


async def test_manager_stop_budget_keeps_inflight_menu_claim_until_settled(menu_cast, monkeypatch):
    from agents.core import lifecycle_budget

    rig = menu_cast
    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.01)
    rig.posts.clear()
    rig.state.block = True
    _write_skill(rig.cast.root, "beta", "Beta")
    command = asyncio.create_task(_command(rig.cast, "/reload_skills"))
    try:
        await asyncio.wait_for(rig.entered.wait(), 3)
        refresh = rig.channel._menu_refresh_task
        claim = rig.channel._poll_claim
        await rig.manager.stop_all()
        await rig.manager.wait_platform_cleanup("telegram")
        assert rig.channel._poll_claim is claim and not rig.channel.client.is_closed
        assert not refresh.done()
        assert rig.manager.queue_command_menu_refresh() is None
        rig.release.set()
        await command
        assert await asyncio.shield(refresh) is False
        assert len(rig.posts) == 1 and "scope" not in rig.posts[0]
        await rig.channel.stop()
        assert rig.channel._poll_claim is None and rig.channel.client.is_closed
    finally:
        rig.release.set()
        await asyncio.gather(command, return_exceptions=True)
