"""Exact-attempt waiting against the persisted queue and native HTTP judge."""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest

from tests.test_h485_smart_observer_dispatch import (
    _blocked,
    _wire,
    isolated_settings,  # noqa: F401 — shared isolated settings fixture
    queue,  # noqa: F401 — shared signed SQLite queue fixture
)


async def _settle(adapter):
    await asyncio.sleep(0)
    while adapter._judge_tasks:
        await asyncio.gather(*tuple(adapter._judge_tasks), return_exceptions=True)
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict,status", [("APPROVE", "approved"), ("DENY", "blocked")])
async def test_two_waiters_join_one_native_attempt_and_read_durable_result(queue, verdict, status):
    started, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def handler(request):
        requests.append(request)
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": verdict}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    adapter.schedule(task_id)
    await started.wait()
    waiters = [asyncio.create_task(adapter.wait_for_review(task_id, digest, timeout=1)) for _ in range(2)]
    await asyncio.sleep(0)
    assert all(not waiter.done() for waiter in waiters)
    assert queue.get(task_id).status == "blocked"
    assert queue.approval_judgement(task_id, digest) is None
    release.set()
    assert await asyncio.gather(*waiters) == [True, True]
    assert len(requests) == 1
    assert queue.get(task_id).status == status
    if verdict == "APPROVE":
        assert adapter.verify_smart_approval(task_id) is True
    else:
        assert queue.approval_judgement(task_id, digest)["decision"] == "deny"
    await _settle(adapter)


@pytest.mark.asyncio
async def test_slot_wait_timeout_cannot_dispatch_later_after_capacity_returns(queue):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    _judge, adapter = _wire(queue, handler)
    slots = adapter._slots_for(asyncio.get_running_loop())
    await slots.acquire()
    await slots.acquire()
    task_id = _blocked(queue)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    adapter.schedule(task_id)
    try:
        assert await adapter.wait_for_review(task_id, digest, timeout=0.01) is False
    finally:
        slots.release()
        slots.release()
        await _settle(adapter)
    assert requests == []
    assert queue.get(task_id).status == "blocked"
    assert queue.approval_judgement(task_id, digest) is None
    assert adapter.judge_status_public()["judging"] == []


@pytest.mark.asyncio
async def test_cancelled_waiter_blocks_native_result_even_if_transport_swallows_cancel(queue):
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    adapter.schedule(task_id)
    await started.wait()
    waiter = asyncio.create_task(adapter.wait_for_review(task_id, digest, timeout=1))
    await asyncio.sleep(0)
    waiter.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        release.set()
        await _settle(adapter)
    assert queue.get(task_id).status == "blocked"
    assert queue.approval_judgement(task_id, digest) is None


@pytest.mark.asyncio
async def test_wrong_revision_wait_cannot_cancel_current_native_review(queue):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    adapter.schedule(task_id)
    await started.wait()
    try:
        assert await adapter.wait_for_review(task_id, "0" * 64, timeout=0.01) is False
        assert adapter.project(queue.get(task_id))["judge_pending"] is True
    finally:
        release.set()
        await _settle(adapter)
    assert queue.approval_judgement(task_id, digest)["decision"] == "deny"


@pytest.mark.asyncio
async def test_caller_loop_joins_hub_loop_native_review(queue):
    hub = asyncio.new_event_loop()
    ready, request_seen = threading.Event(), threading.Event()
    release = []

    def serve():
        asyncio.set_event_loop(hub)
        hub.call_soon(ready.set)
        hub.run_forever()
        hub.close()

    thread = threading.Thread(target=serve, name="h485-native-review-fixture", daemon=True)
    thread.start()
    assert await asyncio.to_thread(ready.wait, 1)

    async def handler(_request):
        gate = asyncio.Event()
        release.append(gate)
        request_seen.set()
        await gate.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    _judge, adapter = _wire(queue, handler)
    adapter.attach_judge(_judge, loop=hub)
    task_id = _blocked(queue)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    try:
        adapter.schedule(task_id)
        assert await asyncio.to_thread(request_seen.wait, 1)
        waiter = asyncio.create_task(adapter.wait_for_review(task_id, digest, timeout=1))
        await asyncio.sleep(0)
        assert not waiter.done()
        hub.call_soon_threadsafe(release[0].set)
        assert await waiter is True
        assert queue.get(task_id).status == "approved"
        assert adapter.verify_smart_approval(task_id) is True
    finally:
        async def cleanup():
            for task in tuple(adapter._judge_tasks):
                task.cancel()
            await _settle(adapter)

        done = asyncio.run_coroutine_threadsafe(cleanup(), hub)
        await asyncio.wrap_future(done)
        hub.call_soon_threadsafe(hub.stop)
        await asyncio.to_thread(thread.join, 1)
    assert not thread.is_alive()
