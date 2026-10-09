"""Native code settings can be saved through the shipped admin API."""

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import settings_db


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-code-settings")
    return TestClient(web.app)


def test_native_code_settings_persist_through_admin(admin_client, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    values = {
        "execute_code": True,
        "execute_code_sessions": True,
        "execute_code_mode": "project",
        "execute_code_project_root": str(project),
        "execute_code_env_passthrough": ["MY_CUSTOM_KEY"],
        "execute_code_image": "python@sha256:" + "a" * 64,
    }
    response = admin_client.put(
        "/api/admin/settings/llm", json={"values": values},
        headers={"X-Admin-Token": "test-code-settings"},
    )
    assert response.status_code == 200
    assert response.json()["updated"] == len(values)
    assert response.json().get("skipped") is None
    settings_db._initialized = False
    saved = {row["key"]: row["value"] for row in settings_db.get_category("llm")}
    assert {key: saved[key] for key in values} == values


@pytest.mark.parametrize("values", [
    {"execute_code_mode": "unsafe"},
    {"execute_code_project_root": "relative/project"},
    {"execute_code_project_root": "\x00bad"},
    {"execute_code_env_passthrough": ["OPENAI_API_KEY"]},
    {"execute_code_env_passthrough": ["FOO=secret"]},
    {"execute_code_env_passthrough": {"FOO": "secret"}},
    {"execute_code_image": "python:latest"},
])
def test_malformed_code_settings_are_rejected_by_admin(admin_client, values):
    response = admin_client.put(
        "/api/admin/settings/llm", json={"values": values},
        headers={"X-Admin-Token": "test-code-settings"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid settings"
