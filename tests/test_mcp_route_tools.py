"""Tests for H22.9 (read-only scope) — agent-native route tools over MCP.

The MCP server exposes an allow-listed set of READ-ONLY routes as ``route_<name>``
tools alongside the existing ``ask_<agent>`` tools. These tests are fully offline:
the agent runner and the route handlers are injected fakes — no orchestrator, no
app build, no network.

Covered:
  * kill-switch OFF (no route tools bound) → only agent tools exposed;
  * kill-switch ON (route tools bound) → agent tools + allow-listed route tools;
  * calling an allow-listed route dispatches its handler in-process, returns data;
  * a non-allow-listed / mutating route name is refused;
  * existing ``ask_<agent>`` behaviour is unchanged.
"""
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest

from agents.core.mcp.route_tools import (
    ROUTE_TOOL_ALLOWLIST,
    RouteTool,
    RouteToolSpec,
    build_route_tools,
    route_tool_name,
    route_tools_enabled,
)
from agents.core.mcp.server import JarvisMCPServer


# ── fakes ───────────────────────────────────────────────────────────────────

AGENTS = {"jarvis": "Prime orchestrator", "frigga": "Family"}


async def _runner(agent_id, text):
    return f"[{agent_id}] {text}"


async def _fake_status():
    return {"status": "ok", "version": "test"}


async def _fake_memory_search(q="", top_k=10):
    return {"results": [{"id": "m1", "q": q}], "query": q, "total": 1, "top_k": top_k}


class _FakeJSONResponse:
    """Mimics a Starlette JSONResponse: payload lives in ``.body`` (bytes)."""

    def __init__(self, data):
        self.body = json.dumps(data).encode("utf-8")


async def _fake_dashboard():
    return _FakeJSONResponse({"weather": "sunny", "news": []})


def _handlers():
    return {
        "status": _fake_status,
        "memory_search": _fake_memory_search,
        "dashboard": _fake_dashboard,
    }


def _server(with_routes: bool):
    route_tools = build_route_tools(_handlers()) if with_routes else []
    return JarvisMCPServer(_runner, AGENTS, route_tools=route_tools)


# ── kill-switch ─────────────────────────────────────────────────────────────

def test_kill_switch_default_off(monkeypatch):
    monkeypatch.delenv("JARVIS_MCP_ROUTE_TOOLS", raising=False)
    assert route_tools_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_kill_switch_truthy(monkeypatch, val):
    monkeypatch.setenv("JARVIS_MCP_ROUTE_TOOLS", val)
    assert route_tools_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_kill_switch_falsy(monkeypatch, val):
    monkeypatch.setenv("JARVIS_MCP_ROUTE_TOOLS", val)
    assert route_tools_enabled() is False


# ── listing: off vs on ──────────────────────────────────────────────────────

def test_list_tools_off_only_agent_tools():
    """Kill-switch off (no route tools) → today's behaviour, agents only."""
    names = {t["name"] for t in _server(with_routes=False).list_tools()}
    assert names == {"ask_jarvis", "ask_frigga"}
    assert not any(n.startswith("route_") for n in names)


def test_list_tools_on_agents_plus_routes():
    names = {t["name"] for t in _server(with_routes=True).list_tools()}
    assert {"ask_jarvis", "ask_frigga"} <= names
    assert {"route_status", "route_memory_search", "route_dashboard"} <= names


def test_route_tool_schemas_present():
    tools = {t["name"]: t for t in _server(with_routes=True).list_tools()}
    ms = tools["route_memory_search"]["inputSchema"]
    assert ms["type"] == "object"
    assert "q" in ms["properties"] and "top_k" in ms["properties"]
    # read-only routes have no required mutating body
    assert tools["route_status"]["inputSchema"]["properties"] == {}


def test_status_surfaces_exposed_routes():
    st = _server(with_routes=True).status()
    assert set(st["exposed_routes"]) == {"status", "memory_search", "dashboard"}
    st_off = _server(with_routes=False).status()
    assert st_off["exposed_routes"] == []


# ── calling route tools (in-process dispatch) ───────────────────────────────

@pytest.mark.asyncio
async def test_call_route_status_returns_data():
    res = await _server(with_routes=True).call_tool("route_status", {})
    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"]) == {"status": "ok", "version": "test"}


@pytest.mark.asyncio
async def test_call_route_memory_search_passes_args():
    res = await _server(with_routes=True).call_tool(
        "route_memory_search", {"q": "coffee", "top_k": 3}
    )
    payload = json.loads(res["content"][0]["text"])
    assert payload["query"] == "coffee"
    assert payload["top_k"] == 3
    assert payload["total"] == 1


@pytest.mark.asyncio
async def test_call_route_dashboard_decodes_jsonresponse():
    """A JSONResponse-style return (.body bytes) is decoded to the same payload."""
    res = await _server(with_routes=True).call_tool("route_dashboard", {})
    assert json.loads(res["content"][0]["text"]) == {"weather": "sunny", "news": []}


@pytest.mark.asyncio
async def test_call_route_filters_unknown_args():
    """Args not in the schema are dropped before reaching the handler."""
    res = await _server(with_routes=True).call_tool(
        "route_memory_search", {"q": "x", "evil": "rm -rf", "top_k": 2}
    )
    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"])["top_k"] == 2


# ── refusing non-allow-listed / mutating routes ─────────────────────────────

@pytest.mark.asyncio
async def test_call_non_allowlisted_route_refused():
    """A route_* name that is not bound is refused — the allow-list is the gate."""
    res = await _server(with_routes=True).call_tool("route_delete_everything", {})
    assert res["isError"] is True
    assert "not exposed" in res["content"][0]["text"]


@pytest.mark.asyncio
async def test_route_tools_refused_when_switch_off():
    """With no route tools bound, even an allow-listed name is unknown/refused."""
    res = await _server(with_routes=False).call_tool("route_status", {})
    assert res["isError"] is True
    assert "not exposed" in res["content"][0]["text"]


def test_build_route_tools_drops_missing_handlers():
    """A spec without a provided handler is silently not offered."""
    tools = build_route_tools({"status": _fake_status})
    assert {t.spec.name for t in tools} == {"status"}


def test_allowlist_is_read_only_get():
    """Guard: every allow-listed entry must be a read-only GET (no mutation)."""
    for spec in ROUTE_TOOL_ALLOWLIST:
        assert spec.method == "GET", f"{spec.name} must be read-only GET"


# ── existing ask_<agent> behaviour unchanged ────────────────────────────────

@pytest.mark.asyncio
async def test_ask_agent_still_works_with_routes_on():
    res = await _server(with_routes=True).call_tool("ask_jarvis", {"text": "hi"})
    assert res["isError"] is False
    assert res["content"][0]["text"] == "[jarvis] hi"


@pytest.mark.asyncio
async def test_unknown_ask_agent_still_errors():
    res = await _server(with_routes=True).call_tool("ask_nobody", {"text": "hi"})
    assert res["isError"] is True
    assert "unknown tool" in res["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_via_rpc_dispatches_route():
    srv = _server(with_routes=True)
    res = await srv.handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "route_status", "arguments": {}},
    })
    assert json.loads(res["result"]["content"][0]["text"])["status"] == "ok"


def test_route_tool_name_helper():
    assert route_tool_name("status") == "route_status"
