"""Hermes approval decisions remain bound to canonical queued actions."""

import hashlib
import hmac
from types import SimpleNamespace

import pytest

from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.hermes_runtime.approvals import HermesApprovals, public_task
from agents.core.hermes_runtime.policy import HermesGate, RuntimeDenied
from agents.core.hermes_runtime.service import HermesRuntimeService, RuntimeUnavailable
from agents.core.hermes_runtime.worker import native_rpc_completion
from agents.core.kernel.binding import make_action_kernel
from agents.core.security.capability import CapabilityBroker, KillSwitch


def test_public_approval_projection_shows_frozen_action_without_authority():
    class Task:
        id = 14
        kind = "hermes.runtime"
        status = "blocked"
        risk_tier = 3
        created_at = "2026-10-06T00:00:00+00:00"
        approval_deadline_at = "2026-10-06T00:05:00+00:00"
        result = None
        payload = {"operation": "rpc", "target": "shell.exec",
                   "arguments": {"command": "true"}, "generation": "g1",
                   "private_nonce": "must-not-leak"}

    assert public_task(Task()) == {
        "task_id": 14, "status": "blocked", "operation": "rpc", "target": "shell.exec",
        "arguments": {"command": "true"}, "risk_tier": 3,
        "created_at": "2026-10-06T00:00:00+00:00",
        "expires_at": "2026-10-06T00:05:00+00:00", "disposition": "queued",
    }


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    signer = DetachedHMACSigner(lambda data: hmac.new(b"hermes-approval-fixture", data, hashlib.sha256).hexdigest())
    head = [None]

    def cas(previous, replacement):
        if previous != head[0]:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(str(tmp_path / "queue.db"), mediation_mode="enforce",
                      mediation_signer=signer,
                      mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
                      mediation_scope="global").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="auto"))
    orch = SimpleNamespace(autonomy=worker, capabilities=CapabilityBroker(),
                           kill_switch=KillSwitch(tmp_path / "kill-switch.json"),
                           intent_log=None)
    worker.bind_mediation(make_action_kernel(orch), signer)
    effects = []

    class Client:
        async def rpc(self, method, args, *, request_id):
            answer = runtime.authorize({"generation": "g1", "nonce": "new-nonce",
                "kind": "rpc", "target": method, "args": args, "request_id": request_id})
            if answer["verdict"] == "grant":
                effects.append((method, args))
                runtime.complete({"generation": "g1", "task_id": answer["task_id"],
                                  "completion_id": answer["completion_id"], "ok": True,
                                  "outcome": {"state": "result", "value": {"ok": True}}})
            return {"ok": True}

    runtime = HermesApprovals(worker=worker, queue=queue, gate=HermesGate(orchestrator=lambda: orch),
                              generation="g1", client=Client())
    yield runtime, queue, effects
    queue.close()


def frame(args=None):
    return {"generation": "g1", "nonce": "original-nonce", "kind": "rpc",
            "target": "shell.exec", "args": args or {"command": "true"},
            "request_id": "original-rpc"}


@pytest.mark.asyncio
async def test_canonical_approval_dispatches_exact_rpc_once(approvals):
    runtime, queue, effects = approvals
    queued = await runtime.submit(frame())
    task_id = queued["task_id"]
    task = queue.get(task_id)
    assert task.status == "blocked" and task.mediation_receipt
    assert task.payload["arguments"] == {"command": "true"}
    assert runtime.list()["tasks"][0]["task_id"] == task_id
    assert (await runtime.decide(task_id, True))["status"] == "approved"
    await next(iter(runtime._jobs))
    assert effects == [("shell.exec", {"command": "true"})], (queue.get(task_id).status, queue.verified_mediation_stats())
    assert runtime.list()["tasks"][0]["result"] == {
        "disposition": "completed", "value": {"ok": True}}
    with pytest.raises(RuntimeDenied):
        await runtime.decide(task_id, True)


