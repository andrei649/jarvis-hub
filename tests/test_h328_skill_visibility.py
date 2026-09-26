"""H328 — a skill is shown where it makes sense: the host's operating system, the
environment, the channel, and the tools this turn is offered.

``platforms`` is a hard gate: a skill for another OS is left out of every offer,
``skill_view`` answers ``skill_unsupported`` and a command naming it is refused.
``environments``, ``metadata.hermes.session_platforms`` and the ``requires_*`` /
``fallback_for_*`` tool gates only hide a skill from what the model is offered: named
explicitly, it still works. Every hide is logged once.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db  # noqa: E402
from agents.core.skills import visibility  # noqa: E402
from agents.core.skills.loader import Skill, SkillLoader  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv(visibility.ENV_OVERRIDE, "")
    monkeypatch.delenv(visibility.ENV_OVERRIDE)
    monkeypatch.setenv("PREFIX", "")
    monkeypatch.delenv("PREFIX")
    visibility._logged.clear()
    yield
    visibility._logged.clear()


def _skill(tmp_path, name, *, platforms=None, environments=None, hermes=None, calls=None):
    path = tmp_path / "skills" / name
    path.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "description": f"{name} does things",
                "commands": [{"command": name, "description": "run it"}],
                "platforms": list(platforms or []), "environments": list(environments or []),
                "hermes": dict(hermes or {})}
    skill = Skill(name, path, manifest)
    skill.trusted = True
    skill.view_files = {"SKILL.md": f"# {name}\n".encode()}
    record = calls if calls is not None else []

    async def _run(args, context=None):
        record.append((name, args))
        return f"{name} ran"

    skill.register_command(name, _run)
    return skill


def _loader(*skills):
    loader = SkillLoader.__new__(SkillLoader)
    loader.skills = {s.name: s for s in skills}
    return loader


def _catalog(loader, *, offer=None):
    token = visibility.bind_offer(offer)
    try:
        return [row["skill"] for row in loader.prompt_catalog()]
    finally:
        visibility.reset_offer(token)


def _bound(channel):
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal

    return bind_turn_principal(Principal(channel=channel, admin=True))


def _unbind(token):
    from agents.core.orchestrator import reset_turn_principal

    reset_turn_principal(token)


# ── the host ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("platform,names", [
    ("darwin", {"macos"}), ("linux", {"linux"}), ("win32", {"windows"}), ("freebsd13", set()),
])
def test_the_host_platform_names(platform, names):
    assert visibility.host_platforms(platform) == frozenset(names)


def test_termux_counts_as_linux_and_android(monkeypatch):
    monkeypatch.setattr(visibility.sys, "platform", "linux")
    monkeypatch.setattr(visibility, "Path", lambda p: SimpleNamespace(is_dir=lambda: False, exists=lambda: False))
    assert visibility.host_platforms() == frozenset({"linux"})
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    assert visibility.host_platforms() == frozenset({"linux", "android"})
    monkeypatch.setattr(visibility.sys, "platform", "darwin")
    assert visibility.host_platforms() == frozenset({"macos", "linux", "android"})
    assert visibility.host_platforms("darwin") == frozenset({"macos"})    # a named platform is just that


def test_readiness(tmp_path):
    linux = frozenset({"linux"})
    assert visibility.readiness(_skill(tmp_path, "any"), host=linux) == ("ready", "")
    assert visibility.readiness(_skill(tmp_path, "both", platforms=["linux", "macos"]), host=linux) == ("ready", "")
    assert visibility.readiness(_skill(tmp_path, "mac", platforms=["macos"]), host=linux) == \
        ("unsupported", "unsupported on linux (it declares macos)")
    assert visibility.readiness(_skill(tmp_path, "odd", platforms=["beos"]), host=frozenset()) == \
        ("unsupported", f"unsupported on {sys.platform} (it declares beos)")
    assert visibility.readiness(SimpleNamespace(platforms=None)) == ("ready", "")


def test_host_environments(monkeypatch):
    present: set[str] = set()

    def fake_path(p):
        return SimpleNamespace(exists=lambda: p in present, is_dir=lambda: p in present)

    monkeypatch.setattr(visibility, "Path", fake_path)
    assert visibility.host_environments() == frozenset()
    present.add("/.dockerenv")
    assert visibility.host_environments() == frozenset({"docker", "container"})
    present.clear()
    present.add("/run/.containerenv")
    assert visibility.host_environments() == frozenset({"docker", "container"})
    present.clear()
    present.add("/run/s6")
    assert visibility.host_environments() == frozenset({"s6"})
    present.clear()
    present.add("/command/s6-svscan")
    assert visibility.host_environments() == frozenset({"s6"})
    present.clear()
    monkeypatch.setenv(visibility.ENV_OVERRIDE, " Lab , ,gpu")
    assert visibility.host_environments() == frozenset({"lab", "gpu"})


# ── the hard gate ────────────────────────────────────────────────────────────────

def _mac_on_linux(monkeypatch, tmp_path, calls=None):
    monkeypatch.setattr(visibility, "host_platforms", lambda platform=None: frozenset({"linux"}))
    return _skill(tmp_path, "notes", platforms=["macos"], calls=calls), _skill(tmp_path, "weather")


def test_a_skill_for_another_os_is_left_out_and_refused(monkeypatch, tmp_path):
    calls = []
    mac, weather = _mac_on_linux(monkeypatch, tmp_path, calls)
    loader = _loader(mac, weather)
    assert _catalog(loader) == ["weather"]
    assert SkillLoader.catalog_gate(mac) == "unsupported"
    reply = asyncio.run(mac.execute("notes", "x", {"channel": "web"}))
    assert reply == "[skill:notes] is unsupported on linux (it declares macos)" and calls == []
    assert mac.to_dict()["readiness"] == "unsupported"
    assert weather.to_dict()["readiness"] == "ready" and weather.to_dict()["readiness_reason"] == ""


def test_skill_view_answers_unsupported_and_skills_list_leaves_it_out(monkeypatch, tmp_path):
    from agents.core.skills.tools import register_skill_tools
    from agents.core.tool_rpc import ToolRPCServer

    loader = _loader(*_mac_on_linux(monkeypatch, tmp_path))
    server = ToolRPCServer()
    register_skill_tools(server, loader=lambda: loader, proposals=lambda: None, approvals=lambda: None,
                         session_id=lambda: "s", posture=lambda: "operator/owner")

    def call(tool, args):
        return asyncio.run(server.handle({"tool": tool, "args": args}, actor="jarvis"))["result"]

    assert call("skill_view", {"name": "notes"}) == {
        "ok": False, "reason": "skill_unsupported",
        "detail": "'notes' is unsupported on linux (it declares macos)", "readiness_status": "unsupported"}
    assert call("skill_view", {"name": "ghost"})["reason"] == "skill_unknown"
    reads = []
    real = visibility.context
    monkeypatch.setattr(visibility, "context", lambda **kw: reads.append(1) or real(**kw))
    assert [s["name"] for s in call("skills_list", {})["skills"]] == ["weather"]
    assert reads == [1]                                        # read once for the whole list


# ── the soft gates ───────────────────────────────────────────────────────────────

def test_an_environment_skill_is_hidden_outside_it_but_still_runs(monkeypatch, tmp_path):
    from agents.core.skills.tools import register_skill_tools
    from agents.core.tool_rpc import ToolRPCServer

    calls = []
    docker = _skill(tmp_path, "logs", environments=["docker"], calls=calls)
    loader = _loader(docker)
    monkeypatch.setattr(visibility, "host_environments", lambda: frozenset())
    token = _bound("web")
    try:
        assert _catalog(loader) == []
        assert SkillLoader.catalog_gate(docker) == "environment"
        assert asyncio.run(docker.execute("logs", "", {"channel": "web"})) == "logs ran"
        server = ToolRPCServer()
        register_skill_tools(server, loader=lambda: loader, proposals=lambda: None, approvals=lambda: None,
                             session_id=lambda: "s", posture=lambda: "operator/owner")
        view = asyncio.run(server.handle({"tool": "skill_view", "args": {"name": "logs"}}, actor="jarvis"))["result"]
        assert view["ok"] is True                                  # named: explicit consent
        listed = asyncio.run(server.handle({"tool": "skills_list", "args": {}}, actor="jarvis"))["result"]
        assert listed["skills"] == []
        monkeypatch.setattr(visibility, "host_environments", lambda: frozenset({"docker", "container"}))
        assert _catalog(loader) == ["logs"]
    finally:
        _unbind(token)
    assert calls == [("logs", "")]


def test_kanban_holds_for_a_turn_with_no_human(tmp_path, monkeypatch):
    monkeypatch.setattr(visibility, "host_environments", lambda: frozenset())
    loader = _loader(_skill(tmp_path, "board", environments=["kanban"]))
    assert _catalog(loader) == ["board"]                      # no principal: a job, the heartbeat
    for channel, shown in (("web", []), ("voice", []), ("telegram", []), ("eval", ["board"])):
        token = _bound(channel)
        try:
            assert _catalog(loader) == shown, channel
        finally:
            _unbind(token)


def test_session_platforms_hide_a_skill_off_its_channels(tmp_path):
    tg = _skill(tmp_path, "tg", hermes={"session_platforms": ["Telegram"]})
    cli = _skill(tmp_path, "cli", hermes={"session_platforms": ["cli"]})
    loader = _loader(tg, cli)
    assert _catalog(loader) == ["cli", "tg"]                  # no channel: not gated
    for channel, shown in (("web", ["cli"]), ("voice", ["cli"]), ("telegram", ["tg"]), ("discord", [])):
        token = _bound(channel)
        try:
            assert _catalog(loader) == shown, channel
        finally:
            _unbind(token)
    token = _bound("web")
    try:
        assert asyncio.run(tg.execute("tg", "", {"channel": "web"})) == "tg ran"   # still runs when named
    finally:
        _unbind(token)


@pytest.mark.parametrize("hermes,offer,shown", [
    ({"requires_tools": ["web_search"]}, None, True),                  # offer unknown: not applied
    ({"requires_tools": ["web_search"]}, set(), False),
    ({"requires_tools": ["web_search"]}, {"web_search"}, True),
    ({"requires_tools": ["web_search", "file_read"]}, {"web_search"}, False),
    ({"requires_toolsets": ["web"]}, {"web_extract"}, True),
    ({"requires_toolsets": ["web"]}, {"file_read"}, False),
    ({"requires_toolsets": ["warp_drive"]}, {"web_search"}, False),   # an unknown toolset is never there
    ({"requires_toolsets": ["web", "terminal"]}, {"web_search"}, False),
    ({"fallback_for_tools": ["web_search"]}, {"web_search"}, False),
    ({"fallback_for_tools": ["web_search"]}, {"file_read"}, True),
    ({"fallback_for_tools": ["web_search"]}, None, True),
    ({"fallback_for_toolsets": ["terminal"]}, {"terminal_run"}, False),
    ({"fallback_for_toolsets": ["terminal"]}, set(), True),
    ({"fallback_for_toolsets": ["warp_drive"]}, {"web_search"}, True),
])
def test_the_tool_gates(tmp_path, hermes, offer, shown):
    loader = _loader(_skill(tmp_path, "s", hermes=hermes))
    assert _catalog(loader, offer=offer) == (["s"] if shown else [])


def test_the_tool_loops_own_offer_is_used_inside_it(tmp_path):
    from agents.core.autonomy_coordinator import _TURN_TOOL_OFFER

    loader = _loader(_skill(tmp_path, "s", hermes={"fallback_for_tools": ["web_search"]}))
    token = _TURN_TOOL_OFFER.set(frozenset({"web_search"}))
    try:
        assert visibility.current_offer() == frozenset({"web_search"})
        assert _catalog(loader) == []
        bound = visibility.bind_offer(set())                      # a bound offer wins
        try:
            assert visibility.current_offer() == frozenset()
        finally:
            visibility.reset_offer(bound)
    finally:
        _TURN_TOOL_OFFER.reset(token)
    assert visibility.current_offer() is None


def test_malformed_hermes_fields_gate_nothing(tmp_path):
    odd = _skill(tmp_path, "odd", hermes={"requires_tools": "web_search", "session_platforms": [3, " "]})
    odd.manifest["hermes"] = {"requires_tools": "web_search", "session_platforms": [3, " "]}
    token = _bound("telegram")
    try:
        assert _catalog(_loader(odd), offer=set()) == ["odd"]
    finally:
        _unbind(token)
    assert visibility.offer_gate(SimpleNamespace(hermes_meta=None, environments=None), {}) == ""


def test_every_hide_is_logged_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(visibility, "host_environments", lambda: frozenset())
    loader = _loader(_skill(tmp_path, "logs", environments=["docker"]), _skill(tmp_path, "weather"))
    token = _bound("web")
    try:
        with caplog.at_level(logging.INFO, logger="jarvis.skills.visibility"):
            _catalog(loader)
            _catalog(loader)
    finally:
        _unbind(token)
    assert [r.getMessage() for r in caplog.records if r.name == "jarvis.skills.visibility"] == [
        "Skill 'logs' is not offered to the model on this turn: environment gate"]


# ── wiring ───────────────────────────────────────────────────────────────────────

def test_the_prompt_context_binds_this_turns_offer(tmp_path):
    from agents.core.orchestrator import Orchestrator

    loader = _loader(_skill(tmp_path, "search", hermes={"requires_tools": ["web_search"]}),
                     _skill(tmp_path, "offline", hermes={"fallback_for_tools": ["web_search"]}))
    seen = []
    runtime = SimpleNamespace(offered_names=lambda agent_id: seen.append(agent_id) or {"web_search"})
    fake = SimpleNamespace(skills=loader, agent_tool_runtime=runtime, get_setting=lambda k, d=None: d)
    agent = SimpleNamespace(id="jarvis")
    rows = Orchestrator._prompt_context(fake, agent, {})["skills"]
    assert [r["skill"] for r in rows] == ["search"] and seen == ["jarvis"]
    assert visibility.current_offer() is None                  # reset after the catalog
    runtime.offered_names = lambda agent_id: set()
    assert [r["skill"] for r in Orchestrator._prompt_context(fake, agent, {})["skills"]] == ["offline"]
    runtime.offered_names = MagicMock(side_effect=RuntimeError("registry down"))
    rows = Orchestrator._prompt_context(fake, agent, {})["skills"]
    assert [r["skill"] for r in rows] == ["offline", "search"]   # unknown offer: not applied
    fake.agent_tool_runtime = None
    assert len(Orchestrator._prompt_context(fake, agent, {})["skills"]) == 2


def test_the_runtime_names_its_offer_without_side_effects():
    from agents.core.agent_runtime import AgentToolRuntime

    runtime = AgentToolRuntime.__new__(AgentToolRuntime)
    runtime._enabled = lambda: True
    runtime._server = SimpleNamespace(tools=lambda: [{"name": "web_search"}, {"name": "terminal_run"}])
    runtime._tool_profile = lambda agent_id, tools: ([t for t in tools if t["name"] == "web_search"], None)
    assert runtime.offered_names("jarvis") == frozenset({"web_search"})
    runtime._enabled = lambda: False
    assert runtime.offered_names("jarvis") == frozenset()
    runtime._enabled = MagicMock(side_effect=RuntimeError("settings"))
    assert runtime.offered_names("jarvis") == frozenset()


def test_the_skills_list_route_says_readiness(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agents import web

    mac, weather = _mac_on_linux(monkeypatch, tmp_path)
    orch = MagicMock()
    orch.skills = SimpleNamespace(skills={"notes": mac, "weather": weather})
    monkeypatch.setattr(web, "orch", orch)
    rows = TestClient(web.app).get("/skills").json()["skills"]
    assert rows["notes"]["readiness"] == "unsupported"
    assert rows["notes"]["readiness_reason"] == "unsupported on linux (it declares macos)"
    assert rows["weather"]["readiness"] == "ready"


def test_an_unbound_turn_has_no_channel():
    from agents.core.skills import switches

    assert switches.current_channel() == ""
    token = _bound("Telegram")
    try:
        assert switches.current_channel() == "telegram"
    finally:
        _unbind(token)
