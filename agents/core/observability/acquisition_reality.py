"""Real-Docker S2 benchmark for the governed capability-acquisition loop."""

from __future__ import annotations

import os
from pathlib import Path

from agents.core.observability.reality_types import RealityCase


def acquisition_s2_case(*, root: str | Path, image: str) -> RealityCase:
    root_path = Path(root)

    async def probe():
        return await _run_s2(root=root_path, image=image)

    return RealityCase(
        capability_id="component:capability_acquisition",
        name="acquisition-s2-real-docker",
        contract=(
            "A net-new explicit miss is researched, generated, isolated, owner-approved, "
            "signed, sandbox-executed, reused, tamper-refused, revoked and removable without "
            "host execution or generated-code network access."
        ),
        probe=probe,
        live=False,
        metadata={"backend": "docker", "benchmark": "S2", "promotable": False},
    )


class _FixtureResponse:
    redirect_url = None

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def aiter_bytes(self):
        yield self.payload

    async def aclose(self) -> None:
        return None


def _require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def _run_s2(*, root: Path, image: str) -> dict[str, object]:
    from agents.core.acquisition.acquired_runner import AcquiredSandboxRunner
    from agents.core.acquisition.audit import AcquisitionLedger
    from agents.core.acquisition.generator import (
        CapabilityContract,
        ContractCase,
        StrictLocalGenerator,
    )
    from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
    from agents.core.acquisition.models import RequestStatus
    from agents.core.acquisition.package_store import AcquiredPackageStore
    from agents.core.acquisition.promotion import (
        PromotionBroker,
        PromotionError,
        PromotionJournal,
        PromotionStore,
    )
    from agents.core.acquisition.quarantine import QuarantineStore
    from agents.core.acquisition.research import GovernedResearch, ResearchStore
    from agents.core.acquisition.resolver import (
        ReuseCandidate,
        ReuseDecisionStore,
        ReuseResolver,
    )
    from agents.core.acquisition.sandbox_profile import (
        AcquisitionSandboxProfile,
        SandboxVerifier,
    )
    from agents.core.acquisition.store import CapabilityRequestStore
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel import Action, authorize
    from agents.core.security.capability import KillSwitch
    from agents.core.skills.marketplace import SkillMarketplace
    from agents.core.tool_rpc import ToolRPCServer

    root.mkdir(parents=True, exist_ok=False)
    profile = AcquisitionSandboxProfile(image=image, timeout_seconds=60)
    profile.require_backend("docker")
    ledger = AcquisitionLedger(root=root / "ledger")
    request_store = CapabilityRequestStore(root=root / "requests", event_sink=ledger.emit)
    decisions = ReuseDecisionStore(root=root / "reuse", event_sink=ledger.emit)
    resolver = ReuseResolver(decision_store=decisions)

    request = request_store.capture(
        "parse Acme API items into a normalized list",
        agent_id="jarvis",
        reason="tool_not_allowed",
    )
    first_decision = resolver.resolve(request, [], request_store=request_store)
    _require(first_decision.outcome == "no_reuse", "net-new request unexpectedly reused")
    request_store.transition(request.request_id, RequestStatus.RESEARCHING, actor="s2-research")

    fixture = b"Acme items are JSON objects. Preserve their id values in list order."

    async def search(_query: str, _limit: int):
        return [{"url": "https://docs.example.com/acme", "title": "Acme item contract"}]

    async def fetch(_url: str, _pinned_ip: str):
        return _FixtureResponse(fixture)

    def draft(_goal: str, references: list[dict]):
        return [{"text": "Read item ids in list order.", "cites": [references[0]["id"]]}]

    research_store = ResearchStore(root=root / "research", event_sink=ledger.emit)
    research = await GovernedResearch(
        enabled=True,
        network_consent=True,
        cloud_consent=False,
        backend_name="searxng",
        search=search,
        fetch=fetch,
        draft=draft,
        draft_route="strict-local",
        resolve=lambda _host: ("93.184.216.34",),
        allowed_domains={"docs.example.com"},
        store=research_store,
    ).run(request)
    _require(research.plan.get("fully_grounded") is True, "research plan was not grounded")

    contract = CapabilityContract(
        goal=request.goal,
        entrypoint="run",
        cases=(
            ContractCase(
                input={"items": [{"id": 1}, {"id": 2}]},
                expected=[1, 2],
            ),
        ),
    )

    async def generate(_prompt):
        return {
            "name": "acme_item_parser",
            "entrypoint": "run",
            "code": (
                "def run(payload):\n"
                "    return [item['id'] for item in payload.get('items', [])]\n"
            ),
            "test": (
                "import unittest\n"
                "from main import run\n\n"
                "class GeneratedTest(unittest.TestCase):\n"
                "    def test_items(self):\n"
                "        self.assertEqual(run({'items': [{'id': 3}]}), [3])\n"
            ),
        }

    generator = StrictLocalGenerator(
        generate=generate,
        route="strict-local",
        event_sink=ledger.emit,
    )
    package = await generator.generate(
        request=request,
        grounded_plan=research.plan,
        contract=contract,
    )
    decisions.record_outcome(request.request_id, "generated")
    request_store.transition(request.request_id, RequestStatus.QUARANTINED, actor="s2-generator")
    quarantine = QuarantineStore(root=root / "quarantine", event_sink=ledger.emit)
    quarantine.put(package)
    verifier = SandboxVerifier(
        profile=profile,
        runtime_root=root / "verification-runs",
    )
    outcome = await verifier.verify_quarantined(
        store=quarantine,
        artifact_id=package.artifact_id,
        contract=contract,
    )
    _require(outcome.verified and outcome.receipt is not None, "real Docker verification failed")

    signing = ManagedSigningKeyStore(root=root / "signing")
    signing.provision(key_id="owner", version=1, key=os.urandom(32))
    packages = AcquiredPackageStore(
        root=root / "packages",
        signing=signing,
        event_sink=ledger.emit,
    )
    tool_rpc = ToolRPCServer()
    runtime = AcquiredSandboxRunner(
        packages=packages,
        profile=profile,
        runtime_root=root / "execution-runs",
        enabled=lambda: True,
        event_sink=ledger.emit,
    )
    marketplace = SkillMarketplace(
        skills_dir=str(root / "normal-skills"),
        db_path=str(root / "marketplace.db"),
    )
    kill_switch = KillSwitch(path=str(root / "kill-switch.json"))
    policy = AutonomyPolicy()

    def kernel_gate(payload: dict) -> str:
        decision = authorize(
            Action(
                kind=str(payload.get("kind", "")),
                agent="jarvis",
                title="S2 acquired capability install",
                payload=dict(payload),
                origin="generated",
            ),
            kill_switch=kill_switch,
            policy=policy,
        )
        return decision.verdict.value

    broker = PromotionBroker(
        enabled=lambda: True,
        quarantine=quarantine,
        requests=request_store,
        proposals=PromotionStore(root=root / "proposals", event_sink=ledger.emit),
        packages=packages,
        journal=PromotionJournal(root=root / "journal"),
        tool_rpc=tool_rpc,
        runtime=runtime,
        marketplace=marketplace,
        profile=profile,
        kernel_gate=kernel_gate,
        event_sink=ledger.emit,
    )

    kill_switch.engage("global", reason="S2 kernel halt proof")
    kernel_halt_blocked = False
    try:
        broker.propose(package.artifact_id, contract=contract)
    except PromotionError:
        kernel_halt_blocked = True
    finally:
        kill_switch.disengage("global")
    _require(kernel_halt_blocked, "kernel halt did not block skill.install")

    proposal = broker.propose(package.artifact_id, contract=contract)
    approval_blocked_before_owner = packages.get(package.name) is None
    try:
        await broker.promote(proposal.proposal_id)
        approval_blocked_before_owner = False
    except PromotionError:
        pass
    _require(approval_blocked_before_owner, "package installed before permanent owner approval")

    broker.decide(
        proposal.proposal_id,
        approved=True,
        actor="owner",
        permanent=True,
    )
    promoted = await broker.promote(proposal.proposal_id)
    _require(promoted.get("status") == "installed", "signed package was not promoted")
    execution = await tool_rpc.handle(
        {"tool": package.name, "args": {"items": [{"id": 1}, {"id": 2}]}}
    )
    sandbox_execution_verified = execution.get("ok") is True and execution.get("result") == [1, 2]
    _require(sandbox_execution_verified, "promoted package did not execute in real Docker")

    second_request = request_store.capture(
        request.goal,
        agent_id="jarvis",
        reason="tool_not_allowed",
    )
    reuse = resolver.resolve(
        second_request,
        [
            ReuseCandidate(
                candidate_id=f"skill:{package.name}",
                name=package.name,
                source="registry",
                description=request.goal,
                version="0.1.0",
                execution_mode="acquired_sandbox",
            )
        ],
        request_store=request_store,
    )
    _require(reuse.outcome == "reused", "second request did not reuse the acquired package")
    metrics = decisions.metrics()
    _require(metrics["reuse_rate"] == 0.5, "reuse-before-generate metric is incorrect")

    active = packages.require_runnable(package.name)
    main_path = active.path / "main.py"
    os.chmod(main_path, 0o600)
    main_path.write_bytes((package.code + "# tampered\n").encode("utf-8"))
    tampered = await tool_rpc.handle({"tool": package.name, "args": {}})
    tamper_refused = tampered.get("ok") is False and tampered.get("reason") == "tool_error"
    _require(tamper_refused, "runtime accepted a tampered signed package")
    main_path.write_bytes(package.code.encode("utf-8"))
    # The restored signed member remains immutable under its owner-only ancestor.
    # lgtm[py/overly-permissive-file]
    os.chmod(main_path, 0o400)
    _require(packages.verify(package.name), "restored package did not re-verify")

    upgrade_rollback_verified = await _prove_upgrade_rollback(
        root=root,
        profile=profile,
        contract=contract,
        request=request,
        original=package,
        original_receipt=outcome.receipt,
        signing=signing,
        ledger=ledger,
    )
    host_execution_absent, generated_network_blocked = await _prove_isolation(
        root=root,
        profile=profile,
    )

    package_outcomes = packages.get(package.name).outcomes
    registry_outcome_recorded = (
        int(package_outcomes.get("successes", 0)) >= 1
        and int(package_outcomes.get("failures", 0)) >= 1
    )
    _require(registry_outcome_recorded, "registry did not record real execution outcomes")

    revoked = await broker.revoke(package.name)
    removed = await broker.rollback(package.name)
    revoked_and_uninstalled = (
        revoked.get("status") == "revoked"
        and removed.get("status") == "uninstalled"
        and packages.get(package.name) is None
        and not tool_rpc.allows(package.name)
    )
    _require(revoked_and_uninstalled, "revoked net-new package was not unregistered and removed")
    audit_chain_valid = ledger.health().get("chain_valid") is True
    _require(audit_chain_valid, "acquisition audit chain is invalid")

    return {
        "passed": True,
        "metadata": {
            "approval_blocked_before_owner": approval_blocked_before_owner,
            "audit_chain_valid": audit_chain_valid,
            "generated_network_blocked": generated_network_blocked,
            "host_execution_absent": host_execution_absent,
            "kernel_halt_blocked": kernel_halt_blocked,
            "registry_outcome_recorded": registry_outcome_recorded,
            "reuse_rate": metrics["reuse_rate"],
            "revoked_and_uninstalled": revoked_and_uninstalled,
            "sandbox_execution_verified": sandbox_execution_verified,
            "tamper_refused": tamper_refused,
            "upgrade_rollback_verified": upgrade_rollback_verified,
        },
    }


