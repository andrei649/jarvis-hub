"""H487 owner-consent evidence: durable, scoped, signed, and fail closed."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from dataclasses import replace

import pytest

from agents.core.autonomy.consent_ledger import ConsentCategory, ConsentContext, ConsentLedger
from agents.core.autonomy.mediation import DetachedHMACSigner, MediationHead, MonotonicHeadAnchor

KEY = b"h487-test-owner-held-hmac-key"
TERMINAL = ConsentCategory("terminal.run")
READ = ConsentCategory("filesystem.read")
CONTENT = ConsentCategory("browser.content", permanent=False)
CATEGORIES = (TERMINAL, READ, CONTENT)


def _signer(key: bytes = KEY) -> DetachedHMACSigner:
    return DetachedHMACSigner(lambda payload: hmac.new(key, payload, hashlib.sha256).hexdigest())


def _context(**changes: str) -> ConsentContext:
    return replace(
        ConsentContext(
            principal="owner-1",
            surface="terminal",
            session_id="chat-1",
            session_instance="instance-1",
            registration_key="registered-tool-v1",
            policy_revision="policy-7",
            target_scope="local:/reports",
        ),
        **changes,
    )


def _ledger(conn: sqlite3.Connection, signer: DetachedHMACSigner | None = None) -> ConsentLedger:
    ledger = ConsentLedger(conn, signer if signer is not None else _signer(), categories=CATEGORIES)
    ledger.initialize()
    return ledger


class _HeadStore:
    def __init__(self) -> None:
        self.head: MediationHead | None = None
        self.fail_advance = False

    def anchor(self) -> MonotonicHeadAnchor:
        def advance(expected: MediationHead | None, replacement: MediationHead) -> bool:
            if self.fail_advance or self.head != expected:
                return False
            self.head = replacement
            return True

        return MonotonicHeadAnchor(lambda: self.head, advance)


def _anchored(conn: sqlite3.Connection, store: _HeadStore, signer: DetachedHMACSigner | None = None) -> ConsentLedger:
    ledger = ConsentLedger(conn, signer if signer is not None else _signer(), categories=CATEGORIES, head_anchor=store.anchor())
    ledger.initialize()
    return ledger


def test_anchored_revoke_rejects_old_signed_grant_and_decision_rows(tmp_path):
    store = _HeadStore()
    with sqlite3.connect(tmp_path / "consent.db") as conn:
        ledger = _anchored(conn, store)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        old_grant = conn.execute("SELECT * FROM h487_consent_grants").fetchone()
        old_decision = conn.execute("SELECT * FROM h487_consent_decisions").fetchone()
        assert ledger.revoke(ctx)
        conn.execute("DELETE FROM h487_consent_decisions")
        conn.execute("INSERT INTO h487_consent_decisions VALUES (?, ?, ?)", old_decision)
        conn.execute("INSERT INTO h487_consent_grants VALUES (?, ?, ?, ?, ?, ?)", old_grant)
        assert not ledger.lookup(ctx, (TERMINAL,))
        assert not ledger.grant(ctx, (READ,), choice="always", decision_id="decision-2", decided_by="owner")


def test_anchored_revoke_rejects_whole_database_restore(tmp_path):
    store = _HeadStore()
    path = tmp_path / "consent.db"
    with sqlite3.connect(path) as conn:
        ledger = _anchored(conn, store)
        assert ledger.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
    old_database = path.read_bytes()
    with sqlite3.connect(path) as conn:
        ledger = _anchored(conn, store)
        assert ledger.revoke(_context())
    path.write_bytes(old_database)
    with sqlite3.connect(path) as conn:
        ledger = _anchored(conn, store)
        assert not ledger.lookup(_context(), (TERMINAL,))
        assert not ledger.grant(_context(), (READ,), choice="always", decision_id="decision-2", decided_by="owner")


def test_anchored_empty_bootstrap_reopen_and_constraints(tmp_path):
    store = _HeadStore()
    path = tmp_path / "consent.db"
    with sqlite3.connect(path) as conn:
        ledger = _anchored(conn, store)
        assert store.head is not None and store.head.last_sequence == 0
        assert ledger.grant(_context(), (TERMINAL, READ, CONTENT), choice="always", decision_id="decision-1", decided_by="owner")
        assert store.head.last_sequence == 1
    with sqlite3.connect(path) as conn:
        ledger = _anchored(conn, store)
        later = _context(session_id="later", session_instance="later")
        assert ledger.lookup(later, (TERMINAL, READ))
        assert not ledger.lookup(later, (TERMINAL, CONTENT))
        assert not ledger.lookup(later, (ConsentCategory("unknown"),))


def test_anchored_rejects_row_or_head_substitution(tmp_path):
    store = _HeadStore()
    with sqlite3.connect(tmp_path / "consent.db") as conn:
        ledger = _anchored(conn, store)
        assert ledger.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        conn.execute("UPDATE h487_consent_grants SET signature=?", ("a" * 64,))
        assert not ledger.lookup(_context(), (TERMINAL,))
        conn.rollback()
        assert ledger.lookup(_context(), (TERMINAL,))
        store.head = replace(store.head, signature="a" * 64)
        assert not ledger.lookup(_context(), (TERMINAL,))


def test_anchored_cas_or_head_signer_failure_preserves_caller_transaction():
    store = _HeadStore()
    with sqlite3.connect(":memory:") as conn:
        ledger = _anchored(conn, store)
        conn.execute("CREATE TABLE unrelated(value TEXT)")
        conn.execute("BEGIN")
        conn.execute("INSERT INTO unrelated VALUES ('caller')")
        store.fail_advance = True
        assert not ledger.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM unrelated").fetchall() == [("caller",)]
        assert conn.execute("SELECT count(*) FROM h487_consent_decisions").fetchone()[0] == 0
        store.fail_advance = False
        conn.commit()

        def mac(payload: bytes) -> str | None:
            if b'"purpose":"h487-consent-head"' in payload:
                return None
            return hmac.new(KEY, payload, hashlib.sha256).hexdigest()

        broken = _anchored(conn, store, DetachedHMACSigner(mac))
        assert not broken.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-2", decided_by="owner")
        assert store.head.last_sequence == 0
        assert conn.execute("SELECT count(*) FROM h487_consent_decisions").fetchone()[0] == 0


def test_anchored_outer_rollback_invalidates_local_grant_without_committing_caller():
    store = _HeadStore()
    with sqlite3.connect(":memory:") as conn:
        ledger = _anchored(conn, store)
        conn.execute("CREATE TABLE unrelated(value TEXT)")
        conn.execute("BEGIN")
        conn.execute("INSERT INTO unrelated VALUES ('caller')")
        assert ledger.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM unrelated").fetchall() == [("caller",)]
        conn.rollback()
        assert store.head.last_sequence == 1
        assert not ledger.lookup(_context(), (TERMINAL,))
        assert not ledger.grant(_context(), (READ,), choice="always", decision_id="decision-2", decided_by="owner")


def test_anchored_does_not_adopt_nonempty_legacy_store(tmp_path):
    store = _HeadStore()
    with sqlite3.connect(tmp_path / "consent.db") as conn:
        legacy = _ledger(conn)
        assert legacy.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        anchored = _anchored(conn, store)
        assert store.head is None
        assert not anchored.lookup(_context(), (TERMINAL,))
        assert not anchored.grant(_context(), (READ,), choice="always", decision_id="decision-2", decided_by="owner")


def test_always_consent_reopens_and_requires_all_categories(tmp_path):
    path = tmp_path / "consent.db"
    with sqlite3.connect(path) as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert not ledger.lookup(ctx, (TERMINAL, READ))
        assert ledger.grant(ctx, (TERMINAL, READ), choice="always", decision_id="decision-1", decided_by="owner")
        assert ledger.lookup(ctx, (TERMINAL, READ))
        assert not ledger.lookup(ctx, (TERMINAL, CONTENT))
        assert not ledger.lookup(ctx, ())
    with sqlite3.connect(path) as conn:
        reopened = _ledger(conn)
        assert reopened.lookup(_context(session_id="new-chat", session_instance="new-instance"), (TERMINAL, READ))
        assert not _ledger(conn, _signer(b"different-owner-key")).lookup(ctx, (TERMINAL,))


@pytest.mark.parametrize("field", ("principal", "surface", "registration_key", "policy_revision", "target_scope"))
def test_always_consent_binds_stable_context(field):
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="admin")
        assert not ledger.lookup(replace(ctx, **{field: f"other-{field}"}), (TERMINAL,))


def test_session_consent_binds_both_session_identifiers():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL,), choice="session", decision_id="decision-1", decided_by="owner")
        assert ledger.lookup(ctx, (TERMINAL,))
        assert not ledger.lookup(_context(session_id="chat-2"), (TERMINAL,))
        assert not ledger.lookup(_context(session_instance="instance-2"), (TERMINAL,))


def test_content_category_downgrades_always_to_session():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL, CONTENT), choice="always", decision_id="decision-1", decided_by="owner")
        later = _context(session_id="chat-2", session_instance="instance-2")
        assert ledger.lookup(ctx, (TERMINAL, CONTENT))
        assert ledger.lookup(later, (TERMINAL,))
        assert not ledger.lookup(later, (CONTENT,))


@pytest.mark.parametrize("decider", ("", "user", "policy", "smart_approval", "telegram", "unknown-human"))
def test_only_supported_human_decider_origins_can_grant(decider):
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        assert not ledger.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-1", decided_by=decider)
        assert not ledger.lookup(_context(), (TERMINAL,))


def test_malformed_and_untrusted_grants_refuse_without_partial_authority():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        for categories, choice, decision_id in (
            ((), "always", "decision-1"),
            ((TERMINAL,), "once", "decision-1"),
            ((TERMINAL,), "always", ""),
            ((TERMINAL, "filesystem.read"), "always", "decision-1"),
            ((TERMINAL, ConsentCategory("unregistered.action")), "always", "decision-1"),
            ((TERMINAL, ConsentCategory("terminal.run", permanent=False)), "always", "decision-1"),
        ):
            assert not ledger.grant(ctx, categories, choice=choice, decision_id=decision_id, decided_by="owner")
        assert not ledger.grant(replace(ctx, principal=""), (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        assert not ledger.lookup(ctx, (TERMINAL,))
        assert not ConsentLedger(conn, None, categories=CATEGORIES).grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")


def test_tampering_with_signed_row_refuses_authority():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        assert ledger.lookup(ctx, (TERMINAL,))
        conn.execute("UPDATE h487_consent_grants SET category_key='filesystem.read'")
        assert not ledger.lookup(ctx, (READ,))
        assert not ledger.lookup(ctx, (TERMINAL,))


def test_revoke_removes_session_and_always_for_only_matching_stable_identity():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        other = _context(principal="owner-2")
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        assert ledger.grant(ctx, (CONTENT,), choice="session", decision_id="decision-2", decided_by="owner")
        assert ledger.grant(other, (TERMINAL,), choice="always", decision_id="decision-3", decided_by="owner")
        assert ledger.revoke(ctx)
        assert not ledger.lookup(ctx, (TERMINAL,))
        assert not ledger.lookup(ctx, (CONTENT,))
        assert ledger.lookup(other, (TERMINAL,))


def test_savepoint_preserves_outer_rollback_and_multirow_atomicity():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        conn.execute("CREATE TABLE unrelated (value TEXT)")
        conn.execute("BEGIN")
        conn.execute("INSERT INTO unrelated VALUES ('caller')")
        assert ledger.grant(ctx, (TERMINAL, READ), choice="always", decision_id="decision-1", decided_by="owner")
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT count(*) FROM unrelated").fetchone()[0] == 0
        assert not ledger.lookup(ctx, (TERMINAL,))

        signer = DetachedHMACSigner(
            lambda payload: None
            if b'"purpose":"owner-category-grant"' in payload and b'"key":"filesystem.read"' in payload
            else hmac.new(KEY, payload, hashlib.sha256).hexdigest()
        )
        broken = _ledger(conn, signer)
        conn.execute("BEGIN")
        conn.execute("INSERT INTO unrelated VALUES ('caller-kept')")
        assert not broken.grant(ctx, (TERMINAL, READ), choice="always", decision_id="decision-2", decided_by="owner")
        assert conn.execute("SELECT value FROM unrelated").fetchall() == [("caller-kept",)]
        assert not ledger.lookup(ctx, (TERMINAL,))
        conn.commit()


def test_decision_id_cannot_be_replayed_after_revoke_or_widened():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        assert not ledger.grant(ctx, (TERMINAL, READ), choice="always", decision_id="decision-1", decided_by="owner")
        assert not ledger.grant(_context(target_scope="local:/elsewhere"), (READ,), choice="always", decision_id="decision-1", decided_by="owner")
        assert ledger.revoke(ctx)
        assert not ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        assert not ledger.lookup(ctx, (TERMINAL,))
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-2", decided_by="owner")


def test_revocation_disables_copied_signed_grant_and_decision_tampering():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        old_row = conn.execute("SELECT * FROM h487_consent_grants").fetchone()
        assert ledger.revoke(ctx)
        conn.execute("INSERT INTO h487_consent_grants VALUES (?, ?, ?, ?, ?, ?)", old_row)
        assert not ledger.lookup(ctx, (TERMINAL,))
        conn.execute("DELETE FROM h487_consent_grants")
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-2", decided_by="owner")
        conn.execute("UPDATE h487_consent_decisions SET signature='z' || substr(signature, 2) WHERE decision_id='decision-2'")
        assert not ledger.lookup(ctx, (TERMINAL,))


def test_revocation_tombstones_superseded_decisions():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        ctx = _context()
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-1", decided_by="owner")
        superseded = conn.execute("SELECT * FROM h487_consent_grants").fetchone()
        assert ledger.grant(ctx, (TERMINAL,), choice="always", decision_id="decision-2", decided_by="owner")
        assert ledger.revoke(ctx)
        conn.execute("INSERT INTO h487_consent_grants VALUES (?, ?, ?, ?, ?, ?)", superseded)
        assert not ledger.lookup(ctx, (TERMINAL,))


def test_unhashable_choice_and_decider_refuse_without_exception():
    with sqlite3.connect(":memory:") as conn:
        ledger = _ledger(conn)
        assert not ledger.grant(_context(), (TERMINAL,), choice=[], decision_id="decision-1", decided_by="owner")
        assert not ledger.grant(_context(), (TERMINAL,), choice="always", decision_id="decision-1", decided_by=[])


def test_multi_category_lookup_uses_one_database_snapshot(tmp_path):
    path = tmp_path / "snapshot.db"
    ctx = _context()
    with sqlite3.connect(path, timeout=1) as reader, sqlite3.connect(path, timeout=1) as writer:
        reader.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA journal_mode=WAL")
        writer_ledger = _ledger(writer)
        armed = False
        fired = False

        def read_mac(payload: bytes) -> str:
            nonlocal fired
            if armed and not fired and b'"purpose":"owner-consent-decision"' in payload:
                fired = True
                assert writer_ledger.revoke(ctx)
                assert writer_ledger.grant(
                    ctx, (TERMINAL,), choice="always", decision_id="decision-2", decided_by="owner"
                )
            return hmac.new(KEY, payload, hashlib.sha256).hexdigest()

        reader_ledger = _ledger(reader, DetachedHMACSigner(read_mac))
        assert reader_ledger.grant(ctx, (READ,), choice="always", decision_id="decision-1", decided_by="owner")
        armed = True
        # READ existed before the concurrent change; TERMINAL only afterwards.
        assert not reader_ledger.lookup(ctx, (READ, TERMINAL))
        assert fired
        assert reader_ledger.lookup(ctx, (TERMINAL,))
        assert not reader_ledger.lookup(ctx, (READ,))
