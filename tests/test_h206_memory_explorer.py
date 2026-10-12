"""H206 — the backend half of the memory graph explorer.

The explorer's timeline asks "what did Nerva know at T". That has to mean what the
store BELIEVED at T: a fact ingested by T and not yet superseded or retracted by T
(transaction time), shown the way the store held it then. ``known_as_of`` answers
"everything ever ingested by T", which is a different question.

Also covered: the bounded whole-map read the canvas draws from, the delete path
retracting the deleted entity's timeline facts (same kernel-mediated handler), and
type edits that neither duplicate a node on Neo4j nor get reset by ingestion.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web  # noqa: E402
from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.memory.bitemporal import BiTemporalKG  # noqa: E402
from agents.core.memory.graph import InMemoryGraph, Neo4jGraph  # noqa: E402
from agents.core.memory.incremental import IncrementalKGUpdater  # noqa: E402
from agents.core.routers import memory_kg  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _body(resp):
    return json.loads(resp.body)


def _status(resp):
    return getattr(resp, "status_code", 200)


class _Req:
    def __init__(self, body=None, headers=None):
        self._b, self.headers = body or {}, headers or {}

    async def json(self):
        return self._b


def _orch(tmp_path, graph=None):
    graph = graph if graph is not None else InMemoryGraph()
    bt = BiTemporalKG(tmp_path / "bt.json")
    return SimpleNamespace(memory=SimpleNamespace(graph=graph), bitemporal=bt,
                           kg_updater=IncrementalKGUpdater(graph, bt)), graph, bt


# ── bitemporal: "believed at T" (transaction time) ────────────────────────────

def test_believed_as_of_drops_a_fact_superseded_before_t(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("andrei", "lives_in", "Bucharest", valid_from=100, ingested_at=100)
    kg.add_fact("andrei", "lives_in", "Cluj", valid_from=200, ingested_at=300)
    # Before the move was ingested the store believed Bucharest, open-ended.
    before = kg.believed_as_of(250, "andrei")
    assert [f["object"] for f in before] == ["Bucharest"]
    assert before[0]["valid_to"] is None and before[0]["invalidated_at"] is None
    # After it, only Cluj is believed; known_as_of would still return both.
    assert [f["object"] for f in kg.believed_as_of(350, "andrei")] == ["Cluj"]
    assert len(kg.known_as_of(350, "andrei")) == 2
    assert kg.believed_as_of(50) == []


def test_believed_as_of_honours_an_explicit_retraction_in_transaction_time(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("andrei", "status", "active", valid_from=100, ingested_at=100)
    assert kg.invalidate("andrei", "status", "active", at=150, ingested_at=400) is True
    # Retracted at transaction time 400 (valid-time end 150): believed until 400.
    assert [f["object"] for f in kg.believed_as_of(399)] == ["active"]
    assert kg.believed_as_of(401) == []


def test_believed_as_of_reads_legacy_rows_without_transaction_stamps(tmp_path):
    path = tmp_path / "bt.json"
    path.write_text(json.dumps({"seq": 2, "facts": [
        {"id": 1, "subject": "a", "predicate": "p", "object": "x", "valid_from": 100,
         "valid_to": 200, "ingested_at": 100, "invalidated_at": 200},
        {"id": 2, "subject": "a", "predicate": "p", "object": "y", "valid_from": 200,
         "valid_to": None, "ingested_at": 500, "invalidated_at": None},
    ]}))
    kg = BiTemporalKG(path)
    # The superseding row was ingested at 500, so x was still believed at 450.
    assert [f["object"] for f in kg.believed_as_of(450)] == ["x"]
    assert [f["object"] for f in kg.believed_as_of(600)] == ["y"]


def test_retract_entity_closes_facts_naming_it_on_either_side(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("andrei", "drives", "BMW", valid_from=100, ingested_at=100)
    kg.add_fact("BMW", "is_a", "car", valid_from=100, ingested_at=100, multi=True)
    kg.add_fact("andrei", "lives_in", "Cluj", valid_from=100, ingested_at=100)
    assert kg.retract_entity("BMW", at=500) == 2
    assert [f["object"] for f in kg.believed_as_of(600)] == ["Cluj"]
    assert [f["object"] for f in kg.as_of(600)] == ["Cluj"]
    # History up to the deletion is kept: at 450 the store still believed all three.
    assert len(kg.believed_as_of(450)) == 3
    assert kg.retract_entity("BMW", at=700) == 0


def test_bounds_report_the_transaction_span(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    assert kg.bounds() == {"count": 0, "first_ingested": None, "last_ingested": None,
                           "first_valid": None, "last_change": None}
    kg.add_fact("a", "p", "x", valid_from=50, ingested_at=100)
    kg.add_fact("a", "p", "y", valid_from=60, ingested_at=300)
    kg.invalidate("a", "p", "y", at=70, ingested_at=900)
    b = kg.bounds()
    assert b["count"] == 2 and b["first_ingested"] == 100 and b["last_ingested"] == 300
    assert b["first_valid"] == 50 and b["last_change"] == 900


# ── GET /api/kg/facts/as-of: axis, limit, bounds ──────────────────────────────

def test_as_of_route_known_axis_means_believed_at_t(tmp_path, monkeypatch):
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    bt.add_fact("andrei", "lives_in", "Bucharest", valid_from=100, ingested_at=100)
    bt.add_fact("andrei", "lives_in", "Cluj", valid_from=200, ingested_at=300)

    known = _body(_run(memory_kg.kg_facts_as_of(at=250, axis="known")))
    assert [f["object"] for f in known["facts"]] == ["Bucharest"]
    assert known["axis"] == "known" and known["clipped"] is False
    assert known["bounds"]["first_ingested"] == 100 and known["bounds"]["last_ingested"] == 300

    valid = _body(_run(memory_kg.kg_facts_as_of(at=250, axis="valid")))
    assert valid["axis"] == "valid"
    assert [f["object"] for f in valid["facts"]] == ["Cluj"]   # true in the world at 250


def test_as_of_route_rejects_an_unknown_axis_and_bounds_the_page(tmp_path, monkeypatch):
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    for i in range(5):
        bt.add_fact(f"s{i}", "p", "o", valid_from=10 + i, ingested_at=10 + i)
    assert _status(_run(memory_kg.kg_facts_as_of(at=100, axis="sideways"))) == 422
    page = _body(_run(memory_kg.kg_facts_as_of(at=100, axis="known", limit=2)))
    assert page["clipped"] is True
    # The newest facts are kept when the page is clipped.
    assert [f["subject"] for f in page["facts"]] == ["s3", "s4"]
    assert _status(_run(memory_kg.kg_facts_as_of(at=100, limit=0))) == 422


def test_as_of_route_keeps_its_user_guard():
    from fastapi.testclient import TestClient
    snap = json.loads((repo_root / "tests/_snapshots/route_auth.json").read_text())
    assert snap["GET /api/kg/facts/as-of"] == "user"
    assert snap["GET /api/kg/map"] == "user"
    with TestClient(web.app) as c:
        assert c.get("/api/kg/facts/as-of", params={"axis": "sideways"}).status_code in (401, 422)


# ── GET /api/kg/map: bounded whole-map read ───────────────────────────────────

def test_map_route_returns_entities_relations_and_first_seen(tmp_path, monkeypatch):
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_entity("Andrei", "person", {"secret": "PRIVATE"})
    graph.add_entity("Cluj", "city")
    graph.add_relation("Andrei", "lives_in", "Cluj", {"source": "conversation"})
    bt.add_fact("Andrei", "lives_in", "Cluj", valid_from=100, ingested_at=120)

    body = _body(_run(memory_kg.kg_map(limit=50)))
    names = {e["name"]: e for e in body["entities"]}
    assert set(names) == {"Andrei", "Cluj"}
    assert names["Andrei"] == {"name": "Andrei", "type": "person", "first_seen": 120}
    assert "properties" not in json.dumps(body)            # no property values on the map
    assert body["relations"] == [{"source": "Andrei", "relation": "lives_in", "target": "Cluj"}]
    assert body["clipped"] is False and body["relations_clipped"] is False


def test_map_route_clips_and_drops_relations_to_unlisted_nodes(tmp_path, monkeypatch):
    orch, graph, _ = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    for i in range(4):
        graph.add_entity(f"N{i}", "thing")
    graph.add_relation("N0", "knows", "N1")
    graph.add_relation("N0", "knows", "N3")
    body = _body(_run(memory_kg.kg_map(limit=2)))
    assert [e["name"] for e in body["entities"]] == ["N0", "N1"]
    assert body["clipped"] is True
    assert body["relations"] == [{"source": "N0", "relation": "knows", "target": "N1"}]


def test_map_route_without_a_graph_is_503(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    assert _status(_run(memory_kg.kg_map(limit=10))) == 503


# ── delete: the same mediated handler retracts the entity's timeline facts ─────

def test_delete_entity_retracts_its_bitemporal_facts(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_relation("Andrei", "drives", "BMW")
    bt.add_fact("Andrei", "drives", "BMW", valid_from=100, ingested_at=100)
    bt.add_fact("Andrei", "lives_in", "Cluj", valid_from=100, ingested_at=100)

    resp = _run(memory_kg.kg_delete_entity("BMW", _Req()))
    assert _status(resp) == 200 and _body(resp)["facts_retracted"] == 1
    assert graph.get_entity("BMW") is None
    assert [f["object"] for f in bt.believed_as_of(10**12)] == ["Cluj"]
    # A name neither store knows is still a 404.
    assert _status(_run(memory_kg.kg_delete_entity("Ghost", _Req()))) == 404


def test_delete_refused_by_the_kernel_retracts_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel",
                        lambda o: (lambda a, capability=None, budget=None: Decision(Verdict.DENY, reason="halted")))
    graph.add_relation("Andrei", "drives", "BMW")
    bt.add_fact("Andrei", "drives", "BMW", valid_from=100, ingested_at=100)
    resp = _run(memory_kg.kg_delete_entity("BMW", _Req()))
    assert _status(resp) == 403 and _body(resp)["error"] == "kernel denied: halted"
    assert graph.get_entity("BMW") is not None
    assert len(bt.believed_as_of(10**12)) == 1


# ── type edits survive ingestion and do not duplicate on Neo4j ────────────────

def test_ingestion_does_not_reset_an_edited_type(tmp_path):
    graph = InMemoryGraph()
    graph.add_entity("Andrei", "person", {"role": "owner"})
    IncrementalKGUpdater(graph).ingest("Andrei works at Raiffeisen")
    assert graph.get_entity("Andrei") == {"name": "Andrei", "type": "person",
                                          "properties": {"role": "owner"}}
    assert graph.get_entity("Raiffeisen")["type"] == "unknown"   # new names still land


def test_ensure_entity_keeps_an_existing_entity(tmp_path):
    graph = InMemoryGraph()
    graph.add_entity("A", "person")
    assert graph.ensure_entity("A", "unknown") is True
    assert graph.get_entity("A")["type"] == "person"
    assert graph.ensure_entity("B", "unknown") is True
    assert graph.get_entity("B")["type"] == "unknown"


def _neo4j_stub(existing_labels):
    g = Neo4jGraph()
    sent = []

    def _stub(statements):
        sent.extend(statements)
        stmt = statements[-1]["statement"]
        if stmt.startswith("MATCH (n {name: $name}) RETURN labels(n) AS labels"):
            if existing_labels is None:
                return [{"columns": ["labels"], "data": []}]
            return [{"columns": ["labels"], "data": [{"row": [existing_labels]}]}]
        return [{"columns": ["n"], "data": [{"row": [{"name": "x"}]}]}]

    g._call_neo4j = _stub
    return g, sent


def test_neo4j_type_edit_relabels_the_existing_node_instead_of_merging_a_new_one():
    g, sent = _neo4j_stub(["Unknown", "bad label"])
    assert g.add_entity("Andrei", "person", {"city": "Cluj"}) is True
    stmt = sent[-1]["statement"]
    assert stmt.startswith("MATCH (n {name: $name})")
    assert "MERGE" not in stmt
    assert "REMOVE n:`Unknown`" in stmt and "SET n:`Person`" in stmt
    assert "bad label" not in stmt                    # an unsafe stored label is never interpolated
    assert sent[-1]["parameters"]["p_city"] == "Cluj"


def test_neo4j_new_entity_still_merges_with_its_label():
    g, sent = _neo4j_stub(None)
    g.add_entity("Andrei", "person")
    assert sent[-1]["statement"].startswith("MERGE (n:Person {name: $name})")


def test_neo4j_ensure_entity_only_labels_on_create():
    g, sent = _neo4j_stub(None)
    assert g.ensure_entity("Andrei", "unknown") is True
    stmt = sent[-1]["statement"]
    assert stmt == "MERGE (n {name: $name}) ON CREATE SET n:Unknown RETURN n"


def test_neo4j_list_relations_is_bounded_and_parameterised():
    g = Neo4jGraph()
    sent = []

    def _stub(statements):
        sent.extend(statements)
        return [{"columns": ["source", "relation", "target"],
                 "data": [{"row": ["A", "KNOWS", "B"]}]}]

    g._call_neo4j = _stub
    assert g.list_relations(25) == [{"source": "A", "relation": "KNOWS", "target": "B"}]
    assert sent[-1]["parameters"] == {"limit": 25}
    assert "LIMIT $limit" in sent[-1]["statement"]


# ── fix round 1 ───────────────────────────────────────────────────────────────

def test_as_of_route_default_is_the_legacy_unbounded_shape(tmp_path, monkeypatch):
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    for i in range(520):
        bt.add_fact(f"s{i}", "p", "o", valid_from=10 + i, ingested_at=10 + i)
    body = _body(_run(memory_kg.kg_facts_as_of(at=10_000)))
    assert set(body) == {"at", "facts"}                      # no axis / clipped / bounds
    assert len(body["facts"]) == 520                         # not capped when no limit is asked for


def test_delete_does_not_report_success_when_the_graph_delete_failed(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_entity("Bob", "person")
    bt.add_fact("Bob", "knows", "Eve", valid_from=100, ingested_at=100)
    monkeypatch.setattr(graph, "delete_entity", lambda name: False)   # e.g. Neo4j transport failure
    resp = _run(memory_kg.kg_delete_entity("Bob", _Req()))
    assert _status(resp) != 200
    assert graph.get_entity("Bob") is not None
    assert len(bt.believed_as_of(10**12)) == 1              # timeline untouched while the entity stays


def test_neo4j_edit_replaces_the_property_map(tmp_path):
    g, sent = _neo4j_stub(["Unknown"])
    g.add_entity("Andrei", "person", {"city": "Cluj"})
    assert "SET n = {" in sent[-1]["statement"] and "+=" not in sent[-1]["statement"]
    g, sent = _neo4j_stub(None)
    g.add_entity("Andrei", "person", {"city": "Cluj"})
    assert "SET n = {" in sent[-1]["statement"] and "+=" not in sent[-1]["statement"]


def test_neo4j_failed_label_lookup_writes_nothing_instead_of_duplicating():
    g = Neo4jGraph()
    g._connected = False                                    # the lookup cannot reach Neo4j
    sent = []
    real = g._call_neo4j

    def _spy(statements):
        sent.extend(statements)
        return real(statements)

    g._call_neo4j = _spy
    assert g.add_entity("Andrei", "person") is False
    assert not any(s["statement"].startswith("MERGE") for s in sent)


def test_neo4j_unlabelled_existing_node_is_relabelled_not_duplicated():
    g, sent = _neo4j_stub([])                               # the node exists but carries no label
    g.add_entity("Andrei", "person")
    stmt = sent[-1]["statement"]
    assert stmt.startswith("MATCH (n {name: $name})") and "SET n:`Person`" in stmt


def test_seed_does_not_overwrite_an_entity_the_owner_edited():
    from agents.core.memory.seed_graph import seed_graph
    graph = InMemoryGraph()
    graph.add_entity("Bucharest", "capital", {"note": "edited"})   # no "Andrei" -> seed runs again
    seed_graph(graph)
    assert graph.get_entity("Bucharest") == {"name": "Bucharest", "type": "capital",
                                             "properties": {"note": "edited"}}
    assert graph.get_entity("Andrei") is not None


def test_ingestion_never_stores_a_name_with_a_line_break(tmp_path):
    graph = InMemoryGraph()
    IncrementalKGUpdater(graph).ingest("Andrei lives in Berlin\nParis is nice.")
    assert graph.list_entities(50)
    assert all("\n" not in e["name"] for e in graph.list_entities(50))
