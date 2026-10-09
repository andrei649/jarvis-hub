"""One human decision may continue one current smart-DENY terminal task."""

from __future__ import annotations

import hashlib
import hmac
import threading
from dataclasses import replace
from uuid import uuid4

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
    tool_approval_scope,
)
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.owner_once import OwnerOnceOwner
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.commands import Principal
from agents.core.kernel import Decision, Verdict
from agents.core.kernel.binding import MediationKernelBridge


def _signer():
    return DetachedHMACSigner(
        lambda data: hmac.new(b"owner-once-fixture", data, hashlib.sha256).hexdigest()
    )


@pytest.fixture
def queue(tmp_path):
    value = TaskQueue(str(tmp_path / "owner-once.db"), mediation_signer=_signer()).initialize()
    yield value
    value.close()


def _turn(*, sender="99", instance="birth"):
    return open_approval_turn(
        session_id="telegram-session", session_instance=instance,
        principal=Principal(channel="telegram", sender=sender, chat="99", admin=True),
        session_is_live=lambda _session, _instance: True,
    )


def _denied(queue, turn):
    token = bind_approval_turn(turn)
    with tool_approval_scope("terminal_run"):
        task_id = queue.enqueue(
            "jarvis", "toolrpc.terminal_run", "One terminal command",
            payload={"tool": "terminal_run", "target": "terminal_run",
                     "args": {"target": "dev", "command": "printf hello"}},
            risk_tier=3, autonomy_level="ask",
        )
        queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    result = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1.0)
    assert queue.store_smart_terminal_judgement(task_id, digest, result, check=lambda: True)[0]
    return task_id, digest, token


def test_current_denial_can_be_offered_once_to_its_live_origin(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True)
        assert offer is not None
        assert offer.task_id == task_id
        assert len(offer.nonce) == 32
        assert queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True) is None
        assert queue.get(task_id).status == "blocked"
    finally:
        close_approval_turn(turn, token)


def test_generic_accept_cannot_promote_exact_smart_denial(queue):
    turn = _turn()
    task_id, _digest, token = _denied(queue, turn)
    try:
        with pytest.raises(TaskQueueError):
            queue.transition_with_group(
                task_id, TaskStatus.APPROVED, decided_by="admin", decision="accept",
                human_reason=None,
            )
        assert queue.get(task_id).status == "blocked"
    finally:
        close_approval_turn(turn, token)


def test_unattended_exact_denial_is_settled_but_stale_snapshot_is_not(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        assert not queue.reject_smart_terminal_denial(task_id, "0" * 64, check=lambda: True)
        assert queue.get(task_id).status == "blocked"
        assert queue.reject_smart_terminal_denial(task_id, digest, check=lambda: True)
        task = queue.get(task_id)
        assert (task.status, task.decision, task.decided_by) == (
            "rejected", "smart-deny", "smart_approval"
        )
        assert not queue.reject_smart_terminal_denial(task_id, digest, check=lambda: True)
    finally:
        close_approval_turn(turn, token)


def test_unattended_denial_without_chat_origin_still_settles(queue):
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Unattended command",
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": "printf hello"}},
        risk_tier=3, autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    result = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1.0)
    assert queue.store_smart_terminal_judgement(task_id, digest, result, check=lambda: True)[0]
    assert queue.reject_smart_terminal_denial(task_id, digest, check=lambda: True)
    assert queue.get(task_id).status == "rejected"
    assert queue.smart_terminal_denial(task_id, digest)["decision"] == "deny"
    assert queue.smart_terminal_denial(task_id, "0" * 64) is None


