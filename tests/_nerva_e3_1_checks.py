"""Directly collected privacy and determinism checks for Nerva Episodes E3.1."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from agents.core.memory.atlas_snapshot import AtlasConfidence
from agents.core.memory.episode_compare import (
    EpisodeComparisonCase,
    compare_episode_retrieval,
)
from agents.core.memory.episodes import (
    EpisodeAssertion,
    EpisodeQuery,
    EpisodeRecord,
    EpisodeReference,
    correct_episode,
    open_episode,
    settle_episode,
    tombstone_sources,
)


def _reference(
    record_id: str,
    occurred_at: float,
    *,
    role: str = "source",
    privacy_class: str = "public",
) -> EpisodeReference:
    return EpisodeReference.build(
        role=role,
        source_id="tests.e3.1",
        record_id=record_id,
        source_kind="event" if role == "source" else "verified_outcome",
        source_schema="tests.e3.1.v1",
        privacy_class=privacy_class,
        integrity_sha256=("a" if role == "source" else "b") * 64,
        occurred_at=occurred_at,
        deletion_root_id=record_id,
        confidence=(
            AtlasConfidence("unknown")
            if role == "source"
            else AtlasConfidence("measured", 1.0, "tests.e3.1")
        ),
    )


def _direct(text: str, *reference_ids: str) -> EpisodeAssertion:
    return EpisodeAssertion.build(
        kind="direct",
        text=text,
        evidence_reference_ids=tuple(reference_ids),
        confidence=AtlasConfidence("unknown"),
    )


def _settled(
    *,
    source: EpisodeReference,
    summary_text: str,
    started_at: float,
    outcome: EpisodeReference | None = None,
) -> EpisodeRecord:
    opened = open_episode(
        participants=("project:fixture",),
        started_at=started_at,
        references=(source,),
        actor_id="fixture:e3.1",
        occurred_at=started_at + 2,
        reason="open comparison fixture",
    ).after[0]
    references = () if outcome is None else (outcome,)
    evidence = (source.reference_id,)
    if outcome is not None:
        evidence += (outcome.reference_id,)
    return settle_episode(
        opened,
        ended_at=started_at + 3,
        actor_id="fixture:e3.1",
        occurred_at=started_at + 4,
        reason="settle comparison fixture",
        additional_references=references,
        summary=_direct(summary_text, *evidence),
    ).after[0]


def _longitudinal_cases() -> tuple[EpisodeComparisonCase, ...]:
    harbor_source = _reference("event:harbor", 100)
    harbor_outcome = _reference(
        "outcome:harbor-green",
        101,
        role="outcome",
    )
    harbor = _settled(
        source=harbor_source,
        outcome=harbor_outcome,
        summary_text="The verified result for Project Harbor is green.",
        started_at=100,
    )

    juniper_source = _reference(
        "event:juniper",
        200,
        privacy_class="private_local",
    )
    juniper = _settled(
        source=juniper_source,
        summary_text=(
            "Project Juniper selected a solar sensor and it passed calibration."
        ),
        started_at=200,
    )

    correction_source = _reference("event:correction", 300)
    obsolete = _settled(
        source=correction_source,
        summary_text="obsolete-active-plan assigned port alpha.",
        started_at=300,
    )
    corrected = correct_episode(
        obsolete,
        actor_id="fixture:e3.1",
        occurred_at=350,
        reason="replace obsolete plan",
        summary=_direct(
            "Current active plan assigns port beta.",
            correction_source.reference_id,
        ),
    ).after[0]

    retirement_source = _reference("event:retirement", 400)
    retired_outcome = _reference(
        "outcome:retired-token",
        401,
        role="outcome",
    )
    retained = _settled(
        source=retirement_source,
        outcome=retired_outcome,
        summary_text="retired-outcome-token was verified for Project Cedar.",
        started_at=400,
    )
    tombstoned = tombstone_sources(
        retained,
        deletion_root_ids=(retired_outcome.deletion_root_id,),
        deleted_at=450,
        actor_id="fixture:e3.1",
        occurred_at=450,
        reason="remove retired outcome evidence",
    ).after[0]

    return (
        EpisodeComparisonCase(
            case_id="corrected-obsolete",
            ability="update",
            privacy_class="synthetic_public",
            facts=(
                "obsolete-active-plan assigned port alpha.",
                "Correction: obsolete-active-plan is retired; port beta is current.",
            ),
            question="What did obsolete-active-plan assign?",
            expected=(),
            abstain=True,
            records=(obsolete, corrected),
            query=EpisodeQuery(
                situation_terms=("obsolete-active-plan",),
                limit=5,
            ),
        ),
        EpisodeComparisonCase(
            case_id="multi-session-juniper",
            ability="multi_session",
            privacy_class="redacted_local",
            facts=(
                "Session one: Project Juniper selected a solar sensor.",
                "Session two: The solar sensor passed calibration.",
            ),
            question="What sensor did Project Juniper select?",
            expected=("solar sensor",),
            abstain=False,
            records=(juniper,),
            query=EpisodeQuery(
                situation_terms=("solar sensor",),
                limit=5,
            ),
        ),
        EpisodeComparisonCase(
            case_id="stable-harbor-outcome",
            ability="extraction",
            privacy_class="synthetic_public",
            facts=("The verified result for Project Harbor is green.",),
            question="What is the verified result for Project Harbor?",
            expected=("green",),
            abstain=False,
            records=(harbor,),
            query=EpisodeQuery(
                outcome_record_ids=("outcome:harbor-green",),
                limit=5,
            ),
        ),
        EpisodeComparisonCase(
            case_id="tombstoned-retired-outcome",
            ability="update",
            privacy_class="synthetic_public",
            facts=(
                "retired-outcome-token was verified for Project Cedar.",
                "The retired-outcome-token evidence was later deleted.",
            ),
            question="What was verified by retired-outcome-token?",
            expected=(),
            abstain=True,
            records=(retained, tombstoned),
            query=EpisodeQuery(
                outcome_record_ids=("outcome:retired-token",),
                limit=5,
            ),
        ),
    )


async def _run_e3_1_checks() -> None:
    cases = _longitudinal_cases()
    report = await compare_episode_retrieval(
        cases=cases,
        comparison_id="e3.1-real-path",
    )

    assert report.schema == "nerva.episode.comparison.v1"
    assert report.evidence_scope == "privacy_safe_fixture_only"
    assert report.authority == "evaluation_only"
    assert report.can_authorize is False
    assert report.can_execute is False
    assert report.can_mark_complete is False
    assert report.retrieval_budget == 5
    assert report.baseline_accuracy.source == "memory.eval.run_recall_eval"
    assert report.episode_accuracy.value == 1.0
    assert report.baseline_accuracy.value < report.episode_accuracy.value
    assert report.episode_win_count >= 2
    assert report.episode_loss_count == 0
    assert report.baseline_failure_count == 0
    assert report.episode_failure_count == 0
    assert report.no_regression is True
    assert report.latency.status == "not_measured"
    assert report.real_outcome_quality.status == "not_measured"
    assert all(
        result.baseline_retrieved_count <= report.retrieval_budget
        and result.episode_match_count <= report.retrieval_budget
        for result in report.cases
    )

    serialized = report.to_json()
    for private_text in (
        "Project Harbor",
        "Project Juniper",
        "obsolete-active-plan",
        "retired-outcome-token",
        "solar sensor",
        "port alpha",
        "port beta",
    ):
        assert private_text not in serialized

    async def perfect_baseline(corpus, *, top_k):
        assert top_k == 5
        return {
            "results": [
                {
                    "id": case.id,
                    "passed": True,
                    "retrieved": list(case.facts)[:top_k],
                }
                for case in corpus
            ]
        }

    forward = await compare_episode_retrieval(
        cases=cases,
        comparison_id="e3.1-replay",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    reversed_report = await compare_episode_retrieval(
        cases=tuple(reversed(cases)),
        comparison_id="e3.1-replay",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    assert forward.baseline_accuracy.source == "tests.perfect_baseline"
    assert forward.to_json() == reversed_report.to_json()
    assert forward.replay_fingerprint == reversed_report.replay_fingerprint

    harbor = next(
        case for case in cases if case.case_id == "stable-harbor-outcome"
    )
    question_aligned = replace(
        harbor,
        query=EpisodeQuery(situation_terms=("project harbor",), limit=5),
    )
    oracle_diagnostic = replace(
        harbor,
        query=EpisodeQuery(
            outcome_record_ids=("outcome:harbor-green",),
            limit=5,
        ),
    )
    aligned_report = await compare_episode_retrieval(
        cases=(question_aligned,),
        comparison_id="e3.1-query-invariance",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    oracle_report = await compare_episode_retrieval(
        cases=(oracle_diagnostic,),
        comparison_id="e3.1-query-invariance",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    assert aligned_report.to_json() == oracle_report.to_json()
    assert (
        oracle_report.episode_accuracy.source
        == "episodes.retrieve_episodes.question_derived"
    )

    juniper = next(
        case for case in cases if case.case_id == "multi-session-juniper"
    )
    juniper_aligned = replace(
        juniper,
        query=EpisodeQuery(situation_terms=("project juniper",), limit=5),
    )
    answer_bearing = replace(
        juniper,
        query=EpisodeQuery(situation_terms=("solar sensor",), limit=5),
    )
    aligned_juniper_report = await compare_episode_retrieval(
        cases=(juniper_aligned,),
        comparison_id="e3.1-answer-query-invariance",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    answer_bearing_report = await compare_episode_retrieval(
        cases=(answer_bearing,),
        comparison_id="e3.1-answer-query-invariance",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    assert aligned_juniper_report.to_json() == answer_bearing_report.to_json()

    oracle_only = replace(
        harbor,
        question="What happened?",
        query=EpisodeQuery(
            outcome_record_ids=("outcome:harbor-green",),
            limit=5,
        ),
    )
    fail_closed = await compare_episode_retrieval(
        cases=(oracle_only,),
        comparison_id="e3.1-oracle-fail-closed",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    assert fail_closed.baseline_accuracy.value == 1.0
    assert fail_closed.episode_accuracy.value == 0.0
    assert fail_closed.cases[0].episode_match_count == 0
    assert fail_closed.episode_win_count == 0
    assert fail_closed.episode_loss_count == 1
    assert fail_closed.no_regression is False

    with pytest.raises(ValueError, match="runner identity"):
        await compare_episode_retrieval(
            cases=(cases[0],),
            comparison_id="e3.1-forged-provenance",
            baseline_runner=perfect_baseline,
        )
    with pytest.raises(ValueError, match="runner identity"):
        await compare_episode_retrieval(
            cases=(cases[0],),
            comparison_id="e3.1-mislabeled-real-runner",
            baseline_source="tests.not-the-real-runner",
        )

    with pytest.raises(ValueError, match="synthetic_public"):
        replace(cases[1], privacy_class="synthetic_public")

    mismatched_budget = replace(
        cases[0],
        query=replace(cases[0].query, limit=6),
    )
    with pytest.raises(ValueError, match="shared retrieval budget"):
        await compare_episode_retrieval(
            cases=(mismatched_budget,),
            comparison_id="e3.1-budget-mismatch",
            baseline_runner=perfect_baseline,
            baseline_source="tests.perfect_baseline",
        )

    async def failed_baseline(_corpus, *, top_k):
        assert top_k == 5
        raise RuntimeError("secret fixture payload must not enter the report")

    failure_report = await compare_episode_retrieval(
        cases=(cases[0],),
        comparison_id="e3.1-failure",
        baseline_runner=failed_baseline,
        baseline_source="tests.failed_baseline",
    )
    assert failure_report.baseline_failure_count == 1
    assert failure_report.cases[0].baseline_failure_type == "RuntimeError"
    assert failure_report.no_regression is False
    assert "secret fixture payload" not in failure_report.to_json()

    async def oversized_baseline(corpus, *, top_k):
        return {
            "top_k": top_k,
            "results": [
                {
                    "id": case.id,
                    "passed": True,
                    "retrieved": ["x"] * (top_k + 1),
                }
                for case in corpus
            ],
        }

    oversized_report = await compare_episode_retrieval(
        cases=(cases[0],),
        comparison_id="e3.1-baseline-over-budget",
        baseline_runner=oversized_baseline,
        baseline_source="tests.oversized_baseline",
    )
    assert oversized_report.baseline_failure_count == 1
    assert oversized_report.no_regression is False

    current = cases[0].records[-1]
    fork = correct_episode(
        cases[0].records[0],
        actor_id="fixture:e3.1",
        occurred_at=current.updated_at,
        reason="conflicting comparison fork",
        summary=_direct(
            "Conflicting current plan assigns port gamma.",
            cases[0].records[0].references[0].reference_id,
        ),
    ).after[0]
    forked_case = EpisodeComparisonCase(
        case_id=cases[0].case_id,
        ability=cases[0].ability,
        privacy_class=cases[0].privacy_class,
        facts=cases[0].facts,
        question=cases[0].question,
        expected=cases[0].expected,
        abstain=cases[0].abstain,
        records=(cases[0].records[0], current, fork),
        query=cases[0].query,
    )
    fork_report = await compare_episode_retrieval(
        cases=(forked_case,),
        comparison_id="e3.1-fork",
        baseline_runner=perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    assert fork_report.episode_failure_count == 1
    assert fork_report.cases[0].episode_failure_type == "ValueError"
    assert fork_report.no_regression is False
    assert "conflicting revisions" not in fork_report.to_json()

    with pytest.raises(ValueError, match="privacy class"):
        EpisodeComparisonCase(
            case_id=cases[0].case_id,
            ability=cases[0].ability,
            privacy_class="private",  # type: ignore[arg-type]
            facts=cases[0].facts,
            question=cases[0].question,
            expected=cases[0].expected,
            abstain=cases[0].abstain,
            records=cases[0].records,
            query=cases[0].query,
        )
    with pytest.raises(ValueError, match="content-free identifier"):
        EpisodeComparisonCase(
            case_id="Project Harbor private fact",
            ability=cases[0].ability,
            privacy_class=cases[0].privacy_class,
            facts=cases[0].facts,
            question=cases[0].question,
            expected=cases[0].expected,
            abstain=cases[0].abstain,
            records=cases[0].records,
            query=cases[0].query,
        )
    with pytest.raises(ValueError, match="case IDs must be unique"):
        await compare_episode_retrieval(
            cases=(cases[0], cases[0]),
            comparison_id="e3.1-duplicate",
            baseline_runner=perfect_baseline,
            baseline_source="tests.perfect_baseline",
        )
    with pytest.raises(ValueError, match="content-free identifier"):
        await compare_episode_retrieval(
            cases=(cases[0],),
            comparison_id="Project Harbor report",
            baseline_runner=perfect_baseline,
            baseline_source="tests.perfect_baseline",
        )


def run_e3_1_checks() -> None:
    """Run bounded E3.1 async checks from the existing E3 regression hook."""

    asyncio.run(_run_e3_1_checks())
