"""One owned tool-loop result and diagnostic, without changing string callers."""

import asyncio
import json
import logging
from dataclasses import FrozenInstanceError

import pytest

from agents.core import agent_runtime
from agents.core.agent import Agent
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer, current_tool_turn


def _runtime(*, iterations=8, wall=120.0):
    server = ToolRPCServer()

    async def echo(args):
        return {"observed": args.get("value")}

    server.register_tool("echo", echo)
    return AgentToolRuntime(
        server, enabled=lambda: True, max_iterations=lambda: iterations,
        max_wall_seconds=wall,
    )


class _Turns:
    supports_tools = True

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = 0
        self.requests = []

    async def generate_tool_turn(self, **kwargs):
        self.calls += 1
        self.requests.append([dict(message) for message in kwargs["messages"]])
        return self.turns.pop(0)


async def _run(runtime, backend, *, agent="jarvis", prompt="User request", **kwargs):
    return await runtime.run(
        agent_id=agent, backend=backend, model="local-model", prompt=prompt,
        system="System instruction", max_tokens=128, temperature=0.2,
        **kwargs,
    )


async def _run_result(runtime, backend, *, agent="jarvis"):
    return await runtime.run_result(
        agent_id=agent, backend=backend, model="local-model", prompt="User request",
        system="System instruction", max_tokens=128, temperature=0.2,
    )


def _exit_logs(caplog):
    return [row for row in caplog.records if "tool_loop_exit" in row.getMessage()]


@pytest.mark.asyncio
async def test_legacy_run_reaches_real_tool_reply_then_logs_one_private_exit(caplog):
    private_prompt = "PROMPT_SECRET_DO_NOT_LOG"
    private_arg = "ARG_SECRET_DO_NOT_LOG"
    private_reply = "REPLY_SECRET_DO_NOT_LOG"
    call = ToolCall(id="call-1", name="echo", raw_arguments='{"value":"' + private_arg + '"}',
                    arguments={"value": private_arg})
    backend = _Turns(ToolTurn(tool_calls=(call,), finish_reason="tool_calls"),
                     ToolTurn(content=private_reply, finish_reason="stop"))
    with caplog.at_level(logging.INFO, logger="jarvis.agent_runtime"):
        answer = await _run(_runtime(), backend, prompt=private_prompt)
    assert answer == private_reply and backend.calls == 2
    tool_message = backend.requests[1][-1]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"]) == {
        "ok": True, "tool": "echo", "result": {"observed": private_arg},
    }
    rows = _exit_logs(caplog)
    assert len(rows) == 1
    assert rows[0].levelno == logging.INFO
    message = rows[0].getMessage()
    assert "model_response" in message
    assert "jarvis" in message
    for private in (private_prompt, private_arg, private_reply, "observed", "call-1"):
        assert private not in message


@pytest.mark.asyncio
async def test_diagnostic_bounds_and_escapes_agent_identity_to_one_line(caplog):
    agent = "name\nFORGED_LINE" + "x" * 300 + "TAIL_SECRET_DO_NOT_LOG"
    backend = _Turns(ToolTurn(content="private answer"))
    with caplog.at_level(logging.INFO, logger="jarvis.agent_runtime"):
        answer = await _run(_runtime(), backend, agent=agent)
    assert answer == "private answer" and backend.calls == 1
    rows = _exit_logs(caplog)
    assert len(rows) == 1
    message = rows[0].getMessage()
    assert "\n" not in message and "TAIL_SECRET_DO_NOT_LOG" not in message
    assert "\\nFORGED_LINE" in message


