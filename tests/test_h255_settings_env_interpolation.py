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
* an expanded secret is never persisted or logged; literal settings are never expanded;
* (H255 review) a setting never expands a variable ``/api/admin/env`` masks into a place
  that variable's value may not reach: the hub's own credentials nowhere, another
  credential only in a credential setting, and outside one no value that looks like a
  credential. Checked through a route that echoes a setting (``/api/onboarding/model-plan``),
  the prompt a setting reaches, the admin write, ``nerva config`` and an import.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
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
                 "H255_UNSET", "H255_MODEL", "H255_PROVIDER_API_KEY", "H255_LEAKY", "H255_USER", "H255_PW"):
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


def _guidance(**overrides) -> dict:
    return {"enabled": True, "flags": {}, "agents": {}, "platform_overrides": overrides}


def test_nested_values_keep_their_references_leaf_by_leaf(store, monkeypatch):
    from agents.core.operating_guidance import build_operating_guidance

    monkeypatch.setenv("H255_FONT", "mono")
    monkeypatch.setenv("H255_WAKE", "computer")
    # llm.operating_guidance reaches the turn's prompt through the runtime settings
    store.put_category("llm", {"operating_guidance": _guidance(cli="Reply in ${env:H255_FONT}", telegram="plain")})
    store.put_category("general", {"wake_words": ["nerva", "${env:H255_WAKE}"]})

    o = _bare_orchestrator()
    o.load_runtime_settings()
    used = o.get_setting("llm.operating_guidance")
    assert used["platform_overrides"] == {"cli": "Reply in mono", "telegram": "plain"}
    assert "Reply in mono" in build_operating_guidance(model="claude-sonnet-4-5", surface="cli",
                                                       platform_overrides=used["platform_overrides"])
    store.put_category("llm", {"operating_guidance": {**used, "platform_overrides": {
        **used["platform_overrides"], "telegram": "bullets"}}})
    assert _stored("llm", "operating_guidance") == _guidance(cli="Reply in ${env:H255_FONT}", telegram="bullets")

    words = store.get_value("general", "wake_words")
    assert words == ["nerva", "computer"]
    store.put_category("general", {"wake_words": [*words, "hub"]})       # list items by position
    assert _stored("general", "wake_words") == ["nerva", "${env:H255_WAKE}", "hub"]


def test_a_removed_or_moved_list_item_never_writes_a_later_ones_expansion(store, monkeypatch):
    from agents.core.settings_interpolation import preserve

    env = {"A": "a-secret", "B": "b-secret"}
    assert preserve(["b-secret"], ["${env:A}", "${env:B}"], setting="t.l", environ=env) == ["${env:B}"]
    assert preserve(["b-secret", "a-secret"], ["${env:A}", "${env:B}"], setting="t.l", environ=env) == [
        "${env:B}", "${env:A}"]
    assert preserve([{"u": "b-secret"}], [{"u": "${env:A}"}, {"u": "${env:B}"}], setting="t.l",
                    environ=env) == [{"u": "${env:B}"}]

    monkeypatch.setenv("H255_WAKE", "computer")
    monkeypatch.setenv("H255_FONT", "jarvis")
    store.put_category("general", {"wake_words": ["${env:H255_WAKE}", "${env:H255_FONT}"]})
    words = store.get_value("general", "wake_words")
    assert words == ["computer", "jarvis"]
    store.put_category("general", {"wake_words": words[1:]})               # the first one removed
    assert _stored("general", "wake_words") == ["${env:H255_FONT}"]
    store.put_category("general", {"wake_words": ["${env:H255_WAKE}", "${env:H255_FONT}"]})
    store.put_category("general", {"wake_words": list(reversed(words))})   # moved
    assert _stored("general", "wake_words") == ["${env:H255_FONT}", "${env:H255_WAKE}"]


