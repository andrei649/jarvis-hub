"""Owner-scheduled jobs (Hermes absorption, wave 2).

Nerva parsed "every weekday at 7" into cron and threw the result away. Now the owner can
arm a job — a reminder, a scheduled question to one agent with a notepad between runs, the
brief on their own time, or a governed task that still crosses the autonomy queue — and
every attempt is recorded; three failures pause the job and raise one incident; the kill
switch pauses every job; frequency and size are bounded.

Hermetic: a temp SQLite store, a fake scheduler, a fake orchestrator, the e-stop module
monkeypatched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import estop
from agents.core.autonomy import jobs as jobs_module
from agents.core.autonomy.jobs import (
    BLUEPRINTS,
    MAX_FAILURES,
    MAX_JOBS,
    MAX_RUNS_KEPT,
    JobRunner,
    JobStore,
    blueprint_catalog,
    cron_kwargs,
    fires_per_day,
    instantiate_blueprint,
    resolve_schedule,
    validate_action,
)

REMIND = {"type": "remind", "message": "stand up"}


# ── schedules ────────────────────────────────────────────────────────────────


def test_plain_words_and_raw_cron_both_resolve():
    assert resolve_schedule("every weekday at 7") == ("0 7 * * 1-5", "weekdays at 07:00")
    assert resolve_schedule("0 7 * * 1-5") == ("0 7 * * 1-5", "cron 0 7 * * 1-5")
    assert resolve_schedule("every 2 hours")[0] == "0 */2 * * *"


@pytest.mark.parametrize(
    "text,fragment",
    [("", "say when"), ("sometime", "could not find a time"), ("every minute", "five minutes"),
     ("* * * * *", "five minutes"), ("*/2 * * * *", "five minutes"), ("x y z w v", "invalid cron")],
)
def test_bad_or_too_frequent_schedules_are_refused_with_a_reason(text, fragment):
    with pytest.raises(ValueError) as info:
        resolve_schedule(text)
    assert fragment in str(info.value)


def test_fires_per_day_and_the_floor():
    assert fires_per_day("0 7 * * *") == 1
    assert fires_per_day("*/5 * * * *") == 288
    assert fires_per_day("0,30 9-17 * * 1-5") == 18
    assert resolve_schedule("*/5 * * * *")[0] == "*/5 * * * *"


def test_cron_day_of_week_is_translated_to_apscheduler_names():
    """cron counts Sunday as 0; APScheduler counts Monday as 0. Passing the field through
    (as the heartbeat scheduler does) shifts every weekday job by one day."""
    assert cron_kwargs("0 7 * * 1-5")["day_of_week"] == "mon-fri"
    assert cron_kwargs("0 9 * * 0,6")["day_of_week"] == "sun,sat"
    assert cron_kwargs("0 9 * * 7")["day_of_week"] == "sun"
    assert cron_kwargs("30 6 * * *") == {"minute": "30", "hour": "6", "day": "*", "month": "*", "day_of_week": "*"}


# ── actions and blueprints ───────────────────────────────────────────────────


def test_actions_are_validated_by_type_with_named_reasons():
    assert validate_action(REMIND) == []
    assert validate_action({"type": "ask", "prompt": "p", "agent": "friday", "deliver": False}) == []
    assert validate_action({"type": "brief", "kind": "evening"}) == []
    assert validate_action({"type": "task", "kind": "writeback.notion", "title": "t", "payload": {}, "risk_tier": 2}) == []
    assert "action.type" in validate_action({"type": "nuke"})[0]
    assert "action.message is required" in validate_action({"type": "remind"})
    assert any("unknown action key" in e for e in validate_action({"type": "remind", "message": "m", "shell": "rm"}))
    assert "action.kind must be morning or evening" in validate_action({"type": "brief", "kind": "noon"})
    assert "action.risk_tier must be 0-3" in validate_action({"type": "task", "kind": "k", "title": "t", "risk_tier": 9})
    assert any("longer than" in e for e in validate_action({"type": "remind", "message": "x" * 5000}))
    assert validate_action("remind") == ["action must be an object"]


def test_blueprints_instantiate_with_the_owners_parameters():
    name, when, action = instantiate_blueprint("reminder", {"message": "water", "schedule_text": "every day at 10"})
    assert (name, when, action) == ("Reminder", "every day at 10", {"type": "remind", "message": "water"})
    name, when, action = instantiate_blueprint("inbox_watch")
    assert when == "every 2 hours" and action["agent"] == "friday" and action["type"] == "ask"
    with pytest.raises(ValueError):
        instantiate_blueprint("reminder")  # needs a message
    with pytest.raises(ValueError):
        instantiate_blueprint("reminder", {"message": "m", "shell": "x"})
    with pytest.raises(ValueError):
        instantiate_blueprint("nope")
    assert {b["id"] for b in blueprint_catalog()} == set(BLUEPRINTS)


# ── the store ────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


def test_store_round_trips_and_bounds(store):
    job = store.create(name="  Stand   up ", schedule_text="every weekday at 9", action=REMIND, blueprint="reminder")
    assert job.name == "Stand up" and job.cron == "0 9 * * 1-5" and job.runnable and job.blueprint == "reminder"
    assert store.get(job.id) == job and [j.id for j in store.list()] == [job.id]

    paused = store.pause(job.id, "owner said so")
    assert not paused.runnable and paused.paused_reason == "owner said so"
    resumed = store.resume(job.id)
    assert resumed.runnable and resumed.consecutive_failures == 0

    updated = store.update(job.id, notepad="n" * 10_000, last_summary="s" * 5_000)
    assert len(updated.notepad) == 4_096 and len(updated.last_summary) == 2_000
    with pytest.raises(ValueError):
        store.update(job.id, shell="rm")
    with pytest.raises(KeyError):
        store.update("nope", name="x")

    assert store.delete(job.id) is True and store.get(job.id) is None and store.delete(job.id) is False
    with pytest.raises(ValueError):
        store.create(name="", schedule_text="every day at 9", action=REMIND)
    with pytest.raises(ValueError):
        store.create(name="x" * 81, schedule_text="every day at 9", action=REMIND)
    with pytest.raises(ValueError):
        store.create(name="bad", schedule_text="every day at 9", action={"type": "remind"})


def test_store_caps_jobs_and_runs(store):
    for i in range(MAX_JOBS):
        store.create(name=f"job {i}", schedule_text="every day at 9", action=REMIND)
    with pytest.raises(ValueError):
        store.create(name="one too many", schedule_text="every day at 9", action=REMIND)
    job = store.list()[0]
    for i in range(MAX_RUNS_KEPT + 25):
        store.record_run(job.id, started_at="t", finished_at="t", status="ok", summary=str(i))
    runs = store.runs(job.id, limit=1000)
    assert len(runs) == MAX_RUNS_KEPT and runs[0].summary == str(MAX_RUNS_KEPT + 24)


# ── the runner ───────────────────────────────────────────────────────────────


class _Scheduler:
    def __init__(self):
        self.running = True
        self.jobs: dict[str, dict] = {}

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = {"func": func, "trigger": trigger, **kwargs}

    def remove_job(self, job_id):
        del self.jobs[job_id]

    def get_jobs(self):
        return [SimpleNamespace(id=job_id) for job_id in self.jobs]


class _Telegram:
    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    async def send(self, text, chat_id=None, **kwargs):
        self.sent.append((text, chat_id))
        return self.ok


def _orch(*, owner_chat="777", telegram=None, reply="the sky is clear"):
    enqueued = []

    async def process(prompt, agent="jarvis", channel="internal"):
        process.calls.append((prompt, agent, channel))
        return reply

    process.calls = []

    def enqueue(**kwargs):
        enqueued.append(kwargs)
        return 41 + len(enqueued)

    return SimpleNamespace(
        channels={"telegram": telegram} if telegram is not None else {},
        get_setting=lambda key, default=None: owner_chat if key == "autonomy.owner_chat_id" else default,
        process=process,
        autonomy_queue=SimpleNamespace(enqueue=enqueue, enqueued=enqueued),
    )


@pytest.fixture
def no_estop(monkeypatch):
    monkeypatch.setattr(estop, "check_paused", lambda component, logger: False)


def _runner(store, orch, scheduler=None):
    scheduler = scheduler or _Scheduler()
    return JobRunner(store, orch=orch, scheduler=lambda: scheduler, now=lambda: 1000.0), scheduler


@pytest.mark.asyncio
async def test_a_reminder_is_delivered_and_recorded(store, no_estop):
    telegram = _Telegram()
    runner, scheduler = _runner(store, _orch(telegram=telegram))

    job = runner.create(name="stand up", schedule_text="every weekday at 9", action=REMIND)
    assert scheduler.jobs[f"job-{job.id}"]["day_of_week"] == "mon-fri"
    run = await runner.fire(job.id)

    assert run.status == "ok" and run.summary == "reminder delivered to telegram"
    assert telegram.sent == [("stand up", 777)]
    after = store.get(job.id)
    assert after.last_status == "ok" and after.consecutive_failures == 0 and after.last_run_at
    assert [r.status for r in store.runs(job.id)] == ["ok"]
    assert runner.snapshot() == {"alive": True, "registered": [job.id], "jobs": 1, "runnable": 1, "paused": 0}


@pytest.mark.asyncio
async def test_an_ask_job_keeps_a_notepad_between_runs(store, no_estop):
    telegram = _Telegram()
    orch = _orch(telegram=telegram, reply="Two mails need you: A and B.")
    runner, _ = _runner(store, orch)
    job = runner.create(name="inbox", schedule_text="every 2 hours", action={"type": "ask", "prompt": "check inbox", "agent": "friday"})

    first = await runner.fire(job.id)
    assert first.status == "ok" and "delivered to telegram" in first.summary
    assert orch.process.calls[0][0] == "check inbox" and orch.process.calls[0][1] == "friday"
    assert store.get(job.id).notepad == "Two mails need you: A and B."

    await runner.fire(job.id)
    second_prompt = orch.process.calls[1][0]
    assert second_prompt.startswith("check inbox") and "Two mails need you: A and B." in second_prompt
    assert "compare, then report what changed" in second_prompt
    assert telegram.sent and telegram.sent[-1][0] == "Two mails need you: A and B."


@pytest.mark.asyncio
async def test_an_ask_job_can_keep_its_answer_to_itself(store, no_estop):
    telegram = _Telegram()
    runner, _ = _runner(store, _orch(telegram=telegram, reply="noted"))
    job = runner.create(name="quiet", schedule_text="every day at 9", action={"type": "ask", "prompt": "p", "deliver": False})
    run = await runner.fire(job.id)
    assert run.status == "ok" and run.summary == "noted" and telegram.sent == []


@pytest.mark.asyncio
async def test_a_brief_job_uses_the_digest_builders(store, no_estop, monkeypatch):
    telegram = _Telegram()
    orch = _orch(telegram=telegram)
    import agents.core.autonomy.digest as digest

    monkeypatch.setattr(digest, "build_evening_retro", lambda queue: "retro text")
    runner, _ = _runner(store, orch)
    job = runner.create(name="retro", schedule_text="every day at 21", action={"type": "brief", "kind": "evening"})
    run = await runner.fire(job.id)
    assert run.status == "ok" and run.summary == "evening brief delivered to telegram"
    assert telegram.sent == [("retro text", 777)]


@pytest.mark.asyncio
async def test_a_task_job_goes_through_the_governed_queue_never_around_it(store, no_estop):
    orch = _orch()
    runner, _ = _runner(store, orch)
    job = runner.create(
        name="nightly note",
        schedule_text="every day at 23",
        action={"type": "task", "kind": "writeback.notion.page", "title": "nightly note", "payload": {"target": "log"}, "risk_tier": 2},
    )
    run = await runner.fire(job.id)
    assert run.status == "ok" and run.summary == "queued task #42 for the autonomy policy to decide"
    (call,) = orch.autonomy_queue.enqueued
    assert call["kind"] == "writeback.notion.page" and call["risk_tier"] == 2 and call["origin"] == f"job:{job.id}"


@pytest.mark.asyncio
async def test_the_emergency_stop_pauses_every_job(store, monkeypatch):
    monkeypatch.setattr(estop, "check_paused", lambda component, logger: True)
    telegram = _Telegram()
    runner, _ = _runner(store, _orch(telegram=telegram))
    job = runner.create(name="stand up", schedule_text="every day at 9", action=REMIND)
    run = await runner.fire(job.id)
    assert run.status == "skipped" and "emergency stop" in run.summary and telegram.sent == []


@pytest.mark.asyncio
async def test_a_paused_job_is_skipped_unless_forced(store, no_estop):
    telegram = _Telegram()
    runner, scheduler = _runner(store, _orch(telegram=telegram))
    job = runner.create(name="stand up", schedule_text="every day at 9", action=REMIND)
    runner.pause(job.id, "holiday")
    assert f"job-{job.id}" not in scheduler.jobs
    assert (await runner.fire(job.id)).status == "skipped"
    assert (await runner.fire(job.id, force=True)).status == "ok"
    runner.resume(job.id)
    assert f"job-{job.id}" in scheduler.jobs


@pytest.mark.asyncio
async def test_three_failures_pause_the_job_and_raise_one_incident(store, no_estop, monkeypatch):
    incidents = []
    import agents.core.autonomy.error_logger as error_logger

    monkeypatch.setattr(error_logger, "persist_problem", lambda log: incidents.append(log))
    runner, scheduler = _runner(store, _orch(owner_chat="", telegram=_Telegram()))  # no owner chat → cannot deliver
    job = runner.create(name="stand up", schedule_text="every day at 9", action=REMIND)

    runs = [await runner.fire(job.id) for _ in range(MAX_FAILURES)]

    assert [r.status for r in runs] == ["failed"] * MAX_FAILURES
    assert "owner chat" in runs[0].error
    after = store.get(job.id)
    assert after.consecutive_failures == MAX_FAILURES and after.paused_reason.startswith("3 consecutive failures")
    assert f"job-{job.id}" not in scheduler.jobs
    assert len(incidents) == 1 and incidents[0].code == "E_JOB_PAUSED" and incidents[0].component == f"job:{job.id}"
    # A fourth firing is skipped, not attempted.
    assert (await runner.fire(job.id)).status == "skipped"
    # Resume clears the counter and puts it back on the scheduler.
    runner.resume(job.id)
    assert store.get(job.id).consecutive_failures == 0 and f"job-{job.id}" in scheduler.jobs


@pytest.mark.asyncio
async def test_a_success_resets_the_failure_count(store, no_estop):
    telegram = _Telegram(ok=False)
    orch = _orch(telegram=telegram)
    runner, _ = _runner(store, orch)
    job = runner.create(name="stand up", schedule_text="every day at 9", action=REMIND)
    assert (await runner.fire(job.id)).status == "failed"
    telegram.ok = True
    assert (await runner.fire(job.id)).status == "ok"
    assert store.get(job.id).consecutive_failures == 0


@pytest.mark.asyncio
async def test_an_empty_model_answer_is_a_failure_not_a_blank_message(store, no_estop):
    telegram = _Telegram()
    runner, _ = _runner(store, _orch(telegram=telegram, reply=""))
    job = runner.create(name="ask", schedule_text="every day at 9", action={"type": "ask", "prompt": "p"})
    run = await runner.fire(job.id)
    assert run.status == "failed" and "no answer" in run.error and telegram.sent == []


def test_register_all_puts_only_runnable_jobs_on_the_scheduler(store):
    scheduler = _Scheduler()
    runner, _ = _runner(store, _orch(), scheduler)
    a = store.create(name="a", schedule_text="every day at 9", action=REMIND)
    b = store.create(name="b", schedule_text="every day at 10", action=REMIND)
    store.pause(b.id, "x")
    assert runner.register_all() == 1 and list(scheduler.jobs) == [f"job-{a.id}"]
    assert runner.delete(a.id) is True and scheduler.jobs == {}
    assert runner.snapshot()["alive"] is True


def test_without_a_scheduler_nothing_registers_and_nothing_breaks(store):
    runner = JobRunner(store, orch=_orch(), scheduler=lambda: None)
    job = runner.create(name="a", schedule_text="every day at 9", action=REMIND)
    assert runner.register_all() == 0 and runner.snapshot()["alive"] is False
    runner.unregister(job.id)  # no scheduler → no-op
    assert jobs_module.MAX_FIRES_PER_DAY == 288
