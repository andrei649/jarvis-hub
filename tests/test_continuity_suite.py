"""Continuity Core (#731) evaluation suite on the E9.0 benchmark harness.

Hermetic: in-process subjects only, a temporary BenchmarkStore root, no network,
no owner data. The suite is ``evaluation_only`` and these tests pin that it
cannot mark anything accepted.
"""

import ast
import asyncio
import inspect
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability import continuity_suite as cs  # noqa: E402
from agents.core.observability.benchmark import (  # noqa: E402
    BenchmarkObservation,
    BenchmarkStore,
    Measurement,
)
from agents.core.observability.continuity_suite import (  # noqa: E402
    BASELINE_ID,
    CANDIDATE_ID,
    CRITERIA,
    SUITE_NAME,
    ContinuityReport,
    ContinuityScenario,
    NaiveRecallBaseline,
    ReferenceContinuityMemory,
    ScenarioEvent,
    ScenarioQuery,
    build_report,
    continuity_cases,
    continuity_scenarios,
    ensure_suite,
    previous_run,
    run_continuity_suite,
    subject_runner,
    suite_fingerprint,
)

_REVISION = "a" * 40
_OTHER_REVISION = "b" * 40

# Pinned: the suite content is immutable per version. Changing any scenario
# must change this value, which is the signal to mint a new suite version.
_PINNED_SUITE_FINGERPRINT = (
    "5a0096d9bb55b96f3ad9ab60368e142c12e35f70516d9ea18a2fb34bbed487de"
)


def _run(store: BenchmarkStore, *, run_id: str, revision: str = _REVISION, **kwargs):
    return asyncio.run(
        run_continuity_suite(store, revision=revision, run_id=run_id, **kwargs)
    )


def test_suite_registers_on_benchmark_store_with_stable_version(tmp_path):
    cases = continuity_cases()
    assert len(cases) == 20
    assert len({case.case_id for case in cases}) == len(cases)
    # Every #731 criterion is covered and nothing outside the criteria list runs.
    assert {case.task_type for case in cases} == set(CRITERIA)
    for case in cases:
        assert case.privacy_class == "synthetic_public"
        assert case.allowed_lanes == ("ci", "local")
        assert case.criterion is not None and case.criterion.kind == "exact"
        assert "continuity" in case.tags
        with pytest.raises(PermissionError):
            case.enforce_lane("cloud")

    store = BenchmarkStore(tmp_path / "store")
    assert ensure_suite(store) == 1
    assert ensure_suite(store) == 1
    assert store.versions(SUITE_NAME) == [1]
    assert store.load_suite(SUITE_NAME, 1) == cases

    # Drifted content mints a new version; the canonical content is restored after.
    store.save_suite(SUITE_NAME, cases[:-1], lane="ci")
    assert store.versions(SUITE_NAME) == [1, 2]
    assert ensure_suite(store) == 3

    with pytest.raises(PermissionError, match="cannot run in 'cloud'"):
        ensure_suite(store, lane="cloud")