def test_every_writer_tells_the_listeners_the_value_as_it_is_used(store, monkeypatch):
    monkeypatch.setattr(store, "_change_listeners", [])
    heard: list = []
    store.on_change(lambda cat, values: heard.append((cat, values)))
    monkeypatch.setenv("H255_WAKE", "computer")
    store.put_category("general", {"wake_words": ["nerva", "${env:H255_WAKE}"]})
    assert heard[-1] == ("general", {"wake_words": ["nerva", "computer"]})
    assert store.reset_settings("general") is not None                     # back to the defaults
    undone = store.undo_last_reset()
    assert "general.wake_words" in json.dumps(undone)
    assert heard[-1][0] == "general" and heard[-1][1]["wake_words"] == ["nerva", "computer"]
    assert _stored("general", "wake_words") == ["nerva", "${env:H255_WAKE}"]


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

    store.put_category("llm", {"operating_guidance": _guidance(cli="Reply in ${env:H255_FONT}", telegram="plain")})
    assert store.get_value("llm", "operating_guidance")["platform_overrides"]["cli"] == "Reply in mono"
    code, _, err = _cli(["config", "set", "llm.operating_guidance.platform_overrides.telegram", "bullets"])
    assert code == 0, err
    assert _stored("llm", "operating_guidance") == _guidance(cli="Reply in ${env:H255_FONT}", telegram="bullets")


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


# ── 7. which variables a setting may name (H255 review) ──────────────────────

PROVIDER_KEY = "sk-ant-h255-PROVIDER-KEY-0042"
ADMIN_TOKEN = "h255-admin-token-VALUE-77"
CREDENTIAL_ONLY = "a credential (/api/admin/env masks it), which only a credential setting may name"


def _put_raw(cat: str, key: str, value) -> None:
    """Store *value* as a row written before the check (or by hand, or by an old import) holds it."""
    conn = sqlite3.connect(str(settings_db.DB_PATH))
    try:
        with conn:
            conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?", (json.dumps(value), cat, key))
    finally:
        conn.close()


def test_which_names_are_credentials_is_the_admin_env_views_own_rule():
    from agents.core import env_provenance
    from agents.core.routers import admin

    assert admin._SECRET_HINTS is env_provenance.SECRET_HINTS      # one list, not two
    for name in ("JARVIS_ADMIN_TOKEN", "JARVIS_SECRET_KEY", "JARVIS_USER_TOKEN", "JARVIS_AUDIT_KEY",
                 "JARVIS_BACKUP_KEY", "NERVA_WORKSPACE_SSO_SECRET"):
        assert env_provenance.hub_credential(name), name
    for name in ("ANTHROPIC_API_KEY", "TUYA_SECRET", "TELEGRAM_BOT_TOKEN"):
        assert env_provenance.masked(name) and not env_provenance.hub_credential(name), name
    for name in ("JARVIS_HOME", "OLLAMA_HOST", "HOME"):
        assert not env_provenance.masked(name), name


