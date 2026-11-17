"""H258 — the settings store's schema version, migration ladder and post-migration report.

A store is stamped with this build's version; a store below the support floor is not
auto-migrated and one above this build is never stamped down; rename / reshape / retire
steps carry the owner's value across (or keep it aside, named), never orphan it; and the
report names the settings and environment variables new since the previous version —
names only, never a value.
"""

from __future__ import annotations

import io
import json
import sqlite3

import pytest

from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main
from agents.core import env_registry, settings_db, settings_ladder
from agents.core.settings_ladder import Step


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    return tmp_path


def _sql(sql, args=()):
    conn = sqlite3.connect(settings_db.DB_PATH)
    try:
        rows = conn.execute(sql, args).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _reinit(monkeypatch):
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.ensure_initialized()


def _meta(key):
    rows = _sql("SELECT value FROM settings_meta WHERE key=?", (key,))
    return rows[0][0] if rows else None


def _report():
    raw = _meta("last_report")
    return json.loads(raw) if raw else None


def _raw(category, key):
    rows = _sql("SELECT value, kind FROM settings WHERE category=? AND key=?", (category, key))
    return rows[0] if rows else None


def _put_raw(category, key, value, kind="text"):
    _sql("INSERT OR REPLACE INTO settings (category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
         (category, key, json.dumps(value), key, kind, "[]"))


def _cli(argv):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


# ── the stamp and the report ─────────────────────────────────────────────────


def test_a_new_store_is_stamped_and_reports_nothing(store):
    settings_db.ensure_initialized()
    assert _meta("schema_version") == str(settings_ladder.STORE_VERSION)
    assert _report() is None
    assert json.loads(_meta("env_names")) == list(env_registry.entries())


def test_an_older_store_is_stamped_and_told_what_is_new(store, monkeypatch):
    settings_db.ensure_initialized()
    # an earlier build: no stamp, no env names recorded, one declaration it did not have
    _sql("DELETE FROM settings_meta")
    _sql("DELETE FROM settings WHERE category='llm' AND key='tool_loop_max_iterations'")
    _reinit(monkeypatch)
    report = _report()
    assert report["from_version"] == 0 and report["to_version"] == settings_ladder.STORE_VERSION
    assert report["new_settings"] == ["llm.tool_loop_max_iterations"]
    assert report["new_env"] == []                        # nothing recorded to compare against
    assert _meta("schema_version") == str(settings_ladder.STORE_VERSION)


def test_environment_variables_new_since_the_previous_build_are_named(store, monkeypatch):
    settings_db.ensure_initialized()
    names = list(env_registry.entries())
    _sql("UPDATE settings_meta SET value=? WHERE key='env_names'", (json.dumps(names[2:]),))
    _reinit(monkeypatch)
    assert _report()["new_env"] == names[:2]
    code, out, _ = _cli(["config", "check"])
    assert code == EXIT_OK
    assert f"settings store schema: version {settings_ladder.STORE_VERSION}" in out
    assert f"new environment variable {names[0]}" in out
    # the next start with nothing new keeps the last report as it was
    _reinit(monkeypatch)
    assert _report()["new_env"] == names[:2]


# ── the floor and a newer build ──────────────────────────────────────────────


def test_a_store_below_the_support_floor_is_not_migrated(store, monkeypatch):
    settings_db.ensure_initialized()
    _sql("UPDATE settings_meta SET value='1' WHERE key='schema_version'")
    _put_raw("legacy", "old_key", 12, "number")
    monkeypatch.setattr(settings_ladder, "STORE_VERSION", 3)
    monkeypatch.setattr(settings_ladder, "SUPPORT_FLOOR", 2)
    monkeypatch.setattr(settings_ladder, "STEPS", (
        Step(3, "rename", ("legacy", "old_key"), "renamed", to=("llm", "tool_loop_max_iterations")),))
    _reinit(monkeypatch)
    report = _report()
    assert report["refused"] == "too_old" and "older than 2" in report["detail"]
    assert _meta("schema_version") == "1"                 # not stamped past what ran
    assert _raw("legacy", "old_key") is not None          # the value is untouched
    code, out, _ = _cli(["config", "check"])
    assert code == EXIT_FAILED and "older than 2" in out
    code, out, err = _cli(["config", "migrate", "--dry-run"])
    assert code == EXIT_FAILED and "refused" in out and "older than 2" in out