def test_same_inputs_produce_the_same_fingerprint():
    assert suite_fingerprint() == suite_fingerprint() == _PINNED_SUITE_FINGERPRINT

    scenarios = continuity_scenarios()
    for scenario in scenarios:
        restored = ContinuityScenario.from_json(scenario.to_json())
        assert restored == scenario
        assert restored.fingerprint == scenario.fingerprint
        assert scenario.to_case().input_text == scenario.to_json()

    changed = replace(scenarios[0], expected="oat-milk")
    assert changed.fingerprint != scenarios[0].fingerprint
    assert suite_fingerprint((changed.to_case(), *continuity_cases()[1:])) != (
        _PINNED_SUITE_FINGERPRINT
    )

    # Hostile payloads fail closed rather than becoming a silently different test.
    payload = json.loads(scenarios[0].to_json())
    payload["schema"] = "nerva.continuity.scenario.v2"
    with pytest.raises(ValueError, match="unsupported scenario schema"):
        ContinuityScenario.from_json(json.dumps(payload))
    payload = json.loads(scenarios[0].to_json())
    payload["events"][0]["op"] = "exfiltrate"
    with pytest.raises(ValueError, match="unsupported scenario event op"):
        ContinuityScenario.from_json(json.dumps(payload))
    payload = json.loads(scenarios[0].to_json())
    payload["events"][0]["value"] = "line one\nline two"
    with pytest.raises(ValueError, match="single trimmed line"):
        ContinuityScenario.from_json(json.dumps(payload))
    payload = json.loads(scenarios[0].to_json())
    payload["notes"] = "extra"
    with pytest.raises(ValueError, match="versioned schema"):
        ContinuityScenario.from_json(json.dumps(payload))
    with pytest.raises(ValueError, match="requires source"):
        ScenarioEvent("observe", person="h", subject="s", predicate="p", value="v")
    with pytest.raises(ValueError, match="cannot carry key"):
        ScenarioEvent("forget", person="h", subject="s", predicate="p", key="name")
    with pytest.raises(ValueError, match="carry exactly a key"):
        ScenarioQuery("identity", person="h")
    with pytest.raises(ValueError, match="not a #731"):
        ContinuityScenario("x", "vibes", (), ScenarioQuery("identity", key="k"), "v")


def test_reference_subject_passes_and_naive_baseline_fails_where_it_should(tmp_path):
    store = BenchmarkStore(tmp_path / "store")
    run = _run(store, run_id="run-one")

    assert run.suite_name == SUITE_NAME
    assert run.lane == "ci"
    assert run.candidate_id == CANDIDATE_ID
    assert run.baseline_id == BASELINE_ID
    assert run.summary["total"] == run.summary["scored"] == 20
    assert run.summary["passed"] == 20
    assert run.summary["errors"] == 0
    assert run.summary["quality_mean"] == 1.0
    # The suite discriminates: the naive baseline fails exactly the properties
    # #731 asks for (taint, leakage, restart continuity, purge honesty,
    # identity governance) and passes only the trivial ones.
    assert run.summary["baseline_quality_mean"] == 0.35
    baseline_failed = {
        result.case_id
        for result in run.results
        if float(result.baseline_quality.value) < 0.5
    }
    assert {
        "recall-across-restart",
        "taint-untrusted-only",
        "taint-cannot-override-owner",
        "correct-untrusted-cannot-correct",
        "leak-other-person",
        "leak-other-person-isolated-store",
        "identity-survives-restart",
        "identity-proposal-not-authoritative",
        "forget-audit-says-purged",
        "forget-explain-purged",
    } <= baseline_failed
    assert "recall-single-session" not in baseline_failed

    # Evidence is retained through the accepted E9.0 store; prompts are not.
    retained = store.runs(SUITE_NAME)
    assert [record.run_id for record in retained] == ["run-one"]
    assert retained[0] == run
    assert "nerva.continuity.scenario.v1" not in run.to_json()
    for result in run.results:
        assert result.candidate["provider_id"] == "local-deterministic"
        assert result.privacy.value == "no_external_disclosure"
        assert result.cost.value == 0.0

    # Direct semantics spot checks on the reference model.
    memory = ReferenceContinuityMemory()
    memory.apply(ScenarioEvent("observe", person="h", subject="s", predicate="p", value="v", source="owner"))
    memory.apply(ScenarioEvent("correct", person="h", subject="s", predicate="p", value="w", source="owner"))
    assert memory.answer(ScenarioQuery("recall", person="h", subject="s", predicate="p")) == "w"
    assert memory.answer(ScenarioQuery("audit", person="h", subject="s", predicate="p")) == "known"
    memory.apply(ScenarioEvent("forget", person="h", subject="s", predicate="p"))
    assert memory.answer(ScenarioQuery("recall", person="h", subject="s", predicate="p")) == "unknown"
    assert memory.answer(ScenarioQuery("audit", person="h", subject="s", predicate="p")) == "purged"
    naive = NaiveRecallBaseline()
    naive.apply(ScenarioEvent("observe", person="h", subject="s", predicate="p", value="v", source="untrusted"))
    assert naive.answer(ScenarioQuery("recall", person="anyone", subject="s", predicate="p")) == "v"


