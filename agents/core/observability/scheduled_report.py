"""E9.1 scheduled current-router shadow comparison and regression report.

One bounded synthetic-public suite runs through the repository's existing
scheduled evaluation lane, persists evidence through the accepted E9.0
``BenchmarkStore``, and emits a deterministic regression summary.

The package is ``evaluation_only``. It cannot change production routing,
authorize or execute anything, promote a capability, or mark work complete.
Only metrics that were genuinely measured on both sides participate in a
regression decision; everything else keeps an explicit unmeasured state.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from agents.core.observability.benchmark import (
    BenchmarkCase,
    BenchmarkCriterion,
    BenchmarkHarness,
    BenchmarkRun,
    BenchmarkStore,
    KeywordRouteBaseline,
    current_router_runner,
)
from agents.core.observability.benchmark import (
    # Single source of truth for the repository's accepted identifier formats.
    # Validating here keeps a malformed value on the honest PrerequisiteError
    # path instead of surfacing as an unhandled ValueError deep in the harness.
    _identifier as _validate_identifier,
)
from agents.core.observability.benchmark import (
    _source_revision as _validate_exact_revision,
)
from agents.core.observability.benchmark import (
    _suite_name as _validate_suite_name,
)
from agents.core.observability.benchmark import (
    _version as _validate_version,
)

SUITE_NAME = "nerva-router-shadow"
CANDIDATE_ID = "current-router"
BASELINE_ID = "keyword-baseline.v1"

ComparisonStatus = Literal[
    "improved",
    "regressed",
    "unchanged",
    "not_measured",
    "no_baseline",
]

# Higher is better for every metric compared here. A metric whose direction is
# not established is not compared at all rather than guessed.
_COMPARED_METRICS = ("quality_mean", "baseline_quality_mean", "pass_ratio")
_REGRESSION_EPSILON = 1e-9
_COMPARISON_STATUSES = frozenset(
    {"improved", "regressed", "unchanged", "not_measured", "no_baseline"}
)

#: E9.1 measures no hardware; the profile is fixed rather than caller-supplied.
HARDWARE_PROFILE = "not_measured"

# Module-private construction guard. A report is canonical only when derived
# from a retained BenchmarkRun through build_report().
_REPORT_GUARD = object()

_SHA256_HEX_LENGTH = 64

#: The exact key set a retained ``BenchmarkRun.summary`` must provide.
_TOTALS_KEYS = frozenset(
    {
        "total",
        "scored",
        "passed",
        "failed",
        "unscored",
        "errors",
        "quality_mean",
        "baseline_quality_mean",
    }
)

_BASELINE_RULES = {
    "weather": "friday",
    "calendar": "pepper",
}


def scheduled_cases() -> tuple[BenchmarkCase, ...]:
    """The versioned synthetic-public suite. No owner or sanitized data."""

    return (
        BenchmarkCase(
            "route-weather",
            "route-selection",
            "what is the weather tomorrow",
            "synthetic_public",
            ("ci",),
            BenchmarkCriterion("exact", "friday"),
        ),
        BenchmarkCase(
            "route-calendar",
            "route-selection",
            "add a calendar entry for the standup",
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
        BenchmarkCase(
            "route-ambiguous",
            "route-selection",
            "remind me about the weather during my calendar block",
            "synthetic_public",
            ("ci",),
            BenchmarkCriterion("exact", "friday"),
        ),
    )


@dataclass(frozen=True)
class EnvironmentProfile:
    """Runner identity and environment, with unknowns left explicitly unknown."""

    runner_id: str
    platform: str
    python_version: str
    # E9.1 measures no hardware. The field is ``init=False`` so an owner-hardware
    # claim cannot be introduced through this contract at all — not by direct
    # construction and not through ``dataclasses.replace``.
    hardware_profile: str = field(default=HARDWARE_PROFILE, init=False)
    schema: str = field(default="nerva.benchmark.environment.v1", init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.runner_id, "runner_id"),
            (self.platform, "platform"),
            (self.python_version, "python_version"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"environment {name} must be a non-empty string")
        if self.hardware_profile != HARDWARE_PROFILE:
            raise ValueError("E9.1 hardware profile must remain not_measured")

    @classmethod
    def detect(cls, *, runner_id: str) -> EnvironmentProfile:
        # Hardware performance is never inferred from a shared CI runner.
        return cls(
            runner_id=runner_id,
            platform=f"{platform.system()}-{platform.machine()}".lower(),
            python_version=platform.python_version(),
        )


@dataclass(frozen=True)
class MetricComparison:
    """One metric compared against the previous retained run."""

    metric: str
    status: ComparisonStatus
    current: float | None = None
    previous: float | None = None
    delta: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric, str) or self.metric not in _COMPARED_METRICS:
            raise ValueError("comparison metric is not a compared E9.1 metric")
        if self.status not in _COMPARISON_STATUSES:
            raise ValueError("comparison status is not recognized")
        for value, name in (
            (self.current, "current"),
            (self.previous, "previous"),
            (self.delta, "delta"),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"comparison {name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"comparison {name} must be finite")

        if self.status in {"not_measured", "no_baseline"}:
            if self.delta is not None:
                raise ValueError("an undecided comparison cannot carry a delta")
            if self.status == "no_baseline" and self.previous is not None:
                raise ValueError("a no_baseline comparison cannot carry a previous value")
            if self.status == "not_measured" and (
                self.current is not None and self.previous is not None
            ):
                raise ValueError(
                    "a not_measured comparison requires an unmeasured side"
                )
            return

        # Decided comparisons must be internally consistent: the delta is
        # recomputed and the label must match its sign, so a positive delta
        # cannot be published as a regression.
        if self.current is None or self.previous is None:
            raise ValueError("a decided comparison requires both values")
        expected = round(float(self.current) - float(self.previous), 6)
        if self.delta is None or abs(float(self.delta) - expected) > _REGRESSION_EPSILON:
            raise ValueError("comparison delta must equal current minus previous")
        if self.status == "regressed" and expected >= -_REGRESSION_EPSILON:
            raise ValueError("a regression requires a negative delta")
        if self.status == "improved" and expected <= _REGRESSION_EPSILON:
            raise ValueError("an improvement requires a positive delta")
        if self.status == "unchanged" and abs(expected) > _REGRESSION_EPSILON:
            raise ValueError("an unchanged comparison requires a zero delta")


@dataclass(frozen=True)
class RegressionReport:
    """Deterministic ``nerva.benchmark.report.v1`` scheduled-run summary."""

    suite_name: str
    suite_version: int
    run_id: str
    source_revision: str
    candidate_id: str
    baseline_id: str | None
    environment: EnvironmentProfile
    totals: dict[str, Any]
    comparisons: tuple[MetricComparison, ...]
    previous_run_id: str | None
    regressed: bool
    #: SHA-256 of the canonical JSON of the retained run this report summarizes.
    run_fingerprint: str = ""
    guard: Any = field(default=None, compare=False, repr=False)
    schema: str = field(default="nerva.benchmark.report.v1", init=False)
    authority: str = field(default="evaluation_only", init=False)
    can_change_routing: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_promote_capability: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        # A report is only canonical when it was derived from a retained run.
        # ``build_report()`` holds the guard; direct construction cannot forge
        # a run identity and present it as nerva.benchmark.report.v1.
        if self.guard is not _REPORT_GUARD:
            raise ValueError(
                "a report must be derived from a retained run through build_report"
            )
        if not isinstance(self.environment, EnvironmentProfile):
            raise ValueError("report requires an EnvironmentProfile")
        # A report is exact evidence; its identifiers are held to the same
        # formats as the run it describes.
        try:
            _validate_exact_revision(self.source_revision)
        except ValueError as exc:
            raise ValueError(f"report source revision is invalid: {exc}") from exc
        try:
            _validate_suite_name(self.suite_name)
            _validate_version(self.suite_version)
            _validate_identifier(self.run_id, "run id")
            _validate_identifier(self.candidate_id, "candidate id")
            if self.baseline_id is not None:
                _validate_identifier(self.baseline_id, "baseline id")
            if self.previous_run_id is not None:
                _validate_identifier(self.previous_run_id, "previous run id")
        except ValueError as exc:
            raise ValueError(f"report identity is invalid: {exc}") from exc
        _validate_sha256(self.run_fingerprint, "run_fingerprint")

        if not isinstance(self.comparisons, tuple):
            raise ValueError("report comparisons must be an immutable tuple")
        for comparison in self.comparisons:
            if not isinstance(comparison, MetricComparison):
                raise ValueError("report comparisons must be MetricComparison")
        metrics = [comparison.metric for comparison in self.comparisons]
        # The exact metric set must be present exactly once, in a deterministic
        # order, so a caller cannot hide a regressed metric by omitting it.
        if tuple(metrics) != _COMPARED_METRICS:
            raise ValueError(
                "report must carry each compared metric exactly once, in order"
            )

        if not isinstance(self.totals, Mapping):
            raise ValueError("report totals must be a mapping")
        _validate_totals(self.totals)
        # Freeze the retained summary so post-construction mutation cannot
        # change later JSON or Markdown evidence.
        object.__setattr__(self, "totals", MappingProxyType(dict(self.totals)))

        # Each comparison's current value is derived from the retained summary,
        # so a report cannot publish a current value its own totals contradict.
        expected_current = _metrics_from_totals(self.totals)
        for comparison in self.comparisons:
            wanted = expected_current[comparison.metric]
            if comparison.current != wanted:
                raise ValueError(
                    f"comparison {comparison.metric} contradicts the retained totals"
                )

        # Measured baseline evidence requires a declared baseline identity, the
        # same rule the accepted BenchmarkRun contract enforces.
        if self.totals["baseline_quality_mean"] is not None and self.baseline_id is None:
            raise ValueError(
                "measured baseline evidence requires a declared baseline identity"
            )
        if self.totals["baseline_quality_mean"] is None and self.baseline_id is not None:
            raise ValueError(
                "a declared baseline identity requires measured baseline evidence"
            )

        decided = [
            comparison
            for comparison in self.comparisons
            if comparison.status == "regressed"
        ]
        if bool(decided) != self.regressed:
            raise ValueError("report regression flag must match its comparisons")
        if self.previous_run_id is None and any(
            comparison.status in {"improved", "regressed", "unchanged"}
            for comparison in self.comparisons
        ):
            raise ValueError("a decided comparison requires a previous run")
        if self.previous_run_id is not None and all(
            comparison.status == "no_baseline" for comparison in self.comparisons
        ):
            raise ValueError("a previous run cannot yield only no_baseline results")
        if self.previous_run_id == self.run_id:
            raise ValueError("a report cannot compare a run against itself")

        # The guard is a construction capability, never retained state.
        object.__setattr__(self, "guard", None)

    def to_dict(self) -> dict[str, Any]:
        # Built explicitly rather than through asdict() so the frozen totals
        # mapping is serialized from immutable state.
        return {
            "schema": self.schema,
            "authority": self.authority,
            "can_change_routing": self.can_change_routing,
            "can_authorize": self.can_authorize,
            "can_execute": self.can_execute,
            "can_promote_capability": self.can_promote_capability,
            "can_mark_complete": self.can_mark_complete,
            "suite_name": self.suite_name,
            "suite_version": self.suite_version,
            "run_id": self.run_id,
            "source_revision": self.source_revision,
            "candidate_id": self.candidate_id,
            "baseline_id": self.baseline_id,
            "environment": asdict(self.environment),
            "totals": dict(self.totals),
            "comparisons": [asdict(item) for item in self.comparisons],
            "previous_run_id": self.previous_run_id,
            "regressed": self.regressed,
            "run_fingerprint": self.run_fingerprint,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_markdown(self) -> str:
        title = (
            f"### Nerva E9.1 scheduled shadow report — "
            f"`{self.suite_name}` v{self.suite_version}"
        )
        identities = (
            f"- candidate: `{self.candidate_id}` · "
            f"baseline: `{self.baseline_id or 'none'}`"
        )
        runner = (
            f"- runner: `{self.environment.runner_id}` "
            f"({self.environment.platform}, py{self.environment.python_version})"
        )
        disclaimer = (
            "This report is evaluation-only. It does not change routing, "
            "promote a capability, or claim owner-hardware performance."
        )

        lines = [
            title,
            "",
            f"- run: `{self.run_id}` · revision: `{self.source_revision}`",
            identities,
            runner,
            f"- hardware profile: `{self.environment.hardware_profile}`",
            f"- previous run: `{self.previous_run_id or 'none'}`",
            "",
            "| metric | status | current | previous | delta |",
            "| --- | --- | --- | --- | --- |",
        ]
        for comparison in self.comparisons:
            row = (
                f"| {comparison.metric} | {comparison.status} "
                f"| {_render(comparison.current)} "
                f"| {_render(comparison.previous)} "
                f"| {_render(comparison.delta)} |"
            )
            lines.append(row)
        lines.append("")
        lines.append(f"Totals: {json.dumps(dict(self.totals), sort_keys=True)}")
        lines.append("")
        lines.append(disclaimer)
        return "\n".join(lines)


class PrerequisiteError(RuntimeError):
    """Raised when a declared prerequisite is missing.

    The scheduled job fails visibly instead of emitting a fabricated pass.
    """


def missing_prerequisites() -> tuple[str, ...]:
    """Return the declared prerequisites that are not satisfied."""

    missing: list[str] = []
    try:
        from agents.core.router import IntentRouter
    except Exception:  # pragma: no cover - import failure is the reported state
        return ("agents.core.router.IntentRouter",)
    try:
        router = IntentRouter(config={})
    except Exception:
        return ("agents.core.router.IntentRouter(config={})",)
    if not hasattr(router, "llm_classifier"):
        missing.append("IntentRouter.llm_classifier")
    elif router.llm_classifier is not None:
        missing.append("IntentRouter.llm_classifier is None (deterministic lane)")
    return tuple(missing)


#: Environment variables consulted, in order, when no revision is passed.
REVISION_ENV_VARS = ("NERVA_SOURCE_REVISION", "GITHUB_SHA")


def source_revision(
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Bind the report to an exact code revision, or fail honestly.

    The revision is supplied explicitly or through the environment. It is never
    discovered by shelling out: a report that cannot name its exact revision is
    not evidence, so the run fails rather than guessing.

    The value must be an exact lowercase commit SHA in the repository's accepted
    format. A symbolic name such as ``latest`` or a branch, and a truncated,
    over-length, uppercase or non-hex digest are refused rather than serialized
    as exact evidence. Surrounding whitespace is stripped first, so a padded but
    otherwise exact SHA is accepted and normalized.
    """

    candidate = (explicit or "").strip()
    if not candidate:
        source = os.environ if env is None else env
        for name in REVISION_ENV_VARS:
            value = (source.get(name) or "").strip()
            if value:
                candidate = value
                break
    if not candidate:
        raise PrerequisiteError(
            "cannot resolve source revision: pass --revision or set "
            + " or ".join(REVISION_ENV_VARS)
        )
    try:
        return _validate_exact_revision(candidate)
    except ValueError as exc:
        raise PrerequisiteError(
            f"source revision is not an exact commit SHA: {exc}"
        ) from exc


