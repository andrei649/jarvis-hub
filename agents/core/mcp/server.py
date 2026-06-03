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

from typing import Awaitable, Callable, Optional

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
    ) -> None:
        """
        Parameters
        ----------
        runner: ``async (agent_id, text) -> str`` — routes through the orchestrator.
        agents: ``{agent_id: human-description}`` of all known agents.
        allowed_agents: subset exposed as tools (None → all).
        lan_only: advisory flag surfaced in status (binding is enforced elsewhere).
        """
        self.runner = runner
        self.agents = agents
        self.allowed = set(allowed_agents if allowed_agents is not None else agents.keys())
        self.lan_only = lan_only

    # ── tools ────────────────────────────────────────────────────────────────

    def _exposed(self) -> list[str]:
        return [a for a in self.agents if a in self.allowed]

    def list_tools(self) -> list[dict]:
        """MCP tool descriptors, one per exposed agent."""
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
        return tools

    async def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        """Run a tool; return an MCP tool-result ({content, isError})."""
        arguments = arguments or {}
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

    @staticmethod
    def _tool_error(message: str) -> dict:
        return {"content": [{"type": "text", "text": message}], "isError": True}

    # ── JSON-RPC dispatch ────────────────────────────────────────────────────

    async def handle(self, message: dict) -> Optional[dict]:
        """Dispatch one JSON-RPC 2.0 message; return the response (or None for a notification)."""
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
            result = await self.call_tool(name, params.get("arguments"))
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
            "tools": [t["name"] for t in self.list_tools()],
        }
