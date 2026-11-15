"""The original owner-DM text is preserved through restart source authority."""

from __future__ import annotations

import uuid

import pytest

from agents.core.autonomy import irreversible
from agents.core.autonomy.mediation import canonical_json
from agents.core.autonomy.restart_records import (
    KIND,
    PREVIEW,
    SOURCE_PURPOSE,
    SOURCE_PURPOSE_V1,
    TITLE,
    request_payload,
)
from agents.core.command_source import (
    bind_source,
    candidate_live,
    plaintext_restart,
    restart_command_text,
    source_for_dispatch,
)
from tests.test_h084_restart_authority import _payload_and_ticket, _rig, _signed_completion, _source


@pytest.mark.parametrize("text", [
    "restart gateway", "Restart Gateway!", "please restart the gateway",
    "PLEASE RESTART THE NERVA GATEWAY???  ", "restart nerva gateway",
    "restart the nerva gateway.", "please restart nerva", "restart nerva\t!",
])
def test_exact_plaintext_restart_families(text):
    assert plaintext_restart(text)
    assert restart_command_text(text)


@pytest.mark.parametrize("text", [
    "/restart", "/RESTART", "restart", "restart the nerva",
    "restart Hermes service", "restart the Hermes service", "restart gateway now",
    "please restart gateway and update", "prestart gateway", "restart gateways",
    "please please restart gateway", " restart gateway", "restart gateway\n",
    "restart\ngateway", "restart gateway; rm -rf /", "restart gateway 🙂",
    "restart gateway" + " " * 114, "ｒｅｓｔａｒｔ gateway", 42, None,
])
def test_plaintext_restart_refuses_near_matches(text):
    assert not plaintext_restart(text)
    assert restart_command_text(text) is (text == "/restart")


@pytest.mark.asyncio
async def test_canonical_dispatch_preserves_exact_original_phrase(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        original = "Please Restart the Nerva Gateway!?  "
        source, principal = _source(rig, text=original)
        with bind_source(source):
            assert candidate_live(source.candidate, adapter=rig.orch.channels["telegram"],
                                  text=original, sender="99", chat_id=99)
            assert not candidate_live(source.candidate, adapter=rig.orch.channels["telegram"],
                                      text="/restart", sender="99", chat_id=99)
            assert source_for_dispatch(text=original, principal=principal, orch=rig.orch) is source
            assert source_for_dispatch(text="/restart", principal=principal, orch=rig.orch) is source
            assert source_for_dispatch(text="restart gateway", principal=principal,
                                       orch=rig.orch) is None
        assert source_for_dispatch(text="/restart", principal=principal, orch=rig.orch) is None
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_v2_ticket_binds_original_text_and_tampering_refuses(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        original = "Please Restart the Nerva Gateway!?  "
        payload, ticket = _payload_and_ticket(rig, text=original)
        assert ticket.body["version"] == 2
        assert ticket.body["purpose"] == SOURCE_PURPOSE
        assert ticket.body["original_text"] == original
        assert rig.queue._restart_ticket(payload, title=TITLE, agent="owner", current=True)
        altered = {**payload, "source_ticket": {**ticket.as_dict(), "body": {
            **ticket.body, "original_text": "/restart"}}}
        assert rig.queue._restart_ticket(altered, title=TITLE, agent="owner", current=True) is None
        assert irreversible.enqueue(rig.orch, KIND, title=TITLE,
                                     payload=altered, preview=PREVIEW) == {
                                         "refused": "approval_queue_refused"}
        assert rig.queue.list() == []
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_phrase_card_completes_with_signed_original_text(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        task_id, arm, verified, ticket = await _signed_completion(
            rig, text="please restart the nerva gateway!", boot_id="a" * 32)
        assert ticket.body["original_text"] == "please restart the nerva gateway!"
        assert rig.queue.get(task_id).status == "done"
        assert rig.queue.validate_restart_completion(task_id, arm.intent_digest) == verified
        assert rig.queue.claim_restart_physical(task_id, arm.intent_digest, "a" * 32)
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_v1_literal_ticket_remains_historical_proof_across_queue_generation(
    tmp_path, monkeypatch,
):
    rig = _rig(tmp_path, monkeypatch)
    try:
        payload, ticket = _payload_and_ticket(rig)
        old_body = {key: value for key, value in ticket.body.items() if key != "original_text"}
        old_body["version"] = 1
        old_body["purpose"] = SOURCE_PURPOSE_V1
        signature = rig.queue._mediation_signer.sign(canonical_json(old_body))
        assert signature
        old_payload = {**request_payload(old_body["requester"]), "source_ticket": {
            "body": old_body, "signature": signature}}
        assert rig.queue._restart_ticket(old_payload, title=TITLE,
                                         agent="owner", current=True)
        result = irreversible.enqueue(rig.orch, KIND, title=TITLE,
                                      payload=old_payload, preview=PREVIEW)
        task_id = result["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        assert rig.queue.claim_mediated(task_id, execution_id=str(uuid.uuid4()))
        assert rig.queue.increment_attempts(task_id) == 1
        running = rig.queue.get(task_id)
        arm = rig.queue.arm_restart(running, "a" * 32)
        assert arm
        verified = rig.queue.complete_restart(
            running, {"status": "ok", "phase": "armed", "intent_digest": arm.intent_digest})
        assert verified
    finally:
        rig.queue.close()
    reopened = _rig(tmp_path, monkeypatch)
    try:
        assert reopened.queue._restart_ticket(old_payload, title=TITLE,
                                               agent="owner", current=False)
        assert reopened.queue._restart_ticket(old_payload, title=TITLE,
                                               agent="owner", current=True) is None
        assert reopened.queue.validate_restart_completion(
            task_id, arm.intent_digest, for_notification=True) == verified
    finally:
        reopened.queue.close()
