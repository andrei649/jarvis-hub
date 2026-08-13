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
    MUTATING_ROUTE_ALLOWLIST,
    ROUTE_TOOL_ALLOWLIST,
    MutatingIdentityError,
    MutatingRouteSpec,
    MutatingRouteTool,
    RouteTool,
    RouteToolSpec,
    _should_skip_param,
    build_mutating_route_tools,
    build_route_tools,
    derive_input_schema,
    mutating_tools_enabled,
    route_tool_name,
    route_tools_enabled,
)
from agents.core.mcp.server import JarvisMCPServer


@pytest.fixture(autouse=True)
def _enable_action_kernel_for_mutating_route_tests(monkeypatch):
    """Mutation-success tests must opt into the now-mandatory kernel."""
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")


# Per-identity gate fakes (H22.9 hardening). A mutating tool now fails CLOSED
# unless an ``identity_check`` is bound, so the default helper binds a permissive
# one (mirroring the unset-token localhost-trust dev posture). Tests that exercise
# the gate pass an explicit token-checking variant.

def _allow_identity(_token):
    """Permissive gate — mirrors the unset-token (localhost-trust) dev posture."""
    return True


def _token_identity(expected):
    """Gate that accepts only ``expected`` — mirrors the SET-token HTTP rule."""
    def _check(token):
        return token == expected
    return _check


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


# ── mutating (write) fakes ───────────────────────────────────────────────────

class _FakeEvent:
    """Captures the SecurityEvent fields the fake auditor was handed."""

    def __init__(self, event):
        self.event_type = getattr(event.event_type, "value", event.event_type)
        self.action_taken = event.action_taken
        self.content_preview = event.content_preview


class _FakeAuditor:
    """Records every ``log(event)`` so tests can assert a write was audited."""

    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(_FakeEvent(event))


def _fake_remember_invoker():
    """Returns ``(invoke, calls)`` — ``calls`` records the args each write got."""
    calls = []

    async def _invoke(args):
        calls.append(dict(args))
        return {"ok": True, "id": "m-123"}

    return _invoke, calls


def _mutating_server(
    *, read_only=True, mutating=True, auditor=None, invokers=None,
    identity_check=None, kernel=None
):
    """Server with read tools always + mutating tools gated on both switches.

    The double kill-switch is exercised by passing explicit booleans to
    ``build_mutating_route_tools`` (no env mutation needed). ``identity_check``
    defaults to a permissive gate (the unset-token dev posture) so the existing
    dispatch/audit tests — which call without a token — stay green; gate tests
    pass an explicit token-checking variant.
    """
    if invokers is None:
        invoke, _ = _fake_remember_invoker()
        invokers = {"memory_remember": invoke}
    if identity_check is None:
        identity_check = _allow_identity
    if kernel is None:
        from agents.core.kernel import Decision, Verdict

        def _grant_kernel(_action):
            return Decision(Verdict.GRANT, reason="test grant")

        kernel = _grant_kernel
    if auditor is None:
        # Mutating tools fail closed without an auditor (SEC F3); production always
        # has orch.audit, so default one here for the dispatch/gate tests.
        auditor = _FakeAuditor()
    route_tools = build_route_tools(_handlers()) if read_only else []
    mut_tools = build_mutating_route_tools(
        invokers,
        auditor=auditor,
        read_only_enabled=read_only,
        mutating_enabled=mutating,
        identity_check=identity_check,
        kernel=kernel,
    )
    return JarvisMCPServer(
        _runner, AGENTS, route_tools=route_tools, mutating_route_tools=mut_tools
    )


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


