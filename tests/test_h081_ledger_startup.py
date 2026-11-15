"""Concurrent ledger startup tolerates only transient WAL lock contention."""

from __future__ import annotations

import sqlite3

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.delivery_ledger import ReliabilityStore


class _StartupConnection:
    def __init__(self, real, *, wal_failures=0, error=None):
        self.real = real
        self.wal_failures = wal_failures
        self.error = error
        self.wal_attempts = 0
        self.closed = False

    def execute(self, sql, *args):
        if sql == "PRAGMA journal_mode=WAL":
            self.wal_attempts += 1
            if self.wal_failures:
                self.wal_failures -= 1
                if self.error is not None:
                    raise self.error
                locked = sqlite3.OperationalError("database is locked")
                locked.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise locked
        return self.real.execute(sql, *args)

    def __enter__(self):
        self.real.__enter__()
        return self

    def __exit__(self, *args):
        return self.real.__exit__(*args)

    def close(self):
        self.closed = True
        self.real.close()


def _inject_connection(monkeypatch, *, wal_failures, error=None):
    connect = sqlite3.connect
    made = []

    def patched(*args, **kwargs):
        wrapped = _StartupConnection(connect(*args, **kwargs),
                                     wal_failures=wal_failures, error=error)
        made.append(wrapped)
        return wrapped

    monkeypatch.setattr(delivery_ledger.sqlite3, "connect", patched)
    return made


def test_transient_wal_lock_retries_and_keeps_claims_functional(tmp_path, monkeypatch):
    made = _inject_connection(monkeypatch, wal_failures=1)
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    try:
        assert made[0].wal_attempts == 2
        assert store._conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert store._conn.execute("PRAGMA busy_timeout").fetchone() == (10000,)
        claim = store.open_delivery("telegram", "123", "notice", key="startup-lock")
        assert claim.send
        assert not store.open_delivery("telegram", "123", "notice", key="startup-lock").send
    finally:
        store.close()


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
                                  sqlite3.SQLITE_BUSY | 0x100])
def test_only_sqlite_lock_codes_get_transient_retry(tmp_path, monkeypatch, code):
    locked = sqlite3.OperationalError("database is locked")
    locked.sqlite_errorcode = code
    made = _inject_connection(monkeypatch, wal_failures=1, error=locked)
    store = ReliabilityStore(tmp_path / "delivery.sqlite")
    try:
        assert made[0].wal_attempts == 2
    finally:
        store.close()


def test_persistent_wal_lock_has_bounded_attempts_and_closes_connection(tmp_path, monkeypatch):
    made = _inject_connection(monkeypatch, wal_failures=100)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        ReliabilityStore(tmp_path / "delivery.sqlite")
    assert 1 < made[0].wal_attempts <= 5
    assert made[0].closed


@pytest.mark.parametrize("error", [
    sqlite3.OperationalError("attempt to write a readonly database"),
    sqlite3.DatabaseError("database disk image is malformed"),
    sqlite3.OperationalError("database is locked"),  # misleading text with a nonlock code
])
def test_nonlock_wal_errors_are_not_retried_and_connection_closes(tmp_path, monkeypatch, error):
    if str(error) == "database is locked":
        error.sqlite_errorcode = sqlite3.SQLITE_IOERR
    made = _inject_connection(monkeypatch, wal_failures=100, error=error)
    with pytest.raises(type(error), match=str(error)):
        ReliabilityStore(tmp_path / "delivery.sqlite")
    assert made[0].wal_attempts == 1
    assert made[0].closed


def test_schema_initialization_error_closes_connection(tmp_path, monkeypatch):
    connect = sqlite3.connect
    made = []

    class SchemaFailure(_StartupConnection):
        def execute(self, sql, *args):
            if sql.startswith("CREATE TABLE"):
                raise sqlite3.DatabaseError("schema unavailable")
            return super().execute(sql, *args)

    def patched(*args, **kwargs):
        wrapped = SchemaFailure(connect(*args, **kwargs))
        made.append(wrapped)
        return wrapped

    monkeypatch.setattr(delivery_ledger.sqlite3, "connect", patched)
    with pytest.raises(sqlite3.DatabaseError, match="schema unavailable"):
        ReliabilityStore(tmp_path / "delivery.sqlite")
    assert made[0].closed
