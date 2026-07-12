from types import SimpleNamespace

from agents.core.observability import capability_registry as cr
from agents.core.tool_rpc import ToolRPCServer


def test_tool_rpc_capability_id_is_opt_in_and_legacy_projection_is_unchanged():
    server = ToolRPCServer()
    server.register_tool("legacy", lambda args: args, description="Legacy tool")
    assert server.tools() == [
        {
            "name": "legacy",
            "gated": False,
            "description": "Legacy tool",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]

    server.register_tool(
        "mapped",
        lambda args: args,
        gated=True,
        capability_id="action:tool.rpc",
    )
    mapped = next(tool for tool in server.tools() if tool["name"] == "mapped")
    assert mapped["capability_id"] == "action:tool.rpc"


def test_live_tool_records_derive_from_tool_rpc_registration():
    server = ToolRPCServer()
    server.register_tool(
        "echo",
        lambda args: args,
        description="Return bounded values.",
        input_schema={"type": "object", "required": ["value"]},
        capability_id="tool:echo",
    )
    server.register_tool(
        "danger",
        lambda args: args,
        gated=True,
        description="Perform a gated mutation.",
        capability_id="tool:danger",
    )
    orch = SimpleNamespace(
        tool_rpc=server,
        components=SimpleNamespace(status={}),
        skills=SimpleNamespace(skills={}),
    )

    records = {record.id: record for record in cr.build_records(orch)}

    echo = records["tool:echo"]
    assert echo.kind == "tool"
    assert echo.state == cr.WIRED
    assert echo.description == "Return bounded values."
    assert echo.inputs == {"type": "object", "required": ["value"]}
    assert echo.risk == "read_only"
    assert echo.confidence == 0.0
    assert echo.detail == {"tool": "echo", "gated": False}
    assert records["tool:danger"].risk == "sensitive"