def ensure_suite(store: BenchmarkStore) -> int:
    """Return the stored version for the current cases, saving only on change.

    Re-running an unchanged suite must not create a new version, otherwise the
    regression history would compare across versions that never differed.
    """

    cases = scheduled_cases()
    versions = store.versions(SUITE_NAME)
    if versions:
        latest = versions[-1]
        stored = store.load_suite(SUITE_NAME, latest)
        if tuple(case.content_fingerprint for case in stored) == tuple(
            case.content_fingerprint for case in cases
        ):
            return latest
    return store.save_suite(SUITE_NAME, cases, lane="ci")


async def run_scheduled_suite(
    store: BenchmarkStore,
    *,
    revision: str,
    run_id: str | None = None,
) -> BenchmarkRun:
    """Execute one bounded shadow comparison and retain its evidence."""

    missing = missing_prerequisites()
    if missing:
        raise PrerequisiteError(
            "scheduled suite prerequisites are missing: " + ", ".join(missing)
        )
    # Defence in depth: a direct caller cannot bypass the exact-revision format.
    revision = source_revision(revision)

    from agents.core.router import IntentRouter

    version = ensure_suite(store)
    cases = store.load_suite(SUITE_NAME, version)
    agents = {"jarvis": object(), "friday": object(), "pepper": object()}
    harness = BenchmarkHarness(
        current_router_runner(IntentRouter(config={}), agents, host_id="ci-runner"),
        candidate_id=CANDIDATE_ID,
        baseline=KeywordRouteBaseline(_BASELINE_RULES),
        baseline_id=BASELINE_ID,
    )
    run = await harness.run(
        cases,
        suite_name=SUITE_NAME,
        suite_version=version,
        lane="ci",
        source_revision=revision,
        run_id=run_id,
    )
    # Negative, failed and unscored results are retained exactly as produced.
    store.record_run(run)
    return run


