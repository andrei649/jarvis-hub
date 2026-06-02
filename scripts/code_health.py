#!/usr/bin/env python3
"""Jarvis Hub — code health pass (local-first "find improvements" tool).

Runs the project's static-analysis toolchain in one shot and prints a digest:

  1. lint        — ruff check          (bugs, unused imports, bad patterns)
  2. format      — ruff format --check  (files that need reformatting)
  3. dead-code   — vulture              (unused functions/classes/vars/imports)
  4. complexity  — ruff C901            (functions above max-complexity)

Configuration lives in pyproject.toml ([tool.ruff], [tool.vulture]), so this
script, CI (.github/workflows/code-health.yml) and your editor all agree.

Usage:
    python scripts/code_health.py             # full digest, never fails the shell
    python scripts/code_health.py --json       # machine-readable summary
    python scripts/code_health.py --strict      # exit 1 if any finding (for gating)
    python scripts/code_health.py --only lint    # run a single step
    python scripts/code_health.py --fix          # apply ruff's safe autofixes

Install the toolchain first:  pip install -r requirements-dev.txt
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = ("lint", "format", "dead-code", "complexity")


def _run(cmd: list[str]) -> tuple[int, str]:
    """Run a command from the repo root, returning (exit_code, combined_output)."""
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode, proc.stdout.strip()


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def step_lint(fix: bool) -> dict:
    cmd = ["ruff", "check", "."]
    if fix:
        cmd.append("--fix")
    code, out = _run([*cmd, "--statistics"])
    # ruff --statistics prints one "<count>\t<rule>\t..." line per rule.
    findings = 0
    rules: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip().isdigit():
            n = int(parts[0].strip())
            findings += n
            if len(parts) >= 2:
                rules.append(f"{n:>4}  {parts[1].strip()}  {parts[-1].strip()}")
    return {"name": "lint", "findings": findings, "detail": rules, "raw": out}


def step_format() -> dict:
    code, out = _run(["ruff", "format", "--check", "."])
    # Each file that would be reformatted is printed as "Would reformat: <path>".
    files = [ln.split("Would reformat:", 1)[1].strip()
             for ln in out.splitlines() if "Would reformat:" in ln]
    return {"name": "format", "findings": len(files), "detail": files, "raw": out}


def step_dead_code() -> dict:
    if not _tool_available("vulture"):
        return {"name": "dead-code", "findings": 0, "detail": [], "skipped": True,
                "raw": "vulture not installed (pip install -r requirements-dev.txt)"}
    # Paths + min_confidence come from [tool.vulture] in pyproject.toml.
    code, out = _run(["vulture"])
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return {"name": "dead-code", "findings": len(lines), "detail": lines, "raw": out}


def step_complexity() -> dict:
    # max-complexity comes from [tool.ruff.lint.mccabe] in pyproject.toml.
    code, out = _run(["ruff", "check", ".", "--select", "C901", "--output-format=concise"])
    lines = [ln for ln in out.splitlines() if "C901" in ln]
    return {"name": "complexity", "findings": len(lines), "detail": lines, "raw": out}


def run(only: str | None, fix: bool) -> list[dict]:
    results = []
    if not only or only == "lint":
        results.append(step_lint(fix))
    if not only or only == "format":
        results.append(step_format())
    if not only or only == "dead-code":
        results.append(step_dead_code())
    if not only or only == "complexity":
        results.append(step_complexity())
    return results


def print_digest(results: list[dict]) -> None:
    icons = {True: "⚠️", False: "✅"}
    print("\n┌─ Jarvis Hub · code health ─────────────────────────────")
    for r in results:
        if r.get("skipped"):
            print(f"│ ⏭  {r['name']:<11} skipped — {r['raw']}")
            continue
        n = r["findings"]
        print(f"│ {icons[n > 0]}  {r['name']:<11} {n} finding(s)")
        for line in r["detail"][:15]:
            print(f"│       {line}")
        extra = len(r["detail"]) - 15
        if extra > 0:
            print(f"│       … and {extra} more")
    total = sum(r["findings"] for r in results)
    print("├────────────────────────────────────────────────────────")
    print(f"│ total: {total} finding(s) across {len(results)} step(s)")
    print("└─ tip: `--fix` applies safe autofixes · config in pyproject.toml\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Jarvis Hub code-health pass")
    ap.add_argument("--json", action="store_true", help="emit JSON summary")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any finding")
    ap.add_argument("--fix", action="store_true", help="apply ruff safe autofixes")
    ap.add_argument("--only", choices=STEPS, help="run a single step")
    args = ap.parse_args()

    if not _tool_available("ruff"):
        print("error: ruff not found — run `pip install -r requirements-dev.txt`",
              file=sys.stderr)
        return 2

    results = run(args.only, args.fix)
    total = sum(r["findings"] for r in results)

    if args.json:
        print(json.dumps({"total": total, "steps": results}, indent=2))
    else:
        print_digest(results)

    return 1 if (args.strict and total > 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
