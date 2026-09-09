"""Server-owned intake remains behind ToolRPC registration and admissibility."""
from types import SimpleNamespace

import pytest

from agents.core.automation_contracts import ContractDecision
from agents.core.tool_rpc import ToolRPCServer


@pytest.mark.parametrize("gated,trusted,callback", [
    (False, False, lambda actor, args: 1),
    (True, False, lambda actor, args: 1),
    (False, True, lambda actor, args: 1),
    (True, True, "not-callable"),
])
def test_custom_intake_requires_server_owned_trusted_gated_registration(gated, trusted, callback):
    with pytest.raises(ValueError):
        ToolRPCServer().register_tool("tool", lambda args: None, gated=gated,
                                      trusted_execution=trusted, gated_intake=callback)


@pytest.mark.asyncio
async def test_contract_refusal_precedes_custom_intake(monkeypatch):
    from agents.core import tool_rpc

    calls = []
    server = ToolRPCServer().register_tool(
        "image_generate", lambda args: None, gated=True, trusted_execution=True,
        gated_intake=lambda actor, args: calls.append((actor, args)),
    )
    monkeypatch.setattr(tool_rpc, "TOOL_RPC_CALL_CONTRACT", SimpleNamespace(
        evaluate=lambda *args, **kwargs: ContractDecision(
            "tool_rpc_call", False, True, reason="target_mismatch",
        ),
    ))
    response = await server.handle({"tool": "image_generate", "args": {"prompt": "boat"}})
    assert response["reason"] == "target_mismatch"
    assert calls == []


@pytest.mark.asyncio
async def test_request_cannot_select_intake_or_publish_it_as_metadata():
    calls = []
    server = ToolRPCServer().register_tool(
        "image_generate", lambda args: None, gated=True, trusted_execution=True,
        gated_intake=lambda actor, args: calls.append((actor, args)) or 17,
    )
    response = await server.handle({"tool": "image_generate", "gated_intake": "attacker",
                                    "actor": "attacker", "args": {"prompt": "boat"}}, actor="ultron")
    assert response["task_id"] == 17
    assert calls == [("ultron", {"prompt": "boat"})]
    assert "gated_intake" not in server.tools()[0]
