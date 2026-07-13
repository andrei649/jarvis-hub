"""H32.5 — permanent approval, managed signing, sandbox-only install and rollback."""

from __future__ import annotations

import asyncio
import os
import stat
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.acquisition.acquired_runner import AcquiredSandboxRunner
from agents.core.acquisition.audit import AcquisitionLedger
from agents.core.acquisition.generator import (
    CapabilityContract,
    ContractCase,
    StrictLocalGenerator,
)
from agents.core.acquisition.managed_signing import ManagedSigningKeyStore, SigningError
from agents.core.acquisition.package_store import AcquiredPackageStore, PackageStoreError
from agents.core.acquisition.promotion import (
    PromotionBroker,
    PromotionError,
    PromotionJournal,
    PromotionStore,
)
from agents.core.acquisition.quarantine import QuarantineStore
from agents.core.acquisition.receipt import make_receipt
from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.acquisition.sandbox_profile import (
    AcquisitionSandboxProfile,
    SandboxExecution,
)
from agents.core.acquisition.store import CapabilityRequestStore
from agents.core.autonomy.executor import TaskExecutor
from agents.core.observability.capability_registry import build_records
from agents.core.skills import loader as loader_module
from agents.core.skills.loader import SkillLoader
from agents.core.skills.marketplace import SkillMarketplace
from agents.core.tool_rpc import ToolRPCServer

PINNED_IMAGE = "python:3.12-slim@sha256:" + "a" * 64


def _contract():
    return CapabilityContract(
        goal="parse Acme API items into a normalized list",
        entrypoint="run",
        cases=(ContractCase(input={"items": [{"id": 1}]}, expected=[1]),),
    )


async def _verified_artifact(tmp_path):
    requests = CapabilityRequestStore(root=tmp_path / "requests")
    request = requests.capture(
        _contract().goal,
        agent_id="jarvis",
        reason="tool_not_allowed",
    )
    requests.transition(request.request_id, "researching", actor="research")
    requests.transition(request.request_id, "quarantined", actor="generator")

    async def generate(_prompt):
        return {
            "name": "acme_item_parser",
            "entrypoint": "run",
            "code": "def run(payload):\n    return [item['id'] for item in payload.get('items', [])]\n",
            "test": (
                "import unittest\n"
                "from main import run\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_items(self):\n"
                "        self.assertEqual(run({'items': [{'id': 2}]}), [2])\n"
            ),
        }

    package = await StrictLocalGenerator(generate=generate, route="strict-local").generate(
        request=request,
        grounded_plan={"fully_grounded": True, "source_hash": "b" * 64},
        contract=_contract(),
    )
    profile = AcquisitionSandboxProfile(image=PINNED_IMAGE)
    receipt = make_receipt(
        package=package,
        contract=_contract(),
        profile=profile,
        generated_test_output="ok",
        contract_output="ok",
        mutation_output="detected",
        generated_test_exit=0,
        contract_exit=0,
        mutation_exit=1,
        started_at=1.0,
        finished_at=2.0,
    )
    quarantine = QuarantineStore(root=tmp_path / "quarantine")
    quarantine.put(package)
    quarantine.transition(package.artifact_id, "verified", receipt=asdict(receipt))
    return requests, request, package, profile, receipt, quarantine


def test_managed_signing_fails_closed_persists_and_supports_rotation(tmp_path):
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    manifest = {"schema": 1, "files": []}
    with pytest.raises(SigningError, match="managed signing key"):
        keys.sign(manifest)

    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    signature_v1 = keys.sign(manifest)
    assert keys.verify(manifest, signature_v1) is True
    assert ManagedSigningKeyStore(root=tmp_path / "keys").verify(manifest, signature_v1) is True

    keys.rotate(key_id="owner", version=2, key=b"z" * 32)
    signature_v2 = keys.sign(manifest)
    assert signature_v2.key_version == 2
    assert keys.verify(manifest, signature_v2) is True
    assert keys.verify(manifest, signature_v1) is True
    assert keys.verify({"schema": 2, "files": []}, signature_v2) is False


