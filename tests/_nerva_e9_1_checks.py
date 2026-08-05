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
from pathlib import Path

import pytest

from agents.core.observability.benchmark import BenchmarkObservation, BenchmarkStore
from agents.core.observability.scheduled_report import (
    _COMPARED_METRICS,
    _REPORT_GUARD,
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
    run_fingerprint,
    run_scheduled_suite,
    scheduled_cases,
    source_revision,
    validate_report_against_run,
)

ROOT = Path(__file__).resolve().parent.parent
_REVISION = "a" * 40
_OTHER_REVISION = "b" * 40


def _environment() -> EnvironmentProfile:
    return EnvironmentProfile.detect(runner_id="test-runner")


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

    report = build_report(run, store=store, environment=_environment(), previous=None)
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
    steady = build_report(second, store=store, environment=_environment(), previous=first)
    assert steady.previous_run_id == "run-one"
    assert steady.regressed is False
    assert {
        comparison.status
        for comparison in steady.comparisons
        if comparison.metric == "quality_mean"
    } == {"unchanged"}

    # A genuinely lower measured quality is a regression. The degraded run is
    # retained first: an unrecorded run cannot become canonical evidence.
    degraded = replace(_with_quality(second, 0.25), run_id="run-degraded")
    store.record_run(degraded)
    report = build_report(degraded, store=store, environment=_environment(), previous=first)
    quality = _comparison(report, "quality_mean")
    assert quality.status == "regressed"
    assert quality.delta is not None and quality.delta < 0
    assert report.regressed is True

    # The inverse is an improvement, not a regression.
    improved = build_report(first, store=store, environment=_environment(), previous=degraded)
    assert _comparison(improved, "quality_mean").status == "improved"
    assert improved.regressed is False


def _check_unmeasured_metrics_are_never_coerced_into_a_score(tmp_path) -> None:
    """An unmeasured side stays `not_measured` and cannot decide a regression."""

    store = BenchmarkStore(tmp_path / "unmeasured")
    first = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))
    unscored = replace(_with_unscored_case(first), run_id="run-unscored")
    store.record_run(unscored)

    report = build_report(unscored, store=store, environment=_environment(), previous=first)
    ratio = _comparison(report, "pass_ratio")
    assert ratio.status == "not_measured"
    assert ratio.delta is None
    # An undecided metric never flips the regression flag on its own.
    assert all(
        comparison.status != "regressed"
        for comparison in report.comparisons
        if comparison.metric == "pass_ratio"
    )

    # A comparison across a different suite version is not a comparison at all,
    # even when both runs are genuinely retained.
    version = store.save_suite(SUITE_NAME, scheduled_cases(), lane="ci")
    other_version = replace(first, suite_version=version, run_id="run-other-version")
    store.record_run(other_version)
    across = build_report(first, store=store, environment=_environment(), previous=other_version)
    assert across.previous_run_id is None
    assert across.previous_run_fingerprint is None
    assert {comparison.status for comparison in across.comparisons} == {"no_baseline"}


def _check_report_is_deterministic_and_evaluation_only(tmp_path) -> None:
    """The same inputs and environment reproduce the same report structure."""

    store = BenchmarkStore(tmp_path / "deterministic")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))

    first = build_report(run, store=store, environment=_environment(), previous=None)
    second = build_report(run, store=store, environment=_environment(), previous=None)
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


def _totals() -> dict:
    # One passed, three failed: a coherent summary whose derived metrics are
    # quality_mean 0.25, baseline_quality_mean 1.0 and pass_ratio 0.25.
    return {
        "total": 4,
        "scored": 4,
        "passed": 1,
        "failed": 3,
        "unscored": 0,
        "errors": 0,
        "quality_mean": 0.25,
        "baseline_quality_mean": 1.0,
    }


def _full_comparisons() -> tuple[MetricComparison, ...]:
    return (
        MetricComparison("quality_mean", "regressed", 0.25, 0.9, -0.65),
        MetricComparison("baseline_quality_mean", "unchanged", 1.0, 1.0, 0.0),
        MetricComparison("pass_ratio", "unchanged", 0.25, 0.25, 0.0),
    )


