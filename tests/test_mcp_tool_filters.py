"""Hermes absorption 4c — attaching an MCP server is not attaching every one of its tools.

`tools_allow` / `tools_deny` are glob patterns on the tool name: applied at `tools/list`
(a hidden tool is never offered) and again at call time (a remembered name cannot go around
the filter). A deny always wins; a malformed filter narrows to nothing, never to everything.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import agents.web as web  # noqa: E402
from agents.core.mcp.client import MCPManager, MCPServer  # noqa: E402

_TOKEN = "mcp-filter-token"
_HDR = {"X-Admin-Token": _TOKEN}

TOOLS_LIST = {
    "jsonrpc": "2.0", "id": 2,
    "result": {"tools": [
        {"name": "read_file", "annotations": {"readOnlyHint": True}},
        {"name": "list_dir", "annotations": {"readOnlyHint": True}},
        {"name": "write_file"},
        {"name": "delete_file"},
    ]},
}


def _server(**kwargs):
    srv = MCPServer("fs", transport="stdio", command="true", trust="full", **kwargs)
    srv.sent = []

    async def fake_send(payload):
        srv.sent.append(payload)
        if payload.get("method") == "tools/list":
            return TOOLS_LIST
        return {"jsonrpc": "2.0", "id": 3, "result": {"ok": True}}

    srv._send = fake_send  # type: ignore[method-assign]
    return srv


@pytest.mark.asyncio
async def test_allow_and_deny_filter_the_listing_and_deny_wins():
    srv = _server(tools_allow=["*_file", "list_*"], tools_deny=["delete_*"])
    await srv._list_tools()
    assert [t.name for t in srv.tools] == ["read_file", "list_dir", "write_file"]
    srv = _server(tools_deny=["write_*", "delete_*"])
    await srv._list_tools()
    assert [t.name for t in srv.tools] == ["read_file", "list_dir"]
    srv = _server()
    await srv._list_tools()
    assert len(srv.tools) == 4


@pytest.mark.asyncio
async def test_a_filtered_tool_cannot_be_called_by_name():
    srv = _server(tools_deny=["delete_*"])
    await srv._list_tools()
    srv.sent.clear()
    assert await srv.call_tool("delete_file", {}) == {"error": "tool_filtered", "tool": "delete_file", "server": "fs"}
    assert srv.sent == []
    assert await srv.call_tool("write_file", {}) == {"ok": True}
    manager = MCPManager()
    manager.register(srv)
    assert (await manager.call_tool("delete_file"))["error"] == "Tool 'delete_file' not found"


def test_malformed_filters_narrow_to_nothing_and_config_round_trips():
    assert MCPServer("a", command="x", tools_allow="read_*").tools_allow == []
    assert MCPServer("a", command="x", tools_deny=[3, "", "  ok  "]).tools_deny == ["ok"]
    assert MCPServer("a", command="x").tools_allow is None
    manager = MCPManager()
    manager.register(MCPServer("fs", command="x", tools_allow=["read_*"], tools_deny=["*secret*"]))
    config = manager.to_config()[0]
    assert config["tools_allow"] == ["read_*"] and config["tools_deny"] == ["*secret*"]
    fresh = MCPManager()
    fresh.load_from_config([config, {"name": "bare", "command": "y", "trust": "full"}])
    assert fresh.servers["fs"].tools_allow == ["read_*"] and fresh.servers["fs"].tools_deny == ["*secret*"]
    assert fresh.servers["bare"].tools_allow is None and fresh.servers["bare"].tools_deny == []


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "_save_mcp_config", lambda: None)
    orch = MagicMock()
    orch.mcp.servers = {}
    orch.mcp.to_config = MagicMock(return_value=[])
    monkeypatch.setattr(web, "orch", orch)
    return TestClient(web.app), orch


def test_the_add_route_takes_filters_and_refuses_malformed_ones(api):
    client, orch = api
    resp = client.post("/api/admin/mcp", json={
        "name": "fs", "command": "fs-mcp", "tools_allow": ["read_*"], "tools_deny": ["delete_*"],
    }, headers=_HDR)
    assert resp.status_code == 200
    assert orch.mcp.servers["fs"].tools_allow == ["read_*"] and orch.mcp.servers["fs"].tools_deny == ["delete_*"]
    resp = client.post("/api/admin/mcp", json={"name": "x", "command": "x", "tools_deny": ["", "ok"]}, headers=_HDR)
    assert resp.status_code == 400 and resp.json() == {"error": "invalid_tool_filter", "field": "tools_deny"}
    assert "x" not in orch.mcp.servers
    row = client.get("/api/admin/mcp", headers=_HDR).json()["servers"][0]
    assert row["tools_allow"] == ["read_*"] and row["tools_deny"] == ["delete_*"]
