#!/usr/bin/env python3
"""Plan and run the same change-aware verification policy used by CI.

The command is intentionally dependency-free until it executes a selected
lane.  It classifies committed and local work through ``change-risk.json``,
builds a deterministic command plan, and can emit both JSON and Markdown
receipts.  Draft mode stops on the first failure; ready mode retains complete
integration evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess  # nosec B404 - fixed argv only; shell execution is forbidden
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import change_risk
import check_ai_workflow_policy

REPO = Path(__file__).resolve().parent.parent
DEFAULT_JSON = REPO / ".artifacts" / "verify-change.json"
DEFAULT_MARKDOWN = REPO / ".artifacts" / "verify-change.md"
AI_POLICY = REPO / check_ai_workflow_policy.POLICY_RELATIVE
COMMAND_TIMEOUT_SECONDS = 1800

CommandRunner = Callable[[list[str], Path], tuple[int, str]]


def _run_git(args: list[str]) -> bytes:
    try:
        return subprocess.check_output(  # noqa: S603  # nosec B603
            ["git", *args], cwd=REPO, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}") from exc


def _resolve_sha(revision: str) -> str:
    return _run_git(["rev-parse", "--verify", revision]).decode().strip()


def _local_changes() -> list[dict[str, str]]:
    tracked = change_risk.parse_name_status_z(
        _run_git(["diff", "--name-status", "-z", "--find-renames", "HEAD"])
    )
    untracked = _run_git(["ls-files", "--others", "--exclude-standard", "-z"])
    for raw_path in untracked.split(b"\0"):
        if raw_path:
            tracked.append(
                {
                    "status": "A",
                    "status_detail": "A",
                    "path": change_risk.normalize_path(
                        raw_path.decode("utf-8", errors="surrogateescape")
                    ),
                }
            )
    return tracked


def discover_changes(base_sha: str, head_sha: str, *, include_worktree: bool) -> list[dict[str, str]]:
    changes = change_risk.git_changes(base_sha, head_sha, REPO)
    if include_worktree:
        changes.extend(_local_changes())
    # A path can be both committed and locally modified.  One classification is
    # sufficient because the worktree digest below binds the local bytes.
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for item in changes:
        unique[(item["path"], item.get("old_path", ""))] = item
    return list(unique.values())


def worktree_digest(changes: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(changes, key=lambda value: (value["path"], value.get("old_path", ""))):
        path = item["path"]
        digest.update(path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        candidate = REPO / path
        if candidate.is_file():
            digest.update(candidate.read_bytes())
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def changed_path_manifest(changes: list[dict[str, str]]) -> list[str]:
    """Return every normalized pre/post image path as a stable receipt manifest."""

    paths = {
        change_risk.normalize_path(path)
        for item in changes
        for path in (item.get("old_path"), item.get("path"))
        if path
    }
    return sorted(paths)


def _load_ai_policy() -> dict[str, Any]:
    data, load_errors = check_ai_workflow_policy.load_policy(AI_POLICY)
    if load_errors or not isinstance(data, dict):
        raise RuntimeError("; ".join(load_errors) or "canonical AI policy is not an object")
    validation_errors = check_ai_workflow_policy.validate_policy(data)
    if validation_errors:
        raise RuntimeError("invalid canonical AI policy: " + "; ".join(validation_errors))
    return data


def policy_risk_tier(classification: dict[str, Any], policy: dict[str, Any]) -> str:
    """Map CI's three-level classifier to the canonical conservative R-tier."""

    mapping = policy["automated_risk_mapping"]["mapping"]
    risk_level = classification.get("risk_level")
    try:
        return str(mapping[risk_level])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"cannot map change-risk level to policy tier: {risk_level!r}") from exc


def default_producer(env: dict[str, str] | None = None) -> str:
    """Name the automation or local actor without inventing an approval identity."""

    env = os.environ if env is None else env
    if env.get("GITHUB_ACTOR", "").strip():
        return f"github:{env['GITHUB_ACTOR'].strip()}"
    local = env.get("USER", "").strip() or env.get("USERNAME", "").strip()
    return f"local:{local}" if local else "verify_change.py"


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _python_test_targets(changes: list[dict[str, str]]) -> list[str]:
    targets: set[str] = set()
    for item in changes:
        path = item["path"]
        if path.startswith("tests/") and path.endswith(".py") and (REPO / path).is_file():
            targets.add(path)
            continue
        candidate: str | None = None
        if (
            path.startswith("agents/") or path.startswith("scripts/")
        ) and path.endswith(".py"):
            candidate = f"tests/test_{Path(path).stem}.py"
        if candidate and (REPO / candidate).is_file():
            targets.add(candidate)
    return sorted(targets)


