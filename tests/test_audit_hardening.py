"""AUD-9 + AUD-12 — keyed audit chain + no raw secrets in the audit log.

AUD-9: with JARVIS_AUDIT_KEY set, chain rows are HMAC-keyed so an attacker with
DB write access can't recompute a forged chain without the key. Default (no key)
keeps the prior plain-SHA-256 behavior, and a DB that spans the transition still
verifies. AUD-12: the scanner's raw matched secret is never persisted — the audit
row (and the admin audit page) carry only a [REDACTED:<pattern>] marker.
"""
import sqlite3
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.security.audit import AuditLogger
from agents.core.security.types import (
    ScanFinding,
    SecurityEvent,
    SecurityEventType,
    ThreatLevel,
)


def _log_n(audit: AuditLogger, n: int = 3) -> None:
    for i in range(n):
        audit.log(SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG,
            timestamp=time.time() + i,
            content_preview=f"event {i}",
            action_taken="logged",
        ))


def _algos(db: str) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[0] for r in conn.execute("SELECT hash_algo FROM security_events").fetchall()}
    finally:
        conn.close()


# ── AUD-9: keying ──────────────────────────────────────────────────
def test_unkeyed_chain_uses_sha256_and_verifies(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    db = str(tmp_path / "audit.db")
    audit = AuditLogger(db_path=db)
    _log_n(audit)
    assert audit.verify_chain() == (True, None)
    assert _algos(db) == {"sha256"}


def test_keyed_chain_uses_hmac_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "an-off-box-audit-key")
    db = str(tmp_path / "audit.db")
    audit = AuditLogger(db_path=db)
    _log_n(audit)
    assert audit.verify_chain() == (True, None)
    assert _algos(db) == {"hmac-sha256"}


def test_keyed_chain_unverifiable_without_key(tmp_path, monkeypatch):
    db = str(tmp_path / "audit.db")
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "secret-key")
    audit = AuditLogger(db_path=db)
    _log_n(audit)
    audit.close()
    # An auditor (or attacker) without the key cannot verify the keyed rows.
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    audit2 = AuditLogger(db_path=db)
    valid, first_bad = audit2.verify_chain()
    assert valid is False and first_bad == 1


def test_mixed_algo_chain_verifies_across_key_introduction(tmp_path, monkeypatch):
    db = str(tmp_path / "audit.db")
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    a1 = AuditLogger(db_path=db)        # legacy sha256 rows
    _log_n(a1, 2)
    a1.close()
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "key-introduced-later")
    a2 = AuditLogger(db_path=db)        # subsequent hmac rows
    _log_n(a2, 2)
    valid, first_bad = a2.verify_chain()
    assert valid is True and first_bad is None
    assert _algos(db) == {"sha256", "hmac-sha256"}


def test_keyed_chain_detects_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "k")
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    _log_n(audit)
    audit._conn.execute("UPDATE security_events SET content_preview='REWRITTEN' WHERE id=2")
    audit._conn.commit()
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 2


def test_attacker_recompute_with_sha256_still_fails(tmp_path, monkeypatch):
    """An attacker who rewrites a keyed row and recomputes its hash with plain
    sha256 (no key) cannot forge a valid chain."""
    import hashlib
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "the-real-key")
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    _log_n(audit)
    row = audit._conn.execute(
        "SELECT timestamp, event_type, findings_json, content_preview, action_taken, prev_hash FROM security_events WHERE id=2"
    ).fetchone()
    ts, etype, fj, _preview, action, prev = row
    forged_preview = "INJECTED"
    forged_input = f"{prev}|{ts}|{etype}|{fj}|{forged_preview}|{action}"
    forged_hash = hashlib.sha256(forged_input.encode()).hexdigest()
    audit._conn.execute(
        "UPDATE security_events SET content_preview=?, row_hash=?, hash_algo='sha256' WHERE id=2",
        (forged_preview, forged_hash),
    )
    audit._conn.commit()
    # The forged row self-checks under sha256, so before AUDIT-1 the break only surfaced
    # one row LATER, at row 3, whose prev_hash still expected the original HMAC. It is now
    # caught on the forged row itself: after a keyed row, a sha256 row is tampering
    # (verify_chain rule (a)). Earlier detection, and it names the row that was actually
    # edited rather than its innocent successor.
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 2


