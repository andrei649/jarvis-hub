from __future__ import annotations

import asyncio
import time

from agents.core.ambient.policy import AttentionDeliveryBroker, AttentionLedger
from agents.core.autonomy.queue import TaskQueue
from agents.core.observability.north_star import compute_north_star


def test_north_star_uses_committed_attention_ledger_not_task_pushed_flag(tmp_path):
    now = time.time()
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    task_id = queue.enqueue("jarvis", "ambient.decision", "Needs attention")
    ledger = AttentionLedger(
        tmp_path / "attention.db", timezone_name="UTC", per_day=2, clock=lambda: now
    )
    broker = AttentionDeliveryBroker(ledger)

    async def accepted():
        return True

    ledger.reserve("released", "decision_push")
    ledger.fail("released", category="not_dispatched", before_dispatch=True)
    asyncio.run(broker.dispatch(f"task-{task_id}", "decision_push", accepted))
    asyncio.run(broker.dispatch("call-task-9", "call", accepted))
    assert ledger.reserve("downgraded", "decision_push").reason == "attention_budget_exhausted"

    result = compute_north_star(
        queue,
        attention_ledger=ledger,
        days=1,
        now=now,
    )

    assert queue.get(task_id).pushed == 0
    assert result["counter_metrics"]["interrupt_rate_per_day"] == 1.0
    assert result["proposal_funnel"]["surfaced"] == 1
    assert result["attention"] == {
        "pushes": 1,
        "calls": 1,
        "failures": 0,
        "released_reservations": 1,
        "downgraded_interrupts": 1,
        "samples": 4,
    }
    assert result["raw"]["interrupts"] == 1
    ledger.close()
    queue.close()


def test_north_star_excludes_old_delivery_timestamps(tmp_path):
    now = time.time()
    old = now - 10 * 86_400
    ledger = AttentionLedger(
        tmp_path / "attention.db", timezone_name="UTC", per_day=4, clock=lambda: old
    )
    broker = AttentionDeliveryBroker(ledger)

    async def accepted():
        return True

    asyncio.run(broker.dispatch("old", "decision_push", accepted))

    result = compute_north_star(
        queue=None,
        attention_ledger=ledger,
        days=7,
        now=now,
    )

    assert result["raw"]["interrupts"] == 0
    assert result["attention"]["samples"] == 0
    ledger.close()
