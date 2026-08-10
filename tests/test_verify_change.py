from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("verify_change", SCRIPTS / "verify_change.py")
assert SPEC and SPEC.loader
verify_change = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_change)


def _classification(*lanes: str) -> dict:
    return {
        "risk_level": "medium",
        "scopes": ["python-runtime"],
        "required_lanes": list(lanes),
    }


def test_docs_plan_has_only_fast_dependency_free_checks():
    plan = verify_change.build_plan(
        _classification("docs-policy"),
        mode="draft",
        base_sha="a" * 40,
        changes=[{"status": "M", "path": "docs/example.md"}],
    )
    assert [item["name"] for item in plan] == [
        "diff-integrity",
        "worktree-diff-integrity",
        "ai-policy",
        "generated-truth",
    ]


def test_draft_python_plan_targets_changed_tests_and_fast_fails(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: self.name == "test_change_risk.py")
    changes = [{"status": "M", "path": "tests/test_change_risk.py"}]
    plan = verify_change.build_plan(
        _classification("python-ubuntu", "python-windows"),
        mode="draft",
        base_sha="b" * 40,
        changes=changes,
    )
    test_command = next(item for item in plan if item["name"] == "python-tests")
    assert "tests/test_change_risk.py" in test_command["argv"]
    assert "tests/" not in test_command["argv"]
    assert "--maxfail=1" in test_command["argv"]
    assert "--timeout=90" in test_command["argv"]
    assert test_command["argv"][test_command["argv"].index("-n") + 1] == "auto"
    assert [item["name"] for item in plan].count("ruff") == 1
    assert [item["name"] for item in plan].count("new-health-debt") == 1


def test_ready_and_full_suite_plan_use_complete_python_suite():
    for mode, lanes in (("ready", ("python-ubuntu",)), ("draft", ("full-suite",))):
        plan = verify_change.build_plan(
            _classification(*lanes),
            mode=mode,
            base_sha="c" * 40,
            changes=[{"status": "M", "path": "tests/test_change_risk.py"}],
        )
        test_command = next(item for item in plan if item["name"] == "python-tests")
        assert "tests/" in test_command["argv"]
        assert ("--maxfail=1" in test_command["argv"]) is (mode == "draft")


def test_frontend_and_mobile_lanes_are_mapped_once():
    plan = verify_change.build_plan(
        _classification("frontend", "mobile"),
        mode="draft",
        base_sha="d" * 40,
        changes=[],
    )
    names = [item["name"] for item in plan]
    assert names[-5:] == [
        "frontend-root",
        "frontend-typecheck",
        "frontend-tests",
        "frontend-build",
        "mobile-tests",
    ]
    assert len(names) == len(set(names))


def test_execute_plan_stops_at_first_failure_in_draft():
    calls = []

    def runner(argv, cwd):
        calls.append((argv, cwd))
        return (1 if argv == ["bad"] else 0), "output"

    plan = [
        {"name": "first", "argv": ["ok"], "cwd": "."},
        {"name": "second", "argv": ["bad"], "cwd": "."},
        {"name": "third", "argv": ["never"], "cwd": "."},
    ]
    code, results = verify_change.execute_plan(plan, mode="draft", runner=runner)
    assert code == 1
    assert [item["name"] for item in results] == ["first", "second"]
    assert len(calls) == 2


def test_ready_execution_collects_all_failures():
    plan = [
        {"name": "one", "argv": ["infra"], "cwd": "."},
        {"name": "two", "argv": ["bad"], "cwd": "."},
        {"name": "three", "argv": ["ok"], "cwd": "."},
    ]
    code, results = verify_change.execute_plan(
        plan,
        mode="ready",
        runner=lambda argv, cwd: (
            2 if argv == ["infra"] else (1 if argv == ["bad"] else 0),
            "evidence",
        ),
    )
    assert code == 2
    assert [item["status"] for item in results] == ["infra_error", "failed", "passed"]
    assert results[0]["command"] == ["infra"]
    assert results[0]["exit_code"] == 2
    assert results[0]["infra_kind"] == "nonstandard_exit"
    assert results[0]["summary"] == "evidence"

    def timeout_runner(argv, cwd):
        raise subprocess.TimeoutExpired(argv, verify_change.COMMAND_TIMEOUT_SECONDS)

    timeout_code, timeout_results = verify_change.execute_plan(
        [{"name": "timeout", "argv": ["slow"], "cwd": "."}],
        mode="ready",
        runner=timeout_runner,
    )
    assert timeout_code == 2
    assert timeout_results[0]["status"] == "infra_error"
    assert timeout_results[0]["infra_kind"] == "timeout"


def test_worktree_digest_binds_file_contents(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_change, "REPO", tmp_path)
    target = tmp_path / "sample.txt"
    target.write_text("one", encoding="utf-8")
    changes = [{"status": "M", "path": "sample.txt"}]
    first = verify_change.worktree_digest(changes)
    target.write_text("two", encoding="utf-8")
    second = verify_change.worktree_digest(changes)
    assert first != second
    assert len(first) == hashlib.sha256().digest_size * 2


def test_markdown_receipt_contains_exact_head_and_commands():
    policy = json.loads(
        (ROOT / ".github" / "ai-development-policy.json").read_text(encoding="utf-8")
    )
    commands = [{"name": "policy", "argv": ["python", "check.py"], "cwd": "."}]
    receipt = verify_change.build_receipt(
        policy=policy,
        mode="draft",
        base_sha="d" * 40,
        head_sha="e" * 40,
        changes=[{"status": "M", "path": "tests/test_verify_change.py"}],
        classification=_classification("docs-policy"),
        commands=commands,
        results=[
            {
                "name": "policy",
                "argv": ["python", "check.py"],
                "command": ["python", "check.py"],
                "cwd": ".",
                "exit_code": 0,
                "status": "passed",
                "duration_seconds": 0.1,
                "summary": "policy passed",
            }
        ],
        status="passed",
        producer="test:verifier",
        generated_at="2026-08-10T12:00:00Z",
    )
    required = verify_change.check_ai_workflow_policy.RECEIPT_FIELDS
    assert set(receipt) >= required
    assert receipt["risk_tier"] == "R2"
    assert receipt["changed_paths"] == ["tests/test_verify_change.py"]
    assert verify_change.check_ai_workflow_policy.validate_evidence_receipt(receipt, policy) == []
    assert verify_change.default_producer({"GITHUB_ACTOR": "nerva-bot"}) == "github:nerva-bot"
    rendered = verify_change.render_markdown(receipt)
    assert "e" * 40 in rendered
    assert "R2" in rendered
    assert "test:verifier" in rendered
    assert "python check.py" in rendered
    assert "| policy | passed | 0.1 |" in rendered
