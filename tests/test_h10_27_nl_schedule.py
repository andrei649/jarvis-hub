"""Tests for H10.27 — Natural-language scheduling."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.nl_schedule import parse_schedule


def test_daily_at_am():
    r = parse_schedule("every day at 7am")
    assert r["ok"] and r["cron"] == "0 7 * * *"


def test_weekday_pm():
    r = parse_schedule("every weekday at 6:30pm")
    assert r["ok"] and r["cron"] == "30 18 * * 1-5"


def test_specific_day_english():
    r = parse_schedule("every monday at 9")
    assert r["ok"] and r["cron"] == "0 9 * * 1"


def test_romanian_day():
    r = parse_schedule("în fiecare luni la 9")
    assert r["ok"] and r["cron"] == "0 9 * * 1"


def test_multiple_days():
    r = parse_schedule("every monday and wednesday at 8am")
    assert r["ok"] and r["cron"] == "0 8 * * 1,3"


def test_weekend():
    r = parse_schedule("every weekend at 10:00")
    assert r["ok"] and r["cron"] == "0 10 * * 0,6"


def test_weekends_plural_is_not_silently_daily():
    # GOV-147: "weekends at 10am" used to miss the day filter and yield a DAILY cron.
    r = parse_schedule("weekends at 10am")
    assert r["ok"] and r["cron"] == "0 10 * * 0,6" and r["description"].startswith("weekends")


def test_interval_minutes_and_hours():
    assert parse_schedule("every 15 minutes")["cron"] == "*/15 * * * *"
    assert parse_schedule("every 2 hours")["cron"] == "0 */2 * * *"
    assert parse_schedule("hourly")["cron"] == "0 * * * *"


def test_bare_time_is_daily():
    assert parse_schedule("at 23:45")["cron"] == "45 23 * * *"


def test_errors():
    assert parse_schedule("")["ok"] is False
    assert parse_schedule("every monday")["ok"] is False     # no time
    assert parse_schedule("at 99:00")["ok"] is False         # invalid time


def test_zero_interval_is_refused_not_invalid_cron():
    # GOV-148: `every 0 minutes` used to emit `*/0 * * * *` with ok:true.
    assert parse_schedule("every 0 minutes")["ok"] is False
    assert parse_schedule("every 0 hours")["ok"] is False


def test_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        assert c.post("/api/schedule/parse", json={}).status_code == 400
        ok = c.post("/api/schedule/parse", json={"text": "every weekday at 7am"})
        assert ok.status_code == 200 and ok.json()["cron"] == "0 7 * * 1-5"
        bad = c.post("/api/schedule/parse", json={"text": "every monday"})
        assert bad.status_code == 422 and bad.json()["ok"] is False
