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
    # Single source of truth for the repository's exact-commit format. Validating
    # here keeps a malformed revision on the honest PrerequisiteError path
    # instead of surfacing as an unhandled ValueError deep in the harness.
    _source_revision as _validate_exact_revision,
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
    schema: str = field(default="nerva.benchmark.report.v1", init=False)
    authority: str = field(default="evaluation_only", init=False)
    can_change_routing: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_promote_capability: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.environment, EnvironmentProfile):
            raise ValueError("report requires an EnvironmentProfile")
        # A report is exact evidence; its revision is held to the same format
        # as the run it describes.
        try:
            _validate_exact_revision(self.source_revision)
        except ValueError as exc:
            raise ValueError(f"report source revision is invalid: {exc}") from exc

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
        if set(self.totals) != _TOTALS_KEYS:
            raise ValueError("report totals must match the benchmark summary keys")
        # Freeze the retained summary so post-construction mutation cannot
        # change later JSON or Markdown evidence.
        object.__setattr__(self, "totals", MappingProxyType(dict(self.totals)))

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


def _run_metrics(run: BenchmarkRun) -> dict[str, float | None]:
    summary = run.summary
    total = summary["total"]
    scored = summary["scored"]
    return {
        "quality_mean": summary["quality_mean"],
        "baseline_quality_mean": summary["baseline_quality_mean"],
        # Only a fully scored run yields a comparable pass ratio.
        "pass_ratio": (
            round(summary["passed"] / total, 6)
            if total and scored == total
            else None
        ),
    }


def build_report(
    run: BenchmarkRun,
    *,
    environment: EnvironmentProfile,
    previous: BenchmarkRun | None = None,
) -> RegressionReport:
    """Compare only genuinely measured metrics against the previous run."""

    current_metrics = _run_metrics(run)
    previous_metrics = _run_metrics(previous) if previous is not None else {}
    comparable = (
        previous is not None
        and previous.suite_name == run.suite_name
        and previous.suite_version == run.suite_version
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
    )


def previous_run(store: BenchmarkStore, *, exclude_run_id: str) -> BenchmarkRun | None:
    """Return the most recent retained run that is not the current one."""

    for candidate in store.runs(SUITE_NAME, last_n=20):
        if candidate.run_id != exclude_run_id:
            return candidate
    return None


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
