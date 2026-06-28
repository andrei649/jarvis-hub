"""0.55 — diagnostic support bundle: non-sensitive aggregates, defensive assembly."""

import json

from agents.core import support_bundle


def test_bundle_has_all_sections_and_is_serializable():
    b = support_bundle.build_bundle(orch=None, now_iso="2026-06-28T00:00:00Z")
    assert set(b) >= {"meta", "posture", "capabilities", "egress", "audit", "routes"}
    json.dumps(b)  # must be plain-JSON (no exotic objects leaking through)


def test_meta_carries_version_and_generated_at():
    b = support_bundle.build_bundle(now_iso="STAMP")
    assert b["meta"]["generated_at"] == "STAMP"
    assert b["meta"].get("version") and b["meta"]["platform"]


def test_posture_reflects_default_off_hardened_and_balanced_profile(monkeypatch):
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    monkeypatch.delenv("JARVIS_SYSTEM_PROFILE", raising=False)
    p = support_bundle.build_bundle()["posture"]
    assert p["hardened"]["enabled"] is False
    assert p["system_profile"]["active"] == "balanced"


def test_audit_uses_a_fake_orch_and_counts_by_type_only():
    class _Ev:
        def __init__(self, t): self.event_type = t

    class _Audit:
        def query(self, limit=100):
            return [_Ev("scan"), _Ev("scan"), _Ev("kernel_grant")]
        def verify_chain(self):
            return (True, None)

    class _Orch:
        audit = _Audit()

    a = support_bundle.build_bundle(_Orch())["audit"]
    assert a["recent_event_counts"] == {"scan": 2, "kernel_grant": 1}
    assert a["window"] == 3 and a["chain_ok"] is True
    # never leaks content/preview — only counts + integrity
    assert set(a) <= {"recent_event_counts", "window", "chain_ok", "chain_broken_at"}


def test_sections_degrade_to_unavailable_not_crash():
    class _Boom:
        @property
        def audit(self):
            raise RuntimeError("down")

    b = support_bundle.build_bundle(_Boom())
    assert b["audit"] == {"error": "unavailable"}      # one bad source never breaks the bundle
    assert "meta" in b and b["meta"]["platform"]


def test_no_obviously_sensitive_keys_anywhere():
    blob = json.dumps(support_bundle.build_bundle()).lower()
    for bad in ("token", "secret", "password", "api_key", "authorization", "private_key"):
        assert bad not in blob
