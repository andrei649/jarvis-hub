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


async def test_rollback_verifies_none_runtime_model_was_actually_restored(monkeypatch):
    import agents.core.routers.models_llm as models_llm

    monkeypatch.setattr(models_llm, "_model_switch_lock", asyncio.Lock())
    persisted = {"backend_type": "lm-studio", "default_model": "owner-default"}
    router = SimpleNamespace(
        active_model=None,
        _backend_name="lm-studio",
        backend_type="lm-studio",
    )
    detect_count = 0

    async def _detect():
        nonlocal detect_count
        detect_count += 1
        router.backend_type = persisted["backend_type"]
        if detect_count == 1:
            router._backend_name = "none"
            router.active_model = "stale-target"
        else:
            router._backend_name = "lm-studio"
            # Deliberately leave stale-target in place after provider restore.

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

    router.detect = AsyncMock(side_effect=_detect)
    # A failed/no-op clear must be observed, not assumed successful.
    router.set_active_model = MagicMock()
    monkeypatch.setattr(
        models_llm,
        "get_orch",
        lambda: SimpleNamespace(llm_router=router),
    )
    monkeypatch.setattr(
        models_llm,
        "_web",
        lambda: SimpleNamespace(_list_local_models=_listing),
    )
    monkeypatch.setattr(models_llm, "get_value", _read_setting)
    monkeypatch.setattr(models_llm, "put_category", _persist)
    monkeypatch.setattr(models_llm, "invalidate_local_model_inventory_cache", MagicMock())

    response = await models_llm.models_local_switch(
        models_llm.LocalModelSwitch(model="mistral:latest")
    )

    assert response.status_code == 500
    assert json.loads(response.body) == {
        "error": "local provider adoption rollback incomplete",
        "provider": "ollama",
    }
    assert persisted == {
        "backend_type": "lm-studio",
        "default_model": "owner-default",
    }
    assert router._backend_name == "lm-studio"
    assert router.active_model == "stale-target"
    router.set_active_model.assert_called_once_with(None)


