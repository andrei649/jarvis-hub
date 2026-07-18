"""HTTP integration tests for the Self-Improvement dashboard router
(agents/core/routers/self_improvement.py):

  GET  /api/self-improvement/status  — read-only subsystem aggregation
  POST /api/self-improvement/enable  — convenience settings-bundle toggle

Mirrors the auth-guard pattern from test_admin_settings_mutations.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web  # noqa: E402
from agents.core import settings_db  # noqa: E402
from agents.core.routers import self_improvement as si_router  # noqa: E402

_TOKEN = "test-admin-secret"
_HDR = {"X-Admin-Token": _TOKEN}


@pytest.fixture()
def admin_client(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    return TestClient(web.app)


class _FakeObserver:
    def status(self):
        return {"probes": 2, "tracked": 1, "unhealthy": []}


class _FakeAcquisition:
    def status_snapshot(self):
        return {
            "enabled": True, "status": "ready",
            "states": {"missing": 1}, "reuse": {"reused": 2, "generated": 1, "reuse_rate": 0.66},
        }


class _FakeTechScout:
    def status(self):
        return {"configured": True, "last_run": None, "queries": ["q"], "total_seen": 0}


class _FakeOrch:
    def __init__(self, *, with_subsystems: bool = False):
        self.observer = _FakeObserver() if with_subsystems else None
        self.acquisition = _FakeAcquisition() if with_subsystems else None
        self.tech_scout = _FakeTechScout() if with_subsystems else None
        self._settings: dict = {}

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)


# ---------------------------------------------------------------------------
# Auth guards
# ---------------------------------------------------------------------------

def test_status_requires_auth_from_network(monkeypatch):
    # Explicit "" rather than relying on the module default: ADMIN_TOKEN is a
    # process-wide global other test files also monkeypatch, so asserting the
    # no-token-configured (403) path must not depend on suite execution order.
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    client = TestClient(web.app)
    resp = client.get("/api/self-improvement/status")
    assert resp.status_code == 403


def test_enable_requires_auth_from_network(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    client = TestClient(web.app)
    resp = client.post("/api/self-improvement/enable")
    assert resp.status_code == 403


def test_status_returns_401_with_wrong_token(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    client = TestClient(web.app)
    resp = client.get("/api/self-improvement/status", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/self-improvement/status
# ---------------------------------------------------------------------------

def test_status_honest_when_orchestrator_unavailable(admin_client, monkeypatch):
    monkeypatch.setattr(si_router, "get_orch", lambda: None)
    resp = admin_client.get("/api/self-improvement/status", headers=_HDR)
    assert resp.status_code == 200
    assert resp.json() == {"available": False}


def test_status_aggregates_subsystems_when_absent(admin_client, monkeypatch):
    monkeypatch.setattr(si_router, "get_orch", lambda: _FakeOrch(with_subsystems=False))
    resp = admin_client.get("/api/self-improvement/status", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["observer"] == {"enabled": False}
    assert data["acquisition"] == {"enabled": False, "status": "unavailable"}
    assert data["tech_scout"]["enabled"] is False
    assert data["tech_scout"]["available"] is False
    assert "errors" in data and "active_groups" in data["errors"]


def test_status_reflects_live_subsystems(admin_client, monkeypatch):
    fake = _FakeOrch(with_subsystems=True)
    fake._settings["autonomy.tech_scout_enabled"] = True
    monkeypatch.setattr(si_router, "get_orch", lambda: fake)
    resp = admin_client.get("/api/self-improvement/status", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["observer"] == {"enabled": True, "probes": 2, "tracked": 1, "unhealthy": []}
    assert data["acquisition"]["enabled"] is True
    assert data["acquisition"]["states"] == {"missing": 1}
    assert data["tech_scout"] == {
        "enabled": True, "available": True,
        "configured": True, "last_run": None, "queries": ["q"], "total_seen": 0,
    }


# ---------------------------------------------------------------------------
# POST /api/self-improvement/enable
# ---------------------------------------------------------------------------

@pytest.fixture()
def restore_bundle_settings():
    """The bundle endpoint writes real settings_db rows shared across the test
    session — snapshot and restore them so this test can't leak an enabled
    subsystem into unrelated tests that assume the shipped default-off state."""
    originals: dict[tuple[str, str], object] = {}
    for category, values in si_router._ENABLE_BUNDLE.items():
        for key in values:
            originals[(category, key)] = settings_db.get_value(category, key)
    yield
    for (category, key), value in originals.items():
        settings_db.put_category(category, {key: value})


def test_enable_flips_the_documented_bundle(admin_client, restore_bundle_settings):
    resp = admin_client.post("/api/self-improvement/enable", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()["applied"]
    assert data == {
        "cognition": {"enabled": True, "review_enabled": True},
        "acquisition": {"enabled": True},
        "ambient": {"enabled": True},
        "autonomy": {"tech_scout_enabled": True},
    }
    # And the settings actually changed, not just the response shape.
    assert settings_db.get_value("cognition", "enabled") is True
    assert settings_db.get_value("acquisition", "enabled") is True
    assert settings_db.get_value("ambient", "enabled") is True
    assert settings_db.get_value("autonomy", "tech_scout_enabled") is True


def test_enable_without_token_is_denied(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    client = TestClient(web.app)
    resp = client.post("/api/self-improvement/enable")
    assert resp.status_code == 401
