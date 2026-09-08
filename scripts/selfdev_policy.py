#!/usr/bin/env python3
"""Classify autonomous Nerva development changes against the trusted control plane.

Routine engineering is owner-out-of-loop when the trusted policy says a change
is eligible. The exception is the small control plane that defines whether an
autonomous change may merge or deploy at all. Those paths are the root of trust
and may not self-authorize their own relaxation.

This module is deliberately stdlib-only. The hourly auto-merge workflow checks
out ``main`` and executes *that trusted copy* of this classifier before it
considers a candidate PR. A candidate therefore cannot authorize itself by
changing this file or ``selfdev-policy.json`` in the same transaction.

The policy distinguishes live enforcement from target state. In v1 autonomous
merge is live and waits for reported automation to finish green; independent
AI-review enforcement and autonomous canary deploy remain explicit targets
until their later #1054 slices land.

Examples::

    python scripts/selfdev_policy.py validate
    python scripts/selfdev_policy.py selftest
    python scripts/selfdev_policy.py classify agents/core/foo.py tests/test_foo.py
    gh pr view 123 --json files --jq '.files[].path' | \
        python scripts/selfdev_policy.py classify --stdin
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO / "selfdev-policy.json"

# Architectural invariants, not a second configurable policy. The policy may
# protect these with a broader pattern (for example `.github/workflows/**`).
# Removing coverage for any of them invalidates the policy before classification.
MANDATORY_PROTECTED_PATHS = (
    "selfdev-policy.json",
    "scripts/selfdev_policy.py",
    ".github/workflows/ci.yml",
    ".github/workflows/pr-auto-merge.yml",
    ".github/workflows/release.yml",
    ".github/workflows/security.yml",
    "agents/core/kernel/__init__.py",
    "agents/core/security/taint.py",
)


class PolicyError(ValueError):
    """The policy cannot safely be interpreted."""


def _normalise_repo_path(raw: str) -> str:
    """Return one GitHub-style repository-relative path or reject ambiguity."""
    value = raw.strip().replace("\\", "/")
    if not value:
        raise PolicyError("empty repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise PolicyError(f"path must stay repository-relative: {raw!r}")
    normalised = path.as_posix()
    if normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    """Load a policy object without silently accepting a non-object document."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"policy file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid policy JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError("policy root must be a JSON object")
    return data


def _patterns(policy: dict[str, Any]) -> list[str]:
    raw = policy.get("protected_paths")
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise PolicyError("protected_paths must be a non-empty list of strings")
    return raw


def protected_pattern(path: str, patterns: list[str]) -> str | None:
    """Return the first root-of-trust pattern matching ``path``, if any."""
    clean = _normalise_repo_path(path)
    for pattern in patterns:
        if fnmatch.fnmatchcase(clean, pattern):
            return pattern
    return None


def _require_bool(section: dict[str, Any], key: str) -> bool:
    value = section.get(key)
    if not isinstance(value, bool):
        raise PolicyError(f"{key} must be boolean")
    return value


def validate_policy(policy: dict[str, Any]) -> None:
    """Reject policy states that could accidentally erase the autonomy boundary."""
    if policy.get("schema_version") != 1:
        raise PolicyError("schema_version must be 1")
    if policy.get("policy_id") != "nerva.selfdev.v1":
        raise PolicyError("policy_id must be nerva.selfdev.v1")
    if policy.get("autonomous_default") is not True:
        raise PolicyError("autonomous_default must remain true for this owner directive")

    patterns = _patterns(policy)
    for required in MANDATORY_PROTECTED_PATHS:
        if protected_pattern(required, patterns) is None:
            raise PolicyError(f"mandatory root-of-trust path is not protected: {required}")

    merge = policy.get("merge")
    if not isinstance(merge, dict) or _require_bool(merge, "enabled") is not True:
        raise PolicyError("merge.enabled must be true")
    if merge.get("deny_protected_changes") is not True:
        raise PolicyError("merge must deny protected-path changes")
    if merge.get("require_non_draft") is not True:
        raise PolicyError("merge must require a non-draft PR")
    if merge.get("require_clean_merge_state") is not True:
        raise PolicyError("merge must require CLEAN GitHub merge state")
    if merge.get("require_at_least_one_check") is not True:
        raise PolicyError("merge must require at least one reported automated check")
    if merge.get("require_all_reported_checks_pass") is not True:
        raise PolicyError("merge must wait for every reported automated check to pass or skip")
    if merge.get("method") != "squash":
        raise PolicyError("merge.method must be squash")

    deploy = policy.get("deploy")
    if not isinstance(deploy, dict):
        raise PolicyError("deploy must be an object")
    _require_bool(deploy, "enabled")
    if deploy.get("target_enabled") is not True:
        raise PolicyError("autonomous deploy must remain an explicit target")
    if deploy.get("deny_protected_changes") is not True:
        raise PolicyError("deploy must deny protected-path changes")
    if deploy.get("strategy") != "staged_canary":
        raise PolicyError("deploy.strategy must be staged_canary")
    if deploy.get("require_versioned_artifact") is not True:
        raise PolicyError("deploy must require a versioned artifact")
    if deploy.get("require_post_deploy_probe") is not True:
        raise PolicyError("deploy must require a post-deploy probe")
    if deploy.get("auto_promote_on_green") is not True:
        raise PolicyError("deploy must automatically promote a green canary")
    if deploy.get("auto_rollback_on_regression") is not True:
        raise PolicyError("deploy must automatically roll back regressions")

    review = policy.get("review")
    if not isinstance(review, dict):
        raise PolicyError("review must be an object")
    _require_bool(review, "independent_reviewer_required")
    if review.get("target_independent_reviewer_required") is not True:
        raise PolicyError("independent reviewer enforcement must remain a target")
    if review.get("builder_may_clear_own_findings") is not False:
        raise PolicyError("the builder may not clear its own reviewer findings")

    budgets = policy.get("budgets")
    if not isinstance(budgets, dict):
        raise PolicyError("budgets must be an object")
    for key in (
        "max_repair_attempts_per_change",
        "max_wall_minutes_per_change",
        "max_parallel_selfdev_changes",
    ):
        value = budgets.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise PolicyError(f"{key} must be a positive integer")

    provenance = policy.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("required") is not True:
        raise PolicyError("provenance must be required")
    required_fields = provenance.get("required_fields")
    if not isinstance(required_fields, list) or not required_fields:
        raise PolicyError("provenance.required_fields must be a non-empty list")
    if not all(isinstance(field, str) and field for field in required_fields):
        raise PolicyError("every provenance field must be a non-empty string")


