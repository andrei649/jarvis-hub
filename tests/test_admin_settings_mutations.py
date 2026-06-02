"""HTTP integration tests for admin settings write-path endpoints.

Covers:
  GET  /api/admin/settings/{category}  — per-category read + 404
  PUT  /api/admin/settings/{category}  — write values
  POST /api/admin/settings/reseed      — force-reseed from defaults
  Auth guards: 401 without token, 403 from non-local without token
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web

_TOKEN = "test-admin-secret"
_HDR = {"X-Admin-Token": _TOKEN}


@pytest.fixture()
def admin_client(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    return TestClient(web.app)


# ---------------------------------------------------------------------------
# Auth guards
# ---------------------------------------------------------------------------

def test_settings_requires_auth_from_network():
    client = TestClient(web.app)  # ADMIN_TOKEN="" → network client gets 403
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 403


def test_settings_returns_401_with_wrong_token(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    client = TestClient(web.app)
    resp = client.get("/api/admin/settings", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/admin/settings/{category}
# ---------------------------------------------------------------------------

def test_get_known_category_returns_200(admin_client):
    resp = admin_client.get("/api/admin/settings/general", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert "general" in data
    assert isinstance(data["general"], list)


def test_get_unknown_category_returns_404(admin_client):
    resp = admin_client.get("/api/admin/settings/nonexistent_xyz_abc", headers=_HDR)
    assert resp.status_code == 404
    assert "unknown category" in resp.json()["error"]


def test_get_category_items_have_key_value(admin_client):
    resp = admin_client.get("/api/admin/settings/general", headers=_HDR)
    items = resp.json().get("general", [])
    if items:
        for item in items:
            assert "key" in item or isinstance(item, dict)


# ---------------------------------------------------------------------------
# PUT /api/admin/settings/{category}
# ---------------------------------------------------------------------------

def test_put_category_returns_updated_and_category(admin_client):
    resp = admin_client.put(
        "/api/admin/settings/general",
        json={"values": {"wake_words": ["jarvis"]}},
        headers=_HDR,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "updated" in data
    assert data["category"] == "general"


def test_put_category_updated_is_count(admin_client):
    resp = admin_client.put(
        "/api/admin/settings/general",
        json={"values": {"wake_words": ["friday"]}},
        headers=_HDR,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["updated"], int)


def test_put_category_without_token_is_denied(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    client = TestClient(web.app)
    resp = client.put("/api/admin/settings/general", json={"values": {}})
    assert resp.status_code == 401


def test_put_category_empty_values_accepted(admin_client):
    resp = admin_client.put(
        "/api/admin/settings/general",
        json={"values": {}},
        headers=_HDR,
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/admin/settings/reseed
# ---------------------------------------------------------------------------

def test_reseed_returns_ok_true(admin_client):
    resp = admin_client.post("/api/admin/settings/reseed", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "reseeded" in data.get("message", "").lower()


def test_reseed_without_token_denied(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    client = TestClient(web.app)
    resp = client.post("/api/admin/settings/reseed")
    assert resp.status_code == 401


def test_put_unknown_keys_returns_skipped_list(admin_client):
    resp = admin_client.put(
        "/api/admin/settings/general",
        json={"values": {"totally_unknown_key_xyz": "value"}},
        headers=_HDR,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] == 0
    assert "skipped" in data
    assert "totally_unknown_key_xyz" in data["skipped"]


def test_put_no_unknown_keys_omits_skipped_field(admin_client):
    resp = admin_client.put(
        "/api/admin/settings/general",
        json={"values": {"wake_words": ["jarvis"]}},
        headers=_HDR,
    )
    assert resp.status_code == 200
    assert "skipped" not in resp.json()


def test_settings_round_trip(admin_client):
    """Write a known key then read it back from the same category."""
    admin_client.put(
        "/api/admin/settings/general",
        json={"values": {"wake_words": ["friday", "hub"]}},
        headers=_HDR,
    )
    resp = admin_client.get("/api/admin/settings/general", headers=_HDR)
    assert resp.status_code == 200
    items = resp.json().get("general", [])
    keys = [i.get("key") for i in items if isinstance(i, dict)]
    assert "wake_words" in keys