def test_a_store_a_newer_build_stamped_is_never_stamped_down(store, monkeypatch):
    settings_db.ensure_initialized()
    _sql("UPDATE settings_meta SET value='9' WHERE key='schema_version'")
    _reinit(monkeypatch)
    assert _meta("schema_version") == "9" and _report()["refused"] == "newer"


# ── rename / reshape / retire ────────────────────────────────────────────────


def _ladder(monkeypatch, *steps):
    monkeypatch.setattr(settings_ladder, "STORE_VERSION", 2)
    monkeypatch.setattr(settings_ladder, "STEPS", tuple(steps))


def test_rename_carries_the_owners_value_and_drops_the_old_key(store, monkeypatch):
    settings_db.ensure_initialized()
    _put_raw("legacy", "old_key", 12, "number")
    _ladder(monkeypatch, Step(2, "rename", ("legacy", "old_key"), "renamed in v2",
                              to=("llm", "tool_loop_max_iterations")))
    code, out, _ = _cli(["config", "migrate", "--dry-run"])
    assert code == EXIT_OK and "rename   legacy.old_key" in out and "llm.tool_loop_max_iterations" in out
    _reinit(monkeypatch)
    assert settings_db.get_value("llm", "tool_loop_max_iterations") == 12
    assert _raw("legacy", "old_key") is None
    step = _report()["steps"][0]
    assert step["carried"] is True and step["to"] == "llm.tool_loop_max_iterations"
    assert _meta("schema_version") == "2"
    # a second start runs nothing again
    _reinit(monkeypatch)
    assert settings_db.get_value("llm", "tool_loop_max_iterations") == 12


def test_rename_never_overwrites_a_value_the_owner_set_on_the_new_key(store, monkeypatch):
    settings_db.ensure_initialized()
    settings_db.put_category("llm", {"tool_loop_max_iterations": 5})
    _put_raw("legacy", "old_key", 12, "number")
    _ladder(monkeypatch, Step(2, "rename", ("legacy", "old_key"), "renamed",
                              to=("llm", "tool_loop_max_iterations")))
    _reinit(monkeypatch)
    assert settings_db.get_value("llm", "tool_loop_max_iterations") == 5
    step = _report()["steps"][0]
    assert step["carried"] is False and step["kept_in"] == "settings_retired"
    kept = _sql("SELECT category, key, value FROM settings_retired")
    assert kept == [("legacy", "old_key", "12")]
    conn = sqlite3.connect(settings_db.DB_PATH)
    try:
        listed = settings_ladder.retired(conn)
    finally:
        conn.close()
    assert listed[0]["setting"] == "legacy.old_key" and "value" not in listed[0]


def test_rename_leaves_an_untouched_old_default_behind(store, monkeypatch):
    settings_db.ensure_initialized()
    _put_raw("legacy", "old_key", 8, "number")
    _ladder(monkeypatch, Step(2, "rename", ("legacy", "old_key"), "renamed", to=("llm", "tool_loop_max_iterations"),
                              old_default=8, has_old_default=True))
    _reinit(monkeypatch)
    declared = settings_db._SPEC[("llm", "tool_loop_max_iterations")]["value"]
    assert settings_db.get_value("llm", "tool_loop_max_iterations") == declared
    assert _raw("legacy", "old_key") is None and _report()["steps"][0]["carried"] is False


