"""Actual independent file anchor defeats signed consent DB/row restoration."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3

import pytest

from agents.core.autonomy.consent_ledger import ConsentCategory, ConsentContext, ConsentLedger
from agents.core.autonomy.mediation import DetachedHMACSigner

CATEGORY = ConsentCategory('terminal.warning.delete_in_root_path')
CONTEXT = ConsentContext('owner', 'terminal', 'synthetic-chat', 'instance',
                         'registrar-v1', 'policy-v1', 'synthetic-local-target')


def _signer():
    return DetachedHMACSigner(lambda data: hmac.new(b'fixture-consent-key', data, hashlib.sha256).hexdigest())


def _anchored(conn, anchor_path):
    from agents.core.autonomy.consent_head_store import make_consent_head_anchor

    anchor = make_consent_head_anchor(anchor_path)
    ledger = ConsentLedger(conn, _signer(), categories=(CATEGORY,), head_anchor=anchor)
    ledger.initialize()
    return ledger, anchor


def _grant(ledger, decision_id='first-owner-decision'):
    return ledger.grant(CONTEXT, (CATEGORY,), choice='always',
                        decision_id=decision_id, decided_by='owner')


def test_old_signed_rows_cannot_restore_revoked_consent_with_actual_external_anchor(tmp_path):
    with sqlite3.connect(tmp_path / 'consent.db') as conn:
        ledger, anchor = _anchored(conn, tmp_path / 'security' / 'consent-head.json')
        assert _grant(ledger) and ledger.lookup(CONTEXT, (CATEGORY,))
        grant = conn.execute('SELECT * FROM h487_consent_grants').fetchone()
        decision = conn.execute('SELECT * FROM h487_consent_decisions').fetchone()
        before = anchor.read()
        assert ledger.revoke(CONTEXT)
        assert anchor.read().last_sequence > before.last_sequence
        conn.execute('INSERT INTO h487_consent_grants VALUES(?,?,?,?,?,?)', grant)
        conn.execute('UPDATE h487_consent_decisions SET payload=?,signature=? WHERE decision_id=?',
                     (decision[1], decision[2], decision[0]))
        conn.commit()
        assert not ledger.lookup(CONTEXT, (CATEGORY,))
        assert not _grant(ledger, 'attempt-after-restoration')


def test_restoring_entire_valid_sqlite_snapshot_keeps_revocation_effective(tmp_path):
    db_path = tmp_path / 'consent.db'
    head_path = tmp_path / 'security' / 'consent-head.json'
    snapshot = sqlite3.connect(tmp_path / 'old-valid-snapshot.db')
    conn = sqlite3.connect(db_path)
    try:
        ledger, anchor = _anchored(conn, head_path)
        assert _grant(ledger)
        conn.commit()
        conn.backup(snapshot)
        assert ledger.revoke(CONTEXT)
        conn.commit()
        revoked_head = anchor.read()
        assert not ledger.lookup(CONTEXT, (CATEGORY,))
    finally:
        conn.close()
    restored = sqlite3.connect(db_path)
    try:
        snapshot.backup(restored)
        ledger, reopened_anchor = _anchored(restored, head_path)
        assert reopened_anchor.read() == revoked_head
        assert not ledger.lookup(CONTEXT, (CATEGORY,))
        assert not _grant(ledger, 'owner-decision-on-rolled-back-db')
    finally:
        restored.close()
        snapshot.close()


def test_two_real_handles_reopen_current_head_and_observe_revocation(tmp_path):
    db = tmp_path / 'consent.db'
    head = tmp_path / 'security' / 'consent-head.json'
    with sqlite3.connect(db) as first, sqlite3.connect(db) as second:
        one, _ = _anchored(first, head)
        assert _grant(one)
        two, _ = _anchored(second, head)
        assert two.lookup(CONTEXT, (CATEGORY,))
        assert two.revoke(CONTEXT)
        assert not one.lookup(CONTEXT, (CATEGORY,))


def test_caller_rollback_after_external_advance_refuses_old_authority_without_committing_caller(tmp_path):
    with sqlite3.connect(tmp_path / 'consent.db') as conn:
        ledger, anchor = _anchored(conn, tmp_path / 'security' / 'consent-head.json')
        conn.execute('CREATE TABLE caller_owned(value TEXT)')
        conn.commit()
        before = anchor.read()
        conn.execute('INSERT INTO caller_owned VALUES(?)', ('uncommitted',))
        assert _grant(ledger)
        assert conn.in_transaction
        assert ledger.lookup(CONTEXT, (CATEGORY,))
        conn.rollback()
        assert conn.execute('SELECT COUNT(*) FROM caller_owned').fetchone()[0] == 0
        assert anchor.read().last_sequence > before.last_sequence
        assert not ledger.lookup(CONTEXT, (CATEGORY,))
        assert not _grant(ledger, 'after-outer-rollback')


def test_existing_unanchored_grants_are_not_silently_adopted_as_rollback_resistant(tmp_path):
    with sqlite3.connect(tmp_path / 'consent.db') as conn:
        legacy = ConsentLedger(conn, _signer(), categories=(CATEGORY,))
        legacy.initialize()
        assert _grant(legacy)
        conn.commit()
        anchored, anchor = _anchored(conn, tmp_path / 'security' / 'consent-head.json')
        assert anchor.read() is None
        assert not anchored.lookup(CONTEXT, (CATEGORY,))
        assert not _grant(anchored, 'implicit-adoption')


@pytest.mark.parametrize('failure', ['missing', 'corrupt', 'wrong-signature'])
def test_unavailable_actual_anchor_does_not_rebootstrap_existing_signed_authority(tmp_path, failure):
    path = tmp_path / 'security' / 'consent-head.json'
    with sqlite3.connect(tmp_path / 'consent.db') as conn:
        ledger, _anchor = _anchored(conn, path)
        assert _grant(ledger)
        if failure == 'missing':
            path.unlink()
        elif failure == 'corrupt':
            path.write_text('{unreadable', encoding='utf-8')
        else:
            head = json.loads(path.read_text())
            head['signature'] = '0' * 64
            path.write_text(json.dumps(head), encoding='utf-8')
        before = path.read_bytes() if path.exists() else None
        reopened, _ = _anchored(conn, path)
        assert not reopened.lookup(CONTEXT, (CATEGORY,))
        assert not _grant(reopened, 'new-owner-decision-after-anchor-loss')
        assert (path.read_bytes() if path.exists() else None) == before


def test_external_revocation_during_lookup_invalidates_a_consistent_old_sqlite_snapshot(tmp_path):
    from agents.core.autonomy.consent_head_store import make_consent_head_anchor

    db = tmp_path / 'consent.db'
    head = tmp_path / 'security' / 'consent-head.json'
    with sqlite3.connect(db, timeout=1) as reader, sqlite3.connect(db, timeout=1) as writer:
        reader.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA journal_mode=WAL')
        writer_ledger, _ = _anchored(writer, head)
        assert _grant(writer_ledger)
        armed = False
        fired = False

        def verify_mac(data):
            nonlocal fired
            if armed and not fired and b'"purpose":"owner-consent-decision"' in data:
                fired = True
                assert writer_ledger.revoke(CONTEXT)
            return hmac.new(b'fixture-consent-key', data, hashlib.sha256).hexdigest()

        reader_ledger = ConsentLedger(reader, DetachedHMACSigner(verify_mac),
                                     categories=(CATEGORY,), head_anchor=make_consent_head_anchor(head))
        reader_ledger.initialize()
        armed = True
        assert not reader_ledger.lookup(CONTEXT, (CATEGORY,))
        assert fired
        assert not writer_ledger.lookup(CONTEXT, (CATEGORY,))
