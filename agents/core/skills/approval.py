"""Owner-controlled approval records for external skill source."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.core.paths import data_path
from agents.core.persistence import JsonStore
from agents.core.skills.signing import source_fingerprint

_SCHEMA_VERSION = 1


class SkillApprovalStore(JsonStore):
    """Atomic path-and-source-bound owner approvals outside skill trees."""

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path or data_path("security", "skill_approvals.json"))

    def _deserialize(self, raw: Any) -> None:
        records = raw.get("approvals", {}) if isinstance(raw, dict) else {}
        self._records = records if isinstance(records, dict) else {}

    def _serialize(self) -> dict[str, Any]:
        return {"version": _SCHEMA_VERSION, "approvals": self._records}

    @staticmethod
    def _canonical_path(path: Path) -> str:
        return str(Path(path).resolve())

    @staticmethod
    def _key(canonical_path: str) -> str:
        return hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()

    def approve(self, path: Path) -> dict[str, str]:
        canonical = self._canonical_path(path)
        record = {
            "canonical_path": canonical,
            "source_fingerprint": source_fingerprint(path),
            "approved_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self._records[self._key(canonical)] = record
            self._save()
        return record

    def is_approved(self, path: Path) -> bool:
        canonical = self._canonical_path(path)
        with self._lock:
            record = self._records.get(self._key(canonical))
        if not isinstance(record, dict) or record.get("canonical_path") != canonical:
            return False
        try:
            current = source_fingerprint(path)
        except OSError:
            return False
        return record.get("source_fingerprint") == current
