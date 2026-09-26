"""H227 — "what can it do right now": the inspector.

Hermes answers the question from a status line and a session panel: the model and its
state, the tools this turn is offered, the skills the prompt names, the resolved system
prompt and the MCP servers. Nerva had each piece somewhere (the raw ToolRPC registry at
``/api/toolrpc/tools``, the MCP admin list, ``nerva prompt-size`` over files on disk) and
nothing that answered for a given agent and a given principal. The inspector does: one
read-only payload built from the same code a turn runs, served at
``GET /api/admin/inspector``, rendered by ``nerva inspect`` and by the HUD's Inspector panel.

Hermetic: a partial Orchestrator over the coordinator's real ToolRPC registry, a stub
agent, an in-memory skill loader and MCP servers that never connect.
"""
from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.core import inspector as ins  # noqa: E402
from agents.core import settings_db  # noqa: E402
from agents.core.agent import Agent  # noqa: E402
from agents.core.commands import Principal  # noqa: E402
from agents.core.job_toolsets import allows  # noqa: E402
from agents.core.skills import visibility  # noqa: E402
from agents.core.skills.loader import Skill, SkillLoader  # noqa: E402
from agents.core.tool_profiles import ToolProfileResolver  # noqa: E402

SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    visibility._logged.clear()
    yield
    visibility._logged.clear()


class _Store:
    def __init__(self, facts):
        self.facts = list(facts)

    def list(self):
        return list(self.facts)


class _Cognition:
    def __init__(self, facts):
        self.living = SimpleNamespace(core=_Store(facts), user_core=_Store([]))

    def sub_enabled(self, name):
        return True

    def module(self, name):
        return self.living if name == "memory" else None


def _skill(tmp_path, name):
    path = tmp_path / "skills" / name
    path.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "description": f"{name} does things",
                "commands": [{"command": name, "description": f"run {name}"}]}
    skill = Skill(name, path, manifest)
    skill.trusted = True
    skill.view_files = {"SKILL.md": f"# {name}\n".encode()}

    async def _run(args, context=None):
        return f"{name} ran"

    skill.register_command(name, _run)
    return skill


def _agent(system="You are Jarvis, the house brain."):
    stub = SimpleNamespace(id="jarvis", name="Jarvis", system_prompt=lambda: system)
    stub.build_prompt = types.MethodType(Agent.build_prompt, stub)
    return stub


class _Http:
    initialized = True


def _mcp():
    from agents.core.mcp.client import MCPManager, MCPServer, MCPTool

    manager = MCPManager()
    remote = MCPServer("notes", transport="streamable-http", url="https://notes.example/mcp")
    remote._http = _Http()          # a live HTTP session: no subprocess to look at
    remote.tools = [MCPTool(name="search", description="find a note", input_schema={}, server="notes"),
                    MCPTool(name="read", description="read a note", input_schema={}, server="notes")]
    local = MCPServer("fs", transport="stdio", command="mcp-fs", trust="full")
    manager.register(remote)
    manager.register(local)
    return manager


def _orch(tmp_path, *, settings=None, facts=("the owner wakes at seven",), patterns=None,
          system="You are Jarvis, the house brain."):
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.orchestrator import Orchestrator

    values = {"llm.tool_loop_enabled": True, **(settings or {})}
    o = Orchestrator.__new__(Orchestrator)
    o._runtime_settings = values
    o._session_id_default = "default"
    o.agents = {"jarvis": _agent(system)}
    o.config = SimpleNamespace(agents={"jarvis": SimpleNamespace(tools=patterns)})
    o.cognition = _Cognition(facts)

    async def _context(_agent_id):
        return ""

    o.memory = SimpleNamespace(get_agent_context=_context)
    o.llm_router = SimpleNamespace(name="lmstudio", active_model="qwen3-8b")
    loader = SkillLoader.__new__(SkillLoader)
    loader.skills = {s.name: s for s in (_skill(tmp_path, "weather"), _skill(tmp_path, "pomodoro"))}
    o.skills = loader
    o.mcp = _mcp()
    AutonomyCoordinator(o)._wire_agent_tool_runtime()
    return o


