"""Hermes absorption 3b — least privilege at the moment of *offering*.

Every agent on every surface was offered the whole ToolRPC allowlist; mediation happened
only at execution. Now a profile keyed by agent × surface × principal decides what the
model even sees, a call outside it is `tool_not_allowed`, and the resolved sets over the
live registry are pinned in tests/_snapshots/tool_profiles.json — regenerate with
`python tests/test_tool_profiles.py --update` when a change is intended.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core import tool_profiles as tp  # noqa: E402
from agents.core.agent_runtime import _NO_TOOLS_REPLY, AgentToolRuntime  # noqa: E402
from agents.core.commands import Principal  # noqa: E402
from agents.core.config import AgentConfig  # noqa: E402
from agents.core.llm.tool_protocol import ToolCall, ToolTurn  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402

SNAPSHOT = Path(__file__).parent / "_snapshots" / "tool_profiles.json"
DEFAULTS = lambda key, default: default  # noqa: E731 — the settings a fresh install has


def _live_registry(root: str) -> list[dict]:
    """The coordinator's real ToolRPC allowlist, file tools switched on."""
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    os.environ["JARVIS_FILE_TOOLS"] = "1"
    os.environ["JARVIS_FILE_ROOTS"] = root
    orch = SimpleNamespace(agents={})
    AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    return orch.tool_rpc.tools()


def _resolved(tools: list[dict]) -> dict:
    postures = {}
    for surface, principal in tp.POSTURES:
        offered, _withheld = tp.resolve_tools(
            tools, posture=tp.ToolPosture(surface, principal), settings=DEFAULTS,
        )
        postures[f"{surface}/{principal}"] = [t["name"] for t in offered]
    return {"registry": [t["name"] for t in tools], "postures": postures}


# ── classification ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("principal", "origin", "expected"),
    [
        (Principal(channel="web", admin=True), "generated", ("operator", "owner")),
        (Principal(channel="web", admin=False), "generated", ("operator", "guest")),
        (Principal(channel="voice", admin=False), "generated", ("operator", "guest")),
        (Principal(channel="telegram", admin=True), "generated", ("inbound", "owner")),
        (Principal(channel="telegram", admin=False), "generated", ("inbound", "guest")),
        (Principal(channel="whatsapp", admin=False), "inbound", ("inbound", "guest")),
        (Principal(), "generated", ("internal", "system")),
        (None, "generated", ("internal", "system")),
        # The origin wins: an inbound parent context makes even the owner's HUD turn inbound.
        (Principal(channel="web", admin=True), "inbound", ("inbound", "owner")),
        # No principal but an inbound origin: a guest, never the system posture.
        (None, "inbound", ("inbound", "guest")),
        # A bound principal on an internal channel is still an unattended turn.
        (Principal(channel="workflow", admin=True), "generated", ("internal", "system")),
        (Principal(channel="  WEB ", admin=True), "generated", ("operator", "owner")),
    ],
)
def test_classify_turn(principal, origin, expected):
    posture = tp.classify_turn(principal, origin)
    assert (posture.surface, posture.principal) == expected
    assert posture.key == "/".join(expected)


# ── the postures ─────────────────────────────────────────────────────────────

TOOLS = [
    {"name": "echo", "gated": False},
    {"name": "file_search", "gated": False},
    {"name": "desktop_run", "gated": True},
]


def _names(surface, principal, *, settings=DEFAULTS, patterns=None, tools=TOOLS):
    offered, withheld = tp.resolve_tools(
        tools, posture=tp.ToolPosture(surface, principal), settings=settings,
        agent_patterns=patterns,
    )
    return [t["name"] for t in offered], withheld


def test_default_postures():
    assert _names("operator", "owner") == (["echo", "file_search", "desktop_run"], [])
    assert _names("operator", "guest") == (["echo", "file_search"], ["desktop_run"])
    assert _names("inbound", "owner") == (["echo", "file_search"], ["desktop_run"])
    assert _names("inbound", "guest") == (["echo"], ["file_search", "desktop_run"])
    assert _names("internal", "system") == (["echo", "file_search"], ["desktop_run"])
    # A posture the resolver does not know offers nothing.
    assert _names("mars", "owner") == ([], ["echo", "file_search", "desktop_run"])


