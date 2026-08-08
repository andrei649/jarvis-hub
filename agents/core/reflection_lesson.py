"""Evidence-bound outcome comparison and ``nerva.lesson.v1`` proposals for E6.0.

Reflection compares an expected outcome with retained observed/verified outcome
evidence and may emit a typed, reversible proposal. It is deliberately
``proposal_only``: it cannot rewrite source evidence, promote its own proposal,
authorize an action, execute work, or mark work complete. Destination modules
remain the sole promotion owners and Ultron / ``nerva.action.v1`` remains the
sole privileged-action authority.

Negative, contradictory and insufficient results are retained with their
privacy, tombstone and verdict state intact. Ineligible evidence stays visible
but can never support a proposal.

The module is additive. It does not modify ``DailyReflector`` behavior, does not
consolidate or forget memories, and does not write to Episodes or Atlas.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from agents.core.memory.atlas_snapshot import AtlasConfidence, PrivacyClass
from agents.core.memory.episodes import EpisodeReference

ComparisonStatus = Literal[
    "confirmed",
    "refuted",
    "contradictory",
    "insufficient_evidence",
]
LessonLifecycle = Literal[
    "proposed",
    "accepted_by_destination",
    "rejected",
    "expired",
    "superseded",
]
LessonDestination = Literal[
    "episodes",
    "howard",
    "synapse",
    "experience",
    "human_review",
]
ExclusionReason = Literal["tombstoned", "no_verdict"]

_ALLOWED_COMPARISON_STATUSES = {
    "confirmed",
    "refuted",
    "contradictory",
    "insufficient_evidence",
}
_ALLOWED_LIFECYCLES = {
    "proposed",
    "accepted_by_destination",
    "rejected",
    "expired",
    "superseded",
}
_ALLOWED_DESTINATIONS = {
    "episodes",
    "howard",
    "synapse",
    "experience",
    "human_review",
}
_ALLOWED_EXCLUSION_REASONS = {"tombstoned", "no_verdict"}
_ALLOWED_PRIVACY_CLASSES = {"public", "personal", "private_local", "restricted"}

# Privacy may only escalate when evidence is combined; it never downgrades.
_PRIVACY_RANK = {
    "public": 0,
    "personal": 1,
    "private_local": 2,
    "restricted": 3,
}

# A lesson derived from restricted evidence may only be routed to a human gate.
_RESTRICTED_DESTINATIONS = {"human_review"}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {
        "accepted_by_destination",
        "rejected",
        "expired",
        "superseded",
    },
    "accepted_by_destination": {"expired", "superseded"},
    "rejected": set(),
    "expired": {"superseded"},
    "superseded": set(),
}

# Reflection observes and proposes; it is never a valid promoting actor.
_FORBIDDEN_PROMOTION_ACTORS = {"reflection", "nerva.reflection", "daily_reflector"}

# Module-private construction guard. Any lifecycle beyond ``proposed`` is
# reachable only through ``transition_lesson()``; a directly constructed
# accepted/rejected/expired/superseded proposal is noncanonical and rejected.
_TRANSITION_GUARD = object()

_SHA256_HEX_LENGTH = 64
_MAX_CLAIM_CHARS = 2048
_MAX_SCOPE_CHARS = 256
_MAX_LIMITATION_CHARS = 512

# E6.0 records are ``proposal_only``. The serialized authority ceiling is a
# module constant re-asserted at emission time: the ``init=False`` dataclass
# fields can still be flipped with ``object.__setattr__`` after construction,
# so ``canonical_payload`` must never trust the instance state for these keys.
_PROPOSAL_ONLY_CEILING: dict[str, Any] = {
    "authority": "proposal_only",
    "can_rewrite_source_evidence": False,
    "can_promote_lesson": False,
    "can_authorize": False,
    "can_execute": False,
    "can_mark_complete": False,
}


@dataclass(frozen=True)
class OutcomeVerdict:
    """Retained per-reference eligibility, verdict and classification state.

    Evidence is never dropped to make a comparison look cleaner. An excluded
    reference keeps its privacy class and tombstone state so retention limits
    stay visible downstream.
    """

    reference_id: str
    eligible: bool
    matched: bool | None
    exclusion_reason: ExclusionReason | None
    privacy_class: PrivacyClass
    tombstoned: bool
    schema: str = field(default="nerva.outcome-verdict.v1", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.reference_id, "verdict reference_id")
        if not isinstance(self.eligible, bool):
            raise ValueError("Reflection verdict eligible must be boolean")
        if not isinstance(self.tombstoned, bool):
            raise ValueError("Reflection verdict tombstoned must be boolean")
        _validate_privacy_class(self.privacy_class)
        if self.eligible:
            if not isinstance(self.matched, bool):
                raise ValueError("Reflection eligible verdict requires a boolean match")
            if self.exclusion_reason is not None:
                raise ValueError("Reflection eligible verdict cannot be excluded")
            if self.tombstoned:
                raise ValueError("Reflection tombstoned evidence cannot be eligible")
            return
        if self.matched is not None:
            raise ValueError("Reflection ineligible verdict cannot carry a match")
        if self.exclusion_reason not in _ALLOWED_EXCLUSION_REASONS:
            raise ValueError("Reflection exclusion reason is not recognized")
        # The reason must agree with the tombstone state in both directions, so
        # a live unresolved reference cannot be relabelled as deleted evidence.
        expected_reason = "tombstoned" if self.tombstoned else "no_verdict"
        if self.exclusion_reason != expected_reason:
            raise ValueError(
                "Reflection exclusion reason must match the tombstone state"
            )


@dataclass(frozen=True)
class OutcomeObservation:
    """Immutable comparison of one expected outcome against observed evidence."""

    observation_id: str
    episode_id: str
    expected_reference: EpisodeReference
    observed_references: tuple[EpisodeReference, ...]
    verdicts: tuple[OutcomeVerdict, ...]
    comparison_status: ComparisonStatus
    environment: str
    evidence_limitations: tuple[str, ...]
    privacy_class: PrivacyClass
    confidence: AtlasConfidence
    observed_at: float
    created_at: float
    schema: str = field(default="nerva.outcome-observation.v1", init=False)
    authority: str = field(default="proposal_only", init=False)
    can_rewrite_source_evidence: bool = field(default=False, init=False)
    can_promote_lesson: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.observation_id, "observation_id")
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.environment, "environment")

        if not isinstance(self.expected_reference, EpisodeReference):
            raise ValueError("Reflection expected_reference must be EpisodeReference")
        if self.expected_reference.role != "decision":
            raise ValueError("Reflection expected_reference must use the decision role")
        if self.expected_reference.tombstoned:
            raise ValueError("Reflection cannot compare against a tombstoned decision")

        if not isinstance(self.observed_references, tuple):
            raise ValueError("Reflection observed_references must be a tuple")
        seen: set[str] = set()
        for reference in self.observed_references:
            if not isinstance(reference, EpisodeReference):
                raise ValueError(
                    "Reflection observed_references must contain EpisodeReference"
                )
            if reference.role != "outcome":
                raise ValueError(
                    "Reflection observed_references must use the outcome role"
                )
            if reference.reference_id in seen:
                raise ValueError("Reflection observed_references cannot duplicate IDs")
            seen.add(reference.reference_id)
        expected_order = tuple(sorted(self.observed_references, key=_observed_sort_key))
        if self.observed_references != expected_order:
            raise ValueError(
                "Reflection observed_references are not deterministically ordered"
            )

        if not isinstance(self.verdicts, tuple):
            raise ValueError("Reflection verdicts must be a tuple")
        for verdict in self.verdicts:
            if not isinstance(verdict, OutcomeVerdict):
                raise ValueError("Reflection verdicts must contain OutcomeVerdict")
        verdict_ids = [verdict.reference_id for verdict in self.verdicts]
        if len(set(verdict_ids)) != len(verdict_ids):
            raise ValueError("Reflection verdicts cannot duplicate a reference")
        if set(verdict_ids) != seen:
            raise ValueError(
                "Reflection verdicts must cover exactly the observed references"
            )
        if list(verdict_ids) != sorted(verdict_ids):
            raise ValueError("Reflection verdicts are not deterministically ordered")

        by_id = {
            reference.reference_id: reference for reference in self.observed_references
        }
        for verdict in self.verdicts:
            reference = by_id[verdict.reference_id]
            if verdict.tombstoned != reference.tombstoned:
                raise ValueError("Reflection verdict tombstone state must match")
            if verdict.privacy_class != reference.privacy_class:
                raise ValueError("Reflection verdict privacy class must match")

        if self.comparison_status not in _ALLOWED_COMPARISON_STATUSES:
            raise ValueError("Reflection comparison status is not recognized")
        _validate_privacy_class(self.privacy_class)
        if not isinstance(self.confidence, AtlasConfidence):
            raise ValueError("Reflection confidence must be AtlasConfidence")

        limitations = _validated_string_tuple(
            self.evidence_limitations,
            "evidence_limitations",
            max_chars=_MAX_LIMITATION_CHARS,
        )
        object.__setattr__(self, "evidence_limitations", limitations)

        _validate_time(self.observed_at, "observed_at")
        _validate_time(self.created_at, "created_at")
        if self.created_at < self.observed_at:
            raise ValueError("Reflection created_at cannot precede observed_at")
        if self.observed_at < self.expected_reference.occurred_at:
            raise ValueError("Reflection outcome cannot precede the expected decision")
        for reference in self.observed_references:
            if reference.occurred_at < self.expected_reference.occurred_at:
                raise ValueError(
                    "Reflection observed evidence cannot precede the expected decision"
                )
            if reference.occurred_at > self.observed_at:
                raise ValueError(
                    "Reflection observed evidence cannot follow observed_at"
                )

        eligible = self.eligible_verdicts
        # Fail closed on partial evidence: any retained reference that is
        # unresolved or deleted forces ``insufficient_evidence``. A comparison
        # never reports a verdict over evidence it could not fully evaluate.
        if self.excluded_verdicts and self.comparison_status != "insufficient_evidence":
            raise ValueError(
                "Reflection cannot report a verdict alongside unresolved evidence"
            )
        if self.comparison_status in {"confirmed", "refuted"} and not eligible:
            raise ValueError(
                "Reflection cannot confirm or refute without eligible outcome evidence"
            )
        if self.comparison_status == "contradictory" and len(eligible) < 2:
            raise ValueError(
                "Reflection contradictory status requires at least two eligible outcomes"
            )
        if (
            self.comparison_status == "insufficient_evidence"
            and eligible
            and not self.excluded_verdicts
        ):
            raise ValueError(
                "Reflection insufficient_evidence conflicts with complete evidence"
            )
        matches = {verdict.matched for verdict in eligible}
        if self.comparison_status == "confirmed" and matches != {True}:
            raise ValueError("Reflection confirmed status requires matching evidence")
        if self.comparison_status == "refuted" and matches != {False}:
            raise ValueError("Reflection refuted status requires non-matching evidence")
        if self.comparison_status == "contradictory" and matches != {True, False}:
            raise ValueError("Reflection contradictory status requires mixed evidence")

        # Privacy is escalated across every retained reference, eligible or not,
        # so excluding evidence can never downgrade the classification.
        minimum_privacy = _escalated_privacy(
            (self.expected_reference, *self.observed_references)
        )
        if _PRIVACY_RANK[self.privacy_class] < _PRIVACY_RANK[minimum_privacy]:
            raise ValueError("Reflection privacy class cannot downgrade its evidence")

        if self.observation_id != self.expected_observation_id:
            raise ValueError("Reflection observation_id does not match its evidence")

    @property
    def eligible_verdicts(self) -> tuple[OutcomeVerdict, ...]:
        return tuple(verdict for verdict in self.verdicts if verdict.eligible)

    @property
    def eligible_reference_ids(self) -> tuple[str, ...]:
        """Reference IDs that may support or counter a proposal."""

        return tuple(verdict.reference_id for verdict in self.eligible_verdicts)

    @property
    def excluded_verdicts(self) -> tuple[OutcomeVerdict, ...]:
        """Retained but ineligible evidence, with its exclusion reason intact."""

        return tuple(verdict for verdict in self.verdicts if not verdict.eligible)

    @property
    def expected_observation_id(self) -> str:
        return "reflection:obs:" + _sha256(self._identity_material())[:24]

    def _identity_material(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "expected_reference_id": self.expected_reference.reference_id,
            "verdicts": [
                {
                    "reference_id": verdict.reference_id,
                    "eligible": verdict.eligible,
                    "matched": verdict.matched,
                    "exclusion_reason": verdict.exclusion_reason,
                }
                for verdict in self.verdicts
            ],
            "comparison_status": self.comparison_status,
            "environment": self.environment,
            "privacy_class": self.privacy_class,
            "observed_at": float(self.observed_at),
        }

    def canonical_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(_PROPOSAL_ONLY_CEILING)
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.canonical_payload())

    @property
    def replay_fingerprint(self) -> str:
        return _sha256(self.to_json())


@dataclass(frozen=True)
class LessonProposal:
    """Immutable ``nerva.lesson.v1`` proposal awaiting destination acceptance."""

    proposal_id: str
    claim: str
    scope: str
    observation_ids: tuple[str, ...]
    supporting_reference_ids: tuple[str, ...]
    counter_reference_ids: tuple[str, ...]
    confidence: AtlasConfidence
    applicability: tuple[str, ...]
    proposed_destinations: tuple[LessonDestination, ...]
    contradicts_proposal_ids: tuple[str, ...]
    privacy_class: PrivacyClass
    lifecycle: LessonLifecycle
    revision: int
    created_at: float
    review_at: float
    expires_at: float
    accepted_by: LessonDestination | None = None
    accepted_at: float | None = None
    superseded_by_proposal_id: str | None = None
    prior_fingerprint: str | None = None
    guard: Any = field(default=None, compare=False, repr=False)
    schema: str = field(default="nerva.lesson.v1", init=False)
    authority: str = field(default="proposal_only", init=False)
    can_rewrite_source_evidence: bool = field(default=False, init=False)
    can_promote_lesson: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.proposal_id, "proposal_id")
        _require_non_empty(self.claim, "claim")
        _require_non_empty(self.scope, "scope")
        if len(self.claim) > _MAX_CLAIM_CHARS:
            raise ValueError("Reflection claim exceeds the bounded character limit")
        if len(self.scope) > _MAX_SCOPE_CHARS:
            raise ValueError("Reflection scope exceeds the bounded character limit")

        observation_ids = _validated_string_tuple(
            self.observation_ids,
            "observation_ids",
            allow_empty=False,
        )
        object.__setattr__(self, "observation_ids", observation_ids)

        supporting = _validated_string_tuple(
            self.supporting_reference_ids,
            "supporting_reference_ids",
            allow_empty=False,
        )
        counter = _validated_string_tuple(
            self.counter_reference_ids,
            "counter_reference_ids",
        )
        object.__setattr__(self, "supporting_reference_ids", supporting)
        object.__setattr__(self, "counter_reference_ids", counter)
        if set(supporting) & set(counter):
            raise ValueError(
                "Reflection evidence cannot both support and counter one claim"
            )

        applicability = _validated_string_tuple(self.applicability, "applicability")
        object.__setattr__(self, "applicability", applicability)
        contradicts = _validated_string_tuple(
            self.contradicts_proposal_ids,
            "contradicts_proposal_ids",
        )
        object.__setattr__(self, "contradicts_proposal_ids", contradicts)
        if self.proposal_id in contradicts:
            raise ValueError("Reflection proposal cannot contradict itself")

        destinations = _validated_string_tuple(
            self.proposed_destinations,
            "proposed_destinations",
            allow_empty=False,
        )
        for destination in destinations:
            if destination not in _ALLOWED_DESTINATIONS:
                raise ValueError("Reflection destination is not recognized")
        object.__setattr__(self, "proposed_destinations", destinations)

        _validate_privacy_class(self.privacy_class)
        if (
            self.privacy_class == "restricted"
            and set(destinations) - _RESTRICTED_DESTINATIONS
        ):
            raise ValueError(
                "Reflection restricted-privacy lessons may only target human review"
            )

        if not isinstance(self.confidence, AtlasConfidence):
            raise ValueError("Reflection confidence must be AtlasConfidence")
        if self.lifecycle not in _ALLOWED_LIFECYCLES:
            raise ValueError("Reflection lifecycle is not recognized")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise ValueError("Reflection revision must be an integer")
        if self.revision < 1:
            raise ValueError("Reflection revision must be positive")

        _validate_time(self.created_at, "created_at")
        _validate_time(self.review_at, "review_at")
        _validate_time(self.expires_at, "expires_at")
        if self.review_at < self.created_at:
            raise ValueError("Reflection review_at cannot precede created_at")
        if self.expires_at < self.review_at:
            raise ValueError("Reflection expires_at cannot precede review_at")

        # Acceptance and every other advanced state is absent by default and
        # reachable only through a destination-owned, audited transition.
        if self.lifecycle == "proposed":
            if self.revision != 1:
                raise ValueError("Reflection proposed state must be revision 1")
            for value, name in (
                (self.accepted_by, "accepted_by"),
                (self.accepted_at, "accepted_at"),
                (self.superseded_by_proposal_id, "superseded_by_proposal_id"),
                (self.prior_fingerprint, "prior_fingerprint"),
            ):
                if value is not None:
                    raise ValueError(f"Reflection proposed state cannot carry {name}")
        else:
            if self.guard is not _TRANSITION_GUARD:
                raise ValueError(
                    "Reflection lifecycle beyond proposed requires an audited "
                    "transition"
                )
            if self.revision < 2:
                raise ValueError("Reflection transitioned state requires revision >= 2")
            _validate_sha256_hex(self.prior_fingerprint, "prior_fingerprint")

        if self.lifecycle == "accepted_by_destination" and (
            self.accepted_by is None or self.accepted_at is None
        ):
            raise ValueError("Reflection acceptance requires destination evidence")
        if self.accepted_by is not None:
            if self.accepted_by not in self.proposed_destinations:
                raise ValueError("Reflection accepted_by must be a proposed destination")
            _validate_time(self.accepted_at, "accepted_at")
            if self.accepted_at < self.created_at:
                raise ValueError("Reflection accepted_at cannot precede created_at")
        elif self.accepted_at is not None:
            raise ValueError("Reflection accepted_at requires an accepting destination")

        if self.lifecycle == "superseded" and self.superseded_by_proposal_id is None:
            raise ValueError("Reflection superseded state requires a replacement")
        if self.superseded_by_proposal_id is not None:
            _require_non_empty(
                self.superseded_by_proposal_id, "superseded_by_proposal_id"
            )
            if self.superseded_by_proposal_id == self.proposal_id:
                raise ValueError("Reflection proposal cannot supersede itself")
            if self.lifecycle != "superseded":
                raise ValueError(
                    "Reflection replacement is only valid in the superseded state"
                )

        # The guard is a construction capability, never retained state.
        object.__setattr__(self, "guard", None)

        if self.proposal_id != self.expected_proposal_id:
            raise ValueError("Reflection proposal_id does not match its evidence")

    @property
    def expected_proposal_id(self) -> str:
        return "reflection:lesson:" + _sha256(self._identity_material())[:24]

    def _identity_material(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "scope": self.scope,
            "observation_ids": list(self.observation_ids),
            "supporting_reference_ids": list(self.supporting_reference_ids),
            "counter_reference_ids": list(self.counter_reference_ids),
            "created_at": float(self.created_at),
        }

    def canonical_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        # The construction guard is never serialized or fingerprinted.
        payload.pop("guard", None)
        payload.update(_PROPOSAL_ONLY_CEILING)
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.canonical_payload())

    @property
    def replay_fingerprint(self) -> str:
        return _sha256(self.to_json())


@dataclass(frozen=True)
class LessonAuditEvent:
    """Audit trail entry retaining and validating the exact prior payload."""

    proposal_id: str
    from_lifecycle: LessonLifecycle
    to_lifecycle: LessonLifecycle
    actor: str
    reason: str
    occurred_at: float
    prior_revision: int
    prior_fingerprint: str
    prior_payload_json: str
    destination: LessonDestination | None = None
    replacement_proposal_id: str | None = None
    schema: str = field(default="nerva.lesson.audit.v1", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.proposal_id, "audit proposal_id")
        _require_non_empty(self.actor, "audit actor")
        _require_non_empty(self.reason, "audit reason")
        _validate_time(self.occurred_at, "audit occurred_at")
        if self.from_lifecycle not in _ALLOWED_LIFECYCLES:
            raise ValueError("Reflection audit from_lifecycle is not recognized")
        if self.to_lifecycle not in _ALLOWED_LIFECYCLES:
            raise ValueError("Reflection audit to_lifecycle is not recognized")
        if isinstance(self.prior_revision, bool) or not isinstance(
            self.prior_revision, int
        ):
            raise ValueError("Reflection audit prior_revision must be an integer")
        _validate_sha256_hex(self.prior_fingerprint, "audit prior_fingerprint")

        # The retained payload must be canonical and self-consistent, so
        # ``restore_prior()`` can never return arbitrary claimed history.
        if not isinstance(self.prior_payload_json, str):
            raise ValueError("Reflection audit prior_payload_json must be a string")
        try:
            payload = json.loads(self.prior_payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Reflection audit prior payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Reflection audit prior payload must be an object")
        if _canonical_json(payload) != self.prior_payload_json:
            raise ValueError("Reflection audit prior payload is not canonical JSON")
        if _sha256(self.prior_payload_json) != self.prior_fingerprint:
            raise ValueError("Reflection audit prior payload does not match its hash")
        if payload.get("proposal_id") != self.proposal_id:
            raise ValueError("Reflection audit prior payload names another proposal")
        if payload.get("lifecycle") != self.from_lifecycle:
            raise ValueError("Reflection audit prior payload contradicts from_lifecycle")
        if payload.get("revision") != self.prior_revision:
            raise ValueError("Reflection audit prior payload contradicts prior_revision")
        if payload.get("schema") != "nerva.lesson.v1":
            raise ValueError("Reflection audit prior payload is not a lesson record")

        # Validate the complete prior payload as a canonical proposal revision.
        # Re-serializing the rebuilt record must reproduce the retained bytes
        # exactly, so no field — claim, evidence, authority flag, chronology or
        # acceptance state — can be altered and re-hashed into fake history.
        try:
            prior = _rebuild_proposal(payload)
        except ValueError as exc:
            raise ValueError(
                f"Reflection audit prior payload is not a valid lesson revision: {exc}"
            ) from exc
        if prior.to_json() != self.prior_payload_json:
            raise ValueError(
                "Reflection audit prior payload is not a canonical lesson revision"
            )

        # Validate the recorded transition itself, not only its endpoints.
        if self.to_lifecycle not in _ALLOWED_TRANSITIONS[self.from_lifecycle]:
            raise ValueError("Reflection audit records an impossible transition")
        if self.occurred_at < prior.created_at:
            raise ValueError("Reflection audit cannot precede proposal creation")

        if self.to_lifecycle == "accepted_by_destination":
            if self.destination is None:
                raise ValueError("Reflection audit acceptance requires a destination")
            if self.destination not in prior.proposed_destinations:
                raise ValueError("Reflection audit destination was never proposed")
            if self.actor.strip().casefold() in _FORBIDDEN_PROMOTION_ACTORS:
                raise ValueError("Reflection audit cannot record a self-promotion")
            if self.actor.strip().casefold() != self.destination:
                raise ValueError("Reflection audit actor must be the destination")
        if (
            self.destination is not None
            and self.destination not in _ALLOWED_DESTINATIONS
        ):
            raise ValueError("Reflection audit destination is not recognized")
        if self.to_lifecycle == "expired" and self.occurred_at < prior.expires_at:
            raise ValueError("Reflection audit cannot expire before expires_at")
        if self.to_lifecycle == "superseded":
            _require_non_empty(
                self.replacement_proposal_id, "audit replacement_proposal_id"
            )
            if self.replacement_proposal_id == self.proposal_id:
                raise ValueError("Reflection audit replacement cannot be the proposal")
        elif self.replacement_proposal_id is not None:
            raise ValueError("Reflection audit replacement is only valid on supersession")

    def restore_prior(self) -> dict[str, Any]:
        """Return the validated exact prior payload so transitions stay reversible."""

        return json.loads(self.prior_payload_json)


def _rebuild_proposal(payload: Mapping[str, Any]) -> LessonProposal:
    """Rebuild a proposal from a payload using fixed authority values.

    Authority flags, schema and the derived identifier are never taken from the
    payload; they are recomputed. Callers compare the rebuilt record's canonical
    JSON with the supplied bytes, so any forged or unknown field is detected.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("Reflection proposal payload must be a mapping")
    confidence_payload = payload.get("confidence")
    if not isinstance(confidence_payload, Mapping):
        raise ValueError("Reflection proposal payload requires qualified confidence")
    if set(confidence_payload) != {"status", "value", "source"}:
        raise ValueError("Reflection proposal confidence has unexpected fields")

    return LessonProposal(
        proposal_id=payload.get("proposal_id"),
        claim=payload.get("claim"),
        scope=payload.get("scope"),
        observation_ids=_as_string_tuple(payload.get("observation_ids")),
        supporting_reference_ids=_as_string_tuple(
            payload.get("supporting_reference_ids")
        ),
        counter_reference_ids=_as_string_tuple(payload.get("counter_reference_ids")),
        confidence=AtlasConfidence(
            status=confidence_payload.get("status"),
            value=confidence_payload.get("value"),
            source=confidence_payload.get("source"),
        ),
        applicability=_as_string_tuple(payload.get("applicability")),
        proposed_destinations=_as_string_tuple(payload.get("proposed_destinations")),
        contradicts_proposal_ids=_as_string_tuple(
            payload.get("contradicts_proposal_ids")
        ),
        privacy_class=payload.get("privacy_class"),
        lifecycle=payload.get("lifecycle"),
        revision=payload.get("revision"),
        created_at=payload.get("created_at"),
        review_at=payload.get("review_at"),
        expires_at=payload.get("expires_at"),
        accepted_by=payload.get("accepted_by"),
        accepted_at=payload.get("accepted_at"),
        superseded_by_proposal_id=payload.get("superseded_by_proposal_id"),
        prior_fingerprint=payload.get("prior_fingerprint"),
        guard=_TRANSITION_GUARD,
    )


