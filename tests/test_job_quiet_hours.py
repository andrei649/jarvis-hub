"""Hermes absorption 4e — a job does not wake the owner.

A job's message that would land in the owner's night is held and delivered by a periodic
flush once quiet hours end. An `urgent` action may still go, but it spends the same daily
interrupt budget every other night-time push spends — and waits when there is none left.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import estop
from agents.core.autonomy.jobs import (
    HELD_FLUSH_JOB_ID,
    MAX_HELD_PER_JOB,
    JobRunner,
    JobStore,
    validate_action,
)

REMIND = {"type": "remind", "message": "stand up"}


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


class _Budget:
    def __init__(self, remaining=1):
        self._remaining = remaining
        self.calls = []

    def consume(self, *, delivery_id=None, channel_class="legacy"):
        self.calls.append((delivery_id, channel_class))
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True


def _orch(telegram, *, budget=None, settings=None):
    settings = settings if settings is not None else {}   # shared: a test may change it later
    settings.setdefault("autonomy.owner_chat_id", "777")
    return SimpleNamespace(
        channels={"telegram": telegram},
        get_setting=lambda key, default=None: settings.get(key, default),
        autonomy=SimpleNamespace(budget=budget) if budget is not None else None,
    )


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def no_estop(monkeypatch):
    monkeypatch.setattr(estop, "check_paused", lambda component, logger: False)


def _runner(store, orch, *, quiet):
    state = {"quiet": quiet}
    scheduler = _Scheduler()
    runner = JobRunner(store, orch=orch, scheduler=lambda: scheduler, now=lambda: 1000.0,
                       quiet=lambda: state["quiet"])
    return runner, scheduler, state


def test_urgent_is_validated():
    assert validate_action({**REMIND, "urgent": True}) == []
    assert validate_action({"type": "brief", "kind": "morning", "urgent": False}) == []
    assert "action.urgent must be true or false" in validate_action({**REMIND, "urgent": "yes"})
    assert any("unknown action key" in e for e in validate_action({"type": "task", "kind": "k", "title": "t", "urgent": True}))


@pytest.mark.asyncio
async def test_a_night_time_reminder_is_held_and_delivered_when_the_night_ends(store, no_estop):
    telegram = _Telegram()
    runner, scheduler, state = _runner(store, _orch(telegram), quiet=True)
    job = runner.create(name="stand up", schedule_text="every day at 3", action=REMIND)

    run = await runner.fire(job.id)
    assert run.status == "ok" and run.summary == "reminder held until quiet hours end"
    assert telegram.sent == []
    assert store.held_count() == 1 and store.held()[0].text == "stand up"
    snap = runner.snapshot()
    assert snap["held"] == 1 and snap["quiet_hours"] is True

    assert await runner.flush_held() == 0          # still night: nothing moves
    state["quiet"] = False
    assert await runner.flush_held() == 1
    assert telegram.sent == [("stand up", 777)] and store.held_count() == 0
    runs = store.runs(job.id)
    assert runs[0].status == "ok" and runs[0].summary.startswith("delivered to telegram from hold (held since ")
    assert runner.snapshot()["held"] == 0


@pytest.mark.asyncio
async def test_an_urgent_job_spends_the_interrupt_budget_or_waits(store, no_estop):
    telegram = _Telegram()
    budget = _Budget(remaining=1)
    runner, _scheduler, _state = _runner(store, _orch(telegram, budget=budget), quiet=True)
    job = runner.create(name="pipe", schedule_text="every day at 3", action={**REMIND, "message": "pipe burst", "urgent": True})

    run = await runner.fire(job.id)
    assert run.summary == "reminder delivered to telegram (urgent, during quiet hours)"
    assert telegram.sent == [("pipe burst", 777)]
    assert budget.calls == [(f"job-{job.id}-1000", "job")]

    run = await runner.fire(job.id)                  # the budget is spent: it waits
    assert run.summary == "reminder held until quiet hours end (interrupt budget spent)"
    assert len(telegram.sent) == 1 and store.held_count() == 1


@pytest.mark.asyncio
async def test_urgent_without_any_budget_waits_too(store, no_estop):
    telegram = _Telegram()
    runner, _scheduler, _state = _runner(store, _orch(telegram), quiet=True)
    job = runner.create(name="pipe", schedule_text="every day at 3", action={**REMIND, "urgent": True})
    run = await runner.fire(job.id)
    assert run.summary == "reminder held until quiet hours end (interrupt budget spent)"
    assert telegram.sent == [] and store.held_count() == 1


@pytest.mark.asyncio
async def test_daytime_delivery_is_unchanged_and_costs_no_budget(store, no_estop):
    telegram = _Telegram()
    budget = _Budget(remaining=0)
    runner, _scheduler, _state = _runner(store, _orch(telegram, budget=budget), quiet=False)
    job = runner.create(name="stand up", schedule_text="every day at 9", action={**REMIND, "urgent": True})
    run = await runner.fire(job.id)
    assert run.summary == "reminder delivered to telegram"
    assert telegram.sent == [("stand up", 777)] and budget.calls == []


@pytest.mark.asyncio
async def test_a_refused_flush_keeps_the_rest_in_order(store, no_estop):
    telegram = _Telegram(ok=False)
    runner, _scheduler, state = _runner(store, _orch(telegram), quiet=True)
    job = runner.create(name="a", schedule_text="every day at 3", action=REMIND)
    for message in ("one", "two"):
        store.hold(job.id, message, None)
    state["quiet"] = False
    assert await runner.flush_held() == 0
    assert [h.text for h in store.held()] == ["one", "two"]   # nothing lost, nothing reordered
    telegram.ok = True
    assert await runner.flush_held() == 2
    assert [t for t, _ in telegram.sent] == ["one", "one", "two"][1:] or [t for t, _ in telegram.sent][-2:] == ["one", "two"]
    assert store.held_count() == 0


def test_held_messages_are_bounded_per_job(store):
    job = store.create(name="a", schedule_text="every day at 3", action=REMIND)
    for i in range(MAX_HELD_PER_JOB + 5):
        store.hold(job.id, f"m{i}", None)
    held = store.held(limit=1000)
    assert len(held) == MAX_HELD_PER_JOB and held[0].text == "m5" and held[-1].text == f"m{MAX_HELD_PER_JOB + 4}"
    assert held[0].as_dict()["chars"] == 2 and store.release(held[0].id) is True
    assert store.release(held[0].id) is False


def test_the_flush_is_registered_beside_the_jobs(store):
    runner, scheduler, _state = _runner(store, _orch(_Telegram()), quiet=False)
    store.create(name="a", schedule_text="every day at 9", action=REMIND)
    assert runner.register_all() == 1
    flush = scheduler.jobs[HELD_FLUSH_JOB_ID]
    assert flush["trigger"] == "interval" and flush["minutes"] == 5
    assert runner.registered_ids() == [store.list()[0].id]   # the flush is not a job


def test_quiet_hours_read_the_ambient_window(store, monkeypatch):
    settings = {"ambient.quiet_hours_start": 22, "ambient.quiet_hours_end": 7}
    clock = {"hour": 3}
    monkeypatch.setattr("agents.core.autonomy.jobs.time.localtime", lambda ts=None: SimpleNamespace(tm_hour=clock["hour"]))
    runner = JobRunner(store, orch=_orch(_Telegram(), settings=settings), scheduler=lambda: None, now=lambda: 0.0)
    assert runner.quiet_hours() is True
    clock["hour"] = 12
    assert runner.quiet_hours() is False
    settings["ambient.quiet_hours_start"] = "bad"
    clock["hour"] = 23
    assert runner.quiet_hours() is True                # the default window still applies
    settings["ambient.quiet_hours_start"] = settings["ambient.quiet_hours_end"] = 5
    assert runner.quiet_hours() is False               # an empty window means never
