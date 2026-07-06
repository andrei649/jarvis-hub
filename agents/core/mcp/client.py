"""
client.py — Model Context Protocol (MCP) client.
Connects to MCP servers via stdio or SSE transport.
"""

import asyncio
import json
import logging
import os
import re
import shlex
from typing import Any

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)

logger = logging.getLogger("jarvis.mcp")

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:/@\-]{1,200}$")
_SHELL_METACHARS = frozenset(";&|<>`\n\r")


def _safe_name(value: Any) -> bool:
    return bool(_SAFE_NAME.match(str(value or "")))


def _tool_call_names_safe(view, now) -> bool:
    return _safe_name(view.get("server")) and _safe_name(view.get("tool"))


def _args_keys_safe(view, now) -> bool:
    keys = view.get("args_keys")
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        return False
    return (
        keys == sorted(keys)
        and all(_safe_name(k) for k in keys)
    )


def _mcp_tool_call_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="mcp.tool_call",
        description="Outbound MCP client tool-call gate.",
        constraints=(
            field_present("server", "tool", "transport"),
            one_of("transport", {"stdio", "sse"}),
            predicate("tool_call_names_safe", _tool_call_names_safe, reason="invalid_name"),
            predicate("args_keys_safe", _args_keys_safe, reason="bad_args_keys"),
        ),
    )


MCP_TOOL_CALL_CONTRACT = _mcp_tool_call_contract_template()


class MCPTool:
    def __init__(self, name: str, description: str, input_schema: dict, server: str):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.server = server


class MCPServer:
    def __init__(
        self,
        name: str,
        transport: str = "stdio",
        command: str = None,
        url: str = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ):
        self.name = name
        self.transport = transport
        self.command = command
        self.url = url
        self.cwd = cwd
        self.env = dict(env or {})
        self.tools: list[MCPTool] = []
        self._proc = None

    async def connect(self):
        if self.transport == "stdio" and self.command:
            argv = self._command_argv()
            if not argv:
                logger.warning("MCP stdio command rejected as unsafe: %s", self.name)
                return False
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd or None,
                env=self._merged_env(),
            )
            await self._initialize()
        elif self.transport == "sse" and self.url:
            logger.info(f"MCP SSE transport not yet implemented: {self.url}")
        logger.info(f"MCP server connected: {self.name} ({len(self.tools)} tools)")
        return True

    def _command_argv(self) -> list[str] | None:
        command = (self.command or "").strip()
        if not command or any(ch in command for ch in _SHELL_METACHARS):
            return None
        try:
            argv = shlex.split(command)
        except ValueError:
            return None
        if not argv or any("\x00" in part for part in argv):
            return None
        return argv

    def _merged_env(self) -> dict[str, str] | None:
        if not self.env:
            return None
        merged = os.environ.copy()
        merged.update({str(k): str(v) for k, v in self.env.items()})
        return merged

    async def _initialize(self):
        resp = await self._send({"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1})
        if resp:
            await self._list_tools()

    async def _list_tools(self):
        resp = await self._send({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2})
        if resp and "result" in resp:
            for t in resp["result"].get("tools", []):
                self.tools.append(MCPTool(
                    name=t.get("name", "unknown"),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server=self.name,
                ))

    async def call_tool(self, name: str, arguments: dict = None) -> Any:
        arguments = arguments or {}
        if not isinstance(arguments, dict):
            return {"error": "bad_args", "tool": name, "server": self.name}
        blocked = self._tool_call_blocked(name, arguments)
        if blocked is not None:
            return blocked
        resp = await self._send({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": 3,
        })
        if resp and "result" in resp:
            return resp["result"]
        return resp

    def _tool_call_blocked(self, name: str, arguments: dict) -> dict | None:
        arg_keys = list(arguments.keys())
        if all(isinstance(k, str) for k in arg_keys):
            arg_keys = sorted(arg_keys)
        payload = {
            "kind": "mcp.tool_call",
            "server": self.name,
            "tool": name,
            "transport": self.transport,
            "args_keys": arg_keys,
        }
        try:
            decision = MCP_TOOL_CALL_CONTRACT.evaluate(payload)
        except Exception:
            logger.warning("MCP tool-call contract evaluation failed", exc_info=True)
            return {"error": "contract_error", "tool": name, "server": self.name}
        reason = contract_denial(decision)
        if reason:
            return {"error": reason, "tool": name, "server": self.name}
        return None

    async def _send(self, msg: dict) -> dict:
        if not self._proc or self._proc.stdin.is_closing():
            logger.warning(f"MCP server {self.name} not connected")
            return {}
        try:
            line = json.dumps(msg) + "\n"
            self._proc.stdin.write(line.encode())
            await self._proc.stdin.drain()
            raw = await asyncio.wait_for(self._proc.stdout.readline(), timeout=10.0)
            return json.loads(raw.decode())
        except Exception as e:
            logger.warning(f"MCP error ({self.name}): {e}")
            return {}

    async def close(self):
        if self._proc:
            self._proc.terminate()
            await self._proc.wait()
            logger.info(f"MCP server closed: {self.name}")


class MCPManager:
    def __init__(self):
        self.servers: dict[str, MCPServer] = {}

    def register(self, server: MCPServer):
        self.servers[server.name] = server

    async def connect_all(self):
        for srv in self.servers.values():
            try:
                await srv.connect()
            except Exception as e:
                logger.warning(f"MCP connect failed ({srv.name}): {e}")

    def get_tools(self) -> list[MCPTool]:
        tools = []
        for srv in self.servers.values():
            tools.extend(srv.tools)
        return tools

    def find_tool(self, name: str) -> MCPTool:
        for srv in self.servers.values():
            for t in srv.tools:
                if t.name == name:
                    return t
        return None

    async def call_tool(self, name: str, arguments: dict = None) -> Any:
        for srv in self.servers.values():
            for t in srv.tools:
                if t.name == name:
                    return await srv.call_tool(name, arguments)
        return {"error": f"Tool '{name}' not found"}

    async def close_all(self):
        for srv in self.servers.values():
            await srv.close()

    def to_config(self) -> list[dict]:
        """Export all servers to config format for persistence."""
        return [
            {
                "name": srv.name,
                "transport": srv.transport,
                "command": srv.command,
                "url": srv.url,
                "cwd": srv.cwd,
            }
            for srv in self.servers.values()
        ]

    def load_from_config(self, configs: list[dict]):
        """Load servers from config list."""
        self.servers.clear()
        for cfg in configs:
            srv = MCPServer(
                name=cfg["name"],
                transport=cfg.get("transport", "stdio"),
                command=cfg.get("command"),
                url=cfg.get("url"),
                cwd=cfg.get("cwd"),
            )
            self.servers[srv.name] = srv