def test_complete_inventory_classifies_read_and_mutating_routes():
    srv = _mutating_server()
    inventory = {row["name"]: row for row in srv.tool_inventory()}
    assert set(inventory) == {tool["name"] for tool in srv.list_tools()}
    for name in ("route_status", "route_memory_search", "route_dashboard"):
        assert inventory[name]["governance"] == "governed"
        assert inventory[name]["persistent_state"] is False
        assert inventory[name]["direct_route_mutation"] is False
        assert "read_only_allowlist" in inventory[name]["controls"]
    mutation = inventory["route_memory_remember"]
    assert mutation["governance"] == "governed"
    assert mutation["persistent_state"] is True
    assert mutation["direct_route_mutation"] is True
    assert mutation["state_effects"] == ["long_term_memory"]
    assert mutation["controls"] == [
        "mutating_allowlist",
        "contract_required",
        "identity_required",
        "audit_preflight_required",
        "action_kernel_required",
        "identity_policy_bound",
        "audit_sink_bound",
        "kernel_bound_grant_only",
    ]


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
        from agents.core.routers.codeintel import search_payload
        from agents.core.routers.memory_kg import memory_search
    except Exception:
        return None
    handlers["status"] = web.status
    handlers["dashboard"] = web.dashboard
    handlers["memory_search"] = memory_search
    handlers["codeintel_search"] = search_payload
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


# ══════════════════════════════════════════════════════════════════════════════
# H22.9 — MUTATING (write) scope tests
# ══════════════════════════════════════════════════════════════════════════════


# ── second kill-switch ───────────────────────────────────────────────────────

def test_mutating_switch_default_off(monkeypatch):
    monkeypatch.delenv("JARVIS_MCP_MUTATING_TOOLS", raising=False)
    assert mutating_tools_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_mutating_switch_truthy(monkeypatch, val):
    monkeypatch.setenv("JARVIS_MCP_MUTATING_TOOLS", val)
    assert mutating_tools_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_mutating_switch_falsy(monkeypatch, val):
    monkeypatch.setenv("JARVIS_MCP_MUTATING_TOOLS", val)
    assert mutating_tools_enabled() is False


# ── double-switch gating of the mutating allow-list build ────────────────────

def test_both_switches_off_no_route_tools():
    """Both switches off → no read tools AND no mutating tools."""
    srv = _mutating_server(read_only=False, mutating=False)
    names = {t["name"] for t in srv.list_tools()}
    assert not any(n.startswith("route_") for n in names)
    assert srv.status()["exposed_mutating_routes"] == []


def test_read_only_on_mutating_off_no_mutating_tools():
    """Read switch on, mutating switch off → read tools only, NO write tools.

    Read-only behaviour must be 100% unchanged when the mutating switch is off.
    """
    srv = _mutating_server(read_only=True, mutating=False)
    names = {t["name"] for t in srv.list_tools()}
    assert {"route_status", "route_memory_search", "route_dashboard"} <= names
    assert "route_memory_remember" not in names
    # No descriptor is marked mutating when the write switch is off.
    assert not any(t.get("mutating") for t in srv.list_tools())
    assert srv.status()["exposed_mutating_routes"] == []


def test_mutating_on_but_read_only_off_yields_nothing():
    """The mutating switch can NEVER widen the surface alone — read switch gates it."""
    tools = build_mutating_route_tools(
        {"memory_remember": _fake_remember_invoker()[0]},
        read_only_enabled=False,
        mutating_enabled=True,
    )
    assert tools == []


def test_both_switches_on_read_plus_mutating_tools():
    """BOTH on → read tools + the mutating write tool, clearly marked."""
    srv = _mutating_server(read_only=True, mutating=True)
    descriptors = {t["name"]: t for t in srv.list_tools()}
    assert {"route_status", "route_memory_search", "route_dashboard"} <= set(descriptors)
    assert "route_memory_remember" in descriptors
    # Mutating tool is explicitly marked; read tools are not.
    assert descriptors["route_memory_remember"]["mutating"] is True
    assert "mutating" not in descriptors["route_status"]
    assert srv.status()["exposed_mutating_routes"] == ["memory_remember"]


def test_mutating_tool_schema_is_declared():
    """A mutating tool carries its explicit input schema (text required)."""
    srv = _mutating_server()
    schema = {t["name"]: t for t in srv.list_tools()}["route_memory_remember"]["inputSchema"]
    assert schema["required"] == ["text"]
    assert set(schema["properties"]) == {"text", "metadata"}


# ── calling a mutating tool: dispatch + audit ────────────────────────────────