def test_manual_reject_does_not_project_as_machine_denial(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        queue.transition(task_id, TaskStatus.REJECTED, decided_by="admin",
                         decision="reject", human_reason=None)
        assert queue.smart_terminal_denial(task_id, digest) is None
    finally:
        close_approval_turn(turn, token)


def test_edited_snapshot_and_forged_human_metadata_hide_machine_denial(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        queue.update_payload(task_id, {"tool": "terminal_run", "target": "terminal_run",
                                       "args": {"target": "dev", "command": "printf edited"}})
        assert queue.smart_terminal_denial(task_id, digest) is None
    finally:
        close_approval_turn(turn, token)

    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", "Another command",
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": "printf hello"}},
        risk_tier=3, autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    denial = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1.0)
    assert queue.store_smart_terminal_judgement(task_id, digest, denial, check=lambda: True)[0]
    assert queue.reject_smart_terminal_denial(task_id, digest, check=lambda: True)
    queue._conn.execute("UPDATE tasks SET human_decision=? WHERE id=?",
                        ('{"action":"once"}', task_id))
    queue._conn.commit()
    assert queue.smart_terminal_denial(task_id, digest) is None


def _delivered(queue, turn, task_id, digest):
    offer = queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True)
    assert offer is not None
    assert queue.mark_owner_once_delivered(
        offer, chat_id=99, user_id=99, message_id=17,
        generation="22222222222242228222222222222222", live_check=lambda: True,
    )
    return offer


def _owner(turn):
    return OwnerOnceOwner(turn.principal_key, "telegram", 99, 99, 17,
                          "22222222222242228222222222222222")


def test_delivered_once_decision_requires_exact_owner_and_is_not_replayable(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        wrong = OwnerOnceOwner(turn.principal_key, "telegram", 99, 98, 17,
                               "22222222222242228222222222222222")
        assert queue.decide_owner_once(offer, offer.nonce, "once",
                                       authenticated_owner=wrong, live_check=lambda: True) is None
        assert queue.get(task_id).status == "blocked"
        claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                        authenticated_owner=_owner(turn), live_check=lambda: True)
        assert claim is not None and claim.task_id == task_id
        assert queue.get(task_id).status == "approved"
        assert queue.decide_owner_once(offer, offer.nonce, "once",
                                       authenticated_owner=_owner(turn), live_check=lambda: True) is None
        assert queue.reject_smart_terminal_denial(task_id, digest, check=lambda: True) is False
    finally:
        close_approval_turn(turn, token)