def _expected(o, principal, origin="generated"):
    resolver = ToolProfileResolver(
        settings=o.get_setting,
        agent_patterns=lambda agent_id: o.config.agents[agent_id].tools,
        principal=lambda: principal,
        origin=lambda: origin,
        shared_session=lambda: True,
    )
    registry = [t for t in o.tool_rpc.tools() if allows(str(t.get("name") or ""))]
    offered, _decision = resolver("jarvis", registry)
    return [t["name"] for t in offered]


def _names(payload):
    return [row["name"] for row in payload["tools"]["offered"]]


# ── tools: the profile, not the registry ─────────────────────────────────────


async def test_a_guests_tools_are_the_profile_resolvers_set_not_the_raw_registry(tmp_path):
    o = _orch(tmp_path)
    payload = await ins.build_inspector(o, "jarvis", view="guest")
    expected = _expected(o, Principal(channel="web", admin=False))
    registry = [t["name"] for t in o.tool_rpc.tools()]
    assert _names(payload) == expected
    assert set(expected) < set(registry)                 # the guest is offered less
    assert "file_write" in registry and "file_write" not in expected
    assert payload["posture"] == "operator/guest"
    assert set(payload["tools"]["withheld"]) == set(registry) - set(expected)
    assert payload["tools"]["registry"] == len(registry)


@pytest.mark.parametrize(("view", "principal", "origin", "posture"), [
    ("owner", Principal(channel="web", admin=True), "generated", "operator/owner"),
    ("guest", Principal(channel="web", admin=False), "generated", "operator/guest"),
    ("inbound-owner", Principal(channel="telegram", admin=True), "inbound", "inbound/owner"),
    ("inbound", Principal(channel="telegram", admin=False), "inbound", "inbound/guest"),
    ("internal", None, "generated", "internal/system"),
])
async def test_every_view_is_the_posture_it_names(tmp_path, view, principal, origin, posture):
    o = _orch(tmp_path)
    payload = await ins.build_inspector(o, "jarvis", view=view, sections=["tools"])
    assert payload["posture"] == posture and payload["view"] == view
    assert _names(payload) == _expected(o, principal, origin)


async def test_the_owner_on_the_hud_is_offered_the_whole_registry(tmp_path):
    o = _orch(tmp_path)
    payload = await ins.build_inspector(o, "jarvis", view="owner", sections=["tools"])
    assert _names(payload) == [t["name"] for t in o.tool_rpc.tools() if allows(t["name"])]
    assert payload["tools"]["withheld"] == []


async def test_the_agents_own_list_narrows_the_offer(tmp_path):
    o = _orch(tmp_path, patterns=["time", "file_*"])
    payload = await ins.build_inspector(o, "jarvis", view="guest", sections=["tools"])
    assert _names(payload) == [n for n in _expected(o, Principal(channel="web")) if n == "time" or n.startswith("file_")]
    assert "file_write" not in _names(payload)           # gated: the guest posture dropped it first


async def test_rows_say_gated_and_untrusted_output(tmp_path):
    o = _orch(tmp_path)
    rows = {r["name"]: r for r in (await ins.build_inspector(o, "jarvis", sections=["tools"]))["tools"]["offered"]}
    registry = {t["name"]: t for t in o.tool_rpc.tools()}
    for name, row in rows.items():
        assert row["gated"] is bool(registry[name].get("gated"))
        assert row["untrusted_output"] is (registry[name].get("untrusted_output") is True)
        assert set(row) == {"name", "gated", "untrusted_output", "description"}
        assert len(row["description"]) <= ins.DESCRIPTION_CHARS
    assert rows["file_write"]["gated"] is True and rows["time"]["gated"] is False
    assert any(r["untrusted_output"] for r in rows.values())
    long = next(n for n, t in registry.items() if len(" ".join(t["description"].split())) > ins.DESCRIPTION_CHARS)
    assert ins.DESCRIPTION_CHARS == 160
    assert rows[long]["description"] == " ".join(registry[long]["description"].split())[:160]