@pytest.mark.asyncio
async def test_denied_rpc_never_dispatches(approvals):
    runtime, queue, effects = approvals
    task_id = (await runtime.submit(frame()))["task_id"]
    assert (await runtime.decide(task_id, False))["status"] == "rejected"
    assert effects == []


@pytest.mark.asyncio
async def test_stopped_generation_refuses_pending_approval(approvals):
    runtime, queue, effects = approvals
    task_id = (await runtime.submit(frame()))["task_id"]
    runtime.revoke()
    with pytest.raises(RuntimeDenied, match="generation revoked"):
        await runtime.decide(task_id, True)
    assert effects == []
    assert queue.get(task_id).status == "rejected"
    assert runtime.list()["tasks"][0]["disposition"] == "generation_revoked"


@pytest.mark.asyncio
async def test_changed_arguments_cannot_consume_approved_task(approvals):
    runtime, queue, effects = approvals
    task_id = (await runtime.submit(frame()))["task_id"]
    await runtime.worker.apply_decision(task_id, "accept", decided_by="user")
    runtime._permits["approved-rid"] = task_id
    changed = frame({"command": "printf substituted"})
    changed.update(nonce="another-nonce", request_id="approved-rid")
    with pytest.raises(RuntimeDenied, match="changed"):
        runtime.authorize(changed)
    assert queue.get(task_id).status == "approved"
    assert effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("approved_value,substituted_value", [
    (False, 0), (True, 1), (1, 1.0), (False, float("nan")),
])
async def test_json_scalar_type_substitution_cannot_consume_approval(
    approvals, approved_value, substituted_value,
):
    runtime, queue, effects = approvals
    original = frame({"command": "true", "nested": {"choice": [approved_value]}})
    task_id = (await runtime.submit(original))["task_id"]
    await runtime.worker.apply_decision(task_id, "accept", decided_by="user")
    runtime._permits["approved-rid"] = task_id
    changed = frame({"command": "true", "nested": {"choice": [substituted_value]}})
    changed.update(nonce="another-nonce", request_id="approved-rid")
    with pytest.raises(RuntimeDenied, match="changed"):
        runtime.authorize(changed)
    assert queue.get(task_id).status == "approved"
    assert effects == []


@pytest.mark.asyncio
async def test_kill_switch_after_approval_refuses_native_dispatch(approvals):
    runtime, queue, effects = approvals
    task_id = (await runtime.submit(frame()))["task_id"]
    await runtime.worker.apply_decision(task_id, "accept", decided_by="user")
    runtime.gate._orchestrator().kill_switch.engage("global", "fixture halt")
    runtime._permits["approved-rid"] = task_id
    retry = {**frame(), "request_id": "approved-rid", "nonce": "another-nonce"}
    with pytest.raises(RuntimeDenied):
        runtime.authorize(retry)
    assert queue.get(task_id).status == "failed"
    assert effects == []


@pytest.mark.asyncio
async def test_approval_deadline_refuses_late_owner_decision(approvals):
    runtime, queue, effects = approvals
    task_id = (await runtime.submit(frame()))["task_id"]
    queue._conn.execute("UPDATE tasks SET approval_deadline_at=? WHERE id=?",
                        ("2020-01-01T00:00:00+00:00", task_id))
    queue._conn.commit()
    with pytest.raises(RuntimeDenied, match="expired"):
        await runtime.decide(task_id, True)
    assert effects == []


@pytest.mark.asyncio
async def test_lost_tool_continuation_cannot_leave_an_actionable_approval(approvals):
    runtime, queue, effects = approvals
    tool = {"generation": "g1", "nonce": "tool-nonce", "kind": "tool",
            "target": "fixture_write", "args": {"content": "authorized"}}
    task_id = (await runtime.submit(tool))["task_id"]
    runtime._tool_last_poll[task_id] -= 11
    with pytest.raises(RuntimeDenied):
        await runtime.decide(task_id, True)
    assert queue.get(task_id).status == "rejected"
    assert runtime.list()["tasks"][0]["disposition"] == "continuation_lost"
    assert effects == []


