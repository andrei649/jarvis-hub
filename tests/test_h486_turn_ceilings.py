"""H486 — default per-turn ceilings on web searches and sub-agent spawns (Hermes: 50).

The generic `llm.tool_loop_per_tool_cap` ships off (0). These two ship ON at 50: a turn
that runs `web_search` past its ceiling is refused with the usual cap notice. The spawn
ceiling is a DORMANT guard: it refuses a spawn made inside a bound tool-loop turn, but no
model-facing spawn tool exists and the HTTP routes run outside any turn. When the generic
cap is also set, the stricter one applies.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.core import agent_runtime, settings_db
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.subagents import SubAgentManager
from agents.core.tool_rpc import ToolRPCServer, bind_tool_turn, reset_tool_turn
from tests.test_subagent_steer import harness  # noqa: F401
from tests.test_web_tools_wiring import _coordinator

WEB, SPAWN = "tool_loop_web_search_cap", "tool_loop_subagent_spawn_cap"


# ── the settings ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", [WEB, SPAWN])
def test_the_ceilings_are_seeded_on_at_fifty(key):
    rows = [row for row in settings_db.DEFAULTS if (row["category"], row["key"]) == ("llm", key)]
    assert len(rows) == 1
    assert rows[0]["value"] == 50 and rows[0]["kind"] == "number"
    assert agent_runtime.DEFAULT_TURN_CEILING == 50


@pytest.mark.parametrize("key", [WEB, SPAWN])
def test_the_ceilings_accept_zero_to_ten_thousand_whole_numbers(key):
    for ok in (0, 1, 50, 10_000):
        assert settings_db.validate_category("llm", {key: ok}) == []
    for bad in (-1, 10_001, 1.5, True, "50", None):
        assert settings_db.validate_category("llm", {key: bad}), bad


def test_safe_mode_does_not_list_the_ceilings_as_loosening():
    """The tool loop is off in safe mode; the ceilings sit with the other loop numbers."""
    from agents.core import safe_mode

    assert f"llm.{WEB}" not in safe_mode.FORCED_SETTINGS
    assert f"llm.{SPAWN}" not in safe_mode.FORCED_SETTINGS


# ── the tool loop ───────────────────────────────────────────────────────────────

class _Backend:
    supports_tools = True

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append([dict(m) for m in kwargs["messages"]])
        if self.script:
            step = self.script.pop(0)
            batch = step if isinstance(step, list) else [step]     # one turn may fan out
            return ToolTurn(
                tool_calls=tuple(
                    ToolCall(id=f"call-{len(self.calls)}-{i}", name=name,
                             raw_arguments=json.dumps(args), arguments=args)
                    for i, (name, args) in enumerate(batch)),
                finish_reason="tool_calls",
            )
        return ToolTurn(content="done", finish_reason="stop")


def _server(log):
    server = ToolRPCServer()

    async def search(args):
        log.append(("web_search", dict(args)))
        return {"rows": [{"title": args.get("q")}]}

    async def small(args):
        log.append(("small", dict(args)))
        return {"n": args.get("n")}

    schema = {"type": "object", "properties": {"q": {"type": "string"}, "n": {"type": "integer"}}}
    server.register_tool("web_search", search, description="search", input_schema=schema)
    server.register_tool("small", small, description="small", input_schema=schema)
    return server


async def _run(runtime, backend, events=None):
    return await runtime.run(agent_id="nerva", backend=backend, model="m", prompt="p", system="s",
                             max_tokens=64, temperature=0.1,
                             event_sink=events.append if events is not None else None)


def _searches(n):
    return [("web_search", {"q": f"q{i}"}) for i in range(n)]


def _search_turns(n, per=8):
    """`n` searches as model turns of `per` calls each (the loop's 32-turn safety limit
    is below 51 single-call turns)."""
    calls = _searches(n)
    return [calls[i:i + per] for i in range(0, n, per)]


@pytest.mark.asyncio
async def test_web_search_past_its_ceiling_is_refused_and_other_tools_are_not():
    log, events = [], []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, tool_turn_caps={"web_search": 2},
                               max_iterations=lambda: 12)
    backend = _Backend(_searches(3) + [("small", {"n": i}) for i in range(4)])
    assert "limit (2)" in await _run(runtime, backend, events)
    assert [name for name, _ in log] == ["web_search", "web_search"]
    assert [e["status"] for e in events if e["event"] == "tool_failed"] == ["tool_cap_reached"]
    log.clear()
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, tool_turn_caps={"web_search": 2},
                               max_iterations=lambda: 12)
    backend = _Backend([("small", {"n": i}) for i in range(5)])
    assert await _run(runtime, backend) == "done" and len(log) == 5


@pytest.mark.asyncio
async def test_the_ceiling_is_reread_each_turn_and_an_unreadable_value_is_the_shipped_fifty():
    log = []
    cap = {"web_search": 3}
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, tool_turn_caps=lambda: dict(cap),
                               max_iterations=lambda: 64)
    assert "limit (3)" in await _run(runtime, _Backend(_searches(4)))
    assert len(log) == 3
    cap["web_search"] = "bad"
    log.clear()
    assert await _run(runtime, _Backend(_search_turns(50))) == "done" and len(log) == 50
    log.clear()
    assert "limit (50)" in await _run(runtime, _Backend(_search_turns(51))) and len(log) == 50
    cap["web_search"] = 0                                         # 0 = this ceiling off
    log.clear()
    assert await _run(runtime, _Backend(_search_turns(51))) == "done" and len(log) == 51


@pytest.mark.asyncio
@pytest.mark.parametrize("generic,specific,expected_runs,expected_limit", [
    (1, 3, 1, 1),      # the generic cap is stricter
    (5, 2, 2, 2),      # the ceiling is stricter
    (2, 0, 2, 2),      # the ceiling off: the generic cap applies
    (0, 0, 6, None),   # both off: no cap
])
async def test_the_stricter_of_generic_cap_and_ceiling_applies(generic, specific, expected_runs,
                                                                expected_limit):
    log = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, per_tool_limit=generic,
                               tool_turn_caps={"web_search": specific}, max_iterations=lambda: 12)
    reply = await _run(runtime, _Backend(_searches(6)))
    assert len(log) == expected_runs
    if expected_limit is None:
        assert reply == "done"
    else:
        assert f"limit ({expected_limit})" in reply


def test_the_coordinator_binds_web_search_to_its_setting(monkeypatch):
    captured = {}

    def runtime_factory(_server, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(agent_runtime, "AgentToolRuntime", runtime_factory)
    coordinator = _coordinator({})
    selected = {}
    coordinator._orch.get_setting = lambda key, default=None: selected.get(key, default)
    coordinator._wire_agent_tool_runtime()
    read = captured["tool_turn_caps"]
    assert read() == {"web_search": 50}
    selected[f"llm.{WEB}"] = 7
    assert read() == {"web_search": 7}


# ── the spawn surface ───────────────────────────────────────────────────────────

async def _runner(task, session_id, agent):
    return {"output": task, "session_id": session_id}


def _manager(**kw):
    kw.setdefault("cost_probe", lambda: {})
    kw.setdefault("persist", False)
    return SubAgentManager(runner=_runner, **kw)


@pytest.mark.asyncio
async def test_spawns_in_one_tool_loop_turn_stop_at_the_ceiling():
    manager = _manager(turn_cap=2)
    token = bind_tool_turn("turn-a")
    try:
        assert (await manager.spawn("a"))["ok"] and (await manager.spawn("b"))["ok"]
        refused = await manager.spawn("c")
        assert refused == {"ok": False, "reason": "turn_spawn_cap", "spawned": 2, "cap": 2}
    finally:
        reset_tool_turn(token)
    token = bind_tool_turn("turn-b")                 # another turn starts from zero
    try:
        assert (await manager.spawn("d"))["ok"]
    finally:
        reset_tool_turn(token)
    assert (await manager.spawn("outside a turn"))["ok"]   # the per-boot budget covers these
    assert [r["status"] for r in manager.list()] == ["done"] * 4


@pytest.mark.asyncio
async def test_the_spawn_ceiling_is_reread_and_zero_or_unreadable_behaves_like_the_setting():
    cap = {"value": 1}
    manager = _manager(turn_cap=lambda: cap["value"])
    token = bind_tool_turn("turn-a")
    try:
        assert (await manager.spawn("a"))["ok"]
        assert (await manager.spawn("b"))["reason"] == "turn_spawn_cap"
        cap["value"] = 0                                        # off
        assert (await manager.spawn("c"))["ok"]
        cap["value"] = "bad"                                    # unreadable: the shipped 50
        assert (await manager.spawn("d"))["ok"]
        assert manager.stats()["turn_cap"] == {"cap": 50, "spawned_this_turn": 3}
    finally:
        reset_tool_turn(token)


def test_the_coordinator_binds_the_spawn_ceiling_to_its_setting(monkeypatch):
    from agents.core import subagents

    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(list=lambda: [], stats=lambda: {})

    monkeypatch.setattr(subagents, "SubAgentManager", factory)
    coordinator = _coordinator({})
    selected = {}
    coordinator._orch.get_setting = lambda key, default=None: selected.get(key, default)
    coordinator.build_executor()
    read = captured["turn_cap"]
    assert read() == 50
    selected[f"llm.{SPAWN}"] = 3
    assert read() == 3


@pytest.mark.asyncio
async def test_the_http_spawn_routes_run_outside_a_turn_so_the_ceiling_is_dormant_there(harness):
    """Pins the honest scope: no tool-loop turn is bound for a request handler, so even a
    ceiling of 1 refuses neither /spawn nor /batch (the per-boot budget governs them)."""
    manager, _started, client = harness
    manager._turn_cap = 1
    async with client:
        for task in ("one", "two", "three"):
            reply = await client.post("/api/subagents/spawn", json={"task": task})
            assert reply.status_code == 200 and reply.json()["ok"] is True
        batch = await client.post("/api/subagents/batch", json={"tasks": [{"task": "a"}, {"task": "b"}]})
        assert batch.status_code == 200
        assert all(child.get("reason") != "turn_spawn_cap" for child in batch.json()["children"])
    assert [r["status"] for r in manager.list()] == ["done"] * 5