def _validate_totals(totals: Mapping[str, Any]) -> None:
    """Reject a summary that cannot describe a real benchmark run."""

    if set(totals) != _TOTALS_KEYS:
        raise ValueError("report totals must match the benchmark summary keys")
    counts = {}
    for name in ("total", "scored", "passed", "failed", "unscored", "errors"):
        value = totals[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"report totals {name} must be an integer")
        if value < 0:
            raise ValueError(f"report totals {name} cannot be negative")
        counts[name] = value
    if counts["total"] < 1:
        raise ValueError("report totals require at least one case")
    outcomes = (
        counts["passed"] + counts["failed"] + counts["unscored"] + counts["errors"]
    )
    if outcomes != counts["total"]:
        raise ValueError("report totals outcomes must sum to the case total")
    if counts["scored"] > counts["total"]:
        raise ValueError("report totals scored cannot exceed the case total")
    # Under the accepted BenchmarkResult contract a passed or failed result has
    # measured quality, while unscored and error results do not. A real
    # BenchmarkRun.summary therefore always satisfies this equality exactly.
    if counts["scored"] != counts["passed"] + counts["failed"]:
        raise ValueError("report totals scored must equal passed plus failed")

    for name in ("quality_mean", "baseline_quality_mean"):
        value = totals[name]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"report totals {name} must be numeric or null")
        if not math.isfinite(float(value)):
            raise ValueError(f"report totals {name} must be finite")
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"report totals {name} must be a ratio")
    if counts["scored"] == 0 and totals["quality_mean"] is not None:
        raise ValueError("report totals cannot score an unscored run")


