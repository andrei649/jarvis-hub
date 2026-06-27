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
    # Row 2 now self-checks under sha256, but row 3's prev_hash still expects the
    # original HMAC hash — and the attacker can't recompute row 3 without the key.
    # The forgery is detected (the break surfaces at row 3); verify never passes.
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 3


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