def _build_report(**overrides) -> RegressionReport:
    fields = {
        "suite_name": SUITE_NAME,
        "suite_version": 1,
        "run_id": "run-one",
        "source_revision": _REVISION,
        "candidate_id": CANDIDATE_ID,
        "baseline_id": BASELINE_ID,
        "environment": _environment(),
        "totals": _totals(),
        "comparisons": _full_comparisons(),
        "previous_run_id": "run-zero",
        "regressed": True,
        "run_fingerprint": "c" * 64,
        "previous_run_fingerprint": "e" * 64,
        "guard": _REPORT_GUARD,
    }
    fields.update(overrides)
    return RegressionReport(**fields)


def _check_report_invariants_reject_incoherent_summaries() -> None:
    """A report cannot understate a regression or invent a comparison."""

    _build_report()
    with pytest.raises(ValueError, match="regression flag must match"):
        _build_report(regressed=False)
    with pytest.raises(ValueError, match="requires a previous run"):
        _build_report(previous_run_id=None, previous_run_fingerprint=None)
    with pytest.raises(ValueError, match="EnvironmentProfile"):
        _build_report(environment={"runner_id": "spoofed"})

    # A decided comparison cannot be asserted without both values.
    with pytest.raises(ValueError, match="requires both values"):
        MetricComparison(metric="quality_mean", status="regressed", current=0.5)
    with pytest.raises(ValueError, match="cannot carry a delta"):
        MetricComparison(metric="quality_mean", status="not_measured", delta=0.1)


def _check_report_cannot_claim_a_bad_revision_or_hardware() -> None:
    """Direct construction cannot serialize non-exact or hardware evidence."""

    for value in ("latest", "HEAD", _REVISION[:39], _REVISION.upper(), "main"):
        with pytest.raises(ValueError, match="source revision is invalid"):
            _build_report(source_revision=value)

    # The hardware profile is structurally fixed: it is not an init field, so an
    # owner-hardware claim cannot enter through construction or replace().
    profile = _environment()
    assert profile.hardware_profile == "not_measured"
    with pytest.raises(TypeError):
        EnvironmentProfile(
            runner_id="r",
            platform="p",
            python_version="3.12.0",
            hardware_profile="ryzen-9-7950x",  # type: ignore[call-arg]
        )
    with pytest.raises((TypeError, ValueError)):
        replace(profile, hardware_profile="ryzen-9-7950x")
    assert json.loads(_build_report().to_json())["environment"][
        "hardware_profile"
    ] == "not_measured"


