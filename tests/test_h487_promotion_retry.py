"""A grouped task's next decision card survives notification failure and restart."""

import pytest

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
