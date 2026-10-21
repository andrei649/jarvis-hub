"""H288 — the plain cron lane is bounded like Hermes' HERMES_CRON_TIMEOUT.

* a hung channel send cannot hold a job's gate: every send is bounded and a timeout is a
  failed delivery;
* the whole run (ask / brief / remind) is bounded by ``jobs.run_timeout_seconds``; an
  overrun is an ordinary failed run, so the three-strike pause and the incident still apply;
* the queued-task executor ships a finite wall-clock budget (``autonomy.task_max_seconds``);
* jobs.db waits for a busy writer like the task queue does (HERMES_CRON_SESSION_DB_TIMEOUT).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core import estop, settings_db
from agents.core.autonomy import jobs as jobs_module
from agents.core.autonomy.jobs import MAX_FAILURES, JobRunner, JobStore

REMIND = {"type": "remind", "message": "stand up"}


class _Scheduler:
    def __init__(self):
        self.running = True
        self.jobs: dict[str, dict] = {}

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = {"func": func, "trigger": trigger, **kwargs}

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)

    def get_jobs(self):
        return [SimpleNamespace(id=job_id) for job_id in self.jobs]


class _HungTelegram:
    def __init__(self):
        self.calls = 0

    async def send(self, text, chat_id=None, **kwargs):
        self.calls += 1
        await asyncio.Event().wait()   # never returns


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def no_estop(monkeypatch):
    monkeypatch.setattr(estop, "check_paused", lambda component, logger: False)


def _runner(store, telegram, settings):
    settings.setdefault("autonomy.owner_chat_id", "777")
    orch = SimpleNamespace(channels={"telegram": telegram},
                           get_setting=lambda key, default=None: settings.get(key, default))
    scheduler = _Scheduler()
    runner = JobRunner(store, orch=orch, scheduler=lambda: scheduler, now=lambda: 1000.0,
                       quiet=lambda: False)
    return runner, scheduler


# -- 1. the cron run wall clock -------------------------------------------------------


def test_run_timeout_setting_is_seeded_and_validated():
    seeded = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    row = seeded[("jobs", "run_timeout_seconds")]
    assert row["value"] == jobs_module.DEFAULT_RUN_TIMEOUT_SECONDS == 900
    assert row["kind"] == "number"
    assert settings_db.validate_category("jobs", {"run_timeout_seconds": 0})
    assert settings_db.validate_category("jobs", {"run_timeout_seconds": 86401})
    assert settings_db.validate_category("jobs", {"run_timeout_seconds": 1.5})
    assert settings_db.validate_category("jobs", {"run_timeout_seconds": True})
    assert not settings_db.validate_category("jobs", {"run_timeout_seconds": 60})


def test_runner_reads_the_run_timeout_and_falls_back_on_bad_values(store):
    settings: dict = {}
    runner, _ = _runner(store, _HungTelegram(), settings)
    assert runner.run_timeout_seconds() == 900
    settings["jobs.run_timeout_seconds"] = 42
    assert runner.run_timeout_seconds() == 42
    for bad in (0, -5, "soon", 1.5, True, 10**9):
        settings["jobs.run_timeout_seconds"] = bad
        assert runner.run_timeout_seconds() == 900


@pytest.mark.asyncio
async def test_a_hung_send_is_a_failed_delivery_not_a_held_gate(store, no_estop, monkeypatch):
    monkeypatch.setattr(jobs_module, "SEND_TIMEOUT_SECONDS", 0.05)
    telegram = _HungTelegram()
    runner, _ = _runner(store, telegram, {})
    job = runner.create(name="stand up", schedule_text="every day at 9", action=REMIND)

    run = await asyncio.wait_for(runner.fire(job.id), 5)
    assert telegram.calls == 1
    assert run.status == "failed"
    assert "timed out" in (run.error or "")
    assert store.get(job.id).last_delivery_status == "failed"
    assert store.get(job.id).consecutive_failures == 1


@pytest.mark.asyncio
async def test_an_overrunning_run_fails_and_pauses_after_three_strikes(store, no_estop, monkeypatch):
    settings = {"jobs.run_timeout_seconds": 1}
    runner, scheduler = _runner(store, _HungTelegram(), settings)
    job = runner.create(name="brief", schedule_text="every day at 9",
                        action={"type": "brief", "kind": "morning"})

    async def slow_brief(kind):
        await asyncio.sleep(30)
        return "never"

    monkeypatch.setattr(runner, "_brief", slow_brief)
    incidents = []
    monkeypatch.setattr(runner, "_incident", lambda j, e, n: incidents.append((j.id, e, n)))

    for strike in range(1, MAX_FAILURES + 1):
        run = await asyncio.wait_for(runner.fire(job.id, force=True), 5)
        assert run.status == "failed"
        assert run.error and "JobRunTimeout" in run.error
        assert "jobs.run_timeout_seconds" in run.error
        assert store.get(job.id).consecutive_failures == strike

    assert len(incidents) == 1 and incidents[0][2] == MAX_FAILURES
    assert job.id not in scheduler.jobs                     # paused, unregistered
    assert store.get(job.id).paused_reason


@pytest.mark.asyncio
async def test_an_inner_timeout_is_not_mislabelled_as_the_run_deadline(store, no_estop, monkeypatch):
    runner, _ = _runner(store, _HungTelegram(), {"jobs.run_timeout_seconds": 60})
    job = runner.create(name="brief", schedule_text="every day at 9",
                        action={"type": "brief", "kind": "morning"})

    async def inner_timeout(kind):
        raise TimeoutError("model provider timed out")

    monkeypatch.setattr(runner, "_brief", inner_timeout)
    run = await runner.fire(job.id, force=True)
    assert run.status == "failed"
    assert "JobRunTimeout" not in (run.error or "")
    assert "model provider timed out" in (run.error or "")


@pytest.mark.asyncio
async def test_a_run_within_its_deadline_is_untouched(store, no_estop):
    class _Ok:
        def __init__(self):
            self.sent = []

        async def send(self, text, chat_id=None, **kwargs):
            self.sent.append((text, chat_id))
            return True

    telegram = _Ok()
    runner, _ = _runner(store, telegram, {"jobs.run_timeout_seconds": 5})
    job = runner.create(name="stand up", schedule_text="every day at 9", action=REMIND)
    run = await runner.fire(job.id)
    assert run.status == "ok" and telegram.sent == [("stand up", 777)]


# -- 2. queued in-process tasks ship a finite budget ----------------------------------


def test_task_max_seconds_setting_is_seeded_finite_and_validated():
    from agents.core.autonomy.executor import DEFAULT_TASK_MAX_SECONDS

    seeded = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    row = seeded[("autonomy", "task_max_seconds")]
    assert row["value"] == DEFAULT_TASK_MAX_SECONDS
    assert 0 < DEFAULT_TASK_MAX_SECONDS < 3600          # below the stuck-running reaper TTL
    assert settings_db.validate_category("autonomy", {"task_max_seconds": 0})
    assert settings_db.validate_category("autonomy", {"task_max_seconds": 86401})
    assert settings_db.validate_category("autonomy", {"task_max_seconds": "x"})
    assert not settings_db.validate_category("autonomy", {"task_max_seconds": 600})


def test_resolve_task_budget_is_finite_by_default(monkeypatch):
    from agents.core.autonomy.executor import DEFAULT_TASK_MAX_SECONDS, resolve_task_budget

    monkeypatch.delenv("JARVIS_TASK_MAX_SECONDS", raising=False)
    assert resolve_task_budget(lambda key, default=None: default) == float(DEFAULT_TASK_MAX_SECONDS)
    assert resolve_task_budget(None) == float(DEFAULT_TASK_MAX_SECONDS)
    assert resolve_task_budget(lambda key, default=None: 120) == 120.0
    for bad in (0, -1, "x", True, 10**9, None):
        assert resolve_task_budget(lambda key, default=None, v=bad: v) == float(DEFAULT_TASK_MAX_SECONDS)
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "30")        # explicit env still wins
    assert resolve_task_budget(lambda key, default=None: 120) == 30.0
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "0")         # 0 is not "unbounded" any more
    assert resolve_task_budget(lambda key, default=None: 120) == 120.0


def test_built_executor_has_a_finite_budget_out_of_the_box(monkeypatch):
    from agents.core.autonomy.executor import DEFAULT_TASK_MAX_SECONDS
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    monkeypatch.delenv("JARVIS_TASK_MAX_SECONDS", raising=False)
    orch = SimpleNamespace(
        get_setting=lambda key, default=None: default,
        autonomy=SimpleNamespace(execution_allowed=None),
        plugins={},
    )
    coordinator = AutonomyCoordinator.__new__(AutonomyCoordinator)
    coordinator._orch = orch
    captured = {}

    class _Stop(Exception):
        pass

    def fake_executor(**kwargs):
        captured.update(kwargs)
        raise _Stop

    monkeypatch.setattr("agents.core.autonomy_coordinator.TaskExecutor", fake_executor)
    with pytest.raises(_Stop):
        coordinator.build_executor()
    assert captured["max_wall_seconds"] == float(DEFAULT_TASK_MAX_SECONDS)


# -- 3. jobs.db busy timeout ----------------------------------------------------------


def test_jobs_db_waits_for_a_busy_writer(store):
    assert store._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
