from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ci_metrics", ROOT / "scripts" / "ci_metrics.py")
assert SPEC and SPEC.loader
ci_metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci_metrics)


def _run(**overrides):
    value = {
        "id": 42,
        "run_attempt": 1,
        "name": "CI",
        "event": "pull_request",
        "head_sha": "a" * 40,
        "created_at": "2026-08-10T09:00:00Z",
        "updated_at": "2026-08-10T09:03:00Z",
        "conclusion": "failure",
    }
    value.update(overrides)
    return value


def _job(name, conclusion, start, end, steps=None, job_id=1):
    return {
        "id": job_id,
        "name": name,
        "conclusion": conclusion,
        "started_at": f"2026-08-10T09:00:{start:02d}Z",
        "completed_at": f"2026-08-10T09:00:{end:02d}Z",
        "steps": steps or [],
    }


def test_flatten_jobs_accepts_gh_paginated_slurp_shape():
    jobs = ci_metrics.flatten_jobs([{"jobs": [{"name": "one"}]}, {"jobs": [{"name": "two"}]}])
    assert [job["name"] for job in jobs] == ["one", "two"]


def test_calculates_queue_first_red_and_terminal():
    jobs = [
        _job(
            "fast-gate",
            "failure",
            5,
            20,
            [
                {
                    "name": "generated status",
                    "conclusion": "failure",
                    "completed_at": "2026-08-10T09:00:18Z",
                }
            ],
        ),
        _job("lint", "success", 6, 30, job_id=2),
    ]
    result = ci_metrics.calculate(_run(), jobs)
    assert result["queue_seconds"] == 5.0
    assert result["time_to_first_red_seconds"] == 18.0
    assert result["time_to_terminal_seconds"] == 30.0
    assert result["failure_categories"] == {"generated-drift": 1}


def test_classifies_test_and_infrastructure_failures():
    jobs = [
        _job("ubuntu tests", "failure", 1, 20, [{"name": "pytest", "conclusion": "failure"}]),
        _job("lint", "failure", 1, 10, [{"name": "Install tools", "conclusion": "failure"}], 2),
    ]
    result = ci_metrics.calculate(_run(), jobs)
    assert result["failure_categories"] == {"test": 1, "tool-or-infra": 1}
    assert result["failed_job_count"] == 2


def test_cancelled_runs_are_explicit_and_do_not_invent_a_red():
    jobs = [_job("windows", "cancelled", 1, 5)]
    result = ci_metrics.calculate(_run(conclusion="cancelled"), jobs)
    assert result["superseded_or_cancelled"] is True
    assert result["time_to_first_red_seconds"] is None
    assert result["cancelled_job_count"] == 1


def test_markdown_exposes_product_metrics_and_job_detail():
    result = ci_metrics.calculate(_run(), [_job("lint", "success", 3, 10)])
    rendered = ci_metrics.markdown(result)
    assert "Time to first red" in rendered
    assert "Time to terminal" in rendered
    assert "| lint | success | 7.0 |" in rendered


def test_cli_fails_closed_when_the_jobs_api_returns_no_measurements(tmp_path):
    run_path = tmp_path / "run.json"
    jobs_path = tmp_path / "jobs.json"
    run_path.write_text(json.dumps(_run()), encoding="utf-8")
    jobs_path.write_text('{"jobs": []}', encoding="utf-8")
    code = ci_metrics.main(
        [
            "--run-json",
            str(run_path),
            "--jobs-json",
            str(jobs_path),
            "--json-output",
            str(tmp_path / "out.json"),
            "--markdown-output",
            str(tmp_path / "out.md"),
        ]
    )
    assert code == 2
