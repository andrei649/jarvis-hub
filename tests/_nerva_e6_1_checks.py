"""Count-neutral hostile checks for Nerva E6.1 lesson evaluation.

The repository pins the collected-test ledger, so these assertions are invoked
explicitly from the existing Daily Reflection test instead of adding a new
pytest collection target.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import suppress
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

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
    _materialize_cases,
    _suite_fingerprint,
    _synthetic_plan,
    evaluate_lesson_plan,
    load_lesson_evaluation_report,
    retention_disposition,
    run_synthetic_evaluation,
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


def _proposal(
    dev,
    *,
    created_at: float = 800.0,
    expires_at: float = 10_000.0,
):
    return propose_lesson(
        observations=(dev,),
        claim="Retry once after a transient export failure.",
        scope="export-workflow",
        proposed_destinations=("episodes",),
        created_at=created_at,
        review_at=created_at + 100.0,
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
    plan = replace(
        _plan((answerable, abstention)),
        budget=EvaluationBudget(max_context_items=3, max_context_chars=512),
    )
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
        assert len(candidate_input.context_items) == len(baseline_input.context_items)
        assert len(candidate_input.context_items) <= candidate_input.max_context_items
        assert len(baseline_input.context_items) <= baseline_input.max_context_items
        assert sum(map(len, candidate_input.context_items)) <= candidate_input.max_context_chars
        assert sum(map(len, baseline_input.context_items)) <= baseline_input.max_context_chars
        proposal_claim = plan.cases[
            next(
                index
                for index, item in enumerate(plan.cases)
                if item.case_id == candidate_input.case_id
            )
        ].proposal.claim
        differences = tuple(
            index
            for index, (candidate_item, baseline_item) in enumerate(
                zip(candidate_input.context_items, baseline_input.context_items, strict=True)
            )
            if candidate_item != baseline_item
        )
        assert len(differences) == 1
        assert candidate_input.context_items[differences[0]] == proposal_claim

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

    cross_case_dev = _observation("cross-case-dev", observed_at=1_100.0)
    first = replace(
        _case("cross-case-a"),
        held_out_observation=cross_case_dev,
    )
    second = _case("cross-case-b", dev=cross_case_dev)
    with pytest.raises(ValueError, match="held-out split overlaps development"):
        _plan((first, second))

    with pytest.raises(ValueError, match="future-dated held-out outcome evidence"):
        _plan((_case("future-held", observed_at=1_350.0),), evaluated_at=1_200.0)

    future_dev = _observation("future-dev", observed_at=1_350.0)
    with pytest.raises(ValueError, match="future-dated development outcome evidence"):
        _plan((_case("future-development", dev=future_dev),), evaluated_at=1_200.0)

    chronology = _case("proposal-chronology")
    dev = chronology.development_observations[0]
    with pytest.raises(ValueError, match="proposal postdates evaluation"):
        _plan(
            (replace(chronology, proposal=_proposal(dev, created_at=1_250.0)),),
            evaluated_at=1_200.0,
        )
    with pytest.raises(ValueError, match="proposal must predate held-out evidence"):
        _plan(
            (replace(chronology, proposal=_proposal(dev, created_at=950.0)),),
            evaluated_at=1_200.0,
        )

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
    stale = _case("stale", observed_at=1_001.0)
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

    duplicate_member = '{"run_id":' + json.dumps(report.run_id) + "," + report.to_json()[1:]
    with pytest.raises(ValueError, match="valid JSON"):
        load_lesson_evaluation_report(duplicate_member, plan=plan, store=store)
    with pytest.raises(ValueError, match="valid JSON"):
        load_lesson_evaluation_report('{"run_id":NaN}', plan=plan, store=store)

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


async def _check_retained_json_decoding_is_strict(tmp_path: Path) -> None:
    case = _case("strict-retained")
    plan = _plan((case,), thresholds=LessonEvaluationThresholds())
    report, store, _, _ = await _evaluate(
        tmp_path,
        plan,
        {"strict-retained": "answer-strict-retained"},
        {"strict-retained": "answer-strict-retained"},
        store_name="strict-retained",
    )
    store_root = tmp_path / "strict-retained"
    runs_path = store_root / "suites" / plan.suite_name / "runs.jsonl"
    suite_path = store_root / "suites" / plan.suite_name / "v1.jsonl"
    run_line = runs_path.read_text(encoding="utf-8").strip()
    suite_line = suite_path.read_text(encoding="utf-8").strip()
    hostile_payloads = (
        (
            runs_path,
            '{"run_id":' + json.dumps(report.run_id) + "," + run_line[1:],
            "retained run JSONL must use strict JSON",
        ),
        (
            runs_path,
            run_line[:-1] + ',"hostile_nonfinite":NaN}',
            "retained run JSONL must use strict JSON",
        ),
        (
            suite_path,
            '{"case_id":' + json.dumps(case.case_id) + "," + suite_line[1:],
            "retained suite JSONL must use strict JSON",
        ),
        (
            suite_path,
            suite_line[:-1] + ',"hostile_nonfinite":NaN}',
            "retained suite JSONL must use strict JSON",
        ),
    )
    for path, hostile, error in hostile_payloads:
        original = path.read_bytes()
        try:
            path.write_text(hostile + "\n", encoding="utf-8")
            with pytest.raises(ValueError, match=error):
                validate_report_against_retained(report, plan=plan, store=store)
            with pytest.raises(ValueError, match=error):
                load_lesson_evaluation_report(report.to_json(), plan=plan, store=store)
        finally:
            path.write_bytes(original)


async def _check_strict_preflight_is_unconditional(tmp_path: Path) -> None:
    for label in ("run", "suite"):
        case = _case(f"auto-preflight-{label}")
        plan = _plan((case,), thresholds=LessonEvaluationThresholds())
        report, store, _, _ = await _evaluate(
            tmp_path,
            plan,
            {case.case_id: f"answer-{case.case_id}"},
            {case.case_id: f"answer-{case.case_id}"},
            store_name=f"auto-preflight-{label}",
        )
        store_root = tmp_path / f"auto-preflight-{label}"
        suite_dir = store_root / "suites" / plan.suite_name
        if label == "run":
            path = suite_dir / "runs.jsonl"
            line = path.read_text(encoding="utf-8").strip()
            hostile = '{"run_id":' + json.dumps(report.run_id) + "," + line[1:]
            error = "retained run JSONL must use strict JSON"
        else:
            path = suite_dir / "v1.jsonl"
            line = path.read_text(encoding="utf-8").strip()
            hostile = '{"case_id":' + json.dumps(case.case_id) + "," + line[1:]
            error = "retained suite JSONL must use strict JSON"
        path.write_text(hostile + "\n", encoding="utf-8")
        before = _tree_snapshot(store_root)
        calls = 0

        async def must_not_run(
            _runner_input,
            fixed_answer=f"answer-{case.case_id}",
        ):
            nonlocal calls
            calls += 1
            return fixed_answer

        with pytest.raises(ValueError, match=error):
            await evaluate_lesson_plan(
                plan,
                store=store,
                candidate_runner=must_not_run,
                baseline_runner=must_not_run,
                now=lambda: _NOW,
            )
        assert calls == 0
        assert _tree_snapshot(store_root) == before


def _tree_snapshot(root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    if not root.exists():
        return (), {}
    directories = tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_dir())
    )
    files = {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    return directories, files


async def _check_duplicate_run_id_is_rejected_before_mutation(tmp_path: Path) -> None:
    case = _case("duplicate")
    plan = _plan((case,), thresholds=LessonEvaluationThresholds())
    report, store, _, _ = await _evaluate(
        tmp_path,
        plan,
        {"duplicate": "answer-duplicate"},
        {"duplicate": "answer-duplicate"},
        store_name="duplicate",
    )
    assert report.run_id == "run-duplicate"
    store_root = tmp_path / "duplicate"
    before = _tree_snapshot(store_root)
    calls = 0

    async def must_not_run(_runner_input):
        nonlocal calls
        calls += 1
        return "answer-duplicate"

    with pytest.raises(ValueError, match="run id already exists"):
        await evaluate_lesson_plan(
            plan,
            store=store,
            candidate_runner=must_not_run,
            baseline_runner=must_not_run,
            now=lambda: _NOW,
            run_id="run-duplicate",
        )
    assert calls == 0
    assert _tree_snapshot(store_root) == before
    assert len(store.runs(plan.suite_name)) == 1
    assert store.versions(plan.suite_name) == [1]


async def _check_auto_run_id_collision_is_rejected_before_mutation(
    tmp_path: Path,
) -> None:
    case = _case("auto-duplicate")
    plan = _plan((case,), thresholds=LessonEvaluationThresholds())
    report, store, _, _ = await _evaluate(
        tmp_path,
        plan,
        {case.case_id: f"answer-{case.case_id}"},
        {case.case_id: f"answer-{case.case_id}"},
        store_name="deadbeefcafe",
    )
    assert report.run_id == "run-deadbeefcafe"
    store_root = tmp_path / "deadbeefcafe"
    before = _tree_snapshot(store_root)
    calls = 0

    async def must_not_run(_runner_input):
        nonlocal calls
        calls += 1
        return f"answer-{case.case_id}"

    with (
        patch(
            "uuid.uuid4",
            return_value=UUID("deadbeef-cafe-0000-0000-000000000000"),
        ),
        pytest.raises(ValueError, match="run id already exists"),
    ):
        await evaluate_lesson_plan(
            plan,
            store=store,
            candidate_runner=must_not_run,
            baseline_runner=must_not_run,
            now=lambda: _NOW,
        )
    assert calls == 0
    assert store.versions(plan.suite_name) == [1]
    assert len(store.runs(plan.suite_name)) == 1
    assert _tree_snapshot(store_root) == before


async def _check_execution_environment_is_redetected(tmp_path: Path) -> None:
    case = _case("forged-environment")
    plan = _plan((case,), thresholds=LessonEvaluationThresholds())
    forged_plan = replace(
        plan,
        environment=replace(
            plan.environment,
            python_version="forged-python",
            platform_system="forged-platform",
        ),
    )
    store_root = tmp_path / "forged-environment"
    store = BenchmarkStore(store_root)
    before = _tree_snapshot(store_root)
    calls = 0

    async def must_not_run(_runner_input):
        nonlocal calls
        calls += 1
        return "answer-forged-environment"

    with pytest.raises(ValueError, match="detected host"):
        await evaluate_lesson_plan(
            forged_plan,
            store=store,
            candidate_runner=must_not_run,
            baseline_runner=must_not_run,
            now=lambda: _NOW,
            run_id="run-forged-environment",
        )
    assert calls == 0
    assert _tree_snapshot(store_root) == before


async def _check_report_output_is_create_once(tmp_path: Path) -> None:
    plain_store = tmp_path / "plain-existing-store"
    plain_report = tmp_path / "plain-existing-report.json"
    plain_report.write_bytes(b"pre-existing-report-sentinel")
    plain_before = _tree_snapshot(plain_store)
    calls = 0

    async def counting_evaluator(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await evaluate_lesson_plan(*args, **kwargs)

    with (
        patch(
            "agents.core.reflection_evaluation.evaluate_lesson_plan",
            side_effect=counting_evaluator,
        ),
        pytest.raises(ValueError, match="report path already exists"),
    ):
        await run_synthetic_evaluation(
            store_root=plain_store,
            report_path=plain_report,
            revision=_REVISION,
            runner_id="pytest-e6-1",
        )
    assert calls == 0
    assert plain_report.read_bytes() == b"pre-existing-report-sentinel"
    assert _tree_snapshot(plain_store) == plain_before

    case = _case("hardlink-alias")
    plan = _plan((case,), thresholds=LessonEvaluationThresholds())
    _, _, _, _ = await _evaluate(
        tmp_path,
        plan,
        {"hardlink-alias": "answer-hardlink-alias"},
        {"hardlink-alias": "answer-hardlink-alias"},
        store_name="hardlink-store",
    )
    hardlink_store = tmp_path / "hardlink-store"
    runs_path = hardlink_store / "suites" / plan.suite_name / "runs.jsonl"
    suite_path = hardlink_store / "suites" / plan.suite_name / "v1.jsonl"
    for label, retained_path in (("runs", runs_path), ("suite", suite_path)):
        hardlink_report = tmp_path / f"hardlink-{label}-report.json"
        os.link(retained_path, hardlink_report)
        store_before = _tree_snapshot(hardlink_store)
        report_before = hardlink_report.read_bytes()
        calls = 0
        with (
            patch(
                "agents.core.reflection_evaluation.evaluate_lesson_plan",
                side_effect=counting_evaluator,
            ),
            pytest.raises(ValueError, match="report path already exists"),
        ):
            await run_synthetic_evaluation(
                store_root=hardlink_store,
                report_path=hardlink_report,
                revision=_REVISION,
                runner_id="pytest-e6-1",
            )
        assert calls == 0
        assert hardlink_report.samefile(retained_path)
        assert hardlink_report.read_bytes() == report_before
        assert _tree_snapshot(hardlink_store) == store_before
        hardlink_report.unlink()


async def _check_report_is_reserved_before_evaluation(tmp_path: Path) -> None:
    store_root = tmp_path / "reservation-store"
    report_path = tmp_path / "reserved-report.json"
    calls = 0

    async def stop_after_reservation(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        assert report_path.is_dir()
        assert tuple(report_path.iterdir()) == ()
        with pytest.raises(FileExistsError):
            report_path.mkdir()
        raise RuntimeError("stop after reservation")

    with (
        patch(
            "agents.core.reflection_evaluation.evaluate_lesson_plan",
            side_effect=stop_after_reservation,
        ),
        pytest.raises(RuntimeError, match="stop after reservation"),
    ):
        await run_synthetic_evaluation(
            store_root=store_root,
            report_path=report_path,
            revision=_REVISION,
            runner_id="pytest-e6-1",
        )
    assert calls == 1
    assert not report_path.exists()
    assert _tree_snapshot(store_root) == ((), {})


async def _check_reservation_tampering_fails_closed(tmp_path: Path) -> None:
    store_root = tmp_path / "reservation-tamper-store"
    report_path = tmp_path / "reservation-tamper-report.json"
    retained_after_evaluation = None

    async def tamper_with_reservation(*args, **kwargs):
        nonlocal retained_after_evaluation
        report = await evaluate_lesson_plan(*args, **kwargs)
        retained_after_evaluation = _tree_snapshot(store_root)
        (report_path / "intruder").write_bytes(b"tampered-reservation")
        return report

    with (
        patch(
            "agents.core.reflection_evaluation.evaluate_lesson_plan",
            side_effect=tamper_with_reservation,
        ),
        pytest.raises(ValueError, match="namespace reservation changed"),
    ):
        await run_synthetic_evaluation(
            store_root=store_root,
            report_path=report_path,
            revision=_REVISION,
            runner_id="pytest-e6-1",
        )
    assert retained_after_evaluation is not None
    assert _tree_snapshot(store_root) == retained_after_evaluation
    assert report_path.is_dir()
    assert (report_path / "intruder").read_bytes() == b"tampered-reservation"


async def _check_reverse_hardlinks_are_blocked_during_evaluation(tmp_path: Path) -> None:
    for label in ("runs", "suite"):
        store_root = tmp_path / f"reverse-hardlink-{label}"
        report_path = tmp_path / f"reverse-hardlink-{label}-report.json"
        link_blocked = False

        async def attempt_reverse_hardlink(
            *args,
            fixed_store_root=store_root,
            fixed_label=label,
            fixed_report_path=report_path,
            **kwargs,
        ):
            nonlocal link_blocked
            suite_dir = fixed_store_root / "suites" / "nerva-e6-1-synthetic"
            suite_dir.mkdir(parents=True, exist_ok=True)
            target = suite_dir / ("runs.jsonl" if fixed_label == "runs" else "v1.jsonl")
            try:
                os.link(fixed_report_path, target)
            except OSError:
                link_blocked = True
            return await evaluate_lesson_plan(*args, **kwargs)

        with patch(
            "agents.core.reflection_evaluation.evaluate_lesson_plan",
            side_effect=attempt_reverse_hardlink,
        ):
            report = await run_synthetic_evaluation(
                store_root=store_root,
                report_path=report_path,
                revision=_REVISION,
                runner_id="pytest-e6-1",
            )
        assert link_blocked is True
        assert report.success is True
        assert json.loads(report_path.read_text(encoding="utf-8"))["success"] is True
        store = BenchmarkStore(store_root)
        assert len(store.runs("nerva-e6-1-synthetic")) == 1
        assert len(store.load_suite("nerva-e6-1-synthetic", 1)) == 2


async def _check_final_output_collision_does_not_write_store(tmp_path: Path) -> None:
    store_root = tmp_path / "final-collision-store"
    report_path = tmp_path / "final-collision-report.json"
    original_open = Path.open
    retained_before_collision: bytes | None = None
    runs_path = store_root / "suites" / "nerva-e6-1-synthetic" / "runs.jsonl"

    def collide_at_final_open(path, *args, **kwargs):
        nonlocal retained_before_collision
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == report_path and mode == "x":
            retained_before_collision = runs_path.read_bytes()
            os.link(runs_path, report_path)
        return original_open(path, *args, **kwargs)

    with (
        patch.object(Path, "open", new=collide_at_final_open),
        pytest.raises(ValueError, match="collided after namespace reservation"),
    ):
        await run_synthetic_evaluation(
            store_root=store_root,
            report_path=report_path,
            revision=_REVISION,
            runner_id="pytest-e6-1",
        )
    assert retained_before_collision is not None
    assert report_path.samefile(runs_path)
    assert runs_path.read_bytes() == retained_before_collision


async def _check_report_path_swap_cannot_redirect_write(tmp_path: Path) -> None:
    store_root = tmp_path / "swap-store"
    report_path = tmp_path / "swap-report.json"
    retained_bytes: bytes | None = None
    path_changed = False

    async def evaluate_then_swap(*args, **kwargs):
        nonlocal path_changed, retained_bytes
        report = await evaluate_lesson_plan(*args, **kwargs)
        runs_path = store_root / "suites" / "nerva-e6-1-synthetic" / "runs.jsonl"
        retained_bytes = runs_path.read_bytes()
        try:
            report_path.unlink()
        except OSError:
            return report
        path_changed = True
        with suppress(OSError):
            os.link(runs_path, report_path)
        return report

    failure: ValueError | None = None
    result = None
    with patch(
        "agents.core.reflection_evaluation.evaluate_lesson_plan",
        side_effect=evaluate_then_swap,
    ):
        try:
            result = await run_synthetic_evaluation(
                store_root=store_root,
                report_path=report_path,
                revision=_REVISION,
                runner_id="pytest-e6-1",
            )
        except ValueError as exc:
            failure = exc

    runs_path = store_root / "suites" / "nerva-e6-1-synthetic" / "runs.jsonl"
    assert retained_bytes is not None
    assert runs_path.read_bytes() == retained_bytes
    if path_changed:
        assert failure is not None
        assert "namespace reservation changed" in str(failure)
        if report_path.exists():
            assert report_path.samefile(runs_path)
            assert report_path.read_bytes() == retained_bytes
    else:
        assert failure is None
        assert result is not None and result.success is True
        assert json.loads(report_path.read_text(encoding="utf-8"))["success"] is True


async def _check_disjoint_report_path_and_deterministic_fixture(tmp_path: Path) -> None:
    for label, report_from in (
        ("equal", lambda sandbox, store: store),
        ("descendant", lambda sandbox, store: store / "report.json"),
        ("ancestor", lambda sandbox, store: sandbox),
    ):
        sandbox = tmp_path / f"path-overlap-{label}"
        store_root = sandbox / "store"
        report_path = report_from(sandbox, store_root)
        before = _tree_snapshot(sandbox)
        with patch("agents.core.reflection_evaluation.evaluate_lesson_plan") as evaluator:
            with pytest.raises(ValueError, match="overlap"):
                await run_synthetic_evaluation(
                    store_root=store_root,
                    report_path=report_path,
                    revision=_REVISION,
                    runner_id="pytest-e6-1",
                )
            evaluator.assert_not_called()
        assert _tree_snapshot(sandbox) == before

    first_start = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
    second_start = first_start + timedelta(days=1)
    first = _synthetic_plan(
        revision=_REVISION,
        runner_id="pytest-e6-1",
        retention_started_at=first_start,
    )
    second = _synthetic_plan(
        revision=_REVISION,
        runner_id="pytest-e6-1",
        retention_started_at=second_start,
    )
    assert first.fixture_digest == second.fixture_digest
    assert _suite_fingerprint(_materialize_cases(first)) == _suite_fingerprint(
        _materialize_cases(second)
    )
    assert first.fingerprint == second.fingerprint
    assert first.retention.fingerprint != second.retention.fingerprint
    assert first.retention.contract_fingerprint == second.retention.contract_fingerprint


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
        "create-once",
        "deterministic logical fixture time",
        "wall-clock retention",
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
    await _check_retained_json_decoding_is_strict(tmp_path)
    await _check_strict_preflight_is_unconditional(tmp_path)
    await _check_duplicate_run_id_is_rejected_before_mutation(tmp_path)
    await _check_auto_run_id_collision_is_rejected_before_mutation(tmp_path)
    await _check_execution_environment_is_redetected(tmp_path)
    await _check_report_output_is_create_once(tmp_path)
    await _check_report_is_reserved_before_evaluation(tmp_path)
    await _check_reservation_tampering_fails_closed(tmp_path)
    await _check_reverse_hardlinks_are_blocked_during_evaluation(tmp_path)
    await _check_final_output_collision_does_not_write_store(tmp_path)
    await _check_report_path_swap_cannot_redirect_write(tmp_path)
    await _check_disjoint_report_path_and_deterministic_fixture(tmp_path)
    _check_workflow_and_docs(Path(__file__).resolve().parent.parent)
