"""Signed original-source restart cards and one-use queue receipts."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from agents.core.autonomy import irreversible
from agents.core.autonomy.queue import TaskQueueError
from agents.core.autonomy.restart_records import KIND, PREVIEW, TITLE, request_payload
from agents.core.command_source import (
    InboundCommandSource,
    TelegramCommandCandidate,
    bind_source,
)
from agents.core.commands import Principal
from agents.core.kernel import Action, Verdict, revalidate
from agents.core.kernel.registry import Mediation, classify
from agents.core.restart_notice import NOTICE_TEXT, notify_completed_restart
from tests.test_h084_update_kernel import _rig
from tests.test_task_mediation_evidence import NOW_MS


def _source(rig, *, update_id=82, text="/restart"):
    adapter = SimpleNamespace(_running=True, _owner_once_generation="g" * 32,
                              _verified_bot_generation="g" * 32, _bot_id=19)
    gateway = SimpleNamespace(command_source_adapter=lambda: adapter,
                              pairing=SimpleNamespace(is_allowed=lambda _c, _s: True))
    candidate = TelegramCommandCandidate(adapter, "g" * 32, 19, update_id, 71,
                                         99, 99, text, asyncio.current_task())
    source = InboundCommandSource(candidate, "inbox-71", gateway)
    principal = Principal(channel="telegram", sender="99", chat="99", admin=True, scope="dm")
    rig.orch.channels = {"telegram": adapter}
    rig.orch._channel_principal = lambda *_args: principal
    return source, principal


def _payload_and_ticket(rig, *, update_id=82, text="/restart"):
    source, principal = _source(rig, update_id=update_id, text=text)
    requester = {"provider_key": source.provider_id, "bot_id": source.bot_id,
                 "update_id": source.update_id, "message_id": source.message_id,
                 "chat_id": source.chat_id, "sender_id": source.sender_id,
                 "inbox_id": source.inbox_id}
    base = request_payload(requester)
    with bind_source(source):
        ticket = rig.queue.issue_restart_source(
            orch=rig.orch, principal=principal, source=source,
            title=TITLE, request_payload=base,
        )
    assert ticket is not None
    return {**base, "source_ticket": ticket.as_dict()}, ticket


def _queue_card(rig, payload):
    queued = irreversible.enqueue(rig.orch, KIND, title=TITLE,
                                  payload=payload, preview=PREVIEW)
    assert "pending" in queued, queued
    return queued["pending"]


async def _signed_completion(rig, *, update_id=82, boot_id="a" * 32, text="/restart"):
    """Genuine B7 source, human card, governed execution and signed DONE."""
    payload, ticket = _payload_and_ticket(rig, update_id=update_id, text=text)
    task_id = _queue_card(rig, payload)
    await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
    running = rig.queue.claim_mediated(task_id, execution_id=str(uuid.uuid4()))
    assert running is not None
    assert rig.queue.increment_attempts(task_id) == 1
    running = rig.queue.get(task_id)
    arm = rig.queue.arm_restart(running, boot_id)
    assert arm is not None
    result = {"status": "ok", "phase": "armed", "intent_digest": arm.intent_digest}
    verified = rig.queue.complete_restart(running, result)
    assert verified is not None
    return task_id, arm, verified, ticket


def test_exact_kernel_restart_seal_is_auto_only():
    from agents.core.autonomy.policy import AutonomyPolicy

    assert classify(KIND) is Mediation.KERNEL
    assert classify("hub.restart_other") is None
    action = Action(kind=KIND, agent="owner", title=TITLE,
                    payload={"risk_tier": 3, "reversible": False, "approved_task_id": 7},
                    origin="manual", scope="global")
    policy = AutonomyPolicy(mode="auto")
    assert revalidate(action, policy=policy, approval_check=lambda actual: actual == action).verdict is Verdict.GRANT
    assert revalidate(action, policy=policy).verdict is not Verdict.GRANT
    policy.mode = "ask"
    assert revalidate(action, policy=policy, approval_check=lambda _a: True).verdict is not Verdict.GRANT


@pytest.mark.asyncio
async def test_source_ticket_requires_current_owner_task_and_exact_payload(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        source, principal = _source(rig)
        base = request_payload({"provider_key": source.provider_id, "bot_id": source.bot_id,
                                "update_id": source.update_id, "message_id": source.message_id,
                                "chat_id": source.chat_id, "sender_id": source.sender_id,
                                "inbox_id": source.inbox_id})
        assert rig.queue.issue_restart_source(
            orch=rig.orch, principal=principal, source=source,
            request_payload=base) is None
        with bind_source(source):
            assert rig.queue.issue_restart_source(
                orch=rig.orch, principal=principal, source=source,
                request_payload={**base, "operation": "changed"}) is None
            async def copied_task():
                return rig.queue.issue_restart_source(
                    orch=rig.orch, principal=principal, source=source,
                    request_payload=base)

            assert await asyncio.create_task(copied_task()) is None
            ticket = rig.queue.issue_restart_source(
                orch=rig.orch, principal=principal, source=source,
                request_payload=base)
        assert ticket is not None
        with pytest.raises(TaskQueueError):
            rig.queue.enqueue("owner", KIND, TITLE, {**base, "source_ticket": ticket.as_dict()})
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_signed_card_completion_and_one_use_physical_notice(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        task_id, arm, verified, _ticket = await _signed_completion(rig)
        assert rig.queue.get(task_id).status == "done"
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) == verified
        payload2, _ = _payload_and_ticket(rig, update_id=83)
        assert irreversible.enqueue(rig.orch, KIND, title=TITLE, payload=payload2,
                                     preview=PREVIEW)["refused"] == "restart_in_progress"
        claim = rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32)
        assert claim is not None
        assert rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32) is None
        assert rig.queue.finish_restart_physical(claim, "requested")
        assert not rig.queue.finish_restart_physical(claim, "requested")
        assert rig.queue.recover_restart_attempts("b" * 32) == {"refused": 0, "unknown": 0}
        assert rig.queue.list_restart_notices("b" * 32) == (verified,)
        notice = rig.queue.claim_restart_notice(
            task_id, arm.intent_digest, "b" * 32, live_check=lambda _v: True)
        assert notice is not None and notice.restart == verified
        assert rig.queue.claim_restart_notice(
            task_id, arm.intent_digest, "b" * 32, live_check=lambda _v: True) is None
        assert rig.queue.finish_restart_notice(notice, "sent")
        assert rig.queue.list_restart_notices("b" * 32) == ()
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_completion_refuses_wrong_result_and_duplicate_arm(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        payload, _ = _payload_and_ticket(rig)
        task_id = _queue_card(rig, payload)
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        assert rig.queue.claim_mediated(task_id, execution_id=str(uuid.uuid4()))
        assert rig.queue.increment_attempts(task_id) == 1
        running = rig.queue.get(task_id)
        arm = rig.queue.arm_restart(running, "a" * 32)
        assert arm is not None
        assert rig.queue.arm_restart(running, "a" * 32) is None
        for result in (
            {"status": "ok", "phase": "changed", "intent_digest": arm.intent_digest},
            {"status": "ok", "phase": "armed", "intent_digest": "f" * 64},
            {"status": "ok", "phase": "armed", "intent_digest": arm.intent_digest,
             "extra": "untrusted"},
        ):
            assert rig.queue.complete_restart(running, result) is None
            assert rig.queue.get(task_id).status == "running"
        result = {"status": "ok", "phase": "armed", "intent_digest": arm.intent_digest}
        assert rig.queue.complete_restart(running, result) is not None
        assert rig.queue.complete_restart(running, result) is None
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("table,column,replacement", [
    ("tasks", "result", '{"status":"ok","phase":"armed","intent_digest":"faked"}'),
    ("tasks", "human_decision", '{"action":"accept","by":"other"}'),
    ("tasks", "mediation_receipt", '{}'),
    ("task_restart_sources", "ticket_sha256", "0" * 64),
    ("task_restart_intents", "arm_signature", "bad"),
    ("task_restart_intents", "completion_signature", "bad"),
    ("task_restart_intents", "completion_body", b'{}'),
])
async def test_signed_completion_detects_mutated_evidence(
    tmp_path, monkeypatch, table, column, replacement,
):
    rig = _rig(tmp_path, monkeypatch)
    try:
        task_id, arm, verified, _ = await _signed_completion(rig)
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) == verified
        row = rig.queue._conn.execute(
            f"SELECT {column} FROM {table} WHERE task_id=?" if table != "tasks"
            else f"SELECT {column} FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
        original = row[column]
        key = "task_id" if table != "tasks" else "id"
        rig.queue._conn.execute(
            f"UPDATE {table} SET {column}=? WHERE {key}=?", (replacement, task_id),
        )
        rig.queue._conn.commit()
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) is None
        assert rig.queue.validate_restart_completion(
            task_id, arm.intent_digest, for_notification=True) is None
        assert rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32) is None
        rig.queue._conn.execute(
            f"UPDATE {table} SET {column}=? WHERE {key}=?", (original, task_id),
        )
        rig.queue._conn.commit()
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) == verified
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_replay_tombstone_survives_terminal_and_current_policy_controls_effect(
    tmp_path, monkeypatch,
):
    rig = _rig(tmp_path, monkeypatch)
    try:
        task_id, arm, verified, ticket = await _signed_completion(rig)
        payload = {**request_payload(ticket.body["requester"]),
                   "source_ticket": ticket.as_dict()}
        assert rig.queue.refuse_restart_physical(task_id, arm.intent_digest, "a" * 32)
        assert irreversible.enqueue(rig.orch, KIND, title=TITLE, payload=payload,
                                     preview=PREVIEW) == {"refused": "restart_request_seen"}
        assert len(rig.queue.list()) == 1
        rig.queue._mediation_policy_revision = "new-policy"
        rig.queue._mediation_clock_ms = lambda: NOW_MS + 86_400_000
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) is None
        assert rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32) is None
        assert rig.queue.validate_restart_completion(
            task_id, arm.intent_digest, for_notification=True) == verified
        assert rig.queue.list_restart_notices("b" * 32) == ()
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_historical_notice_survives_policy_change_and_new_boot(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        task_id, arm, verified, _ = await _signed_completion(rig)
        claim = rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32)
        assert claim is not None
        assert rig.queue.finish_restart_physical(claim, "requested")
        rig.queue._mediation_policy_revision = "new-policy"
        rig.queue._mediation_clock_ms = lambda: NOW_MS + 86_400_000
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) is None
        assert rig.queue.list_restart_notices("a" * 32) == ()
        assert rig.queue.list_restart_notices("b" * 32) == (verified,)
        assert rig.queue.claim_restart_notice(
            task_id, arm.intent_digest, "b" * 32, live_check=lambda _v: False) is None
        assert rig.queue.claim_restart_notice(
            task_id, arm.intent_digest, "b" * 32, live_check=lambda _v: 1) is None
        notice = rig.queue.claim_restart_notice(
            task_id, arm.intent_digest, "b" * 32, live_check=lambda v: v == verified)
        assert notice is not None
        assert rig.queue.claim_restart_notice(
            task_id, arm.intent_digest, "b" * 32, live_check=lambda _v: True) is None
        assert rig.queue.finish_restart_notice(notice, "unknown")
        assert rig.queue.list_restart_notices("c" * 32) == ()
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_real_signed_completion_reaches_one_fixed_owner_notice(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    sends = []

    async def send(channel, text, **kwargs):
        sends.append((channel, text, kwargs))
        return True

    try:
        task_id, arm, verified, _ = await _signed_completion(rig)
        claim = rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32)
        assert claim and rig.queue.finish_restart_physical(claim, "requested")
        rig.orch.sender_pairing = SimpleNamespace(is_allowed=lambda c, s: c == "telegram" and s == "99")
        rig.orch.channel_manager = SimpleNamespace(send=send)
        assert rig.queue.validate_restart_completion(
            task_id, arm.intent_digest, for_notification=True) == verified
        outcome = await notify_completed_restart(rig.orch, boot_id="b" * 32)
        assert outcome == {"status": "ok", "listed": 1, "sent": 1,
                           "withheld": 0, "unknown": 0}
        assert sends == [("telegram", NOTICE_TEXT,
                          {"chat_id": 99, "plain": True, "voice": False,
                           "delivery_key": f"restart.notice:{task_id}:19:99"})]
        assert (await notify_completed_restart(rig.orch, boot_id="c" * 32))["listed"] == 0
        assert len(sends) == 1
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_two_queue_connections_serialize_active_restart(tmp_path, monkeypatch):
    first = _rig(tmp_path, monkeypatch)
    second = _rig(tmp_path, monkeypatch)
    try:
        first_payload, _ = _payload_and_ticket(first, update_id=91)
        second_payload, _ = _payload_and_ticket(second, update_id=92)
        task_id = _queue_card(first, first_payload)
        assert irreversible.enqueue(second.orch, KIND, title=TITLE,
                                     payload=second_payload, preview=PREVIEW) == {
                                         "refused": "restart_in_progress"}
        assert len(first.queue.list()) == len(second.queue.list()) == 1
        await first.worker.apply_decision(task_id, "reject", decided_by="owner")
        queued = irreversible.enqueue(second.orch, KIND, title=TITLE,
                                      payload=second_payload, preview=PREVIEW)
        assert "pending" in queued and queued["pending"] != task_id
        assert len(first.queue.list()) == len(second.queue.list()) == 2
    finally:
        first.queue.close()
        second.queue.close()


@pytest.mark.asyncio
async def test_ticket_expiring_during_insert_rolls_back_card_and_tombstone(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        payload, _ = _payload_and_ticket(rig)
        snapshot = rig.queue._validated_mediation_snapshot_locked

        def expire_in_transaction():
            rig.queue._mediation_clock_ms = lambda: NOW_MS + 86_400_000
            return snapshot()

        monkeypatch.setattr(rig.queue, "_validated_mediation_snapshot_locked",
                            expire_in_transaction)
        assert irreversible.enqueue(rig.orch, KIND, title=TITLE, payload=payload,
                                     preview=PREVIEW) == {"refused": "approval_queue_refused"}
        assert rig.queue.list() == []
        assert rig.queue._conn.execute("SELECT COUNT(*) FROM task_restart_sources").fetchone()[0] == 0
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_source_ticket_kind_and_agent_are_signed(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        payload, _ = _payload_and_ticket(rig)
        for field, value in (("kind", "hub.update"), ("agent", "other")):
            altered = {**payload, "source_ticket": {
                **payload["source_ticket"],
                "body": {**payload["source_ticket"]["body"], field: value}}}
            assert irreversible.enqueue(rig.orch, KIND, title=TITLE,
                                         payload=altered, preview=PREVIEW) == {
                                             "refused": "approval_queue_refused"}
        assert rig.queue.list() == []
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_signed_event_chain_is_required_for_restart_completion(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        task_id, arm, verified, _ = await _signed_completion(rig)
        row = rig.queue._conn.execute(
            "SELECT signature FROM task_mediation_events WHERE task_id=? AND outcome='governed'",
            (task_id,),
        ).fetchone()
        assert row is not None
        rig.queue._conn.execute(
            "UPDATE task_mediation_events SET signature='bad' WHERE task_id=? AND outcome='governed'",
            (task_id,),
        )
        rig.queue._conn.commit()
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) is None
        assert rig.queue.validate_restart_completion(
            task_id, arm.intent_digest, for_notification=True) is None
        rig.queue._conn.execute(
            "UPDATE task_mediation_events SET signature=? WHERE task_id=? AND outcome='governed'",
            (row["signature"], task_id),
        )
        rig.queue._conn.commit()
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) == verified
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed,expected,notices", [
    (False, {"refused": 1, "unknown": 0}, 0),
    (True, {"refused": 0, "unknown": 1}, 1),
])
async def test_new_boot_recovery_never_replays_physical_attempt(
    tmp_path, monkeypatch, claimed, expected, notices,
):
    rig = _rig(tmp_path, monkeypatch)
    try:
        task_id, arm, verified, _ = await _signed_completion(rig)
        if claimed:
            assert rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32)
        assert rig.queue.recover_restart_attempts("b" * 32) == expected
        assert rig.queue.recover_restart_attempts("c" * 32) == {"refused": 0, "unknown": 0}
        assert rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32) is None
        assert rig.queue.list_restart_notices("c" * 32) == ((verified,) if notices else ())
    finally:
        rig.queue.close()
