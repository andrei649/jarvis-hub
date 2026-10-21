"""Regression tests for the defects the independent S4 review found in ``reports.py``.

* The Markdown renderer rescanned the rest of a line for every unclosed ``*``/``_``/``**``
  opener — quadratic: about 3.5 s of event-loop CPU for one 30 000-character email body.
* The 10-runs-per-hour limit counted ``report_runs`` rows, which disappear with their
  report, so "create, run, delete, repeat" ran the model without any limit.
* Saving a report whose scheduled run was due but not yet claimed by the 30-second tick
  recomputed ``next_run_at`` from now and silently skipped that run.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import db, reports
from tests.support.workspace_fixtures import freeze_clock, ws  # noqa: F401  (ws is a fixture)
from tests.test_workspace_reports_support import cast, signed_in  # noqa: F401  (a fixture)

BUCHAREST = ZoneInfo("Europe/Bucharest")
NOW = datetime(2026, 10, 17, 12, 59, tzinfo=BUCHAREST).timestamp()


@pytest.fixture
def clock(ws, monkeypatch):
    return freeze_clock(monkeypatch, NOW)


@pytest.fixture
def conn(clock):
    connection = db.connect()
    yield connection
    connection.close()


# ── the renderer ─────────────────────────────────────────────────────────────────────

UNCLOSED = ["*a " * 10000, "**a " * 7500, "_a " * 10000, "__a " * 7500]


def test_unclosed_emphasis_markers_render_in_linear_time():
    started = time.perf_counter()
    for text in UNCLOSED:
        html = reports.render_markdown(text[:30000])
        assert "<em>" not in html and "<strong>" not in html
    reports.render_markdown(("*_**__a " * 3750)[:30000])
    # The quadratic version needed ~3.5 s for the first input alone; linear takes ms.
    assert time.perf_counter() - started < 1.0


def test_bounded_spans_keep_the_markdown_a_model_writes():
    assert reports.render_inline("_foo_bar_ și *creștere* și **total: 12%**") == (
        "<em>foo_bar</em> și <em>creștere</em> și <strong>total: 12%</strong>")
    assert reports.render_inline("**a *b* c** și __x__") == (
        "<strong>a <em>b</em> c</strong> și <strong>x</strong>")
    assert reports.render_inline("*a *b") == "*a *b"


# ── the run rate limit ───────────────────────────────────────────────────────────────

def test_deleting_reports_does_not_reset_the_run_limit(conn, cast, monkeypatch):
    monkeypatch.setattr(reports, "spawn_run", lambda run_id: None)
    client, headers = signed_in(cast.member_a)
    body = {"department_id": cast.dept_a, "name": "Unic", "instructions": "Rezumă."}
    for _ in range(reports.RUNS_PER_HOUR):
        report = client.post("/api/workspace/reports", json=body, headers=headers).json()
        assert client.post(f"/api/workspace/reports/{report['id']}/run",
                           headers=headers).status_code == 202
        assert client.delete(f"/api/workspace/reports/{report['id']}",
                             headers=headers).status_code == 204
    assert conn.execute("SELECT COUNT(*) FROM report_runs").fetchone()[0] == 0
    report = client.post("/api/workspace/reports", json=body, headers=headers).json()
    limited = client.post(f"/api/workspace/reports/{report['id']}/run", headers=headers)
    assert (limited.status_code, limited.json()["error"]) == (429, "rate_limited")
    assert limited.json()["retry_after_seconds"] == reports.RUN_WINDOW_SECONDS
    colleague, colleague_headers = signed_in(cast.approver_a)
    assert colleague.post(f"/api/workspace/reports/{report['id']}/run",
                          headers=colleague_headers).status_code == 202


def test_the_run_limit_ignores_scheduled_runs_and_old_ones(conn, cast, clock, monkeypatch):
    monkeypatch.setattr(reports, "spawn_run", lambda run_id: None)
    report_id = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Zilnic", "instructions": "Rezumă."})
    for _ in range(reports.RUNS_PER_HOUR):
        with db.tx(conn):
            reports.create_run(conn, report_id, trigger="schedule", triggered_by=None)
        conn.execute("UPDATE report_runs SET status = 'failed'")
    for _ in range(reports.RUNS_PER_HOUR):
        reports.start_manual_run(conn, cast.member_a, report_id)
        conn.execute("UPDATE report_runs SET status = 'failed'")
    clock.advance(reports.RUN_WINDOW_SECONDS + 1)
    assert reports.start_manual_run(conn, cast.member_a, report_id) > 0


# ── editing a report whose run is due ────────────────────────────────────────────────

def test_an_edit_keeps_a_due_run_the_scheduler_has_not_claimed(conn, cast, clock, monkeypatch):
    monkeypatch.setattr(reports, "spawn_run", lambda run_id: None)
    schedule = {"kind": "daily", "time": "13:00", "timezone": "Europe/Bucharest"}
    report_id = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Zilnic", "instructions": "Rezumă.",
        "schedule": schedule})
    due = datetime(2026, 10, 17, 13, 0, tzinfo=BUCHAREST).timestamp()
    assert conn.execute("SELECT next_run_at FROM reports").fetchone()[0] == due
    clock.advance(70)  # 13:00:10 — due, but the tick has not run yet
    reports.update_report(conn, cast.member_a, report_id, {"name": "Zilnic Nord",
                                                           "schedule": schedule})
    assert conn.execute("SELECT next_run_at FROM reports").fetchone()[0] == due
    assert len(reports.claim_due_reports(conn, clock.current)) == 1
    tomorrow = datetime(2026, 10, 18, 13, 0, tzinfo=BUCHAREST).timestamp()
    assert conn.execute("SELECT next_run_at FROM reports").fetchone()[0] == tomorrow


def test_a_changed_schedule_is_recomputed_even_when_a_run_was_due(conn, cast, clock):
    report_id = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Zilnic", "instructions": "Rezumă.",
        "schedule": {"kind": "daily", "time": "13:00"}})
    clock.advance(70)
    reports.update_report(conn, cast.member_a, report_id,
                          {"schedule": {"kind": "daily", "time": "14:30"}})
    later = datetime(2026, 10, 17, 14, 30, tzinfo=BUCHAREST).timestamp()
    assert conn.execute("SELECT next_run_at FROM reports").fetchone()[0] == later
    reports.update_report(conn, cast.member_a, report_id, {"schedule": {"kind": "manual"}})
    assert conn.execute("SELECT next_run_at FROM reports").fetchone()[0] is None
