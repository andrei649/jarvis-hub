"""H157 — every configuration key, from the UI: export, import, per-category reset.

``GET /api/admin/settings/export`` writes the declared settings as JSON for another box,
leaving out secrets and any value that looks like it holds a credential (and saying which
it left out). ``POST /api/admin/settings/import`` runs every key through the same
``validate_category`` a single write uses, refuses an unknown key, and writes all of it or
none of it, in one transaction, with one audit row; ``dry_run`` shows what would change.
``POST /api/admin/settings/{category}/reset`` puts one category back to its declared
values, where the only reset used to be the global reseed.
"""

from __future__ import annotations

import json

import pytest

from agents.core import settings_db

GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db(force=True)
    return settings_db


def _value(cat, key):
    return settings_db.get_value(cat, key)


# ── export ───────────────────────────────────────────────────────────────────────

def test_export_holds_every_declared_setting_but_the_secret_ones(store):
    doc = store.export_settings()
    assert doc["format"] == "nerva-settings/1"
    exported = {(c, k) for c, keys in doc["settings"].items() for k in keys}
    declared = {(d["category"], d["key"]) for d in store.DEFAULTS}
    excluded = {tuple(e["setting"].split(".", 1)) for e in doc["excluded"]}
    assert exported | excluded == declared and not exported & excluded
    for key in store.SECRET_KEYS:
        assert all(key not in keys for keys in doc["settings"].values())


def test_export_leaves_out_ids_and_mcp_headers(store):
    doc = store.export_settings()
    excluded = {e["setting"] for e in doc["excluded"]}
    assert {"plugins.tuya_client_id", "plugins.gecko_ing_client_id", "mcp.servers"} <= excluded
    assert all(e["reason"] for e in doc["excluded"])


def test_a_value_that_looks_like_a_credential_is_left_out(store):
    store.put_category("skills", {"template_vars": {"owner": "Andrei", "gh": GH}})
    doc = store.export_settings()
    assert "template_vars" not in doc["settings"].get("skills", {})
    assert any(e["setting"] == "skills.template_vars" for e in doc["excluded"])
    assert GH not in json.dumps(doc)


def test_export_carries_the_stored_value(store):
    store.put_category("system", {"log_to_file": True})
    assert store.export_settings()["settings"]["system"]["log_to_file"] is True


# ── import ───────────────────────────────────────────────────────────────────────

def test_an_export_imports_back_as_no_change(store):
    doc = store.export_settings()
    changes, errors = store.plan_import(doc)
    assert errors == [] and changes == {}


def test_import_writes_every_valid_change(store):
    changes, errors = store.plan_import({"settings": {"system": {"log_to_file": True},
                                                      "security": {"sandbox_temp_max_age_hours": 24}}})
    assert errors == [] and changes == {"system": {"log_to_file": True},
                                        "security": {"sandbox_temp_max_age_hours": 24}}
    assert store.apply_import(changes) == 2
    assert _value("system", "log_to_file") is True and _value("security", "sandbox_temp_max_age_hours") == 24


@pytest.mark.parametrize("doc,needle", [
    ({"settings": {"system": {"no_such_key": 1}}}, "system.no_such_key: unknown setting"),
    ({"settings": {"nope": {"x": 1}}}, "nope.x: unknown setting"),
    ({"settings": {"security": {"sandbox_temp_max_age_hours": 0}}}, "sandbox_temp_max_age_hours"),
    ({"settings": {"system": "yes"}}, "system: expected an object"),
    ({"settings": []}, "settings: expected an object"),
    ([], "expected an object"),
    ({"format": "other/9", "settings": {}}, "format"),
])
def test_import_refuses_what_a_single_write_would_refuse(store, doc, needle):
    changes, errors = store.plan_import(doc)
    assert any(needle in e for e in errors), errors


def test_one_bad_key_writes_nothing(store):
    doc = {"settings": {"system": {"log_to_file": True},
                        "security": {"sandbox_temp_max_age_hours": 0}}}
    changes, errors = store.plan_import(doc)
    assert errors
    assert _value("system", "log_to_file") is False


def test_the_write_is_one_transaction(store, monkeypatch):
    real = store._encrypt_if_secret
    calls = []

    def fail_on_second(key, value):
        calls.append(key)
        if len(calls) == 2:
            raise RuntimeError("disk gone")
        return real(key, value)

    monkeypatch.setattr(store, "_encrypt_if_secret", fail_on_second)
    with pytest.raises(RuntimeError):
        store.apply_import({"system": {"log_to_file": True}, "security": {"sandbox_temp_max_age_hours": 24}})
    assert _value("system", "log_to_file") is False
    assert _value("security", "sandbox_temp_max_age_hours") == 72


def test_a_posture_flag_goes_through_the_schema(store):
    changes, errors = store.plan_import({"settings": {"product": {"posture": "anything-goes"}}})
    assert errors and not changes


