"""R1 residual safety gates: Oracle repo sync + outbound MCP host execution."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.automation_contracts import ContractDecision
from agents.core.kernel import Action, Decision, Verdict
from agents.core.mcp import client as mcp_client
from agents.core.mcp.client import MCPServer
from agents.core.plugins import oracle_bridge


def _isolate_oracle_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(oracle_bridge, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(oracle_bridge, "FILE_HASH_FILE", tmp_path / "file_hashes.json")


@pytest.mark.asyncio
async def test_oracle_external_commit_blocks_pull_when_kernel_off(monkeypatch, tmp_path):
    _isolate_oracle_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    bridge = oracle_bridge.OracleBridgePlugin(github_token="")
    pull_calls = []

    def _git_pull():
        pull_calls.append("called")
        return True, ""

    monkeypatch.setattr(bridge, "_git_pull", _git_pull)

    out = await bridge._process_claude_commit(
        "a" * 40,
        "feat: external agent change",
        author_login="claude",
        trigger_verified=True,
    )

    assert out["blocked"] is True
    assert out["reason"] == "kernel_required"
    assert pull_calls == []
    assert bridge.current_session is not None
    assert bridge.current_session.status == "failed"


class _QueueKernel:
    def __init__(self):
        self.actions: list[Action] = []

    def __call__(self, action: Action) -> Decision:
        self.actions.append(action)
        return Decision(Verdict.QUEUE, reason="needs owner approval", card={"requires_approval": True})


@pytest.mark.asyncio
async def test_oracle_kernel_queue_enqueues_but_does_not_pull(monkeypatch, tmp_path):
    _isolate_oracle_state(monkeypatch, tmp_path)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = _QueueKernel()
    enqueued = []
    bridge = oracle_bridge.OracleBridgePlugin(github_token="", kernel=kernel, enqueue=lambda *a, **kw: enqueued.append((a, kw)) or 42)
    pull_calls = []
    monkeypatch.setattr(bridge, "_git_pull", lambda: pull_calls.append("called") or (True, ""))

    out = await bridge._process_claude_commit(
        "b" * 40,
        "feat: queued external change",
        author_login="claude",
        trigger_verified=True,
    )

    assert out["blocked"] is True
    assert out["reason"] == "approval_required"
    assert out["task_id"] == 42
    assert pull_calls == []
    assert kernel.actions and kernel.actions[0].kind == "repo.sync"
    assert enqueued[0][0][:3] == ("oracle", "repo.sync", "Review external repo sync")


class _FakeStdin:
    def is_closing(self) -> bool:
        return False

    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass


class _FakeStdout:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    async def readline(self) -> bytes:
        return self._lines.pop(0)


class _FakeProc:
    def __init__(self):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout([
            b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
            b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n',
        ])
        self.stderr = None
        self.returncode = None


@pytest.mark.asyncio
async def test_mcp_stdio_connect_uses_exec_argv_not_shell(monkeypatch):
    shell_calls = []
    exec_calls = []

    async def fake_shell(*args, **kwargs):
        shell_calls.append((args, kwargs))
        raise AssertionError("shell must not be used for MCP stdio")

    async def fake_exec(*argv, **kwargs):
        exec_calls.append((argv, kwargs))
        return _FakeProc()

    monkeypatch.setattr(mcp_client.asyncio, "create_subprocess_shell", fake_shell)
    monkeypatch.setattr(mcp_client.asyncio, "create_subprocess_exec", fake_exec)

    srv = MCPServer("worldview", transport="stdio", command="python -m worldview.mcp")
    await srv.connect()

    assert shell_calls == []
    assert exec_calls[0][0][:3] == ("python", "-m", "worldview.mcp")


@pytest.mark.asyncio
async def test_mcp_stdio_rejects_shell_metacharacters_before_spawn(monkeypatch):
    shell_calls = []
    exec_calls = []

    async def fake_shell(*args, **kwargs):
        shell_calls.append((args, kwargs))
        return _FakeProc()

    async def fake_exec(*args, **kwargs):
        exec_calls.append((args, kwargs))
        return _FakeProc()

    monkeypatch.setattr(mcp_client.asyncio, "create_subprocess_shell", fake_shell)
    monkeypatch.setattr(mcp_client.asyncio, "create_subprocess_exec", fake_exec)

    srv = MCPServer("bad", transport="stdio", command="python -m worldview.mcp; rm -rf .")
    await srv.connect()

    assert srv._proc is None
    assert shell_calls == []
    assert exec_calls == []


class _DenyContract:
    def __init__(self):
        self.calls = []

    def evaluate(self, payload, **kwargs):
        self.calls.append((dict(payload), dict(kwargs)))
        return ContractDecision(
            kind="mcp.tool_call",
            admissible=False,
            requires_approval=True,
            reason="contract_blocked",
        )


@pytest.mark.asyncio
async def test_mcp_call_tool_obeys_live_contract_before_send(monkeypatch):
    contract = _DenyContract()
    monkeypatch.setattr(mcp_client, "MCP_TOOL_CALL_CONTRACT", contract, raising=False)
    send_calls = []
    srv = MCPServer("worldview", transport="stdio", command="python -m worldview.mcp")

    async def fake_send(msg):
        send_calls.append(msg)
        return {"result": {"ran": True}}

    srv._send = fake_send

    out = await srv.call_tool("watch_aoi", {"aoi": "black-sea", "token": "secret"})

    assert out == {"error": "contract_blocked", "tool": "watch_aoi", "server": "worldview"}
    assert send_calls == []
    assert contract.calls[0][0]["args_keys"] == ["aoi", "token"]


@pytest.mark.asyncio
async def test_mcp_call_tool_rejects_mixed_arg_keys_without_send():
    send_calls = []
    srv = MCPServer("worldview", transport="stdio", command="python -m worldview.mcp")

    async def fake_send(msg):
        send_calls.append(msg)
        return {"result": {"ran": True}}

    srv._send = fake_send

    out = await srv.call_tool("watch_aoi", {"aoi": "black-sea", 1: "not-json-safe"})

    assert out == {"error": "bad_args_keys", "tool": "watch_aoi", "server": "worldview"}
    assert send_calls == []
