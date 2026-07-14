"""Tests for local model management endpoints (H12.9).

Covers GET /api/models/local (browse) and POST /api/models/local/switch
(activate). The local providers (LM Studio / Ollama) are mocked so the tests
run in CI without a live backend.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
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
    router = _router_mock("qwen3:7b", "lm-studio")
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


def test_switch_adopts_and_configures_unique_cross_provider_pair(token_client):
    import agents.core.routers.models_llm as models_llm
    import agents.web as web
    from agents.core.llm.local_model_inventory import (
        get_local_model_inventory,
        invalidate_local_model_inventory_cache,
    )

    settings = {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    router = SimpleNamespace(
        active_model="qwen3:7b",
        _backend_name="lm-studio",
        name="lm-studio+cloud",
        backend_type="lm-studio",
        lm_studio_url="http://localhost:1234",
        ollama_url="http://localhost:11434",
    )

    def _set_active(model):
        router.active_model = model

    async def _detect():
        # Mirrors HybridRouter.detect(): provider pin is reloaded from settings.
        router.backend_type = settings["backend_type"]
        router._backend_name = router.backend_type

    router.set_active_model = MagicMock(side_effect=_set_active)
    router.detect = AsyncMock(side_effect=_detect)

    catalog = {
        "active": "qwen3:7b",
        "configured_model": "qwen3:7b",
        "backend": "lm-studio",
        "providers": [],
        "resident_models": [],
        "residency_state": "known",
        "models": [
            {
                "id": "mistral:latest",
                "provider": "ollama",
                "available": True,
                "configured": False,
                "active": False,
            }
        ],
    }

    def _persist(category, data):
        assert category == "llm"
        settings.update(data)
        return len(data), []

    with patch.object(web, "orch", SimpleNamespace(llm_router=router)):
        with patch.object(web, "_list_local_models", AsyncMock(return_value=catalog)):
            with patch.object(models_llm, "put_category", side_effect=_persist) as put:
                response = token_client.post(
                    "/api/models/local/switch",
                    json={"model": "mistral:latest"},
                    headers=HEADERS,
                )

        invalidate_local_model_inventory_cache()
        factory = _fake_httpx_client(
            {
                "/v1/models": _FakeResp({"data": [{"id": "qwen3:7b"}]}),
                "/api/v0/models": _FakeResp({"data": []}),
                "/api/tags": _FakeResp({"models": [{"name": "mistral:latest"}]}),
                "/api/ps": _FakeResp({"models": []}),
            }
        )
        with patch("httpx.AsyncClient", factory):
            inventory = asyncio.run(
                get_local_model_inventory(
                    router=router,
                    controller=SimpleNamespace(enabled=True),
                    force_refresh=True,
                )
            )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "active": "mistral:latest"}
    put.assert_called_once_with(
        "llm", {"backend_type": "ollama", "default_model": "mistral:latest"}
    )
    router.detect.assert_awaited_once_with()
    configured = [model for model in inventory["models"] if model["configured"]]
    assert len(configured) == 1
    assert configured[0]["provider"] == "ollama"
    assert configured[0]["id"] == "mistral:latest"
    assert configured[0]["available"] is True


def test_switch_fails_closed_when_cross_provider_cannot_be_adopted(token_client):
    import agents.core.routers.models_llm as models_llm
    import agents.web as web

    settings = {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    router = _router_mock("qwen3:7b", "lm-studio")
    router.backend_type = "lm-studio"

    async def _detect():
        requested = settings["backend_type"]
        router.backend_type = requested
        # Target adoption fails; rollback to LM Studio remains possible.
        router._backend_name = "lm-studio" if requested == "lm-studio" else "none"

    router.detect = AsyncMock(side_effect=_detect)
    catalog = {
        "active": "qwen3:7b",
        "configured_model": "qwen3:7b",
        "backend": "lm-studio",
        "providers": [],
        "resident_models": [],
        "residency_state": "known",
        "models": [
            {"id": "mistral:latest", "provider": "ollama", "available": True}
        ],
    }

    def _persist(category, data):
        assert category == "llm"
        settings.update(data)
        return len(data), []

    def _read_setting(category, key, default=None):
        assert category == "llm"
        return settings.get(key, default)

    with patch.object(web, "orch", SimpleNamespace(llm_router=router)):
        with patch.object(web, "_list_local_models", AsyncMock(return_value=catalog)):
            with patch.object(models_llm, "get_value", side_effect=_read_setting):
                with patch.object(models_llm, "put_category", side_effect=_persist):
                    response = token_client.post(
                        "/api/models/local/switch",
                        json={"model": "mistral:latest"},
                        headers=HEADERS,
                    )

    assert response.status_code == 409
    assert response.json() == {
        "error": "local provider could not be adopted",
        "provider": "ollama",
    }
    assert settings == {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    assert router._backend_name == "lm-studio"
    assert router.active_model == "qwen3:7b"
    router.detect.assert_awaited()
    assert not any(
        call.args == ("mistral:latest",) for call in router.set_active_model.call_args_list
    )


def test_failed_switch_restores_persisted_pair_when_runtime_model_is_none(token_client):
    import agents.core.routers.models_llm as models_llm
    import agents.web as web

    persisted = {"backend_type": "lm-studio", "default_model": "owner-default"}
    router = _router_mock(None, "lm-studio")
    # Runtime selection can legitimately differ from the persisted configuration.
    router.backend_type = "auto"

    async def _detect():
        requested = persisted["backend_type"]
        router.backend_type = requested
        router._backend_name = "lm-studio" if requested in {"auto", "lm-studio"} else "none"

    def _read_setting(category, key, default=None):
        assert category == "llm"
        return persisted.get(key, default)

    def _persist(category, data):
        assert category == "llm"
        persisted.update(data)
        return len(data), []

    router.detect = AsyncMock(side_effect=_detect)
    catalog = {
        "active": None,
        "configured_model": "owner-default",
        "backend": "lm-studio",
        "providers": [],
        "resident_models": [],
        "residency_state": "known",
        "models": [
            {"id": "mistral:latest", "provider": "ollama", "available": True}
        ],
    }

    with patch.object(web, "orch", SimpleNamespace(llm_router=router)):
        with patch.object(web, "_list_local_models", AsyncMock(return_value=catalog)):
            with patch.object(models_llm, "get_value", side_effect=_read_setting):
                with patch.object(models_llm, "put_category", side_effect=_persist):
                    response = token_client.post(
                        "/api/models/local/switch",
                        json={"model": "mistral:latest"},
                        headers=HEADERS,
                    )

    assert response.status_code == 409
    assert persisted == {
        "backend_type": "lm-studio",
        "default_model": "owner-default",
    }
    assert router.active_model is None
    assert router._backend_name == "lm-studio"


async def test_concurrent_switches_serialize_and_leave_one_coherent_pair(monkeypatch):
    import agents.core.routers.models_llm as models_llm

    persisted = {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    router = SimpleNamespace(
        active_model="qwen3:7b",
        _backend_name="lm-studio",
        backend_type="lm-studio",
    )
    first_detect_started = asyncio.Event()
    release_first_detect = asyncio.Event()
    detect_count = 0
    listing_count = 0

    def _set_active(model):
        router.active_model = model

    async def _detect():
        nonlocal detect_count
        detect_count += 1
        requested_provider = persisted["backend_type"]
        if detect_count == 1:
            assert requested_provider == "ollama"
            first_detect_started.set()
            await release_first_detect.wait()
        router.backend_type = requested_provider
        router._backend_name = requested_provider

    catalogs = [
        {
            "models": [
                {"id": "mistral:latest", "provider": "ollama", "available": True}
            ]
        },
        {
            "models": [
                {"id": "qwen3:7b", "provider": "lm-studio", "available": True}
            ]
        },
    ]

    async def _listing():
        nonlocal listing_count
        result = catalogs[listing_count]
        listing_count += 1
        return result

    def _read_setting(category, key, default=None):
        assert category == "llm"
        return persisted.get(key, default)

    def _persist(category, data):
        assert category == "llm"
        persisted.update(data)
        return len(data), []

    router.set_active_model = MagicMock(side_effect=_set_active)
    router.detect = AsyncMock(side_effect=_detect)
    web_stub = SimpleNamespace(_list_local_models=_listing)
    monkeypatch.setattr(models_llm, "get_orch", lambda: SimpleNamespace(llm_router=router))
    monkeypatch.setattr(models_llm, "_web", lambda: web_stub)
    monkeypatch.setattr(models_llm, "get_value", _read_setting)
    monkeypatch.setattr(models_llm, "put_category", _persist)
    monkeypatch.setattr(models_llm, "invalidate_local_model_inventory_cache", MagicMock())

    first = asyncio.create_task(
        models_llm.models_local_switch(
            models_llm.LocalModelSwitch(model="mistral:latest")
        )
    )
    await first_detect_started.wait()
    second_entered = asyncio.Event()

    async def _second_switch():
        second_entered.set()
        return await models_llm.models_local_switch(
            models_llm.LocalModelSwitch(model="qwen3:7b")
        )

    second = asyncio.create_task(_second_switch())
    await second_entered.wait()
    await asyncio.sleep(0)
    serialized_while_first_paused = listing_count == 1 and not second.done()
    release_first_detect.set()
    first_response, second_response = await asyncio.gather(first, second)

    assert serialized_while_first_paused is True
    assert listing_count == 2
    assert json.loads(first_response.body) == {"ok": True, "active": "mistral:latest"}
    assert json.loads(second_response.body) == {"ok": True, "active": "qwen3:7b"}
    assert persisted == {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    assert (router._backend_name, router.active_model) == ("lm-studio", "qwen3:7b")


async def test_cancelled_switch_completes_rollback_before_releasing_lock(monkeypatch):
    import agents.core.routers.models_llm as models_llm

    persisted = {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    router = SimpleNamespace(
        active_model="qwen3:7b",
        _backend_name="lm-studio",
        backend_type="lm-studio",
    )
    adoption_started = asyncio.Event()
    rollback_started = asyncio.Event()
    release_rollback = asyncio.Event()
    detect_count = 0

    def _set_active(model):
        router.active_model = model

    async def _detect():
        nonlocal detect_count
        detect_count += 1
        if detect_count == 1:
            adoption_started.set()
            await asyncio.Event().wait()
        else:
            rollback_started.set()
            await release_rollback.wait()
            router._backend_name = router.backend_type

    async def _listing():
        return {
            "models": [
                {"id": "mistral:latest", "provider": "ollama", "available": True}
            ]
        }

    def _read_setting(category, key, default=None):
        assert category == "llm"
        return persisted.get(key, default)

    def _persist(category, data):
        assert category == "llm"
        persisted.update(data)
        return len(data), []

    router.set_active_model = MagicMock(side_effect=_set_active)
    router.detect = AsyncMock(side_effect=_detect)
    monkeypatch.setattr(models_llm, "get_orch", lambda: SimpleNamespace(llm_router=router))
    monkeypatch.setattr(
        models_llm,
        "_web",
        lambda: SimpleNamespace(_list_local_models=_listing),
    )
    monkeypatch.setattr(models_llm, "get_value", _read_setting)
    monkeypatch.setattr(models_llm, "put_category", _persist)
    invalidate = MagicMock()
    monkeypatch.setattr(models_llm, "invalidate_local_model_inventory_cache", invalidate)

    request = asyncio.create_task(
        models_llm.models_local_switch(
            models_llm.LocalModelSwitch(model="mistral:latest")
        )
    )
    await adoption_started.wait()
    request.cancel()
    rollback_observed = False
    try:
        await asyncio.wait_for(rollback_started.wait(), timeout=0.5)
        rollback_observed = True
        # A second cancellation while rollback is paused must not release the
        # switch lock or interrupt restoration of the authoritative pair.
        request.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert request.done() is False
        assert models_llm._model_switch_lock.locked() is True
    finally:
        release_rollback.set()

    with pytest.raises(asyncio.CancelledError):
        await request

    assert rollback_observed is True
    assert persisted == {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    assert (router._backend_name, router.active_model) == ("lm-studio", "qwen3:7b")
    assert models_llm._model_switch_lock.locked() is False
    invalidate.assert_not_called()


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
        with patch.object(models_llm, "put_category") as put:
            with patch.object(models_llm, "invalidate_local_model_inventory_cache") as invalidate:
                resp = token_client.post(path, json=body, headers=HEADERS)

    assert resp.status_code == 200
    invalidate.assert_called_once_with()
    if method_name == "load_model":
        put.assert_called_once_with("llm", {"default_model": "alpha"})
    else:
        put.assert_not_called()
