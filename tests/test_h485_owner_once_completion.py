"""A synthetic DONE row is not evidence of owner-once execution."""

from __future__ import annotations

import hashlib
import hmac
import json

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
    tool_approval_scope,
)
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.owner_once import OwnerOnceOwner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.commands import Principal


def test_owner_once_completion_requires_separate_worker_proof(tmp_path):
    signer = DetachedHMACSigner(
        lambda data: hmac.new(b"owner-once-completion", data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(tmp_path / "completion.db"), mediation_signer=signer).initialize()
    try:
        task_id = queue.enqueue(
            "jarvis", "toolrpc.terminal_run", "A terminal command",
            payload={"tool": "terminal_run", "target": "terminal_run",
                     "args": {"target": "dev", "command": "printf hello"}},
            risk_tier=3, autonomy_level="ask",
        )
        queue.transition(task_id, TaskStatus.APPROVED, decided_by="owner_once", decision="owner-once")
        # A direct database writer can forge status/result columns but not the
        # worker's signed completion proof.
        queue._conn.execute(
            "UPDATE tasks SET status='done', result=? WHERE id=?",
            ('{"status":"ok","result":{"ok":true}}', task_id),
        )
        queue._conn.commit()
        assert queue.verify_owner_once_terminal_result(task_id) is False
    finally:
        queue.close()


def test_dispatched_success_has_distinct_signed_done_proof_after_turn_closes(tmp_path):
    signer = DetachedHMACSigner(
        lambda data: hmac.new(b"owner-once-completion", data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(tmp_path / "real-completion.db"), mediation_signer=signer).initialize()
    turn = open_approval_turn(
        session_id="owner", session_instance="birth",
        principal=Principal(channel="telegram", sender="99", chat="99", admin=True),
        session_is_live=lambda _session, _instance: True,
    )
    token = bind_approval_turn(turn)
    try:
        with tool_approval_scope("terminal_run"):
            task_id = queue.enqueue(
                "jarvis", "toolrpc.terminal_run", "A terminal command",
                payload={"tool": "terminal_run", "target": "terminal_run",
                         "args": {"target": "dev", "command": "printf hello"}},
                risk_tier=3, autonomy_level="ask",
            )
            queue.transition(task_id, TaskStatus.BLOCKED,
                             decided_by="policy", decision="needs-approval")
        digest = queue.approval_snapshot_digest(queue.get(task_id))
        denied = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1.0)
        assert queue.store_smart_terminal_judgement(
            task_id, digest, denied, check=lambda: True,
        )[0]
        offer = queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True)
        generation = "22222222222242228222222222222222"
        assert queue.mark_owner_once_delivered(
            offer, chat_id=99, user_id=99, message_id=17,
            generation=generation, live_check=lambda: True,
        )
        owner = OwnerOnceOwner(turn.principal_key, "telegram", 99, 99, 17, generation)
        claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                        authenticated_owner=owner, live_check=lambda: True)
        running = queue.claim_owner_once(task_id, claim, execution_id="owner-run",
                                         live_check=lambda: True)
        assert running is not None
        queue.increment_attempts(task_id)
        running = queue.get(task_id)
        assert queue.owner_once_dispatch_current(task_id, claim, live_check=lambda: True)
        result = queue.issue_owner_once_terminal_result(
            running, {"status": "ok", "result": {"ok": True, "stdout": "hello"}},
        )
        assert "_owner_once_execution" in result and "_smart_execution" not in result
        queue.transition(task_id, TaskStatus.DONE, result=result)
        close_approval_turn(turn, token)
        assert queue.verify_owner_once_terminal_result(task_id)
        assert not queue.verify_owner_once_terminal_approval(task_id, check=lambda _r: True)
        forged = json.loads(json.dumps(result))
        forged["result"]["stdout"] = "different"
        queue._conn.execute("UPDATE tasks SET result=? WHERE id=?", (json.dumps(forged), task_id))
        queue._conn.commit()
        assert not queue.verify_owner_once_terminal_result(task_id)
    finally:
        if turn.live():
            close_approval_turn(turn, token)
        queue.close()
