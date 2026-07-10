"""Agent Runtime v2 bounded ToolRPC loop tests."""

import asyncio
import json

import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer


class _ScriptedBackend:
    supports_tools = True

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        recorded = dict(kwargs)
        recorded["messages"] = [dict(message) for message in kwargs["messages"]]
        self.calls.append(recorded)
        return self.turns.pop(0)


class _RepeatingBackend:
    supports_tools = True

    def __init__(self, call):
        self.call = call
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append(kwargs)
        return ToolTurn(tool_calls=(self.call,), finish_reason="tool_calls")


def _call(
    name="echo",
    *,
    call_id="call-1",
    arguments=None,
    raw_arguments=None,
    parse_error=None,
):
    if arguments is None and parse_error is None:
        arguments = {"value": "hi"}
    if raw_arguments is None:
        raw_arguments = json.dumps(arguments, separators=(",", ":"))
    return ToolCall(
        id=call_id,
        name=name,
        raw_arguments=raw_arguments,
        arguments=arguments,
        parse_error=parse_error,
    )


async def _run(runtime, backend, *, agent_id="jarvis", event_sink=None):
    return await runtime.run(
        agent_id=agent_id,
        backend=backend,
        model="local-model",
        prompt="use a tool",
        system="You are Jarvis.",
        max_tokens=256,
        temperature=0.2,
        event_sink=event_sink,
    )


def _tool_result_from_second_provider_call(backend, index=-1):
    message = backend.calls[1]["messages"][index]
    assert message["role"] == "tool"
    return json.loads(message["content"])


@pytest.mark.asyncio
async def test_runtime_executes_tool_and_continues_to_final_answer():
    handled = []
    events = []
    server = ToolRPCServer()

    async def echo(args):
        handled.append(args)
        return {"echo": args["value"]}

    server.register_tool(
        "echo",
        echo,
        description="Echo one value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    backend = _ScriptedBackend(
        [
            ToolTurn(
                tool_calls=(
                    ToolCall(
                        id="call-echo",
                        name="echo",
                        raw_arguments='{"value":"hi"}',
                        arguments={"value": "hi"},
                    ),
                ),
                finish_reason="tool_calls",
            ),
            ToolTurn(content="Echo completed", finish_reason="stop"),
        ]
    )
    runtime = AgentToolRuntime(server, enabled=lambda: True)

    answer = await runtime.run(
        agent_id="jarvis",
        backend=backend,
        model="local-model",
        prompt="echo hi",
        system="You are Jarvis.",
        max_tokens=256,
        temperature=0.2,
        event_sink=events.append,
    )

    assert answer == "Echo completed"
    assert handled == [{"value": "hi"}]
    assert backend.calls[1]["messages"][-2] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-echo",
                "type": "function",
                "function": {
                    "name": "echo",
                    "arguments": '{"value":"hi"}',
                },
            }
        ],
    }
    tool_message = backend.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call-echo"
    assert json.loads(tool_message["content"]) == {
        "ok": True,
        "tool": "echo",
        "result": {"echo": "hi"},
    }
    assert [event["event"] for event in events] == [
        "tool_requested",
        "tool_started",
        "tool_result",
    ]


def test_can_run_requires_enabled_supported_backend_and_nonempty_allowlist():
    server = ToolRPCServer()

    async def echo(args):
        return args

    backend = _ScriptedBackend([])
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    assert runtime.can_run(backend) is False

    server.register_tool("echo", echo)
    assert runtime.can_run(backend) is True
    assert AgentToolRuntime(server, enabled=lambda: False).can_run(backend) is False

    backend.supports_tools = False
    assert runtime.can_run(backend) is False


def test_can_run_fails_closed_when_runtime_checks_raise():
    server = ToolRPCServer()
    server.register_tool("echo", lambda args: args)
    backend = _ScriptedBackend([])

    def explode():
        raise RuntimeError("unsafe setting failure")

    assert AgentToolRuntime(server, enabled=explode).can_run(backend) is False

    runtime = AgentToolRuntime(server, enabled=lambda: True)
    server.tools = explode
    assert runtime.can_run(backend) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("parse_error", ["invalid_json", "arguments_not_object"])
async def test_invalid_arguments_return_bad_tool_arguments_without_handler_call(parse_error):
    handled = []
    server = ToolRPCServer()

    async def echo(args):
        handled.append(args)
        return args

    server.register_tool("echo", echo)
    backend = _ScriptedBackend(
        [
            ToolTurn(
                tool_calls=(
                    _call(
                        arguments=None,
                        raw_arguments="{malformed",
                        parse_error=parse_error,
                    ),
                )
            ),
            ToolTurn(content="arguments rejected"),
        ]
    )

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    assert answer == "arguments rejected"
    assert handled == []
    assert _tool_result_from_second_provider_call(backend)["reason"] == ("bad_tool_arguments")


