"""H275 — safe mode: the hub boots with every owner customization left out, and nothing
it leaves out is a security gate.

When an install is broken by something the owner added (a persona that confuses the
model, a skill that crashes discovery, a job that runs away, an MCP server that hangs)
the owner needs to start it without that, fix it and start again. ``JARVIS_SAFE_MODE=1``
(or ``python serve.py --safe-mode``) leaves out skills that did not ship, the saved MCP
servers (without touching their saved configuration), acquired packages and extensions,
the owner's plugin grants, the ``*.local.md`` persona, contract and heartbeat overlays
(at construction and at the compaction boundary), and the owner's scheduled jobs. It
says so on every status surface and in the HUD. It only ever takes things away.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import safe_mode  # noqa: E402

REPO = repo_root


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("JARVIS_SAFE_MODE", "JARVIS_USER_HOME", "JARVIS_APP_ROOT", "JARVIS_PLUGIN_GRANTS"):
        # setenv first so the original state (often: unset) is what teardown restores,
        # even when a test writes the variable itself (serve's switch does).
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    safe_mode.reset()
    yield
    safe_mode.reset()


def _on(monkeypatch):
    monkeypatch.setenv(safe_mode.ENV_NAME, "1")


# ── the flag and what it reports ─────────────────────────────────────────────────

@pytest.mark.parametrize("value,on", [("1", True), ("true", True), ("0", False), ("", False)])
def test_the_flag_is_read_at_call_time(monkeypatch, value, on):
    monkeypatch.setenv(safe_mode.ENV_NAME, value)
    assert safe_mode.enabled() is on


def test_status_names_the_layers_left_out_in_boot_order(monkeypatch, caplog):
    assert safe_mode.status() == {"enabled": False, "skipped": []}
    _on(monkeypatch)
    assert safe_mode.status() == {"enabled": True, "skipped": []}
    with caplog.at_level(logging.WARNING, logger="jarvis.safe_mode"):
        safe_mode.note("owner_jobs")
        safe_mode.note("owner_skills")
        safe_mode.note("owner_skills")
    assert safe_mode.status()["skipped"] == ["owner_skills", "owner_jobs"]
    assert [r.getMessage() for r in caplog.records] == ["Safe mode: owner jobs left out",
                                                        "Safe mode: owner skills left out"]
    with pytest.raises(ValueError):
        safe_mode.note("the_kernel")
    monkeypatch.delenv(safe_mode.ENV_NAME)
    assert safe_mode.status() == {"enabled": False, "skipped": []}


def test_the_serve_switch_sets_the_flag(monkeypatch):
    import serve

    assert serve.apply_safe_mode_switch(["--port", "8000"]) is False
    assert safe_mode.enabled() is False
    assert serve.apply_safe_mode_switch(["--safe-mode"]) is True
    assert safe_mode.enabled() is True


def test_the_flag_does_not_outlive_the_serve_switch_test():
    """Guards the fixture above: the switch writes the real environment."""
    assert safe_mode.enabled() is False


# ── skills: the shipped tree only ────────────────────────────────────────────────

def _user_skill(home: Path, name: str) -> None:
    d = home / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: An owner skill. Use when testing.\n---\n\nBody.\n",
                                encoding="utf-8")


def test_the_data_home_skills_are_left_out(monkeypatch, tmp_path):
    from agents.core.skills.loader import SkillLoader

    home = tmp_path / "Nerva"
    _user_skill(home, "owner-notes")
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))
    normal = set(SkillLoader().discover())
    assert "owner-notes" in normal
    _on(monkeypatch)
    safe = set(SkillLoader().discover())
    assert "owner-notes" not in safe and safe == normal - {"owner-notes"}
    assert safe_mode.status()["skipped"] == ["owner_skills"]


def test_a_broken_data_home_skills_folder_is_not_even_read(monkeypatch, tmp_path):
    """The point of safe mode: an owner folder that breaks discovery is not opened."""
    from agents.core.skills.loader import SkillLoader

    home = tmp_path / "Nerva"
    _user_skill(home, "owner-notes")
    broken = home / "skills"
    real_iterdir = Path.iterdir

    def iterdir(self):
        if self == broken:
            raise OSError("unreadable owner folder")
        return real_iterdir(self)

    monkeypatch.setenv("JARVIS_USER_HOME", str(home))
    monkeypatch.setattr(Path, "iterdir", iterdir)
    with pytest.raises(OSError):
        SkillLoader().discover()
    _on(monkeypatch)
    assert "owner-notes" not in SkillLoader().discover()


def test_an_owner_skill_in_the_bundled_tree_is_left_out(monkeypatch, tmp_path):
    """In a checkout with no data home, generated and imported skills land in the
    bundled tree. Only a skill whose bytes match the release is loaded."""
    from agents.core.skills import loader as loader_mod

    shipped = sorted(p for p in (REPO / "skills").iterdir() if (p / "SKILL.md").exists())[0]
    tree = tmp_path / "skills"
    shutil.copytree(shipped, tree / shipped.name)
    _user_skill(tmp_path, "generated-thing")          # tmp_path/skills/generated-thing
    edited = tree / f"{shipped.name}-edited"
    shutil.copytree(shipped, edited)
    text = (edited / "SKILL.md").read_text(encoding="utf-8")
    text = re.sub(r"^(name: |# ).*$", lambda m: m.group(1) + edited.name, text, count=1, flags=re.MULTILINE)
    (edited / "SKILL.md").write_text(text + "\nOwner edit.\n", encoding="utf-8")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tree)
    normal = loader_mod.SkillLoader().discover()
    assert {s.path.name for s in normal.values()} == {shipped.name, "generated-thing", edited.name}
    _on(monkeypatch)
    safe = loader_mod.SkillLoader().discover()
    assert {s.path.name for s in safe.values()} == {shipped.name}
    assert all(not s.external for s in safe.values())


def test_every_shipped_skill_still_loads_in_safe_mode(monkeypatch):
    from agents.core.skills.loader import SkillLoader

    normal = set(SkillLoader().discover())
    _on(monkeypatch)
    assert set(SkillLoader().discover()) == normal and normal


# ── MCP: none registered, the saved list untouched ───────────────────────────────

SAVED = [{"name": "fs", "command": "npx fs", "transport": "stdio"}]


def _web(monkeypatch):
    from agents import web
    from agents.core import settings_db

    orch = MagicMock()
    orch.mcp.servers = {}
    orch.mcp.to_config = MagicMock(return_value=[])
    monkeypatch.setattr(web, "orch", orch)
    writes = []
    monkeypatch.setattr(settings_db, "get_category", lambda cat: [{"key": "servers", "value": SAVED}] if cat == "mcp" else [])
    monkeypatch.setattr(settings_db, "put_category", lambda cat, data: writes.append((cat, data)) or (1, []))
    return web, orch, writes


def test_the_saved_mcp_servers_are_not_loaded_in_safe_mode(monkeypatch):
    web, orch, _ = _web(monkeypatch)
    web._load_mcp_config()
    orch.mcp.load_from_config.assert_called_once_with(SAVED)
    orch.mcp.load_from_config.reset_mock()
    _on(monkeypatch)
    web._load_mcp_config()
    orch.mcp.load_from_config.assert_not_called()
    assert safe_mode.status()["skipped"] == ["mcp_servers"]


def test_the_saved_list_is_never_rewritten_from_an_empty_manager(monkeypatch):
    web, _orch, writes = _web(monkeypatch)
    _on(monkeypatch)
    web._save_mcp_config()
    assert writes == []
    monkeypatch.delenv(safe_mode.ENV_NAME)
    web._save_mcp_config()
    assert writes == [("mcp", {"servers": []})]


_TOKEN = "safe-mode-token"


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/admin/mcp", {"name": "new", "command": "x"}),
    ("delete", "/api/admin/mcp/fs", None),
])
def test_adding_or_removing_an_mcp_server_is_refused_in_safe_mode(monkeypatch, method, path, body):
    from fastapi.testclient import TestClient

    web, orch, writes = _web(monkeypatch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    orch.mcp.servers = {"fs": MagicMock(_proc=None)}
    _on(monkeypatch)
    client = TestClient(web.app)
    kwargs = {"headers": {"X-Admin-Token": _TOKEN}}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 409 and resp.json()["error"] == "safe_mode"
    assert set(orch.mcp.servers) == {"fs"} and writes == []


# ── acquired packages and extensions ─────────────────────────────────────────────

def test_the_acquisition_runtime_reports_itself_disabled(monkeypatch):
    from agents.core.acquisition.runtime import AcquisitionRuntime

    runtime = AcquisitionRuntime.__new__(AcquisitionRuntime)
    runtime._enabled = lambda: True
    runtime.extension_runtime = None
    runtime.package_store = object()
    runtime.sandbox_profile = object()
    assert runtime.is_enabled() is True
    _on(monkeypatch)
    assert runtime.is_enabled() is False
    assert runtime.extensions() is None                 # no extension can be activated
    assert safe_mode.status()["skipped"] == ["acquired_packages"]


# ── plugin grants: only ever a widening, so none is kept ─────────────────────────

def test_the_owner_plugin_grants_are_dropped_and_nothing_else_moves(monkeypatch):
    from agents.core import plugin_gate

    monkeypatch.setenv("JARVIS_PLUGIN_GRANTS", "social_x:veronica,writeback_github:stark")
    monkeypatch.setenv("JARVIS_PLUGIN_LEAST_PRIVILEGE", "1")
    assert plugin_gate.grants_from_env() == {"social_x": {"veronica"}, "writeback_github": {"stark"}}
    normal = plugin_gate.PermissionGate()
    _on(monkeypatch)
    assert plugin_gate.grants_from_env() == {}
    safe = plugin_gate.PermissionGate()
    assert safe._grants == {} and safe.least_privilege is normal.least_privilege is True
    assert set(safe.plugins) == set(normal.plugins)
    # H490: the gate also switches every plugin off in safe mode.
    assert safe_mode.status()["skipped"] == ["plugin_grants", "plugins"]


def test_no_grant_configured_is_not_reported_as_left_out(monkeypatch):
    from agents.core import plugin_gate

    _on(monkeypatch)
    assert plugin_gate.grants_from_env() == {}
    assert safe_mode.status()["skipped"] == []


# ── persona, contract and heartbeat overlays ─────────────────────────────────────

def _app(tmp_path, monkeypatch, agent_id="foo"):
    root = tmp_path / "app"
    agent_dir = root / "agents" / agent_id
    agent_dir.mkdir(parents=True)
    (agent_dir / "SOUL.md").write_text("Shipped persona.\n", encoding="utf-8")
    identity = root / "agents" / "_identity"
    identity.mkdir(parents=True)
    (identity / "IDENTITY.md").write_text("Shipped contract.\n", encoding="utf-8")
    home = tmp_path / "Nerva"
    (home / "souls" / agent_id).mkdir(parents=True)
    monkeypatch.setenv("JARVIS_APP_ROOT", str(root))
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))
    monkeypatch.delenv("JARVIS_SOUL_MAX_CHARS", raising=False)
    return root, home


@pytest.mark.parametrize("where", ["home", "repo"])
def test_the_persona_and_contract_overlays_give_way_to_the_shipped_files(tmp_path, monkeypatch, where):
    from agents.core.agent import identity_path, soul_path_for

    root, home = _app(tmp_path, monkeypatch)
    if where == "home":
        soul = home / "souls" / "foo" / "SOUL.local.md"
        contract = home / "souls" / "IDENTITY.local.md"
    else:
        soul = root / "agents" / "foo" / "SOUL.local.md"
        contract = root / "agents" / "_identity" / "IDENTITY.local.md"
    soul.write_text("Owner persona.\n", encoding="utf-8")
    contract.write_text("Owner contract.\n", encoding="utf-8")
    assert soul_path_for("foo") == soul and identity_path() == contract
    _on(monkeypatch)
    assert soul_path_for("foo") == root / "agents" / "foo" / "SOUL.md"
    assert identity_path() == root / "agents" / "_identity" / "IDENTITY.md"
    assert safe_mode.status()["skipped"] == ["persona_overlays"]


def test_without_an_overlay_nothing_is_reported_left_out(tmp_path, monkeypatch):
    from agents.core.agent import soul_path_for

    root, _home = _app(tmp_path, monkeypatch)
    _on(monkeypatch)
    assert soul_path_for("foo") == root / "agents" / "foo" / "SOUL.md"
    assert safe_mode.status()["skipped"] == []


def test_a_safe_mode_session_cannot_pick_an_overlay_up_at_the_boundary(tmp_path, monkeypatch):
    from agents.core.agent import Agent

    _root, home = _app(tmp_path, monkeypatch)
    _on(monkeypatch)
    agent = Agent.__new__(Agent)
    agent.id = "foo"
    agent.soul = {}
    agent._load_soul()
    assert agent.soul["content"] == "Shipped persona.\n"
    (home / "souls" / "foo" / "SOUL.local.md").write_text("Owner persona written mid-session.\n", encoding="utf-8")
    (home / "souls" / "IDENTITY.local.md").write_text("Owner contract written mid-session.\n", encoding="utf-8")
    agent.refresh_soul()
    assert agent.soul["content"] == "Shipped persona.\n"
    assert "Owner" not in str(agent.identity or {})


_HB = """---
agent: {agent}
cadence: cron:30 6 * * *
enabled: true
checklist:
  - {item}
