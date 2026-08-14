"""Owner-controlled approval records for external skill source."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.core.paths import data_path
from agents.core.persistence import JsonStore
from agents.core.skills.signing import SkillSourceSnapshot, source_snapshot

_SCHEMA_VERSION = 1
_LOCKS_GUARD = threading.Lock()
_REGISTRY_LOCKS: dict[str, threading.RLock] = {}


class SkillApprovalStoreError(RuntimeError):
    """Approval state cannot be safely read or merged."""


def _registry_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _REGISTRY_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _process_registry_lock(path: Path):
    """Serialize registry readers/writers across Windows and POSIX processes."""
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SkillApprovalStore(JsonStore):
    """Atomic path-and-source-bound owner approvals outside skill trees."""

    def __init__(self, path: str | Path | None = None) -> None:
        registry_path = Path(path or data_path("security", "skill_approvals.json"))
        shared_lock = _registry_lock(registry_path)
        super().__init__(registry_path)
        self._registry_lock = shared_lock

    def _deserialize(self, raw: Any) -> None:
        records = (
            raw.get("approvals", {})
            if isinstance(raw, dict) and raw.get("version") == _SCHEMA_VERSION
            else {}
        )
        self._records = records if isinstance(records, dict) else {}

    def _serialize(self) -> dict[str, Any]:
        return {"version": _SCHEMA_VERSION, "approvals": self._records}

    def _reload_locked(self) -> bool:
        """Refresh from disk; malformed or unknown state clears authority."""
        if self.path is None or not self.path.exists():
            self._records = {}
            return True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._records = {}
            return False
        if not isinstance(raw, dict) or raw.get("version") != _SCHEMA_VERSION:
            self._records = {}
            return False
        records = raw.get("approvals")
        if not isinstance(records, dict):
            self._records = {}
            return False
        self._records = records
        return True

    @staticmethod
    def _canonical_path(path: Path) -> str:
        return str(Path(path).resolve())

    @staticmethod
    def _key(canonical_path: str) -> str:
        return hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()

    def approve(self, path: Path) -> dict[str, str]:
        canonical = self._canonical_path(path)
        with self._registry_lock, _process_registry_lock(self.path):
            if not self._reload_locked():
                raise SkillApprovalStoreError(
                    "cannot merge a corrupt or unknown skill approval registry"
                )
            snapshot = source_snapshot(path)
            record = {
                "canonical_path": canonical,
                "source_fingerprint": snapshot.fingerprint,
                "approved_at": datetime.now(UTC).isoformat(),
            }
            self._records[self._key(canonical)] = record
            self._save()
        return record

    def approved_snapshot(
        self,
        path: Path,
        *,
        snapshot: SkillSourceSnapshot | None = None,
    ) -> SkillSourceSnapshot | None:
        """Return the exact approved bytes, or ``None`` on any state failure."""
        canonical = self._canonical_path(path)
        with self._registry_lock, _process_registry_lock(self.path):
            if not self._reload_locked():
                return None
            record = self._records.get(self._key(canonical))
            if (
                not isinstance(record, dict)
                or record.get("canonical_path") != canonical
            ):
                return None
            try:
                current = snapshot or source_snapshot(path)
            except OSError:
                return None
            if record.get("source_fingerprint") != current.fingerprint:
                return None
            return current

    def tracks_path(self, path: Path) -> bool:
        """Return whether private control state identifies this as external.

        Source drift is intentionally ignored here. A stale approval must keep
        the path on the external-code path; otherwise deleting an in-tree
        provenance sidecar could make changed bytes inherit bundled trust.
        """
        canonical = self._canonical_path(path)
        with self._registry_lock, _process_registry_lock(self.path):
            if not self._reload_locked():
                return False
            record = self._records.get(self._key(canonical))
            return bool(
                isinstance(record, dict)
                and record.get("canonical_path") == canonical
            )

    def is_approved(self, path: Path) -> bool:
        return self.approved_snapshot(path) is not None
