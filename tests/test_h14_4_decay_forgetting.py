"""Tests for H14.4 — Decay-based forgetting (ACT-R + dependency-aware delete)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.decay import DecayMemory, activation


# ── activation maths ─────────────────────────────────────────────────────────

def test_activation_recency_and_frequency():
    now = 1000.0
    recent = activation([999.0], now)
    old = activation([100.0], now)
    assert recent > old                       # recent accessed → higher
    frequent = activation([999.0, 998.0, 990.0], now)
    assert frequent > recent                  # more accesses → higher
    assert activation([], now) == float("-inf")


# ── ranking ──────────────────────────────────────────────────────────────────

def test_ranking_orders_by_activation(tmp_path):
    d = DecayMemory(path=tmp_path / "d.json")
    d.add("hot", ts=950); d.add("hot", ts=990)
    d.add("cold", ts=100)
    ranking = d.ranking(now=1000)
    assert ranking[0]["id"] == "hot"
    assert ranking[-1]["id"] == "cold"


def test_forget_candidates_threshold(tmp_path):
    d = DecayMemory(path=tmp_path / "d.json")
    d.add("stale", ts=1)                       # long ago → low activation
    d.add("fresh", ts=999)
    cands = {c["id"] for c in d.forget_candidates(threshold=0.0, now=1000)}
    assert "stale" in cands and "fresh" not in cands


# ── dependency-aware deletion ────────────────────────────────────────────────

def test_forget_removes_transitive_dependents(tmp_path):
    d = DecayMemory(path=tmp_path / "d.json")
    d.add("A", ts=100)
    d.add("B", ts=100, depends_on=["A"])      # B derived from A
    d.add("C", ts=100, depends_on=["B"])      # C derived from B
    d.add("X", ts=100)                         # unrelated
    removed = set(d.forget("A"))
    assert removed == {"A", "B", "C"}          # anti-recontamination cascade
    assert d.score("X", now=200) > float("-inf")   # X untouched
    assert d.forget("nope") == []              # missing → []


def test_persistence(tmp_path):
    p = tmp_path / "d.json"
    d = DecayMemory(path=p)
    d.add("m", ts=500, depends_on=["dep"], label="note")
    d2 = DecayMemory(path=p)
    assert d2.score("m", now=600) > float("-inf")
    assert d2.ranking(now=600)[0]["label"] in ("note", "")


# ── endpoints ────────────────────────────────────────────────────────────────

def test_decay_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "decay", None) is None:
            return
        web.orch.decay.clear()
        web.orch.decay.add("e1", label="first")
        assert c.get("/api/memory/decay/ranking").status_code == 200
        assert c.get("/api/memory/decay/candidates", params={"threshold": 100}).status_code == 200
        assert c.post("/api/memory/decay/forget", json={}).status_code == 400
        ok = c.post("/api/memory/decay/forget", json={"id": "e1"})
        assert ok.status_code == 200 and "e1" in ok.json()["removed"]
        assert c.post("/api/memory/decay/forget", json={"id": "e1"}).status_code == 404