async def test_the_tool_loop_being_off_is_said(tmp_path):
    o = _orch(tmp_path, settings={"llm.tool_loop_enabled": False})
    payload = await ins.build_inspector(o, "jarvis", view="guest", sections=["tools", "status"])
    assert payload["tools"]["loop_enabled"] is False and payload["status"]["tool_loop"] is False
    # What the profile would offer once it is on — not a claim that the model sees it now.
    assert _names(payload) == _expected(o, Principal(channel="web"))


async def test_a_resolver_failure_offers_nothing(tmp_path, monkeypatch):
    o = _orch(tmp_path)

    def boom(agent_id):
        raise RuntimeError("registry down")

    monkeypatch.setattr(o.agent_tool_runtime, "_resolve_offer", boom)
    payload = await ins.build_inspector(o, "jarvis", sections=["tools"])
    assert payload["tools"]["offered"] == [] and payload["tools"]["error"] == "unavailable"
    assert set(payload["tools"]["withheld"]) == {t["name"] for t in o.tool_rpc.tools()}


async def test_without_a_tool_runtime_the_section_says_so(tmp_path):
    o = _orch(tmp_path)
    o.agent_tool_runtime = None
    tools = (await ins.build_inspector(o, "jarvis", sections=["tools"]))["tools"]
    assert tools["wired"] is False and tools["offered"] == [] and tools["registry"] == 0


# ── skills and the prompt ────────────────────────────────────────────────────


async def test_the_skills_are_the_prompt_catalogs_rows(tmp_path):
    o = _orch(tmp_path)
    skills = (await ins.build_inspector(o, "jarvis", sections=["skills"]))["skills"]
    assert skills["in_prompt"] is True and skills["count"] == 2
    assert sorted(r["skill"] for r in skills["rows"]) == ["pomodoro", "weather"]
    assert {r["command"].lstrip("/").split()[0] for r in skills["rows"]} == {"weather", "pomodoro"}
    off = _orch(tmp_path, settings={"llm.skills_in_prompt": False})
    skills = (await ins.build_inspector(off, "jarvis", sections=["skills"]))["skills"]
    assert skills == {"in_prompt": False, "count": 0, "rows": []}


@pytest.mark.parametrize(("view", "bound"), [
    ("owner", ("web", True, "generated")),
    ("guest", ("web", False, "generated")),
    ("inbound-owner", ("telegram", True, "inbound")),
    ("inbound", ("telegram", False, "inbound")),
    ("internal", ("unknown", False, "generated")),
])
async def test_the_look_binds_what_a_turn_from_that_door_binds(tmp_path, monkeypatch, view, bound):
    """The catalog reads the principal (a skill can be off on a surface) and the look runs
    under the action origin a real turn from that door has: inbound for a channel."""
    from agents.core.action_origin import current_action_origin
    from agents.core.orchestrator import current_principal

    o = _orch(tmp_path)
    seen = []
    real = o.skills.prompt_catalog

    def catalog(agent_id=None, **kw):
        p = current_principal()
        seen.append((p.channel, p.admin, current_action_origin()))
        return real(agent_id, **kw)

    monkeypatch.setattr(o.skills, "prompt_catalog", catalog)
    await ins.build_inspector(o, "jarvis", view=view, sections=["skills"])
    assert seen == [bound]


