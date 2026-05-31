"""
error_logger.py — persist runtime errors and synchronize them to BACKLOG.md.

This component addresses your request for an easily-analyzed error logger that
creates backlog tasks automatically when the AI (or the observer loop) reads it.

It does two things:
1. `persist_problem(error_log)`: Appends structured error metadata to a JSONLines
   log file (`memory_logs/problems.jsonl`), rotated/capped at 500 entries to
   prevent infinite disk consumption.
2. `sync_problems_to_backlog()`: Analyzes warnings/errors/critical errors from the
   last 48 hours, groups them, and generates clean, checkbox-style diagnostic
   tasks directly in `BACKLOG.md` in an updateable block.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

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

    # Locate cabinet root directory relative to this file
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    problems_path = os.path.join(base_dir, "memory_logs", "problems.jsonl")

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


def sync_problems_to_backlog(backlog_path: Optional[str] = None, problems_path: Optional[str] = None) -> None:
    """Analyze active errors from the last 48 hours and sync them to BACKLOG.md."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    if backlog_path is None:
        backlog_path = os.path.join(base_dir, "BACKLOG.md")
    if problems_path is None:
        problems_path = os.path.join(base_dir, "memory_logs", "problems.jsonl")

    if not os.path.exists(backlog_path):
        return

    # Load problems
    problems = []
    if os.path.exists(problems_path):
        try:
            with open(problems_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        problems.append(json.loads(line))
        except Exception:
            pass

    # Filter and group errors from the last 48 hours
    groups = {}
    now_ts = datetime.now(timezone.utc).timestamp()
    
    for p in problems:
        ts = p.get("timestamp", 0)
        # 48-hour window
        if now_ts - ts > 48 * 3600:
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

    # If no active errors in the last 48 hours, remove/update section to be empty/clear
    task_lines = [
        "## 🔴 Auto-Generated Diagnostic Tasks",
        "",
        "> [!NOTE]",
        "> These tasks are auto-generated from active runtime failures in `problems.jsonl`.",
        "> Sync runs automatically during the autonomy observer check.",
        ""
    ]

    if groups:
        # Sort by last seen desc
        sorted_groups = sorted(groups.values(), key=lambda g: g["last_seen"], reverse=True)
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

    # Read BACKLOG.md
    try:
        with open(backlog_path, "r", encoding="utf-8") as f:
            backlog_text = f.read()
    except Exception:
        return

    # Check if section exists and replace or insert it
    if "## 🔴 Auto-Generated Diagnostic Tasks" in backlog_text:
        # Match from section header to next major section header
        new_backlog_text = re.sub(
            r"## 🔴 Auto-Generated Diagnostic Tasks[\s\S]*?(?=(?:## ORIZONT 5|## ORIZONT 6|## ✅ Arhiv|## Status|$))",
            task_content,
            backlog_text
        )
    else:
        # Insert right before Orizont 5 Next Wave section
        if "## ORIZONT 5" in backlog_text:
            new_backlog_text = backlog_text.replace("## ORIZONT 5", task_content + "\n## ORIZONT 5")
        elif "## ORIZONT 5 — Next Wave" in backlog_text:
            new_backlog_text = backlog_text.replace("## ORIZONT 5 — Next Wave", task_content + "\n## ORIZONT 5 — Next Wave")
        else:
            new_backlog_text = backlog_text + "\n\n" + task_content

    # Write back to BACKLOG.md
    try:
        with open(backlog_path, "w", encoding="utf-8") as f:
            f.write(new_backlog_text)
    except Exception:
        pass
