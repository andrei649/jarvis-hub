"""Tests for H10.13 — Dynamic Agent Router (conditional routing)."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import WorkflowEngine, _match_route
from agents.core.workflows.pipeline import Pipeline, WorkflowStep

ROUTES = {"billing": "gecko", "tech": "steve"}


# ── route matching (pure) ────────────────────────────────────────────────────

def test_match_route_bare_text():
    assert _match_route("this is a billing question", ROUTES) == "billing"


def test_match_route_json():
    assert _match_route('{"route": "tech"}', ROUTES) == "tech"


def test_match_route_none():
    assert _match_route("unrelated", ROUTES) == ""
    assert _match_route("", ROUTES) == ""


def test_step_roundtrip_router():
    s = WorkflowStep("r", "jarvis", "{_input}", kind="router",
                     router={"routes": ROUTES, "default": "jarvis"})
    s2 = WorkflowStep.from_dict(s.to_dict())
    assert s2.kind == "router" and s2.router["routes"] == ROUTES


# ── engine dispatch ──────────────────────────────────────────────────────────

class _RouterOrch:
    def __init__(self, decision):
        self._decision = decision
        self.dispatched = []

    async def handle_input(self, text, channel="workflow", agent_override=None):
        if agent_override == "classifier":
            return self._decision
        self.dispatched.append(agent_override)
        return f"[{agent_override} handled: {text[:20]}]"


def _pipeline():
    return Pipeline("p", "P", "", [
        WorkflowStep("route", "classifier", "classify: {_input}", kind="router",
                     router={"routes": ROUTES, "default": "jarvis",
                             "dispatch_template": "{_input}"}),
    ])


@pytest.mark.asyncio
async def test_router_dispatches_to_matched_agent():
    orch = _RouterOrch(decision="looks like billing")
    ctx = await WorkflowEngine(orch).run(_pipeline(), "my invoice is wrong")
    assert ctx["route.route"] == "billing"
    assert ctx["route.agent"] == "gecko"
    assert orch.dispatched == ["gecko"]
    assert "gecko handled" in ctx["route"]


@pytest.mark.asyncio
async def test_router_falls_back_to_default():
    orch = _RouterOrch(decision="no idea what this is")
    ctx = await WorkflowEngine(orch).run(_pipeline(), "hmm")
    assert ctx["route.route"] == "default"
    assert ctx["route.agent"] == "jarvis"
    assert orch.dispatched == ["jarvis"]


@pytest.mark.asyncio
async def test_router_no_match_no_default_returns_decision():
    p = Pipeline("p", "P", "", [
        WorkflowStep("route", "classifier", "{_input}", kind="router",
                     router={"routes": ROUTES}),       # no default
    ])
    orch = _RouterOrch(decision="totally unrelated")
    ctx = await WorkflowEngine(orch).run(p, "x")
    assert ctx["route.agent"] == ""
    assert orch.dispatched == []                       # nothing dispatched
    assert ctx["route"] == "totally unrelated"
