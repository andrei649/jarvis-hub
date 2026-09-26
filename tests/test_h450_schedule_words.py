"""H450 — say when in plain words: one-shot delays and times, compact intervals, repeat counts.

Hermes accepts four schedule families the job store did not: a one-shot delay (``in 30m``),
an ISO timestamp anchored to the configured zone, compact intervals and bare durations
(``every 2h``, ``30m``), and one repeat normaliser (``forever | once | 1x | N``). Worse, a
one-shot said in words — ``2026-10-01 09:00``, ``tomorrow at 9``, ``once at 9am`` — was
silently armed as a DAILY cron from its hour. Now a one-shot is a date trigger (stored as
``@at <UTC ISO>``) that runs at most once, stays out of H687's first run even when a first
run is asked for, and re-arms only when its time is edited.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agents.core.autonomy import jobs as jobs_mod
from agents.core.autonomy.jobs import (
    JobRunner,
    JobStore,
    fires_per_day,
    first_run_decision,
    first_run_policy,
    is_one_shot,
    normalize_repeat,
    resolve_schedule,
    run_at,
    validate_options,
)
from agents.core.autonomy.nl_schedule import parse_schedule

BUCHAREST = ZoneInfo("Europe/Bucharest")
# Thursday 2026-09-24 10:00 in Bucharest (UTC+3) = 07:00 UTC
NOW = datetime(2026, 9, 24, 7, 0, tzinfo=UTC)


def _at(text, now=NOW, zone=BUCHAREST):
    cron, description = resolve_schedule(text, now=now, zone=zone)
    assert is_one_shot(cron), (text, cron)
    return run_at(cron), description


# ── one-shot delays ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(("text", "delta"), [
    ("in 30m", timedelta(minutes=30)),
    ("in 30 minutes", timedelta(minutes=30)),
    ("in 30 min", timedelta(minutes=30)),
    ("in 2 hours", timedelta(hours=2)),
    ("in 2h", timedelta(hours=2)),
    ("in 1h30m", timedelta(hours=1, minutes=30)),
    ("in 1 hour 15 minutes", timedelta(hours=1, minutes=15)),
    ("in 3 days", timedelta(days=3)),
    ("In 45 Mins", timedelta(minutes=45)),
    ("peste 30 de minute", timedelta(minutes=30)),
    ("peste 2 ore", timedelta(hours=2)),
    ("în 10 minute", timedelta(minutes=10)),
    ("peste o oră", timedelta(hours=1)),
    ("in an hour", timedelta(hours=1)),
    ("peste 2 zile", timedelta(days=2)),
    ("in 1 zi", timedelta(days=1)),
    ("in 2 hours and 5 minutes", timedelta(hours=2, minutes=5)),
])
def test_a_delay_is_one_run_that_long_from_now(text, delta):
    when, description = _at(text)
    assert when == NOW + delta
    assert description.startswith("once at ")


@pytest.mark.parametrize("text", ["in 2 hours at 9", "in 2 hours or 5 minutes", "in 30m please", "peste 2 ore la 9"])
def test_a_delay_with_anything_else_is_refused_not_read_as_a_daily_time(text):
    with pytest.raises(ValueError, match="say the delay alone"):
        resolve_schedule(text, now=NOW, zone=BUCHAREST)
    assert resolve_schedule("în fiecare zi la 9", now=NOW, zone=BUCHAREST)[0] == "0 9 * * *"


def test_a_delay_has_bounds():
    for text in ("in 0m", "in 0 hours", "peste 0 minute"):
        with pytest.raises(ValueError, match="at least one minute"):
            resolve_schedule(text, now=NOW, zone=BUCHAREST)
    with pytest.raises(ValueError, match="within a year"):
        resolve_schedule("in 400 days", now=NOW, zone=BUCHAREST)
    assert _at("in 365 days")[0] == NOW + timedelta(days=365)


# ── one-shot times ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("text", "local"), [
    ("2026-10-01T09:00", datetime(2026, 10, 1, 9, 0)),
    ("2026-10-01 09:00", datetime(2026, 10, 1, 9, 0)),
    ("2026-10-01 09:00:30", datetime(2026, 10, 1, 9, 0, 30)),
    ("on 2026-10-01 at 9am", datetime(2026, 10, 1, 9, 0)),
    ("tomorrow at 9", datetime(2026, 9, 25, 9, 0)),
    ("tomorrow at 7:30pm", datetime(2026, 9, 25, 19, 30)),
    ("at 9am tomorrow", datetime(2026, 9, 25, 9, 0)),
    ("mâine la 9", datetime(2026, 9, 25, 9, 0)),
    ("maine la 18:45", datetime(2026, 9, 25, 18, 45)),
    ("today at 18:00", datetime(2026, 9, 24, 18, 0)),
    ("azi la 18", datetime(2026, 9, 24, 18, 0)),
    ("astăzi la 11", datetime(2026, 9, 24, 11, 0)),
    ("once at 9am", datetime(2026, 9, 25, 9, 0)),       # 09:00 has passed today: tomorrow
    ("once at 11", datetime(2026, 9, 24, 11, 0)),       # still ahead today
    ("o dată la 9", datetime(2026, 9, 25, 9, 0)),
    ("o data la 23:59", datetime(2026, 9, 24, 23, 59)),
])
def test_a_time_said_once_is_one_run_in_the_configured_zone(text, local):
    when, description = _at(text)
    assert when == local.replace(tzinfo=BUCHAREST).astimezone(UTC)
    assert description == f"once at {local:%Y-%m-%d %H:%M} ({BUCHAREST})"


def test_an_explicit_offset_is_kept():
    assert _at("2026-10-01T09:00:00+00:00")[0] == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    assert _at("2026-10-01T06:00Z")[0] == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    assert _at("2026-10-01T09:00+03:00")[0] == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    assert _at("2026-10-01T09:00-03:00")[0] == datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    assert _at("2026-10-01T09:00-0330")[0] == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


def test_the_regression_a_one_shot_is_never_a_daily_cron():
    """'2026-10-01 09:00', 'tomorrow at 9' and 'once at 9am' used to arm '0 9 * * *'."""
    for text in ("2026-10-01 09:00", "tomorrow at 9", "once at 9am", "mâine la 9", "o dată la 9"):
        cron, _ = resolve_schedule(text, now=NOW, zone=BUCHAREST)
        assert cron.startswith("@at "), (text, cron)
        assert fires_per_day(cron) == 1.0


@pytest.mark.parametrize(("text", "error"), [
    ("2026-09-01T09:00", "has already passed"),
    ("today at 9", "has already passed"),
    ("azi la 8", "has already passed"),
    ("2026-10-01", "say the time too"),
    ("2027-12-01T09:00", "within a year"),
    ("2026-02-30T09:00", "not a real date"),
    ("tomorrow", "could not find a time"),
    ("tomorrow at 25:00", "invalid time"),
    ("2026-10-01T09:00:61", "invalid time"),
    ("2026-10-01T24:00", "invalid time"),
])
def test_a_one_shot_that_cannot_run_is_refused(text, error):
    with pytest.raises(ValueError, match=error):
        resolve_schedule(text, now=NOW, zone=BUCHAREST)


def test_the_zone_defaults_to_the_local_one_and_now_to_the_clock():
    cron, _ = resolve_schedule("in 5 minutes")
    assert "." not in cron, "whole seconds"
    delta = run_at(cron) - datetime.now(UTC)
    assert timedelta(minutes=4) < delta <= timedelta(minutes=5)


# ── compact intervals ────────────────────────────────────────────────────────


@pytest.mark.parametrize(("text", "cron"), [
    ("every 2h", "0 */2 * * *"),
    ("every 30m", "*/30 * * * *"),
    ("every 15 mins", "*/15 * * * *"),
    ("2h", "0 */2 * * *"),
    ("30m", "*/30 * * * *"),
    ("every 1h", "0 */1 * * *"),
    ("every 120 minutes", "0 */2 * * *"),
    ("la fiecare 2h", "0 */2 * * *"),
    ("la fiecare 2 ore", "0 */2 * * *"),
    ("fiecare 3 oră", "0 */3 * * *"),
    ("every 2 hours", "0 */2 * * *"),              # unchanged
    ("every 15 minutes", "*/15 * * * *"),          # unchanged
    ("every weekday at 7am", "0 7 * * 1-5"),       # unchanged
    ("hourly", "0 * * * *"),                       # unchanged
])
def test_compact_intervals_and_bare_durations_recur(text, cron):
    assert resolve_schedule(text, now=NOW, zone=BUCHAREST)[0] == cron


@pytest.mark.parametrize(("text", "error"), [
    ("every 90m", "divide"),
    ("every 7h", "divide"),
    ("every 48h", "divide"),
    ("every 2m", "five minutes"),
    ("every 0h", "at least 1"),
])
def test_an_interval_a_cron_cannot_keep_is_refused(text, error):
    with pytest.raises(ValueError, match=error):
        resolve_schedule(text, now=NOW, zone=BUCHAREST)


def test_the_preview_route_parser_reports_a_one_shot():
    parsed = parse_schedule("in 30m", now=NOW, zone=BUCHAREST)
    assert parsed == {"ok": True, "at": "2026-09-24T07:30:00+00:00",
                      "description": "once at 2026-09-24 10:30 (Europe/Bucharest)"}
    assert parse_schedule("every 2h")["cron"] == "0 */2 * * *"
    local = parse_schedule("2026-10-01 09:00", now=NOW, zone=BUCHAREST)
    assert local["at"] == "2026-10-01T06:00:00+00:00", "always UTC, whatever zone the time was said in"


# ── repeat ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "expected"), [
    (None, None), ("", None), ("forever", None), ("Forever", None), ("unlimited", None),
    ("always", None), ("∞", None), ("mereu", None), ("la nesfârșit", None),
    ("once", 1), ("1x", 1), ("x1", 1), ("o dată", 1), ("o data", 1), (1, 1),
    ("twice", 2), ("de două ori", 2), ("de 2 ori", 2),
    ("3x", 3), ("3 times", 3), ("3", 3), (" 3 ", 3), (3, 3), ("x 5", 5), (10000, 10000),
])
def test_normalize_repeat(value, expected):
    assert normalize_repeat(value) == expected


@pytest.mark.parametrize("value", [0, -1, "0x", 10001, "10001", True, False, 2.5, "soon", [3], {"n": 3}])
def test_normalize_repeat_refuses(value):
    with pytest.raises(ValueError, match="repeat"):
        normalize_repeat(value)


def test_options_carry_the_normalised_count():
    assert validate_options({"repeat": "3x"})["repeat"] == 3
    assert validate_options({"repeat": "forever"})["repeat"] is None
    assert validate_options({"repeat": "once"})["repeat"] == 1
    with pytest.raises(ValueError, match="repeat"):
        validate_options({"repeat": "soon"})


# ── the store and the runner ─────────────────────────────────────────────────


class _Scheduler:
    running = True
    timezone = BUCHAREST

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = {"trigger": trigger, **kwargs}

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)

    def get_jobs(self):
        return [SimpleNamespace(id=j) for j in self.jobs]


def _runner(tmp_path):
    orch = SimpleNamespace(channels={}, get_setting=lambda key, default=None: default)
    store = JobStore(tmp_path / "jobs.db")
    sched = _Scheduler()
    runner = JobRunner(store, orch=orch, scheduler=lambda: sched, quiet=lambda: False)
    return runner, store, sched


REMIND = {"type": "remind", "message": "stretch"}
ASK = {"type": "ask", "prompt": "what changed?"}


def test_a_one_shot_is_stored_registered_and_shown_as_one(tmp_path):
    runner, store, sched = _runner(tmp_path)
    try:
        job, receipt, confirmation = runner.arm(name="stretch", schedule_text="in 30m", action=REMIND)
        assert is_one_shot(job.cron) and receipt is None
        when = run_at(job.cron)
        assert timedelta(minutes=29) < when - datetime.now(UTC) <= timedelta(minutes=30)
        view = job.as_dict()
        assert view["one_shot"] is True and view["run_at"] == when.isoformat()
        entry = sched.jobs[f"job-{job.id}"]
        assert entry["trigger"] == "date" and entry["run_date"] == when
        assert "once at" in confirmation and "on its cadence" not in confirmation
        recurring = runner.arm(name="digest", schedule_text="every 2h", action=ASK)[0]
        assert recurring.as_dict()["one_shot"] is False and recurring.as_dict()["run_at"] is None
    finally:
        store.close()


def test_the_store_resolves_times_in_the_schedulers_zone(tmp_path):
    runner, store, _sched = _runner(tmp_path)
    try:
        tomorrow = (datetime.now(BUCHAREST) + timedelta(days=1)).date()
        job = runner.arm(name="call", schedule_text="tomorrow at 9", action=REMIND)[0]
        assert run_at(job.cron) == datetime(tomorrow.year, tomorrow.month, tomorrow.day, 9,
                                            tzinfo=BUCHAREST).astimezone(UTC)
    finally:
        store.close()


def test_a_one_shot_never_takes_the_first_run_even_when_asked(tmp_path):
    runner, store, _sched = _runner(tmp_path)
    try:
        job, receipt, _ = runner.arm(name="once", schedule_text="in 2h", action=ASK, first_run=True)
        assert receipt is None, "the first run would spend its only run and skip the asked slot"
        assert first_run_decision(job, explicit=True) == (False, "one-shot")
        assert first_run_policy(job) == (False, "one-shot")
    finally:
        store.close()


def test_a_one_shot_runs_once_and_is_then_complete(tmp_path, monkeypatch):
    runner, store, sched = _runner(tmp_path)
    delivered = []

    async def deliver(self, job, text, **kwargs):
        delivered.append(text)
        return "delivered"

    monkeypatch.setattr(JobRunner, "_deliver", deliver, raising=False)
    try:
        job = runner.arm(name="once", schedule_text="in 1h", action=REMIND)[0]
        first = asyncio.run(runner.fire(job.id))
        second = asyncio.run(runner.fire(job.id))
        assert first.status != "skipped", first
        assert (second.status, second.summary) == ("skipped", "one-shot already ran")
        done = store.get(job.id)
        assert done.attempts == 1 and done.runnable is False
        sched.jobs.clear()
        assert runner.register_all() == 0, "a spent one-shot is not armed again at start"
    finally:
        store.close()


def test_a_spent_one_shot_script_job_does_not_run_twice(tmp_path, monkeypatch):
    runner, store, _sched = _runner(tmp_path)
    ran = []

    async def script_fire(job, started):
        ran.append(job.id)
        return store.record_run(job.id, started_at=started, finished_at=started, status="ok", summary="ran")

    try:
        job = runner.arm(name="once", schedule_text="in 1h", action=ASK)[0]
        monkeypatch.setattr(runner, "_script_runtime", SimpleNamespace(fire=script_fire))
        monkeypatch.setattr(store, "get", lambda job_id, _get=store.get: (
            lambda j: j and jobs_mod.replace(j, options={**j.options, "script": "check.py"}))(_get(job_id)))
        monkeypatch.setattr(jobs_mod, "validate_options", lambda *a, **k: {})
        asyncio.run(runner.fire(job.id))
        second = asyncio.run(runner.fire(job.id, force=True))
        assert ran == [job.id] and second.summary == "one-shot already ran"
    finally:
        store.close()


def test_editing_the_time_rearms_a_spent_one_shot(tmp_path):
    runner, store, sched = _runner(tmp_path)
    try:
        job = runner.arm(name="once", schedule_text="in 1h", action=REMIND)[0]
        assert store.reserve_attempt(job.id) and not store.reserve_attempt(job.id)
        edited = runner.edit(job.id, schedule_text="in 3h")
        assert edited.attempts == 0 and edited.runnable
        assert sched.jobs[f"job-{job.id}"]["run_date"] == run_at(edited.cron)
        renamed = runner.edit(job.id, name="once more")
        assert renamed.cron == edited.cron
        assert store.reserve_attempt(job.id)
        assert runner.edit(job.id, name="again").attempts == 1, "only a new time re-arms it"
        recurring = runner.edit(job.id, schedule_text="every 2h")
        assert recurring.cron == "0 */2 * * *" and recurring.runnable
    finally:
        store.close()


def test_the_fallback_ticker_fires_a_one_shot_in_its_minute_only(tmp_path):
    runner, store, sched = _runner(tmp_path)
    sched.running = False
    fired = []

    async def fire(job_id, **kwargs):
        fired.append(job_id)
        return SimpleNamespace(id=1)

    try:
        job = runner.arm(name="once", schedule_text="in 90 minutes", action=REMIND)[0]
        when = run_at(job.cron)
        runner.fire = fire
        asyncio.run(runner.tick(when - timedelta(minutes=1)))
        asyncio.run(runner.tick(when.replace(second=0) + timedelta(seconds=20)))
        asyncio.run(runner.tick(when + timedelta(minutes=5)))
        assert fired == [job.id]
    finally:
        store.close()


def test_slot_timing_of_a_one_shot(tmp_path):
    runner, store, _sched = _runner(tmp_path)
    try:
        job = runner.arm(name="once", schedule_text="in 2h", action=REMIND)[0]
        seconds, gap = runner.slot_timing(job)
        assert 7100 < seconds <= 7200 and gap is None
    finally:
        store.close()


def test_run_at_reads_only_what_the_store_writes():
    assert run_at("@at 2026-10-01T06:00:00+00:00") == datetime(2026, 10, 1, 6, tzinfo=UTC)
    assert run_at("0 */2 * * *") is None
    assert not is_one_shot("0 9 * * *") and not is_one_shot("") and not is_one_shot(None)
    with pytest.raises(ValueError):
        run_at("@at tomorrow")
    with pytest.raises(ValueError, match="carries its zone"):
        run_at("@at 2026-10-01T06:00:00")
    assert run_at("@at 2026-10-01T09:00:00+03:00").isoformat() == "2026-10-01T06:00:00+00:00"
    with pytest.raises(ValueError):
        fires_per_day("@at nope")
