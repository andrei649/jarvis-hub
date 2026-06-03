"""Tests for H10.15 — Critic Agent node (reflexion / self-correction)."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline, WorkflowStep


def test_step_roundtrip_kind_and_critic():
    s = WorkflowStep("c", "judge", "review {draft}", depends_on=["draft"],
                     kind="critic", critic={"target": "draft", "pass_threshold": 0.8})
    s2 = WorkflowStep.from_dict(s.to_dict())
    assert s2.kind == "critic"
    assert s2.critic["target"] == "draft"
    # default-kind step doesn't serialize 'kind'
    assert "kind" not in WorkflowStep("x", "ag", "y").to_dict()


class _ScriptedOrch:
    """Critic ('judge') returns scripted scores; target ('writer') logs re-runs."""
    def __init__(self, scores):
        self._scores = list(scores)
        self.writer_calls = 0

    async def handle_input(self, text, channel="workflow", agent_override=None):
        if agent_override == "judge":
            s = self._scores.pop(0)
            passed = s >= 0.7
            return f'{{"score": {s}, "pass": {str(passed).lower()}, "feedback": "fix it"}}'
        if agent_override == "writer":
            self.writer_calls += 1
            return f"draft v{self.writer_calls}"
        return f"[{agent_override}]"


def _pipeline():
    return Pipeline("p", "P", "", [
        WorkflowStep("draft", "writer", "{_input}"),
        WorkflowStep("review", "judge", "score this: {draft}", depends_on=["draft"],
                     kind="critic", critic={"target": "draft", "pass_threshold": 0.7, "max_retries": 2}),
    ])


@pytest.mark.asyncio
async def test_critic_passes_first_try():
    orch = _ScriptedOrch(scores=[0.9])
    ctx = await WorkflowEngine(orch).run(_pipeline(), "write")
    assert ctx["_critics"]["review"]["passed"] is True
    assert ctx["_critics"]["review"]["attempts"] == 1
    assert orch.writer_calls == 1                  # no re-run needed
    assert ctx["review.score"] == "0.9"


@pytest.mark.asyncio
async def test_critic_retries_then_passes():
    orch = _ScriptedOrch(scores=[0.3, 0.85])      # fail then pass
    ctx = await WorkflowEngine(orch).run(_pipeline(), "write")
    assert ctx["_critics"]["review"]["passed"] is True
    assert ctx["_critics"]["review"]["attempts"] == 2
    assert orch.writer_calls == 2                  # target re-run once


@pytest.mark.asyncio
async def test_critic_exhausts_retries():
    orch = _ScriptedOrch(scores=[0.1, 0.2, 0.3])  # never passes
    ctx = await WorkflowEngine(orch).run(_pipeline(), "write")
    crit = ctx["_critics"]["review"]
    assert crit["passed"] is False
    assert crit["attempts"] == 3                   # 1 + max_retries(2)
    assert orch.writer_calls == 3                  # re-run on each failure
