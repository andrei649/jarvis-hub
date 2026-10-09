"""An exact bounded guardian attempt may be joined, never inferred as authority."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import threading
from dataclasses import replace

import httpx
import pytest

from agents.core import settings_db
from agents.core.autonomy.advisory_judgements import JUDGE_MAX_PENDING
from agents.core.autonomy.approval_judge import ApprovalJudge
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.task_approval_judge import TaskApprovalJudge
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.egress import llm_async_client


@pytest.fixture(autouse=True)
def smart_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "waiting-settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "waiting-test-guardian")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER", "lm-studio")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL", "http://localhost:1234")
    monkeypatch.setenv("JARVIS_SMART_APPROVALS", "1")
    monkeypatch.delenv("JARVIS_SMART_APPROVAL_POLICY", raising=False)
    monkeypatch.delenv("JARVIS_SMART_APPROVAL_DENY", raising=False)


@pytest.fixture
def queue(tmp_path):
    key = b"h485-waiting-test"
    signer = DetachedHMACSigner(lambda raw: hmac.new(key, raw, hashlib.sha256).hexdigest())
    value = TaskQueue(str(tmp_path / "waiting.db"), mediation_signer=signer).initialize()
    yield value
    value.close()


def blocked(queue, command="printf waiting"):
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Run waiting test",
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": command}},
        risk_tier=3, autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    return task_id, digest


def wire(queue, handler, *, loop=None):
    def backend(status):
        instance = object.__new__(LMStudioBackend)
        instance.base_url = status.base_url
        instance.client = llm_async_client(
            "lm-studio", base_url=status.base_url, trust_env=False,
            transport=httpx.MockTransport(handler),
        )
        return instance

    judge = ApprovalJudge(settings=lambda _category, _key, default=None: default,
                          backend_factory=backend)
    adapter = TaskApprovalJudge(queue)
    adapter.attach_judge(judge, loop=loop or asyncio.get_running_loop())
    return adapter


async def drain(adapter):
    await asyncio.sleep(0)
    while adapter._judge_tasks:
        await asyncio.gather(*tuple(adapter._judge_tasks), return_exceptions=True)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_existing_attempt_joins_natural_completion_without_grant_by_wait(queue):
    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    task_id, digest = blocked(queue)
    adapter.schedule(task_id)
    assert await adapter.wait_for_review(task_id, digest, timeout=2) is True
    assert queue.approval_judgement(task_id, digest)["decision"] == "deny"
    assert queue.get(task_id).status == "blocked"
    assert await adapter.wait_for_review(task_id, digest, timeout=1) is False


@pytest.mark.asyncio
async def test_missing_or_invalid_join_never_schedules_or_sends(queue):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    task_id, digest = blocked(queue)
    assert await adapter.wait_for_review(task_id, digest, timeout=1) is False
    assert await adapter.wait_for_review(True, digest, timeout=1) is False
    assert await adapter.wait_for_review(task_id, digest.upper(), timeout=1) is False
    assert await adapter.wait_for_review(task_id, "bad", timeout=1) is False
    assert requests == [] and adapter._judging == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, True, "1"])
async def test_invalid_wait_timeout_returns_false_without_cancelling_existing(queue, timeout):
    gate = asyncio.Event()

    async def handler(_request):
        await gate.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    task_id, digest = blocked(queue)
    adapter.schedule(task_id)
    try:
        assert await adapter.wait_for_review(task_id, digest, timeout=timeout) is False
        assert adapter._judging == {f"{task_id}:{digest}"}
    finally:
        gate.set()
        await drain(adapter)


@pytest.mark.asyncio
async def test_join_timeout_while_waiting_for_slot_blocks_late_native_send(queue):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    task_id, digest = blocked(queue)
    slot = adapter._slots_for(asyncio.get_running_loop())
    await slot.acquire()
    await slot.acquire()
    try:
        adapter.schedule(task_id)
        assert await adapter.wait_for_review(task_id, digest, timeout=0.02) is False
    finally:
        slot.release()
        slot.release()
        await drain(adapter)
    assert requests == []
    assert queue.approval_judgement(task_id, digest) is None


@pytest.mark.asyncio
async def test_caller_cancellation_invalidates_exact_attempt(queue):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(_request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    adapter = wire(queue, handler)
    task_id, digest = blocked(queue)
    adapter.schedule(task_id)
    waiter = asyncio.create_task(adapter.wait_for_review(task_id, digest, timeout=2))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    finally:
        release.set()
        await drain(adapter)
    assert queue.approval_judgement(task_id, digest) is None
    assert queue.get(task_id).status == "blocked"


@pytest.mark.asyncio
async def test_two_joiners_share_one_attempt_and_one_native_send(queue):
    calls = []
    gate = asyncio.Event()

    async def handler(request):
        calls.append(request)
        await gate.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    task_id, digest = blocked(queue)
    adapter.schedule(task_id)
    first = asyncio.create_task(adapter.wait_for_review(task_id, digest, timeout=2))
    second = asyncio.create_task(adapter.wait_for_review(task_id, digest, timeout=2))
    gate.set()
    assert await asyncio.gather(first, second) == [True, True]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cross_loop_hub_attempt_can_be_joined_from_caller_loop(queue):
    hub = asyncio.new_event_loop()
    thread = threading.Thread(target=hub.run_forever, daemon=True)
    thread.start()
    try:
        async def handler(_request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

        adapter = wire(queue, handler, loop=hub)
        task_id, digest = blocked(queue)
        adapter.schedule(task_id)
        assert await adapter.wait_for_review(task_id, digest, timeout=2) is True
        assert queue.approval_judgement(task_id, digest)["decision"] == "deny"
    finally:
        hub.call_soon_threadsafe(hub.stop)
        thread.join(timeout=2)
        hub.close()


@pytest.mark.asyncio
async def test_deadline_includes_slot_wait_even_without_a_waiter(queue, monkeypatch):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    original_status = adapter._judge.status
    monkeypatch.setattr(adapter._judge, "status", lambda: replace(original_status(), timeout=0.03))
    slots = adapter._slots_for(asyncio.get_running_loop())
    await slots.acquire()
    await slots.acquire()
    task_id, digest = blocked(queue)
    try:
        adapter.schedule(task_id)
        await asyncio.sleep(0.06)
        assert adapter.judge_status_public()["judging"] == []
        assert await adapter.wait_for_review(task_id, digest, timeout=1) is False
    finally:
        slots.release()
        slots.release()
        await drain(adapter)
    assert requests == []
    assert queue.approval_judgement(task_id, digest) is None


@pytest.mark.asyncio
async def test_timeout_before_hub_spawn_invalidates_queued_callback(queue):
    hub = asyncio.new_event_loop()
    entered, release = threading.Event(), threading.Event()

    def serve():
        asyncio.set_event_loop(hub)
        hub.run_forever()
        hub.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler, loop=hub)
    task_id, digest = blocked(queue)

    def block_hub():
        entered.set()
        release.wait(timeout=2)

    hub.call_soon_threadsafe(block_hub)
    assert await asyncio.to_thread(entered.wait, 1)
    try:
        adapter.schedule(task_id)
        assert await adapter.wait_for_review(task_id, digest, timeout=0.02) is False
    finally:
        release.set()
        await asyncio.sleep(0.03)
        hub.call_soon_threadsafe(hub.stop)
        await asyncio.to_thread(thread.join, 1)
    assert requests == []
    assert queue.approval_judgement(task_id, digest) is None


@pytest.mark.asyncio
async def test_old_cancelled_callback_cannot_clear_or_settle_replacement(queue):
    first_started = asyncio.Event()
    first_cancelled = asyncio.Event()
    release_old = asyncio.Event()
    second_started = asyncio.Event()
    release_new = asyncio.Event()
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            first_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                first_cancelled.set()
                await release_old.wait()
            return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})
        second_started.set()
        await release_new.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    task_id, digest = blocked(queue)
    key = f"{task_id}:{digest}"
    adapter.schedule(task_id)
    await asyncio.wait_for(first_started.wait(), timeout=2)
    old_task = next(iter(adapter._judge_tasks))
    adapter._cancel_judgement(key)
    await asyncio.wait_for(first_cancelled.wait(), timeout=2)
    adapter.schedule(task_id)
    await asyncio.wait_for(second_started.wait(), timeout=2)
    waiter = asyncio.create_task(adapter.wait_for_review(task_id, digest, timeout=2))
    try:
        release_old.set()
        await asyncio.wait_for(old_task, timeout=2)
        await asyncio.sleep(0)
        assert key in adapter._judging
        assert not waiter.done()
    finally:
        release_new.set()
        assert await waiter is True
        await drain(adapter)
    assert len(requests) == 2
    assert queue.approval_judgement(task_id, digest)["decision"] == "deny"


@pytest.mark.asyncio
async def test_clear_pending_invalidates_only_matching_task_attempt(queue):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(_request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    first_id, first_digest = blocked(queue, "printf first")
    second_id, second_digest = blocked(queue, "printf second")
    adapter.schedule(first_id)
    adapter.schedule(second_id)
    await asyncio.wait_for(entered.wait(), timeout=2)
    adapter.clear_pending(first_id)
    try:
        assert await adapter.wait_for_review(first_id, first_digest, timeout=1) is False
        assert f"{second_id}:{second_digest}" in adapter._judging
    finally:
        release.set()
        await drain(adapter)
    assert queue.approval_judgement(first_id, first_digest) is None
    assert queue.approval_judgement(second_id, second_digest)["decision"] == "deny"


@pytest.mark.asyncio
async def test_cancel_resistant_tasks_retain_capacity_until_their_actual_completion(queue, monkeypatch):
    entered = 0
    cancelled = 0
    all_entered = asyncio.Event()
    all_cancelled = asyncio.Event()
    release = asyncio.Event()
    requests = []

    class ResistantSlot:
        async def __aenter__(self):
            nonlocal entered, cancelled
            entered += 1
            if entered == JUDGE_MAX_PENDING:
                all_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled += 1
                if cancelled == JUDGE_MAX_PENDING:
                    all_cancelled.set()
                await release.wait()
            return self

        async def __aexit__(self, *_exc):
            return False

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    adapter = wire(queue, handler)
    monkeypatch.setattr(adapter, "_slots_for", lambda _loop: ResistantSlot())
    ids = [blocked(queue, f"printf {number}") for number in range(JUDGE_MAX_PENDING + 1)]
    for task_id, _digest in ids[:-1]:
        adapter.schedule(task_id)
    try:
        await asyncio.wait_for(all_entered.wait(), timeout=2)
        for task_id, digest in ids[:-1]:
            adapter._cancel_judgement(f"{task_id}:{digest}")
        await asyncio.wait_for(all_cancelled.wait(), timeout=2)
        adapter.schedule(ids[-1][0])
        assert len(adapter._judge_tasks) == JUDGE_MAX_PENDING
        assert adapter.judge_status_public()["skipped_busy"] == 1
    finally:
        adapter._cancel_judgement(f"{ids[-1][0]}:{ids[-1][1]}")
        release.set()
        await drain(adapter)
    assert requests == []
    adapter.schedule(ids[-1][0])
    await asyncio.sleep(0)
    assert len(adapter._judge_tasks) == 1
    adapter._cancel_judgement(f"{ids[-1][0]}:{ids[-1][1]}")
    await drain(adapter)
