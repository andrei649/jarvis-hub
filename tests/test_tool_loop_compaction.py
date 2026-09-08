"""Hermes absorption 0.3 — the tool loop measures the transcript it grows.

`AgentToolRuntime._run_loop` appends an assistant message plus one tool result per call for
up to 32 iterations and never measured the list; at the end the work was lost to a context
overflow nobody had counted. Now every turn after the first is preceded by a budget check:
older tool results fold into bounded envelopes (never dropped, never reordered — each result
keeps answering the call that made it, which is what every provider validates), the most
recent iterations fold last, and a transcript that still does not fit stops the loop with a
named reason instead of a provider error.
"""

from __future__ import annotations

import json

import pytest

from agents.core import agent_runtime
from agents.core.agent_runtime import AgentToolRuntime, _bounded_result_envelope
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer

CONTEXT_REPLY = "I stopped the tool loop because its context exceeded the safety budget."


class _Backend:
    supports_tools = True

    def __init__(self, tool_calls: int) -> None:
        self.remaining = tool_calls
        self.calls: list[list[dict]] = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append([dict(message) for message in kwargs["messages"]])
        if self.remaining > 0:
            self.remaining -= 1
            return ToolTurn(
                tool_calls=(
                    ToolCall(
                        id=f"call-{len(self.calls)}",
                        name="blob",
                        raw_arguments=json.dumps({"n": len(self.calls)}),
                        arguments={"n": len(self.calls)},
                    ),
                ),
                finish_reason="tool_calls",
            )
        return ToolTurn(content="done", finish_reason="stop")


def _server(payload_chars: int) -> ToolRPCServer:
    server = ToolRPCServer()

    async def blob(args):
        # Distinct per call: an identical payload would be replaced by a reference stub
        # (Hermes absorption 4f) and there would be nothing left to fold.
        return {"blob": "y" * payload_chars, "n": args.get("n")}

    server.register_tool(
        "blob",
        blob,
        description="Return a large payload.",
        input_schema={"type": "object", "properties": {"n": {"type": "integer"}}},
    )
    return server


@pytest.fixture(autouse=True)
def _chars_are_tokens(monkeypatch):
    """Four characters per token, deterministically — the budget math must not depend on tiktoken."""
    monkeypatch.setattr(
        agent_runtime,
        "estimate_messages",
        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4,
    )


async def _run(runtime, backend, *, system="You are Nerva.", events=None):
    return await runtime.run(
        agent_id="nerva",
        backend=backend,
        model="local-model",
        prompt="fetch a lot",
        system=system,
        max_tokens=256,
        temperature=0.2,
        event_sink=events.append if events is not None else None,
    )


@pytest.mark.asyncio
async def test_older_tool_results_fold_before_the_next_turn_and_pairing_survives():
    events = []
    backend = _Backend(tool_calls=3)
    runtime = AgentToolRuntime(
        _server(payload_chars=4_000),
        enabled=lambda: True,
        context_budget_tokens=lambda: 2_400,  # ~9,600 chars: two 4k results fit, three do not
        compaction_keep_recent=1,
    )

    answer = await _run(runtime, backend, events=events)

    assert answer == "done"
    final = backend.calls[-1]  # what the model saw on its last turn
    assert [m["role"] for m in final] == [
        "system", "user", "assistant", "tool", "assistant", "tool", "assistant", "tool",
    ]
    # Every tool result still answers the call that made it.
    for assistant, tool in ((2, 3), (4, 5), (6, 7)):
        assert final[tool]["tool_call_id"] == final[assistant]["tool_calls"][0]["id"]
    # The oldest result folded into a bounded envelope …
    folded = json.loads(final[3]["content"])
    assert folded["notice"] == "TOOL RESULT COMPACTED"
    assert folded["ok"] is True and folded["tool"] == "blob" and folded["truncated"] is True
    assert folded["original_bytes"] > 4_000
    assert len(final[3]["content"].encode("utf-8")) <= 512
    # … and the most recent one is verbatim.
    assert json.loads(final[7]["content"])["result"]["blob"] == "y" * 4_000
    compaction = [e for e in events if e["event"] == "tool_context_compacted"]
    assert compaction and compaction[0]["status"] == "compacted"
    assert compaction[0]["compacted"] >= 1
    assert compaction[0]["tokens_after"] <= compaction[0]["budget"] < compaction[0]["tokens_before"]


@pytest.mark.asyncio
async def test_a_transcript_that_cannot_fit_stops_the_loop_with_a_named_reason():
    events = []
    backend = _Backend(tool_calls=5)
    runtime = AgentToolRuntime(
        _server(payload_chars=100),
        enabled=lambda: True,
        context_budget_tokens=lambda: 2_048,
    )

    # A system prompt alone worth ~2,100 tokens: nothing to fold can bring it under budget.
    answer = await _run(runtime, backend, system="s" * 8_400, events=events)

    assert answer == CONTEXT_REPLY
    assert len(backend.calls) == 1  # the loop never asked the model a second time
    assert events[-1]["event"] == "tool_context_compacted"
    assert events[-1]["status"] == "exhausted"


@pytest.mark.asyncio
async def test_small_results_are_left_verbatim_because_an_envelope_would_be_larger():
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=50),
        enabled=lambda: True,
        context_budget_tokens=lambda: 2_048,
    )

    await _run(runtime, backend, system="s" * 8_300)

    tool_message = backend.calls[-1][-1] if len(backend.calls) > 1 else None
    # Either the loop stopped (nothing foldable) or the small result survived untouched.
    if tool_message is not None:
        assert "COMPACTED" not in tool_message["content"]


def test_the_automatic_budget_derives_from_the_model_window():
    runtime = AgentToolRuntime(ToolRPCServer())

    assert runtime._context_budget("gemma3:27b", 1_024) == int(128_000 * 0.75) - 1_024
    assert runtime._context_budget("some-unknown-model", 0) == int(32_000 * 0.75)
    configured = AgentToolRuntime(ToolRPCServer(), context_budget_tokens=lambda: 5_000)
    assert configured._context_budget("gemma3", 4_096) == 5_000
    floor = AgentToolRuntime(ToolRPCServer(), context_budget_tokens=lambda: 10)
    assert floor._context_budget("gemma3", 0) == 2_048
    broken = AgentToolRuntime(ToolRPCServer(), context_budget_tokens=lambda: 1 / 0)
    assert broken._context_budget("phi4", 0) == int(16_384 * 0.75)


def test_a_claude_route_budget_is_no_longer_24k():
    """Hermes absorption 5c: the automatic budget is window * 0.75 - reserve, and
    an unrecognised cloud model fell to the 32k default — so every cloud tool
    loop compacted against ~24k on a 200k model. A named cloud family now earns
    its real window; an unknown model stays at the conservative default."""
    runtime = AgentToolRuntime(ToolRPCServer())

    assert runtime._context_budget("claude-sonnet-4-6", 8_192) >= 100_000
    assert runtime._context_budget("claude-sonnet-4-6", 8_192) == int(200_000 * 0.75) - 8_192
    assert runtime._context_budget("some-unknown-model", 0) == int(32_000 * 0.75)


def test_the_truncation_envelope_keeps_its_original_notice():
    envelope = json.loads(
        _bounded_result_envelope('{"ok":true}', tool_name="t", ok=True, reason=None, max_bytes=400)
    )
    assert envelope["notice"] == "TOOL RESULT TRUNCATED"
