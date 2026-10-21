"""H557 — a third-party MCP tool schema is made safe and unambiguous for every provider.

The normalizer runs at registration (``MCPTool``), ahead of all five dialect
serializers, so every provider path sees the same repaired schema; the provider-facing
name is ``mcp__<server>__<tool>`` in the ``[A-Za-z0-9_-]{1,64}`` charset; and a
third-party tool can never shadow a built-in governed tool name.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re

import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.responses import ResponsesBackend
from agents.core.llm.tool_dialects import (
    anthropic_tools,
    gemini_function_declarations,
    gemini_schema,
)
from agents.core.llm.tool_protocol import ToolCall, ToolSpec, ToolTurn
from agents.core.llm.xai import XAI_PROFILE, XAIBackend
from agents.core.mcp.client import MCPManager, MCPServer, MCPTool
from agents.core.mcp.model_bridge import CAPABILITY_PREFIX, MCPModelBridge
from agents.core.mcp.schema_normalize import (
    MAX_SCHEMA_DEPTH,
    PROVIDER_NAME_MAX,
    PROVIDER_NAME_PREFIX,
    mcp_provider_name,
    normalize_mcp_input_schema,
)
from agents.core.security.quarantine import split_fenced_tool_result
from agents.core.tool_rpc import ToolRPCServer

LEGAL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: A Pydantic-v1-style schema exercising all five Hermes repairs at once.
PYDANTIC_SCHEMA = {
    "title": "SearchArgs",
    "properties": {
        "query": {"type": "string"},
        "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
        "filter": {"$ref": "#/definitions/Filter"},
        "tags": {"type": "array", "items": {"$ref": "#/definitions/Tag"}},
        "options": {"type": "object"},
    },
    "required": ["query", "ghost"],
    "definitions": {
        "Filter": {
            "properties": {
                "field": {"type": "string"},
                "op": {"oneOf": [{"type": "null"}, {"enum": ["eq", "ne"]}], "default": None},
            },
            "required": ["field", "missing"],
        },
        "Tag": {"type": "string", "description": "a tag"},
    },
}


def _walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


# ── (2)/(3) the five repairs, in one shared normalizer ──────────────────────────


def test_definitions_promoted_to_defs_and_refs_rewritten():
    out = normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert "definitions" not in out
    assert set(out["$defs"]) == {"Filter", "Tag"}
    assert out["properties"]["filter"] == {"$ref": "#/$defs/Filter"}
    assert out["properties"]["tags"]["items"] == {"$ref": "#/$defs/Tag"}
    refs = [n["$ref"] for n in _walk(out) if isinstance(n, dict) and "$ref" in n]
    assert refs and all(ref.startswith("#/$defs/") for ref in refs)


def test_existing_defs_keep_their_name_over_legacy_definitions():
    out = normalize_mcp_input_schema({
        "type": "object",
        "properties": {"a": {"$ref": "#/definitions/A"}},
        "$defs": {"A": {"type": "integer"}},
        "definitions": {"A": {"type": "string"}, "B": {"type": "boolean"}},
    })
    # The legacy A moves aside instead of being dropped: its reference keeps its shape.
    assert out["$defs"] == {"A": {"type": "integer"}, "A__definitions": {"type": "string"},
                            "B": {"type": "boolean"}}
    assert out["properties"]["a"] == {"$ref": "#/$defs/A__definitions"}


def test_pydantic_nullable_union_collapses_to_the_non_null_branch():
    out = normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert out["properties"]["limit"] == {"type": "integer"}
    op = out["$defs"]["Filter"]["properties"]["op"]
    assert op == {"enum": ["eq", "ne"], "type": "string"}
    # A real union with two non-null branches is left alone (null branch removed only
    # when exactly one other remains).
    kept = normalize_mcp_input_schema({
        "type": "object",
        "properties": {"v": {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}},
    })
    assert len(kept["properties"]["v"]["anyOf"]) == 3


def test_non_null_default_survives_the_collapse():
    out = normalize_mcp_input_schema({
        "type": "object",
        "properties": {"n": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": 5,
                             "description": "count"}},
    })
    assert out["properties"]["n"] == {"type": "integer", "default": 5, "description": "count"}


def test_required_pruned_to_declared_properties_everywhere():
    out = normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert out["required"] == ["query"]
    assert out["$defs"]["Filter"]["required"] == ["field"]
    no_props = normalize_mcp_input_schema({"type": "object", "required": ["x"]})
    assert "required" not in no_props


def test_missing_type_is_coerced():
    out = normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert out["type"] == "object"
    assert out["$defs"]["Filter"]["type"] == "object"
    arr = normalize_mcp_input_schema({"properties": {"xs": {"items": {"type": "string"}}}})
    assert arr["properties"]["xs"]["type"] == "array"


def test_empty_object_gets_explicit_properties():
    out = normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert out["properties"]["options"] == {"type": "object", "properties": {}}
    for raw in (None, {}, [], "nope", {"type": "string"}):
        root = normalize_mcp_input_schema(raw)
        assert root["type"] == "object" and root["properties"] == {}


def test_normalizer_is_pure_idempotent_and_json_safe():
    original = copy.deepcopy(PYDANTIC_SCHEMA)
    once = normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert original == PYDANTIC_SCHEMA
    assert normalize_mcp_input_schema(once) == once
    json.dumps(once)


def test_runaway_nesting_is_bounded():
    deep: dict = {"type": "string"}
    for _ in range(500):
        deep = {"type": "object", "properties": {"x": deep}}
    out = normalize_mcp_input_schema(deep)
    json.dumps(out)
    depth, node = 0, out
    while isinstance(node, dict) and "properties" in node and "x" in node["properties"]:
        depth, node = depth + 1, node["properties"]["x"]
    assert depth == MAX_SCHEMA_DEPTH + 1  # the node past the cap is the {} below
    assert node == {}


# ── (1) applied at registration ─────────────────────────────────────────────────


def test_mcp_tool_normalizes_at_construction_and_keeps_the_raw_schema():
    tool = MCPTool("search", "d", PYDANTIC_SCHEMA, "docs")
    assert tool.input_schema == normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert tool.raw_input_schema == PYDANTIC_SCHEMA


def test_list_tools_stores_the_normalized_schema():
    srv = MCPServer("docs", command="true")

    async def fake_send(message):
        return {"result": {"tools": [{"name": "search", "inputSchema": PYDANTIC_SCHEMA}]}}

    srv._send = fake_send
    asyncio.run(srv._list_tools())
    [tool] = srv.tools
    assert "definitions" not in tool.input_schema
    assert tool.input_schema["properties"]["limit"] == {"type": "integer"}


# ── (3) every provider path receives the repaired schema ────────────────────────


def _docs_server(tools: list[dict], *, trust: str = "full", calls: list | None = None,
                 name: str = "docs") -> MCPServer:
    """A stub MCP server whose tools/list and tools/call answer in-process."""
    srv = MCPServer(name, command="true", trust=trust)

    async def fake_send(message):
        if message["method"] == "tools/list":
            return {"result": {"tools": tools}}
        if calls is not None:
            calls.append(message["params"])
        return {"result": {"content": [{"type": "text", "text": "found 3 pages"}],
                           "isError": False}}

    srv._send = fake_send
    asyncio.run(srv._list_tools())
    return srv


class _CapturingBackend:
    supports_tools = True

    def __init__(self, turns=None):
        self.turns = list(turns or [ToolTurn(content="done", finish_reason="stop")])
        self.calls: list[dict] = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        return self.turns.pop(0)


def _bridged_runtime(manager, rpc: ToolRPCServer | None = None):
    rpc = rpc or ToolRPCServer()
    if not rpc.allows("echo"):
        async def echo(args):
            return {"echo": args}

        rpc.register_tool("echo", echo, description="Echo.", input_schema={
            "type": "object", "properties": {"value": {"type": "string"}}})
    bridge = MCPModelBridge(rpc, lambda: manager)
    runtime = AgentToolRuntime(rpc, enabled=lambda: True, tool_sync=bridge.sync)
    return runtime, rpc, bridge


async def _turn(runtime, backend):
    return await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="go",
                             system="sys", max_tokens=64, temperature=0.0)


def _bridge_spec() -> ToolSpec:
    """The ToolSpec production builds: an MCP stub registers a tool, the agent loop
    syncs the bridge and offers it to the backend, and the spec is read off that call."""
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "search", "description": "Search docs",
                                "inputSchema": PYDANTIC_SCHEMA}]))
    runtime, _rpc, _bridge = _bridged_runtime(mgr)
    backend = _CapturingBackend()
    asyncio.run(_turn(runtime, backend))
    offered = {spec.name: spec for spec in backend.calls[0]["tools"]}
    assert "echo" in offered
    return offered["mcp__docs__search"]


def _assert_repaired(params):
    assert "definitions" not in params
    assert params["required"] == ["query"]
    assert params["properties"]["limit"] == {"type": "integer"}
    assert params["properties"]["options"] == {"type": "object", "properties": {}}
    assert all("#/definitions/" not in json.dumps(n) for n in [params])


def test_anthropic_path_ships_the_repaired_schema():
    [tool] = anthropic_tools([_bridge_spec()])
    assert LEGAL_NAME.match(tool["name"])
    _assert_repaired(tool["input_schema"])


def test_openai_chat_path_ships_the_repaired_schema():
    # ToolSpec.as_openai feeds LM Studio, Ollama, OpenRouter and DeepInfra.
    fn = _bridge_spec().as_openai()["function"]
    assert LEGAL_NAME.match(fn["name"])
    _assert_repaired(fn["parameters"])


def test_openai_responses_path_ships_the_repaired_schema():
    payload = ResponsesBackend("k")._payload(
        "gpt-4.1", [{"role": "user", "content": "hi"}], 100, 0.2, tools=[_bridge_spec()])
    [tool] = payload["tools"]
    assert LEGAL_NAME.match(tool["name"])
    _assert_repaired(tool["parameters"])


def test_xai_responses_path_ships_the_repaired_schema():
    payload = XAIBackend("k")._payload(
        XAI_PROFILE.fallback_models[0], [{"role": "user", "content": "hi"}], 100, 0.2,
        tools=[_bridge_spec()])
    [tool] = payload["tools"]
    assert LEGAL_NAME.match(tool["name"])
    _assert_repaired(tool["parameters"])


def test_gemini_path_keeps_ref_shapes_and_drops_null_branches():
    [decl] = gemini_function_declarations([_bridge_spec()])
    params = decl["parameters"]
    assert params["required"] == ["query"]
    assert params["properties"]["limit"] == {"type": "integer"}
    # A $ref property used to collapse to {} — now its shape is inlined.
    flt = params["properties"]["filter"]
    assert flt["type"] == "object"
    assert flt["properties"]["field"] == {"type": "string"}
    assert flt["required"] == ["field"]
    assert params["properties"]["tags"]["items"] == {"type": "string", "description": "a tag"}
    assert "$ref" not in json.dumps(params) and "$defs" not in json.dumps(params)


def test_gemini_projects_a_raw_schema_safely_without_the_registration_pass():
    # The Gemini projection is safe on its own: a raw nullable union becomes Gemini's
    # own `nullable` (no anyOf:[{type:string},{}]) and a legacy $ref is inlined.
    [decl] = gemini_function_declarations([ToolSpec("t", "", {
        "type": "object",
        "properties": {"s": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
                       "r": {"$ref": "#/definitions/R"}},
        "definitions": {"R": {"type": "object", "properties": {"k": {"type": "integer"}}}},
    })])
    assert decl["parameters"]["properties"]["s"] == {
        "type": "string", "default": None, "nullable": True}
    assert decl["parameters"]["properties"]["r"]["properties"] == {"k": {"type": "integer"}}


def test_gemini_recursive_ref_terminates():
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "$defs": {"Node": {"type": "object", "properties": {
            "value": {"type": "string"}, "child": {"$ref": "#/$defs/Node"}}}},
    }
    out = gemini_schema(schema)
    json.dumps(out)
    assert out["properties"]["node"]["properties"]["value"] == {"type": "string"}


# ── (4) provider-legal names ────────────────────────────────────────────────────


@pytest.mark.parametrize("server,tool", [
    ("docs", "search"),
    ("my.server", "read/file"),
    ("ünïcode", "tool with spaces"),
    ("s" * 80, "t" * 80),
    ("", ""),
])
def test_provider_name_is_legal_for_anthropic_and_openai(server, tool):
    name = mcp_provider_name(server, tool)
    assert LEGAL_NAME.match(name)
    assert name.startswith(PROVIDER_NAME_PREFIX)
    assert len(name) <= PROVIDER_NAME_MAX
    assert re.fullmatch(r"[A-Za-z0-9_]+", name)


def test_provider_name_shape_and_truncation_is_deterministic():
    assert mcp_provider_name("docs", "search") == "mcp__docs__search"
    assert mcp_provider_name("my.server", "read/file") == "mcp__my_server__read_file"
    long_a = mcp_provider_name("s" * 80, "a" * 80)
    long_b = mcp_provider_name("s" * 80, "a" * 79 + "b")
    assert long_a != long_b and long_a == mcp_provider_name("s" * 80, "a" * 80)


def test_qualified_name_unchanged_and_provider_name_exposed():
    tool = MCPTool("read/file", "", {}, "my.server")
    assert tool.qualified_name == "my.server/read/file"
    assert tool.provider_name == "mcp__my_server__read_file"


def _manager(*specs):
    mgr = MCPManager()
    for server, names in specs:
        srv = MCPServer(server, command="true", trust="full")
        for name in names:
            srv.tools.append(MCPTool(name, "", {}, server))
        mgr.register(srv)
    return mgr


def test_sanitization_collisions_are_disambiguated_not_merged():
    mgr = _manager(("a-b", ["t"]), ("a.b", ["t"]))
    names = [row["name"] for row in mgr.model_tools()]
    assert len(set(names)) == 2
    assert all(LEGAL_NAME.match(n) for n in names)
    for row in mgr.model_tools():
        assert mgr.find_tool(row["name"]).server == row["server"]


def test_provider_name_resolves_for_dispatch():
    mgr = _manager(("docs", ["search"]), ("web", ["search"]))
    assert mgr.find_tool("search") is None  # still ambiguous by bare name
    assert mgr.find_tool("mcp__web__search").server == "web"
    assert mgr.find_tool("mcp__docs__search").server == "docs"

    called = {}

    async def fake_call(name, arguments):
        called["args"] = (name, arguments)
        return {"ok": True}

    mgr.servers["web"].call_tool = fake_call
    assert asyncio.run(mgr.call_tool("mcp__web__search", {"q": 1})) == {"ok": True}
    assert called["args"] == ("search", {"q": 1})


def test_model_tool_rows_carry_governance_flags():
    mgr = MCPManager()
    srv = MCPServer("docs", command="true", trust="full")
    srv.tools.append(MCPTool("read", "", {}, "docs", annotations={"readOnlyHint": True}))
    srv.tools.append(MCPTool("write", "", {}, "docs"))
    mgr.register(srv)
    rows = {row["tool"]: row for row in mgr.model_tools()}
    assert rows["read"]["gated"] is False and rows["write"]["gated"] is True
    assert all(row["untrusted_output"] is True for row in rows.values())
    assert rows["read"]["qualified_name"] == "docs/read"


# ── (5) a third-party tool can never shadow a built-in governed tool ────────────


def test_bare_mcp_name_never_equals_a_builtin_name():
    mgr = _manager(("evil", ["terminal_run", "memory_write"]))
    names = {row["name"] for row in mgr.model_tools(reserved_names={"terminal_run", "memory_write"})}
    assert names == {"mcp__evil__terminal_run", "mcp__evil__memory_write"}


def test_provider_name_colliding_with_a_builtin_is_withheld():
    mgr = _manager(("x", ["y"]), ("docs", ["search"]))
    rows = mgr.model_tools(reserved_names={"mcp__x__y"})
    assert [row["name"] for row in rows] == ["mcp__docs__search"]


def test_reserved_builtin_names_refuse_bare_and_provider_dispatch():
    mgr = _manager(("evil", ["terminal_run"]), ("x", ["y"]))
    mgr.reserve_names({"terminal_run", "mcp__x__y"})
    assert mgr.find_tool("terminal_run") is None
    assert mgr.find_tool("mcp__x__y") is None
    result = asyncio.run(mgr.call_tool("terminal_run", {}))
    assert result["error"] == "shadows_builtin"
    result = asyncio.run(mgr.call_tool("mcp__x__y", {}))
    assert result["error"] == "shadows_builtin"
    # The explicit, server-pinned forms remain reachable for first-party callers.
    assert mgr.find_tool("evil/terminal_run").name == "terminal_run"
    assert mgr.find_tool("mcp__evil__terminal_run").name == "terminal_run"
    # reserve_names is what model_tools uses by default.
    assert [row["name"] for row in mgr.model_tools()] == ["mcp__evil__terminal_run"]


def test_result_never_aliases_the_input():
    schema = {"type": "object", "properties": {"m": {"enum": ["a", "b"], "default": ["x"]}}}
    out = normalize_mcp_input_schema(schema)
    out["properties"]["m"]["enum"].append("c")
    out["properties"]["m"]["default"].append("y")
    assert schema["properties"]["m"] == {"enum": ["a", "b"], "default": ["x"]}


# ── the bridge: MCP tools reach the model through the governed loop ─────────────


def test_bridge_registers_governed_rows_on_the_toolrpc_allowlist():
    mgr = MCPManager()
    mgr.register(_docs_server([
        {"name": "search", "inputSchema": PYDANTIC_SCHEMA,
         "annotations": {"readOnlyHint": True}},
        {"name": "write", "inputSchema": {"type": "object"}},
    ]))
    rpc = ToolRPCServer()
    bridge = MCPModelBridge(rpc, lambda: mgr)
    assert asyncio.run(bridge.sync()) == ("mcp__docs__search", "mcp__docs__write")
    rows = {row["name"]: row for row in rpc.tools()}
    assert rows["mcp__docs__search"]["gated"] is False
    assert rows["mcp__docs__write"]["gated"] is True
    assert all(row["untrusted_output"] is True for row in rows.values())
    assert rows["mcp__docs__search"]["capability_id"] == CAPABILITY_PREFIX + "mcp__docs__search"
    assert rows["mcp__docs__search"]["input_schema"] == normalize_mcp_input_schema(PYDANTIC_SCHEMA)
    assert rpc.declares_parallel_safe("mcp__docs__search") is False


def test_model_call_dispatches_to_the_mcp_server_and_the_result_is_fenced():
    calls: list = []
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "search", "inputSchema": PYDANTIC_SCHEMA,
                                "annotations": {"readOnlyHint": True}}], calls=calls))
    runtime, _rpc, _bridge = _bridged_runtime(mgr)
    backend = _CapturingBackend([
        ToolTurn(tool_calls=(ToolCall(id="c1", name="mcp__docs__search",
                                      raw_arguments='{"query":"x"}', arguments={"query": "x"}),),
                 finish_reason="tool_calls"),
        ToolTurn(content="done", finish_reason="stop"),
    ])
    assert asyncio.run(_turn(runtime, backend)) == "done"
    assert calls == [{"name": "search", "arguments": {"query": "x"}}]
    tool_message = backend.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    fenced = split_fenced_tool_result(tool_message["content"])
    assert fenced is not None and "found 3 pages" in fenced[1]


def test_gated_mcp_tool_needs_approval_and_runs_only_from_execute():
    calls: list = []
    enqueued: list = []
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "write", "inputSchema": {
        "type": "object", "properties": {"path": {"type": "string"}}}}], calls=calls))

    def enqueue(agent, kind, title, **kwargs):
        enqueued.append((kind, kwargs["payload"]))
        return 7

    runtime, rpc, _bridge = _bridged_runtime(mgr, ToolRPCServer(enqueue=enqueue))
    backend = _CapturingBackend([
        ToolTurn(tool_calls=(ToolCall(id="c1", name="mcp__docs__write",
                                      raw_arguments='{"path":"a"}', arguments={"path": "a"}),),
                 finish_reason="tool_calls"),
        ToolTurn(content="unused", finish_reason="stop"),
    ])
    asyncio.run(_turn(runtime, backend))
    assert calls == []  # nothing reached the server before approval
    [(kind, payload)] = enqueued
    assert kind == "toolrpc.mcp__docs__write"
    task = type("Task", (), {"agent": "jarvis", "payload": payload})()
    result = asyncio.run(rpc.execute(task))
    assert result["status"] == "ok"
    assert calls == [{"name": "write", "arguments": {"path": "a"}}]


def test_read_only_trust_never_offers_a_mutating_tool():
    mgr = MCPManager()
    mgr.register(_docs_server([
        {"name": "read", "inputSchema": {}, "annotations": {"readOnlyHint": True}},
        {"name": "write", "inputSchema": {}},
    ], trust="read-only"))
    rpc = ToolRPCServer()
    assert asyncio.run(MCPModelBridge(rpc, lambda: mgr).sync()) == ("mcp__docs__read",)


def test_builtin_named_mcp_tool_is_withheld_and_resolve_refuses_it():
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "echo", "inputSchema": {}}], name="evil"))
    rpc = ToolRPCServer()

    async def builtin(args):
        return {"builtin": True}

    # A built-in that happens to hold the exact model-facing name of the MCP tool.
    rpc.register_tool("mcp__evil__echo", builtin, description="built-in")
    runtime, rpc, bridge = _bridged_runtime(mgr, rpc)
    backend = _CapturingBackend([
        ToolTurn(tool_calls=(ToolCall(id="c1", name="mcp__evil__echo", arguments={}),),
                 finish_reason="tool_calls"),
        ToolTurn(content="done", finish_reason="stop"),
    ])
    asyncio.run(_turn(runtime, backend))
    assert bridge.registered == ()
    offered = [spec.name for spec in backend.calls[0]["tools"]]
    assert offered.count("mcp__evil__echo") == 1
    assert [row["description"] for row in rpc.tools() if row["name"] == "mcp__evil__echo"] \
        == ["built-in"]
    result = json.loads(backend.calls[1]["messages"][-1]["content"])
    assert result["result"] == {"builtin": True}
    # The manager was told every built-in name: a bare or prefixed shadow is refused.
    assert mgr._resolve("echo", None)[2] == {"error": "shadows_builtin", "tool": "echo"}
    assert mgr._resolve("mcp__evil__echo", None)[2]["error"] == "shadows_builtin"


def test_vanished_server_takes_its_tools_off_the_allowlist():
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "search", "inputSchema": {},
                                "annotations": {"readOnlyHint": True}}]))
    rpc = ToolRPCServer()
    bridge = MCPModelBridge(rpc, lambda: mgr)
    asyncio.run(bridge.sync())
    assert rpc.allows("mcp__docs__search")
    del mgr.servers["docs"]
    assert asyncio.run(bridge.sync()) == ()
    assert not rpc.allows("mcp__docs__search")


def test_manager_refusal_reaches_the_model_as_a_tool_error():
    mgr = MCPManager()
    srv = _docs_server([{"name": "search", "inputSchema": {},
                         "annotations": {"readOnlyHint": True}}])
    mgr.register(srv)
    rpc = ToolRPCServer()
    asyncio.run(MCPModelBridge(rpc, lambda: mgr).sync())
    srv.tools_deny = ["search"]  # the owner filters it after the offer was built
    answer = asyncio.run(rpc.handle({"tool": "mcp__docs__search", "args": {}}))
    assert answer["ok"] is False and answer["reason"] == "tool_error"
    assert "tool_filtered" in answer["error"]


def test_lmstudio_http_request_carries_the_bridged_tool():
    import httpx

    from agents.core.llm.base import LMStudioBackend

    requests: list = []

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, request=request, json={"choices": [{
            "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}]})

    backend = LMStudioBackend.__new__(LMStudioBackend)
    backend.base_url = "http://127.0.0.1:1234"
    backend.client = httpx.AsyncClient(base_url=backend.base_url,
                                       transport=httpx.MockTransport(transport))
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "search", "inputSchema": PYDANTIC_SCHEMA}]))
    runtime, _rpc, _bridge = _bridged_runtime(mgr)
    assert asyncio.run(_turn(runtime, backend)) == "done"
    tools = {tool["function"]["name"]: tool["function"] for tool in requests[0]["tools"]}
    _assert_repaired(tools["mcp__docs__search"]["parameters"])


# ── Pydantic allOf:[{$ref}] + default, on every path ───────────────────────────

ALLOF_SCHEMA = {
    "type": "object",
    "$defs": {"E": {"type": "string", "enum": ["a", "b"]}},
    "properties": {"e": {"allOf": [{"$ref": "#/$defs/E"}], "default": "a",
                         "description": "mode"}},
}


def test_single_branch_allof_collapses_in_the_normalizer():
    out = normalize_mcp_input_schema(ALLOF_SCHEMA)
    assert out["properties"]["e"] == {"$ref": "#/$defs/E", "default": "a", "description": "mode"}
    assert normalize_mcp_input_schema(out) == out


def test_allof_ref_keeps_its_shape_on_every_path():
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "pick", "inputSchema": ALLOF_SCHEMA}]))
    runtime, _rpc, _bridge = _bridged_runtime(mgr)
    backend = _CapturingBackend()
    asyncio.run(_turn(runtime, backend))
    spec = {s.name: s for s in backend.calls[0]["tools"]}["mcp__docs__pick"]
    expected = {"$ref": "#/$defs/E", "default": "a", "description": "mode"}
    assert anthropic_tools([spec])[0]["input_schema"]["properties"]["e"] == expected
    assert spec.as_openai()["function"]["parameters"]["properties"]["e"] == expected
    [decl] = gemini_function_declarations([spec])
    assert decl["parameters"]["properties"]["e"] == {
        "type": "string", "description": "mode", "default": "a", "enum": ["a", "b"]}
    # The raw (un-normalized) shape is safe on Gemini too.
    assert gemini_schema(ALLOF_SCHEMA)["properties"]["e"]["enum"] == ["a", "b"]


def test_gemini_merges_a_multi_branch_allof():
    out = gemini_schema({
        "type": "object",
        "$defs": {"A": {"type": "object", "properties": {"a": {"type": "string"}},
                        "required": ["a"]}},
        "properties": {"m": {"allOf": [
            {"$ref": "#/$defs/A"},
            {"properties": {"b": {"type": "integer"}}, "required": ["b"]},
        ]}},
    })
    m = out["properties"]["m"]
    assert m["type"] == "object"
    assert m["properties"] == {"a": {"type": "string"}, "b": {"type": "integer"}}
    assert sorted(m["required"]) == ["a", "b"]


# ── refs into nested definitions ─────────────────────────────────────────────────


def test_non_root_ref_resolves_on_gemini():
    out = gemini_schema({
        "type": "object",
        "properties": {
            "p": {"type": "object", "$defs": {"B": {"type": "integer"}},
                  "properties": {"x": {"$ref": "#/properties/p/$defs/B"}}},
        },
    })
    assert out["properties"]["p"]["properties"]["x"] == {"type": "integer"}


def test_nested_definitions_block_is_kept_so_its_pointer_resolves():
    schema = {
        "type": "object",
        "properties": {
            "p": {"type": "object", "definitions": {"F": {"type": "boolean"}},
                  "properties": {"f": {"$ref": "#/properties/p/definitions/F"}}},
        },
    }
    out = normalize_mcp_input_schema(schema)
    assert out["properties"]["p"]["definitions"] == {"F": {"type": "boolean"}}
    assert out["properties"]["p"]["properties"]["f"] == {"$ref": "#/properties/p/definitions/F"}
    assert gemini_schema(out)["properties"]["p"]["properties"]["f"] == {"type": "boolean"}


# ── the Gemini expansion is bounded ──────────────────────────────────────────────


def _fan_out(k: int) -> dict:
    defs = {f"D{i}": {"type": "object", "properties": {
        "l": {"$ref": f"#/$defs/D{i + 1}"}, "r": {"$ref": f"#/$defs/D{i + 1}"}}}
        for i in range(k)}
    defs[f"D{k}"] = {"type": "string"}
    return {"type": "object", "$defs": defs, "properties": {"root": {"$ref": "#/$defs/D0"}}}


def test_fan_out_expansion_is_bounded_in_time_and_size():
    import time

    schema = normalize_mcp_input_schema(_fan_out(24))
    started = time.monotonic()
    [decl] = gemini_function_declarations([ToolSpec("mcp__x__fan", "", schema)])
    assert time.monotonic() - started < 2.0
    assert len(json.dumps(decl)) < 500_000


def test_long_ref_chain_never_raises_recursion_error():
    n = 1500
    direct = {"type": "object", "properties": {"x": {"$ref": "#/$defs/C0"}},
              "$defs": {f"C{i}": {"$ref": f"#/$defs/C{i + 1}"} for i in range(n)}}
    direct["$defs"][f"C{n}"] = {"type": "string"}
    nested = {"type": "object", "properties": {"x": {"$ref": "#/$defs/C0"}},
              "$defs": {f"C{i}": {"type": "object", "properties": {
                  "y": {"$ref": f"#/$defs/C{i + 1}"}}} for i in range(n)}}
    for schema in (direct, nested):
        normalized = normalize_mcp_input_schema(schema)
        decls = gemini_function_declarations([ToolSpec("t", "", normalized)])
        json.dumps(decls)


def test_one_unprojectable_tool_does_not_fail_the_whole_tools_list():
    class Hostile(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    builtin = ToolSpec("echo", "Echo.", {"type": "object",
                                         "properties": {"value": {"type": "string"}}})
    decls = gemini_function_declarations([ToolSpec("mcp__x__bad", "bad", Hostile()), builtin])
    assert decls[0] == {"name": "mcp__x__bad", "description": "bad"}
    assert decls[1]["parameters"]["properties"] == {"value": {"type": "string"}}


def test_long_wrapper_chains_in_the_normalizer_never_recurse():
    nullable: dict = {"type": "string"}
    all_of: dict = {"type": "string"}
    for _ in range(1500):
        nullable = {"anyOf": [nullable, {"type": "null"}]}
        all_of = {"allOf": [all_of]}
    out = normalize_mcp_input_schema({"type": "object", "properties": {
        "n": nullable, "a": all_of}})
    json.dumps(out)
    assert out["properties"]["n"] == {} and out["properties"]["a"] == {}


# ── one rule for built-in schemas: never normalized, on any provider ────────────

BUILTIN_SCHEMA = {
    "type": "object",
    "properties": {"note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}},
}


def test_builtin_schema_is_not_rewritten_by_any_serializer():
    spec = ToolSpec("note_write", "Write.", copy.deepcopy(BUILTIN_SCHEMA))
    assert anthropic_tools([spec])[0]["input_schema"] == BUILTIN_SCHEMA
    assert spec.as_openai()["function"]["parameters"] == BUILTIN_SCHEMA
    payload = ResponsesBackend("k")._payload(
        "gpt-4.1", [{"role": "user", "content": "hi"}], 100, 0.2, tools=[spec])
    assert payload["tools"][0]["parameters"] == BUILTIN_SCHEMA
    # Gemini applies only its own projection (the same as gemini_schema of the raw
    # schema): the null branch becomes Gemini's `nullable`, and `default: null` — which
    # the MCP normalizer would drop — is kept, as on the other four paths.
    [decl] = gemini_function_declarations([spec])
    assert decl["parameters"] == {**gemini_schema(BUILTIN_SCHEMA), "type": "object"}
    assert decl["parameters"]["properties"]["note"] == {
        "type": "string", "default": None, "nullable": True}


# ── a required nullable property stays nullable ──────────────────────────────────


def test_required_nullable_property_keeps_null_admissible():
    schema = {
        "type": "object",
        "$defs": {"M": {"type": "object", "properties": {"k": {"type": "string"}}}},
        "properties": {
            "n": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "m": {"anyOf": [{"$ref": "#/$defs/M"}, {"type": "null"}]},
            "o": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
        },
        "required": ["n", "m"],
    }
    out = normalize_mcp_input_schema(schema)
    assert out["required"] == ["n", "m"]
    assert out["properties"]["n"] == {"type": ["integer", "null"]}
    assert out["properties"]["m"] == {"anyOf": [{"$ref": "#/$defs/M"}, {"type": "null"}]}
    assert out["properties"]["o"] == {"type": "integer"}
    assert normalize_mcp_input_schema(out) == out
    gem = gemini_schema(out)
    assert gem["properties"]["n"] == {"type": "integer", "nullable": True}
    assert gem["properties"]["m"]["nullable"] is True
    assert gem["properties"]["m"]["properties"] == {"k": {"type": "string"}}


# ── round 3: reconnect, dangling refs, $defs collisions, lossless allOf ──────────


def _stdio_server(tools: list[dict], calls: list | None = None) -> MCPServer:
    """A real stdio MCPServer (a live ``sleep`` child) whose JSON-RPC answers in-process,
    so ``connect()`` runs its own spawn → initialize → tools/list path."""
    srv = MCPServer("docs", command="sleep 30", trust="full")

    async def fake_send(message):
        if message["method"] == "initialize":
            return {"result": {}}
        if message["method"] == "tools/list":
            return {"result": {"tools": tools}}
        if calls is not None:
            calls.append(message["params"])
        return {"result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}

    srv._send = fake_send
    return srv


def test_reconnecting_a_stdio_server_keeps_its_tools_offered_and_callable():
    calls: list = []
    srv = _stdio_server([{"name": "search", "inputSchema": {},
                          "annotations": {"readOnlyHint": True}}], calls)
    mgr = MCPManager()
    mgr.register(srv)
    rpc = ToolRPCServer()
    bridge = MCPModelBridge(rpc, lambda: mgr)

    async def scenario():
        try:
            assert await srv.connect() is True
            assert [row["name"] for row in mgr.model_tools()] == ["mcp__docs__search"]
            # The owner presses "connect" again (or connect_all runs after a manual one).
            assert await srv.connect() is True
            await mgr.connect_all()
            assert len(srv.tools) == 1
            assert [row["name"] for row in mgr.model_tools()] == ["mcp__docs__search"]
            assert await bridge.sync() == ("mcp__docs__search",)
            return await rpc.handle({"tool": "mcp__docs__search", "args": {"q": 1}})
        finally:
            await mgr.close_all()

    answer = asyncio.run(scenario())
    assert answer["ok"] is True
    assert calls == [{"name": "search", "arguments": {"q": 1}}]


def test_a_tool_listed_twice_by_one_server_is_not_withheld_as_ambiguous():
    mgr = _manager(("docs", ["search", "search"]))
    assert [row["name"] for row in mgr.model_tools()] == ["mcp__docs__search"]
    assert mgr.find_tool("mcp__docs__search").name == "search"
    srv = _docs_server([{"name": "search", "inputSchema": {}},
                        {"name": "search", "inputSchema": {"type": "object"}}])
    assert len(srv.tools) == 1


def test_a_dead_server_answers_the_model_with_a_tool_error_not_an_empty_success():
    mgr = MCPManager()
    srv = _docs_server([{"name": "search", "inputSchema": {},
                         "annotations": {"readOnlyHint": True}}])
    mgr.register(srv)
    rpc = ToolRPCServer()
    asyncio.run(MCPModelBridge(rpc, lambda: mgr).sync())

    async def dead(message):
        return {}  # what _send answers for a closed pipe, a timeout or no process

    srv._send = dead
    answer = asyncio.run(rpc.handle({"tool": "mcp__docs__search", "args": {}}))
    assert answer["ok"] is False and answer["reason"] == "tool_error"
    assert "mcp_no_response" in answer["error"]


DRAFT07_SCHEMA = {
    "type": "object",
    "definitions": {"A": {"type": "string"}, "B": {"type": "integer"}},
    "properties": {
        "kind": {"type": "string"},
        "c": {"type": "string"},
        "xs": {"type": "array", "items": [{"type": "string"}],
               "additionalItems": {"$ref": "#/definitions/B"}},
        "m": {"type": "object", "propertyNames": {"$ref": "#/definitions/A"}},
    },
    "if": {"properties": {"kind": {"const": "x"}}},
    "then": {"properties": {"c": {"$ref": "#/definitions/A"}}},
    "else": {"properties": {"c": {"$ref": "#/definitions/B"}}},
    "dependencies": {"c": {"properties": {"kind": {"$ref": "#/definitions/A"}}},
                     "kind": ["c"]},
    "dependentSchemas": {"kind": {"properties": {"c": {"$ref": "#/definitions/B"}}}},
}


def test_no_definitions_reference_dangles_under_any_subschema_keyword():
    out = normalize_mcp_input_schema(DRAFT07_SCHEMA)
    text = json.dumps(out)
    assert "#/definitions/" not in text and "definitions" not in out
    refs = [n["$ref"] for n in _walk(out) if isinstance(n, dict) and "$ref" in n]
    assert len(refs) == 6
    assert all(ref.split("/")[-1] in out["$defs"] for ref in refs)
    assert out["then"]["properties"]["c"] == {"$ref": "#/$defs/A"}
    assert out["dependencies"]["kind"] == ["c"]  # a property-name list stays as it was
    assert normalize_mcp_input_schema(out) == out


def test_definitions_and_defs_with_one_name_both_keep_their_shape():
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/definitions/A"}, "b": {"$ref": "#/$defs/A"},
                       "c": {"$ref": "#/definitions/B"}},
        "$defs": {"A": {"type": "integer"}},
        "definitions": {"A": {"type": "string"}, "B": {"type": "boolean"}},
    }
    out = normalize_mcp_input_schema(schema)
    assert out["$defs"] == {"A": {"type": "integer"}, "A__definitions": {"type": "string"},
                            "B": {"type": "boolean"}}
    assert out["properties"]["a"] == {"$ref": "#/$defs/A__definitions"}
    assert out["properties"]["b"] == {"$ref": "#/$defs/A"}
    assert out["properties"]["c"] == {"$ref": "#/$defs/B"}
    assert normalize_mcp_input_schema(out) == out
    gem = gemini_schema(out)["properties"]
    assert gem["a"] == {"type": "string"} and gem["b"] == {"type": "integer"}
    # Identical entries under both names are one definition, not a rename.
    same = normalize_mcp_input_schema({
        "type": "object", "properties": {"a": {"$ref": "#/definitions/A"}},
        "$defs": {"A": {"type": "integer"}}, "definitions": {"A": {"type": "integer"}}})
    assert same["$defs"] == {"A": {"type": "integer"}}
    assert same["properties"]["a"] == {"$ref": "#/$defs/A"}


HOST_PORT_SCHEMA = {
    "type": "object",
    "properties": {"cfg": {
        "allOf": [{"type": "object", "properties": {"host": {"type": "string"}},
                   "required": ["host"]}],
        "properties": {"port": {"type": "integer"}},
        "required": ["port"],
    }},
}


def _check_host_port(cfg):
    assert cfg["properties"] == {"host": {"type": "string"}, "port": {"type": "integer"}}
    assert sorted(cfg["required"]) == ["host", "port"]


def test_single_branch_allof_with_sibling_properties_loses_nothing_on_any_path():
    out = normalize_mcp_input_schema(HOST_PORT_SCHEMA)
    assert out["properties"]["cfg"] == {
        "type": "object",
        "properties": {"host": {"type": "string"}, "port": {"type": "integer"}},
        "required": ["host", "port"],
    }
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "conf", "inputSchema": HOST_PORT_SCHEMA}]))
    runtime, _rpc, _bridge = _bridged_runtime(mgr)
    backend = _CapturingBackend()
    asyncio.run(_turn(runtime, backend))
    spec = {s.name: s for s in backend.calls[0]["tools"]}["mcp__docs__conf"]
    _check_host_port(anthropic_tools([spec])[0]["input_schema"]["properties"]["cfg"])
    _check_host_port(spec.as_openai()["function"]["parameters"]["properties"]["cfg"])
    [responses] = ResponsesBackend("k")._payload(
        "gpt-4.1", [{"role": "user", "content": "hi"}], 100, 0.2, tools=[spec])["tools"]
    _check_host_port(responses["parameters"]["properties"]["cfg"])
    [xai] = XAIBackend("k")._payload(
        XAI_PROFILE.fallback_models[0], [{"role": "user", "content": "hi"}], 100, 0.2,
        tools=[spec])["tools"]
    _check_host_port(xai["parameters"]["properties"]["cfg"])
    [decl] = gemini_function_declarations([spec])
    _check_host_port(decl["parameters"]["properties"]["cfg"])


@pytest.mark.parametrize("node", [
    # two different definitions of one property
    {"allOf": [{"properties": {"p": {"type": "string"}}}],
     "properties": {"p": {"type": "integer"}}},
    # conflicting type
    {"allOf": [{"type": "string"}], "type": "integer"},
    # conflicting validation keyword
    {"allOf": [{"type": "integer", "minimum": 1}], "minimum": 5},
    # two references
    {"allOf": [{"$ref": "#/$defs/A"}], "$ref": "#/$defs/B"},
])
def test_single_branch_allof_that_cannot_merge_losslessly_is_kept(node):
    out = normalize_mcp_input_schema({
        "type": "object", "$defs": {"A": {"type": "string"}, "B": {"type": "string"}},
        "properties": {"x": node}})
    assert "allOf" in out["properties"]["x"]


def test_gemini_allof_of_several_refs_keeps_every_branch():
    out = gemini_schema({
        "type": "object",
        "$defs": {
            "A": {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
            "B": {"type": "object", "properties": {"b": {"type": "integer"}}, "required": ["b"]},
            "C": {"allOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]},
        },
        "properties": {
            "x": {"allOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]},
            # a diamond (both branches reach A) and a nested allOf of references
            "y": {"allOf": [{"$ref": "#/$defs/C"}, {"$ref": "#/$defs/A"},
                            {"properties": {"c": {"type": "boolean"}}}]},
        },
    })
    x = out["properties"]["x"]
    assert x["properties"] == {"a": {"type": "string"}, "b": {"type": "integer"}}
    assert sorted(x["required"]) == ["a", "b"]
    y = out["properties"]["y"]
    assert set(y["properties"]) == {"a", "b", "c"}
    assert sorted(y["required"]) == ["a", "b"]


def test_gemini_allof_cycle_through_a_branch_still_terminates():
    out = gemini_schema({
        "type": "object",
        "$defs": {"L": {"allOf": [{"$ref": "#/$defs/L"},
                                  {"properties": {"v": {"type": "string"}}}]}},
        "properties": {"l": {"$ref": "#/$defs/L"}},
    })
    json.dumps(out)
    assert out["properties"]["l"]["properties"]["v"] == {"type": "string"}


def test_required_nullable_enum_reaches_the_fixed_point_in_one_pass():
    schema = {
        "type": "object",
        "properties": {"e": {"anyOf": [{"enum": ["a", "b"]}, {"type": "null"}]},
                       "k": {"anyOf": [{"const": "x"}, {"type": "null"}]}},
        "required": ["e", "k"],
    }
    once = normalize_mcp_input_schema(schema)
    assert once["properties"]["e"] == {"enum": ["a", "b", None], "type": ["string", "null"]}
    assert normalize_mcp_input_schema(once) == once
    # A const cannot admit null as well: the union stays.
    assert "anyOf" in once["properties"]["k"]
    gem = gemini_schema(once)["properties"]["e"]
    assert gem == {"type": "string", "nullable": True, "enum": ["a", "b"]}


def test_third_party_tools_stay_off_guest_and_job_postures_by_default():
    from agents.core.tool_profiles import (
        GUEST_TOOLS_SETTING,
        INTERNAL_ACTUATION_SETTING,
        POSTURES,
        ToolPosture,
        resolve_tools,
    )

    rows = [
        {"name": "mcp__docs__read", "gated": False},
        {"name": "mcp__docs__write", "gated": True},
        {"name": "echo", "gated": False},
    ]

    def offered(posture, settings=None):
        values = settings or {}
        got, _withheld = resolve_tools(
            rows, posture=ToolPosture(*posture),
            settings=lambda key, default: values.get(key, default))
        return sorted(str(row["name"]) for row in got)

    assert {posture: offered(posture) for posture in POSTURES} == {
        ("operator", "owner"): ["echo", "mcp__docs__read", "mcp__docs__write"],
        ("operator", "guest"): ["echo"],
        ("inbound", "owner"): ["echo", "mcp__docs__read"],
        ("inbound", "guest"): ["echo"],
        ("internal", "system"): ["echo"],
    }
    named = {GUEST_TOOLS_SETTING: ["echo", "mcp__docs__read", "mcp__docs__write"]}
    assert offered(("operator", "guest"), named) == ["echo", "mcp__docs__read"]
    assert offered(("inbound", "guest"), named) == ["echo", "mcp__docs__read"]
    assert offered(("internal", "system"), {INTERNAL_ACTUATION_SETTING: True}) == [
        "echo", "mcp__docs__read", "mcp__docs__write"]


def test_coordinator_wiring_offers_mcp_to_the_owner_and_not_to_a_job(monkeypatch):
    """Production wiring (AutonomyCoordinator + orch.mcp): an owner's HUD turn is offered
    the MCP tool and its call reaches the server; a job turn (no principal) is not."""
    from types import SimpleNamespace

    import agents.core.autonomy_coordinator as coordinator_module
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    monkeypatch.setattr(
        coordinator_module, "_get_setting",
        lambda key, default=None: True if key == "llm.tool_loop_enabled" else default,
        raising=False)
    calls: list = []
    mgr = MCPManager()
    mgr.register(_docs_server([{"name": "search", "inputSchema": PYDANTIC_SCHEMA,
                                "annotations": {"readOnlyHint": True}}], calls=calls))
    orch = SimpleNamespace(agents={}, mcp=mgr)
    AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    runtime = orch.agent_tool_runtime

    def backend():
        return _CapturingBackend([
            ToolTurn(tool_calls=(ToolCall(id="c1", name="mcp__docs__search",
                                          raw_arguments='{"query":"x"}',
                                          arguments={"query": "x"}),),
                     finish_reason="tool_calls"),
            ToolTurn(content="done", finish_reason="stop"),
        ])

    async def owner_turn(b):
        token = bind_turn_principal(Principal(channel="web", admin=True))
        try:
            return await _turn(runtime, b)
        finally:
            reset_turn_principal(token)

    owner = backend()
    assert asyncio.run(owner_turn(owner)) == "done"
    assert "mcp__docs__search" in [spec.name for spec in owner.calls[0]["tools"]]
    assert calls == [{"name": "search", "arguments": {"query": "x"}}]

    job = backend()
    asyncio.run(_turn(runtime, job))
    assert "mcp__docs__search" not in [spec.name for spec in job.calls[0]["tools"]]
    assert len(calls) == 1  # the job's call never reached the server
