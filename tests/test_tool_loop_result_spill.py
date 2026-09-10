"""H298 at the loop level — the spill has to happen where results actually arrive.

`tests/test_tool_result_store.py` pins the mechanism in isolation: thresholds,
retention, the preview envelope, the two guards on the read path. None of that
proves the loop *uses* it. These tests drive `AgentToolRuntime.run` against a real
`ToolResultStore` and assert the three things a caller depends on:

* an oversized result reaches the model as a bounded preview whose footer names a
  file that exists and holds the whole thing, byte for byte;
* the same result with no store configured still truncates exactly as before, so
  the feature is additive and a store that cannot be built is not an outage;
* the per-turn budget bites across calls, not just within one — the failure this
  row names is five merely-largish results burying a small window, and a per-result
  cap cannot see that.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core import agent_runtime  # noqa: E402
from agents.core.agent_runtime import AgentToolRuntime  # noqa: E402
from agents.core.llm.tool_protocol import ToolCall, ToolTurn  # noqa: E402
from agents.core.tool_result_store import ToolResultStore  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402


class _Backend:
    """Calls `blob` once per requested turn, then answers."""

    supports_tools = True

    def __init__(self, tool_calls: int, *, tool: str = "blob") -> None:
        self.remaining = tool_calls
        self.tool = tool
        self.calls: list[list[dict]] = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append([dict(message) for message in kwargs["messages"]])
        if self.remaining > 0:
            self.remaining -= 1
            n = len(self.calls)
            return ToolTurn(
                tool_calls=(
                    ToolCall(
                        id=f"call-{n}",
                        name=self.tool,
                        raw_arguments=json.dumps({"n": n}),
                        arguments={"n": n},
                    ),
                ),
                finish_reason="tool_calls",
            )
        return ToolTurn(content="done", finish_reason="stop")


def _server(payload_chars: int, *, name: str = "blob", declared: int | None = None) -> ToolRPCServer:
    server = ToolRPCServer()

    async def blob(args):
        # Distinct per call: an identical payload is replaced by a reference stub
        # before it ever reaches the size check, and there would be nothing to spill.
        return {"blob": "y" * payload_chars, "n": args.get("n")}

    server.register_tool(
        name, blob, description="Return a large payload.",
        input_schema={"type": "object", "properties": {"n": {"type": "integer"}}},
        max_result_bytes=declared,
    )
    return server


@pytest.fixture(autouse=True)
def _chars_are_tokens(monkeypatch):
    """Four characters per token, deterministically — nothing here may depend on tiktoken."""
    monkeypatch.setattr(
        agent_runtime,
        "estimate_messages",
        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4,
    )


async def _run(runtime, backend, *, prompt="fetch a lot", model="local-model"):
    return await runtime.run(
        agent_id="nerva",
        backend=backend,
        model=model,
        prompt=prompt,
        system="You are Nerva.",
        max_tokens=256,
        temperature=0.2,
    )


def _tool_messages(backend) -> list[dict]:
    return [m for m in backend.calls[-1] if m.get("role") == "tool"]


@pytest.mark.asyncio
async def test_an_oversized_result_reaches_the_model_as_a_preview_and_the_disk_whole(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=40_000),
        enabled=lambda: True,
        max_result_bytes=5_000,
        result_store=store,
    )

    assert await _run(runtime, backend) == "done"

    envelope = json.loads(_tool_messages(backend)[0]["content"])
    assert envelope["spilled"] is True and envelope["truncated"] is True
    assert envelope["original_bytes"] > 40_000
    # The bounded half of the bargain: the model's copy is small.
    assert len(json.dumps(envelope).encode("utf-8")) < 5_000

    # The lossless half: the footer names a file that exists and matches, and the
    # digest in the envelope is the digest of what is actually on disk.
    spilled = Path(envelope["result_file"])
    assert spilled.is_file()
    raw = spilled.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == envelope["sha256"]
    recovered = json.loads(raw.decode("utf-8"))
    assert recovered["result"]["blob"] == "y" * 40_000
    # And it is reachable through the door the model is told to use.
    assert store.read(envelope["result_reference"], max_bytes=10**7) == raw.decode("utf-8")


@pytest.mark.asyncio
async def test_the_preview_shows_both_ends_so_the_model_can_tell_what_it_got(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=40_000), enabled=lambda: True,
        max_result_bytes=5_000, result_store=store,
    )

    await _run(runtime, backend)

    envelope = json.loads(_tool_messages(backend)[0]["content"])
    body = Path(envelope["result_file"]).read_text(encoding="utf-8")
    assert body.startswith(envelope["preview"]["head"])
    assert body.endswith(envelope["preview"]["tail"])
    assert envelope["preview"]["tail"], "a head-only preview hides which call answered"


@pytest.mark.asyncio
async def test_with_no_store_the_loop_truncates_exactly_as_it_did_before(tmp_path):
    """The feature is additive. A box that cannot write a spill is not an outage."""
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=40_000), enabled=lambda: True, max_result_bytes=5_000,
    )

    assert await _run(runtime, backend) == "done"

    envelope = json.loads(_tool_messages(backend)[0]["content"])
    assert envelope["notice"] == "TOOL RESULT TRUNCATED"
    assert envelope["truncated"] is True
    assert "spilled" not in envelope and "result_file" not in envelope
    assert not list(tmp_path.glob("**/*.json"))


@pytest.mark.asyncio
async def test_a_store_that_fails_falls_back_to_truncation_rather_than_losing_the_turn(tmp_path):
    blocker = tmp_path / "spills"
    blocker.write_text("not a directory", encoding="utf-8")
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=40_000), enabled=lambda: True,
        max_result_bytes=5_000, result_store=ToolResultStore(blocker),
    )

    assert await _run(runtime, backend) == "done"
    envelope = json.loads(_tool_messages(backend)[0]["content"])
    assert envelope["notice"] == "TOOL RESULT TRUNCATED"


@pytest.mark.asyncio
async def test_a_result_under_the_threshold_is_passed_through_untouched(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=100), enabled=lambda: True,
        max_result_bytes=50_000, result_store=store,
    )

    await _run(runtime, backend)

    payload = json.loads(_tool_messages(backend)[0]["content"])
    assert payload["result"]["blob"] == "y" * 100
    assert "notice" not in payload
    assert not list((tmp_path / "spills").glob("*.json")), "nothing to spill, nothing written"


@pytest.mark.asyncio
async def test_the_per_turn_budget_bites_across_calls_a_per_result_cap_cannot_see(tmp_path):
    """The failure this row names: several merely-largish results, none of them
    over the per-result cap, burying a small window between them.

    An 8k-token window gives ~32,000 bytes of context: floors put the per-result
    allowance at 8,000 bytes and the whole turn's at 16,000. Three 6,000-byte
    results each clear the per-result bar; the turn does not survive all three.
    """
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=3)
    runtime = AgentToolRuntime(
        _server(payload_chars=6_000),
        enabled=lambda: True,
        max_result_bytes=50_000,
        context_budget_tokens=lambda: 500_000,  # not compaction's job — isolate the budget
        result_store=store,
        context_window_tokens=lambda: 8_000,
    )

    await _run(runtime, backend)

    spilled = [
        json.loads(m["content"]).get("spilled") is True for m in _tool_messages(backend)
    ]
    assert spilled[0] is False, "the first result fits and must arrive verbatim"
    assert True in spilled, "a later one must not, or the per-turn budget is decorative"


@pytest.mark.asyncio
async def test_the_models_own_window_sets_the_budget_when_the_owner_declares_none(tmp_path):
    """The pairing test, and the one that keeps the scaling from being inert.

    Nobody configures `llm.tool_result_context_window` on a fresh install. If an
    absent override meant "no budget", the whole second half of this row would do
    nothing on every default deployment. It does not: the window comes from the
    model the turn is running on, the same table compaction reads. Here that is
    gemma2's 8,192 — the small local window this product is built around.
    """
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=3)
    runtime = AgentToolRuntime(
        _server(payload_chars=6_000),
        enabled=lambda: True,
        max_result_bytes=50_000,
        context_budget_tokens=lambda: 500_000,
        result_store=store,
    )

    await _run(runtime, backend, model="gemma2:2b")

    spilled = [json.loads(m["content"]).get("spilled") is True for m in _tool_messages(backend)]
    assert spilled[0] is False
    assert True in spilled, "an 8k window must not swallow three 6 KB results"


@pytest.mark.asyncio
async def test_the_same_results_fit_comfortably_in_a_large_window(tmp_path):
    """And the contrast: a constant cap cannot tell these two turns apart.

    Identical tools, identical payloads, identical settings — only the model
    differs. On a 200k window three 6 KB results are nothing, and spilling them
    would be the cost this row is trying to avoid paid for no reason.
    """
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=3)
    runtime = AgentToolRuntime(
        _server(payload_chars=6_000),
        enabled=lambda: True,
        max_result_bytes=50_000,
        context_budget_tokens=lambda: 500_000,
        result_store=store,
    )

    await _run(runtime, backend, model="claude-sonnet-4-6")

    for message in _tool_messages(backend):
        assert "spilled" not in json.loads(message["content"])
    assert not list((tmp_path / "spills").glob("*.json"))


@pytest.mark.asyncio
async def test_file_read_is_never_spilled_because_that_is_how_a_spill_is_read_back(tmp_path):
    """Spilling the read of a spill is an infinite regress with disk writes."""
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1, tool="file_read")
    runtime = AgentToolRuntime(
        _server(payload_chars=60_000, name="file_read"),
        enabled=lambda: True,
        max_result_bytes=5_000,
        result_store=store,
        context_window_tokens=lambda: 8_000,
    )

    await _run(runtime, backend)

    payload = json.loads(_tool_messages(backend)[0]["content"])
    assert payload["result"]["blob"] == "y" * 60_000
    assert not list((tmp_path / "spills").glob("*.json"))


@pytest.mark.asyncio
async def test_an_owner_override_lowers_the_bar_for_one_tool_only(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=4_000),
        enabled=lambda: True,
        max_result_bytes=50_000,
        result_store=store,
        result_thresholds=lambda: {"blob": 1_000},
    )

    await _run(runtime, backend)
    assert json.loads(_tool_messages(backend)[0]["content"])["spilled"] is True


@pytest.mark.asyncio
async def test_an_unreadable_override_source_does_not_take_the_turn_down(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1)

    def boom():
        raise RuntimeError("settings unavailable")

    runtime = AgentToolRuntime(
        _server(payload_chars=100), enabled=lambda: True,
        result_store=store, result_thresholds=boom,
        context_window_tokens=boom,
    )

    assert await _run(runtime, backend) == "done"
    assert json.loads(_tool_messages(backend)[0]["content"])["result"]["blob"] == "y" * 100


# ── the rung only the registrar can fill ─────────────────────────────────────

@pytest.mark.asyncio
async def test_a_tool_that_declares_its_own_limit_is_held_to_it(tmp_path):
    """The fourth rung of the ladder, and the one nobody has to configure."""
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=4_000, declared=1_000),
        enabled=lambda: True, max_result_bytes=50_000, result_store=store,
    )

    await _run(runtime, backend)
    assert json.loads(_tool_messages(backend)[0]["content"])["spilled"] is True


@pytest.mark.asyncio
async def test_the_owners_override_outranks_what_the_tool_declared(tmp_path):
    """Order matters: the person running the box beats the person who wrote the tool."""
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1)
    runtime = AgentToolRuntime(
        _server(payload_chars=4_000, declared=1_000),
        enabled=lambda: True, max_result_bytes=50_000, result_store=store,
        result_thresholds=lambda: {"blob": 40_000},
    )

    await _run(runtime, backend)
    payload = json.loads(_tool_messages(backend)[0]["content"])
    assert payload["result"]["blob"] == "y" * 4_000
    assert "spilled" not in payload


@pytest.mark.asyncio
async def test_a_pinned_tool_outranks_its_own_declaration_too(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    backend = _Backend(tool_calls=1, tool="file_read")
    runtime = AgentToolRuntime(
        _server(payload_chars=60_000, name="file_read", declared=1_000),
        enabled=lambda: True, max_result_bytes=50_000, result_store=store,
    )

    await _run(runtime, backend)
    assert json.loads(_tool_messages(backend)[0]["content"])["result"]["blob"] == "y" * 60_000


@pytest.mark.parametrize("bad", [0, -1, "big", 3.7e400])
def test_a_meaningless_declaration_is_refused_at_registration(bad):
    """Fail where the mistake is, not silently at the first oversized result."""
    server = ToolRPCServer()

    async def echo(args):
        return {}

    with pytest.raises(ValueError):
        server.register_tool("echo", echo, max_result_bytes=bad)
    assert server.allows("echo") is False


def test_a_declaration_stays_out_of_what_the_model_is_shown():
    """It is a budgeting detail; putting it in `tools()` would move a pinned snapshot."""
    server = ToolRPCServer()

    async def echo(args):
        return {}

    server.register_tool("echo", echo, max_result_bytes=1_234)
    assert server.declared_result_bytes("echo") == 1_234
    assert server.declared_result_bytes("nope") is None
    assert "max_result_bytes" not in server.tools()[0]
