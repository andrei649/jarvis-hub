"""Hostile tests for B7 task-persisted mediation evidence primitives."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from agents.core.autonomy.mediation import (
    ZERO_HASH,
    DetachedHMACSigner,
    MediationHead,
    MonotonicHeadAnchor,
    ReceiptExpectation,
    canonical_digest,
    issue_receipt,
    make_event,
    payload_digest,
    reason_digest,
    verify_event_chain,
    verify_receipt,
)
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus

KEY = b"owner-held-test-key-that-is-long-enough"
NOW_MS = 1_786_662_000_000
RECEIPT_ID = "59cf2075-3397-43d7-8035-185a4ef4c1e7"
ENQUEUE_ID = "c01a535d-7f1d-474c-a352-f06af437314a"
REFUSED_ENQUEUE_ID = "f55b8111-2ca4-4dc7-8d43-91fe674c7b5c"


class _MemoryHeadStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._head: MediationHead | None = None

    def read(self) -> MediationHead | None:
        with self._lock:
            return self._head

    def compare_and_swap(self, expected: MediationHead | None, replacement: MediationHead) -> bool:
        with self._lock:
            if self._head != expected:
                return False
            self._head = replacement
            return True


_HEAD_STORES: dict[str, _MemoryHeadStore] = {}


def _head_anchor(path) -> MonotonicHeadAnchor:
    key = str(path.resolve())
    store = _HEAD_STORES.setdefault(key, _MemoryHeadStore())
    return MonotonicHeadAnchor(store.read, store.compare_and_swap)


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


def test_monotonic_head_anchor_is_exact_and_fail_closed():
    initial = MediationHead(1, 0, ZERO_HASH, 0, "1" * 64)
    replacement = MediationHead(1, 1, "2" * 64, 1, "3" * 64)
    store = _MemoryHeadStore()
    anchor = MonotonicHeadAnchor(store.read, store.compare_and_swap)

    assert anchor.read() is None
    assert anchor.advance(None, initial)
    assert anchor.read() == initial
    assert not anchor.advance(None, replacement)
    assert anchor.advance(initial, replacement)
    assert anchor.read() == replacement
    assert MonotonicHeadAnchor(lambda: object(), lambda _old, _new: True).read() is None
    assert not MonotonicHeadAnchor(None, None).advance(None, replacement)


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


def _queue(tmp_path, *, mode="enforce", signer=None):
    path = tmp_path / "mediation.db"
    return TaskQueue(
        db_path=str(path),
        mediation_mode=mode,
        mediation_signer=signer or _signer(),
        mediation_head_anchor=_head_anchor(path),
        mediation_classifier=lambda kind: kind == "filesystem.write",
        mediation_scope="global",
        mediation_policy_revision="policy-17",
        mediation_clock_ms=lambda: NOW_MS,
    ).initialize()


def _enqueue_mediated(queue: TaskQueue, *, receipt=None, payload=None) -> int:
    return queue.enqueue_mediated(
        "ultron",
        "filesystem.write",
        "Write bounded report",
        payload or {"path": "reports/summary.json", "body": "caf\u00e9"},
        receipt=receipt or _receipt(),
        autonomy_level="ask",
        origin="generated",
    )


def test_enforce_raw_classified_enqueue_refuses_and_persists_real_event(tmp_path):
    queue = _queue(tmp_path)

    with pytest.raises(TaskQueueError, match="requires mediation"):
        queue.enqueue(
            "ultron",
            "filesystem.write",
            "Write bounded report",
            {"path": "reports/summary.json"},
        )

    assert queue.list() == []
    stats = queue.verified_mediation_stats()
    assert stats["valid"] is True
    assert stats["refused_unmediated"] == 1
    assert stats["governed"] == 0


def test_nonclassified_raw_enqueue_remains_compatible_under_enforce(tmp_path):
    queue = _queue(tmp_path)

    task_id = queue.enqueue("jarvis", "draft_email", "Draft reply", {"to": "x"})

    assert queue.get(task_id).status == "proposed"
    assert queue.get(task_id).mediation_enqueue_id is None


def test_mediated_enqueue_atomically_persists_exact_receipt_and_restart_state(tmp_path):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    task = queue.get(task_id)

    assert task.mediation_enqueue_id == ENQUEUE_ID
    assert task.mediation_enqueue_revision == 1
    assert task.mediation_receipt["receipt_id"] == RECEIPT_ID
    assert len(task.mediation_task_sha256) == 64
    assert queue.verified_mediation_stats() == {
        "valid": True,
        "authorized_enqueue": 1,
        "governed": 0,
        "refused_unmediated": 0,
        "ungoverned_detected": 0,
    }

    queue.close()
    reopened = _queue(tmp_path)
    assert reopened.get(task_id).mediation_receipt["signature"] == _receipt().signature
    assert reopened.verified_mediation_stats()["authorized_enqueue"] == 1


def test_mediated_enqueue_rejects_replay_and_rolls_back_on_event_failure(tmp_path):
    queue = _queue(tmp_path)
    _enqueue_mediated(queue)
    with pytest.raises(TaskQueueError, match="invalid mediation receipt"):
        _enqueue_mediated(queue)
    assert len(queue.list()) == 1

    other_path = tmp_path / "other"
    other_path.mkdir()
    other = _queue(other_path)
    other._conn.execute(
        """CREATE TRIGGER deny_mediation_events BEFORE INSERT ON task_mediation_events
           BEGIN SELECT RAISE(ABORT, 'evidence unavailable'); END"""
    )
    with pytest.raises(TaskQueueError, match="persist mediation evidence"):
        _enqueue_mediated(other)
    assert other.list() == []


def test_claim_is_compare_and_set_and_payload_tamper_quarantines(tmp_path):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    execution_id = "16cb1ba3-b0c3-4200-9a7c-548472343049"

    claimed = queue.claim_mediated(task_id, execution_id=execution_id)

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.mediation_execution_id == execution_id
    assert queue.claim_mediated(task_id, execution_id=execution_id) is None
    assert queue.verified_mediation_stats()["governed"] == 1

    second_id = _enqueue_mediated(
        queue,
        receipt=_receipt(
            receipt_id="ea4d1520-a888-4eed-864f-7987fb540253",
            expectation=_expectation(enqueue_id="f55b8111-2ca4-4dc7-8d43-91fe674c7b5c"),
        ),
    )
    queue.transition(second_id, TaskStatus.APPROVED)
    queue.update_payload(second_id, {"path": "attacker", "body": "changed"})
    assert (
        queue.claim_mediated(
            second_id,
            execution_id="f02d92f4-bf11-4dba-a583-97717764f0cb",
        )
        is None
    )
    assert queue.get(second_id).status == "quarantined"
    assert queue.verified_mediation_stats()["ungoverned_detected"] == 1


@pytest.mark.parametrize(
    "column,value",
    [
        ("risk_tier", 0),
        ("mediation_receipt", "{malformed"),
        ("mediation_task_sha256", "0" * 64),
    ],
)
def test_claim_quarantines_persisted_binding_corruption(tmp_path, column, value):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    queue._conn.execute(f"UPDATE tasks SET {column}=? WHERE id=?", (value, task_id))
    queue._conn.commit()

    assert (
        queue.claim_mediated(
            task_id,
            execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049",
        )
        is None
    )
    assert queue.get(task_id).status == "quarantined"
    assert queue.verified_mediation_stats()["ungoverned_detected"] == 1


def test_enforce_startup_quarantines_legacy_classified_rows_and_hold_never_claims(tmp_path):
    path = str(tmp_path / "mediation.db")
    off = TaskQueue(db_path=path).initialize()
    legacy_id = off.enqueue("ultron", "filesystem.write", "Legacy write", {"path": "legacy"})
    off.transition(legacy_id, TaskStatus.APPROVED)
    off.close()

    held = TaskQueue(
        db_path=path,
        mediation_mode="hold",
        mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(tmp_path / "mediation.db"),
        mediation_classifier=lambda kind: kind == "filesystem.write",
        mediation_scope="global",
        mediation_policy_revision="policy-17",
        mediation_clock_ms=lambda: NOW_MS,
    ).initialize()

    assert held.get(legacy_id).status == "quarantined"
    assert held.verified_mediation_stats()["ungoverned_detected"] == 1
    with pytest.raises(TaskQueueError, match="mediation hold"):
        held.enqueue("ultron", "filesystem.write", "Held write", {})


def test_corrupt_event_chain_never_contributes_verified_counters(tmp_path):
    queue = _queue(tmp_path)
    _enqueue_mediated(queue)
    queue._conn.execute(
        "UPDATE task_mediation_events SET event_hash=? WHERE sequence=1",
        ("f" * 64,),
    )
    queue._conn.commit()

    assert queue.verified_mediation_stats() == {
        "valid": False,
        "authorized_enqueue": 0,
        "governed": 0,
        "refused_unmediated": 0,
        "ungoverned_detected": 0,
    }


def test_concurrent_double_claim_produces_one_execution_event(tmp_path):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    execution_ids = (
        "16cb1ba3-b0c3-4200-9a7c-548472343049",
        "f02d92f4-bf11-4dba-a583-97717764f0cb",
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda execution_id: queue.claim_mediated(task_id, execution_id=execution_id),
                execution_ids,
            )
        )

    assert sum(result is not None for result in results) == 1
    assert queue.verified_mediation_stats()["governed"] == 1


def test_planted_classified_row_is_detected_and_quarantined(tmp_path):
    queue = _queue(tmp_path)
    now = "2026-08-14T00:00:00+00:00"
    queue._conn.execute(
        """INSERT INTO tasks
               (agent, kind, title, payload, risk_tier, status, autonomy_level,
                attention_mode, origin, attempts, pushed, created_at, updated_at)
           VALUES ('ultron', 'filesystem.write', 'Planted', '{}', 2, 'approved',
                   'ask', 'interrupt', 'generated', 0, 0, ?, ?)""",
        (now, now),
    )
    queue._conn.commit()
    task_id = queue._conn.execute("SELECT MAX(id) FROM tasks").fetchone()[0]

    assert queue.scan_unmediated_tasks() == [task_id]
    assert queue.get(task_id).status == "quarantined"
    assert queue.verified_mediation_stats()["ungoverned_detected"] == 1


def test_classifier_or_signer_failure_refuses_without_creating_authority(tmp_path):
    classifier_path = tmp_path / "classifier.db"
    broken_classifier = TaskQueue(
        db_path=str(classifier_path),
        mediation_mode="enforce",
        mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(classifier_path),
        mediation_classifier=lambda _kind: (_ for _ in ()).throw(RuntimeError("down")),
    ).initialize()
    with pytest.raises(TaskQueueError, match="requires mediation"):
        broken_classifier.enqueue("jarvis", "draft_email", "Unknown", {})
    assert broken_classifier.list() == []

    signer_path = tmp_path / "signer"
    signer_path.mkdir()
    broken_signer = _queue(
        signer_path,
        signer=DetachedHMACSigner(lambda _payload: "invalid"),
    )
    with pytest.raises(TaskQueueError, match="requires mediation"):
        broken_signer.enqueue("ultron", "filesystem.write", "Unsigned", {})
    assert broken_signer.list() == []
    assert broken_signer.verified_mediation_stats()["governed"] == 0
    assert broken_signer.verified_mediation_stats()["valid"] is False


@pytest.mark.parametrize(
    ("scope", "policy_revision"),
    [("node:laptop", "policy-17"), ("global", "policy-18")],
)
def test_restart_rejects_live_scope_or_policy_revision_drift(tmp_path, scope, policy_revision):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    queue.close()

    reopened = TaskQueue(
        db_path=str(tmp_path / "mediation.db"),
        mediation_mode="enforce",
        mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(tmp_path / "mediation.db"),
        mediation_classifier=lambda kind: kind == "filesystem.write",
        mediation_scope=scope,
        mediation_policy_revision=policy_revision,
        mediation_clock_ms=lambda: NOW_MS,
    ).initialize()

    assert reopened.get(task_id).status == "quarantined"
    assert (
        reopened.claim_mediated(task_id, execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049")
        is None
    )


def test_unknown_registry_classification_is_fail_closed(tmp_path):
    path = tmp_path / "unknown.db"
    queue = TaskQueue(
        db_path=str(path),
        mediation_mode="enforce",
        mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(path),
        mediation_classifier=lambda _kind: None,
    ).initialize()

    with pytest.raises(TaskQueueError, match="requires mediation"):
        queue.enqueue("jarvis", "unknown.effect", "Unknown", {})
    assert queue.list() == []
    assert queue.verified_mediation_stats()["refused_unmediated"] == 1


@pytest.mark.parametrize("delete_where", ["outcome='governed'", "1=1"])
def test_event_tail_or_total_deletion_invalidates_counters(tmp_path, delete_where):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    assert queue.claim_mediated(task_id, execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049")
    queue._conn.execute(f"DELETE FROM task_mediation_events WHERE {delete_where}")
    queue._conn.commit()

    stats = queue.verified_mediation_stats()
    assert stats["valid"] is False
    assert stats["governed"] == 0


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("signature", "0" * 64),
        ("event_count", 99),
        ("last_event_hash", "f" * 64),
        ("version", 2),
    ],
)
def test_corrupt_signed_head_blocks_claim_without_self_healing(tmp_path, column, value):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    queue._conn.execute(f"UPDATE task_mediation_state SET {column}=? WHERE id=1", (value,))
    queue._conn.commit()

    assert queue.verified_mediation_stats()["valid"] is False
    assert (
        queue.claim_mediated(
            task_id,
            execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049",
        )
        is None
    )
    assert queue.get(task_id).status == "approved"
    assert queue.verified_mediation_stats()["valid"] is False


def test_global_task_event_mismatch_blocks_other_claims(tmp_path):
    queue = _queue(tmp_path)
    first_id = _enqueue_mediated(queue)
    second_id = _enqueue_mediated(
        queue,
        receipt=_receipt(
            receipt_id="ea4d1520-a888-4eed-864f-7987fb540253",
            expectation=_expectation(enqueue_id=REFUSED_ENQUEUE_ID),
        ),
    )
    queue.transition(second_id, TaskStatus.APPROVED)
    queue._conn.execute("DELETE FROM tasks WHERE id=?", (first_id,))
    queue._conn.commit()

    assert queue.verified_mediation_stats()["valid"] is False
    assert (
        queue.claim_mediated(
            second_id,
            execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049",
        )
        is None
    )
    assert queue.get(second_id).status == "approved"


def test_corrupt_signed_head_blocks_refusal_append_without_self_healing(tmp_path):
    queue = _queue(tmp_path)
    queue._conn.execute("UPDATE task_mediation_state SET signature='corrupt' WHERE id=1")
    queue._conn.commit()

    with pytest.raises(TaskQueueError, match="requires mediation"):
        queue.enqueue("ultron", "filesystem.write", "Unsigned", {})

    assert queue.verified_mediation_stats()["valid"] is False
    assert queue.verified_mediation_stats()["refused_unmediated"] == 0


def test_valid_signed_database_prefix_replay_cannot_reclaim_task(tmp_path):
    queue = _queue(tmp_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    saved_state = dict(
        queue._conn.execute("SELECT * FROM task_mediation_state WHERE id=1").fetchone()
    )

    assert queue.claim_mediated(
        task_id,
        execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049",
    )
    queue._conn.execute(
        "UPDATE tasks SET status='approved', mediation_execution_id=NULL WHERE id=?",
        (task_id,),
    )
    queue._conn.execute("DELETE FROM task_mediation_events WHERE outcome='governed'")
    queue._conn.execute(
        """UPDATE task_mediation_state
              SET version=?, last_sequence=?, last_event_hash=?, event_count=?,
                  integrity_broken=?, signature=?
            WHERE id=1""",
        (
            saved_state["version"],
            saved_state["last_sequence"],
            saved_state["last_event_hash"],
            saved_state["event_count"],
            saved_state["integrity_broken"],
            saved_state["signature"],
        ),
    )
    queue._conn.commit()

    assert queue.verified_mediation_stats()["valid"] is False
    assert (
        queue.claim_mediated(
            task_id,
            execution_id="f02d92f4-bf11-4dba-a583-97717764f0cb",
        )
        is None
    )
    assert queue.get(task_id).status == "approved"


def test_total_database_prefix_rollback_cannot_restore_append_authority(tmp_path):
    queue = _queue(tmp_path)
    empty_state = dict(
        queue._conn.execute("SELECT * FROM task_mediation_state WHERE id=1").fetchone()
    )
    _enqueue_mediated(queue)
    queue._conn.execute("DELETE FROM tasks")
    queue._conn.execute("DELETE FROM task_mediation_events")
    queue._conn.execute(
        """UPDATE task_mediation_state
              SET version=?, last_sequence=?, last_event_hash=?, event_count=?,
                  integrity_broken=?, signature=?
            WHERE id=1""",
        (
            empty_state["version"],
            empty_state["last_sequence"],
            empty_state["last_event_hash"],
            empty_state["event_count"],
            empty_state["integrity_broken"],
            empty_state["signature"],
        ),
    )
    queue._conn.commit()

    assert queue.verified_mediation_stats()["valid"] is False
    with pytest.raises(TaskQueueError, match="mediation"):
        queue.enqueue("ultron", "filesystem.write", "Replay", {})
    assert queue.verified_mediation_stats()["valid"] is False


def test_enforce_mode_without_external_latest_head_anchor_is_fail_closed(tmp_path):
    queue = TaskQueue(
        db_path=str(tmp_path / "unanchored.db"),
        mediation_mode="enforce",
        mediation_signer=_signer(),
        mediation_classifier=lambda kind: kind == "filesystem.write",
        mediation_scope="global",
        mediation_policy_revision="policy-17",
        mediation_clock_ms=lambda: NOW_MS,
    ).initialize()

    assert queue.verified_mediation_stats()["valid"] is False
    with pytest.raises(TaskQueueError, match="mediation"):
        _enqueue_mediated(queue)


def test_latest_head_cas_failure_rolls_back_task_and_event(tmp_path):
    queue = _queue(tmp_path)
    anchored = queue._mediation_head_anchor.read()
    queue._mediation_head_anchor = MonotonicHeadAnchor(
        lambda: anchored,
        lambda _expected, _replacement: False,
    )

    with pytest.raises(TaskQueueError, match="latest-head anchor"):
        _enqueue_mediated(queue)

    assert queue.list() == []
    assert queue.mediation_events() == []
    assert queue.verified_mediation_stats()["valid"] is True


def test_concurrent_new_and_legacy_initialization_is_lock_safe(tmp_path):
    for name, legacy in (("new.db", False), ("legacy.db", True)):
        path = tmp_path / name
        if legacy:
            seed = TaskQueue(str(path)).initialize()
            seed.close()

        def initialize_once(_index, db_path=path):
            queue = TaskQueue(str(db_path)).initialize()
            queue.close()
            return True

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert all(pool.map(initialize_once, range(8)))


def test_cross_process_legacy_migration_is_serialized(tmp_path):
    path = tmp_path / "legacy-process.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE tasks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               agent TEXT NOT NULL,
               kind TEXT NOT NULL,
               title TEXT NOT NULL,
               payload TEXT NOT NULL DEFAULT '{}',
               risk_tier INTEGER NOT NULL DEFAULT 3,
               status TEXT NOT NULL DEFAULT 'proposed',
               autonomy_level TEXT NOT NULL DEFAULT 'ask',
               origin TEXT NOT NULL DEFAULT 'generated',
               attempts INTEGER NOT NULL DEFAULT 0,
               result TEXT,
               decided_by TEXT,
               decision TEXT,
               pushed INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )"""
    )
    connection.commit()
    connection.close()
    program = (
        "from agents.core.autonomy.queue import TaskQueue; "
        f"q=TaskQueue({str(path)!r}).initialize(); q.close()"
    )

    processes = [
        subprocess.Popen(
            [sys.executable, "-c", program],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    results = [process.communicate(timeout=45) + (process.returncode,) for process in processes]

    assert results == [("", "", 0)] * 8