def test_rename_of_an_encrypted_secret_keeps_it_encrypted(store, monkeypatch):
    settings_db.ensure_initialized()
    secret_key = sorted(settings_db.SECRET_KEYS)[0]
    category = next(c for (c, k) in settings_db._SPEC if k == secret_key)
    settings_db.put_category(category, {secret_key: "sk-h258-secret-value-123456"})
    stored = _raw(category, secret_key)[0]
    assert "sk-h258" not in stored                        # encrypted at rest
    _sql("UPDATE settings SET key='old_secret' WHERE category=? AND key=?", (category, secret_key))
    _sql("DELETE FROM settings WHERE category=? AND key=?", (category, secret_key))
    _reinit(monkeypatch)                                  # the new key is seeded empty again
    _ladder(monkeypatch, Step(2, "rename", (category, "old_secret"), "renamed", to=(category, secret_key)))
    _reinit(monkeypatch)
    assert _raw(category, secret_key)[0] == stored        # moved as stored, still encrypted
    assert settings_db.get_value(category, secret_key) == "sk-h258-secret-value-123456"
    assert "sk-h258" not in json.dumps(_report())


def test_reshape_converts_the_value_or_keeps_it_aside(store, monkeypatch):
    settings_db.ensure_initialized()
    _sql("UPDATE settings SET value=?, kind='text' WHERE category='general' AND key='wake_words'",
         (json.dumps("nerva, computer"),))
    _ladder(monkeypatch, Step(2, "reshape", ("general", "wake_words"), "a comma list became tags",
                              transform=lambda old: [w.strip() for w in old.split(",") if w.strip()]))
    _reinit(monkeypatch)
    assert settings_db.get_value("general", "wake_words") == ["nerva", "computer"]
    assert _raw("general", "wake_words")[1] == "tags"
    assert _report()["steps"][0]["carried"] is True


def test_a_reshape_that_cannot_convert_keeps_the_old_value_aside(store, monkeypatch):
    settings_db.ensure_initialized()
    _sql("UPDATE settings SET value=?, kind='text' WHERE category='general' AND key='wake_words'",
         (json.dumps("nerva"),))
    _ladder(monkeypatch, Step(2, "reshape", ("general", "wake_words"), "tags",
                              transform=lambda old: int("not a number")))
    _reinit(monkeypatch)
    declared = settings_db._SPEC[("general", "wake_words")]["value"]
    assert settings_db.get_value("general", "wake_words") == declared
    assert _sql("SELECT category, key, value FROM settings_retired") == [("general", "wake_words", '"nerva"')]
    assert _report()["steps"][0]["carried"] is False


def test_retire_removes_the_setting_and_keeps_its_value_aside(store, monkeypatch):
    settings_db.ensure_initialized()
    _put_raw("legacy", "gone", {"a": 1}, "json")
    _ladder(monkeypatch, Step(2, "retire", ("legacy", "gone"), "the feature was removed"))
    _reinit(monkeypatch)
    assert _raw("legacy", "gone") is None
    assert _sql("SELECT category, key, why FROM settings_retired") == [("legacy", "gone", "the feature was removed")]
    code, out, _ = _cli(["config", "check"])
    assert code == EXIT_OK and "retire legacy.gone" in out


def test_config_migrate_applies_the_ladder_and_prints_the_report(store, monkeypatch):
    settings_db.ensure_initialized()
    _put_raw("legacy", "gone", 1, "number")
    _ladder(monkeypatch, Step(2, "retire", ("legacy", "gone"), "removed"))
    code, out, err = _cli(["config", "migrate"])
    assert code == EXIT_OK, err
    assert "retire   legacy.gone" in out and "since the previous version" in out
    assert _raw("legacy", "gone") is None and _meta("schema_version") == "2"


def test_every_shipped_step_targets_a_declared_setting_and_never_converts_a_secret():
    for step in settings_ladder.STEPS:
        assert step.kind in settings_ladder.KINDS
        assert settings_ladder.SUPPORT_FLOOR < step.version <= settings_ladder.STORE_VERSION
        if step.kind != "retire":
            target = step.to if step.kind == "rename" else step.setting
            assert target in settings_db._SPEC
        if step.transform is not None:
            assert step.setting[1] not in settings_db.SECRET_KEYS
    versions = [s.version for s in settings_ladder.STEPS]
    assert versions == sorted(versions)
