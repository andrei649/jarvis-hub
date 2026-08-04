"""E9.0 focused tests plus bounded independent-review regressions.

The unchanged contract tests remain in the private base module so the two
corrected tests can preserve the twelve-test collection surface and status
metadata while adding the missing hostile cases.
"""

import json
from dataclasses import replace

import pytest

from agents.core.observability.benchmark import (
    BenchmarkHarness,
    BenchmarkRun,
    Measurement,
    current_router_runner,
)
from agents.core.router import IntentRouter
from tests import _nerva_benchmark_e9_0_base as _base_tests

# Preserve the ten unchanged focused tests without collecting the private base
# module separately.
test_case_round_trip_requires_digest_and_preserves_dimensions = (
    _base_tests.test_case_round_trip_requires_digest_and_preserves_dimensions
)
test_owner_private_cases_fail_closed_outside_local_lane = (
    _base_tests.test_owner_private_cases_fail_closed_outside_local_lane
)
test_harness_keeps_route_model_provider_host_and_baseline_separate = (
    _base_tests.test_harness_keeps_route_model_provider_host_and_baseline_separate
)
test_criterionless_case_is_unscored_not_passed = (
    _base_tests.test_criterionless_case_is_unscored_not_passed
)
test_failed_and_negative_runs_are_retained_without_exception_messages = (
    _base_tests.test_failed_and_negative_runs_are_retained_without_exception_messages
)
test_structure_fingerprint_ignores_volatile_values_but_not_contract_shape = (
    _base_tests.test_structure_fingerprint_ignores_volatile_values_but_not_contract_shape
)
test_store_rejects_path_escape_and_nonfinite_measurement = (
    _base_tests.test_store_rejects_path_escape_and_nonfinite_measurement
)
test_deserialization_rejects_message_like_exception_types_and_semantic_drift = (
    _base_tests.test_deserialization_rejects_message_like_exception_types_and_semantic_drift
)
test_result_rejects_raw_measurement_text_wrong_units_ranges_and_resources = (
    _base_tests.test_result_rejects_raw_measurement_text_wrong_units_ranges_and_resources
)
test_store_binds_task_and_privacy_metadata_to_suite_case = (
    _base_tests.test_store_binds_task_and_privacy_metadata_to_suite_case
)


def _run_with(result, *, baseline_id):
    return BenchmarkRun(
        suite_name="baseline-identity",
        suite_version=1,
        lane="ci",
        run_id="run-baseline-identity",
        started_at=_base_tests._FIXED_TS,
        finished_at=_base_tests._FIXED_TS,
        source_revision=_base_tests._REVISION,
        candidate_id="current-router",
        baseline_id=baseline_id,
        results=(result,),
    )


async def test_run_round_trip_rejects_authority_or_summary_tampering():
    await _base_tests.test_run_round_trip_rejects_authority_or_summary_tampering()

    result = _base_tests._result_fixture()
    with_baseline = _run_with(
        replace(
            result,
            baseline=_base_tests._evidence("friday"),
            baseline_quality=Measurement("measured", 1.0, "ratio", "test"),
        ),
        baseline_id="keyword-baseline.v1",
    )
    payload = json.loads(with_baseline.to_json())
    payload["baseline_id"] = None
    with pytest.raises(ValueError, match="declared baseline identity"):
        BenchmarkRun.from_json(json.dumps(payload))

    without_baseline = _run_with(result, baseline_id=None)
    payload = json.loads(without_baseline.to_json())
    payload["baseline_id"] = "keyword-baseline.v1"
    with pytest.raises(ValueError, match="cannot use not_applicable"):
        BenchmarkRun.from_json(json.dumps(payload))

    skipped = await BenchmarkHarness(
        _base_tests._failing_candidate,
        candidate_id="failing-candidate",
        baseline=_base_tests._candidate,
        baseline_id="keyword-baseline.v1",
    ).run(
        [_base_tests._case()],
        suite_name="baseline-skipped",
        suite_version=1,
        lane="ci",
        source_revision=_base_tests._REVISION,
        run_id="run-baseline-skipped",
        now=_base_tests._clock,
    )
    assert skipped.results[0].baseline_quality.status == "not_measured"
    payload = json.loads(skipped.to_json())
    payload["results"][0]["baseline_quality"] = {
        "status": "failed",
        "value": None,
        "unit": None,
        "source": "baseline.runner",
    }
    payload["results"][0]["baseline_error_type"] = "TimeoutError"
    with pytest.raises(ValueError, match="explicitly unmeasured skipped baseline"):
        BenchmarkRun.from_json(json.dumps(payload))


async def test_current_router_is_measurable_against_transparent_simple_baseline():
    await _base_tests.test_current_router_is_measurable_against_transparent_simple_baseline()

    calls = []

    async def fallback(text, ranked):
        calls.append((text, tuple(ranked)))
        return ["vision"]

    configured = IntentRouter(config={}, llm_classifier=fallback)
    with pytest.raises(ValueError, match="llm_classifier=None"):
        current_router_runner(configured, {"jarvis": object(), "vision": object()})
    assert calls == []

    mutable = IntentRouter(config={})
    runner = current_router_runner(mutable, {"jarvis": object(), "vision": object()})
    mutable.llm_classifier = fallback
    with pytest.raises(ValueError, match="llm_classifier=None"):
        await runner("an unmatched synthetic prompt")
    assert calls == []
