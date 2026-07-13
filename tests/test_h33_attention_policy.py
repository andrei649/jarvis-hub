from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timezone

import pytest

from agents.core.ambient.policy import (
    AttentionDeliveryBroker,
    AttentionLedger,
    DecisionRung,
    LadderContext,
    LadderPolicy,
    bounded_attention_allowance,
)
from agents.core.kernel import BudgetLedger


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> float:
        return self.value.timestamp()


def test_owner_attention_setting_is_bounded_by_construction():
    assert bounded_attention_allowance(7) == 4
    assert bounded_attention_allowance(0) == 0
    assert bounded_attention_allowance(-1) == 0
    assert bounded_attention_allowance("3") == 3
    assert bounded_attention_allowance(True) == 4
    assert bounded_attention_allowance("invalid") == 4


@pytest.mark.parametrize(
    ("requested", "expected", "mode"),
    [
        ("ignore", "ignore", "none"),
        ("remember", "remember", "none"),
        ("monitor", "monitor", "none"),
        ("ask", "ask", "digest"),
        ("interrupt", "interrupt", "interrupt"),
    ],
)
def test_ladder_rung_semantics(requested, expected, mode):
    decision = LadderPolicy().decide(LadderContext(requested_rung=requested))

    assert decision.rung is DecisionRung(expected)
    assert decision.attention_mode == mode


def test_ladder_hard_floors_taint_confidence_quiet_hours_and_silent_proof():
    policy = LadderPolicy(min_confidence=0.8)

    assert policy.decide(LadderContext(requested_rung="interrupt", tainted=True)).rung is DecisionRung.ASK
    assert policy.decide(LadderContext(requested_rung="interrupt", confidence=0.4)).rung is DecisionRung.ASK
    assert policy.decide(
        LadderContext(requested_rung="interrupt", quiet_hours=True, critical=False)
    ).rung is DecisionRung.ASK
    assert policy.decide(
        LadderContext(requested_rung="interrupt", quiet_hours=True, critical=True)
    ).rung is DecisionRung.INTERRUPT
    assert policy.decide(
        LadderContext(
            requested_rung="act_silently",
            capability_id="house.security",
            silent_eligible=True,
            rollbackable=True,
            postcondition_bound=True,
        )
    ).rung is DecisionRung.ASK
    assert policy.decide(
        LadderContext(
            requested_rung="act_silently",
            capability_id="house.light.set",
            silent_eligible=True,
            rollbackable=True,
            postcondition_bound=True,
        )
    ).rung is DecisionRung.ACT_SILENTLY
    assert policy.decide(
        LadderContext(
            requested_rung="act_silently",
            capability_id="house.light.set",
            silent_eligible=True,
            rollbackable=False,
            postcondition_bound=True,
        )
    ).rung is DecisionRung.ASK


def test_attention_ledger_is_persistent_atomic_and_k3_visible(tmp_path):
    path = tmp_path / "attention.db"
    clock = MutableClock(datetime(2026, 7, 13, 10, tzinfo=UTC))
    k3 = BudgetLedger()
    ledger = AttentionLedger(path, timezone_name="Europe/Bucharest", per_day=4, clock=clock, k3=k3)

    def reserve(index: int) -> bool:
        return ledger.reserve(f"delivery-{index}", "push").admitted

    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = list(pool.map(reserve, range(24)))

    assert sum(admitted) == 4
    assert ledger.remaining() == 0
    assert k3.dimension_status("interrupts/day")["used"] == 4
    ledger.close()

    reopened = AttentionLedger(path, timezone_name="Europe/Bucharest", per_day=4, clock=clock)
    assert reopened.remaining() == 0
    assert reopened.reserve("delivery-0", "push").admitted is True  # idempotent retry
    assert reopened.reserve("delivery-new", "call").reason == "attention_budget_exhausted"
    rows = reopened.records()
    assert all(set(row) <= {
        "delivery_id", "channel_class", "state", "window_id", "reserved_at",
        "dispatching_at", "delivered_at", "failed_at", "failure_category", "spent",
    } for row in rows)
    reopened.close()


