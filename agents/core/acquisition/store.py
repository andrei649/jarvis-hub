"""Encrypted, bounded request persistence for explicit capability misses."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError
from agents.core.security.scanner import PIIScanner, SecretScanner

from .models import CapabilityRequest, RequestEvent, RequestStatus

_ALLOWED_REASONS = {"no_registered_capability", "tool_not_allowed"}
_TERMINAL = {
    RequestStatus.INSTALLED,
    RequestStatus.REUSED,
    RequestStatus.ABANDONED,
    RequestStatus.REVOKED,
}
_TRANSITIONS = {
    RequestStatus.MISSING: {
        RequestStatus.RESEARCHING,
        RequestStatus.BLOCKED,
        RequestStatus.ABANDONED,
        RequestStatus.REUSED,
    },
    RequestStatus.RESEARCHING: {
        RequestStatus.QUARANTINED,
        RequestStatus.BLOCKED,
        RequestStatus.ABANDONED,
        RequestStatus.REUSED,
    },
    RequestStatus.QUARANTINED: {
        RequestStatus.APPROVAL_PENDING,
        RequestStatus.BLOCKED,
        RequestStatus.ABANDONED,
    },
    RequestStatus.APPROVAL_PENDING: {
        RequestStatus.INSTALLED,
        RequestStatus.BLOCKED,
        RequestStatus.ABANDONED,
    },
    RequestStatus.INSTALLED: {RequestStatus.REVOKED, RequestStatus.REUSED},
    RequestStatus.BLOCKED: {
        RequestStatus.RESEARCHING,
        RequestStatus.ABANDONED,
    },
    RequestStatus.REUSED: {RequestStatus.REVOKED},
    RequestStatus.ABANDONED: set(),
    RequestStatus.REVOKED: set(),
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class CapabilityStoreError(RuntimeError):
    """The request store cannot safely read or commit its state."""


class CapabilityRequestStore:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
        retention_days: int = 30,
        max_requests: int = 1_000,
        max_bytes: int = 16 * 1024 * 1024,
        cipher: SecretStore | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else data_path("acquisition")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "requests.enc"
        self.tombstone_path = self.root / "tombstones.jsonl"
        self._clock = clock
        self._retention_seconds = max(1, int(retention_days)) * 86_400
        self._max_requests = max(1, int(max_requests))
        self._max_bytes = max(1_024, int(max_bytes))
        self._cipher = cipher or SecretStore(self.root / "request-cipher.json")
        self._lock = threading.RLock()
        self._records: list[CapabilityRequest] | None = None
        self._secret_scanner = SecretScanner()
        self._pii_scanner = PIIScanner()

    def capture(self, goal: str, *, agent_id: str, reason: str) -> CapabilityRequest:
        if reason not in _ALLOWED_REASONS:
            raise ValueError("an explicit capability miss is required")
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 4096:
            raise ValueError("goal must be between 1 and 4096 characters")
        if not isinstance(agent_id, str) or not agent_id.strip() or len(agent_id) > 128:
            raise ValueError("agent identity must be between 1 and 128 characters")
        redacted = self._redact_goal(goal)
        fingerprint = hashlib.sha256(redacted.casefold().encode("utf-8")).hexdigest()
        now = float(self._clock())
        with self._lock:
            records = self._load()
            existing = next(
                (
                    record
                    for record in records
                    if record.fingerprint == fingerprint and record.status not in _TERMINAL
                ),
                None,
            )
            if existing is not None:
                updated = replace(
                    existing,
                    updated_at=now,
                    occurrences=existing.occurrences + 1,
                )
                candidate = [updated if row.request_id == existing.request_id else row for row in records]
                self._commit(candidate)
                return updated
            if len(records) >= self._max_requests:
                raise CapabilityStoreError("capability request capacity reached")
            event = RequestEvent(RequestStatus.MISSING, now, "runtime")
            request = CapabilityRequest(
                request_id=uuid.uuid4().hex,
                fingerprint=fingerprint,
                goal=redacted,
                agent_id=agent_id.strip(),
                reason=reason,
                status=RequestStatus.MISSING,
                created_at=now,
                updated_at=now,
                history=(event,),
            )
            self._commit([*records, request])
            return request

    def transition(
        self,
        request_id: str,
        status: RequestStatus | str,
        *,
        actor: str,
    ) -> CapabilityRequest:
        target = RequestStatus(status)
        actor = str(actor).strip()
        if not actor or len(actor) > 128:
            raise ValueError("actor must be bounded")
        with self._lock:
            records = self._load()
            current = next((row for row in records if row.request_id == request_id), None)
            if current is None:
                raise KeyError(request_id)
            if target not in _TRANSITIONS[current.status]:
                raise ValueError(f"invalid capability request transition: {current.status} -> {target}")
            now = float(self._clock())
            event = RequestEvent(target, now, actor)
            updated = replace(
                current,
                status=target,
                updated_at=now,
                history=(*current.history, event)[-64:],
            )
            self._commit([updated if row.request_id == request_id else row for row in records])
            return updated

    def get(self, request_id: str) -> CapabilityRequest | None:
        with self._lock:
            return next((row for row in self._load() if row.request_id == request_id), None)

    def list(self, *, statuses: set[RequestStatus] | None = None) -> list[CapabilityRequest]:
        with self._lock:
            rows = list(self._load())
        if statuses is not None:
            rows = [row for row in rows if row.status in statuses]
        return sorted(rows, key=lambda row: (row.updated_at, row.request_id), reverse=True)

    def purge(self, *, now: float | None = None) -> dict[str, int]:
        cutoff = float(self._clock() if now is None else now) - self._retention_seconds
        with self._lock:
            records = self._load()
            expired = [row for row in records if row.status in _TERMINAL and row.updated_at < cutoff]
            if not expired:
                return {"purged": 0, "tombstones": 0}
            for row in expired:
                self._append_tombstone(row, purged_at=float(self._clock() if now is None else now))
            expired_ids = {row.request_id for row in expired}
            self._commit([row for row in records if row.request_id not in expired_ids])
            return {"purged": len(expired), "tombstones": len(expired)}

    def _redact_goal(self, goal: str) -> str:
        cleaned = _CONTROL.sub(" ", goal)
        cleaned = self._secret_scanner.redact(cleaned)
        cleaned = self._pii_scanner.redact(cleaned)
        return " ".join(cleaned.split())[:4096]

    def _load(self) -> list[CapabilityRequest]:
        if self._records is not None:
            return self._records
        if not self.path.exists():
            self._records = []
            return self._records
        if self.path.is_symlink():
            raise CapabilityStoreError("capability request store cannot be a symlink")
        try:
            plaintext = self._cipher.decrypt_bytes(self.path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
            if payload.get("schema") != 1 or not isinstance(payload.get("requests"), list):
                raise ValueError("invalid schema")
            records = [CapabilityRequest.from_dict(value) for value in payload["requests"]]
            if len(records) > self._max_requests:
                raise ValueError("request count exceeds capacity")
        except (OSError, UnicodeError, json.JSONDecodeError, SecretStoreError, ValueError, KeyError) as exc:
            raise CapabilityStoreError("cannot decrypt or validate capability request store") from exc
        self._records = records
        return records

    def _commit(self, records: list[CapabilityRequest]) -> None:
        payload = {
            "schema": 1,
            "requests": [record.to_dict() for record in records],
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(raw) > self._max_bytes:
            raise CapabilityStoreError("capability request byte capacity reached")
        token = self._cipher.encrypt_bytes(raw)
        if self.path.is_symlink():
            raise CapabilityStoreError("capability request store cannot be a symlink")
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".requests-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise CapabilityStoreError("cannot atomically commit capability request store") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._records = records

    def _append_tombstone(self, request: CapabilityRequest, *, purged_at: float) -> None:
        if self.tombstone_path.is_symlink():
            raise CapabilityStoreError("capability tombstone log cannot be a symlink")
        record = {
            "request_hash": hashlib.sha256(request.request_id.encode("ascii")).hexdigest(),
            "fingerprint": request.fingerprint,
            "terminal_status": request.status.value,
            "purged_at": purged_at,
        }
        try:
            with self.tombstone_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            os.chmod(self.tombstone_path, 0o600)
        except OSError as exc:
            raise CapabilityStoreError("cannot append capability tombstone") from exc
