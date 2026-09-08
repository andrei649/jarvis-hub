"""The tool loop's trail now has a destination, and the fence leaves a trace.

`AgentToolRuntime` has always emitted a typed event per step — including the Hermes
absorption 5a `tool_result_untrusted` that says a result was fenced as DATA and the
turn tainted — but `_emit` returns immediately with no sink, and `Agent.generate_response`,
the only production caller of `run`, never passed one. So the events were built and
dropped, and `docs/OWNER_TASKS.md` P24 asked its reader to check a timeline that had
nothing in it.

Pinned here: the agent passes a sink; the bounded log keeps and bounds what arrives;
the fence's own event really lands in it through a real runtime; and nothing a tool
returned — arguments or result — is in what the owner reads back.
"""

from __future__ import annotations

import json

import pytest

from agents.core.agent import Agent
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.observability.tool_events import (
    MAX_EVENTS,
    MAX_LIST_ITEMS,
    MAX_VALUE_CHARS,
    TOOL_EVENTS,
    ToolEventLog,
)
from agents.core.tool_rpc import ToolRPCServer

_SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}}


class _Backend:
    supports_tools = True

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append(kwargs)
        if self.script:
            name, args = self.script.pop(0)
            return ToolTurn(
                tool_calls=(ToolCall(id=f"call-{len(self.calls)}", name=name,
                                     raw_arguments=json.dumps(args), arguments=args),),
                finish_reason="tool_calls",
            )
        return ToolTurn(content="done", finish_reason="stop")


# ── the bounded log ──────────────────────────────────────────────────────────

def test_the_log_keeps_order_stamps_and_a_monotonic_tally():
    log = ToolEventLog(max_events=10)
    log.record({"event": "tool_requested", "tool": "web_search"})
    log.record({"event": "tool_result_untrusted", "tool": "web_search"})
    rows = log.snapshot()

    assert [row["event"] for row in rows] == ["tool_requested", "tool_result_untrusted"]
    assert [row["seq"] for row in rows] == [1, 2]
    assert all(row["at"].startswith("20") for row in rows)
    assert log.counts() == {"tool_requested": 1, "tool_result_untrusted": 1}


def test_the_ring_evicts_but_the_tally_does_not():
    """"Did the fence ever fire" must stay answerable after the buffer turns over."""
    log = ToolEventLog(max_events=3)
    for index in range(10):
        log.record({"event": "tool_result", "tool": f"t{index}"})
    assert len(log.snapshot(limit=MAX_EVENTS)) == 3
    assert [row["tool"] for row in log.snapshot()] == ["t7", "t8", "t9"]
    assert log.counts() == {"tool_result": 10}


def test_a_snapshot_cannot_be_asked_for_more_than_the_ring_holds():
    log = ToolEventLog(max_events=5)
    for index in range(5):
        log.record({"event": "e", "n": index})
    assert len(log.snapshot(limit=10_000)) == 5
    assert len(log.snapshot(limit=0)) == 1
    assert len(log.snapshot(limit=-3)) == 1


def test_every_field_is_bounded_and_an_unknown_shape_becomes_its_type_name():
    """The runtime already bounds what it emits; re-applying it here is what keeps a
    future emitter that forgets from leaking a tool's arguments into a casual surface."""
    log = ToolEventLog()
    log.record({
        "event": "tool_failed",
        "long": "x" * (MAX_VALUE_CHARS + 500),
        "many": [f"flag-{i}" for i in range(MAX_LIST_ITEMS + 12)],
        "payload": {"secret": "sk-live-DO-NOT-KEEP"},
        "count": 7,
        "flag": True,
        "nothing": None,
        **{f"k{i}": i for i in range(40)},
    })
    row = log.snapshot()[0]

    assert len(row["long"]) == MAX_VALUE_CHARS
    assert len(row["many"]) == MAX_LIST_ITEMS
    assert row["payload"] == "dict", "a nested value must not be rendered, only named"
    assert "sk-live-DO-NOT-KEEP" not in json.dumps(row)
    assert row["count"] == 7 and row["flag"] is True and row["nothing"] is None


def test_a_malformed_event_is_recorded_rather_than_raised():
    """An observability sink that can break a turn is worse than a missing line."""
    log = ToolEventLog()
    for bad in ("not a dict", 42, None, ["a", "b"]):
        log.record(bad)
    assert [row["event"] for row in log.snapshot()] == ["malformed"] * 4


def test_clear_resets_the_ring_the_tally_and_the_sequence():
    log = ToolEventLog()
    log.record({"event": "e"})
    log.clear()
    assert log.snapshot() == [] and log.counts() == {}
    log.record({"event": "e"})
    assert log.snapshot()[0]["seq"] == 1


# ── the agent actually passes a sink ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_agent_hands_the_loop_a_sink_and_the_default_is_the_shared_log():
    seen = []

    class _Runtime:
        def can_run(self, backend, agent_id=None):
            return True

        async def run(self, **kwargs):
            seen.append(kwargs)
            return "answer"

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = _Runtime()
    await agent.generate_response(
        backend=object(), model="m", prompt="p", system="s", max_tokens=64, temperature=0.1,
    )
    assert seen[0]["event_sink"] == TOOL_EVENTS.record

    own = ToolEventLog()
    agent.tool_event_sink = own.record
    await agent.generate_response(
        backend=object(), model="m", prompt="p", system="s", max_tokens=64, temperature=0.1,
    )
    assert seen[1]["event_sink"] == own.record, "an injected sink wins over the default"


# ── end to end: the fence's own event lands in the log ───────────────────────

@pytest.mark.asyncio
async def test_a_fenced_result_leaves_a_trace_the_owner_can_read():
    """The whole point: run the real loop over a real untrusted tool and find the
    event in the log afterwards — with no page text in it."""
    server = ToolRPCServer()

    async def page(args):
        return {"text": "PAGE-BODY-SHOULD-NEVER-BE-LOGGED", "n": args.get("n")}

    server.register_tool("web_read", page, input_schema=_SCHEMA, untrusted_output=True)

    log = ToolEventLog()
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_iterations=lambda: 4)
    backend = _Backend([("web_read", {"n": 1})])

    answer = await runtime.run(
        agent_id="jarvis", backend=backend, model="m", prompt="read it", system="s",
        max_tokens=64, temperature=0.1, event_sink=log.record,
    )

    assert answer == "done"
    names = [row["event"] for row in log.snapshot()]
    assert "tool_result_untrusted" in names, names
    fenced = next(row for row in log.snapshot() if row["event"] == "tool_result_untrusted")
    assert fenced["tool"] == "web_read"
    assert fenced["reasons"] == ["untrusted_tool"]
    assert log.counts()["tool_result_untrusted"] == 1

    blob = json.dumps(log.snapshot())
    assert "PAGE-BODY-SHOULD-NEVER-BE-LOGGED" not in blob
    assert "<<UNTRUSTED" not in blob, "the fence's own text is not the trail's business"
