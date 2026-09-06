"""Typed ``nerva.ledger.v1`` cognitive-ledger records (Cortex E1.3 / B4).

The ledger links, as plain typed data, the records that already exist in the
codebase but were never chained: a Cortex ``DecisionRecord``
(``nerva.decision.v1``), a kernel ``Decision`` sealed as a ``MediationReceipt``,
a task execution, a reality/benchmark verification and a Reflection
``OutcomeObservation``.  Every record is a content-addressed frozen dataclass
whose ``record_id`` is derived from its canonical JSON, so nothing can be
edited in place: a change is a new record that *supersedes* the old one, and
the chain retains both.

Authority is fixed to ``record_only``.  A ledger record can prove that "this
claim rests on that authorization and that verification"; it can never
authorize, execute or mark work complete (``can_authorize`` / ``can_execute`` /
``can_mark_complete`` are non-init ``False`` fields and a loaded payload that
sets them is rejected).  Ultron remains the only authority; the ledger only
points at Ultron's receipts.

``ExecutionRecord.status == "done"`` and ``VerificationRecord.verdict ==
"verified"`` are deliberately distinct records: *ran* is not *verified*.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar, Literal

from agents.core.autonomy.mediation import (
    canonical_digest,
    canonical_json,
    payload_digest,
    reason_digest,
)

SCHEMA = "nerva.ledger.v1"
AUTHORITY = "record_only"

PrivacyClass = Literal["public", "personal", "private_local", "restricted"]
Environment = Literal["ci", "local", "owner_live"]
Verdict = Literal["grant", "deny", "queue"]
ExecutionStatus = Literal["queued", "running", "partial", "done", "failed"]
VerificationMethod = Literal["reality_run", "benchmark_run"]
VerificationVerdict = Literal["verified", "not_verified", "not_exercised"]
ComparisonStatus = Literal[
    "confirmed", "refuted", "contradictory", "insufficient_evidence"
]

DECISION_SCHEMA = "nerva.decision.v1"
RECEIPT_SCHEMA = "nerva.mediation.receipt.v1"
REALITY_RUN_SCHEMA = "nerva.reality.run.v1"
BENCHMARK_SCHEMA = "nerva.benchmark.v1"
OUTCOME_OBSERVATION_SCHEMA = "nerva.outcome-observation.v1"

_PRIVACY_RANK = {"public": 0, "personal": 1, "private_local": 2, "restricted": 3}
_ENVIRONMENTS = frozenset({"ci", "local", "owner_live"})
_VERDICTS = frozenset({"grant", "deny", "queue"})
_EXECUTION_STATUSES = frozenset({"queued", "running", "partial", "done", "failed"})
_EXECUTED_STATUSES = frozenset({"running", "partial", "done", "failed"})
_VERIFICATION_METHODS = {
    "reality_run": REALITY_RUN_SCHEMA,
    "benchmark_run": BENCHMARK_SCHEMA,
}
_VERIFICATION_VERDICTS = frozenset({"verified", "not_verified", "not_exercised"})
_COMPARISON_STATUSES = frozenset(
    {"confirmed", "refuted", "contradictory", "insufficient_evidence"}
)
_SHA256_HEX = 64
_MAX_TEXT = 4096
_MAX_TOKEN = 256
_ID_PREFIX = "ledger:"


# --------------------------------------------------------------------------- #
# validation helpers
# --------------------------------------------------------------------------- #


def _require_text(value: Any, name: str, *, max_chars: int = _MAX_TOKEN) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ledger {name} must be a non-empty string")
    if len(value) > max_chars:
        raise ValueError(f"ledger {name} exceeds {max_chars} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"ledger {name} must not contain control characters")
    return value


def _validate_time(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"ledger {name} must be a numeric timestamp")
    if not math.isfinite(float(value)) or float(value) < 0.0:
        raise ValueError(f"ledger {name} must be a finite non-negative timestamp")


def _validate_privacy(value: Any, name: str = "privacy_class") -> None:
    if value not in _PRIVACY_RANK:
        raise ValueError(f"ledger {name} is not a recognized privacy class")


def _validate_sha256(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != _SHA256_HEX:
        raise ValueError(f"ledger {name} must be a SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"ledger {name} must be a SHA-256 hex digest")


def _string_tuple(value: Any, name: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"ledger {name} must be an immutable tuple")
    if not value and not allow_empty:
        raise ValueError(f"ledger {name} cannot be empty")
    items = [_require_text(item, name, max_chars=_MAX_TEXT).strip() for item in value]
    if len(set(items)) != len(items):
        raise ValueError(f"ledger {name} cannot contain duplicates")
    return tuple(sorted(items))


def _sha256_of(value: Any) -> str:
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    """``asdict`` keeps tuples; canonical JSON wants lists."""

    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _ledger_ref(ref: Any, kind: str, name: str) -> None:
    """Require a ref that points at a ledger record of ``kind``."""

    if not isinstance(ref, LedgerRef) or not ref.is_ledger:
        raise ValueError(f"ledger {name} must point at a ledger {kind}")
    if not ref.record_id.startswith(f"{_ID_PREFIX}{kind}:"):
        raise ValueError(f"ledger {name} must point at a ledger {kind}")


def _exact_keys(payload: Any, cls: type, name: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"ledger {name} payload must be an object")
    expected = {item.name for item in fields(cls)}
    if set(payload) != expected:
        raise ValueError(f"ledger {name} payload keys do not match the schema")
    return dict(payload)


# --------------------------------------------------------------------------- #
# content-free pointer
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LedgerRef:
    """Content-free pointer to one canonical record inside or outside the ledger.

    Only the schema, the record identity, the integrity digest and the privacy
    class travel; the referenced content never does (the ``EpisodeReference``
    pattern).  Refs whose ``record_schema`` is ``nerva.ledger.v1`` are resolved
    inside a :class:`LedgerChain`; every other schema is an external record
    that a caller may bind through ``LedgerChain.validate(external=...)``.
    """

    record_schema: str
    record_id: str
    integrity_sha256: str
    privacy_class: PrivacyClass

    def __post_init__(self) -> None:
        _require_text(self.record_schema, "ref record_schema")
        _require_text(self.record_id, "ref record_id")
        _validate_sha256(self.integrity_sha256, "ref integrity_sha256")
        _validate_privacy(self.privacy_class, "ref privacy_class")

    @property
    def is_ledger(self) -> bool:
        return self.record_schema == SCHEMA

    @property
    def key(self) -> tuple[str, str]:
        return (self.record_schema, self.record_id)

    def canonical_payload(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    @classmethod
    def from_payload(cls, payload: Any) -> LedgerRef:
        return cls(**_exact_keys(payload, cls, "ref"))

    @classmethod
    def to_record(cls, record: _LedgerRecord) -> LedgerRef:
        """Point at a ledger record by its content fingerprint."""

        if not isinstance(record, _LedgerRecord):
            raise ValueError("ledger ref requires a ledger record")
        return cls(
            record_schema=SCHEMA,
            record_id=record.record_id,
            integrity_sha256=record.fingerprint,
            privacy_class=record.privacy_class,
        )

    @classmethod
    def from_decision_record(
        cls, record: Any, *, privacy_class: PrivacyClass = "private_local"
    ) -> LedgerRef:
        """Point at a Cortex ``nerva.decision.v1`` record by replay fingerprint."""

        schema = getattr(record, "schema", None)
        fingerprint = getattr(record, "replay_fingerprint", None)
        if schema != DECISION_SCHEMA or not isinstance(fingerprint, str):
            raise ValueError("ledger decision ref requires a nerva.decision.v1 record")
        _validate_sha256(fingerprint, "decision replay fingerprint")
        return cls(
            record_schema=DECISION_SCHEMA,
            record_id=f"decision:{fingerprint[:24]}",
            integrity_sha256=fingerprint,
            privacy_class=privacy_class,
        )

    @classmethod
    def from_receipt(
        cls, receipt: Any, *, privacy_class: PrivacyClass = "private_local"
    ) -> LedgerRef:
        """Point at a sealed ``MediationReceipt`` (its bytes are never copied)."""

        to_dict = getattr(receipt, "to_dict", None)
        signature = getattr(receipt, "signature", None)
        receipt_id = getattr(receipt, "receipt_id", None)
        if not callable(to_dict) or not isinstance(signature, str):
            raise ValueError("ledger receipt ref requires a MediationReceipt")
        _validate_sha256(signature, "receipt signature")
        return cls(
            record_schema=RECEIPT_SCHEMA,
            record_id=_require_text(receipt_id, "receipt id"),
            integrity_sha256=canonical_digest(to_dict()),
            privacy_class=privacy_class,
        )

    @classmethod
    def from_reality_run(
        cls, record: Mapping[str, Any], *, privacy_class: PrivacyClass = "private_local"
    ) -> LedgerRef:
        """Point at one ``nerva.reality.run.v1`` ledger row."""

        if not isinstance(record, Mapping) or record.get("schema") != REALITY_RUN_SCHEMA:
            raise ValueError("ledger reality ref requires a nerva.reality.run.v1 record")
        harness_id = _require_text(record.get("harness_id"), "reality harness_id")
        finished_at = _require_text(record.get("finished_at"), "reality finished_at")
        return cls(
            record_schema=REALITY_RUN_SCHEMA,
            record_id=f"{harness_id}@{finished_at}",
            integrity_sha256=_sha256_of(dict(record)),
            privacy_class=privacy_class,
        )

    @classmethod
    def from_benchmark_run(
        cls, run: Any, *, privacy_class: PrivacyClass = "private_local"
    ) -> LedgerRef:
        """Point at a retained ``nerva.benchmark.v1`` run by its JSON fingerprint."""

        to_json = getattr(run, "to_json", None)
        run_id = getattr(run, "run_id", None)
        if getattr(run, "schema", None) != BENCHMARK_SCHEMA or not callable(to_json):
            raise ValueError("ledger benchmark ref requires a nerva.benchmark.v1 run")
        return cls(
            record_schema=BENCHMARK_SCHEMA,
            record_id=_require_text(run_id, "benchmark run_id"),
            integrity_sha256=_sha256_of(to_json()),
            privacy_class=privacy_class,
        )

    @classmethod
    def from_outcome_observation(cls, observation: Any) -> LedgerRef:
        """Point at a Reflection ``OutcomeObservation`` by canonical digest."""

        if getattr(observation, "schema", None) != OUTCOME_OBSERVATION_SCHEMA:
            raise ValueError(
                "ledger outcome ref requires a nerva.outcome-observation.v1 record"
            )
        privacy_class = getattr(observation, "privacy_class", None)
        _validate_privacy(privacy_class, "observation privacy_class")
        return cls(
            record_schema=OUTCOME_OBSERVATION_SCHEMA,
            record_id=_require_text(
                getattr(observation, "observation_id", None), "observation_id"
            ),
            integrity_sha256=_sha256_of(asdict(observation)),
            privacy_class=privacy_class,
        )


# --------------------------------------------------------------------------- #
# record base
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class _LedgerRecord:
    """Common shape of every ``nerva.ledger.v1`` record.

    ``record_id`` is content-addressed: pass ``""`` to ``build`` paths and it is
    derived from the canonical payload; a loaded payload must carry the exact
    derived id.  Named source refs are exposed through :meth:`source_refs` so
    the chain can resolve them and privacy can only escalate along the chain.
    """

    record_kind: ClassVar[str] = ""

    record_id: str
    created_at: float
    privacy_class: PrivacyClass
    supersedes_record_id: str | None = None
    schema: str = field(default=SCHEMA, init=False)
    authority: str = field(default=AUTHORITY, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not self.record_kind:
            raise TypeError("ledger record base cannot be instantiated directly")
        _validate_time(self.created_at, "created_at")
        _validate_privacy(self.privacy_class)
        if self.supersedes_record_id is not None:
            _require_text(self.supersedes_record_id, "supersedes_record_id")
        self._validate_fields()
        floor = self.privacy_floor()
        if _PRIVACY_RANK[self.privacy_class] < _PRIVACY_RANK[floor]:
            raise ValueError(
                "ledger record privacy class cannot fall below its sources"
            )
        expected = self.expected_record_id
        if self.record_id == "":
            object.__setattr__(self, "record_id", expected)
        elif self.record_id != expected:
            raise ValueError("ledger record_id does not match canonical content")

    # subclasses override
    def _validate_fields(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        """Named refs this record derives from, in canonical order."""

        return ()

    def privacy_floor(self) -> PrivacyClass:
        floor: PrivacyClass = "public"
        for _role, ref in self.source_refs():
            if _PRIVACY_RANK[ref.privacy_class] > _PRIVACY_RANK[floor]:
                floor = ref.privacy_class
        return floor

    def canonical_payload(self) -> dict[str, Any]:
        payload = _jsonable(asdict(self))
        payload["record_kind"] = self.record_kind
        return payload

    def to_json(self) -> str:
        return canonical_json(self.canonical_payload()).decode("utf-8")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @property
    def expected_record_id(self) -> str:
        material = self.canonical_payload()
        material["record_id"] = ""
        digest = hashlib.sha256(canonical_json(material)).hexdigest()
        return f"{_ID_PREFIX}{self.record_kind}:{digest[:24]}"

    def superseded_by(self, **changes: Any) -> _LedgerRecord:
        """Return a new record that supersedes this one; nothing is overwritten."""

        payload = {
            item.name: getattr(self, item.name) for item in fields(self) if item.init
        }
        payload.update(changes)
        payload["record_id"] = ""
        payload["supersedes_record_id"] = self.record_id
        return type(self)(**payload)


# --------------------------------------------------------------------------- #
# records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GoalBudget:
    steps: int
    wall_seconds: float
    usd: float

    def __post_init__(self) -> None:
        if isinstance(self.steps, bool) or not isinstance(self.steps, int):
            raise ValueError("ledger budget steps must be an integer")
        if self.steps < 0:
            raise ValueError("ledger budget steps cannot be negative")
        for value, name in ((self.wall_seconds, "wall_seconds"), (self.usd, "usd")):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"ledger budget {name} must be numeric")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"ledger budget {name} must be finite and non-negative")

    @classmethod
    def from_payload(cls, payload: Any) -> GoalBudget:
        return cls(**_exact_keys(payload, cls, "budget"))


@dataclass(frozen=True)
class GoalScope:
    """Domains (kind prefixes such as ``desktop``) and exact capability ids."""

    domains: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        domains = _string_tuple(self.domains, "scope domains", allow_empty=True)
        capability_ids = _string_tuple(
            self.capability_ids, "scope capability_ids", allow_empty=True
        )
        if not domains and not capability_ids:
            raise ValueError("ledger goal scope cannot be empty")
        object.__setattr__(self, "domains", domains)
        object.__setattr__(self, "capability_ids", capability_ids)

    def covers(self, kind: str) -> bool:
        return kind in self.capability_ids or kind.split(".", 1)[0] in self.domains

    @classmethod
    def from_payload(cls, payload: Any) -> GoalScope:
        raw = _exact_keys(payload, cls, "scope")
        return cls(
            domains=tuple(raw["domains"]), capability_ids=tuple(raw["capability_ids"])
        )


@dataclass(frozen=True, kw_only=True)
class GoalSpec(_LedgerRecord):
    """A bounded goal: scope, budget, deadline and stop conditions.

    ``approved_by`` is a ref to the approval evidence (a receipt, an audit row).
    Once approved a goal is frozen: it can no longer be superseded, only
    replaced by a new goal with a new ``goal_id``.
    """

    record_kind: ClassVar[str] = "goal"

    goal_id: str
    title: str
    scope: GoalScope
    budget: GoalBudget
    deadline_at: float
    stop_conditions: tuple[str, ...]
    approved_by: LedgerRef | None = None

    def _validate_fields(self) -> None:
        _require_text(self.goal_id, "goal_id")
        _require_text(self.title, "goal title", max_chars=512)
        if not isinstance(self.scope, GoalScope):
            raise ValueError("ledger goal scope must be GoalScope")
        if not isinstance(self.budget, GoalBudget):
            raise ValueError("ledger goal budget must be GoalBudget")
        _validate_time(self.deadline_at, "deadline_at")
        if self.deadline_at <= self.created_at:
            raise ValueError("ledger goal deadline must follow its creation")
        object.__setattr__(
            self,
            "stop_conditions",
            _string_tuple(self.stop_conditions, "stop_conditions", allow_empty=False),
        )
        if self.approved_by is not None and not isinstance(self.approved_by, LedgerRef):
            raise ValueError("ledger goal approved_by must be LedgerRef")

    @property
    def approved(self) -> bool:
        return self.approved_by is not None

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        if self.approved_by is None:
            return ()
        return (("approved_by", self.approved_by),)

    @classmethod
    def build(cls, **kwargs: Any) -> GoalSpec:
        return cls(record_id="", **kwargs)


@dataclass(frozen=True, kw_only=True)
class EvidenceRecord(_LedgerRecord):
    """A claim, the environment it was observed in, and what it rests on."""

    record_kind: ClassVar[str] = "evidence"

    claim: str
    environment: Environment
    sources: tuple[LedgerRef, ...]
    observed_at: float

    def _validate_fields(self) -> None:
        _require_text(self.claim, "evidence claim", max_chars=_MAX_TEXT)
        if self.environment not in _ENVIRONMENTS:
            raise ValueError("ledger evidence environment is not recognized")
        if not isinstance(self.sources, tuple) or not self.sources:
            raise ValueError("ledger evidence must name at least one source")
        keys = set()
        for ref in self.sources:
            if not isinstance(ref, LedgerRef):
                raise ValueError("ledger evidence sources must be LedgerRef")
            if ref.key in keys:
                raise ValueError("ledger evidence sources cannot duplicate a ref")
            keys.add(ref.key)
        _validate_time(self.observed_at, "observed_at")
        if self.observed_at > self.created_at:
            raise ValueError("ledger evidence cannot be recorded before it is observed")

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        return tuple(("source", ref) for ref in self.sources)

    @classmethod
    def build(cls, **kwargs: Any) -> EvidenceRecord:
        return cls(record_id="", **kwargs)


@dataclass(frozen=True, kw_only=True)
class ActionIntent(_LedgerRecord):
    """A kernel ``Action`` about to be presented for mediation, by digest only."""

    record_kind: ClassVar[str] = "intent"

    goal_ref: LedgerRef
    kind: str
    agent: str
    title: str
    scope: str
    origin: str
    payload_sha256: str
    decision_ref: LedgerRef | None = None

    def _validate_fields(self) -> None:
        _ledger_ref(self.goal_ref, "goal", "intent goal_ref")
        for value, name in (
            (self.kind, "intent kind"),
            (self.agent, "intent agent"),
            (self.scope, "intent scope"),
            (self.origin, "intent origin"),
        ):
            _require_text(value, name)
        _require_text(self.title, "intent title", max_chars=512)
        _validate_sha256(self.payload_sha256, "payload_sha256")
        if self.decision_ref is not None:
            if not isinstance(self.decision_ref, LedgerRef):
                raise ValueError("ledger intent decision_ref must be LedgerRef")
            if self.decision_ref.record_schema != DECISION_SCHEMA:
                raise ValueError("ledger intent decision_ref must be nerva.decision.v1")

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        refs: list[tuple[str, LedgerRef]] = [("goal", self.goal_ref)]
        if self.decision_ref is not None:
            refs.append(("decision", self.decision_ref))
        return tuple(refs)

    @classmethod
    def build(cls, **kwargs: Any) -> ActionIntent:
        return cls(record_id="", **kwargs)

    @classmethod
    def from_action(
        cls,
        action: Any,
        *,
        goal: GoalSpec | LedgerRef,
        created_at: float,
        privacy_class: PrivacyClass,
        decision_ref: LedgerRef | None = None,
    ) -> ActionIntent:
        """Digest a kernel ``Action`` (duck-typed) without retaining its payload."""

        goal_ref = goal if isinstance(goal, LedgerRef) else LedgerRef.to_record(goal)
        return cls.build(
            created_at=created_at,
            privacy_class=privacy_class,
            goal_ref=goal_ref,
            kind=str(getattr(action, "kind", "")),
            agent=str(getattr(action, "agent", "")),
            title=str(getattr(action, "title", "") or getattr(action, "kind", "")),
            scope=str(getattr(action, "scope", "")),
            origin=str(getattr(action, "origin", "")),
            payload_sha256=payload_digest(dict(getattr(action, "payload", {}) or {})),
            decision_ref=decision_ref,
        )


@dataclass(frozen=True, kw_only=True)
class AuthorizationRecord(_LedgerRecord):
    """What Ultron decided about one intent.

    A ``grant`` is only recordable with a sealed receipt ref; a grant without a
    receipt is a forgery and is rejected at construction and on load.
    """

    record_kind: ClassVar[str] = "authorization"

    intent_ref: LedgerRef
    verdict: Verdict
    tier: int | None
    reason_sha256: str
    decided_at: float
    receipt_ref: LedgerRef | None = None

    def _validate_fields(self) -> None:
        _ledger_ref(self.intent_ref, "intent", "authorization intent_ref")
        if self.verdict not in _VERDICTS:
            raise ValueError("ledger authorization verdict is not recognized")
        if self.tier is not None:
            if isinstance(self.tier, bool) or not isinstance(self.tier, int):
                raise ValueError("ledger authorization tier must be an integer")
            if not 0 <= self.tier <= 3:
                raise ValueError("ledger authorization tier is outside 0..3")
        _validate_sha256(self.reason_sha256, "reason_sha256")
        _validate_time(self.decided_at, "decided_at")
        if self.decided_at > self.created_at:
            raise ValueError("ledger authorization cannot be recorded before decided")
        if self.receipt_ref is not None:
            if not isinstance(self.receipt_ref, LedgerRef):
                raise ValueError("ledger authorization receipt_ref must be LedgerRef")
            if self.receipt_ref.record_schema != RECEIPT_SCHEMA:
                raise ValueError(
                    "ledger authorization receipt_ref must be a mediation receipt"
                )
        if self.verdict == "grant" and self.receipt_ref is None:
            raise ValueError("ledger grant without a sealed receipt is forged")

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        refs: list[tuple[str, LedgerRef]] = [("intent", self.intent_ref)]
        if self.receipt_ref is not None:
            refs.append(("receipt", self.receipt_ref))
        return tuple(refs)

    @classmethod
    def build(cls, **kwargs: Any) -> AuthorizationRecord:
        return cls(record_id="", **kwargs)

    @classmethod
    def from_decision(
        cls,
        decision: Any,
        *,
        intent: ActionIntent,
        created_at: float,
        decided_at: float,
        privacy_class: PrivacyClass,
        receipt: Any = None,
    ) -> AuthorizationRecord:
        """Record a kernel ``Decision`` (duck-typed) bound to ``intent``.

        When a receipt is supplied it must bind the same payload digest and the
        same verdict; otherwise the authorization is a forgery.
        """

        if not isinstance(intent, ActionIntent):
            raise ValueError("ledger authorization requires an ActionIntent")
        raw_verdict = getattr(decision, "verdict", None)
        verdict = str(getattr(raw_verdict, "value", raw_verdict))
        if verdict not in _VERDICTS:
            raise ValueError("ledger authorization verdict is not recognized")
        receipt_ref = None
        if receipt is not None:
            if getattr(receipt, "payload_sha256", None) != intent.payload_sha256:
                raise ValueError("ledger receipt does not bind the intent payload")
            if getattr(receipt, "verdict", None) != verdict:
                raise ValueError("ledger receipt verdict differs from the decision")
            if getattr(receipt, "kind", None) != intent.kind:
                raise ValueError("ledger receipt does not bind the intent kind")
            receipt_ref = LedgerRef.from_receipt(receipt)
        return cls.build(
            created_at=created_at,
            privacy_class=privacy_class,
            intent_ref=LedgerRef.to_record(intent),
            verdict=verdict,
            tier=getattr(decision, "tier", None),
            reason_sha256=reason_digest(str(getattr(decision, "reason", "") or "")),
            decided_at=decided_at,
            receipt_ref=receipt_ref,
        )


@dataclass(frozen=True, kw_only=True)
class ExecutionRecord(_LedgerRecord):
    """One execution attempt of an authorized intent.  ``done`` is not verified."""

    record_kind: ClassVar[str] = "execution"

    authorization_ref: LedgerRef
    task_id: str
    execution_id: str
    status: ExecutionStatus
    started_at: float | None = None
    finished_at: float | None = None

    def _validate_fields(self) -> None:
        _ledger_ref(self.authorization_ref, "authorization", "execution")
        _require_text(self.task_id, "task_id")
        _require_text(self.execution_id, "execution_id")
        if self.status not in _EXECUTION_STATUSES:
            raise ValueError("ledger execution status is not recognized")
        if self.started_at is not None:
            _validate_time(self.started_at, "started_at")
        if self.finished_at is not None:
            _validate_time(self.finished_at, "finished_at")
            if self.started_at is None or self.finished_at < self.started_at:
                raise ValueError("ledger execution finished_at requires an earlier start")
        if self.status in _EXECUTED_STATUSES and self.started_at is None:
            raise ValueError("ledger execution beyond queued requires started_at")
        if self.status in {"done", "failed", "partial"} and self.finished_at is None:
            raise ValueError("ledger terminal execution requires finished_at")
        if self.status == "queued" and self.started_at is not None:
            raise ValueError("ledger queued execution cannot have started")

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        return (("authorization", self.authorization_ref),)

    @classmethod
    def build(cls, **kwargs: Any) -> ExecutionRecord:
        return cls(record_id="", **kwargs)


@dataclass(frozen=True, kw_only=True)
class VerificationRecord(_LedgerRecord):
    """Independent verification of an execution by a reality or benchmark run."""

    record_kind: ClassVar[str] = "verification"

    execution_ref: LedgerRef
    method: VerificationMethod
    run_ref: LedgerRef
    verdict: VerificationVerdict
    environment: Environment
    verified_at: float
    limitations: tuple[str, ...] = ()

    def _validate_fields(self) -> None:
        _ledger_ref(self.execution_ref, "execution", "verification")
        if self.method not in _VERIFICATION_METHODS:
            raise ValueError("ledger verification method is not recognized")
        if not isinstance(self.run_ref, LedgerRef):
            raise ValueError("ledger verification run_ref must be LedgerRef")
        if self.run_ref.record_schema != _VERIFICATION_METHODS[self.method]:
            raise ValueError("ledger verification run_ref schema does not match method")
        if self.verdict not in _VERIFICATION_VERDICTS:
            raise ValueError("ledger verification verdict is not recognized")
        if self.environment not in _ENVIRONMENTS:
            raise ValueError("ledger verification environment is not recognized")
        _validate_time(self.verified_at, "verified_at")
        if self.verified_at > self.created_at:
            raise ValueError("ledger verification cannot be recorded before verifying")
        object.__setattr__(
            self,
            "limitations",
            _string_tuple(self.limitations, "limitations", allow_empty=True),
        )
        if self.verdict == "not_exercised" and not self.limitations:
            raise ValueError("ledger not_exercised verification must state a limitation")

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        return (("execution", self.execution_ref), ("run", self.run_ref))

    @classmethod
    def build(cls, **kwargs: Any) -> VerificationRecord:
        return cls(record_id="", **kwargs)


@dataclass(frozen=True, kw_only=True)
class OutcomeRecord(_LedgerRecord):
    """Pointer from a verified execution to its Reflection ``OutcomeObservation``."""

    record_kind: ClassVar[str] = "outcome"

    verification_ref: LedgerRef
    observation_ref: LedgerRef
    comparison_status: ComparisonStatus
    observed_at: float

    def _validate_fields(self) -> None:
        _ledger_ref(self.verification_ref, "verification", "outcome")
        if not isinstance(self.observation_ref, LedgerRef):
            raise ValueError("ledger outcome observation_ref must be LedgerRef")
        if self.observation_ref.record_schema != OUTCOME_OBSERVATION_SCHEMA:
            raise ValueError("ledger outcome observation_ref must be an observation")
        if self.comparison_status not in _COMPARISON_STATUSES:
            raise ValueError("ledger outcome comparison_status is not recognized")
        _validate_time(self.observed_at, "observed_at")
        if self.observed_at > self.created_at:
            raise ValueError("ledger outcome cannot be recorded before it is observed")

    def source_refs(self) -> tuple[tuple[str, LedgerRef], ...]:
        return (
            ("verification", self.verification_ref),
            ("observation", self.observation_ref),
        )

    @classmethod
    def build(cls, **kwargs: Any) -> OutcomeRecord:
        return cls(record_id="", **kwargs)

    @classmethod
    def from_observation(
        cls,
        observation: Any,
        *,
        verification: VerificationRecord | LedgerRef,
        created_at: float,
        privacy_class: PrivacyClass | None = None,
    ) -> OutcomeRecord:
        ref = (
            verification
            if isinstance(verification, LedgerRef)
            else LedgerRef.to_record(verification)
        )
        observation_ref = LedgerRef.from_outcome_observation(observation)
        floor = max(
            (ref.privacy_class, observation_ref.privacy_class),
            key=_PRIVACY_RANK.__getitem__,
        )
        return cls.build(
            created_at=created_at,
            privacy_class=privacy_class or floor,
            verification_ref=ref,
            observation_ref=observation_ref,
            comparison_status=str(getattr(observation, "comparison_status", "")),
            observed_at=float(getattr(observation, "observed_at", -1.0)),
        )


LedgerRecord = (
    GoalSpec
    | EvidenceRecord
    | ActionIntent
    | AuthorizationRecord
    | ExecutionRecord
    | VerificationRecord
    | OutcomeRecord
)

_RECORD_TYPES: dict[str, type[_LedgerRecord]] = {
    cls.record_kind: cls
    for cls in (
        GoalSpec,
        EvidenceRecord,
        ActionIntent,
        AuthorizationRecord,
        ExecutionRecord,
        VerificationRecord,
        OutcomeRecord,
    )
}


# --------------------------------------------------------------------------- #
# loader
# --------------------------------------------------------------------------- #

_NESTED_REF_FIELDS = {
    "approved_by",
    "goal_ref",
    "decision_ref",
    "intent_ref",
    "receipt_ref",
    "authorization_ref",
    "execution_ref",
    "run_ref",
    "verification_ref",
    "observation_ref",
}


def load_record(payload: Any) -> LedgerRecord:
    """Rebuild one record from its canonical payload, rejecting any forgery.

    Unknown or missing keys, a foreign schema, a non-``record_only`` authority,
    any ``can_*`` flag set to ``True``, boolean timestamps and a ``record_id``
    that does not match the content are all rejected with ``ValueError``.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("ledger record payload must be an object")
    kind = payload.get("record_kind")
    cls = _RECORD_TYPES.get(kind) if isinstance(kind, str) else None
    if cls is None:
        raise ValueError("ledger record kind is not recognized")
    expected = {item.name for item in fields(cls)} | {"record_kind"}
    if set(payload) != expected:
        raise ValueError("ledger record payload keys do not match the schema")
    if payload["schema"] != SCHEMA:
        raise ValueError("ledger record schema is not nerva.ledger.v1")
    if payload["authority"] != AUTHORITY:
        raise ValueError("ledger record authority is forged")
    for flag in ("can_authorize", "can_execute", "can_mark_complete"):
        if payload[flag] is not False:
            raise ValueError(f"ledger record {flag} is forged")
    raw = {
        item.name: payload[item.name] for item in fields(cls) if item.init
    }
    for name in tuple(raw):
        value = raw[name]
        if name in _NESTED_REF_FIELDS and value is not None:
            raw[name] = LedgerRef.from_payload(value)
        elif name == "sources":
            if not isinstance(value, list):
                raise ValueError("ledger evidence sources must be a JSON array")
            raw[name] = tuple(LedgerRef.from_payload(item) for item in value)
        elif name == "scope" and cls is GoalSpec:
            raw[name] = GoalScope.from_payload(value)
        elif name == "budget":
            raw[name] = GoalBudget.from_payload(value)
        elif name in {"stop_conditions", "limitations"}:
            if not isinstance(value, list):
                raise ValueError(f"ledger {name} must be a JSON array")
            raw[name] = tuple(value)
    return cls(**raw)