async def _prove_upgrade_rollback(
    *,
    root: Path,
    profile,
    contract,
    request,
    original,
    original_receipt,
    signing,
    ledger,
) -> bool:
    from agents.core.acquisition.generator import StrictLocalGenerator
    from agents.core.acquisition.package_store import AcquiredPackageStore
    from agents.core.acquisition.sandbox_profile import SandboxVerifier

    async def generate_upgrade(_prompt):
        return {
            "name": original.name,
            "entrypoint": original.entrypoint,
            "code": (
                "def run(payload):\n"
                "    return sorted(item['id'] for item in payload.get('items', []))\n"
            ),
            "test": (
                "import unittest\n"
                "from main import run\n\n"
                "class UpgradeTest(unittest.TestCase):\n"
                "    def test_sorted(self):\n"
                "        self.assertEqual(run({'items': [{'id': 2}, {'id': 1}]}), [1, 2])\n"
            ),
        }

    upgrade = await StrictLocalGenerator(
        generate=generate_upgrade,
        route="strict-local",
        event_sink=ledger.emit,
    ).generate(
        request=request,
        grounded_plan={"fully_grounded": True, "source_fixture_hash": "f" * 64},
        contract=contract,
    )
    outcome = await SandboxVerifier(
        profile=profile,
        runtime_root=root / "upgrade-verification-runs",
    ).verify(package=upgrade, contract=contract)
    _require(outcome.verified and outcome.receipt is not None, "upgrade isolation proof failed")
    store = AcquiredPackageStore(
        root=root / "upgrade-packages",
        signing=signing,
        event_sink=ledger.emit,
    )
    store.install(package=original, receipt=original_receipt, version="0.1.0")
    store.install(package=upgrade, receipt=outcome.receipt, version="0.2.0")
    restored = store.rollback(original.name)
    return bool(restored and restored.version == "0.1.0" and store.verify(original.name))


