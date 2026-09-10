"""Editing a job an owner already armed — the gap H146 and H449 both named.

The store could already change fields (``update``), the runner could already register a
trigger, and the routes could already create, pause, resume, run and delete. What nothing
could do was change what an existing job *is*. Hermes' cron page has `edit`; ours had a
delete-and-retype.

The trap this pins is the one that makes a naive edit worse than none: ``update`` writes
``schedule_text`` without touching ``cron``, and the scheduler fires on ``cron``. Route the
owner's edit through it and the HUD, the CLI and ``GET /api/jobs`` all report the new
schedule while the job keeps firing on the old one — a lie the owner cannot see. So the
cron is re-derived, and the trigger is rebuilt, and both are asserted here.
"""

from __future__ import annotations

import pytest

from agents.core.autonomy.jobs import MAX_NAME, JobRunner, JobStore


@pytest.fixture()
def store(tmp_path):
    made = JobStore(tmp_path / "jobs.db")
    yield made
    made.close()


@pytest.fixture()
def job(store):
    return store.create(
        name="stand up",
        schedule_text="every weekday at 7",
        action={"type": "remind", "message": "stand up"},
    )


class _Scheduler:
    """Enough APScheduler to see what the runner armed."""

    running = True

    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def add_job(self, _fn, _trigger, *, id, replace_existing=False, args=None, **kwargs):
        self.jobs[id] = dict(kwargs)

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        del self.jobs[job_id]

    def get_jobs(self):
        return [type("J", (), {"id": key})() for key in self.jobs]


@pytest.fixture()
def runner(store):
    sched = _Scheduler()
    made = JobRunner(store, orch=None, scheduler=lambda: sched, quiet=lambda: False)
    made.scheduler = sched  # test handle
    return made


# ── the store ────────────────────────────────────────────────────────────────

def test_a_new_schedule_rewrites_the_cron_it_will_actually_fire_on(store, job):
    """The whole point. A stale cron behind a fresh schedule_text is invisible to the owner."""
    assert job.cron == "0 7 * * 1-5"
    edited = store.edit(job.id, schedule_text="every day at 9")
    assert edited.schedule_text == "every day at 9"
    assert edited.cron != job.cron
    assert edited.cron == "0 9 * * *"
    assert store.get(job.id).cron == edited.cron, "and it is what was persisted"


def test_an_edit_validates_the_action_exactly_as_creation_does(store, job):
    with pytest.raises(ValueError):
        store.edit(job.id, action={"type": "remind"})  # a reminder with no message
    with pytest.raises(ValueError):
        store.edit(job.id, action={"type": "not-a-type", "message": "x"})
    assert store.get(job.id).action == {"type": "remind", "message": "stand up"}


def test_a_name_is_trimmed_and_bounded_like_a_created_one(store, job):
    assert store.edit(job.id, name="  spaced   out  ").name == "spaced out"
    with pytest.raises(ValueError):
        store.edit(job.id, name="   ")
    with pytest.raises(ValueError):
        store.edit(job.id, name="x" * (MAX_NAME + 1))


def test_an_unparseable_schedule_is_refused_and_changes_nothing(store, job):
    with pytest.raises(ValueError):
        store.edit(job.id, schedule_text="whenever I feel like it, roughly")
    after = store.get(job.id)
    assert after.cron == job.cron and after.schedule_text == job.schedule_text


def test_omitted_fields_keep_their_value(store, job):
    edited = store.edit(job.id, name="stretch")
    assert edited.name == "stretch"
    assert edited.schedule_text == job.schedule_text and edited.cron == job.cron
    assert edited.action == job.action


def test_an_empty_edit_is_refused_rather_than_a_silent_no_op(store, job):
    with pytest.raises(ValueError):
        store.edit(job.id)


def test_editing_a_job_that_does_not_exist_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.edit("nope", name="x")


def test_an_edit_never_resumes_a_paused_job_or_forgives_its_failures(store, job):
    store.update(job.id, consecutive_failures=2)
    store.pause(job.id, "3 consecutive failures")
    edited = store.edit(job.id, name="renamed while paused")
    assert edited.paused_reason == "3 consecutive failures"
    assert edited.consecutive_failures == 2
    assert not edited.runnable


def test_an_edit_stamps_updated_at_but_keeps_created_at(store, job):
    edited = store.edit(job.id, name="stretch")
    assert edited.created_at == job.created_at
    assert edited.updated_at >= job.updated_at


# ── the runner re-arms the scheduler ─────────────────────────────────────────

def test_rescheduling_rebuilds_the_trigger_so_the_old_times_stop_firing(runner, job):
    runner.register(job)
    assert runner.scheduler.jobs[f"job-{job.id}"]["hour"] == "7"
    runner.edit(job.id, schedule_text="every day at 9")
    assert runner.scheduler.jobs[f"job-{job.id}"]["hour"] == "9"


def test_editing_a_paused_job_leaves_no_trigger_armed_for_it(runner, store, job):
    runner.register(job)
    store.pause(job.id, "owner paused it")
    runner.edit(job.id, schedule_text="every day at 9")
    assert f"job-{job.id}" not in runner.scheduler.jobs, (
        "a stale trigger on a paused job would resume it by accident"
    )


def test_a_refused_edit_leaves_the_armed_trigger_untouched(runner, job):
    runner.register(job)
    with pytest.raises(ValueError):
        runner.edit(job.id, schedule_text="not a schedule at all, sorry")
    assert runner.scheduler.jobs[f"job-{job.id}"]["hour"] == "7"
