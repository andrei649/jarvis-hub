"""H067 permanent session consent through the physical governed task path."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from agents.core import kernel
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.channels.session_command_consent import (
    SessionCommandConsent,
    session_command_digest,
)
from agents.core.kernel import Verdict
from agents.core.permission_ledger import PermissionLedger, PermissionRequestError
from agents.core.security.capability import KillSwitch
from tests.test_web_tools_wiring import _coordinator

OWNER = ("telegram", "tg:123:topic:7", "42")


class _IntentLog:
    def __init__(self, key: bytes):
        self.key = key

    def sign_detached(self, body: bytes) -> str:
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()

    def record(self, *_args, **_kwargs) -> None:
        pass


def _request_with_matching_title(ledger, worker):
    """Isolate downstream authorization while the default-title path is red."""
    return ledger.request(
        "session_command", session_command_digest(OWNER, "/new"), "always", "owner-42",
        worker.govern_enqueue, title="grant session command",
    )


@pytest.fixture
def governed(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    intent = _IntentLog(b"h067 local synthetic signer")
    signer = DetachedHMACSigner(intent.sign_detached)
    head = [None]

    def compare_and_set(before, after):
        if head[0] != before:
            return False
        head[0] = after
        return True

    queue = TaskQueue(
        str(tmp_path / "tasks.db"),
        mediation_mode="enforce",
        mediation_signer=signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], compare_and_set),
        mediation_scope="global",
    ).initialize()
    kill = KillSwitch(tmp_path / "kill.json")
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="auto"),
                            kill_switch=kill, mediation_signer=signer)
    coordinator = _coordinator({})
    orch = coordinator._orch
    orch.autonomy = worker
    orch.autonomy_queue = queue
    orch.kill_switch = kill
    orch.intent_log = intent
    kernel_calls = []
    physical_authorize = kernel.authorize

    def observed_authorize(action, *args, **kwargs):
        verdict = physical_authorize(action, *args, **kwargs)
        kernel_calls.append((action, verdict))
        return verdict

    monkeypatch.setattr(kernel, "authorize", observed_authorize)
    monkeypatch.setattr("agents.core.permission_ledger.data_path", lambda _name: tmp_path / "permissions.db")
    executor = coordinator.build_executor()
    worker.executor = executor.execute
    ledger = orch.permission_ledger
    assert isinstance(ledger, PermissionLedger)
    assert executor.resolve("permission.grant") == ledger.apply_grant
    consent = SessionCommandConsent(ledger, worker.govern_enqueue)
    try:
        yield consent, ledger, queue, worker, executor, kill, kernel_calls
    finally:
        queue.close()
        ledger.close()


@pytest.mark.asyncio
async def test_signed_owner_approval_executes_coordinator_grant_and_survives_restart(governed):
    consent, ledger, queue, worker, executor, _kill, kernel_calls = governed
    assert queue.classify_mediation("permission.grant") is True
    assert consent.check(OWNER, "/new") == "ask"
    task_id = consent.request_always(OWNER, "/new", "owner-42")
    task = queue.get(task_id)
    assert task.kind == "permission.grant" and task.status == "blocked"
    assert task.mediation_receipt is not None
    assert len(kernel_calls) == 1
    assert kernel_calls[0][0].kind == "permission.grant"
    assert kernel_calls[0][1].verdict in {Verdict.GRANT, Verdict.QUEUE}
    assert ledger.list_grants() == []
    assert (await worker.tick(task_id=task_id))["done"] == 0
    approved = await worker.apply_decision(task_id, "accept", decided_by="owner-42")
    assert approved.human_decision is not None and approved.status == "approved"
    assert consent.check(OWNER, "/new") == "ask"
    assert (await worker.tick(task_id=task_id))["done"] == 1
    assert queue.get(task_id).result["status"] == "ok"
    assert consent.check(OWNER, "/reset") == "allow"
    assert consent.check(OWNER, "/undo") == "ask"
    assert consent.check(("telegram", "tg:123:topic:8", "42"), "/reset") == "ask"
    assert consent.check(("telegram", "tg:123:topic:7", "43"), "/reset") == "ask"
    assert executor.handles("permission.grant")
    restarted = PermissionLedger(ledger.path, enabled=False)
    try:
        assert restarted.check_required("session_command", task.payload["key"]) == "allow"
        [grant] = restarted.list_grants()
        assert restarted.revoke(grant.id).status == "revoked"
        assert restarted.check_required("session_command", task.payload["key"]) == "ask"
    finally:
        restarted.close()


def test_kill_switch_refuses_request_before_a_task_or_grant_exists(governed):
    consent, ledger, queue, _worker, _executor, kill, _calls = governed
    kill.engage(reason="synthetic emergency stop")
    with pytest.raises(PermissionRequestError, match="kernel_denied"):
        consent.request_always(OWNER, "/new", "owner-42")
    assert queue.list() == [] and ledger.list_grants() == []


def test_never_denial_refuses_request_without_queue_intake(governed):
    consent, ledger, queue, _worker, _executor, _kill, _calls = governed
    ledger.deny("session_command", session_command_digest(OWNER, "/new"))
    with pytest.raises(PermissionRequestError, match="never_entry"):
        consent.request_always(OWNER, "/new", "owner-42")
    assert queue.list() == [] and ledger.check_required(
        "session_command", session_command_digest(OWNER, "/new")
    ) == "deny"


def test_policy_only_without_physical_kernel_cannot_mint(governed, monkeypatch):
    consent, ledger, queue, _worker, _executor, _kill, _calls = governed
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    with pytest.raises(TaskQueueError, match="mediation authority is unavailable"):
        consent.request_always(OWNER, "/new", "owner-42")
    assert queue.list() == [] and ledger.list_grants() == []


def test_missing_detached_signature_cannot_enqueue_a_grant(governed):
    consent, ledger, queue, worker, _executor, _kill, _calls = governed
    worker._mediation_signer = DetachedHMACSigner(None)
    with pytest.raises(TaskQueueError, match="mediation receipt is unavailable"):
        consent.request_always(OWNER, "/new", "owner-42")
    assert queue.list() == [] and ledger.list_grants() == []


@pytest.mark.asyncio
async def test_explicit_title_proves_signed_downstream_grant_path(governed):
    consent, ledger, queue, worker, _executor, _kill, _calls = governed
    task_id = _request_with_matching_title(ledger, worker)
    task = queue.get(task_id)
    assert task.mediation_receipt is not None
    await worker.apply_decision(task_id, "accept", decided_by="owner-42")
    assert (await worker.tick(task_id=task_id))["done"] == 1
    assert consent.check(OWNER, "/new") == "allow"


@pytest.mark.asyncio
async def test_fabricated_owner_attribution_without_human_decision_cannot_mint(governed):
    consent, ledger, queue, worker, _executor, _kill, _calls = governed
    task_id = _request_with_matching_title(ledger, worker)
    queued = queue.get(task_id)
    assert queued.human_decision is None
    queue.transition(task_id, TaskStatus.APPROVED, decided_by="owner-42", decision="accept")
    await worker.tick(task_id=task_id)
    assert ledger.list_grants() == []


@pytest.mark.asyncio
async def test_changed_approved_payload_cannot_mint_original_or_alternate_selector(governed):
    consent, ledger, queue, worker, _executor, _kill, _calls = governed
    task_id = _request_with_matching_title(ledger, worker)
    await worker.apply_decision(task_id, "accept", decided_by="owner-42")
    task = queue.get(task_id)
    other_key = session_command_digest(OWNER, "/undo")
    queue.update_payload(task_id, {**task.payload, "key": other_key})
    await worker.tick(task_id=task_id)
    assert ledger.list_grants() == []
    assert consent.check(OWNER, "/new") == "ask"
    assert consent.check(OWNER, "/undo") == "ask"
