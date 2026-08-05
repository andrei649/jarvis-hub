"""Count-neutral hostile checks for Nerva E6.1 lesson evaluation.

The repository pins the collected-test ledger, so these assertions are invoked
explicitly from the existing Daily Reflection test instead of adding a new
pytest collection target.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from agents.core.memory.atlas_snapshot import AtlasConfidence
from agents.core.memory.episodes import EpisodeReference
from agents.core.observability.benchmark import BenchmarkCase, BenchmarkStore
from agents.core.reflection_evaluation import (
    EvaluationBudget,
    EvaluationEnvironment,
    EvaluationMetrics,
    HeldOutLessonCase,
    LessonEvaluationPlan,
    LessonEvaluationReport,
    LessonEvaluationThresholds,
    RetentionPolicy,
    evaluate_lesson_plan,
    load_lesson_evaluation_report,
    retention_disposition,
    validate_report_against_retained,
)
from agents.core.reflection_lesson import compare_outcome, propose_lesson

_REVISION = "a" * 40
_NOW = "2026-08-05T22:00:00.000Z"
_PREDECLARED = "2026-08-05T21:00:00.000Z"
_EXPIRES = "2026-08-19T21:00:00.000Z"


def _reference(
    key: str,
    role: str,
    occurred_at: float,
    *,
    privacy_class: str = "public",
) -> EpisodeReference:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return EpisodeReference.build(
        role=role,  # type: ignore[arg-type]
        source_id=f"source-{key}",
        record_id=f"record-{key}-{role}",
        source_kind="synthetic_public",
        source_schema="nerva.episode.v1",
        privacy_class=privacy_class,  # type: ignore[arg-type]
        integrity_sha256=digest,
        occurred_at=occurred_at,
        deletion_root_id=f"root-{key}",
        confidence=AtlasConfidence("unknown"),
    )


def _observation(
    key: str,
    status: str = "confirmed",
    *,
    observed_at: float = 700.0,
    privacy_class: str = "public",
):
    expected = _reference(
        f"{key}-decision", "decision", observed_at - 200, privacy_class=privacy_class
    )
    first = _reference(
        f"{key}-outcome-a", "outcome", observed_at - 100, privacy_class=privacy_class
    )
    observed = (first,)
    verdicts: dict[str, bool] = {}
    if status == "confirmed":
        verdicts[first.reference_id] = True
    elif status == "refuted":
        verdicts[first.reference_id] = False
    elif status == "contradictory":
        second = _reference(
            f"{key}-outcome-b", "outcome", observed_at - 90, privacy_class=privacy_class
        )
        observed = (first, second)
        verdicts = {first.reference_id: True, second.reference_id: False}
    elif status != "insufficient_evidence":
        raise AssertionError(f"unknown fixture status: {status}")
    return compare_outcome(
        episode_id=f"episode-{key}",
        expected_reference=expected,
        observed_references=observed,
        matches_expectation=verdicts,
        environment="hermetic-e6-1",
        observed_at=observed_at,
        created_at=observed_at + 1,
    )


def _proposal(dev, *, expires_at: float = 10_000.0):
    return propose_lesson(
        observations=(dev,),
        claim="Retry once after a transient export failure.",
        scope="export-workflow",
        proposed_destinations=("episodes",),
        created_at=800.0,
        review_at=900.0,
        expires_at=expires_at,
    )


def _case(
    case_id: str,
    *,
    subgroup: str = "workflow",
    status: str = "confirmed",
    should_abstain: bool = False,
    dev=None,
    held_out=None,
    privacy_class: str = "synthetic_public",
    observed_at: float = 1_100.0,
) -> HeldOutLessonCase:
    dev = dev or _observation(f"{case_id}-dev", observed_at=700.0)
    proposal = _proposal(dev)
    if held_out is ...:
        held_out = None
    elif held_out is None:
        held_out = _observation(f"{case_id}-held", status=status, observed_at=observed_at)
    return HeldOutLessonCase(
        case_id=case_id,
        subgroup=subgroup,
        privacy_class=privacy_class,  # type: ignore[arg-type]
        question=f"question-{case_id}-secret-sentinel",
        source_context=(
            f"evidence-{case_id}-secret-sentinel",
            "A transient export failure was observed.",
        ),
        expected_answer=None if should_abstain else f"answer-{case_id}",
        should_abstain=should_abstain,
        proposal=proposal,
        development_observations=(dev,),
        held_out_observation=held_out,
    )


def _plan(
    cases: tuple[HeldOutLessonCase, ...],
    *,
    lane: str = "ci",
    evaluated_at: float = 1_200.0,
    thresholds: LessonEvaluationThresholds | None = None,
) -> LessonEvaluationPlan:
    return LessonEvaluationPlan(
        suite_name="nerva-e6-1-held-out",
        cases=tuple(sorted(cases, key=lambda item: item.case_id)),
        lane=lane,  # type: ignore[arg-type]
        source_revision=_REVISION,
        candidate_id="proposal-overlay-keyword.v1",
        baseline_id="raw-evidence-keyword.v1",
        environment=EvaluationEnvironment.detect(runner_id="pytest-e6-1"),
        budget=EvaluationBudget(max_context_items=2, max_context_chars=256),
        thresholds=thresholds or LessonEvaluationThresholds(minimum_quality_delta=0.01),
        retention=RetentionPolicy(
            predeclared_at=_PREDECLARED,
            expires_at=_EXPIRES,
            deletion_behavior="artifact_expiry_only",
        ),
        evaluated_at=evaluated_at,
    )


async def _evaluate(
    tmp_path: Path,
    plan: LessonEvaluationPlan,
    candidate_answers: dict[str, object],
    baseline_answers: dict[str, object],
    *,
    store_name: str,
):
    seen_candidate = []
    seen_baseline = []

    async def candidate(runner_input):
        seen_candidate.append(runner_input)
        answer = candidate_answers[runner_input.case_id]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def baseline(runner_input):
        seen_baseline.append(runner_input)
        answer = baseline_answers[runner_input.case_id]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    store = BenchmarkStore(tmp_path / store_name)
    report = await evaluate_lesson_plan(
        plan,
        store=store,
        candidate_runner=candidate,
        baseline_runner=baseline,
        now=lambda: _NOW,
        run_id=f"run-{store_name}",
    )
    return report, store, tuple(seen_candidate), tuple(seen_baseline)


async def _check_happy_path_and_oracle_isolation(tmp_path: Path) -> None:
    answerable = _case("answerable", subgroup="workflow")
    abstention = _case("abstention", subgroup="safety", should_abstain=True)
    plan = _plan((answerable, abstention))
    report, store, candidate_inputs, baseline_inputs = await _evaluate(
        tmp_path,
        plan,
        {"answerable": "answer-answerable", "abstention": "I don't know"},
        {"answerable": "I don't know", "abstention": "I don't know"},
        store_name="happy",
    )

    assert report.success is True
    assert report.metrics.candidate.quality == 1.0
    assert report.metrics.baseline.quality == 0.5
    assert report.metrics.quality_delta == 0.5
    assert report.authority == "evaluation_only"
    assert report.evidence_label == "synthetic_hermetic"
    assert not report.can_promote_lesson
    assert not report.can_write_memory
    assert not report.can_change_routing
    assert not report.can_authorize
    assert not report.can_execute
    assert not report.can_mark_complete

    assert len(candidate_inputs) == len(baseline_inputs) == 2
    forbidden = {
        "expected",
        "expected_answer",
        "should_abstain",
        "held_out",
        "held_out_observation",
        "oracle",
    }
    for candidate_input, baseline_input in zip(candidate_inputs, baseline_inputs, strict=True):
        names = {field.name for field in fields(candidate_input)}
        assert names.isdisjoint(forbidden)
        assert candidate_input.question == baseline_input.question
        assert candidate_input.source_set_digest == baseline_input.source_set_digest
        assert candidate_input.max_context_items == baseline_input.max_context_items
        assert candidate_input.max_context_chars == baseline_input.max_context_chars
        assert len(candidate_input.context_items) <= candidate_input.max_context_items
        assert len(baseline_input.context_items) <= baseline_input.max_context_items
        assert sum(map(len, candidate_input.context_items)) <= candidate_input.max_context_chars
        assert sum(map(len, baseline_input.context_items)) <= baseline_input.max_context_chars

    runs = store.runs(plan.suite_name)
    assert len(runs) == 1
    run = runs[0]
    assert run.source_revision == _REVISION
    assert run.candidate_id == plan.candidate_id
    assert run.baseline_id == plan.baseline_id
    assert run.authority == "evaluation_only"
    assert all(result.candidate is not None for result in run.results)
    assert all(result.baseline is not None for result in run.results)
    retained_refs = {
        ref
        for result in run.results
        for evidence in (result.candidate, result.baseline)
        if evidence is not None
        for ref in evidence.artifact_refs
    }
    assert "nerva://e6.1/classification/correct" in retained_refs
    assert "nerva://e6.1/classification/abstained" in retained_refs

    serialized = report.to_json()
    for secret in (
        answerable.question,
        answerable.source_context[0],
        answerable.expected_answer,
        answerable.proposal.claim,
        "secret-sentinel",
    ):
        assert secret not in serialized

    validate_report_against_retained(report, plan=plan, store=store)
    loaded = load_lesson_evaluation_report(serialized, plan=plan, store=store)
    assert loaded == report

    constructor_kwargs = {
        field.name: getattr(report, field.name)
        for field in fields(report)
        if field.init and field.name != "guard"
    }
    with pytest.raises(ValueError, match="trusted evaluator"):
        LessonEvaluationReport(**constructor_kwargs)
    with pytest.raises(ValueError):
        replace(report, can_promote_lesson=True)


def _check_predeclared_split_privacy_and_identity() -> None:
    case = _case("split")
    with pytest.raises(ValueError, match="held-out split overlaps development"):
        replace(case, held_out_observation=case.development_observations[0])

    dev = case.development_observations[0]
    shared_reference_held_out = compare_outcome(
        episode_id="episode-other-held",
        expected_reference=dev.expected_reference,
        observed_references=(_reference("other-held", "outcome", 1_000.0),),
        matches_expectation={},
        environment="hermetic-e6-1",
        observed_at=1_100.0,
        created_at=1_101.0,
    )
    with pytest.raises(ValueError, match="held-out split overlaps development"):
        replace(case, held_out_observation=shared_reference_held_out)

    private_dev = _observation("private-dev", privacy_class="private_local")
    private_proposal = _proposal(private_dev)
    private_held = _observation("private-held", observed_at=1_100.0, privacy_class="private_local")
    with pytest.raises(ValueError, match="synthetic-public fixtures require public"):
        replace(
            case,
            proposal=private_proposal,
            development_observations=(private_dev,),
            held_out_observation=private_held,
        )

    owner_private = replace(
        case,
        case_id="owner-private",
        privacy_class="owner_private_local",
        proposal=private_proposal,
        development_observations=(private_dev,),
        held_out_observation=private_held,
    )
    with pytest.raises(ValueError, match="owner-private fixtures are local-only"):
        _plan((owner_private,), lane="ci")

    with pytest.raises(ValueError, match="exact lowercase Git commit SHA"):
        replace(_plan((case,)), source_revision="ABC123")
    with pytest.raises(ValueError, match="detected environment"):
        EvaluationEnvironment(
            runner_id="forged",
            python_version="3.12",
            platform_system="forged",
            platform_machine="forged",
        )


async def _check_fail_closed_outcomes_and_error_matrix(tmp_path: Path) -> None:
    missing = _case("missing", held_out=...)
    contradictory = _case("contradictory", status="contradictory")
    insufficient = _case("insufficient", status="insufficient_evidence")
    stale = _case("stale", observed_at=900.0)
    plan = replace(
        _plan((missing, contradictory, insufficient, stale), evaluated_at=1_200.0),
        max_outcome_age_seconds=100.0,
    )

    calls = 0

    async def must_not_run(_runner_input):
        nonlocal calls
        calls += 1
        return "invented"

    store = BenchmarkStore(tmp_path / "ineligible")
    report = await evaluate_lesson_plan(
        plan,
        store=store,
        candidate_runner=must_not_run,
        baseline_runner=must_not_run,
        now=lambda: _NOW,
        run_id="run-ineligible",
    )
    assert calls == 0
    assert report.success is False
    reasons = {row.eligibility for row in report.case_results}
    assert reasons == {"missing", "stale", "contradictory", "unverified"}
    assert report.metrics.candidate.unverified == 4
    assert all(row.candidate_classification == "unverified_outcome" for row in report.case_results)
    assert len(store.runs(plan.suite_name)) == 1

    first = _case("candidate-error")
    second = _case("baseline-error", subgroup="safety")
    error_plan = _plan((first, second), thresholds=LessonEvaluationThresholds())
    report, store, candidate_inputs, baseline_inputs = await _evaluate(
        tmp_path,
        error_plan,
        {
            "candidate-error": RuntimeError("candidate-secret-message"),
            "baseline-error": "answer-baseline-error",
        },
        {
            "candidate-error": "answer-candidate-error",
            "baseline-error": RuntimeError("baseline-secret-message"),
        },
        store_name="errors",
    )
    assert len(candidate_inputs) == len(baseline_inputs) == 2
    by_id = {row.case_id: row for row in report.case_results}
    assert by_id["candidate-error"].candidate_classification == "runner_error"
    assert by_id["candidate-error"].baseline_classification == "correct"
    assert by_id["baseline-error"].candidate_classification == "correct"
    assert by_id["baseline-error"].baseline_classification == "runner_error"
    evidence = store.runs(error_plan.suite_name)[0].to_json()
    assert "candidate-secret-message" not in evidence
    assert "baseline-secret-message" not in evidence


async def _check_false_hallucinated_and_subgroup_masking(tmp_path: Path) -> None:
    answerable = _case("false-recall", subgroup="majority")
    abstention = _case("hallucination", subgroup="majority", should_abstain=True)
    minority = _case("minority-regression", subgroup="minority")
    plan = _plan(
        (answerable, abstention, minority),
        thresholds=LessonEvaluationThresholds(minimum_quality_delta=0.0),
    )
    report, store, _, _ = await _evaluate(
        tmp_path,
        plan,
        {
            "false-recall": "answer-false-recall",
            "hallucination": "I don't know",
            "minority-regression": "wrong-but-confident",
        },
        {
            "false-recall": "wrong-baseline",
            "hallucination": "invented-baseline",
            "minority-regression": "answer-minority-regression",
        },
        store_name="subgroups",
    )
    assert report.metrics.candidate.quality > report.metrics.baseline.quality
    assert report.success is False
    subgroup = {item.subgroup: item for item in report.subgroups}
    assert subgroup["minority"].passed is False
    assert "subgroup_quality_regression:minority" in report.failure_reasons
    assert len(store.runs(plan.suite_name)) == 1

    explicit = _plan(
        (
            # A proposal refuted by the held-out outcome remains scorable: if
            # the candidate repeats it, that is explicit false recall.
            _case("explicit-false", status="refuted"),
            _case("explicit-hallucination", should_abstain=True, subgroup="safety"),
        ),
        thresholds=LessonEvaluationThresholds(),
    )
    report, _, _, _ = await _evaluate(
        tmp_path,
        explicit,
        {
            "explicit-false": "wrong-non-abstaining-answer",
            "explicit-hallucination": "invented-recall",
        },
        {
            "explicit-false": "answer-explicit-false",
            "explicit-hallucination": "I don't know",
        },
        store_name="explicit-errors",
    )
    rows = {row.case_id: row for row in report.case_results}
    assert rows["explicit-false"].candidate_classification == "false_recall"
    assert rows["explicit-hallucination"].candidate_classification == "hallucinated_recall"


async def _check_tampering_totals_and_retention(tmp_path: Path) -> None:
    case = _case("tamper")
    plan = _plan((case,), thresholds=LessonEvaluationThresholds())
    report, store, _, _ = await _evaluate(
        tmp_path,
        plan,
        {"tamper": "answer-tamper"},
        {"tamper": "answer-tamper"},
        store_name="tamper",
    )
    with pytest.raises(ValueError, match="metric totals"):
        replace(report.metrics.candidate, total=99)
    with pytest.raises(ValueError, match="comparison metric totals"):
        EvaluationMetrics(
            candidate=report.metrics.candidate,
            baseline=report.metrics.baseline,
            quality_delta=0.5,
            false_recall_delta=0,
            hallucinated_recall_delta=0,
            reliability_delta=0.0,
        )

    payload = json.loads(report.to_json())
    payload["candidate_id"] = "different-candidate.v1"
    with pytest.raises(ValueError, match="retained evidence"):
        load_lesson_evaluation_report(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            plan=plan,
            store=store,
        )

    suite_path = tmp_path / "tamper" / "suites" / plan.suite_name / "v1.jsonl"
    raw_case = json.loads(suite_path.read_text(encoding="utf-8").splitlines()[0])
    stored_case = BenchmarkCase.from_dict(raw_case)
    tampered_case = replace(stored_case, tags=("subgroup-tampered",))
    suite_path.write_text(
        json.dumps(tampered_case.to_dict(lane="ci"), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="retained suite"):
        validate_report_against_retained(report, plan=plan, store=store)

    assert retention_disposition(report, now="2026-08-06T00:00:00.000Z") == "retain"
    assert retention_disposition(report, now="2026-08-20T00:00:00.000Z") == "delete_due"


def _check_workflow_and_docs(repo_root: Path) -> None:
    workflow = (repo_root / ".github/workflows/eval-nightly.yml").read_text(encoding="utf-8")
    assert "nerva-lesson-held-out:" in workflow
    section = workflow.split("nerva-lesson-held-out:", 1)[1]
    assert "--fail-on-regression" in section
    assert "if: ${{ always() }}" in section
    assert "retention-days: 14" in section
    assert "actions/cache/save" not in section
    assert "owner_private_local" not in section
    assert "JARVIS_EVAL_LIVE" not in section

    doc = (repo_root / "docs/nerva2/REFLECTION_E6_1.md").read_text(encoding="utf-8")
    for phrase in (
        "evaluation_only",
        "synthetic/hermetic",
        "false_recall",
        "hallucinated_recall",
        "does not promote",
        "14 days",
        "Residual risks",
    ):
        assert phrase in doc


async def run_e6_1_checks(tmp_path: Path) -> None:
    """Run every bounded E6.1 contract and hostile assertion."""

    _check_predeclared_split_privacy_and_identity()
    await _check_happy_path_and_oracle_isolation(tmp_path)
    await _check_fail_closed_outcomes_and_error_matrix(tmp_path)
    await _check_false_hallucinated_and_subgroup_masking(tmp_path)
    await _check_tampering_totals_and_retention(tmp_path)
    _check_workflow_and_docs(Path(__file__).resolve().parent.parent)
