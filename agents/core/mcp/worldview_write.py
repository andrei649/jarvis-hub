"""Governed JARVIS -> WorldView MCP write transport (#169 / M3.5).

The normal :mod:`agents.core.plugins.worldview` bridge is intentionally read-only.
This module owns the separate write path: plugin gate + Action Kernel + scoped
WorldView MCP HMAC token, then stdio MCP tool call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agents.core.kernel import Action, Capability, Verdict, kernel_enabled
from agents.core.mcp.client import MCPManager, MCPServer
from agents.core.security.worldview_mcp import mint_capability

WORLDVIEW_PLUGIN = "worldview"
WORLDVIEW_MCP_SERVER = "worldview"
WORLDVIEW_MCP_WRITE_KIND = "worldview.mcp.write"
WATCH_AOI_SCOPE = "worldview:watch"
RECONSTRUCT_EVENT_SCOPE = "worldview:reconstruct"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_mcp_cwd() -> str:
    return os.environ.get("WORLDVIEW_MCP_CWD", str(_repo_root() / "worldview" / "mcp"))


def _default_mcp_command() -> str:
    return os.environ.get("WORLDVIEW_MCP_COMMAND", "node dist/server.js")


class WorldViewMCPWriteClient:
    """Small governed wrapper for WorldView MCP write tools."""

    def __init__(
        self,
        *,
        permission_gate,
        mcp: MCPManager | Any | None = None,
        agent_id: str = "argus",
        kernel=None,
        secret: str | None = None,
        capability_token_id: str = "",
        auto_connect: bool = True,
        server_name: str = WORLDVIEW_MCP_SERVER,
        ttl_s: int = 300,
        require_broker_capability: bool = True,
    ):
        self.permission_gate = permission_gate
        self.mcp = mcp or MCPManager()
        self.agent_id = agent_id
        self.kernel = kernel
        self.secret = secret
        self.capability_token_id = capability_token_id
        self.auto_connect = auto_connect
        self.server_name = server_name
        self.ttl_s = ttl_s
        self.require_broker_capability = require_broker_capability

    @classmethod
    def from_orchestrator(cls, orch, agent_id: str = "argus") -> WorldViewMCPWriteClient:
        from agents.core.kernel.binding import make_action_kernel

        agent_tokens = getattr(orch, "agent_capabilities", {}) or {}
        has_broker = getattr(orch, "capabilities", None) is not None
        return cls(
            permission_gate=getattr(orch, "permission_gate", None),
            mcp=getattr(orch, "mcp", None),
            agent_id=agent_id,
            kernel=make_action_kernel(orch),
            capability_token_id=agent_tokens.get(agent_id, ""),
            require_broker_capability=has_broker,
        )

    async def watch_aoi(
        self,
        aoi_id: str,
        rule: str,
        *,
        lead: float | None = None,
        origin: str = "generated",
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"aoiId": aoi_id, "rule": rule}
        if lead is not None:
            args["lead"] = lead
        return await self._call_write_tool("watch_aoi", WATCH_AOI_SCOPE, args, origin=origin)

    async def reconstruct_event(
        self,
        from_t: float,
        to_t: float,
        *,
        bbox: str = "",
        layers: list[str] | None = None,
        origin: str = "generated",
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"from": from_t, "to": to_t}
        if bbox:
            args["bbox"] = bbox
        if layers:
            args["layers"] = list(layers)
        return await self._call_write_tool(
            "reconstruct_event",
            RECONSTRUCT_EVENT_SCOPE,
            args,
            origin=origin,
        )

    async def _call_write_tool(
        self,
        tool: str,
        scope: str,
        arguments: dict[str, Any],
        *,
        origin: str,
    ) -> dict[str, Any]:
        plugin_block = self._plugin_block()
        if plugin_block is not None:
            return plugin_block

        kernel_block = self._kernel_block(tool, arguments, origin=origin)
        if kernel_block is not None:
            return kernel_block

        secret = self._secret()
        if not secret:
            return {"status": "blocked", "reason": "missing_worldview_mcp_secret", "tool": tool}

        token = mint_capability([scope], secret, ttl_s=self.ttl_s, sub=self.agent_id)
        mcp_args = {**arguments, "token": token}

        connect_block = await self._ensure_worldview_server(secret, tool)
        if connect_block is not None:
            return connect_block

        result = await self.mcp.call_tool(tool, mcp_args)
        return {"status": "ok", "tool": tool, "result": result}

    def _plugin_block(self) -> dict[str, Any] | None:
        gate = self.permission_gate
        if gate is None:
            return {"status": "forbidden", "plugin": WORLDVIEW_PLUGIN, "reason": "plugin_gate_unavailable"}
        try:
            allowed = bool(gate.check_call(WORLDVIEW_PLUGIN, self.agent_id))
        except Exception:
            allowed = False
        if not allowed:
            return {"status": "forbidden", "plugin": WORLDVIEW_PLUGIN, "reason": "plugin_denied"}
        return None

    def _kernel_block(self, tool: str, arguments: dict[str, Any], *, origin: str) -> dict[str, Any] | None:
        if not kernel_enabled():
            return {"status": "blocked", "reason": "kernel_required", "tool": tool}
        if self.kernel is None:
            return {"status": "blocked", "reason": "kernel_unavailable", "tool": tool}
        if self.require_broker_capability and not self.capability_token_id:
            return {"status": "blocked", "reason": "capability_token_required", "tool": tool}

        payload = {
            "tool": tool,
            "args_keys": sorted(arguments),
            "risk_tier": 2,
        }
        decision = self.kernel(
            Action(
                kind=WORLDVIEW_MCP_WRITE_KIND,
                agent=self.agent_id,
                title=f"WorldView MCP write: {tool}",
                payload=payload,
                origin=origin,
            ),
            capability=Capability(token_id=self.capability_token_id, name=f"plugin:{WORLDVIEW_PLUGIN}"),
        )
        if decision.verdict is Verdict.DENY:
            return {"status": "blocked", "reason": decision.reason or "kernel_denied", "tool": tool}
        if decision.verdict is Verdict.QUEUE:
            return {
                "status": "queued",
                "reason": "approval_required",
                "tool": tool,
                "card": decision.card,
            }
        return None

    def _secret(self) -> str:
        raw = self.secret if self.secret is not None else os.environ.get("WORLDVIEW_MCP_SECRET", "")
        return str(raw or "").strip()

    async def _ensure_worldview_server(self, secret: str, tool: str) -> dict[str, Any] | None:
        if not self.auto_connect or not isinstance(self.mcp, MCPManager):
            return None

        server = self.mcp.servers.get(self.server_name)
        if server is None:
            server = MCPServer(
                self.server_name,
                transport="stdio",
                command=_default_mcp_command(),
                cwd=_default_mcp_cwd(),
                env={"WORLDVIEW_MCP_SECRET": secret},
            )
            self.mcp.register(server)
        elif isinstance(server, MCPServer):
            server.env["WORLDVIEW_MCP_SECRET"] = secret

        if not server.tools:
            try:
                connected = await server.connect()
            except Exception:
                connected = False
            if not connected:
                return {"status": "unavailable", "reason": "mcp_connect_failed", "tool": tool}
        return None
