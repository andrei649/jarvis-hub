"""Agent Runtime v2 bounded ToolRPC loop tests."""

import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from agents.core.agent import Agent
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.config import JarvisConfig
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.orchestrator import Orchestrator
from agents.core.security.secret_broker import SecretBroker
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


class _ToolCapableBackend:
    supports_tools = True


class _RepeatingBackend:
    supports_tools = True

    def __init__(self, call):
        self.call = call
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append(kwargs)
        return ToolTurn(tool_calls=(self.call,), finish_reason="tool_calls")


class _FakeLMStudioTransport:
    """Scripted in-process HTTP transport for end-to-end LM Studio requests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        payload = json.loads(request.content)
        self.requests.append(payload)
        if not self.responses:
            raise AssertionError("LM Studio received an unexpected extra request")
        response = self.responses.pop(0)
        if callable(response):
            response = response(payload)
        return httpx.Response(200, json=response, request=request)


def _fake_lmstudio(*responses):
    transport = _FakeLMStudioTransport(responses)
    backend = LMStudioBackend.__new__(LMStudioBackend)
    backend.base_url = "http://lm-studio.test"
    backend.client = httpx.AsyncClient(
        base_url=backend.base_url,
        transport=httpx.MockTransport(transport),
    )
    return backend, transport


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


async def _wait_until_can_run(runtime, backend):
    for _ in range(100):
        if runtime.can_run(backend):
            return
        await asyncio.sleep(0.005)
    pytest.fail("runtime remained blocked after its straggler completed")


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


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_timeout_configuration_falls_back_to_finite_defaults(non_finite):
    runtime = AgentToolRuntime(
        ToolRPCServer(),
        tool_timeout_seconds=non_finite,
        max_wall_seconds=non_finite,
    )

    assert runtime._tool_timeout_seconds == 30.0
    assert runtime._max_wall_seconds == 120.0


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
async def test_cancellation_resistant_provider_is_detached_and_blocks_new_turns_until_done():
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    cancelled = asyncio.Event()
    release = asyncio.Event()

    class _CancellationResistantBackend:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                return ToolTurn(content="too late")

    backend = _CancellationResistantBackend()
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_wall_seconds=0.01)
    started = asyncio.get_running_loop().time()
    run_task = asyncio.create_task(_run(runtime, backend))

    try:
        done, _ = await asyncio.wait({run_task}, timeout=0.25)
        elapsed = asyncio.get_running_loop().time() - started
        assert run_task in done
        answer = run_task.result()
        assert cancelled.is_set()
        assert elapsed < 0.1
        assert answer == "I stopped the tool loop because it reached the safety deadline."
        assert runtime.can_run(backend) is False
    finally:
        release.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

    await asyncio.wait_for(_wait_until_can_run(runtime, backend), timeout=0.5)


@pytest.mark.asyncio
async def test_cancellation_resistant_tool_is_detached_and_returns_tool_timeout_promptly():
    server = ToolRPCServer()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def resistant(args):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return {"late": True}

    server.register_tool("resistant", resistant)
    backend = _ScriptedBackend(
        [
            ToolTurn(tool_calls=(_call("resistant"),)),
            ToolTurn(content="continued safely"),
        ]
    )
    runtime = AgentToolRuntime(
        server,
        enabled=lambda: True,
        tool_timeout_seconds=0.01,
        max_wall_seconds=1.0,
    )
    started = asyncio.get_running_loop().time()
    run_task = asyncio.create_task(_run(runtime, backend))

    try:
        done, _ = await asyncio.wait({run_task}, timeout=0.25)
        elapsed = asyncio.get_running_loop().time() - started
        assert run_task in done
        answer = run_task.result()
        assert cancelled.is_set()
        assert answer == "continued safely"
        assert elapsed < 0.1
        assert _tool_result_from_second_provider_call(backend)["reason"] == "tool_timeout"
        assert runtime.can_run(backend) is False
    finally:
        release.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

    await asyncio.wait_for(_wait_until_can_run(runtime, backend), timeout=0.5)


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_while_owned_provider_is_detached():
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    class _CancellationResistantBackend:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                return ToolTurn(content="too late")

    backend = _CancellationResistantBackend()
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_wall_seconds=10.0)
    run_task = asyncio.create_task(_run(runtime, backend))
    await asyncio.wait_for(entered.wait(), timeout=0.1)
    run_task.cancel()

    try:
        done, _ = await asyncio.wait({run_task}, timeout=0.1)
        assert run_task in done
        with pytest.raises(asyncio.CancelledError):
            run_task.result()
        assert cancelled.is_set()
        assert runtime.can_run(backend) is False
    finally:
        release.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

    await asyncio.wait_for(_wait_until_can_run(runtime, backend), timeout=0.5)


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
    assert len(content.encode("utf-8")) <= 50_000
    observation = json.loads(content)
    assert observation["truncated"] is True
    assert observation["original_bytes"] > 50_000


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


def _cyclic_result():
    value = []
    value.append(value)
    return value


def _overdeep_result():
    value = None
    for _ in range(70):
        value = [value]
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result_factory",
    [
        lambda: ("tuple",),
        lambda: {"set"},
        lambda: object(),
        lambda: float("nan"),
        lambda: float("inf"),
        lambda: "\ud800",
        lambda: {1: "non-string-key"},
        _cyclic_result,
        _overdeep_result,
    ],
    ids=[
        "tuple",
        "set",
        "custom-object",
        "nan",
        "infinity",
        "lone-surrogate",
        "non-string-key",
        "cycle",
        "depth",
    ],
)
async def test_runtime_rejects_every_non_strict_json_result(result_factory):
    server = ToolRPCServer()

    async def invalid(args):
        return result_factory()

    server.register_tool("invalid", invalid)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call("invalid"),)), ToolTurn(content="recovered")]
    )

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    assert answer == "recovered"
    assert json.loads(backend.calls[1]["messages"][-1]["content"]) == {
        "ok": False,
        "reason": "non_json_result",
        "tool": "invalid",
    }


@pytest.mark.asyncio
async def test_real_secret_broker_never_leaks_tuple_secret_or_nan_to_provider():
    secret = "sk-VERY-SECRET"
    broker = SecretBroker()
    broker.put("runtime_test", secret)
    server = ToolRPCServer(secret_broker=broker)

    async def invalid(args):
        return {"nested": (secret, float("nan"))}

    server.register_tool("invalid", invalid)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call("invalid"),)), ToolTurn(content="safe answer")]
    )

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    provider_content = backend.calls[1]["messages"][-1]["content"]
    assert answer == "safe answer"
    assert secret not in provider_content
    assert "NaN" not in provider_content
    assert json.loads(provider_content)["reason"] == "non_json_result"


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
    calls = tuple(
        _call(call_id=f"call-{index}", arguments={"value": index})
        for index in range(10_000)
    )
    backend = _ScriptedBackend([ToolTurn(tool_calls=calls), ToolTurn(content="fan-out bounded")])

    answer = await _run(AgentToolRuntime(server, enabled=lambda: True), backend)

    assert answer == "fan-out bounded"
    assert sorted(handled) == list(range(8))
    assistant_message = backend.calls[1]["messages"][-10]
    tool_messages = backend.calls[1]["messages"][-9:]
    assert len(assistant_message["tool_calls"]) == 9
    assert [message["tool_call_id"] for message in tool_messages] == [
        f"call-{index}" for index in range(9)
    ]
    assert json.loads(tool_messages[-1]["content"])["reason"] == "too_many_tool_calls"


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
async def test_callable_object_sink_runs_sync_entry_off_loop_and_awaits_result():
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    backend = _ScriptedBackend([ToolTurn(tool_calls=(_call(),)), ToolTurn(content="done")])
    loop_thread = threading.get_ident()
    entry_threads = []
    events = []

    class _AwaitableSink:
        def __call__(self, event):
            entry_threads.append(threading.get_ident())

            async def record():
                events.append(event)

            return record()

    answer = await _run(
        AgentToolRuntime(server, enabled=lambda: True),
        backend,
        event_sink=_AwaitableSink(),
    )

    assert answer == "done"
    assert entry_threads and all(thread != loop_thread for thread in entry_threads)
    assert [event["event"] for event in events] == [
        "tool_requested",
        "tool_started",
        "tool_result",
    ]


@pytest.mark.asyncio
async def test_blocking_sync_sink_has_independent_deadline_and_is_tracked_until_release():
    server = ToolRPCServer()

    async def echo(args):
        return args

    server.register_tool("echo", echo)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call(),)), ToolTurn(content="answer was not blocked")]
    )
    entered = threading.Event()
    release = threading.Event()

    def blocking_sink(event):
        entered.set()
        release.wait()

    runtime = AgentToolRuntime(server, enabled=lambda: True, max_wall_seconds=1.0)
    failsafe = threading.Timer(0.5, release.set)
    failsafe.daemon = True
    failsafe.start()
    started = asyncio.get_running_loop().time()

    try:
        answer = await _run(runtime, backend, event_sink=blocking_sink)
        elapsed = asyncio.get_running_loop().time() - started

        assert entered.is_set()
        assert answer == "answer was not blocked"
        assert elapsed < 0.3
        assert runtime.can_run(backend) is False
    finally:
        release.set()
        failsafe.cancel()

    await asyncio.wait_for(_wait_until_can_run(runtime, backend), timeout=0.5)


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


class _DisabledRuntime:
    def __init__(self):
        self.backends = []

    def can_run(self, backend):
        self.backends.append(backend)
        return False

    async def run(self, **kwargs):
        raise AssertionError("disabled runtime must not run")


class _RecordingRuntime(AgentToolRuntime):
    def __init__(self, server):
        super().__init__(server, enabled=lambda: True)
        self.run_calls = []

    async def run(self, **kwargs):
        self.run_calls.append(dict(kwargs))
        return await super().run(**kwargs)


@pytest.mark.asyncio
async def test_agent_generate_response_disabled_uses_legacy_generate_once():
    class _TextBackend:
        def __init__(self):
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return "legacy answer"

    agent = Agent("jarvis", {"name": "Jarvis"})
    backend = _TextBackend()
    runtime = _DisabledRuntime()
    agent.tool_runtime = runtime

    answer = await agent.generate_response(
        backend=backend,
        model="legacy-model",
        prompt="hello",
        system="system",
        max_tokens=321,
        temperature=0.25,
    )

    assert answer == "legacy answer"
    assert runtime.backends == [backend]
    assert backend.calls == [
        {
            "model": "legacy-model",
            "prompt": "hello",
            "system": "system",
            "max_tokens": 321,
            "temperature": 0.25,
        }
    ]


@pytest.mark.asyncio
async def test_reality_harness_disabled_lmstudio_uses_one_legacy_request_without_tools():
    backend, transport = _fake_lmstudio(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "legacy HTTP answer"},
                }
            ]
        }
    )
    server = ToolRPCServer()

    async def echo(args):
        raise AssertionError("disabled mode must not execute ToolRPC")

    server.register_tool("echo", echo)
    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: False)

    try:
        answer = await agent.generate_response(
            backend=backend,
            model="local-model",
            prompt="hello over HTTP",
            system="You are Jarvis.",
            max_tokens=321,
            temperature=0.25,
        )
    finally:
        await backend.aclose()

    assert answer == "legacy HTTP answer"
    assert transport.responses == []
    assert transport.requests == [
        {
            "model": "local-model",
            "messages": [
                {"role": "system", "content": "You are Jarvis."},
                {"role": "user", "content": "hello over HTTP"},
            ],
            "temperature": 0.25,
            "stream": False,
            "max_tokens": 321,
        }
    ]


@pytest.mark.asyncio
async def test_reality_harness_enabled_lmstudio_executes_echo_and_persists_final_once():
    def tool_turn(payload):
        assert [tool["function"]["name"] for tool in payload["tools"]] == [
            "echo",
            "gated_write",
        ]
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
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
                    },
                }
            ]
        }

    def final_turn(payload):
        observation = json.loads(payload["messages"][-1]["content"])
        assert observation == {
            "ok": True,
            "tool": "echo",
            "result": {"echo": "hi"},
        }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "echo completed"},
                }
            ]
        }

    backend, transport = _fake_lmstudio(tool_turn, final_turn)
    server = ToolRPCServer()
    handled = []
    gated_handled = []

    async def echo(args):
        handled.append(args)
        return {"echo": args["value"]}

    async def gated_write(args):
        gated_handled.append(args)
        return {"written": True}

    server.register_tool(
        "echo",
        echo,
        description="Return one value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    server.register_tool("gated_write", gated_write, gated=True)
    agent = Agent("jarvis", {"name": "Jarvis", "model": "local-model"})
    agent.soul = {"content": "agent system"}
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
    orchestrator, _backend, completion_calls, turns = _streamed_orchestrator_for(
        agent, backend
    )
    emitted = []

    try:
        answer = await orchestrator.handle_input_stream(
            "question",
            channel="web",
            on_token=emitted.append,
            session_id="runtime-reality",
        )
    finally:
        await backend.aclose()

    assert answer == "echo completed"
    assert emitted == ["echo completed"]
    assert handled == [{"value": "hi"}]
    assert gated_handled == []
    assert len(transport.requests) == 2
    assert all(request["stream"] is False for request in transport.requests)
    assert all(request["tool_choice"] == "auto" for request in transport.requests)
    assert transport.responses == []
    assert len(completion_calls) == 1
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert [turn["content"] for turn in turns if turn["role"] == "assistant"] == [
        "echo completed"
    ]


@pytest.mark.parametrize(
    ("tool_name", "expected_requests", "expected_answer"),
    [
        ("unknown_tool", 2, "unknown was blocked"),
        (
            "gated_write",
            1,
            "I paused the tool loop because this action requires approval.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_reality_harness_unknown_and_gated_tool_handlers_never_execute(
    tool_name,
    expected_requests,
    expected_answer,
):
    first_response = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{tool_name}",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": '{"value":"must-not-run"}',
                            },
                        }
                    ],
                },
            }
        ]
    }
    final_response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": "unknown was blocked"},
            }
        ]
    }
    responses = [first_response]
    if tool_name == "unknown_tool":
        responses.append(final_response)
    backend, transport = _fake_lmstudio(*responses)
    handled = []
    server = ToolRPCServer()

    async def gated_write(args):
        handled.append(args)
        return {"written": True}

    server.register_tool("gated_write", gated_write, gated=True)
    runtime = AgentToolRuntime(server, enabled=lambda: True)

    try:
        answer = await _run(runtime, backend)
    finally:
        await backend.aclose()

    assert answer == expected_answer
    assert handled == []
    assert server.allows("unknown_tool") is False
    assert len(transport.requests) == expected_requests
    assert transport.responses == []
    if tool_name == "unknown_tool":
        observation = json.loads(transport.requests[1]["messages"][-1]["content"])
        assert observation == {
            "ok": False,
            "reason": "tool_not_allowed",
            "tool": "unknown_tool",
        }


@pytest.mark.asyncio
async def test_agent_process_runs_tools_inside_shared_seam_with_trusted_agent_id():
    handled = []
    server = ToolRPCServer()

    async def echo(args):
        handled.append(args)
        return {"echo": args["value"]}

    server.register_tool("echo", echo)
    backend = _ScriptedBackend(
        [ToolTurn(tool_calls=(_call(),)), ToolTurn(content="tool-backed answer")]
    )

    class _Router:
        model_manager = None

        def select_backend(self, agent_id, prompt):
            return backend, "runtime-model", "local-fast"

    agent = Agent("athena", {"name": "Athena"}, _Router())
    agent._gen_params = lambda route_name: (256, 0.2)
    runtime = _RecordingRuntime(server)
    agent.tool_runtime = runtime

    answer = await agent.process("echo hi", {"session_id": "runtime-seam"})

    assert answer == "tool-backed answer"
    assert handled == [{"value": "hi"}]
    assert len(runtime.run_calls) == 1
    assert runtime.run_calls[0]["agent_id"] == "athena"
    assert runtime.run_calls[0]["backend"] is backend
    assert runtime.run_calls[0]["model"] == "runtime-model"


@pytest.mark.asyncio
async def test_agent_generate_response_tool_mode_emits_only_final_answer_and_awaits_sink():
    class _EnabledRuntime:
        def __init__(self):
            self.calls = []

        def can_run(self, backend):
            return True

        async def run(self, **kwargs):
            self.calls.append(kwargs)
            return "final answer only"

    agent = Agent("jarvis", {"name": "Jarvis"})
    runtime = _EnabledRuntime()
    agent.tool_runtime = runtime
    backend = object()
    emitted = []

    async def on_token(token):
        await asyncio.sleep(0)
        emitted.append(token)

    answer = await agent.generate_response(
        backend=backend,
        model="tool-model",
        prompt="use tools",
        system="system",
        max_tokens=400,
        temperature=0.1,
        on_token=on_token,
    )

    assert answer == "final answer only"
    assert emitted == ["final answer only"]
    assert len(runtime.calls) == 1
    assert runtime.calls[0] == {
        "agent_id": "jarvis",
        "backend": backend,
        "model": "tool-model",
        "prompt": "use tools",
        "system": "system",
        "max_tokens": 400,
        "temperature": 0.1,
    }


@pytest.mark.parametrize("runtime_response", ["", " \t "])
@pytest.mark.asyncio
async def test_agent_generate_response_tool_mode_does_not_emit_blank_final_answer(
    runtime_response,
):
    class _EnabledRuntime:
        def can_run(self, backend):
            return True

        async def run(self, **kwargs):
            return runtime_response

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = _EnabledRuntime()
    emitted = []

    async def on_token(token):
        await asyncio.sleep(0)
        emitted.append(token)

    answer = await agent.generate_response(
        backend=object(),
        model="tool-model",
        prompt="use tools",
        system="system",
        max_tokens=400,
        temperature=0.1,
        on_token=on_token,
    )

    assert answer == runtime_response
    assert emitted == []


@pytest.mark.asyncio
async def test_agent_generate_response_disabled_preserves_stream_callback_identity():
    class _StreamingBackend:
        def __init__(self):
            self.calls = []

        async def generate_stream(self, **kwargs):
            self.calls.append(kwargs)
            kwargs["on_token"]("legacy token")
            return "legacy streamed answer"

        async def generate(self, **kwargs):
            raise AssertionError("stream-capable backend must not use generate")

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = _DisabledRuntime()
    backend = _StreamingBackend()
    emitted = []
    on_token = emitted.append

    answer = await agent.generate_response(
        backend=backend,
        model="legacy-model",
        prompt="stream this",
        system="system",
        max_tokens=200,
        temperature=0.3,
        on_token=on_token,
    )

    assert answer == "legacy streamed answer"
    assert emitted == ["legacy token"]
    assert len(backend.calls) == 1
    assert backend.calls[0]["on_token"] is on_token


class _FalseyAsyncSink:
    def __init__(self):
        self.values = []

    def __bool__(self):
        return False

    async def __call__(self, value):
        await asyncio.sleep(0)
        self.values.append(value)


class _AsyncSink:
    def __init__(self):
        self.values = []

    async def __call__(self, value):
        await asyncio.sleep(0)
        self.values.append(value)


class _LegacyDualBackend:
    def __init__(self, response):
        self.response = response
        self.generate_calls = 0
        self.stream_calls = 0

    async def generate(self, **kwargs):
        self.generate_calls += 1
        return self.response

    async def generate_stream(self, **kwargs):
        self.stream_calls += 1
        return self.response


@pytest.mark.asyncio
async def test_agent_disabled_mode_preserves_falsey_callback_legacy_behavior():
    agent = Agent("jarvis", {"name": "Jarvis"})
    backend = _LegacyDualBackend("legacy answer")
    on_token = _FalseyAsyncSink()

    answer = await agent.generate_response(
        backend=backend,
        model="legacy-model",
        prompt="answer",
        system="system",
        max_tokens=100,
        temperature=0.4,
        on_token=on_token,
    )

    assert answer == "legacy answer"
    assert backend.generate_calls == 1
    assert backend.stream_calls == 0
    assert on_token.values == []


@pytest.mark.asyncio
async def test_agent_generate_response_streamless_fallback_emits_once_and_awaits_sink():
    class _TextBackend:
        def __init__(self):
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return "fallback answer"

    agent = Agent("jarvis", {"name": "Jarvis"})
    backend = _TextBackend()
    emitted = []

    async def on_token(token):
        await asyncio.sleep(0)
        emitted.append(token)

    answer = await agent.generate_response(
        backend=backend,
        model="text-model",
        prompt="answer",
        system="system",
        max_tokens=100,
        temperature=0.4,
        on_token=on_token,
    )

    assert answer == "fallback answer"
    assert emitted == ["fallback answer"]
    assert len(backend.calls) == 1


def _streamed_orchestrator_for(agent, backend=None):
    orchestrator = Orchestrator(JarvisConfig())
    completion_calls = []
    turns = []

    class _Memory:
        async def add_turn(self, session_id, role, content, agent_id=None, channel=None):
            turns.append(
                {
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "agent_id": agent_id,
                }
            )

    class _Backend:
        async def generate_stream(self, **kwargs):
            raise AssertionError("orchestrator bypassed Agent.generate_response")

    if backend is None:
        backend = _Backend()

    class _Intent:
        target_agents = ["jarvis"]
        is_general = True
        confidence = 1.0
        context = {"keywords_found": [], "scores": {}, "source": "test"}

    async def classify(text, agents):
        return _Intent()

    async def empty_async(*args, **kwargs):
        return {}

    async def no_text(*args, **kwargs):
        return ""

    async def turn_text(*args, **kwargs):
        return "prepared turn"

    async def complete(**kwargs):
        completion_calls.append(kwargs)
        await orchestrator.memory.add_turn(
            orchestrator.session_id,
            "assistant",
            kwargs["synthesized"],
            agent_id=kwargs["responder_id"],
        )

    orchestrator.memory = _Memory()
    orchestrator.skills.parse_command = lambda text: None
    orchestrator._chat_control_enabled = lambda: False
    orchestrator.router.classify = classify
    orchestrator._gather_plugin_data = empty_async
    orchestrator._history_for_prompt = no_text
    orchestrator._recall_block = no_text
    orchestrator._runtime_state_block = lambda: ""
    orchestrator._build_agent_turn_text = turn_text
    orchestrator._route_candidates = lambda intent: intent.target_agents
    orchestrator.agents["jarvis"] = agent
    orchestrator.llm_router.select_backend = lambda agent_id, prompt: (
        backend,
        "selected-model",
        "local-fast",
    )
    orchestrator.checkpoints.load = lambda agent_id, session_id: None
    orchestrator.security = None
    orchestrator._agent_gen_params = lambda agent, route_name: (777, 0.15)
    orchestrator._complete_llm_turn = complete
    return orchestrator, backend, completion_calls, turns


@pytest.mark.asyncio
async def test_streamed_orchestrator_uses_agent_generation_seam_and_persists_once():
    seam_calls = []

    class _SeamAgent:
        name = "Jarvis"
        soul = {"content": "agent system"}
        config = {"model": "configured-model"}

        async def generate_response(self, **kwargs):
            seam_calls.append(kwargs)
            kwargs["on_token"]("seam answer")
            return "seam answer"

    orchestrator, backend, completion_calls, turns = _streamed_orchestrator_for(_SeamAgent())
    emitted = []
    on_token = emitted.append

    answer = await orchestrator.handle_input_stream(
        "question", channel="web", on_token=on_token, session_id="seam-session"
    )

    assert answer == "seam answer"
    assert emitted == ["seam answer"]
    assert len(seam_calls) == 1
    assert seam_calls[0] == {
        "backend": backend,
        "model": "selected-model",
        "prompt": "User said: prepared turn\nRespond as Jarvis.",
        "system": "agent system",
        "max_tokens": 777,
        "temperature": 0.15,
        "on_token": on_token,
    }
    assert len(completion_calls) == 1
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[-1]["content"] == "seam answer"


@pytest.mark.parametrize("runtime_response", ["", " \t "])
@pytest.mark.asyncio
async def test_streamed_orchestrator_replaces_blank_tool_answer_once_and_awaits_sink(
    runtime_response,
):
    class _BlankRuntime:
        def can_run(self, backend):
            return True

        async def run(self, **kwargs):
            return runtime_response

    agent = Agent("jarvis", {"name": "Jarvis", "model": "configured-model"})
    agent.soul = {"content": "agent system"}
    agent.tool_runtime = _BlankRuntime()
    orchestrator, _backend, completion_calls, turns = _streamed_orchestrator_for(agent)
    on_token = _AsyncSink()

    answer = await orchestrator.handle_input_stream(
        "question", channel="web", on_token=on_token, session_id="blank-seam-session"
    )

    fallback = (
        "My reply was cut short before I finished, sir — the model ran out of context "
        "while thinking. Try again, simplify the request, or load a larger-context model "
        "in LM Studio."
    )
    assert answer == fallback
    assert on_token.values == [fallback]
    assert len(completion_calls) == 1
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[-1]["content"] == fallback


@pytest.mark.asyncio
async def test_streamed_orchestrator_preserves_falsey_callback_for_blank_legacy_answer():
    agent = Agent("jarvis", {"name": "Jarvis", "model": "configured-model"})
    agent.soul = {"content": "agent system"}
    backend = _LegacyDualBackend("")
    orchestrator, _backend, completion_calls, turns = _streamed_orchestrator_for(agent, backend)
    on_token = _FalseyAsyncSink()

    answer = await orchestrator.handle_input_stream(
        "question", channel="web", on_token=on_token, session_id="legacy-blank-session"
    )

    fallback = (
        "My reply was cut short before I finished, sir — the model ran out of context "
        "while thinking. Try again, simplify the request, or load a larger-context model "
        "in LM Studio."
    )
    assert answer == fallback
    assert backend.generate_calls == 1
    assert backend.stream_calls == 0
    assert on_token.values == []
    assert len(completion_calls) == 1
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[-1]["content"] == fallback


@pytest.mark.asyncio
async def test_autonomy_coordinator_wires_one_live_governed_agent_tool_runtime():
    settings = {
        "llm.tool_loop_enabled": False,
        "llm.tool_loop_max_iterations": 8,
    }
    agents = {
        "jarvis": SimpleNamespace(tool_runtime=None),
        "athena": SimpleNamespace(tool_runtime=None),
    }
    class _SecretBroker:
        @staticmethod
        def redact(value):
            return value

    secret_broker = _SecretBroker()
    intent_log = object()
    action_kernel = object()

    class _Orchestrator:
        def __init__(self):
            self.agents = agents
            self.secret_broker = secret_broker
            self.intent_log = intent_log

        def get_setting(self, key, default=None):
            return settings.get(key, default)

    orch = _Orchestrator()
    runtime = AutonomyCoordinator(orch)._wire_agent_tool_runtime(
        action_kernel=action_kernel
    )

    assert runtime is orch.agent_tool_runtime
    assert runtime._server is orch.tool_rpc
    assert all(agent.tool_runtime is runtime for agent in orch.agents.values())
    assert orch.tool_rpc._secrets is secret_broker
    assert orch.tool_rpc._audit is intent_log
    assert orch.tool_rpc._kernel is action_kernel
    assert orch.tool_rpc.tools() == [
        {
            "name": "echo",
            "gated": False,
            "description": "Return the provided values.",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
        {
            "name": "time",
            "gated": False,
            "description": "Return the current Unix timestamp.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]

    assert await orch.tool_rpc.handle(
        {"tool": "echo", "args": {"value": "hello"}}, actor="jarvis"
    ) == {
        "ok": True,
        "tool": "echo",
        "result": {"echo": {"value": "hello"}},
    }
    time_result = await orch.tool_rpc.handle({"tool": "time", "args": {}})
    assert time_result["ok"] is True
    assert isinstance(time_result["result"]["now"], float)

    backend = _ToolCapableBackend()
    assert runtime.can_run(backend) is False
    settings["llm.tool_loop_enabled"] = True
    assert runtime.can_run(backend) is True
    settings["llm.tool_loop_enabled"] = "false"
    assert runtime.can_run(backend) is False

    settings["llm.tool_loop_enabled"] = True
    settings["llm.tool_loop_max_iterations"] = 0
    assert runtime._max_iterations() == 0
    assert runtime._iteration_limit() == 1


def test_agent_tool_runtime_wiring_defaults_safely_without_get_setting():
    orch = SimpleNamespace(agents={})

    runtime = AutonomyCoordinator(orch)._wire_agent_tool_runtime()

    assert runtime is orch.agent_tool_runtime
    assert runtime.can_run(_ToolCapableBackend()) is False
    assert runtime._max_iterations() == 8
    assert runtime._iteration_limit() == 8


def test_agent_tool_runtime_wiring_can_be_rebuilt_without_stale_agent_references():
    agent = SimpleNamespace(tool_runtime=None)
    orch = SimpleNamespace(agents={"jarvis": agent})
    coordinator = AutonomyCoordinator(orch)

    first_runtime = coordinator._wire_agent_tool_runtime()
    second_runtime = coordinator._wire_agent_tool_runtime()

    assert second_runtime is not first_runtime
    assert orch.agent_tool_runtime is second_runtime
    assert agent.tool_runtime is second_runtime
    assert orch.tool_rpc is second_runtime._server
