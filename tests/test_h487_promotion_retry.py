"""A grouped task's next decision card survives notification failure and restart."""

import asyncio
from datetime import UTC, datetime

import pytest

from agents.core.ambient.policy import AttentionDeliveryBroker, AttentionLedger
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from tests.test_h487_task_groups import BODY, submit


@pytest.mark.asyncio
async def test_failed_promoted_notification_retries_after_worker_restart(tmp_path):
    path = str(tmp_path / "tasks.db")
    queue = TaskQueue(path).initialize()
    sent = []
    failed = [False]

    async def notify(task):
        sent.append(task.id)
        return True

    class Broker:
        async def dispatch(self, delivery_id, category, callback):
            assert category == "decision_push"
            if failed[0]:
                return {"status": "failed", "reason": "synthetic outage"}
            await callback()
            return {"status": "delivered"}

    try:
        worker = AutonomyWorker(queue, notifier=notify, delivery_broker=Broker())
        leader = await submit(worker, attention="interrupt")
        follower = await submit(worker, attention="interrupt")
        assert sent == [leader.id]
        failed[0] = True
        await worker.apply_decision(leader.id, "accept")
        assert not queue.get(follower.id).pushed
        queue.close()

        reopened = TaskQueue(path).initialize()
        try:
            failed[0] = False
            resumed = AutonomyWorker(reopened, notifier=notify, delivery_broker=Broker())
            await resumed.approval_housekeeping()
            assert reopened.get(follower.id).pushed
            assert sent == [leader.id, follower.id]
            await resumed.approval_housekeeping()
            assert sent == [leader.id, follower.id]
        finally:
            reopened.close()
    finally:
        if queue._conn is not None:
            queue.close()