---
# beat
"""


@pytest.mark.parametrize("where", ["home", "repo"])
def test_the_heartbeat_overlay_gives_way_to_the_shipped_schedule(tmp_path, monkeypatch, where):
    from agents.core.heartbeat import HeartbeatScheduler

    agents_dir = tmp_path / "agents"
    (agents_dir / "baz").mkdir(parents=True)
    (agents_dir / "baz" / "HEARTBEAT.md").write_text(_HB.format(agent="baz", item="shipped step"), encoding="utf-8")
    home = tmp_path / "Nerva"
    overlay = (home / "souls" / "baz" if where == "home" else agents_dir / "baz") / "HEARTBEAT.local.md"
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(_HB.format(agent="baz", item="owner step"), encoding="utf-8")
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))

    normal = HeartbeatScheduler(agents_dir=str(agents_dir))
    normal.load_all()
    assert "owner step" in str(normal._heartbeat_configs["baz"])
    _on(monkeypatch)
    safe = HeartbeatScheduler(agents_dir=str(agents_dir))
    safe.load_all()
    assert "shipped step" in str(safe._heartbeat_configs["baz"])
    assert "owner step" not in str(safe._heartbeat_configs)
    assert safe_mode.status()["skipped"] == ["heartbeat_overlays"]
    overlay.unlink()
    safe_mode.reset()
    HeartbeatScheduler(agents_dir=str(agents_dir)).load_all()
    assert safe_mode.status()["skipped"] == []


# ── the owner's scheduled jobs ───────────────────────────────────────────────────

def test_the_owner_jobs_stay_saved_and_are_not_scheduled(monkeypatch):
    from agents.core.scheduler_service import SchedulerService

    runner = MagicMock()
    runner.register_all.return_value = 3
    service = SchedulerService(SimpleNamespace(jobs=runner))
    service.schedule_owner_jobs()
    assert runner.register_all.call_count == 1
    _on(monkeypatch)
    service.schedule_owner_jobs()
    assert runner.register_all.call_count == 1
    assert safe_mode.status()["skipped"] == ["owner_jobs"]


# ── said everywhere ──────────────────────────────────────────────────────────────

def _body(response):
    return json.loads(response.body)


def test_healthz_and_readyz_say_it_and_a_safe_hub_is_still_ready(monkeypatch):
    from agents.core.routers import ops

    assert _body(asyncio.run(ops.healthz()))["safe_mode"] is False
    monkeypatch.setattr(ops, "get_orch", lambda: SimpleNamespace(agents={"jarvis": object()}, channels={}))
    monkeypatch.setattr(ops, "_llm_snapshot", lambda orch: {})
    assert ops.readiness_snapshot()["safe_mode"] == {"enabled": False, "skipped": []}
    _on(monkeypatch)
    safe_mode.note("owner_jobs")
    assert _body(asyncio.run(ops.healthz()))["safe_mode"] is True
    snap = ops.readiness_snapshot()
    assert snap["ready"] is True and "reason" not in snap
    assert snap["safe_mode"] == {"enabled": True, "skipped": ["owner_jobs"]}


def test_the_status_routes_say_it(monkeypatch):
    from agents.core.routers import status as status_routes

    assert asyncio.run(status_routes.api_status())["safe_mode"] == {"enabled": False, "skipped": []}
    _on(monkeypatch)
    safe_mode.note("mcp_servers")
    assert asyncio.run(status_routes.api_status())["safe_mode"] == {"enabled": True, "skipped": ["mcp_servers"]}
    source = (REPO / "agents/core/routers/status.py").read_text(encoding="utf-8")
    assert '"safe_mode": _safe_mode_status()' in source.split("async def status()")[1].split("async def api_status")[0]


# ── it only takes things away ────────────────────────────────────────────────────

def test_no_gate_reads_the_flag():
    """The kernel, the approval floor, the secrets, the security package and the
    egress policy never branch on safe mode, so it cannot relax any of them."""
    gates = [*(REPO / "agents/core/kernel").rglob("*.py"), *(REPO / "agents/core/security").rglob("*.py"),
             *(REPO / "agents/core/secrets").rglob("*.py")]
    gates += [p for p in (REPO / "agents/core").glob("*.py")
              if p.name.startswith(("egress", "turn_approvals", "approval", "tool_profiles", "capability_actions"))]
    assert gates
    offenders = [str(p.relative_to(REPO)) for p in gates
                 if "safe_mode" in p.read_text(encoding="utf-8") or "JARVIS_SAFE_MODE" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_every_reader_of_the_flag_only_leaves_something_out():
    """The one list of modules that read it; a new reader has to be added here, on purpose."""
    readers = sorted(str(p.relative_to(REPO)) for p in (REPO / "agents").rglob("*.py")
                     if "safe_mode" in p.read_text(encoding="utf-8") and p.name != "safe_mode.py")
    assert readers == sorted([
        # H227: the inspector's status line and `nerva inspect` only report the flag.
        "agents/cli/nerva.py",
        "agents/core/inspector.py",
        "agents/core/acquisition/runtime.py",
        "agents/core/agent.py",
        "agents/core/channels/outbound.py",
        "agents/core/heartbeat.py",
        "agents/core/memory_tool.py",
        "agents/core/orchestrator.py",
        "agents/core/plugin_gate.py",
        "agents/core/project_context.py",
        "agents/core/routers/mcp.py",
        "agents/core/routers/ops.py",
        "agents/core/routers/plugins.py",
        "agents/core/routers/security.py",
        "agents/core/routers/status.py",
        "agents/core/routers/webhooks.py",
        "agents/core/scheduler_service.py",
        "agents/core/skills/loader.py",
        "agents/web.py",
    ])