def test_native_jsonrpc_error_is_not_a_successful_completion():
    ok, outcome = native_rpc_completion({"jsonrpc": "2.0", "id": "r1",
        "error": {"code": 4005, "message": "native refusal"}}, "r1")
    assert ok is False
    assert outcome == {"state": "error", "value": {"code": 4005, "message": "native refusal"}}
    assert native_rpc_completion({"jsonrpc": "2.0", "id": "r1", "result": {"x": 1}}, "r1") == (
        True, {"state": "result", "value": {"x": 1}})


@pytest.mark.asyncio
async def test_native_error_persists_failed_task_and_bounded_error(approvals):
    runtime, queue, effects = approvals
    class ErrorClient:
        async def rpc(self, method, args, *, request_id):
            grant = runtime.authorize({"generation": "g1", "nonce": "retry", "kind": "rpc",
                                       "target": method, "args": args, "request_id": request_id})
            runtime.complete({"generation": "g1", "task_id": grant["task_id"],
                              "completion_id": grant["completion_id"], "ok": False,
                              "outcome": {"state": "error", "value": {"code": 4005,
                                          "message": "native refusal"}}})
            raise RuntimeDenied("native refusal")
    runtime.client = ErrorClient()
    task_id = (await runtime.submit(frame()))["task_id"]
    await runtime.decide(task_id, True)
    await next(iter(runtime._jobs))
    assert queue.get(task_id).status == "failed"
    assert runtime.list()["tasks"][0]["result"] == {
        "disposition": "native_error", "value": {"code": 4005, "message": "native refusal"}}
    assert effects == []


@pytest.mark.asyncio
async def test_intake_timeout_after_commit_rejects_unreported_task(approvals, monkeypatch):
    runtime, queue, effects = approvals
    request = frame()
    task_id = (await runtime.submit(request))["task_id"]
    service = HermesRuntimeService(gate=runtime.gate)
    service._approvals = runtime
    service._loop = __import__("asyncio").get_running_loop()
    service._process = SimpleNamespace(status=lambda: {"ready": True, "generation": "g1", "pid": 1})
    service._client = SimpleNamespace(connected=True)
    service._bridge = SimpleNamespace(generation="g1")
    monkeypatch.setenv("JARVIS_HERMES_ENABLED", "1")

    class TimedOut:
        def result(self, timeout):
            raise TimeoutError

        def cancel(self):
            return True

    def timed_out(coroutine, loop):
        coroutine.close()
        return TimedOut()

    monkeypatch.setattr("agents.core.hermes_runtime.service.asyncio.run_coroutine_threadsafe", timed_out)
    with pytest.raises(RuntimeDenied, match="intake unavailable"):
        service._bridge_authorize(request)
    assert queue.get(task_id).status == "rejected"
    assert effects == []


@pytest.mark.asyncio
async def test_dead_worker_revokes_cards_before_approval(approvals, monkeypatch):
    runtime, queue, effects = approvals
    task_id = (await runtime.submit(frame()))["task_id"]
    service = HermesRuntimeService(gate=runtime.gate)
    service._approvals = runtime
    service._process = SimpleNamespace(status=lambda: {"ready": False, "generation": None, "pid": None})
    service._client = SimpleNamespace(connected=False)
    service._bridge = SimpleNamespace(generation="g1")
    monkeypatch.setenv("JARVIS_HERMES_ENABLED", "1")
    with pytest.raises(RuntimeUnavailable):
        await service.approval_decide(task_id, True)
    assert queue.get(task_id).status == "rejected"
    assert service._bridge.generation is None
    with pytest.raises(RuntimeDenied, match="generation revoked"):
        service._bridge_authorize(frame())
    assert effects == []