def _check_comparison_semantics_cannot_be_self_asserted() -> None:
    """Status, delta and the metric set are verified, not trusted."""

    # An inverted delta cannot wear the opposite label.
    with pytest.raises(ValueError, match="regression requires a negative delta"):
        MetricComparison("quality_mean", "regressed", 0.9, 0.5, 0.4)
    with pytest.raises(ValueError, match="improvement requires a positive delta"):
        MetricComparison("quality_mean", "improved", 0.5, 0.9, -0.4)
    with pytest.raises(ValueError, match="unchanged comparison requires a zero delta"):
        MetricComparison("quality_mean", "unchanged", 0.5, 0.9, -0.4)

    # A delta that does not equal current minus previous is rejected.
    with pytest.raises(ValueError, match="delta must equal current minus previous"):
        MetricComparison("quality_mean", "regressed", 0.5, 0.9, -0.01)
    with pytest.raises(ValueError, match="delta must equal current minus previous"):
        MetricComparison("quality_mean", "regressed", 0.5, 0.9, None)

    # Unknown statuses and unknown metrics are refused.
    with pytest.raises(ValueError, match="status is not recognized"):
        MetricComparison("quality_mean", "looks_fine", 0.5, 0.9, -0.4)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not a compared E9.1 metric"):
        MetricComparison("invented_metric", "unchanged", 1.0, 1.0, 0.0)

    # Undecided statuses cannot smuggle a fully measured pair or a baseline.
    with pytest.raises(ValueError, match="requires an unmeasured side"):
        MetricComparison("quality_mean", "not_measured", 1.0, 1.0)
    with pytest.raises(ValueError, match="cannot carry a previous value"):
        MetricComparison("quality_mean", "no_baseline", 1.0, 1.0)

    # Non-finite and non-numeric values are refused.
    with pytest.raises(ValueError, match="must be finite"):
        MetricComparison("quality_mean", "not_measured", float("nan"))
    with pytest.raises(ValueError, match="must be numeric"):
        MetricComparison("quality_mean", "not_measured", True)

    # A report must carry every compared metric exactly once, in order, so a
    # regressed metric cannot be hidden by omission or duplication.
    full = _full_comparisons()
    for broken in (
        full[:2],
        (*full, full[0]),
        (full[1], full[0], full[2]),
        (full[0], full[0], full[0]),
    ):
        with pytest.raises(ValueError, match="each compared metric exactly once"):
            _build_report(comparisons=broken)
    with pytest.raises(ValueError, match="must be MetricComparison"):
        _build_report(comparisons=(full[0], full[1], {"metric": "pass_ratio"}))

    # A report that names a previous run cannot claim it had no baseline.
    derived = {"quality_mean": 0.25, "baseline_quality_mean": 1.0, "pass_ratio": 0.25}
    no_baseline = tuple(
        MetricComparison(metric, "no_baseline", derived[metric])
        for metric in _COMPARED_METRICS
    )
    with pytest.raises(ValueError, match="cannot yield only no_baseline"):
        _build_report(comparisons=no_baseline, regressed=False)


def _check_totals_semantics_and_comparison_agreement() -> None:
    """Impossible counts and summary-contradicting comparisons are refused."""

    for broken, expected in (
        ({**_totals(), "passed": 2}, "outcomes must sum to the case total"),
        ({**_totals(), "total": 0, "passed": 0, "failed": 0}, "at least one case"),
        ({**_totals(), "scored": 9}, "scored cannot exceed the case total"),
        ({**_totals(), "failed": -3, "passed": 7}, "cannot be negative"),
        ({**_totals(), "scored": 2}, "scored must equal passed plus failed"),
        (
            {**_totals(), "passed": 3, "failed": 1, "scored": 2},
            "scored must equal passed plus failed",
        ),
        ({**_totals(), "total": 4.0}, "must be an integer"),
        ({**_totals(), "errors": True, "failed": 2}, "must be an integer"),
        ({**_totals(), "quality_mean": 1.5}, "must be a ratio"),
        ({**_totals(), "quality_mean": float("inf")}, "must be finite"),
        ({**_totals(), "quality_mean": "high"}, "must be numeric or null"),
        (
            {
                **_totals(),
                "scored": 0,
                "passed": 0,
                "failed": 0,
                "unscored": 4,
                "quality_mean": 0.25,
            },
            "cannot score an unscored run",
        ),
    ):
        with pytest.raises(ValueError, match=expected):
            _build_report(totals=broken)

    # A comparison cannot publish a current value its own totals contradict.
    tampered = (
        MetricComparison("quality_mean", "regressed", 0.9, 0.95, -0.05),
        *_full_comparisons()[1:],
    )
    with pytest.raises(ValueError, match="contradicts the retained totals"):
        _build_report(comparisons=tampered, regressed=True)

    # The same applies to the derived pass ratio.
    tampered_ratio = (
        *_full_comparisons()[:2],
        MetricComparison("pass_ratio", "unchanged", 1.0, 1.0, 0.0),
    )
    with pytest.raises(ValueError, match="contradicts the retained totals"):
        _build_report(comparisons=tampered_ratio)


