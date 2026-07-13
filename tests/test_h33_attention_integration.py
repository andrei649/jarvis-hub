from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

from agents.core.ambient.policy import AttentionDeliveryBroker, AttentionLedger
from agents.core.autonomy.call_broker import CallBroker, NullCallClient
from agents.core.autonomy.policy import ASK, Decision
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget


class AskPolicy:
    outcome_provider = None

    def decide(self, _action):
        return Decision(tier=2, outcome=ASK, reason="needs owner")


def test_task_queue_persists_attention_mode_and_migrates_existing_db(tmp_path):
    path = tmp_path / "tasks.db"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, kind TEXT NOT NULL,
                title TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', risk_tier INTEGER NOT NULL,
                status TEXT NOT NULL, autonomy_level TEXT NOT NULL, origin TEXT NOT NULL,
                attempts INTEGER NOT NULL, result TEXT, decided_by TEXT, decision TEXT,
                pushed INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
    queue = TaskQueue(str(path)).initialize()

    task_id = queue.enqueue(
        "jarvis", "ambient.ask", "Safe digest item", attention_mode="digest"
    )
    task = queue.get(task_id)

    assert task.attention_mode == "digest"
    assert task.to_dict()["attention_mode"] == "digest"
    queue.close()
    assert TaskQueue(str(path)).initialize().get(task_id).attention_mode == "digest"


def test_ambient_ask_is_digest_only_and_interrupt_uses_broker(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=1)
    broker = AttentionDeliveryBroker(ledger)
    delivered = []

    async def notifier(task):
        delivered.append(task.id)
        return True

    worker = AutonomyWorker(
        queue,
        policy=AskPolicy(),
        notifier=notifier,
        budget=InterruptBudget(per_day=1, attention_ledger=ledger),
        delivery_broker=broker,
    )

    digest = asyncio.run(
        worker.submit(
            "jarvis", "ambient.ask", "Digest", attention_mode="digest"
        )
    )
    interrupted = asyncio.run(
        worker.submit(
            "jarvis", "ambient.interrupt", "Interrupt", attention_mode="interrupt"
        )
    )
    exhausted = asyncio.run(
        worker.submit(
            "jarvis", "ambient.interrupt", "Held", attention_mode="interrupt"
        )
    )

    assert digest.attention_mode == "digest"
    assert queue.get(digest.id).pushed == 0
    assert queue.get(interrupted.id).pushed == 1
    assert queue.get(exhausted.id).pushed == 0
    assert delivered == [interrupted.id]
    assert ledger.remaining() == 0


def test_legacy_worker_pushes_also_flow_through_durable_broker(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=1)
    delivered = []

    async def notifier(task):
        delivered.append(task.id)
        return True

    worker = AutonomyWorker(
        queue,
        policy=AskPolicy(),
        notifier=notifier,
        budget=InterruptBudget(per_day=1, attention_ledger=ledger),
    )

    first = asyncio.run(worker.submit("jarvis", "legacy", "Legacy decision"))
    second = asyncio.run(worker.submit("jarvis", "legacy", "Second decision"))

    assert delivered == [first.id]
    assert queue.get(first.id).pushed == 1
    assert queue.get(second.id).pushed == 0
    assert {row["delivery_id"] for row in ledger.records()} == {f"task-{first.id}"}


def test_interrupt_budget_is_a_compatibility_view_over_attention_ledger(tmp_path):
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=2)
    budget = InterruptBudget(per_day=2, attention_ledger=ledger)

    assert budget.remaining() == 2
    assert budget.consume(delivery_id="legacy-one", channel_class="media")
    assert budget.consume(delivery_id="legacy-two", channel_class="call")
    assert not budget.consume(delivery_id="legacy-three", channel_class="push")
    assert budget.remaining() == 0
    assert {row["channel_class"] for row in ledger.records()} == {"media", "call"}


def test_call_broker_uses_same_delivery_choke_point_as_pushes(tmp_path):
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=1)
    budget = InterruptBudget(per_day=1, attention_ledger=ledger)
    client = NullCallClient()
    broker = CallBroker(client=client, budget=budget)
    task = SimpleNamespace(
        id=42,
        payload={"provider": "twilio", "to": "+401234", "message": "hello"},
    )

    first = asyncio.run(broker.execute(task))
    duplicate = asyncio.run(broker.execute(task))
    exhausted = asyncio.run(
        broker.execute(
            SimpleNamespace(
                id=43,
                payload={"provider": "twilio", "to": "+405678", "message": "again"},
            )
        )
    )

    assert first["status"] == "ok"
    assert duplicate["status"] == "ok"
    assert len(client.calls) == 1
    assert exhausted == {"status": "failed", "reason": "interrupt_budget_exhausted"}
    assert ledger.status()["used"] == 1
