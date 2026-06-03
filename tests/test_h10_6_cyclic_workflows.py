"""Tests for H10.6 — Cyclic Workflow Support (loop-back edges)."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline, WorkflowStep


class _CountingOrch:
    """`refiner` returns 'DONE' on the Nth call, else 'draft <call>'."""
    def __init__(self, done_on=2):
        self.calls = 0
        self.done_on = done_on

    async def handle_input(self, text, channel="workflow", agent_override=None):
        if agent_override == "refiner":
            self.calls += 1
            return "DONE" if self.calls >= self.done_on else f"draft {self.calls}"
        return f"[{agent_override}]"


def _loop_pipeline(max_iterations=5, done_on=2):
    return Pipeline("p", "P", "", [
        WorkflowStep("refine_loop", "_passthrough", "{_input}", kind="loop", loop={
            "max_iterations": max_iterations,
            "until": {"type": "contains", "value": "DONE"},
            "steps": [
                {"id": "refiner", "agent_id": "refiner",
                 "prompt_template": "improve: {refiner}"},
            ],
        }),
    ]), _CountingOrch(done_on=done_on)


# ── exit conditions ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_loop_exits_on_condition():
    p, orch = _loop_pipeline(max_iterations=5, done_on=2)
    ctx = await WorkflowEngine(orch).run(p, "go")
    assert ctx["refine_loop"] == "DONE"
    assert ctx["_loops"]["refine_loop"] == {"iterations": 2, "exited_by": "condition"}
    assert orch.calls == 2                            # stopped as soon as DONE


@pytest.mark.asyncio
async def test_loop_hits_max_iterations():
    p, orch = _loop_pipeline(max_iterations=3, done_on=99)   # never says DONE
    ctx = await WorkflowEngine(orch).run(p, "go")
    assert ctx["_loops"]["refine_loop"]["iterations"] == 3
    assert ctx["_loops"]["refine_loop"]["exited_by"] == "max_iterations"
    assert orch.calls == 3


@pytest.mark.asyncio
async def test_loop_exposes_iteration_counter():
    # body transform records the current iteration token from ctx
    p = Pipeline("p", "P", "", [
        WorkflowStep("lp", "_passthrough", "", kind="loop", loop={
            "max_iterations": 4,
            "steps": [
                {"id": "echo", "agent_id": "_passthrough",
                 "prompt_template": "iter={lp._iter}"},
            ],
        }),
    ])

    class _O:
        async def handle_input(self, *a, **k):
            return ""
    ctx = await WorkflowEngine(_O()).run(p, "go")
    assert ctx["lp"] == "iter=4"                       # last pass
    assert ctx["_loops"]["lp"]["iterations"] == 4


# ── safety / edges ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_body_is_noop():
    p = Pipeline("p", "P", "", [
        WorkflowStep("lp", "_passthrough", "x", kind="loop", loop={"steps": []}),
    ])

    class _O:
        async def handle_input(self, *a, **k):
            return "y"
    ctx = await WorkflowEngine(_O()).run(p, "go")
    assert "_loops" not in ctx or "lp" not in ctx.get("_loops", {})


@pytest.mark.asyncio
async def test_max_iterations_clamped():
    p = Pipeline("p", "P", "", [
        WorkflowStep("lp", "_passthrough", "", kind="loop", loop={
            "max_iterations": 9999,
            "steps": [{"id": "b", "agent_id": "_passthrough", "prompt_template": "x"}],
        }),
    ])

    class _O:
        async def handle_input(self, *a, **k):
            return "x"
    ctx = await WorkflowEngine(_O()).run(p, "go")
    assert ctx["_loops"]["lp"]["iterations"] == 100    # hard cap


def test_step_roundtrip_loop():
    s = WorkflowStep("lp", "_passthrough", "{_input}", kind="loop",
                     loop={"max_iterations": 2, "steps": [{"id": "b", "agent_id": "a", "prompt_template": "t"}]})
    s2 = WorkflowStep.from_dict(s.to_dict())
    assert s2.kind == "loop" and s2.loop["max_iterations"] == 2