def test_the_hubs_own_credentials_are_never_expanded_in_any_setting(store, monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", ADMIN_TOKEN)
    for cat, key in (("plugins", "tuya_secret"), ("llm", "ollama_url")):    # a credential setting too
        problems = store.validate_category(cat, {key: "${env:JARVIS_ADMIN_TOKEN}"})
        assert problems == [f"{key}: names the environment variable JARVIS_ADMIN_TOKEN, one of the hub's own "
                            "credentials, which no setting may name"]
    _put_raw("plugins", "tuya_secret", "${env:JARVIS_SECRET_KEY}")
    _put_raw("llm", "ollama_url", "http://127.0.0.1:11434/${JARVIS_ADMIN_TOKEN}")
    with caplog.at_level(logging.DEBUG):
        assert store.get_value("plugins", "tuya_secret") == "${env:JARVIS_SECRET_KEY}"
        assert store.read_setting("llm", "ollama_url") == (True, "http://127.0.0.1:11434/${JARVIS_ADMIN_TOKEN}")
        o = _bare_orchestrator()
        o.load_runtime_settings()
        assert o.get_setting("plugins.tuya_secret") == "${env:JARVIS_SECRET_KEY}"
        assert o.get_setting("llm.ollama_url") == "http://127.0.0.1:11434/${JARVIS_ADMIN_TOKEN}"
    assert _KEY not in caplog.text and ADMIN_TOKEN not in caplog.text
    warned = [r.getMessage() for r in caplog.records if "JARVIS_SECRET_KEY" in r.getMessage()]
    assert len(warned) == 1 and "plugins.tuya_secret" in warned[0] and "hub's own credentials" in warned[0]
    row = {r["key"]: r for r in store.get_category("plugins")}["tuya_secret"]
    assert row["env_refs"] == [{"name": "JARVIS_SECRET_KEY", "set": True,
                                "refused": "one of the hub's own credentials, which no setting may name"}]
    assert "JARVIS_SECRET_KEY" not in store.env_ref_names(store.get_all())   # nothing to reload for


def test_a_credential_variable_expands_only_in_a_credential_setting(store, monkeypatch, caplog):
    monkeypatch.setenv("H255_PROVIDER_API_KEY", PROVIDER_KEY)
    store.put_category("plugins", {"tuya_secret": "${env:H255_PROVIDER_API_KEY}"})
    assert store.get_value("plugins", "tuya_secret") == PROVIDER_KEY        # a credential setting: expands

    assert store.validate_category("llm", {"ollama_url": "http://h/${env:H255_PROVIDER_API_KEY}"}) == [
        f"ollama_url: names the environment variable H255_PROVIDER_API_KEY, {CREDENTIAL_ONLY}"]
    _put_raw("llm", "ollama_url", "http://h/${env:H255_PROVIDER_API_KEY}")
    _put_raw("general", "wake_words", ["nerva", "${H255_PROVIDER_API_KEY}"])
    with caplog.at_level(logging.DEBUG):
        for _ in range(2):
            assert store.get_value("llm", "ollama_url") == "http://h/${env:H255_PROVIDER_API_KEY}"
            assert store.get_value("general", "wake_words") == ["nerva", "${H255_PROVIDER_API_KEY}"]
    assert PROVIDER_KEY not in caplog.text
    warned = [r.getMessage() for r in caplog.records if "H255_PROVIDER_API_KEY" in r.getMessage()]
    assert len(warned) == 2 and all("only a credential setting may name" in m for m in warned)
    assert {m.split()[1] for m in warned} == {"llm.ollama_url", "general.wake_words"}


def test_a_value_that_looks_like_a_credential_expands_only_in_a_credential_setting(store, monkeypatch, caplog):
    monkeypatch.setenv("H255_URL", "http://admin:hunter2@lms.local:1234")
    monkeypatch.setenv("H255_LEAKY", "ghp_" + "a1B2c3D4" * 4 + "e5F6")    # a token under an innocent name
    monkeypatch.setenv("H255_USER", "admin")
    monkeypatch.setenv("H255_PW", "hunter2")
    with caplog.at_level(logging.DEBUG):
        store.put_category("llm", {"lm_studio_url": "${env:H255_URL}"})
        assert store.get_value("llm", "lm_studio_url") == "${env:H255_URL}"
        store.put_category("llm", {"lm_studio_url": "http://${H255_USER}:${H255_PW}@lms.local"})   # assembled
        assert store.get_value("llm", "lm_studio_url") == "http://${H255_USER}:${H255_PW}@lms.local"
        store.put_category("general", {"wake_words": ["${env:H255_LEAKY}"]})
        assert store.get_value("general", "wake_words") == ["${env:H255_LEAKY}"]
    assert "hunter2" not in caplog.text and os.environ["H255_LEAKY"] not in caplog.text

    store.put_category("plugins", {"tuya_secret": "${env:H255_LEAKY}"})       # a credential setting: expands
    assert store.get_value("plugins", "tuya_secret") == os.environ["H255_LEAKY"]
    monkeypatch.setenv("H255_URL", "http://lms.local:1234")                   # no credential in it: expands
    store.put_category("llm", {"lm_studio_url": "${env:H255_URL}"})
    assert store.get_value("llm", "lm_studio_url") == "http://lms.local:1234"


def test_no_route_echoes_a_masked_variable_through_a_setting(store, monkeypatch):
    from fastapi.testclient import TestClient

    import agents.web as web
    from agents.core.routers import model_setup

    monkeypatch.setenv("ANTHROPIC_API_KEY", PROVIDER_KEY)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h255-admin")
    monkeypatch.setattr(model_setup, "_service", None)
    hdr = {"X-Admin-Token": "h255-admin"}
    client = TestClient(web.app)
    assert client.get("/api/admin/env", headers=hdr).json()["ANTHROPIC_API_KEY"] != PROVIDER_KEY

    # the admin write that would name it is refused, naming the variable, never its value
    resp = client.put("/api/admin/settings/llm", headers=hdr,
                      json={"values": {"ollama_url": "http://poc.example/${env:ANTHROPIC_API_KEY}"}})
    assert resp.status_code == 422 and "ANTHROPIC_API_KEY" in resp.text and PROVIDER_KEY not in resp.text
    assert _stored("llm", "ollama_url") == "http://localhost:11434"

    # a row that already names it reads as written: the user-tier plan echoes the reference
    _put_raw("llm", "ollama_url", "http://poc.example/${env:ANTHROPIC_API_KEY}")
    plan = client.get("/api/onboarding/model-plan", headers=hdr)
    assert plan.status_code == 200 and PROVIDER_KEY not in plan.text
    assert plan.json()["ollama"]["url"] == "http://poc.example/${env:ANTHROPIC_API_KEY}"
    shown = client.get("/api/admin/settings/llm", headers=hdr)
    row = next(r for r in shown.json()["llm"] if r["key"] == "ollama_url")
    assert row["env_refs"] == [{"name": "ANTHROPIC_API_KEY", "set": True, "refused": CREDENTIAL_ONLY}]
    assert PROVIDER_KEY not in shown.text


def test_no_prompt_carries_a_masked_variable_through_a_setting(store, monkeypatch):
    from agents.core.operating_guidance import build_operating_guidance

    monkeypatch.setenv("H255_PROVIDER_API_KEY", PROVIDER_KEY)
    monkeypatch.setenv("H255_FONT", "mono")
    guidance = {"enabled": True, "flags": {}, "agents": {},
                "platform_overrides": {"cli": "Reply in ${H255_FONT}; key ${env:H255_PROVIDER_API_KEY}"}}
    assert store.validate_category("llm", {"operating_guidance": guidance}) == [
        f"operating_guidance: names the environment variable H255_PROVIDER_API_KEY, {CREDENTIAL_ONLY}"]
    _put_raw("llm", "operating_guidance", guidance)
    o = _bare_orchestrator()
    o.load_runtime_settings()                                   # the runtime settings the turn reads
    overrides = o.get_setting("llm.operating_guidance")["platform_overrides"]
    text = build_operating_guidance(model="claude-sonnet-4-5", surface="cli", platform_overrides=overrides)
    assert PROVIDER_KEY not in text
    assert "Reply in mono; key ${env:H255_PROVIDER_API_KEY}" in text   # the allowed name expands, the other not


def test_nerva_config_and_an_import_refuse_a_reference_the_setting_may_not_name(store, monkeypatch):
    monkeypatch.setenv("H255_PROVIDER_API_KEY", PROVIDER_KEY)
    code, out, err = _cli(["config", "set", "llm.lm_studio_url", "http://h/${env:H255_PROVIDER_API_KEY}"])
    assert code != 0 and "H255_PROVIDER_API_KEY" in out + err and PROVIDER_KEY not in out + err
    assert _stored("llm", "lm_studio_url") == "http://localhost:1234"

    changes, errors = store.plan_import({"settings": {"llm": {"lm_studio_url": "${JARVIS_ADMIN_TOKEN}"}}})
    assert errors and "JARVIS_ADMIN_TOKEN" in errors[0] and "hub's own credentials" in errors[0]

    _put_raw("llm", "lm_studio_url", "http://h/${env:H255_PROVIDER_API_KEY}")   # stored before the check
    code, out, err = _cli(["config", "check"])
    assert code != 0 and "llm.lm_studio_url" in out and "H255_PROVIDER_API_KEY" in out
    assert PROVIDER_KEY not in out + err
