"""Tests for H12.3 — Knowledge-graph queryable & editable."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.graph import InMemoryGraph


# ── graph backend: list / delete ────────────────────────────────────────────

def test_list_entities():
    g = InMemoryGraph()
    g.add_entity("Andrei", "person")
    g.add_entity("Jarvis", "project")
    names = {e["name"] for e in g.list_entities()}
    assert {"Andrei", "Jarvis"} <= names


def test_delete_entity_removes_relations():
    g = InMemoryGraph()
    g.add_relation("Andrei", "owns", "BMW")
    assert g.get_entity("BMW") is not None
    assert g.delete_entity("BMW") is True
    assert g.get_entity("BMW") is None
    # relation touching BMW is gone
    assert g.get_relations("Andrei") == []
    # deleting a missing entity → False
    assert g.delete_entity("Ghost") is False


def test_delete_relation():
    g = InMemoryGraph()
    g.add_relation("Andrei", "owns", "BMW")
    g.add_relation("Andrei", "likes", "BMW")
    assert g.delete_relation("Andrei", "owns", "BMW") is True
    rels = g.get_relations("Andrei")
    assert len(rels) == 1 and rels[0]["relation"] == "likes"
    assert g.delete_relation("Andrei", "owns", "BMW") is False  # already gone


# ── endpoints ────────────────────────────────────────────────────────────────

def test_kg_crud_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        if not web.orch or not getattr(web.orch, "memory", None):
            return  # orchestrator unavailable in this env

        # upsert entity
        r = c.post("/api/kg/entities", json={"name": "TestCo", "type": "organization"})
        assert r.status_code == 200 and r.json()["ok"] is True

        # missing name → 400
        assert c.post("/api/kg/entities", json={}).status_code == 400

        # get it back + relations
        got = c.get("/api/kg/entities/TestCo")
        assert got.status_code == 200
        assert got.json()["entity"]["name"] == "TestCo"
        assert "relations" in got.json()

        # list includes it
        listed = c.get("/api/kg/entities")
        assert listed.status_code == 200
        assert any(e["name"] == "TestCo" for e in listed.json()["entities"])

        # add a relation
        c.post("/api/kg/entities", json={"name": "TestPerson", "type": "person"})
        rel = c.post("/api/kg/relations",
                     json={"source": "TestPerson", "relation": "works_at", "target": "TestCo"})
        assert rel.status_code == 200 and rel.json()["ok"] is True
        # bad relation → 400
        assert c.post("/api/kg/relations", json={"source": "x"}).status_code == 400

        # delete the relation
        d = c.request("DELETE", "/api/kg/relations",
                      params={"source": "TestPerson", "relation": "works_at", "target": "TestCo"})
        assert d.status_code == 200

        # delete the entity
        assert c.delete("/api/kg/entities/TestCo").status_code == 200
        # second delete → 404
        assert c.delete("/api/kg/entities/TestCo").status_code == 404