def test_a_secret_imports_encrypted_and_never_echoes(store):
    changes, errors = store.plan_import({"settings": {"plugins": {"tuya_secret": "s3cr3t-value"}}})
    assert errors == []
    preview = store.describe_changes(changes)
    assert preview == [{"setting": "plugins.tuya_secret", "from": "(secret)", "to": "(secret)"}]
    store.apply_import(changes)
    assert _value("plugins", "tuya_secret") == "s3cr3t-value"
    import sqlite3

    raw = sqlite3.connect(str(store.DB_PATH)).execute(
        "SELECT value FROM settings WHERE key='tuya_secret'").fetchone()[0]
    assert "s3cr3t-value" not in raw


def test_import_is_bounded(store):
    doc = {"settings": {f"c{n}": {f"k{m}": 1 for m in range(50)} for n in range(50)}}
    changes, errors = store.plan_import(doc)
    assert any("too many settings" in e for e in errors) and not changes


# ── reset one category ───────────────────────────────────────────────────────────

def test_reset_puts_one_category_back_and_leaves_the_rest(store):
    store.put_category("system", {"log_to_file": True, "log_level": "DEBUG"})
    store.put_category("security", {"sandbox_temp_max_age_hours": 24})
    changed = store.reset_category("system")
    assert set(changed) == {"log_to_file", "log_level"}
    assert _value("system", "log_to_file") is False and _value("system", "log_level") == "INFO"
    assert _value("security", "sandbox_temp_max_age_hours") == 24
    assert store.reset_category("system") == []
    assert store.reset_category("no-such-category") is None


# ── the routes ───────────────────────────────────────────────────────────────────

ADMIN = {"X-Admin-Token": "adm-h157"}


@pytest.fixture
def client(store, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h157")
    rows = []

    class Audit:
        def log(self, event):
            rows.append(event)

    from agents.core.routers import admin

    monkeypatch.setattr(admin, "get_orch", lambda: type("O", (), {"audit": Audit()})())
    c = TestClient(web.app)
    c.rows = rows
    return c


@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/settings/export"),
    ("post", "/api/admin/settings/import"),
    ("post", "/api/admin/settings/system/reset"),
])
def test_every_route_is_admin_only(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_the_export_route_is_not_taken_for_a_category(client):
    got = client.get("/api/admin/settings/export", headers=ADMIN)
    assert got.status_code == 200 and got.json()["format"] == "nerva-settings/1"
    assert "no-store" in got.headers.get("cache-control", "")
    assert "attachment" in got.headers.get("content-disposition", "")


def test_import_route_previews_then_applies_with_one_audit_row(client):
    doc = {"settings": {"system": {"log_to_file": True}, "security": {"sandbox_temp_max_age_hours": 24}}}
    dry = client.post("/api/admin/settings/import", json={**doc, "dry_run": True}, headers=ADMIN).json()
    assert dry["dry_run"] is True and dry["count"] == 2 and _value("system", "log_to_file") is False
    assert {"setting": "system.log_to_file", "from": False, "to": True} in dry["changes"]
    assert client.rows == []
    done = client.post("/api/admin/settings/import", json=doc, headers=ADMIN).json()
    assert done["ok"] is True and done["updated"] == 2 and _value("system", "log_to_file") is True
    assert len(client.rows) == 1
    preview = client.rows[0].content_preview
    assert "settings imported" in preview and "system.log_to_file" in preview and "log_to_file=true" in preview


def test_import_route_refuses_with_every_reason_and_writes_nothing(client):
    doc = {"settings": {"system": {"log_to_file": True, "bogus": 1},
                        "security": {"sandbox_temp_max_age_hours": 0}}}
    got = client.post("/api/admin/settings/import", json=doc, headers=ADMIN)
    assert got.status_code == 422
    details = got.json()["details"]
    assert any("system.bogus" in d for d in details) and any("sandbox_temp_max_age_hours" in d for d in details)
    assert _value("system", "log_to_file") is False and client.rows == []


def test_an_import_with_nothing_to_change_writes_no_row(client):
    got = client.post("/api/admin/settings/import", json={"settings": {"system": {"log_to_file": False}}},
                      headers=ADMIN).json()
    assert got["updated"] == 0 and client.rows == []


def test_reset_route(client):
    settings_db.put_category("system", {"log_to_file": True})
    got = client.post("/api/admin/settings/system/reset", json={}, headers=ADMIN)
    assert got.status_code == 200 and got.json()["reset"] == ["log_to_file"]
    assert _value("system", "log_to_file") is False
    assert len(client.rows) == 1 and "settings.system reset to defaults" in client.rows[0].content_preview
    assert client.post("/api/admin/settings/nope/reset", json={}, headers=ADMIN).status_code == 404


def test_a_value_is_left_out_when_the_scanner_cannot_run(store, monkeypatch):
    from agents.core.security import log_redaction

    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("no scanner")

    monkeypatch.setattr(log_redaction, "SecretRedactionFilter", Broken)
    store.put_category("skills", {"template_vars": {"owner": "Andrei"}})
    doc = store.export_settings()
    assert "template_vars" not in doc["settings"].get("skills", {})
    assert store.export_settings()["settings"]["system"]["log_level"] == "INFO"
