"""Tests for H10.9 — Python Flow Decorator API."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.flow_api import jarvis_flow, step, listen, router, build_flow
from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline


@jarvis_flow(name="Research Flow", description="gather then summarize")
class _ResearchFlow:
    @step
    def gather(self):
        return {"agent": "researcher", "prompt": "research: {_input}"}

    @listen("gather")
    def summarize(self):
        return {"agent": "writer", "prompt": "summarize: {gather}"}

    @step(kind="transform", depends_on=["summarize"])
    def shout(self):
        return {"transform": {"op": "formatter", "mode": "upper"}, "prompt": "{summarize}"}


# ── compilation ──────────────────────────────────────────────────────────────

def test_build_flow_produces_pipeline():
    p = build_flow(_ResearchFlow)
    assert isinstance(p, Pipeline)
    assert p.name == "Research Flow" and p.id == "research-flow"
    ids = [s.id for s in p.steps]
    assert ids == ["gather", "summarize", "shout"]      # definition order


def test_dependencies_and_kinds():
    p = build_flow(_ResearchFlow)
    by_id = {s.id: s for s in p.steps}
    assert by_id["gather"].depends_on == []
    assert by_id["summarize"].depends_on == ["gather"]
    assert by_id["shout"].kind == "transform"
    assert by_id["shout"].transform["mode"] == "upper"


def test_router_kind():
    @jarvis_flow(name="Trii")
    class _RouteFlow:
        @step
        def classify(self):
            return {"agent": "classifier", "prompt": "{_input}"}

        @router("classify")
        def route(self):
            return {"router": {"routes": {"billing": "gecko"}, "default": "jarvis"},
                    "prompt": "{classify}"}

    p = build_flow(_RouteFlow)
    route = [s for s in p.steps if s.id == "route"][0]
    assert route.kind == "router" and route.router["default"] == "jarvis"


# ── errors ───────────────────────────────────────────────────────────────────

def test_non_flow_rejected():
    class _Plain:
        pass
    with pytest.raises(ValueError):
        build_flow(_Plain)


def test_empty_flow_rejected():
    @jarvis_flow(name="Empty")
    class _Empty:
        pass
    with pytest.raises(ValueError):
        build_flow(_Empty)


def test_cycle_detected():
    @jarvis_flow(name="Cyclic")
    class _Cyclic:
        @listen("b")
        def a(self):
            return {"agent": "x", "prompt": "{b}"}

        @listen("a")
        def b(self):
            return {"agent": "y", "prompt": "{a}"}

    with pytest.raises(ValueError):
        build_flow(_Cyclic)


# ── end-to-end via engine ────────────────────────────────────────────────────

class _MockOrch:
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return f"{agent_override}:done"


@pytest.mark.asyncio
async def test_compiled_flow_runs():
    p = build_flow(_ResearchFlow)
    ctx = await WorkflowEngine(_MockOrch()).run(p, "topic")
    assert ctx["gather"] == "researcher:done"
    assert ctx["shout"] == "WRITER:DONE"               # transform applied
    assert ctx["_ok"] is True
