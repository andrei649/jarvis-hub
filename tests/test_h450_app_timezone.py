"""H450: preview and owner jobs use one validated application timezone."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from starlette.requests import Request

from agents.core import settings_db
from agents.core.autonomy import jobs as jobs_module
from agents.core.autonomy import nl_schedule, schedule_timezone
from agents.core.autonomy.jobs import JobRunner, JobStore, run_at
from agents.core.autonomy.schedule_timezone import app_schedule_timezone
from agents.core.routers import tools

EASTERN = ZoneInfo("America/New_York")
BUCHAREST = ZoneInfo("Europe/Bucharest")
REMIND = {"type": "remind", "message": "call home"}


@pytest.fixture
def app_zone(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    settings_db.init_db(force=True)
    settings_db.put_category("general", {"timezone": "US/Eastern"})
    # A deterministic UTC host fallback exposes the prior bug on any CI host.
    monkeypatch.setattr(nl_schedule, "_local_zone", lambda: ZoneInfo("UTC"))
    return lambda value: settings_db.put_category("general", {"timezone": value})


class Scheduler:
    running = False
    timezone = ZoneInfo("UTC")

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = {"trigger": trigger, **kwargs}


def make_runner(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    scheduler = Scheduler()
    runner = JobRunner(store, orch=SimpleNamespace(), scheduler=lambda: scheduler, quiet=lambda: False)
    return runner, store, scheduler


async def preview(text):
    body = json.dumps({"text": text}).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/api/schedule/parse", "headers": []}, receive)
    response = await tools.schedule_parse(request)
    return response.status_code, json.loads(response.body)


@pytest.mark.asyncio
async def test_standalone_preview_and_store_anchor_naive_time_to_app_not_host(app_zone, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "get_orch", lambda: None)
    day = (datetime.now(EASTERN) + timedelta(days=1)).date()
    text = f"{day.isoformat()} 09:00"
    expected = datetime(day.year, day.month, day.day, 9, tzinfo=EASTERN).astimezone(UTC)

    status, result = await preview(text)
    assert status == 200 and datetime.fromisoformat(result["at"]) == expected

    store = JobStore(tmp_path / "jobs.db")
    try:
        job = store.create(name="call", schedule_text=text, action=REMIND)
        assert run_at(job.cron) == expected
        offset = f"{day.isoformat()} 09:00+02:00"
        offset_job = store.create(name="offset", schedule_text=offset, action=REMIND)
        assert run_at(offset_job.cron) == datetime(day.year, day.month, day.day, 7, tzinfo=UTC)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_preview_reads_settings_off_the_event_loop(app_zone, monkeypatch):
    caller_thread = threading.get_ident()
    resolved_threads = []
    monkeypatch.setattr(tools, "get_orch", lambda: None)

    def resolve():
        resolved_threads.append(threading.get_ident())
        return EASTERN

    monkeypatch.setattr(schedule_timezone, "app_schedule_timezone", resolve)
    status, result = await preview("every day at 9")
    assert status == 200 and result["cron"] == "0 9 * * *"
    assert len(resolved_threads) == 1 and resolved_threads[0] != caller_thread


@pytest.mark.asyncio
async def test_runner_preview_create_edit_cron_and_status_share_pinned_app_zone(app_zone, tmp_path, monkeypatch):
    runner, store, scheduler = make_runner(tmp_path)
    monkeypatch.setattr(tools, "get_orch", lambda: SimpleNamespace(jobs=runner))
    try:
        day = (datetime.now(EASTERN) + timedelta(days=1)).date()
        text = f"{day.isoformat()} 09:00"
        expected = datetime(day.year, day.month, day.day, 9, tzinfo=EASTERN).astimezone(UTC)
        status, result = await preview(text)
        assert status == 200 and datetime.fromisoformat(result["at"]) == expected
        job = store.create(name="call", schedule_text=text, action=REMIND)
        assert run_at(job.cron) == expected
        edited = store.edit(job.id, schedule_text="tomorrow at 10")
        tomorrow = (datetime.now(EASTERN) + timedelta(days=1)).date()
        assert run_at(edited.cron) == datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10,
                                              tzinfo=EASTERN).astimezone(UTC)
        recurring = store.create(name="daily", schedule_text="every day at 9", action=REMIND)
        assert runner.register(recurring)
        assert scheduler.jobs[f"job-{recurring.id}"]["timezone"] == EASTERN
        assert runner.snapshot()["timezone"] in {"US/Eastern", "America/New_York"}
        assert runner.slot_timing(recurring) is not None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_live_setting_change_waits_for_runner_restart_and_preview_stays_consistent(app_zone, tmp_path, monkeypatch):
    runner, store, _scheduler = make_runner(tmp_path)
    monkeypatch.setattr(tools, "get_orch", lambda: SimpleNamespace(jobs=runner))
    try:
        assert runner.scheduler_timezone() == EASTERN
        app_zone("Europe/Bucharest")
        day = (datetime.now(EASTERN) + timedelta(days=1)).date()
        text = f"{day.isoformat()} 09:00"
        expected = datetime(day.year, day.month, day.day, 9, tzinfo=EASTERN).astimezone(UTC)
        _, result = await preview(text)
        assert datetime.fromisoformat(result["at"]) == expected
        assert run_at(store.create(name="old runner", schedule_text=text, action=REMIND).cron) == expected

        new_runner, new_store, _ = make_runner(tmp_path / "restarted")
        try:
            assert new_runner.scheduler_timezone() == BUCHAREST
            monkeypatch.setattr(tools, "get_orch", lambda: SimpleNamespace(jobs=new_runner))
            _, result = await preview(text)
            fresh_expected = datetime(day.year, day.month, day.day, 9, tzinfo=BUCHAREST).astimezone(UTC)
            assert datetime.fromisoformat(result["at"]) == fresh_expected
            assert run_at(new_store.create(name="new runner", schedule_text=text, action=REMIND).cron) == fresh_expected
        finally:
            new_store.close()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_invalid_or_unreadable_app_zone_refuses_preview_and_job_without_host_fallback(
    app_zone, tmp_path, monkeypatch,
):
    monkeypatch.setattr(tools, "get_orch", lambda: None)
    store = JobStore(tmp_path / "jobs.db")
    try:
        app_zone("not/a/zone")
        status, result = await preview("tomorrow at 9")
        assert status == 422 and "timezone" in result["error"]
        with pytest.raises(ValueError, match="timezone"):
            store.create(name="bad", schedule_text="tomorrow at 9", action=REMIND)
        assert store.list() == []

        app_zone("US/Eastern")
        monkeypatch.setattr(settings_db, "read_setting", lambda *_: (_ for _ in ()).throw(
            settings_db.SettingsUnreadable("storage error")))
        status, result = await preview("tomorrow at 9")
        assert status == 422 and "timezone" in result["error"]
        with pytest.raises(ValueError, match="timezone"):
            store.create(name="unreadable", schedule_text="tomorrow at 9", action=REMIND)
        assert store.list() == []
    finally:
        store.close()


def test_missing_setting_uses_declared_default_and_malformed_value_refuses(app_zone):
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute("DELETE FROM settings WHERE category='general' AND key='timezone'")
    assert app_schedule_timezone() == BUCHAREST
    app_zone(123)
    with pytest.raises(ValueError, match="configured app timezone is invalid"):
        app_schedule_timezone()
    app_zone("../bad")
    with pytest.raises(ValueError, match="configured app timezone is invalid"):
        app_schedule_timezone()


def test_invalid_first_read_does_not_poison_runner_after_setting_repair(app_zone, tmp_path):
    app_zone("invalid/timezone")
    runner, store, _ = make_runner(tmp_path)
    try:
        with pytest.raises(ValueError, match="timezone"):
            runner.scheduler_timezone()
        app_zone("US/Eastern")
        assert runner.scheduler_timezone() == EASTERN
    finally:
        store.close()


def test_first_zone_pin_is_atomic_across_concurrent_callers(app_zone, tmp_path, monkeypatch):
    runner, store, _ = make_runner(tmp_path)
    calls = 0
    lock = threading.Lock()

    def read_zone():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.03)
        return EASTERN

    monkeypatch.setattr(jobs_module, "app_schedule_timezone", read_zone)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(lambda _: runner.scheduler_timezone(), range(8))) == [EASTERN] * 8
        assert calls == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_fallback_tick_uses_same_app_zone_as_registered_cron(app_zone, tmp_path):
    runner, store, scheduler = make_runner(tmp_path)
    try:
        job = store.create(name="daily", schedule_text="every day at 9", action=REMIND)
        runner.register(job)
        assert scheduler.jobs[f"job-{job.id}"]["timezone"] == EASTERN

        async def no_op():
            return None

        async def fire(job_id):
            return job_id

        runner.reconcile_scripts = no_op
        runner.drain_manual = no_op
        runner.fire = fire
        assert await runner.tick(datetime(2026, 10, 12, 13, 0, tzinfo=UTC)) == [job.id]
        assert await runner.tick(datetime(2026, 10, 12, 13, 0, tzinfo=UTC)) == []
    finally:
        store.close()
