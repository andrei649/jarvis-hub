"""Source-assigned tool-loop exits; legacy callers still receive reply strings."""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError, is_dataclass
from types import SimpleNamespace

import pytest

from agents.core import agent_runtime
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.effective_window import EffectiveWindow
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_loop_result import ToolLoopExitReason
from agents.core.tool_rpc import ToolRPCServer


def _call(number: int = 1, name: str = "echo") -> ToolCall:
    args = {"n": number}
    return ToolCall(id=f"call-{number}", name=name, raw_arguments=json.dumps(args), arguments=args)


class _Backend:
    supports_tools = True

    def __init__(self, *turns: ToolTurn) -> None:
        self.turns = list(turns)
        self.calls = 0

    async def generate_tool_turn(self, **_kwargs):
        self.calls += 1
        assert self.turns, "unexpected provider request"
        return self.turns.pop(0)


def _server(*, failure: bool = False, gated: bool = False, payload: int = 0) -> ToolRPCServer:
    server = ToolRPCServer(enqueue=lambda *_args, **_kwargs: 1) if gated else ToolRPCServer()

    async def echo(args):
        if failure:
            return {"ok": False, "reason": "not_found"}
        return {"n": args["n"], "payload": "x" * payload}

    server.register_tool("echo", echo, gated=gated)
    return server


def _runtime(server: ToolRPCServer | None = None, **options) -> AgentToolRuntime:
    return AgentToolRuntime(server or _server(), enabled=lambda: True, **options)


async def _run(runtime: AgentToolRuntime, backend: _Backend, *, typed: bool = True, **options):
    method = runtime.run_result if typed else runtime.run
    arguments = {"agent_id": "jarvis", "backend": backend, "model": "test-model", "prompt": "use a tool",
                 "system": "You are Jarvis.", "max_tokens": 256, "temperature": 0.2, **options}
    return await method(**arguments)


