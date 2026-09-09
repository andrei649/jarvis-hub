"""Fail-closed contract tests for Nerva's policy-driven autonomous merge lane.

This file intentionally keeps the same collected-case count as the policy suite it
replaces. The old contract pinned ``nerva2/*`` as manual-only; the 2026-09-09
owner directive replaces branch-name ceremony with a trusted, machine-readable
root-of-trust policy plus a mandatory automated proof floor.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts import selfdev_policy  # noqa: E402

WORKFLOW_PATH = REPO / ".github" / "workflows" / "pr-auto-merge.yml"
POLICY_PATH = REPO / "selfdev-policy.json"

REQUIRED_CHECKS = [
    "test (ubuntu-latest)",
    "hud-v2-build",
    "Secret scan (gitleaks)",
    "SAST (semgrep)",
    "Dependency audit (pip-audit)",
    "SAST (bandit — blocking gate)",
    "in-sync",
]

PROTECTED_CASES = [
    "selfdev-policy.json",
    "scripts/selfdev_policy.py",
    ".github/workflows/pr-auto-merge.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/new-future-workflow.yml",
    ".github/actions/example/action.yml",
    ".github/CODEOWNERS",
    "AGENTS.md",
    "MAX.md",
    "MOONSHOT.md",
    "NERVA_VISION.md",
    "LICENSE",
    "TRADEMARKS.md",
    "docs/legal/LICENSE-APACHE-2.0-staged.txt",
    "docs/legal/future-policy.md",
    "agents/core/kernel/__init__.py",
    "agents/core/kernel/budget.py",
    "agents/core/kernel/nested/new.py",
    "agents/core/security/__init__.py",
    "agents/core/security/taint.py",
    "agents/core/security/nested/new.py",
    "agents/core/secrets/__init__.py",
    "agents/core/secrets/vault.py",
    "agents/core/secret_store.py",
    "agents/core/secret_manager.py",
    "agents/core/secret_future.py",
    "agents/core/kernel/action_auth.py",
    "agents/core/security/audit.py",
    ".github/workflows/selfdev-policy.yml",
    ".github/actions/selfdev/action.yml",
]

AUTONOMOUS_CASES = [
    "agents/core/agent.py",
    "agents/core/orchestrator.py",
    "agents/core/autonomy/jobs.py",
    "agents/core/memory/manager.py",
    "agents/core/skills/loader.py",
    "agents/core/llm/base.py",
    "agents/core/llm/tool_dialects.py",
    "agents/core/routers/chat.py",
    "agents/core/routers/jobs.py",
    "agents/core/permission_ledger.py",
    "agents/web.py",
    "agents/__init__.py",
    "frontend/src/app.tsx",
    "frontend/src/shell.tsx",
    "frontend/src/panels/jobs.tsx",
    "frontend/src/components/card.tsx",
    "frontend/e2e/hud.spec.ts",
    "frontend/vite.config.ts",
    "mobile/src/App.tsx",
    "mobile/src/api.ts",
    "mobile/__tests__/api.test.ts",
    "tests/test_agent.py",
    "tests/test_jobs_routes.py",
    "tests/test_memory.py",
    "tests/test_cloud_tool_turns.py",
    "tests/test_context_query_tools.py",
    "scripts/backlog.py",
    "scripts/ledger.py",
    "scripts/status_sync.py",
    "scripts/install_smoke.py",
    "BACKLOG.md",
    "STATUS.md",
    "README.md",
    "CHANGELOG.md",
    "NERVA.md",
    "GO_LIVE_PLAN.md",
    "docs/ARCHITECTURE.md",
    "docs/AI_CONTEXT.md",
    "docs/HERMES_ABSORPTION.md",
    "docs/NERVA_2_ROADMAP.md",
    "docs/OWNER_TASKS.md",
    "docs/HISTORY.md",
    "docs/research/example.md",
    "docs/decisions/example.md",
    "skills/example/SKILL.md",
    "skills/example/main.py",
    "worldview/backend-api/src/index.ts",
    "worldview/mcp/src/index.ts",
    "docker-compose.yml",
    ".env.example",
]

BAD_PATH_CASES = [
    "",
    "..",
    "../release.yml",
    "../selfdev-policy.json",
    "../../outside",
    "foo/../bar",
    "foo/../../bar",
    "agents/../selfdev-policy.json",
    ".github/../selfdev-policy.json",
    "docs/../../LICENSE",
    "/etc/passwd",
    "/selfdev-policy.json",
    "/.github/workflows/ci.yml",
    "/agents/core/kernel/budget.py",
    "./../release.yml",
    "a/b/../../../c",
    "a/../../.github/workflows/ci.yml",
    "docs/legal/../../../tmp/x",
    "agents/core/../../../LICENSE",
    "frontend/../../MOONSHOT.md",
]

POLICY_MUTATIONS = [
    "remove-self-policy-protection",
    "remove-workflow-protection",
    "remove-kernel-protection",
    "disable-autonomous-default",
    "disable-merge",
    "allow-protected-merge",
    "allow-draft-merge",
    "allow-nonclean-merge",
    "allow-no-checks",
    "allow-partial-checks",
    "empty-required-checks",
    "duplicate-required-check",
    "empty-required-conclusions",
    "allow-skipped-required-check",
    "drop-success-from-other-conclusions",
    "disable-deploy-target",
    "replace-canary-with-direct-deploy",
    "disable-auto-rollback",
    "disable-review-target",
    "builder-clears-reviewer-findings",
]

ALLOWED_OTHER_CONCLUSIONS = ["success", "neutral", "skipped"]
DISALLOWED_CONCLUSIONS = [
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "stale",
    "startup_failure",
]


def _workflow() -> dict[str, object]:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _steps() -> list[dict[str, object]]:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["auto-merge"]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _step(name: str) -> dict[str, object]:
    matches = [step for step in _steps() if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def _merge_script() -> str:
    script = _step("Merge autonomous fully-green PRs")["run"]
    assert isinstance(script, str)
    return script


def _policy() -> dict:
    return selfdev_policy.load_policy(POLICY_PATH)


def test_workflow_preserves_schedule_concurrency_and_minimum_permissions() -> None:
    workflow = _workflow()
    assert workflow["on"] == {
        "workflow_dispatch": {},
        "schedule": [{"cron": "13 * * * *"}],
    }
    assert workflow["concurrency"] == {
        "group": "pr-auto-merge",
        "cancel-in-progress": "false",
    }
    assert workflow["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "checks": "read",
    }


def test_workflow_checks_out_trusted_main_before_classifying() -> None:
    checkout = _step("Checkout trusted self-development policy")
    assert checkout["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    assert checkout["with"] == {"ref": "main", "fetch-depth": "1"}


def test_workflow_validates_trusted_policy_before_any_merge_logic() -> None:
    steps = _steps()
    names = [step.get("name") for step in steps]
    assert names == [
        "Checkout trusted self-development policy",
        "Validate trusted policy",
        "Merge autonomous fully-green PRs",
    ]
    assert _step("Validate trusted policy")["run"] == "python3 scripts/selfdev_policy.py validate"


def test_workflow_keeps_merge_bounded_and_race_checked() -> None:
    script = _merge_script()
    assert "--squash" in script
    assert "--match-head-commit" in script
    assert "--auto" not in script
    assert "--admin" not in script
    assert "--delete-branch" not in script
    assert "force" not in script.lower()


def test_workflow_uses_trusted_diff_classifier_and_paginated_checks() -> None:
    script = _merge_script()
    assert 'python3 scripts/selfdev_policy.py classify --stdin' in script
    assert 'pulls/$number/files?per_page=100' in script
    assert 'commits/$sha/check-runs?per_page=100' in script
    assert script.count("--paginate") >= 2
    assert "mandatory automated proof set missing/not green" in script


def test_old_nerva_branch_and_attestation_manual_gate_is_gone() -> None:
    script = _merge_script()
    assert "NERVA_BRANCH_PREFIX" not in script
    assert "NERVA2:MOVEMENT-ATTESTATION" not in script
    assert "headRefName" not in script
    assert "body" not in script
    assert "autonomous_merge" in script


@pytest.mark.parametrize("check_name", REQUIRED_CHECKS)
def test_policy_pins_each_mandatory_automated_proof(check_name: str) -> None:
    merge = _policy()["merge"]
    assert check_name in merge["required_check_names"]


@pytest.mark.parametrize("path", PROTECTED_CASES)
def test_root_of_trust_paths_cannot_self_authorize(path: str) -> None:
    result = selfdev_policy.classify([path], _policy())
    assert result["decision"] == "control_plane"
    assert result["autonomous_merge"] is False
    assert result["autonomous_deploy"] is False
    assert result["protected_hits"]


@pytest.mark.parametrize("path", AUTONOMOUS_CASES)
def test_routine_engineering_paths_are_owner_out_of_loop(path: str) -> None:
    result = selfdev_policy.classify([path], _policy())
    assert result["decision"] == "autonomous"
    assert result["autonomous_merge"] is True
    assert result["autonomous_deploy"] is False
    assert result["protected_hits"] == []


@pytest.mark.parametrize("path", BAD_PATH_CASES)
def test_ambiguous_or_escaping_paths_fail_closed(path: str) -> None:
    with pytest.raises(selfdev_policy.PolicyError):
        selfdev_policy.classify([path], _policy())


def _mutated_policy(case: str) -> dict:
    policy = copy.deepcopy(_policy())
    if case == "remove-self-policy-protection":
        policy["protected_paths"].remove("selfdev-policy.json")
    elif case == "remove-workflow-protection":
        policy["protected_paths"].remove(".github/workflows/**")
    elif case == "remove-kernel-protection":
        policy["protected_paths"].remove("agents/core/kernel/**")
    elif case == "disable-autonomous-default":
        policy["autonomous_default"] = False
    elif case == "disable-merge":
        policy["merge"]["enabled"] = False
    elif case == "allow-protected-merge":
        policy["merge"]["deny_protected_changes"] = False
    elif case == "allow-draft-merge":
        policy["merge"]["require_non_draft"] = False
    elif case == "allow-nonclean-merge":
        policy["merge"]["require_clean_merge_state"] = False
    elif case == "allow-no-checks":
        policy["merge"]["require_at_least_one_check"] = False
    elif case == "allow-partial-checks":
        policy["merge"]["require_all_reported_checks_pass"] = False
    elif case == "empty-required-checks":
        policy["merge"]["required_check_names"] = []
    elif case == "duplicate-required-check":
        policy["merge"]["required_check_names"].append(REQUIRED_CHECKS[0])
    elif case == "empty-required-conclusions":
        policy["merge"]["required_check_conclusions"] = []
    elif case == "allow-skipped-required-check":
        policy["merge"]["required_check_conclusions"].append("skipped")
    elif case == "drop-success-from-other-conclusions":
        policy["merge"]["other_check_conclusions"] = ["neutral", "skipped"]
    elif case == "disable-deploy-target":
        policy["deploy"]["target_enabled"] = False
    elif case == "replace-canary-with-direct-deploy":
        policy["deploy"]["strategy"] = "direct"
    elif case == "disable-auto-rollback":
        policy["deploy"]["auto_rollback_on_regression"] = False
    elif case == "disable-review-target":
        policy["review"]["target_independent_reviewer_required"] = False
    elif case == "builder-clears-reviewer-findings":
        policy["review"]["builder_may_clear_own_findings"] = True
    else:  # pragma: no cover - the parametrization is the closed case set
        raise AssertionError(case)
    return policy


@pytest.mark.parametrize("case", POLICY_MUTATIONS)
def test_policy_rejects_control_plane_weakening(case: str) -> None:
    with pytest.raises(selfdev_policy.PolicyError):
        selfdev_policy.validate_policy(_mutated_policy(case))


@pytest.mark.parametrize("conclusion", ALLOWED_OTHER_CONCLUSIONS)
def test_other_reported_checks_have_only_explicit_greenish_conclusions(
    conclusion: str,
) -> None:
    merge = _policy()["merge"]
    assert conclusion in merge["other_check_conclusions"]


@pytest.mark.parametrize("conclusion", DISALLOWED_CONCLUSIONS)
def test_failure_like_conclusions_can_never_unlock_autonomous_merge(
    conclusion: str,
) -> None:
    merge = _policy()["merge"]
    assert conclusion not in merge["required_check_conclusions"]
    assert conclusion not in merge["other_check_conclusions"]