def test_runtime_is_lazy_when_disabled_and_refuses_incomplete_host_binding(tmp_path):
    disabled_root = tmp_path / "disabled"
    disabled = AcquisitionRuntime(enabled=lambda: False, root=disabled_root)
    disabled.bind_promotion(tool_rpc=ToolRPCServer(), marketplace=object())

    assert disabled.ensure_promotion() is None
    assert not disabled_root.exists()

    enabled_root = tmp_path / "enabled"
    incomplete = AcquisitionRuntime(enabled=lambda: True, root=enabled_root)
    incomplete.bind_promotion(
        tool_rpc=ToolRPCServer(),
        marketplace=None,
        profile=AcquisitionSandboxProfile(image=PINNED_IMAGE),
    )

    assert incomplete.ensure_promotion() is None
    assert incomplete.promotion_broker is None
    assert not enabled_root.exists()


@pytest.mark.asyncio
async def test_package_manifest_covers_every_member_and_store_is_sandbox_only(tmp_path, monkeypatch):
    _requests, _request, package, profile, receipt, _quarantine = await _verified_artifact(tmp_path)
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    packages = AcquiredPackageStore(root=tmp_path / "packages", signing=keys)

    record = packages.install(package=package, receipt=receipt, version="0.1.0")

    assert record.execution_mode == "acquired_sandbox"
    assert packages.verify(package.name) is True
    assert record.manifest["entrypoint"] == package.entrypoint
    assert record.manifest["receipt_hash"] == receipt.receipt_hash
    assert record.manifest["runtime_image"] == profile.image
    assert record.manifest["stdlib_policy"]
    assert {row["path"] for row in record.manifest["files"]} == {
        "main.py",
        "test_generated.py",
    }
    assert all(set(row) == {"path", "mode", "size", "sha256"} for row in record.manifest["files"])
    assert (record.path / "ACQUIRED_SANDBOX_ONLY").exists()
    if os.name == "posix":
        assert stat.S_IMODE(record.path.stat().st_mode) == 0o700

    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    copied = skills_root / "unsafe"
    copied.mkdir()
    for name in ("main.py", "ACQUIRED_SANDBOX_ONLY"):
        (copied / name).write_bytes((record.path / name).read_bytes())
    (copied / "SKILL.md").write_text("# unsafe\n", encoding="utf-8")
    monkeypatch.setattr(loader_module, "SKILLS_DIR", skills_root)
    loader = SkillLoader()
    loader.discover()
    assert "unsafe" not in loader.skills

    os.chmod(record.path / "main.py", 0o600)
    (record.path / "main.py").write_text("def run(payload): return ['tampered']\n", encoding="utf-8")
    assert packages.verify(package.name) is False
    with pytest.raises(PackageStoreError, match="integrity"):
        packages.require_runnable(package.name)


@pytest.mark.asyncio
async def test_marketplace_indexes_acquired_metadata_without_in_process_install(tmp_path):
    _requests, _request, package, _profile, receipt, _quarantine = await _verified_artifact(tmp_path)
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    record = AcquiredPackageStore(root=tmp_path / "packages", signing=keys).install(
        package=package, receipt=receipt, version="0.1.0"
    )
    marketplace = SkillMarketplace(
        skills_dir=str(tmp_path / "skills"),
        db_path=str(tmp_path / "marketplace.db"),
    )

    marketplace.index_acquired_package(record.catalog_metadata())

    indexed = next(row for row in marketplace.list_skills() if row["name"] == package.name)
    assert indexed["review_status"] == "approved"
    assert indexed["execution_mode"] == "acquired_sandbox"
    assert not (tmp_path / "skills" / package.name).exists()
    with pytest.raises(PermissionError, match="sandbox broker"):
        marketplace.install_skill(package.name)