async def test_the_system_prompt_holds_the_skills_block_and_the_core_memory(tmp_path):
    o = _orch(tmp_path)
    prompt = (await ins.build_inspector(o, "jarvis", sections=["system_prompt"]))["system_prompt"]
    assert prompt["system"] == "You are Jarvis, the house brain."
    turn = prompt["turn"]
    assert "Available skills:" in turn and "weather" in turn
    assert "[core memory]" in turn and "the owner wakes at seven" in turn
    assert "LLM backend: lmstudio" in turn and "Active model: qwen3-8b" in turn
    assert "Language (applies to every agent" in turn
    assert turn.rstrip().endswith("You can also hand off to another agent with '[handoff:agent_id]'.")
    # An empty user turn: nothing between the last rail and the wrapper's closing lines.
    assert "Data grounding" in turn and "\n\n\nRespond as Jarvis." in turn
    assert prompt["truncated"] is False
    assert prompt["bytes"] == len(prompt["system"].encode()) + len(turn.encode())
    from agents.core.llm.tokenizer import estimate_tokens

    assert prompt["tokens"] == estimate_tokens(prompt["system"]) + estimate_tokens(turn) > 0


async def test_the_inspector_does_not_freeze_the_days_core_snapshot(tmp_path):
    """The core block is rendered once per session and day, then frozen for the prompt
    cache. Looking at it must not be what freezes it: a fact written after the look and
    before the day's first turn still reaches that turn."""
    o = _orch(tmp_path)
    await ins.build_inspector(o, "jarvis", sections=["system_prompt"])
    assert getattr(o, "_core_block_cache", None) is None
    o.cognition.living.core.facts.append("the owner is allergic to peanuts")
    assert "allergic to peanuts" in o._living_core_memory_block()
    # Once a turn froze it, the inspector shows the frozen block, as the next turn will send.
    o.cognition.living.core.facts.append("a fact from after the freeze")
    prompt = (await ins.build_inspector(o, "jarvis", sections=["system_prompt"]))["system_prompt"]
    assert "allergic to peanuts" in prompt["turn"] and "after the freeze" not in prompt["turn"]


async def test_secrets_in_the_prompt_are_masked(tmp_path):
    o = _orch(tmp_path, facts=[f"the deploy token is {SECRET}"], system=f"Use {SECRET} for GitHub.")
    payload = await ins.build_inspector(o, "jarvis")
    assert SECRET not in json.dumps(payload)
    assert "the deploy token is" in payload["system_prompt"]["turn"]


async def test_a_redactor_that_cannot_load_shows_no_prompt(tmp_path, monkeypatch):
    from agents.core.security import log_redaction

    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("no scanner")

    monkeypatch.setattr(log_redaction, "SecretRedactionFilter", Broken)
    monkeypatch.setattr(ins, "_REDACTOR", None)
    o = _orch(tmp_path, system=f"Use {SECRET} for GitHub.")
    prompt = (await ins.build_inspector(o, "jarvis", sections=["system_prompt"]))["system_prompt"]
    assert prompt["system"] == "" and prompt["turn"] == "" and prompt["withheld"] is True
    assert prompt["tokens"] == 0 and prompt["bytes"] == 0
    assert SECRET not in json.dumps(prompt)


