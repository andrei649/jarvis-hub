"""E6.0 Reflection assertions and their direct-collection case manifest."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from agents.core.memory.atlas_snapshot import AtlasConfidence
from agents.core.memory.episodes import EpisodeReference
from agents.core.reflection_lesson import (
    _TRANSITION_GUARD,
    LessonAuditEvent,
    LessonProposal,
    OutcomeObservation,
    OutcomeVerdict,
    _sha256,
    compare_outcome,
    load_lesson_proposal,
    propose_lesson,
    transition_lesson,
    validate_proposal_evidence,
)
from tests.nerva_check_cases import case, run_cases

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


def _observation(verdicts: dict[str, bool], references) -> OutcomeObservation:
    return compare_outcome(
        episode_id="episode-1",
        expected_reference=_expected(),
        observed_references=references,
        matches_expectation=verdicts,
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
    assert unjudged.eligible_reference_ids == ()
    assert any("without a verdict" in item for item in unjudged.evidence_limitations)

    # Negative and unusable results are retained, not dropped.
    assert refuted.eligible_reference_ids == (ok.reference_id,)


def _check_ineligible_evidence_is_retained_with_its_classification() -> None:
    """Unjudged and tombstoned evidence keeps privacy, tombstone and verdict state."""

    restricted = _reference(
        "outcome", "outcome-restricted", 200.0, privacy_class="restricted"
    )
    unjudged = _observation({}, (restricted,))

    # The reference itself is retained, not replaced with an empty tuple.
    assert unjudged.observed_references == (restricted,)
    assert unjudged.comparison_status == "insufficient_evidence"

    # Its classification survives, so privacy cannot be laundered by exclusion.
    assert unjudged.privacy_class == "restricted"
    (verdict,) = unjudged.excluded_verdicts
    assert verdict.reference_id == restricted.reference_id
    assert verdict.eligible is False
    assert verdict.matched is None
    assert verdict.exclusion_reason == "no_verdict"
    assert verdict.privacy_class == "restricted"

    # Tombstoned evidence is retained too, with its own exclusion reason.
    gone = _reference(
        "outcome",
        "outcome-gone",
        200.0,
        privacy_class="private_local",
        tombstoned=True,
        deleted_at=250.0,
    )
    stale = _observation({gone.reference_id: True}, (gone,))
    assert stale.observed_references == (gone,)
    assert stale.comparison_status == "insufficient_evidence"
    assert stale.privacy_class == "private_local"
    (stale_verdict,) = stale.excluded_verdicts
    assert stale_verdict.exclusion_reason == "tombstoned"
    assert stale_verdict.tombstoned is True

    # A tombstoned expected decision is not a valid comparison basis.
    dead_decision = _reference(
        "decision", "decision-gone", 100.0, tombstoned=True, deleted_at=150.0
    )
    with pytest.raises(ValueError, match="tombstoned decision"):
        compare_outcome(
            episode_id="episode-1",
            expected_reference=dead_decision,
            observed_references=(_reference("outcome", "outcome-ok", 200.0),),
            matches_expectation={},
            environment="hermetic-fixture",
            observed_at=300.0,
            created_at=310.0,
        )

    # A verdict cannot misreport its reference's classification or tombstone.
    with pytest.raises(ValueError, match="privacy class must match"):
        replace(
            unjudged,
            verdicts=(
                OutcomeVerdict(
                    reference_id=restricted.reference_id,
                    eligible=False,
                    matched=None,
                    exclusion_reason="no_verdict",
                    privacy_class="public",
                    tombstoned=False,
                ),
            ),
        )

    # Tombstoned evidence can never be marked eligible.
    with pytest.raises(ValueError, match="tombstoned evidence cannot be eligible"):
        OutcomeVerdict(
            reference_id=gone.reference_id,
            eligible=True,
            matched=True,
            exclusion_reason=None,
            privacy_class="private_local",
            tombstoned=True,
        )

    # The exclusion reason must agree with the tombstone state in BOTH
    # directions, so a live unresolved reference cannot be relabelled deleted.
    with pytest.raises(ValueError, match="reason must match the tombstone state"):
        OutcomeVerdict(
            reference_id="episode:ref:live0000000000000000",
            eligible=False,
            matched=None,
            exclusion_reason="tombstoned",
            privacy_class="personal",
            tombstoned=False,
        )
    with pytest.raises(ValueError, match="reason must match the tombstone state"):
        OutcomeVerdict(
            reference_id="episode:ref:dead0000000000000000",
            eligible=False,
            matched=None,
            exclusion_reason="no_verdict",
            privacy_class="personal",
            tombstoned=True,
        )


def _check_partial_evidence_fails_closed() -> None:
    """One unresolved reference makes the whole comparison insufficient."""

    ok = _reference("outcome", "outcome-ok", 200.0)
    unresolved = _reference("outcome", "outcome-unresolved", 210.0)
    deleted = _reference(
        "outcome", "outcome-deleted", 220.0, tombstoned=True, deleted_at=250.0
    )

    # A confirmed reference alongside a live unjudged one is NOT a confirmation.
    mixed = _observation({ok.reference_id: True}, (ok, unresolved))
    assert mixed.comparison_status == "insufficient_evidence"
    assert {verdict.reference_id for verdict in mixed.excluded_verdicts} == {
        unresolved.reference_id
    }

    # The same holds when the unusable reference is deleted rather than unjudged.
    with_deleted = _observation({ok.reference_id: True}, (ok, deleted))
    assert with_deleted.comparison_status == "insufficient_evidence"

    # Mixed refutation is equally inconclusive.
    mixed_refuted = _observation({ok.reference_id: False}, (ok, unresolved))
    assert mixed_refuted.comparison_status == "insufficient_evidence"

    # Partial evidence can never feed a proposal.
    with pytest.raises(ValueError, match="confirmed supporting reference"):
        _proposal(mixed)

    # A verdict cannot be reported alongside unresolved evidence by construction.
    confirmed = _observation({ok.reference_id: True}, (ok,))
    with pytest.raises(ValueError, match="alongside unresolved evidence"):
        replace(
            mixed,
            comparison_status="confirmed",
            observation_id=confirmed.observation_id,
        )


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

    # Eligibility is bound into the observation identity.
    ok = _reference("outcome", "outcome-ok", 200.0)
    assert _observation({ok.reference_id: False}, (ok,)).observation_id != (
        first.observation_id
    )


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

    # Tombstoned evidence is not eligible evidence.
    tombstoned = _reference(
        "outcome", "outcome-gone", 200.0, tombstoned=True, deleted_at=250.0
    )
    stale = _observation({tombstoned.reference_id: True}, (tombstoned,))
    with pytest.raises(ValueError, match="confirmed supporting reference"):
        _proposal(stale)


def _check_evidence_and_chronology_validation() -> None:
    """Bad roles, invalid chronology and inconsistent statuses are rejected."""

    observation = _confirmed()

    # An outcome that predates its decision is impossible.
    early = _reference("outcome", "outcome-early", 50.0)
    with pytest.raises(ValueError, match="cannot precede the expected decision"):
        _observation({early.reference_id: True}, (early,))

    # The expected reference must be a decision, not an arbitrary source.
    with pytest.raises(ValueError, match="decision role"):
        replace(observation, expected_reference=_reference("source", "source-1", 100.0))

    # A forged identifier cannot be attached to unrelated evidence.
    with pytest.raises(ValueError, match="does not match its evidence"):
        replace(observation, observation_id="reflection:obs:forged")

    # A status must agree with the verdicts it claims to summarize.
    with pytest.raises(ValueError, match="refuted status requires"):
        replace(observation, comparison_status="refuted")

    # Confidence must stay qualified rather than becoming a bare number.
    proposal = _proposal(observation)
    with pytest.raises(ValueError, match="AtlasConfidence"):
        replace(proposal, confidence=0.9)  # type: ignore[arg-type]


def _check_forged_evidence_graph_is_rejected() -> None:
    """A recomputed proposal ID does not make invented references canonical."""

    observation = _confirmed()
    proposal = _proposal(observation)
    validate_proposal_evidence(proposal, (observation,))

    # Forge a proposal over invented evidence and recompute its ID correctly,
    # so only the observation-graph boundary can catch it.
    invented_supporting = ("episode:ref:invented000000000000000",)
    invented_observations = ("reflection:obs:invented00000000000",)

    def _forge(observation_ids, supporting_ids, counter_ids=()) -> LessonProposal:
        forged_id = "reflection:lesson:" + _sha256(
            {
                "claim": proposal.claim,
                "scope": proposal.scope,
                "observation_ids": list(observation_ids),
                "supporting_reference_ids": list(supporting_ids),
                "counter_reference_ids": list(counter_ids),
                "created_at": float(proposal.created_at),
            }
        )[:24]
        return LessonProposal(
            proposal_id=forged_id,
            claim=proposal.claim,
            scope=proposal.scope,
            observation_ids=observation_ids,
            supporting_reference_ids=supporting_ids,
            counter_reference_ids=counter_ids,
            confidence=AtlasConfidence("unknown"),
            applicability=(),
            proposed_destinations=("episodes",),
            contradicts_proposal_ids=(),
            privacy_class="personal",
            lifecycle="proposed",
            revision=1,
            created_at=proposal.created_at,
            review_at=proposal.review_at,
            expires_at=proposal.expires_at,
        )

    # The record constructs with a valid self-consistent ID, but it is not
    # canonical against the real observation graph.
    forged_proposal = _forge(invented_observations, invented_supporting)
    assert forged_proposal.proposal_id == forged_proposal.expected_proposal_id
    with pytest.raises(ValueError, match="claims unknown observations"):
        validate_proposal_evidence(forged_proposal, (observation,))
    transition_result = None
    with pytest.raises(ValueError, match="claims unknown observations"):
        transition_result = transition_lesson(
            forged_proposal,
            observations=(observation,),
            to_lifecycle="accepted_by_destination",
            actor="episodes",
            reason="forged evidence cannot reach the acceptance sink",
            occurred_at=450.0,
            destination="episodes",
        )
    assert transition_result is None

    # Claiming the real observations but inflating supporting evidence fails too.
    inflated = _forge(
        proposal.observation_ids,
        tuple(sorted((*proposal.supporting_reference_ids, *invented_supporting))),
    )
    with pytest.raises(ValueError, match="claims unsupported evidence"):
        validate_proposal_evidence(inflated, (observation,))

    # The deserialization boundary refuses a payload whose graph is invented.
    payload = json.loads(forged_proposal.to_json())
    with pytest.raises(ValueError, match="claims unknown observations"):
        load_lesson_proposal(payload, (observation,))

    # A well-formed payload round-trips only when its graph validates.
    restored = load_lesson_proposal(json.loads(proposal.to_json()), (observation,))
    assert restored.replay_fingerprint == proposal.replay_fingerprint

    # The loader rejects forged authority and contradictory state rather than
    # discarding those fields and rebuilding a safe-looking record.
    for changes, expected in (
        ({"can_authorize": True}, "not a canonical proposed record"),
        ({"can_promote_lesson": True}, "not a canonical proposed record"),
        ({"authority": "privileged_action"}, "not a canonical proposed record"),
        ({"accepted_by": "episodes", "accepted_at": 401.0}, "cannot carry accepted_by"),
        ({"prior_fingerprint": "b" * 64}, "cannot carry prior_fingerprint"),
        (
            {"superseded_by_proposal_id": "reflection:lesson:other"},
            "cannot carry superseded_by_proposal_id",
        ),
        ({"unexpected_key": "smuggled"}, "not a canonical proposed record"),
        ({"guard": "smuggled"}, "not a canonical proposed record"),
    ):
        tampered = dict(json.loads(proposal.to_json()))
        tampered.update(changes)
        with pytest.raises(ValueError, match=expected):
            load_lesson_proposal(tampered, (observation,))

    # A missing field is rejected too, rather than defaulted.
    truncated = dict(json.loads(proposal.to_json()))
    del truncated["review_at"]
    with pytest.raises(ValueError):
        load_lesson_proposal(truncated, (observation,))

    # Advanced lifecycles are never rebuilt from a payload.
    accepted, _ = transition_lesson(
        proposal,
        observations=(observation,),
        to_lifecycle="accepted_by_destination",
        actor="episodes",
        reason="destination validated the claim independently",
        occurred_at=450.0,
        destination="episodes",
    )
    with pytest.raises(ValueError, match="only accepts the proposed lifecycle"):
        load_lesson_proposal(json.loads(accepted.to_json()), (observation,))


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


def _check_acceptance_requires_a_destination_owned_transition() -> None:
    """Accepted state is absent by default and unreachable by construction."""

    observation = _confirmed()
    proposal = _proposal(observation)
    assert proposal.lifecycle == "proposed"
    assert proposal.accepted_by is None
    assert proposal.accepted_at is None

    # Direct construction of an accepted proposal is noncanonical.
    with pytest.raises(ValueError, match="requires an audited transition"):
        LessonProposal(
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
            lifecycle="accepted_by_destination",
            revision=2,
            created_at=proposal.created_at,
            review_at=proposal.review_at,
            expires_at=proposal.expires_at,
            accepted_by="episodes",
            accepted_at=450.0,
            prior_fingerprint=proposal.replay_fingerprint,
        )

    # The same applies to every other advanced lifecycle.
    for lifecycle in ("rejected", "expired", "superseded"):
        with pytest.raises(ValueError, match="requires an audited transition"):
            replace(proposal, lifecycle=lifecycle, revision=2)

    # Reflection may not promote its own proposal.
    with pytest.raises(ValueError, match="cannot promote its own"):
        transition_lesson(
            proposal,
            observations=(observation,),
            to_lifecycle="accepted_by_destination",
            actor="reflection",
            reason="self promotion attempt",
            occurred_at=450.0,
            destination="episodes",
        )

    # The acting identity must be the destination that owns the promotion.
    with pytest.raises(ValueError, match="actor must be the destination"):
        transition_lesson(
            proposal,
            observations=(observation,),
            to_lifecycle="accepted_by_destination",
            actor="howard",
            reason="actor and destination disagree",
            occurred_at=450.0,
            destination="episodes",
        )

    # Acceptance requires a destination the proposal actually targets.
    with pytest.raises(ValueError, match="proposed destination"):
        transition_lesson(
            proposal,
            observations=(observation,),
            to_lifecycle="accepted_by_destination",
            actor="howard",
            reason="wrong destination",
            occurred_at=450.0,
            destination="howard",
        )

    with pytest.raises(ValueError, match="explicit destination"):
        transition_lesson(
            proposal,
            observations=(observation,),
            to_lifecycle="accepted_by_destination",
            actor="episodes",
            reason="missing destination",
            occurred_at=450.0,
        )


def _check_lifecycle_audit_is_reversible_and_bound() -> None:
    """Transitions are audited, replacement-bound and exactly recoverable."""

    observation = _confirmed()
    proposal = _proposal(observation)

    accepted, event = transition_lesson(
        proposal,
        observations=(observation,),
        to_lifecycle="accepted_by_destination",
        actor="episodes",
        reason="destination validated the claim independently",
        occurred_at=450.0,
        destination="episodes",
    )
    assert accepted.lifecycle == "accepted_by_destination"
    assert accepted.revision == 2
    assert accepted.accepted_by == "episodes"
    assert accepted.accepted_at == 450.0
    assert accepted.prior_fingerprint == proposal.replay_fingerprint

    # The audit event restores the exact prior payload, not a summary.
    assert event.from_lifecycle == "proposed"
    assert event.destination == "episodes"
    assert event.prior_revision == 1
    assert event.prior_fingerprint == proposal.replay_fingerprint
    assert event.restore_prior() == json.loads(proposal.to_json())

    # Supersession must name and retain the replacement on both records.
    superseded, supersede_event = transition_lesson(
        accepted,
        observations=(observation,),
        to_lifecycle="superseded",
        actor="episodes",
        reason="a broader lesson replaced this one",
        occurred_at=700.0,
        supersedes_with_proposal_id="reflection:lesson:replacement00000000",
    )
    assert superseded.superseded_by_proposal_id == (
        "reflection:lesson:replacement00000000"
    )
    assert supersede_event.replacement_proposal_id == (
        "reflection:lesson:replacement00000000"
    )

    # Both supported expiry edges remain valid once the deadline is reached.
    expired_at_deadline, expiry_event = transition_lesson(
        proposal,
        observations=(observation,),
        to_lifecycle="expired",
        actor="episodes",
        reason="proposal reached its review expiry",
        occurred_at=proposal.expires_at,
    )
    assert expired_at_deadline.lifecycle == "expired"
    assert expiry_event.from_lifecycle == "proposed"
    assert expiry_event.to_lifecycle == "expired"

    accepted_expired, accepted_expiry_event = transition_lesson(
        accepted,
        observations=(observation,),
        to_lifecycle="expired",
        actor="episodes",
        reason="accepted lesson reached its expiry",
        occurred_at=accepted.expires_at + 1.0,
    )
    assert accepted_expired.lifecycle == "expired"
    assert accepted_expiry_event.from_lifecycle == "accepted_by_destination"
    assert accepted_expiry_event.to_lifecycle == "expired"

    with pytest.raises(ValueError, match="supersedes_with_proposal_id"):
        transition_lesson(
            accepted,
            observations=(observation,),
            to_lifecycle="superseded",
            actor="episodes",
            reason="missing replacement",
            occurred_at=700.0,
        )

    # Terminal states are terminal; a rejected proposal cannot be revived.
    rejected, _ = transition_lesson(
        proposal,
        observations=(observation,),
        to_lifecycle="rejected",
        actor="episodes",
        reason="claim overfits one fixture",
        occurred_at=460.0,
    )
    with pytest.raises(ValueError, match="cannot move a rejected proposal"):
        transition_lesson(
            rejected,
            observations=(observation,),
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
            observations=(observation,),
            to_lifecycle="expired",
            actor="episodes",
            reason="premature expiry",
            occurred_at=450.0,
        )


def _check_audit_events_cannot_self_assert_history() -> None:
    """A retained prior payload must be canonical and self-consistent."""

    observation = _confirmed()
    proposal = _proposal(observation)
    _, event = transition_lesson(
        proposal,
        observations=(observation,),
        to_lifecycle="rejected",
        actor="episodes",
        reason="claim overfits one fixture",
        occurred_at=460.0,
    )
    prior = event.prior_payload_json

    def _rebuild(**overrides):
        fields = {
            "proposal_id": event.proposal_id,
            "from_lifecycle": event.from_lifecycle,
            "to_lifecycle": event.to_lifecycle,
            "actor": event.actor,
            "reason": event.reason,
            "occurred_at": event.occurred_at,
            "prior_revision": event.prior_revision,
            "prior_fingerprint": event.prior_fingerprint,
            "prior_payload_json": prior,
        }
        fields.update(overrides)
        return LessonAuditEvent(**fields)

    # A non-canonical re-serialization is rejected before anything else.
    with pytest.raises(ValueError, match="is not canonical JSON"):
        _rebuild(prior_payload_json=json.dumps(json.loads(prior)))

    fabricated = dict(json.loads(prior))
    fabricated["proposal_id"] = "reflection:lesson:someone-else"
    fabricated_json = json.dumps(
        fabricated, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    # Canonical but altered history cannot ride on the original fingerprint.
    with pytest.raises(ValueError, match="does not match its hash"):
        _rebuild(prior_payload_json=fabricated_json)

    # Recomputing the fingerprint still cannot claim another proposal's history.
    with pytest.raises(ValueError, match="names another proposal"):
        _rebuild(
            prior_payload_json=fabricated_json,
            prior_fingerprint=_sha256(fabricated_json),
        )

    # A payload contradicting the recorded lifecycle or revision is rejected.
    with pytest.raises(ValueError, match="contradicts from_lifecycle"):
        _rebuild(from_lifecycle="expired")
    with pytest.raises(ValueError, match="contradicts prior_revision"):
        _rebuild(prior_revision=7)

    # Altering any OTHER prior field and recomputing the hash is still rejected,
    # even though proposal_id, lifecycle, revision and schema stay untouched.
    def _tamper(**changes) -> tuple[str, str]:
        tampered = dict(json.loads(prior))
        tampered.update(changes)
        tampered_json = json.dumps(
            tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return tampered_json, _sha256(tampered_json)

    # Forged authority flag.
    payload_json, digest = _tamper(can_authorize=True)
    with pytest.raises(ValueError, match="not a canonical lesson revision"):
        _rebuild(prior_payload_json=payload_json, prior_fingerprint=digest)

    # Forged acceptance evidence on a proposed-state revision.
    payload_json, digest = _tamper(accepted_by="episodes", accepted_at=401.0)
    with pytest.raises(ValueError, match="not a valid lesson revision"):
        _rebuild(prior_payload_json=payload_json, prior_fingerprint=digest)

    # Rewritten claim, which no longer derives the recorded proposal_id.
    payload_json, digest = _tamper(claim="A different lesson was learned.")
    with pytest.raises(ValueError, match="not a valid lesson revision"):
        _rebuild(prior_payload_json=payload_json, prior_fingerprint=digest)

    # Rewritten evidence graph.
    payload_json, digest = _tamper(
        supporting_reference_ids=["episode:ref:invented000000000000000"]
    )
    with pytest.raises(ValueError, match="not a valid lesson revision"):
        _rebuild(prior_payload_json=payload_json, prior_fingerprint=digest)

    # The recorded transition itself must be possible and correctly attributed.
    rejected, _ = transition_lesson(
        proposal,
        observations=(observation,),
        to_lifecycle="rejected",
        actor="episodes",
        reason="claim overfits one fixture",
        occurred_at=460.0,
    )
    with pytest.raises(ValueError, match="impossible transition"):
        LessonAuditEvent(
            proposal_id=rejected.proposal_id,
            from_lifecycle="rejected",
            to_lifecycle="expired",
            actor="episodes",
            reason="reviving a terminal state",
            occurred_at=700.0,
            prior_revision=rejected.revision,
            prior_fingerprint=rejected.replay_fingerprint,
            prior_payload_json=rejected.to_json(),
        )
    with pytest.raises(ValueError, match="cannot record a self-promotion"):
        _rebuild(
            to_lifecycle="accepted_by_destination",
            actor="reflection",
            destination="episodes",
        )
    with pytest.raises(ValueError, match="actor must be the destination"):
        _rebuild(
            to_lifecycle="accepted_by_destination",
            actor="howard",
            destination="episodes",
        )
    with pytest.raises(ValueError, match="destination was never proposed"):
        _rebuild(
            to_lifecycle="accepted_by_destination",
            actor="howard",
            destination="howard",
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
    validate_proposal_evidence(proposal, (confirmed, contradictory))


def _check_serialization_round_trip() -> None:
    """Canonical JSON is stable, sorted and never leaks the construction guard."""

    observation = _confirmed()
    proposal = _proposal(observation)
    payload = json.loads(proposal.to_json())
    assert payload["schema"] == "nerva.lesson.v1"
    assert payload["authority"] == "proposal_only"
    assert payload["can_promote_lesson"] is False
    assert "guard" not in payload
    assert proposal.to_json() == proposal.to_json()

    accepted, _ = transition_lesson(
        proposal,
        observations=(observation,),
        to_lifecycle="accepted_by_destination",
        actor="episodes",
        reason="destination validated the claim independently",
        occurred_at=450.0,
        destination="episodes",
    )
    assert "guard" not in json.loads(accepted.to_json())
    # The guard is a construction capability, never retained state.
    assert accepted.guard is None
    assert _TRANSITION_GUARD is not None


NERVA_E6_0_CASES = (
    case("e6.0", _check_four_comparison_paths),
    case("e6.0", _check_ineligible_evidence_is_retained_with_its_classification),
    case("e6.0", _check_partial_evidence_fails_closed),
    case("e6.0", _check_deterministic_fingerprints),
    case("e6.0", _check_immutability_and_authority),
    case("e6.0", _check_insufficient_evidence_cannot_produce_a_proposal),
    case("e6.0", _check_evidence_and_chronology_validation),
    case("e6.0", _check_forged_evidence_graph_is_rejected),
    case("e6.0", _check_privacy_cannot_downgrade),
    case("e6.0", _check_acceptance_requires_a_destination_owned_transition),
    case("e6.0", _check_lifecycle_audit_is_reversible_and_bound),
    case("e6.0", _check_audit_events_cannot_self_assert_history),
    case("e6.0", _check_counter_evidence_is_retained),
    case("e6.0", _check_serialization_round_trip),
)


def run_e6_0_checks() -> None:
    """Compatibility entrypoint; direct pytest collection uses the same manifest."""
    run_cases(NERVA_E6_0_CASES)
