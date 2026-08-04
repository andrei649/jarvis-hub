"""Evidence-bound outcome comparison and ``nerva.lesson.v1`` proposals for E6.0.

Reflection compares an expected outcome with retained observed/verified outcome
evidence and may emit a typed, reversible proposal. It is deliberately
``proposal_only``: it cannot rewrite source evidence, promote its own proposal,
authorize an action, execute work, or mark work complete. Destination modules
remain the sole promotion owners and Ultron / ``nerva.action.v1`` remains the
sole privileged-action authority.

The module is additive. It does not modify ``DailyReflector`` behavior, does not
consolidate or forget memories, and does not write to Episodes or Atlas.
"""

from __future__ import annotations

import hashlib
import json
import math
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

_MAX_CLAIM_CHARS = 2048
_MAX_SCOPE_CHARS = 256
_MAX_LIMITATION_CHARS = 512


@dataclass(frozen=True)
class OutcomeObservation:
    """Immutable comparison of one expected outcome against observed evidence."""

    observation_id: str
    episode_id: str
    expected_reference: EpisodeReference
    observed_references: tuple[EpisodeReference, ...]
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
        expected_order = tuple(
            sorted(self.observed_references, key=_observed_sort_key)
        )
        if self.observed_references != expected_order:
            raise ValueError(
                "Reflection observed_references are not deterministically ordered"
            )

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

        usable = self.usable_references
        if self.comparison_status in {"confirmed", "refuted"} and not usable:
            raise ValueError(
                "Reflection cannot confirm or refute without live outcome evidence"
            )
        if self.comparison_status == "contradictory" and len(usable) < 2:
            raise ValueError(
                "Reflection contradictory status requires at least two live outcomes"
            )
        if self.comparison_status == "insufficient_evidence" and usable:
            raise ValueError(
                "Reflection insufficient_evidence conflicts with live outcome evidence"
            )

        minimum_privacy = _escalated_privacy(
            (self.expected_reference, *self.observed_references)
        )
        if _PRIVACY_RANK[self.privacy_class] < _PRIVACY_RANK[minimum_privacy]:
            raise ValueError("Reflection privacy class cannot downgrade its evidence")

        if self.observation_id != self.expected_observation_id:
            raise ValueError("Reflection observation_id does not match its evidence")

    @property
    def usable_references(self) -> tuple[EpisodeReference, ...]:
        """Live outcome references only; tombstoned evidence never supports a claim."""

        return tuple(
            reference
            for reference in self.observed_references
            if not reference.tombstoned
        )

    @property
    def expected_observation_id(self) -> str:
        return "reflection:obs:" + _sha256(self._identity_material())[:24]

    def _identity_material(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "expected_reference_id": self.expected_reference.reference_id,
            "observed_reference_ids": [
                reference.reference_id for reference in self.observed_references
            ],
            "comparison_status": self.comparison_status,
            "environment": self.environment,
            "observed_at": float(self.observed_at),
        }

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)

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
    supersedes_proposal_id: str | None = None
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
        if self.privacy_class == "restricted" and set(destinations) - _RESTRICTED_DESTINATIONS:
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

        if self.supersedes_proposal_id is not None:
            _require_non_empty(self.supersedes_proposal_id, "supersedes_proposal_id")
            if self.supersedes_proposal_id == self.proposal_id:
                raise ValueError("Reflection proposal cannot supersede itself")

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
        return asdict(self)

    def to_json(self) -> str:
        return _canonical_json(self.canonical_payload())

    @property
    def replay_fingerprint(self) -> str:
        return _sha256(self.to_json())


@dataclass(frozen=True)
class LessonAuditEvent:
    """Audit trail entry retaining the exact prior proposal payload."""

    proposal_id: str
    from_lifecycle: LessonLifecycle
    to_lifecycle: LessonLifecycle
    actor: str
    reason: str
    occurred_at: float
    prior_revision: int
    prior_fingerprint: str
    prior_payload_json: str
    schema: str = field(default="nerva.lesson.audit.v1", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.proposal_id, "audit proposal_id")
        _require_non_empty(self.actor, "audit actor")
        _require_non_empty(self.reason, "audit reason")
        _validate_time(self.occurred_at, "audit occurred_at")

    def restore_prior(self) -> dict[str, Any]:
        """Return the exact prior payload so a transition stays reversible."""

        return json.loads(self.prior_payload_json)


