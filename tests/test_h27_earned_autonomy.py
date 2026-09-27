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


@pytest.mark.asyncio
async def test_worker_records_returned_refusals_as_nothing_and_failures_as_failures(tmp_path):
    """Review F2: a returned ``refused`` ran nothing; a returned ``failed`` is a failure."""
    queue = _queue(tmp_path / "autonomy.db")
    results = iter([
        {"status": "refused", "reason": "not_armed"},
        {"status": "failed", "reason": "client_error"},
        {"status": "ok"},
    ])

    async def executor(_task):
        return next(results)

    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor)
    expected = [(0, 0), (0, 1), (1, 1)]
    for successes_failures in expected:
        task_id = queue.enqueue("jarvis", "kg.write", "Update graph", risk_tier=1,
                                autonomy_level=ACT)
        queue.transition(task_id, TaskStatus.APPROVED)
        await worker.tick()
        assert queue.get(task_id).status == TaskStatus.DONE.value
        stats = queue.capability_outcome_stats("action:kg.write")
        assert (stats["successes"], stats["failures"]) == successes_failures
    queue.close()


# ── round-2 MINOR 2: outcomes from REAL handlers, one kind at a time ─────────


async def _run_real(queue, executor, kind, payload, *, ticks=1):
    """One approved task of *kind* through a real worker tick and a real handler."""
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor)
    task_id = queue.enqueue("jarvis", kind, "real handler", risk_tier=1,
                            autonomy_level=ACT, payload=payload)
    queue.transition(task_id, TaskStatus.APPROVED)
    for _ in range(ticks):
        await worker.tick()
    return queue.get(task_id)


def _counts(queue, kind):
    from agents.core.capability_manifests import manifest_for_action

    stats = queue.capability_outcome_stats(manifest_for_action(kind).id)
    return stats["successes"], stats["failures"]


_CALL = {"provider": "twilio", "to": "+40700000000", "message": "hi"}


@pytest.mark.asyncio
async def test_call_budget_refusal_records_nothing_but_a_placed_or_broken_call_does(tmp_path):
    from agents.core.autonomy.call_broker import CallBroker

    class Spent:
        delivery_broker = None

        def consume(self):
            return False

    class Client:
        def __init__(self, fail=False):
            self.placed, self.fail = [], fail

        async def call(self, *args):
            self.placed.append(args)
            if self.fail:
                raise OSError("carrier down")
            return {"status": "ok"}

    queue = _queue(tmp_path / "autonomy.db")
    refused = Client()
    task = await _run_real(queue, CallBroker(client=refused, budget=Spent()).execute,
                           "call.outbound", _CALL)
    assert task.result == {"status": "failed", "reason": "interrupt_budget_exhausted"}
    assert refused.placed == [] and _counts(queue, "call.outbound") == (0, 0)

    placed = Client()
    task = await _run_real(queue, CallBroker(client=placed).execute, "call.outbound", _CALL)
    assert task.result["status"] == "ok" and len(placed.placed) == 1
    assert _counts(queue, "call.outbound") == (1, 0)

    task = await _run_real(queue, CallBroker(client=Client(fail=True)).execute,
                           "call.outbound", _CALL)
    assert task.result["reason"] == "client_error"
    assert _counts(queue, "call.outbound") == (1, 1)
    queue.close()


_HOUSE = {"version": 1, "control": "light", "entity_id": "light.kitchen", "action": "on",
          "risk_tier": 1, "reversible": True, "signal_quality": 1.0}


@pytest.mark.asyncio
async def test_house_kernel_denial_records_nothing_but_a_verified_actuation_succeeds(
        tmp_path, monkeypatch):
    """The house handler raises on a failed result (the task must not settle as DONE),
    so its refusal reaches the worker as an exception carrying the reason."""
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import HOUSE_CONTROL_KIND, register_house_handlers
    from agents.core.kernel import Verdict
    from tests.test_h30_house_actuation import _actuator, _Kernel, _Simulator

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    queue = _queue(tmp_path / "autonomy.db")
    sim = _Simulator()
    denied = register_house_handlers(
        TaskExecutor(), _actuator(tmp_path / "deny", sim, kernel=_Kernel(Verdict.DENY)))
    task = await _run_real(queue, denied.execute, HOUSE_CONTROL_KIND, _HOUSE, ticks=MAX_ATTEMPTS)
    assert task.status == TaskStatus.FAILED.value and "kernel_denied" in task.result["error"]
    assert sim.calls == [] and _counts(queue, HOUSE_CONTROL_KIND) == (0, 0)

    granted = register_house_handlers(TaskExecutor(), _actuator(tmp_path / "grant", sim))
    task = await _run_real(queue, granted.execute, HOUSE_CONTROL_KIND, _HOUSE)
    assert task.result["status"] == "verified" and sim.state == "on"
    assert _counts(queue, HOUSE_CONTROL_KIND) == (1, 0)
    queue.close()