def test_owner_reject_boolean_commits_only_exact_delivered_reply(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        wrong = OwnerOnceOwner(turn.principal_key, "telegram", 99, 98, 17,
                               "22222222222242228222222222222222")
        tally = queue._conn.execute(
            "SELECT consecutive_denials FROM chat_guardian_denial_tallies"
        ).fetchone()[0]
        assert not queue.reject_owner_once(offer, "0" * 32,
                                           authenticated_owner=_owner(turn),
                                           live_check=lambda: True)
        assert not queue.reject_owner_once(offer, offer.nonce,
                                           authenticated_owner=wrong,
                                           live_check=lambda: True)
        assert not queue.reject_owner_once(offer, offer.nonce,
                                           authenticated_owner=_owner(turn),
                                           live_check=lambda: False)
        assert queue.get(task_id).status == "blocked"
        assert queue.reject_owner_once(offer, offer.nonce,
                                       authenticated_owner=_owner(turn),
                                       live_check=lambda: True)
        task = queue.get(task_id)
        assert task.status == "rejected"
        assert task.human_decision["action"] == "reject"
        assert task.human_decision["by"] == "owner_once"
        assert queue.smart_terminal_denial(task_id, digest)["decision"] == "deny"
        assert queue._conn.execute(
            "SELECT consecutive_denials FROM chat_guardian_denial_tallies"
        ).fetchone()[0] == tally
        assert not queue.reject_owner_once(offer, offer.nonce,
                                           authenticated_owner=_owner(turn),
                                           live_check=lambda: True)
    finally:
        close_approval_turn(turn, token)


def test_owner_reject_refuses_stale_offer_and_legacy_deny_remains_none(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        queue.update_payload(task_id, {"tool": "terminal_run", "target": "terminal_run",
                                       "args": {"target": "dev", "command": "printf changed"}})
        assert not queue.reject_owner_once(offer, offer.nonce,
                                           authenticated_owner=_owner(turn),
                                           live_check=lambda: True)
        assert queue.get(task_id).status == "blocked"
        assert queue.smart_terminal_denial(task_id, digest) is None

        second_id, second_digest, second_token = _denied(queue, turn)
        try:
            second = _delivered(queue, turn, second_id, second_digest)
            assert queue.decide_owner_once(second, second.nonce, "deny",
                                           authenticated_owner=_owner(turn),
                                           live_check=lambda: True) is None
            assert queue.get(second_id).status == "rejected"
            assert queue.get(second_id).human_decision["by"] == "owner_once"
            assert queue.smart_terminal_denial(second_id, second_digest)["decision"] == "deny"
            assert not queue.reject_owner_once(second, second.nonce,
                                               authenticated_owner=_owner(turn),
                                               live_check=lambda: True)
        finally:
            close_approval_turn(turn, second_token)
    finally:
        close_approval_turn(turn, token)


def test_owner_denial_observation_requires_exact_offer_audit(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        assert queue.reject_owner_once(offer, offer.nonce,
                                       authenticated_owner=_owner(turn),
                                       live_check=lambda: True)
        assert queue.smart_terminal_denial(task_id, digest)["decision"] == "deny"
        queue._conn.execute("UPDATE task_owner_once SET owner_decision_id=? WHERE task_id=?",
                            ("0" * 32, task_id))
        queue._conn.commit()
        assert queue.smart_terminal_denial(task_id, digest) is None
    finally:
        close_approval_turn(turn, token)


def test_machine_settled_denials_keep_exact_guardian_breaker_and_ack(queue):
    turn = _turn()
    tokens = []
    try:
        items = []
        for expected in (1, 2, 3):
            task_id, digest, nested = _denied(queue, turn)
            tokens.append(nested)
            assert queue.reject_smart_terminal_denial(task_id, digest, check=lambda: True)
            item = queue.chat_invocation_outcome(turn, task_id)
            assert item is not None
            assert item["guardian"] == {
                "decision": "deny", "consecutive_denials": expected,
                "breaker": expected == 3,
            }
            items.append(item)
        assert queue.ack_chat_outcomes(turn, items) == 3
        assert all(queue.chat_invocation_outcome(turn, item["task_id"]) is None
                   for item in items)
    finally:
        for token in reversed(tokens):
            close_approval_turn(turn, token)


def test_owner_once_and_owner_reject_retain_denial_observation(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    second_token = None
    third_token = None
    try:
        offer = _delivered(queue, turn, task_id, digest)
        claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                        authenticated_owner=_owner(turn),
                                        live_check=lambda: True)
        assert claim is not None
        item = queue.chat_invocation_outcome(turn, task_id)
        assert item is not None
        assert item["intent"] == "original"
        assert item["guardian"] == {"decision": "deny", "consecutive_denials": 1,
                                    "breaker": False}
        assert item["decision"]["action"] == "once"
        assert item["decision"]["by"] == "owner_once"

        second_id, second_digest, second_token = _denied(queue, turn)
        second = _delivered(queue, turn, second_id, second_digest)
        assert queue.reject_owner_once(second, second.nonce,
                                       authenticated_owner=_owner(turn),
                                       live_check=lambda: True)
        rejected = queue.chat_invocation_outcome(turn, second_id)
        assert rejected is not None
        assert rejected["guardian"] == {"decision": "deny", "consecutive_denials": 2,
                                        "breaker": False}
        assert rejected["decision"]["action"] == "reject"
        assert rejected["decision"]["by"] == "owner_once"

        third_id, third_digest, third_token = _denied(queue, turn)
        third = _delivered(queue, turn, third_id, third_digest)
        assert queue.decide_owner_once(third, third.nonce, "once",
                                       authenticated_owner=_owner(turn),
                                       live_check=lambda: True) is not None
        warning = queue.chat_invocation_outcome(turn, third_id)
        assert warning is not None
        assert warning["guardian"] == {"decision": "deny", "consecutive_denials": 3,
                                       "breaker": True}
        assert warning["decision"]["action"] == "once"
    finally:
        if third_token is not None:
            close_approval_turn(turn, third_token)
        if second_token is not None:
            close_approval_turn(turn, second_token)
        close_approval_turn(turn, token)


def test_unsigned_owner_once_metadata_cannot_project_a_decision_or_guardian(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        assert queue.decide_owner_once(offer, offer.nonce, "once",
                                       authenticated_owner=_owner(turn),
                                       live_check=lambda: True) is not None
        assert queue.chat_invocation_outcome(turn, task_id) is not None
        queue._conn.execute("UPDATE task_owner_once SET signature=? WHERE task_id=?",
                            ("invalid", task_id))
        queue._conn.commit()
        assert queue.chat_invocation_outcome(turn, task_id) is None
    finally:
        close_approval_turn(turn, token)


def test_withdrawn_owner_acceptance_remains_observable_without_execution_authority(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                        authenticated_owner=_owner(turn),
                                        live_check=lambda: True)
        assert claim is not None
        assert queue.revoke_owner_once(offer)
        assert queue.get(task_id).status == "rejected"
        assert not queue.verify_owner_once_terminal_approval(task_id,
                                                              check=lambda _receipt: True)
        assert not queue.verify_owner_once_terminal_result(task_id)
    finally:
        close_approval_turn(turn, token)
    next_turn = _turn()
    observations = queue.chat_outcome_snapshot(next_turn)
    item = next(item for item in observations if item["task_id"] == task_id)
    assert item["state"] == "rejected"
    assert item["intent"] == "original"
    assert item["decision"]["action"] == "once"
    assert item["decision"]["by"] == "owner_once"
    assert item["guardian"] == {"decision": "deny", "consecutive_denials": 1,
                                "breaker": False}
    assert queue._conn.execute(
        "SELECT consecutive_denials FROM chat_guardian_denial_tallies"
    ).fetchone()[0] == 1
    queue._conn.execute("UPDATE task_owner_once SET offer_nonce_sha256=? WHERE task_id=?",
                        ("0" * 64, task_id))
    queue._conn.commit()
    assert not any(item["task_id"] == task_id for item in queue.chat_outcome_snapshot(next_turn))


def test_off_mode_claim_and_dispatch_are_private_one_use(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                        authenticated_owner=_owner(turn), live_check=lambda: True)
        assert queue.runnable(task_id=task_id) == []
        assert queue.claim_mediated(task_id, execution_id="stray") is None
        running = queue.claim_owner_once(task_id, claim, execution_id="owner-run",
                                         live_check=lambda: True)
        assert running is not None and running.status == "running"
        assert queue.claim_owner_once(task_id, claim, execution_id="second",
                                      live_check=lambda: True) is None
        assert queue.verify_owner_once_terminal_approval(task_id, check=lambda _receipt: True)
        assert queue.owner_once_dispatch_current(task_id, claim, live_check=lambda: True)
        assert not queue.owner_once_dispatch_current(task_id, claim, live_check=lambda: True)
    finally:
        close_approval_turn(turn, token)


def test_web_admin_without_reply_transport_cannot_get_an_offer(queue):
    turn = open_approval_turn(
        session_id="web-owner", session_instance="birth",
        principal=Principal(channel="web", admin=True),
        session_is_live=lambda _session, _instance: True,
    )
    task_id, digest, token = _denied(queue, turn)
    try:
        assert queue.offer_owner_once(task_id, digest, turn=turn,
                                      live_check=lambda: True) is None
        assert queue.reject_smart_terminal_denial(task_id, digest, check=lambda: True)
    finally:
        close_approval_turn(turn, token)


def test_noncanonical_telegram_sender_cannot_get_owner_offer(queue):
    turn = _turn(sender="099")
    task_id, digest, token = _denied(queue, turn)
    try:
        assert queue.offer_owner_once(task_id, digest, turn=turn,
                                      live_check=lambda: True) is None
    finally:
        close_approval_turn(turn, token)


def test_copied_claim_and_revoked_claim_cannot_dispatch(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                        authenticated_owner=_owner(turn), live_check=lambda: True)
        assert queue.claim_owner_once(task_id, replace(claim), execution_id="copy",
                                      live_check=lambda: True) is None
        assert queue.claim_owner_once(task_id, claim, execution_id="owner-run",
                                      live_check=lambda: True) is not None
        assert queue.revoke_owner_once(offer)
        assert not queue.owner_once_dispatch_current(task_id, claim, live_check=lambda: True)
        assert not queue.verify_owner_once_terminal_approval(task_id, check=lambda _r: True)
    finally:
        close_approval_turn(turn, token)


def test_edited_denial_cannot_reuse_old_ready_intent_or_offer(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        old = queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True)
        queue.update_payload(task_id, {"tool": "terminal_run", "target": "terminal_run",
                                       "args": {"target": "dev", "command": "printf changed"}})
        changed_digest = queue.approval_snapshot_digest(queue.get(task_id))
        denial = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 2.0)
        assert queue.store_smart_terminal_judgement(
            task_id, changed_digest, denial, check=lambda: True,
        )[0]
        assert queue.offer_owner_once(task_id, changed_digest, turn=turn,
                                      live_check=lambda: True) is None
        assert not queue.mark_owner_once_delivered(
            old, chat_id=99, user_id=99, message_id=17,
            generation="22222222222242228222222222222222", live_check=lambda: True,
        )
    finally:
        close_approval_turn(turn, token)


def test_stale_offer_withdrawal_does_not_reject_new_approved_revision(queue):
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        old = queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True)
        queue.update_payload(task_id, {"tool": "terminal_run", "target": "terminal_run",
                                       "args": {"target": "dev", "command": "printf replacement"}})
        fresh_digest = queue.approval_snapshot_digest(queue.get(task_id))
        machine = SmartApprovalResult("approve", "a" * 64, "b" * 64,
                                      {"model": "fixture"}, 2.0)
        assert queue.store_smart_terminal_judgement(
            task_id, fresh_digest, machine, check=lambda: True,
        )[0]
        assert queue.get(task_id).status == "approved"
        assert queue.revoke_owner_once(old)
        assert queue.get(task_id).status == "approved"
        assert queue.get(task_id).decision == "smart-approve"
    finally:
        close_approval_turn(turn, token)


@pytest.mark.asyncio
async def test_enforced_claim_preserves_b7_event_and_hold_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    head = [None]

    def cas(expected, replacement):
        if head[0] != expected:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(
        str(tmp_path / "enforced.db"), mediation_mode="enforce", mediation_signer=_signer(),
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
        mediation_classifier=lambda _kind: True, mediation_scope="global",
    ).initialize()
    worker = AutonomyWorker(
        queue, kernel=MediationKernelBridge(lambda _action: Decision(
            Verdict.QUEUE, tier=3, reason="owner review")), mediation_signer=_signer(),
    )
    turn = _turn()
    token = bind_approval_turn(turn)
    try:
        with tool_approval_scope("terminal_run"):
            task = await worker.submit(
                "jarvis", "toolrpc.terminal_run", "One terminal command",
                {"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": "printf hello"}},
                attention_mode="none",
            )
        assert task.status == "blocked"
        digest = queue.approval_snapshot_digest(queue.get(task.id))
        denied = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1.0)
        assert queue.store_smart_terminal_judgement(task.id, digest, denied,
                                                    check=lambda: True)[0]
        offer = _delivered(queue, turn, task.id, digest)
        claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                        authenticated_owner=_owner(turn), live_check=lambda: True)
        assert claim is not None
        assert queue.verify_owner_once_terminal_approval(task.id, check=lambda _r: True)
        queue.mediation_mode = "hold"
        assert queue.claim_owner_once(task.id, claim, execution_id="hold-run",
                                      live_check=lambda: True) is None
        queue.mediation_mode = "enforce"
        assert queue.verify_owner_once_terminal_approval(task.id, check=lambda _r: True)
        assert queue.claim_owner_once(task.id, claim, execution_id=str(uuid4()),
                                      live_check=lambda: True) is not None
        assert queue.verified_mediation_stats()["governed"] == 1
        assert queue.owner_once_dispatch_current(task.id, claim, live_check=lambda: True)
    finally:
        close_approval_turn(turn, token)
        queue.close()


def test_two_connections_once_vs_final_denial_have_one_winner(queue):
    second = TaskQueue(queue.db_path, mediation_signer=_signer()).initialize()
    turn = _turn()
    task_id, digest, token = _denied(queue, turn)
    try:
        offer = _delivered(queue, turn, task_id, digest)
        barrier = threading.Barrier(2)
        outcomes = {}

        def owner_decision():
            barrier.wait()
            outcomes['once'] = queue.decide_owner_once(
                offer, offer.nonce, 'once', authenticated_owner=_owner(turn),
                live_check=lambda: True,
            ) is not None

        def final_denial():
            barrier.wait()
            outcomes['deny'] = second.reject_smart_terminal_denial(
                task_id, digest, check=lambda: True,
            )

        threads = [threading.Thread(target=owner_decision),
                   threading.Thread(target=final_denial)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        assert all(not thread.is_alive() for thread in threads)
        assert sum(outcomes.values()) == 1
        assert queue.get(task_id).status == ('approved' if outcomes['once'] else 'rejected')
    finally:
        close_approval_turn(turn, token)
        second.close()