async def test_the_prompt_is_capped_at_64_kib(tmp_path):
    big = "€" * 30_000                                    # 90,000 bytes of three-byte characters
    o = _orch(tmp_path, system=big)
    prompt = (await ins.build_inspector(o, "jarvis", sections=["system_prompt"]))["system_prompt"]
    shown = len(prompt["system"].encode()) + len(prompt["turn"].encode())
    assert ins.PROMPT_CAP_BYTES == 64 * 1024
    assert shown <= ins.PROMPT_CAP_BYTES and prompt["truncated"] is True
    assert prompt["bytes"] > ins.PROMPT_CAP_BYTES
    # 65,536 is not a multiple of 3: the character the cap splits is dropped, not mangled,
    # and the byte it leaves goes to the turn part, which shares the one budget.
    assert prompt["system"] == "€" * (ins.PROMPT_CAP_BYTES // 3)
    assert shown == ins.PROMPT_CAP_BYTES and prompt["turn"] == "A"      # "Available skills:"…


async def test_nothing_the_inspector_binds_outlives_it(tmp_path):
    from agents.core.action_origin import current_action_origin
    from agents.core.autonomy_coordinator import _TURN_TOOL_OFFER
    from agents.core.orchestrator import current_principal

    o = _orch(tmp_path)
    before = (current_principal(), current_action_origin(), _TURN_TOOL_OFFER.get(None))
    await ins.build_inspector(o, "jarvis", view="inbound")
    assert (current_principal(), current_action_origin(), _TURN_TOOL_OFFER.get(None)) == before


# ── MCP and status ───────────────────────────────────────────────────────────


async def test_mcp_rows_use_the_transport_aware_liveness(tmp_path):
    o = _orch(tmp_path)
    mcp = (await ins.build_inspector(o, "jarvis", sections=["mcp"]))["mcp"]
    rows = {r["name"]: r for r in mcp["servers"]}
    assert rows["notes"] == {"name": "notes", "transport": "streamable-http", "trust": "read-only",
                             "connected": True, "tools": 2, "tool_names": ["search", "read"]}
    assert rows["fs"]["connected"] is False and rows["fs"]["trust"] == "full" and rows["fs"]["tools"] == 0
    assert mcp["connected"] == 1
    assert "https://notes.example" not in json.dumps(mcp)     # no endpoints, no commands
    assert "mcp-fs" not in json.dumps(mcp)


async def test_a_server_whose_liveness_raises_is_not_connected(tmp_path, monkeypatch):
    o = _orch(tmp_path)

    def boom():
        raise RuntimeError("probe")

    monkeypatch.setattr(o.mcp.servers["notes"], "is_connected", boom)
    rows = {r["name"]: r for r in (await ins.build_inspector(o, "jarvis", sections=["mcp"]))["mcp"]["servers"]}
    assert rows["notes"]["connected"] is False


async def test_the_status_line(tmp_path):
    from agents import __version__

    o = _orch(tmp_path, settings={"llm.tool_loop_context_tokens": 24000})

    async def inventory():
        return {"resident_models": [{"provider": "lmstudio", "id": "qwen3-8b"}], "residency_state": "loaded",
                "providers": [{"online": True}], "models": [{"provider": "lmstudio", "id": "qwen3-8b", "configured": True}]}

    status = (await ins.build_inspector(o, "jarvis", sections=["status"], inventory=inventory))["status"]
    assert status["version"] == __version__
    assert (status["backend"], status["model"]) == ("lmstudio", "qwen3-8b")
    assert status["model_state"] == "ready" and status["loaded_model"] == "qwen3-8b"
    assert status["context_tokens"] == 24000 and status["tool_loop"] is True and status["safe_mode"] is False

    async def offline():
        raise OSError("no LM Studio")

    status = (await ins.build_inspector(o, "jarvis", sections=["status"], inventory=offline))["status"]
    assert status["model_state"] == "unknown" and status["loaded_model"] is None
    o._runtime_settings["llm.tool_loop_context_tokens"] = "lots"
    assert (await ins.build_inspector(o, "jarvis", sections=["status"]))["status"]["context_tokens"] == 0


async def test_safe_mode_is_on_the_status_line(tmp_path, monkeypatch):
    from agents.core import safe_mode

    monkeypatch.setattr(safe_mode, "enabled", lambda: True)
    status = (await ins.build_inspector(_orch(tmp_path), "jarvis", sections=["status"]))["status"]
    assert status["safe_mode"] is True
    code, out, _err, _calls = _cli(["inspect", "--section", "status"], {"agent": "jarvis", "status": status})
    assert code == 0 and "SAFE MODE" in out


async def test_without_a_router_the_backend_is_none(tmp_path):
    o = _orch(tmp_path)
    o.llm_router = None
    payload = await ins.build_inspector(o, "jarvis", sections=["status", "system_prompt"])
    assert payload["status"]["backend"] == "none" and payload["status"]["model"] is None
    assert "LLM backend" not in payload["system_prompt"]["turn"]


# ── the request ──────────────────────────────────────────────────────────────


async def test_sections_narrow_the_payload_and_unknown_names_are_refused(tmp_path):
    o = _orch(tmp_path)
    everything = await ins.build_inspector(o, "jarvis")
    assert set(everything) == {"agent", "view", "posture", *ins.SECTIONS}
    assert ins.SECTIONS == ("status", "tools", "skills", "mcp", "system_prompt")
    only = await ins.build_inspector(o, "jarvis", sections=["mcp"])
    assert set(only) == {"agent", "view", "posture", "mcp"}
    # One order whatever the request's, and a section asked twice is answered once.
    two = await ins.build_inspector(o, "jarvis", sections=["mcp", "status", "mcp"])
    assert list(two) == ["agent", "view", "posture", "status", "mcp"]
    with pytest.raises(ValueError, match="section"):
        await ins.build_inspector(o, "jarvis", sections=["secrets"])
    with pytest.raises(ValueError, match="view"):
        await ins.build_inspector(o, "jarvis", view="root")
    with pytest.raises(LookupError):
        await ins.build_inspector(o, "nobody")


async def test_the_payload_is_json(tmp_path):
    o = _orch(tmp_path)
    payload = await ins.build_inspector(o, "jarvis")
    assert json.loads(json.dumps(payload)) == payload


# ── the route ────────────────────────────────────────────────────────────────


@pytest.fixture
def hub(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    o = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", o)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h227")

    async def inventory():
        return {"resident_models": [], "residency_state": "offline", "providers": []}

    monkeypatch.setattr(web, "_list_local_models", inventory)
    return TestClient(web.app), o


def test_the_route_serves_the_payload(hub):
    http, o = hub
    got = http.get("/api/admin/inspector", params={"agent": "jarvis", "view": "guest"},
                   headers={"X-Admin-Token": "adm-h227"})
    assert got.status_code == 200 and "no-store" in got.headers.get("cache-control", "")
    body = got.json()
    assert body["posture"] == "operator/guest"
    assert _names(body) == _expected(o, Principal(channel="web"))
    assert body["status"]["model_state"] == "offline"
    assert "Available skills:" in body["system_prompt"]["turn"]


def test_the_route_defaults_to_jarvis_as_the_owner(hub):
    http, _o = hub
    body = http.get("/api/admin/inspector", headers={"X-Admin-Token": "adm-h227"}).json()
    assert (body["agent"], body["view"], body["posture"]) == ("jarvis", "owner", "operator/owner")


def test_the_route_refuses_what_it_cannot_answer(hub):
    http, _o = hub
    hdr = {"X-Admin-Token": "adm-h227"}
    assert http.get("/api/admin/inspector", params={"agent": "nobody"}, headers=hdr).status_code == 404
    bad = http.get("/api/admin/inspector", params={"view": "root"}, headers=hdr)
    assert bad.status_code == 400 and bad.json()["views"] == list(ins.VIEWS)
    bad = http.get("/api/admin/inspector", params={"section": "secrets"}, headers=hdr)
    assert bad.status_code == 400 and bad.json()["sections"] == list(ins.SECTIONS)
    one = http.get("/api/admin/inspector", params=[("section", "mcp"), ("section", "status")], headers=hdr)
    assert one.status_code == 200 and set(one.json()) == {"agent", "view", "posture", "mcp", "status"}


def test_the_route_needs_the_admin_token(hub):
    http, _o = hub
    assert http.get("/api/admin/inspector").status_code in (401, 403)


def test_the_route_is_admin_guarded():
    snapshot = json.loads((ROOT / "tests" / "_snapshots" / "route_auth.json").read_text(encoding="utf-8"))
    assert snapshot["GET /api/admin/inspector"] == "admin"
    from agents import web
    from tests._route_introspect import iter_effective_routes

    (route,) = [r for r in iter_effective_routes(web.app)
                if getattr(r, "path", "") == "/api/admin/inspector" and hasattr(r, "dependant")]
    assert "admin_guard" in {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}


def test_the_route_before_the_hub_is_up(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "orch", None)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h227")
    got = TestClient(web.app).get("/api/admin/inspector", headers={"X-Admin-Token": "adm-h227"})
    assert got.status_code == 503


# ── `nerva inspect` ──────────────────────────────────────────────────────────


def _cli(argv, payload):
    from agents.cli.nerva import Context, main

    calls = []

    class Hub:
        base_url = "http://127.0.0.1:8080"

        def get(self, path):
            calls.append(path)
            return payload

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: Hub())
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), calls


