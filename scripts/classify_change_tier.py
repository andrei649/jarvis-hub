#!/usr/bin/env python3
"""Classify a change as autonomous (tier 0) or boundary (tier 1), and for
boundary changes decide whether it tightens, is neutral, or loosens.

The rule this encodes:

    Agents may change what the system DOES without asking.
    Agents may TIGHTEN what the system is ALLOWED to do without asking.
    Only a human may LOOSEN what the system is allowed to do.

That last line is the whole boundary. It is deliberately not delegable to a
reviewing model, because a model asked "should agents be allowed to do more?"
is being asked to rule on its own constraints.

Exit codes:
    0  auto-merge eligible (tier 0, or tier 1 that tightens / is neutral)
    2  owner approval required (tier 1 that loosens)
    1  usage / internal error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

MANIFEST = "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"

# Paths that define what the system is allowed to do, rather than what it does.
BOUNDARY_PATHS = (
    ".github/*",
    ".github/**/*",
    "scripts/check_nerva_*.py",
    "scripts/classify_change_tier.py",
    MANIFEST,
    "tests/test_nerva_issue_movement.py",
    "tests/test_nerva_program_manifest.py",
)

# Files whose shrinkage is itself a loosening signal.
GATE_TEST_PATHS = (
    "tests/test_nerva_issue_movement.py",
    "tests/test_nerva_program_manifest.py",
    "tests/test_classify_change_tier.py",
)

WRITE_PERM = re.compile(r"^\s*([a-z-]+)\s*:\s*write\s*$", re.MULTILINE)
PERM_BLOCK = re.compile(r"^(\s*)permissions\s*:\s*(.*)$", re.MULTILINE)
NEEDS_LINE = re.compile(r"^\s*needs\s*:\s*(.+)$", re.MULTILINE)
CONTINUE_ON_ERROR = re.compile(r"^\s*continue-on-error\s*:\s*true\s*$", re.MULTILINE)
SECRETS_REF = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)")
TEST_DEF = re.compile(r"^\s*def (test_[A-Za-z0-9_]+)", re.MULTILINE)
FAIL_GUARD = re.compile(r"^\s*run\s*:\s*exit 1\s*$", re.MULTILINE)


@dataclass
class Verdict:
    tier: int = 0
    direction: str = "neutral"          # tighten | neutral | loosen
    reasons: list[str] = field(default_factory=list)
    boundary_files: list[str] = field(default_factory=list)

    def loosen(self, why: str) -> None:
        self.direction = "loosen"
        self.reasons.append(why)

    def tighten(self, why: str) -> None:
        if self.direction != "loosen":
            self.direction = "tighten"
        self.reasons.append(why)

    @property
    def auto_merge_eligible(self) -> bool:
        return not (self.tier == 1 and self.direction == "loosen")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "direction": self.direction,
            "auto_merge_eligible": self.auto_merge_eligible,
            "requires_owner_approval": not self.auto_merge_eligible,
            "boundary_files": sorted(self.boundary_files),
            "reasons": self.reasons,
        }


def _git(root: str, *args: str) -> str:
    proc = subprocess.run(  # nosec B603
        ("git", "-C", root, *args),
        capture_output=True,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _blob(root: str, ref: str, path: str) -> str:
    return _git(root, "cat-file", "blob", f"{ref}:{path}")


def _changed_files(root: str, base: str, head: str) -> list[tuple[str, str]]:
    """Return (status, path) pairs. Status is one of A/M/D/R."""
    raw = _git(root, "diff", "--name-status", "--no-renames", f"{base}...{head}")
    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out.append((parts[0][0], parts[-1]))
    return out


def is_boundary(path: str) -> bool:
    return any(fnmatch(path, pattern) for pattern in BOUNDARY_PATHS)


def _write_perms(text: str) -> set[str]:
    """Permission keys granted 'write', plus a marker for blanket write-all."""
    perms = {m.group(1) for m in WRITE_PERM.finditer(text)}
    for m in PERM_BLOCK.finditer(text):
        if m.group(2).strip() == "write-all":
            perms.add("*write-all*")
    return perms


def _needs_entries(text: str) -> set[str]:
    entries: set[str] = set()
    for m in NEEDS_LINE.finditer(text):
        body = m.group(1).strip().strip("[]")
        for item in body.split(","):
            name = item.strip().strip("'\"")
            if name:
                entries.add(name)
    return entries


def _inspect_workflow(v: Verdict, path: str, before: str, after: str) -> None:
    gained = _write_perms(after) - _write_perms(before)
    if gained:
        v.loosen(f"{path}: grants new write permission(s): {', '.join(sorted(gained))}")
    dropped_perms = _write_perms(before) - _write_perms(after)
    if dropped_perms:
        v.tighten(f"{path}: drops write permission(s): {', '.join(sorted(dropped_perms))}")

    removed_needs = _needs_entries(before) - _needs_entries(after)
    if removed_needs:
        v.loosen(f"{path}: removes job dependency: {', '.join(sorted(removed_needs))}")

    new_coe = len(CONTINUE_ON_ERROR.findall(after)) - len(CONTINUE_ON_ERROR.findall(before))
    if new_coe > 0:
        v.loosen(f"{path}: adds continue-on-error (a failing check stops failing the run)")

    lost_guards = len(FAIL_GUARD.findall(before)) - len(FAIL_GUARD.findall(after))
    if lost_guards > 0:
        v.loosen(f"{path}: removes {lost_guards} hard-fail guard step(s)")

    # These hold secret NAMES referenced by the workflow text (the identifier
    # after `secrets.`, e.g. "ANTHROPIC_API_KEY"), never secret values — the
    # verdict must be able to print them so the owner sees what a change asks for.
    refs_after = SECRETS_REF.findall(after)
    refs_before = SECRETS_REF.findall(before)
    added_refs = set(refs_after) - set(refs_before)
    if added_refs:
        v.loosen(f"{path}: references new secret(s): {', '.join(sorted(added_refs))}")


def _inspect_manifest(v: Verdict, before: str, after: str) -> None:
    def gate(text: str) -> dict[str, Any]:
        try:
            return json.loads(text).get("movement_gate") or {}
        except Exception:
            return {}

    gb, ga = gate(before), gate(after)
    if gb and not ga:
        v.loosen(f"{MANIFEST}: removes the movement_gate block entirely")
        return
    sb, sa = gb.get("enforcement_state"), ga.get("enforcement_state")
    if sb == "required" and sa and sa != "required":
        v.loosen(f"{MANIFEST}: downgrades enforcement_state {sb!r} -> {sa!r}")
    if sb and sb != "required" and sa == "required":
        v.tighten(f"{MANIFEST}: upgrades enforcement_state {sb!r} -> 'required'")

    rb = (gb.get("receipt_control") or {})
    ra = (ga.get("receipt_control") or {})
    for key in ("fresh_owner_receipts_required", "live_pr_reread_required"):
        if rb.get(key) is True and ra.get(key) is not True:
            v.loosen(f"{MANIFEST}: disables receipt_control.{key}")


def _inspect_tests(v: Verdict, path: str, before: str, after: str) -> None:
    lost = set(TEST_DEF.findall(before)) - set(TEST_DEF.findall(after))
    if lost:
        shown = ", ".join(sorted(lost)[:3])
        more = f" (+{len(lost) - 3} more)" if len(lost) > 3 else ""
        v.loosen(f"{path}: deletes {len(lost)} assertion test(s): {shown}{more}")


def classify(root: str, base: str, head: str) -> Verdict:
    v = Verdict()
    for status, path in _changed_files(root, base, head):
        if not is_boundary(path):
            continue
        v.tier = 1
        v.boundary_files.append(path)

        before = "" if status == "A" else _blob(root, base, path)
        after = "" if status == "D" else _blob(root, head, path)

        if status == "D":
            v.loosen(f"{path}: boundary file deleted")
            continue

        if path.startswith(".github/workflows/"):
            _inspect_workflow(v, path, before, after)
        if path == MANIFEST:
            _inspect_manifest(v, before, after)
        if path in GATE_TEST_PATHS:
            _inspect_tests(v, path, before, after)
        if path == ".github/CODEOWNERS" and len(after.splitlines()) < len(
            before.splitlines()
        ):
            v.loosen(f"{path}: removes owner-review coverage")

    if v.tier == 1 and not v.reasons:
        v.reasons.append("boundary files touched, no loosening signal detected")
    if v.tier == 0:
        v.reasons.append("no boundary files touched")
    return v


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--root", default=".")
    p.add_argument("--format", choices=("json", "text"), default="json")
    args = p.parse_args(argv)

    v = classify(args.root, args.base, args.head)
    if args.format == "json":
        print(json.dumps(v.to_dict(), indent=2))
    else:
        print(f"tier={v.tier} direction={v.direction} auto_merge={v.auto_merge_eligible}")
        for reason in v.reasons:
            print(f"  - {reason}")
    return 0 if v.auto_merge_eligible else 2


if __name__ == "__main__":
    sys.exit(main())
