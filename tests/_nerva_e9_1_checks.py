"""Assertions invoked by the existing E9.0 benchmark test for E9.1.

The helper is deliberately not a pytest collection target. The repository pins
its generated test count, so the bounded scheduled-reporting assertions are
called from an existing Research Lab regression rather than creating count-only
churn.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from agents.core.observability.benchmark import BenchmarkStore
from agents.core.observability.scheduled_report import (
    BASELINE_ID,
    CANDIDATE_ID,
    SUITE_NAME,
    EnvironmentProfile,
    MetricComparison,
    PrerequisiteError,
    RegressionReport,
    build_report,
    ensure_suite,
    main,
    previous_run,
    run_scheduled_suite,
    scheduled_cases,
    source_revision,
)

_REVISION = "a" * 40
_OTHER_REVISION = "b" * 40


def _environment() -> EnvironmentProfile:
    return EnvironmentProfile(
        runner_id="test-runner",
        platform="linux-x86_64",
        python_version="3.12.0",
    )


def _check_suite_is_synthetic_public_and_ci_only() -> None:
    """Only synthetic-public cases may run in repository CI."""

    cases = scheduled_cases()
    assert cases, "the scheduled suite cannot be empty"
    for case in cases:
        assert case.privacy_class == "synthetic_public"
        assert case.allowed_lanes == ("ci",)
        # An owner-private or sanitized case would be refused by the lane gate.
        with pytest.raises(PermissionError):
            case.enforce_lane("local")
    assert len({case.case_id for case in cases}) == len(cases)


def _check_suite_version_is_stable_until_content_changes(tmp_path) -> None:
    """Re-running an unchanged suite must not mint a new version."""

    store = BenchmarkStore(tmp_path / "stable")
    first = ensure_suite(store)
    second = ensure_suite(store)
    assert first == second == 1
    assert store.versions(SUITE_NAME) == [1]

    # A different suite content does produce a new version.
    changed = scheduled_cases()[:-1]
    store.save_suite(SUITE_NAME, changed, lane="ci")
    assert store.versions(SUITE_NAME) == [1, 2]
    # ensure_suite restores the canonical content as version 3 rather than
    # silently reusing the truncated suite.
    assert ensure_suite(store) == 3


def _check_scheduled_run_persists_through_the_accepted_store(tmp_path) -> None:
    """Evidence is retained through E9.0, without creating a second store."""

    store = BenchmarkStore(tmp_path / "runs")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))

    assert run.suite_name == SUITE_NAME
    assert run.lane == "ci"
    assert run.candidate_id == CANDIDATE_ID
    assert run.baseline_id == BASELINE_ID
    assert run.source_revision == _REVISION
    assert run.authority == "evaluation_only"
    assert run.can_change_routing is False

    retained = store.runs(SUITE_NAME, last_n=5)
    assert [record.run_id for record in retained] == ["run-one"]
    # Every suite case is represented, including any that failed or went unscored.
    assert {result.case_id for result in run.results} == {
        case.case_id for case in scheduled_cases()
    }


def _check_first_run_has_no_baseline_and_cannot_claim_a_regression(tmp_path) -> None:
    """A first scheduled run compares against nothing and says so."""

    store = BenchmarkStore(tmp_path / "first")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))
    assert previous_run(store, exclude_run_id="run-one") is None

    report = build_report(run, environment=_environment(), previous=None)
    assert report.previous_run_id is None
    assert report.regressed is False
    assert {comparison.status for comparison in report.comparisons} == {"no_baseline"}
    for comparison in report.comparisons:
        assert comparison.delta is None


def _check_regression_and_improvement_are_decided_only_on_measured_metrics(
    tmp_path,
) -> None:
    """Only metrics measured on both sides participate in the decision."""

    store = BenchmarkStore(tmp_path / "regress")
    first = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))
    second = asyncio.run(
        run_scheduled_suite(store, revision=_OTHER_REVISION, run_id="run-two")
    )

    # Two identical deterministic runs must not report drift.
    steady = build_report(second, environment=_environment(), previous=first)
    assert steady.previous_run_id == "run-one"
    assert steady.regressed is False
    assert {
        comparison.status
        for comparison in steady.comparisons
        if comparison.metric == "quality_mean"
    } == {"unchanged"}

    # A genuinely lower measured quality is a regression.
    degraded = _with_quality(second, 0.25)
    report = build_report(degraded, environment=_environment(), previous=first)
    quality = _comparison(report, "quality_mean")
    assert quality.status == "regressed"
    assert quality.delta is not None and quality.delta < 0
    assert report.regressed is True

    # The inverse is an improvement, not a regression.
    improved = build_report(first, environment=_environment(), previous=degraded)
    assert _comparison(improved, "quality_mean").status == "improved"
    assert improved.regressed is False


def _check_unmeasured_metrics_are_never_coerced_into_a_score(tmp_path) -> None:
    """An unmeasured side stays `not_measured` and cannot decide a regression."""

    store = BenchmarkStore(tmp_path / "unmeasured")
    first = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))
    unscored = _with_unscored_case(first)

    report = build_report(unscored, environment=_environment(), previous=first)
    ratio = _comparison(report, "pass_ratio")
    assert ratio.status == "not_measured"
    assert ratio.delta is None
    # An undecided metric never flips the regression flag on its own.
    assert all(
        comparison.status != "regressed"
        for comparison in report.comparisons
        if comparison.metric == "pass_ratio"
    )

    # A comparison across a different suite version is not a comparison at all.
    other_version = replace(first, suite_version=first.suite_version + 1)
    across = build_report(first, environment=_environment(), previous=other_version)
    assert across.previous_run_id is None
    assert {comparison.status for comparison in across.comparisons} == {"no_baseline"}


def _check_report_is_deterministic_and_evaluation_only(tmp_path) -> None:
    """The same inputs and environment reproduce the same report structure."""

    store = BenchmarkStore(tmp_path / "deterministic")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))

    first = build_report(run, environment=_environment(), previous=None)
    second = build_report(run, environment=_environment(), previous=None)
    assert first.to_json() == second.to_json()

    payload = json.loads(first.to_json())
    assert payload["schema"] == "nerva.benchmark.report.v1"
    assert payload["authority"] == "evaluation_only"
    for flag in (
        "can_change_routing",
        "can_authorize",
        "can_execute",
        "can_promote_capability",
        "can_mark_complete",
    ):
        assert payload[flag] is False

    # The report binds itself to suite, revision, runner identity and environment.
    assert payload["suite_name"] == SUITE_NAME
    assert payload["source_revision"] == _REVISION
    assert payload["environment"]["runner_id"] == "test-runner"
    assert payload["environment"]["hardware_profile"] == "not_measured"
    assert "not_measured" in first.to_markdown() or "no_baseline" in first.to_markdown()


def _check_report_invariants_reject_incoherent_summaries() -> None:
    """A report cannot understate a regression or invent a comparison."""

    environment = _environment()
    regressed = MetricComparison(
        metric="quality_mean",
        status="regressed",
        current=0.5,
        previous=0.9,
        delta=-0.4,
    )

    def _build(**overrides) -> RegressionReport:
        fields = {
            "suite_name": SUITE_NAME,
            "suite_version": 1,
            "run_id": "run-one",
            "source_revision": _REVISION,
            "candidate_id": CANDIDATE_ID,
            "baseline_id": BASELINE_ID,
            "environment": environment,
            "totals": {"total": 4},
            "comparisons": (regressed,),
            "previous_run_id": "run-zero",
            "regressed": True,
        }
        fields.update(overrides)
        return RegressionReport(**fields)

    _build()
    with pytest.raises(ValueError, match="regression flag must match"):
        _build(regressed=False)
    with pytest.raises(ValueError, match="requires a previous run"):
        _build(previous_run_id=None)
    with pytest.raises(ValueError, match="at least one comparison"):
        _build(comparisons=(), regressed=False)
    with pytest.raises(ValueError, match="EnvironmentProfile"):
        _build(environment={"runner_id": "spoofed"})

    # A decided comparison cannot be asserted without both values.
    with pytest.raises(ValueError, match="requires both values"):
        MetricComparison(metric="quality_mean", status="regressed", current=0.5)
    with pytest.raises(ValueError, match="cannot carry a delta"):
        MetricComparison(metric="quality_mean", status="not_measured", delta=0.1)


def _check_missing_prerequisites_fail_visibly(tmp_path, monkeypatch) -> None:
    """A missing prerequisite is a visible failure, never a fabricated pass."""

    import agents.core.observability.scheduled_report as module

    monkeypatch.setattr(
        module,
        "missing_prerequisites",
        lambda: ("IntentRouter.llm_classifier is None (deterministic lane)",),
    )
    store = BenchmarkStore(tmp_path / "missing")
    with pytest.raises(PrerequisiteError, match="prerequisites are missing"):
        asyncio.run(run_scheduled_suite(store, revision=_REVISION))

    summary = tmp_path / "summary.md"
    exit_code = main(
        [
            "--store-root",
            str(tmp_path / "missing"),
            "--summary",
            str(summary),
            "--revision",
            _REVISION,
        ]
    )
    assert exit_code == 2
    text = summary.read_text(encoding="utf-8")
    assert "FAILED" in text
    assert "prerequisites are missing" in text
    # No run may be retained for a suite that never executed.
    assert BenchmarkStore(tmp_path / "missing").runs(SUITE_NAME, last_n=5) == ()

    # An unresolvable revision is equally a visible failure.
    monkeypatch.setattr(module, "missing_prerequisites", lambda: ())
    monkeypatch.setattr(
        module,
        "subprocess",
        _FailingGit(),
    )
    with pytest.raises(PrerequisiteError, match="cannot resolve source revision"):
        source_revision(None)


def _check_cli_reports_without_changing_routing(tmp_path) -> None:
    """The CLI emits a summary and only fails on regression when asked."""

    store_root = tmp_path / "cli"
    summary = tmp_path / "cli-summary.md"
    json_out = tmp_path / "cli-report.json"

    exit_code = main(
        [
            "--store-root",
            str(store_root),
            "--summary",
            str(summary),
            "--json-out",
            str(json_out),
            "--revision",
            _REVISION,
            "--runner-id",
            "test-runner",
        ]
    )
    assert exit_code == 0

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema"] == "nerva.benchmark.report.v1"
    assert payload["can_change_routing"] is False
    assert payload["suite_name"] == SUITE_NAME
    assert "Nerva E9.1 scheduled shadow report" in summary.read_text(encoding="utf-8")

    # A second run compares against the first and stays green when steady.
    assert (
        main(
            [
                "--store-root",
                str(store_root),
                "--summary",
                str(summary),
                "--revision",
                _OTHER_REVISION,
                "--fail-on-regression",
            ]
        )
        == 0
    )
    assert len(BenchmarkStore(store_root).runs(SUITE_NAME, last_n=5)) == 2


class _FailingGit:
    """Stand-in for ``subprocess`` whose git invocation fails."""

    class CalledProcess:
        stdout = ""
        returncode = 1

    def run(self, *args, **kwargs):  # noqa: D102 - test double
        return self.CalledProcess()


def _comparison(report: RegressionReport, metric: str) -> MetricComparison:
    for comparison in report.comparisons:
        if comparison.metric == metric:
            return comparison
    raise AssertionError(f"missing comparison for {metric}")


def _with_quality(run, value: float):
    """Return a copy of ``run`` whose measured candidate quality is ``value``."""

    from agents.core.observability.benchmark import Measurement

    results = tuple(
        replace(
            result,
            quality=Measurement("measured", value, "ratio", "test.fixture"),
            status="failed" if value < 0.5 else result.status,
            passed=False if value < 0.5 else result.passed,
        )
        for result in run.results
    )
    return replace(run, results=results)


def _with_unscored_case(run):
    """Return a copy of ``run`` whose first case has no measured quality."""

    from agents.core.observability.benchmark import Measurement

    first, *rest = run.results
    unscored = replace(
        first,
        status="unscored",
        passed=None,
        quality=Measurement("not_measured"),
        # An unscored candidate leaves the baseline explicitly unmeasured too.
        baseline_quality=Measurement("not_measured"),
    )
    return replace(run, results=(unscored, *rest))


def run_e9_1_checks(tmp_path, monkeypatch) -> None:
    """Run every bounded E9.1 scheduled-reporting assertion."""

    _check_suite_is_synthetic_public_and_ci_only()
    _check_suite_version_is_stable_until_content_changes(tmp_path)
    _check_scheduled_run_persists_through_the_accepted_store(tmp_path)
    _check_first_run_has_no_baseline_and_cannot_claim_a_regression(tmp_path)
    _check_regression_and_improvement_are_decided_only_on_measured_metrics(tmp_path)
    _check_unmeasured_metrics_are_never_coerced_into_a_score(tmp_path)
    _check_report_is_deterministic_and_evaluation_only(tmp_path)
    _check_report_invariants_reject_incoherent_summaries()
    _check_missing_prerequisites_fail_visibly(tmp_path, monkeypatch)
    _check_cli_reports_without_changing_routing(tmp_path)
