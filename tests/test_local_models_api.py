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
    router._backend_name = name
    router.name = "cloud+composite"  # provider identity must not be parsed from this
    router.lm_studio_url = "http://localhost:1234"
    router.ollama_url = "http://localhost:11434"
    return router


def test_list_local_models_shape(token_client):
    import agents.web as web
    from agents.core.llm.local_model_inventory import invalidate_local_model_inventory_cache

    invalidate_local_model_inventory_cache()
    factory = _fake_httpx_client({
        "/v1/models": LM_MODELS,
        "/api/v0/models": _FakeResp({"data": []}),
        "/api/tags": OLLAMA_MODELS,
        "/api/ps": _FakeResp({"models": []}),
    })
    with patch.object(web, "orch", MagicMock(llm_router=_router_mock("qwen3:7b", "lm-studio"))):
        with patch("httpx.AsyncClient", factory):
            resp = token_client.get("/api/models/local", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] == "qwen3:7b"
    assert data["configured_model"] == "qwen3:7b"
    assert data["resident_models"] == []
    assert data["residency_state"] == "known"
    ids = {m["id"] for m in data["models"]}
    assert ids == {"qwen3:7b", "llama3:8b", "mistral:latest"}
    configured = [m for m in data["models"] if m["configured"]]
    assert len(configured) == 1 and configured[0]["id"] == "qwen3:7b"
    assert configured[0]["active"] is True
    assert configured[0]["resident"] is False
    providers = {p["name"]: p["online"] for p in data["providers"]}
    assert providers == {"lm-studio": True, "ollama": True}


def test_list_reports_offline_provider(token_client):
    import agents.web as web
    from agents.core.llm.local_model_inventory import invalidate_local_model_inventory_cache

    invalidate_local_model_inventory_cache()
    factory = _fake_httpx_client({
        "/v1/models": LM_MODELS,
        "/api/v0/models": _FakeResp({"data": []}),
    })  # ollama URLs -> 404
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
        "configured_model": "qwen3:7b",
        "backend": "lm-studio",
        "providers": [{"name": "lm-studio", "online": True}],
        "resident_models": [],
        "residency_state": "known",
        "models": [
            {"id": "qwen3:7b", "provider": "lm-studio", "available": True,
             "configured": True, "active": True},
            {"id": "llama3:8b", "provider": "lm-studio", "available": True,
             "configured": False, "active": False},
        ],
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
        "active": "qwen3:7b", "configured_model": "qwen3:7b",
        "backend": "lm-studio", "providers": [], "resident_models": [],
        "residency_state": "known",
        "models": [{"id": "qwen3:7b", "provider": "lm-studio",
                    "available": True, "configured": True, "active": True}],
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


def test_switch_rejects_unavailable_model(token_client):
    import agents.web as web

    router = _router_mock("qwen3:7b", "lm-studio")
    catalog = {
        "active": "qwen3:7b",
        "configured_model": "qwen3:7b",
        "backend": "lm-studio",
        "providers": [],
        "resident_models": [],
        "residency_state": "known",
        "models": [
            {"id": "ghost-model", "provider": "lm-studio", "available": False,
             "configured": False, "active": False}
        ],
    }
    with patch.object(web, "orch", MagicMock(llm_router=router)):
        with patch.object(web, "_list_local_models", AsyncMock(return_value=catalog)):
            resp = token_client.post(
                "/api/models/local/switch", json={"model": "ghost-model"}, headers=HEADERS
            )

    assert resp.status_code == 404
    router.set_active_model.assert_not_called()


def test_switch_rejects_ambiguous_provider_pair(token_client):
    import agents.web as web

    router = _router_mock(None, "none")
    catalog = {
        "active": None,
        "configured_model": None,
        "backend": "none",
        "providers": [],
        "resident_models": [],
        "residency_state": "known",
        "models": [
            {"id": "alpha", "provider": "lm-studio", "available": True,
             "configured": False, "active": False},
            {"id": "alpha", "provider": "ollama", "available": True,
             "configured": False, "active": False},
        ],
    }
    with patch.object(web, "orch", MagicMock(llm_router=router)):
        with patch.object(web, "_list_local_models", AsyncMock(return_value=catalog)):
            resp = token_client.post(
                "/api/models/local/switch", json={"model": "alpha"}, headers=HEADERS
            )

    assert resp.status_code == 409
    assert resp.json()["error"] == "model id is ambiguous across local providers"
    assert resp.json()["providers"] == ["lm-studio", "ollama"]
    router.set_active_model.assert_not_called()


@pytest.mark.parametrize(
    ("path", "body", "method_name"),
    [
        ("/api/llm/load", {"model": "alpha"}, "load_model"),
        ("/api/llm/unload", {"model": "alpha"}, "unload_model"),
    ],
)
def test_successful_lifecycle_invalidates_inventory_cache(
    token_client, path, body, method_name
):
    import agents.core.routers.models_llm as models_llm
    import agents.web as web

    ctrl = MagicMock()
    setattr(ctrl, method_name, AsyncMock(return_value={"status": "ok", "model": "alpha"}))
    with patch.object(web, "orch", MagicMock(lmstudio=ctrl)):
        with patch.object(models_llm, "invalidate_local_model_inventory_cache") as invalidate:
            resp = token_client.post(path, json=body, headers=HEADERS)

    assert resp.status_code == 200
    invalidate.assert_called_once_with()
