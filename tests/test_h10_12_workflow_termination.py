"""Tests for H10.12 — Workflow Termination Conditions."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import WorkflowEngine, evaluate_condition
from agents.core.workflows.pipeline import Pipeline, WorkflowStep


# ── condition evaluator (pure) ───────────────────────────────────────────────

def test_evaluate_condition_types():
    assert evaluate_condition({"type": "contains", "value": "OK"}, "all OK here")
    assert not evaluate_condition({"type": "contains", "value": "no"}, "yes")
    assert evaluate_condition({"type": "not_contains", "value": "fail"}, "passed")
    assert evaluate_condition({"type": "equals", "value": "DONE"}, "  DONE ")
    assert evaluate_condition({"type": "regex", "value": r"score=\d+"}, "score=42")
    assert evaluate_condition({"type": "not_empty"}, "x")
    assert not evaluate_condition({"type": "not_empty"}, "   ")


def test_evaluate_condition_failopen():
    assert evaluate_condition({}, "anything") is False
    assert evaluate_condition({"type": "regex", "value": "([bad"}, "x") is False  # bad regex
    assert evaluate_condition(None, "x") is False


# ── serialization round-trip ─────────────────────────────────────────────────

def test_step_roundtrip_with_terminate():
    s = WorkflowStep("a", "ag", "{_input}", terminate_when={"type": "contains", "value": "STOP"})
    s2 = WorkflowStep.from_dict(s.to_dict())
    assert s2.terminate_when == {"type": "contains", "value": "STOP"}
    # absent guard stays absent (no key pollution)
    assert "terminate_when" not in WorkflowStep("b", "ag", "x").to_dict()


# ── engine early-termination ─────────────────────────────────────────────────

class _MockOrch:
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return f"[{agent_override}: {text[:40]}]"


@pytest.mark.asyncio
async def test_pipeline_terminates_early():
    # step 'a' emits "[guard: ...]" which contains 'guard' → terminate before 'b'.
    p = Pipeline("p", "P", "", [
        WorkflowStep("a", "guard", "{_input}",
                     terminate_when={"type": "contains", "value": "guard"}),
        WorkflowStep("b", "next", "{a}", depends_on=["a"]),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go")
    assert ctx["_terminated"] is True
    assert ctx["_terminated_by"] == "a"
    assert "b" not in ctx                         # downstream step never ran


@pytest.mark.asyncio
async def test_pipeline_runs_full_when_guard_not_tripped():
    p = Pipeline("p", "P", "", [
        WorkflowStep("a", "ag1", "{_input}",
                     terminate_when={"type": "contains", "value": "NEVERMATCH"}),
        WorkflowStep("b", "ag2", "{a}", depends_on=["a"]),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go")
    assert ctx["_terminated"] is False
    assert "b" in ctx                             # ran to completion
