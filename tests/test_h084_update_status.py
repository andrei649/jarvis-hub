"""Owner update status projects recorded progress without applying an update."""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

from agents.core.commands import ADMIN, CommandContext, Principal, build_default_registry
from agents.core.update_commands import update_command


@pytest.fixture(autouse=True)
def private_test_directory(tmp_path):
    old = os.umask(0o077)
    tmp_path.chmod(0o700)
    try:
        yield
    finally:
        os.umask(old)


def _ctx(*, task=None, args="status", owner=True, channel="web", queue=None):
    if queue is None:
        queue = SimpleNamespace(list=lambda **_kwargs: [] if task is None else [task])
    orch = SimpleNamespace(autonomy_queue=queue, autonomy=SimpleNamespace(queue=queue))
    principal = Principal(channel=channel, admin=owner)
    return CommandContext(orch, principal, "update", args)


def _task(status="done", task_id=17):
    return SimpleNamespace(id=task_id, kind="hub.update", agent="owner", status=status)


def _snapshot(*, current=None, last=None):
    from agents.core.update_progress import ProgressSnapshot

    return ProgressSnapshot(current=current, last=last)


def _record(*, kind="update", task_id=17, phase="verified", result="verified"):
    from agents.core.update_progress import ProgressRecord

    return ProgressRecord(kind=kind, task_id=task_id, phase=phase, result=result)


@pytest.mark.asyncio
async def test_status_is_registered_owner_command_and_does_not_enqueue(monkeypatch):
    from agents.core import update_progress

    registry = build_default_registry()
    command = registry.get("update")
    assert command.tier == ADMIN and command.usage == "[status]"
    monkeypatch.setattr(update_progress, "read_progress_snapshot", lambda: _snapshot())
    from agents.core import hub_update_apply

    monkeypatch.setattr(hub_update_apply, "request_apply",
                        lambda *_a, **_kw: pytest.fail("status queued an update"))
    reply = await update_command(_ctx())
    assert "No update activity is recorded" in reply
    assert "up to date" not in reply.lower()


@pytest.mark.asyncio
async def test_status_keeps_existing_owner_and_argument_gates(monkeypatch):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot",
                        lambda: pytest.fail("forbidden status read"))
    assert "owner" in (await update_command(_ctx(owner=False))).lower()
    assert "chat" in (await update_command(_ctx(channel="api"))).lower()
    assert "Usage" in await update_command(_ctx(args="status now"))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [
    ("blocked", "waiting for human approval"),
    ("proposed", "waiting for human approval"),
    ("approved", "approved"),
    ("running", "recorded as running"),
    ("failed", "recorded as failed"),
    ("rejected", "rejected"),
    ("deferred", "deferred"),
    ("quarantined", "quarantined"),
    ("expired", "expired"),
])
async def test_latest_card_state_uses_fixed_vocabulary(monkeypatch, status, expected):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot", lambda: _snapshot())
    reply = await update_command(_ctx(task=_task(status)))
    assert "#17" in reply and expected in reply
    assert len(reply) <= 512


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,result,expected", [
    ("started", None, "preparing"),
    ("backed_up", None, "backup complete"),
    ("fast_forwarded", None, "applying"),
    ("dependencies_installed", None, "applying"),
    ("restarting", None, "restart requested"),
    ("verifying", None, "checking the new boot"),
    ("rolling_back", None, "rolling back"),
    ("rolled_back_restarting", None, "rollback restart requested"),
    ("verified", "verified", "verified"),
    ("rolled_back", "rolled_back", "rolled back"),
    ("rollback_incomplete", "rollback_incomplete", "operator attention"),
    ("rollback_failed", "rollback_failed", "operator attention"),
    ("failed", "failed", "failed"),
    ("refused", "refused", "refused"),
])
async def test_matching_record_projects_only_known_progress(monkeypatch, phase, result, expected):
    from agents.core import update_progress

    record = _record(phase=phase, result=result)
    snapshot = _snapshot(current=record) if result is None else _snapshot(last=record)
    monkeypatch.setattr(update_progress, "read_progress_snapshot", lambda: snapshot)
    reply = await update_command(_ctx(task=_task("running" if result is None else "done")))
    assert "Recorded update status for card #17" in reply and expected in reply
    assert len(reply) <= 512


