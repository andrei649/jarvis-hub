"""GAP-9 — the governed target execution transport (H28.3's missing half).

Pins the transport's safety order: the audit-chained authorize decision comes
before any process can exist; DENY and APPROVAL_REQUIRED never spawn; a
docker-target command never silently lands on the host; local (flag off) and
ssh refuse with explicit not-implemented reasons; the hardline denylist screens
every backend before authorize; and the whole surface stays default-off behind
JARVIS_TERMINAL_TARGETS at the ToolRPC layer. The local-host transport itself
is pinned in tests/test_local_transport.py.
"""

import pytest

from agents.core.environments import (
    GovernedTargetRunner,
    TargetAuditChain,
    TargetRegistry,
    TerminalTarget,
    default_targets,
)


class _FakeSandbox:
    def __init__(self, backend="docker", exit_code=0):
        self.backend = backend
        self.exit_code = exit_code
        self.commands = []

    def active_backend(self):
        return self.backend

    async def execute_shell(self, command):
        self.commands.append(command)

        class _Result:
            stdout = "ok"
            stderr = ""
            duration = 0.01

        result = _Result()
        result.exit_code = self.exit_code
        return result


def _registry(**audit_kwargs):
    return TargetRegistry(default_targets(), audit=TargetAuditChain(**audit_kwargs))


@pytest.mark.asyncio
async def test_allow_executes_exactly_once_through_docker():
    sandbox = _FakeSandbox()
    registry = _registry()
    result = await GovernedTargetRunner(registry, sandbox).run(
        target="isolated-sandbox", agent="jarvis", command="echo hi"
    )
    assert result["ok"] is True
    assert result["outcome"] == "allow"
    assert result["backend"] == "docker"
    assert sandbox.commands == ["echo hi"]
    # The decision is on the audit chain (recorded before the spawn).
    assert registry.audit.entries[-1]["outcome"] == "allow"


@pytest.mark.asyncio
async def test_denied_agent_never_spawns_and_is_audited():
    registry = TargetRegistry(
        (
            TerminalTarget(
                name="isolated-sandbox",
                backend="docker",
                enabled=True,
                allowed_agents=frozenset({"ultron"}),
                capabilities=frozenset({"terminal.exec"}),
                approval_required=frozenset(),
            ),
        ),
        audit=TargetAuditChain(),
    )
    sandbox = _FakeSandbox()
    result = await GovernedTargetRunner(registry, sandbox).run(
        target="isolated-sandbox", agent="jarvis", command="echo hi"
    )
    assert result["ok"] is False
    assert result["reason"] == "agent_not_allowed"
    assert sandbox.commands == []
    assert registry.audit.entries[-1]["outcome"] == "deny"


