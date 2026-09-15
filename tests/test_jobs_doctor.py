"""Read-only owner-job health, including silent schedule and held-delivery failures."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agents.core.autonomy.jobs import JobRunner, JobStore

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class Scheduler:
    running = True
    state = 1
    timezone = UTC

    def __init__(self):
        self.jobs = []
        self.reads = 0

    def get_jobs(self):
        self.reads += 1
        return self.jobs


@pytest.fixture
def setup(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    scheduler = Scheduler()
    orch = SimpleNamespace(channels={})
    runner = JobRunner(store, orch=orch, scheduler=lambda: scheduler,
                       now=lambda: NOW.timestamp(), quiet=lambda: False)
    job = store.create(name="hourly", schedule_text="0 * * * *",
                       action={"type": "remind", "message": "private message"},
                       options={"deliver": []})
    scheduler.jobs = [SimpleNamespace(id=f"job-{job.id}", next_run_time=NOW + timedelta(hours=1))]
    yield store, scheduler, orch, runner, job
    store.close()


def codes(report):
    return {problem["code"] for problem in report["problems"]}


def test_healthy_snapshot_is_read_only_and_contains_no_message(setup):
    store, scheduler, _orch, runner, job = setup
    writes = store._conn.total_changes
    before = store.get(job.id).as_dict()

    report = runner.doctor()

    assert report["ok"] is True and report["problems"] == []
    assert report["jobs"][0]["job_id"] == job.id
    assert report["jobs"][0]["next_run_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert report["checked_at"] == NOW.isoformat()
    assert "private message" not in json.dumps(report)
    assert store._conn.total_changes == writes and store.get(job.id).as_dict() == before
    assert scheduler.reads == 1


@pytest.mark.parametrize("state,running", [(0, False), (2, True)])
def test_stopped_or_paused_scheduler_is_unhealthy(setup, state, running):
    _store, scheduler, _orch, runner, _job = setup
    scheduler.state, scheduler.running = state, running
    report = runner.doctor()
    assert report["ok"] is False
    assert "scheduler_not_running" in codes(report)


def test_unregistered_active_job_is_unhealthy(setup):
    _store, scheduler, _orch, runner, _job = setup
    scheduler.jobs = []
    assert "not_registered" in codes(runner.doctor())


@pytest.mark.parametrize("next_run,code", [
    (None, "missing_next_run"),
    (NOW - timedelta(seconds=1), "overdue"),
    (NOW.replace(tzinfo=None), "invalid_next_run"),
])
def test_active_schedule_must_have_a_valid_future_run(setup, next_run, code):
    _store, scheduler, _orch, runner, _job = setup
    scheduler.jobs[0].next_run_time = next_run
    report = runner.doctor()
    assert report["ok"] is False and code in codes(report)


def test_last_failure_does_not_disclose_error_content(setup):
    store, _scheduler, _orch, runner, job = setup
    store.update(job.id, last_status="failed", last_summary="private credential details")
    report = runner.doctor()
    assert "last_run_failed" in codes(report)
    assert "private credential details" not in json.dumps(report)


@pytest.mark.parametrize("fields", [
    {"enabled": False}, {"paused_reason": "owner paused"},
])
def test_inactive_owner_jobs_do_not_require_registration(setup, fields):
    store, scheduler, _orch, runner, job = setup
    store.update(job.id, **fields)
    scheduler.jobs = []
    report = runner.doctor()
    assert report["ok"] is True
    assert report["jobs"][0]["active"] is False


def test_exhausted_repeat_does_not_require_registration(setup):
    store, scheduler, _orch, runner, job = setup
    store.update(job.id, options={"repeat": 1, "deliver": []})
    assert store.reserve_attempt(job.id)
    scheduler.jobs = []
    assert runner.doctor()["ok"] is True


def test_delivery_target_from_action_is_checked_without_reading_credentials(setup):
    store, _scheduler, orch, runner, job = setup
    store.update(job.id, action={"type": "remind", "message": "private", "channel": "ntfy"},
                 options={})
    assert "channel_unavailable" in codes(runner.doctor())
    orch.channels["ntfy"] = object()
    assert runner.doctor()["ok"] is True


def test_non_delivering_ask_does_not_require_a_channel(setup):
    store, _scheduler, _orch, runner, job = setup
    store.update(job.id, action={"type": "ask", "prompt": "private", "deliver": False},
                 options={"deliver": ["ntfy"]})
    assert runner.doctor()["ok"] is True


def test_scheduler_read_failure_is_a_health_failure(setup):
    _store, scheduler, _orch, runner, _job = setup

    def unavailable():
        raise RuntimeError("private scheduler details")

    scheduler.get_jobs = unavailable
    report = runner.doctor()
    assert report["ok"] is False and "scheduler_unreadable" in codes(report)
    assert "private scheduler details" not in json.dumps(report)


def test_native_scheduler_job_overdue_is_also_visible(setup):
    _store, scheduler, _orch, runner, _job = setup
    scheduler.jobs.append(SimpleNamespace(id="daily-backup", next_run_time=NOW - timedelta(hours=1)))
    report = runner.doctor()
    assert any(p["job_id"] == "daily-backup" and p["code"] == "overdue"
               for p in report["problems"])


@pytest.mark.asyncio
async def test_held_delivery_failure_survives_restart_until_success(setup):
    store, _scheduler, orch, runner, job = setup
    store.update(job.id, last_status="ok")
    store.hold(job.id, "private held message", "ntfy")

    async def fail(_text):
        raise RuntimeError("private delivery credential")

    orch.channels["ntfy"] = SimpleNamespace(send=fail)
    assert await runner.flush_held() == 0
    assert store.get(job.id).last_delivery_status == "failed"
    with_store = JobStore(store._path)
    try:
        assert with_store.get(job.id).last_delivery_status == "failed"
    finally:
        with_store.close()
    report = runner.doctor()
    assert "last_delivery_failed" in codes(report)
    assert "private" not in json.dumps(report)

    async def succeed(_text):
        return True

    orch.channels["ntfy"].send = succeed
    assert await runner.flush_held() == 1
    assert store.get(job.id).last_delivery_status == "ok"
    assert runner.doctor()["ok"] is True


@pytest.mark.asyncio
async def test_missing_explicit_channel_records_delivery_failure(setup):
    store, _scheduler, _orch, runner, job = setup
    store.update(job.id, options={"deliver": ["ntfy"]})
    await runner.fire(job.id)
    assert store.get(job.id).last_delivery_status == "failed"
    assert "last_delivery_failed" in codes(runner.doctor())


def test_existing_database_migrates_without_losing_job_state(setup):
    store, _scheduler, _orch, _runner, job = setup
    store.update(job.id, notepad="existing notes", last_status="ok")
    store._conn.execute("ALTER TABLE jobs DROP COLUMN last_delivery_status")
    store._conn.commit()
    reopened = JobStore(store._path)
    try:
        migrated = reopened.get(job.id)
        assert migrated.notepad == "existing notes" and migrated.last_status == "ok"
        assert migrated.last_delivery_status is None
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_real_scheduler_registration_and_pause_are_observed(tmp_path):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="UTC")
    store = JobStore(tmp_path / "real-scheduler.db")
    runner = JobRunner(store, orch=SimpleNamespace(channels={}),
                       scheduler=lambda: scheduler, quiet=lambda: False)
    scheduler.start()
    try:
        runner.create(name="hourly", schedule_text="0 * * * *",
                      action={"type": "remind", "message": "never sent"},
                      options={"deliver": []})
        assert runner.doctor()["ok"] is True
        scheduler.pause()
        assert "scheduler_not_running" in codes(runner.doctor())
        scheduler.resume()
        assert runner.doctor()["ok"] is True
    finally:
        scheduler.shutdown(wait=False)
        store.close()


@pytest.mark.parametrize("owner", [True, False])
def test_persisted_scheduler_misfire_is_reported(setup, owner):
    store, scheduler, _orch, runner, job = setup
    scheduled_id = f"job-{job.id}" if owner else "native-backup"
    if not owner:
        scheduler.jobs.append(SimpleNamespace(id=scheduled_id, next_run_time=NOW + timedelta(hours=1)))
    store.record_scheduler_result(scheduled_id, "missed")
    assert "last_run_missed" in codes(runner.doctor())
    store.record_scheduler_result(scheduled_id, "ok")
    assert runner.doctor()["ok"] is True
