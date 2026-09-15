import asyncio
from types import SimpleNamespace

import pytest

from agents.core.autonomy.jobs import (
    JobRunner,
    JobStore,
    blueprint_catalog,
    instantiate_blueprint,
    validate_action,
)


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


def test_options_persist_and_edit_without_resuming(store):
    j = store.create(
        name="bounded",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "hello"},
        options={"repeat": 2, "deliver": ["ntfy"]},
    )
    assert store.get(j.id).options == {"repeat": 2, "deliver": ["ntfy"]}
    store.pause(j.id, "owner")
    changed = store.edit(j.id, options={"repeat": 3, "deliver": []})
    assert changed.options["repeat"] == 3 and not changed.runnable


@pytest.mark.parametrize(
    "options",
    [
        {"repeat": True},
        {"repeat": 0},
        {"repeat": 10001},
        {"deliver": ["https://evil"]},
        {"deliver": ["ntfy", "ntfy"]},
        {"model": "anything"},
        {"workdir": "/tmp"},
    ],
)
def test_invalid_or_unsupported_options_rejected(store, options):
    with pytest.raises(ValueError):
        store.create(
            name="x",
            schedule_text="0 9 * * *",
            action={"type": "remind", "message": "x"},
            options=options,
        )


@pytest.mark.asyncio
async def test_repeat_is_hard_bound_even_manual_and_concurrent(store):
    sent = []

    async def send(text):
        await asyncio.sleep(0)
        sent.append(text)
        return True

    r = JobRunner(
        store,
        orch=SimpleNamespace(channels={"ntfy": SimpleNamespace(send=send)}),
        quiet=lambda: False,
        scheduler=lambda: None,
    )
    j = r.create(
        name="x",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "x"},
        options={"repeat": 1, "deliver": ["ntfy"]},
    )
    runs = await asyncio.gather(r.fire(j.id, force=True), r.fire(j.id, force=True))
    assert len(sent) == 1
    assert sorted(x.status for x in runs) == ["ok", "skipped"]
    assert not store.get(j.id).runnable
    assert (await r.fire(j.id, force=True)).status == "skipped"


def test_sixteen_typed_blueprints_validate():
    catalog = blueprint_catalog()
    assert len(catalog) == 16
    for spec in catalog:
        assert spec["fields"]
        params = {
            f["key"]: (f.get("default") or "example") for f in spec["fields"] if f.get("required")
        }
        _, _, action = instantiate_blueprint(spec["id"], params)
        assert validate_action(action) == []
    with pytest.raises(ValueError):
        instantiate_blueprint("price_watch", {"product": "desk", "threshold": "not a number"})


@pytest.mark.asyncio
async def test_tick_runs_only_due_once_and_does_not_compete_with_scheduler(store):
    r = JobRunner(store, orch=None, scheduler=lambda: None, quiet=lambda: False)
    j = r.create(
        name="x",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "x"},
        options={"deliver": []},
    )
    from datetime import datetime

    from tzlocal import get_localzone

    now = datetime(2026, 9, 15, 9, 0, tzinfo=get_localzone())
    assert len(await r.tick(now)) == 1
    assert await r.tick(now) == []
    assert len(store.runs(j.id)) == 1


def test_numeric_blueprint_cli_parameter_and_cron_ranges(store):
    _, _, action = instantiate_blueprint("price_watch", {"product": "desk", "threshold": "123.50"})
    assert "123.5" in action["prompt"]


def test_cron_ranges_rejected(store):
    with pytest.raises(ValueError):
        store.create(
            name="bad", schedule_text="0 99 * * *", action={"type": "remind", "message": "x"}
        )


