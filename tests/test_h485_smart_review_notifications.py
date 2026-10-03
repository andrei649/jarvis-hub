"""Guardian review precedes unsolicited terminal approval notifications."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from agents.core.ambient.policy import AttentionDeliveryBroker, AttentionLedger
from agents.core.autonomy.worker import AutonomyWorker
from tests.test_h485_smart_observer_dispatch import (
    _wire,
    isolated_settings,  # noqa: F401 — isolated settings fixture
    queue,  # noqa: F401 — signed SQLite fixture
)
from tests.test_h485_smart_review_waiting_integration import _settle


def _worker(queue, tmp_path, handler):
    delivered = []

    async def notify(task):
        delivered.append(task)
        return True

    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=4)
    worker = AutonomyWorker(queue, notifier=notify, delivery_broker=AttentionDeliveryBroker(ledger))
    judge, _unused = _wire(queue, handler)
    worker.attach_approval_judge(judge, loop=asyncio.get_running_loop())
    return worker, delivered


def _payload(command="printf hello"):
    return {"tool": "terminal_run", "target": "terminal_run",
            "args": {"target": "dev", "command": command}}


async def _finish(worker):
    await _settle(worker.approval_judge)
    if worker._bg_tasks:
        await asyncio.gather(*tuple(worker._bg_tasks), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["APPROVE", "ESCALATE"])
async def test_governed_enqueue_holds_push_until_native_verdict(queue, tmp_path, reply):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review command",
                                   payload=_payload(), risk_tier=3)
    try:
        await started.wait()
        assert delivered == [], "the human card escaped before the native review"
    finally:
        release.set()
        await _finish(worker)
    if reply == "APPROVE":
        assert queue.get(task_id).status == "approved"
        assert delivered == []
        assert not queue.get(task_id).pushed
    else:
        assert [task.id for task in delivered] == [task_id]
        assert queue.get(task_id).status == "blocked"
        assert worker.approval_judge.project(queue.get(task_id))["judge"]["decision"] == "escalate"


@pytest.mark.asyncio
async def test_async_submit_waits_without_sending_before_native_review(queue, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    submission = asyncio.create_task(worker.submit("jarvis", "toolrpc.terminal_run", "Review",
                                                   _payload(), risk_tier=3))
    try:
        await started.wait()
        assert delivered == []
        assert not submission.done()
    finally:
        release.set()
        task = await submission
        await _finish(worker)
    assert queue.get(task.id).status == "approved"
    assert delivered == []


@pytest.mark.asyncio
async def test_edited_task_release_uses_fresh_card_instead_of_pre_wait_bytes(queue, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ESCALATE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await started.wait()
        queue.update_payload(task_id, _payload("printf edited"))
    finally:
        release.set()
        await _finish(worker)
    assert [task.payload["args"]["command"] for task in delivered] == ["printf edited"]
    assert queue.get(task_id).status == "blocked"
    assert "judge" not in worker.approval_judge.project(queue.get(task_id))


@pytest.mark.asyncio
async def test_unrelated_manual_card_is_not_held_by_terminal_guardian(queue, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ESCALATE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    terminal = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await started.wait()
        other = worker.govern_enqueue("jarvis", "delete_file", "Manual task", payload={"path": "old"})
        await asyncio.sleep(0)
        assert [task.id for task in delivered] == [other]
    finally:
        release.set()
        await _finish(worker)
    assert {task.id for task in delivered} == {other, terminal}


@pytest.mark.asyncio
async def test_smart_default_off_preserves_immediate_manual_notification(queue, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SMART_APPROVALS", "0")
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"risk":10,"why":"Review"}'}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await started.wait()
        assert [task.id for task in delivered] == [task_id]
    finally:
        release.set()
        await _finish(worker)


@pytest.mark.asyncio
async def test_owner_decision_during_review_suppresses_obsolete_notification(queue, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await started.wait()
        await worker.apply_decision(task_id, "accept", "user")
    finally:
        release.set()
        await _finish(worker)
    task = queue.get(task_id)
    assert task.status == "approved" and task.decided_by == "user"
    assert task.decision == "accept"
    assert delivered == []
    assert worker.smart_terminal_approved(task_id) is False


@pytest.mark.asyncio
async def test_revoked_judge_releases_manual_card_without_machine_approval(queue, tmp_path, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await started.wait()
        monkeypatch.delenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL")
    finally:
        release.set()
        await _finish(worker)
    assert [task.id for task in delivered] == [task_id]
    assert queue.get(task_id).status == "blocked"
    assert "judge" not in worker.approval_judge.project(queue.get(task_id))


@pytest.mark.asyncio
async def test_slot_timeout_releases_manual_card_without_late_http(queue, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_TIMEOUT", "1")
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    slots = worker.approval_judge._slots_for(asyncio.get_running_loop())
    await slots.acquire()
    await slots.acquire()
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await asyncio.gather(*tuple(worker._bg_tasks))
        assert [task.id for task in delivered] == [task_id]
    finally:
        slots.release()
        slots.release()
        await _finish(worker)
    assert requests == []
    assert queue.get(task_id).status == "blocked"


@pytest.mark.asyncio
async def test_native_failure_releases_manual_card_without_approval(queue, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        raise httpx.ConnectError("synthetic disconnected judge")

    worker, delivered = _worker(queue, tmp_path, handler)
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await started.wait()
        assert delivered == []
    finally:
        release.set()
        await _finish(worker)
    assert [task.id for task in delivered] == [task_id]
    assert queue.get(task_id).status == "blocked"
    assert worker.smart_terminal_approved(task_id) is False


@pytest.mark.asyncio
async def test_deadline_crossed_while_waiting_never_sends_unactionable_card(queue, tmp_path, monkeypatch):
    from agents.core.autonomy import queue as queue_module

    clock = [datetime.now(UTC)]
    original_now = queue_module._approval_now
    monkeypatch.setattr(queue_module, "_approval_now", lambda now=None: clock[0] if now is None else original_now(now))
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ESCALATE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    submission = asyncio.create_task(worker.submit(
        "jarvis", "toolrpc.terminal_run", "Deadline review", _payload(), risk_tier=3,
        approval_deadline_at=(clock[0] + timedelta(seconds=30)).isoformat(),
    ))
    try:
        await started.wait()
        clock[0] += timedelta(seconds=60)
    finally:
        release.set()
        task = await submission
        await _finish(worker)
    assert queue.get(task.id).status == "blocked", "expiry sweep intentionally has not run"
    assert delivered == []
    assert not queue.get(task.id).pushed


@pytest.mark.asyncio
async def test_notifier_removed_during_review_does_not_consume_delivery_retry(queue, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ESCALATE"}}]})

    worker, delivered = _worker(queue, tmp_path, handler)
    original_notifier = worker.notifier
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review", payload=_payload())
    try:
        await started.wait()
        worker.notifier = None
    finally:
        release.set()
        await _finish(worker)
    assert delivered == []
    worker.notifier = original_notifier
    assert await worker._maybe_push(queue.get(task_id)) is True
    assert [task.id for task in delivered] == [task_id]
