"""Hermes absorption 4b — MCP trust tiers, `readOnlyHint` fail-closed.

Every tool an MCP server listed could be called. Now a server is read-only unless the owner
says otherwise: only a tool the server itself marked `readOnlyHint: true` may run on it; an
unannotated, unlisted or mutating tool is refused by name before any request leaves. The
hint is the server's claim, so it can only narrow what a tier allows, never widen it.
"""
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import agents.web as web  # noqa: E402
from agents.core.mcp.client import (  # noqa: E402
    TRUST_FULL,
    TRUST_READ_ONLY,
    TRUST_TIERS,
    MCPManager,
    MCPServer,
    MCPTool,
    normalize_trust,
)

_TOKEN = "mcp-trust-token"
_HDR = {"X-Admin-Token": _TOKEN}

TOOLS_LIST = {
    "jsonrpc": "2.0", "id": 2,
    "result": {"tools": [
        {"name": "read", "description": "Read.", "inputSchema": {"type": "object"},
         "annotations": {"readOnlyHint": True, "title": "Read"}},
        {"name": "write", "description": "Write.", "inputSchema": {"type": "object"},
         "annotations": {"readOnlyHint": False}},
        {"name": "vague", "description": "No annotations at all."},
        {"name": "liar", "description": "A string is not a claim.", "annotations": {"readOnlyHint": "true"}},
    ]},
}


def _server(trust=TRUST_READ_ONLY, *, sent=None):
    srv = MCPServer("remote", transport="stdio", command="true", trust=trust)

    async def fake_send(payload):
        if sent is not None:
            sent.append(payload)
        if payload.get("method") == "tools/list":
            return TOOLS_LIST
        return {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"text": "done"}]}}

    srv._send = fake_send  # type: ignore[method-assign]
    return srv


@pytest.mark.asyncio
async def test_tools_list_captures_the_servers_claims_without_believing_strings():
    srv = _server()
    await srv._list_tools()
    by_name = {t.name: t for t in srv.tools}
    assert by_name["read"].read_only is True and by_name["read"].annotations["title"] == "Read"
    assert by_name["write"].read_only is False
    assert by_name["vague"].read_only is False and by_name["vague"].annotations == {}
    assert by_name["liar"].read_only is False  # only a JSON true counts


@pytest.mark.asyncio
async def test_a_read_only_server_runs_only_tools_it_marked_read_only():
    sent: list = []
    srv = _server(sent=sent)
    await srv._list_tools()
    sent.clear()
    assert await srv.call_tool("read", {}) == {"content": [{"text": "done"}]}
    assert [p["method"] for p in sent] == ["tools/call"]
    for name, reason in (("write", "readOnlyHint_required"), ("vague", "readOnlyHint_required"),
                         ("liar", "readOnlyHint_required"), ("delete", "unlisted_tool")):
        out = await srv.call_tool(name, {})
        assert out == {"error": "trust_denied", "tool": name, "server": "remote",
                       "trust": "read-only", "reason": reason}, name
    assert len(sent) == 1  # nothing left the box for the refused calls


@pytest.mark.asyncio
async def test_full_trust_leaves_the_decision_to_the_contract_and_kernel():
    sent: list = []
    srv = _server(TRUST_FULL, sent=sent)
    await srv._list_tools()
    sent.clear()
    assert await srv.call_tool("write", {"x": 1}) == {"content": [{"text": "done"}]}
    assert await srv.call_tool("vague", {}) == {"content": [{"text": "done"}]}
    assert len(sent) == 2


def test_trust_is_validated_and_normalized():
    assert MCPServer("a", command="true").trust == TRUST_READ_ONLY
    assert MCPServer("a", command="true", trust=" RO ").trust == TRUST_READ_ONLY
    assert MCPServer("a", command="true", trust="read-write").trust == TRUST_FULL
    with pytest.raises(ValueError):
        MCPServer("a", command="true", trust="maybe")
    assert normalize_trust(None) is None and normalize_trust("FULL") == TRUST_FULL
    assert TRUST_TIERS == ("read-only", "full")


