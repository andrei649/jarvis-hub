"""Autonomy proposal metadata must remain server-owned and fail closed."""

import pytest

from agents.core.autonomy.policy import ACT, ASK, AutonomyPolicy, RiskTier
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget


@pytest.fixture
def queue(tmp_path):
    value = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield value
    value.close()


@pytest.fixture
def worker(queue):
    return AutonomyWorker(
        queue,
        policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
        budget=InterruptBudget(per_day=4),
    )


@pytest.mark.parametrize("bad", [True, False, -1, 4, "0", object()])
@pytest.mark.asyncio
async def test_invalid_trusted_tier_fails_closed_to_tier_three_and_ask(worker, bad):
    task = await worker.submit(
        agent="steve",
        kind="monitor.status",
        title="status",
        payload={},
        risk_tier=bad,
    )
    assert task.risk_tier == 3
    assert task.autonomy_level == ASK
    assert task.status == "blocked"


@pytest.mark.asyncio
async def test_submit_payload_reserved_fields_cannot_shadow_identity_or_tier(worker):
    payload = {
        "kind": "monitor.status",
        "risk_tier": 0,
        "agent": "attacker",
        "origin": "generated",
        "target": "delete production data",
    }
    task = await worker.submit(
        agent="steve",
        kind="delete_database",
        title="delete",
        payload=payload,
        origin="inbound",
    )
    assert task.agent == "steve"
    assert task.kind == "delete_database"
    assert task.origin == "inbound"
    assert task.risk_tier == 3
    assert task.autonomy_level == ASK
    assert {key: task.payload[key] for key in payload} == payload
    assert task.payload["tainted"] is True
    assert task.payload["taint_source"] == "inbound"


@pytest.mark.asyncio
async def test_submit_blank_kind_ignores_payload_name_and_fails_closed(worker):
    task = await worker.submit(
        agent="steve",
        kind="",
        title="blank",
        payload={"name": "monitor.status"},
    )
    assert task.risk_tier == 3
    assert task.autonomy_level == ASK
    assert task.status == "blocked"


@pytest.mark.asyncio
async def test_submit_trusted_tier_three_recalculates_read_only_act_to_ask(worker):
    task = await worker.submit(
        agent="steve",
        kind="monitor.status",
        title="status",
        risk_tier=RiskTier.IRREVERSIBLE_OR_MONEY,
    )
    assert task.risk_tier == 3
    assert task.autonomy_level == ASK
    assert task.status == "blocked"


@pytest.mark.asyncio
async def test_submit_trusted_tier_zero_cannot_lower_delete_or_money(worker):
    task = await worker.submit(
        agent="gecko",
        kind="delete_database",
        title="delete",
        payload={"amount": 500},
        risk_tier=RiskTier.READ_ONLY,
    )
    assert task.risk_tier == 3
    assert task.autonomy_level == ASK
    assert task.status == "blocked"


def test_govern_enqueue_uses_strictest_policy_caller_taint_and_money_result(worker):
    task_id = worker.govern_enqueue(
        agent="gecko",
        kind="send_payment",
        title="payment",
        payload={
            "amount": 500,
            "risk_tier": 0,
            "agent": "attacker",
            "origin": "generated",
        },
        risk_tier=RiskTier.READ_ONLY,
        autonomy_level=ACT,
        origin="inbound",
    )
    task = worker.queue.get(task_id)
    assert task.agent == "gecko"
    assert task.kind == "send_payment"
    assert task.origin == "inbound"
    assert task.risk_tier == 3
    assert task.autonomy_level == ASK
    assert task.status == "blocked"


@pytest.mark.asyncio
async def test_edit_preserves_identity_and_escalates_durable_tier(worker):
    task = await worker.submit(
        agent="steve",
        kind="delete_database",
        title="delete",
        payload={"target": "old"},
    )
    edited_payload = {
        "kind": "monitor.status",
        "risk_tier": 0,
        "agent": "attacker",
        "origin": "generated",
        "target": "new",
    }

    edited = await worker.apply_decision(
        task.id,
        "edit",
        decided_by="andrei",
        payload=edited_payload,
    )

    assert edited.agent == "steve"
    assert edited.kind == "delete_database"
    assert edited.origin == "generated"
    assert edited.risk_tier == 3
    assert edited.autonomy_level == ASK
    assert edited.status == "blocked"
    assert edited.payload == edited_payload
