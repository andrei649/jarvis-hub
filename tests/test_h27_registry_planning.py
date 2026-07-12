from types import SimpleNamespace

import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.observability import capability_registry as cr
from agents.core.tool_rpc import ToolRPCServer


class _Backend:
    supports_tools = True

    def __init__(self):
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append(kwargs)
        return ToolTurn(content="done")


class _ScriptedBackend(_Backend):
    def __init__(self, turns):
        super().__init__()
        self.turns = list(turns)

    async def generate_tool_turn(self, **kwargs):
        self.calls.append(kwargs)
        return self.turns.pop(0)


def _snapshot(*records):
    return {"capabilities": list(records)}


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


def test_tool_rpc_refuses_invalid_or_duplicate_capability_identity():
    server = ToolRPCServer()
    with pytest.raises(ValueError, match="capability_id"):
        server.register_tool("blank", lambda args: args, capability_id="")
    with pytest.raises(ValueError, match="capability_id"):
        server.register_tool("wrong", lambda args: args, capability_id=123)

    server.register_tool("one", lambda args: args, capability_id="tool:shared")
    with pytest.raises(ValueError, match="already registered"):
        server.register_tool("two", lambda args: args, capability_id="tool:shared")


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


def test_tool_implementation_does_not_duplicate_an_existing_action_record():
    server = ToolRPCServer()
    server.register_tool("write", lambda args: args, capability_id="action:tool.rpc")
    orch = SimpleNamespace(
        tool_rpc=server,
        components=SimpleNamespace(status={}),
        skills=SimpleNamespace(skills={}),
    )

    matching = [record for record in cr.build_records(orch) if record.id == "action:tool.rpc"]

    assert len(matching) == 1
    assert matching[0].kind == "action"


@pytest.mark.asyncio
async def test_registry_planning_off_preserves_legacy_tool_metadata():
    server = ToolRPCServer()
    server.register_tool(
        "echo",
        lambda args: args,
        description="Legacy description.",
        input_schema={"type": "object", "required": ["legacy"]},
        capability_id="tool:echo",
    )
    backend = _Backend()
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        registry_enabled=lambda: False,
        capability_snapshot=lambda: _snapshot(
            {
                "id": "tool:echo",
                "state": "wired",
                "description": "Registry description.",
                "inputs": {"type": "object", "required": ["registry"]},
                "risk": "read_only",
                "confidence": 0.0,
            }
        ),
    )

    assert await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="p") == "done"
    spec = backend.calls[0]["tools"][0]
    assert spec.description == "Legacy description."
    assert spec.input_schema["required"] == ["legacy"]


@pytest.mark.asyncio
async def test_registry_planning_filters_and_enriches_live_capabilities():
    server = ToolRPCServer()
    server.register_tool("good", lambda args: args, capability_id="tool:good")
    server.register_tool("seam", lambda args: args, capability_id="tool:seam")
    server.register_tool("missing", lambda args: args, capability_id="tool:missing")
    backend = _Backend()
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        registry_enabled=lambda: True,
        capability_snapshot=lambda: _snapshot(
            {
                "id": "tool:good",
                "state": "wired",
                "description": "Use the verified data source.",
                "inputs": {"type": "object", "required": ["query"]},
                "risk": "read_only",
                "confidence": 0.0,
            },
            {
                "id": "tool:seam",
                "state": "seam",
                "description": "Not live.",
                "inputs": {"type": "object"},
                "risk": "sensitive",
                "confidence": 0.0,
            },
        ),
    )

    assert await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="p") == "done"
    assert [tool.name for tool in backend.calls[0]["tools"]] == ["good"]
    spec = backend.calls[0]["tools"][0]
    assert spec.input_schema == {"type": "object", "required": ["query"]}
    assert "Use the verified data source." in spec.description
    assert "risk=read_only" in spec.description
    assert "readiness=wired" in spec.description
    assert "confidence=0.000" in spec.description


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [lambda: _snapshot(), lambda: {"bad": []}, lambda: 1])
async def test_registry_planning_no_match_refuses_before_provider_or_tool_call(provider):
    server = ToolRPCServer()
    executed = []
    server.register_tool(
        "orphan",
        lambda args: executed.append(args),
        capability_id="tool:orphan",
    )
    backend = _Backend()
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        registry_enabled=lambda: True,
        capability_snapshot=provider,
    )

    answer = await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="p")

    assert "no live registered capability" in answer.lower()
    assert not backend.calls
    assert not executed


@pytest.mark.asyncio
async def test_provider_cannot_execute_a_tool_filtered_out_by_registry():
    server = ToolRPCServer()
    executed = []

    async def handler(args):
        executed.append(args)
        return {"bad": True}

    server.register_tool("good", handler, capability_id="tool:good")
    server.register_tool("seam", handler, capability_id="tool:seam")
    backend = _ScriptedBackend(
        [
            ToolTurn(
                tool_calls=(
                    ToolCall(id="c1", name="seam", raw_arguments="{}", arguments={}),
                )
            ),
            ToolTurn(content="refused filtered tool"),
        ]
    )
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        registry_enabled=lambda: True,
        capability_snapshot=lambda: _snapshot(
            {
                "id": "tool:good",
                "state": "wired",
                "description": "Good.",
                "inputs": {"type": "object"},
                "risk": "read_only",
                "confidence": 0.0,
            },
            {
                "id": "tool:seam",
                "state": "seam",
                "description": "Not live.",
                "inputs": {"type": "object"},
                "risk": "sensitive",
                "confidence": 0.0,
            },
        ),
    )

    answer = await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="p")

    assert answer == "refused filtered tool"
    assert not executed
    tool_message = backend.calls[1]["messages"][-1]
    assert "tool_not_allowed" in tool_message["content"]


@pytest.mark.asyncio
async def test_tool_rpc_audit_failure_is_swallowed_and_logged(caplog):
    class BrokenAudit:
        def record(self, **kwargs):
            raise RuntimeError("audit offline")

    async def echo(args):
        return args

    server = ToolRPCServer(audit=BrokenAudit())
    server.register_tool("echo", echo)
    with caplog.at_level("DEBUG", logger="jarvis.tool_rpc"):
        result = await server.handle({"tool": "echo", "args": {"value": "ok"}})

    assert result["ok"] is True
    assert "audit sink failed" in caplog.text
