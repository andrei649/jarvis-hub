"""Root-of-trust tests for Nerva's unattended self-development policy."""

from __future__ import annotations

import json
import subprocess  # nosec B404 — fixed interpreter and repository script
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts import selfdev_policy  # noqa: E402

POLICY_PATH = REPO / "selfdev-policy.json"


def real_policy() -> dict:
    return selfdev_policy.load_policy(POLICY_PATH)


def test_repository_policy_is_valid():
    selfdev_policy.validate_policy(real_policy())


def test_normal_product_change_is_autonomous():
    result = selfdev_policy.classify(
        ["agents/core/agent.py", "tests/test_agent.py"], real_policy()
    )
    assert result["decision"] == "autonomous"
    assert result["autonomous_merge"] is True
    assert result["autonomous_deploy"] is True
    assert result["protected_hits"] == []


@pytest.mark.parametrize(
    "path",
    [
        "selfdev-policy.json",
        "scripts/selfdev_policy.py",
        ".github/workflows/pr-auto-merge.yml",
        ".github/workflows/release.yml",
        ".github/workflows/security.yml",
        "agents/core/kernel/__init__.py",
        "agents/core/kernel/budget.py",
        "agents/core/security/taint.py",
        "AGENTS.md",
        "MAX.md",
    ],
)
def test_root_of_trust_change_cannot_self_authorize(path: str):
    result = selfdev_policy.classify([path], real_policy())
    assert result["decision"] == "control_plane"
    assert result["autonomous_merge"] is False
    assert result["autonomous_deploy"] is False
    assert result["reason"] == "protected_path"
    assert result["protected_hits"][0]["path"] == path


def test_one_protected_path_blocks_a_mixed_change():
    result = selfdev_policy.classify(
        ["frontend/src/app.tsx", "agents/core/kernel/registry.py"], real_policy()
    )
    assert result["decision"] == "control_plane"
    assert result["autonomous_merge"] is False
    assert result["protected_hits"] == [
        {"path": "agents/core/kernel/registry.py", "pattern": "agents/core/kernel/**"}
    ]


def test_empty_diff_is_not_vacuously_safe():
    result = selfdev_policy.classify([], real_policy())
    assert result["decision"] == "control_plane"
    assert result["reason"] == "no_paths"
    assert result["autonomous_merge"] is False


def test_policy_cannot_remove_its_own_protection():
    policy = json.loads(json.dumps(real_policy()))
    policy["protected_paths"] = [
        pattern for pattern in policy["protected_paths"] if pattern != "selfdev-policy.json"
    ]
    with pytest.raises(selfdev_policy.PolicyError, match="selfdev-policy.json"):
        selfdev_policy.validate_policy(policy)


def test_policy_cannot_disable_rollback():
    policy = json.loads(json.dumps(real_policy()))
    policy["deploy"]["auto_rollback_on_regression"] = False
    with pytest.raises(selfdev_policy.PolicyError, match="roll back"):
        selfdev_policy.validate_policy(policy)


def test_policy_rejects_parent_traversal_paths():
    with pytest.raises(selfdev_policy.PolicyError, match="repository-relative"):
        selfdev_policy.classify(["../release.yml"], real_policy())


def test_cli_classifies_newline_delimited_pr_files():
    proc = subprocess.run(  # nosec B603
        [sys.executable, str(REPO / "scripts" / "selfdev_policy.py"), "classify", "--stdin"],
        input="frontend/src/app.tsx\ntests/test_app.py\n",
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["decision"] == "autonomous"
    assert data["autonomous_merge"] is True


def test_cli_reports_protected_change_as_data_not_a_crash():
    proc = subprocess.run(  # nosec B603
        [
            sys.executable,
            str(REPO / "scripts" / "selfdev_policy.py"),
            "classify",
            ".github/workflows/release.yml",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["decision"] == "control_plane"
    assert data["reason"] == "protected_path"
