"""Sandbox-only runtime for signed acquired capability packages."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from .package_store import AcquiredPackageStore, PackageStoreError
from .sandbox_profile import AcquisitionSandboxProfile, DockerSandboxRunner

_RESULT_PREFIX = "JARVIS_ACQUIRED_RESULT:"


class AcquiredSandboxRunner:
    def __init__(
        self,
        *,
        packages: AcquiredPackageStore,
        profile: AcquisitionSandboxProfile,
        runtime_root: str | Path,
        enabled=lambda: False,
        runner=None,
        max_input_bytes: int = 64 * 1024,
    ) -> None:
        self.packages = packages
        self.profile = profile
        self.runtime_root = Path(runtime_root)
        self.enabled = enabled
        self.runner = runner or DockerSandboxRunner(
            timeout_seconds=profile.timeout_seconds,
            max_output_bytes=profile.max_output_bytes,
        )
        self.max_input_bytes = max(1024, min(1024 * 1024, int(max_input_bytes)))

    async def run(self, name: str, args: dict):
        try:
            active = self.enabled() is True
        except Exception:
            active = False
        if not active:
            raise PackageStoreError("acquired capability runtime is disabled")
        if not isinstance(args, dict):
            raise PackageStoreError("acquired capability input must be an object")
        try:
            payload = json.dumps(args, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PackageStoreError("acquired capability input must be JSON serializable") from exc
        if len(payload) > self.max_input_bytes:
            raise PackageStoreError("acquired capability input byte cap exceeded")

        try:
            record = self.packages.require_runnable(name)
            if (
                record.manifest.get("runtime_image") != self.profile.image
                or record.manifest.get("runtime_config_hash") != self.profile.config_hash
            ):
                raise PackageStoreError("acquired runtime attestation mismatch")
        except PackageStoreError:
            with self._suppress_outcome_error():
                self.packages.record_outcome(name, success=False)
            raise

        self.runtime_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="acq-run-", dir=self.runtime_root) as temporary:
            contract = Path(temporary) / "contract"
            contract.mkdir()
            self._write(contract / "input.json", payload)
            self._write(
                contract / "invoke.py",
                self._invocation_source(record.manifest["entrypoint"]).encode("utf-8"),
            )
            os.chmod(contract, 0o555)  # nosec B103
            container_name = f"jarvis-acq-run-{uuid.uuid4().hex[:12]}"
            command = self.profile.build_command(
                source_dir=record.path,
                contract_dir=contract,
                container_name=container_name,
                command=["python", "-I", "/workspace/contract/invoke.py"],
            )
            result = await self.runner.run(command, container_name=container_name)

        if result.timed_out or result.exit_code != 0:
            self.packages.record_outcome(name, success=False)
            reason = "timed out" if result.timed_out else "sandbox execution failed"
            raise PackageStoreError(f"acquired capability {reason}")
        envelope = self._parse_output(result.stdout)
        if envelope.get("ok") is not True:
            self.packages.record_outcome(name, success=False)
            raise PackageStoreError("acquired capability returned invalid result")
        self.packages.record_outcome(name, success=True)
        return envelope.get("result")

    @staticmethod
    def _invocation_source(entrypoint: str) -> str:
        return (
            "import contextlib\n"
            "import importlib.util\n"
            "import io\n"
            "import json\n\n"
            "payload = json.loads(open('/workspace/contract/input.json', encoding='utf-8').read())\n"
            "spec = importlib.util.spec_from_file_location('acquired_main', '/workspace/source/main.py')\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            f"entrypoint = getattr(module, {entrypoint!r})\n"
            "with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):\n"
            "    result = entrypoint(payload)\n"
            f"print({_RESULT_PREFIX!r} + json.dumps({{'ok': True, 'result': result}}, separators=(',', ':')))\n"
        )

    @staticmethod
    def _parse_output(stdout: str) -> dict:
        matches = [line for line in str(stdout or "").splitlines() if line.startswith(_RESULT_PREFIX)]
        if len(matches) != 1:
            raise PackageStoreError("acquired capability output envelope missing")
        try:
            value = json.loads(matches[0][len(_RESULT_PREFIX) :])
        except json.JSONDecodeError as exc:
            raise PackageStoreError("acquired capability output envelope invalid") from exc
        if not isinstance(value, dict):
            raise PackageStoreError("acquired capability output envelope invalid")
        return value

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.write_bytes(content)
        os.chmod(path, 0o444)

    @staticmethod
    def _suppress_outcome_error():
        from contextlib import suppress

        return suppress(Exception)


__all__ = ["AcquiredSandboxRunner"]