def compare_outcome(
    *,
    episode_id: str,
    expected_reference: EpisodeReference,
    observed_references: tuple[EpisodeReference, ...],
    matches_expectation: Mapping[str, bool],
    environment: str,
    observed_at: float,
    created_at: float,
    confidence: AtlasConfidence | None = None,
    evidence_limitations: tuple[str, ...] = (),
    privacy_class: PrivacyClass | None = None,
) -> OutcomeObservation:
    """Derive a deterministic comparison from expected and observed evidence.

    ``matches_expectation`` maps each live outcome ``reference_id`` to whether it
    matched the expected outcome. Missing verdicts are never guessed: an
    unjudged live reference is retained as ineligible evidence and forces
    ``insufficient_evidence`` rather than a confident-looking result.
    """

    if not isinstance(observed_references, tuple):
        raise ValueError("Reflection observed_references must be a tuple")
    ordered = tuple(sorted(observed_references, key=_observed_sort_key))

    verdicts: list[OutcomeVerdict] = []
    for reference in ordered:
        if reference.tombstoned:
            verdicts.append(
                OutcomeVerdict(
                    reference_id=reference.reference_id,
                    eligible=False,
                    matched=None,
                    exclusion_reason="tombstoned",
                    privacy_class=reference.privacy_class,
                    tombstoned=True,
                )
            )
            continue
        verdict = matches_expectation.get(reference.reference_id)
        if not isinstance(verdict, bool):
            verdicts.append(
                OutcomeVerdict(
                    reference_id=reference.reference_id,
                    eligible=False,
                    matched=None,
                    exclusion_reason="no_verdict",
                    privacy_class=reference.privacy_class,
                    tombstoned=False,
                )
            )
            continue
        verdicts.append(
            OutcomeVerdict(
                reference_id=reference.reference_id,
                eligible=True,
                matched=verdict,
                exclusion_reason=None,
                privacy_class=reference.privacy_class,
                tombstoned=False,
            )
        )
    verdicts.sort(key=lambda verdict: verdict.reference_id)

    matches = [verdict.matched for verdict in verdicts if verdict.eligible]
    excluded = [verdict for verdict in verdicts if not verdict.eligible]
    # Partial evidence is never summarised as a verdict. One unresolved or
    # deleted reference is enough to make the whole comparison insufficient.
    if not matches or excluded:
        status: ComparisonStatus = "insufficient_evidence"
    elif len(set(matches)) > 1:
        status = "contradictory"
    elif matches[0]:
        status = "confirmed"
    else:
        status = "refuted"

    limitations = list(evidence_limitations)
    unjudged = sum(
        1 for verdict in verdicts if verdict.exclusion_reason == "no_verdict"
    )
    tombstoned = sum(
        1 for verdict in verdicts if verdict.exclusion_reason == "tombstoned"
    )
    if unjudged:
        limitations.append(
            f"{unjudged} live outcome reference(s) retained without a verdict"
        )
    if tombstoned:
        limitations.append(
            f"{tombstoned} tombstoned outcome reference(s) retained as ineligible"
        )
    # Limitations are a set-like trail; a caller-supplied duplicate must not
    # turn an honest comparison into a validation failure.
    limitations = list(dict.fromkeys(limitations))

    # Privacy escalates across every retained reference, so excluded evidence
    # keeps its classification instead of silently lowering the observation's.
    resolved_privacy = privacy_class or _escalated_privacy(
        (expected_reference, *ordered)
    )
    material = {
        "episode_id": episode_id,
        "expected_reference_id": expected_reference.reference_id,
        "verdicts": [
            {
                "reference_id": verdict.reference_id,
                "eligible": verdict.eligible,
                "matched": verdict.matched,
                "exclusion_reason": verdict.exclusion_reason,
            }
            for verdict in verdicts
        ],
        "comparison_status": status,
        "environment": environment,
        "privacy_class": resolved_privacy,
        "observed_at": float(observed_at),
    }
    return OutcomeObservation(
        observation_id="reflection:obs:" + _sha256(material)[:24],
        episode_id=episode_id,
        expected_reference=expected_reference,
        observed_references=ordered,
        verdicts=tuple(verdicts),
        comparison_status=status,
        environment=environment,
        evidence_limitations=tuple(limitations),
        privacy_class=resolved_privacy,
        confidence=confidence or AtlasConfidence("unknown"),
        observed_at=observed_at,
        created_at=created_at,
    )