def test_actuation_toggles_widen_exactly_one_posture_each():
    inbound = lambda key, default: True if key == "llm.inbound_actuation" else default  # noqa: E731
    assert _names("inbound", "owner", settings=inbound)[0] == ["echo", "file_search", "desktop_run"]
    assert _names("inbound", "guest", settings=inbound)[0] == ["echo"]
    assert _names("internal", "system", settings=inbound)[0] == ["echo", "file_search"]
    internal = lambda key, default: True if key == "llm.internal_actuation" else default  # noqa: E731
    assert _names("internal", "system", settings=internal)[0] == ["echo", "file_search", "desktop_run"]
    assert _names("inbound", "owner", settings=internal)[0] == ["echo", "file_search"]
    # A truthy non-bool never counts as on (one env-bool convention, fail closed).
    loose = lambda key, default: "yes"  # noqa: E731
    assert _names("inbound", "owner", settings=loose)[0] == ["echo", "file_search"]


def test_guest_tools_setting_never_reaches_a_gated_tool():
    guest = lambda key, default: ["file_search", "desktop_run"] if key == "llm.guest_tools" else default  # noqa: E731
    assert _names("inbound", "guest", settings=guest) == (["file_search"], ["echo", "desktop_run"])
    empty = lambda key, default: [] if key == "llm.guest_tools" else default  # noqa: E731
    assert _names("inbound", "guest", settings=empty)[0] == []
    assert tp.guest_tool_names(lambda key, default: ["echo", 3, "", "x" * 65, " time "]) == ("echo", "time")
    assert tp.guest_tool_names(lambda key, default: "echo,time") == ()

    def broken(key, default):
        raise RuntimeError("settings store down")

    assert tp.guest_tool_names(broken) == ()
    assert _names("inbound", "guest", settings=broken)[0] == []


def test_agent_patterns_only_narrow():
    assert _names("operator", "owner", patterns=["file_*"]) == (["file_search"], ["echo", "desktop_run"])
    assert _names("operator", "owner", patterns=["*"])[0] == ["echo", "file_search", "desktop_run"]
    assert _names("operator", "owner", patterns=[])[0] == []
    assert _names("operator", "owner", patterns="echo")[0] == []  # malformed → nothing
    assert _names("inbound", "guest", patterns=["desktop_run", "file_search"])[0] == []
    assert _names("inbound", "guest", patterns=["echo"])[0] == ["echo"]
    assert _names("operator", "owner", patterns=None)[0] == ["echo", "file_search", "desktop_run"]


def test_agent_config_reads_the_tools_list():
    assert AgentConfig({"id": "x", "tools": ["file_*", "echo"]}).tools == ["file_*", "echo"]
    assert AgentConfig({"id": "x"}).tools is None
    assert AgentConfig({"id": "x", "tools": "file_*"}).tools is None


def test_settings_rows_exist():
    from agents.core.settings_db import DEFAULTS as ROWS

    rows = {(r["category"], r["key"]): r for r in ROWS}
    assert rows[("llm", "guest_tools")]["kind"] == "tags"
    assert rows[("llm", "guest_tools")]["value"] == ["echo", "time"]
    assert rows[("llm", "inbound_actuation")]["kind"] == "toggle"
    assert rows[("llm", "inbound_actuation")]["value"] is False
    assert rows[("llm", "internal_actuation")]["kind"] == "toggle"
    assert rows[("llm", "internal_actuation")]["value"] is False


