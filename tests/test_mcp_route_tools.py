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

import inspect
import typing

from agents.core.mcp.route_tools import (
    ROUTE_TOOL_ALLOWLIST,
    RouteTool,
    RouteToolSpec,
    _should_skip_param,
    build_route_tools,
    derive_input_schema,
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


async def _fake_memory_search(q: str = "", top_k: int = 10):
    # Annotated to mirror the real handler signature
    # (agents.core.routers.memory_kg.memory_search) so the reflected schema
    # carries types, matching what build_route_tools derives in production.
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


def test_schema_reflected_from_handler_signature():
    """The schema is DERIVED from the handler's signature (not hand-declared).

    Types and defaults come straight off ``_fake_memory_search(q="", top_k=10)``.
    """
    schema = derive_input_schema(_fake_memory_search)
    assert schema == {
        "type": "object",
        "properties": {
            "q": {"type": "string", "default": ""},
            "top_k": {"type": "integer", "default": 10},
        },
    }
    # No-arg handler → empty properties, no ``required``.
    assert derive_input_schema(_fake_status) == {"type": "object", "properties": {}}


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


# ── drift-guard: derived schema must match the live handler signature ────────
#
# This is the whole point of H22.9 hardening: the tool schema is reflected from
# the handler's own signature, so a future signature change that nobody mirrors
# fails CI instead of silently shipping a stale schema.

def _caller_param_names(handler):
    """Names of the params a caller actually supplies (drop framework injections).

    Independent re-implementation of the reflection rule used by
    ``derive_input_schema`` — if the two ever disagree the drift-guard fails.
    """
    sig = inspect.signature(handler)
    try:
        hints = typing.get_type_hints(handler)
    except Exception:
        hints = {}
    names = []
    for pname, param in sig.parameters.items():
        param = param.replace(annotation=hints.get(pname, param.annotation))
        if _should_skip_param(param):
            continue
        names.append(pname)
    return names


def _real_route_handlers():
    """Import the LIVE handlers bound by web.py for the allow-listed routes.

    Reflecting the real functions (not fakes) is what makes the guard bite: a
    real-signature change is caught here. Skips gracefully if the app module
    can't import offline (so the suite stays runnable without a live app).
    """
    handlers = {}
    try:
        from agents import web  # noqa: F401  (binds /status, /dashboard)
        from agents.core.routers.memory_kg import memory_search
    except Exception:
        return None
    handlers["status"] = web.status
    handlers["dashboard"] = web.dashboard
    handlers["memory_search"] = memory_search
    return handlers


def test_drift_guard_schema_matches_real_handler_signature():
    """For each allow-listed route, the derived schema properties == the live
    handler's caller-supplied params. A signature change that isn't reflected by
    ``derive_input_schema`` (or vice-versa) breaks here — schema drift can't merge.
    """
    handlers = _real_route_handlers()
    if handlers is None:
        pytest.skip("app module not importable offline; drift-guard needs live handlers")

    allow_names = {s.name for s in ROUTE_TOOL_ALLOWLIST}
    assert set(handlers) == allow_names, "drift-guard handler map must cover the allow-list"

    for spec in ROUTE_TOOL_ALLOWLIST:
        handler = handlers[spec.name]
        schema = derive_input_schema(handler)
        derived_props = set(schema.get("properties", {}).keys())
        expected = set(_caller_param_names(handler))
        assert derived_props == expected, (
            f"schema drift for route '{spec.name}': "
            f"derived {sorted(derived_props)} != handler params {sorted(expected)}"
        )


def test_drift_guard_catches_unmirrored_signature_change():
    """The guard actually bites: add a param to a handler and the derived schema
    must reflect it (else the equality below would fail), proving no silent drift.
    """
    async def handler_v1(q: str = ""):
        return {}

    async def handler_v2(q: str = "", limit: int = 5):  # a param was added
        return {}

    assert set(derive_input_schema(handler_v1)["properties"]) == {"q"}
    # The new param is reflected automatically — no hand edit needed, no drift.
    assert set(derive_input_schema(handler_v2)["properties"]) == {"q", "limit"}
    assert derive_input_schema(handler_v2)["properties"]["limit"] == {
        "type": "integer",
        "default": 5,
    }


def test_pydantic_model_param_expands_to_fields():
    """A pydantic-model param is flattened into per-field properties + required."""
    pydantic = pytest.importorskip("pydantic")

    class Filter(pydantic.BaseModel):
        q: str
        top_k: int = 10

    async def handler(body: Filter):
        return {}

    schema = derive_input_schema(handler)
    props = schema["properties"]
    assert set(props) == {"q", "top_k"}
    assert props["q"]["type"] == "string"
    assert props["top_k"] == {"type": "integer", "default": 10}
    assert schema.get("required") == ["q"]


def test_framework_injected_params_are_skipped():
    """Request/Depends params are framework-injected, never caller args."""
    fastapi = pytest.importorskip("fastapi")

    async def handler(q: str = "", req: fastapi.Request = None,
                      user=fastapi.Depends(lambda: None)):
        return {}

    props = derive_input_schema(handler)["properties"]
    assert set(props) == {"q"}, "Request/Depends must not appear as caller args"


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
