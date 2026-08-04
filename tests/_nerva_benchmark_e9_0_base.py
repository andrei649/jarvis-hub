import json
from dataclasses import replace

import pytest

from agents.core.observability.benchmark import (
    BenchmarkCase,
    BenchmarkCriterion,
    BenchmarkEvidence,
    BenchmarkHarness,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkRun,
    BenchmarkStore,
    KeywordRouteBaseline,
    Measurement,
    ResourceMeasurement,
    current_router_runner,
)
from agents.core.router import IntentRouter

_FIXED_TS = "2026-08-04T03:30:00.000Z"
_REVISION = "a48a2d0c71f441bc0ad719920e024a4dc44378a6"


def _case(
    case_id: str = "route-weather",
    *,
    expected: str | None = "friday",
    privacy_class: str = "synthetic_public",
    allowed_lanes: tuple[str, ...] = ("ci", "local"),
) -> BenchmarkCase:
    criterion = BenchmarkCriterion("exact", expected) if expected is not None else None
    return BenchmarkCase(
        case_id=case_id,
        task_type="route-selection",
        input_text="What is the weather?",
        privacy_class=privacy_class,
        allowed_lanes=allowed_lanes,
        criterion=criterion,
        tags=("router",),
    )


async def _candidate(prompt: str) -> BenchmarkObservation:
    return BenchmarkObservation(
        response="friday" if "weather" in prompt.lower() else "jarvis",
        route_id="friday",
        model_id="none",
        provider_id="local-deterministic",
        host_id="test-host",
        hardware_profile="test-profile",
        latency_ms=1.5,
        cost_usd=0.0,
        reliability=1.0,
        privacy_effect="no_external_disclosure",
    )


async def _failing_candidate(_prompt: str) -> BenchmarkObservation:
    raise RuntimeError("private backend details must not be retained")


def _clock():
    return _FIXED_TS


