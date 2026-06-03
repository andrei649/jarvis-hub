"""Tests for H10.17 — Per-Agent Run History."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.run_history import RunHistory


def test_record_and_list_most_recent_first(tmp_path):
    h = RunHistory(path=tmp_path / "rh.json")
    h.record("jarvis", input_text="hi", output_text="hello", latency_ms=120, ok=True)
    h.record("jarvis", input_text="bye", output_text="cya", latency_ms=80, ok=True)
    runs = h.list("jarvis")
    assert len(runs) == 2
    assert runs[0]["input_preview"] == "bye"      # most recent first
    assert runs[0]["latency_ms"] == 80.0


def test_ring_buffer_caps_per_agent(tmp_path):
    h = RunHistory(path=tmp_path / "rh.json", max_per_agent=3)
    for i in range(5):
        h.record("stark", input_text=f"q{i}", ok=True)
    runs = h.list("stark", limit=100)
    assert len(runs) == 3                          # capped
    assert runs[0]["input_preview"] == "q4"


def test_agents_rollup(tmp_path):
    h = RunHistory(path=tmp_path / "rh.json")
    h.record("a", ok=True, latency_ms=100)
    h.record("a", ok=False, latency_ms=200)
    h.record("b", ok=True, latency_ms=50)
    rollup = {r["agent_id"]: r for r in h.agents()}
    assert rollup["a"]["runs"] == 2
    assert rollup["a"]["ok_rate"] == 0.5
    assert rollup["a"]["avg_latency_ms"] == 150.0
    assert rollup["b"]["ok_rate"] == 1.0


def test_persistence_and_clear(tmp_path):
    p = tmp_path / "rh.json"
    h = RunHistory(path=p)
    h.record("frigga", input_text="x")
    assert RunHistory(path=p).list("frigga")        # survives reload
    h.clear("frigga")
    assert RunHistory(path=p).list("frigga") == []


def test_history_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "run_history", None) is not None:
            web.orch.run_history.record("veronica", input_text="ping", ok=True)
        r1 = c.get("/api/agents/history")
        assert r1.status_code == 200
        assert "agents" in r1.json()
        r2 = c.get("/api/agents/veronica/history")
        assert r2.status_code == 200
        body = r2.json()
        assert body["agent_id"] == "veronica"
        assert isinstance(body["runs"], list)
