"""BACKLOG HA-2c — a weekday heartbeat fires on the weekday, not a day late.

`HeartbeatScheduler.start` passed cron's day-of-week field (0 = Sunday) straight to
APScheduler (0 = Monday). The jobs engine already owns the translation; the heartbeat now
uses it.
"""
import os
import sys

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
    assert hb.scheduler.started


def test_an_unusable_cron_is_skipped_not_fatal(tmp_path, caplog):
    hb = _heartbeats(tmp_path, {"odd": "cron:0 7 * * 9", "fine": "cron:0 8 * * *"})
    hb.start(orchestrator=None)
    ids = [kw["id"] for _trigger, kw in hb.scheduler.jobs]
    assert ids == ["heartbeat-fine"]
    assert hb.scheduler.started
