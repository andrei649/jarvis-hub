"""H157, the first review (review-H157) — its findings, pinned.

- M1: the import parsed any body as JSON, so on a default install (the admin guard
  trusts loopback) a page the owner visited could post a plain-text import. The import
  and the reset take only a JSON request (which a browser must pre-check), and a
  request the browser marks cross-site is refused.
- M2: a password in a URL (``http://u:pw@host``) was exported; it is a credential now.
- m1/m7: NaN, Infinity and nesting too deep are refused (422), never stored.
- m2: ``mcp.servers`` entries need a name, and the loader skips one without.
- m4: 2000 and 2000.0 are the same number; m5: a reset keeps secrets and says so.
- m6: survivors (a credential in a list, the change listeners, the 1 MB bound).
- nits: the preview never echoes a credential-shaped value; the posture's settings are
  named; the reset is no-store; only a JSON ``true`` makes a dry run.
"""

from __future__ import annotations

import json

import pytest

from agents.core import settings_db

GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
ADMIN = {"X-Admin-Token": "adm-h157b"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db(force=True)
    return settings_db


@pytest.fixture
def client(store, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import admin

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h157b")
    rows = []

    class Audit:
        def log(self, event):
            rows.append(event)

    monkeypatch.setattr(admin, "get_orch", lambda: type("O", (), {"audit": Audit()})())
    c = TestClient(web.app)
    c.rows = rows
    return c


def _value(cat, key):
    return settings_db.get_value(cat, key)


# ── M1: JSON only, never cross-site ──────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/admin/settings/import", "/api/admin/settings/system/reset"])
@pytest.mark.parametrize("kind", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", ""])
def test_a_write_that_is_not_json_is_refused(client, path, kind):
    settings_db.put_category("system", {"log_to_file": True})
    body = json.dumps({"settings": {"security": {"scan_input": False}}})
    got = client.post(path, content=body, headers={**ADMIN, "Content-Type": kind} if kind else ADMIN)
    assert got.status_code == 415
    assert _value("security", "scan_input") is True and _value("system", "log_to_file") is True
    assert client.rows == []


@pytest.mark.parametrize("path", ["/api/admin/settings/import", "/api/admin/settings/system/reset"])
def test_a_write_the_browser_marks_cross_site_is_refused(client, path):
    got = client.post(path, json={"settings": {"security": {"scan_input": False}}},
                      headers={**ADMIN, "Sec-Fetch-Site": "cross-site"})
    assert got.status_code == 403 and _value("security", "scan_input") is True


def test_a_same_origin_json_write_still_works(client):
    got = client.post("/api/admin/settings/import", json={"settings": {"system": {"log_to_file": True}}},
                      headers={**ADMIN, "Sec-Fetch-Site": "same-origin"})
    assert got.status_code == 200 and _value("system", "log_to_file") is True


# ── M2: a password in a URL ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["http://admin:pw@lmstudio.local:1234", "https://u:p%40ss@host/x"])
def test_a_url_with_a_password_is_never_exported(store, url):
    store.put_category("llm", {"lm_studio_url": url})
    doc = store.export_settings()
    assert "lm_studio_url" not in doc["settings"].get("llm", {})
    assert any(e["setting"] == "llm.lm_studio_url" for e in doc["excluded"])
    assert url not in json.dumps(doc)


def test_a_url_without_a_password_is_exported(store):
    store.put_category("llm", {"lm_studio_url": "http://user@lmstudio.local:1234"})
    assert store.export_settings()["settings"]["llm"]["lm_studio_url"] == "http://user@lmstudio.local:1234"


def test_a_credential_in_a_list_setting_is_left_out(store):
    store.put_category("general", {"wake_words": ["nerva", GH]})
    doc = store.export_settings()
    assert "wake_words" not in doc["settings"].get("general", {}) and GH not in json.dumps(doc)


def test_the_preview_never_echoes_a_credential_shaped_value(store):
    store.put_category("skills", {"template_vars": {"gh": GH}})
    changes, errors = store.plan_import({"settings": {"skills": {"template_vars": {}},
                                                      "llm": {"lm_studio_url": "http://a:b@h"}}})
    preview = json.dumps(store.describe_changes(changes))
    assert errors == [] and GH not in preview and "a:b@h" not in preview and "(hidden)" in preview


# ── m1 / m7: values that cannot be stored ────────────────────────────────────────

def test_nan_infinity_and_deep_nesting_are_refused(client):
    for body in ('{"settings": {"skills": {"template_vars": {"x": NaN}}}}',
                 '{"settings": {"skills": {"template_vars": {"x": Infinity}}}}'):
        got = client.post("/api/admin/settings/import", content=body,
                          headers={**ADMIN, "Content-Type": "application/json"})
        assert got.status_code == 422 and "finite" in json.dumps(got.json())
    deep = '{"settings": {"skills": {"template_vars": ' + '[' * 5000 + ']' * 5000 + '}}}'
    got = client.post("/api/admin/settings/import", content=deep,
                      headers={**ADMIN, "Content-Type": "application/json"})
    assert got.status_code == 422
    assert client.get("/api/admin/settings", headers=ADMIN).status_code == 200


# ── m2: MCP servers ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [[{}], [{"name": ""}], ["x"], {"name": "a"}])
def test_an_mcp_server_without_a_name_is_refused(store, value):
    assert store.validate_category("mcp", {"servers": value})
    _, errors = store.plan_import({"settings": {"mcp": {"servers": value}}})
    assert errors


def test_the_mcp_loader_skips_an_entry_without_a_name():
    from agents.core.mcp.client import MCPManager

    client = MCPManager()
    client.load_from_config([{}, "x", {"name": ""}, {"name": "ok", "command": "true"}])
    assert list(client.servers) == ["ok"]


# ── m4 / m5 ──────────────────────────────────────────────────────────────────────

def test_a_float_that_equals_the_stored_int_is_no_change(store):
    changes, errors = store.plan_import({"settings": {"memory": {"compression_max_tokens": 2000.0}}})
    assert errors == [] and changes == {}
    changes, _ = store.plan_import({"settings": {"system": {"log_to_file": 0}}})
    assert changes or store.validate_category("system", {"log_to_file": 0})


def test_a_reset_keeps_secrets_and_says_so(client):
    settings_db.put_category("plugins", {"tuya_secret": "s3cr3t-value", "tuya_client_id": "cid-123456"})
    got = client.post("/api/admin/settings/plugins/reset", json={}, headers=ADMIN)
    body = got.json()
    assert "tuya_secret" in body["kept"] and "tuya_client_id" in body["kept"]
    assert _value("plugins", "tuya_secret") == "s3cr3t-value"
    assert "no-store" in got.headers.get("cache-control", "")


def test_a_reset_names_what_the_posture_still_forces(client):
    settings_db.put_category("product", {"posture": "design_partner"})
    body = client.post("/api/admin/settings/memory/reset", json={}, headers=ADMIN).json()
    assert "recall_enabled" in body["overridden"]


# ── m6: survivors ────────────────────────────────────────────────────────────────

def test_an_import_notifies_the_change_listeners(store):
    seen = []
    listener = lambda cat, values: seen.append((cat, dict(values or {})))  # noqa: E731
    store.on_change(listener)
    try:
        store.apply_import({"system": {"log_to_file": True}})
    finally:
        store._change_listeners.remove(listener)
    assert ("system", {"log_to_file": True}) in seen


def test_the_body_is_bounded_at_one_megabyte(client):
    body = '{"settings": {}, "pad": "' + "x" * 1_100_000 + '"}'
    got = client.post("/api/admin/settings/import", content=body,
                      headers={**ADMIN, "Content-Type": "application/json"})
    assert got.status_code == 413


def test_only_a_json_true_makes_a_dry_run(client):
    got = client.post("/api/admin/settings/import",
                      json={"settings": {"system": {"log_to_file": True}}, "dry_run": "true"},
                      headers=ADMIN).json()
    assert got.get("dry_run") is not True and _value("system", "log_to_file") is True


def test_a_url_with_a_password_inside_a_list_is_left_out(store):
    store.put_category("general", {"wake_words": ["nerva", "http://a:pw@host"]})
    doc = store.export_settings()
    assert "wake_words" not in doc["settings"].get("general", {})


def test_a_chunked_body_is_bounded_too(client):
    def chunks():
        yield b'{"settings": {}, "pad": "'
        for _ in range(12):
            yield b"x" * 100_000
        yield b'"}'

    got = client.post("/api/admin/settings/import", content=chunks(),
                      headers={**ADMIN, "Content-Type": "application/json"})
    assert got.status_code == 413