@pytest.mark.asyncio
async def test_delivery_preflight_and_held_stop(store, monkeypatch):
    from agents.core import estop

    sent = []

    async def send(text):
        sent.append(text)
        return True

    r = JobRunner(
        store,
        orch=SimpleNamespace(channels={"ntfy": SimpleNamespace(send=send)}),
        scheduler=lambda: None,
        quiet=lambda: False,
    )
    j = r.create(
        name="x",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "x"},
        options={"deliver": ["ntfy", "missing"]},
    )
    assert (await r.fire(j.id)).status == "failed"
    assert sent == []


@pytest.mark.asyncio
async def test_held_delivery_honors_estop(store, monkeypatch):
    from agents.core import estop

    async def send(text):
        return True

    r = JobRunner(
        store,
        orch=SimpleNamespace(channels={"ntfy": SimpleNamespace(send=send)}),
        scheduler=lambda: None,
        quiet=lambda: False,
    )
    store.hold("job", "held", "ntfy")
    monkeypatch.setattr(estop, "check_paused", lambda *_: True)
    assert await r.flush_held() == 0
    assert store.held_count() == 1


def test_delete_cancels_pending_delivery_and_tick_marker(store):
    job = store.create(
        name="x", schedule_text="0 9 * * *", action={"type": "remind", "message": "x"}
    )
    store.hold(job.id, "pending", "ntfy")
    store.claim_tick(job.id, "2026-09-15T09:00:00+00:00")
    assert store.delete(job.id)
    assert store.held_count() == 0
    assert store.claim_tick(job.id, "2026-09-15T09:00:00+00:00")


def test_update_never_replays_attempts_reserved_by_another_connection(store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    other = JobStore(store._path)
    job = store.create(
        name="bounded",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "x"},
        options={"repeat": 1},
    )
    read, release = Event(), Event()
    original_get = store.get

    def delayed_get(job_id):
        snapshot = original_get(job_id)
        read.set()
        assert release.wait(3)
        return snapshot

    monkeypatch.setattr(store, "get", delayed_get)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            updating = pool.submit(store.update, job.id, notepad="memo")
            assert read.wait(3)
            assert other.reserve_attempt(job.id)
            release.set()
            updating.result(timeout=3)
        assert other.get(job.id).attempts == 1
        assert not other.reserve_attempt(job.id)
        assert other.get(job.id).notepad == "memo"
    finally:
        release.set()
        other.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "instant",
    [
        "2026-03-28T07:00:00+00:00",
        "2026-03-29T06:00:00+00:00",
        "2026-10-24T06:00:00+00:00",
        "2026-10-25T07:00:00+00:00",
    ],
)
async def test_tick_uses_scheduler_wall_clock_across_dst(store, instant):
    from datetime import datetime

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="Europe/Bucharest")
    runner = JobRunner(store, orch=None, scheduler=lambda: scheduler, quiet=lambda: False)
    runner.create(
        name="nine",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "x"},
        options={"deliver": []},
    )
    runs = await runner.tick(datetime.fromisoformat(instant))
    assert len(runs) == 1 and runs[0].status == "ok"
    assert await runner.tick(datetime.fromisoformat(instant)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["brief", "remind"])
async def test_history_only_preserves_bounded_generated_result(store, monkeypatch, kind):
    from agents.core.autonomy.jobs import MAX_TEXT

    text = "UNIQUE_OUTPUT" + "z" * MAX_TEXT
    runner = JobRunner(store, orch=None, scheduler=lambda: None, quiet=lambda: False)

    async def brief(_):
        return text

    monkeypatch.setattr(runner, "_brief", brief)
    action = (
        {"type": "brief", "kind": "morning"}
        if kind == "brief"
        else {"type": "remind", "message": text[:MAX_TEXT]}
    )
    job = runner.create(
        name="history", schedule_text="0 9 * * *", action=action, options={"deliver": []}
    )
    run = await runner.fire(job.id)
    assert run.status == "ok"
    assert run.summary.startswith("UNIQUE_OUTPUT")
    assert len(run.summary) <= MAX_TEXT
    assert store.runs(job.id)[0].summary == run.summary
