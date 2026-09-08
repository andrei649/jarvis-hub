#!/usr/bin/env python3
"""Classify autonomous Nerva development changes against the trusted control plane.

The normal development posture is owner-out-of-loop: an AI-built change may be
reviewed, merged and eventually deployed automatically. The exception is the
small set of files that define *whether* autonomous development is allowed to
do that. Those paths are the root of trust and may not self-authorize their own
relaxation.

This module is deliberately stdlib-only so the auto-merge workflow can run it
from a clean checkout of ``main`` before it decides whether a candidate PR is
eligible for unattended merge.

Examples::

    python scripts/selfdev_policy.py validate
    python scripts/selfdev_policy.py classify agents/core/foo.py tests/test_foo.py
    gh pr view 123 --json files --jq '.files[].path' | \
        python scripts/selfdev_policy.py classify --stdin
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO / "selfdev-policy.json"

# These are architectural invariants, not a second configurable list. A policy
# edit that removes any of them is invalid. The auto-merge workflow evaluates a
# candidate with the policy/script already present on trusted ``main``.
MANDATORY_PROTECTED_PATHS = (
    "selfdev-policy.json",
    "scripts/selfdev_policy.py",
    ".github/workflows/pr-auto-merge.yml",
    ".github/workflows/release.yml",
    ".github/workflows/security.yml",
    "agents/core/kernel/__init__.py",
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
    if not isinstance(merge, dict) or merge.get("enabled") is not True:
        raise PolicyError("merge.enabled must be true")
    if merge.get("deny_protected_changes") is not True:
        raise PolicyError("merge must deny protected-path changes")
    if merge.get("require_non_draft") is not True:
        raise PolicyError("merge must require a non-draft PR")
    if merge.get("require_clean_merge_state") is not True:
        raise PolicyError("merge must require CLEAN GitHub merge state")

    deploy = policy.get("deploy")
    if not isinstance(deploy, dict) or deploy.get("enabled") is not True:
        raise PolicyError("deploy.enabled must be true")
    if deploy.get("deny_protected_changes") is not True:
        raise PolicyError("deploy must deny protected-path changes")
    if deploy.get("strategy") != "staged_canary":
        raise PolicyError("deploy.strategy must be staged_canary")
    if deploy.get("require_post_deploy_probe") is not True:
        raise PolicyError("deploy must require a post-deploy probe")
    if deploy.get("auto_rollback_on_regression") is not True:
        raise PolicyError("deploy must automatically roll back regressions")

    review = policy.get("review")
    if not isinstance(review, dict) or review.get("independent_reviewer_required") is not True:
        raise PolicyError("an independent reviewer is required")
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


def classify(paths: list[str], policy: dict[str, Any]) -> dict[str, Any]:
    """Classify a candidate change using only machine-readable policy.

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
        "decision": "autonomous" if autonomous else "control_plane",
        "reason": (
            "protected_path" if protected else "no_paths" if not has_paths else "policy_disabled"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate policy invariants")
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
