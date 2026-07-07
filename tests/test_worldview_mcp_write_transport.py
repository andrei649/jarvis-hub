"""Tests for the JARVIS -> WorldView MCP write transport (#169 / M3.5)."""

from __future__ import annotations

import pytest

from agents.core.kernel import Action, Capability, Decision, Verdict
from agents.core.mcp.worldview_write import (
    RECONSTRUCT_EVENT_SCOPE,
    WATCH_AOI_SCOPE,
    WORLDVIEW_MCP_WRITE_KIND,
    WorldViewMCPWriteClient,
)
from agents.core.plugin_gate import PermissionGate
from agents.core.security.worldview_mcp import verify_capability

_SECRET = "shared-worldview-secret"


class _FakeMCP:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict | None = None):
        self.calls.append((name, dict(arguments or {})))
        return {"content": [{"type": "text", "text": "ok"}]}


class _GrantKernel:
    def __init__(self):
        self.calls: list[tuple[Action, Capability | None]] = []

    def __call__(self, action: Action, capability: Capability | None = None):
        self.calls.append((action, capability))
        return Decision(Verdict.GRANT, reason="granted")


class _DenyKernel:
    def __call__(self, action: Action, capability: Capability | None = None):
        return Decision(Verdict.DENY, reason="kernel_nope")


class _QueueKernel:
    def __call__(self, action: Action, capability: Capability | None = None):
        return Decision(Verdict.QUEUE, reason="needs_review", card={"requires_approval": True})


def _client(monkeypatch, *, agent_id="argus", kernel=None, secret=_SECRET, mcp=None):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    return WorldViewMCPWriteClient(
        permission_gate=PermissionGate(),
        mcp=mcp or _FakeMCP(),
        agent_id=agent_id,
        kernel=kernel or _GrantKernel(),
        secret=secret,
        capability_token_id="agent-capability-token",
        auto_connect=False,
    )


async def test_watch_aoi_mints_scoped_token_after_plugin_and_kernel(monkeypatch):
    mcp = _FakeMCP()
    kernel = _GrantKernel()
    client = _client(monkeypatch, kernel=kernel, mcp=mcp)

    out = await client.watch_aoi("hormuz", "recon_due", lead=900)

    assert out["status"] == "ok"
    assert mcp.calls and mcp.calls[0][0] == "watch_aoi"
    args = mcp.calls[0][1]
    assert args["aoiId"] == "hormuz"
    assert args["rule"] == "recon_due"
    assert args["lead"] == 900
    assert verify_capability(args["token"], WATCH_AOI_SCOPE, _SECRET).ok

    action, capability = kernel.calls[0]
    assert action.kind == WORLDVIEW_MCP_WRITE_KIND
    assert action.agent == "argus"
    assert action.payload["tool"] == "watch_aoi"
    assert action.payload["risk_tier"] == 2
    assert "token" not in action.payload
    assert capability == Capability(token_id="agent-capability-token", name="plugin:worldview")


async def test_reconstruct_event_mints_reconstruct_scope(monkeypatch):
    mcp = _FakeMCP()
    client = _client(monkeypatch, mcp=mcp)

    out = await client.reconstruct_event(100.0, 220.0, bbox="20,40,30,45", layers=["ais", "tle"])

    assert out["status"] == "ok"
    assert mcp.calls[0][0] == "reconstruct_event"
    args = mcp.calls[0][1]
    assert args["from"] == 100.0
    assert args["to"] == 220.0
    assert args["bbox"] == "20,40,30,45"
    assert args["layers"] == ["ais", "tle"]
    assert verify_capability(args["token"], RECONSTRUCT_EVENT_SCOPE, _SECRET).ok


async def test_plugin_denial_blocks_before_kernel_or_mcp(monkeypatch):
    mcp = _FakeMCP()
    kernel = _GrantKernel()
    client = _client(monkeypatch, agent_id="frigga", kernel=kernel, mcp=mcp)

    out = await client.watch_aoi("hormuz", "recon_due")

    assert out == {"status": "forbidden", "plugin": "worldview", "reason": "plugin_denied"}
    assert kernel.calls == []
    assert mcp.calls == []


async def test_kernel_must_be_enabled_before_mcp_write(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    mcp = _FakeMCP()
    client = WorldViewMCPWriteClient(
        permission_gate=PermissionGate(),
        mcp=mcp,
        agent_id="argus",
        kernel=_GrantKernel(),
        secret=_SECRET,
        auto_connect=False,
    )

    out = await client.watch_aoi("hormuz", "recon_due")

    assert out == {"status": "blocked", "reason": "kernel_required", "tool": "watch_aoi"}
    assert mcp.calls == []


@pytest.mark.parametrize(
    ("kernel", "expected"),
    [
        (_DenyKernel(), {"status": "blocked", "reason": "kernel_nope", "tool": "watch_aoi"}),
        (
            _QueueKernel(),
            {
                "status": "queued",
                "reason": "approval_required",
                "tool": "watch_aoi",
                "card": {"requires_approval": True},
            },
        ),
    ],
)
async def test_kernel_denies_or_queues_without_mcp_side_effect(monkeypatch, kernel, expected):
    mcp = _FakeMCP()
    client = _client(monkeypatch, kernel=kernel, mcp=mcp)

    out = await client.watch_aoi("hormuz", "recon_due")

    assert out == expected
    assert mcp.calls == []


async def test_missing_mcp_secret_blocks_without_mint_or_mcp(monkeypatch):
    mcp = _FakeMCP()
    client = _client(monkeypatch, secret="", mcp=mcp)

    out = await client.reconstruct_event(100.0, 200.0)

    assert out == {
        "status": "blocked",
        "reason": "missing_worldview_mcp_secret",
        "tool": "reconstruct_event",
    }
    assert mcp.calls == []
