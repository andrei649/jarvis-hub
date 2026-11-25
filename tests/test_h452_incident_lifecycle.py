"""H452 — every job failure is classified into one of eight types, and an incident
alerts the owner once: detected -> alerted -> closed, with closed terminal for that
signature."""
import sqlite3
from types import SimpleNamespace

import pytest

import agents.core.autonomy.error_logger as error_logger
from agents.core.autonomy.jobs import MAX_FAILURES, JobRunner, JobStore, utc_now
from agents.core.autonomy.jobs_incidents import FAILURE_TYPES, classify_failure


@pytest.fixture
def store(tmp_path):
    value = JobStore(tmp_path / "jobs.db")
    yield value
    value.close()


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(error_logger, "persist_problem", lambda log: sent.append(log))
    return sent


def _job(store):
    return store.create(name="daily", schedule_text="every day at 9",
                        action={"type": "ask", "prompt": "report", "deliver": False})


def _runner(store):
    async def process(prompt, **kwargs):
        return "ok"

    return JobRunner(store, orch=SimpleNamespace(process=process), scheduler=lambda: None, quiet=lambda: False)


@pytest.mark.parametrize("code, error, kind", [
    ("HTTPStatusError", "429 Too Many Requests", "rate_limit"),
    ("RuntimeError", "provider quota exhausted for today", "rate_limit"),
    ("JobRunTimeout", "run exceeded its 300s deadline", "timeout"),
    ("RuntimeError", "request timed out", "timeout"),
    ("HTTPStatusError", "401 Unauthorized", "auth"),
    ("RuntimeError", "authentication failed for the selected provider", "auth"),
    ("RuntimeError", "delivery to telegram failed: no owner chat", "delivery"),
    ("ValueError", "unsupported job options: base_url", "config"),
    ("JobGuardBlocked", "job prompt blocked by the scheduled-job injection scanner (strict)", "config"),
    ("ValueError", "action.prompt is required", "config"),
    ("ScheduledScriptFailure", "scheduled script requires complete successful UTF-8 stdout capture", "script"),
    ("RuntimeError", "no model path is available for ask jobs", "agent"),
    ("RuntimeError", "the agent returned no answer", "agent"),
    ("KeyError", "'x'", "unknown"),
])
def test_eight_way_classifier(code, error, kind):
    assert kind in FAILURE_TYPES and classify_failure(code, error) == kind


def test_every_failure_type_is_reachable():
    samples = {"rate_limit": "429", "timeout": "timed out", "auth": "401", "delivery": "delivery failed",
               "config": "invalid config", "script": "script exited 1", "agent": "model error",
               "unknown": "boom"}
    assert {classify_failure("E", text) for text in samples.values()} == set(FAILURE_TYPES)


def test_incident_carries_its_type_and_alerts_once(store):
    job = _job(store)
    runner = _runner(store)
    runner._failed(store.get(job.id), utc_now(), TimeoutError("request timed out"))
    (incident,) = store.incidents.list(job_id=job.id)
    assert incident["failure_type"] == "timeout" and incident["state"] == "detected"
    claimed = store.incidents.claim_alert(job.id)
    assert claimed["state"] == "alerted" and claimed["alerted_at"]
    assert store.incidents.claim_alert(job.id) is None           # once per signature
    runner._failed(store.get(job.id), utc_now(), TimeoutError("request timed out"))
    (same,) = store.incidents.list(job_id=job.id)
    assert same["state"] == "alerted" and same["occurrences"] == 2
    assert store.incidents.ack(same["id"])["state"] == "closed"
    runner._failed(store.get(job.id), utc_now(), TimeoutError("request timed out"))
    assert store.incidents.list(job_id=job.id)[0]["state"] == "closed"   # terminal
    assert store.incidents.claim_alert(job.id) is None
    assert store.incidents.list(state="alerted") == []


@pytest.mark.asyncio
async def test_a_paused_job_alerts_once_per_pause_episode(store, alerts):
    job = store.create(name="daily", schedule_text="every day at 9",
                       action={"type": "remind", "message": "stand up", "channel": "nowhere"})
    runner = JobRunner(store, orch=SimpleNamespace(channels={}), scheduler=lambda: None, quiet=lambda: False)
    for _ in range(MAX_FAILURES):
        await runner.fire(job.id)
    assert store.get(job.id).paused_reason and len(alerts) == 1
    (incident,) = store.incidents.list(job_id=job.id)
    assert incident["state"] == "alerted"
    assert alerts[0].meta["incident_id"] == incident["id"]
    assert alerts[0].meta["failure_type"] == incident["failure_type"] == "delivery"
    # Further firings of the paused job are skipped: no second alert while it stays paused.
    await runner.fire(job.id)
    assert len(alerts) == 1
    # The owner acknowledges and resumes: a new episode, so the same signature may alert again.
    store.incidents.ack(incident["id"])
    runner.resume(job.id)
    assert store.incidents.list(job_id=job.id)[0]["state"] == "detected"
    for _ in range(MAX_FAILURES):
        await runner.fire(job.id)
    assert len(alerts) == 2