def test_config_round_trip_and_the_legacy_default(caplog):
    manager = MCPManager()
    manager.register(MCPServer("ro", command="a"))
    manager.register(MCPServer("rw", command="b", trust=TRUST_FULL))
    config = manager.to_config()
    assert [(c["name"], c["trust"]) for c in config] == [("ro", "read-only"), ("rw", "full")]

    fresh = MCPManager()
    with caplog.at_level(logging.WARNING, logger="jarvis.mcp"):
        fresh.load_from_config(config + [
            {"name": "legacy", "transport": "stdio", "command": "c"},
            {"name": "odd", "transport": "stdio", "command": "d", "trust": "sometimes"},
        ])
    assert fresh.servers["ro"].trust == TRUST_READ_ONLY
    assert fresh.servers["rw"].trust == TRUST_FULL
    # Saved before tiers existed: keeps working as it did, and says so.
    assert fresh.servers["legacy"].trust == TRUST_FULL
    # An unknown spelling is not a licence: read-only.
    assert fresh.servers["odd"].trust == TRUST_READ_ONLY
    messages = [r.getMessage() for r in caplog.records]
    assert any("legacy" in m and "no trust tier" in m for m in messages)
    assert any("odd" in m and "unknown trust tier" in m for m in messages)


@pytest.mark.asyncio
async def test_the_manager_surfaces_a_trust_denial_by_name():
    manager = MCPManager()
    srv = _server()
    await srv._list_tools()
    manager.register(srv)
    out = await manager.call_tool("remote/write", {})
    assert out["error"] == "trust_denied" and out["reason"] == "readOnlyHint_required"
    assert (await manager.call_tool("read"))["content"] == [{"text": "done"}]


def test_worldviews_own_server_is_full_trust():
    from agents.core.mcp import worldview_write

    assert worldview_write.TRUST_FULL == TRUST_FULL
    source = Path(worldview_write.__file__).read_text(encoding="utf-8")
    assert "trust=TRUST_FULL" in source


# ── the admin route ──────────────────────────────────────────────────────────

def _mock_orch(servers=None):
    m = MagicMock()
    m.mcp.servers = servers if servers is not None else {}
    m.mcp.to_config = MagicMock(return_value=[])
    return m


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "_save_mcp_config", lambda: None)
    orch = _mock_orch({})
    monkeypatch.setattr(web, "orch", orch)
    return TestClient(web.app), orch


def test_add_defaults_to_read_only_and_accepts_full(api):
    client, orch = api
    resp = client.post("/api/admin/mcp", json={"name": "fs", "command": "fs-mcp"}, headers=_HDR)
    assert resp.status_code == 200 and orch.mcp.servers["fs"].trust == TRUST_READ_ONLY
    resp = client.post(
        "/api/admin/mcp", json={"name": "git", "command": "git-mcp", "trust": "full"}, headers=_HDR,
    )
    assert resp.status_code == 200 and orch.mcp.servers["git"].trust == TRUST_FULL


def test_add_refuses_an_unknown_tier_before_anything_is_written(api):
    client, orch = api
    resp = client.post(
        "/api/admin/mcp", json={"name": "x", "command": "x-mcp", "trust": "maybe"}, headers=_HDR,
    )
    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid_trust", "trust": "maybe", "supported": ["read-only", "full"]}
    assert orch.mcp.servers == {}


def test_list_shows_the_tier_and_each_tools_claim(api):
    client, orch = api
    srv = MCPServer("fs", command="fs-mcp")
    srv.tools = [
        MCPTool("read", "Read.", {}, "fs", annotations={"readOnlyHint": True}),
        MCPTool("write", "Write.", {}, "fs"),
    ]
    orch.mcp.servers["fs"] = srv
    row = client.get("/api/admin/mcp", headers=_HDR).json()["servers"][0]
    assert row["trust"] == "read-only"
    assert row["tools"] == [
        {"name": "read", "description": "Read.", "read_only": True},
        {"name": "write", "description": "Write.", "read_only": False},
    ]