async def _payload(tmp_path, view="guest"):
    return await ins.build_inspector(_orch(tmp_path), "jarvis", view=view)


async def test_nerva_inspect_json_is_the_payload(tmp_path):
    payload = await _payload(tmp_path)
    code, out, _err, calls = _cli(["inspect", "--as", "guest", "--json"], payload)
    assert code == 0 and json.loads(out) == payload
    assert calls == ["/api/admin/inspector?agent=jarvis&view=guest"]


async def test_nerva_inspect_renders_every_section_from_the_payload(tmp_path):
    payload = await _payload(tmp_path)
    code, out, _err, _calls = _cli(["inspect", "--as", "guest"], payload)
    assert code == 0
    status = payload["status"]
    assert f"backend {status['backend']}" in out and f"model {status['model']}" in out
    assert "context budget 75% of the model window" in out      # 0 = 75 % of the window
    budget = {**payload, "status": {**status, "context_tokens": 24000}}
    assert "context budget 24000 ·" in _cli(["inspect"], budget)[1]
    assert "posture operator/guest" in out
    for row in payload["tools"]["offered"]:
        assert row["name"] in out
    assert f"withheld ({len(payload['tools']['withheld'])})" in out
    for row in payload["skills"]["rows"]:
        assert row["command"] in out
    for row in payload["mcp"]["servers"]:
        assert row["name"] in out
    assert payload["system_prompt"]["system"] in out
    assert "Available skills:" in out
    assert f"about {payload['system_prompt']['tokens']} tokens before any history" in out