@pytest.mark.asyncio
async def test_existing_string_contract_and_model_prose_control():
    reply = agent_runtime._APPROVAL_REPLY
    assert await _run(_runtime(), _Backend(ToolTurn(content=reply)), typed=False) == reply


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [agent_runtime._APPROVAL_REPLY, ""])
async def test_model_reply_that_looks_like_a_fixed_refusal_is_still_model_response(reply):
    result = await _run(_runtime(), _Backend(ToolTurn(content=reply)))
    assert result.reply == reply
    assert result.exit_reason is ToolLoopExitReason.MODEL_RESPONSE
    assert is_dataclass(result) and result.__dataclass_params__.frozen
    assert not hasattr(result, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        result.exit_reason = "approval_required"


@pytest.mark.asyncio
async def test_replay_refusal_raised_inside_owned_model_loop_is_typed_without_a_reply_change():
    from agents.core.llm.provider_replay import ReplayRefused

    class _ReplayRefusingBackend:
        supports_tools = True

        async def generate_tool_turn(self, **_kwargs):
            raise ReplayRefused()

    result = await _run(_runtime(), _ReplayRefusingBackend())
    assert (result.reply, result.exit_reason) == (agent_runtime._CONTEXT_REPLY, "replay_refused")


@pytest.mark.asyncio
async def test_approval_warning_suffix_is_preserved_by_typed_result(monkeypatch):
    runtime = _runtime()

    async def observations(*_args, **_kwargs):
        return [({"ok": False, "reason": "approval_required", "tool": "echo",
                  "code_warnings": "py-os-system@2"}, "queued")]

    monkeypatch.setattr(runtime, "_execute_turn_calls", observations)
    backend = _Backend(ToolTurn(tool_calls=(_call(),)))
    result = await _run(runtime, backend)
    assert result.exit_reason is ToolLoopExitReason.APPROVAL_REQUIRED
    assert result.reply == (agent_runtime._APPROVAL_REPLY
                            + " The code it writes has pattern warnings (warnings, not refusals): py-os-system@2.")


@pytest.mark.asyncio
@pytest.mark.parametrize(("case", "reason", "reply"), [
    ("window", "window_invalid", agent_runtime._WINDOW_REPLY),
    ("context", "context_refused", agent_runtime._CONTEXT_REPLY),
    ("revoked", "turn_revoked", agent_runtime._CONTEXT_REPLY),
    ("replay", "replay_refused", agent_runtime._CONTEXT_REPLY),
    ("capability", "no_capability", agent_runtime._NO_CAPABILITY_REPLY),
    ("tools", "no_tools", agent_runtime._NO_TOOLS_REPLY),
    ("repeat", "repeated_call", agent_runtime._REPEAT_REPLY),
    ("approval", "approval_required", agent_runtime._APPROVAL_REPLY),
    ("failing", "failing_tool", agent_runtime._FAILURE_REPLY),
    ("limit", "iteration_limit", "I stopped the tool loop after 1 model turns because it reached the safety limit."),
    ("fanout", "tool_call_limit", agent_runtime._CONTEXT_REPLY),
])
async def test_exact_terminal_branches(case, reason, reply, monkeypatch):
    server = _server(failure=case == "failing", gated=case == "approval")
    options = {}
    turns = [ToolTurn(content="unexpected")]
    kwargs = {}
    if case == "window":
        kwargs["effective_window"] = EffectiveWindow(valid=False)
    elif case == "context":
        kwargs["prompt"] = "x" * 20_000
        kwargs["effective_window"] = EffectiveWindow(tokens=4096)
    elif case == "revoked":
        from agents.core import conversation_clock
        monkeypatch.setattr(conversation_clock, "active_clock", lambda: SimpleNamespace(active=False))
    elif case == "replay":
        from agents.core.llm.provider_replay import active_replay, replay_scope
        with replay_scope():
            active_replay().active = False
            result = await _run(_runtime(server), _Backend(*turns))
        assert (result.reply, result.exit_reason) == (reply, reason)
        return
    elif case == "capability":
        options.update(registry_enabled=lambda: True, capability_snapshot=lambda: {"capabilities": []})
    elif case == "tools":
        options["tool_profile"] = lambda _agent, _rows: ([], None)
    elif case == "repeat":
        options["repeat_limit"] = 1
        turns = [ToolTurn(tool_calls=(_call(1),)), ToolTurn(tool_calls=(_call(2),))]
        # Same tool and arguments are required for the repeated-call breaker.
        turns[1] = ToolTurn(tool_calls=(_call(1),))
    elif case == "approval":
        turns = [ToolTurn(tool_calls=(_call(),))]
    elif case == "failing":
        options["failure_limit"] = 1
        turns = [ToolTurn(tool_calls=(_call(),))]
    elif case == "limit":
        options["max_iterations"] = lambda: 1
        turns = [ToolTurn(tool_calls=(_call(),))]
    elif case == "fanout":
        options["max_tool_calls_per_turn"] = 1
        turns = [ToolTurn(tool_calls=(_call(1), _call(2)), provider_replay=object())]
    runtime = _runtime(server, **options)
    result = await _run(runtime, _Backend(*turns), **kwargs)
    assert (result.reply, result.exit_reason) == (reply, reason)


@pytest.mark.asyncio
async def test_compaction_boundary_withdraws_live_offer(monkeypatch):
    # A real payload fold, not a fabricated return value, causes the offer refresh.
    monkeypatch.setattr(agent_runtime, "estimate_messages",
                        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4)
    server = _server(payload=4_000)

    class _RevokingBackend(_Backend):
        async def generate_tool_turn(self, **kwargs):
            if self.calls == 2:
                server.tools = list
            return await super().generate_tool_turn(**kwargs)

    backend = _RevokingBackend(*(ToolTurn(tool_calls=(_call(n),)) for n in range(1, 4)))
    runtime = _runtime(server, context_budget_tokens=lambda: 2_400, compaction_keep_recent=1)
    result = await _run(runtime, backend)
    assert result.reply == agent_runtime._TOOLS_WITHDRAWN_REPLY
    assert result.exit_reason == "tools_withdrawn"
    assert backend.calls == 3


@pytest.mark.asyncio
async def test_deadline_is_outer_result_even_if_child_ignores_cancellation():
    entered = asyncio.Event()
    release = asyncio.Event()

    class _ResistantBackend:
        supports_tools = True

        async def generate_tool_turn(self, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return ToolTurn(content="too late")

    runtime = _runtime(max_wall_seconds=0.01)
    try:
        result = await asyncio.wait_for(_run(runtime, _ResistantBackend()), timeout=0.3)
        assert entered.is_set()
        assert (result.reply, result.exit_reason) == (agent_runtime._DEADLINE_REPLY, "deadline")
    finally:
        release.set()
        await asyncio.sleep(0)
