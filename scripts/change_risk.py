#!/usr/bin/env python3
"""Classify a Git change set into deterministic CI risk scopes and lanes.

The classifier is deliberately dependency-free so the first CI decision can run
before Python or Node dependencies are installed. Unknown paths, empty diffs,
copies, and renames fail safe by requiring every configured lane.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / ".github" / "change-risk.json"
SUPPORTED_STATUSES = frozenset({"A", "D", "M", "T", "U", "X", "B", "R", "C"})
FAIL_SAFE_STATUSES = frozenset({"R", "C", "T", "U", "X", "B"})
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
SECURITY_JOBS = frozenset({"scope", "gitleaks", "semgrep", "dependency-audit", "bandit"})
SECURITY_SAST_LANES = frozenset({"python-ubuntu", "contracts-security", "full-suite"})
SECURITY_DEPENDENCY_LANES = frozenset({"dependency-integrity", "full-suite"})


class PolicyError(ValueError):
    """Raised when the classifier policy cannot guarantee safe decisions."""


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _policy_digest(policy: dict[str, Any]) -> str:
    return hashlib.sha256(_compact_json(policy).encode()).hexdigest()


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read change-risk policy {path}: {exc}") from exc

    required = {
        "schema_version",
        "classifier_version",
        "sentinel_check",
        "risk_order",
        "scope_order",
        "all_lanes",
        "ci_jobs",
        "lane_jobs",
        "scopes",
        "documentation_patterns",
        "nerva_patterns",
        "rules",
    }
    missing = sorted(required - policy.keys())
    if missing:
        raise PolicyError(f"policy missing keys: {', '.join(missing)}")

    if policy["schema_version"] != 1:
        raise PolicyError("unsupported policy schema_version; expected 1")
    if policy["risk_order"] != ["low", "medium", "high"]:
        raise PolicyError("risk_order must be exactly low, medium, high")
    if not policy["all_lanes"] or len(policy["all_lanes"]) != len(set(policy["all_lanes"])):
        raise PolicyError("all_lanes must be a non-empty unique list")
    if not policy["ci_jobs"] or len(policy["ci_jobs"]) != len(set(policy["ci_jobs"])):
        raise PolicyError("ci_jobs must be a non-empty unique list")
    stable_jobs = {"classify", "fast-gate", "nerva-integrity"}
    if stable_jobs - set(policy["ci_jobs"]):
        raise PolicyError("ci_jobs must include classify, fast-gate, and nerva-integrity")
    nerva_patterns = policy["nerva_patterns"]
    if (
        not isinstance(nerva_patterns, list)
        or not nerva_patterns
        or not all(isinstance(pattern, str) and pattern for pattern in nerva_patterns)
        or len(nerva_patterns) != len(set(nerva_patterns))
    ):
        raise PolicyError("nerva_patterns must be a non-empty unique list of strings")
    lane_jobs = policy["lane_jobs"]
    if not isinstance(lane_jobs, dict) or set(lane_jobs) != set(policy["all_lanes"]):
        raise PolicyError("lane_jobs must map every configured lane exactly once")
    for lane, jobs in lane_jobs.items():
        if not isinstance(jobs, list) or not jobs or not set(jobs) <= set(policy["ci_jobs"]):
            raise PolicyError(f"lane_jobs.{lane} has invalid CI jobs")

    scope_order = policy["scope_order"]
    scopes = policy["scopes"]
    if set(scope_order) != set(scopes) or len(scope_order) != len(set(scope_order)):
        raise PolicyError("scope_order must list every configured scope exactly once")
    expected_scopes = {
        "docs-only",
        "generated-truth",
        "python-runtime",
        "frontend",
        "mobile",
        "contracts-security",
        "workflows",
        "dependencies",
    }
    if set(scopes) != expected_scopes:
        raise PolicyError("policy scopes do not match the required classifier contract")

    all_lanes = set(policy["all_lanes"])
    risk_levels = set(policy["risk_order"])
    for scope, settings in scopes.items():
        if settings.get("risk") not in risk_levels:
            raise PolicyError(f"scope {scope!r} has an invalid risk")
        lanes = settings.get("lanes")
        if not isinstance(lanes, list) or not lanes or not set(lanes) <= all_lanes:
            raise PolicyError(f"scope {scope!r} has invalid lanes")

    rule_scopes = set()
    for index, rule in enumerate(policy["rules"]):
        scope = rule.get("scope")
        patterns = rule.get("patterns")
        if scope not in scopes or scope == "docs-only":
            raise PolicyError(f"rule {index} has an invalid scope")
        if (
            not isinstance(patterns, list)
            or not patterns
            or not all(isinstance(pattern, str) and pattern for pattern in patterns)
        ):
            raise PolicyError(f"rule {index} must have non-empty string patterns")
        if not isinstance(rule.get("reason"), str) or not rule["reason"]:
            raise PolicyError(f"rule {index} must have a reason")
        rule_scopes.add(scope)
    if rule_scopes != expected_scopes - {"docs-only"}:
        raise PolicyError("every non-docs scope must have at least one rule")
    return policy


def normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/").removeprefix("./")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def _unsafe_path(path: str) -> bool:
    parts = path.split("/")
    return not path or path.startswith("/") or ".." in parts or "\n" in path or "\r" in path


def _matches(path: str, patterns: list[str]) -> bool:
    # fnmatch's '*' intentionally crosses '/' here, giving policy authors a
    # simple recursive repository glob without an additional parser dependency.
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def parse_name_status_z(raw: bytes) -> list[dict[str, str]]:
    """Parse ``git diff --name-status -z`` output without lossy shell quoting."""
    if not raw:
        return []
    fields = raw.split(b"\0")
    if fields[-1] == b"":
        fields.pop()
    changes: list[dict[str, str]] = []
    index = 0
    while index < len(fields):
        status_text = fields[index].decode("utf-8", errors="surrogateescape")
        index += 1
        status = status_text[:1]
        if status not in SUPPORTED_STATUSES:
            raise ValueError(f"unsupported git change status: {status_text!r}")
        if index >= len(fields):
            raise ValueError(f"missing path for git change status {status_text!r}")
        first_path = fields[index].decode("utf-8", errors="surrogateescape")
        index += 1
        if status in {"R", "C"}:
            if index >= len(fields):
                raise ValueError(f"missing destination for git change status {status_text!r}")
            second_path = fields[index].decode("utf-8", errors="surrogateescape")
            index += 1
            changes.append(
                {
                    "status": status,
                    "status_detail": status_text,
                    "old_path": normalize_path(first_path),
                    "path": normalize_path(second_path),
                }
            )
        else:
            changes.append(
                {
                    "status": status,
                    "status_detail": status_text,
                    "path": normalize_path(first_path),
                }
            )
    return changes


def git_changes(base: str | None, head: str, repo: Path = REPO_ROOT) -> list[dict[str, str]]:
    if not head:
        head = "HEAD"
    unusable_base = not base or set(base) == {"0"}
    first_commit = False
    if unusable_base:
        try:
            base = subprocess.check_output(
                ["git", "rev-parse", f"{head}^"], cwd=repo, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except subprocess.CalledProcessError:
            base = EMPTY_TREE_SHA
            first_commit = True
    revision_range = [base, head] if first_commit else [f"{base}...{head}"]
    command = ["git", "diff", "--name-status", "-z", "--find-renames", *revision_range]
    try:
        raw = subprocess.check_output(command, cwd=repo)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git change discovery failed for {base}...{head}") from exc
    return parse_name_status_z(raw)


def _paths_for(change: dict[str, str]) -> list[str]:
    paths = [change["path"]]
    if "old_path" in change:
        paths.append(change["old_path"])
    return paths


def classify_changes(
    changes: list[dict[str, str]],
    policy: dict[str, Any],
    *,
    base_sha: str | None = None,
    head_sha: str | None = None,
    event_name: str | None = None,
) -> dict[str, Any]:
    risk_rank = {risk: index for index, risk in enumerate(policy["risk_order"])}
    scope_rank = {scope: index for index, scope in enumerate(policy["scope_order"])}
    lane_rank = {lane: index for index, lane in enumerate(policy["all_lanes"])}
    normalized_changes = sorted(
        (
            {
                **change,
                "status": change["status"][:1],
                "path": normalize_path(change["path"]),
                **(
                    {"old_path": normalize_path(change["old_path"])}
                    if change.get("old_path")
                    else {}
                ),
            }
            for change in changes
        ),
        key=lambda change: (change["path"], change["status"], change.get("old_path", "")),
    )

    scopes: set[str] = set()
    reasons: list[dict[str, str]] = []
    unknown_paths: set[str] = set()
    status_counts: Counter[str] = Counter()
    all_documentation = bool(normalized_changes)
    fail_safe_codes: set[str] = set()
    nerva_relevant = any(
        _matches(path, policy["nerva_patterns"])
        for change in normalized_changes
        for path in _paths_for(change)
    )

    for change in normalized_changes:
        status = change["status"]
        status_counts[status] += 1
        if status not in SUPPORTED_STATUSES:
            fail_safe_codes.add("unsupported-status")
        if status in FAIL_SAFE_STATUSES:
            code = "rename-or-copy" if status in {"R", "C"} else "non-content-status"
            fail_safe_codes.add(code)
            reasons.append(
                {
                    "code": code,
                    "path": change["path"],
                    "scope": "all",
                    "detail": f"git status {change.get('status_detail', status)} requires full validation",
                }
            )

        for path in _paths_for(change):
            is_doc = _matches(path, policy["documentation_patterns"])
            matched = False
            for rule in policy["rules"]:
                if _matches(path, rule["patterns"]):
                    matched = True
                    scope = rule["scope"]
                    scopes.add(scope)
                    reasons.append(
                        {
                            "code": "scope-match",
                            "path": path,
                            "scope": scope,
                            "detail": rule["reason"],
                        }
                    )
            if _unsafe_path(path) or (not is_doc and not matched):
                unknown_paths.add(path)
            all_documentation = all_documentation and is_doc and not matched

    if all_documentation:
        scopes.add("docs-only")
        reasons.append(
            {
                "code": "docs-only",
                "path": "*",
                "scope": "docs-only",
                "detail": "every changed path is documentation and no higher-risk rule matched",
            }
        )
    if unknown_paths:
        fail_safe_codes.add("unknown-path")
        for path in sorted(unknown_paths):
            reasons.append(
                {
                    "code": "unknown-path",
                    "path": path,
                    "scope": "all",
                    "detail": "path matched no policy rule; every lane is required",
                }
            )
    if not normalized_changes:
        fail_safe_codes.add("empty-diff")
        reasons.append(
            {
                "code": "empty-diff",
                "path": "*",
                "scope": "all",
                "detail": "no changes were discovered; every lane is required",
            }
        )

    fail_safe = bool(fail_safe_codes)
    if fail_safe:
        lanes = set(policy["all_lanes"])
        risk = "high"
    else:
        lanes = {lane for scope in scopes for lane in policy["scopes"][scope]["lanes"]}
        risk = max(
            (policy["scopes"][scope]["risk"] for scope in scopes),
            key=risk_rank.__getitem__,
            default="high",
        )
    if len(scopes - {"docs-only"}) >= 3:
        risk = "high"
        lanes.add("full-suite")

    ordered_scopes = sorted(scopes, key=scope_rank.__getitem__)
    ordered_lanes = sorted(lanes, key=lane_rank.__getitem__)
    reasons = sorted(
        {(_compact_json(reason), tuple(reason.items())) for reason in reasons},
        key=lambda item: item[0],
    )
    unique_reasons = [dict(items) for _, items in reasons]
    digest = _policy_digest(policy)
    identity_payload = {
        "base_sha": base_sha or "",
        "changes": normalized_changes,
        "head_sha": head_sha or "",
        "nerva_relevant": nerva_relevant,
        "policy_sha256": digest,
        "scopes": ordered_scopes,
        "required_lanes": ordered_lanes,
        "risk_level": risk,
    }
    classification_id = hashlib.sha256(_compact_json(identity_payload).encode()).hexdigest()
    rename_count = status_counts["R"] + status_counts["C"]
    metrics = {
        "changed_count": len(normalized_changes),
        "classification_id": classification_id,
        "fail_safe": fail_safe,
        "nerva_relevant": nerva_relevant,
        "required_lane_count": len(ordered_lanes),
        "rename_or_copy_count": rename_count,
        "risk_level": risk,
        "risk_score": risk_rank[risk] + 1,
        "scope_count": len(ordered_scopes),
        "unknown_count": len(unknown_paths),
    }
    return {
        "schema_version": 1,
        "classifier_version": policy["classifier_version"],
        "classification_id": classification_id,
        "policy_sha256": digest,
        "sentinel_check": policy["sentinel_check"],
        "aggregate_ready": True,
        "aggregate_semantics": (
            "ready means policy validation completed and ambiguous changes were escalated "
            "to every configured lane; it does not mean those lanes passed"
        ),
        "risk_level": risk,
        "risk_score": risk_rank[risk] + 1,
        "scopes": ordered_scopes,
        "required_lanes": ordered_lanes,
        "nerva_relevant": nerva_relevant,
        "full_suite_required": "full-suite" in ordered_lanes,
        "fail_safe": fail_safe,
        "fail_safe_reasons": sorted(fail_safe_codes),
        "unknown_paths": sorted(unknown_paths),
        "changes": normalized_changes,
        "reasons": unique_reasons,
        "metadata": {
            "base_sha": base_sha or "",
            "head_sha": head_sha or "",
            "event_name": event_name or "",
            "changed_count": len(normalized_changes),
            "status_counts": dict(sorted(status_counts.items())),
            "scope_counts": dict(Counter(reason["scope"] for reason in unique_reasons)),
            "unknown_count": len(unknown_paths),
            "rename_or_copy_count": rename_count,
        },
        "metrics": metrics,
    }


def write_github_outputs(path: Path, result: dict[str, Any]) -> None:
    required_lanes = set(result["required_lanes"])
    outputs = {
        "aggregate_ready": str(result["aggregate_ready"]).lower(),
        "classification_id": result["classification_id"],
        "policy_sha256": result["policy_sha256"],
        "risk_level": result["risk_level"],
        "risk_score": result["risk_score"],
        "scopes_json": _compact_json(result["scopes"]),
        "required_lanes_json": _compact_json(result["required_lanes"]),
        "full_suite_required": str(result["full_suite_required"]).lower(),
        "fail_safe": str(result["fail_safe"]).lower(),
        "changed_count": result["metadata"]["changed_count"],
        "unknown_count": result["metadata"]["unknown_count"],
        "rename_or_copy_count": result["metadata"]["rename_or_copy_count"],
        "metrics_json": _compact_json(result["metrics"]),
        "nerva_relevant": str(result["nerva_relevant"]).lower(),
        "security_sast_required": str(bool(required_lanes & SECURITY_SAST_LANES)).lower(),
        "security_dependency_required": str(
            bool(required_lanes & SECURITY_DEPENDENCY_LANES)
        ).lower(),
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def write_summary(path: Path, result: dict[str, Any]) -> None:
    scopes = ", ".join(f"`{scope}`" for scope in result["scopes"]) or "none"
    lanes = ", ".join(f"`{lane}`" for lane in result["required_lanes"])
    fail_safe = ", ".join(result["fail_safe_reasons"]) or "no"
    content = (
        "## AI change-risk classification\n\n"
        "| Metric | Decision |\n"
        "| --- | --- |\n"
        f"| Risk | **{result['risk_level']}** ({result['risk_score']}/3) |\n"
        f"| Scopes | {scopes} |\n"
        f"| Required lanes | {lanes} |\n"
        f"| Nerva validation | {'required' if result['nerva_relevant'] else 'no-op'} |\n"
        f"| Changed paths | {result['metadata']['changed_count']} |\n"
        f"| Unknown paths | {result['metadata']['unknown_count']} |\n"
        f"| Rename/copy paths | {result['metadata']['rename_or_copy_count']} |\n"
        f"| Fail-safe escalation | {fail_safe} |\n"
        f"| Classification ID | `{result['classification_id']}` |\n\n"
        "> The required sentinel confirms classification only. Downstream required lanes must still pass.\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)


def aggregate_ci_results(
    required_lanes: list[str],
    job_results: dict[str, str],
    policy: dict[str, Any],
    *,
    aggregate_ready: bool,
    classification_id: str,
    expensive_enabled: bool,
    full_validation: bool,
) -> dict[str, Any]:
    """Evaluate the one stable CI sentinel without treating skipped jobs as green."""
    known_results = {"success", "failure", "cancelled", "skipped"}
    policy_jobs = set(policy["ci_jobs"])
    lanes = set(required_lanes)
    failures: list[str] = []

    if not aggregate_ready:
        failures.append("classifier did not attest aggregate readiness")
    if len(classification_id) != 64 or any(
        char not in "0123456789abcdef" for char in classification_id
    ):
        failures.append("classification_id is not a lowercase SHA-256 digest")
    if not lanes:
        failures.append("classifier emitted no required lanes")
    unknown_lanes = lanes - set(policy["all_lanes"])
    if unknown_lanes:
        failures.append(f"classifier emitted unknown lanes: {sorted(unknown_lanes)}")
    if set(job_results) != policy_jobs:
        failures.append(
            "job result keys do not match policy: "
            f"missing={sorted(policy_jobs - set(job_results))}, "
            f"extra={sorted(set(job_results) - policy_jobs)}"
        )
    invalid_results = {
        job: result for job, result in job_results.items() if result not in known_results
    }
    if invalid_results:
        failures.append(f"CI jobs emitted invalid result states: {invalid_results}")

    # These three jobs form the stable, cheap control plane on every CI run.
    # Nerva integrity deliberately returns success without validation when the
    # trusted classifier says no owned path changed.
    required_jobs = {"classify", "fast-gate", "nerva-integrity"}
    deferred_lanes: list[str] = []
    if full_validation:
        required_jobs.update(policy_jobs)
    elif expensive_enabled:
        for lane in lanes & set(policy["all_lanes"]):
            required_jobs.update(policy["lane_jobs"][lane])
    else:
        deferred_lanes = sorted(lanes)

    required_failures = {
        job: job_results.get(job, "missing")
        for job in sorted(required_jobs)
        if job_results.get(job) != "success"
    }
    if required_failures:
        failures.append(f"required jobs failed or did not run: {required_failures}")

    # A lane that ran and failed must never be hidden merely because another
    # condition did not mark it required. Branch protection may rely only on
    # this sentinel, so every observed failure/cancellation is fail-closed.
    observed_failures = {
        job: result
        for job, result in sorted(job_results.items())
        if result in {"failure", "cancelled"}
    }
    if observed_failures:
        failures.append(f"observed CI failures: {observed_failures}")

    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "required_jobs": sorted(required_jobs),
        "deferred_lanes": deferred_lanes,
        "expensive_enabled": expensive_enabled,
        "full_validation": full_validation,
    }


def aggregate_security_results(
    required_lanes: Any,
    job_results: Any,
    policy: dict[str, Any],
    *,
    aggregate_ready: bool,
    classification_id: str,
    sast_required_output: bool | None,
    dependency_required_output: bool | None,
) -> dict[str, Any]:
    """Evaluate the stable Security sentinel without accepting skipped evidence."""
    known_results = {"success", "failure", "cancelled", "skipped"}
    failures: list[str] = []

    if not aggregate_ready:
        failures.append("classifier did not attest aggregate readiness")
    if len(classification_id) != 64 or any(
        char not in "0123456789abcdef" for char in classification_id
    ):
        failures.append("classification_id is not a lowercase SHA-256 digest")

    lanes: set[str] = set()
    if (
        not isinstance(required_lanes, list)
        or not required_lanes
        or not all(isinstance(lane, str) and lane for lane in required_lanes)
        or len(required_lanes) != len(set(required_lanes))
    ):
        failures.append("classifier emitted malformed or empty required lanes")
    else:
        lanes = set(required_lanes)
        unknown_lanes = lanes - set(policy["all_lanes"])
        if unknown_lanes:
            failures.append(f"classifier emitted unknown lanes: {sorted(unknown_lanes)}")

    expected_sast = bool(lanes & SECURITY_SAST_LANES)
    expected_dependency = bool(lanes & SECURITY_DEPENDENCY_LANES)
    if sast_required_output is None or sast_required_output != expected_sast:
        failures.append("security SAST selector output is missing or inconsistent")
    if dependency_required_output is None or dependency_required_output != expected_dependency:
        failures.append("security dependency selector output is missing or inconsistent")

    results: dict[str, str] = job_results if isinstance(job_results, dict) else {}
    if not isinstance(job_results, dict) or set(results) != SECURITY_JOBS:
        failures.append(
            "security job result keys do not match policy: "
            f"missing={sorted(SECURITY_JOBS - set(results))}, "
            f"extra={sorted(set(results) - SECURITY_JOBS)}"
        )
    invalid_results = {
        job: result for job, result in results.items() if result not in known_results
    }
    if invalid_results:
        failures.append(f"Security jobs emitted invalid result states: {invalid_results}")

    required_jobs = {"scope", "gitleaks"}
    if expected_sast:
        required_jobs.update({"semgrep", "bandit"})
    if expected_dependency:
        required_jobs.add("dependency-audit")
    required_failures = {
        job: results.get(job, "missing")
        for job in sorted(required_jobs)
        if results.get(job) != "success"
    }
    if required_failures:
        failures.append(f"required security jobs failed or did not run: {required_failures}")

    observed_failures = {
        job: result for job, result in sorted(results.items()) if result in {"failure", "cancelled"}
    }
    if observed_failures:
        failures.append(f"observed Security failures: {observed_failures}")

    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "required_jobs": sorted(required_jobs),
        "sast_required": expected_sast,
        "dependency_required": expected_dependency,
    }


def _optional_env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw == "true":
        return True
    if raw == "false":
        return False
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--base", default=os.getenv("CHANGE_RISK_BASE", ""))
    parser.add_argument("--head", default=os.getenv("CHANGE_RISK_HEAD", "HEAD"))
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="classify an explicit modified path instead of discovering a git diff (repeatable)",
    )
    parser.add_argument("--output", type=Path, help="write the complete JSON decision to this file")
    parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"]) if os.getenv("GITHUB_OUTPUT") else None,
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(os.environ["GITHUB_STEP_SUMMARY"])
        if os.getenv("GITHUB_STEP_SUMMARY")
        else None,
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--aggregate-results",
        action="store_true",
        help="evaluate CI job results from CHANGE_RISK_* environment variables",
    )
    parser.add_argument(
        "--aggregate-security-results",
        action="store_true",
        help="evaluate Security job results from CHANGE_RISK_* environment variables",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policy = load_policy(args.policy)
        if args.aggregate_results:
            result = aggregate_ci_results(
                json.loads(os.getenv("CHANGE_RISK_REQUIRED_LANES", "[]")),
                json.loads(os.getenv("CHANGE_RISK_JOB_RESULTS", "{}")),
                policy,
                aggregate_ready=os.getenv("CHANGE_RISK_AGGREGATE_READY") == "true",
                classification_id=os.getenv("CHANGE_RISK_CLASSIFICATION_ID", ""),
                expensive_enabled=os.getenv("CHANGE_RISK_EXPENSIVE_ENABLED") == "true",
                full_validation=os.getenv("CHANGE_RISK_FULL_VALIDATION") == "true",
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            for failure in result["failures"]:
                print(f"::error::{failure}")
            return 0 if result["status"] == "passed" else 1
        if args.aggregate_security_results:
            result = aggregate_security_results(
                json.loads(os.getenv("CHANGE_RISK_REQUIRED_LANES", "null")),
                json.loads(os.getenv("CHANGE_RISK_SECURITY_JOB_RESULTS", "null")),
                policy,
                aggregate_ready=os.getenv("CHANGE_RISK_AGGREGATE_READY") == "true",
                classification_id=os.getenv("CHANGE_RISK_CLASSIFICATION_ID", ""),
                sast_required_output=_optional_env_bool("CHANGE_RISK_SECURITY_SAST_REQUIRED"),
                dependency_required_output=_optional_env_bool(
                    "CHANGE_RISK_SECURITY_DEPENDENCY_REQUIRED"
                ),
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            for failure in result["failures"]:
                print(f"::error::{failure}")
            return 0 if result["status"] == "passed" else 1
        changes = (
            [{"status": "M", "status_detail": "M", "path": path} for path in args.changed_file]
            if args.changed_file
            else git_changes(args.base, args.head)
        )
        result = classify_changes(
            changes,
            policy,
            base_sha=args.base,
            head_sha=args.head,
            event_name=os.getenv("GITHUB_EVENT_NAME"),
        )
    except (PolicyError, RuntimeError, ValueError) as exc:
        print(f"change-risk: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    if args.github_output:
        write_github_outputs(args.github_output, result)
    if args.summary:
        write_summary(args.summary, result)
    if not args.quiet:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
