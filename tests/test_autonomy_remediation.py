"""
Tests for safe host service remediation (agents/core/autonomy/remediation.py).

All tests run offline. We inject mock executors, mock probes, mock audit loggers,
and mock permission gates to assert correct control flow and security.
"""

from __future__ import annotations

import asyncio
import pytest

from agents.core.autonomy.remediation import RemediationRunner, ServiceCommand, ExecResult
from agents.core.plugin_gate import PermissionGate, PluginManifest, NetworkAccess, DataScope


class MockPermissionGate:
    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.calls = []

    def check_call(self, plugin_id: str, agent_id: str, target_domain: str = "") -> bool:
        self.calls.append((plugin_id, agent_id))
        return self.allowed


class MockAuditLogger:
    def __init__(self):
        self.logs = []

    def log(self, event: str, payload: dict):
        self.logs.append((event, payload))


@pytest.mark.asyncio
async def test_blocked_by_permission_gate():
    gate = MockPermissionGate(allowed=False)
    runner = RemediationRunner(permission_gate=gate)
    
    result = await runner.restart("qdrant", agent="steve")
    assert result["status"] == "blocked"
    assert "not permitted" in result["reason"]
    assert gate.calls == [("system-control", "steve")]


@pytest.mark.asyncio
async def test_rejected_not_in_allowlist():
    gate = MockPermissionGate(allowed=True)
    runner = RemediationRunner(allowlist={}, permission_gate=gate)
    
    result = await runner.restart("unknown_service", agent="steve")
    assert result["status"] == "rejected"
    assert "not in restart allowlist" in result["reason"]


@pytest.mark.asyncio
async def test_exec_error_retains_before_state():
    gate = MockPermissionGate(allowed=True)
    audit = MockAuditLogger()
    
    async def mock_exec(argv, timeout, detach):
        raise RuntimeError("exec failed")
        
    def mock_probe(host, port):
        return False
        
    allowlist = {
        "qdrant": ServiceCommand(["docker", "restart", "qdrant"], verify_port=6333)
    }
    
    runner = RemediationRunner(
        allowlist=allowlist,
        permission_gate=gate,
        audit=audit,
        exec_fn=mock_exec,
        probe_fn=mock_probe
    )
    
    result = await runner.restart("qdrant", agent="steve")
    assert result["status"] == "failed"
    assert result["before"] is False
    assert result["service"] == "qdrant"
    assert "exec failed" in result["reason"]
    assert len(audit.logs) == 1
    assert audit.logs[0][0] == "autonomy.remediation"


@pytest.mark.asyncio
async def test_successful_restart_and_verification():
    gate = MockPermissionGate(allowed=True)
    audit = MockAuditLogger()
    
    exec_called = []
    async def mock_exec(argv, timeout, detach):
        exec_called.append(argv)
        return ExecResult(exit_code=0, stdout="done")
        
    probe_state = [False, True]  # False before, True after
    def mock_probe(host, port):
        return probe_state.pop(0) if probe_state else True
        
    allowlist = {
        "qdrant": ServiceCommand(["docker", "restart", "qdrant"], verify_port=6333)
    }
    
    runner = RemediationRunner(
        allowlist=allowlist,
        permission_gate=gate,
        audit=audit,
        exec_fn=mock_exec,
        probe_fn=mock_probe,
        verify_attempts=3,
        verify_delay=0.01
    )
    
    result = await runner.restart("qdrant", agent="steve")
    assert result["status"] == "ok"
    assert result["before"] is False
    assert result["after"] is True
    assert exec_called == [["docker", "restart", "qdrant"]]


@pytest.mark.asyncio
async def test_detached_command_starts_and_probes():
    gate = MockPermissionGate(allowed=True)
    
    exec_called = []
    async def mock_exec(argv, timeout, detach):
        exec_called.append((argv, detach))
        return ExecResult(exit_code=0, stdout="started detached")
        
    probe_state = [False, False, True]
    def mock_probe(host, port):
        return probe_state.pop(0) if probe_state else True
        
    allowlist = {
        "ollama": ServiceCommand(["ollama", "serve"], detach=True, verify_port=11434)
    }
    
    runner = RemediationRunner(
        allowlist=allowlist,
        permission_gate=gate,
        exec_fn=mock_exec,
        probe_fn=mock_probe,
        verify_attempts=5,
        verify_delay=0.01
    )
    
    result = await runner.restart("ollama", agent="steve")
    assert result["status"] == "ok"
    assert result["before"] is False
    assert result["after"] is True
    assert exec_called == [(["ollama", "serve"], True)]
