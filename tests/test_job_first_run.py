"""H687 — a recurring instruction runs once immediately, then on its cadence.

Hermes' LoopManager.set() sets ``next_due_at = now`` for a new loop, so its first
wakeup fires at the next poll instead of after a whole cadence, and the creation reply
says so ("First wakeup fires now, then on the cadence above"). A new Nerva job waited
for its first cron slot and the confirmations named only the schedule. Now an
agent-instruction job (ask / brief / task, or a script or monitor) queues one first run
at creation through the existing governed path — the dispatch receipt drained by
_fire_once under the shared job gate — so the emergency stop, pause, validation and
the quiet-hours hold all still apply. A reminder stays cadence-only unless
``first_run: true`` asks for it, ``first_run: false`` opts any job out, and a
repeat-limited job is never fired early by default: its first run would spend one of
its few attempts and could skip the slot the owner scheduled (critic note 15).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import estop
from agents.core.autonomy.jobs import JobRunner, JobStore, wants_first_run

ADMIN = {"x-admin-token": "secret"}


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


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    stopped = {"on": False}
    monkeypatch.setattr(estop, "check_paused", lambda component, logger: stopped["on"])
    telegram = _Telegram()
    orch = SimpleNamespace(
        channels={"telegram": telegram},
        get_setting=lambda key, default=None: "5" if key == "autonomy.owner_chat_id" else default,
    )
    store = JobStore(tmp_path / "jobs.db")
    orch.jobs = JobRunner(store, orch=orch, scheduler=lambda: _Scheduler(), quiet=lambda: False)
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


def test_an_agent_instruction_job_queues_one_first_run_at_creation(hub):
    client, orch, _tg, _stop = hub
    created = _create(client, blueprint="ask_agent", params={"prompt": "summarise my inbox"})
    first = created["first_run"]
    assert first["status"] == "queued" and first["job_id"] == created["job"]["id"]
    asyncio.run(orch.jobs.drain_manual())
    runs = client.get(f"/api/jobs/{created['job']['id']}/runs", headers=ADMIN).json()["runs"]
    assert len(runs) == 1  # the first run, before any cron slot has come round
    request = client.get(f"/api/jobs/{created['job']['id']}/requests/{first['id']}", headers=ADMIN).json()
    assert request["request"]["run"]["id"] == runs[0]["id"]


def test_the_first_run_goes_through_the_emergency_stop(hub):
    client, orch, telegram, stopped = hub
    stopped["on"] = True
    created = _create(client, blueprint="morning_brief")
    assert created["first_run"]["status"] == "queued"
    asyncio.run(orch.jobs.drain_manual())
    runs = client.get(f"/api/jobs/{created['job']['id']}/runs", headers=ADMIN).json()["runs"]
    assert [(r["status"], r["summary"]) for r in runs] == [("skipped", "emergency stop engaged")]
    assert telegram.sent == []


def test_a_reminder_stays_on_its_cadence(hub):
    client, orch, telegram, _stop = hub
    created = _create(client, blueprint="reminder", params={"message": "water"})
    assert created["first_run"] is None
    asyncio.run(orch.jobs.drain_manual())
    assert client.get(f"/api/jobs/{created['job']['id']}/runs", headers=ADMIN).json()["runs"] == []
    assert telegram.sent == []


def test_first_run_false_opts_out_and_true_opts_a_reminder_in(hub):
    client, orch, telegram, _stop = hub
    out = _create(client, blueprint="ask_agent", params={"prompt": "x"}, options={"first_run": False})
    assert out["first_run"] is None
    into = _create(client, name="water", schedule_text="every day at 10",
                   action={"type": "remind", "message": "water"}, options={"first_run": True})
    assert into["first_run"]["status"] == "queued"
    asyncio.run(orch.jobs.drain_manual())
    assert telegram.sent == [("water", 5)]
    assert client.get(f"/api/jobs/{out['job']['id']}/runs", headers=ADMIN).json()["runs"] == []


def test_a_repeat_limited_job_does_not_spend_an_attempt_early(hub):
    client, orch, _tg, _stop = hub
    created = _create(client, blueprint="ask_agent", params={"prompt": "x"}, options={"repeat": 1})
    assert created["first_run"] is None
    job = orch.jobs.store.get(created["job"]["id"])
    assert job.attempts == 0 and job.runnable


def test_first_run_must_be_a_boolean(hub):
    client, _orch, _tg, _stop = hub
    reply = client.post("/api/jobs", json={"blueprint": "ask_agent", "params": {"prompt": "x"},
                                           "options": {"first_run": "yes"}}, headers=ADMIN)
    assert reply.status_code == 422 and "first_run" in reply.json()["error"]


@pytest.mark.parametrize("action,options,expected", [
    ({"type": "ask"}, {}, True),
    ({"type": "brief"}, {}, True),
    ({"type": "task"}, {}, True),
    ({"type": "remind"}, {}, False),
    ({"type": "remind"}, {"script": "x.py"}, True),
    ({"type": "ask"}, {"monitor_url": "https://example.test"}, True),
    ({"type": "ask"}, {"repeat": 3}, False),
    ({"type": "ask"}, {"repeat": 3, "first_run": True}, True),
    ({"type": "ask"}, {"first_run": False}, False),
    ({"type": "remind"}, {"first_run": True}, True),
])
def test_which_jobs_fire_at_creation(action, options, expected):
    assert wants_first_run(SimpleNamespace(action=action, options=options)) is expected


def test_the_remind_command_says_it_waits_for_its_cadence(hub):
    from agents.core.commands import CommandContext, _remind

    _client, orch, _tg, _stop = hub
    reply = _remind(CommandContext(orch=orch, principal=None, name="remind", args="every day at 10 | water"))
    assert "on its cadence" in reply and "first run" not in reply


def test_the_first_run_confirmation_wording():
    from agents.core.autonomy.jobs import arm_confirmation

    job = SimpleNamespace(schedule_text="every day at 7:00", cron="0 7 * * *")
    assert arm_confirmation(job, {"status": "queued"}) == "first run now, then every day at 7:00 (0 7 * * *)"
    assert arm_confirmation(job, None) == "every day at 7:00 (0 7 * * *), on its cadence"
