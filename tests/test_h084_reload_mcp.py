"""H084 owner chat refreshes only live wanted MCP connections."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest

from agents.core.commands import Principal
from agents.core.maintenance_commands import _names, reload_mcp
from agents.core.mcp.client import MCPManager, MCPServer, MCPTool
from agents.core.mcp.http_transport import MCPTransportError


class FakeServer(MCPServer):
    def __init__(self, name: str, *, plan=(), entered=None, release=None):
        super().__init__(name, command="fake", trust="full")
        self.plan = list(plan)
        self.connected = False
        self.entered = entered
        self.release = release
        self.calls = 0
        self.teardowns = 0

    def is_connected(self):
        return self.connected

    async def _connect_impl(self):
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        names = self.plan.pop(0) if self.plan else []
        if names is False:
            self.last_error = "fake_failure"
            return False
        self.tools = [MCPTool(name, "test", {"type": "object"}, self.name,
                              {"readOnlyHint": True}) for name in names]
        self.connected = True
        return True

    async def _teardown(self):
        self.teardowns += 1
        self.connected = False


def _ctx(manager, *, owner=True, args=""):
    return SimpleNamespace(orch=SimpleNamespace(mcp=manager), args=args,
                           principal=Principal(channel="web", admin=owner))


def _saved_fixture(manager, monkeypatch):
    from agents.core import mcp_reload_confirmation as confirmation

    manager.saved_reload_load_set = {"disabled": (), "only": ()}
    manager.saved_reload_commit_held = lambda rows: None
    configs = manager.to_config()
    monkeypatch.setattr(confirmation, "_read_saved_config", lambda _manager:
                        confirmation.SavedRead(configs, [], "settings", "boot", "live",
                                               id(manager.saved_reload_load_set)))


async def _confirm(ctx):
    preview = await reload_mcp(ctx)
    match = re.search(r"/reload_mcp confirm ([A-Za-z0-9_-]+)", preview)
    assert match, preview
    ctx.args = "confirm " + match.group(1)
    return await reload_mcp(ctx)


@pytest.mark.asyncio
async def test_owner_refreshes_wanted_server_and_reports_actual_tool_diff(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    manager = MCPManager()
    srv = FakeServer("docs", plan=[["read", "new"], ["read", "new"]])
    srv.connected = True
    srv.wanted = True
    srv.tools = [MCPTool("read", "old", {"type": "object"}, "docs"),
                 MCPTool("gone", "old", {"type": "object"}, "docs")]
    manager.register(srv)
    result = await manager.reload_wanted()
    assert result["status"] == "ok"
    row = result["servers"]["docs"]
    assert row["status"] == "refreshed" and row["connected_before"] and row["connected_after"]
    assert row["added"] == ["new"] and row["removed"] == ["gone"]
    assert row["changed"] == ["read"] and srv.wanted and srv.calls == 1
    _saved_fixture(manager, monkeypatch)
    report = await _confirm(_ctx(manager))
    assert "docs" in report and "refresh" in report.lower()


@pytest.mark.asyncio
async def test_guest_args_unwanted_and_session_scoped_never_connect():
    manager = MCPManager()
    unwanted = FakeServer("off", plan=[["danger"]])
    scoped = FakeServer("session", plan=[["private"]])
    scoped.wanted = True
    scoped.session_scope = "conversation-one"
    manager.register(unwanted)
    manager.register(scoped)
    assert "owner" in (await reload_mcp(_ctx(manager, owner=False))).lower()
    assert "usage" in (await reload_mcp(_ctx(manager, args="now"))).lower()
    result = await manager.reload_wanted()
    assert result["servers"]["off"]["status"] == "skipped_unwanted"
    assert result["servers"]["session"]["status"] == "skipped_session"
    assert unwanted.calls == scoped.calls == 0


@pytest.mark.asyncio
async def test_global_and_per_server_halt_refuse_without_connect(monkeypatch):
    manager = MCPManager()
    srv = FakeServer("docs", plan=[["x"]])
    srv.wanted = True
    manager.register(srv)
    monkeypatch.setattr(manager, "_halted", lambda name=None: "estop_engaged" if name is None else None)
    assert (await manager.reload_wanted())["status"] == "halted"
    assert srv.calls == 0
    monkeypatch.setattr(manager, "_halted", lambda name=None: None)
    monkeypatch.setattr(srv, "_halted", lambda **_kw: "kill_switch_engaged")
    result = await manager.reload_wanted()
    assert result["servers"]["docs"]["status"] == "skipped_halted"
    assert srv.calls == 0


@pytest.mark.asyncio
async def test_failed_refresh_distinguishes_retained_old_transport(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    manager = MCPManager()
    retained = FakeServer("retained", plan=[False])
    retained.connected = retained.wanted = True
    retained.tools = [MCPTool("old", "old", {"type": "object"}, "retained")]
    failed = FakeServer("failed", plan=[False])
    failed.wanted = True
    manager.register(retained)
    manager.register(failed)
    result = await manager.reload_wanted()
    assert result["servers"]["retained"]["status"] == "failed_retained"
    assert result["servers"]["retained"]["connected_after"]
    assert result["servers"]["failed"]["status"] == "failed_disconnected"


@pytest.mark.asyncio
async def test_single_flight_and_owner_disconnect_during_refresh(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    entered, release = asyncio.Event(), asyncio.Event()
    manager = MCPManager()
    srv = FakeServer("docs", plan=[["new"]], entered=entered, release=release)
    srv.wanted = True
    manager.register(srv)
    running = asyncio.create_task(manager.reload_wanted())
    await asyncio.wait_for(entered.wait(), 2)
    assert (await manager.reload_wanted())["status"] == "busy"
    await srv.close()
    release.set()
    result = await running
    assert result["servers"]["docs"]["status"] == "disconnected_by_owner"
    assert not srv.is_connected() and not srv.wanted


@pytest.mark.asyncio
async def test_remove_during_refresh_cannot_leave_orphan(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    entered, release = asyncio.Event(), asyncio.Event()
    manager = MCPManager()
    srv = FakeServer("docs", plan=[["new"]], entered=entered, release=release)
    srv.wanted = True
    manager.register(srv)
    running = asyncio.create_task(manager.reload_wanted())
    await asyncio.wait_for(entered.wait(), 2)
    assert await manager.remove_server("docs")
    release.set()
    result = await running
    assert result["servers"]["docs"]["status"] == "removed"
    assert not srv.is_connected() and "docs" not in manager.servers


@pytest.mark.asyncio
async def test_cancellation_tears_down_and_releases_single_flight(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    entered, release = asyncio.Event(), asyncio.Event()
    manager = MCPManager()
    srv = FakeServer("docs", plan=[["new"]], entered=entered, release=release)
    srv.wanted = True
    manager.register(srv)
    running = asyncio.create_task(manager.reload_wanted())
    await asyncio.wait_for(entered.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert srv.teardowns and not srv.is_connected()
    release.set()
    assert (await manager.reload_wanted())["status"] != "busy"


@pytest.mark.asyncio
async def test_reload_obeys_bounded_parallelism(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    manager = MCPManager()
    manager.connect_concurrency = 2
    entered, release = asyncio.Event(), asyncio.Event()
    active = 0
    peak = 0

    async def connect(self):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        entered.set()
        await release.wait()
        active -= 1
        self.connected = True
        return True

    for i in range(5):
        srv = FakeServer(f"s{i}")
        srv.wanted = True
        srv._connect_impl = connect.__get__(srv)
        manager.register(srv)
    running = asyncio.create_task(manager.reload_wanted())
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.sleep(0)
    assert peak == 2
    release.set()
    assert (await running)["status"] == "ok" and peak == 2


@pytest.mark.asyncio
async def test_halt_engaged_during_handshake_tears_down_without_losing_wanted(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    stopped = [False]
    manager = MCPManager()
    monkeypatch.setattr(manager, "_halted", lambda name=None:
                        "estop_engaged" if stopped[0] else None)
    entered, release = asyncio.Event(), asyncio.Event()
    srv = FakeServer("docs", plan=[["new"]], entered=entered, release=release)
    srv.wanted = True
    manager.register(srv)
    monkeypatch.setattr(srv, "_halted", lambda **_kw:
                        "estop_engaged" if stopped[0] else None)
    running = asyncio.create_task(manager.reload_wanted())
    await asyncio.wait_for(entered.wait(), 2)
    stopped[0] = True
    release.set()
    row = (await running)["servers"]["docs"]
    assert row["status"] == "skipped_halted" and not row["connected_after"]
    assert not srv.is_connected() and srv.wanted and srv.teardowns


@pytest.mark.asyncio
async def test_diff_freezes_in_place_schema_edits_and_duplicate_names(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    manager = MCPManager()
    srv = FakeServer("docs")
    srv.connected = srv.wanted = True
    first = MCPTool("read", "old", {"type": "object", "properties": {}}, "docs")
    duplicate = MCPTool("read", "second", {"type": "object"}, "docs")
    srv.tools = [first, duplicate]
    manager.register(srv)

    async def mutate():
        first.input_schema["properties"]["new"] = {"type": "string"}
        srv.tools = [first]
        return True

    monkeypatch.setattr(srv, "_connect_impl", mutate)
    row = (await manager.reload_wanted())["servers"]["docs"]
    assert row["changed"] == ["read"] and row["unchanged"] == 0


@pytest.mark.asyncio
async def test_long_known_secret_tool_name_is_sanitized_before_display_cut(monkeypatch):
    secret = "opaque" * 16
    monkeypatch.setenv("ACME_API_KEY", secret)
    manager = MCPManager()
    srv = FakeServer("docs", plan=[[secret]])
    srv.wanted = True
    manager.register(srv)
    _saved_fixture(manager, monkeypatch)
    report = await _confirm(_ctx(manager))
    assert secret not in report and secret[:64] not in report
    listed = _names("Added", [secret])
    assert secret not in listed and secret[:64] not in listed


@pytest.mark.asyncio
async def test_failed_handshake_closes_new_partial_transport_without_touching_old(monkeypatch):
    srv = MCPServer("docs", command="fake")
    opened = object()
    closed = []

    async def fail_new():
        srv._proc = opened
        srv.last_error = "handshake_failed"
        return False

    async def close():
        closed.append(srv._proc)
        srv._proc = None

    monkeypatch.setattr(srv, "_connect_impl", fail_new)
    monkeypatch.setattr(srv, "_teardown", close)
    assert not await srv.connect()
    assert closed == [opened] and srv._proc is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["initialize", "notification"])
async def test_http_transport_error_during_handshake_closes_allocated_transport(
    monkeypatch, failure_stage,
):
    monkeypatch.setattr("agents.core.mcp.client.http_client_enabled", lambda: True)
    opened = []

    class FailingHTTP:
        initialized = False

        async def initialize(self):
            opened.append("initialize")
            if failure_stage == "initialize":
                raise MCPTransportError("handshake_failed", "test")
            self.initialized = True
            opened.append("notification")
            raise MCPTransportError("notification_failed", "test")

        async def close(self):
            opened.append("close")

    srv = MCPServer("docs", transport="streamable-http", url="http://127.0.0.1:9/mcp",
                    http_transport_factory=lambda *_a, **_k: FailingHTTP())
    assert not await srv.connect()
    expected = ["initialize"] if failure_stage == "initialize" else ["initialize", "notification"]
    assert opened == [*expected, "close"]
    assert srv._http is None and not srv.is_connected()


@pytest.mark.asyncio
async def test_report_counts_failures_even_beyond_displayed_servers(monkeypatch):
    monkeypatch.setattr("agents.core.mcp.client.warm_cleaner", lambda: asyncio.sleep(0))
    manager = MCPManager()
    for index in range(14):
        srv = FakeServer(f"s{index:02d}", plan=[False])
        srv.wanted = index == 13
        manager.register(srv)
    _saved_fixture(manager, monkeypatch)
    report = await _confirm(_ctx(manager))
    assert "s13" not in report
    assert "+6 more servers" in report
    assert "failed 1" in report.lower()
    assert "skipped 13" in report.lower()


@pytest.mark.asyncio
async def test_replaced_manager_is_not_reported_as_current(monkeypatch):
    manager = MCPManager()
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(plan, *, still_current):
        entered.set()
        await release.wait()
        return {"status": "ok", "servers": {"old": {"status": "refreshed",
                "connected_after": True, "added": ["oldtool"], "removed": [], "changed": []}}}

    _saved_fixture(manager, monkeypatch)
    monkeypatch.setattr(manager, "apply_saved_reload", pending)
    ctx = _ctx(manager)
    running = asyncio.create_task(_confirm(ctx))
    await asyncio.wait_for(entered.wait(), 2)
    ctx.orch.mcp = MCPManager()
    release.set()
    report = await running
    assert "manager replaced" in report.lower()
    assert "oldtool" not in report
