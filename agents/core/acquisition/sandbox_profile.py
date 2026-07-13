"""Hard-floor Docker verification profile for generated capability packages."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from agents.core.environments.output_limits import read_capped_stream, render_capped, truncate_text

from .generator import CapabilityContract, GeneratedPackage
from .quarantine import QuarantineError
from .receipt import VerificationReceipt, canonical_hash, make_receipt

_IMAGE = re.compile(r"[^\s@]+@sha256:[a-f0-9]{64}")
_CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}")


class SandboxProfileError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SandboxExecution:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration: float

    @property
    def output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    verified: bool
    reason: str
    receipt: VerificationReceipt | None = None
    approval_candidate: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionSandboxProfile:
    image: str
    memory_mb: int = 128
    cpus: float = 0.5
    pids_limit: int = 32
    timeout_seconds: float = 30.0
    max_output_bytes: int = 32 * 1024
    tmpfs_mb: int = 16
    uid: int = 65532
    gid: int = 65532

    def __post_init__(self) -> None:
        if _IMAGE.fullmatch(str(self.image or "").strip()) is None:
            raise SandboxProfileError("sandbox image must be pinned by sha256 digest")
        if not 32 <= int(self.memory_mb) <= 1024:
            raise SandboxProfileError("sandbox memory is outside hard bounds")
        if not 0.1 <= float(self.cpus) <= 2.0:
            raise SandboxProfileError("sandbox CPU is outside hard bounds")
        if not 8 <= int(self.pids_limit) <= 64:
            raise SandboxProfileError("sandbox pid limit is outside hard bounds")
        if not 1.0 <= float(self.timeout_seconds) <= 300.0:
            raise SandboxProfileError("sandbox timeout is outside hard bounds")
        if not 1024 <= int(self.max_output_bytes) <= 1024 * 1024:
            raise SandboxProfileError("sandbox output cap is outside hard bounds")
        if not 4 <= int(self.tmpfs_mb) <= 64:
            raise SandboxProfileError("sandbox tmpfs is outside hard bounds")

    @property
    def config_hash(self) -> str:
        return canonical_hash(asdict(self))

    def require_backend(self, backend: str) -> None:
        value = str(backend or "").strip().lower()
        if value == "subprocess-host":
            raise SandboxProfileError("host execution is forbidden for acquired capabilities")
        if value not in {"docker", "wasm"}:
            raise SandboxProfileError("isolated Docker/WASM backend required")

    def build_command(
        self,
        *,
        source_dir: str | Path,
        contract_dir: str | Path,
        container_name: str,
        command: list[str],
        mutate_contract: bool = False,
    ) -> list[str]:
        if _CONTAINER.fullmatch(str(container_name or "")) is None:
            raise SandboxProfileError("invalid sandbox container name")
        if not command or any(not isinstance(value, str) or not value for value in command):
            raise SandboxProfileError("bounded sandbox command required")
        source = self._mount_dir(source_dir, "source")
        contract = self._mount_dir(contract_dir, "contract")
        container_tmp = PurePosixPath("/", "tmp").as_posix()
        docker = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--user",
            f"{self.uid}:{self.gid}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--memory",
            f"{self.memory_mb}m",
            "--memory-swap",
            f"{self.memory_mb}m",
            "--cpus",
            str(self.cpus),
            "--pids-limit",
            str(self.pids_limit),
            "--tmpfs",
            f"{container_tmp}:rw,noexec,nosuid,size={self.tmpfs_mb}m",
            "--tmpfs",
            f"/workspace/scratch:rw,noexec,nosuid,size={self.tmpfs_mb}m",
            "--mount",
            f"type=bind,source={source},target=/workspace/source,readonly",
            "--mount",
            f"type=bind,source={contract},target=/workspace/contract,readonly",
            "--workdir",
            "/workspace/source",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONHASHSEED=0",
        ]
        sandbox_command = list(command)
        if mutate_contract:
            sandbox_command.append("--jarvis-mutate-contract")
        return [*docker, self.image, *sandbox_command]

    @staticmethod
    def _mount_dir(value: str | Path, label: str) -> Path:
        path = Path(value)
        if path.is_symlink() or not path.is_dir():
            raise SandboxProfileError(f"sandbox {label} mount must be a real directory")
        return path.resolve()


class DockerSandboxRunner:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 32 * 1024,
        spawn: Callable[..., object] = asyncio.create_subprocess_exec,
        kill_container: Callable[[str], object] | None = None,
    ) -> None:
        self.timeout_seconds = max(0.001, float(timeout_seconds))
        self.max_output_bytes = max(1024, int(max_output_bytes))
        self._spawn = spawn
        self._kill_container = kill_container or self._default_kill_container

    async def run(self, command: list[str], *, container_name: str) -> SandboxExecution:
        started = time.monotonic()
        try:
            process = await self._spawn(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as exc:
            return SandboxExecution(-1, "", type(exc).__name__, False, time.monotonic() - started)
        try:
            stdout, stderr = await asyncio.wait_for(
                self._read_output(process),
                timeout=self.timeout_seconds,
            )
            return SandboxExecution(
                int(process.returncode or 0),
                stdout,
                stderr,
                False,
                time.monotonic() - started,
            )
        except TimeoutError:
            await self._terminate(process, container_name)
            return SandboxExecution(
                -1,
                "",
                f"Execution timed out after {self.timeout_seconds}s",
                True,
                time.monotonic() - started,
            )
        except asyncio.CancelledError:
            await self._terminate(process, container_name)
            raise
        except Exception as exc:
            await self._terminate(process, container_name)
            return SandboxExecution(
                -1,
                "",
                type(exc).__name__,
                False,
                time.monotonic() - started,
            )

    async def _read_output(self, process) -> tuple[str, str]:
        if getattr(process, "stdout", None) is None and getattr(process, "stderr", None) is None:
            result = await process.communicate()
            stdout_raw, stderr_raw = result if result is not None else (b"", b"")
            return (
                truncate_text(
                    (stdout_raw or b"").decode("utf-8", errors="replace"),
                    max_content_bytes=self.max_output_bytes,
                    label="OUTPUT",
                ).text,
                truncate_text(
                    (stderr_raw or b"").decode("utf-8", errors="replace"),
                    max_content_bytes=self.max_output_bytes,
                    label="ERROR",
                ).text,
            )

        async def drain(stream, label):
            if stream is None:
                return ""
            head, tail, total = await read_capped_stream(
                stream,
                max_content_bytes=self.max_output_bytes,
            )
            return render_capped(
                head,
                tail,
                total,
                max_content_bytes=self.max_output_bytes,
                label=label,
            ).text

        stdout, stderr = await asyncio.gather(
            drain(getattr(process, "stdout", None), "OUTPUT"),
            drain(getattr(process, "stderr", None), "ERROR"),
        )
        await process.wait()
        return stdout, stderr

    async def _terminate(self, process, container_name: str) -> None:
        with suppress(Exception):
            process.kill()
        with suppress(Exception):
            await process.wait()
        with suppress(Exception):
            result = self._kill_container(container_name)
            if asyncio.iscoroutine(result):
                await result

    @staticmethod
    async def _default_kill_container(container_name: str) -> None:
        try:
            killer = await asyncio.create_subprocess_exec(
                "docker",
                "kill",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        except (FileNotFoundError, OSError):
            return


class SandboxVerifier:
    def __init__(
        self,
        *,
        profile: AcquisitionSandboxProfile,
        runner: object | None = None,
        runtime_root: str | Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.profile = profile
        self.runner = runner or DockerSandboxRunner(
            timeout_seconds=profile.timeout_seconds,
            max_output_bytes=profile.max_output_bytes,
        )
        self.runtime_root = Path(runtime_root)
        self.clock = clock

    async def verify_quarantined(
        self,
        *,
        store,
        artifact_id: str,
        contract: CapabilityContract,
    ) -> VerificationOutcome:
        """Verify only an encrypted quarantine record and persist its terminal proof."""
        try:
            record = store.get_record(artifact_id)
        except QuarantineError:
            return VerificationOutcome(False, "quarantine is tampered or unreadable")
        if record is None or record.status != "quarantined":
            return VerificationOutcome(False, "quarantined artifact is missing or not eligible")
        outcome = await self.verify(package=record.package, contract=contract)
        if outcome.verified and outcome.receipt is not None:
            store.transition(artifact_id, "verified", receipt=asdict(outcome.receipt))
        else:
            store.transition(artifact_id, "rejected")
        return outcome

    async def verify(
        self,
        *,
        package: GeneratedPackage,
        contract: CapabilityContract,
    ) -> VerificationOutcome:
        if not self._package_is_current(package, contract):
            return VerificationOutcome(False, "package or contract hash is tampered")
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        started = float(self.clock())
        with tempfile.TemporaryDirectory(prefix="acq-verify-", dir=self.runtime_root) as temporary:
            root = Path(temporary)
            source = root / "source"
            contract_dir = root / "contract"
            source.mkdir()
            contract_dir.mkdir()
            self._write_private(source / "main.py", package.code)
            self._write_private(source / "test_generated.py", package.test_code)
            self._write_private(contract_dir / "contract_test.py", self.contract_test_source(contract))
            # Both directories are read-only bind mounts for the isolated non-host UID.
            # lgtm[py/overly-permissive-file]
            os.chmod(source, 0o555)  # nosec B103
            # lgtm[py/overly-permissive-file]
            os.chmod(contract_dir, 0o555)  # nosec B103

            prefix = f"jarvis-acq-{package.artifact_id[:10]}"
            generated = await self._run(
                source,
                contract_dir,
                f"{prefix}-generated",
                ["python", "-I", "-m", "unittest", "discover", "-s", "/workspace/source", "-p", "test_generated.py"],
            )
            if generated.timed_out:
                return VerificationOutcome(False, "generated tests timed out")
            if generated.exit_code != 0:
                return VerificationOutcome(False, "generated tests failed")

            contract_result = await self._run(
                source,
                contract_dir,
                f"{prefix}-contract",
                ["python", "-I", "/workspace/contract/contract_test.py"],
            )
            if contract_result.timed_out:
                return VerificationOutcome(False, "contract test timed out")
            if contract_result.exit_code != 0:
                return VerificationOutcome(False, "system-owned contract test failed")

            mutation = await self._run(
                source,
                contract_dir,
                f"{prefix}-mutation",
                ["python", "-I", "/workspace/contract/contract_test.py"],
                mutate=True,
            )
            if mutation.timed_out:
                return VerificationOutcome(False, "anti-vacuity mutation timed out")
            if mutation.exit_code == 0:
                return VerificationOutcome(False, "anti-vacuity mutation survived")
            if (
                (source / "main.py").is_symlink()
                or (source / "test_generated.py").is_symlink()
                or hashlib.sha256((source / "main.py").read_bytes()).hexdigest()
                != package.source_hash
                or hashlib.sha256((source / "test_generated.py").read_bytes()).hexdigest()
                != package.test_hash
            ):
                return VerificationOutcome(False, "sandbox source changed during verification")

            receipt = make_receipt(
                package=package,
                contract=contract,
                profile=self.profile,
                generated_test_output=generated.output,
                contract_output=contract_result.output,
                mutation_output=mutation.output,
                generated_test_exit=generated.exit_code,
                contract_exit=contract_result.exit_code,
                mutation_exit=mutation.exit_code,
                started_at=started,
                finished_at=float(self.clock()),
            )
            return VerificationOutcome(
                True,
                "isolated verification passed",
                receipt=receipt,
                approval_candidate={
                    "artifact_id": package.artifact_id,
                    "package_hash": package.package_hash,
                    "receipt_hash": receipt.receipt_hash,
                },
            )

    async def _run(
        self,
        source: Path,
        contract: Path,
        name: str,
        command: list[str],
        *,
        mutate: bool = False,
    ) -> SandboxExecution:
        docker = self.profile.build_command(
            source_dir=source,
            contract_dir=contract,
            container_name=name,
            command=command,
            mutate_contract=mutate,
        )
        return await self.runner.run(docker, container_name=name)

    @staticmethod
    def contract_test_source(contract: CapabilityContract) -> str:
        payload = json.dumps(asdict(contract), ensure_ascii=False, separators=(",", ":"))
        return (
            "import importlib.util\n"
            "import json\n"
            "import sys\n\n"
            f"CONTRACT = json.loads({payload!r})\n"
            "spec = importlib.util.spec_from_file_location('acquired_main', '/workspace/source/main.py')\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "entrypoint = getattr(module, CONTRACT['entrypoint'])\n"
            "if '--jarvis-mutate-contract' in sys.argv[1:]:\n"
            f"    entrypoint = lambda _payload: {{'__jarvis_forced_mutation__': '{contract.contract_hash}'}}\n"
            "for case in CONTRACT['cases']:\n"
            "    actual = entrypoint(case['input'])\n"
            "    if actual != case['expected']:\n"
            "        raise AssertionError(f\"contract mismatch: {actual!r}\")\n"
            "print('SYSTEM_CONTRACT_OK')\n"
        )

    @staticmethod
    def _package_is_current(package: GeneratedPackage, contract: CapabilityContract) -> bool:
        source_hash = hashlib.sha256(package.code.encode("utf-8")).hexdigest()
        test_hash = hashlib.sha256(package.test_code.encode("utf-8")).hexdigest()
        return (
            package.source_hash == source_hash
            and package.test_hash == test_hash
            and package.contract_hash == contract.contract_hash
            and package.package_hash == canonical_hash(package.canonical_members())
            and package.model_route == "strict-local"
        )

    @staticmethod
    def _write_private(path: Path, content: str) -> None:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        # Transient bind-mounted source is readable by the sandbox's non-host UID,
        # but the mount itself is read-only and the entire directory is deleted
        # immediately after verification.
        # lgtm[py/overly-permissive-file]
        os.chmod(path, 0o444)


__all__ = [
    "AcquisitionSandboxProfile",
    "DockerSandboxRunner",
    "SandboxExecution",
    "SandboxProfileError",
    "SandboxVerifier",
    "VerificationOutcome",
]
