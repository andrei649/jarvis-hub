"""Query-parity regressions for the Nerva Episodes E3.1 comparison."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nerva_e3_1_checks import _longitudinal_cases  # noqa: E402
from agents.core.memory.episode_compare import (  # noqa: E402
    compare_episode_retrieval,
)
from agents.core.memory.episodes import EpisodeQuery  # noqa: E402


async def _perfect_baseline(corpus, *, top_k):
    return {
        "top_k": top_k,
        "results": [
            {
                "id": case.id,
                "passed": True,
                "retrieved": list(case.facts)[:top_k],
            }
            for case in corpus
        ],
    }


async def _run_query_parity_checks() -> None:
    harbor = next(
        case
        for case in _longitudinal_cases()
        if case.case_id == "stable-harbor-outcome"
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
        baseline_runner=_perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )
    oracle_report = await compare_episode_retrieval(
        cases=(oracle_diagnostic,),
        comparison_id="e3.1-query-invariance",
        baseline_runner=_perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )

    assert aligned_report.to_json() == oracle_report.to_json()
    assert (
        oracle_report.episode_accuracy.source
        == "episodes.retrieve_episodes.question_derived"
    )

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
        baseline_runner=_perfect_baseline,
        baseline_source="tests.perfect_baseline",
    )

    assert fail_closed.baseline_accuracy.value == 1.0
    assert fail_closed.episode_accuracy.value == 0.0
    assert fail_closed.cases[0].episode_match_count == 0
    assert fail_closed.episode_win_count == 0
    assert fail_closed.episode_loss_count == 1
    assert fail_closed.no_regression is False


def test_e3_1_canonical_query_parity() -> None:
    asyncio.run(_run_query_parity_checks())