# --------------------------------------------------------------------------- #
# chain
# --------------------------------------------------------------------------- #

_KIND_ORDER = {
    "goal": 0,
    "evidence": 1,
    "intent": 2,
    "authorization": 3,
    "execution": 4,
    "verification": 5,
    "outcome": 6,
}


def _sort_key(record: _LedgerRecord) -> tuple[float, int, str]:
    return (float(record.created_at), _KIND_ORDER[record.record_kind], record.record_id)


@dataclass(frozen=True)
class LedgerChain:
    """An immutable, validated set of ledger records.

    ``build`` validates: every ledger ref resolves to a record whose fingerprint
    matches; chronology is monotone (no record precedes what it derives from);
    supersession points at an existing record of the same kind, never forks,
    never overwrites, and never touches an approved goal; intents fall inside
    an approved goal's scope and deadline; executions beyond ``queued`` rest on
    a ``grant``; verifications follow the execution they verify.  External refs
    are retained as ``unresolved`` unless a caller binds their fingerprints.
    """

    records: tuple[LedgerRecord, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.records, key=_sort_key))
        object.__setattr__(self, "records", ordered)
        self.validate()

    @classmethod
    def build(cls, records: Iterable[LedgerRecord]) -> LedgerChain:
        return cls(records=tuple(records))

    @property
    def by_id(self) -> dict[str, LedgerRecord]:
        return {record.record_id: record for record in self.records}

    @property
    def heads(self) -> tuple[LedgerRecord, ...]:
        """Records not superseded by any other record (the current view)."""

        superseded = {
            record.supersedes_record_id
            for record in self.records
            if record.supersedes_record_id is not None
        }
        return tuple(r for r in self.records if r.record_id not in superseded)

    @property
    def unresolved(self) -> tuple[LedgerRef, ...]:
        """External refs the chain cannot verify by itself, in canonical order."""

        seen: dict[tuple[str, str], LedgerRef] = {}
        for record in self.records:
            for _role, ref in record.source_refs():
                if not ref.is_ledger:
                    seen.setdefault(ref.key, ref)
        return tuple(seen[key] for key in sorted(seen))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            canonical_json([record.fingerprint for record in self.records])
        ).hexdigest()

    def append(self, *records: LedgerRecord) -> LedgerChain:
        """Return a new validated chain; the existing chain is untouched."""

        return LedgerChain.build((*self.records, *records))

    def resolve(self, ref: LedgerRef) -> LedgerRecord:
        if not ref.is_ledger:
            raise ValueError("ledger chain cannot resolve an external ref")
        record = self.by_id.get(ref.record_id)
        if record is None:
            raise ValueError(f"ledger ref {ref.record_id} is not in the chain")
        if record.fingerprint != ref.integrity_sha256:
            raise ValueError(f"ledger ref {ref.record_id} integrity mismatch")
        return record

    def trace(self, record_id: str) -> tuple[LedgerRecord, ...]:
        """Every ledger record ``record_id`` transitively rests on, oldest first."""

        index = self.by_id
        if record_id not in index:
            raise ValueError(f"ledger record {record_id} is not in the chain")
        seen: dict[str, LedgerRecord] = {}
        pending = [index[record_id]]
        while pending:
            record = pending.pop()
            for _role, ref in record.source_refs():
                if ref.is_ledger and ref.record_id not in seen:
                    seen[ref.record_id] = self.resolve(ref)
                    pending.append(seen[ref.record_id])
        return tuple(sorted(seen.values(), key=_sort_key))

    def to_payloads(self) -> list[dict[str, Any]]:
        return [record.canonical_payload() for record in self.records]

    def validate(self, *, external: Mapping[tuple[str, str], str] | None = None) -> None:
        """Re-run every structural rule; ``external`` binds outside fingerprints."""

        index: dict[str, LedgerRecord] = {}
        for record in self.records:
            if not isinstance(record, _LedgerRecord):
                raise ValueError("ledger chain accepts ledger records only")
            if record.record_id in index:
                raise ValueError(f"ledger record {record.record_id} is duplicated")
            index[record.record_id] = record
        superseders: dict[str, str] = {}
        for record in self.records:
            self._check_sources(record, index, external)
            self._check_supersession(record, index, superseders)
            self._check_kind_rules(record, index)

    # -- rules ------------------------------------------------------------ #

    @staticmethod
    def _resolve_in(index: Mapping[str, LedgerRecord], ref: LedgerRef) -> LedgerRecord:
        record = index.get(ref.record_id)
        if record is None:
            raise ValueError(f"ledger ref {ref.record_id} is not in the chain")
        if record.fingerprint != ref.integrity_sha256:
            raise ValueError(f"ledger ref {ref.record_id} integrity mismatch")
        return record

    def _check_sources(
        self,
        record: LedgerRecord,
        index: Mapping[str, LedgerRecord],
        external: Mapping[tuple[str, str], str] | None,
    ) -> None:
        for role, ref in record.source_refs():
            if ref.is_ledger:
                source = self._resolve_in(index, ref)
                if source.created_at > record.created_at:
                    raise ValueError(
                        f"ledger {record.record_kind} precedes its {role} source"
                    )
                if source.record_id == record.record_id:
                    raise ValueError("ledger record cannot derive from itself")
            elif external is not None and ref.key in external:
                if external[ref.key] != ref.integrity_sha256:
                    raise ValueError(
                        f"ledger external ref {ref.record_id} integrity mismatch"
                    )

    @staticmethod
    def _check_supersession(
        record: LedgerRecord,
        index: Mapping[str, LedgerRecord],
        superseders: dict[str, str],
    ) -> None:
        prior_id = record.supersedes_record_id
        if prior_id is None:
            return
        prior = index.get(prior_id)
        if prior is None:
            raise ValueError("ledger supersession must name a retained record")
        if prior.record_kind != record.record_kind:
            raise ValueError("ledger supersession cannot change the record kind")
        if prior.created_at > record.created_at:
            raise ValueError("ledger supersession cannot precede the prior record")
        if prior_id in superseders:
            raise ValueError("ledger supersession cannot fork one record twice")
        superseders[prior_id] = record.record_id
        if isinstance(prior, GoalSpec) and prior.approved:
            raise ValueError("ledger approved goal is frozen")
        if isinstance(record, GoalSpec) and record.goal_id != prior.goal_id:
            raise ValueError("ledger goal supersession cannot change goal_id")

    @staticmethod
    def _check_kind_rules(record: LedgerRecord, index: Mapping[str, LedgerRecord]) -> None:
        if isinstance(record, ActionIntent):
            goal = index[record.goal_ref.record_id]
            if not isinstance(goal, GoalSpec):
                raise ValueError("ledger intent goal_ref must resolve to a goal")
            if not goal.approved:
                raise ValueError("ledger intent requires an approved goal")
            if not goal.scope.covers(record.kind):
                raise ValueError("ledger intent kind is outside the goal scope")
            if record.created_at > goal.deadline_at:
                raise ValueError("ledger intent is past the goal deadline")
        elif isinstance(record, AuthorizationRecord):
            intent = index[record.intent_ref.record_id]
            if not isinstance(intent, ActionIntent):
                raise ValueError("ledger authorization must resolve to an intent")
            if record.decided_at < intent.created_at:
                raise ValueError("ledger authorization precedes its intent")
        elif isinstance(record, ExecutionRecord):
            authorization = index[record.authorization_ref.record_id]
            if not isinstance(authorization, AuthorizationRecord):
                raise ValueError("ledger execution must resolve to an authorization")
            if authorization.verdict == "deny":
                raise ValueError("ledger execution cannot follow a denied intent")
            if record.status in _EXECUTED_STATUSES and authorization.verdict != "grant":
                raise ValueError("ledger execution beyond queued requires a grant")
            if record.started_at is not None and record.started_at < authorization.decided_at:
                raise ValueError("ledger execution started before its authorization")
        elif isinstance(record, VerificationRecord):
            execution = index[record.execution_ref.record_id]
            if not isinstance(execution, ExecutionRecord):
                raise ValueError("ledger verification must resolve to an execution")
            if execution.status not in {"done", "partial", "failed"}:
                raise ValueError("ledger verification requires a finished execution")
            if execution.finished_at is not None and record.verified_at < execution.finished_at:
                raise ValueError("ledger verification precedes the execution it verifies")
        elif isinstance(record, OutcomeRecord):
            verification = index[record.verification_ref.record_id]
            if not isinstance(verification, VerificationRecord):
                raise ValueError("ledger outcome must resolve to a verification")
            if record.observed_at < verification.verified_at:
                raise ValueError("ledger outcome precedes its verification")
            if record.comparison_status == "confirmed" and verification.verdict != "verified":
                raise ValueError(
                    "ledger confirmed outcome requires a verified verification"
                )