def _metrics_from_totals(totals: Mapping[str, Any]) -> dict[str, float | None]:
    """The only comparable metrics a summary supports.

    Used both when building a report and when validating one, so a serialized
    comparison can never contradict the summary it is published with.
    """

    total = totals["total"]
    scored = totals["scored"]
    return {
        "quality_mean": totals["quality_mean"],
        "baseline_quality_mean": totals["baseline_quality_mean"],
        # Only a fully scored run yields a comparable pass ratio.
        "pass_ratio": (
            round(totals["passed"] / total, 6) if total and scored == total else None
        ),
    }


def _run_metrics(run: BenchmarkRun) -> dict[str, float | None]:
    return _metrics_from_totals(run.summary)


def build_report(
    run: BenchmarkRun,
    *,
    environment: EnvironmentProfile,
    previous: BenchmarkRun | None = None,
) -> RegressionReport:
    """Compare only genuinely measured metrics against the previous run."""

    current_metrics = _run_metrics(run)
    previous_metrics = _run_metrics(previous) if previous is not None else {}
    # Comparability requires the same suite content *and* the same evaluator
    # identities. A retained run for the same suite version produced by a
    # different candidate or baseline measures something else, so comparing it
    # would manufacture a regression out of an identity change.
    comparable = (
        previous is not None
        and previous.suite_name == run.suite_name
        and previous.suite_version == run.suite_version
        and previous.candidate_id == run.candidate_id
        and previous.baseline_id == run.baseline_id
    )

    comparisons: list[MetricComparison] = []
    for metric in _COMPARED_METRICS:
        current = current_metrics.get(metric)
        if not comparable:
            comparisons.append(
                MetricComparison(
                    metric=metric,
                    status="no_baseline",
                    current=current,
                )
            )
            continue
        prior = previous_metrics.get(metric)
        if current is None or prior is None:
            # An unmeasured side is never coerced into a score.
            comparisons.append(
                MetricComparison(
                    metric=metric,
                    status="not_measured",
                    current=current,
                    previous=prior,
                )
            )
            continue
        delta = round(current - prior, 6)
        if delta < -_REGRESSION_EPSILON:
            status: ComparisonStatus = "regressed"
        elif delta > _REGRESSION_EPSILON:
            status = "improved"
        else:
            status = "unchanged"
        comparisons.append(
            MetricComparison(
                metric=metric,
                status=status,
                current=current,
                previous=prior,
                delta=delta,
            )
        )

    return RegressionReport(
        suite_name=run.suite_name,
        suite_version=run.suite_version,
        run_id=run.run_id,
        source_revision=run.source_revision,
        candidate_id=run.candidate_id,
        baseline_id=run.baseline_id,
        environment=environment,
        totals=run.summary,
        comparisons=tuple(comparisons),
        previous_run_id=previous.run_id if comparable and previous else None,
        regressed=any(
            comparison.status == "regressed" for comparison in comparisons
        ),
        run_fingerprint=run_fingerprint(run),
        guard=_REPORT_GUARD,
    )