@pytest.mark.asyncio
async def test_channel_reply_contract_block_records_nothing_but_a_send_does(tmp_path):
    from agents.core.channel_reply import ChannelReplyBroker

    class Channels:
        def __init__(self, sent=True):
            self.sent, self.ok = [], sent

        async def send_channel_reply(self, channel, text, **reply):
            self.sent.append((channel, text))
            return self.ok

    queue = _queue(tmp_path / "autonomy.db")
    reply = {"channel": "telegram", "text": "hi", "thread_id": "t1", "message_id": "m1",
             "reply": {"chat_id": "1"}}
    channels = Channels()
    broker = ChannelReplyBroker(channel_manager=channels)
    task = await _run_real(queue, broker.execute, "channel.reply", {"channel": "telegram", "text": "hi"})
    assert task.result["status"] == "blocked" and channels.sent == []
    assert _counts(queue, "channel.reply") == (0, 0)

    task = await _run_real(queue, broker.execute, "channel.reply", reply)
    assert task.result["status"] == "ok" and channels.sent == [("telegram", "hi")]
    assert _counts(queue, "channel.reply") == (1, 0)

    broken = ChannelReplyBroker(channel_manager=Channels(sent=False))
    task = await _run_real(queue, broken.execute, "channel.reply", reply)
    assert task.result["reason"] == "send_failed"
    assert _counts(queue, "channel.reply") == (1, 1)
    queue.close()


@pytest.mark.asyncio
async def test_node_reauthorisation_denial_records_nothing(tmp_path):
    from agents.core.node_mesh import KIND, NodeMesh
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    queue = _queue(tmp_path / "autonomy.db")
    kill = KillSwitch(path=str(tmp_path / "kill.json"))
    mesh = NodeMesh(capability_broker=CapabilityBroker(), kill_switch=kill)
    mesh.register_node("phone", ["notify"])
    kill.engage()
    task = await _run_real(queue, mesh.execute, KIND, {"node": "phone", "capability": "notify"})
    assert task.result["status"] == "failed" and "kill-switch" in task.result["reason"]
    task = await _run_real(queue, mesh.execute, KIND, {"node": "gone", "capability": "notify"})
    assert task.result == {"status": "failed", "reason": "unknown_node", "node": "gone"}
    assert _counts(queue, KIND) == (0, 0)
    queue.close()


@pytest.mark.asyncio
async def test_missing_credential_records_nothing_but_a_delivered_write_succeeds(tmp_path):
    from agents.core.social import HttpSocialClient, SocialBroker
    from agents.core.writeback import HttpWriteBackClient, WriteBackBroker

    class Social:
        async def send(self, platform, action, fields, credentials):
            return {"status": "ok", "id": "1"}

    class Target:
        async def write(self, target, action, fields, credentials):
            return {"status": "ok", "id": "2"}

    queue = _queue(tmp_path / "autonomy.db")
    post = {"platform": "x", "action": "post", "fields": {"text": "hi"}}
    issue = {"system": "github", "action": "create_issue", "fields": {"repo": "a/b", "title": "t"}}
    cases = [
        ("social.x.post", post, SocialBroker(client=HttpSocialClient()), SocialBroker(client=Social())),
        ("writeback.github.create_issue", issue,
         WriteBackBroker(client=HttpWriteBackClient()), WriteBackBroker(client=Target())),
    ]
    for kind, payload, unconfigured, configured in cases:
        task = await _run_real(queue, unconfigured.execute, kind, payload)
        assert task.result["reason"] == "credential_not_configured", kind
        assert _counts(queue, kind) == (0, 0), kind
        task = await _run_real(queue, configured.execute, kind, payload)
        assert task.result["status"] == "ok", kind
        assert _counts(queue, kind) == (1, 0), kind
    queue.close()


@pytest.mark.asyncio
async def test_tool_rpc_and_skill_install_refusals_record_nothing(tmp_path):
    from agents.core.acquisition.promotion import PromotionBroker
    from agents.core.tool_rpc import ToolRPCServer

    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, ToolRPCServer().execute, "tool.rpc",
                           {"tool": "not_registered", "args": {}})
    assert task.result["reason"] == "tool_not_allowed"
    assert _counts(queue, "tool.rpc") == (0, 0)

    off = dict.fromkeys(("quarantine", "requests", "proposals", "packages", "journal",
                         "tool_rpc", "runtime", "marketplace", "profile"))
    broker = PromotionBroker(enabled=lambda: False, **off)
    task = await _run_real(queue, broker.execute_task, "skill.install", {"proposal_id": "p1"})
    assert task.result == {"status": "failed", "reason": "promotion_refused"}
    assert _counts(queue, "skill.install") == (0, 0)
    queue.close()


def test_refusal_vocabulary_names_refusals_only():
    """The vocabulary decides only for a returned ``failed``: a reason in it ran nothing.
    Every reason a handler uses for an attempt that broke stays out of it, and so does
    any reason nobody listed."""
    from agents.core.autonomy.worker import REFUSAL_REASONS, is_refusal

    for reason in ("interrupt_budget_exhausted", "budget_exceeded", "credential_not_configured",
                   "kernel_denied", "strong_confirmation_required", "execution_in_progress",
                   "tool_not_allowed", "promotion_refused", "human_decision_required",
                   "changed_since_request", "not_requested", "provider_revision_conflict",
                   "unknown_node"):
        assert reason in REFUSAL_REASONS, reason
        assert is_refusal({"status": "failed", "reason": reason}), reason
    assert is_refusal({"status": "failed", "reason": "call_config_missing:account_sid,from"})
    assert is_refusal({"status": "failed", "reason": "kill-switch engaged for scope 'node:phone'"})
    for reason in ("client_error", "send_failed", "tool_error", "apply_failed", "invalid_call",
                   "verification_failed", "wall_time_budget_exceeded", "invalid_result",
                   "house_state_unavailable", "something_new", "", None):
        assert reason not in REFUSAL_REASONS, reason
        assert not is_refusal({"status": "failed", "reason": reason}), reason
    assert is_refusal({"status": "refused", "reason": "anything"})
    assert is_refusal({"status": "blocked", "reason": "missing_field:thread_id"})
    assert not is_refusal({"status": "ok"}) and not is_refusal(None)


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