@pytest.mark.parametrize(
    "rollback_fault", ["partial-write", "write-raises", "wrong-provider"]
)
async def test_incomplete_provider_rollback_returns_distinct_bounded_server_error(
    monkeypatch, rollback_fault
):
    import agents.core.routers.models_llm as models_llm

    monkeypatch.setattr(models_llm, "_model_switch_lock", asyncio.Lock())
    persisted = {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    router = SimpleNamespace(
        active_model="qwen3:7b",
        _backend_name="lm-studio",
        backend_type="lm-studio",
    )
    detect_count = 0
    write_count = 0
    read_keys: list[str] = []

    def _set_active(model):
        router.active_model = model

    async def _detect():
        nonlocal detect_count
        detect_count += 1
        router.backend_type = persisted["backend_type"]
        if detect_count == 1:
            router._backend_name = "none"
        elif rollback_fault == "wrong-provider":
            router._backend_name = "ollama"
        else:
            router._backend_name = (
                "lm-studio" if router.backend_type == "lm-studio" else "none"
            )

    async def _listing():
        return {
            "models": [
                {"id": "mistral:latest", "provider": "ollama", "available": True}
            ]
        }

    def _read_setting(category, key, default=None):
        assert category == "llm"
        read_keys.append(key)
        return persisted.get(key, default)

    def _persist(category, data):
        nonlocal write_count
        assert category == "llm"
        write_count += 1
        if write_count == 1:
            persisted.update(data)
            return len(data), []
        if rollback_fault == "partial-write":
            persisted["backend_type"] = data["backend_type"]
            return 1, ["default_model"]
        if rollback_fault == "write-raises":
            raise RuntimeError("secret rollback database path")
        persisted.update(data)
        return len(data), []

    router.set_active_model = MagicMock(side_effect=_set_active)
    router.detect = AsyncMock(side_effect=_detect)
    orch = SimpleNamespace(llm_router=router)
    monkeypatch.setattr(models_llm, "get_orch", lambda: orch)
    monkeypatch.setattr(
        models_llm,
        "_web",
        lambda: SimpleNamespace(_list_local_models=_listing),
    )
    monkeypatch.setattr(models_llm, "get_value", _read_setting)
    monkeypatch.setattr(models_llm, "put_category", _persist)
    invalidate = MagicMock()
    monkeypatch.setattr(models_llm, "invalidate_local_model_inventory_cache", invalidate)

    response = await models_llm.models_local_switch(
        models_llm.LocalModelSwitch(model="mistral:latest")
    )
    payload = json.loads(response.body)

    assert response.status_code == 500
    assert payload == {
        "error": "local provider adoption rollback incomplete",
        "provider": "ollama",
    }
    assert "secret" not in str(payload)
    assert write_count == 2
    assert detect_count == 2
    assert read_keys == [
        "backend_type",
        "default_model",
        "backend_type",
        "default_model",
    ]
    invalidate.assert_not_called()


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


@pytest.mark.parametrize("lifecycle", ["load", "unload"])
async def test_lifecycle_waits_for_switch_and_preserves_provider_model_pair(
    monkeypatch, lifecycle
):
    import agents.core.routers.models_llm as models_llm

    monkeypatch.setattr(models_llm, "_model_switch_lock", asyncio.Lock())
    persisted = {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    writes: list[dict] = []
    router = SimpleNamespace(
        active_model="qwen3:7b",
        _backend_name="lm-studio",
        backend_type="lm-studio",
    )
    switch_detect_started = asyncio.Event()
    release_switch_detect = asyncio.Event()
    lifecycle_entered = asyncio.Event()
    pair_on_lifecycle_entry: list[tuple[str, str | None]] = []

    def _set_active(model):
        router.active_model = model

    async def _detect():
        switch_detect_started.set()
        await release_switch_detect.wait()
        router.backend_type = persisted["backend_type"]
        router._backend_name = persisted["backend_type"]

    async def _listing():
        return {
            "models": [
                {"id": "mistral:latest", "provider": "ollama", "available": True}
            ]
        }

    async def _lifecycle_result(*args, **kwargs):
        lifecycle_entered.set()
        pair_on_lifecycle_entry.append((router._backend_name, router.active_model))
        # Mirrors the controller's internal router refresh: lifecycle owns the
        # LM Studio process, but must not leave a non-LM routing pair changed.
        router.active_model = "lm-alpha" if lifecycle == "load" else None
        return {"status": "ok", "model": "lm-alpha"}

    def _read_setting(category, key, default=None):
        assert category == "llm"
        return persisted.get(key, default)

    def _persist(category, data):
        assert category == "llm"
        writes.append(dict(data))
        persisted.update(data)
        return len(data), []

    router.set_active_model = MagicMock(side_effect=_set_active)
    router.detect = AsyncMock(side_effect=_detect)
    ctrl = SimpleNamespace(
        load_model=AsyncMock(side_effect=_lifecycle_result),
        unload_model=AsyncMock(side_effect=_lifecycle_result),
    )
    orch = SimpleNamespace(llm_router=router, lmstudio=ctrl)
    monkeypatch.setattr(models_llm, "get_orch", lambda: orch)
    monkeypatch.setattr(
        models_llm,
        "_web",
        lambda: SimpleNamespace(_list_local_models=_listing),
    )
    monkeypatch.setattr(models_llm, "get_value", _read_setting)
    monkeypatch.setattr(models_llm, "put_category", _persist)
    invalidate = MagicMock()
    monkeypatch.setattr(models_llm, "invalidate_local_model_inventory_cache", invalidate)

    switch = asyncio.create_task(
        models_llm.models_local_switch(
            models_llm.LocalModelSwitch(model="mistral:latest")
        )
    )
    await switch_detect_started.wait()
    if lifecycle == "load":
        lifecycle_request = asyncio.create_task(
            models_llm.llm_load(models_llm.LMLoad(model="lm-alpha"))
        )
    else:
        lifecycle_request = asyncio.create_task(
            models_llm.llm_unload(models_llm.LMUnload(model="lm-alpha"))
        )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    lifecycle_entered_while_switch_paused = lifecycle_entered.is_set()
    release_switch_detect.set()
    switch_response, lifecycle_response = await asyncio.gather(
        switch, lifecycle_request
    )

    assert lifecycle_entered_while_switch_paused is False
    assert json.loads(switch_response.body) == {"ok": True, "active": "mistral:latest"}
    assert json.loads(lifecycle_response.body)["status"] == "ok"
    assert pair_on_lifecycle_entry == [("ollama", "mistral:latest")]
    assert writes == [
        {"backend_type": "ollama", "default_model": "mistral:latest"}
    ]
    assert persisted == {
        "backend_type": "ollama",
        "default_model": "mistral:latest",
    }
    assert (router._backend_name, router.active_model) == (
        "ollama",
        "mistral:latest",
    )
    assert invalidate.call_count == 2


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


async def test_cancelled_switch_logs_bounded_critical_after_incomplete_rollback(
    monkeypatch,
):
    import agents.core.routers.models_llm as models_llm

    monkeypatch.setattr(models_llm, "_model_switch_lock", asyncio.Lock())
    persisted = {"backend_type": "lm-studio", "default_model": "qwen3:7b"}
    router = SimpleNamespace(
        active_model="qwen3:7b",
        _backend_name="lm-studio",
        backend_type="lm-studio",
    )
    adoption_started = asyncio.Event()
    rollback_detect_started = asyncio.Event()
    release_rollback_detect = asyncio.Event()
    write_count = 0
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
            rollback_detect_started.set()
            await release_rollback_detect.wait()
            router.backend_type = persisted["backend_type"]
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
        nonlocal write_count
        assert category == "llm"
        write_count += 1
        if write_count == 1:
            persisted.update(data)
            return len(data), []
        persisted["backend_type"] = data["backend_type"]
        return 1, ["default_model"]

    router.set_active_model = MagicMock(side_effect=_set_active)
    router.detect = AsyncMock(side_effect=_detect)
    monkeypatch.setattr(
        models_llm,
        "get_orch",
        lambda: SimpleNamespace(llm_router=router),
    )
    monkeypatch.setattr(
        models_llm,
        "_web",
        lambda: SimpleNamespace(_list_local_models=_listing),
    )
    monkeypatch.setattr(models_llm, "get_value", _read_setting)
    monkeypatch.setattr(models_llm, "put_category", _persist)
    invalidate = MagicMock()
    critical = MagicMock()
    monkeypatch.setattr(models_llm, "invalidate_local_model_inventory_cache", invalidate)
    monkeypatch.setattr(models_llm.logger, "critical", critical)

    request = asyncio.create_task(
        models_llm.models_local_switch(
            models_llm.LocalModelSwitch(model="mistral:latest")
        )
    )
    await adoption_started.wait()
    request.cancel()
    await asyncio.wait_for(rollback_detect_started.wait(), timeout=0.5)
    request.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert request.done() is False
    assert models_llm._model_switch_lock.locked() is True
    release_rollback_detect.set()

    with pytest.raises(asyncio.CancelledError):
        await request

    assert write_count == 2
    assert detect_count == 2
    assert persisted == {
        "backend_type": "lm-studio",
        "default_model": "mistral:latest",
    }
    critical.assert_called_once_with(
        "local provider rollback incomplete after cancelled adoption to %s",
        "ollama",
    )
    assert "secret" not in str(critical.call_args)
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
    orch = SimpleNamespace(
        lmstudio=ctrl,
        llm_router=SimpleNamespace(
            _backend_name="lm-studio",
            active_model="configured-beta",
        ),
    )
    with patch.object(web, "orch", orch):
        with patch.object(models_llm, "get_value", return_value="lm-studio") as get:
            with patch.object(models_llm, "put_category") as put:
                with patch.object(
                    models_llm, "invalidate_local_model_inventory_cache"
                ) as invalidate:
                    resp = token_client.post(path, json=body, headers=HEADERS)

    assert resp.status_code == 200
    invalidate.assert_called_once_with()
    get.assert_not_called()
    put.assert_not_called()


@pytest.mark.parametrize(
    ("path", "body", "method_name"),
    [
        ("/api/llm/load", {"model": "configured-beta"}, "load_model"),
        ("/api/llm/unload", {"model": "configured-beta"}, "unload_model"),
    ],
)
def test_lifecycle_preserves_lm_configured_model_after_controller_refresh(
    token_client, path, body, method_name
):
    import agents.core.routers.models_llm as models_llm
    import agents.web as web

    persisted = {
        "backend_type": "lm-studio",
        "default_model": "configured-beta",
    }
    router = SimpleNamespace(
        _backend_name="lm-studio",
        active_model="configured-beta",
    )

    def _set_active_model(model):
        router.active_model = model

    async def _lifecycle(*args, **kwargs):
        # The real controller refresh currently selects the catalog's first id.
        router.active_model = "catalog-first-alpha"
        return {"status": "ok", "model": "configured-beta"}

    def _persist(category, data):
        assert category == "llm"
        persisted.update(data)
        return len(data), []

    router.set_active_model = MagicMock(side_effect=_set_active_model)
    ctrl = MagicMock()
    setattr(ctrl, method_name, AsyncMock(side_effect=_lifecycle))
    orch = SimpleNamespace(lmstudio=ctrl, llm_router=router)

    with patch.object(web, "orch", orch):
        with patch.object(models_llm, "put_category", side_effect=_persist) as put:
            with patch.object(
                models_llm, "invalidate_local_model_inventory_cache"
            ) as invalidate:
                response = token_client.post(path, json=body, headers=HEADERS)

    assert response.status_code == 200
    assert router.active_model == "configured-beta"
    assert persisted == {
        "backend_type": "lm-studio",
        "default_model": "configured-beta",
    }
    router.set_active_model.assert_called_once_with("configured-beta")
    put.assert_not_called()
    invalidate.assert_called_once_with()


def test_load_never_combines_persisted_ollama_provider_with_lm_model(token_client):
    import agents.core.routers.models_llm as models_llm
    import agents.web as web

    ctrl = SimpleNamespace(
        load_model=AsyncMock(return_value={"status": "ok", "model": "lm-alpha"})
    )
    orch = SimpleNamespace(
        lmstudio=ctrl,
        # Deliberately stale live state: persisted provider remains authoritative
        # for preventing an incoherent Ollama + LM Studio model pair.
        llm_router=SimpleNamespace(_backend_name="lm-studio"),
    )
    with patch.object(web, "orch", orch):
        with patch.object(models_llm, "get_value", return_value="ollama") as get:
            with patch.object(models_llm, "put_category") as put:
                with patch.object(
                    models_llm, "invalidate_local_model_inventory_cache"
                ) as invalidate:
                    response = token_client.post(
                        "/api/llm/load",
                        json={"model": "lm-alpha"},
                        headers=HEADERS,
                    )

    assert response.status_code == 200
    get.assert_not_called()
    put.assert_not_called()
    invalidate.assert_called_once_with()
