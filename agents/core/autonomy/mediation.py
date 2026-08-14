"""Bounded, tamper-evident primitives for persisted Action Kernel mediation.

This module deliberately owns no policy and no signing key.  It accepts a
detached HMAC callable, binds a kernel decision to canonical task bytes, and
provides signed append-only event records.  All public verification and sealing
entry points are total: malformed or unavailable evidence returns ``False`` or
``None`` rather than accidentally granting authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass

SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
MAX_CANONICAL_BYTES = 65_536
MAX_RECEIPT_LIFETIME_MS = 86_400_000

_MAX_JSON_DEPTH = 5
_MAX_JSON_ITEMS = 1_024
_MAX_JSON_KEYS = 256
_MAX_JSON_KEY_CHARS = 128
_MAX_JSON_STRING_CHARS = 16_384
_MAX_TITLE_CHARS = 512
_MAX_REASON_CHARS = 4_096
_MAX_INTEGER = (1 << 63) - 1
_TOKEN = re.compile(r"[A-Za-z0-9_.:@/-]{1,128}")
_HASH = re.compile(r"[0-9a-f]{64}")
_VERDICTS = frozenset({"deny", "grant", "queue"})
_OUTCOMES = frozenset(
    {"authorized_enqueue", "governed", "refused_unmediated", "ungoverned_detected"}
)


def _bounded_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= _MAX_INTEGER:
        raise ValueError(f"{label} is outside the bounded range")
    return value


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded canonical identifier")
    return value


def _uuid(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a canonical UUID") from exc
    if parsed.version is None or str(parsed) != value:
        raise ValueError(f"{label} must be a canonical UUID")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _title(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_TITLE_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("title must be bounded canonical text")
    return value


def _validate_json(value: object, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("canonical JSON exceeds the nesting bound")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not -_MAX_INTEGER <= value <= _MAX_INTEGER:
            raise ValueError("canonical JSON integer is outside the bounded range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return
    if isinstance(value, str):
        if len(value) > _MAX_JSON_STRING_CHARS:
            raise ValueError("canonical JSON string exceeds the bound")
        return
    if isinstance(value, Mapping):
        if len(value) > _MAX_JSON_KEYS:
            raise ValueError("canonical JSON object exceeds the key bound")
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > _MAX_JSON_KEY_CHARS
                or any(ord(character) < 32 or ord(character) == 127 for character in key)
            ):
                raise ValueError("canonical JSON object keys must be bounded strings")
            _validate_json(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > _MAX_JSON_ITEMS:
            raise ValueError("canonical JSON array exceeds the item bound")
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    raise ValueError("value is not canonical JSON")


def canonical_json(value: object) -> bytes:
    """Return deterministic bounded UTF-8 JSON bytes or raise ``ValueError``."""

    _validate_json(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("value is not canonical JSON") from exc
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise ValueError("canonical JSON exceeds the byte bound")
    return encoded


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def payload_digest(payload: object) -> str:
    """Digest the exact canonical task payload without retaining its contents."""

    return canonical_digest(payload)


def reason_digest(reason: str) -> str:
    """Digest an exact bounded kernel reason without persisting sensitive text."""

    if not isinstance(reason, str) or len(reason) > _MAX_REASON_CHARS:
        raise ValueError("kernel reason must be bounded text")
    try:
        return hashlib.sha256(reason.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise ValueError("kernel reason must be valid UTF-8 text") from exc


class DetachedHMACSigner:
    """Fail-closed adapter around an injected ``canonical bytes -> HMAC`` callable.

    The adapter owns no key material.  The callable must return a lowercase
    SHA-256 hex tag as ``str`` or ASCII ``bytes``.  Signing backend failures,
    malformed tags, and malformed inputs are deliberately collapsed to
    ``None``/``False``.
    """

    __slots__ = ("_mac",)

    def __init__(self, mac: Callable[[bytes], str | bytes] | None) -> None:
        self._mac = mac

    def sign(self, payload: bytes) -> str | None:
        try:
            if not callable(self._mac) or not isinstance(payload, bytes):
                return None
            if not payload or len(payload) > MAX_CANONICAL_BYTES:
                return None
            value = self._mac(payload)
            if isinstance(value, bytes):
                value = value.decode("ascii")
            if not isinstance(value, str) or _HASH.fullmatch(value) is None:
                return None
            return value
        except Exception:
            return None

    def verify(self, payload: bytes, signature: object) -> bool:
        try:
            if not isinstance(signature, str) or _HASH.fullmatch(signature) is None:
                return False
            expected = self.sign(payload)
            return expected is not None and hmac.compare_digest(expected, signature)
        except Exception:
            return False


@dataclass(frozen=True, slots=True)
class MediationHead:
    """Authenticated latest-head value held outside the rollbackable queue DB."""

    version: int
    last_sequence: int
    last_event_hash: str
    event_count: int
    signature: str

    def __post_init__(self) -> None:
        if self.version != SCHEMA_VERSION:
            raise ValueError("mediation head version is unsupported")
        _bounded_int(self.last_sequence, "last_sequence")
        _digest(self.last_event_hash, "last_event_hash")
        _bounded_int(self.event_count, "event_count")
        if self.event_count != self.last_sequence:
            raise ValueError("mediation head count must equal its sequence")
        _digest(self.signature, "signature")


class MonotonicHeadAnchor:
    """Fail-closed adapter for a trusted external latest-head CAS store.

    The callbacks own durability and monotonicity outside the queue database.
    Restoring an older SQLite snapshot therefore cannot restore execution
    authority. Callback failure or malformed state is treated as unavailable.
    """

    __slots__ = ("_compare_and_swap", "_read")

    def __init__(
        self,
        read: Callable[[], MediationHead | None] | None,
        compare_and_swap: Callable[[MediationHead | None, MediationHead], bool] | None,
    ) -> None:
        self._read = read
        self._compare_and_swap = compare_and_swap

    def read(self) -> MediationHead | None:
        try:
            if not callable(self._read):
                return None
            value = self._read()
            return value if isinstance(value, MediationHead) else None
        except Exception:
            return None

    def advance(self, expected: MediationHead | None, replacement: MediationHead) -> bool:
        try:
            return (
                callable(self._compare_and_swap)
                and isinstance(replacement, MediationHead)
                and self._compare_and_swap(expected, replacement) is True
            )
        except Exception:
            return False


@dataclass(frozen=True, slots=True)
class ReceiptExpectation:
    """The exact proposed task identity a signed receipt must authorize."""

    enqueue_id: str
    agent: str
    kind: str
    title: str
    origin: str
    scope: str
    payload: object
    policy_revision: str
    enqueue_revision: int

    def __post_init__(self) -> None:
        _uuid(self.enqueue_id, "enqueue id")
        _token(self.agent, "agent")
        _token(self.kind, "kind")
        _title(self.title)
        _token(self.origin, "origin")
        _token(self.scope, "scope")
        payload_digest(self.payload)
        _token(self.policy_revision, "policy revision")
        _bounded_int(self.enqueue_revision, "enqueue revision", minimum=1)


@dataclass(frozen=True, slots=True)
class MediationReceipt:
    """Immutable version-1 detached-HMAC Action Kernel decision receipt."""

    version: int
    receipt_id: str
    enqueue_id: str
    agent: str
    kind: str
    title: str
    origin: str
    scope: str
    payload_sha256: str
    verdict: str
    tier: int
    reason_sha256: str
    policy_revision: str
    issued_at_ms: int
    expires_at_ms: int
    enqueue_revision: int
    signature: str

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or self.version != SCHEMA_VERSION:
            raise ValueError("unsupported mediation receipt version")
        _uuid(self.receipt_id, "receipt id")
        _uuid(self.enqueue_id, "enqueue id")
        _token(self.agent, "agent")
        _token(self.kind, "kind")
        _title(self.title)
        _token(self.origin, "origin")
        _token(self.scope, "scope")
        _digest(self.payload_sha256, "payload digest")
        if self.verdict not in _VERDICTS:
            raise ValueError("kernel verdict is invalid")
        _bounded_int(self.tier, "kernel tier")
        if self.tier > 3:
            raise ValueError("kernel tier is outside the bounded range")
        _digest(self.reason_sha256, "reason digest")
        _token(self.policy_revision, "policy revision")
        issued = _bounded_int(self.issued_at_ms, "issued time")
        expires = _bounded_int(self.expires_at_ms, "expiry time")
        if expires <= issued or expires - issued > MAX_RECEIPT_LIFETIME_MS:
            raise ValueError("receipt lifetime is invalid")
        _bounded_int(self.enqueue_revision, "enqueue revision", minimum=1)
        _digest(self.signature, "receipt signature")

    def unsigned_dict(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("signature")
        return value

    def signing_bytes(self) -> bytes:
        return canonical_json(self.unsigned_dict())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MediationReceipt:
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("mediation receipt fields are invalid")
        return cls(**dict(value))


def issue_receipt(
    signer: DetachedHMACSigner,
    *,
    receipt_id: str,
    expectation: ReceiptExpectation,
    verdict: str,
    tier: int,
    reason: str,
    issued_at_ms: int,
    expires_at_ms: int,
) -> MediationReceipt | None:
    """Seal an exact decision receipt, returning ``None`` on every failure."""

    try:
        unsigned = {
            "version": SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "enqueue_id": expectation.enqueue_id,
            "agent": expectation.agent,
            "kind": expectation.kind,
            "title": expectation.title,
            "origin": expectation.origin,
            "scope": expectation.scope,
            "payload_sha256": payload_digest(expectation.payload),
            "verdict": verdict,
            "tier": tier,
            "reason_sha256": reason_digest(reason),
            "policy_revision": expectation.policy_revision,
            "issued_at_ms": issued_at_ms,
            "expires_at_ms": expires_at_ms,
            "enqueue_revision": expectation.enqueue_revision,
        }
        # Construct once with a syntactically valid placeholder so the frozen
        # type validates every field before signing any bytes.
        candidate = MediationReceipt(**unsigned, signature=ZERO_HASH)
        signature = signer.sign(candidate.signing_bytes())
        if signature is None:
            return None
        return MediationReceipt(**unsigned, signature=signature)
    except Exception:
        return None


def _coerce_receipt(value: object) -> MediationReceipt:
    if isinstance(value, MediationReceipt):
        return value
    if isinstance(value, Mapping):
        return MediationReceipt.from_dict(value)
    raise ValueError("mediation receipt is invalid")


def verify_receipt(
    signer: DetachedHMACSigner,
    receipt: object,
    *,
    expected: ReceiptExpectation,
    now_ms: int,
    consumed_enqueue_ids: Iterable[str] = (),
    accepted_verdicts: Iterable[str] = ("grant", "queue"),
) -> bool:
    """Validate signature, freshness, exact task binding, revision, and replay."""

    try:
        value = _coerce_receipt(receipt)
        now = _bounded_int(now_ms, "current time")
        consumed = {_uuid(item, "consumed enqueue id") for item in consumed_enqueue_ids}
        accepted = frozenset(accepted_verdicts)
        if not accepted or not accepted <= _VERDICTS or value.verdict not in accepted:
            return False
        if value.enqueue_id in consumed:
            return False
        if not value.issued_at_ms <= now < value.expires_at_ms:
            return False
        if not signer.verify(value.signing_bytes(), value.signature):
            return False
        return (
            value.enqueue_id == expected.enqueue_id
            and value.agent == expected.agent
            and value.kind == expected.kind
            and value.title == expected.title
            and value.origin == expected.origin
            and value.scope == expected.scope
            and value.payload_sha256 == payload_digest(expected.payload)
            and value.policy_revision == expected.policy_revision
            and value.enqueue_revision == expected.enqueue_revision
        )
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class MediationEvent:
    """Immutable version-1 signed hash-chain event."""

    version: int
    event_id: str
    sequence: int
    outcome: str
    task_id: int
    enqueue_id: str
    receipt_id: str
    receipt_sha256: str
    execution_id: str
    occurred_at_ms: int
    previous_event_hash: str
    event_hash: str
    signature: str

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or self.version != SCHEMA_VERSION:
            raise ValueError("unsupported mediation event version")
        _uuid(self.event_id, "event id")
        _bounded_int(self.sequence, "event sequence", minimum=1)
        if self.outcome not in _OUTCOMES:
            raise ValueError("mediation event outcome is invalid")
        task_id = _bounded_int(self.task_id, "task id")
        _uuid(self.enqueue_id, "enqueue id")
        _uuid(self.receipt_id, "receipt id", optional=True)
        _digest(self.receipt_sha256, "receipt digest")
        _uuid(self.execution_id, "execution id", optional=True)
        _bounded_int(self.occurred_at_ms, "event time")
        _digest(self.previous_event_hash, "previous event hash")
        _digest(self.event_hash, "event hash")
        _digest(self.signature, "event signature")
        if self.outcome == "governed":
            if task_id == 0 or not self.receipt_id or not self.execution_id:
                raise ValueError("governed event requires task, receipt, and execution identity")
            if self.receipt_sha256 == ZERO_HASH:
                raise ValueError("governed event requires a receipt digest")
        elif self.outcome == "authorized_enqueue":
            if task_id == 0 or not self.receipt_id or self.execution_id:
                raise ValueError(
                    "authorized enqueue requires task and receipt without execution identity"
                )
            if self.receipt_sha256 == ZERO_HASH:
                raise ValueError("authorized enqueue requires a receipt digest")
        elif self.execution_id:
            raise ValueError("non-governed event cannot carry an execution identity")
        if bool(self.receipt_id) != (self.receipt_sha256 != ZERO_HASH):
            raise ValueError("event receipt identity and digest must be present together")

    def core_dict(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("signature")
        value.pop("event_hash")
        return value

    def signed_dict(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("signature")
        return value

    def signing_bytes(self) -> bytes:
        return canonical_json(self.signed_dict())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MediationEvent:
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("mediation event fields are invalid")
        return cls(**dict(value))


def _receipt_event_identity(receipt: object, enqueue_id: str) -> tuple[str, str]:
    if receipt is None:
        return "", ZERO_HASH
    value = _coerce_receipt(receipt)
    if value.enqueue_id != enqueue_id:
        raise ValueError("event and receipt enqueue identity differ")
    return value.receipt_id, canonical_digest(value.to_dict())


def make_event(
    signer: DetachedHMACSigner,
    *,
    event_id: str,
    sequence: int,
    outcome: str,
    task_id: int,
    enqueue_id: str,
    receipt: MediationReceipt | Mapping[str, object] | None,
    execution_id: str,
    occurred_at_ms: int,
    previous_event_hash: str,
) -> MediationEvent | None:
    """Build and sign one event, returning ``None`` on malformed evidence."""

    try:
        receipt_id, receipt_sha256 = _receipt_event_identity(receipt, enqueue_id)
        core = {
            "version": SCHEMA_VERSION,
            "event_id": event_id,
            "sequence": sequence,
            "outcome": outcome,
            "task_id": task_id,
            "enqueue_id": enqueue_id,
            "receipt_id": receipt_id,
            "receipt_sha256": receipt_sha256,
            "execution_id": execution_id,
            "occurred_at_ms": occurred_at_ms,
            "previous_event_hash": previous_event_hash,
        }
        event_hash = canonical_digest(core)
        candidate = MediationEvent(
            **core,
            event_hash=event_hash,
            signature=ZERO_HASH,
        )
        signature = signer.sign(candidate.signing_bytes())
        if signature is None:
            return None
        return MediationEvent(**core, event_hash=event_hash, signature=signature)
    except Exception:
        return None


def _coerce_event(value: object) -> MediationEvent:
    if isinstance(value, MediationEvent):
        return value
    if isinstance(value, Mapping):
        return MediationEvent.from_dict(value)
    raise ValueError("mediation event is invalid")


def verify_event_chain(
    signer: DetachedHMACSigner,
    events: Iterable[MediationEvent | Mapping[str, object]],
    *,
    previous_event_hash: str = ZERO_HASH,
    start_sequence: int = 1,
) -> bool:
    """Verify ordering, linkage, hashes, HMACs and event replay uniqueness."""

    try:
        previous = _digest(previous_event_hash, "event-chain anchor")
        expected_sequence = _bounded_int(start_sequence, "starting sequence", minimum=1)
        seen_event_ids: set[str] = set()
        previous_time = -1
        for raw in events:
            event = _coerce_event(raw)
            if event.event_id in seen_event_ids:
                return False
            if event.sequence != expected_sequence or event.previous_event_hash != previous:
                return False
            if event.occurred_at_ms < previous_time:
                return False
            if canonical_digest(event.core_dict()) != event.event_hash:
                return False
            if not signer.verify(event.signing_bytes(), event.signature):
                return False
            seen_event_ids.add(event.event_id)
            previous = event.event_hash
            previous_time = event.occurred_at_ms
            expected_sequence += 1
        return bool(seen_event_ids)
    except Exception:
        return False


__all__ = [
    "MAX_CANONICAL_BYTES",
    "MAX_RECEIPT_LIFETIME_MS",
    "SCHEMA_VERSION",
    "ZERO_HASH",
    "DetachedHMACSigner",
    "MediationHead",
    "MediationEvent",
    "MediationReceipt",
    "MonotonicHeadAnchor",
    "ReceiptExpectation",
    "canonical_digest",
    "canonical_json",
    "issue_receipt",
    "make_event",
    "payload_digest",
    "reason_digest",
    "verify_event_chain",
    "verify_receipt",
]
