"""H32.4 — strict-local generation, encrypted quarantine, isolated verification."""

from __future__ import annotations

import asyncio
import os
import stat
from dataclasses import FrozenInstanceError, replace

import pytest

from agents.core.acquisition.generator import (
    CapabilityContract,
    ContractCase,
    GenerationError,
    StrictLocalGenerator,
)
from agents.core.acquisition.quarantine import QuarantineError, QuarantineStore
from agents.core.acquisition.receipt import receipt_is_current
from agents.core.acquisition.sandbox_profile import (
    AcquisitionSandboxProfile,
    DockerSandboxRunner,
    SandboxExecution,
    SandboxProfileError,
    SandboxVerifier,
)
from agents.core.acquisition.store import CapabilityRequestStore

PINNED_IMAGE = "python:3.12-slim@sha256:" + "a" * 64


def _request(tmp_path):
    return CapabilityRequestStore(root=tmp_path / "requests").capture(
        "parse Acme API items into a normalized list",
        agent_id="jarvis",
        reason="tool_not_allowed",
    )


def _contract():
    return CapabilityContract(
        goal="parse Acme API items into a normalized list",
        entrypoint="run",
        cases=(
            ContractCase(
                input={"items": [{"id": 1}, {"id": 2}]},
                expected=[1, 2],
            ),
        ),
    )


