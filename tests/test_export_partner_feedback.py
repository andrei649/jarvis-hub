"""H23.27 — explicit, portable and privacy-safe design-partner export."""

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "export_partner_feedback", REPO / "scripts" / "export_partner_feedback.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


exporter = _load()


def test_environment_is_allowlisted_not_host_fingerprinted():
    source = {
        "app_version": "0.11.0",
        "os": "Windows",
        "os_version": "11",
        "python": "3.12.4",
        "architecture": "AMD64",
        "system_profile": "balanced",
        "hostname": "andrei-pc",
        "username": "andrei",
        "cwd": "C:/Users/andrei/private",
        "token": "secret",
    }
    assert exporter.sanitize_environment(source) == {
        "app_version": "0.11.0",
        "os": "Windows",
        "os_version": "11",
        "python": "3.12.4",
        "architecture": "AMD64",
        "system_profile": "balanced",
    }


def test_packet_aggregates_funnel_actions_failures_latency_and_feedback():
    packet = exporter.build_packet(
        environment={"app_version": "0.11.0", "os": "Windows"},
        analytics_events=[
            {"name": "funnel.intro.view"},
            {"name": "funnel.intro.complete"},
            {"name": "funnel.model.complete"},
        ],
        autonomy_rows=[{"status": "done"}, {"status": "rejected"}, {"status": "failed"}],
        run_rows=[
            {"ok": True, "latency_ms": 10, "input_preview": "private prompt"},
            {"ok": False, "latency_ms": 20, "output_preview": "private answer"},
            {"ok": True, "latency_ms": 100},
        ],
        feedback_rows=[
            {"kind": "nps", "score": 10, "message": "Excellent", "session_id": "private"},
            {"kind": "nps", "score": 4, "message": None},
            {"kind": "bug", "score": None, "message": "Button stuck"},
        ],
        north_star={"north_star": {"total_accepted": 1}, "guardrails_ok": True},
        generated_at="2026-07-12T00:00:00Z",
    )
    assert packet["onboarding"]["completed_steps"] == ["intro", "model"]
    assert packet["autonomy"] == {"accepted": 1, "rejected": 1, "failed": 1, "total": 3}
    assert packet["reliability"]["runs"] == 3
    assert packet["reliability"]["failures"] == 1
    assert packet["reliability"]["latency_ms"] == {"p50": 20.0, "p95": 92.0}
    assert packet["feedback"]["nps"] == 0
    assert packet["feedback"]["written"] == [
        {"kind": "nps", "score": 10, "message": "Excellent"},
        {"kind": "bug", "score": None, "message": "Button stuck"},
    ]
    json.dumps(packet)


def test_packet_never_copies_conversation_or_credentials():
    packet = exporter.build_packet(
        environment={"hostname": "secret-host", "api_key": "sk-private"},
        analytics_events=[{"name": "pageview", "props_json": '{"prompt":"private"}'}],
        autonomy_rows=[{"status": "done", "title": "private task", "payload": "private"}],
        run_rows=[
            {
                "ok": True,
                "latency_ms": 1,
                "input_preview": "PRIVATE PROMPT",
                "output_preview": "PRIVATE ANSWER",
            }
        ],
        feedback_rows=[],
        north_star={"north_star": {"total_accepted": 1}, "authorization": "Bearer private"},
        generated_at="t",
    )
    blob = json.dumps(packet).lower()
    for forbidden in (
        "private prompt",
        "private answer",
        "private task",
        "sk-private",
        "secret-host",
        "authorization",
        "input_preview",
        "output_preview",
    ):
        assert forbidden not in blob
    assert packet["meta"]["conversation_content_included"] is False
    assert "payload" not in packet["autonomy"]


def test_sqlite_readers_are_read_only_aggregate_inputs(tmp_path):
    feedback = tmp_path / "feedback.db"
    with sqlite3.connect(feedback) as conn:
        conn.execute(
            "CREATE TABLE feedback (id INTEGER, ts TEXT, kind TEXT, score INTEGER,"
            " message TEXT, session_id TEXT)"
        )
        conn.execute("INSERT INTO feedback VALUES (1, 't', 'nps', 9, 'works', 'private')")
    autonomy = tmp_path / "autonomy.db"
    with sqlite3.connect(autonomy) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER, status TEXT, title TEXT, payload TEXT)")
        conn.execute("INSERT INTO tasks VALUES (1, 'done', 'secret title', 'secret payload')")
    analytics = tmp_path / "analytics.db"
    with sqlite3.connect(analytics) as conn:
        conn.execute("CREATE TABLE events (id INTEGER, name TEXT, props_json TEXT)")
        conn.execute("INSERT INTO events VALUES (1, 'funnel.intro.complete', '{\"prompt\":\"x\"}')")

    assert exporter.read_feedback_rows(feedback) == [
        {"kind": "nps", "score": 9, "message": "works"}
    ]
    assert exporter.read_autonomy_rows(autonomy) == [{"status": "done"}]
    assert exporter.read_analytics_events(analytics) == [{"name": "funnel.intro.complete"}]


def test_run_history_reader_discards_previews(tmp_path):
    path = tmp_path / "run_history.json"
    path.write_text(
        json.dumps(
            {
                "jarvis": [
                    {
                        "ok": False,
                        "latency_ms": 42,
                        "input_preview": "private prompt",
                        "output_preview": "private answer",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert exporter.read_run_rows(path) == [{"ok": False, "latency_ms": 42.0}]


def test_missing_stores_degrade_to_empty_evidence(tmp_path):
    missing = tmp_path / "missing"
    assert exporter.read_feedback_rows(missing) == []
    assert exporter.read_autonomy_rows(missing) == []
    assert exporter.read_analytics_events(missing) == []
    assert exporter.read_run_rows(missing) == []


def test_markdown_is_shareable_and_repeats_privacy_boundary():
    packet = exporter.build_packet(
        environment={"app_version": "0.11.0"},
        analytics_events=[],
        autonomy_rows=[],
        run_rows=[],
        feedback_rows=[],
        north_star={},
        generated_at="2026-07-12T00:00:00Z",
    )
    markdown = exporter.render_markdown(packet)
    for heading in (
        "# Design-partner feedback export",
        "## Privacy boundary",
        "## Install environment",
        "## Onboarding",
        "## Autonomous actions & reliability",
        "## Feedback",
        "## North-star",
    ):
        assert heading in markdown
    assert "No conversation content" in markdown
