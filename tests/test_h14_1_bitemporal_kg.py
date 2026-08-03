"""Tests for H14.1 — Bi-temporal Knowledge Graph."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nerva_e2_0_checks import run_e2_0_checks  # noqa: E402

from agents.core.memory.bitemporal import BiTemporalKG  # noqa: E402


def test_contradiction_invalidates_not_deletes(tmp_path):
    kg = BiTemporalKG(path=tmp_path / "bt.json")
    kg.add_fact("andrei", "lives_in", "Bucharest", valid_from=100)
    kg.add_fact("andrei", "lives_in", "Cluj", valid_from=200)
    # both versions are retained in history
    hist = kg.history("andrei", "lives_in")
    assert [h["object"] for h in hist] == ["Bucharest", "Cluj"]
    # the old one was closed at the new fact's valid_from (not removed)
    assert hist[0]["valid_to"] == 200
    assert hist[0]["invalidated_at"] == 200
    assert hist[1]["valid_to"] is None


def test_as_of_valid_time_recall(tmp_path):
    kg = BiTemporalKG(path=tmp_path / "bt.json")
    kg.add_fact("andrei", "lives_in", "Bucharest", valid_from=100)
    kg.add_fact("andrei", "lives_in", "Cluj", valid_from=200)
    # at t=150 → Bucharest; at t=250 → Cluj
    assert [f["object"] for f in kg.as_of(150, "andrei", "lives_in")] == ["Bucharest"]
    assert [f["object"] for f in kg.as_of(250, "andrei", "lives_in")] == ["Cluj"]
    # before any fact → nothing
    assert kg.as_of(50, "andrei", "lives_in") == []


def test_current_reflects_latest(tmp_path):
    kg = BiTemporalKG(path=tmp_path / "bt.json")
    kg.add_fact("andrei", "drives", "BMW", valid_from=100)
    kg.add_fact("andrei", "drives", "Tesla", valid_from=200)
    cur = kg.current("andrei", "drives")
    assert [f["object"] for f in cur] == ["Tesla"]


def test_known_as_of_transaction_time(tmp_path):
    kg = BiTemporalKG(path=tmp_path / "bt.json")
    # fact about the past, but only ingested later
    kg.add_fact("andrei", "born_in", "Iasi", valid_from=0, ingested_at=500)
    # we didn't know it at t=400
    assert kg.known_as_of(400, "andrei") == []
    assert len(kg.known_as_of(600, "andrei")) == 1
    run_e2_0_checks(tmp_path)


def test_multi_valued_does_not_invalidate(tmp_path):
    kg = BiTemporalKG(path=tmp_path / "bt.json")
    kg.add_fact("andrei", "owns", "guitar", valid_from=100, multi=True)
    kg.add_fact("andrei", "owns", "piano", valid_from=200, multi=True)
    cur = {f["object"] for f in kg.current("andrei", "owns")}
    assert cur == {"guitar", "piano"}      # both still valid


def test_explicit_invalidate_and_persistence(tmp_path):
    p = tmp_path / "bt.json"
    kg = BiTemporalKG(path=p)
    kg.add_fact("andrei", "status", "active", valid_from=100)
    assert kg.invalidate("andrei", "status", "active", at=300) is True
    # survives reload, and is gone from current
    kg2 = BiTemporalKG(path=p)
    assert kg2.current("andrei", "status") == []
    assert len(kg2.history("andrei")) == 1


def test_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "bitemporal", None) is None:
            return
        web.orch.bitemporal.clear()
        bad = c.post("/api/kg/facts", json={"subject": "x"})
        assert bad.status_code == 400
        ok = c.post("/api/kg/facts", json={
            "subject": "tkg", "predicate": "lives_in", "object": "Cluj", "valid_from": 200})
        assert ok.status_code == 200
        asof = c.get("/api/kg/facts/as-of", params={"at": 250, "subject": "tkg"})
        assert asof.status_code == 200
        assert any(f["object"] == "Cluj" for f in asof.json()["facts"])
        hist = c.get("/api/kg/facts/history", params={"subject": "tkg"})
        assert hist.status_code == 200 and len(hist.json()["history"]) == 1
