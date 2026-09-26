"""H296 — a tool tells the model what this install can do, not only what the code accepts.

Every ToolRPC tool advertised one static schema, written when the code was: the model
was told ``terminal_run`` takes any ``target`` string (and learned the names from a
refusal), ``desktop_run`` any ``action`` string, ``speak`` any device or room. Hermes
has ``dynamic_schema_overrides``: a per-tool hook that rewrites the schema from live
config. Nerva's is ``register_tool(schema_overrides=...)``: a zero-argument hook
merged over the static schema every time the tool list is built. It narrows what is
advertised (description, per-property keys of properties already declared, which of
them are required) and never invents an argument; a hook that raises or answers
something malformed is logged once and the static schema is advertised instead. A
shape that moves mid-session is picked up at the compaction boundary (H672) and
named there ("tool schemas moved"), exactly like an added or removed tool.

The override only changes what the model is told. Each handler still checks every
call itself, so an enum is advice to the model, not the gate.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import agent_runtime, tool_rpc  # noqa: E402
from agents.core.agent_runtime import AgentToolRuntime  # noqa: E402
from agents.core.autonomy_coordinator import (  # noqa: E402
    _DESKTOP_RUN_SCHEMA,
    AutonomyCoordinator,
    _desktop_run_overrides,
)
from agents.core.desktop_operator import _DESKTOP_ARG_RULES  # noqa: E402
from agents.core.environments.targets import TargetRegistry, TerminalTarget  # noqa: E402
from agents.core.llm.tool_protocol import ToolCall, ToolTurn  # noqa: E402
from agents.core.media_director import (  # noqa: E402
    DeviceRegistry,
    MediaDevice,
    MediaDirector,
    SessionBoard,
)
from agents.core.session_refresh import boundary_note, refresh_prompt, refresh_tools  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer, advertised_schema  # noqa: E402
from agents.core.voice import speak_tool  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "maxLength": 64},
        "mode": {"type": "string"},
    },
    "required": ["target"],
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def _fresh_warnings():
    tool_rpc._OVERRIDE_WARNED.clear()
    yield
    tool_rpc._OVERRIDE_WARNED.clear()


async def _noop(args):
    return {"ok": True}


def _server(hook, *, description="Do one thing.", schema=None):
    server = ToolRPCServer()
    server.register_tool("thing", _noop, description=description,
                         input_schema=json.loads(json.dumps(schema or SCHEMA)), schema_overrides=hook)
    return server


def _row(server, name="thing"):
    return next(row for row in server.tools() if row["name"] == name)


# ── the hook and the merge ───────────────────────────────────────────────────────

@pytest.mark.parametrize("hook", ["not callable", 3, {"properties": {}}])
def test_a_hook_that_is_not_callable_is_refused_at_registration(hook):
    with pytest.raises(ValueError, match="schema_overrides"):
        _server(hook)


def test_an_override_narrows_a_declared_argument_and_rewrites_the_description():
    server = _server(lambda: {
        "description": "Do one thing on a registered target.",
        "properties": {"target": {"enum": ["a", "b"]}},
        "required": ["target", "mode"],
    })
    row = _row(server)
    assert row["description"] == "Do one thing on a registered target."
    # Merged over the declared keys: the static bounds stay, the enum is added.
    assert row["input_schema"]["properties"]["target"] == {"type": "string", "maxLength": 64, "enum": ["a", "b"]}
    assert row["input_schema"]["properties"]["mode"] == {"type": "string"}
    assert row["input_schema"]["required"] == ["target", "mode"]
    assert row["input_schema"]["additionalProperties"] is False


def test_the_static_schema_is_never_mutated_by_an_override():
    hook_answer = {"properties": {"target": {"enum": ["a"]}}}
    server = _server(lambda: hook_answer)
    first = _row(server)
    first["input_schema"]["properties"]["target"]["enum"].append("smuggled")
    server._tools["thing"]["schema_overrides"] = None
    assert _row(server)["input_schema"] == SCHEMA
    assert hook_answer == {"properties": {"target": {"enum": ["a"]}}}


def test_a_row_is_a_copy_so_a_caller_cannot_mutate_the_registered_schema():
    server = _server(None)
    _row(server)["input_schema"]["properties"]["target"]["maxLength"] = 10**6
    assert _row(server)["input_schema"] == SCHEMA


@pytest.mark.parametrize("answer", [None, {}])
def test_nothing_to_change_advertises_the_static_schema(answer):
    row = _row(_server(lambda: answer))
    assert row["description"] == "Do one thing." and row["input_schema"] == SCHEMA


def test_a_tool_without_a_hook_is_advertised_as_registered():
    row = _row(_server(None))
    assert row["description"] == "Do one thing." and row["input_schema"] == SCHEMA


def test_the_hook_is_asked_every_time_the_tool_list_is_built():
    calls = []
    live = {"names": ["a"]}

    def hook():
        calls.append(1)
        return {"properties": {"target": {"enum": list(live["names"])}}}

    server = _server(hook)
    assert _row(server)["input_schema"]["properties"]["target"]["enum"] == ["a"]
    live["names"] = ["a", "b"]
    assert _row(server)["input_schema"]["properties"]["target"]["enum"] == ["a", "b"]
    assert len(calls) == 2


def _boom():
    raise RuntimeError("registry unreadable")


class _Unserialisable:
    pass


@pytest.mark.parametrize("hook", [
    _boom,
    lambda: ["not", "a", "mapping"],
    lambda: {"examples": []},                                             # unknown key
    lambda: {"examples": [], "description": "live"},                     # beside a known one
    lambda: {"properties": {"target": [["enum", ["x"]]]}},               # pairs, not a mapping
    lambda: {"required": ("target", "mode")},                            # a tuple, not a list
    lambda: {"properties": {"host": {"enum": ["x"]}}},                    # invents an argument
    lambda: {"properties": {"target": "narrow"}},                         # not a mapping
    lambda: {"properties": ["target"]},
    lambda: {"required": ["host"]},                                       # an undeclared name
    lambda: {"required": "target"},
    lambda: {"description": ""},
    lambda: {"description": "   "},
    lambda: {"description": 7},
    lambda: {"description": "x" * (tool_rpc.MAX_OVERRIDE_DESCRIPTION + 1)},
    lambda: {"properties": {"target": {"enum": {"a", "b"}}}},             # a set is not JSON
    lambda: {"properties": {"target": {"default": _Unserialisable()}}},
])
def test_a_hook_that_fails_or_answers_badly_leaves_the_static_schema(hook):
    row = _row(_server(hook))
    assert row["description"] == "Do one thing." and row["input_schema"] == SCHEMA


def test_the_longest_allowed_description_is_advertised():
    text = "y" * tool_rpc.MAX_OVERRIDE_DESCRIPTION
    assert _row(_server(lambda: {"description": text}))["description"] == text


def test_a_failing_hook_warns_once_and_again_after_it_recovered(caplog):
    state = {"fail": True}

    def hook():
        if state["fail"]:
            raise RuntimeError("secret-looking detail that is not logged")
        return {"properties": {"target": {"enum": ["a"]}}}

    server = _server(hook)
    with caplog.at_level(logging.WARNING, logger="jarvis.tool_rpc"):
        server.tools()
        server.tools()
        warned = [r for r in caplog.records if "live schema" in r.getMessage()]
        assert len(warned) == 1
        assert "thing" in warned[0].getMessage() and "RuntimeError" in warned[0].getMessage()
        assert "secret-looking" not in warned[0].getMessage()
        state["fail"] = False
        assert _row(server)["input_schema"]["properties"]["target"]["enum"] == ["a"]
        state["fail"] = True
        server.tools()
    assert len([r for r in caplog.records if "live schema" in r.getMessage()]) == 2


def test_advertised_schema_is_the_same_merge_outside_a_server():
    description, schema = advertised_schema("x", "static", SCHEMA, lambda: {"description": "live"})
    assert (description, schema) == ("live", SCHEMA)
    assert schema is not SCHEMA


def test_the_capability_registry_projection_carries_the_live_schema():
    """Registry mode (``_registry_metadata``) offers a record's ``inputs`` and
    ``description``: the records are built from ``tools()``, so the override reaches them."""
    from types import SimpleNamespace

    from agents.core.observability import capability_registry

    server = ToolRPCServer()
    server.register_tool("thing", _noop, description="Do one thing.", input_schema=json.loads(json.dumps(SCHEMA)),
                         capability_id="tool:thing",
                         schema_overrides=lambda: {"description": "Live.", "properties": {"target": {"enum": ["a"]}}})
    record = next(r for r in capability_registry._tool_records(SimpleNamespace(tool_rpc=server))
                  if r.id == "tool:thing")
    assert record.description == "Live." and record.inputs["properties"]["target"]["enum"] == ["a"]


# ── the session boundary picks the new shape up (H672) ───────────────────────────

def _tool(name, **schema):
    return {"name": name, "description": "d", "input_schema": schema or {"type": "object"}}


def test_a_moved_schema_is_a_rebuild_named_at_the_boundary():
    before = [_tool("terminal_run", enum=["a"]), _tool("file_read")]
    after = [_tool("terminal_run", enum=["a", "b"]), _tool("file_read")]
    out = refresh_tools(lambda: after, before)
    assert out.reshaped == ("terminal_run",) and out.added == () and out.removed == ()
    assert out.changed and out.reason == "rebuilt"
    assert out.tools[0]["input_schema"]["enum"] == ["a", "b"]
    note = boundary_note(refresh_prompt(lambda: "p", "p"), out)
    assert note == "tool schemas moved: terminal_run"


def test_a_moved_description_is_a_reshape_too():
    before = [_tool("speak")]
    after = [{**_tool("speak"), "description": "No speaker can announce yet."}]
    assert refresh_tools(lambda: after, before).reshaped == ("speak",)


def test_the_same_shape_in_another_key_order_is_not_a_reshape():
    before = [{"name": "t", "description": "d", "input_schema": {"type": "object", "required": ["a"]}}]
    after = [{"input_schema": {"required": ["a"], "type": "object"}, "description": "d", "name": "t"}]
    out = refresh_tools(lambda: after, before)
    assert out.reshaped == () and not out.changed and out.reason == "identical"


def test_an_added_tool_is_not_also_a_reshape():
    out = refresh_tools(lambda: [_tool("a"), _tool("b", enum=[1])], [_tool("a")])
    assert out.added == ("b",) and out.reshaped == ()


class _Backend:
    """A scripted model: ``tool_calls`` blob calls, then ``done``. It records the
    ``target`` enum it was offered on every turn; ``hooks`` run while a turn is
    'generated' — the moment a target is registered mid-loop."""

    supports_tools = True

    def __init__(self, tool_calls, hooks=None):
        self.remaining = tool_calls
        self.hooks = hooks or {}
        self.offers: list[list] = []

    async def generate_tool_turn(self, **kwargs):
        shell = next(tool for tool in kwargs["tools"] if tool.name == "shell")
        self.offers.append(list(shell.input_schema["properties"]["target"].get("enum") or []))
        hook = self.hooks.get(len(self.offers))
        if hook is not None:
            hook()
        if self.remaining > 0:
            self.remaining -= 1
            n = len(self.offers)
            return ToolTurn(tool_calls=(ToolCall(id=f"call-{n}", name="blob", raw_arguments=json.dumps({"n": n}),
                                                   arguments={"n": n}),),
                            finish_reason="tool_calls")
        return ToolTurn(content="done", finish_reason="stop")


async def test_a_target_registered_mid_loop_is_offered_after_the_fold(monkeypatch):
    monkeypatch.setattr(agent_runtime, "estimate_messages",
                        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4)
    live = {"targets": ["pi-house"]}
    server = ToolRPCServer()

    async def blob(args):
        return {"blob": "y" * 4_000, "n": args.get("n")}

    server.register_tool("blob", blob, description="Return a large payload.",
                         input_schema={"type": "object", "properties": {"n": {"type": "integer"}}})
    server.register_tool("shell", _noop, description="Run a command.", input_schema=json.loads(json.dumps(SCHEMA)),
                         schema_overrides=lambda: {"properties": {"target": {"enum": list(live["targets"])}}})
    runtime = AgentToolRuntime(server, enabled=lambda: True, context_budget_tokens=lambda: 2_400,
                               compaction_keep_recent=1)
    events: list[dict] = []
    backend = _Backend(3, hooks={2: lambda: live["targets"].append("sandbox")})

    answer = await runtime.run(agent_id="nerva", backend=backend, model="local-model", prompt="go",
                               system="You are Nerva.", max_tokens=256, temperature=0.2,
                               event_sink=events.append)

    assert answer == "done"
    assert backend.offers[0] == ["pi-house"]
    assert backend.offers[-1] == ["pi-house", "sandbox"]
    refreshed = [e for e in events if e["event"] == "tool_offer_refreshed"]
    assert refreshed and refreshed[0]["reshaped"] == ["shell"] and refreshed[0]["reason"] == "rebuilt"
    assert refreshed[0]["added"] == [] and refreshed[0]["removed"] == []


# ── terminal_run: the targets actually registered ────────────────────────────────

def _target(name, **overrides):
    values = {"name": name, "backend": "docker", "enabled": True, "allowed_agents": frozenset({"jarvis"}),
              "capabilities": frozenset({"terminal.exec"}), "approval_required": frozenset({"terminal.exec"})}
    values.update(overrides)
    return TerminalTarget(**values)


def _coordinator(targets):
    coordinator = AutonomyCoordinator(object())
    coordinator._targets = TargetRegistry(targets)
    return coordinator


def test_terminal_run_says_it_is_switched_off(monkeypatch):
    monkeypatch.delenv("JARVIS_TERMINAL_TARGETS", raising=False)
    answer = _coordinator([_target("pi-house")])._terminal_run_overrides()
    assert set(answer) == {"description"}
    assert "switched off" in answer["description"] and "JARVIS_TERMINAL_TARGETS" in answer["description"]


def test_terminal_run_says_when_no_target_is_registered(monkeypatch):
    monkeypatch.setenv("JARVIS_TERMINAL_TARGETS", "1")
    answer = _coordinator([])._terminal_run_overrides()
    assert set(answer) == {"description"} and "No target is registered" in answer["description"]


def test_terminal_run_names_the_registered_targets_sorted_and_bounded(monkeypatch):
    monkeypatch.setenv("JARVIS_TERMINAL_TARGETS", "1")
    assert _coordinator([_target("zeta"), _target("alpha")])._terminal_run_overrides() == {
        "properties": {"target": {"enum": ["alpha", "zeta"]}}}
    many = _coordinator([_target(f"t{i:03d}") for i in range(70)])._terminal_run_overrides()
    assert many["properties"]["target"]["enum"] == [f"t{i:03d}" for i in range(64)]


def test_the_target_registry_lists_its_names_sorted():
    assert TargetRegistry([_target("b"), _target("a")]).names() == ["a", "b"]
    assert TargetRegistry().names() == []


# ── desktop_run: the actions its validator accepts ───────────────────────────────

def test_desktop_run_advertises_the_validators_actions_without_touching_the_static_schema():
    before = json.dumps(_DESKTOP_RUN_SCHEMA, sort_keys=True)
    answer = _desktop_run_overrides()
    action = answer["properties"]["steps"]["items"]["properties"]["action"]
    assert action == {"type": "string", "maxLength": 64, "enum": sorted(_DESKTOP_ARG_RULES)}
    assert json.dumps(_DESKTOP_RUN_SCHEMA, sort_keys=True) == before
    description, schema = advertised_schema("desktop_run", "d", _DESKTOP_RUN_SCHEMA, _desktop_run_overrides)
    assert schema["properties"]["steps"]["items"]["properties"]["action"]["enum"] == sorted(_DESKTOP_ARG_RULES)
    assert schema["properties"]["steps"]["maxItems"] == 100


# ── speak: the devices and rooms that can announce ───────────────────────────────

def _director(tmp_path, devices, presence_room=""):
    registry = DeviceRegistry(path=None)
    for device in devices:
        registry.register(device)
    return MediaDirector(registry=registry, sessions=SessionBoard(path=None), drivers={},
                         local_roots=(tmp_path,), presence=lambda: None, presence_room=presence_room)


def _device(id_, room, supports=("announce",), room_default=False):
    return MediaDevice(id=id_, name=id_, kind="speaker", room=room, supports=supports, room_default=room_default)


def _speak(director):
    return speak_tool.SpeakTool(director=lambda: director, approved_task=lambda: None, authorizer=None)


def test_speak_names_announce_devices_rooms_and_presence(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    director = _director(tmp_path, [
        _device("speaker-kitchen", "kitchen", room_default=True),
        _device("tv-living", "living", supports=("play",)),
    ], presence_room="kitchen")
    assert _speak(director).schema_overrides() == {
        "properties": {"target": {"enum": ["speaker-kitchen", "kitchen", speak_tool.PRESENCE_TARGET]}}}


def test_speak_leaves_out_an_ambiguous_room_and_an_unresolvable_presence(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    director = _director(tmp_path, [
        _device("a", "hall", room_default=True),
        _device("b", "hall", room_default=True),
        _device("c", "office"),
    ], presence_room="garage")
    enum = _speak(director).schema_overrides()["properties"]["target"]["enum"]
    assert enum == ["a", "b", "c", "office"]


def test_speak_lists_rooms_in_a_stable_order(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    rooms = [f"room-{c}" for c in "qwertyuiop"]
    director = _director(tmp_path, [_device(f"s-{room}", room, supports=("announce", "play"))
                                    for room in reversed(rooms)])
    enum = _speak(director).schema_overrides()["properties"]["target"]["enum"]
    assert enum == sorted(f"s-{room}" for room in rooms) + sorted(rooms)


def test_speak_does_not_list_a_room_named_like_a_device_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    director = _director(tmp_path, [_device("den", "den")])
    assert _speak(director).schema_overrides()["properties"]["target"]["enum"] == ["den"]


def test_speak_bounds_the_advertised_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    director = _director(tmp_path, [_device(f"s{i:03d}", "") for i in range(80)])
    enum = _speak(director).schema_overrides()["properties"]["target"]["enum"]
    assert enum == [f"s{i:03d}" for i in range(speak_tool.MAX_ADVERTISED_TARGETS)]


def test_speak_with_no_announce_speaker_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    director = _director(tmp_path, [_device("tv", "living", supports=("play",))], presence_room="living")
    answer = _speak(director).schema_overrides()
    assert set(answer) == {"description"}
    assert answer["description"].startswith(speak_tool.DESCRIPTION)
    assert "No speaker can announce yet" in answer["description"]


@pytest.mark.parametrize("on,director", [(False, "real"), (True, None), (True, "raises")])
def test_speak_without_a_media_director_says_so(tmp_path, monkeypatch, on, director):
    if on:
        monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    else:
        monkeypatch.delenv("JARVIS_MEDIA_DIRECTOR", raising=False)
    real = _director(tmp_path, [_device("s", "kitchen")])

    def get():
        if director == "raises":
            raise RuntimeError("down")
        return real if director == "real" else None

    tool = speak_tool.SpeakTool(director=get, approved_task=lambda: None, authorizer=None)
    answer = tool.schema_overrides()
    assert set(answer) == {"description"} and "not available right now" in answer["description"]


def test_the_registered_speak_tool_advertises_the_live_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    director = _director(tmp_path, [_device("speaker-kitchen", "kitchen", room_default=True)])
    server = ToolRPCServer()
    assert speak_tool.register_speak_tool(server, director=lambda: director, approved_task=lambda: None,
                                          authorizer=None, enqueue=None, enabled=True) == ["speak"]
    target = _row(server, "speak")["input_schema"]["properties"]["target"]
    assert target["enum"] == ["speaker-kitchen", "kitchen"]
    assert target["maxLength"] == speak_tool.INPUT_SCHEMA["properties"]["target"]["maxLength"]
    director.registry.register(_device("speaker-hall", "hall"))
    assert _row(server, "speak")["input_schema"]["properties"]["target"]["enum"] == [
        "speaker-hall", "speaker-kitchen", "hall", "kitchen"]
