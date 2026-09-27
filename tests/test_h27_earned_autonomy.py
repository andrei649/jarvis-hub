from __future__ import annotations

import sqlite3
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


def _house_rig(tmp_path, monkeypatch, sim):
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.house.actuation import register_house_handlers
    from tests.test_h30_house_actuation import _actuator

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    actuator = _actuator(tmp_path / "house", sim)
    return actuator, register_house_handlers(TaskExecutor(), actuator)


@pytest.mark.asyncio
async def test_house_verification_failure_raised_by_the_handler_records_a_failure(
        tmp_path, monkeypatch):
    """Round 3, item 3: the device was commanded and never reached the state asked for.
    The registered handler raises ``HouseActuationError("verification_failed")``; a
    reason on a raised error is not by itself a refusal, so this records a failure."""
    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import HOUSE_CONTROL_KIND
    from tests.test_h30_house_actuation import _Simulator

    sim = _Simulator()
    sim.apply_updates = False                       # the light never turns on
    _actuator, executor = _house_rig(tmp_path, monkeypatch, sim)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, executor.execute, HOUSE_CONTROL_KIND, _HOUSE, ticks=MAX_ATTEMPTS)
    assert task.status == TaskStatus.FAILED.value
    assert task.result == {"error": "verification_failed"}
    assert len(sim.calls) == 1                      # commanded once; retries read the cache
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 1)
    queue.close()


@pytest.mark.asyncio
async def test_house_attempt_that_actuated_then_raised_is_a_failure_not_in_progress(
        tmp_path, monkeypatch):
    """Round 3, item 2: the first attempt commands the device, verification fails and the
    ledger's ``finish`` raises once (sqlite busy), leaving the attempt's row ``running``.
    The retries must not read that stranded row as a concurrent execution (the refusal
    ``execution_in_progress``): the device was commanded and nobody verified it, so the
    task fails as ``execution_stranded`` and records a failure — and the device is never
    commanded a second time."""
    import sqlite3

    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import HOUSE_CONTROL_KIND
    from tests.test_h30_house_actuation import _Simulator

    sim = _Simulator()
    sim.apply_updates = False
    actuator, executor = _house_rig(tmp_path, monkeypatch, sim)
    real_finish = actuator._ledger.finish
    calls = {"n": 0}

    def flaky_finish(task_id, result):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_finish(task_id, result)

    monkeypatch.setattr(actuator._ledger, "finish", flaky_finish)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, executor.execute, HOUSE_CONTROL_KIND, _HOUSE, ticks=MAX_ATTEMPTS)
    assert task.status == TaskStatus.FAILED.value
    # Round 4 (hunt NIT 1): the task record says a human must look at the device.
    assert task.result == {"error": "execution_stranded", "manual_recovery_required": True}
    assert len(sim.calls) == 1
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 1)
    queue.close()


@pytest.mark.parametrize("begun_with", ["same_payload", "other_payload"])
@pytest.mark.asyncio
async def test_house_row_stranded_by_a_crash_is_a_failure_and_never_reactuates(
        tmp_path, monkeypatch, begun_with):
    """The same after a crash between ``begin`` and ``finish``: the row is ``running``
    and no execution of the task is in flight in this process. An unfinished row is a
    begun attempt whatever payload it began with (never ``task_payload_changed``)."""
    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import (
        HOUSE_CONTROL_KIND,
        _canonical_task,
        _payload_hash,
    )
    from tests.test_h30_house_actuation import _Simulator

    sim = _Simulator()
    actuator, executor = _house_rig(tmp_path, monkeypatch, sim)
    queue = _queue(tmp_path / "autonomy.db")
    task_id = queue.enqueue("jarvis", HOUSE_CONTROL_KIND, "real handler", risk_tier=1,
                            autonomy_level=ACT, payload=_HOUSE)
    digest = _payload_hash(_canonical_task(HOUSE_CONTROL_KIND, queue.get(task_id).payload))
    if begun_with == "other_payload":
        digest = "0" * len(digest)
    assert actuator._ledger.begin(task_id, digest)      # the attempt that died
    queue.transition(task_id, TaskStatus.APPROVED)
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor.execute)
    for _ in range(MAX_ATTEMPTS):
        await worker.tick()
    task = queue.get(task_id)
    assert task.status == TaskStatus.FAILED.value
    # Round 4 (hunt NIT 1): the task record says a human must look at the device.
    assert task.result == {"error": "execution_stranded", "manual_recovery_required": True}
    assert sim.calls == []
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 1)
    queue.close()


@pytest.mark.asyncio
async def test_house_concurrent_execution_of_the_same_task_is_a_refusal(tmp_path, monkeypatch):
    """The genuine ``execution_in_progress``: another execution of this very task is in
    flight right now (its device call has not returned). This attempt ran nothing and
    records nothing; the execution in flight completes on its own."""
    import asyncio

    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import HOUSE_CONTROL_KIND
    from tests.test_h30_house_actuation import _Simulator

    sim = _Simulator()
    actuator, executor = _house_rig(tmp_path, monkeypatch, sim)
    entered, release = asyncio.Event(), asyncio.Event()
    real_apply = sim.apply

    async def held_apply(command):
        entered.set()
        await release.wait()
        return await real_apply(command)

    sim.apply = held_apply
    queue = _queue(tmp_path / "autonomy.db")
    task_id = queue.enqueue("jarvis", HOUSE_CONTROL_KIND, "real handler", risk_tier=1,
                            autonomy_level=ACT, payload=_HOUSE)
    queue.transition(task_id, TaskStatus.APPROVED)
    in_flight = asyncio.create_task(actuator.execute_task(queue.get(task_id)))
    await asyncio.wait_for(entered.wait(), 5)
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor.execute)
    for _ in range(MAX_ATTEMPTS):
        await worker.tick()
    task = queue.get(task_id)
    assert task.status == TaskStatus.FAILED.value
    assert task.result == {"error": "execution_in_progress"}
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 0)
    release.set()
    assert (await asyncio.wait_for(in_flight, 5))["status"] == "verified"
    assert len(sim.calls) == 1 and sim.state == "on"
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
    """Refusals before anything ran. For ``skill.install`` that is ``promotion_refused``,
    which since round 3 names only a check that declined before any install work (here:
    acquisition disabled) — an install that breaks once it began is ``install_failed``
    and records a failure (the tests below)."""
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


