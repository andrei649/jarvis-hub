"""Tests for H12.6 — Incremental KG updates."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.incremental import extract_triples, IncrementalKGUpdater
from agents.core.memory.graph import InMemoryGraph
from agents.core.memory.bitemporal import BiTemporalKG


# ── extraction ───────────────────────────────────────────────────────────────

def test_extract_possessive():
    t = extract_triples("Andrei's daughter is Cosmina.")
    assert ("Andrei", "daughter", "Cosmina") in t


def test_extract_lives_and_works():
    t = extract_triples("Andrei lives in Cluj. Andrei works at Raiffeisen.")
    assert ("Andrei", "lives_in", "Cluj") in t
    assert ("Andrei", "works_at", "Raiffeisen") in t


def test_extract_skips_stopwords_and_self():
    # "It is a thing" → subject 'It' is a stopword → skipped
    assert extract_triples("It is a thing") == []
    # no self-referential triples
    assert all(s.lower() != o.lower() for s, _, o in extract_triples("Bob is Bob"))


def test_extract_empty():
    assert extract_triples("") == []
    assert extract_triples("lowercase words only here") == []


# ── updater writes to graph + bitemporal ─────────────────────────────────────

def test_ingest_writes_to_graph_and_bitemporal(tmp_path):
    g = InMemoryGraph()
    bt = BiTemporalKG(path=tmp_path / "bt.json")
    up = IncrementalKGUpdater(g, bitemporal=bt)
    n = up.ingest("Andrei lives in Cluj.")
    assert n == 1
    # graph has the relation
    rels = g.get_relations("Andrei")
    assert any(r["relation"] == "lives_in" and r["target"] == "Cluj" for r in rels)
    # bitemporal has the fact
    assert any(f["object"] == "Cluj" for f in bt.current("Andrei", "lives_in"))
    assert up.last_added[0]["object"] == "Cluj"


def test_ingest_contradiction_invalidates_in_bitemporal(tmp_path):
    g = InMemoryGraph()
    bt = BiTemporalKG(path=tmp_path / "bt.json")
    up = IncrementalKGUpdater(g, bitemporal=bt)
    up.ingest("Andrei lives in Bucharest.")
    up.ingest("Andrei lives in Cluj.")
    cur = [f["object"] for f in bt.current("Andrei", "lives_in")]
    assert cur == ["Cluj"]                        # single current value
    assert len(bt.history("Andrei", "lives_in")) == 2   # history kept


def test_ingest_tolerates_no_graph():
    up = IncrementalKGUpdater(None, bitemporal=None)
    assert up.ingest("Andrei lives in Cluj.") == 1   # counted, no crash


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_ingest_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "kg_updater", None) is None:
            return
        assert c.post("/api/kg/ingest", json={}).status_code == 400
        r = c.post("/api/kg/ingest", json={"text": "Veronica works at Digitaholic."})
        assert r.status_code == 200
        assert r.json()["added"] >= 1
