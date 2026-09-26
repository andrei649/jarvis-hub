"""H285 — the owner declares which skills, plugins and MCP servers load at boot.

A plugin toggle flipped an in-memory flag that a restart forgot, an MCP server could
only be disconnected or deleted, and a skill could not be switched off at all. Now six
declared settings rows (``loadset.{skills,plugins,mcp}_{disabled,only}``) are read at
boot by the skill loader, the plugin gate and the MCP load; the plugin toggle writes
them; the per-plugin ``plugins.<id>`` switches count; the status rows show what was
switched off and what the lists name in vain. They only narrow: a name that is not
installed is reported and nothing else happens, and a switched-off MCP server keeps
its saved configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import load_set, settings_db  # noqa: E402

REPO = repo_root


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    """A fresh settings store per test, and fresh load-set records."""
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    for var in ("JARVIS_SAFE_MODE", "JARVIS_USER_HOME"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    for kind in load_set.KINDS:
        load_set.begin(kind)
    yield
    for kind in load_set.KINDS:
        load_set.begin(kind)


def _declare(**values):
    updated, skipped = settings_db.put_category(load_set.CATEGORY, values)
    assert skipped == [] and updated == len(values)


# ── the lists ────────────────────────────────────────────────────────────────────

def test_a_list_is_trimmed_deduplicated_and_bounded():
    parse = load_set.parse_names
    assert parse(" a, b ,,a\nc ") == ["a", "b", "c"]
    assert parse(["x", " y ", "x"]) == ["x", "y"]
    assert parse(None) == [] and parse(7) == [] and parse("") == []
    assert parse("ok,bad\x1bname,tab\there") == ["ok"]
    assert parse("x" * (load_set.MAX_NAME_CHARS + 1) + ",fine") == ["fine"]
    assert parse("x" * load_set.MAX_NAME_CHARS) == ["x" * load_set.MAX_NAME_CHARS]
    many = parse(",".join(f"n{i}" for i in range(load_set.MAX_NAMES + 10)))
    assert len(many) == load_set.MAX_NAMES and many[-1] == f"n{load_set.MAX_NAMES - 1}"


def test_the_six_rows_are_declared_settings():
    rows = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    for kind in load_set.KINDS:
        for suffix in ("disabled", "only"):
            row = rows[(load_set.CATEGORY, f"{kind}_{suffix}")]
            assert row["kind"] == "text" and row["value"] == ""
    assert settings_db.get_value(load_set.CATEGORY, "skills_disabled") == ""


@pytest.mark.parametrize("disabled,only,names,expected", [
    ("", "", ("a",), True),
    ("a", "", ("a",), False),
    ("a", "", ("b",), True),
    ("", "a,b", ("a",), True),
    ("", "a,b", ("c",), False),
    ("a", "a", ("a",), False),                 # disabled wins over only
    ("", "folder", ("name", "folder"), True),  # any of its names
    ("folder", "", ("name", "folder"), False),
    ("", "", ("",), True),
])
def test_disabled_removes_and_only_restricts(disabled, only, names, expected):
    _declare(skills_disabled=disabled, skills_only=only)
    assert load_set.permits("skills", *names) is expected


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        load_set.declared("widgets")


def test_an_unreadable_store_narrows_nothing(monkeypatch):
    monkeypatch.setattr(settings_db, "get_value", MagicMock(side_effect=RuntimeError("locked")))
    assert load_set.declared("skills") == {"disabled": [], "only": []}
    assert load_set.permits("skills", "anything") is True


# ── skills ───────────────────────────────────────────────────────────────────────

def _discover():
    from agents.core.skills.loader import SkillLoader

    loader = SkillLoader()
    return loader, loader.discover()


def test_a_disabled_skill_is_not_registered_and_the_row_says_so():
    _loader, normal = _discover()
    victim = sorted(normal)[0]
    _declare(skills_disabled=f"{victim},not-installed")
    loader, skills = _discover()
    assert victim not in skills and set(skills) == set(normal) - {victim}
    status = load_set.status("skills")
    assert status["skipped"] == [victim] and status["unknown"] == ["not-installed"]
    assert status["disabled"] == [victim, "not-installed"]


def test_an_only_list_loads_just_what_it_names():
    _loader, normal = _discover()
    keep = sorted(normal)[:2]
    _declare(skills_only=",".join([*keep, "ghost"]))
    _loader, skills = _discover()
    assert set(skills) == set(keep)
    status = load_set.status("skills")
    assert set(status["skipped"]) == set(normal) - set(keep) and status["unknown"] == ["ghost"]


def test_a_skill_can_be_named_by_its_folder(tmp_path, monkeypatch):
    from agents.core.skills import loader as loader_mod

    shipped = next(p for p in sorted((REPO / "skills").iterdir()) if (p / "SKILL.md").exists())
    tree = tmp_path / "skills"
    import shutil

    shutil.copytree(shipped, tree / shipped.name)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tree)
    assert len(loader_mod.SkillLoader().discover()) == 1
    _declare(skills_disabled=shipped.name)
    assert loader_mod.SkillLoader().discover() == {}


def test_naming_an_uninstalled_skill_installs_or_approves_nothing(tmp_path, monkeypatch):
    """Narrowing only: the list is never a way around skill.install."""
    from agents.core.skills.loader import SKILLS_DIR

    before = sorted(p.name for p in SKILLS_DIR.iterdir())
    home = tmp_path / "Nerva"
    (home / "skills").mkdir(parents=True)
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))
    _declare(skills_only="weather-pro,brief")
    loader, skills = _discover()
    assert "weather-pro" not in skills
    assert sorted(p.name for p in SKILLS_DIR.iterdir()) == before
    assert list((home / "skills").iterdir()) == []
    assert not any("weather-pro" in str(p) for p in loader._approval_store.list() or []) \
        if hasattr(loader._approval_store, "list") else True
    assert load_set.status("skills")["unknown"] == ["weather-pro"]


def test_the_skills_route_shows_the_load_set(monkeypatch):
    import asyncio

    from agents.core.routers import skills as skills_routes

    loader, _ = _discover()
    _declare(skills_disabled="ghost")
    loader.discover()
    monkeypatch.setattr(skills_routes, "get_orch", lambda: MagicMock(skills=loader))
    body = asyncio.run(skills_routes.list_skills())
    assert body["load_set"]["unknown"] == ["ghost"] and body["load_set"]["disabled"] == ["ghost"]


# ── MCP: switched off, never forgotten ───────────────────────────────────────────

SAVED = [
    {"name": "fs", "command": "npx fs", "transport": "stdio"},
    {"name": "git", "command": "npx git", "transport": "stdio", "trust": "full"},
    {"name": "web", "command": "npx web", "transport": "stdio"},
]


def _web(monkeypatch):
    from agents import web
    from agents.core.mcp.client import MCPManager

    orch = MagicMock()
    orch.mcp = MCPManager()
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "_MCP_HELD", [])
    settings_db.put_category("mcp", {"servers": [dict(row) for row in SAVED]})
    return web, orch


def _saved():
    return settings_db.get_value("mcp", "servers")


def test_a_switched_off_server_is_not_registered_but_stays_saved(monkeypatch):
    web, orch = _web(monkeypatch)
    _declare(mcp_disabled="git,ghost")
    web._load_mcp_config()
    assert set(orch.mcp.servers) == {"fs", "web"}
    assert load_set.status("mcp")["skipped"] == ["git"] and load_set.status("mcp")["unknown"] == ["ghost"]
    web._save_mcp_config()
    saved = {row["name"]: row for row in _saved()}
    assert set(saved) == {"fs", "git", "web"} and saved["git"] == SAVED[1]


def test_an_only_list_for_mcp(monkeypatch):
    web, orch = _web(monkeypatch)
    _declare(mcp_only="web")
    web._load_mcp_config()
    assert set(orch.mcp.servers) == {"web"}
    assert web.mcp_held_names() == {"fs", "git"}


_TOKEN = "load-set-token"


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/admin/mcp", {"name": "git", "command": "x"}),
    ("delete", "/api/admin/mcp/git", None),
])
def test_a_held_server_cannot_be_added_again_or_removed_unseen(monkeypatch, method, path, body):
    from fastapi.testclient import TestClient

    web, orch = _web(monkeypatch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    _declare(mcp_disabled="git")
    web._load_mcp_config()
    kwargs = {"headers": {"X-Admin-Token": _TOKEN}}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(TestClient(web.app), method)(path, **kwargs)
    assert resp.status_code == 409 and resp.json()["error"] == "switched_off"
    assert "loadset.mcp_disabled" in resp.json()["message"]
    assert {row["name"] for row in _saved()} == {"fs", "git", "web"}


def test_adding_and_removing_other_servers_keeps_the_held_one(monkeypatch):
    from fastapi.testclient import TestClient

    web, orch = _web(monkeypatch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    _declare(mcp_disabled="git")
    web._load_mcp_config()
    client = TestClient(web.app)
    headers = {"X-Admin-Token": _TOKEN}
    assert client.post("/api/admin/mcp", json={"name": "new", "command": "npx new"}, headers=headers).status_code == 200
    assert client.delete("/api/admin/mcp/fs", headers=headers).status_code == 200
    saved = {row["name"]: row for row in _saved()}
    assert set(saved) == {"git", "web", "new"} and saved["git"] == SAVED[1]
    listed = client.get("/api/admin/mcp", headers=headers).json()
    assert {s["name"] for s in listed["servers"]} == {"web", "new"}
    assert listed["load_set"]["skipped"] == ["git"]


# ── plugins: the toggle survives a restart ───────────────────────────────────────

def test_the_gate_switches_off_what_the_list_names():
    from agents.core.plugin_gate import PermissionGate

    _declare(plugins_disabled="weather,ghost-plugin")
    gate = PermissionGate()
    assert gate.plugins["weather"].enabled is False and gate.plugins["news"].enabled is True
    assert load_set.status("plugins")["skipped"] == ["weather"]
    assert load_set.status("plugins")["unknown"] == ["ghost-plugin"]


def test_an_only_list_for_plugins():
    from agents.core.plugin_gate import PermissionGate

    _declare(plugins_only="news")
    gate = PermissionGate()
    assert [pid for pid, m in gate.plugins.items() if m.enabled] == ["news"]


def test_the_settings_page_plugin_switch_counts():
    from agents.core.plugin_gate import PermissionGate

    settings_db.put_category("plugins", {"spotify": False})
    assert "spotify" in load_set.declared("plugins")["disabled"]
    assert PermissionGate().plugins["spotify"].enabled is False


def test_the_list_only_disables():
    from agents.core.plugin_gate import BUILTIN_PLUGINS, PermissionGate

    gate = PermissionGate()
    gate.plugins["weather"].enabled = False
    _declare(plugins_only="weather,news")
    gate.apply_load_set()
    assert gate.plugins["weather"].enabled is False            # never switched back on
    assert set(gate.plugins) == set(BUILTIN_PLUGINS)          # nothing registered


def _toggle_client(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.plugin_gate import PermissionGate

    orch = MagicMock()
    orch.permission_gate = PermissionGate()
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    return TestClient(web.app), orch


def test_a_toggle_is_kept_across_a_restart(monkeypatch):
    from agents.core.plugin_gate import PermissionGate

    client, orch = _toggle_client(monkeypatch)
    headers = {"X-Admin-Token": _TOKEN}
    resp = client.put("/plugins/weather/toggle", headers=headers).json()
    assert resp == {"id": "weather", "enabled": False, "action": "disabled", "persisted": True}
    assert settings_db.get_value("plugins", "weather") is False
    assert PermissionGate().plugins["weather"].enabled is False       # the next boot
    resp = client.put("/plugins/weather/toggle", headers=headers).json()
    assert resp["enabled"] is True and resp["persisted"] is True
    assert settings_db.get_value("plugins", "weather") is True
    assert load_set.declared("plugins")["disabled"] == []
    assert PermissionGate().plugins["weather"].enabled is True


def test_a_plugin_without_a_settings_switch_is_kept_in_the_list(monkeypatch):
    from agents.core.plugin_gate import PermissionGate

    client, _orch = _toggle_client(monkeypatch)
    assert settings_db.get_value("plugins", "digest") is None
    assert client.put("/plugins/digest/toggle", headers={"X-Admin-Token": _TOKEN}).json()["persisted"] is True
    assert settings_db.get_value(load_set.CATEGORY, "plugins_disabled") == "digest"
    assert PermissionGate().plugins["digest"].enabled is False


def test_enabling_under_an_only_list_adds_the_plugin_to_it(monkeypatch):
    from agents.core.plugin_gate import PermissionGate

    _declare(plugins_only="news")
    client, orch = _toggle_client(monkeypatch)
    assert orch.permission_gate.plugins["weather"].enabled is False
    assert client.put("/plugins/weather/toggle", headers={"X-Admin-Token": _TOKEN}).json()["enabled"] is True
    assert settings_db.get_value(load_set.CATEGORY, "plugins_only") == "news,weather"
    assert PermissionGate().plugins["weather"].enabled is True


def test_a_toggle_that_cannot_be_kept_says_so(monkeypatch):
    client, orch = _toggle_client(monkeypatch)
    monkeypatch.setattr(load_set, "persist_plugin", MagicMock(side_effect=RuntimeError("disk full")))
    resp = client.put("/plugins/news/toggle", headers={"X-Admin-Token": _TOKEN}).json()
    assert resp["enabled"] is False and resp["persisted"] is False


def test_the_plugins_route_shows_the_load_set(monkeypatch):
    client, orch = _toggle_client(monkeypatch)
    _declare(plugins_disabled="ghost")
    orch.permission_gate.apply_load_set()
    body = client.get("/plugins", headers={"X-Admin-Token": _TOKEN}).json()
    assert body["load_set"]["unknown"] == ["ghost"]


def test_only_an_explicit_off_switch_counts():
    settings_db.put_category("plugins", {"spotify": 0, "news": False})
    assert load_set.declared("plugins")["disabled"] == ["news"]


def test_a_write_the_store_refuses_is_not_reported_as_kept(monkeypatch):
    monkeypatch.setattr(settings_db, "put_category", lambda cat, data: (0, list(data)))
    assert load_set.persist_plugin("weather", False) is False
