"""Native scheduler health must survive restart without retaining job payloads."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
    JobSubmissionEvent,
)

from agents.core.autonomy.jobs import JobRun, JobStore
from agents.core.scheduler_health import install_scheduler_health


class Scheduler:
    def __init__(self):
        self.listeners = []

    def add_listener(self, callback, mask):
        self.listeners.append((callback, mask))

    def emit(self, event):
        for callback, mask in self.listeners:
            if mask & event.code:
                callback(event)


@pytest.fixture
def health(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    scheduler = Scheduler()
    install_scheduler_health(scheduler, store)
    yield store, scheduler
    store.close()


def event(code=EVENT_JOB_EXECUTED, *, result=None):
    return JobExecutionEvent(code, "native-backup", "default", datetime.now(UTC),
                             retval=result, exception=RuntimeError("private key") if code == EVENT_JOB_ERROR else None,
                             traceback="private stack")


@pytest.mark.parametrize("code,status", [(EVENT_JOB_ERROR, "failed"), (EVENT_JOB_MISSED, "missed")])
def test_scheduler_failures_persist_without_exception_details(health, code, status):
    store, scheduler = health
    scheduler.emit(event(code))
    reopened = JobStore(store._path)
    try:
        result = reopened.scheduler_results()["native-backup"]
        assert result["status"] == status
        assert "private" not in str(result)
    finally:
        reopened.close()


@pytest.mark.parametrize("result", [
    {"ok": False, "error": "private"}, {"_scheduler_status": "failed"},
    {"skipped": True, "reason": "probe_failed"},
    {"skipped": True, "reason": "scan_failed"},
    {"skipped": True, "reason": "living_memory_failed"},
    {"reprojection": {"reason": "reprojection_failed"}},
])
def test_caught_failures_are_not_reported_as_success(health, result):
    store, scheduler = health
    scheduler.emit(event(result=result))
    assert store.scheduler_results()["native-backup"]["status"] == "failed"


def test_success_clears_failure_but_intentional_skip_does_not(health):
    store, scheduler = health
    scheduler.emit(event(EVENT_JOB_ERROR))
    for result in ({"skipped": True, "reason": "disabled"}, {"ok": False, "skipped": "off"},
                   {"_scheduler_status": "skipped"}):
        scheduler.emit(event(result=result))
        assert store.scheduler_results()["native-backup"]["status"] == "failed"
    scheduler.emit(event(result={"ok": True}))
    assert store.scheduler_results()["native-backup"]["status"] == "ok"


@pytest.mark.parametrize("status,expected", [("skipped", "missed"), ("failed", "failed"), ("ok", "ok")])
def test_owner_job_run_status_preserves_actual_outcome(health, status, expected):
    store, scheduler = health
    scheduler.emit(event(EVENT_JOB_MISSED))
    scheduler.emit(event(result=JobRun(1, "owner-job", "", "", status,
                                       "private result", "private error")))
    result = store.scheduler_results()["native-backup"]
    assert result["status"] == expected
    assert "private" not in str(result)


def test_successful_company_sweep_with_skipped_children_clears_failure(health):
    store, scheduler = health
    scheduler.emit(event(EVENT_JOB_ERROR))
    scheduler.emit(event(result={"ok": True, "swept": 1, "skipped": {"another-company": "not due"}}))
    assert store.scheduler_results()["native-backup"]["status"] == "ok"


def test_max_instances_and_listener_installation_are_not_lost(health):
    store, scheduler = health
    install_scheduler_health(scheduler, store)
    assert len(scheduler.listeners) == 1
    scheduler.emit(JobSubmissionEvent(EVENT_JOB_MAX_INSTANCES, "native-backup", "default", [datetime.now(UTC)]))
    assert store.scheduler_results()["native-backup"]["status"] == "max_instances"


def test_recording_failure_is_visible_and_does_not_escape_callback(health, monkeypatch):
    store, scheduler = health
    def fail(*args, **kwargs):
        raise RuntimeError("private database detail")
    with monkeypatch.context() as patch:
        patch.setattr(store, "record_scheduler_result", fail)
        scheduler.emit(event())
        assert scheduler._nerva_health_error is True
    scheduler.emit(event())
    assert scheduler._nerva_health_error is False


def test_another_job_success_cannot_hide_lost_health_evidence(health, monkeypatch):
    store, scheduler = health
    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")
    with monkeypatch.context() as patch:
        patch.setattr(store, "record_scheduler_result", fail)
        scheduler.emit(event(EVENT_JOB_ERROR))
    other = event()
    other.job_id = "other-job"
    scheduler.emit(other)
    assert scheduler._nerva_health_error is True
    scheduler.emit(event())
    assert scheduler._nerva_health_error is False


def test_history_is_bounded_and_rejects_unstructured_statuses(health):
    store, _scheduler = health
    for index in range(270):
        store.record_scheduler_result(f"job-{index}", "ok")
    assert len(store.scheduler_results()) == 256
    with pytest.raises(ValueError):
        store.record_scheduler_result("job", "private error text")


@pytest.mark.asyncio
async def test_caught_heartbeat_failure_has_explicit_result(tmp_path):
    from agents.core.heartbeat import HeartbeatScheduler
    async def fail(_agent):
        raise RuntimeError("private heartbeat details")
    result = await HeartbeatScheduler(str(tmp_path))._run_heartbeat("jarvis", SimpleNamespace(run_heartbeat=fail))
    assert result == {"_scheduler_status": "failed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["run_log_quick_scan", "run_log_hourly_scan", "run_log_daily_scan"])
async def test_caught_log_scan_failure_has_explicit_result(method):
    from agents.core.scheduler_service import SchedulerService
    def fail(*args, **kwargs):
        raise RuntimeError("private scan details")
    scanner = SimpleNamespace(quick_scan=fail, hourly_scan=fail, daily_scan=fail)
    service = SchedulerService(SimpleNamespace(get_setting=lambda key, default: default, log_scanner=scanner))
    assert await getattr(service, method)() == {"_scheduler_status": "failed"}


@pytest.mark.asyncio
async def test_caught_digest_build_failure_has_explicit_result(monkeypatch):
    from agents.core import scheduler_service
    def fail(*args, **kwargs):
        raise RuntimeError("private digest details")
    monkeypatch.setattr(scheduler_service, "build_evening_retro", fail)
    service = scheduler_service.SchedulerService(SimpleNamespace(autonomy_queue=object()))
    assert await service.run_daily_digest("evening") == {"_scheduler_status": "failed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("connected", [True, False])
async def test_refused_or_unconfigured_digest_is_a_delivery_failure(monkeypatch, connected):
    from agents.core import scheduler_service
    monkeypatch.setattr(scheduler_service, "build_evening_retro", lambda *args: "private digest")
    async def refuse(*args, **kwargs):
        return False
    orch = SimpleNamespace(autonomy_queue=object(), get_setting=lambda key, default: "123",
                           channels={"telegram": SimpleNamespace(send=refuse)} if connected else {})
    assert await scheduler_service.SchedulerService(orch).run_daily_digest("evening") == {"_scheduler_status": "failed"}


@pytest.mark.asyncio
async def test_caught_retention_failure_has_explicit_result(monkeypatch):
    from agents.core import retention
    from agents.core.scheduler_service import SchedulerService
    def fail(*args, **kwargs):
        raise RuntimeError("private retention details")
    monkeypatch.setattr(retention, "run_retention", fail)
    service = SchedulerService(SimpleNamespace(get_setting=lambda key, default: True))
    assert await service.run_retention_purge() == {"_scheduler_status": "failed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["run_retention_purge", "run_log_quick_scan", "run_log_hourly_scan", "run_log_daily_scan"])
async def test_disabled_native_jobs_are_explicitly_skipped(method):
    from agents.core.scheduler_service import SchedulerService
    service = SchedulerService(SimpleNamespace(get_setting=lambda key, default: False))
    assert await getattr(service, method)() == {"_scheduler_status": "skipped"}


@pytest.mark.asyncio
async def test_partial_memory_maintenance_failure_reaches_health(health):
    from agents.core.scheduler_service import SchedulerService
    store, scheduler = health
    async def consolidate(kind):
        return {}
    def fail(*args, **kwargs):
        raise RuntimeError("private decay details")
    living = SimpleNamespace(consolidate=consolidate)
    orch = SimpleNamespace(cognition=SimpleNamespace(sub_enabled=lambda key: True, module=lambda key: living),
                           decay=SimpleNamespace(ranking=fail), get_setting=lambda key, default: default)
    result = await SchedulerService(orch).run_memory_maintenance()
    scheduler.emit(event(result=result))
    assert store.scheduler_results()["native-backup"]["status"] == "failed"


@pytest.mark.asyncio
async def test_caught_worldview_failure_has_explicit_result(monkeypatch):
    from agents.core.memory.worldview_sync import WorldViewKGSync
    from agents.core.orchestrator import Orchestrator
    async def fail(*args, **kwargs):
        raise RuntimeError("private worldview details")
    monkeypatch.setattr(WorldViewKGSync, "sync", fail)
    orch = SimpleNamespace(plugins={"worldview": object()}, memory=object())
    assert await Orchestrator._run_worldview_kg_sync(orch) == {"_scheduler_status": "failed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [True, False])
@pytest.mark.parametrize("via_heartbeat", [True, False])
async def test_real_scheduler_events_reach_persistent_health(tmp_path, fails, via_heartbeat):
    import asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    store = JobStore(tmp_path / "real-events.db")
    if via_heartbeat:
        from agents.core.heartbeat import HeartbeatScheduler
        heartbeat = HeartbeatScheduler(str(tmp_path))
        heartbeat.start(SimpleNamespace(jobs=SimpleNamespace(store=store)))
        scheduler = heartbeat.scheduler
    else:
        scheduler = AsyncIOScheduler(timezone="UTC")
        install_scheduler_health(scheduler, store)
    completed = asyncio.Event()
    scheduler.add_listener(lambda event: completed.set(), EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    async def run():
        if fails:
            raise RuntimeError("private actual job failure")
        return {"ok": True}
    scheduler.add_job(run, "date", id="native-real")
    if not scheduler.running:
        scheduler.start()
    try:
        await asyncio.wait_for(completed.wait(), timeout=5)
        outcome = store.scheduler_results()["native-real"]
        assert outcome["status"] == ("failed" if fails else "ok")
        assert "private" not in str(outcome)
    finally:
        scheduler.shutdown(wait=False)
        store.close()
