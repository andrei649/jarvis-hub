"""Same-invocation feedback is a fresh authenticated observation, never authority."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
    tool_approval_scope,
)
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.commands import Principal


@pytest.fixture
def queue(tmp_path):
    key = b"h485-current-turn"
    signer = DetachedHMACSigner(lambda raw: hmac.new(key, raw, hashlib.sha256).hexdigest())
    value = TaskQueue(str(tmp_path / "current-turn.db"), mediation_signer=signer).initialize()
    yield value
    value.close()


def turn(*, session="s", instance="i", principal=None, live=None):
    return open_approval_turn(
        session_id=session, session_instance=instance,
        principal=principal or Principal(channel="web", admin=True),
        session_is_live=live or (lambda _sid, _instance: True),
    )


def propose(queue, context, *, command="printf hello"):
    with tool_approval_scope("terminal_run"):
        task_id = queue.enqueue(
            "jarvis", "toolrpc.terminal_run", "Run command",
            payload={"tool": "terminal_run", "target": "terminal_run",
                     "args": {"target": "dev", "command": command}},
            risk_tier=3, autonomy_level="ask",
        )
        queue.transition(task_id, TaskStatus.BLOCKED,
                         decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    return task_id, digest


def deny(queue, task_id, digest):
    result = SmartApprovalResult(
        "deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1_000_000.0,
    )
    assert queue.store_smart_terminal_judgement(
        task_id, digest, result, check=lambda: True,
    )[0]["decision"] == "deny"


def test_current_invocation_denial_is_not_next_turn_snapshot_until_explicit_ack(queue):
    context = turn()
    token = bind_approval_turn(context)
    try:
        task_id, digest = propose(queue, context)
        deny(queue, task_id, digest)
        assert queue.chat_outcome_snapshot(context) == []
        item = queue.chat_invocation_outcome(context, task_id)
        assert item["task_id"] == task_id and item["originating_turn_id"] == context.turn_id
        assert item["guardian"] == {"decision": "deny", "consecutive_denials": 1,
                                    "breaker": False}
        assert len(item["revision"]) == 64
        assert queue.chat_invocation_outcome(context, task_id) == item
        assert queue.chat_outcomes_for_backup("s")["tasks"][0]["acknowledged_revision"] is None
        assert queue.ack_chat_outcomes(context, [item]) == 1
        assert queue.chat_invocation_outcome(context, task_id) is None
    finally:
        close_approval_turn(context, token)
    assert queue.chat_outcome_snapshot(turn()) == []


def test_unready_foreign_identity_and_revoked_context_never_get_invocation_feedback(queue):
    live = [True]
    context = turn(live=lambda _sid, _instance: live[0])
    token = bind_approval_turn(context)
    try:
        task_id, digest = propose(queue, context)
        deny(queue, task_id, digest)
        assert queue.chat_invocation_outcome(turn(), task_id) is None
        assert queue.chat_invocation_outcome(turn(session="other"), task_id) is None
        assert queue.chat_invocation_outcome(turn(instance="other"), task_id) is None
        telegram = Principal(channel="telegram", sender="owner", chat="room", admin=True)
        assert queue.chat_invocation_outcome(turn(principal=telegram), task_id) is None
        for invalid in (True, 0, -1, "1"):
            assert queue.chat_invocation_outcome(context, invalid) is None
        live[0] = False
        assert queue.chat_invocation_outcome(context, task_id) is None
    finally:
        close_approval_turn(context, token)

    another = turn()
    second_token = bind_approval_turn(another)
    try:
        with tool_approval_scope("terminal_run"):
            unready = queue.enqueue(
                "jarvis", "toolrpc.terminal_run", "Unready",
                payload={"tool": "terminal_run", "target": "terminal_run",
                         "args": {"target": "dev", "command": "printf unready"}},
                risk_tier=3, autonomy_level="ask",
            )
        assert queue.chat_invocation_outcome(another, unready) is None
    finally:
        close_approval_turn(another, second_token)


def test_edit_birth_and_expiry_cannot_replay_stale_guardian_feedback(queue):
    context = turn()
    token = bind_approval_turn(context)
    try:
        task_id, digest = propose(queue, context)
        deny(queue, task_id, digest)
        original = queue.chat_invocation_outcome(context, task_id)
        queue.update_payload(task_id, queue.get(task_id).payload)
        edited = queue.chat_invocation_outcome(context, task_id)
        assert edited["intent"] == "changed" and "guardian" not in edited
        assert edited["revision"] != original["revision"]
        assert queue.ack_chat_outcomes(context, [original]) == 0
        queue._conn.execute("UPDATE tasks SET created_at='replacement' WHERE id=?", (task_id,))
        queue._conn.commit()
        substituted = queue.chat_invocation_outcome(context, task_id)
        assert substituted is None or (
            substituted["outcome"] == "lost" and "guardian" not in substituted
        )
        queue._conn.execute("UPDATE tasks SET created_at=?,status='expired' WHERE id=?",
                            (queue.chat_outcomes_for_backup("s")["tasks"][0]["task_birth"], task_id))
        queue._conn.commit()
        expired = queue.chat_invocation_outcome(context, task_id)
        assert expired is None or (
            expired["outcome"] == "expired_unanswered" and "guardian" not in expired
        )
    finally:
        close_approval_turn(context, token)


def test_current_ack_requires_exact_revision_and_principal_then_next_turn_is_empty(queue):
    context = turn()
    token = bind_approval_turn(context)
    try:
        task_id, digest = propose(queue, context)
        deny(queue, task_id, digest)
        old = queue.chat_invocation_outcome(context, task_id)
        assert queue.ack_chat_outcomes(turn(session="foreign"), [old]) == 0
        assert queue.ack_chat_outcomes(context, [{**old, "revision": "0" * 64}]) == 0
        queue.update_payload(task_id, queue.get(task_id).payload)
        assert queue.ack_chat_outcomes(context, [old]) == 0
        fresh = queue.chat_invocation_outcome(context, task_id)
        assert fresh["revision"] != old["revision"]
        assert queue.ack_chat_outcomes(context, [fresh]) == 1
    finally:
        close_approval_turn(context, token)
    assert queue.chat_outcome_snapshot(turn()) == []


def test_previous_turn_ack_contract_remains_available(queue):
    origin = turn()
    token = bind_approval_turn(origin)
    try:
        task_id, _digest = propose(queue, origin)
    finally:
        close_approval_turn(origin, token)
    consumer = turn()
    item, = queue.chat_outcome_snapshot(consumer)
    assert item["task_id"] == task_id
    assert queue.ack_chat_outcomes(consumer, [item]) == 1
    assert queue.chat_outcome_snapshot(turn()) == []