@pytest.mark.asyncio
async def test_deadline_logs_once_and_late_child_cannot_log_again(caplog):
    entered = asyncio.Event()
    release = asyncio.Event()

    class Resistant:
        supports_tools = True

        async def generate_tool_turn(self, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return ToolTurn(content="late provider completion")

    backend = Resistant()
    runtime = _runtime(wall=0.01)
    try:
        with caplog.at_level(logging.INFO, logger="jarvis.agent_runtime"):
            task = asyncio.create_task(_run(runtime, backend))
            await asyncio.wait_for(entered.wait(), 0.2)
            answer = await asyncio.wait_for(task, 0.3)
            assert answer == "I stopped the tool loop because it reached the safety deadline."
            rows = _exit_logs(caplog)
            assert len(rows) == 1 and "deadline" in rows[0].getMessage()
            release.set()
            for _ in range(30):
                if runtime.can_run(backend):
                    break
                await asyncio.sleep(0.01)
            assert runtime.can_run(backend)
            assert len(_exit_logs(caplog)) == 1
    finally:
        release.set()


@pytest.mark.asyncio
async def test_typed_deadline_result_is_frozen_after_late_child_finishes(caplog):
    entered = asyncio.Event()
    release = asyncio.Event()

    class Resistant:
        supports_tools = True

        async def generate_tool_turn(self, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return ToolTurn(content="late result")

    runtime = _runtime(wall=0.01)
    backend = Resistant()
    try:
        with caplog.at_level(logging.INFO, logger="jarvis.agent_runtime"):
            task = asyncio.create_task(_run_result(runtime, backend))
            await asyncio.wait_for(entered.wait(), 0.2)
            result = await asyncio.wait_for(task, 0.3)
            assert result.exit_reason == "deadline"
            assert result.reply == "I stopped the tool loop because it reached the safety deadline."
            with pytest.raises(FrozenInstanceError):
                result.reply = "late result"
            release.set()
            for _ in range(30):
                if runtime.can_run(backend):
                    break
                await asyncio.sleep(0.01)
            assert runtime.can_run(backend)
            assert result.exit_reason == "deadline" and "safety deadline" in result.reply
            assert len(_exit_logs(caplog)) == 1
    finally:
        release.set()


@pytest.mark.asyncio
async def test_cancellation_and_provider_error_propagate_without_terminal_result_log(caplog):
    entered = asyncio.Event()

    class Blocked:
        supports_tools = True

        async def generate_tool_turn(self, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

    with caplog.at_level(logging.INFO, logger="jarvis.agent_runtime"):
        pending = asyncio.create_task(_run(_runtime(), Blocked()))
        await asyncio.wait_for(entered.wait(), 0.2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert _exit_logs(caplog) == []

        class Broken:
            supports_tools = True

            async def generate_tool_turn(self, **_kwargs):
                raise RuntimeError("PROVIDER_SECRET_DO_NOT_LOG")

        with pytest.raises(RuntimeError, match="PROVIDER_SECRET_DO_NOT_LOG"):
            await _run(_runtime(), Broken())
        assert _exit_logs(caplog) == []

        guarded = _Turns(ToolTurn(content="must not be requested"))

        def deny_before_provider():
            raise RuntimeError("gate refused")

        with pytest.raises(RuntimeError, match="gate refused"):
            await _run(_runtime(), guarded, before_model_call=deny_before_provider)
        assert guarded.calls == 0
        assert _exit_logs(caplog) == []


@pytest.mark.asyncio
async def test_concurrent_typed_results_on_shared_runtime_keep_their_own_reason(caplog):
    runtime = _runtime(iterations=1)
    legacy = await _run(runtime, _Turns(ToolTurn(content="legacy string")))
    assert legacy == "legacy string" and type(legacy) is str
    assert callable(getattr(runtime, "run_result", None))
    caplog.clear()  # Count only the concurrently awaited pair, not the legacy control.
    call = ToolCall(id="one", name="echo", raw_arguments='{"value":"x"}',
                    arguments={"value": "x"})
    with caplog.at_level(logging.INFO, logger="jarvis.agent_runtime"):
        model, limited = await asyncio.gather(
            _run_result(runtime, _Turns(ToolTurn(content="normal answer")), agent="first"),
            _run_result(runtime, _Turns(ToolTurn(tool_calls=(call,), finish_reason="tool_calls")), agent="second"),
        )
    assert (model.reply, model.exit_reason) == ("normal answer", "model_response")
    assert limited.exit_reason == "iteration_limit"
    assert "safety limit" in limited.reply
    rows = _exit_logs(caplog)
    assert len(rows) == 2
    assert any("first" in row.getMessage() and "model_response" in row.getMessage() for row in rows)
    assert any("second" in row.getMessage() and "iteration_limit" in row.getMessage() for row in rows)


@pytest.mark.asyncio
async def test_diagnostic_failure_cannot_replace_a_valid_string_reply(monkeypatch):
    def unavailable_log(*_args, **_kwargs):
        raise RuntimeError("logging failed")

    monkeypatch.setattr(agent_runtime.logger, "info", unavailable_log)
    answer = await _run(_runtime(), _Turns(ToolTurn(content="safe answer")))
    assert answer == "safe answer" and type(answer) is str


@pytest.mark.asyncio
async def test_diagnostic_runs_after_tool_turn_binding_is_reset(monkeypatch):
    seen = []

    def capture(format_string, *args):
        if "tool_loop_exit" in format_string:
            seen.append((current_tool_turn(), args))

    monkeypatch.setattr(agent_runtime.logger, "info", capture)
    answer = await _run(_runtime(), _Turns(ToolTurn(content="safe answer")))
    assert answer == "safe answer"
    assert len(seen) == 1 and seen[0][0] is None


@pytest.mark.asyncio
async def test_agent_accepts_an_injected_run_only_runtime_without_new_result_method():
    class RunOnly:
        def can_run(self, _backend, agent_id=None):
            return True

        async def run(self, **kwargs):
            assert kwargs["agent_id"] == "jarvis"
            return "answer from run only"

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = RunOnly()
    answer = await agent.generate_response(
        backend=object(), model="local-model", prompt="hello", system="system",
        max_tokens=64, temperature=0.2,
    )
    assert answer == "answer from run only" and type(answer) is str
