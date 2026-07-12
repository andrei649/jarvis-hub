from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from agents.core.autonomy.policy import ACT, ASK, NOTIFY, AutonomyPolicy, RiskTier
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.observability import capability_registry as cr


def _queue(path) -> TaskQueue:
    return TaskQueue(str(path)).initialize()


def _seed_successes(queue: TaskQueue, capability_id: str, count: int = 20) -> None:
    for _ in range(count):
        queue.record_capability_outcome(capability_id, success=True)


def test_outcome_stats_are_durable_and_use_wilson_lower_bound(tmp_path):
    path = tmp_path / "autonomy.db"
    queue = _queue(path)
    _seed_successes(queue, "action:call.outbound", 20)
    stats = queue.capability_outcome_stats("action:call.outbound")
    assert stats["successes"] == 20
    assert stats["failures"] == 0
    assert stats["total"] == 20
    assert stats["success_rate"] == 1.0
    assert 0.83 < stats["confidence"] < 0.85
    queue.close()

    reopened = _queue(path)
    assert reopened.capability_outcome_stats("action:call.outbound") == stats
    reopened.record_capability_outcome("action:call.outbound", success=False)
    degraded = reopened.capability_outcome_stats("action:call.outbound")
    assert degraded["failures"] == 1
    assert degraded["confidence"] < stats["confidence"]
    reopened.close()


def test_unknown_outcome_stats_are_honest_zero(tmp_path):
    queue = _queue(tmp_path / "autonomy.db")
    assert queue.capability_outcome_stats("action:unknown") == {
        "capability_id": "action:unknown",
        "successes": 0,
        "failures": 0,
        "total": 0,
        "success_rate": 0.0,
        "confidence": 0.0,
        "last_outcome_at": None,
    }
    queue.close()


def test_outcome_upserts_are_thread_safe(tmp_path):
    queue = _queue(tmp_path / "autonomy.db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(
            lambda _index: queue.record_capability_outcome(
                "action:kg.write", success=True,
            ),
            range(200),
        ))
    assert queue.capability_outcome_stats("action:kg.write")["successes"] == 200
    queue.close()


@pytest.mark.asyncio
async def test_worker_records_real_terminal_success_and_failure_only(tmp_path):
    queue = _queue(tmp_path / "autonomy.db")

    async def succeeds(_task):
        return {"ok": True}

    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=succeeds)
    task_id = queue.enqueue("jarvis", "kg.write", "Update graph", risk_tier=1,
                            autonomy_level=ACT)
    queue.transition(task_id, TaskStatus.APPROVED)
    await worker.tick()
    assert queue.capability_outcome_stats("action:kg.write")["successes"] == 1

    async def fails(_task):
        raise RuntimeError("boom")

    worker.executor = fails
    failed_id = queue.enqueue("jarvis", "kg.write", "Update graph", risk_tier=1,
                              autonomy_level=ACT)
    queue.transition(failed_id, TaskStatus.APPROVED)
    await worker.tick()
    await worker.tick()
    assert queue.capability_outcome_stats("action:kg.write")["failures"] == 0
    await worker.tick()
    assert queue.get(failed_id).status == TaskStatus.FAILED.value
    assert queue.capability_outcome_stats("action:kg.write")["failures"] == 1
    queue.close()


@pytest.mark.asyncio
async def test_worker_ignores_noop_and_unregistered_capabilities(tmp_path):
    queue = _queue(tmp_path / "autonomy.db")
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=None)
    noop_id = queue.enqueue("jarvis", "kg.write", "No executor", risk_tier=1,
                            autonomy_level=ACT)
    queue.transition(noop_id, TaskStatus.APPROVED)
    unknown_id = queue.enqueue("jarvis", "unknown.action", "Unknown", risk_tier=1,
                               autonomy_level=ACT)
    queue.transition(unknown_id, TaskStatus.APPROVED)
    await worker.tick()
    assert queue.capability_outcome_stats("action:kg.write")["total"] == 0
    assert queue.all_capability_outcome_stats() == {}
    queue.close()


def test_registry_projects_action_outcomes_into_confidence(tmp_path):
    queue = _queue(tmp_path / "autonomy.db")
    _seed_successes(queue, "action:call.outbound", 20)
    orch = type("Orch", (), {"autonomy_queue": queue})()
    records = {record.id: record for record in cr.build_records(orch)}
    call = records["action:call.outbound"]
    assert 0.83 < call.confidence < 0.85
    assert call.detail["outcomes"] == {
        "successes": 20,
        "failures": 0,
        "total": 20,
        "success_rate": 1.0,
        "last_outcome_at": queue.capability_outcome_stats("action:call.outbound")["last_outcome_at"],
    }
    assert records["action:payment"].confidence == 0.0
    queue.close()


