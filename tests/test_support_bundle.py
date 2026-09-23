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
    assert p["product_posture"]["name"] == "off"
    assert "memory.recall_enabled" in p["product_posture"]["flags"]
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


def test_diagnostics_stay_local_there_is_no_upload_path():
    """H242: Hermes's ``diagnostics.share_nous`` uploads a debug bundle to the vendor;
    Nerva refused that path. The bundle is assembled in-process and served to the owner
    over one admin GET — no network client in either module, no write verb on the route."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    network = {"urllib", "http", "httpx", "requests", "aiohttp", "socket", "ftplib", "smtplib"}
    for rel in ("agents/core/support_bundle.py", "agents/core/routers/support.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        assert not imported & network, (rel, imported & network)

    from agents.core.routers.support import router

    verbs = {(method, route.path) for route in router.routes for method in route.methods}
    assert verbs == {("GET", "/api/support/bundle")}