def _check_report_is_bound_to_the_retained_run(tmp_path) -> None:
    """A report must be derived from, and provably match, one retained run."""

    store = BenchmarkStore(tmp_path / "bound")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))
    report = build_report(run, store=store, environment=_environment(), previous=None)

    # The honest path validates.
    validate_report_against_run(report, run)
    assert report.run_fingerprint == run_fingerprint(run)
    assert "guard" not in json.loads(report.to_json())

    # Direct construction without the guard is noncanonical, even when every
    # field is internally coherent.
    with pytest.raises(ValueError, match="derived from a retained run"):
        _build_report(guard=None)

    # A report cannot claim a run it does not describe, even with coherent
    # totals — every identity field is recomputed from the run.
    for changed, expected in (
        (replace(run, run_id="run-invented"), "run_id does not match"),
        (replace(run, candidate_id="other-router"), "candidate_id does not match"),
        (replace(run, source_revision=_OTHER_REVISION), "source_revision does not"),
        (replace(run, suite_name="other-suite"), "suite_name does not match"),
        (replace(run, suite_version=run.suite_version + 1), "suite_version does not"),
    ):
        with pytest.raises(ValueError, match=expected):
            validate_report_against_run(report, changed)

    # A fingerprint that does not belong to the run is caught even when every
    # identity field agrees.
    unbound = build_report(run, store=store, environment=_environment(), previous=None)
    with pytest.raises(ValueError, match="not bound to the retained run"):
        validate_report_against_run(
            _build_report(
                suite_name=run.suite_name,
                suite_version=run.suite_version,
                run_id=run.run_id,
                source_revision=run.source_revision,
                candidate_id=run.candidate_id,
                baseline_id=run.baseline_id,
                totals=dict(unbound.totals),
                comparisons=unbound.comparisons,
                previous_run_id=None,
                previous_run_fingerprint=None,
                regressed=False,
                run_fingerprint="d" * 64,
            ),
            run,
        )

    # Malformed identifiers and fingerprints are refused outright.
    with pytest.raises(ValueError, match="report identity is invalid"):
        _build_report(run_id="not a valid id")
    with pytest.raises(ValueError, match="report identity is invalid"):
        _build_report(candidate_id="UPPER CASE")
    with pytest.raises(ValueError, match="run_fingerprint must be a SHA-256"):
        _build_report(run_fingerprint="short")
    with pytest.raises(ValueError, match="cannot compare a run against itself"):
        _build_report(previous_run_id="run-one", run_id="run-one")
    # A predecessor and its fingerprint are inseparable in both directions.
    with pytest.raises(ValueError, match="requires its fingerprint"):
        _build_report(previous_run_fingerprint=None)
    with pytest.raises(ValueError, match="requires its fingerprint"):
        _build_report(previous_run_id=None)
    with pytest.raises(ValueError, match="cannot compare a run against itself"):
        _build_report(previous_run_fingerprint="c" * 64)


def _check_unretained_evidence_cannot_become_canonical(tmp_path) -> None:
    """Only runs actually retained in the accepted store may be reported."""

    store = BenchmarkStore(tmp_path / "retention")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))

    # A synthetic in-memory run that was never recorded is not evidence.
    synthetic = replace(run, run_id="run-never-recorded")
    with pytest.raises(ValueError, match="run retained in the benchmark store"):
        build_report(synthetic, store=store, environment=_environment(), previous=None)

    # The same applies to a predecessor supplied for the comparison.
    with pytest.raises(ValueError, match="predecessor retained in the benchmark store"):
        build_report(run, store=store, environment=_environment(), previous=synthetic)

    # An empty store cannot back any report at all.
    empty = BenchmarkStore(tmp_path / "retention-empty")
    with pytest.raises(ValueError, match="run retained in the benchmark store"):
        build_report(run, store=empty, environment=_environment(), previous=None)

    # Once retained, the very same run is canonical and binds to its predecessor.
    store.record_run(synthetic)
    report = build_report(
        synthetic, store=store, environment=_environment(), previous=run
    )
    assert report.previous_run_fingerprint == run_fingerprint(run)
    validate_report_against_run(
        report, synthetic, previous=run, environment=_environment()
    )

    # Binding rejects a substituted predecessor and a missing one.
    with pytest.raises(ValueError, match="previous_run_id does not match"):
        validate_report_against_run(report, synthetic, previous=synthetic)
    with pytest.raises(ValueError, match="claims a predecessor that was not supplied"):
        validate_report_against_run(report, synthetic)

    # A predecessor keeping the same run id but different content is caught by
    # the fingerprint, not just the identifier.
    impostor = replace(run, source_revision=_OTHER_REVISION)
    assert impostor.run_id == run.run_id
    with pytest.raises(ValueError, match="not bound to the retained predecessor"):
        validate_report_against_run(report, synthetic, previous=impostor)