@pytest.mark.asyncio
async def test_unknown_tool_returns_tool_not_allowed_and_continues():
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    backend = _ScriptedBackend(
        [
            ToolTurn(tool_calls=(_call("invented_tool"),)),
            ToolTurn(content="I cannot use that tool."),
        ]
    )

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    assert answer == "I cannot use that tool."
    assert _tool_result_from_second_provider_call(backend) == {
        "ok": False,
        "reason": "tool_not_allowed",
        "tool": "invented_tool",
    }


@pytest.mark.asyncio
async def test_approval_required_enqueues_once_and_stops_without_another_provider_call():
    enqueued = []
    handled = []

    def enqueue(agent, kind, title, **kwargs):
        enqueued.append({"agent": agent, "kind": kind, **kwargs})
        return len(enqueued)

    server = ToolRPCServer(enqueue=enqueue)

    async def send(args):
        handled.append(args)
        return {"sent": True}

    server.register_tool("send", send, gated=True)
    backend = _ScriptedBackend(
        [
            ToolTurn(
                tool_calls=(
                    _call(
                        "send",
                        call_id="approval-1",
                        arguments={"agent": "model-controlled"},
                    ),
                    _call(
                        "send",
                        call_id="approval-2",
                        arguments={"agent": "model-controlled"},
                    ),
                )
            ),
            ToolTurn(content="must not be requested"),
        ]
    )

    answer = await _run(
        AgentToolRuntime(server, enabled=lambda: True),
        backend,
        agent_id="trusted-athena",
    )

    assert "approval" in answer.lower()
    assert handled == []
    assert len(enqueued) == 1
    assert enqueued[0]["agent"] == "trusted-athena"
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_handler_exception_returns_tool_error_without_exception_details():
    server = ToolRPCServer()

    async def fail(args):
        raise RuntimeError("do-not-leak-handler-secret")

    server.register_tool("fail", fail)
    events = []
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call("fail"),)), ToolTurn(content="safe recovery")]
    )

    answer = await _run(
        AgentToolRuntime(server, enabled=lambda: True),
        backend,
        event_sink=events.append,
    )

    result_message = backend.calls[1]["messages"][-1]["content"]
    assert answer == "safe recovery"
    assert json.loads(result_message)["reason"] == "tool_error"
    assert "do-not-leak-handler-secret" not in result_message
    assert "do-not-leak-handler-secret" not in json.dumps(events)


@pytest.mark.asyncio
async def test_handler_timeout_returns_tool_timeout():
    server = ToolRPCServer()

    async def hang(args):
        await asyncio.Event().wait()

    server.register_tool("hang", hang)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call("hang"),)), ToolTurn(content="timed out safely")]
    )
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        tool_timeout_seconds=0.01,
        max_wall_seconds=1.0,
    )

    answer = await asyncio.wait_for(_run(runtime, backend), timeout=0.2)

    assert answer == "timed out safely"
    assert _tool_result_from_second_provider_call(backend)["reason"] == "tool_timeout"


@pytest.mark.asyncio
async def test_whole_loop_timeout_returns_honest_deadline_message():
    server = ToolRPCServer()
    server.register_tool("echo", lambda args: args)

    class _HangingBackend:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            await asyncio.Event().wait()

    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        max_wall_seconds=0.01,
    )

    answer = await asyncio.wait_for(_run(runtime, _HangingBackend()), timeout=0.2)

    assert answer == "I stopped the tool loop because it reached the safety deadline."


@pytest.mark.asyncio
async def test_read_only_calls_run_concurrently_and_results_keep_provider_order():
    server = ToolRPCServer()
    released = asyncio.Event()
    started = []

    async def coordinated(args):
        value = args["value"]
        started.append(value)
        if len(started) == 2:
            released.set()
        await released.wait()
        if value == "first":
            await asyncio.sleep(0.01)
        return {"value": value}

    server.register_tool("coordinated", coordinated)
    backend = _ScriptedBackend(
        [
            ToolTurn(
                tool_calls=(
                    _call(
                        "coordinated",
                        call_id="first-call",
                        arguments={"value": "first"},
                    ),
                    _call(
                        "coordinated",
                        call_id="second-call",
                        arguments={"value": "second"},
                    ),
                )
            ),
            ToolTurn(content="both complete"),
        ]
    )
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        tool_timeout_seconds=0.2,
    )

    answer = await asyncio.wait_for(_run(runtime, backend), timeout=0.4)

    assert answer == "both complete"
    tool_messages = backend.calls[1]["messages"][-2:]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "first-call",
        "second-call",
    ]
    assert [json.loads(message["content"])["result"]["value"] for message in tool_messages] == [
        "first",
        "second",
    ]