def test_full_table_downgrade_is_rejected(tmp_path, monkeypatch):
    """The AUDIT-1 break itself: rewrite EVERY row with plain sha256.

    This is the case the single-row test above could not see. With the whole table
    downgraded there is no surviving HMAC row for a prev_hash to disagree with, so the
    chain re-linked cleanly and ``verify_chain`` returned ``(True, None)`` over entirely
    attacker-chosen content — with a key configured and ``hardened.enforce()`` clean.
    The attacker's toolkit is sqlite3 + hashlib; the key is never read.

    Reproduced independently while writing docs/test-manual/15-audit-gap-verification.md
    (case ADV-001); scripts/qa_audit_probes.py carries the same reproduction as a probe.
    """
    import hashlib
    import sqlite3

    monkeypatch.setenv("JARVIS_AUDIT_KEY", "the-real-key")
    db = str(tmp_path / "audit.db")
    audit = AuditLogger(db_path=db)
    _log_n(audit)
    assert audit.verify_chain() == (True, None)
    assert _algos(db) == {"hmac-sha256"}
    audit.close()

    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT id, timestamp, event_type, findings_json, action_taken "
            "FROM security_events ORDER BY id").fetchall()
        prev = ""
        for rid, ts, etype, findings, action in rows:
            forged = f"attacker rewrote row {rid}"
            row_hash = hashlib.sha256(
                f"{prev}|{ts}|{etype}|{findings}|{forged}|{action}".encode()).hexdigest()
            con.execute(
                "UPDATE security_events SET content_preview=?, row_hash=?, prev_hash=?, "
                "hash_algo='sha256' WHERE id=?", (forged, row_hash, prev, rid))
            prev = row_hash
        con.commit()
    finally:
        con.close()

    after = AuditLogger(db_path=db)
    try:
        valid, first_bad = after.verify_chain()
        assert valid is False, (
            "a fully rewritten chain verified — the hardened-mode guarantee that "
            "'an attacker with DB write access cannot forge the chain without the key' "
            "is void (adversarial audit 2026-07-25, AUDIT-1)"
        )
        assert first_bad == 1
    finally:
        after.close()


def test_legacy_chain_fails_closed_once_a_key_is_configured(tmp_path, monkeypatch):
    """The other half of rule (b), stated as its own contract rather than a side effect.

    An all-sha256 chain read by a keyed logger is indistinguishable from a fully
    downgraded one — that is precisely why the full-table forgery worked. Verification
    must refuse rather than vouch. The owner resolves it deliberately: log an event (the
    tail becomes keyed, and the legacy prefix is then a legitimate mixed chain, covered by
    test_mixed_algo_chain_verifies_across_key_introduction) or re-anchor the old rows.
    """
    db = str(tmp_path / "audit.db")
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    legacy = AuditLogger(db_path=db)
    _log_n(legacy, 3)
    assert legacy.verify_chain() == (True, None)     # honest while genuinely unkeyed
    legacy.close()

    monkeypatch.setenv("JARVIS_AUDIT_KEY", "key-set-on-an-old-chain")
    keyed = AuditLogger(db_path=db)
    try:
        valid, first_bad = keyed.verify_chain()
        assert valid is False and first_bad == 1
        # ...and one new event restores it: the tail is keyed, the prefix is legacy.
        _log_n(keyed, 1)
        assert keyed.verify_chain() == (True, None)
    finally:
        keyed.close()


