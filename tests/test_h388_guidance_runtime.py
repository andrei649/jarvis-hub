"""Upstream guidance reaches real model calls with the exact profiled offer."""

import asyncio
import contextvars
import json

import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer


class Backend:
    supports_tools = True

    def __init__(self, calls=0):
        self.remaining = calls
        self.requests = []

    async def generate_tool_turn(self, **kwargs):
        self.requests.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        if self.remaining:
            self.remaining -= 1
            args = {"n": len(self.requests)}
            return ToolTurn(tool_calls=(ToolCall(id=f"call-{len(self.requests)}", name="echo",
                raw_arguments=json.dumps(args), arguments=args),), finish_reason="tool_calls")
        return ToolTurn(content="done", finish_reason="stop")


def setup_runtime(*, profile=None, calls=None, budget=0):
    server = ToolRPCServer()

    async def echo(args):
        if calls is not None:
            calls.append(args["n"])
            return {"n": args["n"], "payload": "x" * 7200}
        return dict(args)

    for name in ("echo", "session_search"):
        server.register_tool(name, echo, description=name,
                             input_schema={"type": "object", "properties": {"n": {"type": "integer"}}})
    runtime = AgentToolRuntime(server, enabled=lambda: True, tool_profile=profile,
        context_budget_tokens=lambda: budget, compaction_keep_recent=0,
        compacted_result_bytes=96)
    return runtime


async def run(runtime, backend, *, model="gpt-5", events=None):
    return await runtime.run(agent_id="jarvis", backend=backend, model=model,
        prompt="synthetic request", system="IDENTITY AUTHORITY\nPERSONA", max_tokens=64,
        temperature=0.1, event_sink=events.append if events is not None else None)


@pytest.mark.asyncio
async def test_real_tool_call_receives_hermes_guidance_for_actual_model_and_tools():
    runtime, backend = setup_runtime(), Backend()
    runtime._guidance_context = lambda aid: {"surface": "telegram"}
    assert await run(runtime, backend) == "done"
    system = backend.requests[0]["messages"][0]["content"]
    assert system.startswith("IDENTITY AUTHORITY\nPERSONA")
    assert "# Finishing the job" in system and "# Tool-use enforcement" in system
    assert "# Parallel tool calls" in system and "session_search" in system
    assert "You are on Telegram" in system
    assert {t.name for t in backend.requests[0]["tools"]} == {"echo", "session_search"}


@pytest.mark.asyncio
async def test_withheld_tool_cannot_leak_into_feature_specific_advice():
    def profile(aid, metadata):
        return [m for m in metadata if m["name"] == "echo"], None

    runtime, backend = setup_runtime(profile=profile), Backend()
    runtime._guidance_context = lambda aid: {"surface": "cli"}
    await run(runtime, backend)
    system = backend.requests[0]["messages"][0]["content"]
    assert "# Finishing the job" in system
    assert "session_search" not in system
    assert [t.name for t in backend.requests[0]["tools"]] == ["echo"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model,expected,absent", [
    ("gemini-2.5", "# Google model operational directives", "unsupported-model"),
    ("claude-sonnet", "# Finishing the job", "# Tool-use enforcement"),
    ("unknown-family", "# Finishing the job", "# Google model operational directives"),
])
async def test_guidance_selects_actual_routed_family(model, expected, absent):
    runtime, backend = setup_runtime(), Backend()
    runtime._guidance_context = lambda aid: {}
    await run(runtime, backend, model=model)
    assert backend.requests[0]["model"] == model
    system = backend.requests[0]["messages"][0]["content"]
    assert expected in system and absent not in system


@pytest.mark.asyncio
async def test_trusted_independent_flags_disable_only_selected_blocks():
    runtime, backend = setup_runtime(), Backend()
    runtime._guidance_context = lambda aid: {"enabled": {
        "task_completion": False, "tool_use_enforcement": False, "session_search": False}}
    await run(runtime, backend)
    system = backend.requests[0]["messages"][0]["content"]
    assert "# Finishing the job" not in system and "# Tool-use enforcement" not in system
    assert "session_search" not in system and "# Parallel tool calls" in system
    assert [t.name for t in backend.requests[0]["tools"]] == ["echo", "session_search"]


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [None, {"enabled": {"task_completion": "bad"}}])
async def test_disabled_or_unreadable_optional_guidance_keeps_tool_authority(config):
    runtime, backend = setup_runtime(), Backend()
    runtime._guidance_context = lambda aid: config
    assert await run(runtime, backend) == "done"
    assert backend.requests[0]["messages"][0]["content"] == "IDENTITY AUTHORITY\nPERSONA"
    assert {t.name for t in backend.requests[0]["tools"]} == {"echo", "session_search"}


@pytest.mark.asyncio
async def test_shared_runtime_keeps_authenticated_surfaces_in_their_own_turns():
    active = contextvars.ContextVar("test_guidance_surface")
    runtime = setup_runtime()
    runtime._guidance_context = lambda aid: {"surface": active.get()}

    async def turn(surface):
        token = active.set(surface)
        try:
            backend = Backend()
            await run(runtime, backend)
            return backend.requests[0]["messages"][0]["content"]
        finally:
            active.reset(token)

    telegram, cli = await asyncio.gather(turn("telegram"), turn("cli"))
    assert "You are on Telegram" in telegram and "plain terminal" not in telegram
    assert "plain terminal" in cli and "You are on Telegram" not in cli


@pytest.mark.asyncio
async def test_compaction_rebuild_removes_advice_for_a_withdrawn_tool(monkeypatch):
    # Match the existing compaction regressions: repeated text otherwise has a
    # tokenizer-dependent size and may never cross the actual fold boundary.
    monkeypatch.setattr("agents.core.agent_runtime.estimate_messages", lambda messages:
        sum(len(str(m.get("content", ""))) for m in messages) // 4)
    calls, events = [], []

    def profile(aid, metadata):
        return [m for m in metadata if not calls or m["name"] != "session_search"], None

    runtime, backend = setup_runtime(profile=profile, calls=calls, budget=3000), Backend(calls=2)
    runtime._guidance_context = lambda aid: {}
    assert await run(runtime, backend, events=events) == "done"
    assert "session_search" in backend.requests[0]["messages"][0]["content"]
    assert any(e["event"] == "tool_offer_refreshed" and "session_search" in e["removed"] for e in events)
    assert "session_search" not in backend.requests[-1]["messages"][0]["content"]
    assert "# Finishing the job" in backend.requests[-1]["messages"][0]["content"]
    assert calls == [1, 2]
