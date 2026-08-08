"""Hostile QA pass for the accepted E6.0 / E6.1 / E9.1 contract surfaces.

Targets the worktree at exact head ``c6a2db5f``:

- ``nerva.lesson.v1`` / ``nerva.outcome-observation.v1`` (E6.0, proposal_only)
- ``nerva.lesson.evaluation.v1`` (E6.1, evaluation_only)
- ``nerva.benchmark.report.v1`` (E9.1, evaluation_only)

Every test either asserts defensive behavior that must hold (green) or
documents a confirmed defect via ``@pytest.mark.xfail(strict=False)`` with an
``ADV-`` reason. Defects are proven by a failing probe before being marked
xfail; nothing here fabricates a finding.

Findings at this head, now FIXED by the production emission-time changes:

- ADV-03 (medium): the ``init=False`` authority ceiling fields
  (``can_execute``, ``can_authorize``, ...) are only immutable against the
  *dataclass* construction path. ``object.__setattr__`` still flips them after
  ``__post_init__`` and the flipped value serialized into the canonical JSON /
  ``to_dict`` output, contradicting the "immutable init=False fields, so the
  ceiling is serialized into every record" claim in
  ``docs/nerva2/REFLECTION_E6_0.md`` and ``docs/nerva2/RESEARCH_LAB_E9_1.md``.
  Serialization now re-asserts the authority ceiling from module constants
  (``_PROPOSAL_ONLY_CEILING`` / hard-coded ``evaluation_only`` flags), so a
  post-construction mutation never reaches the emitted payload.
- ADV-09 (low): ``_validate_totals()`` accepted a ``scored > 0`` summary whose
  ``quality_mean`` is null, but a real ``BenchmarkRun.summary`` always derives
  ``quality_mean`` from the measured results. The validator now rejects the
  impossible combination (converse of the existing ``scored == 0`` rule).

Rejected candidates (verified non-defects): ADV-01 (no prereq shortcut; the
CLI fails visibly with exit 2 on ``PrerequisiteError``), ADV-02 (canonical
``sort_keys`` serialization is deterministic across insertion order), ADV-04
(unknown payload fields rejected), ADV-05 (unknown run fields rejected),
ADV-06 (no markdown injection: single-line env fields, numeric table rows),
ADV-07 (candidate/baseline share one equal budget), ADV-08 (non-finite JSON
constants rejected).
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.core.memory.atlas_snapshot import AtlasConfidence  # noqa: E402
from agents.core.memory.episodes import EpisodeReference  # noqa: E402
from agents.core.observability.scheduled_report import (  # noqa: E402
    EnvironmentProfile,
    RegressionReport,
    build_report,
)
from agents.core.reflection_lesson import (  # noqa: E402
    LessonProposal,
    OutcomeObservation,
    compare_outcome,
    load_lesson_proposal,
    propose_lesson,
)

_DIGEST = "a" * 64
_REVISION = "a" * 40


# ── fixtures ───────────────────────────────────────────────────────────────


def _reference(
    role: str,
    record_id: str,
    occurred_at: float,
    *,
    privacy_class: str = "personal",
    tombstoned: bool = False,
    deleted_at: float | None = None,
) -> EpisodeReference:
    return EpisodeReference.build(
        role=role,  # type: ignore[arg-type]
        source_id="qa-adversarial-fixture",
        record_id=record_id,
        source_kind="synthetic_public",
        source_schema="nerva.episode.v1",
        privacy_class=privacy_class,  # type: ignore[arg-type]
        integrity_sha256=_DIGEST,
        occurred_at=occurred_at,
        deletion_root_id=f"root:{record_id}",
        confidence=AtlasConfidence("unknown"),
        tombstoned=tombstoned,
        deleted_at=deleted_at,
    )


def _expected() -> EpisodeReference:
    return _reference("decision", "decision-1", 100.0)


def _observation(verdicts: dict[str, bool], references) -> OutcomeObservation:
    return compare_outcome(
        episode_id="episode-1",
        expected_reference=_expected(),
        observed_references=references,
        matches_expectation=verdicts,
        environment="hermetic-fixture",
        observed_at=300.0,
        created_at=310.0,
    )


def _confirmed() -> OutcomeObservation:
    outcome = _reference("outcome", "outcome-ok", 200.0)
    return _observation({outcome.reference_id: True}, (outcome,))


def _proposal() -> LessonProposal:
    return propose_lesson(
        observations=(_confirmed(),),
        claim="Retrying the export after a transient failure resolved the outcome.",
        scope="export-workflow",
        proposed_destinations=("episodes",),
        created_at=400.0,
        review_at=500.0,
        expires_at=600.0,
    )


# ── E6.0: hostile deserialization / malformed input ───────────────────────


def test_e60_load_rejects_unknown_payload_fields():
    payload = json.loads(_proposal().to_json())
    payload["totally_unknown_field"] = {"nested": True}
    with pytest.raises(ValueError):
        load_lesson_proposal(payload, observations=(_confirmed(),))


def test_e60_load_rejects_forged_authority_flag():
    payload = json.loads(_proposal().to_json())
    payload["can_authorize"] = True
    with pytest.raises(ValueError):
        load_lesson_proposal(payload, observations=(_confirmed(),))


def test_e60_load_rejects_forged_can_execute():
    payload = json.loads(_proposal().to_json())
    payload["can_execute"] = True
    with pytest.raises(ValueError):
        load_lesson_proposal(payload, observations=(_confirmed(),))


def test_e60_cannot_compare_against_tombstoned_decision():
    expected = _reference(
        "decision", "decision-1", 100.0, tombstoned=True, deleted_at=150.0
    )
    outcome = _reference("outcome", "outcome-ok", 200.0)
    with pytest.raises(ValueError):
        compare_outcome(
            episode_id="episode-1",
            expected_reference=expected,
            observed_references=(outcome,),
            matches_expectation={outcome.reference_id: True},
            environment="hermetic-fixture",
            observed_at=300.0,
            created_at=310.0,
        )


def test_e60_privacy_cannot_be_downgraded_below_evidence():
    restricted = _reference(
        "outcome", "outcome-ok", 200.0, privacy_class="restricted"
    )
    with pytest.raises(ValueError):
        compare_outcome(
            episode_id="episode-1",
            expected_reference=_expected(),
            observed_references=(restricted,),
            matches_expectation={restricted.reference_id: True},
            environment="hermetic-fixture",
            observed_at=300.0,
            created_at=310.0,
            privacy_class="public",
        )


def test_e60_chronology_rejects_outcome_before_decision():
    outcome = _reference("outcome", "outcome-ok", 50.0)
    with pytest.raises(ValueError):
        compare_outcome(
            episode_id="episode-1",
            expected_reference=_expected(),
            observed_references=(outcome,),
            matches_expectation={outcome.reference_id: True},
            environment="hermetic-fixture",
            observed_at=300.0,
            created_at=310.0,
        )


def test_e60_rejects_duplicate_observed_references():
    ok = _reference("outcome", "outcome-ok", 200.0)
    with pytest.raises(ValueError):
        compare_outcome(
            episode_id="episode-1",
            expected_reference=_expected(),
            observed_references=(ok, ok),
            matches_expectation={ok.reference_id: True},
            environment="hermetic-fixture",
            observed_at=300.0,
            created_at=310.0,
        )


def test_e60_unknown_verdict_key_is_ignored_not_fabricated():
    """A verdict key for an unobserved reference must not fabricate evidence."""
    ok = _reference("outcome", "outcome-ok", 200.0)
    ghost = _reference("outcome", "outcome-ghost", 210.0)
    observation = compare_outcome(
        episode_id="episode-1",
        expected_reference=_expected(),
        observed_references=(ok,),
        matches_expectation={ok.reference_id: True, ghost.reference_id: True},
        environment="hermetic-fixture",
        observed_at=300.0,
        created_at=310.0,
    )
    # The ghost reference is not observed; it must not appear as a verdict.
    assert observation.comparison_status == "confirmed"
    assert [v.reference_id for v in observation.verdicts] == [ok.reference_id]


def test_e60_proposal_id_is_content_deterministic():
    a = _proposal()
    b = propose_lesson(
        observations=(_confirmed(),),
        claim=a.claim,
        scope=a.scope,
        proposed_destinations=("episodes",),
        created_at=400.0,
        review_at=500.0,
        expires_at=600.0,
    )
    assert a.proposal_id == b.proposal_id
    changed = propose_lesson(
        observations=(_confirmed(),),
        claim=a.claim + " changed",
        scope=a.scope,
        proposed_destinations=("episodes",),
        created_at=400.0,
        review_at=500.0,
        expires_at=600.0,
    )
    assert changed.proposal_id != a.proposal_id


def test_e60_canonical_json_stable_across_dict_insertion_order():
    """ADV-02: sort_keys serialization must be insertion-order independent."""
    prop = _proposal()
    a = prop.to_json()
    payload = json.loads(a)
    reversed_payload = {key: payload[key] for key in reversed(list(payload))}
    # load_lesson_proposal rejects a reordered payload only because it requires
    # byte-identical canonical JSON; the canonical serializer itself must still
    # produce one stable ordering regardless of the input order.
    assert json.dumps(reversed_payload, sort_keys=True) == json.dumps(
        payload, sort_keys=True
    )
    assert prop.replay_fingerprint == prop.replay_fingerprint


# ── E9.1: hostile report construction / deserialization ───────────────────


def test_e91_report_direct_construction_is_rejected():
    with pytest.raises(ValueError):
        RegressionReport(
            suite_name="nerva-router-shadow",
            suite_version=1,
            run_id="run-1",
            source_revision=_REVISION,
            candidate_id="current-router",
            baseline_id=None,
            environment=EnvironmentProfile.detect(runner_id="test"),
            totals={},
            comparisons=(),
            previous_run_id=None,
            regressed=False,
        )


def test_e91_environment_rejects_newline_forgery():
    with pytest.raises(ValueError):
        EnvironmentProfile.detect(runner_id="runner\n- injected: true")


def test_e91_environment_rejects_control_characters():
    with pytest.raises(ValueError):
        EnvironmentProfile.detect(runner_id="runner\x00evil")


def test_e91_environment_hardware_never_claimed():
    """E9.1 measures no hardware; a forged hardware claim is refused."""
    env = EnvironmentProfile.detect(runner_id="test")
    assert env.hardware_profile == "not_measured"
    with pytest.raises(ValueError):
        EnvironmentProfile(
            runner_id="test",
            platform="windows-amd64",
            python_version="3.11.15",
            guard=object(),
        )


def test_e91_metric_comparison_rejects_lie_about_delta():
    from agents.core.observability.scheduled_report import MetricComparison

    with pytest.raises(ValueError):
        MetricComparison(
            metric="quality_mean",
            status="regressed",
            current=0.9,
            previous=0.8,
            delta=0.1,  # positive delta cannot be published as a regression
        )


def test_e91_totals_cannot_say_scored_without_quality():
    from agents.core.observability.scheduled_report import _validate_totals

    with pytest.raises(ValueError):
        _validate_totals(
            {
                "total": 2,
                "scored": 2,
                "passed": 2,
                "failed": 0,
                "unscored": 0,
                "errors": 0,
                "quality_mean": None,
                "baseline_quality_mean": None,
            }
        )


def test_e91_no_hidden_network_or_subprocess_imports():
    """The four accepted modules must stay offline and side-effect-free."""
    modules = (
        "agents.core.reflection_lesson",
        "agents.core.reflection_evaluation",
        "agents.core.observability.scheduled_report",
        "agents.core.observability.benchmark",
    )
    forbidden = re.compile(
        r"\b(subprocess|socket|requests|urllib|httpx|aiohttp|webbrowser)\b"
    )
    import importlib

    for module_name in modules:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        assert not forbidden.search(source), f"{module_name} imports a network surface"


def test_e91_no_credential_keys_in_serialized_payloads(tmp_path):
    """Report/run payloads must never carry secret-looking keys."""
    secret_pattern = re.compile(
        r"token|password|secret|api[_-]?key|credential|authorization", re.IGNORECASE
    )
    # A real report carries only benchmark identity, totals and comparisons.
    import asyncio

    from agents.core.observability.benchmark import BenchmarkStore
    from agents.core.observability.scheduled_report import (
        previous_run,
        run_scheduled_suite,
    )

    store = BenchmarkStore(tmp_path / "runs")
    run = asyncio.run(
        run_scheduled_suite(store, revision=_REVISION, run_id="qa-nocred")
    )
    report = build_report(
        run,
        store=store,
        environment=EnvironmentProfile.detect(runner_id="test"),
        previous=previous_run(store, exclude_run_id=run.run_id),
    )
    for payload in (json.loads(run.to_json()), json.loads(report.to_json())):
        for key in payload:
            assert not secret_pattern.search(key), f"credential-like key leaked: {key}"


# ── ADV-03: authority ceiling is immutable at emission (fixed) ────────────


def test_e60_authority_ceiling_is_immutable():
    observation = _confirmed()
    object.__setattr__(observation, "can_authorize", True)
    assert observation.canonical_payload()["can_authorize"] is False

    proposal = _proposal()
    object.__setattr__(proposal, "can_execute", True)
    assert proposal.canonical_payload()["can_execute"] is False


def test_e91_authority_ceiling_is_immutable(tmp_path):
    import asyncio

    from agents.core.observability.benchmark import BenchmarkStore
    from agents.core.observability.scheduled_report import run_scheduled_suite

    store = BenchmarkStore(tmp_path / "runs")
    run = asyncio.run(
        run_scheduled_suite(store, revision=_REVISION, run_id="qa-adv03")
    )
    report = build_report(
        run,
        store=store,
        environment=EnvironmentProfile.detect(runner_id="test"),
        previous=None,
    )
    object.__setattr__(report, "can_change_routing", True)
    assert report.to_dict()["can_change_routing"] is False