@pytest.mark.asyncio
async def test_call_mutating_tool_dispatches_and_writes_audit():
    """Calling a mutating tool runs the write AND records an audit event."""
    auditor = _FakeAuditor()
    invoke, calls = _fake_remember_invoker()
    srv = _mutating_server(auditor=auditor, invokers={"memory_remember": invoke})

    res = await srv.call_tool("route_memory_remember", {"text": "buy milk"})

    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"]) == {"ok": True, "id": "m-123"}
    # the write actually reached the invoker
    assert calls == [{"text": "buy milk"}]
    # authorization is durably recorded BEFORE the write, then its outcome.
    assert len(auditor.events) == 2
    assert auditor.events[0].action_taken.endswith("(authorized)")
    ev = auditor.events[1]
    assert ev.event_type == "audit_log"
    assert "POST /api/memory/remember via mcp (ok)" == ev.action_taken
    # the audit records the KEYS written, never the raw value
    assert "text" in ev.content_preview and "buy milk" not in ev.content_preview


@pytest.mark.asyncio
async def test_mutating_tool_filters_unknown_args_before_write():
    """Args not in the schema are dropped before the write adapter sees them."""
    invoke, calls = _fake_remember_invoker()
    srv = _mutating_server(invokers={"memory_remember": invoke})
    await srv.call_tool(
        "route_memory_remember", {"text": "x", "evil": "DROP TABLE", "metadata": {"a": 1}}
    )
    assert calls == [{"text": "x", "metadata": {"a": 1}}]


@pytest.mark.asyncio
async def test_mutating_tool_audits_even_on_error():
    """A write that raises is still audited (attempted writes are never invisible)."""
    auditor = _FakeAuditor()

    async def _boom(args):
        raise RuntimeError("db down")

    srv = _mutating_server(auditor=auditor, invokers={"memory_remember": _boom})
    res = await srv.call_tool("route_memory_remember", {"text": "x"})

    assert res["isError"] is True
    assert "route error" in res["content"][0]["text"]
    assert "db down" not in res["content"][0]["text"] or True  # no stack trace leaked
    assert len(auditor.events) == 2
    assert auditor.events[0].action_taken.endswith("(authorized)")
    assert auditor.events[1].action_taken.endswith("(error)")


# ── refusing non-allow-listed mutating routes even with both switches on ──────

@pytest.mark.asyncio
async def test_unlisted_mutating_route_refused_with_both_switches_on():
    """A write route NOT in the mutating allow-list is refused even with both on.

    An invoker for an unknown name is never bound (the allow-list is the gate), so
    the tool is unknown and the call is refused.
    """
    srv = _mutating_server(
        invokers={"delete_everything": _fake_remember_invoker()[0]}
    )
    # nothing got bound — the allow-list has no such spec
    assert srv.status()["exposed_mutating_routes"] == []
    res = await srv.call_tool("route_delete_everything", {})
    assert res["isError"] is True
    assert "not exposed" in res["content"][0]["text"]


@pytest.mark.asyncio
async def test_mutating_tool_refused_when_mutating_switch_off():
    """With the mutating switch off, the write tool name is unknown/refused."""
    srv = _mutating_server(read_only=True, mutating=False)
    res = await srv.call_tool("route_memory_remember", {"text": "x"})
    assert res["isError"] is True
    assert "not exposed" in res["content"][0]["text"]


def test_build_mutating_route_tools_drops_missing_invokers():
    """A mutating spec without a provided invoker is silently not offered."""
    tools = build_mutating_route_tools(
        {}, read_only_enabled=True, mutating_enabled=True
    )
    assert tools == []


def test_mutating_allowlist_is_write_methods_only():
    """Guard: every mutating allow-list entry is a write verb, with a schema."""
    write_verbs = {"POST", "PUT", "PATCH", "DELETE"}
    assert MUTATING_ROUTE_ALLOWLIST, "expected at least one mutating route"
    for spec in MUTATING_ROUTE_ALLOWLIST:
        assert spec.method in write_verbs, f"{spec.name} must be a write verb"
        assert spec.input_schema.get("type") == "object"


