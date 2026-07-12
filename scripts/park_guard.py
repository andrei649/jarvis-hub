#!/usr/bin/env python3
"""Block pull requests that modify parked modules without a scoped unpark declaration."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil

# CI guard executes resolved git with a fixed argv and never invokes a shell.
import subprocess  # nosec B404
import sys
from pathlib import PurePosixPath

# O26 Phase 6, revised 2026-07-11. Values are the only phase declarations that
# may unlock each module; training/rust deliberately remain owner-pull only.
PARK_POLICY = {
    "browser_agent": {"phase": "wave-1", "paths": ("agents/core/browser_agent.py",)},
    "desktop_operator": {"phase": "wave-1", "paths": ("agents/core/desktop_operator.py",)},
    "screen_grounding": {"phase": "wave-1", "paths": ("agents/core/screen_grounding.py",)},
    "image_gen": {"phase": "wave-2", "paths": ("agents/core/image_gen.py",)},
    "media_gen": {"phase": "wave-2", "paths": ("agents/core/media_gen.py",)},
    "media_skill": {"phase": "wave-2", "paths": ("agents/core/media_skill.py",)},
    "wyoming": {"phase": "wave-3", "paths": ("agents/core/voice/wyoming.py",)},
    "satellite_hub": {"phase": "wave-3", "paths": ("agents/core/satellite_hub.py",)},
    "node_mesh": {"phase": "wave-3", "paths": ("agents/core/node_mesh.py",)},
    "e2e_sync": {"phase": "wave-3", "paths": ("agents/core/e2e_sync.py",)},
    "training": {"phase": "owner", "paths": ("training/",)},
    "rust": {"phase": "owner", "paths": ("rust/",)},
    "park-policy": {
        "phase": "policy",
        "paths": ("scripts/park_guard.py", ".github/workflows/park-guard.yml"),
    },
}

_PHASE_ALIASES = {
    "wave-1": {"wave-1", "wave 1", "h28", "orizont 28"},
    "wave-2": {"wave-2", "wave 2", "h29", "orizont 29"},
    "wave-3": {"wave-3", "wave 3", "h30", "h33", "orizont 30", "orizont 33"},
}
_DECLARATION_RE = re.compile(r"^\s*unpark:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)


def _normalize(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/").lstrip("./")))


def _matches(path: str, pattern: str) -> bool:
    normalized = _normalize(path)
    expected = _normalize(pattern)
    return normalized.startswith(expected) if pattern.endswith("/") else normalized == expected


def declarations(text: str) -> set[str]:
    """Parse explicit line-based declarations; incidental prose never unlocks code."""
    tokens = set()
    for value in _DECLARATION_RE.findall(text or ""):
        for token in re.split(r"\s*[,;]\s*", value):
            normalized = re.sub(r"\s+", " ", token.strip().lower())
            if normalized:
                tokens.add(normalized)
    return tokens


def _allowed(module: str, phase: str, declared: set[str]) -> bool:
    if module in declared:
        return True
    if phase in _PHASE_ALIASES and declared.intersection(_PHASE_ALIASES[phase]):
        return True
    if phase == "owner":
        return f"owner {module}" in declared
    if phase == "policy":
        return "park-policy" in declared
    return False


def evaluate(changed_paths: list[str], pr_text: str) -> dict:
    declared = declarations(pr_text)
    violations = []
    parked_touches = []
    for raw_path in changed_paths:
        path = _normalize(raw_path)
        for module, rule in PARK_POLICY.items():
            if not any(_matches(path, pattern) for pattern in rule["paths"]):
                continue
            parked_touches.append({"path": path, "module": module, "phase": rule["phase"]})
            if not _allowed(module, rule["phase"], declared):
                expected = (
                    f"unpark: owner {module}"
                    if rule["phase"] == "owner"
                    else f"unpark: {module} (or {rule['phase']})"
                )
                violations.append(
                    {
                        "path": path,
                        "module": module,
                        "phase": rule["phase"],
                        "expected": expected,
                    }
                )
            break
    return {
        "ok": not violations,
        "declarations": sorted(declared),
        "parked_touches": parked_touches,
        "violations": violations,
    }


def changed_paths(base: str, head: str) -> list[str]:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git executable not found")
    proc = subprocess.run(  # noqa: S603  # nosec B603
        [git, "diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base}...{head}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git diff failed ({proc.returncode})")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="base commit for a three-dot diff")
    parser.add_argument("--head", default="HEAD", help="head commit for a three-dot diff")
    parser.add_argument("--changed-path", action="append", default=[])
    parser.add_argument("--text", help="PR title/body; defaults to CI environment")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.changed_path:
        paths = args.changed_path
    elif args.base:
        paths = changed_paths(args.base, args.head)
    else:
        parser.error("provide --base or at least one --changed-path")
    pr_text = args.text
    if pr_text is None:
        pr_text = f"{os.environ.get('PR_TITLE', '')}\n{os.environ.get('PR_BODY', '')}"
    result = evaluate(paths, pr_text)
    if args.json:
        print(json.dumps(result, indent=2))
    elif result["ok"]:
        print(f"Park guard PASS: {len(result['parked_touches'])} authorized parked-path touch(es).")
    else:
        print("Park guard FAIL: parked modules changed without a matching declaration.")
        for violation in result["violations"]:
            print(
                f"- {violation['path']} ({violation['module']}, {violation['phase']}); "
                f"expected `{violation['expected']}`"
            )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