async def _prove_isolation(*, root: Path, profile) -> tuple[bool, bool]:
    from agents.core.acquisition.sandbox_profile import DockerSandboxRunner

    source = root / "isolation-source"
    contract = root / "isolation-contract"
    source.mkdir()
    contract.mkdir()
    sentinel = root / "host-sentinel"
    sentinel.write_text("unchanged", encoding="utf-8")
    runner = DockerSandboxRunner(
        timeout_seconds=profile.timeout_seconds,
        max_output_bytes=profile.max_output_bytes,
    )
    host_command = profile.build_command(
        source_dir=source,
        contract_dir=contract,
        container_name="jarvis-acq-s2-host",
        command=[
            "python",
            "-I",
            "-c",
            f"import os; raise SystemExit(1 if os.path.exists({str(sentinel)!r}) else 0)",
        ],
    )
    host_result = await runner.run(host_command, container_name="jarvis-acq-s2-host")
    host_absent = host_result.exit_code == 0 and sentinel.read_text(encoding="utf-8") == "unchanged"

    network_command = profile.build_command(
        source_dir=source,
        contract_dir=contract,
        container_name="jarvis-acq-s2-network",
        command=[
            "python",
            "-I",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), 1)",
        ],
    )
    network_result = await runner.run(
        network_command,
        container_name="jarvis-acq-s2-network",
    )
    network_blocked = (
        "--network" in network_command
        and network_command[network_command.index("--network") + 1] == "none"
        and network_result.exit_code != 0
    )
    return host_absent, network_blocked


__all__ = ["acquisition_s2_case"]