def test_attention_failure_and_clock_rollback_are_conservative(tmp_path):
    path = tmp_path / "attention.db"
    clock = MutableClock(datetime(2026, 7, 13, 10, tzinfo=UTC))
    ledger = AttentionLedger(path, timezone_name="UTC", per_day=2, clock=clock)
    assert ledger.reserve("before", "push").admitted
    ledger.fail("before", category="not_dispatched", before_dispatch=True)
    assert ledger.remaining() == 2

    assert ledger.reserve("ambiguous", "push").admitted
    ledger.start_dispatch("ambiguous")
    ledger.fail("ambiguous", category="ambiguous_timeout", before_dispatch=False)
    assert ledger.remaining() == 1

    clock.value = datetime(2026, 7, 14, 10, tzinfo=UTC)
    assert ledger.remaining() == 2
    assert ledger.reserve("tomorrow", "push").admitted
    clock.value = datetime(2026, 7, 13, 8, tzinfo=UTC)
    assert ledger.remaining() == 1  # rollback cannot reopen the previous allowance
    ledger.close()


def test_attention_failure_is_idempotent_for_terminal_records(tmp_path):
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=1)
    assert ledger.reserve("spent", "push").admitted
    exhausted = ledger.reserve("exhausted", "push")
    assert exhausted.reason == "attention_budget_exhausted"

    ledger.fail("exhausted", category="provider_error", before_dispatch=False)

    [record] = [row for row in ledger.records() if row["delivery_id"] == "exhausted"]
    assert record["state"] == "failed"
    assert record["failure_category"] == "budget_exhausted"
    assert record["spent"] == 0
    ledger.close()


def test_attention_ledger_never_persists_content_or_recipient(tmp_path):
    path = tmp_path / "attention.db"
    ledger = AttentionLedger(path, timezone_name="UTC")
    ledger.reserve("opaque-delivery", "telegram")
    ledger.start_dispatch("opaque-delivery")
    ledger.delivered("opaque-delivery")
    ledger.close()

    raw = path.read_bytes().lower()
    assert b"private body" not in raw
    assert b"recipient@example.com" not in raw
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(attention_deliveries)")}
    assert not columns & {"body", "payload", "recipient", "phone", "chat_id", "attributes"}


def test_attention_corruption_fails_closed(tmp_path):
    path = tmp_path / "attention.db"
    path.write_bytes(b"not a sqlite database")
    ledger = AttentionLedger(path, timezone_name="UTC")

    assert ledger.health()["status"] == "degraded"
    assert ledger.reserve("x", "push").reason == "attention_ledger_unavailable"
    assert ledger.remaining() == 0


def test_delivery_broker_debits_before_dispatch_and_never_retries_ambiguous(tmp_path):
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=1)
    broker = AttentionDeliveryBroker(ledger)
    calls = []

    async def accepted():
        calls.append("accepted")
        return True

    first = asyncio.run(broker.dispatch("one", "telegram", accepted))
    duplicate = asyncio.run(broker.dispatch("one", "telegram", accepted))
    exhausted = asyncio.run(broker.dispatch("two", "call", accepted))

    assert first["status"] == "delivered"
    assert duplicate["status"] == "delivered"
    assert calls == ["accepted"]
    assert exhausted == {"status": "downgraded", "reason": "attention_budget_exhausted"}

    async def ambiguous():
        raise TimeoutError("provider may have accepted")

    second = AttentionDeliveryBroker(
        AttentionLedger(tmp_path / "attention-2.db", timezone_name="UTC", per_day=1)
    )
    result = asyncio.run(second.dispatch("ambiguous", "telegram", ambiguous))
    assert result == {"status": "failed", "reason": "ambiguous_timeout"}
    assert second.ledger.remaining() == 0


def test_delivery_broker_pre_dispatch_failure_releases_reservation(tmp_path):
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=1)
    broker = AttentionDeliveryBroker(ledger)

    result = asyncio.run(broker.dispatch("one", "push", None))

    assert result == {"status": "failed", "reason": "dispatcher_unavailable"}
    assert ledger.remaining() == 1


def test_attention_export_is_bounded_and_json_safe(tmp_path):
    ledger = AttentionLedger(tmp_path / "attention.db", timezone_name="UTC", per_day=4)
    for index in range(4):
        ledger.reserve(f"d-{index}", "push")
    status = ledger.status()

    assert status["limit"] == 4
    assert status["used"] == 4
    assert status["remaining"] == 0
    assert len(json.dumps(status)) < 2_000