@pytest.mark.asyncio
async def test_promotion_effect_write_failure_rolls_back_decision_and_group(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    try:
        worker = AutonomyWorker(queue)
        leader, follower = await submit(worker), await submit(worker)
        group = queue.pending_groups()[0]
        queue._conn.execute(
            "CREATE TRIGGER refuse_promotion BEFORE INSERT ON task_approval_promotion_effects "
            "BEGIN SELECT RAISE(ABORT, 'cannot write promotion'); END"
        )
        with pytest.raises(Exception, match="cannot write promotion"):
            await worker.apply_decision(leader.id, "accept")
        assert queue.get(leader.id).status == "blocked"
        assert queue.get(follower.id).status == "blocked"
        assert queue.pending_groups() == [group]
        assert queue.pending_approval_promotion_effects() == ()
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_old_ack_cannot_discard_newer_group_promotion(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    try:
        worker = AutonomyWorker(queue)
        first, second, _ = await submit(worker), await submit(worker), await submit(worker)
        queue.transition(first.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        old_effect, = queue.pending_approval_promotion_effects()
        queue.transition(second.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        new_effect, = queue.pending_approval_promotion_effects()
        assert old_effect.group_id == new_effect.group_id
        assert old_effect.revision != new_effect.revision
        assert queue.ack_approval_promotion_effects((old_effect,)) == 0
        assert queue.pending_approval_promotion_effects() == (new_effect,)
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_failed_group_does_not_starve_later_group(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    sent = []
    failing_ids = set()

    async def notify(task):
        sent.append(task.id)
        return True

    class Broker:
        async def dispatch(self, delivery_id, category, callback):
            if delivery_id in failing_ids:
                return {"status": "failed", "reason": "synthetic outage"}
            await callback()
            return {"status": "delivered"}

    try:
        worker = AutonomyWorker(queue, notifier=notify, delivery_broker=Broker())
        first, first_follower = await submit(worker, attention="interrupt"), await submit(
            worker, attention="interrupt"
        )
        failing_ids.add(f"task-{first_follower.id}")
        other_body = {**BODY, "title": "Different decision"}
        second, second_follower = await submit(worker, other_body, attention="interrupt"), await submit(
            worker, other_body, attention="interrupt"
        )
        await worker.apply_decision(first.id, "accept")
        await worker.apply_decision(second.id, "accept")
        assert not queue.get(first_follower.id).pushed
        assert queue.get(second_follower.id).pushed
        assert sent == [first.id, second.id, second_follower.id]
        assert len(queue.pending_approval_promotion_effects()) == 1
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_no_remaining_leader_acks_effect_without_notification(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    sent = []

    async def notify(task):
        sent.append(task.id)
        return True

    try:
        worker = AutonomyWorker(queue, notifier=notify)
        leader, follower = await submit(worker), await submit(worker)
        queue.transition(leader.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        queue.transition(follower.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        assert len(queue.pending_approval_promotion_effects()) == 1
        result = await worker.approval_housekeeping()
        assert result["promotion_effects_acked"] == 1
        assert queue.pending_approval_promotion_effects() == ()
        assert sent == []
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_halted_worker_keeps_effect_for_restart(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    sent = []

    async def notify(task):
        sent.append(task.id)
        return True

    class Broker:
        async def dispatch(self, delivery_id, category, callback):
            await callback()
            return {"status": "delivered"}

    try:
        worker = AutonomyWorker(queue, notifier=notify, delivery_broker=Broker())
        leader, follower = await submit(worker, attention="interrupt"), await submit(
            worker, attention="interrupt"
        )
        queue.transition(leader.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        before = queue.pending_approval_promotion_effects()
        worker._halted = lambda: True
        assert (await worker.approval_housekeeping())["promotion_effects_acked"] == 0
        assert queue.pending_approval_promotion_effects() == before
        resumed = AutonomyWorker(queue, notifier=notify, delivery_broker=Broker())
        assert (await resumed.approval_housekeeping())["promotion_effects_acked"] == 1
        assert sent == [leader.id, follower.id]
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_decided_follower_is_not_sent_after_broker_wait(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC")
    waiting = asyncio.Event()
    release = asyncio.Event()
    sent = []
    delayed_ids = set()

    async def notify(task):
        sent.append(task.id)
        return True

    class DelayedBroker(AttentionDeliveryBroker):
        async def dispatch(self, delivery_id, category, callback):
            if delivery_id in delayed_ids:
                async def delayed():
                    waiting.set()
                    await release.wait()
                    return await callback()

                return await super().dispatch(delivery_id, category, delayed)
            return await super().dispatch(delivery_id, category, callback)

    try:
        worker = AutonomyWorker(queue, notifier=notify, delivery_broker=DelayedBroker(ledger))
        leader, follower = await submit(worker, attention="interrupt"), await submit(
            worker, attention="interrupt"
        )
        delayed_ids.add(f"task-{follower.id}")
        decision = asyncio.create_task(worker.apply_decision(leader.id, "accept"))
        await asyncio.wait_for(waiting.wait(), 2)
        queue.transition(follower.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        release.set()
        await decision
        assert sent == [leader.id]
        assert not queue.get(follower.id).pushed
        await worker.approval_housekeeping()
        assert queue.pending_approval_promotion_effects() == ()
        assert sent == [leader.id]
    finally:
        release.set()
        ledger.close()
        queue.close()


@pytest.mark.asyncio
async def test_older_edited_card_is_not_sent_after_newer_edit(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC")
    waiting = asyncio.Event()
    release = asyncio.Event()
    sent = []

    async def notify(task):
        sent.append((task.id, task.payload["path"]))
        return True

    class DelayedBroker(AttentionDeliveryBroker):
        async def dispatch(self, delivery_id, category, callback):
            if "-edit-" in delivery_id:
                async def delayed():
                    waiting.set()
                    await release.wait()
                    return await callback()

                return await super().dispatch(delivery_id, category, delayed)
            return await super().dispatch(delivery_id, category, callback)

    try:
        worker = AutonomyWorker(queue, notifier=notify, delivery_broker=DelayedBroker(ledger))
        task = await submit(worker, attention="interrupt")
        decision = asyncio.create_task(worker.apply_decision(task.id, "edit", payload={"path": "older"}))
        await asyncio.wait_for(waiting.wait(), 2)
        edited = queue.get(task.id)
        await asyncio.sleep(0.001)
        newer, _ = queue.update_payload_policy_with_group(
            task.id, {"path": "newer"}, risk_tier=edited.risk_tier,
            autonomy_level=edited.autonomy_level,
        )
        assert newer.updated_at != edited.updated_at
        release.set()
        await decision
        assert sent == [(task.id, "old")]
        assert queue.get(task.id).payload["path"] == "newer"
    finally:
        release.set()
        ledger.close()
        queue.close()


@pytest.mark.asyncio
async def test_idempotent_broker_receipt_marks_still_pending_follower(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    calls = []

    async def notify(task):
        calls.append(task.id)
        return True

    class IdempotentBroker:
        async def dispatch(self, delivery_id, category, callback):
            return {"status": "delivered", "reason": "idempotent"}

    try:
        worker = AutonomyWorker(queue)
        leader, follower = await submit(worker, attention="interrupt"), await submit(
            worker, attention="interrupt"
        )
        queue.transition(leader.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        resumed = AutonomyWorker(queue, notifier=notify, delivery_broker=IdempotentBroker())
        assert (await resumed.approval_housekeeping())["promotion_effects_acked"] == 1
        assert queue.get(follower.id).pushed
        assert calls == []
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_expiry_promoted_card_is_not_sent_after_follower_decision(tmp_path, monkeypatch):
    from agents.core.autonomy import queue as queue_module
    from agents.core.autonomy.inbox import OwnerTaskRegistrationContext

    original_now = queue_module._approval_now
    monkeypatch.setattr(queue_module, "_approval_now", lambda now=None: original_now(
        now or datetime(2026, 9, 27, 11, tzinfo=UTC)
    ))
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC")
    waiting = asyncio.Event()
    release = asyncio.Event()
    sent = []
    delayed_ids = set()

    async def notify(task):
        sent.append(task.id)
        return True

    class DelayedBroker(AttentionDeliveryBroker):
        async def dispatch(self, delivery_id, category, callback):
            if delivery_id in delayed_ids:
                async def delayed():
                    waiting.set()
                    await release.wait()
                    return await callback()

                return await super().dispatch(delivery_id, category, delayed)
            return await super().dispatch(delivery_id, category, callback)

    try:
        worker = AutonomyWorker(queue, notifier=notify, delivery_broker=DelayedBroker(ledger))
        context = OwnerTaskRegistrationContext.from_request(BODY)
        leader = await worker.submit(
            **BODY, attention_mode="interrupt", grouping_context=context,
            approval_deadline_at="2026-09-27T12:00:00.000000+00:00",
        )
        follower = await worker.submit(**BODY, attention_mode="interrupt", grouping_context=context)
        delayed_ids.add(f"task-{follower.id}")
        sweep = asyncio.create_task(worker.approval_housekeeping(
            now=datetime(2026, 9, 27, 12, tzinfo=UTC)
        ))
        await asyncio.wait_for(waiting.wait(), 2)
        queue.transition(follower.id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        release.set()
        await sweep
        assert sent == [leader.id]
        assert queue.get(leader.id).status == "expired"
        assert not queue.get(follower.id).pushed
    finally:
        release.set()
        ledger.close()
        queue.close()
