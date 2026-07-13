"""H32.7 — real Docker S2 acquisition-loop superiority proof."""

from __future__ import annotations

import os

import pytest

from agents.core.observability.acquisition_reality import acquisition_s2_case
from agents.core.observability.reality_harness import run_reality


def test_s2_case_is_an_explicit_non_promoting_real_docker_contract(tmp_path):
    case = acquisition_s2_case(root=tmp_path / "s2", image="python@sha256:" + "a" * 64)
    assert case.capability_id == "component:capability_acquisition"
    assert case.live is False
    assert case.metadata == {"backend": "docker", "benchmark": "S2", "promotable": False}
    assert "owner-approved" in case.contract
    assert "host execution" in case.contract


@pytest.mark.asyncio
async def test_s2_flow_contract_uses_the_same_container_boundary(monkeypatch, tmp_path):
    from agents.core.acquisition.sandbox_profile import DockerSandboxRunner, SandboxExecution

    async def deterministic_container(_self, command, *, container_name):
        rendered = " ".join(command)
        if "/workspace/contract/invoke.py" in rendered:
            output = 'JARVIS_ACQUIRED_RESULT:{"ok":true,"result":[1,2]}'
            return SandboxExecution(0, output, "", False, 0.01)
        if "socket.create_connection" in rendered:
            return SandboxExecution(1, "", "network unreachable", False, 0.01)
        if "--jarvis-mutate-contract" in command:
            return SandboxExecution(1, "", "mutation detected", False, 0.01)
        return SandboxExecution(0, "ok", "", False, 0.01)

    monkeypatch.setattr(DockerSandboxRunner, "run", deterministic_container)
    case = acquisition_s2_case(
        root=tmp_path / "s2",
        image="python@sha256:" + "a" * 64,
    )
    result = await case.probe()
    assert result["passed"] is True
    assert result["metadata"]["reuse_rate"] == 0.5
    assert all(value is True for key, value in result["metadata"].items() if key != "reuse_rate")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_SANDBOX_ISOLATION") != "1",
    reason="the H32 S2 proof runs only in the dedicated real-Docker CI lane",
)
async def test_real_acquisition_loop_is_governed_reusable_and_revocable(tmp_path):
    case = acquisition_s2_case(
        root=tmp_path / "s2",
        image=os.environ.get("JARVIS_ACQUISITION_SANDBOX_IMAGE", ""),
    )

    report = await run_reality([case], promote=False)

    assert report["total"] == 1
    assert report["passed"] == 1, report["results"]
    assert report["skipped"] == 0
    result = report["results"][0]
    assert result["capability_id"] == "component:capability_acquisition"
    assert result["metadata"] == {
        "backend": "docker",
        "benchmark": "S2",
        "promotable": False,
        "approval_blocked_before_owner": True,
        "audit_chain_valid": True,
        "generated_network_blocked": True,
        "host_execution_absent": True,
        "kernel_halt_blocked": True,
        "registry_outcome_recorded": True,
        "reuse_rate": 0.5,
        "revoked_and_uninstalled": True,
        "sandbox_execution_verified": True,
        "tamper_refused": True,
        "upgrade_rollback_verified": True,
    }
