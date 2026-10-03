"""Only a worker-recorded smart terminal completion carries a signed result proof."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.autonomy.worker import AutonomyWorker


@pytest.fixture
def queue(tmp_path):
    key = b"h485-smart-completion"
    signer = DetachedHMACSigner(lambda raw: hmac.new(key, raw, hashlib.sha256).hexdigest())
    value = TaskQueue(str(tmp_path / "smart-completion.db"), mediation_signer=signer).initialize()
    yield value
    value.close()


def approved_terminal(queue, command="printf hello"):
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Run command",
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": command}},
        risk_tier=3, autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED,
                     decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    result = SmartApprovalResult(
        "approve", "a" * 64, "b" * 64, {"model": "fixture"}, 1_000_000.0,
    )
    assert queue.store_smart_terminal_judgement(
        task_id, digest, result, check=lambda: True,
    )[0]["decision"] == "approve"
    return task_id


@pytest.mark.asyncio
@pytest.mark.parametrize("named", [False, True])
async def test_actual_worker_completion_gets_proof_in_batch_and_named_tick(queue, named):
    seen = []

    async def executor(task):
        seen.append(task.id)
        return {"status": "ok", "result": {"ok": True, "stdout": "hello"}}

    worker = AutonomyWorker(queue, executor=executor)
    task_id = approved_terminal(queue)
    summary = await (worker.tick(task_id=task_id) if named else worker.tick())
    assert summary["done"] == 1 and seen == [task_id]
    task = queue.get(task_id)
    assert task.status == "done" and task.result["result"]["stdout"] == "hello"
    assert task.result["_smart_execution"]["purpose"] == "nerva.smart-terminal-execution"
    assert queue.verify_smart_terminal_result(task_id) is True


def test_synthetic_done_with_success_shape_has_no_worker_completion_proof(queue):
    task_id = approved_terminal(queue)
    queue.transition(task_id, TaskStatus.RUNNING, expected_status=TaskStatus.APPROVED)
    queue.transition(task_id, TaskStatus.DONE,
                     result={"status": "ok", "result": {"ok": True, "stdout": "fake"}})
    assert queue.verify_smart_terminal_result(task_id) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["result", "proof", "completion_signature", "task", "birth", "approval_receipt"])
async def test_tampered_persisted_bytes_or_receipt_fail_completion_proof(queue, mutation):
    async def executor(_task):
        return {"status": "ok", "result": {"ok": True, "stdout": "hello"}}

    task_id = approved_terminal(queue)
    assert (await AutonomyWorker(queue, executor=executor).tick(task_id=task_id))["done"] == 1
    assert queue.verify_smart_terminal_result(task_id)
    if mutation in {"result", "proof", "completion_signature"}:
        value = queue.get(task_id).result
        if mutation == "result":
            value["result"]["stdout"] = "changed"
        elif mutation == 'proof':
            value["_smart_execution"]["result_sha256"] = "0" * 64
        else:
            value['_smart_execution']['signature'] = '0' * 64
        queue._conn.execute("UPDATE tasks SET result=? WHERE id=?", (json.dumps(value), task_id))
    elif mutation == "task":
        value = queue.get(task_id).payload
        value["args"]["command"] = "printf changed"
        queue._conn.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(value), task_id))
    elif mutation == "birth":
        queue._conn.execute("UPDATE tasks SET created_at='replacement' WHERE id=?", (task_id,))
    else:
        queue._conn.execute("UPDATE task_smart_approvals SET signature=? WHERE task_id=?",
                            ("0" * 64, task_id))
    queue._conn.commit()
    assert queue.verify_smart_terminal_result(task_id) is False


@pytest.mark.asyncio
async def test_missing_signer_keeps_operation_result_but_no_success_proof(queue):
    async def executor(_task):
        return {"status": "ok", "result": {"ok": True, "stdout": "hello"}}

    task_id = approved_terminal(queue)
    queue._mediation_signer = DetachedHMACSigner(None)
    assert (await AutonomyWorker(queue, executor=executor).tick(task_id=task_id))["done"] == 1
    task = queue.get(task_id)
    assert task.result["result"]["stdout"] == "hello"
    assert "_smart_execution" not in task.result
    assert queue.verify_smart_terminal_result(task_id) is False


@pytest.mark.asyncio
async def test_refused_result_and_executor_supplied_fake_proof_never_verify(queue):
    async def executor(_task):
        return {"status": "refused", "reason": "kernel_denied",
                "_smart_execution": {"signature": "forged"}}

    task_id = approved_terminal(queue)
    assert (await AutonomyWorker(queue, executor=executor).tick(task_id=task_id))["done"] == 1
    assert queue.verify_smart_terminal_result(task_id) is False
    assert "_smart_execution" not in queue.get(task_id).result


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [
    {"status": "failed", "result": {"ok": True}},
    {"status": "ok", "result": {"ok": False}},
    {"status": "ok"},
])
async def test_ambiguous_or_incomplete_success_shape_never_receives_proof(queue, operation):
    async def executor(_task):
        return {**operation, "_smart_execution": {"signature": "forged"}}

    task_id = approved_terminal(queue)
    assert (await AutonomyWorker(queue, executor=executor).tick(task_id=task_id))["done"] == 1
    persisted = queue.get(task_id)
    assert persisted.result["status"] == operation["status"]
    assert "_smart_execution" not in persisted.result
    assert queue.verify_smart_terminal_result(task_id) is False
