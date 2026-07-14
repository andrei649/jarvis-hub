"""Agreement tests for local inventory and the HUD-compatible status projection."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _module():
    return importlib.import_module("agents.core.llm.local_model_inventory")


def _inventory(
    *,
    resident_models: list[dict] | None = None,
    providers: list[dict] | None = None,
    configured_model: str | None = "configured",
    models: list[dict] | None = None,
    residency_state: str = "known",
) -> dict:
    return {
        "active": configured_model,
        "configured_model": configured_model,
        "backend": "lm-studio",
        "resident_models": resident_models or [],
        "residency_state": residency_state,
        "providers": providers
        or [
            {
                "name": "lm-studio",
                "online": True,
                "catalog_state": "known",
                "residency_state": residency_state,
            }
        ],
        "models": models or [],
    }


@pytest.mark.parametrize(
    ("inventory", "expected_state"),
    [
        (
            _inventory(
                resident_models=[{"provider": "ollama", "id": "resident"}],
                residency_state="unknown",
            ),
            "ready",
        ),
        (_inventory(residency_state="unknown"), "unknown"),
        (_inventory(residency_state="known"), "no_model"),
        (
            _inventory(
                residency_state="offline",
                providers=[
                    {
                        "name": "lm-studio",
                        "online": False,
                        "catalog_state": "offline",
                        "residency_state": "offline",
                    },
                    {
                        "name": "ollama",
                        "online": False,
                        "catalog_state": "offline",
                        "residency_state": "offline",
                    },
                ],
            ),
            "offline",
        ),
    ],
)
def test_status_projection_precedence(inventory, expected_state):
    projected = _module().project_llm_status(inventory)
    assert projected["model_state"] == expected_state
    assert projected["model_loaded"] == bool(inventory["resident_models"])
    assert projected["resident_models"] == inventory["resident_models"]
    assert projected["residency_state"] == inventory["residency_state"]


def test_status_projection_prefers_configured_resident_then_stable_first():
    module = _module()
    residents = [
        {"provider": "lm-studio", "id": "first"},
        {"provider": "ollama", "id": "configured"},
    ]
    configured = _inventory(
        resident_models=residents,
        models=[
            {
                "provider": "ollama",
                "id": "configured",
                "configured": True,
                "resident": True,
            }
        ],
    )
    assert module.project_llm_status(configured)["loaded_model"] == "configured"

    no_resident_match = _inventory(resident_models=residents, models=[])
    assert module.project_llm_status(no_resident_match)["loaded_model"] == "first"
    assert module.project_llm_status(_inventory())["loaded_model"] is None


def test_status_and_local_models_endpoint_share_exact_inventory(monkeypatch):
    import agents.web as web

    inventory = _inventory(
        resident_models=[
            {"provider": "lm-studio", "id": "configured"},
            {"provider": "ollama", "id": "other"},
        ],
        residency_state="unknown",
        models=[
            {
                "provider": "lm-studio",
                "id": "configured",
                "available": True,
                "configured": True,
                "active": True,
                "resident": True,
                "controls": {
                    "can_configure": True,
                    "can_load": False,
                    "can_unload": True,
                },
            }
        ],
    )
    router = SimpleNamespace(
        active_model="configured",
        _backend_name="lm-studio",
        name="lm-studio+cloud",
    )
    orch = SimpleNamespace(
        llm_router=router,
        lmstudio=SimpleNamespace(enabled=True),
        model_info=None,
        channel_manager=None,
        channels={},
        running_channels=[],
    )
    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-secret")
    with (
        patch.object(web, "orch", orch),
        patch.object(web, "_list_local_models", AsyncMock(return_value=inventory)) as listing,
        patch.object(web, "_enrich_agents", return_value=[]),
        patch.object(web, "_sys_info", return_value={}),
        TestClient(web.app) as client,
    ):
        models = client.get(
            "/api/models/local", headers={"X-Admin-Token": "test-secret"}
        ).json()
        status = client.get("/status").json()

    assert listing.await_count == 2
    assert status["model_loaded"] == bool(models["resident_models"])
    assert status["resident_models"] == models["resident_models"]
    assert status["residency_state"] == models["residency_state"]
    assert status["model_state"] == "ready"
    assert status["loaded_model"] == "configured"
    assert status["configured_model"] == models["configured_model"]
    assert status["llm_backend"] == models["backend"]
    assert status["lm_online"] is True
