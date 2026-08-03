"""Deterministic, privacy-safe comparison reports for Cortex shadow decisions.

The harness evaluates the current router against explicit synthetic or redacted
fixture expectations. It is evaluation-only: it does not change route
selection, persist traces, authorize actions, execute work, or mark tasks
complete.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from agents.core.cortex_decision import DecisionRecord, DecisionRequest, EvidenceValue

FixturePrivacyClass = Literal["synthetic_public", "redacted_local"]


@dataclass(frozen=True)
class ComparisonCase:
    """One explicitly privacy-classified router baseline fixture."""

    case_id: str
    text: str
    expected_primary: str
    expected_source: str
    privacy_class: FixturePrivacyClass = "synthetic_public"

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("comparison case_id cannot be empty")
        if not self.text.strip():
            raise ValueError("comparison fixture text cannot be empty")
        if not self.expected_primary.strip():
            raise ValueError("expected_primary cannot be empty")
        if not self.expected_source.strip():
            raise ValueError("expected_source cannot be empty")
        if self.privacy_class not in {"synthetic_public", "redacted_local"}:
            raise ValueError("comparison fixtures must be synthetic or redacted")


@dataclass(frozen=True)
class ComparisonCaseResult:
    """Privacy-minimised result for one comparison case."""

    case_id: str
    request_digest: str
    decision_fingerprint: str | None
    actual_primary: str | None
    expected_primary: str
    actual_source: str | None
    expected_source: str
    primary_match: bool
    source_match: bool
    candidate_count: int
    fallback_count: int
    hard_rejection_count: int
    failure_type: str | None = None


@dataclass(frozen=True)
class ComparisonReport:
    """Canonical aggregate baseline over current-router shadow records."""

    baseline_id: str
    cases: tuple[ComparisonCaseResult, ...]
    primary_agreement: EvidenceValue
    source_agreement: EvidenceValue
    average_candidate_count: EvidenceValue
    fallback_case_count: int
    general_case_count: int
    failure_count: int
    source_distribution: tuple[tuple[str, int], ...]
    latency: EvidenceValue = field(
        default_factory=lambda: EvidenceValue("not_measured")
    )
    cost: EvidenceValue = field(default_factory=lambda: EvidenceValue("not_measured"))
    real_outcome_quality: EvidenceValue = field(
        default_factory=lambda: EvidenceValue("not_measured")
    )
    schema: str = field(default="nerva.cortex.comparison.v1", init=False)
    authority: str = field(default="evaluation_only", init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

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


class RouterProtocol(Protocol):
    async def classify(self, text: str, agents: dict[str, Any]) -> Any: ...


async def compare_router(
    *,
    router: RouterProtocol,
    cases: Sequence[ComparisonCase],
    agents: Mapping[str, Any],
    baseline_id: str,
) -> ComparisonReport:
    """Evaluate current routing without altering it or retaining request text."""

    if not baseline_id.strip():
        raise ValueError("baseline_id cannot be empty")
    ordered_cases = tuple(sorted(cases, key=lambda item: item.case_id))
    if not ordered_cases:
        raise ValueError("at least one comparison case is required")
    case_ids = [case.case_id for case in ordered_cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("comparison case_id values must be unique")

    agent_map = {str(key): value for key, value in agents.items()}
    results: list[ComparisonCaseResult] = []
    for case in ordered_cases:
        request_digest = DecisionRequest.from_input(case.text, agent_map).text_digest
        try:
            intent = await router.classify(case.text, agent_map)
            record = DecisionRecord.from_intent(
                text=case.text,
                agents=agent_map,
                intent=intent,
            )
            actual_primary = record.selected_route
            actual_source = record.source
            results.append(
                ComparisonCaseResult(
                    case_id=case.case_id,
                    request_digest=request_digest,
                    decision_fingerprint=record.replay_fingerprint,
                    actual_primary=actual_primary,
                    expected_primary=case.expected_primary,
                    actual_source=actual_source,
                    expected_source=case.expected_source,
                    primary_match=actual_primary == case.expected_primary,
                    source_match=actual_source == case.expected_source,
                    candidate_count=len(record.candidates),
                    fallback_count=len(record.fallbacks),
                    hard_rejection_count=len(record.hard_constraint_rejections),
                )
            )
        except Exception as exc:
            results.append(
                ComparisonCaseResult(
                    case_id=case.case_id,
                    request_digest=request_digest,
                    decision_fingerprint=None,
                    actual_primary=None,
                    expected_primary=case.expected_primary,
                    actual_source=None,
                    expected_source=case.expected_source,
                    primary_match=False,
                    source_match=False,
                    candidate_count=0,
                    fallback_count=0,
                    hard_rejection_count=0,
                    failure_type=type(exc).__name__,
                )
            )

    result_tuple = tuple(results)
    completed = tuple(result for result in result_tuple if result.failure_type is None)
    total = len(result_tuple)
    primary_matches = sum(result.primary_match for result in result_tuple)
    source_matches = sum(result.source_match for result in result_tuple)
    average_candidates = (
        sum(result.candidate_count for result in completed) / len(completed)
        if completed
        else 0.0
    )
    sources = Counter(
        result.actual_source for result in completed if result.actual_source is not None
    )

    return ComparisonReport(
        baseline_id=baseline_id,
        cases=result_tuple,
        primary_agreement=EvidenceValue(
            "measured",
            round(primary_matches / total, 6),
            "fixture.expected_primary",
        ),
        source_agreement=EvidenceValue(
            "measured",
            round(source_matches / total, 6),
            "fixture.expected_source",
        ),
        average_candidate_count=EvidenceValue(
            "measured",
            round(average_candidates, 6),
            "nerva.decision.v1.candidates",
        ),
        fallback_case_count=sum(result.fallback_count > 0 for result in completed),
        general_case_count=sum(
            result.actual_source == "general" for result in completed
        ),
        failure_count=sum(result.failure_type is not None for result in result_tuple),
        source_distribution=tuple(sorted(sources.items())),
    )


def load_comparison_cases(payload: Sequence[Mapping[str, Any]]) -> tuple[ComparisonCase, ...]:
    """Parse a JSON-compatible fixture list into validated cases."""

    cases: list[ComparisonCase] = []
    for item in payload:
        cases.append(
            ComparisonCase(
                case_id=str(item["case_id"]),
                text=str(item["text"]),
                expected_primary=str(item["expected_primary"]),
                expected_source=str(item["expected_source"]),
                privacy_class=str(item.get("privacy_class", "synthetic_public")),
            )
        )
    return tuple(cases)