def classify(paths: list[str], policy: dict[str, Any]) -> dict[str, Any]:
    """Classify a candidate change using only machine-readable trusted policy.

    No paths is intentionally non-autonomous: a merge decision without a known
    diff is not a successful classification.
    """
    validate_policy(policy)
    patterns = _patterns(policy)
    clean_paths = [_normalise_repo_path(path) for path in paths]
    hits: list[dict[str, str]] = []
    for path in clean_paths:
        pattern = protected_pattern(path, patterns)
        if pattern is not None:
            hits.append({"path": path, "pattern": pattern})

    has_paths = bool(clean_paths)
    protected = bool(hits)
    autonomous = has_paths and not protected and policy["autonomous_default"] is True
    return {
        "policy_id": policy["policy_id"],
        "paths": clean_paths,
        "protected_hits": hits,
        "autonomous_merge": autonomous and policy["merge"]["enabled"],
        "autonomous_deploy": autonomous and policy["deploy"]["enabled"],
        "independent_review_enforced": policy["review"]["independent_reviewer_required"],
        "decision": "autonomous" if autonomous else "control_plane",
        "reason": (
            "protected_path" if protected else "no_paths" if not has_paths else "policy_disabled"
        ),
    }


def selftest(policy: dict[str, Any]) -> None:
    """Fast stdlib regression pack used by the dedicated CI workflow."""
    validate_policy(policy)

    normal = classify(["agents/core/agent.py", "tests/test_agent.py"], policy)
    if normal["decision"] != "autonomous" or normal["autonomous_merge"] is not True:
        raise PolicyError("selftest: normal product change must be autonomous-merge eligible")
    if normal["autonomous_deploy"] is not False:
        raise PolicyError("selftest: deploy must not be claimed live before its slice lands")

    for path in (
        "selfdev-policy.json",
        "scripts/selfdev_policy.py",
        ".github/workflows/ci.yml",
        ".github/workflows/anything-new.yml",
        "agents/core/kernel/budget.py",
        "agents/core/security/taint.py",
        "AGENTS.md",
        "MAX.md",
    ):
        result = classify([path], policy)
        if result["decision"] != "control_plane" or result["autonomous_merge"] is not False:
            raise PolicyError(f"selftest: root-of-trust path self-authorized: {path}")

    mixed = classify(["frontend/src/app.tsx", "agents/core/kernel/registry.py"], policy)
    if mixed["autonomous_merge"] is not False or not mixed["protected_hits"]:
        raise PolicyError("selftest: one protected path must block a mixed candidate")

    empty = classify([], policy)
    if empty["reason"] != "no_paths" or empty["autonomous_merge"] is not False:
        raise PolicyError("selftest: an unknown/empty diff must fail closed")

    weakened = copy.deepcopy(policy)
    weakened["protected_paths"] = [
        item for item in weakened["protected_paths"] if item != ".github/workflows/**"
    ]
    try:
        validate_policy(weakened)
    except PolicyError:
        pass
    else:
        raise PolicyError("selftest: workflow root-of-trust protection was removable")

    no_checks = copy.deepcopy(policy)
    no_checks["merge"]["require_all_reported_checks_pass"] = False
    try:
        validate_policy(no_checks)
    except PolicyError:
        pass
    else:
        raise PolicyError("selftest: automated-check merge invariant was removable")

    no_rollback = copy.deepcopy(policy)
    no_rollback["deploy"]["auto_rollback_on_regression"] = False
    try:
        validate_policy(no_rollback)
    except PolicyError:
        pass
    else:
        raise PolicyError("selftest: rollback invariant was removable")

    try:
        classify(["../release.yml"], policy)
    except PolicyError:
        pass
    else:
        raise PolicyError("selftest: parent traversal path was accepted")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate policy invariants")
    sub.add_parser("selftest", help="run the stdlib policy regression pack")
    classify_parser = sub.add_parser("classify", help="classify changed repository paths")
    classify_parser.add_argument("paths", nargs="*")
    classify_parser.add_argument(
        "--stdin",
        action="store_true",
        help="append newline-delimited paths read from stdin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _parser().parse_args(argv)
    try:
        policy = load_policy(args.policy)
        if args.command == "validate":
            validate_policy(policy)
            print(f"valid {policy['policy_id']}")
            return 0
        if args.command == "selftest":
            selftest(policy)
            print(f"selftest ok {policy['policy_id']}")
            return 0

        paths = list(args.paths)
        if args.stdin:
            paths.extend(line for line in sys.stdin.read().splitlines() if line.strip())
        print(json.dumps(classify(paths, policy), sort_keys=True))
        return 0
    except PolicyError as exc:
        print(f"selfdev policy error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
