"""Structural guardrails for the path-aware blocking Security workflow."""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO / ".github" / "workflows" / "security.yml"
TOOLS = REPO / ".github" / "security-tools"


def _workflow():
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _step_using(job, prefix):
    return next(step for step in job["steps"] if step.get("uses", "").startswith(prefix))


def test_secret_scan_stays_unconditional_while_expensive_scans_are_path_selected():
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert "paths" not in workflow["on"]["pull_request"]
    assert workflow["on"]["schedule"] == [{"cron": "43 5 * * 1"}]
    assert jobs["gitleaks"].get("needs") is None
    assert jobs["scope"]["outputs"]["required_lanes_json"].startswith("${{")
    assert set(jobs["scope"]["outputs"]) == {
        "aggregate_ready",
        "classification_id",
        "required_lanes_json",
        "security_sast_required",
        "security_dependency_required",
    }
    assert jobs["scope"]["steps"][0]["with"]["fetch-depth"] == "0"
    classify = jobs["scope"]["steps"][-1]["run"]
    assert '"$GITHUB_EVENT_NAME" == "schedule"' in classify
    assert "--changed-file .github/workflows/security.yml" in classify

    semgrep_if = jobs["sast"]["if"]
    bandit_if = jobs["bandit"]["if"]
    dependency_if = jobs["dependency-audit"]["if"]
    for job_name in ("sast", "dependency-audit", "bandit"):
        assert jobs[job_name]["needs"] == "scope"
    assert semgrep_if == "${{ needs.scope.outputs.security_sast_required == 'true' }}"
    assert bandit_if == semgrep_if
    assert dependency_if == ("${{ needs.scope.outputs.security_dependency_required == 'true' }}")
    assert "contains(" not in "\n".join((semgrep_if, bandit_if, dependency_if))


def test_scanner_pip_caches_are_keyed_by_their_exact_pinned_requirement():
    workflow = _workflow()
    jobs = workflow["jobs"]
    expected = {
        "sast": ("semgrep.txt", "semgrep==1.167.0"),
        "dependency-audit": ("pip-audit.txt", "pip-audit==2.10.1"),
        "bandit": ("bandit.txt", "bandit==1.9.4"),
    }
    for job_name, (filename, pin) in expected.items():
        setup = _step_using(jobs[job_name], "actions/setup-python@")
        assert setup["with"]["cache"] == "pip"
        assert setup["with"]["cache-dependency-path"] == f".github/security-tools/{filename}"
        assert (TOOLS / filename).read_text(encoding="utf-8").strip() == pin
        commands = "\n".join(step.get("run", "") for step in jobs[job_name]["steps"])
        assert f"-r .github/security-tools/{filename}" in commands


def test_required_security_check_is_stable_and_fails_closed():
    workflow = _workflow()
    required = workflow["jobs"]["required"]

    assert required["name"] == "required"
    assert required["if"] == "${{ always() }}"
    assert set(required["needs"]) == {
        "scope",
        "gitleaks",
        "sast",
        "dependency-audit",
        "bandit",
    }
    assert _step_using(required, "actions/checkout@")["uses"].endswith(
        "@3d3c42e5aac5ba805825da76410c181273ba90b1"
    )
    command = required["steps"][-1]["run"]
    assert command == "python scripts/change_risk.py --aggregate-security-results"
    assert set(required["env"]) == {
        "CHANGE_RISK_AGGREGATE_READY",
        "CHANGE_RISK_CLASSIFICATION_ID",
        "CHANGE_RISK_REQUIRED_LANES",
        "CHANGE_RISK_SECURITY_SAST_REQUIRED",
        "CHANGE_RISK_SECURITY_DEPENDENCY_REQUIRED",
        "CHANGE_RISK_SECURITY_JOB_RESULTS",
    }
    assert (
        '"scope":"${{ needs.scope.result }}"' in required["env"]["CHANGE_RISK_SECURITY_JOB_RESULTS"]
    )


def test_every_blocking_scanner_emits_an_actionable_error_annotation():
    workflow = _workflow()
    jobs = workflow["jobs"]

    commands = {
        name: "\n".join(step.get("run", "") for step in jobs[name]["steps"])
        for name in ("gitleaks", "sast", "dependency-audit", "bandit")
    }
    for command in commands.values():
        assert "::error title=" in command
        assert "GITHUB_STEP_SUMMARY" in command
        assert "Reproduce with" in command
    assert "./scripts/lock_deps.sh" in commands["dependency-audit"]
    assert ".bandit-baseline.json" in commands["bandit"]


def test_security_jobs_have_bounded_runtime_and_pr_specific_cancellation():
    workflow = _workflow()

    assert workflow["concurrency"] == {
        "group": "security-${{ github.event.pull_request.number || github.ref }}",
        "cancel-in-progress": "true",
    }
    for job in workflow["jobs"].values():
        assert 0 < int(job["timeout-minutes"]) <= 20
