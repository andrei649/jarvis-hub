"""H259 — a settings reset shows what it would do, keeps secrets, and can be undone.

The HUD could not tell a changed setting from its default: every row now carries its
declared ``default`` (never for a secret). A reset — one category, or every category
through the old ``reseed`` — previews what it would change (``dry_run``), leaves the
secrets alone, and records what it replaced, so ``POST /api/admin/settings/undo`` puts
it back. A setting changed since the reset is not overwritten by the undo, and is named.
The reseed no longer deletes the store: it used to wipe every setting, secrets included,
with no preview and no way back.
"""

from __future__ import annotations

import pytest

from agents.core import settings_db

ADMIN = {"X-Admin-Token": "adm-h259"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db(force=True)
    return settings_db


def _value(cat, key):
    return settings_db.get_value(cat, key)


def _secret():
    """A declared secret setting (category, key)."""
    for spec in settings_db.DEFAULTS:
        if settings_db.is_secret_setting(spec["category"], spec["key"]) and spec.get("kind") in ("password", "text", "secret"):
            return spec["category"], spec["key"]
    raise AssertionError("no declared secret setting")


# ── the defaults, for the HUD ───────────────────────────────────────────────────

def test_every_declared_row_carries_its_default_but_a_secret(store):
    rows = store.get_all()
    for cat, items in rows.items():
        for it in items:
            spec = store._SPEC.get((cat, it["key"]))
            if spec is None or store.is_secret_setting(cat, it["key"]):
                assert "default" not in it, f"{cat}.{it['key']}"
            else:
                assert it["default"] == spec["value"], f"{cat}.{it['key']}"
    assert {it["key"]: it for it in store.get_category("system")}["log_level"]["default"] == "INFO"


def test_a_changed_row_says_so_against_its_default(store):
    store.put_category("system", {"log_level": "DEBUG"})
    row = {it["key"]: it for it in store.get_all()["system"]}["log_level"]
    assert row["value"] == "DEBUG" and row["default"] == "INFO" and row["source"] == "set"


# ── planning and previewing a reset ─────────────────────────────────────────────

def test_a_reset_plan_names_only_what_moves(store):
    store.put_category("system", {"log_to_file": True})
    assert store.plan_reset("system") == {"system": {"log_to_file": False}}
    assert store.plan_reset("nope") is None
    store.put_category("security", {"sandbox_temp_max_age_hours": 24})
    everything = store.plan_reset(None)
    assert everything["system"] == {"log_to_file": False}
    assert everything["security"] == {"sandbox_temp_max_age_hours": settings_db._SPEC[("security", "sandbox_temp_max_age_hours")]["value"]}
    assert set(everything) == {"system", "security"}


def test_a_reset_plan_never_moves_a_secret(store):
    cat, key = _secret()
    store.put_category(cat, {key: "sk-this-is-mine"})
    assert key not in (store.plan_reset(cat) or {}).get(cat, {})
    assert key not in (store.plan_reset(None) or {}).get(cat, {})


# ── the undo ────────────────────────────────────────────────────────────────────

def test_a_reset_is_recorded_and_undone(store):
    store.put_category("system", {"log_to_file": True, "log_level": "DEBUG"})
    moved, snap = store.reset_settings("system")
    assert moved == {"system": {"log_level": "INFO", "log_to_file": False}} and isinstance(snap, int)
    assert _value("system", "log_level") == "INFO"
    undone = store.undo_last_reset()
    assert undone["id"] == snap and undone["scope"] == "system"
    assert undone["restored"] == ["system.log_level", "system.log_to_file"] and undone["skipped"] == []
    assert _value("system", "log_level") == "DEBUG" and _value("system", "log_to_file") is True
    assert store.undo_last_reset() is None                       # nothing left to undo


def test_a_reset_and_its_undo_tell_the_listeners_what_they_wrote(store, monkeypatch):
    heard = []
    monkeypatch.setattr(settings_db, "_change_listeners", [lambda cat, values: heard.append((cat, values))])
    store.put_category("webhooks", {"receiver_enabled": False})
    heard.clear()
    store.reset_settings("webhooks")
    assert heard == [("webhooks", {"receiver_enabled": True})]     # the receiver hears it is on again
    heard.clear()
    store.undo_last_reset()
    assert heard == [("webhooks", {"receiver_enabled": False})]


def test_a_reset_that_moves_nothing_records_nothing(store):
    moved, snap = store.reset_settings("system")
    assert moved == {} and snap is None
    assert store.list_resets() == [] and store.undo_last_reset() is None


def test_the_undo_leaves_a_setting_changed_since_and_names_it(store):
    store.put_category("system", {"log_to_file": True, "log_level": "DEBUG"})
    store.reset_settings("system")
    store.put_category("system", {"log_level": "WARNING"})       # the owner moved on
    undone = store.undo_last_reset()
    assert undone["restored"] == ["system.log_to_file"]
    assert undone["skipped"] == [{"setting": "system.log_level", "reason": "changed since the reset"}]
    assert _value("system", "log_level") == "WARNING" and _value("system", "log_to_file") is True


def test_the_undo_refuses_a_value_that_is_no_longer_valid(store, monkeypatch):
    store.put_category("system", {"log_level": "DEBUG"})
    store.reset_settings("system")
    spec = dict(settings_db._SPEC[("system", "log_level")])
    spec["opts"] = [o for o in spec.get("opts", []) if o != "DEBUG"]
    monkeypatch.setitem(settings_db._SPEC, ("system", "log_level"), spec)
    monkeypatch.setattr(settings_db, "DEFAULTS",
                        [spec if (d["category"], d["key"]) == ("system", "log_level") else d for d in settings_db.DEFAULTS])
    undone = store.undo_last_reset()
    assert undone["restored"] == []
    assert undone["skipped"][0]["setting"] == "system.log_level"
    assert undone["skipped"][0]["reason"].startswith("no longer valid")
    assert _value("system", "log_level") == "INFO"


def test_the_undo_leaves_a_setting_no_longer_declared(store, monkeypatch):
    store.put_category("system", {"log_level": "DEBUG", "log_to_file": True})
    store.reset_settings("system")
    monkeypatch.delitem(settings_db._SPEC, ("system", "log_level"))     # a later build dropped it
    undone = store.undo_last_reset()
    assert undone["restored"] == ["system.log_to_file"]
    assert undone["skipped"] == [{"setting": "system.log_level", "reason": "no longer declared"}]
    assert _value("system", "log_to_file") is True


def test_undo_takes_the_latest_reset_first(store):
    store.put_category("system", {"log_to_file": True})
    first = store.reset_settings("system")[1]
    store.put_category("security", {"sandbox_temp_max_age_hours": 24})
    second = store.reset_settings("security")[1]
    assert store.undo_last_reset()["id"] == second
    assert _value("security", "sandbox_temp_max_age_hours") == 24 and _value("system", "log_to_file") is False
    assert store.undo_last_reset()["id"] == first
    assert _value("system", "log_to_file") is True


def test_the_list_names_settings_never_values_and_keeps_twenty(store):
    for n in range(store.RESETS_KEPT + 3):
        store.put_category("system", {"log_level": "DEBUG" if n % 2 else "WARNING"})
        store.reset_settings("system")
    resets = store.list_resets()
    assert store.RESETS_KEPT == 20 and len(resets) == 20
    assert resets[0]["id"] > resets[-1]["id"]                     # newest first
    assert resets[0]["settings"] == ["system.log_level"] and resets[0]["undone"] is False
    assert "DEBUG" not in repr(resets) and "WARNING" not in repr(resets)
    store.undo_last_reset()
    assert [r["undone"] for r in store.list_resets()[:2]] == [True, False]


def test_a_reset_of_everything_keeps_secrets_and_undeclared_rows(store):
    cat, key = _secret()
    store.put_category(cat, {key: "sk-this-is-mine"})
    conn = store.get_conn()
    with conn:
        conn.execute("INSERT INTO settings (category, key, value, label, kind, opts) VALUES ('x','y','1','','text','[]')")
    conn.close()
    store.put_category("system", {"log_to_file": True})
    moved, snap = store.reset_settings(None)
    assert moved["system"] == {"log_to_file": False} and snap is not None
    assert _value(cat, key) == "sk-this-is-mine"
    assert _value("x", "y") == 1
    assert store.list_resets()[0]["scope"] == "all"


# ── the routes ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(store, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h259")
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
    ("post", "/api/admin/settings/undo"),
    ("get", "/api/admin/settings/resets"),
    ("post", "/api/admin/settings/reseed"),
])
def test_the_new_routes_are_admin_only(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_a_category_reset_previews_then_applies_and_says_how_to_undo(client):
    settings_db.put_category("system", {"log_to_file": True})
    dry = client.post("/api/admin/settings/system/reset", json={"dry_run": True}, headers=ADMIN).json()
    assert dry["dry_run"] is True and dry["changes"] == [{"setting": "system.log_to_file", "from": True, "to": False}]
    assert _value("system", "log_to_file") is True and client.rows == [] and settings_db.list_resets() == []
    done = client.post("/api/admin/settings/system/reset", json={}, headers=ADMIN).json()
    assert done["reset"] == ["log_to_file"] and isinstance(done["undo"], int)
    assert _value("system", "log_to_file") is False


def test_only_a_json_true_makes_a_dry_run_and_the_request_is_bounded(client):
    settings_db.put_category("system", {"log_to_file": True})
    big = client.post("/api/admin/settings/system/reset", json={"dry_run": True, "pad": "x" * 5000}, headers=ADMIN)
    assert big.status_code == 413 and _value("system", "log_to_file") is True
    real = client.post("/api/admin/settings/system/reset", json={"dry_run": "yes"}, headers=ADMIN).json()
    assert real["reset"] == ["log_to_file"] and _value("system", "log_to_file") is False


def test_the_reset_preview_hides_a_credential_shaped_value(client):
    gh = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    settings_db.put_category("skills", {"template_vars": {"gh": gh}})
    dry = client.post("/api/admin/settings/skills/reset", json={"dry_run": True}, headers=ADMIN)
    assert gh not in dry.text
    assert {"setting": "skills.template_vars", "from": "(hidden)", "to": settings_db._SPEC[("skills", "template_vars")]["value"]} in dry.json()["changes"]


def test_the_reseed_is_a_json_request_from_this_origin(client):
    assert client.post("/api/admin/settings/reseed", headers=ADMIN).status_code == 415
    cross = client.post("/api/admin/settings/reseed", json={}, headers={**ADMIN, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403


def test_the_reseed_previews_keeps_secrets_and_can_be_undone(client):
    cat, key = _secret()
    settings_db.put_category(cat, {key: "sk-this-is-mine"})
    settings_db.put_category("system", {"log_to_file": True})
    dry = client.post("/api/admin/settings/reseed", json={"dry_run": True}, headers=ADMIN).json()
    assert dry["dry_run"] is True and {"setting": "system.log_to_file", "from": True, "to": False} in dry["changes"]
    assert f"{cat}.{key}" in dry["kept"] and "sk-this-is-mine" not in repr(dry)
    assert "system.log_level" not in dry["kept"]                    # only secrets are kept
    assert _value("system", "log_to_file") is True and client.rows == []
    done = client.post("/api/admin/settings/reseed", json={}, headers=ADMIN).json()
    assert done["ok"] is True and "system.log_to_file" in done["reset"] and isinstance(done["undo"], int)
    assert _value(cat, key) == "sk-this-is-mine" and _value("system", "log_to_file") is False
    assert len(client.rows) == 1 and "every category" in client.rows[0].content_preview
    assert "sk-this-is-mine" not in client.rows[0].content_preview
    listed = client.get("/api/admin/settings/resets", headers=ADMIN)
    assert listed.status_code == 200 and listed.json()["resets"][0]["scope"] == "all"
    assert "no-store" in listed.headers.get("cache-control", "")
    undone = client.post("/api/admin/settings/undo", json={}, headers=ADMIN).json()
    assert undone["ok"] is True and "system.log_to_file" in undone["restored"]
    assert _value("system", "log_to_file") is True
    assert len(client.rows) == 2 and "reset undone" in client.rows[1].content_preview


def test_an_undo_with_nothing_to_undo_says_so(client):
    got = client.post("/api/admin/settings/undo", json={}, headers=ADMIN)
    assert got.status_code == 404 and got.json()["error"] == "nothing to undo" and client.rows == []


def test_the_undo_is_a_json_request_from_this_origin(client):
    assert client.post("/api/admin/settings/undo", headers=ADMIN).status_code == 415
    cross = client.post("/api/admin/settings/undo", json={}, headers={**ADMIN, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403


def test_the_resets_route_is_not_taken_for_a_category(client):
    got = client.get("/api/admin/settings/resets", headers=ADMIN)
    assert got.status_code == 200 and got.json() == {"resets": []}