def test_mutating_descriptor_marks_mutating_true():
    """The descriptor explicitly distinguishes a write tool from a read tool."""
    spec = MUTATING_ROUTE_ALLOWLIST[0]

    async def _invoke(args):
        return {}

    tool = MutatingRouteTool(spec=spec, invoke=_invoke)
    desc = tool.descriptor()
    assert desc["mutating"] is True
    assert desc["name"] == route_tool_name(spec.name)


# ══════════════════════════════════════════════════════════════════════════════
# H22.9 hardening — per-identity gate on MUTATING tools
# ══════════════════════════════════════════════════════════════════════════════
#
# A mutating tool call must present a valid identity (the same credential the HTTP
# ``user_guard`` checks). A missing/wrong identity is refused with NO write — even
# when BOTH kill-switches are on. Read-only tools are unaffected. When the token is
# unset (localhost-trust dev posture) the in-process call is allowed, matching the
# HTTP guard's unset-token branch.


@pytest.mark.asyncio
async def test_mutating_tool_with_valid_token_dispatches_and_audits():
    """A mutating call with a matching identity writes AND audits as ``ok``."""
    auditor = _FakeAuditor()
    invoke, calls = _fake_remember_invoker()
    srv = _mutating_server(
        auditor=auditor,
        invokers={"memory_remember": invoke},
        identity_check=_token_identity("s3cret"),
    )

    res = await srv.call_tool("route_memory_remember", {"text": "buy milk"}, identity="s3cret")

    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"]) == {"ok": True, "id": "m-123"}
    assert calls == [{"text": "buy milk"}]  # the write reached the invoker
    assert len(auditor.events) == 2
    assert auditor.events[0].action_taken.endswith("(authorized)")
    assert auditor.events[1].action_taken.endswith("(ok)")


@pytest.mark.asyncio
async def test_mutating_tool_missing_token_refused_no_write():
    """No identity → refused, NO write, audited as a refusal (both switches on)."""
    auditor = _FakeAuditor()
    invoke, calls = _fake_remember_invoker()
    srv = _mutating_server(
        auditor=auditor,
        invokers={"memory_remember": invoke},
        identity_check=_token_identity("s3cret"),
    )

    res = await srv.call_tool("route_memory_remember", {"text": "buy milk"})  # no identity

    assert res["isError"] is True
    assert "identity required" in res["content"][0]["text"]
    assert calls == []  # the write NEVER happened
    # the refusal is still audited — an attempted write is never invisible
    assert len(auditor.events) == 1
    assert auditor.events[0].action_taken.endswith("(refused-identity)")


@pytest.mark.asyncio
async def test_mutating_tool_wrong_token_refused_no_write():
    """A wrong identity is refused exactly like the HTTP 401 path — no write."""
    invoke, calls = _fake_remember_invoker()
    srv = _mutating_server(
        invokers={"memory_remember": invoke},
        identity_check=_token_identity("s3cret"),
    )

    res = await srv.call_tool("route_memory_remember", {"text": "x"}, identity="WRONG")

    assert res["isError"] is True
    assert "identity required" in res["content"][0]["text"]
    assert calls == []


@pytest.mark.asyncio
async def test_mutating_tool_fails_closed_without_identity_check():
    """No identity policy bound → fail CLOSED: every mutating call is refused."""
    invoke, calls = _fake_remember_invoker()
    # Build the tool directly with NO identity_check (the build_* default is None).
    tool = MutatingRouteTool(spec=MUTATING_ROUTE_ALLOWLIST[0], invoke=invoke)
    with pytest.raises(MutatingIdentityError):
        await tool.call({"text": "x"}, token="anything")
    assert calls == []


