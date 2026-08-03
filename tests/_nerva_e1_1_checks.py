"""Assertions invoked by an existing router test for the E1.1 baseline.

The helper deliberately is not a pytest collection target. The repository pins
its generated test count, so bounded Nerva assertions are called from the
existing router regression test rather than creating status-only churn.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agents.core.cortex_compare import (
    ComparisonCase,
    compare_router,
    load_comparison_cases,
)
from agents.core.router import Intent, IntentRouter

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "nerva" / "cortex_e1_1_cases.json"


def _cases() -> tuple[ComparisonCase, ...]:
    return load_comparison_cases(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _agents() -> dict[str, object]:
    return {agent_id: object() for agent_id in IntentRouter.ROUTING_TABLE}


def _run(cases=None, router=None):
    return asyncio.run(
        compare_router(
            router=router or IntentRouter(config=None),
            cases=cases or _cases(),
            agents=_agents(),
            baseline_id="cortex-e1.1-current-router-v1",
        )
    )


def run_e1_1_checks() -> None:
    """Run the E1.1 contract, privacy, failure and ledger assertions."""

    cases = _cases()
    report = _run(cases)

    assert report.total_cases == 20
    assert report.failure_count == 0
    assert report.primary_agreement.value == 1.0
    assert report.source_agreement.value == 1.0
    assert report.general_case_count == 1
    assert dict(report.source_distribution) == {
        "general": 1,
        "keyword_match": 18,
        "wake_word": 1,
    }
    assert dict(report.privacy_distribution) == {"synthetic_public": 20}
    assert all(result.privacy_class == "synthetic_public" for result in report.cases)
    assert report.replay_fingerprint == _run(tuple(reversed(cases))).replay_fingerprint

    serialized = report.to_json()
    assert all(case.text not in serialized for case in cases)
    assert report.latency.status == "not_measured"
    assert report.cost.status == "not_measured"
    assert report.real_outcome_quality.status == "not_measured"
    assert report.authority == "evaluation_only"
    assert not report.can_authorize
    assert not report.can_execute
    assert not report.can_mark_complete

    class FailingRouter:
        async def classify(self, text, agents):
            if "explode" in text:
                raise RuntimeError("secret fixture content must not leak")
            return Intent(
                ["jarvis"],
                is_general=True,
                context={"source": "general"},
                confidence=0.0,
            )

    failure_cases = (
        ComparisonCase(
            "ok", "safe synthetic", "jarvis", "general", "synthetic_public"
        ),
        ComparisonCase(
            "bad", "explode now", "jarvis", "general", "redacted_local"
        ),
    )
    failure_report = _run(cases=failure_cases, router=FailingRouter())
    assert failure_report.failure_count == 1
    assert [result.case_id for result in failure_report.cases] == ["bad", "ok"]
    assert failure_report.cases[0].failure_type == "RuntimeError"
    assert failure_report.cases[0].privacy_class == "redacted_local"
    assert dict(failure_report.privacy_distribution) == {
        "redacted_local": 1,
        "synthetic_public": 1,
    }
    assert "secret fixture content" not in failure_report.to_json()
    assert "explode now" not in failure_report.to_json()

    duplicate_cases = (
        ComparisonCase(
            "same", "weather", "friday", "keyword_match", "synthetic_public"
        ),
        ComparisonCase(
            "same", "news", "friday", "keyword_match", "synthetic_public"
        ),
    )
    with pytest.raises(ValueError, match="unique"):
        _run(cases=duplicate_cases)

    missing_classification = [
        {
            "case_id": "unclassified",
            "text": "weather",
            "expected_primary": "friday",
            "expected_source": "keyword_match",
        }
    ]
    with pytest.raises(ValueError, match="privacy_class"):
        load_comparison_cases(missing_classification)

    malformed_value = [
        {
            "case_id": "bad-type",
            "text": None,
            "expected_primary": "friday",
            "expected_source": "keyword_match",
            "privacy_class": "synthetic_public",
        }
    ]
    with pytest.raises(ValueError, match="text"):
        load_comparison_cases(malformed_value)

    snapshot = (ROOT / "docs" / "nerva2" / "M1_DELIVERY.md").read_text(
        encoding="utf-8"
    )
    assert "9235ef69961862df49826a910be00955d7be420e" in snapshot
    assert "E1.1 / #792 / PR #793" in snapshot
    assert "On a feature branch, these artifacts remain candidate evidence only" in snapshot
    assert (
        "When this snapshot is present on `main` through merged PR #793, E1.1 is"
        in snapshot
    )
    assert "pseudonymous/linkable" in snapshot
    assert (
        "#781 Atlas, #783 Synapse and #784 Research Lab remain separately eligible"
        in snapshot
    )
    assert "#782 Episodes remains blocked only by #781" in snapshot
    assert (
        "Ultron / `nerva.action.v1` remains the sole privileged-action authority"
        in snapshot
    )

    backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    marker = "<!-- NERVA2:E0-REPOSITORY-LEDGER:START -->"
    assert marker in backlog
    assert marker in status
    assert "This post-E0 snapshot is additive" in snapshot
    assert "immutable E0 marker blocks" in snapshot
