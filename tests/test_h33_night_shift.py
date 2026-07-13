from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from agents.core.ambient.contracts import MonitorDefinition, MonitorPredicate
from agents.core.ambient.execution import AmbientTaskExecutor, SilentActionBinding
from agents.core.ambient.night import (
    AmbientNightLedger,
    ambient_night_report,
    resolve_owner_time,
)
from agents.core.ambient.policy import AttentionLedger, LadderContext, LadderPolicy
from agents.core.ambient.registry import MonitorRegistry
from agents.core.ambient.store import AmbientStore
from agents.core.observability.north_star import compute_north_star


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> float:
        return self.value.timestamp()


def _definition() -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="monitor.safe.light",
        version=1,
        source="house",
        schema="house.event.v1",
        predicates=(MonitorPredicate("attributes.current_state", "eq", "on"),),
        alert_rung="act_silently",
    )


def _task(definition: MonitorDefinition, task_id: int = 7):
    return SimpleNamespace(
        id=task_id,
        kind="ambient.action",
        payload={
            "ambient_generation": 3,
            "consent_generation": 2,
            "event_fingerprint": f"{task_id:064x}",
            "monitor_hash": definition.definition_hash,
            "monitor_id": definition.monitor_id,
            "monitor_version": definition.version,
            "rung": "act_silently",
            "source": "house",
        },
    )


def test_owner_timezone_dst_windows_execute_once_and_survive_restart(tmp_path):
    zone = ZoneInfo("Europe/Bucharest")
    spring_gap = datetime(2026, 3, 29, 3, 30)
    resolved_gap = resolve_owner_time(spring_gap, zone)
    assert resolved_gap.astimezone(zone).replace(tzinfo=None) == datetime(2026, 3, 29, 4, 0)

    clock = MutableClock(resolved_gap)
    path = tmp_path / "night.db"
    ledger = AmbientNightLedger(
        path,
        timezone_name="Europe/Bucharest",
        start_hour=22,
        end_hour=7,
        clock=clock,
    )
    spring = ledger.claim_scheduled("spring-job", spring_gap)
    assert spring.admitted is True
    assert spring.window_id.startswith("2026-03-28:")
    assert ledger.claim_scheduled("spring-job", spring_gap).reason == "night_action_duplicate"

    fall_fold = datetime(2026, 10, 25, 3, 30)
    first_fold = resolve_owner_time(fall_fold, zone)
    assert first_fold.fold == 0
    clock.value = first_fold
    fall = ledger.claim_scheduled("fall-job", fall_fold)
    assert fall.admitted is True
    assert fall.window_id.startswith("2026-10-24:")
    ledger.close()

    reopened = AmbientNightLedger(
        path,
        timezone_name="Europe/Bucharest",
        start_hour=22,
        end_hour=7,
        clock=clock,
    )
    assert reopened.claim_scheduled("fall-job", fall_fold).reason == "night_action_duplicate"
    assert reopened.claim_scheduled("rollback-job", spring_gap).reason == "clock_rollback"
    reopened.close()


def test_night_ledger_corruption_fails_closed(tmp_path):
    path = tmp_path / "night.db"
    path.write_bytes(b"not a sqlite database")
    ledger = AmbientNightLedger(
        path,
        timezone_name="UTC",
        start_hour=22,
        end_hour=7,
        clock=lambda: datetime(2026, 7, 13, 23, tzinfo=UTC).timestamp(),
    )

    assert ledger.health() == {
        "status": "degraded",
        "reason": "night_ledger_unavailable",
    }
    assert ledger.claim("unsafe").admitted is False


def test_quiet_critical_interrupt_uses_one_budget_across_dst_fold_and_rollback(tmp_path):
    policy = LadderPolicy()
    assert policy.decide(
        LadderContext(requested_rung="interrupt", quiet_hours=True)
    ).rung.value == "ask"
    assert policy.decide(
        LadderContext(requested_rung="interrupt", quiet_hours=True, critical=True)
    ).rung.value == "interrupt"

    zone = ZoneInfo("Europe/Bucharest")
    clock = MutableClock(datetime(2026, 10, 25, 3, 30, tzinfo=zone, fold=0))
    attention = AttentionLedger(
        tmp_path / "attention.db",
        timezone_name="Europe/Bucharest",
        per_day=1,
        clock=clock,
    )
    assert attention.reserve("critical-first", "decision_push").admitted is True

    clock.value = datetime(2026, 10, 25, 3, 30, tzinfo=zone, fold=1)
    assert attention.remaining() == 0
    assert attention.reserve("critical-fold", "decision_push").reason == (
        "attention_budget_exhausted"
    )

    clock.value = datetime(2026, 10, 24, 23, 30, tzinfo=zone)
    assert attention.remaining() == 0
    attention.close()


