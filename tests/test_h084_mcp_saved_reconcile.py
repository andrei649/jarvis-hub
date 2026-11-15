"""Saved MCP reload is an inert preview followed by a fenced local reconcile."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.mcp.client import MCPManager, MCPServer, MCPTool
from agents.core.mcp.saved_reload import SavedReloadRefused


def _row(name, **changes):
    return {"name": name, "transport": "stdio", "command": "fake", "trust": "full", **changes}


async def _yes():
    return True


async def test_preview_is_inert_and_apply_preserves_stopped_intent():
    manager = MCPManager()
    live = MCPServer("old", command="fake", trust="full")
    manager.register(live)
    plan = manager.prepare_saved_reload([_row("old", command="new"), _row("added")])
    assert plan.summary == {"added": 1, "removed": 0, "changed": 1, "unchanged": 0}
    assert manager.servers["old"] is live and "added" not in manager.servers
    result = await manager.apply_saved_reload(plan, still_current=_yes)
    assert result["status"] == "ok"
    assert manager.servers["old"] is not live and not manager.servers["old"].wanted
    assert "added" in manager.servers and not manager.servers["added"].wanted
    assert result["servers"]["added"]["status"] == "added"


async def test_unchanged_owner_stopped_server_is_skipped():
    manager = MCPManager()
    srv = MCPServer("off", command="fake", trust="full")
    manager.register(srv)
    result = await manager.apply_saved_reload(
        manager.prepare_saved_reload([_row("off")]), still_current=_yes)
    assert result["servers"]["off"]["status"] == "skipped_unwanted"
    assert manager.servers["off"] is srv and not srv.wanted


async def test_duplicate_and_session_collision_refuse_without_effect():
    manager = MCPManager()
    scoped = MCPServer("private", command="fake", trust="full")
    scoped.session_scope = "session-1"
    manager.register(scoped)
    with pytest.raises(ValueError):
        manager.prepare_saved_reload([_row("same"), _row("same")])
    with pytest.raises(ValueError):
        manager.prepare_saved_reload([_row("private")])
    assert manager.servers == {"private": scoped}


async def test_plan_stales_after_owner_disconnect():
    manager = MCPManager()
    srv = MCPServer("old", command="fake", trust="full")
    srv.wanted = True
    manager.register(srv)
    plan = manager.prepare_saved_reload([_row("old", command="new")])
    await srv.close()
    result = await manager.apply_saved_reload(plan, still_current=_yes)
    assert result["status"] == "stale" and manager.servers["old"] is srv


async def test_close_race_never_replaces_newer_owner_registration(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    manager.register(old)
    entered, release = asyncio.Event(), asyncio.Event()

    async def parked_close():
        entered.set()
        await release.wait()
        old.wanted = False
        old._epoch += 1

    monkeypatch.setattr(old, "close", parked_close)
    plan = manager.prepare_saved_reload([_row("old", command="new")])
    pending = asyncio.create_task(manager.apply_saved_reload(plan, still_current=_yes))
    await entered.wait()
    replacement = MCPServer("old", command="owner", trust="full")
    manager.register(replacement)
    release.set()
    result = await pending
    assert result["status"] in {"partial", "stale"}
    assert manager.servers["old"] is replacement
    assert set(result["servers"]["old"]) >= {
        "status", "connected_before", "connected_after", "added", "removed", "changed"}


async def test_owner_removal_during_confirmation_recheck_cannot_resurrect(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    old.wanted = True
    manager.register(old)
    plan = manager.prepare_saved_reload([_row("old", command="new")])
    entered, release = asyncio.Event(), asyncio.Event()
    checks = 0

    async def check():
        nonlocal checks
        checks += 1
        if checks == 3:
            entered.set()
            await release.wait()
        return True

    pending = asyncio.create_task(manager.apply_saved_reload(plan, still_current=check))
    await entered.wait()
    await manager.remove_server("old")
    release.set()
    result = await pending
    assert result["status"] == "partial" and "old" not in manager.servers


async def test_invalid_nested_config_and_secret_never_enter_preview_or_report():
    manager = MCPManager()
    for row in (_row("x", trust="bogus"), _row("x", tools_deny=[42]),
                _row("x", env={"TOKEN": 42}, origin={"id": "catalog"}),
                _row("x", command="fake; echo danger")):
        with pytest.raises(SavedReloadRefused):
            manager.prepare_saved_reload([row])
    secret = "very-private-config-value-123456"
    plan = manager.prepare_saved_reload([_row("x", origin={"id": "catalog"},
                                              env={"OPTION": secret})])
    assert secret not in plan.fingerprint and secret not in repr(plan)
    assert set(plan.summary) == {"added", "removed", "changed", "unchanged"}


async def test_legacy_runtime_header_change_is_not_mistaken_for_unchanged():
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full", headers={"Authorization": "old"})
    manager.register(old)
    plan = manager.prepare_saved_reload([_row("old", headers={"Authorization": "new"})])
    assert plan.summary["changed"] == 1
    result = await manager.apply_saved_reload(plan, still_current=_yes)
    assert result["servers"]["old"]["status"] == "replaced"
    assert manager.servers["old"].headers == {"Authorization": "new"}


async def test_wanted_replacement_connects_but_new_server_stays_disconnected(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    old.wanted = True
    manager.register(old)
    calls = []

    async def connect(self):
        calls.append(self.name)
        self.tools = [MCPTool("read", "safe", {"type": "object"}, self.name)]
        return True

    monkeypatch.setattr(MCPServer, "_connect_impl", connect)
    monkeypatch.setattr(MCPServer, "is_connected", lambda self: bool(self.tools))
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    result = await manager.apply_saved_reload(
        manager.prepare_saved_reload([_row("old", command="new"), _row("added")]),
        still_current=_yes)
    assert result["status"] == "ok"
    assert calls == ["old"]
    assert result["servers"]["old"]["added"] == ["read"]
    assert not manager.servers["added"].wanted


async def test_close_failure_retains_old_server_and_reports_partial(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    manager.register(old)

    async def broken_close():
        raise RuntimeError("private transport detail")

    monkeypatch.setattr(old, "close", broken_close)
    result = await manager.apply_saved_reload(
        manager.prepare_saved_reload([_row("old", command="new")]),
        still_current=_yes)
    assert result["status"] == "partial"
    assert result["servers"]["old"]["status"] == "failed_close"
    assert "private transport detail" not in str(result)
    assert manager.servers["old"] is old


async def test_repeated_cancellation_waits_for_owned_close(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    manager.register(old)
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def parked_close():
        entered.set()
        await release.wait()
        old._epoch += 1
        old.wanted = False
        finished.set()

    monkeypatch.setattr(old, "close", parked_close)
    plan = manager.prepare_saved_reload([_row("old", command="new")])
    pending = asyncio.create_task(manager.apply_saved_reload(plan, still_current=_yes))
    await entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    pending.cancel()
    assert not pending.done() and manager._reload_lock.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert finished.is_set() and not manager._reload_lock.locked()
    assert manager.servers["old"] is old


async def test_halt_after_refresh_closes_new_connection(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    old.wanted = True
    manager.register(old)
    halted = False
    closed = []

    async def connect(self):
        nonlocal halted
        self.tools = [MCPTool("read", "safe", {"type": "object"}, self.name)]
        halted = True
        return True

    async def close(self):
        closed.append(self.name)
        self.wanted = False
        self._epoch += 1
        self.tools = []

    monkeypatch.setattr(MCPServer, "_connect_impl", connect)
    monkeypatch.setattr(MCPServer, "close", close)
    monkeypatch.setattr(MCPServer, "is_connected", lambda self: bool(self.tools))
    monkeypatch.setattr(manager, "_halted", lambda name=None: "estop" if halted else None)
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    result = await manager.apply_saved_reload(
        manager.prepare_saved_reload([_row("old")]), still_current=_yes)
    assert result["status"] == "partial"
    assert result["servers"]["old"]["status"] == "halted_after_connect"
    assert not result["servers"]["old"]["connected_after"] and closed == ["old"]


async def test_close_timeout_retains_owned_cleanup_and_blocks_restart(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    manager.register(old)
    entered, release = asyncio.Event(), asyncio.Event()

    async def parked_close():
        old.wanted = False
        old._epoch += 1
        entered.set()
        await release.wait()

    monkeypatch.setattr(old, "close", parked_close)
    monkeypatch.setattr("agents.core.mcp.client.SAVED_RELOAD_CLOSE_SECONDS", 0.01)
    result = await manager.apply_saved_reload(
        manager.prepare_saved_reload([_row("old", command="new")]), still_current=_yes)
    assert entered.is_set()
    assert result["status"] == "partial"
    assert result["servers"]["old"]["status"] == "failed_close_timeout"
    assert manager.servers["old"] is old and "old" in manager._saved_closing
    with pytest.raises(SavedReloadRefused):
        manager.prepare_saved_reload([_row("old", command="new")])
    assert not await manager.connect_server("old")
    release.set()
    await manager._saved_closing["old"]
    await asyncio.sleep(0)
    assert "old" not in manager._saved_closing


@pytest.mark.parametrize("change", ["authority", "registration"])
async def test_warm_cleaner_cannot_start_stale_replacement(monkeypatch, change):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    old.wanted = True
    manager.register(old)
    plan = manager.prepare_saved_reload([_row("old", command="new")])
    entered, release = asyncio.Event(), asyncio.Event()
    permitted = True
    connections = []

    async def warm():
        entered.set()
        await release.wait()

    async def connect(self):
        connections.append(self)
        return False

    async def current():
        return permitted

    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", warm)
    monkeypatch.setattr(MCPServer, "_connect_impl", connect)
    pending = asyncio.create_task(manager.apply_saved_reload(plan, still_current=current))
    await entered.wait()
    if change == "authority":
        permitted = False
    else:
        manager.register(MCPServer("old", command="owner", trust="full"))
    release.set()
    result = await pending
    assert result["status"] == "partial"
    assert connections == []


async def test_disconnect_during_post_connect_authority_await_reports_owner_change(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    old.wanted = True
    manager.register(old)
    plan = manager.prepare_saved_reload([_row("old", command="new")])
    entered, release = asyncio.Event(), asyncio.Event()
    checks = 0

    async def current():
        nonlocal checks
        checks += 1
        if checks == 5:
            entered.set()
            await release.wait()
        return True

    async def connect(self):
        self.tools = [MCPTool("read", "safe", {"type": "object"}, self.name)]
        return True

    monkeypatch.setattr(MCPServer, "_connect_impl", connect)
    monkeypatch.setattr(MCPServer, "is_connected", lambda self: bool(self.tools))
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    pending = asyncio.create_task(manager.apply_saved_reload(plan, still_current=current))
    await entered.wait()
    replacement = manager.servers["old"]
    await replacement.close()
    release.set()
    result = await pending
    assert result["status"] == "partial"
    assert result["servers"]["old"]["status"] == "owner_changed"
    assert manager.servers["old"] is replacement and not replacement.wanted


async def test_cancel_after_replacement_connect_waits_for_owned_teardown(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    old.wanted = True
    manager.register(old)
    plan = manager.prepare_saved_reload([_row("old", command="new")])
    checking, teardown, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    checks = 0

    async def current():
        nonlocal checks
        checks += 1
        if checks == 5:
            checking.set()
            await asyncio.Event().wait()
        return True

    async def connect(self):
        self._proc = SimpleNamespace(returncode=None)
        self.tools = [MCPTool("read", "safe", {"type": "object"}, self.name)]
        return True

    async def stop_transport(self):
        if self._proc is not None:
            teardown.set()
            await release.wait()
            self._proc = None

    monkeypatch.setattr(MCPServer, "_connect_impl", connect)
    monkeypatch.setattr(MCPServer, "_teardown", stop_transport)
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    pending = asyncio.create_task(manager.apply_saved_reload(plan, still_current=current))
    await asyncio.wait_for(checking.wait(), 1)
    replacement = manager.servers["old"]
    assert replacement.is_connected() and replacement.wanted
    pending.cancel()
    await asyncio.wait_for(teardown.wait(), 1)
    pending.cancel()
    assert manager._reload_lock.locked() and not pending.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not replacement.is_connected() and not replacement.wanted
    assert not manager._reload_lock.locked()


async def test_cancel_after_new_unchanged_refresh_closes_only_new_transport(monkeypatch):
    manager = MCPManager()
    old = MCPServer("old", command="fake", trust="full")
    old.wanted = True
    manager.register(old)
    plan = manager.prepare_saved_reload([_row("old")])
    checking, teardown, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    checks = 0

    async def current():
        nonlocal checks
        checks += 1
        if checks == 4:
            checking.set()
            await asyncio.Event().wait()
        return True

    async def connect(self):
        self._proc = SimpleNamespace(returncode=None)
        self.tools = [MCPTool("read", "safe", {"type": "object"}, self.name)]
        return True

    async def stop_transport(self):
        if self._proc is not None:
            teardown.set()
            await release.wait()
            self._proc = None

    monkeypatch.setattr(MCPServer, "_connect_impl", connect)
    monkeypatch.setattr(MCPServer, "_teardown", stop_transport)
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    pending = asyncio.create_task(manager.apply_saved_reload(plan, still_current=current))
    await asyncio.wait_for(checking.wait(), 1)
    assert old.is_connected()
    pending.cancel()
    await asyncio.wait_for(teardown.wait(), 1)
    assert manager._reload_lock.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not old.is_connected() and not old.wanted
