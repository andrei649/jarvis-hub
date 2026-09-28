"""Fail-closed contract tests for Nerva's policy-driven autonomous merge lane.

This file intentionally keeps the same collected-case count as the policy suite it
replaces. The old contract pinned ``nerva2/*`` as manual-only; the 2026-09-09
owner directive replaces branch-name ceremony with a trusted, machine-readable
root-of-trust policy plus a mandatory automated proof floor.
"""

from __future__ import annotations

import copy
import json
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


#: The owner's local-development grant as it reads when given in full.
LOCAL_GRANT = {"enabled": True, "allow_protected_changes": True, "require_owner_approval": False}

#: The ways the owner revokes the local-development grant in selfdev-policy.json;
#: validate_policy accepts every one of them (the block is optional).
GRANT_REVOCATIONS = {
    "enabled-false": lambda local: {**local, "enabled": False},
    "owner-approval-required": lambda local: {**local, "require_owner_approval": True},
    "protected-changes-disallowed": lambda local: {**local, "allow_protected_changes": False},
    "block-removed": lambda local: None,
}


def _with_local_development(local: dict | None) -> dict:
    """A deep copy of the committed policy with ``local_development`` set explicitly
    (``None`` removes the block). The grant's semantics are tested on these synthetic
    copies, so they never depend on whether the owner's file still carries the grant
    (review F0)."""
    policy = copy.deepcopy(_policy())
    if local is None:
        policy.pop("local_development", None)
    else:
        policy["local_development"] = dict(local)
    selfdev_policy.validate_policy(policy)
    return policy


def test_owner_authorizes_local_development_on_every_repository_path() -> None:
    policy = _with_local_development(LOCAL_GRANT)
    for path in PROTECTED_CASES + AUTONOMOUS_CASES:
        result = selfdev_policy.classify([path], policy)
        assert result["autonomous_local_development"] is True, path
    assert selfdev_policy.classify([], policy)["autonomous_local_development"] is False
    unprotected_only = _with_local_development({**LOCAL_GRANT, "allow_protected_changes": False})
    for path in AUTONOMOUS_CASES:
        assert selfdev_policy.classify([path], unprotected_only)["autonomous_local_development"] is True
    for path in PROTECTED_CASES:
        assert selfdev_policy.classify([path], unprotected_only)["autonomous_local_development"] is False


def test_local_authorization_does_not_grant_merge_or_deploy() -> None:
    """The structural invariant, and the one test here that reads the committed file:
    protected paths never merge or deploy autonomously, whatever local_development says."""
    variants = [_policy(), _with_local_development(LOCAL_GRANT), _with_local_development(None)]
    variants += [_with_local_development(revoke(LOCAL_GRANT)) for revoke in GRANT_REVOCATIONS.values()
                 if revoke(LOCAL_GRANT) is not None]
    for policy in variants:
        for paths in [PROTECTED_CASES] + [[path] for path in PROTECTED_CASES]:
            result = selfdev_policy.classify(paths, policy)
            assert result["autonomous_merge"] is False, paths
            assert result["autonomous_deploy"] is False, paths
            assert result["decision"] == "control_plane", paths


def test_local_authorization_can_be_revoked_and_is_not_inferred() -> None:
    for name, revoke in GRANT_REVOCATIONS.items():
        policy = _with_local_development(revoke(LOCAL_GRANT))
        result = selfdev_policy.classify(PROTECTED_CASES, policy)
        assert result["autonomous_local_development"] is False, name
    for field in LOCAL_GRANT:
        partial = {key: value for key, value in LOCAL_GRANT.items() if key != field}
        policy = _with_local_development(None)
        policy["local_development"] = partial
        with pytest.raises(selfdev_policy.PolicyError):
            selfdev_policy.classify(PROTECTED_CASES, policy)


def test_local_authorization_rejects_malformed_configuration() -> None:
    for invalid in (None, True, {}, {"enabled": "true"}):
        policy = copy.deepcopy(_policy())
        policy["local_development"] = invalid
        with pytest.raises(selfdev_policy.PolicyError):
            selfdev_policy.validate_policy(policy)


#: Every test in this file that concerns the local-development grant.
LOCAL_DEVELOPMENT_TESTS = (
    "test_owner_authorizes_local_development_on_every_repository_path",
    "test_local_authorization_does_not_grant_merge_or_deploy",
    "test_local_authorization_can_be_revoked_and_is_not_inferred",
    "test_local_authorization_rejects_malformed_configuration",
)


@pytest.mark.parametrize("revocation", sorted(GRANT_REVOCATIONS))
def test_revoking_the_committed_grant_keeps_this_suite_green(
    revocation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review F0: the grant is the owner's to revoke in selfdev-policy.json, and a
    revocation PR must not need these tests edited to go green. Only the structural
    invariant reads the committed file; the grant's semantics run on synthetic copies."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    local = GRANT_REVOCATIONS[revocation](dict(policy.get("local_development") or LOCAL_GRANT))
    if local is None:
        policy.pop("local_development", None)
    else:
        policy["local_development"] = local
    selfdev_policy.validate_policy(policy)
    revoked = tmp_path / "selfdev-policy.json"
    revoked.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "POLICY_PATH", revoked)
    assert _policy() == policy
    for name in LOCAL_DEVELOPMENT_TESTS:
        globals()[name]()


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