def _check_environment_is_detected_bounded_and_validated(tmp_path) -> None:
    """Environment evidence is produced by detect(), bounded, and verified."""

    # A caller cannot assert an environment; only detect() may produce one.
    with pytest.raises(ValueError, match="produced by EnvironmentProfile.detect"):
        EnvironmentProfile(
            runner_id="spoofed",
            platform="linux-x86_64",
            python_version="3.12.0",
        )
    with pytest.raises((TypeError, ValueError)):
        replace(_environment(), runner_id="spoofed")

    # The one caller-supplied label is bounded: single line, printable, trimmed.
    for bad in (
        "runner\nplatform: owner-workstation",
        "runner\rid",
        "runner\tid",
        "  padded  ",
        "x" * 129,
        "",
        "   ",
        "runner\x00id",
    ):
        with pytest.raises(ValueError, match="environment runner_id"):
            EnvironmentProfile.detect(runner_id=bad)

    # Platform and interpreter are read from the process, not accepted.
    detected = EnvironmentProfile.detect(runner_id="test-runner")
    assert detected.hardware_profile == "not_measured"
    assert "guard" not in detected.canonical_payload()

    # The exact environment record is validated alongside the run evidence.
    store = BenchmarkStore(tmp_path / "environment")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))
    report = build_report(run, store=store, environment=detected, previous=None)
    validate_report_against_run(report, run, environment=detected)
    with pytest.raises(ValueError, match="environment does not match"):
        validate_report_against_run(
            report, run, environment=EnvironmentProfile.detect(runner_id="other-runner")
        )


def _check_baseline_identity_matches_baseline_evidence() -> None:
    """Measured baseline evidence and a declared baseline identity travel together."""

    with pytest.raises(ValueError, match="requires a declared baseline identity"):
        _build_report(baseline_id=None)

    # The rule is one-way on purpose. A declared baseline whose evidence failed
    # or was skipped is a legal E9.0 run, and it must still produce a report.
    no_baseline_totals = {**_totals(), "baseline_quality_mean": None}
    coherent = (
        MetricComparison("quality_mean", "regressed", 0.25, 0.9, -0.65),
        MetricComparison("baseline_quality_mean", "not_measured", None, 1.0),
        MetricComparison("pass_ratio", "unchanged", 0.25, 0.25, 0.0),
    )
    accepted = _build_report(
        totals=no_baseline_totals,
        baseline_id=BASELINE_ID,
        comparisons=coherent,
    )
    assert accepted.baseline_id == BASELINE_ID
    assert accepted.totals["baseline_quality_mean"] is None


