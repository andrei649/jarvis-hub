"""The shared hub constructor refuses a corrupt policy store before startup."""

from types import SimpleNamespace

import pytest

from agents.core import orchestrator as module
from agents.core import settings_db
from agents.core.orchestrator import Orchestrator


def test_hub_constructor_validates_policy_before_building_components(monkeypatch):
    checked = []

    def unreadable():
        checked.append(True)
        raise settings_db.SettingsUnreadable("synthetic corrupt policy")

    monkeypatch.setattr(settings_db, "ensure_initialized", unreadable)
    with pytest.raises(settings_db.SettingsUnreadable, match="synthetic corrupt policy"):
        Orchestrator(SimpleNamespace())
    assert checked == [True]


@pytest.mark.parametrize("last_good", [False, True])
def test_runtime_reload_keeps_good_policy_but_refuses_empty_fresh_policy(monkeypatch, last_good):
    orch = Orchestrator.__new__(Orchestrator)
    good = {"llm.cloud_fallback": "never", "security.guardrails_mode": "BLOCK"}
    orch._runtime_settings = good.copy() if last_good else {}

    def unreadable():
        raise settings_db.SettingsUnreadable("synthetic corrupt policy")

    monkeypatch.setattr(module, "_get_settings", unreadable)
    if last_good:
        orch.load_runtime_settings()
        assert orch._runtime_settings == good
    else:
        with pytest.raises(settings_db.SettingsUnreadable):
            orch.load_runtime_settings()


def test_already_initialized_store_is_validated_at_each_hub_start(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.ensure_initialized()
    settings_db.DB_PATH.write_bytes(b"synthetic corrupt sqlite")
    with pytest.raises(settings_db.SettingsUnreadable):
        settings_db.ensure_initialized()


@pytest.mark.parametrize("last_good", [False, True])
def test_actual_corrupt_database_refuses_fresh_runtime_and_keeps_running_policy(tmp_path, monkeypatch, last_good):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.ensure_initialized()
    orch = Orchestrator.__new__(Orchestrator)
    good = {"llm.cloud_fallback": "never", "security.guardrails_mode": "BLOCK"}
    orch._runtime_settings = good.copy() if last_good else {}
    settings_db.DB_PATH.write_bytes(b"synthetic corrupt sqlite")
    if last_good:
        orch.load_runtime_settings()
        assert orch._runtime_settings == good
    else:
        with pytest.raises(settings_db.SettingsUnreadable):
            orch.load_runtime_settings()


def test_invalid_option_json_cannot_bypass_startup_or_write_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    conn.execute("UPDATE settings SET opts='{' WHERE category='security' AND key='guardrails_mode'")
    conn.commit()
    conn.close()
    with pytest.raises(settings_db.SettingsUnreadable):
        settings_db.ensure_initialized()
    with pytest.raises(settings_db.SettingsUnreadable):
        settings_db.put_category("security", {"guardrails_mode": "WARN"})


def test_fresh_runtime_refuses_an_unclassified_read_failure(monkeypatch):
    orch = Orchestrator.__new__(Orchestrator)
    orch._runtime_settings = {}

    def unreadable():
        raise PermissionError("synthetic policy access denied")

    monkeypatch.setattr(module, "_get_settings", unreadable)
    with pytest.raises(PermissionError):
        orch.load_runtime_settings()
