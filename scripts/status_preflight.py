#!/usr/bin/env python3
"""Run the generated-status check selected from the changed-file set.

The command is intentionally narrow: it only reasons about inputs and projections
owned by ``scripts/status_sync.py``. It does not select or run application tests.
BACKLOG/registry/version/route-snapshot changes use tracked test counts and normally
finish in well under 30 seconds.
"""

from __future__ import annotations

import argparse
import json

# Local CLI executes fixed Python/git argv and never invokes a shell.
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATUS_SYNC = REPO / "scripts" / "status_sync.py"
PROJECT_STATUS = REPO / "project-status.json"
FAST_CHECK_ARGS = [
    str(STATUS_SYNC),
    "--check",
    "--reuse-test-counts",
    "--json",
]
FAST_FIX_COMMAND = "python scripts/status_sync.py --reuse-test-counts"

STATUS_SOURCE_FILES = {
    "BACKLOG.md",
    "agents/__init__.py",
    "agents/_system/agents.yaml",
    "tests/_snapshots/route_surface.json",
    "scripts/status_sync.py",
}
STATUS_GENERATED_FILES = {
    "project-status.json",
    "README.md",
    "NERVA.md",
    "GO_LIVE_PLAN.md",
    "STATUS.md",
}

CommandRunner = Callable[[list[str]], tuple[int, str]]


def _normalize(files: list[str]) -> list[str]:
    return sorted(
        {
            name.strip().replace("\\", "/").removeprefix("./")
            for name in files
            if name.strip()
        }
    )


def _default_runner(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603  # nosec B603
        args,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout + proc.stderr


def discover_changed_files(*, base: str, runner: CommandRunner | None = None) -> list[str]:
    """Union committed, tracked-local, and untracked changes."""
    runner = runner or _default_runner
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=ACMRD", f"{base}...HEAD"],
        ["git", "diff", "--name-only", "--diff-filter=ACMRD", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    changed = []
    for command in commands:
        code, output = runner(command)
        if code != 0:
            raise RuntimeError(f"changed-file discovery failed ({code}): {' '.join(command)}")
        changed.extend(output.splitlines())
    return _normalize(changed)


def affected_test_counts(files: list[str]) -> list[str]:
    """Conservatively name tracked counts that may need a deliberate refresh."""
    affected = set()
    for name in files:
        path = name.lower()
        if (path.startswith("tests/") and path.endswith(".py")) or path in {
            "pytest.ini",
            "pyproject.toml",
        }:
            affected.add("backend")
        if path.startswith("frontend/") and (
            ".test." in path
            or ".spec." in path
            or "/__tests__/" in path
            or path == "frontend/vite.config.ts"
            or path.endswith(("vitest.config.js", "vitest.config.ts"))
        ):
            affected.add("frontend")
        if path.startswith("mobile/") and (
            ".test." in path
            or ".spec." in path
            or "/__tests__/" in path
            or path.endswith(("jest.config.js", "jest.config.ts"))
        ):
            affected.add("mobile")
    return sorted(affected)


def relevant_status_files(files: list[str]) -> list[str]:
    return sorted(
        name
        for name in files
        if name in STATUS_SOURCE_FILES
        or name in STATUS_GENERATED_FILES
        or bool(affected_test_counts([name]))
    )


def count_refresh_command(counts: list[str]) -> str:
    if counts == ["backend"]:
        return "python scripts/status_sync.py --reuse-js-counts"
    return "python scripts/status_sync.py"


def _test_counts(raw: str, *, source: str) -> dict[str, int]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source} is not valid JSON") from exc
    tests = payload.get("tests", {}) if isinstance(payload, dict) else {}
    counts = {name: tests.get(name) for name in ("backend", "frontend", "mobile")}
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in counts.values()):
        raise RuntimeError(f"{source} has no valid backend/frontend/mobile counts")
    return counts