def _check_legal_baseline_failure_states_still_report(tmp_path, monkeypatch) -> None:
    """A failed or skipped baseline is retained AND reported, never raised on."""

    import agents.core.observability.scheduled_report as module

    # (a) every baseline invocation fails: the run is valid, baseline evidence is
    # failed, and baseline_quality_mean is None.
    class _FailingBaseline:
        async def __call__(self, prompt: str) -> BenchmarkObservation:
            raise RuntimeError("baseline unavailable")

    # Patches are scoped so later assertions still exercise the real runner.
    with monkeypatch.context() as patched:
        patched.setattr(
            module, "KeywordRouteBaseline", lambda rules: _FailingBaseline()
        )
        store = BenchmarkStore(tmp_path / "baseline-failed")
        run = asyncio.run(
            run_scheduled_suite(store, revision=_REVISION, run_id="run-bf")
        )
        assert run.baseline_id == BASELINE_ID
        assert run.summary["baseline_quality_mean"] is None
        assert store.runs(SUITE_NAME, last_n=5)

        report = build_report(
            run, store=store, environment=_environment(), previous=None
        )
        assert _comparison(report, "baseline_quality_mean").status == "no_baseline"
        assert report.regressed is False
        # The candidate side is still honestly measured and visible.
        assert report.totals["scored"] == report.totals["total"]

    # (b) every candidate invocation errors, so the baseline is honestly skipped.
    def _erroring_runner(router, agents, *, host_id="in-process"):
        async def run_case(prompt: str) -> BenchmarkObservation:
            raise RuntimeError("candidate unavailable")

        return run_case

    with monkeypatch.context() as patched:
        patched.setattr(module, "current_router_runner", _erroring_runner)
        errored_store = BenchmarkStore(tmp_path / "candidate-errored")
        errored = asyncio.run(
            run_scheduled_suite(errored_store, revision=_REVISION, run_id="run-ce")
        )
        assert errored.summary["errors"] == errored.summary["total"]
        assert errored.summary["quality_mean"] is None
        assert errored.summary["baseline_quality_mean"] is None
        assert errored_store.runs(SUITE_NAME, last_n=5)

        errored_report = build_report(
            errored, store=errored_store, environment=_environment(), previous=None
        )
        # Nothing is fabricated: no pass, no regression, everything undecided.
        assert errored_report.regressed is False
        assert {item.status for item in errored_report.comparisons} == {"no_baseline"}
        assert "not_measured" in errored_report.to_markdown()


def _check_json_report_is_replaced_not_appended(tmp_path) -> None:
    """Repeated runs leave one parseable document, not concatenated objects."""

    store_root = tmp_path / "json-out"
    summary = tmp_path / "json-out-summary.md"
    json_out = tmp_path / "json-out-report.json"

    for revision in (_REVISION, _OTHER_REVISION):
        assert (
            main(
                [
                    "--store-root",
                    str(store_root),
                    "--summary",
                    str(summary),
                    "--json-out",
                    str(json_out),
                    "--revision",
                    revision,
                ]
            )
            == 0
        )

    # The artifact still parses as a single report document after two runs.
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema"] == "nerva.benchmark.report.v1"
    # It describes the most recent run, not the first.
    assert payload["source_revision"] == _OTHER_REVISION
    assert not list(json_out.parent.glob("*.tmp"))

    # The step summary is a running log and legitimately keeps both entries.
    assert summary.read_text(encoding="utf-8").count("scheduled shadow report") == 2


def _check_comparison_requires_matching_evaluator_identities(tmp_path) -> None:
    """A prior run from different evaluators is not a baseline."""

    store = BenchmarkStore(tmp_path / "identities")
    run = asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-one"))
    prior = replace(run, run_id="run-prior")
    store.record_run(prior)

    # The control: identical identities do compare, and the report binds to the
    # exact retained predecessor.
    same = build_report(run, store=store, environment=_environment(), previous=prior)
    assert same.previous_run_id == "run-prior"
    assert same.previous_run_fingerprint == run_fingerprint(prior)

    # A different candidate or baseline identity measures something else, so it
    # must degrade to no_baseline rather than manufacture a decided result —
    # even though both runs are genuinely retained.
    for index, changed in enumerate(
        (
            replace(prior, candidate_id="other-router", run_id="run-other-candidate"),
            replace(prior, baseline_id="other-baseline.v1", run_id="run-other-base"),
        )
    ):
        store.record_run(changed)
        report = build_report(run, store=store, environment=_environment(), previous=changed)
        assert report.previous_run_id is None
        assert report.previous_run_fingerprint is None
        assert report.regressed is False
        assert {item.status for item in report.comparisons} == {"no_baseline"}
        assert index >= 0


