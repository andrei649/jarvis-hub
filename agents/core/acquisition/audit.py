"""Tamper-evident, encrypted and bounded audit ledger for capability acquisition."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

_EVENT_TYPES = frozenset(
    {
        "request.created",
        "request.transitioned",
        "reuse.reused",
        "reuse.no_reuse",
        "reuse.install_approval_required",
        "reuse.generated",
        "reuse.blocked",
        "reuse.abandoned",
        "research.completed",
        "generation.completed",
        "quarantine.created",
        "quarantine.transitioned",
        "quarantine.purged",
        "sandbox.verified",
        "sandbox.rejected",
        "approval.proposed",
        "approval.approved",
        "approval.rejected",
        "signature.created",
        "install.committed",
        "registry.registered",
        "registry.unregistered",
        "execution.started",
        "execution.completed",
        "revocation.completed",
        "rollback.completed",
    }
)
_TOKEN = re.compile(r"[A-Za-z0-9_.:@/-]{1,128}")
_HASH = re.compile(r"[0-9a-f]{64}")
_ZERO_HASH = "0" * 64


class AcquisitionAuditError(RuntimeError):
    """The acquisition ledger cannot be safely read, validated, or committed."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AcquisitionAuditError("audit detail must be canonical JSON") from exc


def _hash_token(value: str) -> str:
    token = str(value or "").strip()
    return hashlib.sha256(token.encode("utf-8")).hexdigest() if token else _ZERO_HASH


@dataclass(frozen=True, slots=True)
class AcquisitionAuditEvent:
    sequence: int
    event_id: str
    event_type: str
    actor: str
    task_id: str
    request_hash: str
    artifact_hash: str
    status: str
    detail_hash: str
    occurred_at: float
    previous_hash: str
    event_hash: str

    def public(self) -> dict[str, object]:
        return asdict(self)