async def _approved_promotion(tmp_path):
    from tests.test_h32_promotion import _broker, _contract, _verified_artifact

    requests, _request, package, profile, _receipt, quarantine = await _verified_artifact(tmp_path)
    broker, packages, _server, _market = _broker(tmp_path, requests=requests,
                                                 quarantine=quarantine, profile=profile)
    proposal = broker.propose(package.artifact_id, contract=_contract())
    broker.decide(proposal.proposal_id, approved=True, actor="owner", permanent=True)
    return broker, packages, {"proposal_id": proposal.proposal_id}


@pytest.mark.asyncio
async def test_skill_install_that_breaks_once_the_install_began_records_a_failure(
        tmp_path, monkeypatch):
    """Round 3, item 1: ``promotion_refused`` is only a refusal before any install work.
    Here the package store raises once, mid-install: that is ``install_failed``, a
    failure; the next task installs, a success."""
    from agents.core.acquisition.package_store import PackageStoreError

    broker, packages, payload = await _approved_promotion(tmp_path)
    real_install, attempts = packages.install, []

    def install_once(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise PackageStoreError("disk full while writing the package")
        return real_install(**kwargs)

    monkeypatch.setattr(packages, "install", install_once)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result == {"status": "failed", "reason": "install_failed"}
    assert len(attempts) == 1 and _counts(queue, "skill.install") == (0, 1)
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result["status"] == "installed" and len(attempts) == 2
    assert _counts(queue, "skill.install") == (1, 1)
    queue.close()


@pytest.mark.parametrize("seam", ["journal_begin", "journal_advance"])
@pytest.mark.asyncio
async def test_skill_install_journal_commit_error_is_a_failure(tmp_path, monkeypatch, seam):
    """A journal that cannot commit (the first durable write of the install, or a later
    stage) is the install's own machinery failing, never a refusal."""
    from agents.core.acquisition.promotion import PromotionError

    broker, _packages, payload = await _approved_promotion(tmp_path)

    def cannot_commit(*_args, **_kwargs):
        raise PromotionError("cannot atomically commit promotion store")

    monkeypatch.setattr(broker.journal, seam.split("_", 1)[1], cannot_commit)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result == {"status": "failed", "reason": "install_failed"}
    assert _counts(queue, "skill.install") == (0, 1)
    queue.close()


@pytest.mark.parametrize("store", ["proposals", "quarantine"])
@pytest.mark.asyncio
async def test_skill_install_store_unreadable_before_any_work_is_a_failure(
        tmp_path, monkeypatch, store):
    """Before the journal begins nothing was installed, but a proposal or quarantine
    store that cannot be read is the machinery failing, not a gate declining: a
    failure, under its own reason. A proposal that is not approved stays a refusal."""
    from agents.core.acquisition.promotion import PromotionError
    from agents.core.acquisition.quarantine import QuarantineError

    broker, _packages, payload = await _approved_promotion(tmp_path)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", {"proposal_id": "unknown"})
    assert task.result == {"status": "failed", "reason": "promotion_refused"}
    assert _counts(queue, "skill.install") == (0, 0)

    if store == "proposals":
        def unreadable(*_args, **_kwargs):
            raise PromotionError("cannot decrypt or validate promotion store")

        monkeypatch.setattr(broker.proposals, "_read_payload", unreadable)
        monkeypatch.setattr(broker.proposals, "_rows", None)
    else:
        def unreadable(*_args, **_kwargs):
            raise QuarantineError("cannot decrypt or validate quarantine")

        monkeypatch.setattr(broker.quarantine, "get_record", unreadable)
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result == {"status": "failed", "reason": "promotion_store_unavailable"}
    assert _counts(queue, "skill.install") == (0, 1)
    queue.close()


@pytest.mark.asyncio
async def test_tool_rpc_classifier_crash_records_a_failure(tmp_path):
    """Round 3, item 5: a classifier that raises is the tool's own machinery failing;
    ``classify_failed`` left the refusal vocabulary, so it records a failure."""
    from agents.core.tool_rpc import ToolRPCServer

    ran = []

    async def handler(args):
        ran.append(args)
        return {"ok": True}

    def classifier(_args):
        raise RuntimeError("classifier bug")

    server = ToolRPCServer().register_tool("labelled", handler, gated=True, classifier=classifier)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, server.execute, "tool.rpc", {"tool": "labelled", "args": {}})
    assert task.result["reason"] == "classify_failed" and ran == []
    assert _counts(queue, "tool.rpc") == (0, 1)
    queue.close()


