"""diff.py — which diagnostics an edit introduced (H564/H597).

Given the file's text and diagnostics before the edit and after it:

1. **Re-anchor** — the baseline's line numbers are carried across the edit with a
   line-level diff (:class:`difflib.SequenceMatcher`): a baseline diagnostic on an
   unchanged line moves with that line; one on a changed or deleted line has no
   anchor and cannot match anything.
2. **Subtract** — a post-edit diagnostic is pre-existing when a baseline one with the
   same severity, code, source and message sits on its re-anchored line (exactly, as
   a multiset), or — outside the edited lines only — anywhere in the file (a shift the
   line map cannot see, such as a column move). Everything else is new.
3. **Attribute** — each new diagnostic says whether it lies on a line the edit
   changed (``in_edit``), and the edited line ranges are reported.
4. **Bound** — errors and warnings only, deduplicated, at most :data:`MAX_REPORTED`,
   each message cut to :data:`MAX_MESSAGE_CHARS` with control characters removed and
   scanned for injected instructions (the server is third-party; what it says is data).
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from collections.abc import Sequence

MAX_REPORTED = 20
MAX_MESSAGE_CHARS = 300
MAX_DIFF_LINES = 20000
SEVERITY = {1: "error", 2: "warning", 3: "information", 4: "hint"}
REPORTED_SEVERITIES = frozenset({1, 2})
_CONTROL = re.compile("[" + "\\x00-\\x08\\x0b-\\x1f\\x7f" + "\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069" + "\\U000e0000-\\U000e007f" + "]")
_SPACE = re.compile(r"\s+")


def line_map(old: str, new: str) -> tuple[dict[int, int], list[tuple[int, int]]]:
    """``(old line → new line for unchanged lines, edited new-line ranges [start, end))``."""
    a, b = old.splitlines(), new.splitlines()
    if len(a) > MAX_DIFF_LINES or len(b) > MAX_DIFF_LINES:
        return {}, [(0, max(len(b), 1))]
    mapping: dict[int, int] = {}
    edited: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[i1 + k] = j1 + k
        else:
            edited.append((j1, max(j2, j1 + 1)))   # a pure deletion marks the line it closed up on
    return mapping, edited


def _line(diag: dict) -> int:
    try:
        line = diag["range"]["start"]["line"]
        return line if isinstance(line, int) and not isinstance(line, bool) else -1
    except (KeyError, TypeError):
        return -1


def _severity(diag: dict) -> int:
    value = diag.get("severity")
    return value if value in SEVERITY else 1   # LSP: a missing severity is the client's call — treat as error


def _identity(diag: dict) -> tuple:
    code = diag.get("code")
    return (_severity(diag), str(code) if code is not None else "", str(diag.get("source") or ""),
            str(diag.get("message") or ""))


def clean(text: object, limit: int = MAX_MESSAGE_CHARS) -> str:
    out = _SPACE.sub(" ", _CONTROL.sub("", str(text or ""))).strip()
    return out if len(out) <= limit else out[: limit - 1] + "…"


def _guard(text: str) -> str:
    """A message that reads like instructions to the model is withheld, by rule name."""
    try:
        from agents.core.security.quarantine import detect_injection_normalized

        hits = detect_injection_normalized(text)
    except Exception:  # noqa: BLE001 — the scanner is a guard, not a dependency
        hits = []
    return f"[BLOCKED diagnostic text: it matched {len(hits)} injection rule(s)]" if hits else text


def _in_edit(line: int, edited: Sequence[tuple[int, int]]) -> bool:
    return any(start <= line < end for start, end in edited)


def introduced(old_text: str, before: Sequence[dict], new_text: str, after: Sequence[dict]) -> dict:
    """The report: new diagnostics (bounded), counts, edited ranges."""
    mapping, edited = line_map(old_text, new_text)
    anchored: Counter = Counter()
    floating: Counter = Counter()
    for diag in before:
        if not isinstance(diag, dict):
            continue
        ident = _identity(diag)
        floating[ident] += 1
        new_line = mapping.get(_line(diag))
        if new_line is not None:
            anchored[(ident, new_line)] += 1
    fresh: list[dict] = []
    survived = 0
    for diag in after:
        if not isinstance(diag, dict):
            continue
        ident, line = _identity(diag), _line(diag)
        if anchored[(ident, line)] > 0:
            anchored[(ident, line)] -= 1
            floating[ident] -= 1
            survived += 1
            continue
        if not _in_edit(line, edited) and floating[ident] > 0:
            floating[ident] -= 1
            survived += 1
            continue
        fresh.append(diag)
    baseline_total = sum(1 for d in before if isinstance(d, dict))
    reported: list[dict] = []
    seen: set[tuple] = set()
    for diag in fresh:
        severity = _severity(diag)
        if severity not in REPORTED_SEVERITIES:
            continue
        line = _line(diag)
        message = _guard(clean(diag.get("message")))
        key = (line, severity, message)
        if key in seen:
            continue
        seen.add(key)
        try:
            col = int(diag["range"]["start"]["character"])
            end_line = int(diag["range"]["end"]["line"])
        except (KeyError, TypeError, ValueError):
            col, end_line = 0, line
        item = {"line": line + 1, "column": col + 1, "end_line": end_line + 1,
                "severity": SEVERITY[severity], "message": message,
                "in_edit": _in_edit(line, edited)}
        code = diag.get("code")
        if code is not None:
            item["code"] = _guard(clean(code, 60))
        source = diag.get("source")
        if source:
            item["source"] = _guard(clean(source, 40))
        reported.append(item)
    reported.sort(key=lambda d: (not d["in_edit"], d["severity"] != "error", d["line"], d["column"]))
    return {
        "new": reported[:MAX_REPORTED],
        "new_count": len(reported),
        "truncated": len(reported) > MAX_REPORTED,
        "resolved_count": max(0, baseline_total - survived),
        "edited_lines": [[start + 1, end] for start, end in edited[:20]],
    }


__all__ = ["MAX_REPORTED", "clean", "introduced", "line_map"]