def previous_run(store: BenchmarkStore, *, exclude_run_id: str) -> BenchmarkRun | None:
    """Return the most recent retained run that is not the current one."""

    for candidate in store.runs(SUITE_NAME, last_n=20):
        if candidate.run_id != exclude_run_id:
            return candidate
    return None


def run_fingerprint(run: BenchmarkRun) -> str:
    """SHA-256 of the retained run's canonical JSON."""

    return hashlib.sha256(run.to_json().encode("utf-8")).hexdigest()


def validate_report_against_run(report: RegressionReport, run: BenchmarkRun) -> None:
    """Prove a report describes exactly the retained run it claims.

    Every identity field is recomputed from the run, so a report carrying an
    invented suite, revision, evaluator or summary is rejected even when its own
    internal numbers are coherent.
    """

    if not isinstance(report, RegressionReport):
        raise ValueError("run binding requires a RegressionReport")
    if not isinstance(run, BenchmarkRun):
        raise ValueError("run binding requires a BenchmarkRun")
    for name, actual, expected in (
        ("suite_name", report.suite_name, run.suite_name),
        ("suite_version", report.suite_version, run.suite_version),
        ("run_id", report.run_id, run.run_id),
        ("source_revision", report.source_revision, run.source_revision),
        ("candidate_id", report.candidate_id, run.candidate_id),
        ("baseline_id", report.baseline_id, run.baseline_id),
    ):
        if actual != expected:
            raise ValueError(f"report {name} does not match the retained run")
    if dict(report.totals) != run.summary:
        raise ValueError("report totals do not match the retained run summary")
    if report.run_fingerprint != run_fingerprint(run):
        raise ValueError("report is not bound to the retained run")


