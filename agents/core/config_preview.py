"""
config_preview.py — H10.28 Agent Config Preview.

Before saving a change to an agent's SOUL.md / system prompt, show exactly what
would change (unified diff + line counts) and surface validation warnings, so an
edit in the Admin HUD can be reviewed instead of blind-saved. Pairs with the
H10.22 version store (which holds the current content) and complements its diff
between *committed* versions with a diff against a *proposed, uncommitted* one.
"""

from __future__ import annotations

import difflib

# Soft bounds — warnings, not hard errors (the user may have good reason).
_MIN_LEN = 20
_MAX_LEN = 20_000


def validate_prompt(proposed: str) -> tuple[bool, list[str]]:
    """Lightweight checks → (valid, warnings). Only emptiness is a hard fail."""
    warnings: list[str] = []
    text = proposed or ""
    stripped = text.strip()
    if not stripped:
        return False, ["proposed content is empty"]
    if len(stripped) < _MIN_LEN:
        warnings.append(f"very short ({len(stripped)} chars) — likely incomplete")
    if len(text) > _MAX_LEN:
        warnings.append(f"very large ({len(text)} chars) — over {_MAX_LEN} soft limit")
    if not any(line.lstrip().startswith("#") for line in text.splitlines()):
        warnings.append("no markdown headings — SOUL.md usually has sections (## Mission, …)")
    # Unbalanced frontmatter fence is a common copy-paste error.
    if text.count("---") == 1:
        warnings.append("a single '---' fence — frontmatter may be unbalanced")
    return True, warnings


def preview_change(current: str, proposed: str) -> dict:
    """Return a diff + change stats + validation for a proposed prompt change."""
    current = current or ""
    proposed = proposed or ""
    cur_lines = current.splitlines()
    new_lines = proposed.splitlines()

    diff_lines = list(difflib.unified_diff(
        cur_lines, new_lines, fromfile="current", tofile="proposed", lineterm="",
    ))
    added = sum(1 for d in diff_lines if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff_lines if d.startswith("-") and not d.startswith("---"))

    valid, warnings = validate_prompt(proposed)
    return {
        "changed": current != proposed,
        "diff": "\n".join(diff_lines),
        "added_lines": added,
        "removed_lines": removed,
        "valid": valid,
        "warnings": warnings,
        "is_new": current == "",
    }
