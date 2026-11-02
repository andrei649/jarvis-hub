"""H255 — ``${NAME}`` / ``${env:NAME}`` in settings values (Hermes config-b.core.env_interpolation).

One test per clause of the pinned contract, through the product's own entry points
(``settings_db`` readers and writers, the orchestrator's runtime settings, the admin
settings routes, ``nerva config``, export and import):

* a string value is expanded against the process environment when it is loaded for use,
  recursively, keys and non-strings untouched; the stored row and every view keep the
  reference;
* an unset ``${env:NAME}`` stays as written and a WARNING names ``.env`` (once while it
  stays unset); any other ``${source:…}`` prefix stays as written and warns once;
* the runtime-settings load cache loads again when a variable it names changes;
* a save writes the reference back, never what it expands to (also after a rotation, in
  nested values, from the admin route, the CLI and an import);
* an expanded secret is never persisted or logged; literal settings are never expanded.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import sqlite3

import pytest

from agents.core import settings_db

_KEY = base64.urlsafe_b64encode(b"h255-test-key-32-bytes-padding!!").decode()
SECRET = "h255-tuya-SECRET-value-9f3c"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_SECRET_KEY", _KEY)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(settings_db, "_field_cipher", None)
    for name in ("H255_SECRET", "H255_ID", "H255_URL", "H255_WAKE", "H255_FONT", "H255_TRIG",
                 "H255_UNSET", "H255_MODEL"):
        monkeypatch.delenv(name, raising=False)
    try:  # the module this row adds; the entry-point tests below do not need it to exist
        from agents.core import settings_interpolation
        settings_interpolation.reset()
    except ImportError:
        pass
    settings_db.ensure_initialized()
    return settings_db


def _raw(cat: str, key: str) -> str:
    conn = sqlite3.connect(str(settings_db.DB_PATH))
    try:
        return conn.execute("SELECT value FROM settings WHERE category=? AND key=?", (cat, key)).fetchone()[0]
    finally:
        conn.close()


def _stored(cat: str, key: str):
    """The stored value, decrypted but not expanded."""
    return settings_db._decrypt_if_secret(json.loads(_raw(cat, key)))


def _whole_db_text() -> str:
    conn = sqlite3.connect(str(settings_db.DB_PATH))
    try:
        return "\n".join(str(row) for row in conn.execute("SELECT * FROM settings"))
    finally:
        conn.close()


# ── 1. expansion at load time ─────────────────────────────────────────────────


def test_expand_rules_strings_only_recursive_one_pass():
    from agents.core.settings_interpolation import expand

    env = {"A": "alpha", "B": "${A}", "SP": "spaced"}
    value = {"${A}": ["x-${A}", "${env:B}", 3, True, None, {"k": "${ env:SP }"}], "n": 1.5, "s": "${A}${A}"}
    out = expand(value, setting="t.v", environ=env)
    assert out == {"${A}": ["x-alpha", "${A}", 3, True, None, {"k": "spaced"}], "n": 1.5, "s": "alphaalpha"}
    assert value["${A}"][0] == "x-${A}"                  # a copy: the input is not changed


def test_get_value_and_read_setting_expand_while_the_row_keeps_the_reference(store, monkeypatch):
    monkeypatch.setenv("H255_ID", "tuya-client-42")
    monkeypatch.setenv("H255_URL", "http://lms.local:1234")
    store.put_category("plugins", {"tuya_client_id": "${env:H255_ID}"})
    store.put_category("llm", {"lm_studio_url": "${H255_URL}"})

    assert store.get_value("plugins", "tuya_client_id") == "tuya-client-42"
    assert store.read_setting("plugins", "tuya_client_id") == (True, "tuya-client-42")
    assert store.get_value("llm", "lm_studio_url") == "http://lms.local:1234"
    assert _stored("plugins", "tuya_client_id") == "${env:H255_ID}"
    assert _stored("llm", "lm_studio_url") == "${H255_URL}"


def test_a_secret_reference_is_encrypted_at_rest_and_expands_on_read(store, monkeypatch):
    monkeypatch.setenv("H255_SECRET", SECRET)
    store.put_category("plugins", {"tuya_secret": "${env:H255_SECRET}"})
    raw = _raw("plugins", "tuya_secret")
    assert raw.startswith('"' + store._ENC_PREFIX) and SECRET not in raw
    assert store.get_value("plugins", "tuya_secret") == SECRET
    assert _stored("plugins", "tuya_secret") == "${env:H255_SECRET}"


def test_views_show_the_reference_and_name_the_variable_never_its_value(store, monkeypatch):
    monkeypatch.setenv("H255_SECRET", SECRET)
    store.put_category("plugins", {"tuya_secret": "${env:H255_SECRET}", "tuya_client_id": "${env:H255_UNSET}"})
    rows = {r["key"]: r for r in store.get_category("plugins")}
    assert rows["tuya_secret"]["value"] == "${env:H255_SECRET}"
    assert rows["tuya_secret"]["env_refs"] == [{"name": "H255_SECRET", "set": True}]
    assert rows["tuya_client_id"]["env_refs"] == [{"name": "H255_UNSET", "set": False}]
    every = {r["key"]: r for r in store.get_all()["plugins"]}
    assert every["tuya_secret"]["value"] == "${env:H255_SECRET}"
    assert SECRET not in json.dumps(store.get_all())
    # the same rows as they are used (the runtime load)
    used = {r["key"]: r for r in store.interpolated(store.get_all())["plugins"]}
    assert used["tuya_secret"]["value"] == SECRET


def _bare_orchestrator():
    from agents.core import orchestrator as orch_mod

    o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    o._runtime_settings = {}
    o._env_ref_snapshot = {}
    return o


def test_the_runtime_settings_load_expands_references(store, monkeypatch):
    monkeypatch.setenv("H255_SECRET", SECRET)
    monkeypatch.setenv("H255_WAKE", "computer")
    store.put_category("plugins", {"tuya_secret": "${env:H255_SECRET}"})
    store.put_category("general", {"wake_words": ["nerva", "${env:H255_WAKE}"]})
    o = _bare_orchestrator()
    o.load_runtime_settings()
    assert o.get_setting("plugins.tuya_secret") == SECRET
    assert o.get_setting("general.wake_words") == ["nerva", "computer"]


def test_an_expansion_the_setting_would_refuse_stays_as_written(store, monkeypatch, caplog):
    store.put_category("sessions", {"reset_triggers": ["${env:H255_TRIG}"]})
    monkeypatch.setenv("H255_TRIG", "/fresh")
    assert store.get_value("sessions", "reset_triggers") == ["/fresh"]
    monkeypatch.setenv("H255_TRIG", "/" + "x" * 200)        # over the 120-character bound
    with caplog.at_level(logging.WARNING, logger="jarvis.settings"):
        assert store.get_value("sessions", "reset_triggers") == ["${env:H255_TRIG}"]
    assert "sessions.reset_triggers" in caplog.text and "x" * 50 not in caplog.text


# ── 2. unresolved env: refs and other source: prefixes ───────────────────────


def test_an_unset_env_reference_stays_literal_and_warns_once_naming_env(store, monkeypatch, caplog):
    store.put_category("plugins", {"tuya_client_id": "${env:H255_UNSET}"})
    with caplog.at_level(logging.WARNING, logger="jarvis.settings"):
        assert store.get_value("plugins", "tuya_client_id") == "${env:H255_UNSET}"
        assert store.get_value("plugins", "tuya_client_id") == "${env:H255_UNSET}"
    warned = [r for r in caplog.records if "H255_UNSET" in r.getMessage()]
    assert len(warned) == 1 and warned[0].levelno == logging.WARNING
    assert ".env" in warned[0].getMessage() and "plugins.tuya_client_id" in warned[0].getMessage()

    caplog.clear()
    monkeypatch.setenv("H255_UNSET", "now-set")
    assert store.get_value("plugins", "tuya_client_id") == "now-set"
    monkeypatch.delenv("H255_UNSET")
    with caplog.at_level(logging.WARNING, logger="jarvis.settings"):
        assert store.get_value("plugins", "tuya_client_id") == "${env:H255_UNSET}"
    assert len([r for r in caplog.records if "H255_UNSET" in r.getMessage()]) == 1   # unset again: warns again


def test_a_bare_reference_expands_and_stays_literal_silently_when_unset(store, monkeypatch, caplog):
    store.put_category("plugins", {"tuya_client_id": "${H255_UNSET}"})
    with caplog.at_level(logging.WARNING, logger="jarvis.settings"):
        assert store.get_value("plugins", "tuya_client_id") == "${H255_UNSET}"
    assert "H255_UNSET" not in caplog.text
    monkeypatch.setenv("H255_UNSET", "bare-resolved")
    assert store.get_value("plugins", "tuya_client_id") == "bare-resolved"


def test_another_source_prefix_stays_literal_and_warns_once_per_prefix(store, caplog):
    store.put_category("plugins", {"tuya_client_id": "${vault:secret/tuya}", "tuya_device_id": "${vault:other}",
                                   "notion_database_id": "${bitwarden:NOTION}"})
    with caplog.at_level(logging.WARNING, logger="jarvis.settings"):
        for _ in range(3):
            assert store.get_value("plugins", "tuya_client_id") == "${vault:secret/tuya}"
            assert store.get_value("plugins", "tuya_device_id") == "${vault:other}"
            assert store.get_value("plugins", "notion_database_id") == "${bitwarden:NOTION}"
    vault = [r for r in caplog.records if "${vault:" in r.getMessage()]
    bitwarden = [r for r in caplog.records if "${bitwarden:" in r.getMessage()]
    assert len(vault) == 1 and len(bitwarden) == 1
    assert "${env:NAME}" in vault[0].getMessage()


# ── 3. the load cache invalidates when a variable it names changes ───────────


def test_runtime_settings_reload_when_a_referenced_variable_changes(store, monkeypatch):
    from agents.core import orchestrator as orch_mod

    loads = []
    real = orch_mod._get_settings
    monkeypatch.setattr(orch_mod, "_get_settings", lambda: loads.append(1) or real())
    store.put_category("plugins", {"tuya_secret": "${env:H255_SECRET}"})
    o = _bare_orchestrator()
    o.load_runtime_settings()
    assert o.get_setting("plugins.tuya_secret") == "${env:H255_SECRET}" and len(loads) == 1

    monkeypatch.setenv("H255_SECRET", SECRET)               # a .env loaded late
    assert o.get_setting("plugins.tuya_secret") == SECRET and len(loads) == 2
    assert o.get_setting("plugins.tuya_secret") == SECRET and len(loads) == 2   # cached again

    monkeypatch.setenv("H255_SECRET", SECRET + "-rotated")  # rotated in the process
    assert o.get_setting("plugins.tuya_secret") == SECRET + "-rotated" and len(loads) == 3

    monkeypatch.setenv("H255_ID", "unrelated")              # a variable no setting names
    assert o.get_setting("plugins.tuya_secret") == SECRET + "-rotated" and len(loads) == 3

    monkeypatch.delenv("H255_SECRET")                       # unset again
    assert o.get_setting("plugins.tuya_secret") == "${env:H255_SECRET}" and len(loads) == 4


def test_snapshot_holds_digests_never_values():
    from agents.core.settings_interpolation import changed, snapshot

    snap = snapshot(["A", "B"], environ={"A": SECRET})
    assert SECRET not in json.dumps(snap) and snap["B"] is None
    assert not changed(snap, environ={"A": SECRET})
    assert changed(snap, environ={"A": SECRET, "B": ""})
    assert changed(snap, environ={})


# ── 4. a save writes the reference back, never the expanded value ────────────


def test_a_write_of_the_expanded_value_keeps_the_reference(store, monkeypatch, caplog):
    monkeypatch.setenv("H255_SECRET", SECRET)
    store.put_category("plugins", {"tuya_secret": "${env:H255_SECRET}"})
    with caplog.at_level(logging.DEBUG):
        loaded = store.get_value("plugins", "tuya_secret")
        assert loaded == SECRET
        store.put_category("plugins", {"tuya_secret": loaded})          # read, then saved as read
    assert _stored("plugins", "tuya_secret") == "${env:H255_SECRET}"
    assert SECRET not in _whole_db_text() and SECRET not in caplog.text


def test_the_reference_is_kept_after_the_variable_rotated(store, monkeypatch):
    monkeypatch.setenv("H255_SECRET", SECRET)
    store.put_category("plugins", {"tuya_secret": "${env:H255_SECRET}"})
    loaded = store.get_value("plugins", "tuya_secret")
    assert loaded == SECRET
    monkeypatch.setenv("H255_SECRET", "rotated-since")
    store.put_category("plugins", {"tuya_secret": loaded})              # the value the load gave
    assert _stored("plugins", "tuya_secret") == "${env:H255_SECRET}"


def test_a_changed_or_cleared_value_is_written_as_given(store, monkeypatch):
    monkeypatch.setenv("H255_ID", "tuya-client-42")
    store.put_category("plugins", {"tuya_client_id": "${env:H255_ID}"})
    assert store.get_value("plugins", "tuya_client_id") == "tuya-client-42"
    store.put_category("plugins", {"tuya_client_id": "typed-by-the-owner"})
    assert _stored("plugins", "tuya_client_id") == "typed-by-the-owner"
    store.put_category("plugins", {"tuya_client_id": "${env:H255_ID}"})
    store.put_category("plugins", {"tuya_client_id": ""})
    assert _stored("plugins", "tuya_client_id") == ""


def test_nested_values_keep_their_references_leaf_by_leaf(store, monkeypatch):
    monkeypatch.setenv("H255_FONT", "mono")
    monkeypatch.setenv("H255_WAKE", "computer")
    store.put_category("appearance", {"preferences": {"font": "${env:H255_FONT}", "theme": "dark"}})
    store.put_category("general", {"wake_words": ["nerva", "${env:H255_WAKE}"]})

    prefs = store.get_value("appearance", "preferences")
    assert prefs == {"font": "mono", "theme": "dark"}
    store.put_category("appearance", {"preferences": {**prefs, "theme": "light"}})
    assert _stored("appearance", "preferences") == {"font": "${env:H255_FONT}", "theme": "light"}

    words = store.get_value("general", "wake_words")
    assert words == ["nerva", "computer"]
    store.put_category("general", {"wake_words": [*words, "hub"]})       # list items by position
    assert _stored("general", "wake_words") == ["nerva", "${env:H255_WAKE}", "hub"]


def test_preserve_matches_list_items_by_name_else_position():
    from agents.core.settings_interpolation import preserve

    env = {"TOKEN": "tok-1", "HOST": "h.example"}
    old = [{"name": "a", "url": "https://${env:HOST}/a"}, {"name": "b", "token": "${env:TOKEN}"}]
    new = [{"name": "b", "token": "tok-1", "extra": 1}, {"name": "c", "token": "tok-1"},
           {"name": "a", "url": "https://h.example/a"}]
    assert preserve(new, old, setting="t.servers", environ=env) == [
        {"name": "b", "token": "${env:TOKEN}", "extra": 1},
        {"name": "c", "token": "tok-1"},                     # a new item: nothing to keep
        {"name": "a", "url": "https://${env:HOST}/a"},
    ]
    assert preserve(["x", "tok-1"], ["x", "${TOKEN}"], setting="t.tags", environ=env) == ["x", "${TOKEN}"]


def test_the_admin_routes_show_the_reference_and_a_save_keeps_it(store, monkeypatch):
    from fastapi.testclient import TestClient

    import agents.web as web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "h255-admin")
    hdr = {"X-Admin-Token": "h255-admin"}
    monkeypatch.setenv("H255_SECRET", SECRET)
    client = TestClient(web.app)
    resp = client.put("/api/admin/settings/plugins", headers=hdr,
                      json={"values": {"tuya_secret": "${env:H255_SECRET}"}})
    assert resp.status_code == 200, resp.text
    shown = client.get("/api/admin/settings/plugins", headers=hdr)
    assert SECRET not in shown.text
    row = next(r for r in shown.json()["plugins"] if r["key"] == "tuya_secret")
    assert row["value"] == "${env:H255_SECRET}" and row["env_refs"] == [{"name": "H255_SECRET", "set": True}]

    # a writer that holds the value as it is used (read through get_value) saves it back
    resp = client.put("/api/admin/settings/plugins", headers=hdr,
                      json={"values": {"tuya_secret": store.get_value("plugins", "tuya_secret")}})
    assert resp.status_code == 200, resp.text
    assert _stored("plugins", "tuya_secret") == "${env:H255_SECRET}"
    assert SECRET not in _whole_db_text()


def _cli(argv):
    from agents.cli.nerva import Context, main

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def test_nerva_config_writes_and_shows_the_reference_and_a_path_write_keeps_it(store, monkeypatch):
    monkeypatch.setenv("H255_ID", "tuya-client-42")
    monkeypatch.setenv("H255_FONT", "mono")
    code, _, err = _cli(["config", "set", "plugins.tuya_device_id", "${env:H255_ID}"])
    assert code == 0, err
    code, out, _ = _cli(["config", "get", "plugins.tuya_device_id"])
    assert code == 0 and out.strip() == '"${env:H255_ID}"'
    assert store.get_value("plugins", "tuya_device_id") == "tuya-client-42"

    store.put_category("appearance", {"preferences": {"font": "${env:H255_FONT}", "theme": "dark"}})
    assert store.get_value("appearance", "preferences")["font"] == "mono"
    code, _, err = _cli(["config", "set", "appearance.preferences.theme", "light"])
    assert code == 0, err
    stored = _stored("appearance", "preferences")
    assert stored["font"] == "${env:H255_FONT}" and stored["theme"] == "light"


def test_export_carries_the_reference_and_an_import_keeps_it(store, monkeypatch):
    monkeypatch.setenv("H255_URL", "http://lms.local:1234")
    store.put_category("llm", {"lm_studio_url": "${env:H255_URL}"})
    doc = store.export_settings()
    assert doc["settings"]["llm"]["lm_studio_url"] == "${env:H255_URL}"
    assert "lms.local" not in json.dumps(doc)

    changes, errors = store.plan_import({"settings": {"llm": {"lm_studio_url": "http://lms.local:1234"}}})
    assert not errors
    store.apply_import(changes)
    assert _stored("llm", "lm_studio_url") == "${env:H255_URL}"


# ── 5. secrets are never persisted expanded or logged ─────────────────────────


def test_no_expanded_secret_reaches_the_store_or_a_log(store, monkeypatch, caplog):
    monkeypatch.setenv("H255_SECRET", SECRET)
    with caplog.at_level(logging.DEBUG):
        store.put_category("plugins", {"tuya_secret": "${env:H255_SECRET}",
                                       "tuya_client_id": "id-${env:H255_SECRET}"})
        o = _bare_orchestrator()
        o.load_runtime_settings()
        assert o.get_setting("plugins.tuya_client_id") == "id-" + SECRET
        store.put_category("plugins", {"tuya_secret": o.get_setting("plugins.tuya_secret"),
                                       "tuya_client_id": o.get_setting("plugins.tuya_client_id")})
        store.export_settings()
    assert SECRET not in _whole_db_text()
    assert SECRET not in caplog.text
    assert _stored("plugins", "tuya_client_id") == "id-${env:H255_SECRET}"


# ── 6. literal settings are never expanded ────────────────────────────────────


def test_literal_settings_read_exactly_as_stored(store, monkeypatch):
    monkeypatch.setenv("H255_MODEL", "expensive/model")
    monkeypatch.setenv("H255_ID", "12345")
    store.put_category("llm", {"claude_model": "${env:H255_MODEL}"})
    store.put_category("autonomy", {"owner_chat_id": "${env:H255_ID}"})
    store.put_category("commands", {"quick_commands": {"home": {"type": "exec", "command": "ls ${H255_ID}"}}})
    assert store.get_value("llm", "claude_model") == "${env:H255_MODEL}"
    assert store.get_value("autonomy", "owner_chat_id") == "${env:H255_ID}"
    assert store.get_value("commands", "quick_commands")["home"]["command"] == "ls ${H255_ID}"
    rows = {r["key"]: r for r in store.get_category("llm")}
    assert "env_refs" not in rows["claude_model"]
    for cat, key in store.ROUTE_ONLY:
        assert store.is_literal(cat, key)
    assert store.is_literal("skills", "template_vars") and store.is_literal("mcp", "servers")


def test_every_model_choice_the_selection_guards_judge_is_literal():
    from agents.core.llm import selection_guards as sg

    for (cat, key), spec in settings_db._SPEC.items():
        if cat not in ("llm", "autonomy") or spec.get("kind") not in ("text", "model-select", "select"):
            continue
        for probe in ("vendor/some-model", "allow"):
            if sg.choices_from_settings(cat, {key: probe}, lambda _k: "openrouter"):
                assert settings_db.is_literal(cat, key), f"{cat}.{key} is judged by H378 but expanded"