def test_resolver_reads_the_current_turn():
    turn = {"principal": Principal(channel="telegram", admin=False), "origin": "generated"}
    resolver = tp.ToolProfileResolver(
        settings=DEFAULTS,
        agent_patterns=lambda agent_id: ["*"] if agent_id == "jarvis" else ["echo"],
        principal=lambda: turn["principal"],
        origin=lambda: turn["origin"],
    )
    offered, decision = resolver("jarvis", TOOLS)
    assert [t["name"] for t in offered] == ["echo"]
    assert (decision.surface, decision.principal) == ("inbound", "guest")
    assert decision.offered == ("echo",) and decision.withheld == ("file_search", "desktop_run")
    turn["principal"] = Principal(channel="web", admin=True)
    offered, decision = resolver("jarvis", TOOLS)
    assert decision.offered == ("echo", "file_search", "desktop_run")
    offered, decision = resolver("friday", TOOLS)
    assert decision.offered == ("echo",)  # the agent's own list narrows the owner's posture

    def boom():
        raise RuntimeError("no principal store")

    failing = tp.ToolProfileResolver(settings=DEFAULTS, principal=boom, origin=boom)
    _offered, decision = failing("jarvis", TOOLS)
    assert (decision.surface, decision.principal) == ("inbound", "guest")


# ── the snapshot over the live registry ──────────────────────────────────────

def test_postures_over_the_live_registry_match_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    resolved = _resolved(_live_registry(str(tmp_path)))
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert resolved == snap, (
        "The tool profiles over the live registry changed. If intended, regenerate "
        "tests/_snapshots/tool_profiles.json with `python tests/test_tool_profiles.py --update`."
    )
    gated = {t["name"] for t in _live_registry(str(tmp_path)) if t["gated"]}
    assert gated == {"desktop_run", "terminal_run", "osint_enrich", "file_write", "file_delete"}
    for key, names in snap["postures"].items():
        if key != "operator/owner":
            assert not gated & set(names), f"{key} offers actuation by default: {names}"
    assert snap["postures"]["inbound/guest"] == ["echo", "time"]


# ── the runtime ──────────────────────────────────────────────────────────────

class _Backend:
    supports_tools = True

    def __init__(self, script):
        self.script = list(script)
        self.tools_seen: list[list[str]] = []

    async def generate_tool_turn(self, **kwargs):
        self.tools_seen.append([t.name for t in kwargs["tools"]])
        if self.script:
            name, args = self.script.pop(0)
            return ToolTurn(
                tool_calls=(ToolCall(id=f"c{len(self.tools_seen)}", name=name,
                                     raw_arguments=json.dumps(args), arguments=args),),
                finish_reason="tool_calls",
            )
        return ToolTurn(content="done", finish_reason="stop")


def _server(log):
    server = ToolRPCServer(enqueue=lambda *a, **k: 1)

    async def lookup(args):
        log.append(("lookup", dict(args)))
        return {"found": True}

    async def actuate(args):
        log.append(("actuate", dict(args)))
        return {"did": True}

    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    server.register_tool("lookup", lookup, description="Look.", input_schema=schema)
    server.register_tool("actuate", actuate, gated=True, description="Act.", input_schema=schema)
    return server


def _resolver(posture, guest=("lookup",)):
    settings = lambda key, default: list(guest) if key == "llm.guest_tools" else default  # noqa: E731
    principal = {
        ("operator", "owner"): Principal(channel="web", admin=True),
        ("inbound", "guest"): Principal(channel="telegram", admin=False),
        ("internal", "system"): Principal(),
    }[posture]
    return tp.ToolProfileResolver(settings=settings, principal=lambda: principal,
                                  origin=lambda: "generated")


async def _run(runtime, backend, events):
    return await runtime.run(agent_id="nerva", backend=backend, model="m", prompt="p",
                             system="s", max_tokens=64, temperature=0.1, event_sink=events.append)


