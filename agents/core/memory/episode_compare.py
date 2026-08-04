"""Privacy-minimised comparison of Episodes and the current recall baseline.

Evaluation only: this module does not change production recall or gain action,
execution, or completion authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from agents.core.memory.episodes import (
    EpisodeMatch,
    EpisodeQuery,
    EpisodeRecord,
    retrieve_episodes,
)
from agents.core.memory.eval import (
    MemoryEvalCase,
    keyword_answer,
    run_recall_eval,
    score_answer,
)

FixturePrivacyClass = Literal["synthetic_public", "redacted_local"]
MetricStatus = Literal["measured", "not_measured"]
BaselineRunner = Callable[..., Awaitable[dict[str, Any]]]

_ALLOWED_PRIVACY = {"synthetic_public", "redacted_local"}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CANONICAL_BASELINE_SOURCE = "memory.eval.run_recall_eval"
_EPISODE_SOURCE = "episodes.retrieve_episodes"
_DELTA_SOURCE = "episode-baseline"


@dataclass(frozen=True)
class EpisodeComparisonMetric:
    """One measured or explicitly unmeasured comparison value."""

    status: MetricStatus
    value: float | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"measured", "not_measured"}:
            raise ValueError("comparison metric status is not recognized")
        if self.status == "not_measured":
            if self.value is not None or self.source is not None:
                raise ValueError("unmeasured comparison metric cannot carry data")
            return
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("measured comparison metric requires a number")
        if not math.isfinite(float(self.value)):
            raise ValueError("measured comparison metric must be finite")
        _identifier(self.source, "metric source")


@dataclass(frozen=True)
class EpisodeComparisonCase:
    """Transient fixture input; canonical reports retain none of its text."""

    case_id: str
    ability: str
    privacy_class: FixturePrivacyClass
    facts: tuple[str, ...]
    question: str
    expected: tuple[str, ...]
    abstain: bool
    records: tuple[EpisodeRecord, ...]
    query: EpisodeQuery

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        _identifier(self.ability, "ability")
        _non_empty(self.question, "question")
        if self.privacy_class not in _ALLOWED_PRIVACY:
            raise ValueError("comparison fixture privacy class must be explicit")
        _text_tuple(self.facts, "facts", allow_empty=False)
        _text_tuple(self.expected, "expected", allow_empty=self.abstain)
        if not isinstance(self.abstain, bool):
            raise ValueError("comparison abstain must be boolean")
        if self.abstain and self.expected:
            raise ValueError("abstention case cannot carry expected text")
        if not self.abstain and not self.expected:
            raise ValueError("answerable case requires expected text")
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, EpisodeRecord) for record in self.records
        ):
            raise ValueError("comparison records must be EpisodeRecord tuples")
        if not self.records:
            raise ValueError("comparison case requires episode records")
        if any(record.authority != "memory_record_only" for record in self.records):
            raise ValueError("comparison records must remain memory-only")
        if not isinstance(self.query, EpisodeQuery):
            raise ValueError("comparison case requires EpisodeQuery")
        _validate_typed_privacy(self)

    def memory_case(self) -> MemoryEvalCase:
        """Project transient text onto the existing real-recall harness."""

        return MemoryEvalCase(
            id=self.case_id,
            ability=self.ability,
            facts=list(self.facts),
            question=self.question,
            expected=list(self.expected),
            abstain=self.abstain,
        )


@dataclass(frozen=True)
class EpisodeComparisonCaseResult:
    """Text-free outcome for one baseline-versus-Episodes case."""

    case_id: str
    ability: str
    privacy_class: FixturePrivacyClass
    baseline_passed: bool
    episode_passed: bool
    baseline_retrieved_count: int
    episode_match_count: int
    baseline_failure_type: str | None = None
    episode_failure_type: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.case_id, "result case_id")
        _identifier(self.ability, "result ability")
        if self.privacy_class not in _ALLOWED_PRIVACY:
            raise ValueError("comparison result privacy class is not recognized")
        for name in ("baseline_passed", "episode_passed"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"comparison {name} must be boolean")
        for name in ("baseline_retrieved_count", "episode_match_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"comparison {name} must be non-negative")
        for name in ("baseline_failure_type", "episode_failure_type"):
            value = getattr(self, name)
            if value is not None:
                _identifier(value, name)
        if self.baseline_failure_type is not None and self.baseline_passed:
            raise ValueError("failed baseline case cannot pass")
        if self.episode_failure_type is not None and self.episode_passed:
            raise ValueError("failed episode case cannot pass")


@dataclass(frozen=True)
class EpisodeComparisonReport:
    """Canonical, text-free E3.1 comparison report."""

    comparison_id: str
    retrieval_budget: int
    cases: tuple[EpisodeComparisonCaseResult, ...]
    baseline_accuracy: EpisodeComparisonMetric
    episode_accuracy: EpisodeComparisonMetric
    accuracy_delta: EpisodeComparisonMetric
    episode_win_count: int
    tie_count: int
    episode_loss_count: int
    baseline_failure_count: int
    episode_failure_count: int
    no_regression: bool
    privacy_distribution: tuple[tuple[str, int], ...]
    latency: EpisodeComparisonMetric = field(
        default_factory=lambda: EpisodeComparisonMetric("not_measured")
    )
    real_outcome_quality: EpisodeComparisonMetric = field(
        default_factory=lambda: EpisodeComparisonMetric("not_measured")
    )
    schema: str = field(default="nerva.episode.comparison.v1", init=False)
    evidence_scope: str = field(default="privacy_safe_fixture_only", init=False)
    authority: str = field(default="evaluation_only", init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _identifier(self.comparison_id, "comparison_id")
        _retrieval_budget(self.retrieval_budget)
        if not isinstance(self.cases, tuple) or not self.cases:
            raise ValueError("comparison report requires cases")
        if any(
            not isinstance(case, EpisodeComparisonCaseResult) for case in self.cases
        ):
            raise ValueError("comparison report cases must be typed results")
        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != tuple(sorted(case_ids)):
            raise ValueError("comparison report cases must be ordered")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("comparison report case IDs must be unique")
        for name in (
            "baseline_accuracy",
            "episode_accuracy",
            "accuracy_delta",
            "latency",
            "real_outcome_quality",
        ):
            if not isinstance(getattr(self, name), EpisodeComparisonMetric):
                raise ValueError(f"comparison {name} must be a typed metric")
        if self.baseline_accuracy.status != "measured":
            raise ValueError("comparison baseline accuracy must be measured")
        if self.episode_accuracy.status != "measured":
            raise ValueError("comparison episode accuracy must be measured")
        if self.accuracy_delta.status != "measured":
            raise ValueError("comparison accuracy delta must be measured")
        if self.latency.status != "not_measured":
            raise ValueError("E3.1 latency must remain explicitly unmeasured")
        if self.real_outcome_quality.status != "not_measured":
            raise ValueError("E3.1 real outcomes must remain explicitly unmeasured")
        for metric in (self.baseline_accuracy, self.episode_accuracy):
            if metric.value is None or not 0.0 <= float(metric.value) <= 1.0:
                raise ValueError("comparison accuracy must be between zero and one")
        if self.accuracy_delta.value is None or not -1.0 <= float(
            self.accuracy_delta.value
        ) <= 1.0:
            raise ValueError("comparison accuracy delta must be between -1 and 1")
        for name in (
            "episode_win_count",
            "tie_count",
            "episode_loss_count",
            "baseline_failure_count",
            "episode_failure_count",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"comparison {name} must be non-negative")
        if not isinstance(self.no_regression, bool):
            raise ValueError("comparison no_regression must be boolean")
        self._validate_derived_values()

    def _validate_derived_values(self) -> None:
        total = len(self.cases)
        if any(
            case.baseline_retrieved_count > self.retrieval_budget
            or case.episode_match_count > self.retrieval_budget
            for case in self.cases
        ):
            raise ValueError("comparison result exceeds the shared retrieval budget")

        baseline_passes = sum(case.baseline_passed for case in self.cases)
        episode_passes = sum(case.episode_passed for case in self.cases)
        expected_baseline = round(baseline_passes / total, 6)
        expected_episode = round(episode_passes / total, 6)
        expected_delta = round(expected_episode - expected_baseline, 6)
        if not math.isclose(
            float(self.baseline_accuracy.value), expected_baseline, abs_tol=1e-9
        ):
            raise ValueError("comparison baseline accuracy does not match cases")
        if not math.isclose(
            float(self.episode_accuracy.value), expected_episode, abs_tol=1e-9
        ):
            raise ValueError("comparison episode accuracy does not match cases")
        if not math.isclose(
            float(self.accuracy_delta.value), expected_delta, abs_tol=1e-9
        ):
            raise ValueError("comparison accuracy delta does not match cases")

        expected_wins = sum(
            case.episode_passed and not case.baseline_passed for case in self.cases
        )
        expected_losses = sum(
            case.baseline_passed and not case.episode_passed for case in self.cases
        )
        expected_ties = total - expected_wins - expected_losses
        if (
            self.episode_win_count,
            self.tie_count,
            self.episode_loss_count,
        ) != (expected_wins, expected_ties, expected_losses):
            raise ValueError("comparison outcome counts do not match cases")

        expected_baseline_failures = sum(
            case.baseline_failure_type is not None for case in self.cases
        )
        expected_episode_failures = sum(
            case.episode_failure_type is not None for case in self.cases
        )
        if self.baseline_failure_count != expected_baseline_failures:
            raise ValueError("comparison baseline failures do not match cases")
        if self.episode_failure_count != expected_episode_failures:
            raise ValueError("comparison episode failures do not match cases")

        expected_privacy = tuple(
            sorted(Counter(case.privacy_class for case in self.cases).items())
        )
        if self.privacy_distribution != expected_privacy:
            raise ValueError("comparison privacy distribution does not match cases")

        expected_no_regression = (
            expected_baseline_failures == 0
            and expected_episode_failures == 0
            and expected_episode >= expected_baseline
        )
        if self.no_regression is not expected_no_regression:
            raise ValueError("comparison no_regression does not match evidence")

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def replay_fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


async def compare_episode_retrieval(
    *,
    cases: Sequence[EpisodeComparisonCase],
    comparison_id: str,
    top_k: int = 5,
    baseline_runner: BaselineRunner = run_recall_eval,
    baseline_source: str = _CANONICAL_BASELINE_SOURCE,
) -> EpisodeComparisonReport:
    """Compare both paths over identical cases and one explicit retrieval budget."""

    _identifier(comparison_id, "comparison_id")
    _retrieval_budget(top_k)
    _validate_baseline_provenance(baseline_runner, baseline_source)

    ordered = tuple(sorted(cases, key=lambda case: case.case_id))
    if not ordered:
        raise ValueError("comparison requires at least one case")
    if any(not isinstance(case, EpisodeComparisonCase) for case in ordered):
        raise ValueError("comparison cases must be typed EpisodeComparisonCase values")
    ids = [case.case_id for case in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("comparison case IDs must be unique")
    for case in ordered:
        if case.query.limit != top_k:
            raise ValueError(
                "comparison Episode query limit must match the shared retrieval budget"
            )

    baseline_by_id: dict[str, dict[str, Any]] = {}
    baseline_error: str | None = None
    try:
        payload = await baseline_runner(
            [case.memory_case() for case in ordered],
            top_k=top_k,
        )
        baseline_by_id = _baseline_results(payload, set(ids), top_k)
    except Exception as exc:
        baseline_error = type(exc).__name__

    results: list[EpisodeComparisonCaseResult] = []
    for case in ordered:
        baseline = baseline_by_id.get(case.case_id)
        baseline_failure = baseline_error
        baseline_passed = False
        baseline_count = 0
        if baseline_error is None:
            if baseline is None:
                baseline_failure = "ValueError"
            else:
                baseline_passed = baseline["passed"]
                baseline_count = len(baseline["retrieved"])

        episode_passed = False
        episode_count = 0
        episode_failure: str | None = None
        try:
            matches = retrieve_episodes(case.records, case.query)
            episode_count = len(matches)
            if episode_count > top_k:
                raise ValueError("Episodes retrieval exceeded the shared budget")
            answer = keyword_answer(case.question, _match_texts(matches))
            episode_passed = score_answer(case.memory_case(), answer)
        except Exception as exc:
            episode_failure = type(exc).__name__

        results.append(
            EpisodeComparisonCaseResult(
                case_id=case.case_id,
                ability=case.ability,
                privacy_class=case.privacy_class,
                baseline_passed=baseline_passed,
                episode_passed=episode_passed,
                baseline_retrieved_count=baseline_count,
                episode_match_count=episode_count,
                baseline_failure_type=baseline_failure,
                episode_failure_type=episode_failure,
            )
        )

    case_results = tuple(results)
    total = len(case_results)
    baseline_passes = sum(item.baseline_passed for item in case_results)
    episode_passes = sum(item.episode_passed for item in case_results)
    baseline_accuracy = baseline_passes / total
    episode_accuracy = episode_passes / total
    wins = sum(
        item.episode_passed and not item.baseline_passed for item in case_results
    )
    losses = sum(
        item.baseline_passed and not item.episode_passed for item in case_results
    )
    baseline_failures = sum(
        item.baseline_failure_type is not None for item in case_results
    )
    episode_failures = sum(
        item.episode_failure_type is not None for item in case_results
    )
    privacy = Counter(item.privacy_class for item in case_results)

    return EpisodeComparisonReport(
        comparison_id=comparison_id,
        retrieval_budget=top_k,
        cases=case_results,
        baseline_accuracy=EpisodeComparisonMetric(
            "measured", round(baseline_accuracy, 6), baseline_source
        ),
        episode_accuracy=EpisodeComparisonMetric(
            "measured", round(episode_accuracy, 6), _EPISODE_SOURCE
        ),
        accuracy_delta=EpisodeComparisonMetric(
            "measured",
            round(episode_accuracy - baseline_accuracy, 6),
            _DELTA_SOURCE,
        ),
        episode_win_count=wins,
        tie_count=total - wins - losses,
        episode_loss_count=losses,
        baseline_failure_count=baseline_failures,
        episode_failure_count=episode_failures,
        no_regression=(
            baseline_failures == 0
            and episode_failures == 0
            and episode_accuracy >= baseline_accuracy
        ),
        privacy_distribution=tuple(sorted(privacy.items())),
    )


def _validate_baseline_provenance(
    baseline_runner: BaselineRunner,
    baseline_source: str,
) -> None:
    if not callable(baseline_runner):
        raise ValueError("comparison baseline runner must be callable")
    _identifier(baseline_source, "baseline_source")
    uses_real_runner = baseline_runner is run_recall_eval
    claims_real_runner = baseline_source == _CANONICAL_BASELINE_SOURCE
    if uses_real_runner != claims_real_runner:
        raise ValueError("comparison baseline source must match the runner identity")


def _validate_typed_privacy(case: EpisodeComparisonCase) -> None:
    if case.privacy_class != "synthetic_public":
        return
    non_public = {
        reference.privacy_class
        for record in case.records
        for reference in record.references
        if reference.privacy_class != "public"
    }
    if non_public:
        raise ValueError(
            "synthetic_public comparison cases require public Episode references"
        )


def _baseline_results(
    report: dict[str, Any],
    expected_ids: set[str],
    retrieval_budget: int,
) -> dict[str, dict[str, Any]]:
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        raise ValueError("baseline report is malformed")
    if report.get("top_k", retrieval_budget) != retrieval_budget:
        raise ValueError("baseline report retrieval budget does not match request")
    by_id: dict[str, dict[str, Any]] = {}
    for item in report["results"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("baseline result is malformed")
        retrieved = item.get("retrieved")
        if (
            item["id"] in by_id
            or not isinstance(item.get("passed"), bool)
            or not isinstance(retrieved, list)
            or len(retrieved) > retrieval_budget
        ):
            raise ValueError("baseline result is not canonical")
        by_id[item["id"]] = item
    if set(by_id) != expected_ids:
        raise ValueError("baseline result IDs do not match comparison cases")
    return by_id


def _match_texts(matches: Sequence[EpisodeMatch]) -> list[str]:
    output: list[str] = []
    for match in matches:
        for assertion in (
            match.episode.summary,
            match.episode.significance,
            match.episode.goal,
        ):
            if assertion is not None:
                output.append(assertion.text)
    return output


def _retrieval_budget(value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
        raise ValueError("comparison retrieval budget must be between 1 and 100")


def _text_tuple(value: Any, name: str, *, allow_empty: bool) -> None:
    if not isinstance(value, tuple) or (not value and not allow_empty):
        raise ValueError(f"comparison {name} must be an immutable tuple")
    for item in value:
        _non_empty(item, name)


def _identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"comparison {name} must be a bounded content-free identifier"
        )


def _non_empty(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"comparison {name} must be a non-empty string")
