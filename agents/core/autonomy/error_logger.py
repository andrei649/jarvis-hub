"""
error_logger.py — persist runtime errors and surface them as diagnostics.

It does two things:
1. `persist_problem(error_log)`: Appends structured error metadata to a JSONLines
   log file (`memory_logs/problems.jsonl`), rotated/capped at 500 entries to
   prevent infinite disk consumption.
2. `sync_problems_to_diagnostics()`: Analyzes warnings/errors/critical errors from
   the last 48 hours, groups them, and writes a checkbox-style diagnostic doc to
   the git-ignored `memory_logs/diagnostics.md`.

NOTE: this used to inject an auto-generated block into the git-tracked
`BACKLOG.md`, which caused recurring `git pull` conflicts (the app rewrote the
tracked file on every autonomy tick; on Windows it also flipped line endings).
Diagnostics now live in a git-ignored file. `sync_problems_to_backlog` is kept
as a backward-compatible alias.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from agents.core.paths import data_path

# Using the unified ErrorLog structure from core.errors
from ..errors import ErrorLog


def persist_problem(error_log: ErrorLog) -> None:
    """Serialize and append an ErrorLog to the local problems file."""
    data = {
        "code": error_log.code,
        "message": error_log.message,
        "category": str(error_log.category),
        "severity": str(error_log.severity),
        "component": error_log.component,
        "timestamp": error_log.timestamp,
        "meta": error_log.meta or {}
    }

    problems_path = str(data_path("problems.jsonl"))

    try:
        os.makedirs(os.path.dirname(problems_path), exist_ok=True)
    except OSError:
        pass

    # Read existing entries to rotate them
    records = []
    if os.path.exists(problems_path):
        try:
            with open(problems_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
        except Exception:
            pass

    records.append(data)

    # Cap at last 500 records
    records = records[-500:]

    try:
        with open(problems_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    except Exception:
        pass


def summarize_problems(problems_path: Optional[str] = None, *, hours: float = 48) -> list[dict]:
    """Load, filter (last `hours`), and group problems by (code, component).

    Pure/read-only — shared by the diagnostics-doc writer below and the
    self-improvement dashboard's `GET /api/self-improvement/status`, so the two
    surfaces can never drift on what counts as an "active" problem.

    Returns groups sorted by most-recently-seen first, each with `code`,
    `component`, `message` (latest), `severity`, `count`, `last_seen`.
    """
    if problems_path is None:
        problems_path = str(data_path("problems.jsonl"))

    problems = []
    if os.path.exists(problems_path):
        try:
            with open(problems_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        problems.append(json.loads(line))
        except Exception:
            pass

    groups = {}
    now_ts = datetime.now(timezone.utc).timestamp()
    window_seconds = hours * 3600

    for p in problems:
        ts = p.get("timestamp", 0)
        if now_ts - ts > window_seconds:
            continue

        severity = p.get("severity", "").lower()
        if severity not in ["warning", "error", "critical"]:
            continue

        key = (p.get("code"), p.get("component"))
        if key not in groups:
            groups[key] = {
                "code": p.get("code"),
                "component": p.get("component"),
                "message": p.get("message"),
                "severity": p.get("severity"),
                "count": 0,
                "last_seen": ts
            }

        groups[key]["count"] += 1
        if ts >= groups[key]["last_seen"]:
            groups[key]["message"] = p.get("message")
            groups[key]["last_seen"] = ts

    return sorted(groups.values(), key=lambda g: g["last_seen"], reverse=True)


def sync_problems_to_diagnostics(output_path: Optional[str] = None, problems_path: Optional[str] = None) -> None:
    """Analyze active errors from the last 48 hours and write them to a standalone,
    git-ignored diagnostics file (``memory_logs/diagnostics.md``).

    Historically this injected an auto-generated block into the git-tracked
    ``BACKLOG.md``. That caused recurring merge conflicts: every autonomy tick
    rewrote the tracked planning doc (and on Windows flipped its line endings
    LF→CRLF), so any ``git pull`` afterwards conflicted on BACKLOG.md. Runtime
    diagnostics now live in a git-ignored file and never touch tracked docs.
    The write is idempotent (skips when unchanged) and pins LF endings.
    """
    if output_path is None:
        output_path = str(data_path("diagnostics.md"))

    sorted_groups = summarize_problems(problems_path, hours=48)

    # Build the standalone diagnostics document.
    task_lines = [
        "# 🔴 Runtime Diagnostics (auto-generated)",
        "",
        "> Auto-generated from active runtime failures in `problems.jsonl`.",
        "> Updated automatically during the autonomy observer check. This file is",
        "> git-ignored — it intentionally does NOT live in BACKLOG.md.",
        ""
    ]

    if sorted_groups:
        for g in sorted_groups:
            code = g["code"]
            comp = g["component"]
            msg = g["message"]
            count = g["count"]
            sev = g["severity"].upper()

            emoji = "🔴" if sev == "CRITICAL" else ("❌" if sev == "ERROR" else "⚠️")
            task_lines.append(f"- [ ] **{code}** [{comp}] {emoji} {msg} (Occurred {count} times)")
    else:
        task_lines.append("✓ No active runtime failures detected in the last 48 hours.")

    task_lines.append("")
    task_content = "\n".join(task_lines)

    # Idempotent write with pinned LF endings (no CRLF churn on Windows).
    try:
        existing = ""
        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                existing = f.read()
        if existing == task_content:
            return
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(task_content)
    except Exception:
        pass


# Backward-compatible alias: the old name wrote into BACKLOG.md, which is exactly
# the behaviour that caused conflicts. It now points at the safe diagnostics file.
sync_problems_to_backlog = sync_problems_to_diagnostics
