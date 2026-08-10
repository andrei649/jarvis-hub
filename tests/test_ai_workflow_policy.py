"""Focused guards for the canonical AI-development control-plane policy."""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_ai_workflow_policy import (  # noqa: E402
    DERIVED_DOCUMENTS,
    HISTORICAL_DOCUMENTS,
    POLICY_RELATIVE,
    PR_TEMPLATE_RELATIVE,
    RECEIPT_FIELDS,
    load_policy,
    main,
    validate_evidence_receipt,
    validate_policy,
    validate_repository,
)


def _policy() -> dict:
    data, errors = load_policy(REPO / POLICY_RELATIVE)
    assert errors == []
    assert isinstance(data, dict)
    return data


def _copy_policy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in (
        POLICY_RELATIVE,
        PR_TEMPLATE_RELATIVE,
        *DERIVED_DOCUMENTS,
        *HISTORICAL_DOCUMENTS,
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, destination)
    return root


def test_repository_ai_workflow_policy_is_consistent() -> None:
    assert validate_repository(REPO) == []
    trusted = (REPO / ".github/workflows/trusted-governance.yml").read_text(encoding="utf-8")
    assert "pull_request_target:" in trusted
    assert "persist-credentials: false" in trusted
    assert 'ref: ${{ github.event.pull_request.base.sha }}' in trusted
    assert "python scripts/change_risk.py" in trusted
    assert ".commit_id == $head" in trusted
    assert "github.event.pull_request.head.sha" in trusted
    assert "contents: read" in trusted and "pull-requests: read" in trusted
    assert "checkout the candidate" not in trusted.lower()


def test_policy_separates_state_and_binds_evidence_to_exact_head() -> None:
    policy = _policy()

    assert set(policy["state_machines"]) == {"delivery", "ci", "governance", "lease"}
    assert policy["evidence_receipt"]["bind_to"] == "exact_head_sha"
    assert policy["evidence_receipt"]["reuse"] == {
        "allowed": True,
        "requires_same_head_sha": True,
        "requires_same_policy_id": True,
        "requires_same_policy_schema_version": True,
        "requires_unchanged_relevant_inputs": True,
        "otherwise_state": "stale",
    }
    assert "stale" in policy["state_machines"]["ci"]["transitions"]["passed"]
    assert "stale" in policy["state_machines"]["governance"]["transitions"]["approved"]
    assert policy["automated_risk_mapping"]["mapping"] == {
        "low": "R0",
        "medium": "R2",
        "high": "R3",
    }
    assert policy["coordination"]["lease_system_of_record"] == "none"
    assert policy["coordination"]["planned_lease_system_of_record"] == "github"
    assert policy["coordination"]["lease_enforcement_status"] == "not_implemented"
    receipt = {
        "policy_id": policy["policy_id"],
        "policy_schema_version": policy["schema_version"],
        "head_sha": "a" * 40,
        "risk_tier": "R2",
        "changed_paths": ["agents/web.py"],
        "commands": [{"name": "test", "argv": ["python", "-m", "pytest"], "cwd": "."}],
        "results": [
            {
                "command": ["python", "-m", "pytest"],
                "exit_code": 0,
                "summary": "tests passed",
            }
        ],
        "producer": "test:policy",
        "generated_at": "2026-08-10T12:00:00Z",
    }
    assert set(receipt) >= RECEIPT_FIELDS
    assert validate_evidence_receipt(receipt, policy) == []
    missing_producer = copy.deepcopy(receipt)
    missing_producer.pop("producer")
    assert "receipt missing canonical fields: producer" in validate_evidence_receipt(
        missing_producer, policy
    )
    wrong_mapping = {**receipt, "classification": {"risk_level": "high"}}
    assert "receipt.risk_tier does not match the automated change-risk mapping" in (
        validate_evidence_receipt(wrong_mapping, policy)
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda policy: policy["preflight"].update(automatic_rebase=True),
            "preflight.automatic_rebase must be false",
        ),
        (
            lambda policy: policy["coordination"].update(draft_pr_is_lock=True),
            "coordination.draft_pr_is_lock must be false",
        ),
        (
            lambda policy: policy["coordination"].update(lease_system_of_record="github"),
            "coordination.lease_system_of_record must be none until enforcement exists",
        ),
        (
            lambda policy: policy["automated_risk_mapping"]["mapping"].update(medium="R1"),
            "automated_risk_mapping.mapping must conservatively map low->R0, medium->R2, and high->R3",
        ),
        (
            lambda policy: policy["review"].update(max_normal_rounds=3),
            "review.max_normal_rounds must be 2",
        ),
        (
            lambda policy: policy["evidence_receipt"]["reuse"].update(
                requires_same_head_sha=False
            ),
            "evidence_receipt.reuse.requires_same_head_sha must be true",
        ),
        (
            lambda policy: policy["change_control"].update(
                direct_push_to_default_branch=True
            ),
            "change_control.direct_push_to_default_branch must be false",
        ),
    ],
)
def test_policy_lint_fails_closed_on_unsafe_rule_changes(mutate, expected: str) -> None:
    policy = copy.deepcopy(_policy())
    mutate(policy)

    assert expected in validate_policy(policy)


def test_repository_lint_rejects_reintroduced_stale_guidance(tmp_path: Path) -> None:
    root = _copy_policy_fixture(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8")
        + "\nLegacy instruction: git pull --rebase origin master\n"
        + "GitHub-backed path-prefix leases are the coordination system of record.\n",
        encoding="utf-8",
    )

    errors = validate_repository(root)

    assert any("obsolete default branch and unconditional sync" in error for error in errors)
    assert any("unenforced remote-lease claim" in error for error in errors)


def test_repository_lint_requires_historical_status_banner(tmp_path: Path) -> None:
    root = _copy_policy_fixture(tmp_path)
    summary = root / ".opencode/summary.md"
    summary.write_text(
        "# Current instructions\n\nSee .github/ai-development-policy.json.\n",
        encoding="utf-8",
    )

    errors = validate_repository(root)

    assert ".opencode/summary.md: missing historical/superseded status" in "\n".join(errors)
    assert ".opencode/summary.md: missing instructional: false" in "\n".join(errors)


def test_policy_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text('{"schema_version": 1, "schema_version": 2}\n', encoding="utf-8")

    data, errors = load_policy(policy_path)

    assert data is None
    assert len(errors) == 1
    assert "duplicate JSON key: schema_version" in errors[0]


def test_cli_emits_machine_readable_success(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(REPO), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"errors": [], "ok": True}
