"""Nerva E6.1 held-out lesson-proposal evaluation.

The evaluator composes the accepted E6.0 evidence graph with the accepted E9.0
BenchmarkStore and BenchmarkHarness. It is deliberately hermetic and has no
promotion, routing, memory-write, authorization, execution, or completion
surface.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import platform
import re
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from agents.core.memory.atlas_snapshot import AtlasConfidence
from agents.core.memory.episodes import EpisodeReference
from agents.core.observability.benchmark import (
    BenchmarkCase,
    BenchmarkCriterion,
    BenchmarkEvidence,
    BenchmarkHarness,
    BenchmarkObservation,
    BenchmarkRun,
    BenchmarkStore,
)
from agents.core.reflection_lesson import (
    LessonProposal,
    OutcomeObservation,
    compare_outcome,
    propose_lesson,
    validate_proposal_evidence,
)

EvaluationLane = Literal["ci", "local"]
EvaluationPrivacy = Literal["synthetic_public", "owner_private_local"]
Eligibility = Literal["eligible", "missing", "stale", "contradictory", "unverified"]
Classification = Literal[
    "correct",
    "abstained",
    "false_recall",
    "hallucinated_recall",
    "runner_error",
    "unverified_outcome",
]
EvidenceLabel = Literal["synthetic_hermetic", "owner_local"]
DeletionBehavior = Literal["artifact_expiry_only"]
RetentionDisposition = Literal["retain", "delete_due"]
LessonAnswerRunner = Callable[["LessonRunnerInput"], Awaitable[str]]

_ID_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
_SUITE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_REVISION_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_CLASSIFICATIONS: tuple[Classification, ...] = (
    "correct",
    "abstained",
    "false_recall",
    "hallucinated_recall",
    "runner_error",
    "unverified_outcome",
)
_ABSTENTIONS = {
    "abstain",
    "i do not know",
    "i don't know",
    "unknown",
}
_CLASSIFICATION_PREFIX = "nerva://e6.1/classification/"
_REPORT_GUARD = object()
_ENVIRONMENT_GUARD = object()
_MAX_TEXT = 10_000


def _canonical(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: str | Mapping[str, Any] | Sequence[Any]) -> str:
    encoded = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical lowercase identifier")
    return value


def _suite_name(value: object) -> str:
    if not isinstance(value, str) or _SUITE_RE.fullmatch(value) is None or value in {".", ".."}:
        raise ValueError("suite name must be a bounded path-free identifier")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _source_revision(value: object) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise ValueError("source revision must be an exact lowercase Git commit SHA")
    return value


def _finite(value: object, label: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def _bounded_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT or "\x00" in value:
        raise ValueError(f"{label} must be bounded non-empty text")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be canonical UTC RFC 3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be canonical UTC RFC 3339") from exc
    canonical = parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if value != canonical:
        raise ValueError(f"{label} must use millisecond precision")
    return parsed


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class EvaluationBudget:
    """One shared context budget used by both evaluator identities."""

    max_context_items: int
    max_context_chars: int

    def __post_init__(self) -> None:
        for value, label, maximum in (
            (self.max_context_items, "max_context_items", 128),
            (self.max_context_chars, "max_context_chars", 100_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{label} must be a bounded positive integer")

    @property
    def fingerprint(self) -> str:
        return _sha256(asdict(self))


@dataclass(frozen=True)
class LessonEvaluationThresholds:
    """Predeclared overall thresholds; subgroup regressions always remain zero."""

    minimum_quality_delta: float = 0.0
    maximum_false_recall_delta: int = 0
    maximum_hallucinated_recall_delta: int = 0
    maximum_reliability_regression: float = 0.0

    def __post_init__(self) -> None:
        _finite(self.minimum_quality_delta, "minimum_quality_delta", maximum=1)
        _finite(
            self.maximum_reliability_regression,
            "maximum_reliability_regression",
            maximum=1,
        )
        for value, label in (
            (self.maximum_false_recall_delta, "maximum_false_recall_delta"),
            (
                self.maximum_hallucinated_recall_delta,
                "maximum_hallucinated_recall_delta",
            ),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")

    @property
    def fingerprint(self) -> str:
        return _sha256(asdict(self))


@dataclass(frozen=True)
class RetentionPolicy:
    """Predeclared artifact TTL; it never promotes or rewrites evidence."""

    predeclared_at: str
    expires_at: str
    deletion_behavior: DeletionBehavior

    def __post_init__(self) -> None:
        start = _timestamp(self.predeclared_at, "retention predeclared_at")
        finish = _timestamp(self.expires_at, "retention expires_at")
        if finish <= start:
            raise ValueError("retention expiry must follow predeclaration")
        if finish - start > timedelta(days=365):
            raise ValueError("retention interval must be bounded")
        if self.deletion_behavior != "artifact_expiry_only":
            raise ValueError("unsupported retention deletion behavior")

    @property
    def fingerprint(self) -> str:
        return _sha256(asdict(self))


@dataclass(frozen=True)
class EvaluationEnvironment:
    """Detected evaluator identity; callers cannot self-assert it."""

    runner_id: str
    python_version: str
    platform_system: str
    platform_machine: str
    evidence_label: EvidenceLabel = "synthetic_hermetic"
    guard: Any = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.guard is not _ENVIRONMENT_GUARD:
            raise ValueError("evaluation requires a detected environment")
        _identifier(self.runner_id, "runner id")
        for value, label in (
            (self.python_version, "python version"),
            (self.platform_system, "platform system"),
            (self.platform_machine, "platform machine"),
        ):
            _bounded_text(value, label)
            if "\n" in value or "\r" in value or len(value) > 128:
                raise ValueError(f"{label} must be bounded single-line text")
        if self.evidence_label not in {"synthetic_hermetic", "owner_local"}:
            raise ValueError("unsupported evaluation evidence label")

    @classmethod
    def detect(
        cls,
        *,
        runner_id: str,
        evidence_label: EvidenceLabel = "synthetic_hermetic",
    ) -> EvaluationEnvironment:
        return cls(
            runner_id=runner_id,
            python_version=platform.python_version(),
            platform_system=platform.system() or "unknown",
            platform_machine=platform.machine() or "unknown",
            evidence_label=evidence_label,
            guard=_ENVIRONMENT_GUARD,
        )

    @property
    def fingerprint(self) -> str:
        return _sha256(
            {
                "runner_id": self.runner_id,
                "python_version": self.python_version,
                "platform_system": self.platform_system,
                "platform_machine": self.platform_machine,
                "evidence_label": self.evidence_label,
            }
        )


def _observation_split_tokens(observation: OutcomeObservation) -> set[str]:
    references = (observation.expected_reference, *observation.observed_references)
    tokens = {
        f"observation:{observation.observation_id}",
        f"fingerprint:{observation.replay_fingerprint}",
        f"episode:{observation.episode_id}",
    }
    for reference in references:
        tokens.update(
            {
                f"reference:{reference.reference_id}",
                f"source-record:{reference.source_id}:{reference.record_id}",
            }
        )
    return tokens


def _observation_is_public(observation: OutcomeObservation) -> bool:
    references = (observation.expected_reference, *observation.observed_references)
    return observation.privacy_class == "public" and all(
        reference.privacy_class == "public" for reference in references
    )


@dataclass(frozen=True)
class HeldOutLessonCase:
    """One immutable split fixture; truth is never passed to an answer runner."""

    case_id: str
    subgroup: str
    privacy_class: EvaluationPrivacy
    question: str
    source_context: tuple[str, ...]
    expected_answer: str | None
    should_abstain: bool
    proposal: LessonProposal
    development_observations: tuple[OutcomeObservation, ...]
    held_out_observation: OutcomeObservation | None

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case id")
        _identifier(self.subgroup, "subgroup")
        if self.privacy_class not in {"synthetic_public", "owner_private_local"}:
            raise ValueError("unsupported lesson evaluation privacy class")
        _bounded_text(self.question, "evaluation question")
        if not isinstance(self.source_context, tuple) or not self.source_context:
            raise ValueError("source_context must be a non-empty tuple")
        for item in self.source_context:
            _bounded_text(item, "source context item")
        if not isinstance(self.should_abstain, bool):
            raise ValueError("should_abstain must be boolean")
        if self.should_abstain:
            if self.expected_answer is not None:
                raise ValueError("abstention fixtures cannot carry an expected answer")
        else:
            _bounded_text(self.expected_answer, "expected answer")
        if not isinstance(self.proposal, LessonProposal):
            raise ValueError("evaluation requires a LessonProposal")
        if self.proposal.lifecycle != "proposed":
            raise ValueError("evaluation accepts only the proposed lesson lifecycle")
        if (
            not isinstance(self.development_observations, tuple)
            or not self.development_observations
            or any(
                not isinstance(item, OutcomeObservation) for item in self.development_observations
            )
        ):
            raise ValueError("development split requires OutcomeObservation evidence")
        validate_proposal_evidence(self.proposal, self.development_observations)
        if self.held_out_observation is not None and not isinstance(
            self.held_out_observation, OutcomeObservation
        ):
            raise ValueError("held-out evidence must use OutcomeObservation")

        development_tokens: set[str] = set()
        for observation in self.development_observations:
            development_tokens |= _observation_split_tokens(observation)
        if self.held_out_observation is not None:
            held_tokens = _observation_split_tokens(self.held_out_observation)
            if development_tokens & held_tokens:
                raise ValueError("held-out split overlaps development evidence")

        if self.privacy_class == "synthetic_public":
            observations = (
                *self.development_observations,
                *((self.held_out_observation,) if self.held_out_observation is not None else ()),
            )
            if self.proposal.privacy_class != "public" or not all(
                _observation_is_public(item) for item in observations
            ):
                raise ValueError("synthetic-public fixtures require public proposal evidence")

    @property
    def source_set_digest(self) -> str:
        return _sha256(list(self.source_context))

    @property
    def fixture_fingerprint(self) -> str:
        return _sha256(
            {
                "case_id": self.case_id,
                "subgroup": self.subgroup,
                "privacy_class": self.privacy_class,
                "question_digest": _sha256(self.question),
                "source_set_digest": self.source_set_digest,
                "expected_answer_digest": (
                    _sha256(self.expected_answer) if self.expected_answer is not None else None
                ),
                "should_abstain": self.should_abstain,
                "proposal_fingerprint": self.proposal.replay_fingerprint,
                "development_fingerprints": [
                    item.replay_fingerprint for item in self.development_observations
                ],
                "held_out_fingerprint": (
                    self.held_out_observation.replay_fingerprint
                    if self.held_out_observation is not None
                    else None
                ),
            }
        )

    def eligibility(
        self,
        *,
        evaluated_at: float,
        max_outcome_age_seconds: float,
    ) -> Eligibility:
        if self.held_out_observation is None:
            return "missing"
        if (
            evaluated_at >= self.proposal.expires_at
            or evaluated_at - self.held_out_observation.observed_at > max_outcome_age_seconds
        ):
            return "stale"
        if self.held_out_observation.comparison_status == "contradictory":
            return "contradictory"
        if self.held_out_observation.comparison_status == "insufficient_evidence":
            return "unverified"
        return "eligible"


@dataclass(frozen=True)
class LessonEvaluationPlan:
    """Complete experiment declaration frozen before any runner executes."""

    suite_name: str
    cases: tuple[HeldOutLessonCase, ...]
    lane: EvaluationLane
    source_revision: str
    candidate_id: str
    baseline_id: str
    environment: EvaluationEnvironment
    budget: EvaluationBudget
    thresholds: LessonEvaluationThresholds
    retention: RetentionPolicy
    evaluated_at: float
    max_outcome_age_seconds: float = 86_400.0

    def __post_init__(self) -> None:
        _suite_name(self.suite_name)
        if (
            not isinstance(self.cases, tuple)
            or not self.cases
            or any(not isinstance(item, HeldOutLessonCase) for item in self.cases)
        ):
            raise ValueError("evaluation plan requires typed held-out cases")
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("evaluation case ids must be unique")
        if ids != tuple(sorted(ids)):
            raise ValueError("evaluation cases must be deterministically ordered")
        if self.lane not in {"ci", "local"}:
            raise ValueError("lesson evaluation supports only ci or local lanes")
        _source_revision(self.source_revision)
        _identifier(self.candidate_id, "candidate id")
        _identifier(self.baseline_id, "baseline id")
        if self.candidate_id == self.baseline_id:
            raise ValueError("candidate and baseline identities must differ")
        if not isinstance(self.environment, EvaluationEnvironment):
            raise ValueError("evaluation plan requires a detected environment")
        if not isinstance(self.budget, EvaluationBudget):
            raise ValueError("evaluation plan requires one shared budget")
        if not isinstance(self.thresholds, LessonEvaluationThresholds):
            raise ValueError("evaluation plan requires typed thresholds")
        if not isinstance(self.retention, RetentionPolicy):
            raise ValueError("evaluation plan requires a retention policy")
        _finite(self.evaluated_at, "evaluated_at")
        _finite(self.max_outcome_age_seconds, "max_outcome_age_seconds")
        if self.max_outcome_age_seconds == 0:
            raise ValueError("max_outcome_age_seconds must be positive")

        privacy_classes = {item.privacy_class for item in self.cases}
        if len(privacy_classes) != 1:
            raise ValueError("privacy lanes must use separately retained suites")
        if "owner_private_local" in privacy_classes and self.lane != "local":
            raise ValueError("owner-private fixtures are local-only")
        expected_label = (
            "owner_local" if "owner_private_local" in privacy_classes else "synthetic_hermetic"
        )
        if self.environment.evidence_label != expected_label:
            raise ValueError("environment evidence label mismatches the privacy lane")

        for item in self.cases:
            context_items = (item.proposal.claim, *item.source_context)
            if any(len(text) > self.budget.max_context_chars for text in context_items):
                raise ValueError("context item exceeds the shared character budget")

    @property
    def privacy_lane(self) -> EvaluationPrivacy:
        return self.cases[0].privacy_class

    @property
    def fixture_digest(self) -> str:
        return _sha256([item.fixture_fingerprint for item in self.cases])

    @property
    def fingerprint(self) -> str:
        return _sha256(
            {
                "suite_name": self.suite_name,
                "case_fingerprints": [item.fixture_fingerprint for item in self.cases],
                "lane": self.lane,
                "source_revision": self.source_revision,
                "candidate_id": self.candidate_id,
                "baseline_id": self.baseline_id,
                "environment_fingerprint": self.environment.fingerprint,
                "budget_fingerprint": self.budget.fingerprint,
                "thresholds_fingerprint": self.thresholds.fingerprint,
                "retention_fingerprint": self.retention.fingerprint,
                "evaluated_at": float(self.evaluated_at),
                "max_outcome_age_seconds": float(self.max_outcome_age_seconds),
            }
        )


@dataclass(frozen=True)
class LessonRunnerInput:
    """Oracle-free input passed to candidate or baseline answer code."""

    case_id: str
    question: str
    context_items: tuple[str, ...]
    treatment: Literal["proposal_overlay", "raw_evidence"]
    source_set_digest: str
    max_context_items: int
    max_context_chars: int

    def __post_init__(self) -> None:
        _identifier(self.case_id, "runner case id")
        _bounded_text(self.question, "runner question")
        if self.treatment not in {"proposal_overlay", "raw_evidence"}:
            raise ValueError("unsupported evaluation treatment")
        _digest(self.source_set_digest, "runner source-set digest")
        if not isinstance(self.context_items, tuple) or not self.context_items:
            raise ValueError("runner context must be a non-empty tuple")
        if len(self.context_items) > self.max_context_items:
            raise ValueError("runner context exceeds the shared item budget")
        if sum(len(item) for item in self.context_items) > self.max_context_chars:
            raise ValueError("runner context exceeds the shared character budget")
        for item in self.context_items:
            _bounded_text(item, "runner context item")


@dataclass(frozen=True)
class ClassificationMetrics:
    total: int
    eligible: int
    quality_passed: int
    correct: int
    abstained: int
    false_recall: int
    hallucinated_recall: int
    runner_error: int
    unverified: int
    quality: float | None
    reliability: float | None

    def __post_init__(self) -> None:
        counts = (
            self.total,
            self.eligible,
            self.quality_passed,
            self.correct,
            self.abstained,
            self.false_recall,
            self.hallucinated_recall,
            self.runner_error,
            self.unverified,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
        ):
            raise ValueError("metric totals must be non-negative integers")
        classified = (
            self.correct
            + self.abstained
            + self.false_recall
            + self.hallucinated_recall
            + self.runner_error
        )
        if (
            self.total != self.eligible + self.unverified
            or self.eligible != classified
            or self.quality_passed > self.eligible
        ):
            raise ValueError("metric totals are inconsistent")
        expected_quality = round(self.quality_passed / self.eligible, 6) if self.eligible else None
        expected_reliability = (
            round(1.0 - (self.runner_error / self.eligible), 6) if self.eligible else None
        )
        if self.quality != expected_quality or self.reliability != expected_reliability:
            raise ValueError("metric totals do not match derived ratios")


@dataclass(frozen=True)
class EvaluationMetrics:
    candidate: ClassificationMetrics
    baseline: ClassificationMetrics
    quality_delta: float | None
    false_recall_delta: int
    hallucinated_recall_delta: int
    reliability_delta: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, ClassificationMetrics) or not isinstance(
            self.baseline, ClassificationMetrics
        ):
            raise ValueError("comparison metrics require typed summaries")
        if self.candidate.total != self.baseline.total:
            raise ValueError("comparison metric totals disagree")
        quality_delta = (
            round(self.candidate.quality - self.baseline.quality, 6)
            if self.candidate.quality is not None and self.baseline.quality is not None
            else None
        )
        reliability_delta = (
            round(self.candidate.reliability - self.baseline.reliability, 6)
            if self.candidate.reliability is not None and self.baseline.reliability is not None
            else None
        )
        if (
            self.quality_delta != quality_delta
            or self.false_recall_delta != self.candidate.false_recall - self.baseline.false_recall
            or self.hallucinated_recall_delta
            != self.candidate.hallucinated_recall - self.baseline.hallucinated_recall
            or self.reliability_delta != reliability_delta
        ):
            raise ValueError("comparison metric totals are inconsistent")


@dataclass(frozen=True)
class CaseEvaluationResult:
    case_id: str
    subgroup: str
    eligibility: Eligibility
    candidate_classification: Classification
    baseline_classification: Classification
    candidate_quality: float | None
    baseline_quality: float | None

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case result id")
        _identifier(self.subgroup, "case result subgroup")
        if self.eligibility not in {
            "eligible",
            "missing",
            "stale",
            "contradictory",
            "unverified",
        }:
            raise ValueError("unsupported case eligibility")
        if self.candidate_classification not in _CLASSIFICATIONS or (
            self.baseline_classification not in _CLASSIFICATIONS
        ):
            raise ValueError("unsupported case classification")
        if self.eligibility == "eligible":
            if self.candidate_quality not in {0.0, 1.0} or (
                self.baseline_quality not in {0.0, 1.0}
            ):
                raise ValueError("eligible cases require binary quality evidence")
        elif (
            self.candidate_classification != "unverified_outcome"
            or self.baseline_classification != "unverified_outcome"
            or self.candidate_quality is not None
            or self.baseline_quality is not None
        ):
            raise ValueError("ineligible outcomes must remain explicitly unverified")


@dataclass(frozen=True)
class SubgroupEvaluation:
    subgroup: str
    metrics: EvaluationMetrics
    passed: bool
    failure_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.subgroup, "subgroup result")
        if not isinstance(self.metrics, EvaluationMetrics):
            raise ValueError("subgroup requires typed metrics")
        if not isinstance(self.passed, bool):
            raise ValueError("subgroup pass state must be boolean")
        if (
            not isinstance(self.failure_reasons, tuple)
            or tuple(sorted(set(self.failure_reasons))) != self.failure_reasons
        ):
            raise ValueError("subgroup reasons must be unique and sorted")
        if self.passed != (not self.failure_reasons):
            raise ValueError("subgroup pass state contradicts its reasons")


@dataclass(frozen=True)
class LessonEvaluationReport:
    """Content-free retained report, constructible only by the evaluator."""

    report_id: str
    suite_name: str
    suite_version: int
    suite_fingerprint: str
    run_id: str
    run_fingerprint: str
    source_revision: str
    plan_fingerprint: str
    fixture_digest: str
    environment_fingerprint: str
    candidate_id: str
    baseline_id: str
    privacy_lane: EvaluationPrivacy
    evidence_label: EvidenceLabel
    metrics: EvaluationMetrics
    subgroups: tuple[SubgroupEvaluation, ...]
    case_results: tuple[CaseEvaluationResult, ...]
    success: bool
    failure_reasons: tuple[str, ...]
    retention_until: str
    deletion_behavior: DeletionBehavior
    guard: Any = field(default=None, compare=False, repr=False)
    schema: str = field(default="nerva.lesson.evaluation.v1", init=False)
    kind: str = field(default="report", init=False)
    authority: str = field(default="evaluation_only", init=False)
    can_promote_lesson: bool = field(default=False, init=False)
    can_write_memory: bool = field(default=False, init=False)
    can_change_routing: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.guard is not _REPORT_GUARD:
            raise ValueError("report construction requires the trusted evaluator")
        _identifier(self.report_id, "report id")
        _suite_name(self.suite_name)
        if (
            isinstance(self.suite_version, bool)
            or not isinstance(self.suite_version, int)
            or self.suite_version < 1
        ):
            raise ValueError("report suite version must be positive")
        for value, label in (
            (self.suite_fingerprint, "suite fingerprint"),
            (self.run_fingerprint, "run fingerprint"),
            (self.plan_fingerprint, "plan fingerprint"),
            (self.fixture_digest, "fixture digest"),
            (self.environment_fingerprint, "environment fingerprint"),
        ):
            _digest(value, label)
        _identifier(self.run_id, "report run id")
        _source_revision(self.source_revision)
        _identifier(self.candidate_id, "report candidate id")
        _identifier(self.baseline_id, "report baseline id")
        if self.privacy_lane not in {"synthetic_public", "owner_private_local"}:
            raise ValueError("unsupported report privacy lane")
        if self.evidence_label not in {"synthetic_hermetic", "owner_local"}:
            raise ValueError("unsupported report evidence label")
        if not isinstance(self.metrics, EvaluationMetrics):
            raise ValueError("report requires typed metrics")
        if not self.case_results or len(self.case_results) != self.metrics.candidate.total:
            raise ValueError("report case totals disagree with metrics")
        if tuple(item.case_id for item in self.case_results) != tuple(
            sorted(item.case_id for item in self.case_results)
        ):
            raise ValueError("report cases must be deterministically ordered")
        expected_groups = tuple(sorted({item.subgroup for item in self.case_results}))
        if tuple(item.subgroup for item in self.subgroups) != expected_groups:
            raise ValueError("report subgroup coverage is inconsistent")
        if tuple(sorted(set(self.failure_reasons))) != self.failure_reasons:
            raise ValueError("report failure reasons must be unique and sorted")
        if self.success != (not self.failure_reasons):
            raise ValueError("report success contradicts its failure reasons")
        _timestamp(self.retention_until, "report retention_until")
        if self.deletion_behavior != "artifact_expiry_only":
            raise ValueError("unsupported report deletion behavior")

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "suite_name": self.suite_name,
            "suite_version": self.suite_version,
            "suite_fingerprint": self.suite_fingerprint,
            "run_id": self.run_id,
            "run_fingerprint": self.run_fingerprint,
            "source_revision": self.source_revision,
            "plan_fingerprint": self.plan_fingerprint,
            "fixture_digest": self.fixture_digest,
            "environment_fingerprint": self.environment_fingerprint,
            "candidate_id": self.candidate_id,
            "baseline_id": self.baseline_id,
            "privacy_lane": self.privacy_lane,
            "evidence_label": self.evidence_label,
            "metrics": asdict(self.metrics),
            "subgroups": [asdict(item) for item in self.subgroups],
            "case_results": [asdict(item) for item in self.case_results],
            "success": self.success,
            "failure_reasons": list(self.failure_reasons),
            "retention_until": self.retention_until,
            "deletion_behavior": self.deletion_behavior,
            "schema": self.schema,
            "kind": self.kind,
            "authority": self.authority,
            "can_promote_lesson": self.can_promote_lesson,
            "can_write_memory": self.can_write_memory,
            "can_change_routing": self.can_change_routing,
            "can_authorize": self.can_authorize,
            "can_execute": self.can_execute,
            "can_mark_complete": self.can_mark_complete,
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict())


def _fit_context(items: Sequence[str], budget: EvaluationBudget) -> tuple[str, ...]:
    selected: list[str] = []
    used = 0
    for item in items:
        if len(selected) >= budget.max_context_items:
            break
        if used + len(item) > budget.max_context_chars:
            continue
        selected.append(item)
        used += len(item)
    if not selected:
        raise ValueError("shared budget cannot admit any context item")
    return tuple(selected)


def _runner_input(
    case: HeldOutLessonCase,
    plan: LessonEvaluationPlan,
    *,
    candidate: bool,
) -> LessonRunnerInput:
    source = (case.proposal.claim, *case.source_context) if candidate else case.source_context
    return LessonRunnerInput(
        case_id=case.case_id,
        question=case.question,
        context_items=_fit_context(source, plan.budget),
        treatment="proposal_overlay" if candidate else "raw_evidence",
        source_set_digest=case.source_set_digest,
        max_context_items=plan.budget.max_context_items,
        max_context_chars=plan.budget.max_context_chars,
    )


def _normalize_answer(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _classify(case: HeldOutLessonCase, answer: str) -> Classification:
    normalized = _normalize_answer(answer)
    if not normalized:
        return "runner_error"
    abstained = normalized in _ABSTENTIONS
    if case.should_abstain:
        return "abstained" if abstained else "hallucinated_recall"
    if abstained:
        return "abstained"
    expected = _normalize_answer(case.expected_answer or "")
    return "correct" if normalized == expected else "false_recall"


def _artifact_refs(
    case: HeldOutLessonCase,
    plan: LessonEvaluationPlan,
    classification: Classification,
) -> tuple[str, ...]:
    return (
        f"{_CLASSIFICATION_PREFIX}{classification}",
        f"nerva://e6.1/budget/{plan.budget.fingerprint}",
        f"nerva://e6.1/fixture/{case.fixture_fingerprint}",
        f"nerva://e6.1/source/{case.source_set_digest}",
    )


def _adapter(
    plan: LessonEvaluationPlan,
    cases: Mapping[str, HeldOutLessonCase],
    answer_runner: LessonAnswerRunner,
    *,
    candidate: bool,
) -> Callable[[str], Awaitable[BenchmarkObservation]]:
    route_id = plan.candidate_id if candidate else plan.baseline_id

    async def run(envelope_json: str) -> BenchmarkObservation:
        try:
            envelope = json.loads(envelope_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("evaluation envelope is invalid") from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "budget_fingerprint",
            "case_id",
            "fixture_fingerprint",
            "question_digest",
            "schema",
            "source_set_digest",
        }:
            raise ValueError("evaluation envelope fields are invalid")
        case_id = envelope["case_id"]
        case = cases.get(case_id)
        if case is None:
            raise ValueError("evaluation envelope names an unknown case")
        expected_envelope = _case_envelope(case, plan)
        if envelope_json != expected_envelope:
            raise ValueError("evaluation envelope does not match the frozen fixture")
        eligibility = case.eligibility(
            evaluated_at=plan.evaluated_at,
            max_outcome_age_seconds=plan.max_outcome_age_seconds,
        )
        if eligibility != "eligible":
            classification: Classification = "unverified_outcome"
        else:
            try:
                answer = await answer_runner(_runner_input(case, plan, candidate=candidate))
                if not isinstance(answer, str):
                    raise TypeError("lesson answer runner must return text")
                classification = _classify(case, answer)
            except Exception:
                classification = "runner_error"
        privacy_effect = (
            "local_only"
            if case.privacy_class == "owner_private_local"
            else "no_external_disclosure"
        )
        return BenchmarkObservation(
            response=classification,
            route_id=route_id,
            host_id=plan.environment.runner_id,
            reliability=0.0 if classification == "runner_error" else 1.0,
            privacy_effect=privacy_effect,
            artifact_refs=_artifact_refs(case, plan, classification),
        )

    return run


def _case_envelope(case: HeldOutLessonCase, plan: LessonEvaluationPlan) -> str:
    return _canonical(
        {
            "schema": "nerva.lesson.evaluation.runner-envelope.v1",
            "case_id": case.case_id,
            "question_digest": _sha256(case.question),
            "source_set_digest": case.source_set_digest,
            "fixture_fingerprint": case.fixture_fingerprint,
            "budget_fingerprint": plan.budget.fingerprint,
        }
    )


def _materialize_cases(plan: LessonEvaluationPlan) -> tuple[BenchmarkCase, ...]:
    materialized: list[BenchmarkCase] = []
    for case in plan.cases:
        eligibility = case.eligibility(
            evaluated_at=plan.evaluated_at,
            max_outcome_age_seconds=plan.max_outcome_age_seconds,
        )
        expected = "abstained" if case.should_abstain else "correct"
        materialized.append(
            BenchmarkCase(
                case_id=case.case_id,
                task_type="lesson-recall",
                input_text=_case_envelope(case, plan),
                privacy_class=case.privacy_class,
                allowed_lanes=(plan.lane,),
                criterion=(
                    BenchmarkCriterion("exact", expected) if eligibility == "eligible" else None
                ),
                tags=(
                    f"eligibility-{eligibility}",
                    f"subgroup-{case.subgroup}",
                ),
                artifact_refs=(
                    f"nerva://e6.1/budget/{plan.budget.fingerprint}",
                    f"nerva://e6.1/fixture/{case.fixture_fingerprint}",
                    f"nerva://e6.1/proposal/{case.proposal.replay_fingerprint}",
                    f"nerva://e6.1/source/{case.source_set_digest}",
                ),
            )
        )
    return tuple(materialized)


def _classification(
    evidence: BenchmarkEvidence | None,
    *,
    expected_route: str,
    plan: LessonEvaluationPlan,
    case: HeldOutLessonCase,
) -> Classification:
    if evidence is None:
        raise ValueError("retained evidence is missing an evaluator result")
    if evidence.route_id != expected_route:
        raise ValueError("retained evaluator identity mismatch")
    if evidence.host_id != plan.environment.runner_id:
        raise ValueError("retained environment identity mismatch")
    refs = [
        ref.removeprefix(_CLASSIFICATION_PREFIX)
        for ref in evidence.artifact_refs
        if ref.startswith(_CLASSIFICATION_PREFIX)
    ]
    if len(refs) != 1 or refs[0] not in _CLASSIFICATIONS:
        raise ValueError("retained classification evidence is inconsistent")
    classification = refs[0]
    required = set(_artifact_refs(case, plan, classification))
    if not required.issubset(evidence.artifact_refs):
        raise ValueError("retained source or budget binding is missing")
    if evidence.response_digest != _sha256(classification) or (
        evidence.response_length != len(classification)
    ):
        raise ValueError("retained classification digest is inconsistent")
    return classification  # type: ignore[return-value]


def _summary(
    rows: Sequence[CaseEvaluationResult],
    *,
    candidate: bool,
) -> ClassificationMetrics:
    classification_key = "candidate_classification" if candidate else "baseline_classification"
    quality_key = "candidate_quality" if candidate else "baseline_quality"
    classes = [getattr(item, classification_key) for item in rows]
    eligible = sum(item.eligibility == "eligible" for item in rows)
    return ClassificationMetrics(
        total=len(rows),
        eligible=eligible,
        quality_passed=sum(getattr(item, quality_key) == 1.0 for item in rows),
        correct=classes.count("correct"),
        abstained=classes.count("abstained"),
        false_recall=classes.count("false_recall"),
        hallucinated_recall=classes.count("hallucinated_recall"),
        runner_error=classes.count("runner_error"),
        unverified=classes.count("unverified_outcome"),
        quality=(
            round(
                sum(getattr(item, quality_key) == 1.0 for item in rows) / eligible,
                6,
            )
            if eligible
            else None
        ),
        reliability=(
            round(1.0 - (classes.count("runner_error") / eligible), 6) if eligible else None
        ),
    )


def _comparison(rows: Sequence[CaseEvaluationResult]) -> EvaluationMetrics:
    candidate = _summary(rows, candidate=True)
    baseline = _summary(rows, candidate=False)
    return EvaluationMetrics(
        candidate=candidate,
        baseline=baseline,
        quality_delta=(
            round(candidate.quality - baseline.quality, 6)
            if candidate.quality is not None and baseline.quality is not None
            else None
        ),
        false_recall_delta=candidate.false_recall - baseline.false_recall,
        hallucinated_recall_delta=(candidate.hallucinated_recall - baseline.hallucinated_recall),
        reliability_delta=(
            round(candidate.reliability - baseline.reliability, 6)
            if candidate.reliability is not None and baseline.reliability is not None
            else None
        ),
    )


def _subgroup_reasons(subgroup: str, metrics: EvaluationMetrics) -> tuple[str, ...]:
    reasons: list[str] = []
    if metrics.candidate.unverified or metrics.baseline.unverified:
        reasons.append(f"subgroup_unverified:{subgroup}")
    if metrics.quality_delta is None or metrics.quality_delta < 0:
        reasons.append(f"subgroup_quality_regression:{subgroup}")
    if metrics.false_recall_delta > 0:
        reasons.append(f"subgroup_false_recall_regression:{subgroup}")
    if metrics.hallucinated_recall_delta > 0:
        reasons.append(f"subgroup_hallucination_regression:{subgroup}")
    if metrics.reliability_delta is None or metrics.reliability_delta < 0:
        reasons.append(f"subgroup_reliability_regression:{subgroup}")
    return tuple(sorted(reasons))


def _overall_reasons(
    metrics: EvaluationMetrics,
    thresholds: LessonEvaluationThresholds,
) -> list[str]:
    reasons: list[str] = []
    if metrics.candidate.unverified or metrics.baseline.unverified:
        reasons.append("unverified_outcomes")
    if metrics.quality_delta is None or metrics.quality_delta < thresholds.minimum_quality_delta:
        reasons.append("quality_threshold_not_met")
    if metrics.false_recall_delta > thresholds.maximum_false_recall_delta:
        reasons.append("false_recall_regression")
    if metrics.hallucinated_recall_delta > thresholds.maximum_hallucinated_recall_delta:
        reasons.append("hallucinated_recall_regression")
    if (
        metrics.reliability_delta is None
        or metrics.reliability_delta < -thresholds.maximum_reliability_regression
    ):
        reasons.append("reliability_regression")
    return reasons


def _suite_fingerprint(cases: Sequence[BenchmarkCase]) -> str:
    return _sha256([case.content_fingerprint for case in cases])


def _run_fingerprint(run: BenchmarkRun) -> str:
    return _sha256(run.to_json())


def _report_from_retained(
    plan: LessonEvaluationPlan,
    run: BenchmarkRun,
    suite: Sequence[BenchmarkCase],
) -> LessonEvaluationReport:
    if run.source_revision != plan.source_revision:
        raise ValueError("retained run source revision mismatches the plan")
    if run.candidate_id != plan.candidate_id or run.baseline_id != plan.baseline_id:
        raise ValueError("retained evaluator identities mismatch the plan")
    if run.lane != plan.lane:
        raise ValueError("retained run lane mismatches the plan")
    expected_refs = {
        f"nerva://e6.1/environment/{plan.environment.fingerprint}",
        f"nerva://e6.1/fixture-set/{plan.fixture_digest}",
        f"nerva://e6.1/plan/{plan.fingerprint}",
        f"nerva://e6.1/retention/{plan.retention.fingerprint}",
    }
    if not expected_refs.issubset(run.artifact_refs):
        raise ValueError("retained run identity bindings are incomplete")
    by_result = {item.case_id: item for item in run.results}
    rows: list[CaseEvaluationResult] = []
    for case in plan.cases:
        result = by_result.get(case.case_id)
        if result is None:
            raise ValueError("retained run omits a frozen fixture")
        eligibility = case.eligibility(
            evaluated_at=plan.evaluated_at,
            max_outcome_age_seconds=plan.max_outcome_age_seconds,
        )
        candidate_classification = _classification(
            result.candidate,
            expected_route=plan.candidate_id,
            plan=plan,
            case=case,
        )
        baseline_classification = _classification(
            result.baseline,
            expected_route=plan.baseline_id,
            plan=plan,
            case=case,
        )
        candidate_quality = (
            float(result.quality.value) if result.quality.status == "measured" else None
        )
        baseline_quality = (
            float(result.baseline_quality.value)
            if result.baseline_quality.status == "measured"
            else None
        )
        rows.append(
            CaseEvaluationResult(
                case_id=case.case_id,
                subgroup=case.subgroup,
                eligibility=eligibility,
                candidate_classification=candidate_classification,
                baseline_classification=baseline_classification,
                candidate_quality=candidate_quality,
                baseline_quality=baseline_quality,
            )
        )
    ordered_rows = tuple(sorted(rows, key=lambda item: item.case_id))
    metrics = _comparison(ordered_rows)
    subgroups: list[SubgroupEvaluation] = []
    all_reasons = _overall_reasons(metrics, plan.thresholds)
    for subgroup in sorted({item.subgroup for item in ordered_rows}):
        subgroup_rows = tuple(item for item in ordered_rows if item.subgroup == subgroup)
        subgroup_metrics = _comparison(subgroup_rows)
        reasons = _subgroup_reasons(subgroup, subgroup_metrics)
        subgroups.append(
            SubgroupEvaluation(
                subgroup=subgroup,
                metrics=subgroup_metrics,
                passed=not reasons,
                failure_reasons=reasons,
            )
        )
        all_reasons.extend(reasons)
    failure_reasons = tuple(sorted(set(all_reasons)))
    report_material = {
        "plan_fingerprint": plan.fingerprint,
        "run_fingerprint": _run_fingerprint(run),
        "suite_fingerprint": _suite_fingerprint(suite),
    }
    return LessonEvaluationReport(
        report_id=f"lesson-eval-{_sha256(report_material)[:20]}",
        suite_name=run.suite_name,
        suite_version=run.suite_version,
        suite_fingerprint=_suite_fingerprint(suite),
        run_id=run.run_id,
        run_fingerprint=_run_fingerprint(run),
        source_revision=run.source_revision,
        plan_fingerprint=plan.fingerprint,
        fixture_digest=plan.fixture_digest,
        environment_fingerprint=plan.environment.fingerprint,
        candidate_id=run.candidate_id,
        baseline_id=run.baseline_id or "missing-baseline",
        privacy_lane=plan.privacy_lane,
        evidence_label=plan.environment.evidence_label,
        metrics=metrics,
        subgroups=tuple(subgroups),
        case_results=ordered_rows,
        success=not failure_reasons,
        failure_reasons=failure_reasons,
        retention_until=plan.retention.expires_at,
        deletion_behavior=plan.retention.deletion_behavior,
        guard=_REPORT_GUARD,
    )


async def evaluate_lesson_plan(
    plan: LessonEvaluationPlan,
    *,
    store: BenchmarkStore,
    candidate_runner: LessonAnswerRunner,
    baseline_runner: LessonAnswerRunner,
    now: Callable[[], str] | None = None,
    run_id: str | None = None,
) -> LessonEvaluationReport:
    """Run and retain one comparison before deciding whether it regressed."""

    if not isinstance(plan, LessonEvaluationPlan):
        raise ValueError("evaluation requires a frozen LessonEvaluationPlan")
    if not isinstance(store, BenchmarkStore):
        raise ValueError("evaluation requires the accepted BenchmarkStore")
    if not callable(candidate_runner) or not callable(baseline_runner):
        raise ValueError("candidate and baseline answer runners must be callable")
    cases = _materialize_cases(plan)
    version = store.save_suite(plan.suite_name, cases, lane=plan.lane)
    by_id = {item.case_id: item for item in plan.cases}
    harness = BenchmarkHarness(
        _adapter(plan, by_id, candidate_runner, candidate=True),
        candidate_id=plan.candidate_id,
        baseline=_adapter(plan, by_id, baseline_runner, candidate=False),
        baseline_id=plan.baseline_id,
    )
    kwargs: dict[str, Any] = {}
    if now is not None:
        kwargs["now"] = now
    run = await harness.run(
        cases,
        suite_name=plan.suite_name,
        suite_version=version,
        lane=plan.lane,
        source_revision=plan.source_revision,
        run_id=run_id,
        **kwargs,
    )
    run = replace(
        run,
        artifact_refs=(
            f"nerva://e6.1/environment/{plan.environment.fingerprint}",
            f"nerva://e6.1/fixture-set/{plan.fixture_digest}",
            f"nerva://e6.1/plan/{plan.fingerprint}",
            f"nerva://e6.1/retention/{plan.retention.fingerprint}",
        ),
    )
    # Append before threshold/report decisions: negative evidence is never lost.
    store.record_run(run)
    retained = next(
        item for item in store.runs(plan.suite_name, last_n=100_000) if item.run_id == run.run_id
    )
    retained_suite = store.load_suite(plan.suite_name, version)
    return _report_from_retained(plan, retained, retained_suite)


def _retained_run(
    report: LessonEvaluationReport,
    *,
    store: BenchmarkStore,
) -> BenchmarkRun:
    matches = tuple(
        item
        for item in store.runs(report.suite_name, last_n=100_000)
        if item.run_id == report.run_id
    )
    if len(matches) != 1:
        raise ValueError("report does not have exactly one retained run")
    return matches[0]


def validate_report_against_retained(
    report: LessonEvaluationReport,
    *,
    plan: LessonEvaluationPlan,
    store: BenchmarkStore,
) -> None:
    """Rebuild the report from the immutable suite and append-only run."""

    if not isinstance(report, LessonEvaluationReport):
        raise ValueError("report must use the typed evaluation schema")
    if report.plan_fingerprint != plan.fingerprint:
        raise ValueError("report plan identity mismatches retained evidence")
    run = _retained_run(report, store=store)
    suite = store.load_suite(report.suite_name, report.suite_version)
    expected_suite = _materialize_cases(plan)
    if tuple(item.content_fingerprint for item in suite) != tuple(
        item.content_fingerprint for item in expected_suite
    ):
        raise ValueError("report does not match the retained suite")
    expected = _report_from_retained(plan, run, suite)
    if report != expected:
        raise ValueError("report does not match retained evidence")


def load_lesson_evaluation_report(
    payload: str,
    *,
    plan: LessonEvaluationPlan,
    store: BenchmarkStore,
) -> LessonEvaluationReport:
    """Load only a byte-equivalent report derivable from retained evidence."""

    try:
        raw = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("lesson evaluation report must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("lesson evaluation report must be an object")
    run_id = raw.get("run_id")
    suite_name = raw.get("suite_name")
    suite_version = raw.get("suite_version")
    if (
        not isinstance(run_id, str)
        or not isinstance(suite_name, str)
        or not isinstance(suite_version, int)
    ):
        raise ValueError("lesson evaluation report identity fields are invalid")
    matches = tuple(
        item for item in store.runs(suite_name, last_n=100_000) if item.run_id == run_id
    )
    if len(matches) != 1:
        raise ValueError("report does not match retained evidence")
    suite = store.load_suite(suite_name, suite_version)
    expected_suite = _materialize_cases(plan)
    if tuple(item.content_fingerprint for item in suite) != tuple(
        item.content_fingerprint for item in expected_suite
    ):
        raise ValueError("report does not match retained evidence")
    expected = _report_from_retained(plan, matches[0], suite)
    if raw != json.loads(expected.to_json()):
        raise ValueError("report does not match retained evidence")
    return expected


def retention_disposition(
    report: LessonEvaluationReport,
    *,
    now: str,
) -> RetentionDisposition:
    """Describe artifact TTL without deleting E6.0 or E9.0 records."""

    current = _timestamp(now, "retention check time")
    expiry = _timestamp(report.retention_until, "report retention_until")
    return "delete_due" if current >= expiry else "retain"


def _synthetic_reference(
    key: str,
    role: Literal["decision", "outcome"],
    occurred_at: float,
) -> EpisodeReference:
    return EpisodeReference.build(
        role=role,
        source_id=f"e6-1-{key}",
        record_id=f"{key}-{role}",
        source_kind="synthetic_public",
        source_schema="nerva.episode.v1",
        privacy_class="public",
        integrity_sha256=_sha256(key),
        occurred_at=occurred_at,
        deletion_root_id=f"root-{key}",
        confidence=AtlasConfidence("unknown"),
    )


def _synthetic_observation(
    key: str,
    *,
    observed_at: float,
) -> OutcomeObservation:
    expected = _synthetic_reference(f"{key}-decision", "decision", observed_at - 2)
    outcome = _synthetic_reference(f"{key}-outcome", "outcome", observed_at - 1)
    return compare_outcome(
        episode_id=f"episode-{key}",
        expected_reference=expected,
        observed_references=(outcome,),
        matches_expectation={outcome.reference_id: True},
        environment="synthetic-hermetic",
        observed_at=observed_at,
        created_at=observed_at,
    )


def _synthetic_plan(
    *,
    revision: str,
    runner_id: str,
    epoch: float,
) -> LessonEvaluationPlan:
    dev = _synthetic_observation("dev", observed_at=epoch - 10)
    proposal = propose_lesson(
        observations=(dev,),
        claim="Retry once after the synthetic transient export failure.",
        scope="synthetic-export",
        proposed_destinations=("episodes",),
        created_at=epoch - 9,
        review_at=epoch + 86_400,
        expires_at=epoch + 2_592_000,
    )
    held_workflow = _synthetic_observation("held-workflow", observed_at=epoch - 2)
    held_safety = _synthetic_observation("held-safety", observed_at=epoch - 1)
    cases = (
        HeldOutLessonCase(
            case_id="synthetic-abstention",
            subgroup="safety",
            privacy_class="synthetic_public",
            question="What unsupported value should be recalled?",
            source_context=("The value is intentionally absent.", "No oracle is present."),
            expected_answer=None,
            should_abstain=True,
            proposal=proposal,
            development_observations=(dev,),
            held_out_observation=held_safety,
        ),
        HeldOutLessonCase(
            case_id="synthetic-retry",
            subgroup="workflow",
            privacy_class="synthetic_public",
            question="What resolved the synthetic transient export failure?",
            source_context=("The first export attempt failed transiently.", "A retry succeeded."),
            expected_answer="retry once",
            should_abstain=False,
            proposal=proposal,
            development_observations=(dev,),
            held_out_observation=held_workflow,
        ),
    )
    predeclared = datetime.now(UTC)
    return LessonEvaluationPlan(
        suite_name="nerva-e6-1-synthetic",
        cases=cases,
        lane="ci",
        source_revision=revision,
        candidate_id="proposal-overlay-keyword.v1",
        baseline_id="raw-evidence-keyword.v1",
        environment=EvaluationEnvironment.detect(runner_id=runner_id),
        budget=EvaluationBudget(2, 512),
        thresholds=LessonEvaluationThresholds(minimum_quality_delta=0.01),
        retention=RetentionPolicy(
            predeclared_at=_utc_timestamp(predeclared),
            expires_at=_utc_timestamp(predeclared + timedelta(days=14)),
            deletion_behavior="artifact_expiry_only",
        ),
        evaluated_at=epoch,
    )


async def run_synthetic_evaluation(
    *,
    store_root: str | Path,
    report_path: str | Path,
    revision: str,
    runner_id: str,
) -> LessonEvaluationReport:
    """Run the fixed synthetic-public CI fixture and retain its report."""

    epoch = time.time()
    plan = _synthetic_plan(revision=revision, runner_id=runner_id, epoch=epoch)

    async def candidate(runner_input: LessonRunnerInput) -> str:
        if runner_input.case_id == "synthetic-retry":
            return "retry once"
        return "I don't know"

    async def baseline(runner_input: LessonRunnerInput) -> str:
        return "I don't know"

    report = await evaluate_lesson_plan(
        plan,
        store=BenchmarkStore(store_root),
        candidate_runner=candidate,
        baseline_runner=baseline,
    )
    output = Path(report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.to_json() + "\n", encoding="utf-8")
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--runner-id", default="github-e6-1")
    parser.add_argument("--fail-on-regression", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = asyncio.run(
        run_synthetic_evaluation(
            store_root=args.store_root,
            report_path=args.json_out,
            revision=args.revision,
            runner_id=args.runner_id,
        )
    )
    print(report.to_json())
    return 1 if args.fail_on_regression and not report.success else 0


if __name__ == "__main__":
    sys.exit(main())