def _check_totals_are_frozen_after_construction() -> None:
    """Mutating the retained summary cannot change later evidence."""

    supplied = _totals()
    report = _build_report(totals=supplied)
    before_json = report.to_json()
    before_markdown = report.to_markdown()

    # The caller's dict is copied, so mutating it afterwards changes nothing.
    supplied["passed"] = 0
    assert report.to_json() == before_json

    # The retained mapping itself refuses mutation.
    with pytest.raises(TypeError):
        report.totals["passed"] = 0  # type: ignore[index]
    with pytest.raises(AttributeError):
        report.totals.clear()  # type: ignore[attr-defined]
    assert report.to_json() == before_json
    assert report.to_markdown() == before_markdown
    assert json.loads(report.to_json())["totals"]["passed"] == 1

    # The summary key set is verified rather than accepted as given.
    with pytest.raises(ValueError, match="totals must match the benchmark summary"):
        _build_report(totals={"total": 4})
    with pytest.raises(ValueError, match="totals must match the benchmark summary"):
        _build_report(totals={**_totals(), "smuggled": 1})
    with pytest.raises(ValueError, match="totals must be a mapping"):
        _build_report(totals=[("total", 4)])


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

    # An unresolvable revision is equally a visible failure. The revision is
    # never discovered by shelling out, only supplied explicitly or by env.
    monkeypatch.setattr(module, "missing_prerequisites", lambda: ())
    with pytest.raises(PrerequisiteError, match="cannot resolve source revision"):
        source_revision(None, env={})
    with pytest.raises(PrerequisiteError, match="cannot resolve source revision"):
        source_revision(None, env={"GITHUB_SHA": "   "})
    assert source_revision(None, env={"GITHUB_SHA": _REVISION}) == _REVISION
    assert (
        source_revision(None, env={"NERVA_SOURCE_REVISION": _REVISION})
        == _REVISION
    )
    # An explicit argument always wins over the environment.
    assert source_revision(_OTHER_REVISION, env={"GITHUB_SHA": _REVISION}) == (
        _OTHER_REVISION
    )
    # Whitespace padding is stripped, not treated as a distinct revision.
    assert source_revision(f"  {_REVISION}  ", env={}) == _REVISION


def _check_revision_must_be_an_exact_commit_sha(tmp_path) -> None:
    """A symbolic, malformed or truncated revision is never serialized."""

    for value in (
        "latest",
        "HEAD",
        "main",
        "refs/heads/main",
        _REVISION[:39],
        _REVISION + "a",
        _REVISION.upper(),
        "z" * 40,
        "a" * 41,
    ):
        with pytest.raises(PrerequisiteError, match="not an exact commit SHA"):
            source_revision(value, env={})
        # The environment path is validated identically.
        with pytest.raises(PrerequisiteError, match="not an exact commit SHA"):
            source_revision(None, env={"GITHUB_SHA": value})

    # A 64-character digest is also an accepted exact revision.
    assert source_revision("b" * 64, env={}) == "b" * 64

    # A direct caller cannot bypass the format either, and the CLI turns it
    # into the honest FAILED path rather than an unhandled traceback.
    store_root = tmp_path / "bad-revision"
    with pytest.raises(PrerequisiteError, match="not an exact commit SHA"):
        asyncio.run(run_scheduled_suite(BenchmarkStore(store_root), revision="latest"))

    summary = tmp_path / "bad-revision-summary.md"
    assert (
        main(
            [
                "--store-root",
                str(store_root),
                "--summary",
                str(summary),
                "--revision",
                "latest",
            ]
        )
        == 2
    )
    text = summary.read_text(encoding="utf-8")
    assert "FAILED" in text
    assert "not an exact commit SHA" in text
    assert BenchmarkStore(store_root).runs(SUITE_NAME, last_n=5) == ()


