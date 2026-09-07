"""The /api/jobs surface (Hermes absorption, wave 2) — admin-guarded, honest 503 without a runner."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import estop
from agents.core.autonomy.jobs import JobRunner, JobStore

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
    monkeypatch.setattr(estop, "check_paused", lambda component, logger: False)
    telegram = _Telegram()
    orch = SimpleNamespace(
        channels={"telegram": telegram},
        get_setting=lambda key, default=None: "5" if key == "autonomy.owner_chat_id" else default,
    )
    store = JobStore(tmp_path / "jobs.db")
    orch.jobs = JobRunner(store, orch=orch, scheduler=lambda: _Scheduler())
    with TestClient(web.app) as client:
        # The app lifespan builds the real orchestrator on startup and tears it down on
        # exit; the stand-in is bound only in between, or the routes resolve the real one
        # and the shutdown trips over the stand-in.
        real = web.orch
        web.orch = orch
        try:
            yield client, orch, telegram
        finally:
            web.orch = real
    store.close()


def test_every_jobs_route_is_owner_only(hub):
    client, _orch, _tg = hub
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/jobs", json={}).status_code == 401
    assert client.get("/api/jobs/blueprints").status_code == 401
    assert client.delete("/api/jobs/x").status_code == 401


def test_jobs_lifecycle_over_http(hub):
    client, orch, telegram = hub
    assert client.get("/api/jobs", headers=ADMIN).json()["jobs"] == []
    blueprints = client.get("/api/jobs/blueprints", headers=ADMIN).json()["blueprints"]
    assert {b["id"] for b in blueprints} >= {"reminder", "morning_brief", "inbox_watch"}

    created = client.post(
        "/api/jobs",
        json={"blueprint": "reminder", "params": {"message": "water", "schedule_text": "every day at 10"}},
        headers=ADMIN,
    )
    assert created.status_code == 201
    job = created.json()["job"]
    assert job["cron"] == "0 10 * * *" and job["name"] == "Reminder" and job["runnable"] is True

    listed = client.get("/api/jobs", headers=ADMIN).json()
    assert [j["id"] for j in listed["jobs"]] == [job["id"]] and listed["scheduler"]["alive"] is True

    ran = client.post(f"/api/jobs/{job['id']}/run", headers=ADMIN).json()
    assert ran["ok"] is True and ran["run"]["status"] == "ok" and telegram.sent == [("water", 5)], ran
    runs = client.get(f"/api/jobs/{job['id']}/runs", headers=ADMIN).json()["runs"]
    assert [r["status"] for r in runs] == ["ok"]
    detail = client.get(f"/api/jobs/{job['id']}", headers=ADMIN).json()
    assert detail["job"]["last_status"] == "ok" and len(detail["runs"]) == 1

    paused = client.post(f"/api/jobs/{job['id']}/pause", json={"reason": "holiday"}, headers=ADMIN).json()
    assert paused["job"]["paused_reason"] == "holiday" and paused["job"]["runnable"] is False
    resumed = client.post(f"/api/jobs/{job['id']}/resume", headers=ADMIN).json()
    assert resumed["job"]["runnable"] is True

    assert client.delete(f"/api/jobs/{job['id']}", headers=ADMIN).json() == {"ok": True}
    assert client.get(f"/api/jobs/{job['id']}", headers=ADMIN).status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/run", headers=ADMIN).status_code == 404


def test_bad_requests_are_422_with_reasons(hub):
    client, _orch, _tg = hub
    r = client.post("/api/jobs", json={"name": "x"}, headers=ADMIN)
    assert r.status_code == 422 and "required" in r.json()["errors"][0]
    r = client.post("/api/jobs", json={"name": "x", "schedule_text": "every minute", "action": {"type": "remind", "message": "m"}}, headers=ADMIN)
    assert r.status_code == 422 and "five minutes" in r.json()["errors"][0]
    r = client.post("/api/jobs", json={"blueprint": "nope"}, headers=ADMIN)
    assert r.status_code == 422
    r = client.post("/api/jobs", json={"name": "x", "shell": "rm"}, headers=ADMIN)
    assert r.status_code == 422  # extra keys are refused by the body model


def test_a_hub_without_a_runner_says_so(hub, monkeypatch):
    client, orch, _tg = hub
    orch.jobs = None
    assert client.get("/api/jobs", headers=ADMIN).status_code == 503
    assert client.post("/api/jobs", json={"blueprint": "reminder"}, headers=ADMIN).status_code == 503
