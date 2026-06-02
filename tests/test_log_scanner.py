"""
Tests for LogBugScanner — scheduled log-bug-finding pipeline.

All tests run offline: no psutil, no network, no LM Studio required.
Clock is injected via now_fn to keep results deterministic.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from agents.core.autonomy.log_scanner import (
    LogBugScanner,
    ScanResult,
    QUICK_WINDOW_SECONDS,
    QUICK_SPIKE_MIN_COUNT,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_problems(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _make_error(code="JARVIS-PLUGIN-003", component="gmail",
                severity="error", offset_seconds=0, now=None):
    ts = (now or time.time()) - offset_seconds
    return {
        "code": code,
        "message": f"Test error {code}",
        "category": "plugin",
        "severity": severity,
        "component": component,
        "timestamp": ts,
        "meta": {},
    }


# ── quick_scan ────────────────────────────────────────────────────────────────

class TestQuickScan:
    def test_healthy_when_no_errors(self, tmp_path):
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, [])
        scanner = LogBugScanner()
        result = scanner.quick_scan(path)
        assert result.scan_type == "quick"
        assert result.healthy is True
        assert result.total_errors == 0
        assert result.spike_detected is False

    def test_healthy_when_missing_file(self, tmp_path):
        scanner = LogBugScanner()
        result = scanner.quick_scan(str(tmp_path / "nonexistent.jsonl"))
        assert result.healthy is True

    def test_spike_detected_above_absolute_threshold(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        # 3 errors in the current window → absolute spike threshold hit
        records = [
            _make_error(offset_seconds=60, now=now),
            _make_error(offset_seconds=120, now=now),
            _make_error(offset_seconds=180, now=now),
        ]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.quick_scan(path)
        assert result.spike_detected is True
        assert result.total_errors == 3

    def test_no_spike_below_threshold_no_baseline(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [_make_error(offset_seconds=60, now=now)]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.quick_scan(path)
        # 1 error, no baseline → ratio check skipped, below absolute floor
        assert result.spike_detected is False

    def test_spike_by_ratio_vs_baseline(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        # 1 error in previous window, 2 in current → ratio 2.0 = exact threshold
        records = [
            _make_error(offset_seconds=QUICK_WINDOW_SECONDS + 60, now=now),  # previous
            _make_error(offset_seconds=60, now=now),   # current
            _make_error(offset_seconds=120, now=now),  # current
        ]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.quick_scan(path)
        assert result.spike_detected is True

    def test_new_code_detection(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [_make_error(code="JARVIS-NEW-999", offset_seconds=30, now=now)]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.quick_scan(path)
        assert "JARVIS-NEW-999" in result.new_codes

    def test_known_code_not_flagged_as_new_after_first_scan(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [_make_error(code="JARVIS-PLUGIN-003", offset_seconds=30, now=now)]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        # First scan — code is new
        r1 = scanner.quick_scan(path)
        assert "JARVIS-PLUGIN-003" in r1.new_codes
        # Second scan — scanner has seen it, no longer new
        r2 = scanner.quick_scan(path)
        assert "JARVIS-PLUGIN-003" not in r2.new_codes

    def test_info_severity_not_counted_as_bug(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [_make_error(severity="info", offset_seconds=30, now=now)]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.quick_scan(path)
        assert result.total_errors == 0
        assert result.healthy is True

    def test_old_errors_outside_window_ignored(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        # Error from 2 hours ago — outside both quick windows
        records = [_make_error(offset_seconds=7200, now=now)]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.quick_scan(path)
        assert result.total_errors == 0


# ── hourly_scan ───────────────────────────────────────────────────────────────

class TestHourlyScan:
    def test_healthy_no_errors(self, tmp_path):
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, [])
        scanner = LogBugScanner()
        result = scanner.hourly_scan(path)
        assert result.healthy is True
        assert result.scan_type == "hourly"

    def test_counts_errors_in_current_hour(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [
            _make_error(offset_seconds=60, now=now),
            _make_error(offset_seconds=120, now=now),
        ]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.hourly_scan(path)
        assert result.total_errors == 2

    def test_detects_new_code_not_in_history(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        # Historical error (old)
        records = [
            _make_error(code="JARVIS-OLD-001", offset_seconds=7200, now=now),
            _make_error(code="JARVIS-NEW-999", offset_seconds=60, now=now),
        ]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.hourly_scan(path)
        assert "JARVIS-NEW-999" in result.new_codes
        assert "JARVIS-OLD-001" not in result.new_codes

    def test_repeated_code_not_flagged_as_new(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [
            _make_error(code="JARVIS-PLUGIN-003", offset_seconds=7200, now=now),  # historical
            _make_error(code="JARVIS-PLUGIN-003", offset_seconds=60, now=now),    # current
        ]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.hourly_scan(path)
        assert "JARVIS-PLUGIN-003" not in result.new_codes

    def test_spike_detected_2x_ratio(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [
            _make_error(offset_seconds=3660, now=now),   # previous hour (1 error)
            _make_error(offset_seconds=60, now=now),      # current hour
            _make_error(offset_seconds=120, now=now),     # current hour
        ]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.hourly_scan(path)
        assert result.spike_detected is True


# ── daily_scan ────────────────────────────────────────────────────────────────

class TestDailyScan:
    def test_healthy_no_errors(self, tmp_path):
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, [])
        scanner = LogBugScanner()
        result = scanner.daily_scan(path, report_dir=str(tmp_path / "reports"))
        assert result.healthy is True
        assert result.scan_type == "daily"
        assert result.total_errors == 0

    def test_report_file_created(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [_make_error(offset_seconds=3600, now=now)]
        path = str(tmp_path / "problems.jsonl")
        report_dir = str(tmp_path / "reports")
        _write_problems(path, records)
        result = scanner.daily_scan(path, report_dir=report_dir)
        assert result.report_path is not None
        assert os.path.exists(result.report_path)
        assert result.report_path.endswith(".md")

    def test_report_contents(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [
            _make_error(code="JARVIS-PLUGIN-003", component="gmail",
                        severity="error", offset_seconds=3600, now=now),
            _make_error(code="JARVIS-PLUGIN-003", component="gmail",
                        severity="error", offset_seconds=7200, now=now),
            _make_error(code="JARVIS-LLM-010", component="cloud-llm",
                        severity="critical", offset_seconds=1800, now=now),
        ]
        path = str(tmp_path / "problems.jsonl")
        report_dir = str(tmp_path / "reports")
        _write_problems(path, records)
        result = scanner.daily_scan(path, report_dir=report_dir)
        content = open(result.report_path).read()
        assert "JARVIS-PLUGIN-003" in content
        assert "JARVIS-LLM-010" in content
        assert "gmail" in content
        assert "cloud-llm" in content
        assert "Top Issues" in content

    def test_new_codes_detected_vs_history(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [
            _make_error(code="JARVIS-OLD-001", offset_seconds=90000, now=now),  # >24h, historical
            _make_error(code="JARVIS-NEW-999", offset_seconds=3600, now=now),   # in 24h window
        ]
        path = str(tmp_path / "problems.jsonl")
        report_dir = str(tmp_path / "reports")
        _write_problems(path, records)
        result = scanner.daily_scan(path, report_dir=report_dir)
        assert "JARVIS-NEW-999" in result.new_codes
        assert "JARVIS-OLD-001" not in result.new_codes

    def test_old_errors_outside_24h_excluded(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [_make_error(offset_seconds=90000, now=now)]  # 25 hours ago
        path = str(tmp_path / "problems.jsonl")
        report_dir = str(tmp_path / "reports")
        _write_problems(path, records)
        result = scanner.daily_scan(path, report_dir=report_dir)
        assert result.total_errors == 0
        assert result.healthy is True

    def test_top_issues_sorted_by_frequency(self, tmp_path):
        now = time.time()
        scanner = LogBugScanner(now_fn=lambda: now)
        records = [
            _make_error(code="JARVIS-A-001", offset_seconds=100, now=now),
            _make_error(code="JARVIS-B-002", offset_seconds=200, now=now),
            _make_error(code="JARVIS-B-002", offset_seconds=300, now=now),
            _make_error(code="JARVIS-B-002", offset_seconds=400, now=now),
        ]
        path = str(tmp_path / "problems.jsonl")
        _write_problems(path, records)
        result = scanner.daily_scan(path, report_dir=str(tmp_path / "reports"))
        assert result.top_issues[0]["code"] == "JARVIS-B-002"
        assert result.top_issues[0]["count"] == 3


# ── spike detector ────────────────────────────────────────────────────────────

class TestDetectSpike:
    def test_below_absolute_threshold_no_baseline(self):
        scanner = LogBugScanner()
        assert scanner._detect_spike(2, 0) is False

    def test_at_absolute_threshold(self):
        scanner = LogBugScanner()
        assert scanner._detect_spike(QUICK_SPIKE_MIN_COUNT, 0) is True

    def test_ratio_spike(self):
        scanner = LogBugScanner()
        assert scanner._detect_spike(2, 1) is True   # ratio = 2.0

    def test_no_ratio_spike(self):
        scanner = LogBugScanner()
        assert scanner._detect_spike(1, 1) is False  # ratio = 1.0 < 2.0

    def test_zero_baseline_no_spike_below_absolute(self):
        scanner = LogBugScanner()
        assert scanner._detect_spike(1, 0) is False
