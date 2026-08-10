#!/usr/bin/env python3
"""Reject only newly introduced complexity and TypeScript suppression debt.

Legacy findings are compared against the merge-base version of each changed
file, so existing debt can be burned down incrementally without a flag day.
Ruff is a required analyzer: missing tools and analyzer crashes are distinct
infrastructure failures, never a green result.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404 - fixed argv only
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCRIPT_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
NO_CHECK = re.compile(r"@ts-nocheck\b")
COMPLEXITY_TOTAL = re.compile(r"\(\d+\s*>\s*\d+\)")
PROCESS_TIMEOUT_SECONDS = 30

RuffRunner = Callable[[str, str], list[dict[str, Any]]]


class AnalyzerError(RuntimeError):
    """The debt decision could not be measured reliably."""


def _git(args: list[str], *, check: bool = True) -> bytes:
    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603
            ["git", *args],
            cwd=REPO,
            capture_output=True,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalyzerError(f"git command timed out after {PROCESS_TIMEOUT_SECONDS}s") from exc
    if check and proc.returncode != 0:
        raise AnalyzerError(proc.stderr.decode(errors="replace").strip() or "git command failed")
    return proc.stdout


def _name_status(raw: bytes) -> dict[str, str]:
    """Map current paths to their merge-base paths, preserving renames."""
    tokens = [value for value in raw.split(b"\0") if value]
    changed: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        status = tokens[index].decode("ascii", errors="replace")
        index += 1
        if status[:1] in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise AnalyzerError("malformed rename/copy status from git")
            old_path = tokens[index].decode("utf-8", errors="surrogateescape").replace("\\", "/")
            new_path = tokens[index + 1].decode(
                "utf-8", errors="surrogateescape"
            ).replace("\\", "/")
            index += 2
            changed[new_path] = old_path if status.startswith("R") else new_path
        else:
            if index >= len(tokens):
                raise AnalyzerError("malformed path status from git")
            path = tokens[index].decode("utf-8", errors="surrogateescape").replace("\\", "/")
            index += 1
            changed.setdefault(path, path)
    return changed


def changed_files(base: str) -> dict[str, str]:
    try:
        committed = _name_status(
            _git(
                [
                    "diff",
                    "--name-status",
                    "-z",
                    "--find-renames",
                    "--diff-filter=ACMR",
                    f"{base}...HEAD",
                ]
            )
        )
    except AnalyzerError as exc:
        raise AnalyzerError(f"cannot discover changes from {base}: {exc}") from exc
    local = _name_status(
        _git(
            [
                "diff",
                "--name-status",
                "-z",
                "--find-renames",
                "--diff-filter=ACMR",
                "HEAD",
            ]
        )
    )
    untracked = _git(["ls-files", "--others", "--exclude-standard", "-z"])
    changed = dict(committed)
    for path, old_path in local.items():
        changed.setdefault(path, old_path)
    for value in untracked.split(b"\0"):
        if value:
            path = value.decode("utf-8", errors="surrogateescape").replace("\\", "/")
            changed.setdefault(path, path)
    return dict(sorted(changed.items()))


def changed_paths(base: str) -> list[str]:
    return list(changed_files(base))


def _base_content(base: str, path: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603
            ["git", "show", f"{base}:{path}"],
            cwd=REPO,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalyzerError(f"git show timed out after {PROCESS_TIMEOUT_SECONDS}s") from exc
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace")


def _current_content(path: str) -> str:
    candidate = REPO / path
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8", errors="replace")


def _ruff_complexity(content: str, filename: str) -> list[dict[str, Any]]:
    if shutil.which("ruff") is None:
        raise AnalyzerError("required analyzer ruff is not installed")
    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603
            [
                "ruff",
                "check",
                "--select",
                "C901",
                "--output-format=json",
                "--stdin-filename",
                filename,
                "-",
            ],
            cwd=REPO,
            input=content,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalyzerError(
            f"ruff complexity analyzer timed out after {PROCESS_TIMEOUT_SECONDS}s"
        ) from exc
    if proc.returncode not in {0, 1}:
        raise AnalyzerError(
            f"ruff complexity analyzer failed for {filename}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise AnalyzerError(f"ruff returned invalid JSON for {filename}") from exc
    if not isinstance(payload, list):
        raise AnalyzerError(f"ruff returned an invalid result for {filename}")
    return payload


def _fingerprint(item: dict[str, Any]) -> tuple[str, str]:
    message = COMPLEXITY_TOTAL.sub("(complexity > limit)", str(item.get("message", "")))
    return str(item.get("code", "")), message


def compare_file(
    path: str,
    *,
    base_content: str,
    current_content: str,
    ruff_runner: RuffRunner = _ruff_complexity,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        before = Counter(_fingerprint(item) for item in ruff_runner(base_content, path))
        for item in ruff_runner(current_content, path):
            fingerprint = _fingerprint(item)
            if before[fingerprint]:
                before[fingerprint] -= 1
                continue
            location = item.get("location") or {}
            findings.append(
                {
                    "kind": "C901",
                    "path": path,
                    "line": int(location.get("row", 1)),
                    "message": str(item.get("message", "new excessive complexity")),
                }
            )
    if suffix in SCRIPT_EXTENSIONS:
        old_count = len(NO_CHECK.findall(base_content))
        new_count = len(NO_CHECK.findall(current_content))
        for index in range(max(0, new_count - old_count)):
            marker_number = old_count + index + 1
            line = next(
                (
                    number
                    for number, value in enumerate(current_content.splitlines(), start=1)
                    if "@ts-nocheck" in value
                ),
                1,
            )
            findings.append(
                {
                    "kind": "ts-nocheck",
                    "path": path,
                    "line": line,
                    "message": f"new @ts-nocheck suppression #{marker_number}",
                }
            )
    return findings


def evaluate(
    paths: list[str],
    *,
    base: str,
    base_reader: Callable[[str, str], str] = _base_content,
    current_reader: Callable[[str], str] = _current_content,
    ruff_runner: RuffRunner = _ruff_complexity,
    base_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    relevant = [
        path
        for path in sorted(set(paths))
        if Path(path).suffix.lower() == ".py" or Path(path).suffix.lower() in SCRIPT_EXTENSIONS
    ]
    findings = []
    for path in relevant:
        findings.extend(
            compare_file(
                path,
                base_content=base_reader(base, (base_paths or {}).get(path, path)),
                current_content=current_reader(path),
                ruff_runner=ruff_runner,
            )
        )
    return {
        "schema_version": 1,
        "status": "failed" if findings else "passed",
        "base": base,
        "files_checked": relevant,
        "new_debt_count": len(findings),
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        base_paths = (
            {path: path for path in args.changed_file}
            if args.changed_file
            else changed_files(args.base)
        )
        result = evaluate(list(base_paths), base=args.base, base_paths=base_paths)
    except (OSError, AnalyzerError) as exc:
        result = {
            "schema_version": 1,
            "status": "error",
            "base": args.base,
            "files_checked": [],
            "new_debt_count": 0,
            "findings": [],
            "error": str(exc),
        }
        print(json.dumps(result, sort_keys=True) if args.json else f"health debt: ERROR — {exc}")
        return 2

    for finding in result["findings"]:
        print(
            f"::error file={finding['path']},line={finding['line']},title=New {finding['kind']} debt::"
            f"{finding['message']}",
            file=sys.stderr,
        )
    print(
        json.dumps(result, sort_keys=True)
        if args.json
        else f"health debt: {result['status'].upper()} ({result['new_debt_count']} new findings)"
    )
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