def changed_tracked_test_counts(
    *, base: str, runner: CommandRunner | None = None
) -> list[str]:
    """Return tracked count fields changed from the merge base."""
    runner = runner or _default_runner
    code, output = runner(["git", "show", f"{base}:project-status.json"])
    if code != 0:
        raise RuntimeError(f"cannot read project-status.json at {base}")
    try:
        current_raw = PROJECT_STATUS.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("current project-status.json is missing") from exc
    previous = _test_counts(output, source=f"{base}:project-status.json")
    current = _test_counts(current_raw, source="project-status.json")
    return sorted(name for name in current if current[name] != previous[name])


def _parse_status_result(output: str) -> dict:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "status" in payload:
            return payload
    raise RuntimeError("status_sync.py did not return a JSON result")


def run_preflight(
    files: list[str],
    *,
    base: str = "origin/main",
    runner: CommandRunner | None = None,
) -> tuple[int, dict]:
    runner = runner or _default_runner
    changed = _normalize(files)
    relevant = relevant_status_files(changed)
    counts = affected_test_counts(changed)
    payload_base = {
        "mode": "tracked-test-counts",
        "changed_files": changed,
        "status_inputs": relevant,
        "changed_keys": [],
        "generated_files": [],
        "fix_command": None,
    }
    if not relevant:
        return 0, {
            **payload_base,
            "status": "skipped",
            "reason": "no generated-status inputs changed",
        }

    if "project-status.json" in changed:
        try:
            changed_counts = changed_tracked_test_counts(base=base, runner=runner)
        except RuntimeError as exc:
            return 2, {**payload_base, "status": "error", "reason": str(exc)}
        unjustified = sorted(set(changed_counts) - set(counts))
        if unjustified:
            return 1, {
                **payload_base,
                "status": "refresh_required",
                "reason": "tracked test count changed without a matching collection input",
                "changed_keys": [f"tests.{name}" for name in unjustified],
                "generated_files": ["project-status.json"],
                "fix_command": count_refresh_command(unjustified),
            }

    code, output = runner([sys.executable, *FAST_CHECK_ARGS])
    try:
        status_result = _parse_status_result(output)
    except RuntimeError as exc:
        return 2, {**payload_base, "status": "error", "reason": str(exc)}
    payload = {
        **payload_base,
        "status": status_result["status"],
        "changed_keys": status_result.get("changed_keys", []),
        "generated_files": status_result.get("files", []),
        "fix_command": status_result.get("fix_command"),
    }
    if code == 0 and status_result["status"] == "in_sync":
        return 0, payload
    if code == 1 and status_result["status"] == "out_of_sync":
        payload["fix_command"] = payload["fix_command"] or FAST_FIX_COMMAND
        return 1, payload
    payload["status"] = "error"
    payload["reason"] = status_result.get("error", f"status_sync.py exited {code}")
    return 2, payload


def render(payload: dict) -> str:
    label = str(payload["status"]).replace("_", " ").upper()
    lines = [f"Generated-status preflight: {label} ({payload['mode']})"]
    if payload["changed_files"]:
        lines.append("Changed files: " + ", ".join(payload["changed_files"]))
    if payload["status_inputs"]:
        lines.append("Status inputs: " + ", ".join(payload["status_inputs"]))
    if payload["changed_keys"]:
        lines.append("Changed status keys: " + ", ".join(payload["changed_keys"]))
    if payload["generated_files"]:
        lines.append("Generated files: " + ", ".join(payload["generated_files"]))
    if payload.get("reason"):
        lines.append("Reason: " + payload["reason"])
    if payload["fix_command"]:
        lines.append("Fix with: " + payload["fix_command"])
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="explicit changed path; repeat to bypass git discovery",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        files = args.changed_file or discover_changed_files(base=args.base)
        code, payload = run_preflight(files, base=args.base)
    except RuntimeError as exc:
        code, payload = 2, {
            "status": "error",
            "mode": "tracked-test-counts",
            "changed_files": [],
            "status_inputs": [],
            "changed_keys": [],
            "generated_files": [],
            "fix_command": None,
            "reason": str(exc),
        }
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if args.json
        else render(payload)
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
