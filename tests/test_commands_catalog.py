"""The live slash-command menu shares chat's registry and principal, never dispatches."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.commands import (
    ADMIN,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)
from agents.core.routers._deps import user_guard
from agents.core.routers.commands import router


@pytest.fixture
def catalog(monkeypatch):
    registry = build_default_registry()
    monkeypatch.setattr(web, "orch", SimpleNamespace(commands=registry))
    monkeypatch.setattr(web, "_admin_configured", lambda: True)
    monkeypatch.setattr(web, "_admin_credential_ok", lambda value: value == "owner-token")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app), registry


def test_catalog_is_mounted_on_the_real_app_with_a_user_guard():
    from tests.test_route_auth_matrix import _runtime_guards

    assert _runtime_guards()["GET /api/commands"] == "user"


def test_user_catalog_contains_only_commands_visible_to_that_chat_principal(catalog):
    client, registry = catalog
    response = client.get("/api/commands")
    assert response.status_code == 200
    rows = response.json()["commands"]
    assert [row["name"] for row in rows] == [c.name for c in registry.visible(Principal())]
    assert all(row["tier"] == "user" for row in rows)
    assert not {"stop", "pause", "resume", "remind"} & {row["name"] for row in rows}
    assert "no-store" in response.headers["cache-control"]


def test_owner_catalog_matches_chat_and_does_not_execute_handlers(catalog):
    client, registry = catalog
    registry.register(SlashCommand("probe", "A live command", lambda _ctx: pytest.fail("dispatched"),
                                   tier=ADMIN, usage="<value>"))
    response = client.get("/api/commands", headers={"X-Admin-Token": "owner-token"})
    assert response.status_code == 200
    rows = response.json()["commands"]
    assert [row["name"] for row in rows] == [c.name for c in registry.visible(Principal(admin=True))]
    assert next(row for row in rows if row["name"] == "probe") == {
        "name": "probe", "command": "/probe", "description": "A live command",
        "tier": "admin", "usage": "<value>",
    }
    assert {"stop", "pause", "resume", "remind"} <= {row["name"] for row in rows}


def test_bad_owner_token_and_query_flag_cannot_reveal_owner_commands(catalog):
    client, _ = catalog
    response = client.get("/api/commands?admin=true", headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 200
    assert all(row["tier"] == "user" for row in response.json()["commands"])


def test_catalog_requires_user_authorization_before_reading_registry(catalog):
    client, _ = catalog

    def deny():
        raise HTTPException(status_code=401, detail="user token required")

    client.app.dependency_overrides[user_guard] = deny
    response = client.get("/api/commands")
    assert response.status_code == 401
    assert "commands" not in response.json()


@pytest.mark.parametrize("orch", [None, SimpleNamespace(), SimpleNamespace(commands=None)])
def test_unavailable_registry_is_not_replaced_by_an_invented_default(catalog, monkeypatch, orch):
    client, _ = catalog
    monkeypatch.setattr(web, "orch", orch)
    response = client.get("/api/commands")
    assert response.status_code == 503
    assert response.json() == {"ok": False, "reason": "commands_unavailable", "commands": []}


def test_empty_live_registry_is_distinct_from_unavailable(catalog, monkeypatch):
    client, _ = catalog
    monkeypatch.setattr(web, "orch", SimpleNamespace(commands=CommandRegistry()))
    response = client.get("/api/commands")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "commands": []}


def test_catalog_tracks_the_live_registry_after_startup(catalog, monkeypatch):
    client, _ = catalog
    replacement = CommandRegistry()
    replacement.register(SlashCommand("fresh", "Only on this hub", lambda _: "unused"))
    monkeypatch.setattr(web, "orch", SimpleNamespace(commands=replacement))
    assert [row["name"] for row in client.get("/api/commands").json()["commands"]] == ["fresh"]
