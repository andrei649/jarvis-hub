"""H459 — slots the hub was down for are caught up once at boot, within a grace window
that scales with the job's cadence; older slots are recorded as missed, never replayed
in a burst, and a slot is never run twice."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agents.core.autonomy.jobs import (
    CATCH_UP_GRACE_MAX_S,
    CATCH_UP_GRACE_MIN_S,
    JobRunner,
    JobStore,
    catch_up_grace,
)

DAY0 = datetime(2026, 11, 10, tzinfo=UTC)


@pytest.fixture
def env(tmp_path, monkeypatch):
    from agents.core import settings_db

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    settings_db.init_db(force=True)
    store = JobStore(tmp_path / "jobs.db")
    prompts = []

    async def detailed(prompt, **kwargs):
        prompts.append(prompt)
        return "done", None

    runner = JobRunner(store, orch=SimpleNamespace(process_detailed=detailed), scheduler=lambda: None,
                       quiet=lambda: False)
    runner._pinned_timezone = ZoneInfo("UTC")
    yield store, runner, prompts
    store.close()


def _job(store, cron, *, at, prompt="report"):
    job = store.create(name="j", schedule_text=cron, action={"type": "ask", "prompt": prompt, "deliver": False})
    stamp = at.isoformat()
    with store._lock:
        store._conn.execute("UPDATE jobs SET created_at=?, updated_at=? WHERE id=?", (stamp, stamp, job.id))
        store._conn.commit()
    return store.get(job.id)


def test_grace_scales_with_cadence():
    assert catch_up_grace(None) == CATCH_UP_GRACE_MAX_S
    assert catch_up_grace(3600) == 1800
    assert catch_up_grace(60) == CATCH_UP_GRACE_MIN_S
    assert catch_up_grace(7 * 86400) == CATCH_UP_GRACE_MAX_S


@pytest.mark.asyncio
async def test_a_recent_missed_slot_runs_once(env):
    store, runner, prompts = env
    job = _job(store, "0 9 * * *", at=DAY0 + timedelta(hours=8))
    now = DAY0 + timedelta(hours=10)                     # the 09:00 slot passed while down
    outcomes = runner.fire_overdue_jobs(now=now)
    assert [(o["job_id"], o["action"], o["slot"]) for o in outcomes] == [
        (job.id, "queued", (DAY0 + timedelta(hours=9)).isoformat())]
    assert outcomes[0]["request"]["status"] == "queued"
    await runner.drain_manual()
    assert len(prompts) == 1, store.runs(job.id, limit=3)
    # A second boot (or a second process) does not run the same slot again.
    assert runner.fire_overdue_jobs(now=now) == []
    await runner.drain_manual()
    assert len(prompts) == 1


def test_a_slot_older_than_its_window_is_recorded_as_missed(env):
    store, runner, _prompts = env
    job = _job(store, "0 9 * * *", at=DAY0 + timedelta(hours=8))
    now = DAY0 + timedelta(hours=9 + 7)                  # 7 h late; daily window is 6 h
    outcomes = runner.fire_overdue_jobs(now=now)
    assert [o["action"] for o in outcomes] == ["missed"]
    run = store.runs(job.id, limit=1)[0]
    assert run.status == "skipped" and "missed while the hub was down" in run.summary
    assert store.dispatch.outstanding() == []
    assert runner.fire_overdue_jobs(now=now) == []       # recorded once


def test_only_the_newest_slot_is_owed_never_a_burst(env):
    store, runner, _prompts = env
    _job(store, "0 */2 * * *", at=DAY0)                   # every two hours
    now = DAY0 + timedelta(days=3, minutes=20)            # down three days
    outcomes = runner.fire_overdue_jobs(now=now)
    assert len(outcomes) == 1 and outcomes[0]["action"] == "queued"
    assert outcomes[0]["slot"] == (DAY0 + timedelta(days=3)).isoformat()


@pytest.mark.parametrize("late_minutes, action", [(20, "queued"), (45, "missed")])
def test_hourly_window_is_half_the_cadence(env, late_minutes, action):
    store, runner, _prompts = env
    _job(store, "0 * * * *", at=DAY0)
    outcomes = runner.fire_overdue_jobs(now=DAY0 + timedelta(hours=5, minutes=late_minutes))
    assert [o["action"] for o in outcomes] == [action]


def test_frequent_paused_held_and_already_active_jobs_are_not_caught_up(env, monkeypatch):
    store, runner, _prompts = env
    _job(store, "*/5 * * * *", at=DAY0)                   # next slot is minutes away anyway
    paused = _job(store, "0 9 * * *", at=DAY0)
    store.pause(paused.id, "owner")
    ran = _job(store, "0 9 * * *", at=DAY0)
    stamp = (DAY0 + timedelta(hours=9, minutes=1)).isoformat()
    store.record_run(ran.id, started_at=stamp, finished_at=stamp, status="skipped", summary="emergency stop")
    edited = _job(store, "0 9 * * *", at=DAY0)
    with store._lock:                                     # edited after the slot: nothing owed
        store._conn.execute("UPDATE jobs SET updated_at=? WHERE id=?",
                            ((DAY0 + timedelta(hours=9, minutes=30)).isoformat(), edited.id))
        store._conn.commit()
    now = DAY0 + timedelta(hours=10)
    assert runner.fire_overdue_jobs(now=now) == []
    fresh = _job(store, "0 9 * * *", at=DAY0)
    monkeypatch.setattr(runner, "_held", lambda: True)    # safe mode catches nothing up
    assert runner.fire_overdue_jobs(now=now) == []
    monkeypatch.setattr(runner, "_held", lambda: False)
    assert [o["job_id"] for o in runner.fire_overdue_jobs(now=now)] == [fresh.id]


def _one_shot(store, when, *, created):
    job = _job(store, "0 9 * * *", at=created)
    with store._lock:
        store._conn.execute("UPDATE jobs SET cron=? WHERE id=?", ("@at " + when.isoformat(), job.id))
        store._conn.commit()
    return store.get(job.id)


@pytest.mark.parametrize("late, action", [(timedelta(minutes=2), None), (timedelta(hours=1), "queued"),
                                          (timedelta(hours=7), "missed")])
def test_one_shot_missed_while_down(env, late, action):
    store, runner, _prompts = env
    when = DAY0 + timedelta(hours=9)
    job = _one_shot(store, when, created=DAY0)
    outcomes = runner.fire_overdue_jobs(now=when + late)
    # Inside the scheduler's own misfire window the in-process trigger still runs it.
    assert [o["action"] for o in outcomes] == ([] if action is None else [action])
    if action:
        assert outcomes[0]["job_id"] == job.id


@pytest.mark.asyncio
async def test_a_catch_up_obeys_pause_and_the_guards_when_it_drains(env):
    store, runner, prompts = env
    job = _job(store, "0 9 * * *", at=DAY0)
    runner.fire_overdue_jobs(now=DAY0 + timedelta(hours=10))
    store.pause(job.id, "owner paused before the drain")
    await runner.drain_manual()
    assert prompts == []
    assert store.runs(job.id, limit=1)[0].summary.startswith("paused")


def test_register_all_catches_up_and_a_failure_never_blocks_scheduling(env, monkeypatch):
    store, runner, _prompts = env
    added = []

    class Sched:
        running = True

        def add_job(self, func, trigger, **kwargs):
            added.append(kwargs.get("id"))

        def get_jobs(self):
            return []

    runner._scheduler = lambda: Sched()
    _job(store, "0 9 * * *", at=DAY0)
    called = []
    monkeypatch.setattr(runner, "fire_overdue_jobs", lambda now=None: called.append(1) or [])
    assert runner.register_all() == 1 and called == [1]

    def broken(now=None):
        raise RuntimeError("clock unreadable")

    monkeypatch.setattr(runner, "fire_overdue_jobs", broken)
    assert runner.register_all() == 1