def test_refusal_vocabulary_is_per_kind_and_names_refusals_only():
    """The vocabulary decides only for a returned ``failed``: a reason in it ran nothing.
    Round 4, item 4: it is a mapping kind -> reasons (and kind -> prefixes), so a reason
    one handler uses as a refusal is never read as a refusal from another kind's handler.
    Every reason a handler uses for an attempt that broke stays out of it, and so does
    any reason nobody listed."""
    from agents.core.autonomy.worker import (
        REFUSAL_REASON_PREFIXES_BY_KIND,
        REFUSAL_REASONS_BY_KIND,
        WITHHELD_REASONS_BY_KIND,
        is_refusal,
        is_refusal_reason,
        is_withheld,
    )
    from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS

    # Every manifest kind has an entry (an empty one when its handler never returns a
    # refusal as ``failed``), and nothing else does.
    assert set(REFUSAL_REASONS_BY_KIND) == set(ACTION_CAPABILITY_MANIFESTS)
    assert set(REFUSAL_REASON_PREFIXES_BY_KIND) <= set(ACTION_CAPABILITY_MANIFESTS)
    assert set(WITHHELD_REASONS_BY_KIND) <= set(ACTION_CAPABILITY_MANIFESTS)
    # No reason is shared by accident: every reason more than one kind lists is listed
    # here, with exactly the kinds that list it, on purpose.
    kinds_by_reason: dict[str, set[str]] = {}
    for kind, reasons in REFUSAL_REASONS_BY_KIND.items():
        for reason in reasons:
            kinds_by_reason.setdefault(reason, set()).add(kind)
    house = {"house.control", "house.security_control"}
    voice_and_grant = {"settings.voice_command", "permission.grant"}
    assert {reason: kinds for reason, kinds in kinds_by_reason.items() if len(kinds) > 1} == {
        "credential_not_configured": {"call.outbound", "social.*", "writeback.*"},
        "kernel_denied": house | {"tool.rpc"},
        "execution_in_progress": house,
        "task_payload_changed": house,
        # round 5, item 6: the two switches, decided before any driver call.
        "unified_action_api_disabled": house,
        "action_kernel_disabled": house,
        "human_decision_required": voice_and_grant,
        "decision_not_approval": voice_and_grant,
        "payload_required": voice_and_grant,
    }
    # A withheld reason is never also a refusal, for any kind.
    for kind, reasons in WITHHELD_REASONS_BY_KIND.items():
        assert not set(reasons) & set().union(*REFUSAL_REASONS_BY_KIND.values()), kind

    for kind, reason in (("call.outbound", "interrupt_budget_exhausted"),
                         ("call.outbound", "budget_exceeded"),
                         ("call.outbound", "credential_not_configured"),
                         ("house.control", "kernel_denied"),
                         ("house.security_control", "strong_confirmation_required"),
                         ("house.control", "execution_in_progress"),
                         ("tool.rpc", "tool_not_allowed"),
                         ("tool.rpc", "kernel_denied"),
                         ("skill.install", "promotion_refused"),
                         ("settings.voice_command", "human_decision_required"),
                         ("settings.voice_command", "changed_since_request"),
                         ("settings.voice_command", "not_requested"),
                         ("settings.voice_command", "provider_revision_conflict"),
                         ("node.dispatch", "unknown_node"),
                         ("plugin.egress", "URL monitor execution claim required")):
        assert reason in REFUSAL_REASONS_BY_KIND[kind], (kind, reason)
        assert is_refusal(kind, {"status": "failed", "reason": reason}), (kind, reason)
    # The kind resolves like the manifests: exact first, then a ``.*`` pattern.
    assert is_refusal("social.x.post", {"status": "failed", "reason": "postiz_not_configured"})
    assert is_refusal("writeback.github.create_issue",
                      {"status": "failed", "reason": "credential_not_configured"})
    assert is_refusal("call.outbound", {"status": "failed", "reason": "call_config_missing:account_sid,from"})
    assert is_refusal("node.dispatch",
                      {"status": "failed", "reason": "kill-switch engaged for scope 'node:phone'"})
    # ... and a reason, or a prefix, is a refusal only for the kind that uses it.
    for kind, reason in (("call.outbound", "kernel_denied"), ("tool.rpc", "execution_in_progress"),
                         ("house.control", "tool_not_allowed"),
                         ("house.control", "strong_confirmation_required"),
                         ("kg.write", "kernel_denied"), ("social.x.post", "interrupt_budget_exhausted"),
                         ("node.dispatch", "call_config_missing:account_sid"),
                         ("call.outbound", "kill-switch engaged for scope 'node:phone'"),
                         ("unknown.action", "kernel_denied")):
        assert not is_refusal_reason(kind, reason), (kind, reason)
        assert not is_refusal(kind, {"status": "failed", "reason": reason}), (kind, reason)
    every_kind = list(REFUSAL_REASONS_BY_KIND)
    for reason in ("client_error", "send_failed", "tool_error", "apply_failed", "invalid_call",
                   "verification_failed", "wall_time_budget_exceeded", "invalid_result",
                   "house_state_unavailable", "something_new", "", None,
                   # machinery failures and reasons that can follow an attempt
                   "classify_failed", "provider_store_unavailable", "install_failed",
                   "promotion_store_unavailable", "execution_stranded", "validation_failed",
                   "attention_ledger_unavailable", "work_run_ledger_unavailable",
                   "withheld_after_generation",
                   # round 5: a broker that failed to start, a kernel that broke
                   "capability_broker_unavailable", "kernel_error", "kernel_unavailable",
                   "local_guard_failed", "backend_source_changed"):
        for kind in every_kind:
            assert not is_refusal(kind, {"status": "failed", "reason": reason}), (kind, reason)
    # The one class that is neither: an image generated, then withheld by governance.
    assert is_withheld("tool.rpc", {"status": "failed", "reason": "withheld_after_generation"})
    assert not is_withheld("call.outbound", {"status": "failed", "reason": "withheld_after_generation"})
    assert not is_withheld("tool.rpc", {"status": "ok", "reason": "withheld_after_generation"})
    assert is_refusal("kg.write", {"status": "refused", "reason": "anything"})
    assert is_refusal("channel.reply", {"status": "blocked", "reason": "missing_field:thread_id"})
    assert not is_refusal("kg.write", {"status": "ok"}) and not is_refusal("kg.write", None)
    # Only a FAILED result is read through the vocabulary: a success that happens to
    # carry a listed reason is still a success.
    assert not is_refusal("tool.rpc", {"status": "ok", "reason": "kernel_denied"})
    assert not is_refusal("house.control", {"status": "verified", "reason": "execution_in_progress"})


