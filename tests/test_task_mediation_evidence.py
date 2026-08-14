"""Hostile tests for B7 task-persisted mediation evidence primitives."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace

import pytest

from agents.core.autonomy.mediation import (
    ZERO_HASH,
    DetachedHMACSigner,
    ReceiptExpectation,
    canonical_digest,
    issue_receipt,
    make_event,
    payload_digest,
    reason_digest,
    verify_event_chain,
    verify_receipt,
)

KEY = b"owner-held-test-key-that-is-long-enough"
NOW_MS = 1_786_662_000_000
RECEIPT_ID = "59cf2075-3397-43d7-8035-185a4ef4c1e7"
ENQUEUE_ID = "c01a535d-7f1d-474c-a352-f06af437314a"
REFUSED_ENQUEUE_ID = "f55b8111-2ca4-4dc7-8d43-91fe674c7b5c"


def _mac(payload: bytes) -> str:
    return hmac.new(KEY, payload, hashlib.sha256).hexdigest()


def _signer() -> DetachedHMACSigner:
    return DetachedHMACSigner(_mac)


def _expectation(**overrides) -> ReceiptExpectation:
    values = {
        "enqueue_id": ENQUEUE_ID,
        "agent": "ultron",
        "kind": "filesystem.write",
        "title": "Write bounded report",
        "origin": "generated",
        "scope": "global",
        "payload": {"path": "reports/summary.json", "body": "caf\u00e9"},
        "policy_revision": "policy-17",
        "enqueue_revision": 1,
    }
    values.update(overrides)
    return ReceiptExpectation(**values)


def _receipt(**overrides):
    values = {
        "receipt_id": RECEIPT_ID,
        "expectation": _expectation(),
        "verdict": "queue",
        "tier": 2,
        "reason": "owner approval required",
        "issued_at_ms": NOW_MS,
        "expires_at_ms": NOW_MS + 60_000,
    }
    values.update(overrides)
    receipt = issue_receipt(_signer(), **values)
    assert receipt is not None
    return receipt


def test_canonical_payload_and_reason_digests_are_deterministic_and_exact():
    left = {"z": [1, True, None], "a": {"text": "caf\u00e9"}}
    right = {"a": {"text": "caf\u00e9"}, "z": [1, True, None]}

    assert canonical_digest(left) == canonical_digest(right)
    assert payload_digest(left) == payload_digest(right)
    assert payload_digest({"value": 1}) != payload_digest({"value": 1.0})
    assert reason_digest("denied") != reason_digest("denied ")


@pytest.mark.parametrize(
    "value",
    [
        {"nested": {"too": {"deep": {"for": {"bounded": {"json": {"x": 1}}}}}}},
        {"blob": "x" * 65_537},
        {"not-finite": float("nan")},
        {1: "non-string key"},
        ("tuple", "is-not-json"),
    ],
)
def test_canonical_digest_rejects_malformed_or_unbounded_json(value):
    with pytest.raises(ValueError):
        canonical_digest(value)


def test_receipt_signature_covers_every_canonical_field_and_exact_task_binding():
    receipt = _receipt()
    expected = _expectation()

    assert verify_receipt(_signer(), receipt, expected=expected, now_ms=NOW_MS + 1)
    assert receipt.payload_sha256 == payload_digest(expected.payload)
    assert receipt.reason_sha256 == reason_digest("owner approval required")

    for change in (
        {"receipt_id": "cf0c86cc-4df7-4708-b9e9-81ec006e9c0c"},
        {"enqueue_id": "2462731a-c8c3-4ada-8aee-32d9bc18839f"},
        {"agent": "jarvis"},
        {"kind": "filesystem.delete"},
        {"title": "Write a different report"},
        {"origin": "manual"},
        {"scope": "node:laptop"},
        {"payload_sha256": "1" * 64},
        {"verdict": "grant"},
        {"tier": 3},
        {"reason_sha256": "2" * 64},
        {"policy_revision": "policy-18"},
        {"issued_at_ms": NOW_MS - 1},
        {"expires_at_ms": NOW_MS + 1},
        {"enqueue_revision": 2},
    ):
        assert not verify_receipt(
            _signer(), replace(receipt, **change), expected=expected, now_ms=NOW_MS + 1
        )


@pytest.mark.parametrize(
    "expected",
    [
        _expectation(payload={"path": "reports/other.json", "body": "caf\u00e9"}),
        _expectation(kind="filesystem.delete"),
        _expectation(scope="node:laptop"),
        _expectation(title="Edited after approval"),
        _expectation(enqueue_revision=2),
        _expectation(policy_revision="policy-18"),
    ],
)
def test_receipt_rejects_task_substitution_revision_and_policy_drift(expected):
    assert not verify_receipt(_signer(), _receipt(), expected=expected, now_ms=NOW_MS + 1)


def test_receipt_expiry_future_issue_and_replay_are_rejected():
    receipt = _receipt()
    expected = _expectation()

    assert not verify_receipt(_signer(), receipt, expected=expected, now_ms=NOW_MS - 1)
    assert not verify_receipt(_signer(), receipt, expected=expected, now_ms=receipt.expires_at_ms)
    assert not verify_receipt(
        _signer(),
        receipt,
        expected=expected,
        now_ms=NOW_MS + 1,
        consumed_enqueue_ids={ENQUEUE_ID},
    )


def test_signed_deny_receipt_is_evidence_but_not_executable_authority():
    receipt = _receipt(verdict="deny")

    assert not verify_receipt(_signer(), receipt, expected=_expectation(), now_ms=NOW_MS + 1)
    assert verify_receipt(
        _signer(),
        receipt,
        expected=_expectation(),
        now_ms=NOW_MS + 1,
        accepted_verdicts={"deny"},
    )


def test_receipt_parsing_and_signer_failures_are_total_and_fail_closed():
    signer = _signer()
    receipt = _receipt()
    malformed = receipt.to_dict()
    malformed["unknown"] = "smuggled"
    boolean_version = receipt.to_dict()
    boolean_version["version"] = True

    assert not verify_receipt(signer, malformed, expected=_expectation(), now_ms=NOW_MS + 1)
    assert not verify_receipt(signer, boolean_version, expected=_expectation(), now_ms=NOW_MS + 1)
    assert not verify_receipt(signer, None, expected=_expectation(), now_ms=NOW_MS + 1)
    assert (
        issue_receipt(
            DetachedHMACSigner(lambda _payload: (_ for _ in ()).throw(RuntimeError("offline"))),
            receipt_id=RECEIPT_ID,
            expectation=_expectation(),
            verdict="queue",
            tier=2,
            reason="approval",
            issued_at_ms=NOW_MS,
            expires_at_ms=NOW_MS + 10,
        )
        is None
    )
    assert not DetachedHMACSigner(lambda _payload: object()).verify(b"payload", "0" * 64)
    assert not DetachedHMACSigner(None).verify(b"payload", "0" * 64)


def test_signed_event_chain_verifies_and_detects_field_hash_signature_and_link_tamper():
    signer = _signer()
    receipt = _receipt()
    first = make_event(
        signer,
        event_id="b7f4bfba-c4f2-41b4-93b4-fba1e748c7ef",
        sequence=1,
        outcome="refused_unmediated",
        task_id=0,
        enqueue_id=REFUSED_ENQUEUE_ID,
        receipt=None,
        execution_id="",
        occurred_at_ms=NOW_MS,
        previous_event_hash=ZERO_HASH,
    )
    assert first is not None
    second = make_event(
        signer,
        event_id="6b70842d-8d02-4c93-af99-0600115d3b71",
        sequence=2,
        outcome="governed",
        task_id=41,
        enqueue_id=ENQUEUE_ID,
        receipt=receipt,
        execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049",
        occurred_at_ms=NOW_MS + 10,
        previous_event_hash=first.event_hash,
    )
    assert second is not None
    assert verify_event_chain(signer, [first, second])

    assert not verify_event_chain(signer, [replace(first, outcome="ungoverned_detected"), second])
    assert not verify_event_chain(signer, [replace(first, event_hash="3" * 64), second])
    assert not verify_event_chain(signer, [first, replace(second, previous_event_hash=ZERO_HASH)])
    assert not verify_event_chain(signer, [first, replace(second, signature="4" * 64)])


def test_event_chain_rejects_receipt_copy_reorder_replay_and_malformed_rows():
    signer = _signer()
    receipt = _receipt()
    event = make_event(
        signer,
        event_id="3a0b4b1a-675b-44aa-9836-406bba9db96a",
        sequence=1,
        outcome="governed",
        task_id=7,
        enqueue_id=ENQUEUE_ID,
        receipt=receipt,
        execution_id="f02d92f4-bf11-4dba-a583-97717764f0cb",
        occurred_at_ms=NOW_MS,
        previous_event_hash=ZERO_HASH,
    )
    assert event is not None
    assert (
        make_event(
            signer,
            event_id="aa5e9da3-b263-4ee3-b8b7-860170d73b29",
            sequence=1,
            outcome="governed",
            task_id=8,
            enqueue_id=REFUSED_ENQUEUE_ID,
            receipt=receipt,
            execution_id="0ab4ce57-ed93-409a-8c27-3d86219d5fc4",
            occurred_at_ms=NOW_MS,
            previous_event_hash=ZERO_HASH,
        )
        is None
    )

    other_receipt = _receipt(receipt_id="ea4d1520-a888-4eed-864f-7987fb540253")
    assert not verify_event_chain(
        signer,
        [replace(event, receipt_id=other_receipt.receipt_id)],
    )
    assert not verify_event_chain(signer, [event, event])
    malformed = event.to_dict()
    malformed["sequence"] = "1"
    assert not verify_event_chain(signer, [malformed])


def test_invalid_event_or_signing_failure_returns_none_without_authority():
    receipt = _receipt()
    broken = DetachedHMACSigner(lambda _payload: "not-a-valid-tag")

    assert (
        make_event(
            broken,
            event_id="invalid",
            sequence=0,
            outcome="governed",
            task_id=-1,
            enqueue_id=ENQUEUE_ID,
            receipt=receipt,
            execution_id="not-a-uuid",
            occurred_at_ms=-1,
            previous_event_hash="not-a-hash",
        )
        is None
    )