# ── AUD-12: no raw secrets persisted / displayed ───────────────────
def test_matched_text_masked_at_rest(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    db = str(tmp_path / "audit.db")
    audit = AuditLogger(db_path=db)
    secret = "sk-ant-THIS-IS-A-RAW-SECRET-0123456789"
    audit.log(SecurityEvent(
        event_type=SecurityEventType.AUDIT_LOG,
        timestamp=time.time(),
        findings=[ScanFinding(
            pattern_name="anthropic_key",
            matched_text=secret,
            threat_level=ThreatLevel.CRITICAL,
            start=0, end=len(secret), description="API key",
        )],
        content_preview="(masked upstream)",
        action_taken="blocked",
    ))
    conn = sqlite3.connect(db)
    try:
        fj = conn.execute("SELECT findings_json FROM security_events").fetchone()[0]
    finally:
        conn.close()
    assert secret not in fj
    assert "[REDACTED:anthropic_key]" in fj


def test_admin_endpoint_redacts_legacy_raw_rows():
    import json as _json
    from agents.core.routers.admin import _redact_audit_details

    raw = _json.dumps([
        {"pattern_name": "anthropic_key", "matched_text": "sk-ant-RAWSECRET",
         "threat_level": "critical", "start": 0, "end": 5, "description": "x"},
    ])
    out = _redact_audit_details(raw)
    assert "sk-ant-RAWSECRET" not in out
    assert "[REDACTED:anthropic_key]" in out


def test_redact_audit_details_idempotent_and_passthrough():
    import json as _json
    from agents.core.routers.admin import _redact_audit_details

    already = _json.dumps([{"pattern_name": "x", "matched_text": "[REDACTED:x]"}])
    assert _redact_audit_details(already) == already      # unchanged
    assert _redact_audit_details(None) is None            # non-str passthrough
    assert _redact_audit_details("[]") == "[]"            # no findings


# ── query() — the audit read path (was untested; covers audit.py:134-169) ──
# Reconstructs SecurityEvents (incl. findings) from the chain; the round-trip also
# re-confirms AUD-12 — the stored matched_text is the [REDACTED:..] marker, never raw.

def test_query_round_trips_events_and_keeps_secrets_redacted(tmp_path):
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    t0 = 1_000_000.0
    audit.log(SecurityEvent(
        event_type=SecurityEventType.AUDIT_LOG, timestamp=t0,
        content_preview="first", action_taken="logged",
        findings=[ScanFinding(pattern_name="email", matched_text="alice@example.com",
                              threat_level=ThreatLevel.MEDIUM, start=3, end=20, description="pii")],
    ))
    audit.log(SecurityEvent(
        event_type=SecurityEventType.SSRF_BLOCKED, timestamp=t0 + 10,
        content_preview="second", action_taken="blocked",
    ))

    evs = audit.query()
    assert [e.content_preview for e in evs] == ["second", "first"]   # newest first
    assert evs[0].event_type is SecurityEventType.SSRF_BLOCKED
    f = evs[1].findings[0]                                            # findings reconstructed
    assert f.pattern_name == "email" and f.threat_level is ThreatLevel.MEDIUM
    assert (f.start, f.end) == (3, 20)
    assert f.matched_text == "[REDACTED:email]"                       # AUD-12: raw secret never stored
    assert "alice@example.com" not in f.matched_text


def test_query_filters_by_type_since_and_limit(tmp_path):
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    t0 = 2_000_000.0
    for i in range(5):
        audit.log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=t0 + i,
                                content_preview=f"a{i}", action_taken="x"))
    audit.log(SecurityEvent(event_type=SecurityEventType.SSRF_BLOCKED, timestamp=t0 + 100,
                            content_preview="ssrf", action_taken="x"))

    assert [e.content_preview for e in audit.query(event_type="ssrf_blocked")] == ["ssrf"]
    since = {e.content_preview for e in audit.query(since=t0 + 3)}
    assert "ssrf" in since and "a0" not in since and "a4" in since
    assert len(audit.query(limit=2)) == 2