def _payload(**overrides):
    payload = {
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
    payload.update(overrides)
    return payload


async def _generate(_prompt):
    return _payload()


@pytest.mark.asyncio
async def test_generator_is_strict_local_requires_system_contract_and_never_writes_repo_skills(
    tmp_path, monkeypatch
):
    request = _request(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    generator = StrictLocalGenerator(generate=_generate, route="strict-local")

    package = await generator.generate(
        request=request,
        grounded_plan={"fully_grounded": True, "steps": [{"citations": [{"content_hash": "b" * 64}]}]},
        contract=_contract(),
    )

    assert package.entrypoint == "run"
    assert package.model_route == "strict-local"
    assert package.plan_hash and package.package_hash
    assert not (repo / "skills").exists()

    with pytest.raises(GenerationError, match="system-owned contract"):
        await generator.generate(request=request, grounded_plan={"fully_grounded": True}, contract=None)
    with pytest.raises(GenerationError, match="strict-local"):
        await StrictLocalGenerator(generate=_generate, route="cloud").generate(
            request=request, grounded_plan={"fully_grounded": True}, contract=_contract()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,reason",
    [
        (_payload(code="import requests\ndef run(payload): return payload\n"), "stdlib allowlist"),
        (_payload(code="import socket\ndef run(payload): return payload\n"), "stdlib allowlist"),
        (_payload(code="def run(payload): return open('/etc/passwd').read()\n"), "forbidden"),
        (_payload(code="def other(payload): return payload\n"), "entrypoint"),
        (_payload(code="def run(payload):\n    pass\n"), "implementation"),
        (_payload(test=""), "verification test"),
        (_payload(files={"../escape.py": "x"}), "archive or path"),
        (_payload(filename="../main.py"), "archive or path"),
        (_payload(code="def run(payload):\n    return 'sk-" + "A" * 42 + "'\n"), "secret"),
    ],
)
async def test_generator_rejects_dependencies_network_secrets_placeholders_and_path_payloads(
    tmp_path, payload, reason
):
    async def generate(_prompt):
        return payload

    generator = StrictLocalGenerator(generate=generate, route="strict-local")
    with pytest.raises(GenerationError, match=reason):
        await generator.generate(
            request=_request(tmp_path),
            grounded_plan={"fully_grounded": True, "steps": []},
            contract=_contract(),
        )


@pytest.mark.asyncio
async def test_generator_enforces_code_and_test_byte_caps(tmp_path):
    async def generate(_prompt):
        return _payload(code="def run(payload):\n    return payload\n" + "#x\n" * 100)

    generator = StrictLocalGenerator(
        generate=generate,
        route="strict-local",
        max_code_bytes=64,
        max_test_bytes=128,
    )
    with pytest.raises(GenerationError, match="code byte cap"):
        await generator.generate(
            request=_request(tmp_path), grounded_plan={"fully_grounded": True}, contract=_contract()
        )


@pytest.mark.asyncio
async def test_quarantine_is_encrypted_bounded_restart_safe_and_runtime_scoped(tmp_path, monkeypatch):
    request = _request(tmp_path)
    package = await StrictLocalGenerator(generate=_generate, route="strict-local").generate(
        request=request,
        grounded_plan={"fully_grounded": True},
        contract=_contract(),
    )
    runtime_root = tmp_path / "jarvis-data" / "acquisition" / "quarantine"
    monkeypatch.setattr(
        "agents.core.acquisition.quarantine.data_path",
        lambda *_parts: runtime_root,
    )
    store = QuarantineStore()
    stored = store.put(package)

    assert store.root == runtime_root
    assert stored.status == "quarantined"
    raw = store.path.read_bytes()
    assert b"acme_item_parser" not in raw and b"def run" not in raw
    assert QuarantineStore().get(package.artifact_id).package_hash == package.package_hash

    materialized = tmp_path / "materialized"
    store.materialize(package.artifact_id, materialized)
    assert (materialized / "main.py").read_text(encoding="utf-8") == package.code
    assert (materialized / "test_generated.py").read_text(encoding="utf-8") == package.test_code

    tiny = QuarantineStore(root=tmp_path / "tiny", max_total_bytes=64)
    with pytest.raises(QuarantineError, match="capacity"):
        tiny.put(package)


def test_quarantine_rejects_symlink_materialization_and_supports_immediate_purge(tmp_path):
    store = QuarantineStore(root=tmp_path / "q")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "linked"
    try:
        target.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(QuarantineError, match="symlink"):
        store.materialize("missing", target)
    assert store.purge_all(reason="acquisition_disabled") == 0


@pytest.mark.asyncio
async def test_quarantine_expiry_and_disable_purge_remove_artifacts_immediately(tmp_path):
    now = [0.0]
    package = await StrictLocalGenerator(
        generate=_generate,
        route="strict-local",
        clock=lambda: now[0],
    ).generate(
        request=_request(tmp_path), grounded_plan={"fully_grounded": True}, contract=_contract()
    )
    store = QuarantineStore(root=tmp_path / "q", clock=lambda: now[0], retention_days=7)
    store.put(package)
    now[0] = 8 * 86_400.0
    assert store.purge_expired() == 1
    assert store.get(package.artifact_id) is None

    store.put(package)
    assert store.purge_all(reason="acquisition_disabled") == 1
    assert store.get(package.artifact_id) is None


def test_sandbox_profile_has_a_non_negotiable_isolation_floor(tmp_path):
    profile = AcquisitionSandboxProfile(image=PINNED_IMAGE)
    source = tmp_path / "source"
    contract = tmp_path / "contract"
    for path in (source, contract):
        path.mkdir()

    command = profile.build_command(
        source_dir=source,
        contract_dir=contract,
        container_name="jarvis-acq-test",
        command=["python", "-I", "/workspace/contract/contract_test.py"],
    )
    rendered = " ".join(command)
    assert "--network none" in rendered
    assert "--read-only" in command
    assert "--cap-drop ALL" in rendered
    assert "no-new-privileges" in rendered
    assert f"--user {profile.uid}:{profile.gid}" in rendered
    assert profile.uid > 0 and profile.gid > 0
    assert "--pids-limit 32" in rendered
    assert "--memory 128m" in rendered and "--memory-swap 128m" in rendered
    assert "--cpus 0.5" in rendered
    assert "--tmpfs /tmp:rw,noexec,nosuid,size=16m" in rendered
    assert "--tmpfs /workspace/scratch:rw,noexec,nosuid,size=16m" in rendered
    assert f"source={source.resolve()},target=/workspace/source,readonly" in rendered
    assert "--device" not in command and "docker.sock" not in rendered
    assert PINNED_IMAGE in command

    with pytest.raises(SandboxProfileError, match="digest"):
        AcquisitionSandboxProfile(image="python:3.12-slim")
    with pytest.raises(SandboxProfileError, match="isolated"):
        profile.require_backend("disabled")
    with pytest.raises(SandboxProfileError, match="host"):
        profile.require_backend("subprocess-host")
    with pytest.raises(SandboxProfileError, match="non-root"):
        AcquisitionSandboxProfile(image=PINNED_IMAGE, uid=0)


def test_sandbox_projection_is_owner_only_for_the_runtime_identity(tmp_path):
    profile = AcquisitionSandboxProfile(image=PINNED_IMAGE)
    source = tmp_path / "source"
    source.mkdir()
    member = source / "main.py"
    member.write_text("VALUE = 1\n", encoding="utf-8")

    profile.seal_mount(source)

    if os.name == "posix":
        assert stat.S_IMODE(source.stat().st_mode) == 0o500
        assert stat.S_IMODE(member.stat().st_mode) == 0o400


class _SequencedRunner:
    def __init__(self, results):
        self.results = list(results)
        self.commands = []

    async def run(self, command, *, container_name):
        self.commands.append((list(command), container_name))
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_system_contract_and_mutation_proof_gate_receipt_and_approval_candidate(tmp_path):
    package = await StrictLocalGenerator(generate=_generate, route="strict-local").generate(
        request=_request(tmp_path), grounded_plan={"fully_grounded": True}, contract=_contract()
    )
    runner = _SequencedRunner(
        [
            SandboxExecution(0, "generated ok", "", False, 0.1),
            SandboxExecution(0, "contract ok", "", False, 0.1),
            SandboxExecution(1, "", "mutation detected", False, 0.1),
        ]
    )
    profile = AcquisitionSandboxProfile(image=PINNED_IMAGE)
    verifier = SandboxVerifier(profile=profile, runner=runner, runtime_root=tmp_path / "runtime")
    store = QuarantineStore(root=tmp_path / "quarantine")
    store.put(package)

    outcome = await verifier.verify_quarantined(
        store=store,
        artifact_id=package.artifact_id,
        contract=_contract(),
    )

    assert outcome.verified is True
    assert outcome.receipt is not None and outcome.receipt.receipt_hash
    assert outcome.approval_candidate == {
        "artifact_id": package.artifact_id,
        "package_hash": package.package_hash,
        "receipt_hash": outcome.receipt.receipt_hash,
    }
    assert receipt_is_current(outcome.receipt, package, _contract(), profile) is True
    assert store.get_record(package.artifact_id).status == "verified"
    assert store.get_record(package.artifact_id).receipt["receipt_hash"] == outcome.receipt.receipt_hash
    with pytest.raises(FrozenInstanceError):
        outcome.receipt.package_hash = "0" * 64
    assert len(runner.commands) == 3
    assert runner.commands[2][0][-1] == "--jarvis-mutate-contract"
    assert not (tmp_path / "runtime").exists() or not any((tmp_path / "runtime").iterdir())

    tampered = replace(outcome.receipt, package_hash="0" * 64)
    assert receipt_is_current(tampered, package, _contract(), profile) is False
    tampered_package = replace(package, code=package.code + "\n# changed")
    assert receipt_is_current(outcome.receipt, tampered_package, _contract(), profile) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results,reason",
    [
        ([SandboxExecution(1, "", "bad test", False, 0.1)], "generated tests failed"),
        (
            [
                SandboxExecution(0, "ok", "", False, 0.1),
                SandboxExecution(-1, "", "timeout", True, 30.0),
            ],
            "contract test timed out",
        ),
        (
            [
                SandboxExecution(0, "ok", "", False, 0.1),
                SandboxExecution(0, "ok", "", False, 0.1),
                SandboxExecution(0, "mutation survived", "", False, 0.1),
            ],
            "anti-vacuity",
        ),
    ],
)
async def test_failed_timed_out_or_vacuous_verification_never_proposes_approval(
    tmp_path, results, reason
):
    package = await StrictLocalGenerator(generate=_generate, route="strict-local").generate(
        request=_request(tmp_path), grounded_plan={"fully_grounded": True}, contract=_contract()
    )
    verifier = SandboxVerifier(
        profile=AcquisitionSandboxProfile(image=PINNED_IMAGE),
        runner=_SequencedRunner(results),
        runtime_root=tmp_path / "runtime",
    )
    outcome = await verifier.verify(package=package, contract=_contract())
    assert outcome.verified is False
    assert reason in outcome.reason
    assert outcome.receipt is None
    assert outcome.approval_candidate is None


@pytest.mark.asyncio
async def test_missing_quarantine_artifact_never_proposes_approval(tmp_path):
    outcome = await SandboxVerifier(
        profile=AcquisitionSandboxProfile(image=PINNED_IMAGE),
        runner=_SequencedRunner([]),
        runtime_root=tmp_path / "runtime",
    ).verify_quarantined(
        store=QuarantineStore(root=tmp_path / "quarantine"),
        artifact_id="missing",
        contract=_contract(),
    )
    assert outcome.verified is False
    assert outcome.approval_candidate is None and outcome.receipt is None


@pytest.mark.asyncio
async def test_docker_runner_timeout_and_cancellation_kill_process_and_container():
    class Process:
        returncode = None

        def __init__(self):
            self.stdout = None
            self.stderr = None
            self.killed = False

        async def communicate(self):
            await asyncio.sleep(10)

        def kill(self):
            self.killed = True

        async def wait(self):
            self.returncode = -9

    processes = []
    killed = []

    async def spawn(*_command, **_kwargs):
        process = Process()
        processes.append(process)
        return process

    async def kill_container(name):
        killed.append(name)

    runner = DockerSandboxRunner(
        timeout_seconds=0.01,
        spawn=spawn,
        kill_container=kill_container,
    )
    result = await runner.run(["docker", "run"], container_name="timeout-container")
    assert result.timed_out is True
    assert processes[0].killed is True
    assert killed == ["timeout-container"]

    runner.timeout_seconds = 60
    task = asyncio.create_task(
        runner.run(["docker", "run"], container_name="cancel-container")
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[1].killed is True
    assert killed[-1] == "cancel-container"


@pytest.mark.asyncio
async def test_docker_runner_bounds_output_while_draining_the_child():
    class Process:
        returncode = 0

        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stdout.feed_data(b"x" * 100_000)
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        async def wait(self):
            return 0

    async def spawn(*_command, **_kwargs):
        return Process()

    result = await DockerSandboxRunner(
        timeout_seconds=1,
        max_output_bytes=1024,
        spawn=spawn,
    ).run(["docker", "run"], container_name="output-container")
    assert result.exit_code == 0
    assert "TRUNCATED" in result.stdout and "bytes omitted" in result.stdout
    assert len(result.stdout.encode()) < 2_000
