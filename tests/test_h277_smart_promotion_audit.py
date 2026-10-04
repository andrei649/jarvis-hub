"""An automatic terminal promotion audits the judge that actually authorized it."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.autonomy.approval_judge import ApprovalJudge
from agents.core.autonomy.audit_sink import ActionAuditSink
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.autonomy.task_approval_judge import TaskApprovalJudge
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.egress import llm_async_client
from agents.core.security.anchor import IntentLog


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "smart-promotion-settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    for name in ("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER",
                 "JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL", "JARVIS_SMART_APPROVALS",
                 "JARVIS_SMART_APPROVAL_POLICY", "JARVIS_SMART_APPROVAL_DENY"):
        monkeypatch.delenv(name, raising=False)


async def _drain(adapter):
    await asyncio.sleep(0)
    while adapter._judge_tasks:
        await asyncio.gather(*tuple(adapter._judge_tasks))
        await asyncio.sleep(0)


def _backend(requests):
    async def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "APPROVE"}, "finish_reason": "stop"}]})

    backend = object.__new__(LMStudioBackend)
    backend.base_url = "http://localhost:1234"
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(respond),
    )
    return backend


@pytest.mark.asyncio
@pytest.mark.parametrize("configured,actual_model", [
    ("fixture-judge", "fixture-judge"),
    ("active", "loaded-guardian-v2"),
])
async def test_smart_promotion_audit_names_committed_actual_judge(
    tmp_path, configured, actual_model,
):
    """Removing the judge from autonomy.smart_approve must fail this real audit check."""
    signer = DetachedHMACSigner(
        lambda raw: hmac.new(b"smart-promotion-fixture", raw, hashlib.sha256).hexdigest(),
    )
    queue = TaskQueue(str(tmp_path / "queue.db"), mediation_signer=signer).initialize()
    intent = IntentLog(tmp_path / "intent.json", secret_key="smart-promotion-audit-fixture")
    worker = AutonomyWorker(queue, audit=ActionAuditSink(intent))
    requests = []
    backend = _backend(requests)
    router = SimpleNamespace(local_backend=backend, local_backend_name="lm-studio",
                             active_model=actual_model)
    env = {"JARVIS_ROLE_APPROVAL_JUDGE_MODEL": configured,
           "JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER": "lm-studio",
           "JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL": backend.base_url,
           "JARVIS_SMART_APPROVALS": "1"}
    judge = ApprovalJudge(
        router=router, env=env, settings=lambda category, key, default=None: default,
        backend_factory=(None if configured == "active" else lambda status: backend),
    )
    worker.attach_approval_judge(judge, loop=asyncio.get_running_loop(), audit=intent)
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Review command",
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": "printf hello"}},
        risk_tier=3, autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    try:
        if configured == "active":
            # The loaded model may change after the durable CAS; the audit must
            # name the committed model, not refresh this mutable router.
            adapter = worker.approval_judge
            record = adapter._record_judgement

            def record_after_model_change(snapshot, annotation):
                router.active_model = "later-loaded-model"
                record(snapshot, annotation)

            adapter._record_judgement = record_after_model_change
        worker.approval_judge.schedule(task_id)
        await _drain(worker.approval_judge)
        task = queue.get(task_id)
        assert task.status == "approved" and task.decision == "smart-approve"
        assert len(requests) == 1
        assert json.loads(requests[0].content)["model"] == actual_model

        committed = []
        assert queue.verify_smart_terminal_approval(
            task_id, check=lambda receipt: committed.append(receipt) or True,
        )
        assert committed[0]["judge"] == {
            "provider": "lm-studio", "model": actual_model, "local": True,
        }
        if configured == "active":
            assert judge.status().model == "later-loaded-model"
        events = [row for row in intent.list(limit=100)
                  if row["action"] == "autonomy.smart_approve"]
        assert len(events) == 1
        assert events[0]["metadata"]["judge"] == committed[0]["judge"]
        assert events[0]["metadata"]["task_id"] == task_id
        assert intent.verify()["ok"] is True
    finally:
        await backend.client.aclose()
        queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("alter", ["signature", "observation"])
async def test_unmatched_smart_receipt_never_invents_an_audit_model(tmp_path, alter):
    """Receipt loss or changed observation leaves the old generic audit truthful."""
    signer = DetachedHMACSigner(
        lambda raw: hmac.new(b"smart-promotion-fixture", raw, hashlib.sha256).hexdigest(),
    )
    queue = TaskQueue(str(tmp_path / "queue.db"), mediation_signer=signer).initialize()
    intent = IntentLog(tmp_path / "intent.json", secret_key="smart-promotion-audit-fixture")
    worker = AutonomyWorker(queue, audit=ActionAuditSink(intent))
    adapter = TaskApprovalJudge(queue, worker=worker)
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Review command",
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": "printf hello"}},
        risk_tier=3, autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    snapshot = adapter._snapshot(queue.get(task_id))
    result = SmartApprovalResult(
        verdict="approve", policy_revision="a" * 64, judge_revision="b" * 64,
        judge={"provider": "lm-studio", "model": "committed-model", "local": True}, at=1_000_000.0,
    )
    stored, group_id = queue.store_smart_terminal_judgement(
        task_id, snapshot["snapshot_sha256"], result, check=lambda: True,
    )
    assert stored is not None and queue.get(task_id).decision == "smart-approve"
    adapter._smart_promotions[snapshot["id"]] = group_id
    if alter == "signature":
        queue._conn.execute(
            "UPDATE task_smart_approvals SET signature=? WHERE task_id=?", ("0" * 64, task_id),
        )
        queue._conn.commit()
    else:
        stored = {**stored, "judge": {"provider": "lm-studio", "model": "invented", "local": True}}
    try:
        await adapter._after_judgement(snapshot, stored)
        rows = [row for row in intent.list(limit=100)
                if row["action"] == "autonomy.smart_approve"]
        assert len(rows) == 1
        assert rows[0]["metadata"] == {
            "task_id": task_id, "agent": "jarvis", "kind": "toolrpc.terminal_run",
            "detail": "one operation approved by the configured guardian",
        }
        assert intent.verify()["ok"] is True
    finally:
        queue.close()