class AcquisitionLedger:
    """Append-only detail ledger with encrypted storage and hash-only compaction."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        clock=time.time,
        retention_days: int = 90,
        max_rows: int = 100_000,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.root = Path(root) if root is not None else data_path("acquisition", "ledger")
        if self.root.is_symlink():
            raise AcquisitionAuditError("acquisition ledger root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.path = self.root / "ledger.enc"
        self._cipher = SecretStore(self.root / "ledger-cipher.json")
        self._clock = clock
        self._retention = max(1, int(retention_days)) * 86_400
        self._max_rows = max(1, min(100_000, int(max_rows)))
        self._max_bytes = max(4096, min(64 * 1024 * 1024, int(max_bytes)))
        self._lock = threading.RLock()
        self._events: list[AcquisitionAuditEvent] | None = None
        self._summary: dict[str, object] | None = None

    def emit(
        self,
        event_type: str,
        *,
        actor: str,
        request_id: str = "",
        artifact_id: str = "",
        task_id: str = "",
        status: str = "",
        details: object | None = None,
    ) -> AcquisitionAuditEvent:
        event_type = str(event_type or "").strip().lower()
        if event_type not in _EVENT_TYPES:
            raise AcquisitionAuditError("unknown acquisition audit event")
        actor = self._bounded_token(actor, "actor")
        task_id = self._bounded_optional(task_id, "task id")
        status = self._bounded_optional(status, "status")
        detail_hash = hashlib.sha256(_canonical(details if details is not None else {})).hexdigest()
        with self._lock:
            events, summary = self._load()
            previous_hash = events[-1].event_hash if events else str(summary["tail_hash"])
            sequence = int(summary["last_sequence"]) + len(events) + 1
            core = {
                "sequence": sequence,
                "event_id": uuid.uuid4().hex,
                "event_type": event_type,
                "actor": actor,
                "task_id": task_id,
                "request_hash": _hash_token(request_id),
                "artifact_hash": _hash_token(artifact_id),
                "status": status,
                "detail_hash": detail_hash,
                "occurred_at": float(self._clock()),
                "previous_hash": previous_hash,
            }
            event = AcquisitionAuditEvent(
                **core,
                event_hash=hashlib.sha256(_canonical(core)).hexdigest(),
            )
            candidate = [*events, event]
            candidate, summary = self._compact(candidate, dict(summary), now=event.occurred_at)
            self._commit(candidate, summary)
            return event

    def list_public(self, *, limit: int = 100) -> list[dict[str, object]]:
        limit = max(1, min(1000, int(limit)))
        with self._lock:
            events, _summary = self._load()
            return [event.public() for event in reversed(events[-limit:])]

    def export_public(self) -> dict[str, object]:
        with self._lock:
            events, summary = self._load()
            return {
                "schema": 1,
                "summary": dict(summary),
                "events": [event.public() for event in events],
            }

    def purge_details(self, *, actor: str) -> dict[str, int]:
        if self._bounded_token(actor, "actor").lower() != "owner":
            raise AcquisitionAuditError("owner purge required")
        with self._lock:
            events, summary = self._load()
            count = len(events)
            if events:
                summary = self._summarize(dict(summary), events)
                self._commit([], summary)
            return {
                "purged": count,
                "summarized_events": int(summary["count"]),
            }

    def health(self) -> dict[str, object]:
        with self._lock:
            events, summary = self._load()
            self._validate(events, summary)
            return {
                "status": "healthy",
                "events": len(events),
                "summarized_events": int(summary["count"]),
                "chain_valid": True,
            }

    def _load(self) -> tuple[list[AcquisitionAuditEvent], dict[str, object]]:
        if self._events is not None and self._summary is not None:
            return self._events, self._summary
        if not self.path.exists():
            self._events = []
            self._summary = self._empty_summary()
            return self._events, self._summary
        if self.path.is_symlink():
            raise AcquisitionAuditError("acquisition ledger cannot be a symlink")
        try:
            raw = self.path.read_bytes()
            if len(raw) > self._max_bytes * 2:
                raise ValueError("encrypted acquisition ledger exceeds capacity")
            payload = json.loads(self._cipher.decrypt_bytes(raw).decode("utf-8"))
            if payload.get("schema") != 1 or not isinstance(payload.get("events"), list):
                raise ValueError("invalid acquisition ledger schema")
            summary = dict(payload.get("summary", {}))
            events = [AcquisitionAuditEvent(**dict(row)) for row in payload["events"]]
            if len(events) > self._max_rows:
                raise ValueError("acquisition ledger row capacity exceeded")
            self._validate(events, summary)
        except AcquisitionAuditError:
            raise
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            SecretStoreError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            raise AcquisitionAuditError("cannot decrypt or validate acquisition ledger") from exc
        self._events = events
        self._summary = summary
        return events, summary

    def _validate(self, events: list[AcquisitionAuditEvent], summary: dict[str, object]) -> None:
        required = {"count", "first_sequence", "last_sequence", "tail_hash", "summary_hash"}
        if set(summary) != required:
            raise AcquisitionAuditError("invalid acquisition hash chain summary")
        if int(summary["count"]) < 0 or int(summary["last_sequence"]) < 0:
            raise AcquisitionAuditError("invalid acquisition hash chain summary")
        previous = str(summary["tail_hash"])
        expected_sequence = int(summary["last_sequence"]) + 1
        if _HASH.fullmatch(previous) is None or _HASH.fullmatch(str(summary["summary_hash"])) is None:
            raise AcquisitionAuditError("invalid acquisition hash chain summary")
        for event in events:
            core = event.public()
            core.pop("event_hash")
            if (
                event.event_type not in _EVENT_TYPES
                or event.sequence != expected_sequence
                or event.previous_hash != previous
                or _HASH.fullmatch(event.event_hash) is None
                or hashlib.sha256(_canonical(core)).hexdigest() != event.event_hash
            ):
                raise AcquisitionAuditError("acquisition audit hash chain is invalid")
            previous = event.event_hash
            expected_sequence += 1

    def _compact(
        self,
        events: list[AcquisitionAuditEvent],
        summary: dict[str, object],
        *,
        now: float,
    ) -> tuple[list[AcquisitionAuditEvent], dict[str, object]]:
        cutoff = now - self._retention
        expired = [event for event in events if event.occurred_at < cutoff]
        if expired:
            summary = self._summarize(summary, expired)
            events = events[len(expired) :]
        if len(events) > self._max_rows:
            overflow = events[: len(events) - self._max_rows]
            summary = self._summarize(summary, overflow)
            events = events[len(overflow) :]
        while len(self._payload(events, summary)) > self._max_bytes and len(events) > 1:
            summary = self._summarize(summary, events[:1])
            events = events[1:]
        if len(self._payload(events, summary)) > self._max_bytes:
            raise AcquisitionAuditError("acquisition ledger byte capacity reached")
        return events, summary

    @staticmethod
    def _summarize(
        summary: dict[str, object],
        events: list[AcquisitionAuditEvent],
    ) -> dict[str, object]:
        if not events:
            return summary
        summary_hash = hashlib.sha256(
            bytes.fromhex(str(summary["summary_hash"]))
            + b"".join(bytes.fromhex(event.event_hash) for event in events)
        ).hexdigest()
        return {
            "count": int(summary["count"]) + len(events),
            "first_sequence": int(summary["first_sequence"]) or events[0].sequence,
            "last_sequence": events[-1].sequence,
            "tail_hash": events[-1].event_hash,
            "summary_hash": summary_hash,
        }

    def _commit(self, events: list[AcquisitionAuditEvent], summary: dict[str, object]) -> None:
        self._validate(events, summary)
        raw = self._payload(events, summary)
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".ledger-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise AcquisitionAuditError("cannot atomically commit acquisition ledger") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._events = events
        self._summary = summary

    @staticmethod
    def _payload(events: list[AcquisitionAuditEvent], summary: dict[str, object]) -> bytes:
        return _canonical(
            {
                "schema": 1,
                "summary": summary,
                "events": [event.public() for event in events],
            }
        )

    @staticmethod
    def _empty_summary() -> dict[str, object]:
        return {
            "count": 0,
            "first_sequence": 0,
            "last_sequence": 0,
            "tail_hash": _ZERO_HASH,
            "summary_hash": _ZERO_HASH,
        }

    @staticmethod
    def _bounded_token(value: str, label: str) -> str:
        token = str(value or "").strip()
        if _TOKEN.fullmatch(token) is None:
            raise AcquisitionAuditError(f"bounded audit {label} required")
        return token

    @staticmethod
    def _bounded_optional(value: str, label: str) -> str:
        token = str(value or "").strip()
        if token and _TOKEN.fullmatch(token) is None:
            raise AcquisitionAuditError(f"audit {label} is invalid")
        return token


__all__ = ["AcquisitionAuditError", "AcquisitionAuditEvent", "AcquisitionLedger"]
