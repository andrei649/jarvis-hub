"""Hermes absorption 3a — the tool loop notices when the model is going in circles.

A model that calls the same tool with the same arguments again and again is looping, not
working. The iteration limit ended it eventually — after burning every turn and telling the
model nothing. Now the third identical call is refused with the reason, so the model can
change course, and a fourth ends the turn with a named reply and an event.
"""

from __future__ import annotations

import json

import pytest

from agents.core.agent_runtime import _FAILURE_REPLY, _REPEAT_REPLY, AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer


class _Backend:
    """Emits one tool call per turn from a script of argument dicts, then answers."""

    supports_tools = True

    def __init__(self, script: list[tuple[str, dict]]) -> None:
        self.script = list(script)
        self.calls: list[list[dict]] = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append([dict(message) for message in kwargs["messages"]])
        if self.script:
            name, args = self.script.pop(0)
            return ToolTurn(
                tool_calls=(
                    ToolCall(
                        id=f"call-{len(self.calls)}",
                        name=name,
                        raw_arguments=json.dumps(args),
                        arguments=args,
                    ),
                ),
                finish_reason="tool_calls",
            )
        return ToolTurn(content="done", finish_reason="stop")


def _server(log: list[dict]) -> ToolRPCServer:
    server = ToolRPCServer()

    async def lookup(args):
        log.append(dict(args))
        return {"found": args.get("q")}

    async def ping(args):
        log.append({"ping": True})
        return {"pong": True}

    schema = {"type": "object", "properties": {"q": {"type": "string"}, "k": {"type": "integer"}}}
    server.register_tool("lookup", lookup, description="Look up.", input_schema=schema)
    server.register_tool("ping", ping, description="Ping.", input_schema={"type": "object", "properties": {}})
    return server


async def _run(runtime, backend, events=None):
    return await runtime.run(
        agent_id="nerva",
        backend=backend,
        model="local-model",
        prompt="find it",
        system="You are Nerva.",
        max_tokens=256,
        temperature=0.2,
        event_sink=events.append if events is not None else None,
    )


def _tool_results(backend):
    """The tool messages the model saw on its last turn, decoded."""
    return [json.loads(m["content"]) for m in backend.calls[-1] if m.get("role") == "tool"]


@pytest.mark.asyncio
async def test_the_third_identical_result_gets_a_notice_without_refusal():
    log: list[dict] = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True)
    backend = _Backend([("lookup", {"q": "x"})] * 3)
    events: list[dict] = []
    reply = await _run(runtime, backend, events)
    assert reply == "done"
    assert log == [{"q": "x"}] * 3
    results = _tool_results(backend)
    assert results[0]["result"] == {"found": "x"} and results[1]["result"] == {"found": "x"}
    assert "identical_call" in results[2]["stall_notice"]["tracks"]
    failed = [e for e in events if e["event"] == "tool_failed"]
    assert failed == []
    assert not [e for e in events if e["event"] == "tool_loop_repeated"]


@pytest.mark.asyncio
async def test_a_fourth_identical_call_does_not_halt_by_default():
    log: list[dict] = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True)
    backend = _Backend([("lookup", {"q": "x"})] * 4 + [("lookup", {"q": "y"})])
    events: list[dict] = []
    reply = await _run(runtime, backend, events)
    assert reply == "done"
    assert log == [{"q": "x"}] * 4 + [{"q": "y"}]
    assert len(backend.calls) == 6
    stop = [e for e in events if e["event"] == "tool_loop_repeated"]
    assert stop == []


@pytest.mark.asyncio
async def test_argument_order_does_not_make_a_different_call():
    log: list[dict] = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True)
    backend = _Backend([
        ("lookup", {"q": "x", "k": 1}),
        ("lookup", {"k": 1, "q": "x"}),
        ("lookup", {"q": "x", "k": 1}),
    ])
    reply = await _run(runtime, backend)
    assert reply == "done"
    assert len(log) == 3
    assert "identical_call" in _tool_results(backend)[2]["stall_notice"]["tracks"]