def _check_regressed_run_is_retained_but_not_promoted(tmp_path, monkeypatch) -> None:
    """A regression keeps its evidence; only baseline promotion is withheld."""

    import agents.core.observability.scheduled_report as module

    store_root = tmp_path / "regressed"
    store = BenchmarkStore(store_root)
    asyncio.run(run_scheduled_suite(store, revision=_REVISION, run_id="run-prior"))

    # Force a genuine regression by degrading the candidate itself, so the
    # retained totals and the reported comparison stay mutually consistent.
    # Fabricating metrics here would be exactly the self-assertion the report
    # contract now refuses.
    def _mis_routing_runner(router, agents, *, host_id="in-process"):
        async def run(prompt: str) -> BenchmarkObservation:
            return BenchmarkObservation(
                response="jarvis",
                route_id="jarvis",
                model_id="none",
                provider_id="local-deterministic",
                host_id=host_id,
                hardware_profile="not-measured",
                cost_usd=0.0,
                reliability=1.0,
                privacy_effect="no_external_disclosure",
            )

        return run

    monkeypatch.setattr(module, "current_router_runner", _mis_routing_runner)

    summary = tmp_path / "regressed-summary.md"
    json_out = tmp_path / "regressed-report.json"
    exit_code = main(
        [
            "--store-root",
            str(store_root),
            "--summary",
            str(summary),
            "--json-out",
            str(json_out),
            "--revision",
            _OTHER_REVISION,
            "--fail-on-regression",
        ]
    )

    # The gate fails, as it must.
    assert exit_code == 1

    # The negative evidence survives the failure: the run is retained in the
    # accepted store and the report is written, both before the non-zero exit.
    retained = BenchmarkStore(store_root).runs(SUITE_NAME, last_n=5)
    assert len(retained) == 2
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["regressed"] is True
    assert payload["previous_run_id"] == "run-prior"
    assert "regressed" in summary.read_text(encoding="utf-8")

    # Without the flag the same regression is reported but not enforced.
    assert (
        main(
            [
                "--store-root",
                str(store_root),
                "--summary",
                str(summary),
                "--revision",
                _OTHER_REVISION,
            ]
        )
        == 0
    )


def _check_workflow_separates_retention_from_promotion() -> None:
    """Evidence upload runs always; baseline promotion stays gated on success."""

    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "eval-nightly.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["nerva-router-shadow"]["steps"]
    by_name = {step.get("name"): step for step in steps}

    upload = by_name["Upload scheduled shadow evidence"]
    assert "always()" in upload["if"]
    assert "success()" not in upload["if"]

    save = by_name["Save scheduled shadow baseline"]
    assert "success()" in save["if"]
    assert "pull_request" in save["if"]

    # Least privilege is declared on the job itself.
    assert workflow["jobs"]["nerva-router-shadow"]["permissions"] == {
        "contents": "read"
    }


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
    _check_report_cannot_claim_a_bad_revision_or_hardware()
    _check_comparison_semantics_cannot_be_self_asserted()
    _check_totals_are_frozen_after_construction()
    _check_totals_semantics_and_comparison_agreement()
    _check_report_is_bound_to_the_retained_run(tmp_path)
    _check_unretained_evidence_cannot_become_canonical(tmp_path)
    _check_environment_is_detected_bounded_and_validated(tmp_path)
    _check_baseline_identity_matches_baseline_evidence()
    _check_legal_baseline_failure_states_still_report(tmp_path, monkeypatch)
    _check_json_report_is_replaced_not_appended(tmp_path)
    _check_comparison_requires_matching_evaluator_identities(tmp_path)
    _check_missing_prerequisites_fail_visibly(tmp_path, monkeypatch)
    _check_revision_must_be_an_exact_commit_sha(tmp_path)
    _check_regressed_run_is_retained_but_not_promoted(tmp_path, monkeypatch)
    _check_workflow_separates_retention_from_promotion()
    _check_cli_reports_without_changing_routing(tmp_path)