def compare_outcome(
    *,
    episode_id: str,
    expected_reference: EpisodeReference,
    observed_references: tuple[EpisodeReference, ...],
    matches_expectation: dict[str, bool],
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
    unjudged live reference forces ``insufficient_evidence`` rather than a
    confident-looking result.
    """

    if not isinstance(observed_references, tuple):
        raise ValueError("Reflection observed_references must be a tuple")
    ordered = tuple(sorted(observed_references, key=_observed_sort_key))
    live = tuple(reference for reference in ordered if not reference.tombstoned)

    verdicts: list[bool] = []
    unjudged = False
    for reference in live:
        verdict = matches_expectation.get(reference.reference_id)
        if not isinstance(verdict, bool):
            unjudged = True
            continue
        verdicts.append(verdict)

    if not live or not verdicts or unjudged:
        status: ComparisonStatus = "insufficient_evidence"
    elif len(set(verdicts)) > 1:
        status = "contradictory"
    elif verdicts[0]:
        status = "confirmed"
    else:
        status = "refuted"

    limitations = list(evidence_limitations)
    if unjudged:
        limitations.append("one or more live outcome references had no verdict")
    if len(live) != len(ordered):
        limitations.append("tombstoned outcome evidence was excluded")

    # ``insufficient_evidence`` must not retain live references, otherwise the
    # observation would contradict its own status. The references stay visible
    # through the limitation trail instead of being silently dropped.
    retained = () if status == "insufficient_evidence" else ordered
    if status == "insufficient_evidence" and ordered:
        limitations.append(
            f"{len(ordered)} outcome reference(s) excluded as unusable evidence"
        )

    # Limitations are a set-like trail; a caller-supplied duplicate must not
    # turn an honest comparison into a validation failure.
    limitations = list(dict.fromkeys(limitations))

    resolved_privacy = privacy_class or _escalated_privacy(
        (expected_reference, *retained)
    )
    material = {
        "episode_id": episode_id,
        "expected_reference_id": expected_reference.reference_id,
        "observed_reference_ids": [
            reference.reference_id for reference in retained
        ],
        "comparison_status": status,
        "environment": environment,
        "observed_at": float(observed_at),
    }
    return OutcomeObservation(
        observation_id="reflection:obs:" + _sha256(material)[:24],
        episode_id=episode_id,
        expected_reference=expected_reference,
        observed_references=retained,
        comparison_status=status,
        environment=environment,
        evidence_limitations=tuple(limitations),
        privacy_class=resolved_privacy,
        confidence=confidence or AtlasConfidence("unknown"),
        observed_at=observed_at,
        created_at=created_at,
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

    Fails closed when no observation carries usable evidence, so an
    insufficient-evidence comparison can never produce an accepted-looking
    proposal.
    """

    if not isinstance(observations, tuple) or not observations:
        raise ValueError("Reflection proposal requires at least one observation")

    supporting: set[str] = set()
    counter: set[str] = set()
    for observation in observations:
        if not isinstance(observation, OutcomeObservation):
            raise ValueError("Reflection proposal requires OutcomeObservation evidence")
        reference_ids = {
            reference.reference_id for reference in observation.usable_references
        }
        if observation.comparison_status == "confirmed":
            supporting |= reference_ids
        elif observation.comparison_status == "refuted":
            counter |= reference_ids
        elif observation.comparison_status == "contradictory":
            # Contradiction is retained as counter-evidence rather than dropped.
            counter |= reference_ids

    if not supporting:
        raise ValueError(
            "Reflection proposal requires at least one confirmed supporting reference"
        )
    # A reference cannot simultaneously support and counter the same claim.
    counter -= supporting

    privacy = "public"
    for observation in observations:
        if _PRIVACY_RANK[observation.privacy_class] > _PRIVACY_RANK[privacy]:
            privacy = observation.privacy_class

    observation_ids = tuple(sorted({obs.observation_id for obs in observations}))
    supporting_ids = tuple(sorted(supporting))
    counter_ids = tuple(sorted(counter))
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
        privacy_class=privacy,  # type: ignore[arg-type]
        lifecycle="proposed",
        revision=1,
        created_at=created_at,
        review_at=review_at,
        expires_at=expires_at,
    )


def transition_lesson(
    proposal: LessonProposal,
    *,
    to_lifecycle: LessonLifecycle,
    actor: str,
    reason: str,
    occurred_at: float,
    destination: LessonDestination | None = None,
    supersedes_with_proposal_id: str | None = None,
) -> tuple[LessonProposal, LessonAuditEvent]:
    """Advance a proposal's lifecycle and return the audited prior state.

    Destination acceptance is structurally separate from Reflection: the actor
    must be an external destination that the proposal actually targets.
    """

    if not isinstance(proposal, LessonProposal):
        raise ValueError("Reflection transition requires a LessonProposal")
    if to_lifecycle not in _ALLOWED_LIFECYCLES:
        raise ValueError("Reflection lifecycle is not recognized")
    _require_non_empty(actor, "transition actor")
    _validate_time(occurred_at, "transition occurred_at")
    if occurred_at < proposal.created_at:
        raise ValueError("Reflection transition cannot precede proposal creation")

    allowed = _ALLOWED_TRANSITIONS[proposal.lifecycle]
    if to_lifecycle not in allowed:
        raise ValueError(
            f"Reflection cannot move a {proposal.lifecycle} proposal "
            f"to {to_lifecycle}"
        )

    if to_lifecycle == "accepted_by_destination":
        if actor.strip().casefold() in _FORBIDDEN_PROMOTION_ACTORS:
            raise ValueError("Reflection cannot promote its own lesson proposal")
        if destination is None:
            raise ValueError("Reflection acceptance requires an explicit destination")
        if destination not in proposal.proposed_destinations:
            raise ValueError("Reflection acceptance requires a proposed destination")

    if to_lifecycle == "expired" and occurred_at < proposal.expires_at:
        raise ValueError("Reflection proposal cannot expire before expires_at")

    if to_lifecycle == "superseded":
        _require_non_empty(supersedes_with_proposal_id, "supersedes_with_proposal_id")

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
        supersedes_proposal_id=proposal.supersedes_proposal_id,
    )
    return updated, event


def _observed_sort_key(reference: EpisodeReference) -> tuple[float, str]:
    return (reference.occurred_at, reference.reference_id)


def _escalated_privacy(
    references: tuple[EpisodeReference, ...],
) -> PrivacyClass:
    resolved = "public"
    for reference in references:
        if _PRIVACY_RANK[reference.privacy_class] > _PRIVACY_RANK[resolved]:
            resolved = reference.privacy_class
    return resolved  # type: ignore[return-value]


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
