"""AUD-8 — admin settings writes are schema-validated and audited (F10).

A malformed value (wrong type, or off a select's allow-list) is rejected with 422
before it can corrupt a setting the rest of the system reads back and trusts, and
every accepted change is recorded in the audit log as the changed KEY NAMES only
(never values, so a secret that was just set can't leak through the audit row).
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db


# ── validate_category ──────────────────────────────────────────────
def test_valid_values_pass():
    assert settings_db.validate_category("security", {
        "guardrails_mode": "BLOCK",   # select ∈ opts
        "scan_input": True,           # toggle
        "sandbox_timeout": 30,        # number
    }) == []


def test_bad_enum_rejected():
    errs = settings_db.validate_category("security", {"guardrails_mode": "HACK"})
    assert errs and "guardrails_mode" in errs[0]


def test_bad_type_rejected():
    assert settings_db.validate_category("security", {"scan_input": "yes"})       # toggle wants bool
    assert settings_db.validate_category("security", {"sandbox_timeout": "lots"})  # number wants num


def test_bool_is_not_a_number():
    # bool is an int subclass — a toggle value must not pass a number field.
    assert settings_db.validate_category("security", {"sandbox_timeout": True})


def test_unknown_keys_are_not_errors():
    # put_category ignores unknown keys, so they aren't a validation failure.
    assert settings_db.validate_category("security", {"not_a_real_key": 123}) == []


def test_tags_must_be_list_of_strings():
    assert settings_db.validate_category("general", {"wake_words": ["jarvis", "hub"]}) == []
    assert settings_db.validate_category("general", {"wake_words": "jarvis"})
    assert settings_db.validate_category("general", {"wake_words": [1, 2]})


# ── route: 422 + audit ─────────────────────────────────────────────
class _AuditSpy:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(event)


class _Orch:
    def __init__(self):
        self.audit = _AuditSpy()


def _client_and_guard():
    from fastapi.testclient import TestClient
    from agents import web
    from agents.core.routers import _deps
    web.app.dependency_overrides[_deps.admin_guard] = lambda: None
    return TestClient(web.app), web, _deps


def test_route_rejects_bad_value_with_422():
    client, web, _deps = _client_and_guard()
    try:
        resp = client.put("/api/admin/settings/security", json={"values": {"guardrails_mode": "HACK"}})
        assert resp.status_code == 422
        body = resp.json()
        assert any("guardrails_mode" in d for d in body["details"])
    finally:
        web.app.dependency_overrides.pop(_deps.admin_guard, None)


def test_route_accepts_good_value_and_audits(monkeypatch):
    client, web, _deps = _client_and_guard()
    spy_orch = _Orch()
    monkeypatch.setattr(web, "orch", spy_orch)
    try:
        resp = client.put("/api/admin/settings/security", json={"values": {"scan_input": False}})
        assert resp.status_code == 200
        assert resp.json()["updated"] >= 1
        # exactly one SETTINGS_CHANGE event, naming the key but not implying a value
        from agents.core.security.types import SecurityEventType
        evs = [e for e in spy_orch.audit.events
               if e.event_type == SecurityEventType.SETTINGS_CHANGE]
        assert len(evs) == 1
        assert "scan_input" in evs[0].content_preview
    finally:
        web.app.dependency_overrides.pop(_deps.admin_guard, None)
