"""Tests for local model management endpoints (H12.9).

Covers GET /api/models/local (browse) and POST /api/models/local/switch
(activate). The local providers (LM Studio / Ollama) are mocked so the tests
run in CI without a live backend.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

HEADERS = {"X-Admin-Token": "test-secret"}


@pytest.fixture(scope="module")
def token_client():
    import agents.web as web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


class _FakeResp:
    def __init__(self, payload, ok=True, status=200):
        self._payload = payload
        self.is_success = ok
        self.status_code = status

    def json(self):
        return self._payload


def _fake_httpx_client(responses):
    """Build an httpx.AsyncClient stand-in mapping URL -> _FakeResp."""
    client = MagicMock()

    async def _get(url):
        for needle, resp in responses.items():
            if needle in url:
                return resp
        return _FakeResp({}, ok=False, status=404)

    client.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory


LM_MODELS = _FakeResp({"data": [{"id": "qwen3:7b"}, {"id": "llama3:8b"}]})
OLLAMA_MODELS = _FakeResp({"models": [{"name": "mistral:latest"}]})


def test_requires_admin_token(token_client):
    resp = token_client.get("/api/models/local")
    assert resp.status_code == 401


def _router_mock(active, name):
    router = MagicMock(active_model=active)
    router.name = name  # `name` is a reserved MagicMock kwarg; set explicitly
    return router


def test_list_local_models_shape(token_client):
    import agents.web as web
    factory = _fake_httpx_client({"1234": LM_MODELS, "11434": OLLAMA_MODELS})
    with patch.object(web, "orch", MagicMock(llm_router=_router_mock("qwen3:7b", "lm-studio"))):
        with patch("httpx.AsyncClient", factory):
            resp = token_client.get("/api/models/local", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] == "qwen3:7b"
    ids = {m["id"] for m in data["models"]}
    assert ids == {"qwen3:7b", "llama3:8b", "mistral:latest"}
    active = [m for m in data["models"] if m["active"]]
    assert len(active) == 1 and active[0]["id"] == "qwen3:7b"
    providers = {p["name"]: p["online"] for p in data["providers"]}
    assert providers == {"lm-studio": True, "ollama": True}


def test_list_reports_offline_provider(token_client):
    import agents.web as web
    factory = _fake_httpx_client({"1234": LM_MODELS})  # ollama URL -> 404
    with patch.object(web, "orch", MagicMock(llm_router=_router_mock(None, "lm-studio"))):
        with patch("httpx.AsyncClient", factory):
            resp = token_client.get("/api/models/local", headers=HEADERS)

    data = resp.json()
    providers = {p["name"]: p["online"] for p in data["providers"]}
    assert providers["lm-studio"] is True
    assert providers["ollama"] is False
    assert {m["id"] for m in data["models"]} == {"qwen3:7b", "llama3:8b"}


def test_switch_to_available_model(token_client):
    import agents.web as web
    router = MagicMock(active_model="qwen3:7b", name="lm-studio")
    catalog = {
        "active": "qwen3:7b",
        "backend": "lm-studio",
        "providers": [{"name": "lm-studio", "online": True}],
        "models": [{"id": "qwen3:7b", "provider": "lm-studio", "active": True},
                   {"id": "llama3:8b", "provider": "lm-studio", "active": False}],
    }
    import agents.core.routers.models_llm as models_llm
    with patch.object(web, "orch", MagicMock(llm_router=router)):
        with patch.object(web, "_list_local_models", AsyncMock(return_value=catalog)):
            with patch.object(models_llm, "put_category") as put:
                resp = token_client.post(
                    "/api/models/local/switch", json={"model": "llama3:8b"}, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "active": "llama3:8b"}
    router.set_active_model.assert_called_once_with("llama3:8b")
    put.assert_called_once_with("llm", {"default_model": "llama3:8b"})


def test_switch_to_unknown_model_404(token_client):
    import agents.web as web
    router = MagicMock(active_model="qwen3:7b", name="lm-studio")
    catalog = {
        "active": "qwen3:7b", "backend": "lm-studio", "providers": [],
        "models": [{"id": "qwen3:7b", "provider": "lm-studio", "active": True}],
    }
    with patch.object(web, "orch", MagicMock(llm_router=router)):
        with patch.object(web, "_list_local_models", AsyncMock(return_value=catalog)):
            resp = token_client.post(
                "/api/models/local/switch", json={"model": "ghost-model"}, headers=HEADERS)

    assert resp.status_code == 404
    router.set_active_model.assert_not_called()
    assert "ghost-model" in resp.json()["error"]


def test_switch_requires_model_field(token_client):
    resp = token_client.post("/api/models/local/switch", json={}, headers=HEADERS)
    assert resp.status_code == 422