def test_alerted_signature_does_not_alert_again_without_a_resume(store, alerts):
    job = _job(store)
    runner = _runner(store)
    for _ in range(MAX_FAILURES + 2):              # the job is forced on after it paused
        runner._failed(store.get(job.id), utc_now(), RuntimeError("model backend down"))
    assert len(alerts) == 1


def test_a_new_error_is_a_new_incident_that_may_alert(store, alerts):
    job = _job(store)
    runner = _runner(store)
    for _ in range(MAX_FAILURES):
        runner._failed(store.get(job.id), utc_now(), RuntimeError("model backend down"))
    assert len(alerts) == 1
    runner.resume(job.id)
    for _ in range(MAX_FAILURES):
        runner._failed(store.get(job.id), utc_now(), RuntimeError("401 Unauthorized"))
    assert len(alerts) == 2
    kinds = {row["failure_type"]: row["state"] for row in store.incidents.list(job_id=job.id)}
    assert kinds == {"agent": "detected", "auth": "alerted"}


@pytest.mark.parametrize("failure", ["raises", "reports"])
def test_an_alert_that_cannot_be_persisted_is_released(store, monkeypatch, failure):
    def broken(log):
        if failure == "raises":
            raise OSError("disk full")
        return False

    monkeypatch.setattr(error_logger, "persist_problem", broken)
    job = _job(store)
    runner = _runner(store)
    for _ in range(MAX_FAILURES):
        runner._failed(store.get(job.id), utc_now(), RuntimeError("model backend down"))
    (incident,) = store.incidents.list(job_id=job.id)
    assert incident["state"] == "detected" and incident["alerted_at"] is None


# Review repro r5: the real problem log cannot be written (persist_problem used to swallow
# the OSError, so the claim was never released).
@pytest.mark.asyncio
async def test_unwritable_problem_log_releases_the_alert_claim(tmp_path, monkeypatch):
    from agents.core import settings_db

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    settings_db.init_db(force=True)
    (tmp_path / "problems.jsonl").mkdir()          # open(..., "a") -> IsADirectoryError
    local = JobStore(tmp_path / "jobs.db")

    async def boom(prompt, **kwargs):
        raise RuntimeError("provider exploded")

    try:
        job = local.create(name="j", schedule_text="every day at 9",
                           action={"type": "ask", "prompt": "x", "deliver": False})
        runner = JobRunner(local, orch=SimpleNamespace(process_detailed=boom),
                           scheduler=lambda: None, quiet=lambda: False)
        for _ in range(MAX_FAILURES):
            await runner.fire(job.id, force=True)
        incidents = local.incidents.list(job_id=job.id)
        assert incidents and incidents[0]["state"] == "detected", incidents
    finally:
        local.close()


def test_credential_override_is_classified_config_not_auth():
    assert classify_failure("JobGuardBlocked", "job carries an endpoint/credential override (base_url); "
                            "refusing to run a job that could send a stored key elsewhere") == "config"


def test_an_existing_store_gains_the_columns(tmp_path):
    path = tmp_path / "jobs.db"
    JobStore(path).close()
    with sqlite3.connect(path) as conn:          # an incident table from before H452
        conn.execute("DROP TABLE job_incidents")
        conn.execute("""CREATE TABLE job_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            signature TEXT NOT NULL, state TEXT NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            occurrences INTEGER NOT NULL, failure_count INTEGER NOT NULL,
            error_code TEXT NOT NULL, safe_error TEXT NOT NULL,
            acknowledged_at TEXT, UNIQUE(job_id, signature))""")
        conn.execute("""INSERT INTO job_incidents (job_id,signature,state,first_seen,last_seen,occurrences,
            failure_count,error_code,safe_error) VALUES ('j','s','detected','t','t',1,1,'E','old')""")
    reopened = JobStore(path)
    try:
        (row,) = reopened.incidents.list()
        assert row["failure_type"] == "unknown" and row["alerted_at"] is None
    finally:
        reopened.close()
