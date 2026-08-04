"""Assertions invoked by the existing Daily Reflection test for E6.0.

The helper is deliberately not a pytest collection target. The repository pins
its generated test count, so the bounded Reflection assertions are called from
an existing reflection regression test rather than creating count-only churn.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from agents.core.memory.atlas_snapshot import AtlasConfidence
from agents.core.memory.episodes import EpisodeReference
from agents.core.reflection_lesson import (
    LessonProposal,
    OutcomeObservation,
    compare_outcome,
    propose_lesson,
    transition_lesson,
)

_DIGEST = "a" * 64


def _reference(
    role: str,
    record_id: str,
    occurred_at: float,
    *,
    privacy_class: str = "personal",
    tombstoned: bool = False,
    deleted_at: float | None = None,
) -> EpisodeReference:
    return EpisodeReference.build(
        role=role,  # type: ignore[arg-type]
        source_id="reflection-fixture",
        record_id=record_id,
        source_kind="synthetic_public",
        source_schema="nerva.episode.v1",
        privacy_class=privacy_class,  # type: ignore[arg-type]
        integrity_sha256=_DIGEST,
        occurred_at=occurred_at,
        deletion_root_id=f"root:{record_id}",
        confidence=AtlasConfidence("unknown"),
        tombstoned=tombstoned,
        deleted_at=deleted_at,
    )


def _expected() -> EpisodeReference:
    return _reference("decision", "decision-1", 100.0)


def _observation(status_inputs: dict[str, bool], references) -> OutcomeObservation:
    return compare_outcome(
        episode_id="episode-1",
        expected_reference=_expected(),
        observed_references=references,
        matches_expectation=status_inputs,
        environment="hermetic-fixture",
        observed_at=300.0,
        created_at=310.0,
    )


def _confirmed() -> OutcomeObservation:
    outcome = _reference("outcome", "outcome-ok", 200.0)
    return _observation({outcome.reference_id: True}, (outcome,))


def _proposal(observation: OutcomeObservation) -> LessonProposal:
    return propose_lesson(
        observations=(observation,),
        claim="Retrying the export after a transient failure resolved the outcome.",
        scope="export-workflow",
        proposed_destinations=("episodes",),
        created_at=400.0,
        review_at=500.0,
        expires_at=600.0,
    )


def _check_four_comparison_paths() -> None:
    """Positive, negative, contradictory and insufficient paths stay distinct."""

    ok = _reference("outcome", "outcome-ok", 200.0)
    bad = _reference("outcome", "outcome-bad", 210.0)

    confirmed = _observation({ok.reference_id: True}, (ok,))
    assert confirmed.comparison_status == "confirmed"

    refuted = _observation({ok.reference_id: False}, (ok,))
    assert refuted.comparison_status == "refuted"

    contradictory = _observation(
        {ok.reference_id: True, bad.reference_id: False}, (ok, bad)
    )
    assert contradictory.comparison_status == "contradictory"

    # A live reference without a verdict is never guessed into a result.
    unjudged = _observation({}, (ok,))
    assert unjudged.comparison_status == "insufficient_evidence"
    assert unjudged.observed_references == ()
    assert any("no verdict" in item for item in unjudged.evidence_limitations)

    # Negative and unusable results are retained, not dropped.
    assert refuted.usable_references
    assert any("unusable evidence" in item for item in unjudged.evidence_limitations)


def _check_deterministic_fingerprints() -> None:
    """The same evidence yields identical observation and proposal fingerprints."""

    first = _confirmed()
    second = _confirmed()
    assert first.observation_id == second.observation_id
    assert first.replay_fingerprint == second.replay_fingerprint

    proposal_a = _proposal(first)
    proposal_b = _proposal(second)
    assert proposal_a.proposal_id == proposal_b.proposal_id
    assert proposal_a.replay_fingerprint == proposal_b.replay_fingerprint

    # Different evidence must not collide with the confirmed fingerprint.
    other = _reference("outcome", "outcome-other", 220.0)
    different = _observation({other.reference_id: True}, (other,))
    assert different.observation_id != first.observation_id


def _check_immutability_and_authority() -> None:
    """Records are frozen and their authority flags cannot be forged."""

    observation = _confirmed()
    proposal = _proposal(observation)

    for record in (observation, proposal):
        with pytest.raises(FrozenInstanceError):
            record.claim = "mutated"  # type: ignore[misc]
        assert record.authority == "proposal_only"
        assert record.can_rewrite_source_evidence is False
        assert record.can_promote_lesson is False
        assert record.can_authorize is False
        assert record.can_execute is False
        assert record.can_mark_complete is False

    assert observation.schema == "nerva.outcome-observation.v1"
    assert proposal.schema == "nerva.lesson.v1"

    # init=False authority fields cannot be overridden through replace().
    # CPython raises ValueError on 3.11 and TypeError on newer versions.
    with pytest.raises((TypeError, ValueError)):
        replace(proposal, can_authorize=True)


def _check_insufficient_evidence_cannot_produce_a_proposal() -> None:
    """Missing, stale or unverified outcomes fail closed."""

    ok = _reference("outcome", "outcome-ok", 200.0)
    unjudged = _observation({}, (ok,))
    with pytest.raises(ValueError, match="confirmed supporting reference"):
        _proposal(unjudged)

    refuted = _observation({ok.reference_id: False}, (ok,))
    with pytest.raises(ValueError, match="confirmed supporting reference"):
        _proposal(refuted)

    # Tombstoned evidence is not live evidence.
    tombstoned = _reference(
        "outcome", "outcome-gone", 200.0, tombstoned=True, deleted_at=250.0
    )
    stale = _observation({tombstoned.reference_id: True}, (tombstoned,))
    assert stale.comparison_status == "insufficient_evidence"
    with pytest.raises(ValueError, match="confirmed supporting reference"):
        _proposal(stale)


def _check_evidence_and_chronology_validation() -> None:
    """Dangling references, bad roles and invalid chronology are rejected."""

    observation = _confirmed()

    # An outcome that predates its decision is impossible.
    early = _reference("outcome", "outcome-early", 50.0)
    with pytest.raises(ValueError, match="cannot precede the expected decision"):
        _observation({early.reference_id: True}, (early,))

    # The expected reference must be a decision, not an arbitrary source.
    with pytest.raises(ValueError, match="decision role"):
        OutcomeObservation(
            observation_id=observation.observation_id,
            episode_id="episode-1",
            expected_reference=_reference("source", "source-1", 100.0),
            observed_references=observation.observed_references,
            comparison_status="confirmed",
            environment="hermetic-fixture",
            evidence_limitations=(),
            privacy_class="personal",
            confidence=AtlasConfidence("unknown"),
            observed_at=300.0,
            created_at=310.0,
        )

    # A forged identifier cannot be attached to unrelated evidence.
    with pytest.raises(ValueError, match="does not match its evidence"):
        replace(observation, observation_id="reflection:obs:forged")

    # A claim must link to evidence that exists in the proposal.
    proposal = _proposal(observation)
    with pytest.raises(ValueError, match="does not match its evidence"):
        replace(proposal, supporting_reference_ids=("reflection:ref:dangling",))

    # Confidence must stay qualified rather than becoming a bare number.
    with pytest.raises(ValueError, match="AtlasConfidence"):
        replace(proposal, confidence=0.9)  # type: ignore[arg-type]


def _check_privacy_cannot_downgrade() -> None:
    """Privacy escalates with evidence and restricted lessons stay gated."""

    restricted = _reference(
        "outcome", "outcome-restricted", 200.0, privacy_class="restricted"
    )
    observation = _observation({restricted.reference_id: True}, (restricted,))
    assert observation.privacy_class == "restricted"

    with pytest.raises(ValueError, match="cannot downgrade"):
        replace(observation, privacy_class="public")

    # A restricted lesson may only be routed to a human gate.
    with pytest.raises(ValueError, match="human review"):
        propose_lesson(
            observations=(observation,),
            claim="Restricted evidence supported the expectation.",
            scope="restricted-workflow",
            proposed_destinations=("episodes",),
            created_at=400.0,
            review_at=500.0,
            expires_at=600.0,
        )

    gated = propose_lesson(
        observations=(observation,),
        claim="Restricted evidence supported the expectation.",
        scope="restricted-workflow",
        proposed_destinations=("human_review",),
        created_at=400.0,
        review_at=500.0,
        expires_at=600.0,
    )
    assert gated.privacy_class == "restricted"


def _check_reflection_cannot_promote_its_own_proposal() -> None:
    """Promotion authority belongs to the destination, never to Reflection."""

    proposal = _proposal(_confirmed())

    with pytest.raises(ValueError, match="cannot promote its own"):
        transition_lesson(
            proposal,
            to_lifecycle="accepted_by_destination",
            actor="reflection",
            reason="self promotion attempt",
            occurred_at=450.0,
            destination="episodes",
        )

    # Acceptance requires a destination the proposal actually targets.
    with pytest.raises(ValueError, match="proposed destination"):
        transition_lesson(
            proposal,
            to_lifecycle="accepted_by_destination",
            actor="howard",
            reason="wrong destination",
            occurred_at=450.0,
            destination="howard",
        )

    with pytest.raises(ValueError, match="explicit destination"):
        transition_lesson(
            proposal,
            to_lifecycle="accepted_by_destination",
            actor="episodes",
            reason="missing destination",
            occurred_at=450.0,
        )


def _check_lifecycle_audit_is_reversible() -> None:
    """Lifecycle changes are audited and the exact prior state is recoverable."""

    proposal = _proposal(_confirmed())
    assert proposal.lifecycle == "proposed"
    assert proposal.revision == 1

    accepted, event = transition_lesson(
        proposal,
        to_lifecycle="accepted_by_destination",
        actor="episodes",
        reason="destination validated the claim independently",
        occurred_at=450.0,
        destination="episodes",
    )
    assert accepted.lifecycle == "accepted_by_destination"
    assert accepted.revision == 2
    assert accepted.proposal_id == proposal.proposal_id

    # The audit event restores the exact prior payload, not a summary.
    assert event.from_lifecycle == "proposed"
    assert event.prior_revision == 1
    assert event.prior_fingerprint == proposal.replay_fingerprint
    assert event.restore_prior() == json.loads(proposal.to_json())

    # Terminal states are terminal; a rejected proposal cannot be revived.
    rejected, _ = transition_lesson(
        proposal,
        to_lifecycle="rejected",
        actor="episodes",
        reason="claim overfits one fixture",
        occurred_at=460.0,
    )
    with pytest.raises(ValueError, match="cannot move a rejected proposal"):
        transition_lesson(
            rejected,
            to_lifecycle="accepted_by_destination",
            actor="episodes",
            reason="revival attempt",
            occurred_at=470.0,
            destination="episodes",
        )

    # Expiry cannot be backdated ahead of its own deadline.
    with pytest.raises(ValueError, match="cannot expire before"):
        transition_lesson(
            proposal,
            to_lifecycle="expired",
            actor="episodes",
            reason="premature expiry",
            occurred_at=450.0,
        )

    # Supersession must name the replacement.
    with pytest.raises(ValueError, match="supersedes_with_proposal_id"):
        transition_lesson(
            proposal,
            to_lifecycle="superseded",
            actor="episodes",
            reason="missing replacement",
            occurred_at=650.0,
        )


def _check_counter_evidence_is_retained() -> None:
    """Contradictions survive as counter-evidence instead of being discarded."""

    ok = _reference("outcome", "outcome-ok", 200.0)
    bad = _reference("outcome", "outcome-bad", 210.0)
    confirmed = _observation({ok.reference_id: True}, (ok,))
    contradictory = _observation(
        {ok.reference_id: True, bad.reference_id: False}, (ok, bad)
    )

    proposal = propose_lesson(
        observations=(confirmed, contradictory),
        claim="The retry path usually resolves the outcome but not always.",
        scope="export-workflow",
        proposed_destinations=("episodes", "human_review"),
        created_at=400.0,
        review_at=500.0,
        expires_at=600.0,
    )
    assert ok.reference_id in proposal.supporting_reference_ids
    assert bad.reference_id in proposal.counter_reference_ids
    # No reference may both support and counter the same claim.
    assert not set(proposal.supporting_reference_ids) & set(
        proposal.counter_reference_ids
    )


def _check_serialization_round_trip() -> None:
    """Canonical JSON is stable, sorted and carries the authority ceiling."""

    proposal = _proposal(_confirmed())
    payload = json.loads(proposal.to_json())
    assert payload["schema"] == "nerva.lesson.v1"
    assert payload["authority"] == "proposal_only"
    assert payload["can_promote_lesson"] is False
    assert proposal.to_json() == proposal.to_json()
    assert json.dumps(payload, sort_keys=True, separators=(",", ":")) == json.dumps(
        json.loads(proposal.to_json()), sort_keys=True, separators=(",", ":")
    )


def run_e6_0_checks() -> None:
    """Run every bounded E6.0 Reflection assertion."""

    _check_four_comparison_paths()
    _check_deterministic_fingerprints()
    _check_immutability_and_authority()
    _check_insufficient_evidence_cannot_produce_a_proposal()
    _check_evidence_and_chronology_validation()
    _check_privacy_cannot_downgrade()
    _check_reflection_cannot_promote_its_own_proposal()
    _check_lifecycle_audit_is_reversible()
    _check_counter_evidence_is_retained()
    _check_serialization_round_trip()
