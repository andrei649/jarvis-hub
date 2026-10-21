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

from agents.core.llm.responses import ResponsesBackend
from agents.core.llm.tool_dialects import (
    anthropic_tools,
    gemini_function_declarations,
    gemini_schema,
)
from agents.core.llm.tool_protocol import ToolSpec
from agents.core.llm.xai import XAI_PROFILE, XAIBackend
from agents.core.mcp.client import MCPManager, MCPServer, MCPTool
from agents.core.mcp.schema_normalize import (
    MAX_SCHEMA_DEPTH,
    PROVIDER_NAME_MAX,
    PROVIDER_NAME_PREFIX,
    mcp_provider_name,
    normalize_mcp_input_schema,
)

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


def test_existing_defs_win_over_legacy_definitions():
    out = normalize_mcp_input_schema({
        "type": "object",
        "properties": {"a": {"$ref": "#/definitions/A"}},
        "$defs": {"A": {"type": "integer"}},
        "definitions": {"A": {"type": "string"}, "B": {"type": "boolean"}},
    })
    assert out["$defs"] == {"A": {"type": "integer"}, "B": {"type": "boolean"}}


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


def _bridge_spec() -> ToolSpec:
    mgr = MCPManager()
    srv = MCPServer("docs", command="true")
    srv.tools.append(MCPTool("search", "Search docs", PYDANTIC_SCHEMA, "docs"))
    mgr.register(srv)
    [row] = mgr.model_tools()
    return ToolSpec(name=row["name"], description=row["description"], input_schema=row["input_schema"])


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


def test_gemini_repairs_a_raw_schema_without_the_registration_pass():
    # The Gemini path is safe on its own: a raw nullable union no longer yields
    # anyOf:[{type:string},{}] with default:null.
    [decl] = gemini_function_declarations([ToolSpec("t", "", {
        "type": "object",
        "properties": {"s": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
                       "r": {"$ref": "#/definitions/R"}},
        "definitions": {"R": {"type": "object", "properties": {"k": {"type": "integer"}}}},
    })])
    assert decl["parameters"]["properties"]["s"] == {"type": "string"}
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
        srv = MCPServer(server, command="true")
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
    srv = MCPServer("docs", command="true")
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
