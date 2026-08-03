"""Tests for the evaluation-only Cortex E1.1 comparison baseline."""

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

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "nerva" / "cortex_e1_1_cases.json"
)


def _cases():
    return load_comparison_cases(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _agents():
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


def test_twenty_case_current_router_baseline_matches_fixture_expectations():
    report = _run()

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


def test_case_order_does_not_change_canonical_report():
    cases = _cases()

    assert _run(cases).replay_fingerprint == _run(
        tuple(reversed(cases))
    ).replay_fingerprint


def test_report_omits_fixture_text_and_keeps_unmeasured_dimensions_honest():
    cases = _cases()
    report = _run(cases)
    serialized = report.to_json()

    assert all(case.text not in serialized for case in cases)
    assert report.latency.status == "not_measured"
    assert report.cost.status == "not_measured"
    assert report.real_outcome_quality.status == "not_measured"
    assert report.authority == "evaluation_only"
    assert not report.can_authorize
    assert not report.can_execute
    assert not report.can_mark_complete


def test_router_failures_are_bounded_and_exception_messages_are_not_serialized():
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

    cases = (
        ComparisonCase("ok", "safe synthetic", "jarvis", "general"),
        ComparisonCase("bad", "explode now", "jarvis", "general"),
    )
    report = _run(cases=cases, router=FailingRouter())

    assert report.failure_count == 1
    assert [case.case_id for case in report.cases] == ["bad", "ok"]
    assert report.cases[0].failure_type == "RuntimeError"
    assert "secret fixture content" not in report.to_json()
    assert "explode now" not in report.to_json()


def test_duplicate_case_ids_fail_closed():
    cases = (
        ComparisonCase("same", "weather", "friday", "keyword_match"),
        ComparisonCase("same", "news", "friday", "keyword_match"),
    )

    with pytest.raises(ValueError, match="unique"):
        _run(cases=cases)