async def test_nerva_inspect_section_prints_only_that_section(tmp_path):
    payload = await _payload(tmp_path)
    code, out, _err, _calls = _cli(["inspect", "--section", "skills"], payload)
    assert code == 0 and "skills   2 in the prompt" in out
    assert [line.split() for line in out.splitlines() if line.startswith("  ")] == [
        ["pomodoro", "run", "pomodoro"], ["weather", "run", "weather"]]
    code, out, _err, calls = _cli(["inspect", "jarvis", "--section", "mcp"], payload)
    assert code == 0 and "notes" in out and "Available skills:" not in out
    assert calls == ["/api/admin/inspector?agent=jarvis&view=owner&section=mcp"]
    code, out, _err, calls = _cli(["inspect", "--section", "prompt", "--json"], payload)
    assert calls == ["/api/admin/inspector?agent=jarvis&view=owner&section=system_prompt"]
    assert json.loads(out) == payload


async def test_nerva_inspect_says_when_the_tool_loop_is_off(tmp_path):
    o = _orch(tmp_path, settings={"llm.tool_loop_enabled": False})
    payload = await ins.build_inspector(o, "jarvis", sections=["tools"])
    code, out, _err, _calls = _cli(["inspect", "--section", "tools"], payload)
    assert code == 0 and "tool loop is off" in out


def test_nerva_inspect_is_in_the_command_tree():
    from agents.cli.nerva import build_parser, command_tree

    tree = command_tree(build_parser())
    assert "inspect" in tree
    ns = build_parser().parse_args(["inspect"])
    assert (ns.agent, ns.view, ns.section, ns.json) == ("jarvis", "owner", None, False)
    with pytest.raises(SystemExit):
        build_parser().parse_args(["inspect", "--as", "root"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["inspect", "--section", "secrets"])


def test_the_view_and_section_names_are_one_list():
    from agents.cli import nerva

    assert tuple(nerva.INSPECT_VIEWS) == tuple(ins.VIEWS)
    assert set(nerva.INSPECT_SECTIONS.values()) == set(ins.SECTIONS)

