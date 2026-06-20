"""
client.py — Model Context Protocol (MCP) client.
Connects to MCP servers via stdio or SSE transport.
"""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("jarvis.mcp")


class MCPTool:
    def __init__(self, name: str, description: str, input_schema: dict, server: str):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.server = server


class MCPServer:
    def __init__(self, name: str, transport: str = "stdio", command: str = None, url: str = None):
        self.name = name
        self.transport = transport
        self.command = command
        self.url = url
        self.tools: list[MCPTool] = []
        self._proc = None

    async def connect(self):
        if self.transport == "stdio" and self.command:
            self._proc = await asyncio.create_subprocess_shell(
                self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await self._initialize()
        elif self.transport == "sse" and self.url:
            logger.info(f"MCP SSE transport not yet implemented: {self.url}")
        logger.info(f"MCP server connected: {self.name} ({len(self.tools)} tools)")

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
        resp = await self._send({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
            "id": 3,
        })
        if resp and "result" in resp:
            return resp["result"]
        return resp

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
            )
            self.servers[srv.name] = srv
