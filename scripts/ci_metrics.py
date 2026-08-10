#!/usr/bin/env python3
"""Convert GitHub Actions run/job evidence into stable CI feedback metrics."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round(max(0.0, (end - start).total_seconds()), 3)


def flatten_jobs(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        jobs = payload.get("jobs", [])
        return jobs if isinstance(jobs, list) else []
    if isinstance(payload, list):
        jobs = []
        for page in payload:
            if isinstance(page, dict) and isinstance(page.get("jobs"), list):
                jobs.extend(page["jobs"])
            elif isinstance(page, dict) and "name" in page:
                jobs.append(page)
        return jobs
    return []


def _category(job: dict[str, Any]) -> str | None:
    failed_steps = [
        step
        for step in job.get("steps", [])
        if step.get("conclusion") in {"failure", "timed_out", "action_required"}
    ]
    text = " ".join(
        [str(job.get("name", "")), *(str(step.get("name", "")) for step in failed_steps)]
    ).lower()
    if not failed_steps and job.get("conclusion") not in {"failure", "timed_out"}:
        return None
    if any(token in text for token in ("generated", "status", "preflight")):
        return "generated-drift"
    if any(token in text for token in ("semgrep", "bandit", "gitleaks", "audit", "security")):
        return "security"
    if any(token in text for token in ("install", "setup", "checkout", "cache", "tool")):
        return "tool-or-infra"
    if any(token in text for token in ("test", "pytest", "jest", "vitest", "smoke")):
        return "test"
    if any(token in text for token in ("lint", "ruff", "format", "complexity")):
        return "static-analysis"
    return "other"


def calculate(run: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    created = _time(run.get("created_at") or run.get("run_started_at"))
    starts = [_time(job.get("started_at")) for job in jobs]
    completions = [_time(job.get("completed_at")) for job in jobs]
    valid_starts = [value for value in starts if value]
    valid_completions = [value for value in completions if value]

    failed_events = []
    for job in jobs:
        for step in job.get("steps", []):
            if step.get("conclusion") in {"failure", "timed_out", "action_required"}:
                ended = _time(step.get("completed_at"))
                if ended:
                    failed_events.append(ended)
        if job.get("conclusion") in {"failure", "timed_out"}:
            ended = _time(job.get("completed_at"))
            if ended:
                failed_events.append(ended)

    job_metrics = []
    categories: dict[str, int] = {}
    for job in sorted(jobs, key=lambda item: (str(item.get("name", "")), int(item.get("id", 0)))):
        category = _category(job)
        if category:
            categories[category] = categories.get(category, 0) + 1
        started = _time(job.get("started_at"))
        completed = _time(job.get("completed_at"))
        job_metrics.append(
            {
                "id": job.get("id"),
                "name": job.get("name", ""),
                "conclusion": job.get("conclusion"),
                "duration_seconds": _seconds(started, completed),
                "failure_category": category,
            }
        )

    first_start = min(valid_starts) if valid_starts else None
    terminal = max(valid_completions) if valid_completions else _time(run.get("updated_at"))
    first_red = min(failed_events) if failed_events else None
    cancelled_jobs = sum(job.get("conclusion") == "cancelled" for job in jobs)
    failed_jobs = sum(job.get("conclusion") in {"failure", "timed_out"} for job in jobs)
    passed_jobs = sum(job.get("conclusion") == "success" for job in jobs)
    return {
        "schema_version": 1,
        "run_id": run.get("id"),
        "run_attempt": run.get("run_attempt", 1),
        "workflow": run.get("name", ""),
        "event": run.get("event", ""),
        "head_sha": run.get("head_sha", ""),
        "conclusion": run.get("conclusion"),
        "job_count": len(jobs),
        "passed_job_count": passed_jobs,
        "failed_job_count": failed_jobs,
        "cancelled_job_count": cancelled_jobs,
        "queue_seconds": _seconds(created, first_start),
        "time_to_first_red_seconds": _seconds(created, first_red),
        "time_to_terminal_seconds": _seconds(created, terminal),
        "superseded_or_cancelled": run.get("conclusion") == "cancelled" or cancelled_jobs > 0,
        "failure_categories": dict(sorted(categories.items())),
        "jobs": job_metrics,
    }


def markdown(metrics: dict[str, Any]) -> str:
    def show(value: Any) -> str:
        return "—" if value is None else str(value)

    lines = [
        "## CI feedback metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Workflow | {metrics['workflow']} |",
        f"| Conclusion | {metrics['conclusion']} |",
        f"| Queue seconds | {show(metrics['queue_seconds'])} |",
        f"| Time to first red | {show(metrics['time_to_first_red_seconds'])} |",
        f"| Time to terminal | {show(metrics['time_to_terminal_seconds'])} |",
        f"| Passed / failed / cancelled jobs | {metrics['passed_job_count']} / {metrics['failed_job_count']} / {metrics['cancelled_job_count']} |",
        f"| Failure categories | {json.dumps(metrics['failure_categories'], sort_keys=True)} |",
        "",
        "| Job | Conclusion | Seconds | Category |",
        "| --- | --- | ---: | --- |",
    ]
    for job in metrics["jobs"]:
        lines.append(
            f"| {job['name']} | {job['conclusion']} | {show(job['duration_seconds'])} | "
            f"{job['failure_category'] or '—'} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--jobs-json", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run = json.loads(args.run_json.read_text(encoding="utf-8"))
        jobs = flatten_jobs(json.loads(args.jobs_json.read_text(encoding="utf-8")))
        if not isinstance(run, dict):
            raise ValueError("run JSON must be an object")
        if not jobs:
            raise ValueError("jobs JSON contains no measured jobs")
        metrics = calculate(run, jobs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ci-metrics: {exc}")
        return 2
    args.json_output.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(markdown(metrics), encoding="utf-8")
    print(json.dumps(metrics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