def load_chain(payloads: Iterable[Any]) -> LedgerChain:
    return LedgerChain.build(load_record(payload) for payload in payloads)


def summarize(chain: LedgerChain) -> dict[str, Any]:
    """Count heads per kind and expose the ran-vs-verified distinction plainly."""

    heads = chain.heads
    counts = dict.fromkeys(_KIND_ORDER, 0)
    for record in heads:
        counts[record.record_kind] += 1
    executed_done = sum(
        1 for r in heads if isinstance(r, ExecutionRecord) and r.status == "done"
    )
    verified = sum(
        1 for r in heads if isinstance(r, VerificationRecord) and r.verdict == "verified"
    )
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "records": len(chain.records),
        "heads": counts,
        "executed_done": executed_done,
        "verified": verified,
        "unresolved_external_refs": len(chain.unresolved),
        "fingerprint": chain.fingerprint,
    }


__all__ = [
    "AUTHORITY",
    "SCHEMA",
    "ActionIntent",
    "AuthorizationRecord",
    "EvidenceRecord",
    "ExecutionRecord",
    "GoalBudget",
    "GoalScope",
    "GoalSpec",
    "LedgerChain",
    "LedgerRecord",
    "LedgerRef",
    "OutcomeRecord",
    "VerificationRecord",
    "load_chain",
    "load_record",
    "summarize",
]
