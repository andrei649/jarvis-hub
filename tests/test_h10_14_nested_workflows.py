"""Tests for H10.14 — Nested Workflow Steps (recursive decomposition)."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline, WorkflowStep


class _MockOrch:
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return f"{agent_override}({text})"


def _subflow_cfg():
    return {
        "steps": [
            {"id": "outline", "agent_id": "planner", "prompt_template": "plan: {_input}"},
            {"id": "draft", "agent_id": "writer", "prompt_template": "write: {outline}",
             "depends_on": ["outline"]},
        ],
        "output": "draft",
    }


# ── basic nesting ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subflow_runs_and_exposes_output():
    p = Pipeline("p", "P", "", [
        WorkflowStep("compose", "_passthrough", "{_input}", kind="subflow", subflow=_subflow_cfg()),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "a topic")
    # final sub-step output bubbles up as the step's output
    assert ctx["compose"] == "writer(write: planner(plan: a topic))"
    # sub-step outputs exposed namespaced
    assert ctx["compose.outline"] == "planner(plan: a topic)"
    assert ctx["_subflows"]["compose"]["ok"] is True
    assert ctx["_ok"] is True


@pytest.mark.asyncio
async def test_subflow_chains_with_outer_steps():
    p = Pipeline("p", "P", "", [
        WorkflowStep("prep", "pre", "{_input}"),
        WorkflowStep("compose", "_passthrough", "{prep}", depends_on=["prep"],
                     kind="subflow", subflow=_subflow_cfg()),
        WorkflowStep("post", "fin", "finalize {compose}", depends_on=["compose"]),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go")
    assert ctx["compose"].startswith("writer(write: planner(plan: pre(go)")
    assert ctx["post"].startswith("fin(finalize writer(")


# ── errors / edges ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_subflow_returns_error():
    bad = {"steps": [
        {"id": "a", "agent_id": "x", "prompt_template": "{b}", "depends_on": ["b"]},
        {"id": "b", "agent_id": "y", "prompt_template": "{a}", "depends_on": ["a"]},
    ]}
    p = Pipeline("p", "P", "", [
        WorkflowStep("s", "_passthrough", "{_input}", kind="subflow", subflow=bad),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go")
    assert ctx["s"].startswith("[error:subflow:")
    assert "s" in ctx["_errors"]


@pytest.mark.asyncio
async def test_empty_subflow_returns_input_value():
    p = Pipeline("p", "P", "", [
        WorkflowStep("s", "_passthrough", "x", kind="subflow", subflow={"steps": []}),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go")
    assert ctx["s"] == ""        # no prior value for s → empty


@pytest.mark.asyncio
async def test_depth_cap():
    p = Pipeline("p", "P", "", [
        WorkflowStep("s", "_passthrough", "{_input}", kind="subflow", subflow=_subflow_cfg()),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go", _depth=5)
    assert ctx["s"].startswith("[error:subflow: max nesting depth")


def test_step_roundtrip_subflow():
    s = WorkflowStep("s", "_passthrough", "{_input}", kind="subflow", subflow=_subflow_cfg())
    s2 = WorkflowStep.from_dict(s.to_dict())
    assert s2.kind == "subflow" and s2.subflow["output"] == "draft"