@pytest.mark.asyncio
async def test_a_reason_is_a_refusal_only_from_the_kind_that_uses_it(tmp_path):
    """Round 4, item 4: ``kernel_denied`` is house's and tool.rpc's refusal. A call or a
    graph write never says it, so from their handlers it is a failure, not a refusal
    borrowed from another kind; from tool.rpc it still records nothing."""
    queue = _queue(tmp_path / "autonomy.db")

    def returning(result):
        async def executor(_task):
            return dict(result)
        return executor

    await _run_real(queue, returning({"status": "failed", "reason": "kernel_denied"}),
                    "call.outbound", _CALL)
    await _run_real(queue, returning({"status": "failed", "reason": "tool_not_allowed"}),
                    "kg.write", {})
    await _run_real(queue, returning({"status": "failed", "reason": "kernel_denied"}),
                    "tool.rpc", {"tool": "image_generate"})
    assert _counts(queue, "call.outbound") == (0, 1)
    assert _counts(queue, "kg.write") == (0, 1)
    assert _counts(queue, "tool.rpc") == (0, 0)
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


# ── round 4, item 1: a task's outcome is decided over ALL its attempts ─────────


class _RaisedRefusal(RuntimeError):
    """A refusal raised instead of returned (the shape of the house handler's)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


async def _attempts(queue, kind, outcomes):
    """One approved task of *kind*, each attempt run by a FRESH worker (what an earlier
    attempt did must be durable, not a worker's memory). The executor plays *outcomes*
    in order: an exception is raised, a dict is returned."""
    from agents.core.autonomy.worker import MAX_ATTEMPTS

    task_id = queue.enqueue("jarvis", kind, "attempts", risk_tier=1, autonomy_level=ACT,
                            payload={})
    queue.transition(task_id, TaskStatus.APPROVED)
    script = iter(outcomes)

    async def executor(_task):
        outcome = next(script)
        if isinstance(outcome, BaseException):
            raise outcome
        return dict(outcome)

    for _ in range(MAX_ATTEMPTS):
        await AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor).tick()
    return queue.get(task_id)


@pytest.mark.parametrize("kind, outcomes", [
    # open_run-style: the first attempt wrote the run, then its commit raised; the
    # retry finds the run it wrote and returns the ledger's refusal.
    ("goal.approve", [sqlite3.OperationalError("disk I/O error"),
                      {"status": "refused", "reason": "run_already_open_for_goal"}]),
    ("call.outbound", [RuntimeError("carrier timed out after dialling"),
                       {"status": "failed", "reason": "interrupt_budget_exhausted"}]),
    # The house handler raises its refusals: the retries after an attempt that broke
    # raise ``execution_in_progress`` until the retry budget is spent.
    ("house.control", [RuntimeError("database is locked"),
                       _RaisedRefusal("execution_in_progress"),
                       _RaisedRefusal("execution_in_progress")]),
], ids=["open_run_refused_on_retry", "returned_failed_refusal", "raised_refusal"])
@pytest.mark.asyncio
async def test_a_refusal_after_an_attempt_that_broke_records_one_failure(tmp_path, kind, outcomes):
    """Round 4, item 1 (closure E): an attempt raised, and a later attempt of the same
    task returned (or raised) a refusal. The refusal is true of THAT attempt, but the
    task did attempt the capability and it broke: one failure, never nothing."""
    queue = _queue(tmp_path / "autonomy.db")
    task = await _attempts(queue, kind, outcomes)
    assert task.attempts == len(outcomes)
    assert _counts(queue, kind) == (0, 1)
    queue.close()


@pytest.mark.parametrize("kind, outcomes, expected", [
    ("goal.approve", [{"status": "refused", "reason": "run_already_open_for_goal"}], (0, 0)),
    ("call.outbound", [{"status": "failed", "reason": "interrupt_budget_exhausted"}], (0, 0)),
    ("house.control", [_RaisedRefusal("execution_in_progress")] * 3, (0, 0)),
    # A refusal raised by an earlier attempt is not a failure either.
    ("house.control", [_RaisedRefusal("kernel_denied"),
                       {"status": "failed", "reason": "kernel_denied"}], (0, 0)),
    # A later attempt that succeeds is the task's one outcome.
    ("call.outbound", [RuntimeError("carrier timed out"), {"status": "ok"}], (1, 0)),
], ids=["returned_refused", "returned_failed_refusal", "raised_refusals",
        "refusal_then_refusal", "broke_then_succeeded"])
@pytest.mark.asyncio
async def test_a_refusal_with_no_attempt_that_broke_still_records_nothing(
        tmp_path, kind, outcomes, expected):
    """Round 4, item 1, the guard: a refusal on the first attempt (or on every attempt)
    records nothing, and a success after an attempt that broke records one success."""
    queue = _queue(tmp_path / "autonomy.db")
    await _attempts(queue, kind, outcomes)
    assert _counts(queue, kind) == expected
    queue.close()


@pytest.mark.asyncio
async def test_skill_install_retry_after_a_partial_install_records_one_failure(tmp_path, monkeypatch):
    """Round 4, items 1 and 2 (hunt MINOR 1, the round-3 hunter's repro): the install
    ran — package active, tool registered — then ``mark_installed`` raised something
    that is not a PromotionError. The task records exactly one failure, never the
    ``promotion_refused`` a retry would read, and never nothing."""
    from agents.core.autonomy.worker import MAX_ATTEMPTS

    broker, packages, payload = await _approved_promotion(tmp_path)
    real_mark, calls = broker.proposals.mark_installed, []

    def mark_once(proposal_id):
        calls.append(proposal_id)
        if len(calls) == 1:
            raise RuntimeError("secret store hiccup while encrypting")
        return real_mark(proposal_id)

    monkeypatch.setattr(broker.proposals, "mark_installed", mark_once)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", payload, ticks=MAX_ATTEMPTS)
    name = broker.journal.get(payload["proposal_id"]).name
    assert packages.get(name) is not None and broker.tool_rpc.allows(name)
    # Item 1 (the worker, over all attempts) alone gives this: one failure...
    assert _counts(queue, "skill.install") == (0, 1)
    # ... and item 2 (the handler) makes the first attempt say so itself, so no retry
    # ever reads the refusal.
    assert task.result == {"status": "failed", "reason": "install_failed"}
    assert len(calls) == 1
    queue.close()


# ── round 4, item 2: every error once the install began is install_failed ─────


@pytest.mark.parametrize("seam, error", [
    ("proposals.mark_installed", RuntimeError("secret store hiccup")),
    ("marketplace.index_acquired_package", KeyError("catalog")),
    ("tool_rpc.register_tool", ValueError("tool name already registered")),
])
@pytest.mark.asyncio
async def test_skill_install_any_error_once_the_install_began_is_install_failed(
        tmp_path, monkeypatch, seam, error):
    """Hunt MINOR 1: not only a PromotionError — any error raised from ``journal.begin``
    onward is the install breaking: ``install_failed``, a failure, returned by the
    handler (never escaping it to be retried into a refusal)."""
    broker, _packages, payload = await _approved_promotion(tmp_path)
    owner, method = seam.split(".")

    def broken(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(getattr(broker, owner), method, broken)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result == {"status": "failed", "reason": "install_failed"}
    assert _counts(queue, "skill.install") == (0, 1)
    queue.close()


@pytest.mark.asyncio
async def test_skill_install_journal_unreadable_inside_begin_is_store_unavailable(tmp_path, monkeypatch):
    """Hunt NIT 3: a journal that cannot be read inside ``journal.begin`` has written
    nothing yet — ``promotion_store_unavailable`` (a failure), not ``install_failed``."""
    from agents.core.acquisition.promotion import PromotionError

    broker, packages, payload = await _approved_promotion(tmp_path)

    def unreadable():
        raise PromotionError("cannot decrypt or validate promotion store")

    monkeypatch.setattr(broker.journal, "_read_payload", unreadable)
    monkeypatch.setattr(broker.journal, "_rows", None)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result == {"status": "failed", "reason": "promotion_store_unavailable"}
    assert packages.list_records() == []
    assert _counts(queue, "skill.install") == (0, 1)
    queue.close()


@pytest.mark.asyncio
async def test_skill_install_quarantine_hash_mismatch_is_a_refusal(tmp_path):
    """Hunt NIT 3: the quarantine's package hash check is a pre-install check that
    declined (a tampered package), like the receipt tamper check: ``promotion_refused``,
    nothing installed, nothing recorded. An unreadable quarantine stays a failure (the
    store-unreadable test above)."""
    from dataclasses import replace

    broker, packages, payload = await _approved_promotion(tmp_path)
    broker.quarantine._records = [
        replace(record, package=replace(record.package, code=record.package.code + "\n# tampered"))
        for record in broker.quarantine._load()
    ]
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result == {"status": "failed", "reason": "promotion_refused"}
    assert packages.list_records() == []
    assert _counts(queue, "skill.install") == (0, 0)
    queue.close()


# ── round 4, item 5: store failures are failures, not refusals ────────────────


@pytest.mark.asyncio
async def test_call_with_an_unavailable_attention_ledger_is_a_failure(tmp_path):
    """Closure B: the attention ledger that cannot be read is the call's own machinery
    failing — ``attention_ledger_unavailable``, a failure — while a spent interrupt
    budget stays the refusal ``interrupt_budget_exhausted``. No call is placed."""
    from agents.core.ambient.policy import AttentionDeliveryBroker, AttentionLedger
    from agents.core.autonomy.call_broker import CallBroker

    placed = []

    class Client:
        async def call(self, *args):
            placed.append(args)
            return {"status": "ok"}

    def budget(ledger):
        return type("Budget", (), {"delivery_broker": AttentionDeliveryBroker(ledger)})()

    closed = AttentionLedger(tmp_path / "closed.db", timezone_name="Europe/Bucharest")
    closed.close()                                   # the store is gone
    spent = AttentionLedger(tmp_path / "spent.db", timezone_name="Europe/Bucharest", per_day=0)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, CallBroker(client=Client(), budget=budget(closed)).execute,
                           "call.outbound", _CALL)
    assert task.result == {"status": "failed", "reason": "attention_ledger_unavailable"}
    assert _counts(queue, "call.outbound") == (0, 1)
    task = await _run_real(queue, CallBroker(client=Client(), budget=budget(spent)).execute,
                           "call.outbound", _CALL)
    assert task.result == {"status": "failed", "reason": "interrupt_budget_exhausted"}
    assert _counts(queue, "call.outbound") == (0, 1)
    assert placed == []
    spent.close()
    queue.close()


@pytest.mark.asyncio
async def test_goal_approve_with_a_work_run_ledger_that_failed_to_construct_is_a_failure(
        tmp_path, monkeypatch):
    """Closure D: the coordinator binds the work-run ledger whatever the flag says, so
    a missing ledger at execution means it failed to construct — machinery, reported
    as ``failed`` (a failure), never as a ``refused`` that ran nothing."""
    import time

    from agents.core.autonomy import work_runs
    from agents.core.autonomy.goal_contract import GoalDraft, SuccessCheck, propose
    from tests.test_web_tools_wiring import _coordinator

    def cannot_open(self, *_args, **_kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(work_runs.WorkRunLedger, "__init__", cannot_open)
    executor = _coordinator({}).build_executor()
    draft = GoalDraft(title="Prepare the quarterly brief", scope_kinds=("research",),
                      budget=work_runs.Budget(max_steps=5), deadline_at=time.time() + 86_400,
                      stop_conditions=("the source data goes stale",),
                      checks=(SuccessCheck(id="brief", describe="the brief exists"),))
    intake = []
    propose(draft, lambda **kwargs: intake.append(kwargs) or 1)
    queue = _queue(tmp_path / "autonomy.db")
    task_id = queue.enqueue("jarvis", "goal.approve", "Approve goal", risk_tier=3,
                            autonomy_level=ASK, payload=intake[0]["payload"])
    queue.transition(task_id, TaskStatus.APPROVED, decided_by="owner", decision="accept")
    await AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor.execute).tick()
    assert queue.get(task_id).result == {"status": "failed", "reason": "work_run_ledger_unavailable"}
    assert _counts(queue, "goal.approve") == (0, 1)
    queue.close()


# ── round 4, item 7: house — the recovery flag, the shared in-flight claim ────


@pytest.mark.asyncio
async def test_house_two_actuators_on_one_ledger_share_the_in_flight_claim(tmp_path, monkeypatch):
    """Hunt NIT 4: ``routers/house.py`` builds a new HouseActuator on the same ledger
    file when the orchestrator changes. An execution in flight through the first must
    read, through the second, as the refusal ``execution_in_progress`` — not as a
    stranded row (a failure asking for manual recovery) — and the device is commanded
    once. A claim kept per actuator instance fails this."""
    import asyncio

    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import HOUSE_CONTROL_KIND
    from tests.test_h30_house_actuation import _Simulator

    sim = _Simulator()
    first, _first_executor = _house_rig(tmp_path, monkeypatch, sim)
    second, executor = _house_rig(tmp_path, monkeypatch, sim)
    assert first is not second and first._ledger.path == second._ledger.path
    entered, release = asyncio.Event(), asyncio.Event()
    real_apply = sim.apply

    async def held_apply(command):
        entered.set()
        await release.wait()
        return await real_apply(command)

    sim.apply = held_apply
    queue = _queue(tmp_path / "autonomy.db")
    task_id = queue.enqueue("jarvis", HOUSE_CONTROL_KIND, "real handler", risk_tier=1,
                            autonomy_level=ACT, payload=_HOUSE)
    queue.transition(task_id, TaskStatus.APPROVED)
    in_flight = asyncio.create_task(first.execute_task(queue.get(task_id)))
    await asyncio.wait_for(entered.wait(), 5)
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor.execute)
    for _ in range(MAX_ATTEMPTS):
        await worker.tick()
    task = queue.get(task_id)
    assert task.status == TaskStatus.FAILED.value
    assert task.result == {"error": "execution_in_progress"}
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 0)
    release.set()
    assert (await asyncio.wait_for(in_flight, 5))["status"] == "verified"
    assert len(sim.calls) == 1 and sim.state == "on"
    queue.close()


# ── round 5, item 2: a store that cannot load is a store failure ──────────────


@pytest.mark.parametrize("corrupt", ["another_record", "this_record"])
@pytest.mark.asyncio
async def test_skill_install_a_record_failing_on_a_cold_load_is_a_store_failure(tmp_path, corrupt):
    """Hunt MINOR 2, through the real cold-load path: the records are committed to disk
    and the cache is cold (a restart). A record that fails its integrity check while the
    store loads makes the store unreadable — ``promotion_store_unavailable``, a failure
    (0,1) — not this package's integrity refusal. That holds for the approved package's
    own record too: a record that fails its hash check cannot be trusted to name its
    artifact (the artifact id is inside the hash). Only the package's own check on a
    record the store did load is ``promotion_refused`` (the in-memory test above)."""
    from dataclasses import replace

    broker, packages, payload = await _approved_promotion(tmp_path)
    store = broker.quarantine
    records = list(store._load())
    good = records[0]
    if corrupt == "another_record":
        other = replace(good.package, artifact_id="f" * len(good.package.artifact_id),
                        code=good.package.code + "\n# bit rot")
        on_disk = [*records, replace(good, package=other)]
    else:
        on_disk = [replace(good, package=replace(good.package, code=good.package.code + "\n# bit rot")),
                   *records[1:]]
    store._commit(on_disk)                # committed to disk
    store._records = None                 # a restart: the cache is cold
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, broker.execute_task, "skill.install", payload)
    assert task.result == {"status": "failed", "reason": "promotion_store_unavailable"}
    assert packages.list_records() == []
    assert _counts(queue, "skill.install") == (0, 1)
    queue.close()


# ── round 5, item 3: the worker's own bookkeeping is never a failed attempt ────


def _flaky_done(queue, monkeypatch):
    """The worker's ``queue.transition(..., DONE)`` raises once (a disk error, or a busy
    database past its timeout), then works."""
    real, raised = queue.transition, []

    def transition(task_id, new_status, **kwargs):
        if new_status == TaskStatus.DONE and not raised:
            raised.append(task_id)
            raise sqlite3.OperationalError("disk I/O error")
        return real(task_id, new_status, **kwargs)

    monkeypatch.setattr(queue, "transition", transition)
    return raised


@pytest.mark.parametrize("outcomes, expected, status", [
    # The handler SUCCEEDED (the run was opened), then the worker could not mark the task
    # DONE. The retry reads the handler's refusal for work it already did: the task's one
    # outcome is the success, recorded once — never a failure.
    ([{"status": "ok", "run_id": "r1"},
      {"status": "refused", "reason": "run_already_open_for_goal"}], (1, 0), "done"),
    # ... and a retry that then breaks does not undo it.
    ([{"status": "ok", "run_id": "r1"}, RuntimeError("database is locked"),
      RuntimeError("database is locked")], (1, 0), "failed"),
    # The success whose DONE raised is the final attempt: the task cannot settle DONE,
    # the capability still did the work.
    ([RuntimeError("carrier timed out"), RuntimeError("carrier timed out"),
      {"status": "ok"}], (1, 0), "failed"),
    # A refusal whose DONE raised is not an attempt that broke: the retry's refusal
    # still records nothing.
    ([{"status": "refused", "reason": "run_already_open_for_goal"},
      {"status": "refused", "reason": "run_already_open_for_goal"}], (0, 0), "done"),
    # Guard: the handler's own returned failure (DONE raised) then a success is the
    # all-attempts rule unchanged — the one success.
    ([{"status": "failed", "reason": "client_error"}, {"status": "ok"}], (1, 0), "done"),
], ids=["success_then_refusal", "success_then_raises", "success_on_the_last_attempt",
        "refusal_then_refusal", "failure_then_success"])
@pytest.mark.asyncio
async def test_a_done_transition_that_raised_is_the_workers_error_not_the_capabilitys(
        tmp_path, monkeypatch, outcomes, expected, status):
    """Round 5, item 3 (hunt MINOR 3): only an exception the capability's handler raises
    (``_execute``) is a failed attempt. The worker's own bookkeeping raising after the
    handler returned — ``queue.transition(DONE)`` — records that attempt's own outcome
    (a success once, marked durably so no later attempt records again), never a failure
    of the capability. Each attempt runs on a fresh worker."""
    queue = _queue(tmp_path / "autonomy.db")
    raised = _flaky_done(queue, monkeypatch)
    task = await _attempts(queue, "goal.approve", outcomes)
    assert raised, "the DONE transition never raised"
    assert task.status == status and task.attempts == len(outcomes)
    assert _counts(queue, "goal.approve") == expected
    queue.close()


# ── round 5, item 6: house — a broken kernel is a failure ─────────────────────


@pytest.mark.parametrize("kernel, reason", [
    ("raises", "kernel_error"),
    ("not_a_decision", "kernel_error"),
    ("missing", "kernel_unavailable"),
])
@pytest.mark.asyncio
async def test_house_kernel_that_broke_is_a_failure_not_kernel_denied(
        tmp_path, monkeypatch, kernel, reason):
    """Closure NIT: a kernel that raised, returned something that is not a Decision, or
    is not there is the house machinery failing — its own reason, a failure (0,1) —
    not the refusal ``kernel_denied``. The device is never commanded. A real Decision
    that denies stays ``kernel_denied`` and records nothing (the test above)."""
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import (
        HOUSE_CONTROL_KIND,
        HouseActuator,
        register_house_handlers,
    )
    from tests.test_h30_house_actuation import _Simulator

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")

    def raising(_action, capability=None):
        raise RuntimeError("policy store unreadable")

    def not_a_decision(_action, capability=None):
        return {"verdict": "grant"}

    sim = _Simulator()
    actuator = HouseActuator(
        state_reader=sim, driver=sim,
        authorizer={"raises": raising, "not_a_decision": not_a_decision, "missing": None}[kernel],
        outcome_provider=lambda _cap: {"total": 0, "confidence": 0.0},
        ledger_path=tmp_path / "actuation.db", clock=lambda: sim.now)
    queue = _queue(tmp_path / "autonomy.db")
    executor = register_house_handlers(TaskExecutor(), actuator)
    task = await _run_real(queue, executor.execute, HOUSE_CONTROL_KIND, _HOUSE, ticks=MAX_ATTEMPTS)
    assert task.status == TaskStatus.FAILED.value
    assert task.result == {"error": reason}
    assert sim.calls == [] and sim.state == "off"
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 1)
    queue.close()


@pytest.mark.parametrize("unset, reason", [
    ("JARVIS_UNIFIED_ACTION_API", "unified_action_api_disabled"),
    ("JARVIS_ACTION_KERNEL", "action_kernel_disabled"),
])
@pytest.mark.asyncio
async def test_house_switched_off_is_a_refusal_under_its_own_reason(tmp_path, monkeypatch, unset, reason):
    """The config states that mean "not allowed to run" — the unified action API or the
    kernel switched off — are decided before any driver call: refusals that record
    nothing, named for the switch (not ``kernel_denied``: no kernel denied anything)."""
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import HOUSE_CONTROL_KIND, register_house_handlers
    from tests.test_h30_house_actuation import _actuator, _Simulator

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.delenv(unset)
    sim = _Simulator()
    queue = _queue(tmp_path / "autonomy.db")
    executor = register_house_handlers(TaskExecutor(), _actuator(tmp_path, sim))
    task = await _run_real(queue, executor.execute, HOUSE_CONTROL_KIND, _HOUSE, ticks=MAX_ATTEMPTS)
    assert task.result == {"error": reason}
    assert sim.calls == []
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 0)
    queue.close()


@pytest.mark.parametrize("returned", ["approval_required", "kernel_denied"])
@pytest.mark.asyncio
async def test_house_a_reason_the_driver_returned_after_it_ran_is_never_a_refusal(
        tmp_path, monkeypatch, returned):
    """Closure NIT: ``CapabilityActionAPI._invoke`` maps a handler OUTPUT reason
    (``approval_required``, ``kernel_denied``) to queued/refused — after the handler ran.
    For the house the driver was called, so the device may have been commanded: the
    post-actuation verification decides (here the state never changed:
    ``verification_failed``, a failure), never the refusal ``kernel_denied``. The
    ledger row is finished, not aborted, so a retry never commands the device again."""
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from agents.core.house.actuation import HOUSE_CONTROL_KIND, register_house_handlers
    from tests.test_h30_house_actuation import _actuator, _Simulator

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator()
    sim.apply_updates = False

    async def refusing_apply(command):
        sim.calls.append(dict(command))
        return {"ok": False, "reason": returned}

    sim.apply = refusing_apply
    queue = _queue(tmp_path / "autonomy.db")
    executor = register_house_handlers(TaskExecutor(), _actuator(tmp_path, sim))
    task = await _run_real(queue, executor.execute, HOUSE_CONTROL_KIND, _HOUSE, ticks=MAX_ATTEMPTS)
    assert task.status == TaskStatus.FAILED.value
    assert task.result == {"error": "verification_failed"}
    assert len(sim.calls) == 1
    assert _counts(queue, HOUSE_CONTROL_KIND) == (0, 1)
    queue.close()


@pytest.mark.asyncio
async def test_house_rollback_names_a_broken_kernel_not_kernel_denied(tmp_path, monkeypatch):
    """The rollback's own perform: a kernel that raised on the recovery is
    ``kernel_error`` in the rollback record (manual recovery required), not the
    ``kernel_denied`` a real Decision gives (``test_h30_house_actuation``)."""
    from types import SimpleNamespace

    from agents.core.house.actuation import HOUSE_CONTROL_KIND
    from agents.core.kernel import Decision, Verdict
    from tests.test_h30_house_actuation import _actuator, _Simulator

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")

    def kernel(action, capability=None):
        if action.kind == HOUSE_CONTROL_KIND:
            return Decision(Verdict.GRANT, reason="ok", tier=1)
        raise RuntimeError("policy store unreadable")

    sim = _Simulator(state="on")
    sim.forced_state_after_apply = "jammed"
    result = await _actuator(tmp_path, sim, kernel=kernel).execute_task(
        SimpleNamespace(id=82, kind=HOUSE_CONTROL_KIND, agent="jarvis",
                        payload={**_HOUSE, "action": "off"}))
    assert result["reason"] == "verification_failed" and result["manual_recovery_required"] is True
    assert result["rollback"] == {"status": "failed", "reason": "kernel_error"}


# ── round 5, item 7: node.dispatch — a broker that failed to start ────────────


@pytest.mark.asyncio
async def test_node_without_a_capability_broker_is_a_failure(tmp_path):
    """Closure NIT: ``orch.capabilities`` is None only when its component failed to
    start, so ``capability_broker_unavailable`` is machinery — a failure (0,1), no
    longer in the refusal vocabulary. ``unknown_node`` stays a refusal."""
    from agents.core.autonomy.worker import is_refusal_reason
    from agents.core.node_mesh import KIND, NodeMesh

    mesh = NodeMesh(capability_broker=None)
    mesh.register_node("phone", ["notify"])
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, mesh.execute, KIND, {"node": "phone", "capability": "notify"})
    assert task.result == {"status": "failed", "reason": "capability_broker_unavailable",
                           "node": "phone"}
    assert _counts(queue, KIND) == (0, 1)
    assert not is_refusal_reason(KIND, "capability_broker_unavailable")
    assert is_refusal_reason(KIND, "unknown_node")
    queue.close()


# ── round 5, item 8: only an explicit success status records a success ────────


@pytest.mark.parametrize("result, expected", [
    # The cloud image runtime's "the submission may have happened, the result is not
    # known": an attempt that could have touched the world — a failure.
    ({"status": "unknown", "reason": "cloud image completion unavailable; submission not replayed"},
     (0, 1)),
    ({"status": "something_new"}, (0, 1)),
    ({"reason": "no status at all"}, (0, 1)),
    # Every success status a real handler returns (see SUCCESS_STATUSES), and the bare
    # ``{"ok": True}`` a handler returns without a status.
    ({"status": "ok"}, (1, 0)),
    ({"status": "redirect", "url": "https://jobs.example/next"}, (1, 0)),
    ({"status": "verified"}, (1, 0)),
    ({"status": "installed"}, (1, 0)),
    ({"ok": True}, (1, 0)),
], ids=["unknown", "unlisted_status", "no_status", "ok", "redirect", "verified", "installed",
        "bare_ok"])
@pytest.mark.asyncio
async def test_only_an_explicit_success_status_records_a_success(tmp_path, result, expected):
    """Closure MINOR: ``_attempt_outcome`` counted every status but ``failed`` as a
    success, so the cloud image runtime's ``unknown`` (a provider error, a response too
    large, a refusal after the request) read as a success. Now a success needs a status
    a handler uses for one; any other status is a failure (the conservative direction)."""
    queue = _queue(tmp_path / "autonomy.db")

    async def executor(_task):
        return dict(result)

    await _run_real(queue, executor, "plugin.egress", {"plugin": "cloud-image"})
    assert _counts(queue, "plugin.egress") == expected
    queue.close()


# ── round 5, item 9: the generic LLM fallback never exercises a capability ────


@pytest.mark.parametrize("fallback", ["returns", "raises"])
@pytest.mark.asyncio
async def test_a_manifest_kind_run_by_the_llm_fallback_records_nothing(tmp_path, fallback):
    """Closure MINOR: ``oracle_bridge`` enqueues ``repo.sync`` as an ask task; no handler
    is registered for it, so once approved the coordinator's executor runs its title
    through the generic ``_llm`` fallback. The repo.sync capability was not exercised:
    nothing is recorded for it, whether the fallback returns or raises. A manifest kind
    with a registered handler on the same executor still records its outcome."""
    from agents.core.autonomy.worker import MAX_ATTEMPTS
    from tests.test_web_tools_wiring import _coordinator

    coordinator = _coordinator({})
    prompts = []

    async def process(prompt, **_kwargs):
        prompts.append(prompt)
        if fallback == "raises":
            raise RuntimeError("model backend unavailable")
        return "a review of the sync"

    coordinator._orch.process = process
    executor = coordinator.build_executor()

    async def graph_write(_task):
        return {"status": "ok", "kind": "kg.write"}

    executor.register("kg.write", graph_write)
    queue = _queue(tmp_path / "autonomy.db")
    task = await _run_real(queue, executor.execute, "repo.sync",
                           {"repo": "https://github.com/example/repo"}, ticks=MAX_ATTEMPTS)
    assert prompts and prompts[0] == "real handler"      # the title, through the LLM
    assert task.status == (TaskStatus.DONE.value if fallback == "returns"
                           else TaskStatus.FAILED.value)
    assert _counts(queue, "repo.sync") == (0, 0)
    await _run_real(queue, executor.execute, "kg.write", {})
    assert _counts(queue, "kg.write") == (1, 0)
    queue.close()
