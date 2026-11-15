"""Scratch-only V43 tests for the manager/reload half of native menu refresh."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core import maintenance_commands
from agents.core.channels.manager import ChannelManager
from tests.test_h084_reload_skills import _command, _write_skill

pytest_plugins = ("tests.test_h084_reload_skills",)


class MenuAdapter:
    channel_id = "telegram"

    def __init__(self):
        self._running = True
        self._poll_claim = object()
        self._verified_bot_generation = "generation"
        self._owner_once_generation = "generation"
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.task = None
        self.guard = None

    def request_command_menu_refresh(self, *, guard):
        self.calls += 1
        self.guard = guard

        async def post():
            self.entered.set()
            await self.release.wait()
            return guard()

        self.task = asyncio.create_task(post())
        return self.task

    async def stop(self):
        self._running = False


@pytest.mark.asyncio
async def test_manager_queue_guards_owner_adapter_revision_epoch_pause_and_cleanup():
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    owner = SimpleNamespace(channel_manager=manager)
    task = manager.queue_command_menu_refresh(
        owner_current=lambda: owner.channel_manager is manager)
    assert task is adapter.task and adapter.guard() is True
    await adapter.entered.wait()
    manager._platform_paused["telegram"] = (adapter, "paused")
    assert adapter.guard() is False
    assert manager.queue_command_menu_refresh() is None
    manager._platform_paused.clear()
    manager._platform_cleanup["telegram"] = {asyncio.current_task()}
    assert adapter.guard() is False
    manager._platform_cleanup.clear()
    manager._platform_retired["telegram"] = [adapter]
    assert adapter.guard() is False
    manager._platform_retired.clear()
    manager.channels["telegram"] = object()
    assert adapter.guard() is False
    manager.channels["telegram"] = adapter
    manager._platform_revisions["telegram"] += 1
    assert adapter.guard() is False
    manager._platform_revisions["telegram"] -= 1
    manager._platform_stopping = True
    assert adapter.guard() is False
    manager._platform_stopping = False
    owner.channel_manager = object()
    assert adapter.guard() is False
    owner.channel_manager = manager
    manager._platform_epoch += 1
    assert adapter.guard() is False
    adapter.release.set()
    assert await task is False


@pytest.mark.asyncio
async def test_active_start_does_not_drop_verified_generation_refresh():
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    manager._platform_starts["telegram"] = asyncio.current_task()
    try:
        task = manager.queue_command_menu_refresh()
        assert task is not None and adapter.calls == 1
        assert adapter.guard() is True
        adapter.release.set()
        assert await task is True
    finally:
        manager._platform_starts.clear()


@pytest.mark.asyncio
async def test_committed_reload_queues_and_releases_scan_lock_before_menu_io(cast):
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    cast.orch.channel_manager = manager
    _write_skill(cast.root, "beta", "Beta")
    command = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await asyncio.wait_for(adapter.entered.wait(), 5)
        assert cast.live.get_skill("Beta") is not None
        assert maintenance_commands._RELOAD_LOCK.acquire(blocking=False)
        maintenance_commands._RELOAD_LOCK.release()
        adapter.release.set()
        answer = await command
        assert "Beta" in answer.reply and "Added" in answer.reply
        assert "menu updated" in answer.reply.lower()
        assert adapter.calls == 1
    finally:
        adapter.release.set()
        if not command.done():
            await command


@pytest.mark.asyncio
async def test_cancelled_committed_reload_leaves_exact_menu_task_owned(cast):
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    cast.orch.channel_manager = manager
    _write_skill(cast.root, "beta", "Beta")
    command = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await asyncio.wait_for(adapter.entered.wait(), 5)
        command.cancel()
        with pytest.raises(asyncio.CancelledError):
            await command
        assert adapter.task is not None and not adapter.task.cancelled()
        assert cast.live.get_skill("Beta") is not None
        adapter.release.set()
        assert await adapter.task is True
    finally:
        adapter.release.set()


@pytest.mark.asyncio
async def test_status_sync_failure_still_queues_and_reports_committed(cast, monkeypatch):
    manager = ChannelManager()
    adapter = MenuAdapter()
    adapter.release.set()
    manager.register(adapter)
    cast.orch.channel_manager = manager
    _write_skill(cast.root, "beta", "Beta")
    monkeypatch.setattr(cast.live, "sync_origins", lambda: (_ for _ in ()).throw(RuntimeError("status")))
    answer = await _command(cast, "/reload_skills")
    assert cast.live.get_skill("Beta") is not None
    assert adapter.calls == 1
    assert "Status or usage sync needs retry" in answer.reply
    assert "menu updated" in answer.reply.lower()


@pytest.mark.asyncio
async def test_unavailable_adapter_defers_and_enqueue_error_reports_retry(cast):
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    cast.orch.channel_manager = manager
    adapter.request_command_menu_refresh = lambda *, guard: None
    _write_skill(cast.root, "beta", "Beta")
    answer = await _command(cast, "/reload_skills")
    assert "Beta" in answer.reply and "menu will refresh" in answer.reply.lower()
    assert cast.live.get_skill("Beta") is not None

    def fail_queue(*, guard):
        raise RuntimeError("private enqueue failure")

    adapter.request_command_menu_refresh = fail_queue
    _write_skill(cast.root, "gamma", "Gamma")
    answer = await _command(cast, "/reload_skills")
    assert "Gamma" in answer.reply and "menu refresh needs retry" in answer.reply.lower()
    assert "private enqueue failure" not in answer.reply
    assert cast.live.get_skill("Gamma") is not None


@pytest.mark.asyncio
async def test_menu_timeout_reports_pending_without_cancelling_owned_task(cast, monkeypatch):
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    cast.orch.channel_manager = manager
    monkeypatch.setattr(maintenance_commands, "_MENU_REFRESH_WAIT_SECONDS", 0.001)
    _write_skill(cast.root, "beta", "Beta")
    answer = await _command(cast, "/reload_skills")
    assert "Beta" in answer.reply and "menu refresh pending" in answer.reply.lower()
    assert adapter.task is not None and not adapter.task.cancelled()
    adapter.release.set()
    assert await adapter.task is True


@pytest.mark.asyncio
async def test_postcommit_report_failure_cannot_claim_registry_unchanged(cast, monkeypatch):
    manager = ChannelManager()
    adapter = MenuAdapter()
    adapter.release.set()
    manager.register(adapter)
    cast.orch.channel_manager = manager
    monkeypatch.setattr(maintenance_commands, "_report", lambda *_: (_ for _ in ()).throw(RuntimeError("private")))
    _write_skill(cast.root, "beta", "Beta")
    answer = await _command(cast, "/reload_skills")
    assert cast.live.get_skill("Beta") is not None
    assert "registry committed" in answer.reply.lower()
    assert "menu updated" in answer.reply.lower()
    assert "private" not in answer.reply


@pytest.mark.asyncio
async def test_menu_post_failure_is_a_committed_retry_notice(cast):
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    cast.orch.channel_manager = manager

    async def failed_post():
        raise RuntimeError("private transport error")

    adapter.request_command_menu_refresh = lambda *, guard: asyncio.create_task(failed_post())
    _write_skill(cast.root, "beta", "Beta")
    answer = await _command(cast, "/reload_skills")
    assert cast.live.get_skill("Beta") is not None
    assert "menu refresh needs retry" in answer.reply.lower()
    assert "private transport error" not in answer.reply


@pytest.mark.asyncio
async def test_precommit_refusals_do_not_queue(cast):
    manager = ChannelManager()
    adapter = MenuAdapter()
    manager.register(adapter)
    cast.orch.channel_manager = manager
    answer = await _command(cast, "/reload_skills now")
    assert "nothing changed" in answer.reply and adapter.calls == 0
    broken = cast.root / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_bytes(b"\xff\xfe")
    answer = await _command(cast, "/reload_skills")
    assert "unchanged" in answer.reply and adapter.calls == 0