def derive_proposal_evidence(
    observations: tuple[OutcomeObservation, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], PrivacyClass]:
    """Return the only evidence graph a canonical proposal may claim.

    Used both when proposing and when validating an externally supplied
    proposal, so a forged claim cannot present invented references.
    """

    if not isinstance(observations, tuple) or not observations:
        raise ValueError("Reflection proposal requires at least one observation")

    supporting: set[str] = set()
    counter: set[str] = set()
    privacy = "public"
    for observation in observations:
        if not isinstance(observation, OutcomeObservation):
            raise ValueError("Reflection proposal requires OutcomeObservation evidence")
        eligible = set(observation.eligible_reference_ids)
        if observation.comparison_status == "confirmed":
            supporting |= eligible
        elif observation.comparison_status in {"refuted", "contradictory"}:
            # Contradiction is retained as counter-evidence rather than dropped.
            counter |= eligible
        if _PRIVACY_RANK[observation.privacy_class] > _PRIVACY_RANK[privacy]:
            privacy = observation.privacy_class

    if not supporting:
        raise ValueError(
            "Reflection proposal requires at least one confirmed supporting reference"
        )
    # A reference cannot simultaneously support and counter the same claim.
    counter -= supporting

    observation_ids = tuple(sorted({obs.observation_id for obs in observations}))
    return (
        observation_ids,
        tuple(sorted(supporting)),
        tuple(sorted(counter)),
        privacy,  # type: ignore[return-value]
    )