@pytest.mark.asyncio
async def test_upgrade_retains_and_restores_the_last_signed_package(tmp_path):
    _requests, request, package, profile, receipt, _quarantine = await _verified_artifact(tmp_path)
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    packages = AcquiredPackageStore(root=tmp_path / "packages", signing=keys)
    packages.install(package=package, receipt=receipt, version="0.1.0")

    async def generate_upgrade(_prompt):
        return {
            "name": package.name,
            "entrypoint": "run",
            "code": "def run(payload):\n    return sorted(item['id'] for item in payload.get('items', []))\n",
            "test": (
                "import unittest\n"
                "from main import run\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_items(self):\n"
                "        self.assertEqual(run({'items': [{'id': 2}, {'id': 1}]}), [1, 2])\n"
            ),
        }

    upgrade = await StrictLocalGenerator(
        generate=generate_upgrade,
        route="strict-local",
        clock=lambda: package.generated_at + 1,
    ).generate(
        request=request,
        grounded_plan={"fully_grounded": True, "source_hash": "c" * 64},
        contract=_contract(),
    )
    upgrade_receipt = make_receipt(
        package=upgrade,
        contract=_contract(),
        profile=profile,
        generated_test_output="ok",
        contract_output="ok",
        mutation_output="detected",
        generated_test_exit=0,
        contract_exit=0,
        mutation_exit=1,
        started_at=3.0,
        finished_at=4.0,
    )
    packages.install(package=upgrade, receipt=upgrade_receipt, version="0.2.0")
    assert packages.get(package.name).version == "0.2.0"

    restored = packages.rollback(package.name)
    assert restored is not None and restored.version == "0.1.0"
    assert packages.verify(package.name) is True


@pytest.mark.asyncio
async def test_unregister_denies_new_calls_and_cancels_inflight_handler():
    started = asyncio.Event()

    async def slow(_args):
        started.set()
        await asyncio.sleep(60)

    server = ToolRPCServer()
    server.register_tool("acquired", slow, capability_id="skill:acquired")
    task = asyncio.create_task(server.handle({"tool": "acquired", "args": {}}))
    await started.wait()

    assert await server.unregister_tool("acquired", cancel_inflight=True) is True
    assert (await server.handle({"tool": "acquired", "args": {}}))["reason"] == "tool_not_allowed"
    with pytest.raises(asyncio.CancelledError):
        await task


class _Runtime:
    def __init__(self):
        self.calls = []

    async def run(self, name, args):
        self.calls.append((name, args))
        return {"normalized": [1]}


def _broker(
    tmp_path,
    *,
    requests,
    quarantine,
    profile,
    signing=True,
    failpoint=None,
    tool_rpc=None,
    marketplace=None,
    ledger=None,
):
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    if signing:
        keys.provision(key_id="owner", version=1, key=b"k" * 32)
    packages = AcquiredPackageStore(
        root=tmp_path / "packages",
        signing=keys,
        event_sink=ledger.emit if ledger is not None else None,
    )
    server = tool_rpc or ToolRPCServer()
    market = marketplace or SkillMarketplace(
        skills_dir=str(tmp_path / "skills"),
        db_path=str(tmp_path / "marketplace.db"),
    )
    broker = PromotionBroker(
        enabled=lambda: True,
        quarantine=quarantine,
        requests=requests,
        proposals=PromotionStore(
            root=tmp_path / "proposals",
            event_sink=ledger.emit if ledger is not None else None,
        ),
        packages=packages,
        journal=PromotionJournal(root=tmp_path / "journal"),
        tool_rpc=server,
        runtime=_Runtime(),
        marketplace=market,
        profile=profile,
        kernel_gate=lambda _payload: "queue",
        failpoint=failpoint,
        event_sink=ledger.emit if ledger is not None else None,
    )
    return broker, packages, server, market


