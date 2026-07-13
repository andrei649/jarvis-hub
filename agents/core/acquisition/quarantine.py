"""Encrypted runtime quarantine for generated capability packages."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

from .generator import GeneratedPackage

_STATUSES = frozenset(
    {"quarantined", "verified", "rejected", "abandoned", "tampered", "promoted", "revoked"}
)
_TRANSITIONS = {
    "quarantined": frozenset({"verified", "rejected", "abandoned", "tampered"}),
    "verified": frozenset({"promoted", "rejected", "abandoned", "tampered"}),
    "promoted": frozenset({"revoked"}),
    "rejected": frozenset(),
    "abandoned": frozenset(),
    "tampered": frozenset(),
    "revoked": frozenset(),
}


class QuarantineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    package: GeneratedPackage
    status: str
    created_at: float
    updated_at: float
    expires_at: float
    receipt: dict[str, Any] | None = None


class QuarantineStore:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        clock=time.time,
        retention_days: int = 7,
        max_artifacts: int = 256,
        max_artifact_bytes: int = 256 * 1024,
        max_total_bytes: int = 32 * 1024 * 1024,
        event_sink=None,
    ) -> None:
        self.root = Path(root) if root is not None else data_path("acquisition", "quarantine")
        if self._has_symlink_component(self.root):
            raise QuarantineError("quarantine root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.path = self.root / "artifacts.enc"
        self._cipher = SecretStore(self.root / "artifact-cipher.json")
        self._clock = clock
        self._retention = max(1, int(retention_days)) * 86_400
        self._max_artifacts = max(1, int(max_artifacts))
        self._max_artifact_bytes = max(128, int(max_artifact_bytes))
        self._max_total_bytes = max(64, int(max_total_bytes))
        self._lock = threading.RLock()
        self._records: list[QuarantineRecord] | None = None
        self._event_sink = event_sink

    def put(self, package: GeneratedPackage) -> QuarantineRecord:
        if not isinstance(package, GeneratedPackage):
            raise QuarantineError("generated package required")
        self._validate_package(package)
        now = float(self._clock())
        record = QuarantineRecord(
            package=package,
            status="quarantined",
            created_at=now,
            updated_at=now,
            expires_at=now + self._retention,
        )
        with self._lock:
            records = [
                row
                for row in self._load()
                if row.package.artifact_id != package.artifact_id and row.expires_at > now
            ]
            if len(records) >= self._max_artifacts:
                raise QuarantineError("quarantine artifact capacity reached")
            self._commit([*records, record])
            self._emit(
                "quarantine.created",
                package=package,
                status=record.status,
                details={"package_hash": package.package_hash},
            )
        return record

    def get(self, artifact_id: str) -> GeneratedPackage | None:
        record = self.get_record(artifact_id)
        return record.package if record else None

    def get_record(self, artifact_id: str) -> QuarantineRecord | None:
        token = str(artifact_id or "").strip()
        with self._lock:
            record = next((row for row in self._load() if row.package.artifact_id == token), None)
            if record is not None:
                self._validate_package(record.package)
            return record

    def transition(
        self,
        artifact_id: str,
        status: str,
        *,
        receipt: dict[str, Any] | None = None,
    ) -> QuarantineRecord:
        target = str(status or "").strip().lower()
        if target not in _STATUSES:
            raise QuarantineError("invalid quarantine status")
        with self._lock:
            records = self._load()
            current = next(
                (row for row in records if row.package.artifact_id == artifact_id),
                None,
            )
            if current is None:
                raise KeyError(artifact_id)
            if target not in _TRANSITIONS[current.status]:
                raise QuarantineError("invalid quarantine transition")
            updated = replace(
                current,
                status=target,
                updated_at=float(self._clock()),
                receipt=dict(receipt) if receipt is not None else current.receipt,
            )
            self._commit([updated if row is current else row for row in records])
            event_type = (
                "sandbox.verified"
                if target == "verified"
                else "sandbox.rejected"
                if target in {"rejected", "tampered"}
                else "revocation.completed"
                if target == "revoked"
                else "quarantine.transitioned"
            )
            self._emit(
                event_type,
                package=current.package,
                status=target,
                details={
                    "from": current.status,
                    "receipt_hash": (receipt or current.receipt or {}).get("receipt_hash", ""),
                },
            )
            return updated

    def materialize(
        self,
        artifact_id: str,
        target: str | Path,
        *,
        allowed_root: str | Path | None = None,
    ) -> Path:
        destination = Path(target)
        if self._has_symlink_component(destination):
            raise QuarantineError("materialization target cannot be a symlink")
        if destination.exists():
            raise QuarantineError("materialization target must not exist")
        destination.mkdir(parents=True, exist_ok=False)
        resolved = destination.resolve()
        if allowed_root is not None:
            allowed_path = Path(allowed_root)
            if self._has_symlink_component(allowed_path):
                raise QuarantineError("materialization root cannot be a symlink")
            allowed = allowed_path.resolve()
            try:
                resolved.relative_to(allowed)
            except ValueError as exc:
                raise QuarantineError("materialization path escapes runtime root") from exc
        try:
            package = self.get(artifact_id)
            if package is None:
                raise KeyError(artifact_id)
            self._write_private(resolved / "main.py", package.code)
            self._write_private(resolved / "test_generated.py", package.test_code)
            return resolved
        except Exception:
            with suppress(OSError):
                shutil.rmtree(resolved)
            raise

    def purge(self, artifact_id: str) -> int:
        with self._lock:
            records = self._load()
            kept = [row for row in records if row.package.artifact_id != artifact_id]
            if len(kept) == len(records):
                return 0
            self._commit(kept)
            return 1

    def purge_expired(self, *, now: float | None = None) -> int:
        reference = float(self._clock() if now is None else now)
        with self._lock:
            records = self._load()
            kept = [row for row in records if row.expires_at > reference]
            removed = len(records) - len(kept)
            if removed:
                self._commit(kept)
            return removed

    def purge_all(self, *, reason: str) -> int:
        if str(reason or "").strip() not in {"acquisition_disabled", "revoked", "owner_purge"}:
            raise QuarantineError("explicit purge reason required")
        with self._lock:
            count = len(self._load())
            if count:
                self._commit([])
            return count

    def _emit(self, event_type: str, *, package: GeneratedPackage, status: str, details: dict) -> None:
        if self._event_sink is not None:
            self._event_sink(
                event_type,
                actor="quarantine",
                request_id=package.request_id,
                artifact_id=package.artifact_id,
                status=status,
                details=details,
            )

    def _load(self) -> list[QuarantineRecord]:
        if self._records is not None:
            return self._records
        if not self.path.exists():
            self._records = []
            return self._records
        if self.path.is_symlink():
            raise QuarantineError("quarantine store cannot be a symlink")
        try:
            payload = json.loads(self._cipher.decrypt_bytes(self.path.read_bytes()).decode("utf-8"))
            if payload.get("schema") != 1 or not isinstance(payload.get("records"), list):
                raise ValueError("invalid quarantine schema")
            records: list[QuarantineRecord] = []
            for item in payload["records"]:
                package = GeneratedPackage(**dict(item["package"]))
                self._validate_package(package)
                status = str(item["status"])
                if status not in _STATUSES:
                    raise ValueError("invalid quarantine status")
                records.append(
                    QuarantineRecord(
                        package=package,
                        status=status,
                        created_at=float(item["created_at"]),
                        updated_at=float(item["updated_at"]),
                        expires_at=float(item["expires_at"]),
                        receipt=dict(item["receipt"]) if item.get("receipt") is not None else None,
                    )
                )
            if len(records) > self._max_artifacts:
                raise ValueError("quarantine count exceeds capacity")
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            SecretStoreError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            raise QuarantineError("cannot decrypt or validate quarantine") from exc
        self._records = records
        return records

    def _commit(self, records: list[QuarantineRecord]) -> None:
        raw = json.dumps(
            {"schema": 1, "records": [asdict(record) for record in records]},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(raw) > self._max_total_bytes:
            raise QuarantineError("quarantine total capacity reached")
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".artifacts-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise QuarantineError("cannot atomically commit quarantine") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._records = records

    def _validate_package(self, package: GeneratedPackage) -> None:
        size = len(package.code.encode("utf-8")) + len(package.test_code.encode("utf-8"))
        if size > self._max_artifact_bytes:
            raise QuarantineError("quarantine artifact capacity reached")
        if package.source_hash != self._sha(package.code):
            raise QuarantineError("generated source hash mismatch")
        if package.test_hash != self._sha(package.test_code):
            raise QuarantineError("generated test hash mismatch")
        if package.package_hash != self._package_hash(package):
            raise QuarantineError("generated package hash mismatch")

    @staticmethod
    def _sha(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _package_hash(package: GeneratedPackage) -> str:
        import hashlib

        raw = json.dumps(
            package.canonical_members(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _write_private(path: Path, content: str) -> None:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            os.chmod(path, 0o600)
        except FileExistsError as exc:
            raise QuarantineError("materialization refuses existing files") from exc
        except OSError as exc:
            raise QuarantineError("cannot materialize quarantined package") from exc

    @staticmethod
    def _has_symlink_component(path: Path) -> bool:
        absolute = path.expanduser().absolute()
        return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


__all__ = ["QuarantineError", "QuarantineRecord", "QuarantineStore"]