def test_silent_executor_records_verified_noop_and_rollback_without_repeating(tmp_path):
    clock = MutableClock(datetime(2026, 7, 13, 21, 30, tzinfo=UTC))  # 00:30 owner time
    night = AmbientNightLedger(
        tmp_path / "night.db",
        timezone_name="Europe/Bucharest",
        start_hour=22,
        end_hour=7,
        clock=clock,
    )
    store = AmbientStore(tmp_path / "ambient.db")
    registry = MonitorRegistry(store, enabled=True)
    definition = _definition()
    registry.create(definition, actor="owner")
    outcomes = {
        7: {"status": "ok", "verified": True},
        8: {"status": "noop", "verified": True},
        9: {"status": "failed", "verified": False},
    }
    action_calls = []

    async def action_api(_binding, task):
        action_calls.append(task.id)
        return outcomes[task.id]

    async def rollback(_binding, task, _result):
        return {"status": "restored", "verified": task.id == 9}

    executor = AmbientTaskExecutor(
        enabled_provider=lambda: True,
        generation_provider=lambda: 3,
        registry=registry,
        ownership_provider=lambda source: source == "house",
        kill_switch=lambda: False,
        binding_resolver=lambda monitor_id: SilentActionBinding(
            monitor_id=monitor_id,
            capability_id="house.light.set",
            rollbackable=True,
            postcondition_bound=True,
        ),
        action_api=action_api,
        rollback=rollback,
        night_ledger=night,
    )

    assert asyncio.run(executor.execute(_task(definition, 7)))["verified"] is True
    assert asyncio.run(executor.execute(_task(definition, 8)))["status"] == "noop"
    assert asyncio.run(executor.execute(_task(definition, 9)))["compensation"] == "verified"
    assert asyncio.run(executor.execute(_task(definition, 7))) == {
        "status": "revoked",
        "reason": "night_action_duplicate",
    }
    assert action_calls == [7, 8, 9]
    assert {row["result"] for row in night.records()} == {"verified", "noop", "rolled_back"}
    night.close()
    store.close()


def test_night_report_counts_rungs_but_only_verified_work_as_completed(tmp_path):
    zone = ZoneInfo("Europe/Bucharest")
    night_time = datetime(2026, 7, 14, 0, 30, tzinfo=zone).timestamp()
    clock = MutableClock(datetime.fromtimestamp(night_time, tz=UTC))
    ledger = AmbientNightLedger(
        tmp_path / "night.db",
        timezone_name="Europe/Bucharest",
        start_hour=22,
        end_hour=7,
        clock=clock,
    )
    for action_id, result in (
        ("verified", {"status": "ok", "verified": True}),
        ("noop", {"status": "noop", "verified": True}),
        ("rolled", {"status": "failed", "compensation": "verified"}),
        ("failed", {"status": "failed", "compensation": "manual_recovery_required"}),
    ):
        claim = ledger.claim(action_id, rung="act_silently")
        ledger.complete(claim, result)

    class Journal:
        @staticmethod
        def journal(*, limit=1_000):
            assert limit == 1_000
            return [
                {"decision_id": f"d-{rung}", "rung": rung, "decided_at": night_time}
                for rung in ("ignore", "remember", "monitor", "ask", "interrupt", "act_silently")
            ]

    report = ambient_night_report(
        ambient_store=Journal(),
        night_ledger=ledger,
        timezone_name="Europe/Bucharest",
        start_hour=22,
        end_hour=7,
        cutoff=night_time - 3600,
    )

    assert report["rungs"] == {
        "ignore": 1,
        "remember": 1,
        "monitor": 1,
        "act_silently": 1,
        "ask": 1,
        "interrupt": 1,
    }
    assert report["results"] == {
        "verified": 1,
        "noop": 1,
        "rolled_back": 1,
        "failed": 1,
    }
    assert report["completed_work"] == 1
    assert report["excluded_non_work"] == 3  # ignore + monitor + noop

    north_star = compute_north_star(
        queue=None,
        ambient_store=Journal(),
        ambient_night_ledger=ledger,
        owner_timezone="Europe/Bucharest",
        night_window=(22, 7),
        now=night_time + 3600,
        days=1,
    )
    assert north_star["ambient_night_shift"] == report
    ledger.close()
