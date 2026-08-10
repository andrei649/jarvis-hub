"""Structural guards for the change-aware CI workflow and stable sentinel."""

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CI_PATH = REPO / ".github" / "workflows" / "ci.yml"
REUSABLE_PATH = REPO / ".github" / "workflows" / "change-risk.yml"
NERVA_PATH = REPO / ".github" / "workflows" / "nerva-roadmap.yml"
POLICY_PATH = REPO / ".github" / "change-risk.json"


def _workflow(path):
    # BaseLoader follows YAML syntax without YAML 1.1's obsolete `on` -> true
    # coercion, while GitHub Actions applies YAML 1.2 semantics.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


CI = _workflow(CI_PATH)
REUSABLE = _workflow(REUSABLE_PATH)
NERVA = _workflow(NERVA_PATH)
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _run_commands(job):
    return [step.get("run", "") for step in job["steps"] if isinstance(step, dict)]


def test_workflows_are_valid_yaml_mappings():
    assert isinstance(CI, dict)
    assert isinstance(CI["on"], dict)
    assert isinstance(CI["jobs"], dict)
    assert isinstance(REUSABLE["on"], dict)
    assert isinstance(REUSABLE["jobs"], dict)
    assert isinstance(NERVA["on"], dict)
    assert isinstance(NERVA["jobs"], dict)


def test_ci_has_one_stable_fail_closed_required_sentinel():
    sentinels = [
        (workflow["name"], job_id)
        for workflow in (CI, REUSABLE)
        for job_id, job in workflow["jobs"].items()
        if job.get("name") == "required"
    ]

    assert sentinels == [("CI", "required")]
    assert POLICY["sentinel_check"] == "CI / required"
    required = CI["jobs"]["required"]
    assert required["if"] == "${{ always() }}"
    assert set(required["needs"]) == set(POLICY["ci_jobs"])
    assert "--aggregate-results" in "\n".join(_run_commands(required))
    assert "CHANGE_RISK_AGGREGATE_READY" in required["env"]
    assert "CHANGE_RISK_JOB_RESULTS" in required["env"]


def test_policy_ci_job_contract_matches_the_actual_workflow():
    assert set(POLICY["ci_jobs"]) == set(CI["jobs"]) - {"required"}
    assert set(POLICY["lane_jobs"]) == set(POLICY["all_lanes"])
    assert all(set(jobs) <= set(POLICY["ci_jobs"]) for jobs in POLICY["lane_jobs"].values())


def test_draft_and_ready_transitions_trigger_fresh_evidence():
    event_types = set(CI["on"]["pull_request"]["types"])

    assert {"synchronize", "ready_for_review", "converted_to_draft"} <= event_types
    outputs = CI["jobs"]["classify"]["outputs"]
    assert "pull_request.draft == false" in outputs["expensive_enabled"]
    assert "risk_level == 'high'" in outputs["full_validation"]
    assert outputs["nerva_relevant"].startswith("${{")


def test_every_expensive_job_is_change_aware_and_bounded():
    expensive_jobs = set(POLICY["ci_jobs"]) - {
        "classify",
        "fast-gate",
        "nerva-integrity",
    }

    for job_name in expensive_jobs:
        job = CI["jobs"][job_name]
        assert set(job["needs"]) == {"classify", "fast-gate"}
        assert "expensive_enabled" in job["if"]
        assert "full_validation" in job["if"]
        assert "fromJSON" in job["if"]
        assert int(job["timeout-minutes"]) <= 30


def test_fast_jobs_are_bounded_and_cancel_superseded_runs():
    assert CI["concurrency"]["cancel-in-progress"] == "true"
    assert int(CI["jobs"]["classify"]["timeout-minutes"]) <= 5
    assert int(CI["jobs"]["fast-gate"]["timeout-minutes"]) <= 5
    assert CI["jobs"]["classify"]["steps"][0]["with"]["fetch-depth"] == "0"
    nerva = CI["jobs"]["nerva-integrity"]
    assert set(nerva["needs"]) == {"classify", "fast-gate"}
    assert nerva["uses"] == "./.github/workflows/nerva-roadmap.yml"
    assert "nerva_relevant" in nerva["with"]["enabled"]
    assert set(nerva["with"]) == {"enabled", "baseline_ref", "candidate_ref"}


def test_lint_and_static_analyzer_install_run_once():
    workflow_text = CI_PATH.read_text(encoding="utf-8")
    assert workflow_text.count("ruff check .") == 1
    assert workflow_text.count("pip install --require-hashes -r requirements-dev.lock") == 1

    for job_name in ("test", "sandbox-isolation"):
        commands = "\n".join(_run_commands(CI["jobs"][job_name]))
        assert "requirements-beta.lock" in commands
        assert "requirements-dev.lock" not in commands


def test_ubuntu_full_test_lane_revalidates_live_collection_truth():
    steps = CI["jobs"]["test"]["steps"]
    live_truth = next(step for step in steps if step.get("name") == "Verify live backend test-count truth")

    assert live_truth["if"] == "${{ matrix.os == 'ubuntu-latest' }}"
    assert "status_sync.py --check --reuse-js-counts --json" in live_truth["run"]


def test_health_debt_delta_gate_runs_once_after_ruff():
    commands = _run_commands(CI["jobs"]["lint"])
    ruff_index = next(index for index, command in enumerate(commands) if "ruff check ." in command)
    debt_index = next(
        index for index, command in enumerate(commands) if "check_new_health_debt.py" in command
    )

    assert debt_index == ruff_index + 1
    assert '--base "$BASE_SHA" --json' in commands[debt_index]
    assert CI_PATH.read_text(encoding="utf-8").count("check_new_health_debt.py") == 1


def test_reusable_classifier_is_not_a_competing_pull_request_check():
    assert "pull_request" not in REUSABLE["on"]
    assert set(REUSABLE["jobs"]) == {"classify"}
    assert "required_lanes_json" in REUSABLE["on"]["workflow_call"]["outputs"]
    assert "nerva_relevant" in REUSABLE["on"]["workflow_call"]["outputs"]
    assert set(NERVA["on"]) == {"workflow_call", "workflow_dispatch"}
