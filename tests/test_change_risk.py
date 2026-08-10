"""Focused contract tests for the dependency-free CI change-risk classifier."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "change_risk", REPO / "scripts" / "change_risk.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


risk = _load()
POLICY = risk.load_policy(REPO / ".github" / "change-risk.json")


def _change(path, status="M", **extra):
    return {"status": status, "status_detail": status, "path": path, **extra}


def _classify(*changes):
    return risk.classify_changes(list(changes), POLICY, base_sha="base", head_sha="head")


def test_documentation_only_change_uses_the_small_lane():
    result = _classify(_change("docs/FAQ.md"), _change("README.md"))

    assert result["scopes"] == ["docs-only"]
    assert result["required_lanes"] == ["docs-policy"]
    assert result["risk_level"] == "low"
    assert result["full_suite_required"] is False
    assert result["fail_safe"] is False
    assert result["nerva_relevant"] is False


def test_generated_truth_is_not_misclassified_as_docs_only():
    result = _classify(_change("BACKLOG.md"), _change("project-status.json"))

    assert result["scopes"] == ["generated-truth"]
    assert result["required_lanes"] == ["generated-truth"]
    assert result["risk_level"] == "medium"
    assert result["nerva_relevant"] is True


def test_python_runtime_requires_both_supported_operating_systems():
    result = _classify(_change("agents/core/router.py"))

    assert result["scopes"] == ["python-runtime"]
    assert result["required_lanes"] == ["python-ubuntu", "python-windows"]
    assert result["risk_level"] == "medium"


def test_frontend_and_mobile_scopes_are_independent():
    result = _classify(_change("frontend/src/App.tsx"), _change("mobile/App.tsx"))

    assert result["scopes"] == ["frontend", "mobile"]
    assert result["required_lanes"] == ["frontend", "mobile"]
    assert result["full_suite_required"] is False


@pytest.mark.parametrize(
    ("path", "expected_scope", "expected_lane"),
    [
        ("agents/core/security/policy.py", "contracts-security", "contracts-security"),
        (".github/workflows/ci.yml", "workflows", "workflow-policy"),
        ("requirements-beta.lock", "dependencies", "dependency-integrity"),
    ],
)
def test_high_risk_surfaces_require_a_full_suite(path, expected_scope, expected_lane):
    result = _classify(_change(path))

    assert expected_scope in result["scopes"]
    assert expected_lane in result["required_lanes"]
    assert result["risk_level"] == "high"
    assert result["full_suite_required"] is True


def test_classifier_policy_is_self_protected():
    result = _classify(
        _change("scripts/change_risk.py"),
        _change("tests/test_change_risk.py"),
        _change(".github/change-risk.json"),
    )

    assert "workflows" in result["scopes"]
    assert result["risk_level"] == "high"
    assert "workflow-policy" in result["required_lanes"]


def test_canonical_ai_development_policy_is_a_workflow_surface():
    result = _classify(
        _change(".github/ai-development-policy.json"),
        _change("scripts/check_ai_workflow_policy.py"),
        _change("scripts/check_new_health_debt.py"),
        _change("scripts/ci_metrics.py"),
        _change("scripts/verify_change.py"),
        _change("tests/test_ai_workflow_policy.py"),
        _change("tests/test_ci_metrics.py"),
        _change("tests/test_new_health_debt.py"),
        _change("tests/test_verify_change.py"),
    )

    assert "workflows" in result["scopes"]
    assert result["risk_level"] == "high"
    assert "workflow-policy" in result["required_lanes"]


def test_unknown_path_escalates_to_every_lane():
    result = _classify(_change("new-runtime-language/source.wut"))

    assert result["scopes"] == []
    assert result["required_lanes"] == POLICY["all_lanes"]
    assert result["risk_level"] == "high"
    assert result["fail_safe"] is True
    assert result["fail_safe_reasons"] == ["unknown-path"]
    assert result["unknown_paths"] == ["new-runtime-language/source.wut"]


def test_empty_diff_escalates_instead_of_going_green_as_docs_only():
    result = _classify()

    assert result["scopes"] == []
    assert result["required_lanes"] == POLICY["all_lanes"]
    assert result["fail_safe_reasons"] == ["empty-diff"]


def test_rename_classifies_both_paths_and_escalates_to_full_validation():
    result = _classify(
        _change(
            "agents/core/new_router.py",
            status="R",
            old_path="docs/nerva2/old_router.md",
        )
    )

    assert result["scopes"] == ["python-runtime"]
    assert result["required_lanes"] == POLICY["all_lanes"]
    assert result["metadata"]["rename_or_copy_count"] == 1
    assert result["fail_safe_reasons"] == ["rename-or-copy"]
    assert result["nerva_relevant"] is True


def test_path_traversal_cannot_bypass_fail_safe_classification():
    result = _classify(_change("../agents/core/router.py"))

    assert result["fail_safe"] is True
    assert result["unknown_paths"] == ["../agents/core/router.py"]
    assert result["required_lanes"] == POLICY["all_lanes"]


def test_three_runtime_scopes_raise_combination_risk():
    result = _classify(
        _change("agents/web.py"),
        _change("frontend/src/App.tsx"),
        _change("mobile/App.tsx"),
    )

    assert result["risk_level"] == "high"
    assert "full-suite" in result["required_lanes"]


def test_classification_id_is_deterministic_across_diff_order():
    first = _classify(_change("agents/web.py"), _change("frontend/src/App.tsx"))
    second = _classify(_change("frontend/src/App.tsx"), _change("agents/web.py"))

    assert first["classification_id"] == second["classification_id"]
    assert first["metrics"] == second["metrics"]
    other_head = risk.classify_changes(
        [_change("agents/web.py"), _change("frontend/src/App.tsx")],
        POLICY,
        base_sha="base",
        head_sha="other-head",
    )
    assert other_head["classification_id"] != first["classification_id"]


def test_name_status_parser_preserves_rename_source_and_destination():
    changes = risk.parse_name_status_z(b"M\0docs/FAQ.md\0R087\0old.py\0agents/new.py\0")

    assert changes == [
        {"status": "M", "status_detail": "M", "path": "docs/FAQ.md"},
        {
            "status": "R",
            "status_detail": "R087",
            "old_path": "old.py",
            "path": "agents/new.py",
        },
    ]


def test_name_status_parser_rejects_truncated_or_unknown_records():
    with pytest.raises(ValueError, match="missing destination"):
        risk.parse_name_status_z(b"R100\0old.py\0")
    with pytest.raises(ValueError, match="unsupported"):
        risk.parse_name_status_z(b"Q\0mystery\0")


def test_github_outputs_and_summary_are_machine_and_human_readable(tmp_path):
    result = _classify(_change("docs/FAQ.md"))
    outputs = tmp_path / "outputs"
    nerva_outputs = tmp_path / "nerva-outputs"
    security_outputs = tmp_path / "security-outputs"
    summary = tmp_path / "summary.md"

    risk.write_github_outputs(outputs, result)
    risk.write_github_outputs(nerva_outputs, _classify(_change("docs/nerva2/CORTEX_E1_2.md")))
    risk.write_github_outputs(security_outputs, _classify(_change("requirements-beta.lock")))
    risk.write_summary(summary, result)

    values = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
    nerva_values = dict(line.split("=", 1) for line in nerva_outputs.read_text().splitlines())
    security_values = dict(line.split("=", 1) for line in security_outputs.read_text().splitlines())
    assert values["aggregate_ready"] == "true"
    assert json.loads(values["scopes_json"]) == ["docs-only"]
    assert json.loads(values["required_lanes_json"]) == ["docs-policy"]
    assert json.loads(values["metrics_json"])["changed_count"] == 1
    assert values["security_sast_required"] == "false"
    assert values["security_dependency_required"] == "false"
    assert values["nerva_relevant"] == "false"
    assert nerva_values["nerva_relevant"] == "true"
    assert security_values["security_sast_required"] == "true"
    assert security_values["security_dependency_required"] == "true"
    assert "The required sentinel confirms classification only" in summary.read_text()


def test_policy_validation_rejects_missing_required_contracts(tmp_path):
    broken = json.loads(json.dumps(POLICY))
    broken["scopes"].pop("mobile")
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(broken))

    with pytest.raises(risk.PolicyError, match="scope_order"):
        risk.load_policy(path)

    broken = json.loads(json.dumps(POLICY))
    broken.pop("nerva_patterns")
    path.write_text(json.dumps(broken))
    with pytest.raises(risk.PolicyError, match="nerva_patterns"):
        risk.load_policy(path)


def _job_results(default="skipped", **overrides):
    values = dict.fromkeys(POLICY["ci_jobs"], default)
    values["nerva-integrity"] = "success"
    values.update(overrides)
    return values


def _security_results(default="skipped", **overrides):
    values = dict.fromkeys(risk.SECURITY_JOBS, default)
    values.update(overrides)
    return values


def test_draft_aggregate_requires_fast_evidence_and_defers_expensive_lanes():
    result = risk.aggregate_ci_results(
        ["python-ubuntu", "python-windows"],
        _job_results(**{"classify": "success", "fast-gate": "success"}),
        POLICY,
        aggregate_ready=True,
        classification_id="a" * 64,
        expensive_enabled=False,
        full_validation=False,
    )

    assert result["status"] == "passed"
    assert result["required_jobs"] == ["classify", "fast-gate", "nerva-integrity"]
    assert result["deferred_lanes"] == ["python-ubuntu", "python-windows"]

    missing_nerva = risk.aggregate_ci_results(
        ["docs-policy"],
        _job_results(
            **{
                "classify": "success",
                "fast-gate": "success",
                "nerva-integrity": "skipped",
            }
        ),
        POLICY,
        aggregate_ready=True,
        classification_id="a" * 64,
        expensive_enabled=False,
        full_validation=False,
    )
    assert missing_nerva["status"] == "failed"
    assert any("nerva-integrity" in failure for failure in missing_nerva["failures"])


def test_selective_ready_aggregate_rejects_a_skipped_required_job():
    result = risk.aggregate_ci_results(
        ["frontend"],
        _job_results(
            **{
                "classify": "success",
                "fast-gate": "success",
                "signal-layer-smoke": "success",
                "frontend": "success",
                "hud-v2-build": "success",
                "openapi-types": "skipped",
            }
        ),
        POLICY,
        aggregate_ready=True,
        classification_id="b" * 64,
        expensive_enabled=True,
        full_validation=False,
    )

    assert result["status"] == "failed"
    assert any("openapi-types" in failure for failure in result["failures"])


def test_full_validation_requires_every_ci_job():
    passed = risk.aggregate_ci_results(
        ["generated-truth"],
        _job_results(default="success"),
        POLICY,
        aggregate_ready=True,
        classification_id="c" * 64,
        expensive_enabled=True,
        full_validation=True,
    )
    failed_results = _job_results(default="success", mobile="cancelled")
    failed = risk.aggregate_ci_results(
        ["generated-truth"],
        failed_results,
        POLICY,
        aggregate_ready=True,
        classification_id="c" * 64,
        expensive_enabled=True,
        full_validation=True,
    )

    assert passed["status"] == "passed"
    assert set(passed["required_jobs"]) == set(POLICY["ci_jobs"])
    assert failed["status"] == "failed"
    assert any("cancelled" in failure for failure in failed["failures"])


def test_aggregate_fails_closed_on_bad_classifier_metadata():
    result = risk.aggregate_ci_results(
        ["invented-lane"],
        _job_results(**{"classify": "success", "fast-gate": "success"}),
        POLICY,
        aggregate_ready=False,
        classification_id="not-a-digest",
        expensive_enabled=False,
        full_validation=False,
    )

    assert result["status"] == "failed"
    assert len(result["failures"]) >= 3

    cases = [
        ([], True, "e" * 64, False, False, _security_results()),
        (["invented-lane"], True, "e" * 64, False, False, _security_results()),
        (["docs-policy", "docs-policy"], True, "e" * 64, False, False, _security_results()),
        (["docs-policy"], False, "e" * 64, False, False, _security_results()),
        (["docs-policy"], True, "not-a-digest", False, False, _security_results()),
        (["docs-policy"], True, "e" * 64, None, False, _security_results()),
        (["docs-policy"], True, "e" * 64, False, None, {"scope": "success"}),
    ]
    for lanes, ready, digest, sast, dependency, results in cases:
        security = risk.aggregate_security_results(
            lanes,
            results,
            POLICY,
            aggregate_ready=ready,
            classification_id=digest,
            sast_required_output=sast,
            dependency_required_output=dependency,
        )
        assert security["status"] == "failed", security


def test_nonrequired_job_failure_cannot_be_hidden_by_selective_mode():
    result = risk.aggregate_ci_results(
        ["docs-policy"],
        _job_results(**{"classify": "success", "fast-gate": "success", "mobile": "failure"}),
        POLICY,
        aggregate_ready=True,
        classification_id="d" * 64,
        expensive_enabled=True,
        full_validation=False,
    )

    assert result["status"] == "failed"
    assert any("observed CI failures" in failure for failure in result["failures"])

    selected_but_skipped = risk.aggregate_security_results(
        ["python-ubuntu"],
        _security_results(scope="success", gitleaks="success"),
        POLICY,
        aggregate_ready=True,
        classification_id="f" * 64,
        sast_required_output=True,
        dependency_required_output=False,
    )
    unselected_but_failed = risk.aggregate_security_results(
        ["docs-policy"],
        _security_results(scope="success", gitleaks="success", bandit="failure"),
        POLICY,
        aggregate_ready=True,
        classification_id="f" * 64,
        sast_required_output=False,
        dependency_required_output=False,
    )
    clean = risk.aggregate_security_results(
        ["docs-policy"],
        _security_results(scope="success", gitleaks="success"),
        POLICY,
        aggregate_ready=True,
        classification_id="f" * 64,
        sast_required_output=False,
        dependency_required_output=False,
    )

    assert selected_but_skipped["status"] == "failed"
    assert any("did not run" in failure for failure in selected_but_skipped["failures"])
    assert unselected_but_failed["status"] == "failed"
    assert any(
        "observed Security failures" in failure for failure in unselected_but_failed["failures"]
    )
    assert clean["status"] == "passed"


def test_workflow_exposes_reusable_classifier_outputs_without_a_second_sentinel():
    workflow = (REPO / ".github" / "workflows" / "change-risk.yml").read_text()

    assert "workflow_call:" in workflow
    assert "required_lanes_json:" in workflow
    assert "nerva_relevant:" in workflow
    assert "pull_request:" not in workflow
    assert "name: required" not in workflow
    assert "fetch-depth: 0" in workflow
    assert "timeout-minutes: 5" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
