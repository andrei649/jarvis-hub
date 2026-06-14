"""Tests for H12.10 trust indicator endpoint (mic + strict-local)."""
import pytest
from fastapi.testclient import TestClient
from agents import web
# _trust_status / _env_truthy moved into the oauth router (CLN-3). They read the
# live orchestrator via app_state.get_orch(), which resolves web.orch at call
# time, so monkeypatch.setattr(web, "orch", ...) below is still observed.
from agents.core.routers.oauth import _trust_status, _env_truthy


@pytest.fixture
def client():
    with TestClient(web.app) as c:
        yield c


def test_trust_status_shape(client):
    resp = client.get("/api/trust/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mic"] in ("on", "off")
    assert isinstance(data["strict_local"], bool)
    assert isinstance(data["cloud_available"], bool)
    assert isinstance(data["claude_available"], bool)


def test_trust_status_no_store_header(client):
    resp = client.get("/api/trust/status")
    assert resp.headers.get("Cache-Control") == "no-store"


def test_mic_default_on():
    assert _trust_status()["mic"] == "on"


def test_mic_muted_via_env(monkeypatch):
    monkeypatch.setenv("JARVIS_MIC_MUTED", "1")
    assert _trust_status()["mic"] == "off"
    monkeypatch.setenv("JARVIS_MIC_MUTED", "true")
    assert _trust_status()["mic"] == "off"
    monkeypatch.setenv("JARVIS_MIC_MUTED", "0")
    assert _trust_status()["mic"] == "on"


def test_strict_local_env_override_forces_on(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_LOCAL", "1")
    assert _trust_status()["strict_local"] is True


def test_strict_local_reflects_cloud_availability(monkeypatch):
    """strict_local must be False once any cloud backend is reachable."""
    monkeypatch.delenv("JARVIS_STRICT_LOCAL", raising=False)

    class _Router:
        _cloud_available = True
        _claude_available = False

    monkeypatch.setattr(web, "orch", type("O", (), {"llm_router": _Router()})())
    data = _trust_status()
    assert data["cloud_available"] is True
    assert data["strict_local"] is False


def test_strict_local_true_when_no_cloud(monkeypatch):
    monkeypatch.delenv("JARVIS_STRICT_LOCAL", raising=False)

    class _Router:
        _cloud_available = False
        _claude_available = False

    monkeypatch.setattr(web, "orch", type("O", (), {"llm_router": _Router()})())
    assert _trust_status()["strict_local"] is True


def test_env_truthy_spellings():
    assert _env_truthy("yes") is True
    assert _env_truthy("ON") is True
    assert _env_truthy("") is False
    assert _env_truthy(None) is False
    assert _env_truthy("off") is False
