"""G1 (H249/H267/H629) on the Integrations panel: a key or choice the administrator pinned.

Owner side: the panel shows a pinned key or search choice as "managed by your
administrator" and offers no edit. Attacker side: every panel writer — key PUT and DELETE,
"use" (a search backend or a model provider) and the search-choice reset — refuses with
409 naming the managed file, audited; a stored panel key never overwrites a pinned name at
start; managed mode refuses every panel write.
"""
import os

import pytest

from agents.core import integration_keys, managed_scope
from tests.test_integrations_panel_routes import ADMIN, BASE, KEY, MODEL_KEY, hub  # noqa: F401


@pytest.fixture
def pinned(tmp_path, monkeypatch, hub):  # noqa: F811
    directory = tmp_path / "etc-nerva"
    directory.mkdir()
    monkeypatch.delenv("JARVIS_MANAGED_DIR", raising=False)
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(directory))
    managed_scope.invalidate()
    yield directory
    managed_scope.invalidate()


def _write(directory, name, text):
    (directory / name).write_text(text, encoding="utf-8")
    managed_scope.invalidate()


def _refused(response, directory, name=".env"):
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"] == "managed" and "managed by your administrator" in body["detail"]
    assert body["source"] == str(directory / name)


def test_key_put_and_delete_refuse_a_pinned_key(hub, pinned, monkeypatch):  # noqa: F811
    _write(pinned, ".env", "EXA_API_KEY=admin-exa-key-000000000000\n")
    monkeypatch.setenv("EXA_API_KEY", "admin-exa-key-000000000000")      # applied at the hub's load
    _refused(hub.client.put(f"{BASE}/search.exa/key", json={"value": KEY}, headers=ADMIN), pinned)
    _refused(hub.client.delete(f"{BASE}/search.exa/key", headers=ADMIN), pinned)
    assert os.environ["EXA_API_KEY"] == "admin-exa-key-000000000000"
    assert any(action == "settings_managed_refused" for action, _ in hub.orch.audit.rows)
    with pytest.raises(managed_scope.ManagedRefused):
        integration_keys.set_key("EXA_API_KEY", KEY)
    with pytest.raises(managed_scope.ManagedRefused):
        integration_keys.clear_key("EXA_API_KEY")


def test_the_panel_shows_a_pinned_key_read_only(hub, pinned, monkeypatch):  # noqa: F811
    _write(pinned, ".env", "EXA_API_KEY=admin-exa-key-000000000000\n")
    monkeypatch.setenv("EXA_API_KEY", "admin-exa-key-000000000000")
    row = next(r for r in hub.client.get(BASE, headers=ADMIN).json()["integrations"] if r["id"] == "search.exa")
    assert row["key"]["source"] == "managed" and row["key"]["editable"] is False


def test_search_choice_writers_refuse_a_pinned_choice(hub, pinned, monkeypatch):  # noqa: F811
    _write(pinned, ".env", "NERVA_WEB_BACKEND=tavily\n")
    monkeypatch.setenv("JARVIS_WEB_BACKEND", "tavily")
    hub.client.put(f"{BASE}/search.exa/key", json={"value": KEY}, headers=ADMIN)
    _refused(hub.client.post(f"{BASE}/search.exa/use", headers=ADMIN,
                             json={"acknowledge_training": True, "confirm_expensive": True}), pinned)
    _refused(hub.client.delete(f"{BASE}/search-choice", headers=ADMIN), pinned)
    assert hub.client.get(BASE, headers=ADMIN).json()["search"]["choice_source"] == "managed"
    assert os.environ["JARVIS_WEB_BACKEND"] == "tavily"


def test_use_refuses_a_pinned_model_provider(hub, pinned):  # noqa: F811
    _write(pinned, "config.yaml", "llm:\n  compatible_provider: ''\n")
    hub.client.put(f"{BASE}/model.deepseek/key", json={"value": MODEL_KEY}, headers=ADMIN)
    response = hub.client.post(f"{BASE}/model.deepseek/use", headers=ADMIN, json={
        "model": "deepseek-v4-pro", "acknowledge_training": True, "confirm_expensive": True})
    _refused(response, pinned, "config.yaml")


def test_a_stored_panel_key_never_overwrites_a_pinned_name_at_start(hub, pinned, monkeypatch):  # noqa: F811
    integration_keys.set_key("EXA_API_KEY", KEY)
    integration_keys.set_key("PARALLEL_API_KEY", "parallel-synthetic-key-0001")
    integration_keys._PLACED.clear()
    os.environ.pop("EXA_API_KEY")
    os.environ.pop("PARALLEL_API_KEY")
    # the administrator pins EXA_API_KEY; the hub's load did not put it in this test's env
    _write(pinned, ".env", "EXA_API_KEY=admin-exa-key-000000000000\n")
    assert integration_keys.apply_stored() == ["PARALLEL_API_KEY"]
    assert "EXA_API_KEY" not in os.environ


def test_managed_mode_refuses_every_panel_write(hub, pinned):  # noqa: F811
    _write(pinned, ".managed", "sudo nixos-rebuild switch\n")
    _refused(hub.client.put(f"{BASE}/search.exa/key", json={"value": KEY}, headers=ADMIN), pinned, ".managed")
    assert "sudo nixos-rebuild switch" in hub.client.delete(f"{BASE}/search-choice", headers=ADMIN).json()["detail"]