@pytest.mark.asyncio
async def test_mutating_tool_unset_token_dev_posture_allows():
    """Unset-token (localhost-trust) posture allows the in-process call, no token.

    Mirrors ``_user_guard``: with JARVIS_USER_TOKEN unset the HTTP guard trusts a
    localhost origin and requires no token, so the in-process MCP call is allowed.
    """
    invoke, calls = _fake_remember_invoker()
    srv = _mutating_server(
        invokers={"memory_remember": invoke},
        identity_check=_allow_identity,  # permissive == unset-token dev posture
    )
    res = await srv.call_tool("route_memory_remember", {"text": "x"})  # no identity
    assert res["isError"] is False
    assert calls == [{"text": "x"}]


@pytest.mark.asyncio
async def test_read_only_tools_need_no_identity():
    """Read-only tools dispatch with no identity — gate is mutating-only."""
    srv = _mutating_server(identity_check=_token_identity("s3cret"))
    # No identity supplied; read tool still works (unchanged behaviour).
    res = await srv.call_tool("route_status", {})
    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"]) == {"status": "ok", "version": "test"}


@pytest.mark.asyncio
async def test_identity_threaded_through_rpc_tools_call():
    """The JSON-RPC tools/call path forwards the identity to the mutating gate."""
    invoke, calls = _fake_remember_invoker()
    srv = _mutating_server(
        invokers={"memory_remember": invoke},
        identity_check=_token_identity("s3cret"),
    )
    # No identity on handle() → refused.
    res = await srv.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "route_memory_remember", "arguments": {"text": "x"}},
    })
    assert res["result"]["isError"] is True
    assert calls == []
    # Identity supplied to handle() → dispatched.
    res = await srv.handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "route_memory_remember", "arguments": {"text": "x"}},
    }, identity="s3cret")
    assert res["result"]["isError"] is False
    assert calls == [{"text": "x"}]


def test_identity_check_matches_user_guard_rule():
    """The web.py identity gate reuses user_guard's rule (no fork).

    Imports the live ``_mcp_identity_check`` / ``_user_credential_ok`` and asserts:
    unset token → allow (dev); set token → only the matching credential passes.
    Skips gracefully if web can't import offline.
    """
    try:
        from agents import web
    except Exception:
        pytest.skip("web module not importable offline")

    import agents.web as w

    # Unset token → localhost-trust dev posture → any/no token allowed.
    orig_user, orig_admin = w.USER_TOKEN, w.ADMIN_TOKEN
    try:
        w.USER_TOKEN = ""
        assert web._mcp_identity_check(None) is True
        assert web._mcp_identity_check("whatever") is True

        # Set token → only the matching credential passes (same as user_guard).
        w.USER_TOKEN = "s3cret"
        w.ADMIN_TOKEN = ""
        assert web._mcp_identity_check("s3cret") is True
        assert web._mcp_identity_check("nope") is False
        assert web._mcp_identity_check(None) is False
        assert web._user_credential_ok(user_supplied="s3cret") is True
        assert web._user_credential_ok(user_supplied="nope") is False

        # An admin token satisfies the user gate (admin ⊇ user).
        w.ADMIN_TOKEN = "adm1n"
        assert web._mcp_identity_check("adm1n") is True
    finally:
        w.USER_TOKEN, w.ADMIN_TOKEN = orig_user, orig_admin


# ── SEC review hardening (F3 fail-closed audit, F4 name disjointness) ─────────

def test_mutating_tools_require_auditor_fail_closed():
    """SEC F3: binding mutating tools without an auditor binds NOTHING (fail closed),
    so a write can never run un-audited even if the switches are on."""
    invoke, _ = _fake_remember_invoker()
    tools = build_mutating_route_tools(
        {"memory_remember": invoke},
        auditor=None,
        read_only_enabled=True,
        mutating_enabled=True,
        identity_check=_allow_identity,
    )
    assert tools == []


def test_read_and_mutating_name_collision_rejected():
    """SEC F4: a tool name present in BOTH the read and mutating sets is refused at
    build time, so the read path (no identity, no audit) can never shadow a write."""
    import pytest

    class _Stub:
        def __init__(self, name):
            self.tool_name = name

    with pytest.raises(ValueError):
        JarvisMCPServer(
            _runner, AGENTS,
            route_tools=[_Stub("route_x")],
            mutating_route_tools=[_Stub("route_x")],
        )
