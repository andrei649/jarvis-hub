"""Cross-process keyed delivery claims and their durable retry evidence."""

from __future__ import annotations

import multiprocessing
import time

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.delivery_ledger import ReliabilityStore


def _claim_in_process(path: str, ready, start, results) -> None:
    store = ReliabilityStore(path)
    original = store._insert

    def delayed_insert(channel, target, key, state, attempt, error, text, now):
        if state == delivery_ledger.STATE_PENDING:
            time.sleep(0.3)
        return original(channel, target, key, state, attempt, error, text, now)

    store._insert = delayed_insert
    ready.put(True)
    start.wait(10)
    try:
        claim = store.open_delivery("telegram", "123", "notice", key="restart:42")
        results.put((claim.send, None))
    except Exception as exc:  # diagnostic for the race, never a successful claim
        results.put((False, type(exc).__name__))
    finally:
        store.close()


def test_two_spawned_processes_can_claim_one_key_only_once(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    path = str(tmp_path / "delivery.sqlite")
    workers = [ctx.Process(target=_claim_in_process, args=(path, ready, start, results))
               for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        assert [ready.get(timeout=10) for _ in workers] == [True, True]
        start.set()
        received = [results.get(timeout=10) for _ in workers]
        assert sorted(received) == [(False, None), (True, None)]
    finally:
        start.set()
        for worker in workers:
            worker.join(timeout=10)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
    assert all(worker.exitcode == 0 for worker in workers)


@pytest.mark.parametrize("key", ["", "\n", "é", "k\x00x", "x" * 201, 12])
def test_explicit_invalid_keys_never_become_unkeyed_claims(tmp_path, key):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    assert delivery_ledger.valid_delivery_key(None)
    assert delivery_ledger.valid_delivery_key("k:/ @.-_" * 20)
    assert not delivery_ledger.valid_delivery_key(key)
    with pytest.raises(ValueError):
        store.open_delivery("telegram", "123", "body", key=key)
    assert store.stats()["by_state"]["pending"] == 0


def test_checked_attempt_requires_owned_pending_row(tmp_path):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    claim = store.open_delivery("telegram", "123", "body", key="k")
    assert claim.attempting_checked()
    assert not claim.attempting_checked()
    assert store.get(claim.id)["state"] == "attempting"
    deleted = store.open_delivery("telegram", "123", "body", key="other")
    with store._conn:
        store._conn.execute("DELETE FROM deliveries WHERE id=?", (deleted.id,))
    assert not deleted.attempting_checked()


def test_recovered_pending_cannot_be_attempted(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    claim = store.open_delivery("telegram", "123", "body", key="k")
    monkeypatch.setattr(delivery_ledger, "_BOOT", "next-boot")
    assert store.recover(alive=lambda _: False) == {"failed": 1, "unknown": 0}
    assert not claim.attempting_checked()
    assert store.open_delivery("telegram", "123", "body", key="k").send


def test_recovery_does_not_downgrade_a_claim_after_a_stale_read(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    claim = store.open_delivery("telegram", "123", "body", key="k")
    original = store._conn
    old_boot = delivery_ledger._BOOT
    # A second connection acts as the claimant while recovery pauses after its SELECT.
    other = ReliabilityStore(store.path)

    class PausedConnection:
        def execute(self, sql, params=()):
            cursor = original.execute(sql, params)
            if sql.startswith("SELECT id, state, pid, boot, updated FROM deliveries"):
                rows = cursor.fetchall()
                monkeypatch.setattr(delivery_ledger, "_BOOT", old_boot)
                assert other._set_pending_attempting(claim.id)
                monkeypatch.setattr(delivery_ledger, "_BOOT", "next-boot")

                class ReadRows:
                    def fetchall(self):
                        return rows

                return ReadRows()
            return cursor

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return original.__exit__(exc_type, exc, tb)

    # Store connection stubs are not needed if the recovery implementation offers a
    # direct read/compare seam; this wrapper intentionally exercises its SQL ordering.
    monkeypatch.setattr(delivery_ledger, "_BOOT", "next-boot")
    monkeypatch.setattr(store, "_conn", PausedConnection())
    try:
        assert store.recover(alive=lambda _: False) == {"failed": 0, "unknown": 0}
        assert other.get(claim.id)["state"] == "attempting"
    finally:
        other.close()


def test_recent_keyed_evidence_survives_pruning_and_quota_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery_ledger, "MAX_PROTECTED_KEYED_ROWS", 2)
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    first = store.open_delivery("telegram", "123", "one", key="key-1")
    first.attempting_checked()
    first.finished(True)
    second = store.open_delivery("telegram", "123", "two", key="key-2")
    second.attempting_checked()
    second.finished(False)
    for _index in range(delivery_ledger.MAX_ROWS + 5):
        row = store.open_delivery("telegram", "123", "noise")
        row.finished(False)
    assert store.open_delivery("telegram", "123", "one", key="key-1").send is False
    with pytest.raises(delivery_ledger.KeyedDeliveryCapacity):
        store.open_delivery("telegram", "123", "three", key="key-3")
    with pytest.raises(delivery_ledger.KeyedDeliveryCapacity):
        store.open_delivery("telegram", "123", "retry", key="key-2")
    assert store.get(first.id)["state"] == "sent"
    assert store.get(second.id)["state"] == "failed"


def test_failed_retry_and_unknown_remain_distinct(tmp_path):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    first = store.open_delivery("telegram", "123", "body", key="retry")
    assert first.attempting_checked()
    first.finished(False)
    retry = store.open_delivery("telegram", "123", "body", key="retry")
    assert retry.send and retry.attempting_checked()
    retry.raised(TimeoutError())
    assert not store.open_delivery("telegram", "123", "body", key="retry").send


def test_failed_insert_rolls_back_writer_claim(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    original = store._insert

    def broken(*args, **kwargs):
        raise OSError("disk refused")

    monkeypatch.setattr(store, "_insert", broken)
    with pytest.raises(OSError):
        store.open_delivery("telegram", "123", "body", key="k")
    monkeypatch.setattr(store, "_insert", original)
    assert store.open_delivery("telegram", "123", "body", key="k").send


def test_keyed_protection_expires_at_the_documented_window(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery_ledger, "MAX_PROTECTED_KEYED_ROWS", 1)
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    started = time.time()
    first = store.open_delivery("telegram", "123", "body", key="k1", now=started)
    assert first.attempting_checked()
    first.finished(True)
    with pytest.raises(delivery_ledger.KeyedDeliveryCapacity):
        store.open_delivery("telegram", "123", "body", key="k2", now=started + 1)
    assert store.open_delivery("telegram", "123", "body", key="k2",
                               now=started + delivery_ledger.IDEMPOTENCY_WINDOW_S + 1).send


def test_recent_failed_history_survives_pruning_for_retry_limit(tmp_path):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    for attempt in (1, 2):
        row = store.open_delivery("telegram", "123", "body", key="retry")
        assert row.send and store.get(row.id)["attempt"] == attempt
        assert row.attempting_checked()
        row.finished(False)
    for _index in range(delivery_ledger.MAX_ROWS + 5):
        noise = store.open_delivery("telegram", "123", "noise")
        noise.finished(False)
    third = store.open_delivery("telegram", "123", "body", key="retry")
    assert third.send and store.get(third.id)["attempt"] == 3
    assert third.attempting_checked()
    third.finished(False)
    exhausted = store.open_delivery("telegram", "123", "body", key="retry")
    assert not exhausted.send and store.get(exhausted.id)["error"] == "attempts_exhausted"


def test_skipped_diagnostics_do_not_spend_a_failed_retry(tmp_path):
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    first = store.open_delivery("telegram", "123", "body", key="retry")
    assert first.attempting_checked()
    first.finished(False)
    assert store.mark_dead("telegram", "123", "gone")
    for _index in range(5):
        skipped = store.open_delivery("telegram", "123", "body", key="retry")
        assert not skipped.send and skipped.dead
    assert store.clear_dead("telegram", "123")
    second = store.open_delivery("telegram", "123", "body", key="retry")
    assert second.send and store.get(second.id)["attempt"] == 2
