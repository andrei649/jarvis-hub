"""Signed acquired-package store that is permanently sandbox-only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

from .generator import STDLIB_ALLOWLIST, GeneratedPackage
from .managed_signing import ManagedSignature, ManagedSigningKeyStore, SigningError
from .receipt import VerificationReceipt, receipt_matches_package

_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")
_PACKAGE_FILES = ("main.py", "test_generated.py")


class PackageStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AcquiredRecord:
    name: str
    version: str
    package_hash: str
    relative_path: str
    path: Path
    manifest: dict
    signature: ManagedSignature
    execution_mode: str
    status: str
    active: bool
    installed_at: float
    outcomes: dict[str, object]

    def catalog_metadata(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "description": f"Governed acquired capability {self.name}.",
            "author": "jarvis-acquisition",
            "execution_mode": self.execution_mode,
            "package_hash": self.package_hash,
            "receipt_hash": self.manifest["receipt_hash"],
            "runtime_image": self.manifest["runtime_image"],
            "signature": asdict(self.signature),
        }


class AcquiredPackageStore:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        signing: ManagedSigningKeyStore,
        clock=time.time,
        max_versions_per_skill: int = 3,
        max_packages: int = 256,
        max_registry_bytes: int = 16 * 1024 * 1024,
        event_sink=None,
    ) -> None:
        self.root = Path(root) if root is not None else data_path("acquisition", "packages")
        if self.root.is_symlink():
            raise PackageStoreError("acquired package root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.path = self.root / "registry.enc"
        self._cipher = SecretStore(self.root / "registry-cipher.json")
        self.signing = signing
        self.clock = clock
        self.max_versions_per_skill = max(1, min(10, int(max_versions_per_skill)))
        self.max_packages = max(1, min(10_000, int(max_packages)))
        self.max_registry_bytes = max(1024, int(max_registry_bytes))
        self._lock = threading.RLock()
        self._records: list[AcquiredRecord] | None = None
        self._event_sink = event_sink

    def install(
        self,
        *,
        package: GeneratedPackage,
        receipt: VerificationReceipt,
        version: str,
    ) -> AcquiredRecord:
        if _NAME.fullmatch(package.name) is None:
            raise PackageStoreError("acquired package name is invalid")
        version = str(version or "").strip()
        if _VERSION.fullmatch(version) is None:
            raise PackageStoreError("acquired package version is invalid")
        if not receipt_matches_package(receipt, package):
            raise PackageStoreError("verification receipt integrity mismatch")
        # Fail closed before touching the package tree if no owner-managed key exists.
        try:
            self.signing.active_identity()
        except SigningError as exc:
            raise PackageStoreError("managed signing key required") from exc

        installed_at = float(self.clock())
        files = [
            {
                "path": "main.py",
                "mode": 0o400,
                "size": len(package.code.encode("utf-8")),
                "sha256": package.source_hash,
            },
            {
                "path": "test_generated.py",
                "mode": 0o400,
                "size": len(package.test_code.encode("utf-8")),
                "sha256": package.test_hash,
            },
        ]
        manifest = {
            "schema": 1,
            "name": package.name,
            "version": version,
            "artifact_id": package.artifact_id,
            "request_id": package.request_id,
            "package_hash": package.package_hash,
            "entrypoint": package.entrypoint,
            "tests": ["test_generated.py"],
            "files": files,
            "stdlib_policy": list(STDLIB_ALLOWLIST),
            "execution_mode": "acquired_sandbox",
            "plan_hash": package.plan_hash,
            "goal_hash": package.goal_hash,
            "contract_hash": package.contract_hash,
            "model_route": package.model_route,
            "receipt_hash": receipt.receipt_hash,
            "runtime_image": receipt.runtime_image,
            "runtime_config_hash": receipt.runtime_config_hash,
            "generated_at": package.generated_at,
            "installed_at": installed_at,
        }
        try:
            signature = self.signing.sign(manifest)
        except SigningError as exc:
            raise PackageStoreError("managed signing failed") from exc

        relative = Path(package.name) / f"{version}-{package.package_hash[:12]}"
        target = (self.root / relative).resolve()
        self._require_inside(target)
        with self._lock:
            records = self._load()
            existing = next(
                (
                    row
                    for row in records
                    if row.name == package.name and row.package_hash == package.package_hash
                ),
                None,
            )
            if existing is not None and self._verify_record(existing):
                return existing
            if len(records) >= self.max_packages:
                raise PackageStoreError("acquired package capacity reached")

            temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=self.root)).resolve()
            try:
                self._write(temporary / "main.py", package.code.encode("utf-8"))
                self._write(
                    temporary / "test_generated.py",
                    package.test_code.encode("utf-8"),
                )
                self._write(
                    temporary / "ACQUIRED_SANDBOX_ONLY",
                    b"execution_mode=acquired_sandbox\n",
                )
                self._write(
                    temporary / "manifest.json",
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                )
                self._write(
                    temporary / "signature.json",
                    json.dumps(asdict(signature), sort_keys=True, separators=(",", ":")).encode("utf-8"),
                )
                # The permanent store is owner-only. Runtime execution uses a separately
                # verified ephemeral projection, never this directory as a bind mount.
                os.chmod(temporary, 0o700)  # nosec B103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    self._remove_tree(target)
                os.replace(temporary, target)
                temporary = None
            except OSError as exc:
                raise PackageStoreError("cannot atomically install acquired package") from exc
            finally:
                if temporary is not None:
                    shutil.rmtree(temporary, ignore_errors=True)

            updated = [
                replace(row, active=False, status="retained")
                if row.name == package.name and row.active
                else row
                for row in records
            ]
            record = AcquiredRecord(
                name=package.name,
                version=version,
                package_hash=package.package_hash,
                relative_path=relative.as_posix(),
                path=target,
                manifest=manifest,
                signature=signature,
                execution_mode="acquired_sandbox",
                status="active",
                active=True,
                installed_at=installed_at,
                outcomes=self._empty_outcomes(),
            )
            updated.append(record)
            updated = self._prune(updated, package.name)
            try:
                self._commit(updated)
            except Exception:
                self._remove_tree(target)
                raise
            self._emit(
                "signature.created",
                package=package,
                status="signed",
                details={
                    "manifest_hash": signature.manifest_hash,
                    "key_id": signature.key_id,
                    "key_version": signature.key_version,
                },
            )
            self._emit(
                "install.committed",
                package=package,
                status="installed",
                details={
                    "package_hash": package.package_hash,
                    "version": version,
                    "execution_mode": "acquired_sandbox",
                },
            )
            return record

    def get(self, name: str) -> AcquiredRecord | None:
        token = str(name or "").strip()
        with self._lock:
            return next((row for row in self._load() if row.name == token and row.active), None)

    def list_records(self, *, include_retained: bool = False) -> list[AcquiredRecord]:
        with self._lock:
            rows = list(self._load())
        return rows if include_retained else [row for row in rows if row.active]

    def verify(self, name: str) -> bool:
        record = self.get(name)
        return bool(record and self._verify_record(record))

    def require_runnable(self, name: str) -> AcquiredRecord:
        record = self.get(name)
        if record is None or record.status != "active":
            raise PackageStoreError("acquired package is disabled or revoked")
        if record.execution_mode != "acquired_sandbox" or not self._verify_record(record):
            raise PackageStoreError("acquired package integrity verification failed")
        return record

    def record_outcome(self, name: str, *, success: bool) -> AcquiredRecord:
        with self._lock:
            records = self._load()
            current = next((row for row in records if row.name == name and row.active), None)
            if current is None:
                raise KeyError(name)
            outcomes = dict(current.outcomes)
            key = "successes" if success else "failures"
            outcomes[key] = int(outcomes.get(key, 0)) + 1
            total = int(outcomes.get("successes", 0)) + int(outcomes.get("failures", 0))
            outcomes["total"] = total
            outcomes["confidence"] = min(0.49, total / (total + 20.0))
            outcomes["last_outcome_at"] = float(self.clock())
            updated = replace(current, outcomes=outcomes)
            self._commit([updated if row is current else row for row in records])
            return updated

    def revoke(self, name: str) -> bool:
        return self._set_active_status(name, "revoked")

    def uninstall(self, name: str) -> bool:
        with self._lock:
            records = self._load()
            current = next((row for row in records if row.name == name and row.active), None)
            if current is None:
                return False
            self._remove_tree(current.path)
            self._commit([row for row in records if row is not current])
            return True

    def rollback(self, name: str) -> AcquiredRecord | None:
        with self._lock:
            records = self._load()
            current = next((row for row in records if row.name == name and row.active), None)
            prior = next(
                (
                    row
                    for row in reversed(records)
                    if row.name == name and not row.active and row.status == "retained"
                ),
                None,
            )
            if prior is None or not self._verify_record(prior):
                return None
            updated_prior = replace(prior, active=True, status="active")
            updated = []
            for row in records:
                if row is prior:
                    updated.append(updated_prior)
                elif row is current:
                    updated.append(replace(row, active=False, status="retained"))
                else:
                    updated.append(row)
            self._commit(updated)
            return updated_prior

    def _set_active_status(self, name: str, status: str) -> bool:
        with self._lock:
            records = self._load()
            current = next((row for row in records if row.name == name and row.active), None)
            if current is None:
                return False
            updated = replace(current, status=status)
            self._commit([updated if row is current else row for row in records])
            return True

    def _verify_record(self, record: AcquiredRecord) -> bool:
        try:
            path = record.path.resolve()
            self._require_inside(path)
            if path.is_symlink() or not path.is_dir():
                return False
            if record.execution_mode != "acquired_sandbox":
                return False
            if record.manifest.get("execution_mode") != "acquired_sandbox":
                return False
            if record.package_hash != record.manifest.get("package_hash"):
                return False
            if not self.signing.verify(record.manifest, record.signature):
                return False
            files = record.manifest.get("files")
            if not isinstance(files, list) or {row.get("path") for row in files} != set(_PACKAGE_FILES):
                return False
            for member in files:
                if set(member) != {"path", "mode", "size", "sha256"}:
                    return False
                target = path / member["path"]
                if target.is_symlink() or not target.is_file():
                    return False
                raw = target.read_bytes()
                if len(raw) != int(member["size"]):
                    return False
                if hashlib.sha256(raw).hexdigest() != member["sha256"]:
                    return False
            marker = path / "ACQUIRED_SANDBOX_ONLY"
            return marker.is_file() and not marker.is_symlink()
        except (OSError, ValueError, TypeError, KeyError, SigningError):
            return False

    def _load(self) -> list[AcquiredRecord]:
        if self._records is not None:
            return self._records
        if not self.path.exists():
            self._records = []
            return self._records
        if self.path.is_symlink():
            raise PackageStoreError("acquired package registry cannot be a symlink")
        try:
            payload = json.loads(self._cipher.decrypt_bytes(self.path.read_bytes()).decode("utf-8"))
            if payload.get("schema") != 1 or not isinstance(payload.get("records"), list):
                raise ValueError("invalid acquired registry schema")
            records = []
            for item in payload["records"]:
                signature = ManagedSignature(**item["signature"])
                relative = Path(item["relative_path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("invalid acquired package path")
                target = (self.root / relative).resolve()
                self._require_inside(target)
                records.append(
                    AcquiredRecord(
                        name=str(item["name"]),
                        version=str(item["version"]),
                        package_hash=str(item["package_hash"]),
                        relative_path=relative.as_posix(),
                        path=target,
                        manifest=dict(item["manifest"]),
                        signature=signature,
                        execution_mode=str(item["execution_mode"]),
                        status=str(item["status"]),
                        active=bool(item["active"]),
                        installed_at=float(item["installed_at"]),
                        outcomes=dict(item["outcomes"]),
                    )
                )
            if len(records) > self.max_packages:
                raise ValueError("acquired package count exceeds capacity")
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            SecretStoreError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            raise PackageStoreError("cannot decrypt or validate acquired registry") from exc
        self._records = records
        return records

    def _commit(self, records: list[AcquiredRecord]) -> None:
        serializable = []
        for record in records:
            item = asdict(record)
            item.pop("path", None)
            serializable.append(item)
        raw = json.dumps(
            {"schema": 1, "records": serializable},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(raw) > self.max_registry_bytes:
            raise PackageStoreError("acquired package registry capacity reached")
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".registry-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise PackageStoreError("cannot atomically commit acquired registry") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._records = records

    def _prune(self, records: list[AcquiredRecord], name: str) -> list[AcquiredRecord]:
        matching = [row for row in records if row.name == name]
        if len(matching) <= self.max_versions_per_skill:
            return records
        keep = {id(row) for row in matching[-self.max_versions_per_skill :]}
        pruned = []
        for row in records:
            if row.name == name and id(row) not in keep:
                self._remove_tree(row.path)
            else:
                pruned.append(row)
        return pruned

    def _require_inside(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise PackageStoreError("acquired package path escapes store") from exc

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.write_bytes(content)
        os.chmod(path, 0o400)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        if not path.exists():
            return

        def retry(function, value, _error):
            with suppress(OSError):
                # Owner-only access is the least privilege that still permits cleanup.
                # lgtm[py/overly-permissive-file]
                os.chmod(value, 0o700)  # nosec B103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
                function(value)

        shutil.rmtree(path, onerror=retry)

    @staticmethod
    def _empty_outcomes() -> dict[str, object]:
        return {
            "successes": 0,
            "failures": 0,
            "total": 0,
            "confidence": 0.0,
            "last_outcome_at": None,
        }

    def _emit(self, event_type: str, *, package: GeneratedPackage, status: str, details: dict) -> None:
        if self._event_sink is not None:
            self._event_sink(
                event_type,
                actor="acquired-package-store",
                request_id=package.request_id,
                artifact_id=package.artifact_id,
                status=status,
                details=details,
            )


__all__ = ["AcquiredPackageStore", "AcquiredRecord", "PackageStoreError"]
