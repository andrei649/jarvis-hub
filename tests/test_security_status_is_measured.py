"""`/security/status` published literals and the Console drew them as measurements.

Every number was hardcoded: `mode` always "WARN", `redact_count` and
`block_count` always 0, the scanner pattern counts hand-written as 10 and 6 (both
wrong), and the SSRF counters 0. The module docstring said so outright —
"`security_status` is fully static" — but nothing downstream did. Console →
Systems → Security rendered a hub running in BLOCK mode that had redacted forty
PII spans as "Mode WARN · Redacted 0 · Blocked 0", and the warn styling
(`findings > 0`) could never fire.

Nothing was counting, so the fix is not "read the right variable" — the counters
had to exist. They live on GuardrailsEngine now, shared across every instance
`bind()` produces so the total is per-process rather than per-backend.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.security.guardrails import GuardrailsEngine
from agents.core.security.types import RedactionMode

# A string that trips the secret scanner. Generated shape, not a real credential.
_TRIPWIRE = "sk-ant-" + "QAFAKE" + "0" * 20


def _engine(mode=RedactionMode.WARN):
    return GuardrailsEngine(mode=mode)


# ── the counters count ────────────────────────────────────────────────────────

def test_a_clean_scan_counts_a_scan_and_no_findings():
    eng = _engine()
    eng._guard_input("hello, nothing sensitive here")
    stats = eng.stats()
    assert stats["counters"]["scanned"] == 1
    assert stats["counters"]["findings"] == 0
    assert stats["counters"]["warned"] == 0


def test_warn_mode_counts_the_finding_and_the_warn():
    eng = _engine(RedactionMode.WARN)
    out = eng._guard_input(f"my key is {_TRIPWIRE}")
    counters = eng.stats()["counters"]
    assert counters["findings"] >= 1
    assert counters["warned"] == 1
    assert counters["redacted"] == 0
    assert out == f"my key is {_TRIPWIRE}"          # WARN does not alter the text


def test_redact_mode_counts_a_redaction_and_actually_redacts():
    eng = _engine(RedactionMode.REDACT)
    out = eng._guard_input(f"my key is {_TRIPWIRE}")
    counters = eng.stats()["counters"]
    assert counters["redacted"] == 1
    assert counters["blocked"] == 0
    assert _TRIPWIRE not in out


def test_block_mode_counts_a_block():
    from agents.core.security.guardrails import SecurityBlockError

    eng = _engine(RedactionMode.BLOCK)
    with pytest.raises(SecurityBlockError):
        eng._guard_input(f"my key is {_TRIPWIRE}")
    assert eng.stats()["counters"]["blocked"] == 1


def test_bound_engines_share_one_counter_set():
    """`bind()` makes a fresh instance per backend. Per-instance counters would
    each report a fraction of the truth, which is how a busy hub could still
    show zeros."""
    parent = _engine(RedactionMode.REDACT)
    child = parent.bind(SimpleNamespace(supports_tools=False))

    child._guard_input(f"key {_TRIPWIRE}")
    parent._guard_input(f"key {_TRIPWIRE}")

    assert parent.stats()["counters"]["redacted"] == 2
    assert child.stats()["counters"]["redacted"] == 2


def test_pattern_counts_come_from_the_compiled_ruleset():
    """The route claimed 10 secret and 6 PII patterns. Both were wrong, and would
    have stayed wrong every time a pattern was added."""
    stats = _engine().stats()
    assert set(stats["scanners"]) == {"secrets", "pii"}
    for sid, info in stats["scanners"].items():
        assert info["patterns"] > 0, sid
    # Not the old hand-written numbers.
    assert (stats["scanners"]["secrets"]["patterns"],
            stats["scanners"]["pii"]["patterns"]) != (10, 6)


# ── the route reports them ────────────────────────────────────────────────────

def test_status_reports_the_live_mode_and_counters(monkeypatch):
    eng = _engine(RedactionMode.BLOCK)
    eng._counters.update(scanned=12, findings=40, warned=0, redacted=40, blocked=6)
    monkeypatch.setattr(web, "orch", SimpleNamespace(security=eng))

    body = TestClient(web.app).get("/security/status").json()
    g = body["guardrails"]

    assert g["mode"] == "block"          # NOT the hardcoded "WARN"
    assert g["redact_count"] == 40       # NOT 0
    assert g["block_count"] == 6         # NOT 0
    assert g["findings"] == 40
    assert g["available"] is True


def test_status_says_unavailable_rather_than_zero_when_guardrails_are_off(monkeypatch):
    """"No guardrails" and "guardrails found nothing" are different facts."""
    monkeypatch.setattr(web, "orch", SimpleNamespace(security=None))

    body = TestClient(web.app).get("/security/status").json()
    g = body["guardrails"]

    assert g["enabled"] is False
    assert g["available"] is False
    assert g["mode"] is None             # not "WARN"
    assert "not attached" in g["note"]


def test_status_attributes_findings_to_the_scanner_that_produced_them(monkeypatch):
    """DRA-47 — per-scanner findings used to be reported as null/available:false
    ("the engine merges results before it sees which scanner produced what").
    It does see: the merge loop holds the producing scanner."""
    eng = _engine(RedactionMode.WARN)
    eng._guard_input(f"key {_TRIPWIRE}")
    monkeypatch.setattr(web, "orch", SimpleNamespace(security=eng))

    body = TestClient(web.app).get("/security/status").json()
    scanners = body["scanners"]

    assert scanners["secrets"]["findings"] >= 1
    assert scanners["pii"]["findings"] == 0          # the tripwire is not PII
    assert scanners["secrets"]["available"] is True
    assert scanners["pii"]["available"] is True


def test_bound_engines_share_the_per_scanner_findings_total():
    """Same rationale as the shared counter set: bind() forks an instance per
    backend, so a per-instance per-scanner count would report a fraction."""
    parent = _engine(RedactionMode.WARN)
    child = parent.bind(SimpleNamespace(supports_tools=False))

    child._guard_input(f"key {_TRIPWIRE}")
    parent._guard_input(f"key {_TRIPWIRE}")

    assert (parent.stats()["scanners"]["secrets"]["findings"]
            == child.stats()["scanners"]["secrets"]["findings"] >= 2)


def test_status_reports_the_real_ssrf_block_count(monkeypatch):
    """DRA-47 — the guard was real, the counter was not wired. A refusal counts;
    an allowed address does not."""
    from agents.core.security.ssrf import (
        blocked_requests,
        check_ssrf,
        reset_blocked_requests,
        resolve_and_validate,
    )

    reset_blocked_requests()
    assert blocked_requests() == 0
    resolve_and_validate("169.254.169.254")          # cloud metadata literal
    check_ssrf("http://10.0.0.1/x")                  # private range
    resolve_and_validate("8.8.8.8")                  # allowed — must NOT count

    monkeypatch.setattr(web, "orch", SimpleNamespace(security=_engine()))
    body = TestClient(web.app).get("/security/status").json()

    assert body["ssrf"]["blocked_requests"] == 2
    assert body["ssrf"]["available"] is True


def test_status_survives_no_orchestrator_at_all(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    resp = TestClient(web.app).get("/security/status")
    assert resp.status_code == 200
    assert resp.json()["guardrails"]["available"] is False
