"""Focused tests for the single-pass code-health evidence runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import code_health as health  # noqa: E402


def _available(name: str) -> dict:
    return {
        "name": name,
        "status": "available",
        "version": f"{name} test-version",
        "path": f"/tools/{name}",
        "infra_kind": None,
        "detail": "",
        "duration_ms": 1,
    }


def _missing(name: str) -> dict:
    return {
        "name": name,
        "status": "infra_error",
        "version": None,
        "path": None,
        "infra_kind": "missing_tool",
        "detail": f"{name} is not installed",
        "duration_ms": 0,
    }


def test_run_executes_each_selected_analyzer_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "_inspect_tool", _available)
    outcomes = {
        ("ruff", "check", ".", "--statistics"): health.CommandOutcome(
            1, "2\tF401\tunused import", 11
        ),
        ("ruff", "format", "--check", "--output-format=concise", "."): health.CommandOutcome(
            1,
            "agents/needs_format.py:1:1: unformatted: File would be reformatted",
            12,
        ),
        ("vulture",): health.CommandOutcome(
            3, "agents/old.py:4: unused function 'old' (90% confidence)", 13
        ),
        (
            "ruff",
            "check",
            ".",
            "--select",
            "C901",
            "--output-format=concise",
        ): health.CommandOutcome(0, "", 14),
    }
    calls: list[tuple[str, ...]] = []

    def fake_run(command: list[str]) -> health.CommandOutcome:
        key = tuple(command)
        calls.append(key)
        return outcomes[key]

    monkeypatch.setattr(health, "_run", fake_run)

    report = health.run(only=None, fix=False)

    assert calls == list(outcomes)
    assert report["status"] == "findings"
    assert report["total_findings"] == 4
    assert report["infrastructure_failures"] == 0
    assert [step["status"] for step in report["steps"]] == [
        "findings",
        "findings",
        "findings",
        "clean",
    ]
    assert {step["tool_version"] for step in report["steps"]} == {
        "ruff test-version",
        "vulture test-version",
    }
    assert all(isinstance(step["duration_ms"], int) for step in report["steps"])


def test_missing_required_tool_is_infrastructure_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "_inspect_tool",
        lambda name: _missing(name) if name == "ruff" else _available(name),
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> health.CommandOutcome:
        calls.append(command)
        return health.CommandOutcome(0, "", 2)

    monkeypatch.setattr(health, "_run", fake_run)

    report = health.run(only=None, fix=False)

    assert calls == [["vulture"]]
    assert report["status"] == "infra_error"
    assert report["infrastructure_failures"] == 3
    assert [step["infra_kind"] for step in report["steps"] if step["tool"] == "ruff"] == [
        "missing_tool",
        "missing_tool",
        "missing_tool",
    ]
    assert health._exit_code(report, strict=False) == health.EXIT_INFRA


def test_crashed_analyzer_is_not_misreported_as_a_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "_run",
        lambda command: health.CommandOutcome(2, "ruff panicked", 7),
    )

    result = health.step_complexity(_available("ruff"))

    assert result["status"] == "infra_error"
    assert result["infra_kind"] == "unexpected_exit"
    assert result["findings"] == 0
    assert result["exit_code"] == 2


def test_execution_error_has_distinct_infrastructure_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_oserror(*args, **kwargs):
        raise OSError("cannot execute")

    monkeypatch.setattr(health.subprocess, "run", raise_oserror)

    outcome = health._run(["ruff", "--version"])

    assert outcome.returncode is None
    assert outcome.infra_kind == "execution_error"
    assert "cannot execute" in outcome.output


def test_one_report_can_emit_text_and_json_without_another_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "schema_version": 1,
        "status": "clean",
        "total": 0,
        "total_findings": 0,
        "infrastructure_failures": 0,
        "selected_steps": ["lint"],
        "duration_ms": 9,
        "tools": {"ruff": _available("ruff")},
        "steps": [
            {
                "name": "lint",
                "tool": "ruff",
                "tool_version": "ruff test-version",
                "status": "clean",
                "infra_kind": None,
                "findings": 0,
                "detail": [],
                "raw": "",
                "command": ["ruff", "check", "."],
                "exit_code": 0,
                "duration_ms": 7,
            }
        ],
    }
    calls = 0

    def fake_run(only: str | None, fix: bool) -> dict:
        nonlocal calls
        calls += 1
        return report

    monkeypatch.setattr(health, "run", fake_run)
    destination = tmp_path / "report.json"

    assert health.main(["--json-output", str(destination)]) == health.EXIT_OK
    assert calls == 1
    assert "status: clean" in capsys.readouterr().out
    assert json.loads(destination.read_text(encoding="utf-8")) == report


def test_exit_codes_distinguish_findings_from_infrastructure() -> None:
    findings = {"infrastructure_failures": 0, "total_findings": 2}
    infrastructure = {"infrastructure_failures": 1, "total_findings": 0}

    assert health._exit_code(findings, strict=False) == health.EXIT_OK
    assert health._exit_code(findings, strict=True) == health.EXIT_FINDINGS
    assert health._exit_code(infrastructure, strict=False) == health.EXIT_INFRA
    assert health._exit_code(infrastructure, strict=True) == health.EXIT_INFRA


def test_workflow_runs_analyzers_once_and_bounds_execution() -> None:
    workflow = (REPO / ".github/workflows/code-health.yml").read_text(encoding="utf-8")
    execution_lines = [
        line.strip()
        for line in workflow.splitlines()
        if line.strip().startswith("python scripts/code_health.py")
    ]

    assert execution_lines == [
        "python scripts/code_health.py --json-output code_health.json | tee code_health.txt"
    ]
    assert "set -o pipefail" in workflow
    assert "concurrency:" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "timeout-minutes: 15" in workflow
