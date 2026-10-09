"""Durable, machine-attributed smart decisions for exact terminal tasks."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from agents.core.autonomy.mediation import DetachedHMACSigner, issue_intake_evidence
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult


def _SmartResult(*, verdict: str = "approve") -> SmartApprovalResult:
    return SmartApprovalResult(
        verdict=verdict,
        policy_revision="a" * 64,
        judge_revision="b" * 64,
        judge={"model": "test-guardian"},
        at=1_000_000.0,
    )


def _signer() -> DetachedHMACSigner:
    key = b"h277-smart-terminal-queue-test-key"
    return DetachedHMACSigner(lambda payload: hmac.new(key, payload, hashlib.sha256).hexdigest())


def _queue(tmp_path, *, signer=True) -> TaskQueue:
    return TaskQueue(
        str(tmp_path / "tasks.db"),
        mediation_signer=_signer() if signer else None,
    ).initialize()


def _blocked_terminal(queue: TaskQueue, *, command="pwd", target="dev") -> tuple[int, str]:
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Run terminal command",
        payload={
            "tool": "terminal_run",
            "args": {"target": target, "command": command, "cwd": "/tmp", "timeout": 15},
            "target": "terminal_run",
        },
        risk_tier=2,
        autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert digest is not None
    return task_id, digest


def test_smart_approval_signs_exact_terminal_and_survives_running(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    annotation, group_id = queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    )

    task = queue.get(task_id)
    assert annotation == _SmartResult().annotation()
    assert group_id is None
    assert task.status == "approved"
    assert (task.decided_by, task.decision, task.human_decision) == (
        "smart_approval", "smart-approve", None,
    )
    assert queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)

    queue.transition(task_id, TaskStatus.RUNNING)
    assert queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_missing_signer_and_revoked_policy_never_promote(tmp_path):
    queue = _queue(tmp_path, signer=False)
    task_id, digest = _blocked_terminal(queue)
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()

    queue = _queue(tmp_path, signer=True)
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: False,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()


@pytest.mark.parametrize("verdict", ["deny", "escalate"])
def test_only_escalation_retains_generic_owner_override(verdict, tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    annotation, group_id = queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(verdict=verdict), check=lambda: True,
    )
    assert annotation["decision"] == verdict
    assert annotation["advisory"] is False
    assert group_id is None
    assert queue.get(task_id).status == "blocked"
    assert not queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)

    if verdict == 'deny':
        with pytest.raises(TaskQueueError):
            queue.transition(task_id, TaskStatus.APPROVED, decided_by='owner',
                             decision='accept', human_reason=None)
        assert queue.get(task_id).human_decision is None
        assert queue.get(task_id).status == 'blocked'
    else:
        queue.transition(task_id, TaskStatus.APPROVED, decided_by='owner',
                         decision='accept', human_reason=None)
        assert queue.get(task_id).human_decision['by'] == 'owner'
    assert not queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_signed_approval_is_bound_to_policy_and_exact_command(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(task_id, digest, _SmartResult(), check=lambda: True)
    assert not queue.verify_smart_terminal_approval(task_id, check=lambda receipt: False)

    with sqlite3.connect(queue.db_path) as db:
        task = queue.get(task_id)
        changed = dict(task.payload)
        changed["args"] = {**changed["args"], "command": "whoami"}
        db.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(changed), task_id))
    assert not queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_receipt_signature_and_authority_fields_cannot_be_forged(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(task_id, digest, _SmartResult(), check=lambda: True)
    with sqlite3.connect(queue.db_path) as db:
        db.execute("UPDATE task_smart_approvals SET signature=? WHERE task_id=?", ("0" * 64, task_id))
    assert not queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_stale_snapshot_and_duplicate_or_wrong_kind_cannot_approve(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    assert queue.store_smart_terminal_judgement(
        task_id, "0" * 64, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    )[0] is not None
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    ) == (None, None)

    other = queue.enqueue("jarvis", "toolrpc.file_write", "write", payload={"tool": "file_write"})
    queue.transition(other, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    other_digest = queue.approval_snapshot_digest(queue.get(other))
    assert queue.store_smart_terminal_judgement(
        other, other_digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    queue.close()


def test_receipt_from_another_task_cannot_authorize_replay(tmp_path):
    queue = _queue(tmp_path)
    first, first_digest = _blocked_terminal(queue)
    second, second_digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(first, first_digest, _SmartResult(), check=lambda: True)
    queue.store_smart_terminal_judgement(second, second_digest, _SmartResult(), check=lambda: True)

    with sqlite3.connect(queue.db_path) as db:
        receipt, signature = db.execute(
            "SELECT receipt, signature FROM task_smart_approvals WHERE task_id=?", (first,),
        ).fetchone()
        db.execute(
            "UPDATE task_smart_approvals SET receipt=?, signature=? WHERE task_id=?",
            (receipt, signature, second),
        )
    assert queue.verify_smart_terminal_approval(first, check=lambda receipt: True)
    assert not queue.verify_smart_terminal_approval(second, check=lambda receipt: True)
    queue.close()


@pytest.mark.parametrize("column,value", [
    ("decision", "accept"),
    ("decided_by", "owner"),
    ("mediation_execution_id", "forged-claim"),
])
def test_edited_authority_fields_invalidate_receipt(column, value, tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(task_id, digest, _SmartResult(), check=lambda: True)
    with sqlite3.connect(queue.db_path) as db:
        db.execute(f"UPDATE tasks SET {column}=? WHERE id=?", (value, task_id))
    assert not queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_expired_terminal_row_does_not_receive_machine_authority(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    with sqlite3.connect(queue.db_path) as db:
        db.execute(
            "UPDATE tasks SET approval_deadline_at=? WHERE id=?",
            ("2000-01-01T00:00:00+00:00", task_id),
        )
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    ) == (None, None)

    queue.close()


def test_taint_metadata_is_snapshot_bound_without_blanket_smart_denial(tmp_path):
    queue = _queue(tmp_path)
    task_id, stale_digest = _blocked_terminal(queue)
    with sqlite3.connect(queue.db_path) as db:
        task = queue.get(task_id)
        payload = {**task.payload, "tainted": True, "taint_source": "inbound"}
        db.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(payload), task_id))
    assert queue.store_smart_terminal_judgement(
        task_id, stale_digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    tainted_digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert queue.store_smart_terminal_judgement(
        task_id, tainted_digest, _SmartResult(), check=lambda: True,
    )[0] is not None
    assert queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_two_queue_connections_have_one_atomic_smart_promotion(tmp_path):
    first = _queue(tmp_path)
    second = _queue(tmp_path)
    task_id, digest = _blocked_terminal(first)
    barrier = threading.Barrier(2)
    outcomes = []

    def apply(queue):
        barrier.wait()
        outcomes.append(queue.store_smart_terminal_judgement(
            task_id, digest, _SmartResult(), check=lambda: True,
        ))

    threads = [threading.Thread(target=apply, args=(queue,)) for queue in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(annotation is not None for annotation, _ in outcomes) == 1
    assert first.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    first.close()
    second.close()


def test_enforced_mediation_without_a_valid_task_receipt_refuses_approval(tmp_path):
    initial = _queue(tmp_path)
    task_id, digest = _blocked_terminal(initial)
    initial.close()
    governed = TaskQueue(
        str(tmp_path / "tasks.db"), mediation_mode="enforce", mediation_signer=_signer(),
    ).initialize()
    assert governed.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert governed.get(task_id).status == "blocked"
    governed.close()


def test_lookalike_or_plain_risk_annotation_cannot_create_machine_authority(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    real = _SmartResult()
    lookalike = SimpleNamespace(
        verdict=real.verdict,
        policy_revision=real.policy_revision,
        judge_revision=real.judge_revision,
        judge=real.judge,
        at=real.at,
        annotation=real.annotation,
    )
    assert queue.store_smart_terminal_judgement(
        task_id, digest, lookalike, check=lambda: True,
    ) == (None, None)
    assert queue.store_smart_terminal_judgement(
        task_id, digest, {"risk": "safe", "decision": "approve"}, check=lambda: True,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()


def test_mutable_judge_identity_is_detached_before_commit_check(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    result = _SmartResult()

    def change_input_during_check():
        result.judge["model"] = "swapped-after-review"
        return True

    annotation, _ = queue.store_smart_terminal_judgement(
        task_id, digest, result, check=change_input_during_check,
    )
    assert annotation["judge"] == {"model": "test-guardian"}
    with sqlite3.connect(queue.db_path) as db:
        receipt = json.loads(db.execute(
            "SELECT receipt FROM task_smart_approvals WHERE task_id=?", (task_id,),
        ).fetchone()[0])
    assert receipt["judge"] == {"model": "test-guardian"}
    assert queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_terminal_command_with_nul_is_not_smart_approvable(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue, command="pwd\x00; rm -rf /tmp/example")
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()


def test_blocked_task_with_prior_owner_attribution_is_not_auto_promoted(tmp_path):
    queue = _queue(tmp_path)
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Run terminal command",
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": "pwd"}},
        risk_tier=2,
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="owner", decision="defer")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()


@pytest.mark.parametrize("verdict", ["deny", "escalate"])
def test_current_smart_hold_projects_through_approval_reader_until_edit(verdict, tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    result = _SmartResult(verdict=verdict)
    annotation, _ = queue.store_smart_terminal_judgement(
        task_id, digest, result, check=lambda: True,
    )
    assert queue.approval_judgement(task_id, digest) == annotation

    with sqlite3.connect(queue.db_path) as db:
        task = queue.get(task_id)
        payload = {**task.payload, "args": {**task.payload["args"], "command": "whoami"}}
        db.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(payload), task_id))
    edited_digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert edited_digest != digest
    assert queue.approval_judgement(task_id, digest) is None
    assert queue.approval_judgement(task_id, edited_digest) is None
    queue.close()


def test_valid_kernel_intake_evidence_is_preserved_and_checked(tmp_path):
    queue = _queue(tmp_path)
    task_id, _ = _blocked_terminal(queue)
    task = queue.get(task_id)
    evidence = issue_intake_evidence(
        _signer(), intake_id=str(uuid.uuid4()),
        agent=task.agent, kind=task.kind, title=task.title, origin=task.origin,
        payload=task.payload, verdict="queue", tier=2, task_tier=2,
        issued_at_ms=int(time.time() * 1000), task_id=task_id,
    )
    assert evidence is not None
    assert queue.attach_kernel_intake_evidence(task_id, evidence)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    )[0] is not None
    assert queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    assert queue.get(task_id).kernel_intake_evidence == evidence.to_dict()
    queue.close()


@pytest.mark.parametrize("first_verdict", ["deny", "escalate"])
def test_new_exact_snapshot_supersedes_only_unsigned_smart_hold(first_verdict, tmp_path):
    queue = _queue(tmp_path)
    task_id, first_digest = _blocked_terminal(queue)
    first, _ = queue.store_smart_terminal_judgement(
        task_id, first_digest, _SmartResult(verdict=first_verdict), check=lambda: True,
    )
    assert first["decision"] == first_verdict
    queue.update_payload(task_id, {
        "tool": "terminal_run", "target": "terminal_run",
        "args": {"target": "dev", "command": "whoami"},
    })
    next_digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert next_digest != first_digest
    assert queue.approval_judgement(task_id, first_digest) is None

    latest, group_id = queue.store_smart_terminal_judgement(
        task_id, next_digest, _SmartResult(), check=lambda: True,
    )
    assert latest["decision"] == "approve" and group_id is None
    assert queue.get(task_id).status == "approved"
    assert queue.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    queue.close()


def test_same_snapshot_never_replaces_unsigned_smart_hold(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(verdict="deny"), check=lambda: True,
    )
    assert queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()


@pytest.mark.parametrize("corruption", [
    {"annotation": "not-json"},
    {"annotation": '{"decision":"deny"}'},
    {"receipt": "{}"},
    {"signature": "0" * 64},
])
def test_malformed_or_partially_signed_prior_record_cannot_be_superseded(corruption, tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(verdict="deny"), check=lambda: True,
    )
    with sqlite3.connect(queue.db_path) as db:
        for column, value in corruption.items():
            db.execute(f"UPDATE task_smart_approvals SET {column}=? WHERE task_id=?", (value, task_id))
    queue.update_payload(task_id, {
        "tool": "terminal_run", "target": "terminal_run",
        "args": {"target": "dev", "command": "whoami"},
    })
    next_digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert queue.store_smart_terminal_judgement(
        task_id, next_digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()


def test_signed_approval_is_never_superseded_after_reblock(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(task_id, digest, _SmartResult(), check=lambda: True)
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    queue.update_payload(task_id, {
        "tool": "terminal_run", "target": "terminal_run",
        "args": {"target": "dev", "command": "whoami"},
    })
    next_digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert queue.store_smart_terminal_judgement(
        task_id, next_digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    assert queue.get(task_id).status == "blocked"
    queue.close()


def test_owner_edited_blocked_task_is_not_smart_rejudged(tmp_path):
    queue = _queue(tmp_path)
    task_id, digest = _blocked_terminal(queue)
    queue.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(verdict="escalate"), check=lambda: True,
    )
    edited, _ = queue.update_payload_policy_with_group(
        task_id,
        {"tool": "terminal_run", "target": "terminal_run",
         "args": {"target": "dev", "command": "whoami"}},
        risk_tier=2, autonomy_level="ask", decided_by="owner", human_reason=None,
    )
    assert edited.status == "blocked" and edited.human_decision["action"] == "edit"
    next_digest = queue.approval_snapshot_digest(edited)
    assert queue.store_smart_terminal_judgement(
        task_id, next_digest, _SmartResult(), check=lambda: True,
    ) == (None, None)
    queue.close()


def test_two_connections_can_supersede_one_stale_hold_only_once(tmp_path):
    first = _queue(tmp_path)
    second = _queue(tmp_path)
    task_id, digest = _blocked_terminal(first)
    first.store_smart_terminal_judgement(
        task_id, digest, _SmartResult(verdict="deny"), check=lambda: True,
    )
    first.update_payload(task_id, {
        "tool": "terminal_run", "target": "terminal_run",
        "args": {"target": "dev", "command": "whoami"},
    })
    next_digest = first.approval_snapshot_digest(first.get(task_id))
    barrier = threading.Barrier(2)
    outcomes = []

    def replace(queue):
        barrier.wait()
        outcomes.append(queue.store_smart_terminal_judgement(
            task_id, next_digest, _SmartResult(), check=lambda: True,
        ))

    threads = [threading.Thread(target=replace, args=(queue,)) for queue in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(annotation is not None for annotation, _ in outcomes) == 1
    assert first.verify_smart_terminal_approval(task_id, check=lambda receipt: True)
    first.close()
    second.close()
