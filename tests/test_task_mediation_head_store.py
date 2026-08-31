"""Durable latest-head store for B7 task mediation evidence (DRA-59).

B7 shipped `MonotonicHeadAnchor` — a fail-closed adapter for a trusted
latest-head CAS store held OUTSIDE the rollbackable queue database — but no
production store behind it, and no way to select the mode without editing
source. Enforce/hold were therefore unreachable: the default
`MonotonicHeadAnchor(None, None)` reads `None`, so `initialize()` marks
integrity broken. These tests pin the store, the mode resolver and the
production wiring; the mode stays default-off.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.mediation import (  # noqa: E402
    ZERO_HASH,
    DetachedHMACSigner,
    MediationHead,
    ReceiptExpectation,
    issue_receipt,
)
from agents.core.autonomy.mediation_head_store import (  # noqa: E402
    FileMediationHeadStore,
    make_task_mediation_anchor,
    resolve_task_mediation_mode,
)
from agents.core.autonomy.queue import (  # noqa: E402
    TaskQueue,
    TaskQueueError,
    TaskStatus,
)

KEY = b"owner-held-test-key-that-is-long-enough"
NOW_MS = 1_786_662_000_000
RECEIPT_ID = "59cf2075-3397-43d7-8035-185a4ef4c1e7"
ENQUEUE_ID = "c01a535d-7f1d-474c-a352-f06af437314a"


def _mac(payload: bytes) -> str:
    return hmac.new(KEY, payload, hashlib.sha256).hexdigest()


def _signer() -> DetachedHMACSigner:
    return DetachedHMACSigner(_mac)


def _receipt():
    receipt = issue_receipt(
        _signer(),
        receipt_id=RECEIPT_ID,
        expectation=ReceiptExpectation(
            enqueue_id=ENQUEUE_ID,
            agent="ultron",
            kind="filesystem.write",
            title="Write bounded report",
            origin="generated",
            scope="global",
            payload={"path": "reports/summary.json"},
            effective_tier=2,
            policy_revision="policy-17",
            enqueue_revision=1,
        ),
        verdict="queue",
        tier=2,
        reason="owner approval required",
        issued_at_ms=NOW_MS,
        expires_at_ms=NOW_MS + 60_000,
    )
    assert receipt is not None
    return receipt


def _queue(db_path: Path, head_path: Path, *, mode: str = "enforce") -> TaskQueue:
    return TaskQueue(
        db_path=str(db_path),
        mediation_mode=mode,
        mediation_signer=_signer(),
        mediation_head_anchor=make_task_mediation_anchor(head_path),
        mediation_classifier=lambda kind: kind == "filesystem.write",
        mediation_scope="global",
        mediation_policy_revision="policy-17",
        mediation_clock_ms=lambda: NOW_MS,
    ).initialize()


def _enqueue_mediated(queue: TaskQueue) -> int:
    return queue.enqueue_mediated(
        "ultron",
        "filesystem.write",
        "Write bounded report",
        {"path": "reports/summary.json"},
        receipt=_receipt(),
        autonomy_level="ask",
        origin="generated",
    )


# ── mode resolution ──────────────────────────────────────────────────────────

def test_production_default_stays_off(monkeypatch):
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    assert resolve_task_mediation_mode() == "off"


@pytest.mark.parametrize("mode", ["off", "hold", "enforce", " ENFORCE "])
def test_known_modes_are_honored(monkeypatch, mode):
    monkeypatch.setenv("JARVIS_TASK_MEDIATION", mode)
    assert resolve_task_mediation_mode() == mode.strip().lower()


def test_unknown_mode_falls_back_to_off_without_raising(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_TASK_MEDIATION", "enfroce")
    resolved = resolve_task_mediation_mode()
    assert resolved == "off"
    # TaskQueue raises ValueError on an unknown mode, so a config typo must not
    # reach it.
    TaskQueue(str(tmp_path / "typo.db"), mediation_mode=resolved).initialize().close()


# ── the store itself ─────────────────────────────────────────────────────────

def _head(sequence: int, digest: str = "a" * 64) -> MediationHead:
    return MediationHead(
        version=1,
        last_sequence=sequence,
        last_event_hash=digest if sequence else ZERO_HASH,
        event_count=sequence,
        signature="b" * 64,
    )


def test_compare_and_swap_rejects_stale_and_non_monotonic(tmp_path):
    store = FileMediationHeadStore(tmp_path / "head.json")
    assert store.read() is None

    # Bootstrap must start at sequence 0.
    assert store.compare_and_swap(None, _head(3)) is False
    assert store.compare_and_swap(None, _head(0)) is True
    assert store.read() == _head(0)

    # Wrong expected value → refused.
    assert store.compare_and_swap(_head(2), _head(1)) is False
    # Correct expected, forward move → accepted.
    assert store.compare_and_swap(_head(0), _head(1)) is True
    # Same or backwards sequence → refused even with the right expected value.
    assert store.compare_and_swap(_head(1), _head(1, "c" * 64)) is False
    assert store.compare_and_swap(_head(1), _head(0)) is False
    assert store.read() == _head(1)


def test_corrupt_head_file_reads_as_unavailable(tmp_path):
    path = tmp_path / "head.json"
    store = FileMediationHeadStore(path)
    assert store.compare_and_swap(None, _head(0)) is True
    path.write_text('{"version": 1, "last_sequence":', encoding="utf-8")
    assert store.read() is None
    # A structurally valid but semantically invalid head is rejected too.
    path.write_text(json.dumps({"version": 9, "last_sequence": 1, "last_event_hash": "a" * 64,
                                "event_count": 1, "signature": "b" * 64}), encoding="utf-8")
    assert store.read() is None


# ── queue integration ────────────────────────────────────────────────────────

def test_enforce_bootstraps_against_the_durable_anchor(tmp_path):
    head_path = tmp_path / "head.json"
    queue = _queue(tmp_path / "mediation.db", head_path)
    assert queue.verified_mediation_stats()["valid"] is True
    assert head_path.exists()
    stored = FileMediationHeadStore(head_path).read()
    assert stored is not None and stored.last_sequence == 0
    queue.close()


def test_evidence_survives_restart_on_the_file_anchor(tmp_path):
    db_path = tmp_path / "mediation.db"
    head_path = tmp_path / "head.json"
    queue = _queue(db_path, head_path)
    task_id = _enqueue_mediated(queue)
    queue.transition(task_id, TaskStatus.APPROVED)
    assert queue.claim_mediated(
        task_id, execution_id="16cb1ba3-b0c3-4200-9a7c-548472343049"
    ) is not None
    assert queue.verified_mediation_stats()["governed"] == 1
    queue.close()

    reopened = _queue(db_path, head_path)
    stats = reopened.verified_mediation_stats()
    assert stats["valid"] is True
    assert stats["governed"] == 1
    reopened.close()


def test_signed_prefix_rollback_is_denied(tmp_path):
    db_path = tmp_path / "mediation.db"
    head_path = tmp_path / "head.json"
    queue = _queue(db_path, head_path)
    _enqueue_mediated(queue)
    first_head = FileMediationHeadStore(head_path).read()
    queue.close()
    stale_head = tmp_path / "stale-head.json"
    shutil.copy2(head_path, stale_head)

    # A refused unmediated enqueue is itself a recorded event, so the head moves.
    queue = _queue(db_path, head_path)
    with pytest.raises(TaskQueueError, match="requires mediation"):
        queue.enqueue("ultron", "filesystem.write", "Sneak past", {"path": "x"})
    later_head = FileMediationHeadStore(head_path).read()
    assert queue.verified_mediation_stats()["valid"] is True
    queue.close()
    assert first_head is not None and later_head is not None
    assert later_head.last_sequence > first_head.last_sequence

    # Roll the external head back to the earlier state, leaving the DB untouched:
    # the queue must refuse to treat its own (newer) evidence as authoritative.
    shutil.copy2(stale_head, head_path)
    reopened = _queue(db_path, head_path)
    assert reopened.verified_mediation_stats()["valid"] is False
    reopened.close()


# ── production wiring ────────────────────────────────────────────────────────

def test_orchestrator_wires_the_durable_anchor_and_ships_off(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator(JarvisConfig())
    queue = orch.autonomy_queue
    assert queue.mediation_mode == "off"          # dark by default
    anchor = queue._mediation_head_anchor
    assert callable(anchor._read)                 # a real store, not the null anchor
    assert callable(anchor._compare_and_swap)