def _spec(name: str, argv: list[str], *, cwd: str = ".") -> dict[str, Any]:
    return {"name": name, "argv": argv, "cwd": cwd}


def build_plan(
    classification: dict[str, Any],
    *,
    mode: str,
    base_sha: str,
    changes: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Return an ordered, de-duplicated command plan for the classification."""
    lanes = set(classification["required_lanes"])
    plan = [
        _spec("diff-integrity", ["git", "diff", "--check", f"{base_sha}...HEAD"]),
        _spec("worktree-diff-integrity", ["git", "diff", "--check"]),
        _spec("ai-policy", [sys.executable, "scripts/check_ai_workflow_policy.py", "--json"]),
        _spec(
            "generated-truth",
            [sys.executable, "scripts/status_preflight.py", "--base", base_sha, "--json"],
        ),
    ]
    if lanes & {
        "python-ubuntu",
        "python-windows",
        "contracts-security",
        "workflow-policy",
        "dependency-integrity",
        "full-suite",
    }:
        plan.append(_spec("ruff", ["ruff", "check", "."]))
        plan.append(
            _spec(
                "new-health-debt",
                [sys.executable, "scripts/check_new_health_debt.py", "--base", base_sha, "--json"],
            )
        )

    if lanes & {"python-ubuntu", "python-windows", "full-suite"}:
        targets = _python_test_targets(changes)
        if mode == "ready" or "full-suite" in lanes or not targets:
            targets = ["tests/"]
        pytest_argv = [
            sys.executable,
            "-m",
            "pytest",
            *targets,
            "-n",
            "auto",
            "--dist",
            "loadfile",
            "--timeout=90",
            "-q",
            "--tb=short",
        ]
        if mode == "draft":
            pytest_argv.append("--maxfail=1")
        plan.append(_spec("python-tests", pytest_argv))

    if lanes & {"contracts-security", "dependency-integrity", "full-suite"}:
        plan.append(
            _spec(
                "sandbox-canary",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_sandbox_isolation.py",
                    "tests/test_h32_acquisition_sandbox_isolation.py",
                    "-q",
                    "--maxfail=1",
                ],
            )
        )

    if lanes & {"frontend", "full-suite"}:
        plan.extend(
            [
                _spec("frontend-root", ["npm", "run", "test:coverage"]),
                _spec("frontend-typecheck", ["npx", "tsc", "--noEmit"], cwd="frontend"),
                _spec("frontend-tests", ["npm", "test"], cwd="frontend"),
                _spec("frontend-build", ["npm", "run", "build"], cwd="frontend"),
            ]
        )
    if lanes & {"mobile", "full-suite"}:
        plan.append(_spec("mobile-tests", ["npm", "test", "--", "--runInBand"], cwd="mobile"))

    seen: set[tuple[str, tuple[str, ...], str]] = set()
    unique = []
    for command in plan:
        key = (command["name"], tuple(command["argv"]), command["cwd"])
        if key not in seen:
            unique.append(command)
            seen.add(key)
    return unique


def _default_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603  # nosec B603
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "JARVIS_TESTING": "1"},
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    return proc.returncode, proc.stdout


def execute_plan(
    plan: list[dict[str, Any]], *, mode: str, runner: CommandRunner | None = None
) -> tuple[int, list[dict[str, Any]]]:
    runner = runner or _default_runner
    results = []
    overall = 0
    for command in plan:
        started = time.monotonic()
        infra_kind = None
        try:
            code, output = runner(command["argv"], REPO / command["cwd"])
        except subprocess.TimeoutExpired as exc:
            raw_output = exc.stdout or ""
            if isinstance(raw_output, bytes):
                raw_output = raw_output.decode("utf-8", errors="replace")
            code = 2
            output = raw_output or f"command timed out after {COMMAND_TIMEOUT_SECONDS}s"
            infra_kind = "timeout"
        except OSError as exc:
            code, output = 2, f"failed to start command: {exc}"
            infra_kind = "execution_error"
        if code not in {0, 1} and infra_kind is None:
            infra_kind = "nonstandard_exit"
        result_status = "passed" if code == 0 else ("infra_error" if infra_kind else "failed")
        elapsed = round(time.monotonic() - started, 3)
        summary = next(
            (line.strip()[:500] for line in reversed(output.splitlines()) if line.strip()),
            f"exit {code}",
        )
        results.append(
            {
                **command,
                "command": list(command["argv"]),
                "exit_code": code,
                "duration_seconds": elapsed,
                "status": result_status,
                "infra_kind": infra_kind,
                "summary": summary,
                "output_tail": output[-8000:],
            }
        )
        if code != 0:
            overall = max(overall, 2 if infra_kind else 1)
            if mode == "draft":
                break
    return overall, results


def build_receipt(
    *,
    policy: dict[str, Any],
    mode: str,
    base_sha: str,
    head_sha: str,
    changes: list[dict[str, str]],
    classification: dict[str, Any],
    commands: list[dict[str, Any]],
    results: list[dict[str, Any]],
    status: str,
    producer: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build and validate one canonical exact-source evidence receipt."""

    receipt = {
        "schema_version": 1,
        "policy_id": policy["policy_id"],
        "policy_schema_version": policy["schema_version"],
        "mode": mode,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "risk_tier": policy_risk_tier(classification, policy),
        "changed_paths": changed_path_manifest(changes),
        "worktree_sha256": worktree_digest(changes),
        "classification": classification,
        "commands": commands,
        "results": results,
        "producer": producer,
        "generated_at": generated_at,
        "status": status,
    }
    errors = check_ai_workflow_policy.validate_evidence_receipt(receipt, policy)
    if errors:
        raise ValueError("invalid evidence receipt: " + "; ".join(errors))
    return receipt


def render_markdown(receipt: dict[str, Any]) -> str:
    classification = receipt["classification"]
    lines = [
        "## Verify-change receipt",
        "",
        f"- Policy: `{receipt['policy_id']}` schema `{receipt['policy_schema_version']}`",
        f"- Head: `{receipt['head_sha']}`",
        f"- Worktree: `{receipt['worktree_sha256']}`",
        f"- Risk: **{receipt['risk_tier']}** (CI classifier: `{classification['risk_level']}`)",
        f"- Scopes: {', '.join(classification['scopes']) or 'none'}",
        f"- Required lanes: {', '.join(classification['required_lanes'])}",
        f"- Mode: `{receipt['mode']}`",
        f"- Result: **{receipt['status']}**",
        f"- Producer: `{receipt['producer']}` at `{receipt['generated_at']}`",
        f"- Changed paths: {', '.join(f'`{path}`' for path in receipt['changed_paths']) or 'none'}",
        "",
        "| Check | Result | Seconds | Command |",
        "| --- | --- | ---: | --- |",
    ]
    results_by_name = {item["name"]: item for item in receipt.get("results", [])}
    for command in receipt["commands"]:
        result = results_by_name.get(command["name"])
        status = result["status"] if result else "planned"
        duration = result["duration_seconds"] if result else "—"
        rendered = " ".join(command["argv"]).replace("|", "\\|")
        lines.append(f"| {command['name']} | {status} | {duration} | `{rendered}` |")
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--mode", choices=("draft", "ready"), default="draft")
    parser.add_argument("--no-worktree", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument(
        "--producer",
        default=default_producer(),
        help="actor or automation identity recorded in the evidence receipt",
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--stdout", action="store_true", help="also print the JSON receipt")
    args = parser.parse_args(argv)

    try:
        base_sha = _resolve_sha(args.base)
        head_sha = _resolve_sha(args.head)
        ai_policy = _load_ai_policy()
        policy = change_risk.load_policy()
        changes = discover_changes(base_sha, head_sha, include_worktree=not args.no_worktree)
        classification = change_risk.classify_changes(
            changes,
            policy,
            base_sha=base_sha,
            head_sha=head_sha,
            event_name="local-verify-change",
        )
        plan = build_plan(
            classification,
            mode=args.mode,
            base_sha=base_sha,
            changes=changes,
        )
    except (OSError, RuntimeError, ValueError, change_risk.PolicyError) as exc:
        print(f"verify-change: {exc}", file=sys.stderr)
        return 2

    code, results = (0, []) if args.plan_only else execute_plan(plan, mode=args.mode)
    try:
        receipt = build_receipt(
            policy=ai_policy,
            mode=args.mode,
            base_sha=base_sha,
            head_sha=head_sha,
            changes=changes,
            classification=classification,
            commands=plan,
            results=results,
            status=(
                "planned"
                if args.plan_only
                else ("passed" if code == 0 else ("infra_error" if code == 2 else "failed"))
            ),
            producer=args.producer,
            generated_at=utc_timestamp(),
        )
    except ValueError as exc:
        print(f"verify-change: {exc}", file=sys.stderr)
        return 2
    encoded = json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    _write(args.json_output, encoded)
    _write(args.markdown_output, render_markdown(receipt))
    if args.stdout:
        print(encoded, end="")
    else:
        print(
            f"verify-change: {receipt['status']} ({classification['risk_level']}; "
            f"{len(plan)} checks) — {args.markdown_output}"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