@pytest.mark.asyncio
async def test_different_arguments_or_tools_are_never_repeats():
    log: list[dict] = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True)
    backend = _Backend([
        ("lookup", {"q": "a"}), ("lookup", {"q": "b"}), ("lookup", {"q": "c"}),
        ("ping", {}), ("ping", {}), ("lookup", {"q": "a"}), ("lookup", {"q": "b"}),
    ])
    reply = await _run(runtime, backend)
    assert reply == "done"
    assert len(log) == 7
    assert all(r.get("ok", True) is not False for r in _tool_results(backend))


@pytest.mark.asyncio
async def test_repeat_limit_zero_disables_the_detector():
    log: list[dict] = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, repeat_limit=0)
    backend = _Backend([("lookup", {"q": "x"})] * 6)
    reply = await _run(runtime, backend)
    assert reply == "done"
    assert len(log) == 6


@pytest.mark.asyncio
async def test_identical_calls_fanned_out_in_one_turn_count_too():
    log: list[dict] = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, max_tool_calls_per_turn=4)

    class _FanOut(_Backend):
        async def generate_tool_turn(self, **kwargs):
            self.calls.append([dict(message) for message in kwargs["messages"]])
            if len(self.calls) == 1:
                return ToolTurn(
                    tool_calls=tuple(
                        ToolCall(id=f"c{i}", name="lookup", raw_arguments='{"q":"x"}',
                                 arguments={"q": "x"})
                        for i in range(3)
                    ),
                    finish_reason="tool_calls",
                )
            return ToolTurn(content="done", finish_reason="stop")

    backend = _FanOut([])
    reply = await _run(runtime, backend)
    assert reply == "done"
    assert len(log) == 3
    results = _tool_results(backend)
    assert [r.get("reason") for r in results] == [None, None, None]
    assert "identical_call" in results[2]["stall_notice"]["tracks"]


def _failing_server(log: list[dict]) -> ToolRPCServer:
    server = ToolRPCServer()

    async def flaky(args):
        log.append(dict(args))
        if args.get("ok"):
            return {"fine": True}
        return {"ok": False, "reason": "not_found"}

    schema = {"type": "object", "properties": {"n": {"type": "integer"}, "ok": {"type": "boolean"}}}
    server.register_tool("flaky", flaky, description="Fails unless asked not to.", input_schema=schema)
    return server


@pytest.mark.asyncio
async def test_the_same_tool_failing_eight_times_in_a_row_ends_the_turn_when_opted_in():
    log: list[dict] = []
    runtime = AgentToolRuntime(_failing_server(log), enabled=lambda: True, max_iterations=lambda: 12,
                               stall_halt_enabled=True)
    backend = _Backend([("flaky", {"n": i}) for i in range(9)])
    events: list[dict] = []
    reply = await _run(runtime, backend, events)
    assert reply == _FAILURE_REPLY
    assert len(log) == 8
    stop = [e for e in events if e["event"] == "tool_loop_failing"]
    assert len(stop) == 1 and stop[0]["tool"] == "flaky" and stop[0]["failures"] == 8
    assert stop[0]["limit"] == 8 and stop[0]["status"] == "same_tool_failure"


@pytest.mark.asyncio
async def test_a_success_resets_the_failure_streak():
    log: list[dict] = []
    runtime = AgentToolRuntime(_failing_server(log), enabled=lambda: True, max_iterations=lambda: 12)
    script = [("flaky", {"n": i}) for i in range(4)] + [("flaky", {"n": 9, "ok": True})]
    script += [("flaky", {"n": i + 10}) for i in range(4)]
    backend = _Backend(script)
    reply = await _run(runtime, backend)
    assert reply == "done"
    assert len(log) == 9


@pytest.mark.asyncio
async def test_failure_limit_zero_disables_the_streak_breaker():
    log: list[dict] = []
    runtime = AgentToolRuntime(
        _failing_server(log), enabled=lambda: True, max_iterations=lambda: 12, failure_limit=0,
    )
    backend = _Backend([("flaky", {"n": i}) for i in range(7)])
    reply = await _run(runtime, backend)
    assert reply == "done" and len(log) == 7
