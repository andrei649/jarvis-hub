"""The audit log's Merkle chain is only tamper-EVIDENT if something verifies it.

Found 2026-06-10: AuditLogger.verify_chain() existed with zero callers — no
endpoint, no test. This adds both: unit coverage for the chain math (including
an actual tamper) and the new GET /api/security/audit/verify endpoint.
"""

import json
import sys
import time
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.security.audit import AuditLogger
from agents.core.security.types import SecurityEvent, SecurityEventType


def _logger_with_events(tmp_path, n=3) -> AuditLogger:
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    for i in range(n):
        audit.log(SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG,
            timestamp=time.time() + i,
            content_preview=f"event {i}",
            action_taken="logged",
        ))
    return audit


def test_chain_verifies_clean(tmp_path):
    audit = _logger_with_events(tmp_path)
    valid, first_bad = audit.verify_chain()
    assert valid is True and first_bad is None
    assert audit.count() == 3


def test_chain_detects_tampering(tmp_path):
    audit = _logger_with_events(tmp_path)
    # Tamper with a mid-chain row the way an attacker with file access would.
    audit._conn.execute(
        "UPDATE security_events SET content_preview='REWRITTEN HISTORY' WHERE id=2"
    )
    audit._conn.commit()
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 2


def test_chain_detects_relinking(tmp_path):
    """Recomputing one row's hash without fixing successors still breaks the chain."""
    audit = _logger_with_events(tmp_path)
    audit._conn.execute("UPDATE security_events SET prev_hash='deadbeef' WHERE id=3")
    audit._conn.commit()
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 3


def _raw_insert(audit, *, preview, row_hash, prev_hash, algo="sha256", ts_offset=99):
    """Insert a row straight into the table, the way an attacker with DB write
    access would — bypassing log()'s hash computation."""
    audit._conn.execute(
        "INSERT INTO security_events (timestamp, event_type, findings_json, "
        "content_preview, action_taken, row_hash, prev_hash, hash_algo) "
        "VALUES (?, ?, '[]', ?, 'logged', ?, ?, ?)",
        (time.time() + ts_offset, SecurityEventType.AUDIT_LOG.value, preview, row_hash, prev_hash, algo),
    )
    audit._conn.commit()


def test_blank_hash_row_after_chain_fails(tmp_path):
    """A forged row that leaves row_hash blank must NOT pass verification.

    Regression for the empty-hash bypass: verify_chain used to `continue` past
    any row with an empty row_hash, so an attacker could inject fabricated audit
    rows (or truncate the tail) that read as genuine via query() while remaining
    invisible to the integrity check.
    """
    audit = _logger_with_events(tmp_path)  # ids 1..3, real hashes
    _raw_insert(audit, preview="INJECTED", row_hash="", prev_hash="")
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 4


def test_blank_hash_forgery_fails_even_with_hmac_key(tmp_path, monkeypatch):
    """The bypass worked even in HMAC mode (blank hash dodged the HMAC check
    entirely). With the key set, a blank-hash forgery must still fail closed."""
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "off-box-secret")
    audit = _logger_with_events(tmp_path)  # rows are hmac-sha256
    _raw_insert(audit, preview="FORGED", row_hash="", prev_hash=audit.tail_hash(), algo="hmac-sha256")
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 4


def test_legacy_blank_hash_prefix_is_tolerated(tmp_path):
    """Rows written before the Merkle columns existed carry row_hash='' (the v1
    migration backfills the DEFAULT ''). Those legitimate legacy rows form a
    contiguous prefix and must still verify clean once real hashed rows follow."""
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    for i in range(2):  # legacy prefix, blank hashes
        _raw_insert(audit, preview=f"legacy {i}", row_hash="", prev_hash="", ts_offset=i)
    for i in range(3):  # current code writes real hashes on top
        audit.log(SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG,
            timestamp=time.time() + 10 + i,
            content_preview=f"new {i}",
            action_taken="logged",
        ))
    valid, first_bad = audit.verify_chain()
    assert valid is True and first_bad is None


async def test_verify_endpoint(tmp_path, monkeypatch):
    import agents.web as web
    from agents.core.routers.security import audit_verify

    class _Orch:
        audit = _logger_with_events(tmp_path)

    monkeypatch.setattr(web, "orch", _Orch())
    resp = await audit_verify()
    body = json.loads(resp.body)
    # The original contract still holds...
    assert body["valid"] is True
    assert body["first_invalid_id"] is None
    assert body["entries"] == 3
    # ...and the endpoint no longer lets an UNKEYED pass read as tamper evidence
    # (adversarial audit 2026-07-25, ADV-009). This fixture logs without a key, so
    # anyone with file access could recompute the whole chain — `valid` is the weaker
    # claim, and the response has to say which one the reader is looking at.
    assert body["key_configured"] is False
    assert body["tamper_evident"] is False
    assert body["integrity"] == "sha256"
    assert "NOT tamper evidence" in body["reason"]


async def test_verify_endpoint_unavailable(monkeypatch):
    import agents.web as web
    from agents.core.routers.security import audit_verify

    monkeypatch.setattr(web, "orch", None)
    resp = await audit_verify()
    assert resp.status_code == 503
