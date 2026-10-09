"""Fresh profile authorization at ToolRPC dispatch, after an agent-loop await."""

from types import SimpleNamespace

import pytest

from agents.core.action_origin import bind_action_origin, current_action_origin, reset_action_origin
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.autonomy_coordinator import _TURN_TOOL_OFFER, AutonomyCoordinator
from agents.core.commands import Principal
from agents.core.job_toolsets import toolset_scope
from agents.core.llm.tool_protocol import ToolCall
from agents.core.orchestrator import bind_turn_principal, current_principal, reset_turn_principal
from agents.core.tool_rpc import ToolRPCServer
from agents.core.turn_approvals import open_turn_approvals, reset_turn_approvals


def _call(name="echo"):
    return ToolCall(id="call-1", name=name, raw_arguments="{}", arguments={})


def _runtime(server, profile):
    return AgentToolRuntime(
        server, enabled=lambda: True, tool_profile=profile, execution_profile=profile,
    )


@pytest.mark.asyncio
async def test_revocation_during_tool_started_await_blocks_before_preflight_or_handler():
    side_effects = []
    allowed = {"echo"}
    server = ToolRPCServer()

    def preflight(args):
        side_effects.append("preflight")
        return args

    async def handler(_args):
        side_effects.append("handler")
        return {"ran": True}

    server.register_tool("echo", handler, preflight=preflight)

    def profile(_agent_id, rows):
        return [row for row in rows if row["name"] in allowed], None

    async def sink(event):
        if event["event"] == "tool_started":
            allowed.clear()

    result, _content = await _runtime(server, profile)._execute_rpc(
        _call(), agent_id="nerva", event_sink=sink,
    )
    assert result == {"ok": False, "reason": "tool_not_allowed", "tool": "echo"}
    assert side_effects == []


@pytest.mark.asyncio
async def test_revoked_gated_tool_never_starts_preflight_or_approval_intake():
    effects = []
    allowed = {"image_generate"}
    server = ToolRPCServer()

    def preflight(args):
        effects.append("preflight")
        return args

    def intake(_actor, _args):
        effects.append("intake")
        return 17

    async def handler(_args):
        effects.append("handler")
        return {"ran": True}

    server.register_tool(
        "image_generate", handler, gated=True, trusted_execution=True,
        preflight=preflight, gated_intake=intake,
    )

    def profile(_agent_id, rows):
        return [row for row in rows if row["name"] in allowed], None

    async def sink(event):
        if event["event"] == "tool_started":
            allowed.clear()

    pending, token = open_turn_approvals()
    try:
        result, _ = await _runtime(server, profile)._execute_rpc(
            _call("image_generate"), agent_id="nerva", event_sink=sink,
        )
        assert result == {"ok": False, "reason": "tool_not_allowed", "tool": "image_generate"}
        assert effects == []
        assert pending == []
    finally:
        reset_turn_approvals(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "missing", "wrong_name"])
async def test_resolver_error_or_missing_selected_tool_denies_closed(failure):
    server = ToolRPCServer()
    ran = []

    async def handler(_args):
        ran.append(True)
        return {"ran": True}

    server.register_tool("echo", handler)

    def profile(_agent_id, rows):
        if failure == "exception":
            raise RuntimeError("profile store unavailable")
        if failure == "wrong_name":
            return [{**rows[0], "name": "other"}], None
        return [], None

    result, _content = await _runtime(server, profile)._execute_rpc(
        _call(), agent_id="nerva", event_sink=None,
    )
    assert result == {"ok": False, "reason": "tool_not_allowed", "tool": "echo"}
    assert ran == []


@pytest.mark.asyncio
async def test_job_scope_denies_first_and_principal_origin_reach_child_dispatch():
    server = ToolRPCServer()
    seen = []

    async def handler(_args):
        return {"ran": True}

    server.register_tool("echo", handler)

    def profile(_agent_id, rows):
        principal, origin = current_principal(), current_action_origin()
        seen.append((principal.channel, principal.admin, origin))
        return (rows if principal.admin and origin == "generated" else []), None

    runtime = _runtime(server, profile)
    principal_token = bind_turn_principal(Principal(channel="web", admin=True))
    origin_token = bind_action_origin("generated")
    try:
        with toolset_scope(frozenset()):
            blocked, _ = await runtime._execute_rpc(_call(), agent_id="nerva", event_sink=None)
        assert blocked["reason"] == "job_toolset_not_allowed" and seen == []
        with toolset_scope(frozenset({"echo"})):
            allowed, _ = await runtime._execute_rpc(_call(), agent_id="nerva", event_sink=None)
            assert allowed["ok"] is True
            reset_action_origin(origin_token)
            origin_token = bind_action_origin("inbound")
            refused, _ = await runtime._execute_rpc(_call(), agent_id="nerva", event_sink=None)
        assert refused["reason"] == "tool_not_allowed"
        assert seen == [("web", True, "generated"), ("web", True, "inbound")]
    finally:
        reset_action_origin(origin_token)
        reset_turn_principal(principal_token)


@pytest.mark.asyncio
async def test_model_payload_cannot_supply_check_to_direct_rpc_call():
    server = ToolRPCServer()

    async def handler(_args):
        return {"ran": True}

    server.register_tool("echo", handler)
    result = await server.handle({
        "tool": "echo", "args": {}, "_execution_check": lambda *_args: False,
    })
    assert result == {"ok": True, "tool": "echo", "result": {"ran": True}}


@pytest.mark.asyncio
async def test_coordinator_dispatch_uses_underlying_resolver_without_rewriting_h661_offer():
    orch = SimpleNamespace(
        agents={}, config=SimpleNamespace(agents={"jarvis": SimpleNamespace(tools=["echo"])}),
    )
    runtime = AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    assert runtime._execution_profile is not runtime._tool_profile
    seen = []

    async def handler(_args):
        seen.append(_TURN_TOOL_OFFER.get())
        return {"ran": True}

    orch.tool_rpc._tools["echo"]["handler"] = handler
    orch.tool_rpc._tools["time"]["handler"] = handler
    token = _TURN_TOOL_OFFER.set(frozenset({"file_read"}))
    try:
        result, _ = await runtime._execute_rpc(
            _call(), agent_id="jarvis", event_sink=None,
        )
        assert result["ok"] is True
        denied, _ = await runtime._execute_rpc(
            _call("time"), agent_id="jarvis", event_sink=None,
        )
        assert denied == {"ok": False, "reason": "tool_not_allowed", "tool": "time"}
        assert seen == [frozenset({"file_read"})]
        assert _TURN_TOOL_OFFER.get() == frozenset({"file_read"})
    finally:
        _TURN_TOOL_OFFER.reset(token)