def propose_lesson(
    *,
    observations: tuple[OutcomeObservation, ...],
    claim: str,
    scope: str,
    proposed_destinations: tuple[LessonDestination, ...],
    created_at: float,
    review_at: float,
    expires_at: float,
    confidence: AtlasConfidence | None = None,
    applicability: tuple[str, ...] = (),
    contradicts_proposal_ids: tuple[str, ...] = (),
) -> LessonProposal:
    """Emit one bounded proposal from evidence-bearing observations.

    Fails closed when no observation carries eligible confirming evidence, so an
    insufficient-evidence comparison can never produce an accepted-looking
    proposal.
    """

    observation_ids, supporting_ids, counter_ids, privacy = derive_proposal_evidence(
        observations
    )
    material = {
        "claim": claim,
        "scope": scope,
        "observation_ids": list(observation_ids),
        "supporting_reference_ids": list(supporting_ids),
        "counter_reference_ids": list(counter_ids),
        "created_at": float(created_at),
    }
    return LessonProposal(
        proposal_id="reflection:lesson:" + _sha256(material)[:24],
        claim=claim,
        scope=scope,
        observation_ids=observation_ids,
        supporting_reference_ids=supporting_ids,
        counter_reference_ids=counter_ids,
        confidence=confidence or AtlasConfidence("unknown"),
        applicability=applicability,
        proposed_destinations=proposed_destinations,
        contradicts_proposal_ids=contradicts_proposal_ids,
        privacy_class=privacy,
        lifecycle="proposed",
        revision=1,
        created_at=created_at,
        review_at=review_at,
        expires_at=expires_at,
    )