@pytest.mark.asyncio
async def test_runtime_offers_only_the_profile_and_refuses_the_rest():
    log, events = [], []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True,
                               tool_profile=_resolver(("inbound", "guest")))
    backend = _Backend([("actuate", {"q": "x"}), ("lookup", {"q": "x"})])
    assert await _run(runtime, backend, events) == "done"
    assert backend.tools_seen[0] == ["lookup"]  # actuate was never on the table
    assert log == [("lookup", {"q": "x"})]
    profile = [e for e in events if e["event"] == "tool_profile"]
    assert profile == [{
        "event": "tool_profile", "agent_id": "nerva", "surface": "inbound",
        "principal": "guest", "offered": 1, "withheld": ["actuate"],
    }]
    refused = [e for e in events if e["event"] == "tool_failed"]
    assert refused and refused[0]["tool"] == "actuate" and refused[0]["status"] == "tool_not_allowed"


@pytest.mark.asyncio
async def test_owner_at_the_hud_keeps_everything():
    log, events = [], []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True,
                               tool_profile=_resolver(("operator", "owner")))
    backend = _Backend([("lookup", {"q": "x"})])
    assert await _run(runtime, backend, events) == "done"
    assert backend.tools_seen[0] == ["actuate", "lookup"]
    assert events[0]["withheld"] == []


@pytest.mark.asyncio
async def test_can_run_is_false_when_the_profile_offers_nothing():
    log, events = [], []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True,
                               tool_profile=_resolver(("inbound", "guest"), guest=()))
    backend = _Backend([])
    assert runtime.can_run(backend) is True            # no agent named: the old check
    assert runtime.can_run(backend, agent_id="nerva") is False
    # Invoked anyway, the loop never calls the provider with an empty tool list.
    assert await _run(runtime, backend, events) == _NO_TOOLS_REPLY
    assert backend.tools_seen == [] and events[-1]["offered"] == 0


@pytest.mark.asyncio
async def test_a_resolver_error_offers_nothing():
    def broken(agent_id, tools):
        raise RuntimeError("profile store down")

    log, events = [], []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, tool_profile=broken)
    backend = _Backend([("lookup", {"q": "x"})])
    assert runtime.can_run(backend, agent_id="nerva") is False
    assert await _run(runtime, backend, events) == _NO_TOOLS_REPLY
    assert log == []


def test_no_profile_means_the_old_behaviour():
    runtime = AgentToolRuntime(_server([]), enabled=lambda: True)
    assert runtime.can_run(_Backend([]), agent_id="nerva") is True


# ── the wiring ───────────────────────────────────────────────────────────────

def test_coordinator_resolves_from_the_turn_principal_and_the_agent_config(tmp_path, monkeypatch):
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    orch = SimpleNamespace(
        agents={},
        config=SimpleNamespace(agents={"friday": SimpleNamespace(tools=["file_*", "time"])}),
    )
    runtime = AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    registry = orch.tool_rpc.tools()
    all_names = [t["name"] for t in registry]

    token = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        offered, decision = runtime._profiled("jarvis", registry)
        assert [t["name"] for t in offered] == all_names
        assert (decision.surface, decision.principal) == ("operator", "owner")
        offered, decision = runtime._profiled("friday", registry)
        # The agent's own list narrows the owner's posture — which includes the gated file
        # tools, so `file_*` keeps them; a guest posture would have dropped them first.
        assert [t["name"] for t in offered] == [
            "file_delete", "file_list", "file_read", "file_search", "file_write", "time",
        ]
    finally:
        reset_turn_principal(token)

    token = bind_turn_principal(Principal(channel="telegram", admin=False))
    try:
        offered, decision = runtime._profiled("jarvis", registry)
        assert [t["name"] for t in offered] == ["echo", "time"]
        assert "desktop_run" in decision.withheld and "session_search" in decision.withheld
    finally:
        reset_turn_principal(token)

    # No principal bound at all: an unattended turn, read tools only.
    offered, decision = runtime._profiled("jarvis", registry)
    assert (decision.surface, decision.principal) == ("internal", "system")
    assert not any(t["gated"] for t in offered) and "file_search" in decision.offered


if __name__ == "__main__":
    if "--update" in sys.argv:
        with tempfile.TemporaryDirectory() as root:
            resolved = _resolved(_live_registry(root))
        SNAPSHOT.write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {SNAPSHOT}")
    else:
        print("usage: python tests/test_tool_profiles.py --update")