@pytest.mark.asyncio
async def test_permanent_approval_is_hard_floor_then_installs_and_registers_atomically(tmp_path):
    requests, request, package, profile, _receipt, quarantine = await _verified_artifact(tmp_path)
    ledger = AcquisitionLedger(root=tmp_path / "ledger")
    broker, packages, server, market = _broker(
        tmp_path,
        requests=requests,
        quarantine=quarantine,
        profile=profile,
        ledger=ledger,
    )

    proposal = broker.propose(package.artifact_id, contract=_contract())
    assert proposal.action_kind == "skill.install"
    assert proposal.risk_tier == 3
    assert proposal.approval_mode == "permanent"
    assert proposal.status == "pending"
    assert packages.get(package.name) is None
    assert requests.get(request.request_id).status.value == "approval_pending"
    with pytest.raises(PromotionError, match="permanent owner approval"):
        broker.decide(proposal.proposal_id, approved=True, actor="owner", permanent=False)
    with pytest.raises(PromotionError, match="owner"):
        broker.decide(proposal.proposal_id, approved=True, actor="agent", permanent=True)

    broker.decide(proposal.proposal_id, approved=True, actor="owner", permanent=True)
    result = await broker.promote(proposal.proposal_id)

    assert result["status"] == "installed"
    assert packages.verify(package.name) is True
    assert server.allows(package.name) is True
    response = await server.handle({"tool": package.name, "args": {"items": [{"id": 1}]}})
    assert response == {
        "ok": True,
        "tool": package.name,
        "result": {"normalized": [1]},
    }
    assert requests.get(request.request_id).status.value == "installed"
    assert quarantine.get_record(package.artifact_id).status == "promoted"
    assert broker.journal.get(proposal.proposal_id).stage == "committed"
    assert any(row["name"] == package.name for row in market.list_skills())

    executor = TaskExecutor()
    broker.register_executor(executor)
    assert executor.resolve("skill.install") == broker.execute_task
    assert {
        "approval.proposed",
        "approval.approved",
        "signature.created",
        "install.committed",
        "registry.registered",
    } <= {row["event_type"] for row in ledger.list_public(limit=100)}


@pytest.mark.asyncio
async def test_missing_signing_key_or_toctou_tamper_never_installs(tmp_path):
    requests, _request, package, profile, _receipt, quarantine = await _verified_artifact(tmp_path)
    broker, packages, _server, _market = _broker(
        tmp_path,
        requests=requests,
        quarantine=quarantine,
        profile=profile,
        signing=False,
    )
    proposal = broker.propose(package.artifact_id, contract=_contract())
    broker.decide(proposal.proposal_id, approved=True, actor="owner", permanent=True)
    with pytest.raises(PromotionError, match="signing"):
        await broker.promote(proposal.proposal_id)
    assert packages.get(package.name) is None

    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    record = quarantine.get_record(package.artifact_id)
    quarantine._records = [replace(record, package=replace(package, code=package.code + "# tamper\n"))]
    broker, packages, _server, _market = _broker(
        tmp_path,
        requests=requests,
        quarantine=quarantine,
        profile=profile,
    )
    with pytest.raises(PromotionError, match="receipt|integrity|tamper"):
        broker.propose(package.artifact_id, contract=_contract())
    assert packages.get(package.name) is None


class _SandboxRunner:
    def __init__(self, output):
        self.output = output
        self.commands = []
        self.source_snapshots = []

    async def run(self, command, *, container_name):
        self.commands.append((command, container_name))
        source_mount = next(
            value
            for value in command
            if value.startswith("type=bind,source=") and "target=/workspace/source" in value
        )
        source = Path(source_mount.split("source=", 1)[1].split(",target=", 1)[0])
        self.source_snapshots.append((source, (source / "main.py").read_bytes()))
        return SandboxExecution(0, self.output, "", False, 0.1)


@pytest.mark.asyncio
async def test_acquired_runtime_rechecks_signature_profile_enabled_and_records_outcomes(tmp_path):
    _requests, _request, package, profile, receipt, _quarantine = await _verified_artifact(tmp_path)
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    packages = AcquiredPackageStore(root=tmp_path / "packages", signing=keys)
    packages.install(package=package, receipt=receipt, version="0.1.0")
    runner = _SandboxRunner('JARVIS_ACQUIRED_RESULT:{"ok":true,"result":[1]}')
    runtime = AcquiredSandboxRunner(
        packages=packages,
        profile=profile,
        runner=runner,
        runtime_root=tmp_path / "runtime",
        enabled=lambda: True,
        event_sink=(ledger := AcquisitionLedger(root=tmp_path / "ledger")).emit,
    )

    assert await runtime.run(package.name, {"items": [{"id": 1}]}) == [1]
    assert packages.get(package.name).outcomes["successes"] == 1
    assert [row["event_type"] for row in reversed(ledger.list_public(limit=10))] == [
        "execution.started",
        "execution.completed",
    ]
    assert "--network" in runner.commands[0][0]
    assert runner.source_snapshots[0][0] != packages.get(package.name).path
    assert runner.source_snapshots[0][1] == package.code.encode("utf-8")
    assert runner.source_snapshots[0][0].exists() is False

    runner.output = "invalid envelope"
    with pytest.raises(PackageStoreError, match="envelope missing"):
        await runtime.run(package.name, {})
    assert ledger.list_public(limit=1)[0]["status"] == "failed"

    os.chmod(packages.get(package.name).path / "main.py", 0o600)
    (packages.get(package.name).path / "main.py").write_text("tampered", encoding="utf-8")
    with pytest.raises(PackageStoreError, match="integrity"):
        await runtime.run(package.name, {})
    assert packages.get(package.name).outcomes["failures"] == 2

    disabled = AcquiredSandboxRunner(
        packages=packages,
        profile=profile,
        runner=runner,
        runtime_root=tmp_path / "runtime-disabled",
        enabled=lambda: False,
    )
    with pytest.raises(PackageStoreError, match="disabled"):
        await disabled.run(package.name, {})


