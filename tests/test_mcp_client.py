"""Regression tests for the outbound MCP client (agents/core/mcp/client.py).

`MCPServer._send` calls `asyncio.wait_for`, but `asyncio` used to be imported
only locally inside `connect()` — so on the request path `asyncio` was undefined.
The resulting `NameError` was swallowed by the broad `except Exception` in
`_send`, which returned `{}`. Net effect: every outbound MCP request silently
failed (initialize / tools/list / tools/call all returned empty), with no crash
to reveal it. These tests exercise `_send` with a fake subprocess so the import
regression fails loudly instead of degrading to an empty response.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.mcp.client import MCPServer


class _FakeStdin:
    def is_closing(self) -> bool:
        return False

    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass


class _FakeStdout:
    def __init__(self, line: bytes):
        self._line = line

    async def readline(self) -> bytes:
        return self._line


class _FakeProc:
    def __init__(self, response: bytes):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(response)


class _FakeConnectProc:
    def __init__(self):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(b'{"jsonrpc":"2.0","id":1,"result":{}}\n')
        self.stderr = None
        self.returncode = None


async def test_send_roundtrips_response_without_nameerror():
    # Before the fix `asyncio.wait_for` raised NameError (asyncio unimported on
    # this path); the broad except turned it into {}. A real response must come
    # back now, proving asyncio is in scope.
    srv = MCPServer("test", transport="stdio", command="echo")
    srv._proc = _FakeProc(b'{"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}\n')
    resp = await srv._send({"jsonrpc": "2.0", "method": "ping", "id": 1})
    assert resp == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


async def test_send_returns_empty_when_not_connected():
    # Existing fast-fail path is preserved: no proc → warn + {}.
    srv = MCPServer("test", transport="stdio", command="echo")
    assert await srv._send({"jsonrpc": "2.0", "id": 1}) == {}


async def test_stdio_connect_passes_cwd_and_env_without_shell(monkeypatch):
    exec_calls = []

    async def fake_exec(*argv, **kwargs):
        exec_calls.append((argv, kwargs))
        return _FakeConnectProc()

    monkeypatch.setattr("agents.core.mcp.client.asyncio.create_subprocess_exec", fake_exec)

    srv = MCPServer(
        "worldview",
        transport="stdio",
        command="node dist/server.js",
        cwd="worldview/mcp",
        env={"WORLDVIEW_MCP_SECRET": "shared-secret"},
    )
    await srv.connect()

    assert exec_calls[0][0] == ("node", "dist/server.js")
    assert exec_calls[0][1]["cwd"] == "worldview/mcp"
    assert exec_calls[0][1]["env"]["WORLDVIEW_MCP_SECRET"] == "shared-secret"
