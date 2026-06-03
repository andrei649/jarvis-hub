"""Tests for H10.2 — Visual Workflow Trace Overlay."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline, WorkflowStep


class _MockOrch:
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return f"[{agent_override}: {text[:30]}]"


def _pipeline():
    return Pipeline("demo", "Demo", "", [
        WorkflowStep("a", "ag1", "{_input}"),
        WorkflowStep("b", "ag2", "{a}", depends_on=["a"]),
    ])


@pytest.mark.asyncio
async def test_run_emits_per_step_trace():
    ctx = await WorkflowEngine(_MockOrch()).run(_pipeline(), "go")
    trace = ctx["_trace"]
    assert [t["step"] for t in trace] == ["a", "b"]
    for t in trace:
        assert {"step", "kind", "agent", "input_preview",
                "output_preview", "elapsed_ms", "ok"} <= set(t)
        assert t["ok"] is True
        assert t["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_recent_runs_ring_most_recent_first():
    engine = WorkflowEngine(_MockOrch())
    await engine.run(_pipeline(), "first")
    await engine.run(_pipeline(), "second")
    recent = engine.recent()
    assert len(recent) == 2
    assert recent[0]["pipeline_id"] == "demo"
    # most-recent first → 'second' run's first step input mentions 'second'
    assert "second" in recent[0]["steps"][0]["input_preview"]
    assert recent[0]["ok"] is True
    assert "elapsed" in recent[0]


@pytest.mark.asyncio
async def test_trace_marks_failed_step():
    class _BrokenOrch:
        async def handle_input(self, text, channel="workflow", agent_override=None):
            raise RuntimeError("boom")

    p = Pipeline("p", "P", "", [WorkflowStep("a", "ag", "{_input}")])
    ctx = await WorkflowEngine(_BrokenOrch()).run(p, "go")
    assert ctx["_trace"][0]["ok"] is False


def test_traces_endpoint():
    from fastapi.testclient import TestClient
    from agents import web
    with TestClient(web.app) as c:
        r = c.get("/api/workflows/traces")
        assert r.status_code == 200
        assert "runs" in r.json()