@pytest.mark.asyncio
async def test_acquired_registry_projects_real_outcomes_at_low_confidence(tmp_path):
    _requests, _request, package, _profile, receipt, _quarantine = await _verified_artifact(tmp_path)
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    packages = AcquiredPackageStore(root=tmp_path / "packages", signing=keys)
    packages.install(package=package, receipt=receipt, version="0.1.0")
    packages.record_outcome(package.name, success=True)
    orch = SimpleNamespace(
        acquisition=SimpleNamespace(package_store=packages, request_store=None),
        tool_rpc=None,
        components=None,
        skills=None,
        autonomy_queue=None,
    )
    record = next(row for row in build_records(orch) if row.id == f"skill:{package.name}")
    assert record.state == "wired"
    assert record.confidence < 0.5
    assert record.detail["outcomes"]["successes"] == 1
    assert record.detail["execution_mode"] == "acquired_sandbox"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crash_stage,expected",
    [
        ("verified", "rolled_back"),
        ("installed", "committed"),
        ("registered", "committed"),
    ],
)
async def test_restart_reconciliation_handles_every_transaction_crash_point(
    tmp_path, crash_stage, expected
):
    requests, request, package, profile, _receipt, quarantine = await _verified_artifact(tmp_path)

    def failpoint(stage):
        if stage == crash_stage:
            raise RuntimeError(f"crash:{stage}")

    broker, _packages, _server, _market = _broker(
        tmp_path,
        requests=requests,
        quarantine=quarantine,
        profile=profile,
        failpoint=failpoint,
    )
    proposal = broker.propose(package.artifact_id, contract=_contract())
    broker.decide(proposal.proposal_id, approved=True, actor="owner", permanent=True)
    with pytest.raises(RuntimeError, match="crash"):
        await broker.promote(proposal.proposal_id)

    restarted, packages, server, _market = _broker(
        tmp_path,
        requests=requests,
        quarantine=quarantine,
        profile=profile,
    )
    result = await restarted.reconcile()

    assert restarted.journal.get(proposal.proposal_id).stage == expected
    if expected == "committed":
        assert result["committed"] == 1
        assert packages.verify(package.name) is True
        assert server.allows(package.name) is True
        assert requests.get(request.request_id).status.value == "installed"
    else:
        assert result["rolled_back"] == 1
        assert packages.get(package.name) is None
        assert server.allows(package.name) is False
        assert requests.get(request.request_id).status.value == "blocked"


@pytest.mark.asyncio
async def test_revoke_and_net_new_rollback_unregister_before_disabling_package(tmp_path):
    requests, request, package, profile, _receipt, quarantine = await _verified_artifact(tmp_path)
    broker, packages, server, market = _broker(
        tmp_path,
        requests=requests,
        quarantine=quarantine,
        profile=profile,
    )
    proposal = broker.propose(package.artifact_id, contract=_contract())
    broker.decide(proposal.proposal_id, approved=True, actor="owner", permanent=True)
    await broker.promote(proposal.proposal_id)

    result = await broker.revoke(package.name)
    assert result["status"] == "revoked"
    assert server.allows(package.name) is False
    assert packages.get(package.name).status == "revoked"
    assert requests.get(request.request_id).status.value == "revoked"
    assert all(row["name"] != package.name for row in market.list_skills())

    rolled_back = await broker.rollback(package.name)
    assert rolled_back["status"] == "uninstalled"
    assert packages.get(package.name) is None
