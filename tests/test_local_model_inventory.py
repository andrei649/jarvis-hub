"""Truth contract for configured, available, and resident local models."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import httpx
import pytest


class _Response:
    def __init__(self, payload: dict | None = None, status_code: int = 200):
        self._payload = payload or {}
        self.status_code = status_code

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


def _module():
    return importlib.import_module("agents.core.llm.local_model_inventory")


def _router(
    *,
    active: str | None = "alpha",
    backend: str = "lm-studio",
) -> SimpleNamespace:
    return SimpleNamespace(
        active_model=active,
        _backend_name=backend,
        # Deliberately misleading: provider identity must never be parsed from name.
        name="cloud+ollama+lm-studio",
        lm_studio_url="http://lm.test/custom",
        ollama_url="http://ollama.test/custom",
    )


def _responses(
    *,
    lm_catalog: dict | Exception | None = None,
    lm_resident: dict | Exception | None = None,
    ollama_catalog: dict | Exception | None = None,
    ollama_resident: dict | Exception | None = None,
) -> dict[str, _Response | Exception]:
    return {
        "http://lm.test/custom/v1/models": _Response(
            lm_catalog if isinstance(lm_catalog, dict) else {"data": []}
        )
        if not isinstance(lm_catalog, Exception)
        else lm_catalog,
        "http://lm.test/custom/api/v0/models": _Response(
            lm_resident if isinstance(lm_resident, dict) else {"data": []}
        )
        if not isinstance(lm_resident, Exception)
        else lm_resident,
        "http://ollama.test/custom/api/tags": _Response(
            ollama_catalog if isinstance(ollama_catalog, dict) else {"models": []}
        )
        if not isinstance(ollama_catalog, Exception)
        else ollama_catalog,
        "http://ollama.test/custom/api/ps": _Response(
            ollama_resident if isinstance(ollama_resident, dict) else {"models": []}
        )
        if not isinstance(ollama_resident, Exception)
        else ollama_resident,
    }


def _install_http(monkeypatch, responses: dict[str, _Response | Exception]) -> list[str]:
    calls: list[str] = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            calls.append(url)
            value = responses[url]
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return calls


async def _inventory(
    monkeypatch,
    *,
    responses: dict[str, _Response | Exception] | None = None,
    router: SimpleNamespace | None = None,
    controller: SimpleNamespace | None = None,
    force_refresh: bool = True,
):
    module = _module()
    calls = _install_http(monkeypatch, responses or _responses())
    result = await module.get_local_model_inventory(
        router=router or _router(),
        controller=controller or SimpleNamespace(enabled=True),
        force_refresh=force_refresh,
    )
    return result, calls


async def test_inventory_preserves_provider_pair_identity_and_exact_ids(monkeypatch):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    inventory, calls = await _inventory(
        monkeypatch,
        responses=_responses(
            lm_catalog={
                "data": [
                    {"id": " alpha "},
                    {"id": "Alpha"},
                ]
            },
            lm_resident={
                "data": [
                    {"id": "resident-missing-from-catalog", "state": "loaded"},
                    {"id": " alpha ", "state": "not-loaded"},
                ]
            },
            ollama_catalog={"models": [{"name": "alpha"}, {"name": " beta "}]},
            ollama_resident={"models": [{"name": " alpha "}, {"name": "orphan"}]},
        ),
    )

    assert calls == [
        "http://lm.test/custom/v1/models",
        "http://lm.test/custom/api/v0/models",
        "http://ollama.test/custom/api/tags",
        "http://ollama.test/custom/api/ps",
    ]
    assert inventory["backend"] == "lm-studio"
    assert inventory["configured_model"] == "alpha"
    assert inventory["active"] == "alpha"
    assert inventory["resident_models"] == [
        {"provider": "lm-studio", "id": "resident-missing-from-catalog"},
        {"provider": "ollama", "id": "alpha"},
        {"provider": "ollama", "id": "orphan"},
    ]
    pairs = [(row["provider"], row["id"]) for row in inventory["models"]]
    assert pairs == [
        ("lm-studio", "Alpha"),
        ("lm-studio", "alpha"),
        ("lm-studio", "resident-missing-from-catalog"),
        ("ollama", "alpha"),
        ("ollama", "beta"),
        ("ollama", "orphan"),
    ]

    lm_alpha = next(row for row in inventory["models"] if row["provider"] == "lm-studio" and row["id"] == "alpha")
    ollama_alpha = next(row for row in inventory["models"] if row["provider"] == "ollama" and row["id"] == "alpha")
    orphan = next(row for row in inventory["models"] if row["id"] == "orphan")
    lm_resident_only = next(
        row for row in inventory["models"] if row["id"] == "resident-missing-from-catalog"
    )
    assert lm_alpha == {
        "id": "alpha",
        "provider": "lm-studio",
        "available": True,
        "configured": True,
        "active": True,
        "resident": False,
        "controls": {"can_configure": True, "can_load": True, "can_unload": False},
    }
    assert ollama_alpha["configured"] is False
    assert ollama_alpha["active"] is False
    assert ollama_alpha["resident"] is True
    assert ollama_alpha["controls"] == {
        "can_configure": True,
        "can_load": False,
        "can_unload": False,
    }
    assert orphan["available"] is False
    assert orphan["resident"] is True
    assert orphan["controls"]["can_configure"] is False
    assert lm_resident_only["available"] is False
    assert lm_resident_only["resident"] is True
    assert lm_resident_only["controls"]["can_unload"] is True


@pytest.mark.parametrize(
    ("loaded", "expected"),
    [
        ([], []),
        (["one"], [{"provider": "lm-studio", "id": "one"}]),
        (
            ["two", "one"],
            [
                {"provider": "lm-studio", "id": "one"},
                {"provider": "lm-studio", "id": "two"},
            ],
        ),
    ],
)
async def test_inventory_reports_zero_one_or_multiple_residents(monkeypatch, loaded, expected):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    inventory, _ = await _inventory(
        monkeypatch,
        responses=_responses(
            lm_catalog={"data": [{"id": model} for model in loaded]},
            lm_resident={"data": [{"id": model, "state": "loaded"} for model in loaded]},
        ),
        router=_router(active=None),
    )
    assert inventory["resident_models"] == expected


async def test_ambiguous_configuration_gets_one_unknown_synthetic_row(monkeypatch):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    inventory, _ = await _inventory(
        monkeypatch,
        responses=_responses(
            lm_catalog={"data": [{"id": "alpha"}]},
            ollama_catalog={"models": [{"name": "alpha"}]},
        ),
        router=_router(active=" alpha ", backend="none"),
    )

    alpha_rows = [row for row in inventory["models"] if row["id"] == "alpha"]
    assert [(row["provider"], row["configured"]) for row in alpha_rows] == [
        ("lm-studio", False),
        ("ollama", False),
        ("unknown", True),
    ]
    synthetic = alpha_rows[-1]
    assert synthetic["available"] is None
    assert synthetic["resident"] is None
    assert synthetic["active"] is True
    assert synthetic["controls"] == {
        "can_configure": False,
        "can_load": False,
        "can_unload": False,
    }


async def test_configured_model_absent_from_known_catalog_stays_visible(monkeypatch):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    inventory, _ = await _inventory(
        monkeypatch,
        responses=_responses(lm_catalog={"data": []}, lm_resident={"data": []}),
        router=_router(active="ghost", backend="lm-studio"),
    )
    row = next(row for row in inventory["models"] if row["id"] == "ghost")
    assert row["provider"] == "lm-studio"
    assert row["available"] is False
    assert row["resident"] is False
    assert row["configured"] is True
    assert row["controls"] == {
        "can_configure": False,
        "can_load": False,
        "can_unload": False,
    }


async def test_probe_dimensions_fail_independently_without_raw_errors(monkeypatch):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    inventory, _ = await _inventory(
        monkeypatch,
        responses=_responses(
            lm_catalog=RuntimeError("secret catalog path C:/owner/private"),
            lm_resident={"data": [{"id": "resident-only", "state": "loaded"}]},
            ollama_catalog={"models": [{"name": "available-only"}]},
            ollama_resident=RuntimeError("secret ps failure"),
        ),
        router=_router(active=None),
    )
    providers = {provider["name"]: provider for provider in inventory["providers"]}
    assert providers == {
        "lm-studio": {
            "name": "lm-studio",
            "online": True,
            "catalog_state": "unknown",
            "residency_state": "known",
        },
        "ollama": {
            "name": "ollama",
            "online": True,
            "catalog_state": "known",
            "residency_state": "unknown",
        },
    }
    resident = next(row for row in inventory["models"] if row["id"] == "resident-only")
    available = next(row for row in inventory["models"] if row["id"] == "available-only")
    assert resident["available"] is None and resident["resident"] is True
    assert resident["controls"]["can_unload"] is True
    assert available["available"] is True and available["resident"] is None
    assert available["controls"]["can_load"] is False
    assert inventory["residency_state"] == "unknown"
    assert "secret" not in str(inventory)


async def test_both_failed_probes_mark_provider_offline(monkeypatch):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    inventory, _ = await _inventory(
        monkeypatch,
        responses=_responses(
            lm_catalog=RuntimeError("down"),
            lm_resident=RuntimeError("down"),
            ollama_catalog=RuntimeError("down"),
            ollama_resident=RuntimeError("down"),
        ),
        router=_router(active="offline-config", backend="lm-studio"),
    )
    assert inventory["residency_state"] == "offline"
    assert all(provider["online"] is False for provider in inventory["providers"])
    configured = next(row for row in inventory["models"] if row["configured"])
    assert configured["available"] is None
    assert configured["resident"] is None


async def test_cache_reuses_raw_probes_but_recomputes_config_and_controls(monkeypatch):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    responses = _responses(
        lm_catalog={"data": [{"id": "alpha"}, {"id": "beta"}]},
        lm_resident={"data": []},
    )
    calls = _install_http(monkeypatch, responses)
    first = await module.get_local_model_inventory(
        router=_router(active="alpha"),
        controller=SimpleNamespace(enabled=True),
    )
    second = await module.get_local_model_inventory(
        router=_router(active="beta"),
        controller=SimpleNamespace(enabled=False),
    )

    assert len(calls) == 4
    assert next(row for row in first["models"] if row["id"] == "alpha")["configured"] is True
    beta = next(row for row in second["models"] if row["id"] == "beta")
    assert beta["configured"] is True
    assert beta["active"] is True
    assert beta["controls"]["can_load"] is False

    module.invalidate_local_model_inventory_cache()
    await module.get_local_model_inventory(router=_router(), controller=SimpleNamespace(enabled=True))
    assert len(calls) == 8


async def test_cache_expires_and_force_refresh_bypasses_it(monkeypatch):
    module = _module()
    module.invalidate_local_model_inventory_cache()
    calls = _install_http(monkeypatch, _responses())
    await module.get_local_model_inventory(router=_router(), controller=SimpleNamespace(enabled=True))
    await module.get_local_model_inventory(router=_router(), controller=SimpleNamespace(enabled=True))
    assert len(calls) == 4

    await module.get_local_model_inventory(
        router=_router(), controller=SimpleNamespace(enabled=True), force_refresh=True
    )
    assert len(calls) == 8

    monkeypatch.setattr(module, "_CACHE_TTL_SECONDS", -1.0)
    await module.get_local_model_inventory(router=_router(), controller=SimpleNamespace(enabled=True))
    assert len(calls) == 12
