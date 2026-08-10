#!/usr/bin/env python3
"""Run Nerva's static-analysis toolchain once and emit text and/or JSON evidence.

Findings remain advisory unless ``--strict`` is selected. Missing tools, tool
crashes, timeouts, unexpected exit codes, and unparseable failing output are
infrastructure failures and always exit 2.

Usage:
    python scripts/code_health.py
    python scripts/code_health.py --json
    python scripts/code_health.py --json-output code_health.json
    python scripts/code_health.py --strict
    python scripts/code_health.py --only lint
    python scripts/code_health.py --fix

Install the pinned toolchain with:
    pip install --require-hashes -r requirements-dev.lock
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STEPS = ("lint", "format", "dead-code", "complexity")
STEP_TO_TOOL = {
    "lint": "ruff",
    "format": "ruff",
    "dead-code": "vulture",
    "complexity": "ruff",
}
COMMAND_TIMEOUT_SECONDS = 300
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_INFRA = 2
VULTURE_FINDING = re.compile(r"^.+:\d+: .+ \(\d+% confidence\)$")
RUFF_FORMAT_FINDING = re.compile(r"^(?P<path>.+):\d+:\d+: unformatted: File would be reformatted$")


@dataclass(frozen=True)
class CommandOutcome:
    """One command execution, including infrastructure failure information."""

    returncode: int | None
    output: str
    duration_ms: int
    infra_kind: str | None = None


@dataclass(frozen=True)
class ParsedFindings:
    """Analyzer findings with a compact digest independent of the total count."""

    count: int
    detail: list[str]


def _run(cmd: list[str]) -> CommandOutcome:
    """Run a command from the repository root without hiding execution failures."""

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandOutcome(
            returncode=None,
            output=str(exc),
            duration_ms=_elapsed_ms(started),
            infra_kind="missing_tool",
        )
    except subprocess.TimeoutExpired as exc:
        output = _coerce_output(exc.stdout)
        return CommandOutcome(
            returncode=None,
            output=output or f"command timed out after {COMMAND_TIMEOUT_SECONDS}s",
            duration_ms=_elapsed_ms(started),
            infra_kind="timeout",
        )
    except OSError as exc:
        return CommandOutcome(
            returncode=None,
            output=str(exc),
            duration_ms=_elapsed_ms(started),
            infra_kind="execution_error",
        )
    return CommandOutcome(
        returncode=proc.returncode,
        output=proc.stdout.strip(),
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace").strip()
    return output.strip()


def _inspect_tool(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    if path is None:
        return {
            "name": name,
            "status": "infra_error",
            "version": None,
            "path": None,
            "infra_kind": "missing_tool",
            "detail": f"{name} is not installed",
            "duration_ms": 0,
        }

    outcome = _run([name, "--version"])
    if outcome.infra_kind is not None or outcome.returncode != 0:
        return {
            "name": name,
            "status": "infra_error",
            "version": None,
            "path": path,
            "infra_kind": outcome.infra_kind or "version_probe_failed",
            "detail": outcome.output or f"{name} --version exited {outcome.returncode}",
            "duration_ms": outcome.duration_ms,
        }
    return {
        "name": name,
        "status": "available",
        "version": outcome.output,
        "path": path,
        "infra_kind": None,
        "detail": "",
        "duration_ms": outcome.duration_ms,
    }


def _infra_step(
    name: str,
    tool: dict[str, Any],
    *,
    command: list[str],
    infra_kind: str,
    raw: str,
    duration_ms: int,
    exit_code: int | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "tool": tool["name"],
        "tool_version": tool.get("version"),
        "status": "infra_error",
        "infra_kind": infra_kind,
        "findings": 0,
        "detail": [],
        "raw": raw,
        "command": command,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }


def _tool_failure_step(name: str, tool: dict[str, Any], command: list[str]) -> dict[str, Any]:
    return _infra_step(
        name,
        tool,
        command=command,
        infra_kind=str(tool.get("infra_kind") or "tool_probe_failed"),
        raw=str(tool.get("detail") or "required tool is unavailable"),
        duration_ms=int(tool.get("duration_ms") or 0),
        exit_code=None,
    )


def _completed_step(
    name: str,
    tool: dict[str, Any],
    command: list[str],
    outcome: CommandOutcome,
    parsed: ParsedFindings,
) -> dict[str, Any]:
    return {
        "name": name,
        "tool": tool["name"],
        "tool_version": tool["version"],
        "status": "findings" if parsed.count else "clean",
        "infra_kind": None,
        "findings": parsed.count,
        "detail": parsed.detail,
        "raw": outcome.output,
        "command": command,
        "exit_code": outcome.returncode,
        "duration_ms": outcome.duration_ms,
    }


def _execute_step(
    name: str,
    tool: dict[str, Any],
    command: list[str],
    parser: Callable[[str], ParsedFindings],
    *,
    expected_exit_codes: set[int] | None = None,
) -> dict[str, Any]:
    if tool["status"] != "available":
        return _tool_failure_step(name, tool, command)

    outcome = _run(command)
    if outcome.infra_kind is not None:
        return _infra_step(
            name,
            tool,
            command=command,
            infra_kind=outcome.infra_kind,
            raw=outcome.output,
            duration_ms=outcome.duration_ms,
            exit_code=outcome.returncode,
        )

    allowed = expected_exit_codes or {0, 1}
    if outcome.returncode not in allowed:
        return _infra_step(
            name,
            tool,
            command=command,
            infra_kind="unexpected_exit",
            raw=outcome.output,
            duration_ms=outcome.duration_ms,
            exit_code=outcome.returncode,
        )

    parsed = parser(outcome.output)
    if outcome.returncode != 0 and parsed.count == 0:
        return _infra_step(
            name,
            tool,
            command=command,
            infra_kind="unparseable_failure",
            raw=outcome.output,
            duration_ms=outcome.duration_ms,
            exit_code=outcome.returncode,
        )
    return _completed_step(name, tool, command, outcome, parsed)


def _parse_lint(output: str) -> ParsedFindings:
    rules: list[str] = []
    findings = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip().isdigit():
            count = int(parts[0].strip())
            findings += count
            label = parts[1].strip() if len(parts) >= 2 else "unknown"
            description = parts[-1].strip() if len(parts) >= 3 else ""
            rules.append(f"{count:>4}  {label}  {description}".strip())
    return ParsedFindings(findings, rules)


def _parse_format(output: str) -> ParsedFindings:
    files = [
        match.group("path")
        for line in output.splitlines()
        if (match := RUFF_FORMAT_FINDING.match(line.strip()))
    ]
    if files:
        return ParsedFindings(len(files), files)

    # Retain compatibility with Ruff's older human-readable formatter output.
    files = [
        line.split("Would reformat:", 1)[1].strip()
        for line in output.splitlines()
        if "Would reformat:" in line
    ]
    return ParsedFindings(len(files), files)


def _parse_dead_code(output: str) -> ParsedFindings:
    lines = [line for line in output.splitlines() if VULTURE_FINDING.match(line.strip())]
    return ParsedFindings(len(lines), lines)


def _parse_complexity(output: str) -> ParsedFindings:
    lines = [line for line in output.splitlines() if "C901" in line]
    return ParsedFindings(len(lines), lines)


def step_lint(fix: bool, tool: dict[str, Any]) -> dict[str, Any]:
    command = ["ruff", "check", "."]
    if fix:
        command.append("--fix")
    command.append("--statistics")
    return _execute_step("lint", tool, command, _parse_lint)


def step_format(tool: dict[str, Any]) -> dict[str, Any]:
    command = ["ruff", "format", "--check", "--output-format=concise", "."]
    return _execute_step("format", tool, command, _parse_format)


def step_dead_code(tool: dict[str, Any]) -> dict[str, Any]:
    command = ["vulture"]
    # Vulture's public exit contract is 0=no debt, 3=dead code, while 1 and 2
    # mean invalid input/CLI. Treat only the measured-debt code as a finding.
    return _execute_step("dead-code", tool, command, _parse_dead_code, expected_exit_codes={0, 3})


def step_complexity(tool: dict[str, Any]) -> dict[str, Any]:
    command = ["ruff", "check", ".", "--select", "C901", "--output-format=concise"]
    return _execute_step("complexity", tool, command, _parse_complexity)


def run(only: str | None, fix: bool) -> dict[str, Any]:
    """Run each selected analyzer exactly once and build a reusable report."""

    started = time.perf_counter()
    selected = [only] if only else list(STEPS)
    required_tools = sorted({STEP_TO_TOOL[name] for name in selected})
    tools = {name: _inspect_tool(name) for name in required_tools}
    functions = {
        "lint": lambda: step_lint(fix, tools["ruff"]),
        "format": lambda: step_format(tools["ruff"]),
        "dead-code": lambda: step_dead_code(tools["vulture"]),
        "complexity": lambda: step_complexity(tools["ruff"]),
    }
    results = [functions[name]() for name in selected]
    total = sum(result["findings"] for result in results)
    infra_failures = sum(result["status"] == "infra_error" for result in results)
    status = "infra_error" if infra_failures else ("findings" if total else "clean")
    return {
        "schema_version": 1,
        "status": status,
        "total": total,
        "total_findings": total,
        "infrastructure_failures": infra_failures,
        "selected_steps": selected,
        "duration_ms": _elapsed_ms(started),
        "tools": tools,
        "steps": results,
    }


def print_digest(report: dict[str, Any]) -> None:
    print("\n┌─ Nerva · code health ──────────────────────────────────")
    for result in report["steps"]:
        if result["status"] == "infra_error":
            print(f"│ ❌  {result['name']:<11} infrastructure error [{result['infra_kind']}]")
            if result["raw"]:
                print(f"│       {result['raw'].splitlines()[0]}")
            continue
        icon = "⚠️" if result["findings"] else "✅"
        version = result["tool_version"] or "unknown version"
        print(
            f"│ {icon}  {result['name']:<11} {result['findings']} finding(s) "
            f"· {version} · {result['duration_ms']}ms"
        )
        for line in result["detail"][:15]:
            print(f"│       {line}")
        extra = len(result["detail"]) - 15
        if extra > 0:
            print(f"│       … and {extra} more")
    print("├────────────────────────────────────────────────────────")
    print(
        f"│ status: {report['status']} · {report['total_findings']} finding(s) · "
        f"{report['infrastructure_failures']} infrastructure failure(s) · "
        f"{report['duration_ms']}ms"
    )
    print("└─ findings are advisory; infrastructure failures exit 2\n")


def _exit_code(report: dict[str, Any], *, strict: bool) -> int:
    if report["infrastructure_failures"]:
        return EXIT_INFRA
    if strict and report["total_findings"]:
        return EXIT_FINDINGS
    return EXIT_OK


def _json_text(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nerva code-health pass")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="emit JSON only")
    output.add_argument("--json-output", type=Path, help="also write JSON while printing text")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any finding")
    parser.add_argument("--fix", action="store_true", help="apply Ruff safe autofixes")
    parser.add_argument("--only", choices=STEPS, help="run a single step")
    args = parser.parse_args(argv)

    report = run(args.only, args.fix)
    serialized = _json_text(report)
    if args.json:
        print(serialized, end="")
    else:
        print_digest(report)

    if args.json_output is not None:
        try:
            args.json_output.write_text(serialized, encoding="utf-8", newline="\n")
        except OSError as exc:
            print(
                f"error: cannot write JSON evidence to {args.json_output}: {exc}",
                file=sys.stderr,
            )
            return EXIT_INFRA

    return _exit_code(report, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