def test_prune_refuses_to_leave_a_chain_that_would_not_verify(tmp_path, monkeypatch):
    """Retention must not prune into the shape verify_chain rejects (AUDIT-1 rule b).

    A keyed logger pruning a chain whose survivors are all sha256 used to report success
    and leave behind a chain that no longer verifies. Re-anchoring those rows under the
    key would be worse — it vouches for rows written before the key existed — so the
    prune refuses and the owner re-anchors deliberately.
    """
    db = str(tmp_path / "audit.db")
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    legacy = AuditLogger(db_path=db)
    for i in range(4):
        legacy.log(SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG,
            timestamp=1000.0 + i, content_preview=f"legacy {i}", action_taken="logged",
        ))
    legacy.close()

    monkeypatch.setenv("JARVIS_AUDIT_KEY", "key-set-on-an-old-chain")
    keyed = AuditLogger(db_path=db)
    try:
        assert keyed.prune_before(1002.0) == 0, "pruned into an unverifiable chain"
        assert keyed.count() == 4, "rows were deleted despite the refusal"
    finally:
        keyed.close()


# ── AUDIT-1: the verdict has to be readable, not just correct ──────
def test_chain_status_separates_tamper_evidence_from_mere_validity(tmp_path, monkeypatch):
    """An unkeyed chain that verifies is integrity, not tamper evidence (ADV-009)."""
    db = str(tmp_path / "audit.db")
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    audit = AuditLogger(db_path=db)
    _log_n(audit)
    status = audit.chain_status()
    assert status["valid"] is True
    assert status["tamper_evident"] is False, (
        "an unkeyed chain was reported as tamper-evident — anyone with file access can "
        "recompute it, so 'valid' here is the weaker claim and must say so"
    )
    assert status["integrity"] == "sha256"
    assert "NOT tamper evidence" in status["reason"]
    audit.close()

    monkeypatch.setenv("JARVIS_AUDIT_KEY", "an-off-box-audit-key")
    keyed = AuditLogger(db_path=str(tmp_path / "keyed.db"))
    try:
        _log_n(keyed)
        status = keyed.chain_status()
        assert status["valid"] is True and status["tamper_evident"] is True
        assert status["integrity"] == "hmac-sha256"
    finally:
        keyed.close()


def test_chain_status_distinguishes_a_rewrite_from_a_legacy_chain(tmp_path, monkeypatch):
    """Both are `valid: false`; they want opposite responses from the owner."""
    db = str(tmp_path / "audit.db")
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    legacy = AuditLogger(db_path=db)
    _log_n(legacy, 2)
    legacy.close()

    monkeypatch.setenv("JARVIS_AUDIT_KEY", "key-set-later")
    keyed = AuditLogger(db_path=db)
    try:
        status = keyed.chain_status()
        assert status["valid"] is False
        assert "predates it" in status["reason"], (
            f"a legacy chain reads as a rewrite: {status['reason']!r}"
        )
        # a genuine mid-chain edit says something different
        _log_n(keyed, 1)
        keyed._conn.execute("UPDATE security_events SET content_preview='X' WHERE id=1")
        keyed._conn.commit()
        broken = keyed.chain_status()
        assert broken["valid"] is False and "broken at entry" in broken["reason"]
    finally:
        keyed.close()


def test_mixed_chain_reports_how_much_is_actually_keyed(tmp_path, monkeypatch):
    db = str(tmp_path / "audit.db")
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    a1 = AuditLogger(db_path=db)
    _log_n(a1, 2)
    a1.close()
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "key-introduced-later")
    a2 = AuditLogger(db_path=db)
    try:
        _log_n(a2, 2)          # the mixed chain only exists once a keyed row is written
        status = a2.chain_status()
        assert status["valid"] is True
        assert status["integrity"] == "mixed"
        assert status["tamper_evident"] is False, (
            "a chain with unkeyed legacy rows is not wholly tamper-evident"
        )
        assert "predate the key" in status["reason"]
    finally:
        a2.close()
