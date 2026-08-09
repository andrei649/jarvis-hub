"""Successor-local hostile regressions for the E6 authority ceiling.

Provenance: closed #854 (ADV-03). Reflection records and the lesson
evaluation report must serialize the proposal_only/evaluation_only ceiling
as constants, never their mutable can_* fields, so a tampered in-memory
instance (flags flipped via object.__setattr__ after construction) cannot
emit elevated authority.
"""

from __future__ import annotations

from agents.core.memory.atlas_snapshot import AtlasConfidence
from agents.core.memory.episodes import EpisodeReference
from agents.core.observability.benchmark import BenchmarkStore
from agents.core.reflection_evaluation import evaluate_lesson_plan
from agents.core.reflection_lesson import (
    LessonProposal,
    OutcomeObservation,
    compare_outcome,
    propose_lesson,
)
from tests._nerva_e6_1_checks import _case, _plan

_DIGEST = "a" * 64


def _reference(
    role: str,
    record_id: str,
    occurred_at: float,
    *,
    privacy_class: str = "personal",
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
    )


def _expected() -> EpisodeReference:
    return _reference("decision", "decision-1", 100.0)


def _confirmed() -> OutcomeObservation:
    outcome = _reference("outcome", "outcome-ok", 200.0)
    return compare_outcome(
        episode_id="episode-1",
        expected_reference=_expected(),
        observed_references=(outcome,),
        matches_expectation={outcome.reference_id: True},
        environment="hermetic-fixture",
        observed_at=300.0,
        created_at=310.0,
    )


def _proposal() -> LessonProposal:
    return propose_lesson(
        observations=(_confirmed(),),
        claim="Retrying the export after a transient failure resolved the outcome.",
        scope="export-workflow",
        proposed_destinations=("episodes",),
        created_at=400.0,
        review_at=500.0,
        expires_at=600.0,
    )


def test_e6_observation_ceiling_is_immutable() -> None:
    observation = _confirmed()
    object.__setattr__(observation, "can_authorize", True)
    object.__setattr__(observation, "can_execute", True)

    payload = observation.canonical_payload()
    assert payload["authority"] == "proposal_only"
    assert payload["can_authorize"] is False
    assert payload["can_execute"] is False
    assert payload["can_promote_lesson"] is False
    assert payload["can_rewrite_source_evidence"] is False
    assert payload["can_mark_complete"] is False


def test_e6_proposal_ceiling_is_immutable() -> None:
    proposal = _proposal()
    object.__setattr__(proposal, "can_authorize", True)
    object.__setattr__(proposal, "can_execute", True)

    payload = proposal.canonical_payload()
    assert payload["authority"] == "proposal_only"
    assert payload["can_authorize"] is False
    assert payload["can_execute"] is False
    assert payload["can_promote_lesson"] is False
    assert payload["can_rewrite_source_evidence"] is False
    assert payload["can_mark_complete"] is False


async def _evaluation_report(tmp_path):
    plan = _plan((_case("answerable"),))
    store = BenchmarkStore(tmp_path / "store")

    async def candidate(runner_input):
        return "answer-answerable"

    async def baseline(runner_input):
        return "I don't know"

    return await evaluate_lesson_plan(
        plan,
        store=store,
        candidate_runner=candidate,
        baseline_runner=baseline,
        now=lambda: "2026-08-05T22:00:00.000Z",
        run_id="run-e6-1-successor",
    )


def test_e61_evaluation_report_ceiling_is_immutable(tmp_path) -> None:
    import asyncio

    from agents.core.reflection_evaluation import LessonEvaluationReport

    report = asyncio.run(_evaluation_report(tmp_path))
    assert isinstance(report, LessonEvaluationReport)

    object.__setattr__(report, "can_execute", True)
    object.__setattr__(report, "can_authorize", True)
    object.__setattr__(report, "can_change_routing", True)

    payload = report.to_dict()
    assert payload["authority"] == "evaluation_only"
    assert payload["can_execute"] is False
    assert payload["can_authorize"] is False
    assert payload["can_change_routing"] is False
    assert payload["can_promote_lesson"] is False
    assert payload["can_write_memory"] is False
    assert payload["can_mark_complete"] is False

