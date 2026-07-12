import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from agents.core.environments.targets import (
    ALLOW,
    APPROVAL_REQUIRED,
    DENY,
    TargetAuditChain,
    TargetAuditCorrupt,
    TargetRegistry,
    TerminalTarget,
    default_targets,
)


def _clock():
    return datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def _target(**overrides):
    values = {
        "name": "test-target",
        "backend": "docker",
        "enabled": True,
        "allowed_agents": frozenset({"jarvis"}),
        "capabilities": frozenset({"terminal.read", "terminal.exec"}),
        "approval_required": frozenset({"terminal.exec"}),
    }
    values.update(overrides)
    return TerminalTarget(**values)


def test_default_targets_are_named_conservative_backend_profiles():
    targets = {target.name: target for target in default_targets()}

    assert set(targets) == {"bonobo-windows", "pi-house", "isolated-sandbox"}
    assert targets["bonobo-windows"].backend == "local"
    assert targets["bonobo-windows"].enabled is False
    assert targets["pi-house"].backend == "ssh"
    assert targets["pi-house"].enabled is False
    assert targets["isolated-sandbox"].backend == "docker"
    assert targets["isolated-sandbox"].enabled is True
    assert targets["isolated-sandbox"].approval_required == frozenset()


def test_target_policy_returns_allow_approval_or_deny_and_audits_each():
    audit = TargetAuditChain(clock=_clock)
    registry = TargetRegistry([_target()], audit=audit)

    read = registry.authorize("test-target", "jarvis", "terminal.read")
    execute = registry.authorize("test-target", "jarvis", "terminal.exec")
    agent_denied = registry.authorize("test-target", "ultron", "terminal.read")
    cap_denied = registry.authorize("test-target", "jarvis", "file.write")
    missing = registry.authorize("missing", "jarvis", "terminal.read")

    assert (read.outcome, read.reason) == (ALLOW, "target_policy_allowed")
    assert (execute.outcome, execute.reason) == (
        APPROVAL_REQUIRED, "target_policy_requires_approval"
    )
    assert (agent_denied.outcome, agent_denied.reason) == (DENY, "agent_not_allowed")
    assert (cap_denied.outcome, cap_denied.reason) == (DENY, "capability_not_allowed")
    assert (missing.outcome, missing.reason) == (DENY, "target_missing")
    assert len(audit.entries) == 5
    assert audit.verify_chain() is True


def test_disabled_target_and_wildcard_agent_policy():
    registry = TargetRegistry([
        _target(name="disabled", enabled=False),
        _target(name="shared", allowed_agents=frozenset({"*"})),
    ])

    assert registry.authorize(
        "disabled", "jarvis", "terminal.read"
    ).reason == "target_disabled"
    assert registry.authorize("shared", "any-agent", "terminal.read").outcome == ALLOW


def test_target_and_registry_validation_fail_closed():
    with pytest.raises(ValueError, match="backend"):
        _target(backend="cloud")
    with pytest.raises(ValueError, match="name"):
        _target(name="../escape")
    with pytest.raises(ValueError, match="subset"):
        _target(approval_required=frozenset({"file.delete"}))
    with pytest.raises(ValueError, match="boolean"):
        _target(enabled="yes")
    with pytest.raises(ValueError, match="collections"):
        _target(capabilities="terminal.read")

    registry = TargetRegistry([_target()])
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(_target())
    with pytest.raises(ValueError, match="agent"):
        registry.authorize("test-target", "", "terminal.read")
    with pytest.raises(ValueError, match="capability"):
        registry.authorize("test-target", "jarvis", "../exec")


def test_audit_chain_detects_tampering_and_redacts_caller_data():
    audit = TargetAuditChain(clock=_clock)
    registry = TargetRegistry([_target()], audit=audit)
    registry.authorize(
        "test-target", "jarvis", "terminal.exec", correlation_id="run-123"
    )

    encoded = json.dumps(audit.entries)
    assert "run-123" in encoded
    assert "command" not in encoded
    assert audit.verify_chain() is True

    tampered = audit.entries
    tampered[0]["reason"] = "tampered"
    assert audit.verify_chain(tampered) is False
    assert audit.verify_chain() is True


def test_durable_chain_round_trips_and_corruption_refuses_startup(tmp_path):
    path = tmp_path / "target-audit.jsonl"
    audit = TargetAuditChain(path=path, clock=_clock)
    registry = TargetRegistry([_target()], audit=audit)
    registry.authorize("test-target", "jarvis", "terminal.read")
    registry.authorize("test-target", "jarvis", "terminal.exec")

    loaded = TargetAuditChain(path=path, clock=_clock)
    assert loaded.verify_chain() is True
    assert [entry["sequence"] for entry in loaded.entries] == [1, 2]

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["outcome"] = DENY
    lines[0] = json.dumps(payload)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(TargetAuditCorrupt):
        TargetAuditChain(path=path, clock=_clock)


def test_durable_append_refuses_before_crossing_file_budget(tmp_path):
    path = tmp_path / "bounded-audit.jsonl"
    audit = TargetAuditChain(path=path, clock=_clock, max_file_bytes=900)
    registry = TargetRegistry([_target()], audit=audit)

    registry.authorize("test-target", "jarvis", "terminal.read")
    size_before = path.stat().st_size
    with pytest.raises(ValueError, match="size budget"):
        while True:
            registry.authorize("test-target", "jarvis", "terminal.read")

    assert path.stat().st_size == size_before or path.stat().st_size < 900
    assert path.stat().st_size <= 900
    assert TargetAuditChain(path=path, clock=_clock, max_file_bytes=900).verify_chain()


def test_concurrent_authorizations_form_one_contiguous_valid_chain():
    audit = TargetAuditChain(clock=_clock)
    registry = TargetRegistry([_target(allowed_agents=frozenset({"*"}))], audit=audit)

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(
            lambda index: registry.authorize(
                "test-target", f"agent-{index}", "terminal.read", correlation_id=f"r-{index}"
            ),
            range(100),
        ))

    assert all(decision.outcome == ALLOW for decision in decisions)
    assert [entry["sequence"] for entry in audit.entries] == list(range(1, 101))
    assert audit.verify_chain() is True