def test_case_round_trip_requires_digest_and_preserves_dimensions():
    case = _case()
    payload = case.to_dict(lane="ci")

    restored = BenchmarkCase.from_dict(payload)
    assert restored == case
    assert payload["schema"] == "nerva.benchmark.v1"
    assert payload["kind"] == "case"
    assert payload["input_digest"] == case.input_digest

    payload["input_digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        BenchmarkCase.from_dict(payload)


def test_owner_private_cases_fail_closed_outside_local_lane(tmp_path):
    case = _case(
        privacy_class="owner_private_local",
        allowed_lanes=("local",),
    )
    store = BenchmarkStore(tmp_path)

    with pytest.raises(PermissionError, match="explicit local serialization"):
        case.to_dict()
    with pytest.raises(PermissionError, match="cannot run"):
        case.to_dict(lane="ci")
    with pytest.raises(PermissionError, match="cannot run"):
        store.save_suite("private-suite", [case], lane="cloud")
    assert not (tmp_path / "suites" / "private-suite").exists()

    version = store.save_suite("private-suite", [case], lane="local")
    assert version == 1
    assert store.load_suite("private-suite", 1) == (case,)


async def test_harness_keeps_route_model_provider_host_and_baseline_separate():
    case = _case()
    baseline = KeywordRouteBaseline({"weather": "friday"})
    harness = BenchmarkHarness(
        _candidate,
        candidate_id="current-router",
        baseline=baseline,
        baseline_id="keyword-baseline.v1",
    )

    run = await harness.run(
        [case],
        suite_name="router-foundation",
        suite_version=1,
        lane="ci",
        source_revision=_REVISION,
        run_id="run-foundation",
        now=_clock,
    )

    result = run.results[0]
    assert result.status == "passed"
    assert result.quality.value == 1.0
    assert result.baseline_quality.value == 1.0
    assert result.candidate["route_id"] == "friday"
    assert result.candidate["model_id"] == "none"
    assert result.candidate["provider_id"] == "local-deterministic"
    assert result.candidate["host_id"] == "test-host"
    assert result.baseline["model_id"] == "keyword-baseline.v1"
    assert "response" not in result.candidate
    assert case.input_text not in run.to_json()
    assert run.authority == "evaluation_only"
    assert run.can_change_routing is False
    assert run.can_authorize is False
    assert run.can_execute is False
    assert run.can_mark_complete is False


async def test_criterionless_case_is_unscored_not_passed():
    run = await BenchmarkHarness(_candidate, candidate_id="current-router").run(
        [_case(expected=None)],
        suite_name="unscored-suite",
        suite_version=1,
        lane="ci",
        source_revision=_REVISION,
        run_id="run-unscored",
        now=_clock,
    )

    result = run.results[0]
    assert result.status == "unscored"
    assert result.passed is None
    assert result.quality.status == "not_measured"
    assert run.summary["passed"] == 0
    assert run.summary["scored"] == 0
    assert run.summary["quality_mean"] is None


async def test_failed_and_negative_runs_are_retained_without_exception_messages(tmp_path):
    cases = (
        _case("route-negative", expected="pepper"),
        _case("route-error", expected="friday"),
    )
    store = BenchmarkStore(tmp_path)
    version = store.save_suite("retention-suite", cases, lane="ci")

    negative = await BenchmarkHarness(_candidate, candidate_id="current-router").run(
        [cases[0]],
        suite_name="retention-suite",
        suite_version=version,
        lane="ci",
        source_revision=_REVISION,
        run_id="run-negative",
        now=_clock,
    )
    error = await BenchmarkHarness(
        _failing_candidate, candidate_id="failing-candidate"
    ).run(
        [cases[1]],
        suite_name="retention-suite",
        suite_version=version,
        lane="ci",
        source_revision=_REVISION,
        run_id="run-error",
        now=_clock,
    )

    assert negative.results[0].status == "failed"
    assert error.results[0].status == "error"
    assert error.results[0].error_type == "RuntimeError"
    assert "private backend details" not in error.to_json()

    with pytest.raises(ValueError, match="cover the suite case ids exactly"):
        store.record_run(negative)

    combined_negative = replace(negative, results=(negative.results[0], error.results[0]))
    combined_error = replace(error, results=(negative.results[0], error.results[0]))
    store.record_run(combined_negative)
    store.record_run(combined_error)
    retained = store.runs("retention-suite")
    assert [run.run_id for run in retained] == ["run-error", "run-negative"]
    assert retained[0].results[1].status == "error"
    assert retained[1].results[0].status == "failed"


async def test_run_round_trip_rejects_authority_or_summary_tampering():
    run = await BenchmarkHarness(_candidate, candidate_id="current-router").run(
        [_case()],
        suite_name="round-trip-suite",
        suite_version=1,
        lane="ci",
        source_revision=_REVISION,
        run_id="run-round-trip",
        now=_clock,
    )
    assert BenchmarkRun.from_json(run.to_json()) == run

    payload = json.loads(run.to_json())
    payload["can_change_routing"] = True
    with pytest.raises(ValueError, match="authority flags"):
        BenchmarkRun.from_json(json.dumps(payload))

    payload = json.loads(run.to_json())
    payload["summary"]["passed"] = 99
    with pytest.raises(ValueError, match="summary mismatch"):
        BenchmarkRun.from_json(json.dumps(payload))

    payload = json.loads(run.to_json())
    payload["results"][0]["candidate"]["response"] = "must not survive"
    with pytest.raises(ValueError, match="evidence fields"):
        BenchmarkRun.from_json(json.dumps(payload))


def test_structure_fingerprint_ignores_volatile_values_but_not_contract_shape():
    result = _result_fixture()
    run = BenchmarkRun(
        suite_name="stable-shape",
        suite_version=1,
        lane="ci",
        run_id="run-one",
        started_at=_FIXED_TS,
        finished_at=_FIXED_TS,
        source_revision=_REVISION,
        candidate_id="current-router",
        baseline_id=None,
        results=(result,),
    )
    changed_values = replace(
        run,
        run_id="run-two",
        source_revision="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        results=(replace(result, quality=Measurement("measured", 0.0, "ratio", "test")),),
    )
    changed_shape = replace(
        run,
        results=(
            replace(
                result,
                baseline=_evidence("jarvis"),
                baseline_quality=Measurement("measured", 1.0, "ratio", "test"),
            ),
        ),
        baseline_id="keyword-baseline.v1",
    )

    assert changed_values.structure_fingerprint == run.structure_fingerprint
    assert changed_shape.structure_fingerprint != run.structure_fingerprint


def _evidence(route_id: str) -> BenchmarkEvidence:
    return BenchmarkEvidence(
        route_id=route_id,
        model_id="none",
        provider_id="local-deterministic",
        host_id="test-host",
        hardware_profile="test-profile",
        response_digest="0" * 64,
        response_length=6,
    )


def _result_fixture():
    return BenchmarkResult(
        case_id="route-weather",
        task_type="route-selection",
        privacy_class="synthetic_public",
        status="passed",
        passed=True,
        candidate=_evidence("friday"),
        baseline=None,
        quality=Measurement("measured", 1.0, "ratio", "test"),
        baseline_quality=Measurement("not_applicable"),
        latency=Measurement("measured", 1.0, "ms", "test"),
        cost=Measurement("measured", 0.0, "usd", "test"),
        reliability=Measurement("measured", 1.0, "ratio", "test"),
        privacy=Measurement(
            "measured", "no_external_disclosure", "classification", "test"
        ),
    )


def test_store_rejects_path_escape_and_nonfinite_measurement(tmp_path):
    store = BenchmarkStore(tmp_path)
    with pytest.raises(ValueError, match="path-free"):
        store.save_suite("../escape", [_case()], lane="ci")
    with pytest.raises(ValueError, match="finite"):
        Measurement("measured", float("nan"), "ms", "test")


async def test_current_router_is_measurable_against_transparent_simple_baseline():
    cases = (
        BenchmarkCase(
            "route-weather",
            "route-selection",
            "What is the weather?",
            "synthetic_public",
            ("ci",),
            BenchmarkCriterion("exact", "friday"),
        ),
        BenchmarkCase(
            "route-calendar",
            "route-selection",
            "Show my calendar",
            "synthetic_public",
            ("ci",),
            BenchmarkCriterion("exact", "pepper"),
        ),
        BenchmarkCase(
            "route-general",
            "route-selection",
            "hello",
            "synthetic_public",
            ("ci",),
            BenchmarkCriterion("exact", "jarvis"),
        ),
    )
    router = IntentRouter(config={})
    candidate = current_router_runner(
        router,
        {"jarvis": object(), "friday": object(), "pepper": object()},
        host_id="test-host",
    )
    baseline = KeywordRouteBaseline({"weather": "friday", "calendar": "pepper"})

    run = await BenchmarkHarness(
        candidate,
        candidate_id="current-router",
        baseline=baseline,
        baseline_id="keyword-baseline.v1",
    ).run(
        cases,
        suite_name="current-router-foundation",
        suite_version=1,
        lane="ci",
        source_revision=_REVISION,
        run_id="run-current-router",
        now=_clock,
    )

    assert run.summary == {
        "total": 3,
        "scored": 3,
        "passed": 3,
        "failed": 0,
        "unscored": 0,
        "errors": 0,
        "quality_mean": 1.0,
        "baseline_quality_mean": 1.0,
    }
    assert all(
        result.candidate["route_id"] == result.baseline["route_id"]
        for result in run.results
    )


async def test_deserialization_rejects_message_like_exception_types_and_semantic_drift():
    error = await BenchmarkHarness(
        _failing_candidate, candidate_id="failing-candidate"
    ).run(
        [_case()],
        suite_name="hostile-errors",
        suite_version=1,
        lane="ci",
        source_revision=_REVISION,
        run_id="run-hostile-errors",
        now=_clock,
    )
    payload = json.loads(error.to_json())
    payload["results"][0]["error_type"] = "RuntimeError: secret fixture\ntrace"
    with pytest.raises(ValueError, match="canonical exception class"):
        BenchmarkRun.from_json(json.dumps(payload))

    valid = _result_fixture()
    with pytest.raises(ValueError, match="only error results"):
        replace(valid, error_type="RuntimeError")
    with pytest.raises(ValueError, match="baseline errors require"):
        replace(valid, baseline_error_type="TimeoutError")
    with pytest.raises(ValueError, match="failed baseline quality requires"):
        replace(valid, baseline_quality=Measurement("failed", source="baseline.runner"))


def test_result_rejects_raw_measurement_text_wrong_units_ranges_and_resources():
    result = _result_fixture()
    run = BenchmarkRun(
        suite_name="metric-integrity",
        suite_version=1,
        lane="ci",
        run_id="run-metric-integrity",
        started_at=_FIXED_TS,
        finished_at=_FIXED_TS,
        source_revision=_REVISION,
        candidate_id="current-router",
        baseline_id=None,
        results=(result,),
    )

    payload = json.loads(run.to_json())
    payload["results"][0]["latency"] = {
        "status": "measured",
        "value": "owner private text",
        "unit": "ms",
        "source": "test",
    }
    with pytest.raises(ValueError, match="finite non-negative"):
        BenchmarkRun.from_json(json.dumps(payload))

    payload = json.loads(run.to_json())
    payload["results"][0]["cost"]["unit"] = "ms"
    with pytest.raises(ValueError, match="cost must use usd"):
        BenchmarkRun.from_json(json.dumps(payload))

    payload = json.loads(run.to_json())
    payload["results"][0]["reliability"]["value"] = 1.1
    with pytest.raises(ValueError, match="finite non-negative"):
        BenchmarkRun.from_json(json.dumps(payload))

    payload = json.loads(run.to_json())
    payload["results"][0]["privacy"]["value"] = "private fixture contents"
    with pytest.raises(ValueError, match="supported classification"):
        BenchmarkRun.from_json(json.dumps(payload))

    with pytest.raises(ValueError, match="finite non-negative"):
        ResourceMeasurement(
            "gpu-memory",
            Measurement("measured", "secret", "mb", "test"),
        )
    with pytest.raises(ValueError, match="failed evidence cannot claim a unit"):
        Measurement("failed", unit="ms", source="test")


async def test_store_binds_task_and_privacy_metadata_to_suite_case(tmp_path):
    private_case = _case(
        privacy_class="owner_private_local",
        allowed_lanes=("local",),
    )
    store = BenchmarkStore(tmp_path)
    version = store.save_suite("metadata-bound", [private_case], lane="local")
    run = await BenchmarkHarness(_candidate, candidate_id="current-router").run(
        [private_case],
        suite_name="metadata-bound",
        suite_version=version,
        lane="local",
        source_revision=_REVISION,
        run_id="run-metadata-bound",
        now=_clock,
    )

    downgraded_privacy = replace(
        run,
        results=(replace(run.results[0], privacy_class="synthetic_public"),),
    )
    with pytest.raises(ValueError, match="metadata must match"):
        store.record_run(downgraded_privacy)

    changed_task = replace(
        run,
        results=(replace(run.results[0], task_type="different-task"),),
    )
    with pytest.raises(ValueError, match="metadata must match"):
        store.record_run(changed_task)

    store.record_run(run)
    assert store.runs("metadata-bound")[0] == run