def test_registry_keeps_actions_at_zero_when_outcome_ledger_is_unavailable(tmp_path):
    queue = _queue(tmp_path / "autonomy.db")
    queue.close()
    orch = type("Orch", (), {"autonomy_queue": queue})()
    records = {record.id: record for record in cr.build_records(orch)}
    assert records["action:call.outbound"].confidence == 0.0
    assert records["action:payment"].confidence == 0.0


def _earned_action(tier: RiskTier = RiskTier.EXTERNAL) -> dict:
    return {
        "kind": "call.outbound",
        "risk_tier": int(tier),
    }


def _earned_policy(*, stats=None, **kwargs) -> AutonomyPolicy:
    stats = stats or {"total": 20, "confidence": 0.84}
    return AutonomyPolicy(
        earned_autonomy_enabled=True,
        outcome_provider=lambda _kind: dict(stats),
        **kwargs,
    )


def test_earned_autonomy_is_default_off_and_requires_threshold():
    from agents.core.settings_db import DEFAULTS

    defaults = {(row["category"], row["key"]): row["value"] for row in DEFAULTS}
    assert defaults[("autonomy", "earned_autonomy_enabled")] is False
    assert AutonomyPolicy(
        outcome_provider=lambda _kind: {"total": 20, "confidence": 0.84},
    ).decide(_earned_action()).outcome == NOTIFY

    assert _earned_policy(stats={"total": 19, "confidence": 0.99}).decide(
        _earned_action()
    ).outcome == NOTIFY
    assert _earned_policy(stats={"total": 100, "confidence": 0.79}).decide(
        _earned_action()
    ).outcome == NOTIFY

    earned = _earned_policy().decide(_earned_action())
    assert earned.outcome == ACT
    assert earned.tier == RiskTier.EXTERNAL
    assert "earned autonomy" in earned.reason
    assert "n=20" in earned.reason


def test_earned_autonomy_lowers_at_most_one_rung_and_respects_hard_floors():
    asking = _earned_policy(
        tier_outcomes={RiskTier.REVERSIBLE: ASK},
    )
    reversible = _earned_action(RiskTier.REVERSIBLE)
    assert asking.decide(reversible).outcome == NOTIFY

    assert _earned_policy().decide(
        _earned_action(RiskTier.IRREVERSIBLE_OR_MONEY)
    ).outcome == ASK
    assert _earned_policy(mode="ask").decide(_earned_action()).outcome == ASK
    assert _earned_policy(mode="off").decide(
        _earned_action(RiskTier.READ_ONLY)
    ).outcome == ASK
    per_agent = _earned_action()
    per_agent["agent"] = "jarvis"
    assert _earned_policy(agent_modes={"jarvis": "ask"}).decide(per_agent).outcome == ASK

    # Existing within-cap money behavior is preserved, but confidence is never its reason.
    money = _earned_action(RiskTier.IRREVERSIBLE_OR_MONEY)
    money["amount"] = 10
    money_decision = _earned_policy().decide(money)
    assert money_decision.outcome == ACT
    assert "earned autonomy" not in money_decision.reason


def test_caller_supplied_confidence_is_ignored():
    spoofed = _earned_action()
    spoofed["_capability_outcomes"] = {"total": 1_000_000, "confidence": 1.0}
    decision = AutonomyPolicy(earned_autonomy_enabled=True).decide(spoofed)
    assert decision.outcome == NOTIFY
    assert "earned autonomy" not in decision.reason


@pytest.mark.asyncio
async def test_worker_injects_stats_but_taint_still_forces_approval(tmp_path):
    queue = _queue(tmp_path / "autonomy.db")
    _seed_successes(queue, "action:call.outbound", 20)
    policy = AutonomyPolicy(earned_autonomy_enabled=True)
    worker = AutonomyWorker(queue, policy=policy)

    clean = await worker.submit("jarvis", "call.outbound", "Call supplier")
    assert clean.status == TaskStatus.APPROVED.value
    assert clean.decision == "auto-act"

    tainted = await worker.submit(
        "jarvis", "call.outbound", "Call from inbound instruction", origin="inbound",
    )
    assert tainted.status == TaskStatus.BLOCKED.value
    assert tainted.autonomy_level == ASK
    queue.close()