def test_subject_errors_are_retained_without_messages_and_provenance_is_explicit(tmp_path):
    class Exploding:
        def apply(self, event):
            raise RuntimeError("private memory backend detail")

        def answer(self, query):
            raise RuntimeError("private memory backend detail")

    class NotText:
        def apply(self, event):
            return None

        def answer(self, query):
            return 42

    store = BenchmarkStore(tmp_path / "store")
    errored = _run(
        store,
        run_id="run-exploding",
        candidate=subject_runner(Exploding, subject_id="exploding.v1"),
        candidate_id="exploding.v1",
    )
    assert errored.summary["errors"] == errored.summary["total"]
    assert errored.results[0].error_type == "RuntimeError"
    assert "private memory backend" not in errored.to_json()
    # Candidate errors keep the baseline explicitly unmeasured, never fabricated.
    assert errored.results[0].baseline_quality.status == "not_measured"

    untyped = _run(
        store,
        run_id="run-untyped",
        candidate=subject_runner(NotText, subject_id="untyped.v1"),
        candidate_id="untyped.v1",
    )
    assert {result.error_type for result in untyped.results} == {"TypeError"}

    async def scripted(prompt: str) -> BenchmarkObservation:
        return await subject_runner(ReferenceContinuityMemory, subject_id="ok.v1")("not json")

    with pytest.raises(ValueError, match="valid JSON"):
        asyncio.run(scripted("x"))
    with pytest.raises(ValueError, match="model id"):
        subject_runner(ReferenceContinuityMemory, subject_id="ok.v1", model_id="GPT 5")
    with pytest.raises(ValueError, match="callable"):
        subject_runner(object(), subject_id="ok.v1")  # type: ignore[arg-type]

    # A model-backed subject is described by the caller, not inferred.
    cloud = subject_runner(
        ReferenceContinuityMemory,
        subject_id="cloud-memory.v1",
        model_id="some-model",
        provider_id="some-provider",
        privacy_effect="sanitized_before_external_use",
    )
    observation = asyncio.run(cloud(continuity_scenarios()[0].to_json()))
    assert observation.provider_id == "some-provider"
    assert observation.privacy_effect == "sanitized_before_external_use"


