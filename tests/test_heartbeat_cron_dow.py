"""BACKLOG HA-2c — a weekday heartbeat fires on the weekday, not a day late.

`HeartbeatScheduler.start` passed cron's day-of-week field (0 = Sunday) straight to
APScheduler (0 = Monday). The jobs engine already owns the translation; the heartbeat now
uses it.
"""
import os
import sys
from datetime import UTC, datetime

import pytest
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.core.autonomy.jobs import cron_kwargs  # noqa: E402
from agents.core.heartbeat import HeartbeatScheduler  # noqa: E402


class _Scheduler:
    def __init__(self):
        self.jobs = []
        self.started = False

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((trigger, kwargs))

    def start(self):
        self.started = True


def _heartbeats(tmp_path, cadences: dict[str, str]) -> HeartbeatScheduler:
    for agent, cadence in cadences.items():
        (tmp_path / agent).mkdir()
        (tmp_path / agent / "HEARTBEAT.md").write_text(
            f"---\nagent: {agent}\ncadence: {cadence}\n---\nbody", encoding="utf-8",
        )
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    hb.load_all()
    hb.scheduler = _Scheduler()
    return hb


def test_weekday_heartbeats_are_translated_to_apschedulers_monday_based_names(tmp_path):
    hb = _heartbeats(tmp_path, {
        "friday": "cron:0 7 * * 1-5",
        "sunday": "cron:0 9 * * 0",
        "daily": "cron:30 6 * * *",
        "named": "cron:0 7 * * mon-fri",
    })
    hb.start(orchestrator=None)
    by_agent = {kw["id"]: kw for trigger, kw in hb.scheduler.jobs if trigger == "cron"}
    weekdays = by_agent["heartbeat-friday"]
    assert weekdays["day_of_week"] == cron_kwargs("0 7 * * 1-5")["day_of_week"]
    assert weekdays["day_of_week"] != "1-5" and weekdays["day_of_week"].startswith("mon")
    assert (weekdays["minute"], weekdays["hour"], weekdays["day"], weekdays["month"]) == ("0", "7", "*", "*")
    assert by_agent["heartbeat-sunday"]["day_of_week"] == cron_kwargs("0 9 * * 0")["day_of_week"]
    assert by_agent["heartbeat-sunday"]["day_of_week"] not in ("0", "mon")
    assert by_agent["heartbeat-daily"]["day_of_week"] == "*"
    assert by_agent["heartbeat-named"]["day_of_week"] == "mon-fri"
    assert hb.scheduler.started


def test_an_unusable_cron_is_skipped_not_fatal(tmp_path, caplog):
    hb = _heartbeats(tmp_path, {"odd": "cron:0 7 * * 9", "fine": "cron:0 8 * * *"})
    hb.start(orchestrator=None)
    ids = [kw["id"] for _trigger, kw in hb.scheduler.jobs]
    assert ids == ["heartbeat-fine"]
    assert hb.scheduler.started


@pytest.mark.parametrize("expression,expected_day", [
    ("0 7 * * 1-5", "2026-09-14"),
    ("0 7 * * 0", "2026-09-13"),
    ("0 7 * * mon-fri", "2026-09-14"),
])
def test_individual_heartbeat_resume_preserves_calendar_day(tmp_path, expression, expected_day):
    hb = _heartbeats(tmp_path, {"jarvis": f"cron:{expression}"})
    hb.scheduler.running = True
    assert hb.start_heartbeat("jarvis", orchestrator=None) is True
    _kind, kwargs = hb.scheduler.jobs[-1]
    trigger = CronTrigger(**{key: kwargs[key] for key in ("minute", "hour", "day", "month", "day_of_week")}, timezone=UTC)
    next_run = trigger.get_next_fire_time(None, datetime(2026, 9, 13, tzinfo=UTC))
    assert next_run.date().isoformat() == expected_day
    assert (next_run.hour, next_run.minute) == (7, 0)


def test_individual_resume_rejects_invalid_cron_without_registration(tmp_path):
    hb = _heartbeats(tmp_path, {"jarvis": "cron:0 7 * * 9"})
    hb.scheduler.running = True
    assert hb.start_heartbeat("jarvis", orchestrator=None) is False
    assert hb.scheduler.jobs == []