def validate_proposal_evidence(
    proposal: LessonProposal,
    observations: tuple[OutcomeObservation, ...],
) -> None:
    """Bind a proposal to its observation graph, rejecting forged references.

    A proposal is canonical only once it validates against the observations it
    claims. Recomputing ``proposal_id`` over invented references is not enough
    to pass this boundary.
    """

    if not isinstance(proposal, LessonProposal):
        raise ValueError("Reflection evidence binding requires a LessonProposal")
    observation_ids, supporting_ids, counter_ids, privacy = derive_proposal_evidence(
        observations
    )
    if proposal.observation_ids != observation_ids:
        raise ValueError("Reflection proposal claims unknown observations")
    if proposal.supporting_reference_ids != supporting_ids:
        raise ValueError("Reflection proposal claims unsupported evidence")
    if proposal.counter_reference_ids != counter_ids:
        raise ValueError("Reflection proposal claims unknown counter-evidence")
    if _PRIVACY_RANK[proposal.privacy_class] < _PRIVACY_RANK[privacy]:
        raise ValueError("Reflection proposal downgrades its evidence privacy")


def load_lesson_proposal(
    payload: Mapping[str, Any],
    observations: tuple[OutcomeObservation, ...],
) -> LessonProposal:
    """Canonical deserialization boundary for a ``proposed`` lesson record.

    Advanced lifecycles are never rebuilt from a payload; they are reachable
    only by replaying the audited transitions that produced them.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("Reflection proposal payload must be a mapping")
    if payload.get("schema") != "nerva.lesson.v1":
        raise ValueError("Reflection proposal payload is not a lesson record")
    if payload.get("lifecycle") != "proposed":
        raise ValueError(
            "Reflection deserialization only accepts the proposed lifecycle"
        )

    proposal = _rebuild_proposal(payload)
    # The rebuilt record recomputes schema, authority flags and the derived
    # identifier. Requiring byte-identical canonical JSON therefore rejects
    # forged authority, contradictory acceptance state, unknown keys, missing
    # keys and unsorted collections instead of silently normalizing them.
    if proposal.to_json() != _canonical_json(dict(payload)):
        raise ValueError(
            "Reflection proposal payload is not a canonical proposed record"
        )
    validate_proposal_evidence(proposal, observations)
    return proposal


def transition_lesson(
    proposal: LessonProposal,
    *,
    observations: tuple[OutcomeObservation, ...],
    to_lifecycle: LessonLifecycle,
    actor: str,
    reason: str,
    occurred_at: float,
    destination: LessonDestination | None = None,
    supersedes_with_proposal_id: str | None = None,
) -> tuple[LessonProposal, LessonAuditEvent]:
    """Advance a proposal's lifecycle and return the audited prior state.

    Destination acceptance is structurally separate from Reflection: the acting
    identity must be the destination itself, and that destination must be one
    the proposal actually targets.
    """

    validate_proposal_evidence(proposal, observations)
    if to_lifecycle not in _ALLOWED_LIFECYCLES:
        raise ValueError("Reflection lifecycle is not recognized")
    _require_non_empty(actor, "transition actor")
    _validate_time(occurred_at, "transition occurred_at")
    if occurred_at < proposal.created_at:
        raise ValueError("Reflection transition cannot precede proposal creation")

    allowed = _ALLOWED_TRANSITIONS[proposal.lifecycle]
    if to_lifecycle not in allowed:
        raise ValueError(
            f"Reflection cannot move a {proposal.lifecycle} proposal to {to_lifecycle}"
        )

    normalized_actor = actor.strip().casefold()
    if normalized_actor in _FORBIDDEN_PROMOTION_ACTORS and (
        to_lifecycle == "accepted_by_destination"
    ):
        raise ValueError("Reflection cannot promote its own lesson proposal")

    accepted_by = proposal.accepted_by
    accepted_at = proposal.accepted_at
    if to_lifecycle == "accepted_by_destination":
        if destination is None:
            raise ValueError("Reflection acceptance requires an explicit destination")
        if destination not in proposal.proposed_destinations:
            raise ValueError("Reflection acceptance requires a proposed destination")
        # The audited actor must be the destination that owns the promotion.
        if normalized_actor != destination:
            raise ValueError("Reflection acceptance actor must be the destination")
        accepted_by = destination
        accepted_at = occurred_at

    if to_lifecycle == "expired" and occurred_at < proposal.expires_at:
        raise ValueError("Reflection proposal cannot expire before expires_at")

    replacement = None
    if to_lifecycle == "superseded":
        _require_non_empty(supersedes_with_proposal_id, "supersedes_with_proposal_id")
        replacement = supersedes_with_proposal_id

    prior_payload = proposal.to_json()
    event = LessonAuditEvent(
        proposal_id=proposal.proposal_id,
        from_lifecycle=proposal.lifecycle,
        to_lifecycle=to_lifecycle,
        actor=actor,
        reason=reason,
        occurred_at=occurred_at,
        prior_revision=proposal.revision,
        prior_fingerprint=proposal.replay_fingerprint,
        prior_payload_json=prior_payload,
        destination=destination,
        replacement_proposal_id=replacement,
    )
    updated = LessonProposal(
        proposal_id=proposal.proposal_id,
        claim=proposal.claim,
        scope=proposal.scope,
        observation_ids=proposal.observation_ids,
        supporting_reference_ids=proposal.supporting_reference_ids,
        counter_reference_ids=proposal.counter_reference_ids,
        confidence=proposal.confidence,
        applicability=proposal.applicability,
        proposed_destinations=proposal.proposed_destinations,
        contradicts_proposal_ids=proposal.contradicts_proposal_ids,
        privacy_class=proposal.privacy_class,
        lifecycle=to_lifecycle,
        revision=proposal.revision + 1,
        created_at=proposal.created_at,
        review_at=proposal.review_at,
        expires_at=proposal.expires_at,
        accepted_by=accepted_by,
        accepted_at=accepted_at,
        superseded_by_proposal_id=replacement,
        prior_fingerprint=proposal.replay_fingerprint,
        guard=_TRANSITION_GUARD,
    )
    return updated, event


def _observed_sort_key(reference: EpisodeReference) -> tuple[float, str]:
    return (reference.occurred_at, reference.reference_id)


def _escalated_privacy(references: tuple[EpisodeReference, ...]) -> PrivacyClass:
    resolved = "public"
    for reference in references:
        if _PRIVACY_RANK[reference.privacy_class] > _PRIVACY_RANK[resolved]:
            resolved = reference.privacy_class
    return resolved  # type: ignore[return-value]


def _as_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("Reflection payload field must be a JSON array")
    return tuple(str(item) for item in value)


def _validated_string_tuple(
    value: Any,
    name: str,
    *,
    allow_empty: bool = True,
    max_chars: int | None = None,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"Reflection {name} must be an immutable tuple")
    if not value and not allow_empty:
        raise ValueError(f"Reflection {name} cannot be empty")
    normalized: list[str] = []
    for item in value:
        _require_non_empty(item, name)
        if max_chars is not None and len(item) > max_chars:
            raise ValueError(f"Reflection {name} entry exceeds its character limit")
        normalized.append(item.strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"Reflection {name} cannot contain duplicates")
    return tuple(sorted(normalized))


def _require_non_empty(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Reflection {name} must be a non-empty string")


def _validate_privacy_class(value: Any) -> None:
    if value not in _ALLOWED_PRIVACY_CLASSES:
        raise ValueError("Reflection privacy class is not recognized")


def _validate_sha256_hex(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"Reflection {name} must be a SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"Reflection {name} must be a SHA-256 hex digest")


def _validate_time(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Reflection {name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"Reflection {name} must be finite")


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    if not isinstance(value, str):
        value = _canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