@pytest.mark.asyncio
async def test_new_card_never_inherits_older_receipt_success(monkeypatch):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot",
                        lambda: _snapshot(last=_record(task_id=16)))
    reply = await update_command(_ctx(task=_task("done", 17)))
    assert "final verification unavailable" in reply.lower()
    assert "verified" not in reply.lower()


@pytest.mark.asyncio
async def test_newer_current_operation_hides_an_older_matching_success(monkeypatch):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot", lambda: _snapshot(
        current=_record(task_id=18, phase="restarting", result=None),
        last=_record(task_id=17),
    ))
    reply = await update_command(_ctx(task=_task("done", 17)))
    assert "final verification unavailable" in reply.lower()
    assert "verified" not in reply.lower()


@pytest.mark.asyncio
async def test_done_card_with_only_restart_marker_has_no_final_verification(monkeypatch):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot",
                        lambda: _snapshot(last=_record(phase="restarting", result=None)))
    reply = await update_command(_ctx(task=_task("done")))
    assert "final verification unavailable" in reply.lower()
    assert "verified" not in reply.lower()


@pytest.mark.asyncio
async def test_no_card_labels_latest_receipt_as_last_recorded(monkeypatch):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot",
                        lambda: _snapshot(last=_record(kind="rollback", task_id=None,
                                                       phase="rolled_back", result="rolled_back")))
    reply = await update_command(_ctx())
    assert "Last recorded operation" in reply and "rolled back" in reply


@pytest.mark.asyncio
async def test_store_and_queue_failures_are_unavailable_and_do_not_leak(monkeypatch):
    from agents.core import update_progress

    def broken():
        raise update_progress.UpdateProgressUnavailable("secret/path")

    monkeypatch.setattr(update_progress, "read_progress_snapshot", broken)
    reply = await update_command(_ctx())
    assert "unavailable" in reply.lower() and "secret" not in reply

    def broken_list(**_kwargs):
        raise RuntimeError("secret queue")

    reply = await update_command(_ctx(queue=SimpleNamespace(list=broken_list)))
    assert "unavailable" in reply.lower() and "secret" not in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("task", [
    _task("unknown"), _task("done", True),
    SimpleNamespace(id=17, kind="other", agent="owner", status="done"),
    SimpleNamespace(id=17, kind="hub.update", agent="agent", status="done"),
])
async def test_malformed_latest_card_is_unavailable(monkeypatch, task):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot", lambda: _snapshot())
    assert "unavailable" in (await update_command(_ctx(task=task))).lower()


@pytest.mark.asyncio
async def test_queue_must_be_the_orchestrators_bound_queue(monkeypatch):
    from agents.core import update_progress

    monkeypatch.setattr(update_progress, "read_progress_snapshot",
                        lambda: pytest.fail("unbound queue read"))
    ctx = _ctx()
    ctx.orch.autonomy_queue = object()
    assert "unavailable" in (await update_command(ctx)).lower()


@pytest.mark.asyncio
async def test_queue_replacement_during_read_withholds_stale_status(monkeypatch):
    from agents.core import update_progress

    ctx = _ctx(task=_task("blocked"))

    def replace_during_read():
        ctx.orch.autonomy_queue = object()
        return _snapshot()

    monkeypatch.setattr(update_progress, "read_progress_snapshot", replace_during_read)
    assert "unavailable" in (await update_command(ctx)).lower()


@pytest.mark.asyncio
async def test_status_reads_queue_and_progress_off_event_loop(monkeypatch):
    from agents.core import update_progress

    main = threading.current_thread()
    calls = []

    def queue_list(**kwargs):
        calls.append(("queue", threading.current_thread(), kwargs))
        return [_task("blocked")]

    def reader():
        calls.append(("record", threading.current_thread(), None))
        return _snapshot()

    monkeypatch.setattr(update_progress, "read_progress_snapshot", reader)
    reply = await update_command(_ctx(queue=SimpleNamespace(list=queue_list)))
    assert "waiting for human approval" in reply
    assert [row[0] for row in calls] == ["queue", "record"]
    assert calls[0][1] is not main and calls[1][1] is not main
    assert calls[0][2] == {"kind": "hub.update", "limit": 1}
