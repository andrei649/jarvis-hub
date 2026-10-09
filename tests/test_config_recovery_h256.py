"""H256: broken persisted settings never relax the running policy or get overwritten."""

import logging

import pytest

from agents.core import settings_db
from agents.core.config import JarvisConfig


def test_yaml_keeps_last_good_and_snapshots_exact_corrupt_bytes(tmp_path, caplog):
    path = tmp_path / "agents.yaml"
    path.write_text("agents:\n  sentinel:\n    status: disabled\n", encoding="utf-8")
    config = JarvisConfig(str(path))
    broken = b"agents: [\n"
    path.write_bytes(broken)

    with caplog.at_level(logging.WARNING):
        config._load()
        config._load()

    assert config.agents["sentinel"].status == "disabled"
    copies = list((tmp_path / "backups" / "config").glob("agents.yaml.corrupt.*"))
    assert len(copies) == 1 and copies[0].read_bytes() == broken
    assert copies[0].stat().st_mode & 0o777 == 0o600
    assert sum("agents.yaml" in r.message for r in caplog.records) == 1
    with pytest.raises(RuntimeError, match="agents.yaml"):
        JarvisConfig(str(path))


def test_yaml_non_mapping_refuses_fresh_start(tmp_path):
    path = tmp_path / "agents.yaml"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="agents.yaml"):
        JarvisConfig(str(path))


def test_disappeared_yaml_keeps_running_policy_and_refuses_fresh_start(tmp_path):
    path = tmp_path / "agents.yaml"
    path.write_text("general:\n  cloud_fallback: never\n")
    config = JarvisConfig(str(path))
    path.unlink()
    config._load()
    assert config.general["cloud_fallback"] == "never"
    with pytest.raises(FileNotFoundError):
        JarvisConfig(str(path))


def test_planted_backups_symlink_cannot_redirect_corrupt_copy(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "backups").symlink_to(outside, target_is_directory=True)
    path = tmp_path / "agents.yaml"
    path.write_bytes(b"agents: [\n")

    with pytest.raises(RuntimeError, match="agents.yaml"):
        JarvisConfig(str(path))

    assert list(outside.iterdir()) == []


def test_yaml_applies_repaired_file_after_recovery(tmp_path):
    path = tmp_path / "agents.yaml"
    path.write_text("agents:\n  sentinel:\n    status: disabled\n", encoding="utf-8")
    config = JarvisConfig(str(path))
    path.write_text("agents: [\n", encoding="utf-8")
    config._load()
    path.write_text("agents:\n  sentinel:\n    status: active\n", encoding="utf-8")
    config._load()
    assert config.agents["sentinel"].status == "active"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    return settings_db


def test_corrupt_db_fresh_start_refuses_without_reseeding(store):
    broken = b"not a sqlite database\x00\xff"
    store.DB_PATH.write_bytes(broken)
    with pytest.raises(store.SettingsUnreadable):
        store.get_value("security", "guardrails_mode", "permissive")
    assert store.DB_PATH.read_bytes() == broken


def test_running_db_keeps_last_good_and_every_writer_refuses(store):
    store.put_category("security", {"guardrails_mode": "strict"})
    assert store.get_value("security", "guardrails_mode") == "strict"
    broken = b"not a sqlite database\x00\xff"
    store.DB_PATH.write_bytes(broken)

    assert store.get_value("security", "guardrails_mode", "permissive") == "strict"
    for write in (
        lambda: store.put_category("security", {"guardrails_mode": "permissive"}),
        lambda: store.apply_import({"security": {"guardrails_mode": "permissive"}}),
        lambda: store.reset_settings("security"),
        store.undo_last_reset,
        lambda: store.init_db(force=True),
    ):
        with pytest.raises(store.SettingsUnreadable):
            write()
        assert store.DB_PATH.read_bytes() == broken
    copies = list((store.DB_PATH.parent / "backups" / "config").glob("settings.db.corrupt.*"))
    assert len(copies) == 1 and copies[0].read_bytes() == broken


def test_lkg_is_scoped_to_db_path(store, tmp_path, monkeypatch):
    assert store.get_value("security", "guardrails_mode") is not None
    other = tmp_path / "other.db"
    broken = b"not a sqlite database"
    other.write_bytes(broken)
    monkeypatch.setattr(store, "DB_PATH", other)
    with pytest.raises(store.SettingsUnreadable):
        store.get_value("security", "guardrails_mode", "permissive")
    assert other.read_bytes() == broken


def test_invalid_stored_json_refuses_write_and_serves_last_good(store):
    store.put_category("security", {"guardrails_mode": "strict"})
    assert store.get_value("security", "guardrails_mode") == "strict"
    conn = store.get_conn()
    conn.execute("UPDATE settings SET value=? WHERE category='security' AND key='guardrails_mode'", ("{",))
    conn.commit()
    conn.close()

    assert store.get_value("security", "guardrails_mode", "permissive") == "strict"
    with pytest.raises(store.SettingsUnreadable):
        store.put_category("security", {"guardrails_mode": "permissive"})
    conn = store.get_conn()
    assert conn.execute("SELECT value FROM settings WHERE category='security' AND key='guardrails_mode'").fetchone()[0] == "{"
    conn.close()


def test_unrelated_bad_row_does_not_allow_default_for_missing_policy(store):
    assert store.get_value("security", "guardrails_mode") is not None
    conn = store.get_conn()
    conn.execute("UPDATE settings SET value=? WHERE category='security' AND key='guardrails_mode'", ("{",))
    conn.commit()
    conn.close()

    with pytest.raises(store.SettingsUnreadable):
        store.get_value("security", "unknown_policy", "permissive")
