"""
server.py — H10.5 MCP Server Mode.

Exposes Jarvis agents as **governed** Model Context Protocol tools so any MCP
client (Claude Desktop, Cursor, another Jarvis) can call a Jarvis agent as a
tool. This is the inverse of ``client.py`` (which consumes external MCP tools).

Design goals:
  * **Transport-agnostic core** — ``handle()`` dispatches a JSON-RPC 2.0 message
    (initialize / tools/list / tools/call). A stdio loop or the HTTP/SSE route
    in web.py just feed messages in and write results out.
  * **Governed** — only allow-listed agents are exposed; calls route through the
    orchestrator (so guardrails + permission gate still apply). LAN-only by
    default (a deployment/bind concern surfaced in ``status()``).
  * **Offline-testable** — the runner is injected, so tests need no orchestrator.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, Optional

from agents.core.mcp.route_tools import (
    ROUTE_TOOL_PREFIX,
    MutatingIdentityError,
    MutatingRouteTool,
    RouteTool,
    normalize_result,
)

PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "jarvis-hub"
SERVER_VERSION = "1.0"

# JSON-RPC error codes
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Agent runner: ``async (agent_id, text) -> str``
AgentRunner = Callable[[str, str], Awaitable[str]]


def _tool_name(agent_id: str) -> str:
    return f"ask_{agent_id}"


class JarvisMCPServer:
    def __init__(
        self,
        runner: AgentRunner,
        agents: dict[str, str],
        allowed_agents: Optional[list[str]] = None,
        lan_only: bool = True,
        route_tools: Optional[list[RouteTool]] = None,
        mutating_route_tools: Optional[list[MutatingRouteTool]] = None,
    ) -> None:
        """
        Parameters
        ----------
        runner: ``async (agent_id, text) -> str`` — routes through the orchestrator.
        agents: ``{agent_id: human-description}`` of all known agents.
        allowed_agents: subset exposed as tools (None → all).
        lan_only: advisory flag surfaced in status (binding is enforced elsewhere).
        route_tools: H22.9 — allow-listed READ-ONLY route tools (``route_<name>``)
            exposed alongside the agent tools. ``None``/empty → today's behaviour
            (agent tools only). The caller gates this on the
            ``JARVIS_MCP_ROUTE_TOOLS`` kill-switch.
        mutating_route_tools: H22.9 (mutating scope) — allow-listed MUTATING
            (write) route tools (``route_<name>``, marked ``"mutating": True``).
            ``None``/empty → no write tools. The caller gates these on BOTH the
            ``JARVIS_MCP_ROUTE_TOOLS`` AND ``JARVIS_MCP_MUTATING_TOOLS`` switches
            (see ``build_mutating_route_tools``). Every invocation is audited.
        """
        self.runner = runner
        self.agents = agents
        self.allowed = set(allowed_agents if allowed_agents is not None else agents.keys())
        self.lan_only = lan_only
        # Map ``route_<name>`` → RouteTool. Only allow-listed, read-only routes
        # ever land here (the allow-list IS the gate — see route_tools.py).
        self.route_tools: dict[str, RouteTool] = {
            rt.tool_name: rt for rt in (route_tools or [])
        }
        # Map ``route_<name>`` → MutatingRouteTool. Only allow-listed WRITE routes,
        # and only when BOTH kill-switches were on at build time (the caller
        # enforces that via build_mutating_route_tools). Disjoint from read tools.
        self.mutating_route_tools: dict[str, MutatingRouteTool] = {
            rt.tool_name: rt for rt in (mutating_route_tools or [])
        }

    # ── tools ────────────────────────────────────────────────────────────────

    def _exposed(self) -> list[str]:
        return [a for a in self.agents if a in self.allowed]

    def list_tools(self) -> list[dict]:
        """MCP tool descriptors: one per exposed agent, plus allow-listed routes.

        Route tools are appended only when this server was built with them (the
        ``JARVIS_MCP_ROUTE_TOOLS`` kill-switch is owned by the caller). With the
        switch off, ``self.route_tools`` is empty and the output is unchanged.
        """
        tools = []
        for agent_id in self._exposed():
            tools.append({
                "name": _tool_name(agent_id),
                "description": self.agents.get(agent_id) or f"Ask the {agent_id} agent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The request for the agent."}
                    },
                    "required": ["text"],
                },
            })
        for rt in self.route_tools.values():
            tools.append(rt.descriptor())
        # Mutating (write) tools — present only when BOTH kill-switches were on
        # at build time; each descriptor is marked ``"mutating": True``.
        for mt in self.mutating_route_tools.values():
            tools.append(mt.descriptor())
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: Optional[dict] = None,
        identity: Optional[str] = None,
    ) -> dict:
        """Run a tool; return an MCP tool-result ({content, isError}).

        ``identity`` is the caller's presented credential (e.g. ``JARVIS_USER_TOKEN``),
        threaded from the MCP transport. It is required only by MUTATING route
        tools, which enforce it with the same rule as the HTTP ``user_guard``; a
        missing/invalid identity refuses the write. Read-only tools and agent
        tools ignore it (unchanged behaviour).
        """
        arguments = arguments or {}
        if name.startswith(ROUTE_TOOL_PREFIX):
            return await self._call_route_tool(name, arguments, identity)
        agent_id = name[len("ask_"):] if name.startswith("ask_") else ""
        if not agent_id or agent_id not in self.agents:
            return self._tool_error(f"unknown tool: {name}")
        if agent_id not in self.allowed:
            return self._tool_error(f"agent '{agent_id}' is not exposed over MCP")
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._tool_error("missing required string argument: text")
        try:
            reply = await self.runner(agent_id, text)
        except Exception as exc:  # never leak a stack trace to an external client
            return self._tool_error(f"agent error: {exc}")
        return {"content": [{"type": "text", "text": str(reply)}], "isError": False}

    async def _call_route_tool(
        self, name: str, arguments: dict, identity: Optional[str] = None
    ) -> dict:
        """Dispatch an allow-listed route tool IN-PROCESS (read or write).

        The allow-list is the gate: a ``route_<name>`` that is not in
        ``self.route_tools`` (read) or ``self.mutating_route_tools`` (write) is
        refused, so a non-allow-listed route name can never reach a handler. The
        handler is called directly (no loopback HTTP), and its JSON payload is
        returned as text content.

        Read-only tools need no identity. Mutating tools enforce ``identity``
        with the same rule as the HTTP ``user_guard`` (and audit every call,
        including a refusal); an invalid identity is refused without writing.
        """
        rt = self.route_tools.get(name)
        if rt is not None:
            kwargs = rt.filtered_kwargs(arguments)
            try:
                raw = await rt.handler(**kwargs)
                payload = normalize_result(raw)
            except Exception as exc:  # never leak a stack trace to an external client
                return self._tool_error(f"route error: {exc}")
            return {
                "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                "isError": False,
            }

        mt = self.mutating_route_tools.get(name)
        if mt is not None:
            try:
                # Per-identity gate runs inside call(); audits the refusal too.
                raw = await mt.call(arguments, token=identity)
                payload = normalize_result(raw)
            except MutatingIdentityError as exc:
                # A write refused for want of a valid identity — clear error,
                # no stack trace, no write performed (audited as refused).
                return self._tool_error(f"identity required: {exc}")
            except Exception as exc:  # never leak a stack trace to an external client
                return self._tool_error(f"route error: {exc}")
            return {
                "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                "isError": False,
            }

        return self._tool_error(f"route '{name}' is not exposed over MCP")

    @staticmethod
    def _tool_error(message: str) -> dict:
        return {"content": [{"type": "text", "text": message}], "isError": True}

    # ── JSON-RPC dispatch ────────────────────────────────────────────────────

    async def handle(self, message: dict, identity: Optional[str] = None) -> Optional[dict]:
        """Dispatch one JSON-RPC 2.0 message; return the response (or None for a notification).

        ``identity`` is the caller's credential, supplied by the transport (the
        HTTP/SSE route in web.py reads the ``X-User-Token``/``X-Admin-Token``
        header; a stdio loop may pass it explicitly). It is forwarded to
        ``call_tool`` and enforced only for mutating route tools.
        """
        msg_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}

        if method == "initialize":
            return self._ok(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method in ("notifications/initialized", "initialized"):
            return None  # notification — no response
        if method == "tools/list":
            return self._ok(msg_id, {"tools": self.list_tools()})
        if method == "tools/call":
            name = params.get("name", "")
            result = await self.call_tool(name, params.get("arguments"), identity=identity)
            return self._ok(msg_id, result)
        if method == "ping":
            return self._ok(msg_id, {})
        return self._err(msg_id, METHOD_NOT_FOUND, f"method not found: {method}")

    @staticmethod
    def _ok(msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _err(msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    # ── introspection ────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol": PROTOCOL_VERSION,
            "lan_only": self.lan_only,
            "exposed_agents": self._exposed(),
            "exposed_routes": [rt.spec.name for rt in self.route_tools.values()],
            "exposed_mutating_routes": [
                mt.spec.name for mt in self.mutating_route_tools.values()
            ],
            "tools": [t["name"] for t in self.list_tools()],
        }
