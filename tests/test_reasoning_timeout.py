"""Hermes absorption 5c — a reasoning-aware timeout floor the tool loop follows.

The flat per-agent ceiling (CDX-6, 120 s) killed a thinking model on the local deep
route on exactly the hard questions it was routed there for. Pinned here: the flat
route keeps 120 s; the local deep route and reasoning-family model names get the
reasoning floor on any route; the floor never drops below the flat value and never
exceeds an hour; non-numeric settings fall back to the defaults; a timed-out reply
names the reasoning budget; the tool loop's own deadline moves in step with the
turn's; the floor is recorded per agent for the turn; and ``is_reasoning_model``
is a pure table.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from agents.core import orchestrator as orch_mod
from agents.core.agent_runtime import _DEADLINE_REPLY, AgentToolRuntime
from agents.core.llm.moe_routing import MOE_MODELS, REASONING_FAMILIES, is_reasoning_model
from agents.core.orchestrator import (
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_REASONING_TIMEOUT,
    TIMEOUT_MAX_SECONDS,
    TIMEOUT_MIN_SECONDS,
    Orchestrator,
)
from agents.core.tool_rpc import ToolRPCServer

_SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}}


class _Agent:
    """The bits of an Agent the parallel path touches; `process` sleeps for `delay`."""

    last_latency = 0.01

    def __init__(self, delay: float = 0.0, model: str = "gemma-4-12b"):
        self.delay = delay
        self.config = {"model": model}
        self.failures: list[str] = []
        self.seen_context: dict | None = None

    async def process(self, text, context):
        self.seen_context = context
        if self.delay:
            await asyncio.sleep(self.delay)
        return "answered"

    def build_prompt(self, text, context):
        return f"User said: {text}"

    def _record_failure(self, reason: str = "unknown"):
        self.failures.append(reason)


def _orch(
    settings: dict | None = None,
    routes: dict | None = None,
    agents: dict | None = None,
    models: dict | None = None,
    route_on_prompt=None,
):
    """A bare orchestrator: settings from a dict; a router stub that answers
    ``select_backend(agent_id, prompt)`` from ``routes`` / ``models`` (or from
    ``route_on_prompt(agent_id, prompt)`` when the route must depend on the prompt)."""
    settings = dict(settings or {})
    routes = dict(routes or {})
    models = dict(models or {})

    def select_backend(agent_id, prompt):
        if route_on_prompt is not None:
            return None, models.get(agent_id, ""), route_on_prompt(agent_id, prompt)
        return None, models.get(agent_id, ""), routes.get(agent_id, "")

    async def _history(_n):
        return "", []

    async def _text(_agent_id, text, **_kw):
        return text

    async def _recall(_text):
        return ""

    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = dict(agents or {})
    orch._history_for_prompt = _history
    orch._format_plugin_data = lambda _d: ""
    orch._recall_block = _recall
    orch._runtime_state_block = lambda: ""
    orch._language_block = lambda: ""
    orch._data_grounding_block = lambda _d: ""
    orch._build_agent_turn_text = _text
    orch._route_for_agent = lambda agent_id, _t: routes.get(agent_id, "")
    orch.get_setting = lambda key, default=None: settings.get(key, default)
    orch.llm_router = SimpleNamespace(select_backend=select_backend)
    return orch


# ── the floor decision ───────────────────────────────────────────────────────

def test_flat_route_keeps_the_120s_default():
    orch = _orch()
    assert orch._agent_call_timeout(route_name="local-fast", model="gemma-4-12b") == (
        DEFAULT_AGENT_TIMEOUT, "flat",
    )
    assert orch._agent_call_timeout(route_name="", model="") == (120.0, "flat")
    assert orch._agent_call_timeout() == (120.0, "flat")


def test_local_deep_route_gets_the_reasoning_floor():
    orch = _orch()
    assert orch._agent_call_timeout(route_name="local-deep", model="gemma-4-31b") == (
        DEFAULT_REASONING_TIMEOUT, "reasoning",
    )
    # The setting, not the constant, once the owner tuned it.
    orch = _orch({"agents.reasoning_timeout_seconds": 900})
    assert orch._agent_call_timeout(route_name="local-deep") == (900.0, "reasoning")


def test_qwen3_and_deepseek_r1_names_get_the_floor_on_any_route():
    orch = _orch()
    for model in ("qwen3:8b", "deepseek-r1:14b", "Qwen3-30B-A3B", "gpt-oss-20b"):
        for route in ("local-fast", "cloud-flash", ""):
            seconds, floor = orch._agent_call_timeout(route_name=route, model=model)
            assert (seconds, floor) == (600.0, "reasoning"), (model, route)


def test_vendor_prefixed_name_is_recognised():
    orch = _orch()
    assert orch._agent_call_timeout(route_name="local-fast", model="ollama/qwen3:32b") == (600.0, "reasoning")
    assert orch._agent_call_timeout(route_name="local-fast", model="lmstudio-community/DeepSeek-R1-Distill") == (600.0, "reasoning")
    assert orch._agent_call_timeout(route_name="local-fast", model="google/gemma-4-12b") == (120.0, "flat")


def test_floor_never_drops_below_the_flat_value_and_never_exceeds_3600():
    # A reasoning ceiling set BELOW the flat one can only lengthen, never shorten.
    orch = _orch({"agents.agent_timeout_seconds": 300, "agents.reasoning_timeout_seconds": 30})
    assert orch._agent_call_timeout(route_name="local-deep") == (300.0, "reasoning")
    # Both bounds are visible constants; nothing escapes them.
    orch = _orch({"agents.agent_timeout_seconds": 99_999, "agents.reasoning_timeout_seconds": 99_999})
    assert orch._agent_call_timeout(route_name="local-fast") == (TIMEOUT_MAX_SECONDS, "flat")
    assert orch._agent_call_timeout(route_name="local-deep") == (3600.0, "reasoning")
    orch = _orch({"agents.agent_timeout_seconds": 0, "agents.reasoning_timeout_seconds": -5})
    assert orch._agent_call_timeout(route_name="local-fast") == (TIMEOUT_MIN_SECONDS, "flat")
    assert orch._agent_call_timeout(route_name="local-deep") == (1.0, "reasoning")


def test_non_numeric_setting_falls_back_to_defaults():
    orch = _orch({"agents.agent_timeout_seconds": "banana", "agents.reasoning_timeout_seconds": "lots"})
    assert orch._agent_call_timeout(route_name="local-fast") == (120.0, "flat")
    assert orch._agent_call_timeout(route_name="local-deep") == (600.0, "reasoning")
    orch = _orch({"agents.reasoning_timeout_seconds": None})
    assert orch._agent_call_timeout(route_name="local-deep") == (600.0, "reasoning")


# ── the turn ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_reply_names_the_reasoning_budget():
    settings = {"agents.agent_timeout_seconds": 1, "agents.reasoning_timeout_seconds": 1}
    slow = _Agent(delay=5.0)
    orch = _orch(settings, routes={"jarvis": "local-deep"}, agents={"jarvis": slow})
    results = await orch._call_agents_parallel(["jarvis"], "prove it", {})
    assert results == {"jarvis": "[jarvis timeout: reasoning budget 1s]"}
    assert slow.failures == ["timeout"]

    slow = _Agent(delay=5.0)
    orch = _orch(settings, routes={"jarvis": "local-fast"}, agents={"jarvis": slow})
    results = await orch._call_agents_parallel(["jarvis"], "hi", {})
    assert results == {"jarvis": "[jarvis timeout]"}


@pytest.mark.asyncio
async def test_agent_context_carries_the_wall_clock_without_touching_the_shared_dict():
    agent = _Agent()
    orch = _orch(routes={"jarvis": "local-deep"}, agents={"jarvis": agent})
    shared = {"session_id": "s"}
    await orch._call_agents_parallel(["jarvis"], "hi", shared)
    assert agent.seen_context == {"session_id": "s", "wall_seconds": 600.0}
    assert shared == {"session_id": "s"}, "the shared turn context is copied, never mutated"


@pytest.mark.asyncio
async def test_tool_loop_wall_clock_moves_in_step_with_the_turn_timeout():
    """A hung backend under the 120 s constructor default is cut at the turn's own
    budget instead; `None` keeps the constructor default byte-identical."""
    server = ToolRPCServer()

    async def lookup(args):
        return {"n": args.get("n")}

    server.register_tool("lookup", lookup, input_schema=_SCHEMA)

    class _Hung:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            await asyncio.sleep(600)

    runtime = AgentToolRuntime(server, enabled=lambda: True)  # 120 s default
    assert runtime._max_wall_seconds == 120.0
    t0 = time.monotonic()
    reply = await runtime.run(
        agent_id="jarvis", backend=_Hung(), model="qwen3:8b", prompt="think", wall_seconds=0.05,
    )
    elapsed = time.monotonic() - t0
    assert reply == _DEADLINE_REPLY
    assert elapsed < 10.0, elapsed  # the 1 s floor, not the 120 s default

    runtime = AgentToolRuntime(server, enabled=lambda: True, max_wall_seconds=0.05)
    t0 = time.monotonic()
    reply = await runtime.run(
        agent_id="jarvis", backend=_Hung(), model="qwen3:8b", prompt="think", wall_seconds=None,
    )
    assert reply == _DEADLINE_REPLY
    assert time.monotonic() - t0 < 1.0  # None → the constructor's own 0.05 s


@pytest.mark.asyncio
async def test_last_timeout_floor_is_recorded_per_agent():
    agents = {"jarvis": _Agent(), "stark": _Agent(model="qwen3:8b"), "athena": _Agent()}
    orch = _orch(
        {"agents.reasoning_timeout_seconds": 900},
        routes={"jarvis": "local-deep", "stark": "local-fast", "athena": "cloud-flash"},
        agents=agents,
    )
    orch._last_timeout_floor = {"stale": {"floor": "reasoning", "seconds": 1.0}}
    await orch._call_agents_parallel(["jarvis", "stark", "athena"], "hi", {})
    assert orch._last_timeout_floor == {
        "jarvis": {"floor": "reasoning", "seconds": 900.0},
        "stark": {"floor": "reasoning", "seconds": 900.0},
        "athena": {"floor": "flat", "seconds": 120.0},
    }, "per turn, per agent — the previous turn's map is gone"


@pytest.mark.asyncio
async def test_floor_follows_the_prompt_the_agent_routes_on():
    """The agent routes on the prompt built from the ENRICHED turn text (history,
    recall, plugin blocks). A floor decided on the raw user text calls a turn flat
    while its history makes the router escalate to the deep slot — and the thinking
    model still dies at two minutes. Fails on the raw-text implementation."""
    agent = _Agent()
    orch = _orch(
        agents={"jarvis": agent},
        route_on_prompt=lambda _aid, prompt: "local-deep" if "analyze" in prompt else "local-fast",
    )

    async def enriched(_agent_id, text, **_kw):
        return f"{text}\n[history] please analyze the numbers"

    orch._build_agent_turn_text = enriched
    await orch._call_agents_parallel(["jarvis"], "what next?", {"session_id": "s"})
    assert orch._last_timeout_floor == {"jarvis": {"floor": "reasoning", "seconds": 600.0}}
    assert agent.seen_context["wall_seconds"] == 600.0


@pytest.mark.asyncio
async def test_the_routers_model_wins_over_the_configured_one():
    """A flat route whose router picks a thinking model gets the floor by name — the
    model the agent runs on, not the one written in its config."""
    orch = _orch(
        agents={"jarvis": _Agent(model="gemma-4-12b")},
        routes={"jarvis": "local"},
        models={"jarvis": "qwen3:8b"},
    )
    await orch._call_agents_parallel(["jarvis"], "hi", {})
    assert orch._last_timeout_floor["jarvis"] == {"floor": "reasoning", "seconds": 600.0}
    # No router at all: the configured model still decides by name.
    orch = _orch(agents={"jarvis": _Agent(model="deepseek-r1:14b")})
    orch.llm_router = None
    await orch._call_agents_parallel(["jarvis"], "hi", {})
    assert orch._last_timeout_floor["jarvis"]["floor"] == "reasoning"


def test_nan_bool_and_zero_settings_never_collapse_the_ceiling():
    """float('nan') and True both pass float() — they must read as the default, never
    as a one-second ceiling; a reasoning setting of 0 means the default."""
    for bad in (float("nan"), "nan", True, "inf", float("-inf")):
        orch = _orch({"agents.agent_timeout_seconds": bad, "agents.reasoning_timeout_seconds": bad})
        assert orch._agent_call_timeout(route_name="local-fast") == (120.0, "flat"), bad
        assert orch._agent_call_timeout(route_name="local-deep") == (600.0, "reasoning"), bad
    orch = _orch({"agents.reasoning_timeout_seconds": 0})
    assert orch._agent_call_timeout(route_name="local-deep") == (600.0, "reasoning")
    orch = _orch({"agents.agent_timeout_seconds": 0})
    assert orch._agent_call_timeout(route_name="local-fast") == (1.0, "flat")


@pytest.mark.asyncio
async def test_tool_loop_deadline_is_raised_to_the_turn_budget():
    """The direction the reasoning floor actually uses: a loop whose own default is
    tiny finishes a slower backend when the turn hands it a larger budget."""
    server = ToolRPCServer()

    class _Slow:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            await asyncio.sleep(0.5)
            from agents.core.llm.tool_protocol import ToolTurn

            return ToolTurn(content="final", finish_reason="stop")

    async def lookup(args):
        return {"n": args.get("n")}

    server.register_tool("lookup", lookup, input_schema=_SCHEMA)
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_wall_seconds=0.05)
    reply = await runtime.run(
        agent_id="jarvis", backend=_Slow(), model="qwen3:8b", prompt="think", wall_seconds=5.0,
    )
    assert reply == "final"


@pytest.mark.asyncio
async def test_an_invalid_wall_clock_keeps_the_constructor_default():
    """Garbage in ``wall_seconds`` is not a budget: the loop keeps its own deadline
    (here 0.05 s) instead of being lifted to the one-second floor."""
    server = ToolRPCServer()

    class _Hung:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            await asyncio.sleep(600)

    async def lookup(args):
        return {"n": args.get("n")}

    server.register_tool("lookup", lookup, input_schema=_SCHEMA)
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_wall_seconds=0.05)
    for garbage in ("abc", 0, -1, True, float("nan"), float("inf")):
        t0 = time.monotonic()
        reply = await runtime.run(
            agent_id="jarvis", backend=_Hung(), model="m", prompt="p", wall_seconds=garbage,
        )
        assert reply == _DEADLINE_REPLY
        assert time.monotonic() - t0 < 0.8, garbage


# ── the pure table ───────────────────────────────────────────────────────────

def test_is_reasoning_model_table():
    for family in REASONING_FAMILIES:
        assert is_reasoning_model(family), family
        assert is_reasoning_model(f"{family}:latest"), family
    for name, cfg in MOE_MODELS.items():
        assert is_reasoning_model(name) is bool(cfg.get("supports_thinking")), name
    assert is_reasoning_model("ollama/deepseek-r1:70b")
    assert is_reasoning_model("  Qwen3-8B  ")
    assert is_reasoning_model("qwq:32b")
    assert is_reasoning_model("phi4-reasoning:14b")
    assert is_reasoning_model("phi4-mini-reasoning:3.8b")
    assert not is_reasoning_model("phi4")
    assert not is_reasoning_model("phi4:14b")
    assert not is_reasoning_model("google/gemma-4-12b")
    assert not is_reasoning_model("gemini-2.5-flash")
    assert not is_reasoning_model("")
    assert not is_reasoning_model(None)
    assert not is_reasoning_model("/")
    assert not is_reasoning_model(42)  # type: ignore[arg-type]
    assert orch_mod.REASONING_ROUTE == "local-deep"