def test_suite_cannot_mark_anything_accepted(tmp_path):
    # The module's actual imports (not its prose) stay clear of every
    # privileged-action path: kernel, approval queue, promotion, autonomy.
    imported = set()
    for node in ast.walk(ast.parse(inspect.getsource(cs))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in ("kernel", "approval", "promotion", "autonomy", "capability_actions"):
        assert not [name for name in imported if forbidden in name], forbidden
    assert "agents.core.observability.benchmark" in imported
    assert not [
        name
        for name in dir(cs)
        if name.lower().startswith(("accept", "promote", "approve", "mark_"))
    ]

    store = BenchmarkStore(tmp_path / "store")
    run = _run(store, run_id="run-one")
    assert run.authority == "evaluation_only"
    assert (run.can_change_routing, run.can_authorize, run.can_execute, run.can_mark_complete) == (
        False,
        False,
        False,
        False,
    )

    report = build_report(run, store=store)
    payload = json.loads(report.to_json())
    assert payload["schema"] == "nerva.continuity.report.v1"
    assert payload["authority"] == "evaluation_only"
    assert payload["acceptance"] == "not_claimed"
    for flag in (
        "can_change_routing",
        "can_authorize",
        "can_execute",
        "can_promote_capability",
        "can_mark_complete",
        "can_accept_epic",
    ):
        assert payload[flag] is False, flag
    # Every criterion names the epic that owns acceptance; the report owns none.
    assert {item["criterion"]: item["acceptance_owner"] for item in payload["criteria"]} == dict(
        CRITERIA
    )
    # The ceiling is structural: the flags are not constructor inputs and a
    # report cannot be forged outside build_report.
    with pytest.raises(ValueError, match="init=False"):
        replace(report, can_accept_epic=True)
    with pytest.raises(ValueError, match="through build_report"):
        ContinuityReport(
            **{
                key: value
                for key, value in report.__dict__.items()
                if key
                not in {
                    "guard",
                    "schema",
                    "authority",
                    "can_change_routing",
                    "can_authorize",
                    "can_execute",
                    "can_promote_capability",
                    "can_mark_complete",
                    "can_accept_epic",
                }
            }
        )


def _degrade(run, criterion: str):
    """Flip every scored result of one criterion to a failed candidate score."""

    return replace(
        run,
        results=tuple(
            replace(
                result,
                status="failed",
                passed=False,
                quality=Measurement("measured", 0.0, "ratio", "test"),
            )
            if result.task_type == criterion
            else result
            for result in run.results
        ),
    )


def test_report_is_deterministic_and_regresses_only_against_comparable_runs(
    tmp_path, monkeypatch, capsys
):
    store = BenchmarkStore(tmp_path / "store")
    first = _run(store, run_id="run-one")

    assert build_report(first, store=store).to_json() == build_report(first, store=store).to_json()
    assert previous_run(store, exclude_run_id="run-one") is None
    report = build_report(first, store=store)
    assert report.previous_run_id is None and report.regressed is False
    assert report.suite_fingerprint == _PINNED_SUITE_FINGERPRINT
    assert {item.criterion: item.pass_ratio for item in report.criteria} == dict.fromkeys(
        CRITERIA, 1.0
    )
    assert "acceptance not claimed" in report.to_markdown()

    # An unretained run is not evidence.
    with pytest.raises(ValueError, match="retained in the benchmark store"):
        build_report(replace(first, run_id="run-ghost"), store=store)

    degraded = replace(_degrade(first, "forget-purge-honesty"), run_id="run-degraded")
    store.record_run(degraded)
    worse = build_report(degraded, store=store, previous=first)
    assert worse.previous_run_id == "run-one"
    assert worse.regressed_criteria == ("forget-purge-honesty",)
    assert worse.regressed is True
    assert "forget-purge-honesty (regressed)" in worse.to_markdown()
    # The inverse direction is not a regression.
    better = build_report(first, store=store, previous=degraded)
    assert better.regressed is False

    # A different candidate identity is not comparable: no regression can be
    # manufactured out of an evaluator change.
    other = _run(
        store,
        run_id="run-other",
        revision=_OTHER_REVISION,
        candidate=subject_runner(NaiveRecallBaseline, subject_id="naive-as-candidate.v1"),
        candidate_id="naive-as-candidate.v1",
    )
    across = build_report(other, store=store, previous=first)
    assert across.previous_run_id is None and across.regressed is False

    # CLI lane entry: a missing exact revision fails visibly (exit 2), a normal
    # run writes the summary and JSON document (exit 0), and a genuinely worse
    # comparable run exits 1 under --fail-on-regression.
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("NERVA_SOURCE_REVISION", raising=False)
    root = tmp_path / "cli"
    assert cs.main(["--store-root", str(root)]) == 2
    summary = tmp_path / "summary.md"
    document = tmp_path / "report.json"
    assert (
        cs.main(
            [
                "--store-root",
                str(root),
                "--revision",
                _REVISION,
                "--run-id",
                "run-cli-one",
                "--summary",
                str(summary),
                "--json-out",
                str(document),
                "--fail-on-regression",
            ]
        )
        == 0
    )
    written = json.loads(document.read_text(encoding="utf-8"))
    assert written["run_id"] == "run-cli-one" and written["regressed"] is False
    assert "Continuity Core suite" in summary.read_text(encoding="utf-8")
    monkeypatch.setattr(cs, "ReferenceContinuityMemory", NaiveRecallBaseline)
    assert (
        cs.main(
            [
                "--store-root",
                str(root),
                "--revision",
                _OTHER_REVISION,
                "--run-id",
                "run-cli-two",
                "--json-out",
                str(document),
                "--fail-on-regression",
            ]
        )
        == 1
    )
    written = json.loads(document.read_text(encoding="utf-8"))
    assert written["previous_run_id"] == "run-cli-one"
    assert "recall-precision-under-taint" in written["regressed_criteria"]
    assert "(regressed)" in capsys.readouterr().out
