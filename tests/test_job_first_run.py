"""H687 — a recurring instruction runs once immediately, then on its cadence.

Hermes' ``/loop`` is an interval, and LoopManager.set() starts it with
``next_due_at = now``: the first wakeup fires at the next poll, and the reply says so
("First wakeup fires now, then on the cadence above"). A Hermes cron job, by
contrast, waits for its first computed run. A new Nerva job always waited for its
first cron slot, and the confirmations named only the schedule.

Now an agent-instruction job on an interval cadence queues one first run at creation
through the governed dispatch path (a request of origin 'first_run', drained by
_fire_once under the shared job gate), so the emergency stop, pause, validation and
the quiet-hours hold all apply. What waits for its slot:
- a calendar schedule (a morning brief armed in the evening, a weekday job on a
  Saturday);
- a reminder;
- a repeat-limited job (critic note 15);
- anything armed during quiet hours or under two minutes before its first slot.
``first_run`` on the create call overrides the default either way. It is a
creation-time choice, never a stored option.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import estop
from agents.core.autonomy.jobs import (
    JobRunner,
    JobStore,
    arm_confirmation,
    first_run_decision,
    is_interval_cron,
)

ADMIN = {"x-admin-token": "secret"}
ASK_EVERY_2H = {"name": "digest", "schedule_text": "every 2 hours",
                "action": {"type": "ask", "prompt": "summarise my inbox"}}


class _Scheduler:
    running = True

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = kwargs

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)

    def get_jobs(self):
        return [SimpleNamespace(id=j) for j in self.jobs]


class _Telegram:
    def __init__(self):
        self.sent = []

    async def send(self, text, chat_id=None, **kwargs):
        self.sent.append((text, chat_id))
        return True


def _hub(tmp_path, monkeypatch, *, quiet=False, scheduler=True):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    stopped = {"on": False}
    monkeypatch.setattr(estop, "check_paused", lambda component, logger: stopped["on"])
    telegram = _Telegram()
    orch = SimpleNamespace(
        channels={"telegram": telegram},
        get_setting=lambda key, default=None: "5" if key == "autonomy.owner_chat_id" else default,
    )
    store = JobStore(tmp_path / "jobs.db")
    sched = _Scheduler() if scheduler else None
    orch.jobs = JobRunner(store, orch=orch, scheduler=lambda: sched, quiet=lambda: quiet)
    # Far from any slot unless a test says otherwise.
    monkeypatch.setattr(JobRunner, "seconds_to_next_slot", lambda self, job, now=None: 3600.0)
    return orch, telegram, stopped, store


@pytest.fixture
def hub(tmp_path, monkeypatch):
    orch, telegram, stopped, store = _hub(tmp_path, monkeypatch)
    with TestClient(web.app) as client:
        real = web.orch
        web.orch = orch
        try:
            yield client, orch, telegram, stopped
        finally:
            web.orch = real
    store.close()


def _create(client, **body):
    reply = client.post("/api/jobs", json=body, headers=ADMIN)
    assert reply.status_code == 201, reply.text
    return reply.json()


def _runs(client, job_id):
    return client.get(f"/api/jobs/{job_id}/runs", headers=ADMIN).json()["runs"]


def test_an_interval_instruction_queues_one_first_run_at_creation(hub):
    client, orch, _tg, _stop = hub
    created = _create(client, **ASK_EVERY_2H)
    first = created["first_run"]
    assert first["status"] == "queued" and first["job_id"] == created["job"]["id"]
    assert first["origin"] == "first_run"
    assert created["confirmation"] == "first run now, then every 2 hours (0 */2 * * *)"
    asyncio.run(orch.jobs.drain_manual())
    runs = _runs(client, created["job"]["id"])
    assert len(runs) == 1  # the first run, before any cron slot has come round
    request = client.get(f"/api/jobs/{created['job']['id']}/requests/{first['id']}", headers=ADMIN).json()
    assert request["request"]["run"]["id"] == runs[0]["id"]


def test_a_calendar_schedule_waits_for_its_slot(hub):
    client, orch, telegram, _stop = hub
    for created in (_create(client, blueprint="morning_brief"),
                    _create(client, blueprint="ask_agent", params={"prompt": "x"})):
        assert created["first_run"] is None
        assert created["confirmation"].endswith("on its cadence")
    asyncio.run(orch.jobs.drain_manual())
    assert telegram.sent == [] and all(_runs(client, j.id) == [] for j in orch.jobs.store.list())


def test_the_first_run_goes_through_the_emergency_stop(hub):
    client, orch, telegram, stopped = hub
    stopped["on"] = True
    created = _create(client, **ASK_EVERY_2H)
    asyncio.run(orch.jobs.drain_manual())
    runs = _runs(client, created["job"]["id"])
    assert [(r["status"], r["summary"]) for r in runs] == [("skipped", "emergency stop engaged")]
    assert telegram.sent == []


def test_pausing_before_the_drain_cancels_the_first_run(hub):
    client, orch, telegram, _stop = hub
    created = _create(client, **ASK_EVERY_2H)
    job_id = created["job"]["id"]
    assert client.post(f"/api/jobs/{job_id}/pause", json={"reason": "wrong prompt"}, headers=ADMIN).status_code == 200
    asyncio.run(orch.jobs.drain_manual())
    assert _runs(client, job_id) == [] and telegram.sent == []
    request = client.get(f"/api/jobs/{job_id}/requests/{created['first_run']['id']}", headers=ADMIN).json()
    assert request["request"]["status"] == "cancelled"
    assert request["request"]["reason"] == "job paused before its first run"


def test_a_first_run_that_slips_past_the_pause_still_obeys_it(hub):
    client, orch, telegram, _stop = hub
    created = _create(client, **ASK_EVERY_2H)
    job_id = created["job"]["id"]
    orch.jobs.store.pause(job_id, "paused behind the runner's back")  # no cancel_queued
    asyncio.run(orch.jobs.drain_manual())
    assert [r["status"] for r in _runs(client, job_id)] == ["skipped"] and telegram.sent == []


def test_the_owners_run_now_folds_into_the_first_run_and_keeps_its_force(hub):
    client, orch, _tg, _stop = hub
    created = _create(client, **ASK_EVERY_2H)
    job_id = created["job"]["id"]
    ran = client.post(f"/api/jobs/{job_id}/run", headers=ADMIN).json()
    assert ran["request"]["id"] == created["first_run"]["id"] and ran["request"]["origin"] == "manual"
    client.post(f"/api/jobs/{job_id}/pause", json={"reason": "later"}, headers=ADMIN)
    asyncio.run(orch.jobs.drain_manual())
    runs = _runs(client, job_id)  # ▶ now runs a paused job, as before (no model here, so it fails)
    assert len(runs) == 1 and runs[0]["status"] != "skipped"


def test_an_edit_before_the_drain_runs_the_edited_job(hub):
    client, orch, _tg, _stop = hub
    created = _create(client, **ASK_EVERY_2H)
    job_id = created["job"]["id"]
    edited = client.patch(f"/api/jobs/{job_id}", json={"action": {"type": "ask", "prompt": "summarise my calendar"}},
                          headers=ADMIN)
    assert edited.status_code == 200, edited.text
    old = client.get(f"/api/jobs/{job_id}/requests/{created['first_run']['id']}", headers=ADMIN).json()["request"]
    assert old["status"] == "cancelled" and old["reason"] == "configuration changed before the first run"
    asyncio.run(orch.jobs.drain_manual())
    runs = _runs(client, job_id)  # executed (no model here, so it fails), not cancelled
    assert len(runs) == 1 and runs[0]["status"] != "skipped"


def test_a_reminder_stays_on_its_cadence(hub):
    client, orch, telegram, _stop = hub
    created = _create(client, name="water", schedule_text="every 2 hours", action={"type": "remind", "message": "water"})
    assert created["first_run"] is None
    asyncio.run(orch.jobs.drain_manual())
    assert _runs(client, created["job"]["id"]) == [] and telegram.sent == []


def test_first_run_false_opts_out_and_true_opts_in(hub):
    client, orch, telegram, _stop = hub
    out = _create(client, **ASK_EVERY_2H, first_run=False)
    assert out["first_run"] is None
    into = _create(client, name="water", schedule_text="every day at 10",
                   action={"type": "remind", "message": "water"}, first_run=True)
    assert into["first_run"]["status"] == "queued"
    asyncio.run(orch.jobs.drain_manual())
    assert telegram.sent == [("water", 5)]
    assert _runs(client, out["job"]["id"]) == []


def test_first_run_is_a_creation_choice_never_a_stored_option(hub):
    client, _orch, _tg, _stop = hub
    stored = client.post("/api/jobs", json={**ASK_EVERY_2H, "options": {"first_run": True}}, headers=ADMIN)
    assert stored.status_code == 422 and "first_run" in stored.json()["error"]
    created = _create(client, **ASK_EVERY_2H, first_run=True)
    assert created["job"]["options"] == {}
    patched = client.patch(f"/api/jobs/{created['job']['id']}", json={"options": {"first_run": False}}, headers=ADMIN)
    assert patched.status_code == 422
    assert client.post("/api/jobs", json={**ASK_EVERY_2H, "first_run": "yes"}, headers=ADMIN).status_code == 422


def test_a_repeat_limited_job_does_not_spend_an_attempt_early(hub):
    client, orch, _tg, _stop = hub
    created = _create(client, **ASK_EVERY_2H, options={"repeat": 1})
    assert created["first_run"] is None
    job = orch.jobs.store.get(created["job"]["id"])
    assert job.attempts == 0 and job.runnable


def test_a_refused_enqueue_still_answers_201_and_says_so(hub, monkeypatch):
    client, orch, _tg, _stop = hub

    def full(job_id, *, origin="manual"):
        raise ValueError("manual request capacity reached; wait for queued work")

    monkeypatch.setattr(orch.jobs.store.dispatch, "enqueue", full)
    created = _create(client, **ASK_EVERY_2H)
    assert created["first_run"] is None
    assert created["confirmation"].startswith("first run not queued (manual request capacity reached")
    assert [j.id for j in orch.jobs.store.list()] == [created["job"]["id"]]


def test_quiet_hours_hold_back_the_first_run(tmp_path, monkeypatch):
    orch, _tg, _stop, store = _hub(tmp_path, monkeypatch, quiet=True)
    try:
        _job, receipt, confirmation = orch.jobs.arm(**ASK_EVERY_2H)
        assert receipt is None and "quiet hours" in confirmation
    finally:
        store.close()


def test_no_first_run_right_before_the_first_slot(tmp_path, monkeypatch):
    orch, _tg, _stop, store = _hub(tmp_path, monkeypatch)
    monkeypatch.setattr(JobRunner, "seconds_to_next_slot", lambda self, job, now=None: 30.0)
    try:
        _job, receipt, confirmation = orch.jobs.arm(**ASK_EVERY_2H)
        assert receipt is None and "under two minutes" in confirmation
    finally:
        store.close()


def test_without_a_scheduler_the_reply_says_nothing_fires_yet(tmp_path, monkeypatch):
    orch, _tg, _stop, store = _hub(tmp_path, monkeypatch, scheduler=False)
    try:
        _job, receipt, confirmation = orch.jobs.arm(**ASK_EVERY_2H)
        assert receipt["status"] == "queued"
        assert confirmation.endswith("the scheduler is not running, so nothing fires until it is")
    finally:
        store.close()


def test_an_interval_script_job_submits_its_first_run(hub, tmp_path, monkeypatch):
    client, orch, _tg, _stop = hub
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "watch.py").write_text("print('ready')")
    submitted = []
    orch.jobs.bind_scripts(submit=lambda *a: submitted.append(a) or 17, get=lambda _: None, find=lambda _: [])
    created = _create(client, name="watch", schedule_text="every 30 minutes", action={"type": "ask", "prompt": ""},
                      options={"script": "watch.py", "no_agent": True, "deliver": []})
    assert created["first_run"]["status"] == "queued"
    asyncio.run(orch.jobs.drain_manual())
    assert len(submitted) == 1


def test_the_remind_command_says_it_waits_for_its_cadence(hub):
    from agents.core.commands import CommandContext, _remind

    _client, orch, _tg, _stop = hub
    reply = _remind(CommandContext(orch=orch, principal=None, name="remind", args="every day at 10 | water"))
    assert "on its cadence" in reply and "first run" not in reply


@pytest.mark.parametrize("cron,expected", [
    ("*/30 * * * *", True), ("0 * * * *", True), ("0 */2 * * *", True),
    ("0 7 * * *", False), ("0 8 * * 1-5", False), ("*/10 9-17 * * *", False), ("0 9 1 * *", False),
])
def test_what_counts_as_an_interval(cron, expected):
    assert is_interval_cron(cron) is expected


def _job(action, options=None, cron="0 */2 * * *"):
    return SimpleNamespace(action=action, options=options or {}, cron=cron, runnable=True)


@pytest.mark.parametrize("job,kwargs,expected", [
    (_job({"type": "ask"}), {}, (True, "interval")),
    (_job({"type": "brief"}), {}, (True, "interval")),
    (_job({"type": "task"}), {}, (True, "interval")),
    (_job({"type": "ask"}, {"script": "x.py"}), {}, (True, "interval")),
    (_job({"type": "ask"}, {"monitor_url": "https://example.test"}), {}, (True, "interval")),
    (_job({"type": "remind"}), {}, (False, "reminder")),
    (_job({"type": "ask"}, cron="0 7 * * *"), {}, (False, "calendar")),
    (_job({"type": "ask"}, {"repeat": 3}), {}, (False, "repeat-limited")),
    (_job({"type": "ask"}), {"quiet": True}, (False, "quiet hours")),
    (_job({"type": "ask"}), {"seconds_to_slot": 119.0}, (False, "slot")),
    (_job({"type": "ask"}), {"seconds_to_slot": 121.0}, (True, "interval")),
    (_job({"type": "ask"}, {"repeat": 3}), {"explicit": True}, (True, "asked")),
    (_job({"type": "remind"}, cron="0 7 * * *"), {"explicit": True, "quiet": True}, (True, "asked")),
    (_job({"type": "ask"}), {"explicit": False}, (False, "opted out")),
    (SimpleNamespace(action={"type": "ask"}, options={}, cron="*/5 * * * *", runnable=False), {"explicit": True},
     (False, "not runnable")),
])
def test_which_jobs_fire_at_creation(job, kwargs, expected):
    assert first_run_decision(job, **kwargs) == expected


def test_the_first_run_confirmation_wording():
    job = SimpleNamespace(schedule_text="every 2 hours", cron="0 */2 * * *")
    assert arm_confirmation(job, {"status": "queued"}) == "first run now, then every 2 hours (0 */2 * * *)"
    assert arm_confirmation(job, None) == "every 2 hours (0 */2 * * *), on its cadence"
    assert arm_confirmation(job, None, why="not queued (full)") == (
        "first run not queued (full); every 2 hours (0 */2 * * *), on its cadence")


def test_the_cli_passes_the_first_run_choice(monkeypatch):
    from tests.test_nerva_cli import _FakeHub, _run

    job = {"id": "abc123abc123", "name": "Ask", "schedule_text": "every 2 hours", "cron": "0 */2 * * *"}
    hub = _FakeHub({"POST /api/jobs": {"ok": True, "job": job, "first_run": None,
                                       "confirmation": "every 2 hours (0 */2 * * *), on its cadence"}})
    code, _out, _err, hub = _run(["jobs", "create", "--blueprint", "inbox_watch", "--no-first-run"], hub)
    assert code == 0 and hub.calls[-1][2]["first_run"] is False
