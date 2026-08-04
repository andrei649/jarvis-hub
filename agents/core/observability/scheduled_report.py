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
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
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
    hardware_profile: str = "not_measured"
    schema: str = field(default="nerva.benchmark.environment.v1", init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.runner_id, "runner_id"),
            (self.platform, "platform"),
            (self.python_version, "python_version"),
            (self.hardware_profile, "hardware_profile"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"environment {name} must be a non-empty string")

    @classmethod
    def detect(cls, *, runner_id: str) -> EnvironmentProfile:
        # Hardware performance is never inferred from a shared CI runner.
        return cls(
            runner_id=runner_id,
            platform=f"{platform.system()}-{platform.machine()}".lower(),
            python_version=platform.python_version(),
            hardware_profile="not_measured",
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
        if self.status in {"improved", "regressed"} and (
            self.current is None or self.previous is None
        ):
            raise ValueError("a decided comparison requires both values")
        if self.status in {"not_measured", "no_baseline"} and self.delta is not None:
            raise ValueError("an undecided comparison cannot carry a delta")


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
        if not isinstance(self.comparisons, tuple) or not self.comparisons:
            raise ValueError("report requires at least one comparison")
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_markdown(self) -> str:
        lines = [
            f"### Nerva E9.1 scheduled shadow report — `{self.suite_name}` "
            f"v{self.suite_version}",
            "",
            f"- run: `{self.run_id}` · revision: `{self.source_revision}`",
            f"- candidate: `{self.candidate_id}` · baseline: "
            f"`{self.baseline_id or 'none'}`",
            f"- runner: `{self.environment.runner_id}` "
            f"({self.environment.platform}, py{self.environment.python_version})",
            f"- hardware profile: `{self.environment.hardware_profile}`",
            f"- previous run: `{self.previous_run_id or 'none'}`",
            "",
            "| metric | status | current | previous | delta |",
            "| --- | --- | --- | --- | --- |",
        ]
        for comparison in self.comparisons:
            lines.append(
                f"| {comparison.metric} | {comparison.status} | "
                f"{_render(comparison.current)} | {_render(comparison.previous)} | "
                f"{_render(comparison.delta)} |"
            )
        lines.extend(
            [
                "",
                f"Totals: {json.dumps(self.totals, sort_keys=True)}",
                "",
                "This report is evaluation-only. It does not change routing, "
                "promote a capability, or claim owner-hardware performance.",
            ]
        )
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


def source_revision(explicit: str | None = None) -> str:
    """Bind the report to an exact code revision, or fail honestly."""

    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        raise PrerequisiteError(f"cannot resolve source revision: {exc}") from exc
    revision = result.stdout.strip()
    if result.returncode != 0 or not revision:
        raise PrerequisiteError("cannot resolve source revision from git")
    return revision


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
