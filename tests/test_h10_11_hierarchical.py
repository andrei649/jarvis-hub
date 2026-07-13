"""Tests for H10.11 — Hierarchical Workflow Manager."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.hierarchical import HierarchicalManager


class _Orch:
    """Scripted orchestrator: per-agent reply or callable."""
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []

    async def handle_input(self, text, channel="workflow", agent_override=None):
        self.calls.append((agent_override, text))
        b = self.behavior.get(agent_override, f"{agent_override}:ok")
        return b(text, self.calls) if callable(b) else b


CREW = [
    {"id": "research", "agent": "researcher", "prompt": "research {_goal}"},
    {"id": "write", "agent": "writer", "prompt": "write using {research}"},
]


# ── happy path ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_runs_crew_validates_and_synthesizes():
    orch = _Orch({"researcher": "facts", "writer": "draft", "jarvis": "FINAL"})
    out = await HierarchicalManager(orch, manager_agent="jarvis").run("a report", CREW)
    assert out["ok"] is True
    assert [m["id"] for m in out["members"]] == ["research", "write"]
    assert out["members"][0]["output"] == "facts"
    assert out["final"] == "FINAL"
    assert out["redistributed"] == []
    # manager synthesized last, seeing both crew outputs
    assert orch.calls[-1][0] == "jarvis" and "facts" in orch.calls[-1][1]


@pytest.mark.asyncio
async def test_context_flows_between_members():
    orch = _Orch({"researcher": "DATA", "writer": lambda t, c: f"wrote[{t}]", "jarvis": "F"})
    out = await HierarchicalManager(orch).run("g", CREW)
    assert "using DATA" in out["members"][1]["output"]


# ── validation + redistribution ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redistributes_to_fallback_on_failure():
    # primary agent errors; fallback succeeds
    def flaky(_t, _c):
        return "[error:boom]"
    orch = _Orch({"primary": flaky, "backup": "recovered", "jarvis": "F"})
    crew = [{"id": "task", "agent": "primary", "fallback": "backup", "prompt": "{_goal}"}]
    out = await HierarchicalManager(orch, max_retries=1).run("g", crew)
    m = out["members"][0]
    assert m["ok"] is True and m["agent"] == "backup"
    assert m["redistributed"] is True and m["attempts"] == 2
    assert out["redistributed"] == ["task"]


@pytest.mark.asyncio
async def test_retries_same_agent_then_succeeds():
    state = {"n": 0}
    def recover(_t, _c):
        state["n"] += 1
        return "[error:first]" if state["n"] == 1 else "fixed"
    orch = _Orch({"w": recover, "jarvis": "F"})
    out = await HierarchicalManager(orch, max_retries=2).run("g",
                                                              [{"id": "t", "agent": "w"}])
    assert out["members"][0]["ok"] is True and out["members"][0]["attempts"] == 2


@pytest.mark.asyncio
async def test_exhausted_retries_marks_not_ok():
    orch = _Orch({"w": lambda t, c: "[error:always]", "jarvis": "F"})
    out = await HierarchicalManager(orch, max_retries=1).run("g", [{"id": "t", "agent": "w"}])
    assert out["members"][0]["ok"] is False and out["ok"] is False


@pytest.mark.asyncio
async def test_agent_exception_detail_is_not_returned_to_client():
    secret = "database password leaked from C:\\private\\settings.ini"

    def explode(_text, _calls):
        raise RuntimeError(secret)

    orch = _Orch({"w": explode, "jarvis": "F"})
    out = await HierarchicalManager(orch, max_retries=0).run(
        "g", [{"id": "t", "agent": "w"}]
    )
    member_output = out["members"][0]["output"]
    assert member_output.startswith("[error:")
    assert secret not in member_output


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_hierarchical_endpoint():
    from fastapi.testclient import TestClient
    from agents import web
    with TestClient(web.app) as c:
        assert c.post("/api/workflows/hierarchical", json={"goal": "g"}).status_code == 400
        r = c.post("/api/workflows/hierarchical",
                   json={"goal": "say hi", "crew": [{"id": "s", "agent": "jarvis"}]})
        assert r.status_code == 200
        body = r.json()
        assert "final" in body and "members" in body and len(body["members"]) == 1
