"""Tests for H5.6 — Multi-Agent Workflows.

Pipeline topology, parallel execution, template rendering, and engine
integration. All offline — orchestrator is mocked.
"""
import asyncio
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.workflows.pipeline import Pipeline, WorkflowStep
from agents.core.workflows.engine import WorkflowEngine, _render
from agents.core.workflows.registry import WorkflowRegistry


# ── helpers ───────────────────────────────────────────────────────────────────

class _MockOrch:
    """Minimal orchestrator mock — records calls, returns "[<agent>: <text>]"."""
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def handle_input(self, text: str, channel: str = "workflow", agent_override: str = None) -> str:
        self.calls.append((agent_override or "?", text))
        return f"[{agent_override}: {text[:40]}]"


def _make_pipeline(*steps) -> Pipeline:
    return Pipeline(id="test", name="Test", description="", steps=list(steps))


# ── Task 1: pipeline topology ─────────────────────────────────────────────────

def test_linear_pipeline_batches():
    p = _make_pipeline(
        WorkflowStep("a", "ag1", "{_input}"),
        WorkflowStep("b", "ag2", "{a}", depends_on=["a"]),
        WorkflowStep("c", "ag3", "{b}", depends_on=["b"]),
    )
    batches = p.execution_batches()
    assert len(batches) == 3
    assert [s.id for b in batches for s in b] == ["a", "b", "c"]


def test_parallel_pipeline_batches():
    p = _make_pipeline(
        WorkflowStep("left",  "ag1", "{_input}"),
        WorkflowStep("right", "ag2", "{_input}"),
        WorkflowStep("merge", "ag3", "{left} + {right}", depends_on=["left", "right"]),
    )
    batches = p.execution_batches()
    assert len(batches) == 2
    first_ids = {s.id for s in batches[0]}
    assert first_ids == {"left", "right"}
    assert batches[1][0].id == "merge"


def test_cycle_raises():
    p = _make_pipeline(
        WorkflowStep("a", "ag1", "x", depends_on=["b"]),
        WorkflowStep("b", "ag2", "y", depends_on=["a"]),
    )
    with pytest.raises(ValueError, match="Cycle"):
        p.execution_batches()


def test_pipeline_to_dict():
    s = WorkflowStep("s1", "gecko", "{_input}", depends_on=[])
    p = Pipeline("pid", "Test", "desc", [s])
    d = p.to_dict()
    assert d["id"] == "pid"
    assert d["steps"][0]["agent_id"] == "gecko"


# ── Task 2: template rendering ────────────────────────────────────────────────

def test_render_basic():
    assert _render("Hello {_input}!", {"_input": "world"}) == "Hello world!"


def test_render_step_reference():
    ctx = {"_input": "X", "step1": "result_one"}
    assert _render("{step1} and {_input}", ctx) == "result_one and X"


def test_render_unknown_key_empty():
    assert _render("{missing}", {}) == ""


# ── Task 3: engine execution ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_linear_pipeline():
    orch = _MockOrch()
    engine = WorkflowEngine(orch)
    p = _make_pipeline(
        WorkflowStep("a", "gecko", "balance: {_input}"),
        WorkflowStep("b", "veronica", "summarize: {a}", depends_on=["a"]),
    )
    result = await engine.run(p, "check finances")
    assert result["_ok"] is True
    assert "a" in result and "b" in result
    assert "gecko" in result["a"]
    assert "veronica" in result["b"]
    assert result["_elapsed"] >= 0


@pytest.mark.asyncio
async def test_engine_parallel_steps_both_called():
    orch = _MockOrch()
    engine = WorkflowEngine(orch)
    p = _make_pipeline(
        WorkflowStep("sec",  "ultron", "security status"),
        WorkflowStep("sys",  "steve",  "system status"),
        WorkflowStep("dig",  "jarvis", "{sec} + {sys}", depends_on=["sec", "sys"]),
    )
    result = await engine.run(p, "")
    agents_called = [c[0] for c in orch.calls]
    assert "ultron" in agents_called
    assert "steve" in agents_called
    assert "jarvis" in agents_called
    assert result["_ok"] is True


@pytest.mark.asyncio
async def test_engine_passthrough_step():
    orch = _MockOrch()
    engine = WorkflowEngine(orch)
    p = _make_pipeline(
        WorkflowStep("pt", "_passthrough", "raw: {_input}"),
    )
    result = await engine.run(p, "hello")
    assert result["pt"] == "raw: hello"
    assert len(orch.calls) == 0   # no LLM call for passthrough


@pytest.mark.asyncio
async def test_engine_marks_errors():
    call_count = 0

    class _BrokenOrch:
        async def handle_input(self, text, channel="workflow", agent_override=None):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

    engine = WorkflowEngine(_BrokenOrch())
    p = _make_pipeline(WorkflowStep("bad", "broken_agent", "{_input}"))
    result = await engine.run(p, "test")
    assert result["_ok"] is False
    assert "bad" in result["_errors"]
    assert result["bad"].startswith("[error:")


# ── Task 4: registry ──────────────────────────────────────────────────────────

def test_registry_has_builtin_pipelines():
    reg = WorkflowRegistry()
    assert len(reg.ids()) >= 3
    assert "finance_report" in reg.ids()
    assert "research_and_brief" in reg.ids()
    assert "security_digest" in reg.ids()


def test_registry_get_and_register():
    reg = WorkflowRegistry()
    custom = Pipeline("custom", "Custom", "desc", [
        WorkflowStep("s1", "jarvis", "say {_input}")
    ])
    reg.register(custom)
    assert reg.get("custom") is custom
    assert reg.get("nonexistent") is None


def test_registry_list_returns_dicts():
    reg = WorkflowRegistry()
    items = reg.list()
    assert all(isinstance(i, dict) for i in items)
    assert all("id" in i and "steps" in i for i in items)


# ── Task 5: built-in pipeline topology sanity ─────────────────────────────────

@pytest.mark.asyncio
async def test_finance_report_pipeline_topology():
    reg = WorkflowRegistry()
    p = reg.get("finance_report")
    assert p is not None
    batches = p.execution_batches()
    # balance + health in parallel, summary depends on both
    first = {s.id for s in batches[0]}
    assert "balance" in first and "health" in first
    assert batches[1][0].id == "summary"


@pytest.mark.asyncio
async def test_security_digest_parallel_then_synthesize():
    reg = WorkflowRegistry()
    p = reg.get("security_digest")
    batches = p.execution_batches()
    first = {s.id for s in batches[0]}
    assert "security" in first and "system" in first
    assert batches[1][0].id == "digest"