@pytest.mark.asyncio
async def test_large_json_tool_result_is_explicitly_truncated_at_default_limit():
    server = ToolRPCServer()

    async def large(args):
        return {"blob": "x" * 60_000}

    server.register_tool("large", large)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call("large"),)), ToolTurn(content="summarized")]
    )

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    content = backend.calls[1]["messages"][-1]["content"]
    assert answer == "summarized"
    assert "TOOL RESULT TRUNCATED" in content
    assert len(content.encode("utf-8")) < 50_500


@pytest.mark.asyncio
async def test_non_json_tool_result_returns_non_json_result_without_repr():
    server = ToolRPCServer()

    async def opaque(args):
        return object()

    server.register_tool("opaque", opaque)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call("opaque"),)), ToolTurn(content="recovered")]
    )

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    content = backend.calls[1]["messages"][-1]["content"]
    assert answer == "recovered"
    assert json.loads(content) == {
        "ok": False,
        "reason": "non_json_result",
        "tool": "opaque",
    }
    assert "object at" not in content


@pytest.mark.asyncio
async def test_repeating_calls_stop_at_iteration_cap_and_emit_exhaustion():
    server = ToolRPCServer()
    handled = []

    async def echo(args):
        handled.append(args)
        return args

    server.register_tool("echo", echo)
    backend = _RepeatingBackend(_call())
    events = []
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        max_iterations=lambda: 2,
    )

    answer = await _run(runtime, backend, event_sink=events.append)

    assert answer == (
        "I stopped the tool loop after 2 model turns because it reached the safety limit."
    )
    assert len(backend.calls) == 2
    assert len(handled) == 2
    assert events[-1]["event"] == "tool_loop_exhausted"


@pytest.mark.asyncio
@pytest.mark.parametrize(("configured", "expected"), [(0, 1), (99, 32)])
async def test_iteration_setting_is_clamped_to_one_through_thirty_two(configured, expected):
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    backend = _RepeatingBackend(_call())
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        max_iterations=lambda: configured,
    )

    answer = await _run(runtime, backend)

    assert len(backend.calls) == expected
    assert answer.startswith(f"I stopped the tool loop after {expected} model turns")


@pytest.mark.asyncio
async def test_calls_over_per_turn_cap_get_local_failure_without_toolrpc_execution():
    server = ToolRPCServer()
    handled = []

    async def echo(args):
        handled.append(args["value"])
        return args

    server.register_tool("echo", echo)
    calls = tuple(_call(call_id=f"call-{index}", arguments={"value": index}) for index in range(10))
    backend = _ScriptedBackend([ToolTurn(tool_calls=calls), ToolTurn(content="fan-out bounded")])

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    assert answer == "fan-out bounded"
    assert sorted(handled) == list(range(8))
    tool_messages = backend.calls[1]["messages"][-10:]
    assert [message["tool_call_id"] for message in tool_messages] == [
        f"call-{index}" for index in range(10)
    ]
    assert [json.loads(message["content"])["reason"] for message in tool_messages[-2:]] == [
        "too_many_tool_calls",
        "too_many_tool_calls",
    ]


@pytest.mark.asyncio
async def test_raising_event_sink_is_swallowed_without_changing_answer():
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call(),)), ToolTurn(content="still answered")]
    )

    def broken_sink(event):
        raise RuntimeError("observer unavailable")

    answer = await _run(
        AgentToolRuntime(server, enabled=lambda: True),
        backend,
        event_sink=broken_sink,
    )

    assert answer == "still answered"


@pytest.mark.asyncio
async def test_awaitable_event_sink_receives_lifecycle_events():
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    backend = _ScriptedBackend([ToolTurn(tool_calls=(_call(),)), ToolTurn(content="done")])
    events = []

    async def sink(event):
        events.append(event)

    answer = await _run(
        AgentToolRuntime(server, enabled=lambda: True),
        backend,
        event_sink=sink,
    )

    assert answer == "done"
    assert [event["event"] for event in events] == [
        "tool_requested",
        "tool_started",
        "tool_result",
    ]


@pytest.mark.asyncio
async def test_event_payloads_do_not_include_raw_arguments_or_results():
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args["value"]}

    server.register_tool("echo", echo)
    backend = _ScriptedBackend(
        [
            ToolTurn(tool_calls=(_call(arguments={"value": "event-secret-value"}),)),
            ToolTurn(content="done"),
        ]
    )
    events = []

    await _run(
        AgentToolRuntime(server, enabled=lambda: True),
        backend,
        event_sink=events.append,
    )

    assert "event-secret-value" not in json.dumps(events)