def _validate_sha256(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"report {name} must be a SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"report {name} must be a SHA-256 hex digest")


def _render(value: float | None) -> str:
    return "not_measured" if value is None else f"{value:g}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Nerva E9.1 scheduled router shadow comparison.",
    )
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--runner-id", default="github-ubuntu-latest")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit non-zero when a measured metric regressed.",
    )
    args = parser.parse_args(argv)

    try:
        revision = source_revision(args.revision)
        store = BenchmarkStore(args.store_root)
        run = asyncio.run(run_scheduled_suite(store, revision=revision))
    except PrerequisiteError as exc:
        # Fail visibly. A missing prerequisite is never reported as a pass.
        message = f"E9.1 scheduled suite could not run: {exc}"
        print(message, file=sys.stderr)
        _write(args.summary, f"### Nerva E9.1 — FAILED\n\n{message}\n")
        return 2

    report = build_report(
        run,
        environment=EnvironmentProfile.detect(runner_id=args.runner_id),
        previous=previous_run(store, exclude_run_id=run.run_id),
    )
    _write(args.summary, report.to_markdown() + "\n")
    _write(args.json_out, report.to_json() + "\n")
    print(report.to_markdown())
    if report.regressed and args.fail_on_regression:
        return 1
    return 0


def _write(target: str | None, content: str) -> None:
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
