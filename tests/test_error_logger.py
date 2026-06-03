"""
Tests for structured error logging and the runtime diagnostics syncer
(core/autonomy/error_logger.py).

Verifies grouping/aggregation, the 48-hour window, and that diagnostics are
written to a standalone (git-ignored) file — never injected into a tracked doc
like BACKLOG.md (BUG-4).
"""

from __future__ import annotations

import json
import time

from agents.core.autonomy.error_logger import sync_problems_to_diagnostics


def _write_problems(path, probs):
    with open(path, "w", encoding="utf-8") as f:
        for p in probs:
            f.write(json.dumps(p) + "\n")


def test_sync_writes_grouped_diagnostics_to_standalone_file(tmp_path):
    diag_file = tmp_path / "diagnostics.md"
    problems_file = tmp_path / "problems.jsonl"

    now = time.time()
    _write_problems(problems_file, [
        {"code": "JARVIS-PLUGIN-003", "message": "Gmail auth expired", "category": "plugin",
         "severity": "error", "component": "gmail", "timestamp": now - 3600, "meta": {}},
        {"code": "JARVIS-PLUGIN-003", "message": "Gmail auth expired", "category": "plugin",
         "severity": "error", "component": "gmail", "timestamp": now - 600, "meta": {}},
        {"code": "JARVIS-LLM-010", "message": "heavy thinking timed out", "category": "llm",
         "severity": "warning", "component": "cloud-llm", "timestamp": now - 1800, "meta": {}},
        # Old error — must be filtered out (>48h)
        {"code": "JARVIS-NETWORK-005", "message": "Disconnected", "category": "network",
         "severity": "critical", "component": "net", "timestamp": now - (50 * 3600), "meta": {}},
    ])

    sync_problems_to_diagnostics(output_path=str(diag_file), problems_path=str(problems_file))

    result = diag_file.read_text(encoding="utf-8")
    assert "Runtime Diagnostics" in result
    assert "Gmail auth expired (Occurred 2 times)" in result        # aggregated
    assert "heavy thinking timed out (Occurred 1 times)" in result
    assert "JARVIS-NETWORK-005" not in result                       # >48h filtered out


def test_sync_does_not_touch_a_tracked_backlog(tmp_path):
    """Regression guard for BUG-4: the syncer must never modify BACKLOG.md."""
    diag_file = tmp_path / "diagnostics.md"
    problems_file = tmp_path / "problems.jsonl"
    backlog_file = tmp_path / "BACKLOG.md"

    _write_problems(problems_file, [
        {"code": "JARVIS-PLUGIN-003", "message": "Gmail auth expired", "category": "plugin",
         "severity": "error", "component": "gmail", "timestamp": time.time() - 600, "meta": {}},
    ])
    original_backlog = "# Jarvis Hub Backlog\n\n## Status General\n- Done: 100%\n"
    backlog_file.write_text(original_backlog, encoding="utf-8")

    sync_problems_to_diagnostics(output_path=str(diag_file), problems_path=str(problems_file))

    # Diagnostics went to the standalone file; the backlog is byte-identical.
    assert diag_file.exists()
    assert backlog_file.read_text(encoding="utf-8") == original_backlog


def test_sync_reports_healthy_when_no_recent_failures(tmp_path):
    diag_file = tmp_path / "diagnostics.md"
    problems_file = tmp_path / "problems.jsonl"

    problems_file.write_text("", encoding="utf-8")          # no problems
    diag_file.write_text("- [ ] old task\n", encoding="utf-8")  # stale content

    sync_problems_to_diagnostics(output_path=str(diag_file), problems_path=str(problems_file))

    result = diag_file.read_text(encoding="utf-8")
    assert "No active runtime failures detected in the last 48 hours" in result
    assert "old task" not in result                          # stale content replaced


def test_sync_is_idempotent(tmp_path):
    """A second run with unchanged inputs must not rewrite the file (no churn)."""
    diag_file = tmp_path / "diagnostics.md"
    problems_file = tmp_path / "problems.jsonl"
    problems_file.write_text("", encoding="utf-8")

    sync_problems_to_diagnostics(output_path=str(diag_file), problems_path=str(problems_file))
    mtime1 = diag_file.stat().st_mtime_ns
    time.sleep(0.01)
    sync_problems_to_diagnostics(output_path=str(diag_file), problems_path=str(problems_file))
    mtime2 = diag_file.stat().st_mtime_ns
    assert mtime1 == mtime2
