"""Admin-configured conversation policy reaches the durable lifecycle getter."""

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import settings_db
from agents.core.channels.session_reset import resolve_policy


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "sessions-admin-test")
    return TestClient(web.app)


def test_admin_sessions_settings_roundtrip_into_policy(client):
    values = {
        "reset_mode": "idle", "idle_minutes": 45, "daily_hour": 6,
        "reset_by_type": {"group": {"mode": "daily"}},
        "reset_by_channel": {"telegram": {"types": {"private": {"mode": "both"}}}},
        "reset_triggers": ["/new", "/reset"], "stall_seconds": 90,
        "stall_channel": "ntfy", "store_max_age_days": 30,
    }
    headers = {"X-Admin-Token": "sessions-admin-test"}
    saved = client.put("/api/admin/settings/sessions", json={"values": values}, headers=headers)
    assert saved.status_code == 200 and saved.json()["updated"] == len(values)
    rows = client.get("/api/admin/settings/sessions", headers=headers).json()["sessions"]
    assert {row["key"]: row["value"] for row in rows}.items() >= values.items()
    def setting(key, default):
        return settings_db.get_value(*key.split(".", 1), default=default)
    assert resolve_policy(setting, "telegram", "private").mode == "both"
    assert resolve_policy(setting, "email", "group").mode == "daily"
    assert setting("sessions.stall_channel", None) == "ntfy"


@pytest.mark.parametrize("key,value", [
    ("idle_minutes", 0), ("idle_minutes", True), ("daily_hour", 24),
    ("reset_by_channel", {"telegram": {"types": {"private": {"mode": "bogus"}}}}),
    ("reset_triggers", [""]), ("stall_seconds", 0), ("store_max_age_days", -1),
])
def test_admin_rejects_invalid_session_policy(client, key, value):
    headers = {"X-Admin-Token": "sessions-admin-test"}
    response = client.put("/api/admin/settings/sessions", json={"values": {key: value}}, headers=headers)
    assert response.status_code == 422
