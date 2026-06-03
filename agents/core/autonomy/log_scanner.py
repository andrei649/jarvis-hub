"""
log_scanner.py — Scheduled log-bug-finding pipeline.

Three scan cadences, all feeding the existing autonomy worker:

  quick_scan  (every 15 min)  Counts new ERROR/CRITICAL entries in the last
                               15-minute window. Fires a monitor.alert task if
                               the rate spikes (≥3 errors OR 2× last window)
                               or if a new error code appears for the first time.

  hourly_scan (every hour)    Compares current-hour vs previous-hour error
                               rates, detects first-seen codes, and refreshes
                               memory_logs/diagnostics.md via sync_problems_to_diagnostics().

  daily_scan  (07:05 daily)   Full 24-hour digest: frequency table per code,
                               per-component health, first occurrences. Writes
                               memory_logs/reports/bug-report-YYYY-MM-DD.md and
                               returns a ScanResult the orchestrator surfaces in
                               the morning brief.

All logic is pure (no I/O side-effects in the main methods) so the test suite
can run offline with injected paths and clocks.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("jarvis.autonomy.log_scanner")

# Severities that count as "bugs" for spike/trend detection.
_BUG_SEVERITIES = {"error", "critical"}

# Quick-scan parameters.
QUICK_WINDOW_SECONDS = 15 * 60       # 15 minutes
QUICK_SPIKE_MIN_COUNT = 3            # absolute floor: always fire above this
QUICK_SPIKE_RATIO = 2.0              # current/previous rate that counts as a spike

# Hourly-scan parameters.
HOUR_SECONDS = 3600
HOURLY_SPIKE_RATIO = 2.0


@dataclass
class ScanResult:
    scan_type: str                   # "quick" | "hourly" | "daily"
    window_start: float              # unix timestamp
    window_end: float
    total_errors: int                # ERROR+CRITICAL in the window
    spike_detected: bool
    new_codes: list[str]             # codes first-seen this window
    top_issues: list[dict]           # [{code, component, count, severity}]
    report_path: Optional[str]       # daily scan only
    healthy: bool                    # True ⟺ no actionable findings


def _load_problems(problems_path: str, since_ts: float = 0.0) -> list[dict]:
    """Read problems.jsonl, optionally filtering to entries after `since_ts`."""
    records: list[dict] = []
    if not os.path.exists(problems_path):
        return records
    try:
        with open(problems_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("timestamp", 0) >= since_ts:
                        records.append(rec)
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return records


def _is_bug(record: dict) -> bool:
    return record.get("severity", "").lower() in _BUG_SEVERITIES


def _top_issues(records: list[dict], limit: int = 10) -> list[dict]:
    counts: dict[tuple, dict] = {}
    for r in records:
        if not _is_bug(r):
            continue
        key = (r.get("code"), r.get("component"))
        if key not in counts:
            counts[key] = {
                "code": r.get("code"),
                "component": r.get("component"),
                "severity": r.get("severity"),
                "count": 0,
                "last_seen": r.get("timestamp", 0),
            }
        counts[key]["count"] += 1
        if r.get("timestamp", 0) > counts[key]["last_seen"]:
            counts[key]["last_seen"] = r.get("timestamp", 0)
            counts[key]["severity"] = r.get("severity")
    return sorted(counts.values(), key=lambda x: x["count"], reverse=True)[:limit]


class LogBugScanner:
    """Pure scanner — inject `now_fn` in tests to control the clock."""

    def __init__(self, now_fn=None):
        self._now = now_fn or (lambda: datetime.now(timezone.utc).timestamp())
        # Tracks which error codes have been seen in previous windows so we can
        # detect first-seen codes in subsequent quick/hourly scans.
        self._seen_codes: set[str] = set()

    # ──────────────────────────────────────────────────────────────
    # Public scan methods
    # ──────────────────────────────────────────────────────────────

    def quick_scan(self, problems_path: str) -> ScanResult:
        """15-minute window scan for spikes and new error codes."""
        now = self._now()
        current_start = now - QUICK_WINDOW_SECONDS
        previous_start = current_start - QUICK_WINDOW_SECONDS

        all_recent = _load_problems(problems_path, since_ts=previous_start)
        previous = [r for r in all_recent if previous_start <= r["timestamp"] < current_start]
        current = [r for r in all_recent if r["timestamp"] >= current_start]

        current_bugs = [r for r in current if _is_bug(r)]
        previous_bugs = [r for r in previous if _is_bug(r)]

        spike = self._detect_spike(len(current_bugs), len(previous_bugs))
        new_codes = self._detect_new_codes(current_bugs)
        self._seen_codes.update(r.get("code") for r in current_bugs if r.get("code"))

        return ScanResult(
            scan_type="quick",
            window_start=current_start,
            window_end=now,
            total_errors=len(current_bugs),
            spike_detected=spike,
            new_codes=new_codes,
            top_issues=_top_issues(current_bugs),
            report_path=None,
            healthy=not spike and not new_codes,
        )

    def hourly_scan(self, problems_path: str) -> ScanResult:
        """1-hour window scan: trend vs previous hour + new code detection."""
        now = self._now()
        current_start = now - HOUR_SECONDS
        previous_start = current_start - HOUR_SECONDS

        all_recent = _load_problems(problems_path, since_ts=previous_start)
        previous = [r for r in all_recent if previous_start <= r["timestamp"] < current_start]
        current = [r for r in all_recent if r["timestamp"] >= current_start]

        current_bugs = [r for r in current if _is_bug(r)]
        previous_bugs = [r for r in previous if _is_bug(r)]

        # Historical codes = everything seen before this hour.
        historical = _load_problems(problems_path, since_ts=0.0)
        historical_before = [r for r in historical if r.get("timestamp", 0) < current_start]
        historical_codes = {r.get("code") for r in historical_before if _is_bug(r)}
        new_codes = [
            r.get("code") for r in current_bugs
            if r.get("code") and r.get("code") not in historical_codes
        ]
        new_codes = list(dict.fromkeys(new_codes))  # deduplicate, preserve order

        spike = self._detect_spike(
            len(current_bugs), len(previous_bugs), ratio=HOURLY_SPIKE_RATIO
        )

        return ScanResult(
            scan_type="hourly",
            window_start=current_start,
            window_end=now,
            total_errors=len(current_bugs),
            spike_detected=spike,
            new_codes=new_codes,
            top_issues=_top_issues(current_bugs),
            report_path=None,
            healthy=not spike and not new_codes and len(current_bugs) == 0,
        )

    def daily_scan(self, problems_path: str, report_dir: Optional[str] = None) -> ScanResult:
        """Full 24-hour digest — writes a Markdown report file."""
        now = self._now()
        day_start = now - 86400

        records = _load_problems(problems_path, since_ts=day_start)
        bugs = [r for r in records if _is_bug(r)]

        # First occurrences of each code in the last 24 hours.
        first_seen: dict[str, float] = {}
        for r in sorted(bugs, key=lambda x: x.get("timestamp", 0)):
            code = r.get("code")
            if code and code not in first_seen:
                first_seen[code] = r["timestamp"]

        # Historical baseline: anything older than 24 hours.
        all_records = _load_problems(problems_path, since_ts=0.0)
        historical_codes = {
            r.get("code") for r in all_records
            if _is_bug(r) and r.get("timestamp", 0) < day_start
        }
        new_codes = [c for c in first_seen if c not in historical_codes]

        top = _top_issues(bugs)
        component_counts = Counter(
            r.get("component", "unknown") for r in bugs
        )

        report_path = self._write_daily_report(
            now, bugs, top, new_codes, component_counts, first_seen, report_dir
        )

        return ScanResult(
            scan_type="daily",
            window_start=day_start,
            window_end=now,
            total_errors=len(bugs),
            spike_detected=False,
            new_codes=new_codes,
            top_issues=top,
            report_path=report_path,
            healthy=len(bugs) == 0,
        )

    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────

    def _detect_spike(self, current: int, previous: int,
                      ratio: float = QUICK_SPIKE_RATIO) -> bool:
        if current >= QUICK_SPIKE_MIN_COUNT:
            return True
        if previous == 0:
            return False
        return (current / previous) >= ratio

    def _detect_new_codes(self, records: list[dict]) -> list[str]:
        """Return codes in `records` not yet in the running seen-codes set."""
        new: list[str] = []
        for r in records:
            code = r.get("code")
            if code and code not in self._seen_codes:
                new.append(code)
        return list(dict.fromkeys(new))

    def _write_daily_report(
        self,
        now: float,
        bugs: list[dict],
        top: list[dict],
        new_codes: list[str],
        component_counts: Counter,
        first_seen: dict[str, float],
        report_dir: Optional[str],
    ) -> Optional[str]:
        if report_dir is None:
            base = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
            report_dir = os.path.join(base, "memory_logs", "reports")
        try:
            os.makedirs(report_dir, exist_ok=True)
        except OSError:
            return None

        date_str = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(report_dir, f"bug-report-{date_str}.md")

        lines = [
            f"# Bug Report — {date_str}",
            "",
            f"**Total errors (24 h):** {len(bugs)}  ",
            f"**New error codes:** {len(new_codes)}  ",
            f"**Affected components:** {len(component_counts)}",
            "",
        ]

        if new_codes:
            lines += ["## 🆕 New Error Codes (first seen today)", ""]
            for code in new_codes:
                ts = first_seen.get(code, 0)
                t = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M UTC")
                lines.append(f"- `{code}` — first seen at {t}")
            lines.append("")

        if top:
            lines += ["## Top Issues", ""]
            for issue in top:
                sev = issue["severity"].upper()
                lines.append(
                    f"- **{issue['code']}** [{issue['component']}] {sev} "
                    f"— {issue['count']} occurrence(s)"
                )
            lines.append("")

        if component_counts:
            lines += ["## Component Health", ""]
            for comp, cnt in component_counts.most_common():
                lines.append(f"- `{comp}`: {cnt} error(s)")
            lines.append("")

        if not bugs:
            lines.append("✓ No errors recorded in the last 24 hours.")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            return None

        return path
