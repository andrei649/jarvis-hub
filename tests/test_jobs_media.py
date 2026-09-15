"""Owner media reminders use captured bytes and durable delivery receipts."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.artifact_store import BinaryArtifactStore
from agents.core.autonomy.jobs import JobRunner, JobStore, validate_action

PDF = b"%PDF-1.7\nowner report\n%%EOF"


class Adapter:
    token = "fixture-token"
    api_base = "https://api.telegram.org/botfixture-token"

    def __init__(self):
        self.calls = []

    async def send_media(self, data, *, mime, filename, chat_id):
        self.calls.append(("media", data, mime, filename, chat_id))
        return True

    async def send_scheduled_text(self, text, **kwargs):
        self.calls.append(("text", text, kwargs))
        return True


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from agents.core import estop
    from agents.core.channels import send_rate_limit

    monkeypatch.setenv("JARVIS_BINARY_ARTIFACTS", "1")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    monkeypatch.setattr(estop, "check_paused", lambda *args: False)
    monkeypatch.setattr(send_rate_limit, "allow_send", lambda channel: True)
    item = BinaryArtifactStore(tmp_path).put(PDF)
    adapter = Adapter()
    settings = {"autonomy.owner_chat_id": "123", "jobs.media_send_timeout_seconds": 300}
    audit = []

    def log(kind, fields):
        audit.append((kind, fields))
        return "logged"

    orch = SimpleNamespace(
        channels={"telegram": adapter},
        get_setting=lambda key, default=None: settings.get(key, default),
        action_audit=SimpleNamespace(log=log),
    )
    store = JobStore(tmp_path / "jobs.db")
    runner = JobRunner(store, orch=orch, scheduler=lambda: None, quiet=lambda: False)
    return SimpleNamespace(
        runner=runner,
        store=store,
        adapter=adapter,
        item=item,
        settings=settings,
        audit=audit,
        orch=orch,
    )


def create(s, **changes):
    action = {"type": "remind", "message": "owner report", "media_ids": [s.item["id"]], **changes}
    return s.runner.create(name="report", schedule_text="0 9 * * *", action=action)


@pytest.mark.parametrize(
    "ids",
    [
        [],
        ["../secret"],
        ["https://remote"],
        ["ba-" + "a" * 32] * 2,
        ["ba-" + "a" * 32] * 9,
        "not-list",
    ],
)
def test_media_fields_are_strict(ids):
    assert validate_action({"type": "remind", "message": "report", "media_ids": ids})


@pytest.mark.asyncio
async def test_actual_job_delivers_bound_bytes_and_text_and_reports_sent(setup):
    s = setup
    job = create(s)
    run = await s.runner.fire(job.id)
    assert run.status == "ok"
    assert [call[0] for call in s.adapter.calls] == ["media", "text"]
    assert s.adapter.calls[0][1] == PDF
    assert s.adapter.calls[0][-1] == 123
    assert len(s.audit) == 2
    assert s.runner.media.public(job.id)["status"] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["recipient", "token", "bytes"])
async def test_changed_authorization_refuses_before_any_send(setup, change):
    s = setup
    job = create(s)
    if change == "recipient":
        s.settings["autonomy.owner_chat_id"] = "999"
    elif change == "token":
        s.adapter.token = "changed"
    else:
        from agents.core.paths import data_root

        # Use the actual store's private locator, never a production API path.
        store = BinaryArtifactStore(data_root())
        store.remove(s.item["id"])
    result = await s.runner.fire(job.id)
    assert result.status == "failed"
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_total_timeout_is_unknown_and_cannot_be_replayed_after_restart(setup):
    s = setup
    s.settings["jobs.media_send_timeout_seconds"] = 1
    job = create(s)

    async def stalls(*args, **kwargs):
        s.adapter.calls.append(("started",))
        await asyncio.sleep(5)

    s.adapter.send_media = stalls
    result = await s.runner.fire(job.id)
    assert result.status == "failed"
    assert s.runner.media.public(job.id)["status"] == "unknown"
    assert s.store.get(job.id).paused_reason
    s.runner = JobRunner(s.store, orch=s.orch, scheduler=lambda: None, quiet=lambda: False)
    s.store.update(job.id, paused_reason=None)
    await s.runner.fire(job.id)
    assert s.adapter.calls == [("started",)]


@pytest.mark.asyncio
async def test_quiet_hold_keeps_original_binding_across_edit(setup):
    s = setup
    s.runner._quiet = lambda: True
    job = create(s)
    assert (await s.runner.fire(job.id)).status == "ok"
    assert not s.adapter.calls
    s.runner.edit(
        job.id, action={"type": "remind", "message": "changed", "media_ids": [s.item["id"]]}
    )
    s.runner._quiet = lambda: False
    await s.runner.flush_held()
    assert not s.adapter.calls


@pytest.mark.asyncio
async def test_partial_send_is_durable_and_no_automatic_retry(setup, monkeypatch):
    s = setup
    other = BinaryArtifactStore().put(PDF + b"\nsecond")
    job = create(s, media_ids=[s.item["id"], other["id"]])
    calls = 0

    async def send(data, **kwargs):
        nonlocal calls
        calls += 1
        s.adapter.calls.append(("media", data))
        if calls == 1:
            s.settings["autonomy.owner_chat_id"] = "456"
        return True

    s.adapter.send_media = send
    assert (await s.runner.fire(job.id)).status == "failed"
    # Recipient changes during an in-flight send make its acknowledgement ambiguous.
    assert s.runner.media.public(job.id)["status"] == "unknown"
    assert calls == 1


@pytest.mark.asyncio
async def test_held_destination_change_reports_failure_without_sending(setup):
    s = setup
    job = create(s)
    s.runner._quiet = lambda: True
    await s.runner.fire(job.id)
    s.settings["autonomy.owner_chat_id"] = "456"
    s.runner._quiet = lambda: False
    await s.runner.flush_held()
    assert s.runner.media.public(job.id)["status"] == "failed"
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_actual_telegram_media_transport_is_one_fixed_bytes_request(monkeypatch):
    import httpx

    from agents.core.channels.telegram import TelegramChannel

    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})

    channel = TelegramChannel("fixture-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert await channel.send_media(
            PDF, mime="application/pdf", filename="ba-" + "a" * 32, chat_id=123
        )
        assert len(calls) == 1 and calls[0].url.path.endswith("/sendDocument")
        assert PDF in calls[0].content and b"123" in calls[0].content
        assert not await channel.send_media(
            PDF, mime="application/pdf", filename="../secret", chat_id=123
        )
        assert len(calls) == 1
    finally:
        await channel.client.aclose()


@pytest.mark.parametrize("value", [0, 301, True, "300", 1.5])
def test_invalid_deadline_refuses_authoring(setup, value):
    setup.settings["jobs.media_send_timeout_seconds"] = value
    with pytest.raises(ValueError, match="deadline"):
        create(setup)


@pytest.mark.asyncio
async def test_missing_audit_refuses_media(setup):
    s = setup
    job = create(s)
    s.orch.action_audit = None
    assert (await s.runner.fire(job.id)).status == "failed"
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_admin_route_job_and_adapter_flow_reports_effective_status(setup, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from agents import web
    from agents.core.channels.telegram import TelegramChannel
    from agents.core.routers import jobs

    s = setup
    requests = []

    async def telegram_response(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(requests)}})

    channel = TelegramChannel("fixture-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(telegram_response))
    s.orch.channels["telegram"] = channel
    s.orch.jobs = s.runner
    monkeypatch.setattr(jobs, "get_orch", lambda: s.orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-fixture")
    app = FastAPI()
    app.include_router(jobs.router)
    body = {
        "name": "report",
        "schedule_text": "0 9 * * *",
        "action": {"type": "remind", "message": "report", "media_ids": [s.item["id"]]},
    }
    async with (
        channel.client,
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client,
    ):
        assert (await client.post("/api/jobs", json=body)).status_code in (401, 403)
        headers = {"X-Admin-Token": "owner-fixture"}
        created = await client.post("/api/jobs", json=body, headers=headers)
        assert created.status_code == 201
        job_id = created.json()["job"]["id"]
        response = await client.post(f"/api/jobs/{job_id}/run", headers=headers)
        assert response.status_code == 202
        await s.runner.drain_manual()
        result = (await client.get(f"/api/jobs/{job_id}", headers=headers)).json()["job"]
        assert result["media_delivery"] == {"status": "sent", "sent": 2, "total": 2, "reason": ""}
        assert "fixture-token" not in str(result) and "bot" not in result
        assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
            "sendDocument",
            "sendMessage",
        ]
        assert PDF in requests[0].content
        assert b'"chat_id":123' in requests[1].content


@pytest.mark.asyncio
async def test_estop_interrupts_a_stalled_send_before_deadline(setup, monkeypatch):
    from agents.core import estop

    s = setup
    job = create(s)
    started = asyncio.Event()
    stopped = False

    async def stall(*args, **kwargs):
        started.set()
        await asyncio.sleep(10)

    s.adapter.send_media = stall
    monkeypatch.setattr(estop, "check_paused", lambda *args: stopped)
    task = asyncio.create_task(s.runner.fire(job.id))
    await started.wait()
    stopped = True
    result = await asyncio.wait_for(task, 0.5)
    assert result.status == "failed"
    assert s.runner.media.public(job.id)["status"] == "unknown"


def test_deadline_setting_is_registered_and_can_be_persisted(tmp_path, monkeypatch):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    assert settings_db.validate_category("jobs", {"media_send_timeout_seconds": 1.5})
    assert settings_db.validate_category("jobs", {"media_send_timeout_seconds": 301})
    assert not settings_db.validate_category("jobs", {"media_send_timeout_seconds": 120})
    assert settings_db.put_category("jobs", {"media_send_timeout_seconds": 120}) == (1, [])
    assert settings_db.get_value("jobs", "media_send_timeout_seconds") == 120


@pytest.mark.asyncio
async def test_one_deadline_covers_two_media_sends_and_records_first_ack(setup):
    s = setup
    s.settings["jobs.media_send_timeout_seconds"] = 1
    other = BinaryArtifactStore().put(PDF + b"\nother")
    job = create(s, media_ids=[s.item["id"], other["id"]])

    async def slow(data, **kwargs):
        s.adapter.calls.append(("media", data))
        await asyncio.sleep(0.65)
        return True

    s.adapter.send_media = slow
    assert (await s.runner.fire(job.id)).status == "failed"
    status = s.runner.media.public(job.id)
    assert status["status"] == "unknown" and status["sent"] == 1
    assert len(s.adapter.calls) == 2


@pytest.mark.asyncio
async def test_held_delivery_survives_recreated_runner_and_sends_once(setup):
    s = setup
    job = create(s)
    s.runner._quiet = lambda: True
    await s.runner.fire(job.id)
    restarted = JobRunner(
        JobStore(s.store._path), orch=s.orch, scheduler=lambda: None, quiet=lambda: False
    )
    assert await restarted.flush_held() == 1
    assert await restarted.flush_held() == 0
    assert len(s.adapter.calls) == 2


@pytest.mark.asyncio
async def test_rate_refusal_after_first_ack_is_partial_not_retryable(setup, monkeypatch):
    from agents.core.channels import send_rate_limit

    s = setup
    job = create(s)
    checks = []
    monkeypatch.setattr(
        send_rate_limit, "allow_send", lambda name: not checks.append(name) and len(checks) == 1
    )
    assert (await s.runner.fire(job.id)).status == "failed"
    assert s.runner.media.public(job.id)["status"] == "partial"
    assert len(s.adapter.calls) == 1


@pytest.mark.asyncio
async def test_changed_captured_catalog_content_is_refused(setup, tmp_path, monkeypatch):
    from agents.core.media_catalog import MediaCatalog

    s = setup
    monkeypatch.setenv("JARVIS_MEDIA_CATALOG", "1")
    folder = tmp_path / "media" / "cache"
    folder.mkdir(parents=True)
    path = folder / "report.pdf"
    path.write_bytes(PDF)
    row = MediaCatalog(tmp_path / "media" / "catalog.json").add(
        kind="image", path=str(path), prompt="report", now=1
    )
    job = create(s, media_ids=[row["id"]])
    path.write_bytes(PDF + b"\nchanged")
    assert (await s.runner.fire(job.id)).status == "failed"
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_explicit_empty_options_clear_history_only_before_media_binding(setup):
    s = setup
    job = s.runner.create(
        name="history",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "report"},
        options={"deliver": []},
    )
    edited = s.runner.edit(
        job.id,
        action={"type": "remind", "message": "report", "media_ids": [s.item["id"]]},
        options={},
    )
    assert edited.options == {}
    assert (await s.runner.fire(job.id)).status == "ok"
    assert [call[0] for call in s.adapter.calls] == ["media", "text"]


@pytest.mark.asyncio
async def test_paused_held_receipt_waits_for_explicit_resume(setup):
    s = setup
    s.runner.quiet_hours = lambda: True
    job = create(s)
    await s.runner.fire(job.id)
    s.store.update(job.id, paused_reason="owner paused")
    s.runner.quiet_hours = lambda: False
    assert await s.runner.media.flush_held() == 0
    assert s.runner.media.public(job.id)["status"] == "held"
    s.store.update(job.id, paused_reason=None)
    assert await s.runner.media.flush_held() == 1


@pytest.mark.asyncio
async def test_cancel_resistant_transport_cannot_ack_or_continue_abandoned_delivery(setup):
    s = setup
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stubborn(*args, **kwargs):
        s.adapter.calls.append(("media",))
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return True

    s.adapter.send_media = stubborn
    job = create(s)
    delivery = asyncio.create_task(s.runner.media.deliver(job, job.action["message"]))
    await entered.wait()
    delivery.cancel()
    with pytest.raises(asyncio.CancelledError):
        await delivery
    await cancelled.wait()
    assert s.runner.media.public(job.id)["status"] == "unknown"
    # Even an explicit resume during late transport cleanup cannot revive this receipt.
    s.store.update(job.id, paused_reason=None)
    release.set()
    await asyncio.gather(*list(s.runner.media._tasks), return_exceptions=True)
    assert s.runner.media.public(job.id)["status"] == "unknown"
    assert [call[0] for call in s.adapter.calls] == ["media"]


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_result", ["sent", "deleted"])
async def test_held_snapshot_cannot_replay_receipt_changed_before_gate(setup, concurrent_result):
    import contextlib

    s = setup
    s.runner._quiet = lambda: True
    job = create(s)
    await s.runner.fire(job.id)
    s.runner._quiet = lambda: False
    other = JobStore(s.store._path)
    original_gate = s.runner.media._gate

    @contextlib.contextmanager
    def interleaved_gate(job_id):
        # A separate dispatcher owns/completes this receipt after the held snapshot.
        with other._lock, other._conn:
            if concurrent_result == "sent":
                other._conn.execute(
                    "UPDATE job_media_receipts SET status='sent' WHERE job_id=?", (job_id,)
                )
            else:
                other._conn.execute("DELETE FROM job_media_receipts WHERE job_id=?", (job_id,))
        with original_gate(job_id):
            yield

    s.runner.media._gate = interleaved_gate
    assert await s.runner.media.flush_held() == 0
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_paused_held_backlog_does_not_starve_runnable_delivery(setup):
    s = setup
    s.runner._quiet = lambda: True
    for _ in range(5):
        job = create(s)
        for _ in range(20):
            await s.runner.media.deliver(job, job.action["message"])
        s.store.update(job.id, paused_reason="owner paused")
    ready = create(s)
    await s.runner.media.deliver(ready, ready.action["message"])
    s.runner._quiet = lambda: False
    assert await s.runner.media.flush_held() == 1
    assert s.runner.media.public(ready.id)["status"] == "sent"


@pytest.mark.asyncio
async def test_scheduled_text_has_no_http400_fallback(setup, monkeypatch):
    import httpx

    from agents.core import estop
    from agents.core.channels.telegram import TelegramChannel

    s = setup
    requests = []
    stopped = False

    async def response(request):
        nonlocal stopped
        requests.append(request)
        if request.url.path.endswith("sendMessage"):
            stopped = True
            return httpx.Response(400, json={"ok": False})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    channel = TelegramChannel("fixture-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    s.orch.channels["telegram"] = channel
    monkeypatch.setattr(estop, "check_paused", lambda *args: stopped)
    async with channel.client:
        job = create(s)
        assert (await s.runner.fire(job.id)).status == "failed"
        assert len(requests) == 2  # exactly one file request, one text request
        assert s.runner.media.public(job.id)["status"] == "unknown"


@pytest.mark.asyncio
async def test_total_deadline_includes_resolution_and_late_read_cannot_send(setup):
    import threading

    s = setup
    s.settings["jobs.media_send_timeout_seconds"] = 1
    job = create(s)
    release = threading.Event()
    original_read = s.runner.media._read

    def delayed_read(ids):
        release.wait(3)
        return original_read(ids)

    s.runner.media._read = delayed_read
    try:
        assert (await s.runner.fire(job.id)).status == "failed"
        assert s.runner.media.public(job.id)["status"] == "failed"
        assert s.adapter.calls == []
    finally:
        release.set()
        await asyncio.gather(*list(s.runner.media._tasks), return_exceptions=True)
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_total_deadline_includes_associated_text_after_file_ack(setup):
    s = setup
    s.settings["jobs.media_send_timeout_seconds"] = 1

    async def slow_text(*args, **kwargs):
        s.adapter.calls.append(("text",))
        await asyncio.sleep(5)
        return True

    s.adapter.send_scheduled_text = slow_text
    job = create(s)
    assert (await s.runner.fire(job.id)).status == "failed"
    result = s.runner.media.public(job.id)
    assert result["status"] == "unknown" and result["sent"] == 1
    assert [call[0] for call in s.adapter.calls] == ["media", "text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        [],
        {"ok": True},
        {"ok": True, "result": {}},
        {"ok": True, "result": {"message_id": True}},
        {"ok": True, "result": {"message_id": 0}},
    ],
)
async def test_scheduled_telegram_requires_exact_positive_ack(body):
    import httpx

    from agents.core.channels.telegram import TelegramChannel

    channel = TelegramChannel("fixture-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    )
    async with channel.client:
        assert not await channel.send_scheduled_text("report", chat_id=123)
        assert not await channel.send_media(
            PDF, mime="application/pdf", filename="ba-" + "a" * 32, chat_id=123
        )


@pytest.mark.asyncio
async def test_transport_secrets_never_enter_run_history_or_logs(setup, caplog):
    s = setup

    async def failure(*args, **kwargs):
        raise RuntimeError("request failed https://api.telegram.org/botfixture-secret/sendDocument")

    s.adapter.send_media = failure
    job = create(s)
    result = await s.runner.fire(job.id)
    assert result.status == "failed"
    assert "fixture-secret" not in str(result) + caplog.text
    assert s.runner.media.public(job.id)["reason"] == "media delivery failed"


@pytest.mark.asyncio
async def test_stale_runner_snapshot_cannot_use_new_action_authorization(setup):
    s = setup
    old = create(s, message="old message")
    s.runner.edit(old.id, action={**old.action, "message": "new message"})
    with pytest.raises(ValueError, match="authorization"):
        await s.runner.media.deliver(old, "old message")
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_reminder_text_must_match_bound_owner_message(setup):
    s = setup
    job = create(s)
    with pytest.raises(ValueError, match="authorization"):
        await s.runner.media.deliver(job, "unbound replacement")
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_dispatch_lookup_consumes_same_deadline_before_network(setup, monkeypatch):
    import time

    from agents.core.autonomy import jobs_media

    s = setup
    job = create(s)
    clock = [0.0]
    monkeypatch.setattr(
        jobs_media, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time)
    )
    original_binding = s.runner.media._binding

    def slow_lookup(job_id):
        value = original_binding(job_id)
        clock[0] += 301
        return value

    s.runner.media._binding = slow_lookup
    assert (await s.runner.fire(job.id)).status == "failed"
    assert s.adapter.calls == []


@pytest.mark.asyncio
async def test_reauthorization_preserves_superseded_interrupted_receipt_as_unknown(setup):
    s = setup
    job = create(s)
    s.runner._quiet = lambda: True
    await s.runner.fire(job.id)
    with s.store._lock, s.store._conn:
        s.store._conn.execute(
            "UPDATE job_media_receipts SET status='sending' WHERE job_id=?", (job.id,)
        )
        receipt = s.store._conn.execute(
            "SELECT id FROM job_media_receipts WHERE job_id=?", (job.id,)
        ).fetchone()[0]
    s.runner.edit(job.id, action=job.action)
    assert s.runner.media._receipt(receipt)["status"] == "unknown"
    s.runner.media._failure(receipt, "late cleanup")
    assert s.runner.media._receipt(receipt)["status"] == "unknown"
