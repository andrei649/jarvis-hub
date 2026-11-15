"""V24 owner shortcut discovery never executes or discloses shortcut payloads."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.commands import ADMIN, CommandRegistry, SlashCommand
from agents.core.routers._deps import user_guard
from agents.core.routers.commands import router
from agents.core.skills import bundles


class Loader:
    def __init__(self, *names, denied=()):
        self.skills = {name: SimpleNamespace(name=name, path=None, description="PRIVATE BODY")
                       for name in names}
        self.denied = set(denied)
        self.checked = []

    def catalog_gate(self, skill):
        self.checked.append(skill.name)
        return "disabled" if skill.name in self.denied else ""


@pytest.fixture
def client(monkeypatch):
    registry = CommandRegistry()
    registry.register(SlashCommand("status", "Registry status", lambda _: pytest.fail("handler ran"), tier=ADMIN))
    orch = SimpleNamespace(commands=registry, skills=Loader("notes"))
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "_admin_configured", lambda: True)
    monkeypatch.setattr(web, "_admin_credential_ok", lambda value: value == "owner-token")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app), orch


def owner(client):
    return client.get("/api/commands", headers={"X-Admin-Token": "owner-token"})


def test_owner_projects_fixed_metadata_without_reading_bodies_or_running_handlers(client, monkeypatch):
    http, orch = client
    monkeypatch.setattr("agents.core.command_shortcuts._quick_inventory", lambda: {
        "launch": {"type": "exec", "command": "VERY_PRIVATE_TARGET"}})
    monkeypatch.setattr(bundles, "snapshot", lambda: ([SimpleNamespace(slug="morning", name="Morning",
                                                     description="PRIVATE DESCRIPTION", instruction="PRIVATE INSTRUCTION")], []))
    result = owner(http)
    assert result.status_code == 200
    body = result.json()
    assert body["commands"][0]["name"] == "status"
    assert body["shortcuts"] == [
        {"kind": "quick", "name": "launch", "command": "/launch", "description": "Quick command",
         "tier": "admin", "usage": "[args]"},
        {"kind": "bundle", "name": "morning", "command": "/bundle morning",
         "description": "Skill bundle", "tier": "admin", "usage": "[instruction]"},
        {"kind": "skill", "name": "notes", "command": "/notes", "description": "Skill",
         "tier": "admin", "usage": "[instruction]"},
    ]
    assert body["truncated"] is False and body["shortcuts_unavailable"] is False
    assert all(secret not in result.text for secret in ("VERY_PRIVATE_TARGET", "PRIVATE BODY", "PRIVATE DESCRIPTION", "PRIVATE INSTRUCTION"))
    assert orch.skills.checked == ["notes"]


def test_guest_never_reads_private_shortcut_sources(client, monkeypatch):
    http, orch = client

    def forbidden(*_args, **_kwargs):
        pytest.fail("private inventory read for guest")

    class Poison:
        @property
        def skills(self):
            forbidden()

    monkeypatch.setattr("agents.core.command_shortcuts._quick_inventory", forbidden)
    monkeypatch.setattr(bundles, "snapshot", forbidden)
    orch.skills = Poison()
    body = http.get("/api/commands").json()
    assert body["shortcuts"] == []
    assert body["shortcuts_unavailable"] is False


def test_collisions_ambiguity_and_web_gate_hide_skills(client, monkeypatch):
    http, orch = client
    orch.skills = Loader("status", "h", "launch", "morning", "twins", "web-off", "notes", denied={"web-off"})
    orch.skills.skills["other"] = SimpleNamespace(name="twins", path=None)
    monkeypatch.setattr("agents.core.command_shortcuts._quick_inventory", lambda: {
        "launch": {"type": "alias", "target": "/help"}})
    monkeypatch.setattr(bundles, "snapshot", lambda: ([SimpleNamespace(slug="morning", name="Morning")], []))
    names = {(row["kind"], row["name"]) for row in owner(http).json()["shortcuts"]}
    assert ("quick", "launch") in names and ("bundle", "morning") in names
    assert ("skill", "notes") in names
    assert not any(kind == "skill" and name in {"status", "h", "launch", "morning", "twins", "web-off"}
                   for kind, name in names)


def test_registry_first_combined_cap_and_source_failure(client, monkeypatch):
    http, orch = client
    for n in range(255):
        orch.commands.register(SlashCommand(f"r{n:03d}", "Registry row", lambda _: None, tier=ADMIN))
    monkeypatch.setattr("agents.core.command_shortcuts._quick_inventory", lambda: {
        f"q{n:03d}": {"type": "exec", "command": "secret"} for n in range(3)})
    monkeypatch.setattr(bundles, "snapshot", lambda: ([], []))
    body = owner(http).json()
    assert len(body["commands"]) == 256 and body["shortcuts"] == [] and body["truncated"] is True
    orch.commands.unregister(orch.commands.get("r254"))
    body = owner(http).json()
    assert len(body["commands"]) == 255 and [row["name"] for row in body["shortcuts"]] == ["q000"]
    assert body["truncated"] is True
    orch.commands = CommandRegistry()
    orch.commands.register(SlashCommand("status", "Registry row", lambda _: None, tier=ADMIN))
    monkeypatch.setattr(bundles, "snapshot", lambda: (_ for _ in ()).throw(OSError("private path")))
    body = owner(http).json()
    assert [row["name"] for row in body["commands"]] == ["status"]
    assert [row["name"] for row in body["shortcuts"]] == ["q000", "q001", "q002"]
    assert body["shortcuts_unavailable"] is True
    assert "private path" not in str(body)


def test_quick_source_reads_valid_store_and_checks_original_name(client, monkeypatch):
    from agents.core import command_shortcuts

    http, _orch = client
    monkeypatch.setattr(command_shortcuts.settings_db, "get_value", lambda category, key, default: {
        "PrivateKey": {"type": "alias", "target": "/help"},
        "Launch": {"type": "exec", "command": "PRIVATE TARGET"},
    })
    monkeypatch.setattr(bundles, "snapshot", lambda: ([], []))
    checked = []

    def safe(raw, wire):
        checked.append((raw, wire))
        return raw != "PrivateKey"

    monkeypatch.setattr(command_shortcuts, "name_allowed", safe)
    body = owner(http).json()
    assert ("PrivateKey", "privatekey") in checked and ("Launch", "launch") in checked
    assert [row["command"] for row in body["shortcuts"]] == ["/launch", "/notes"]
    assert "PRIVATE TARGET" not in str(body)


def test_quick_failure_keeps_safe_bundles_but_suppresses_skills(client, monkeypatch):
    http, _orch = client
    monkeypatch.setattr("agents.core.command_shortcuts._quick_inventory",
                        lambda: (_ for _ in ()).throw(OSError("secret store path")))
    monkeypatch.setattr(bundles, "snapshot", lambda: ([SimpleNamespace(slug="morning", name="Morning")], []))
    body = owner(http).json()
    assert [row["kind"] for row in body["shortcuts"]] == ["bundle"]
    assert body["shortcuts_unavailable"] is True
    assert "secret store path" not in str(body)


def test_oversize_skill_inventory_is_not_partially_resolved(client, monkeypatch):
    http, orch = client
    orch.skills = Loader(*(f"skill{n:03d}" for n in range(513)))
    monkeypatch.setattr("agents.core.command_shortcuts._quick_inventory", lambda: {})
    monkeypatch.setattr(bundles, "snapshot", lambda: ([], []))
    body = owner(http).json()
    assert body["shortcuts"] == []
    assert body["shortcuts_unavailable"] is True and body["truncated"] is True
    assert orch.skills.checked == []
