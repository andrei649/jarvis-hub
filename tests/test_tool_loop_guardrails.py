"""Hermes absorption 4f — two more guardrails in the tool loop.

A per-tool cap refuses the call past the limit with a notice that says so (0 = off, from
`llm.tool_loop_per_tool_cap`); a successful result byte-identical to one already in the
transcript is replaced by a reference stub, so the model reads "same as call N" instead of
paying for the payload twice. Error results are never stubbed.
"""

from __future__ import annotations

import json

import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer


class _Backend:
    supports_tools = True

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append([dict(m) for m in kwargs["messages"]])
        if self.script:
            name, args = self.script.pop(0)
            return ToolTurn(
                tool_calls=(ToolCall(id=f"call-{len(self.calls)}", name=name,
                                     raw_arguments=json.dumps(args), arguments=args),),
                finish_reason="tool_calls",
            )
        return ToolTurn(content="done", finish_reason="stop")


def _server(log, *, payload="x" * 700):
    server = ToolRPCServer()

    async def big(args):
        log.append(("big", dict(args)))
        return {"page": payload}

    async def small(args):
        log.append(("small", dict(args)))
        return {"n": args.get("n")}

    async def broken(args):
        log.append(("broken", dict(args)))
        return {"ok": False, "reason": "not_found", "detail": "z" * 700}

    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    for name, fn in (("big", big), ("small", small), ("broken", broken)):
        server.register_tool(name, fn, description=name, input_schema=schema)
    return server


async def _run(runtime, backend, events=None):
    return await runtime.run(agent_id="nerva", backend=backend, model="m", prompt="p", system="s",
                             max_tokens=64, temperature=0.1,
                             event_sink=events.append if events is not None else None)


def _tool_messages(backend):
    return [json.loads(m["content"]) for m in backend.calls[-1] if m.get("role") == "tool"]


@pytest.mark.asyncio
async def test_a_tool_past_its_cap_is_refused_with_the_reason():
    log, events = [], []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, per_tool_limit=2,
                               max_iterations=lambda: 8)
    backend = _Backend([("small", {"n": 1}), ("small", {"n": 2}), ("small", {"n": 3}), ("big", {"n": 9})])
    assert await _run(runtime, backend, events) == "done"
    assert [name for name, _ in log] == ["small", "small", "big"]   # the third small never ran
    refused = _tool_messages(backend)[2]
    assert refused["ok"] is False and refused["reason"] == "tool_cap_reached"
    assert refused["calls"] == 3 and refused["limit"] == 2
    assert "already called 2 times" in refused["notice"]
    assert [e["status"] for e in events if e["event"] == "tool_failed"] == ["tool_cap_reached"]


@pytest.mark.asyncio
async def test_the_cap_reads_a_setting_and_zero_means_off():
    log = []
    cap = {"value": 0}
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, per_tool_limit=lambda: cap["value"],
                               max_iterations=lambda: 8)
    backend = _Backend([("small", {"n": i}) for i in range(5)])
    assert await _run(runtime, backend) == "done" and len(log) == 5
    cap["value"] = "bad"
    backend = _Backend([("small", {"n": i}) for i in range(3)])
    assert await _run(runtime, backend) == "done" and len(log) == 8    # unreadable → off


@pytest.mark.asyncio
async def test_an_identical_success_becomes_a_reference_stub():
    log, events = [], []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, max_iterations=lambda: 8)
    backend = _Backend([("big", {"n": 1}), ("big", {"n": 2}), ("big", {"n": 3})])
    assert await _run(runtime, backend, events) == "done"
    assert len(log) == 3                                    # the tool still runs each time
    first, second, third = _tool_messages(backend)
    assert first["result"] == {"page": "x" * 700}
    assert second == {"ok": True, "tool": "big", "same_as": "call-1",
                      "notice": "This result is byte-identical to the result of call call-1 "
                                "earlier this turn and was not repeated; refer to that result."}
    assert third["same_as"] == "call-1"
    dedup = [e for e in events if e["event"] == "tool_result_deduplicated"]
    assert [e["call_id"] for e in dedup] == ["call-2", "call-3"] and dedup[0]["same_as"] == "call-1"


@pytest.mark.asyncio
async def test_small_results_and_failures_are_never_stubbed():
    log = []
    runtime = AgentToolRuntime(_server(log), enabled=lambda: True, max_iterations=lambda: 8)
    backend = _Backend([("small", {"n": 1}), ("small", {"n": 1}), ("broken", {"n": 1}), ("broken", {"n": 1})])
    assert await _run(runtime, backend) == "done"
    msgs = _tool_messages(backend)
    assert msgs[0] == msgs[1] and "same_as" not in msgs[1]           # under the stub size
    assert msgs[2] == msgs[3] and msgs[3]["result"]["reason"] == "not_found"   # a failure, verbatim