@pytest.mark.asyncio
async def test_approval_required_never_spawns():
    registry = TargetRegistry(
        (
            TerminalTarget(
                name="guarded",
                backend="docker",
                enabled=True,
                allowed_agents=frozenset({"*"}),
                capabilities=frozenset({"terminal.exec"}),
                approval_required=frozenset({"terminal.exec"}),
            ),
        ),
        audit=TargetAuditChain(),
    )
    sandbox = _FakeSandbox()
    result = await GovernedTargetRunner(registry, sandbox).run(
        target="guarded", agent="jarvis", command="echo hi"
    )
    assert result["ok"] is False
    assert result["reason"] == "target_policy_requires_approval"
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_docker_target_never_degrades_onto_the_host():
    sandbox = _FakeSandbox(backend="subprocess-host")
    result = await GovernedTargetRunner(_registry(), sandbox).run(
        target="isolated-sandbox", agent="jarvis", command="echo hi"
    )
    assert result["ok"] is False
    assert result["reason"].startswith("docker_backend_unavailable")
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_local_and_ssh_refuse_with_explicit_not_implemented(monkeypatch):
    # Enabled variants of the disabled inventory targets, to reach the backend
    # dispatch: the refusal must be an honest not-implemented, not a crash.
    # With JARVIS_TERMINAL_LOCAL_HOST unset the local refusal is byte-identical
    # to the pre-transport behaviour.
    monkeypatch.delenv("JARVIS_TERMINAL_LOCAL_HOST", raising=False)
    registry = TargetRegistry(
        (
            TerminalTarget(
                name="host",
                backend="local",
                enabled=True,
                allowed_agents=frozenset({"*"}),
                capabilities=frozenset({"terminal.exec"}),
                approval_required=frozenset(),
            ),
            TerminalTarget(
                name="pi",
                backend="ssh",
                enabled=True,
                allowed_agents=frozenset({"*"}),
                capabilities=frozenset({"terminal.exec"}),
                approval_required=frozenset(),
            ),
        ),
        audit=TargetAuditChain(),
    )
    sandbox = _FakeSandbox()
    runner = GovernedTargetRunner(registry, sandbox)
    local = await runner.run(target="host", agent="jarvis", command="echo hi")
    ssh = await runner.run(target="pi", agent="jarvis", command="echo hi")
    assert local["reason"] == "local_transport_not_implemented"
    assert ssh["reason"] == "ssh_transport_not_implemented"
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_hardline_denies_before_policy_on_every_backend():
    # A catastrophic command never reaches authorize: no audit entry, no spawn,
    # on the container target as much as on the host.
    sandbox = _FakeSandbox()
    registry = _registry()
    runner = GovernedTargetRunner(registry, sandbox)
    result = await runner.run(
        target="isolated-sandbox", agent="jarvis", command="rm -rf / --no-preserve-root"
    )
    assert result == {
        "ok": False,
        "reason": "hardline_denied:recursive_root_removal",
        "target": "isolated-sandbox",
    }
    assert sandbox.commands == []
    assert registry.audit.entries == []


@pytest.mark.asyncio
async def test_command_bounds_are_enforced_before_policy():
    sandbox = _FakeSandbox()
    runner = GovernedTargetRunner(_registry(), sandbox)
    empty = await runner.run(target="isolated-sandbox", agent="jarvis", command="  ")
    long = await runner.run(
        target="isolated-sandbox", agent="jarvis", command="x" * 5000
    )
    assert empty["reason"] == "empty_command"
    assert long["reason"] == "command_too_long"
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_failed_command_reports_honest_exit_code():
    sandbox = _FakeSandbox(exit_code=2)
    result = await GovernedTargetRunner(_registry(), sandbox).run(
        target="isolated-sandbox", agent="jarvis", command="false"
    )
    assert result["ok"] is False
    assert result["exit_code"] == 2


@pytest.mark.asyncio
async def test_durable_audit_chain_survives_and_verifies(tmp_path):
    path = tmp_path / "target-audit.jsonl"
    registry = _registry(path=path)
    sandbox = _FakeSandbox()
    await GovernedTargetRunner(registry, sandbox).run(
        target="isolated-sandbox", agent="jarvis", command="echo hi"
    )
    assert path.exists()
    # A fresh chain over the same file re-verifies the recorded decision.
    reloaded = TargetAuditChain(path=path)
    assert reloaded.entries[-1]["outcome"] == "allow"


def test_terminal_run_is_default_off_and_approval_railed(monkeypatch):
    from agents.core.autonomy_coordinator import _TRUSTED_TOOL_RPC_KINDS
    from agents.core.env_config import env_flag

    monkeypatch.delenv("JARVIS_TERMINAL_TARGETS", raising=False)
    assert env_flag("JARVIS_TERMINAL_TARGETS") is False
    # An approved terminal_run task is only trusted through the same durable
    # execution rail as desktop_run.
    assert "toolrpc.terminal_run" in _TRUSTED_TOOL_RPC_KINDS
    assert "toolrpc.desktop_run" in _TRUSTED_TOOL_RPC_KINDS
