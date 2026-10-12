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
    """A removed property really goes (REMOVE), without `SET n = {...}` wiping unwritable keys."""
    g, sent = _shape_stub(["Unknown"], ["name", "city", "gone"])
    g.replace_entity("Andrei", "person", {"city": "Cluj"})
    stmt = sent[-1]["statement"]
    assert "REMOVE n.`gone`" in stmt and "SET n += {name: $name, city: $p_city}" in stmt
    assert "SET n = {" not in stmt
    g, sent = _shape_stub(None, [])
    g.replace_entity("Andrei", "person", {"city": "Cluj"})
    assert sent[-1]["statement"].startswith("MERGE (n:Person {name: $name}) SET n += {")


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


# ── fix round 2 ───────────────────────────────────────────────────────────────

def test_other_neo4j_writers_keep_merging_properties():
    """Only the explorer's edit replaces the map: manager.add_fact / house / seed call add_entity
    and must not wipe properties an owner edit or the house projection wrote."""
    for labels in (["Unknown"], None):
        g, sent = _neo4j_stub(labels)
        assert g.add_entity("Andrei", "person") is True
        stmt = sent[-1]["statement"]
        assert "SET n += {" in stmt and "SET n = {" not in stmt


def test_upsert_route_replaces_through_replace_entity(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, _, _ = _orch(tmp_path)
    seen = []

    class _G(InMemoryGraph):
        def add_entity(self, name, entity_type, properties=None):
            seen.append("add")
            return super().add_entity(name, entity_type, properties)

        def replace_entity(self, name, entity_type, properties=None):
            seen.append("replace")
            return InMemoryGraph.add_entity(self, name, entity_type, properties)

    g = _G()
    orch.memory.graph = g
    monkeypatch.setattr(web, "orch", orch)
    resp = _run(memory_kg.kg_upsert_entity(_Req({"name": "A", "type": "person", "properties": {"k": "v"}})))
    assert _status(resp) == 200 and seen == ["replace"]


def test_delete_reaches_timeline_only_entities(tmp_path, monkeypatch):
    """After a restart the in-memory graph is empty while the bi-temporal JSON persists: the
    timeline still shows those names, and deleting one must close its facts, not 404."""
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    bt.add_fact("C", "knows", "D", valid_from=100, ingested_at=100)
    assert graph.get_entity("C") is None
    resp = _run(memory_kg.kg_delete_entity("C", _Req()))
    assert _status(resp) == 200
    body = _body(resp)
    assert body["facts_retracted"] == 1 and body["graph_deleted"] is False
    assert bt.believed_as_of(10**12) == []
    assert [f["object"] for f in bt.believed_as_of(150)] == ["D"]     # history kept
    # Neither store knows it any more: now it is a 404.
    assert _status(_run(memory_kg.kg_delete_entity("C", _Req()))) == 404


def test_delete_of_a_graph_entity_reports_graph_deleted(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_entity("Bob", "person")
    assert _body(_run(memory_kg.kg_delete_entity("Bob", _Req())))["graph_deleted"] is True


def test_add_fact_refuses_times_the_ui_cannot_show(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    for bad in (1e13, -1e13, float("inf"), "soon", True):
        resp = _run(memory_kg.kg_add_fact(_Req({"subject": "A", "predicate": "p", "object": "B",
                                                "ingested_at": bad, "valid_from": 100})))
        assert _status(resp) == 400, bad
    assert bt.believed_as_of(10**12) == []
    ok = _run(memory_kg.kg_add_fact(_Req({"subject": "A", "predicate": "p", "object": "B",
                                          "ingested_at": 100, "valid_from": 100})))
    assert _status(ok) == 200


# ── mutation hardening (H206 mutation pass) ───────────────────────────────────

def _legacy(tmp_path, facts):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"seq": len(facts), "facts": facts}))
    return BiTemporalKG(path)


def _row(i, obj, vf, vt, ing, inv, subj="a", pred="p"):
    return {"id": i, "subject": subj, "predicate": pred, "object": obj, "valid_from": vf,
            "valid_to": vt, "ingested_at": ing, "invalidated_at": inv}


def test_retract_entity_is_persisted_across_a_reload(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("andrei", "drives", "BMW", valid_from=100, ingested_at=100)
    assert kg.retract_entity("BMW", at=500) == 1
    again = BiTemporalKG(tmp_path / "bt.json")
    assert again.believed_as_of(600) == [] and len(again.believed_as_of(450)) == 1


def test_believed_boundary_is_exclusive_at_the_moment_of_retraction(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("a", "p", "x", valid_from=100, ingested_at=100)
    kg.invalidate("a", "p", "x", at=150, ingested_at=400)
    assert len(kg.believed_as_of(399.9)) == 1
    assert kg.believed_as_of(400) == []          # dropped AT the retraction instant
    assert len(kg.believed_as_of(100)) == 1      # and present at its own ingestion instant


def test_believed_rows_hide_the_internal_transaction_stamp(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("a", "p", "x", valid_from=100, ingested_at=100)
    kg.add_fact("a", "p", "y", valid_from=200, ingested_at=300)
    assert all("invalidated_tx" not in f for f in kg.believed_as_of(1000))
    assert all("invalidated_tx" not in f for f in kg.believed_as_of(150))


def test_believed_filters_by_predicate_and_by_subject(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("a", "likes", "x", valid_from=1, ingested_at=1)
    kg.add_fact("a", "owns", "y", valid_from=1, ingested_at=1)
    kg.add_fact("b", "likes", "z", valid_from=1, ingested_at=1)
    assert [f["object"] for f in kg.believed_as_of(10, predicate="owns")] == ["y"]
    assert sorted(f["object"] for f in kg.believed_as_of(10, "a")) == ["x", "y"]
    assert [f["object"] for f in kg.believed_as_of(10, "a", "likes")] == ["x"]


def test_first_seen_is_the_earliest_ingestion_on_either_side(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("a", "knows", "b", valid_from=1, ingested_at=300)
    kg.add_fact("c", "knows", "b", valid_from=1, ingested_at=100)
    kg.add_fact("a", "knows", "d", valid_from=1, ingested_at=500)
    assert kg.first_seen() == {"a": 300, "b": 100, "c": 100, "d": 500}


def test_legacy_superseder_must_have_a_different_object(tmp_path):
    # id 3 re-ingests the SAME object at 300; only id 2 (object y, ingested 500) superseded x.
    kg = _legacy(tmp_path, [_row(1, "x", 100, 200, 100, 200),
                            _row(3, "x", 200, None, 300, None),
                            _row(2, "y", 200, None, 500, None)])
    assert [f["id"] for f in kg.believed_as_of(400) if f["object"] == "x" and f["id"] == 1] == [1]


def test_legacy_end_is_the_earliest_superseder(tmp_path):
    kg = _legacy(tmp_path, [_row(1, "x", 100, 200, 100, 200),
                            _row(2, "y", 200, None, 500, None),
                            _row(3, "z", 200, None, 700, None)])
    assert 1 in [f["id"] for f in kg.believed_as_of(450)]
    assert 1 not in [f["id"] for f in kg.believed_as_of(550)]     # gone at 500, not at 700


def test_legacy_closed_without_superseder_ends_at_its_invalidation_stamp(tmp_path):
    kg = _legacy(tmp_path, [_row(1, "x", 100, 200, 100, 250)])
    assert len(kg.believed_as_of(220)) == 1
    assert kg.believed_as_of(260) == []


def test_legacy_row_with_a_valid_end_but_no_stamp_is_not_believed_forever(tmp_path):
    kg = _legacy(tmp_path, [_row(1, "x", 100, 200, 100, None)])
    assert kg.believed_as_of(300) == []


def test_knowledge_graph_defaults_ensure_and_replace_delegate():
    from agents.core.memory.graph import KnowledgeGraph
    g = InMemoryGraph()
    g.add_entity("A", "person", {"k": 1})
    assert KnowledgeGraph.ensure_entity(g, "A", "unknown") is True      # existing: untouched
    assert g.get_entity("A")["type"] == "person"
    assert KnowledgeGraph.ensure_entity(g, "B", "thing") is True        # missing: created
    assert g.get_entity("B")["type"] == "thing"
    assert KnowledgeGraph.replace_entity(g, "A", "robot", {"z": 2}) is True
    assert g.get_entity("A") == {"name": "A", "type": "robot", "properties": {"z": 2}}


def test_in_memory_list_relations_is_bounded():
    g = InMemoryGraph()
    for i in range(5):
        g.add_relation(f"s{i}", "r", f"t{i}")
    assert len(g.list_relations(2)) == 2
    assert len(g.list_relations(0)) == 1                 # never below one
    assert g.list_relations(10)[0] == {"source": "s0", "relation": "r", "target": "t0"}


def test_neo4j_error_flag_is_reset_by_every_call(monkeypatch):
    g = Neo4jGraph()
    g._connected = False
    g._call_neo4j([{"statement": "RETURN 1", "parameters": {}}])
    assert g._tls.error == "unreachable"

    class _Resp:
        def __init__(self, body):
            self._b = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._b

    class _Client:
        body: dict = {}

        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            return _Resp(_Client.body)

    monkeypatch.setattr("agents.core.memory.graph.httpx.Client", _Client)
    g._connected = True
    _Client.body = {"results": [{"columns": ["labels"], "data": []}]}
    g._call_neo4j([{"statement": "RETURN 1", "parameters": {}}])
    assert g._tls.error is None
    assert g._labels_of("x") is None                    # a clean "no such node", not an error
    _Client.body = {"results": [], "errors": [{"code": "Neo.ClientError"}]}
    assert g._call_neo4j([{"statement": "x", "parameters": {}}]) == []
    assert g._tls.error == "rejected"
    try:
        g._labels_of("x")
        raise AssertionError("a rejected lookup must raise")
    except RuntimeError as exc:
        assert "rejected" in str(exc)

    class _Boom(_Client):
        def post(self, *a, **kw):
            raise ConnectionError("down")

    monkeypatch.setattr("agents.core.memory.graph.httpx.Client", _Boom)
    assert g._call_neo4j([{"statement": "x", "parameters": {}}]) == []
    assert "down" in g._tls.error


def test_neo4j_labels_of_ignores_non_list_rows():
    g = Neo4jGraph()
    g._call_neo4j = lambda s: [{"columns": ["labels"], "data": [{"row": ["Person"]}, {"row": [["Pet"]]}]}]
    assert g._labels_of("x") == ["Pet"]


class _SpyGraph(InMemoryGraph):
    def __init__(self, entities=(), relations=()):
        super().__init__()
        self._e, self._r, self.calls = list(entities), list(relations), []

    def list_entities(self, limit=100):
        self.calls.append(("e", limit))
        return self._e[:limit]

    def list_relations(self, limit=500, names=None):
        self.calls.append(("r", limit))
        self.names = names
        return self._r[:limit]


def _spy_map(tmp_path, monkeypatch, graph, **kw):
    orch, _, _ = _orch(tmp_path, graph)
    monkeypatch.setattr(web, "orch", orch)
    return _body(_run(memory_kg.kg_map(**kw)))


def test_map_route_clamps_limit_both_ways(tmp_path, monkeypatch):
    g = _SpyGraph([{"name": f"N{i}", "type": "t"} for i in range(5)])
    _spy_map(tmp_path, monkeypatch, g, limit=10**6)
    assert ("e", 1001) in g.calls and ("r", 4001) in g.calls          # capped at 1000 / 4000
    g.calls.clear()
    body = _spy_map(tmp_path, monkeypatch, g, limit=0)
    assert [e["name"] for e in body["entities"]] == ["N0"] and ("e", 2) in g.calls
    g.calls.clear()
    body = _spy_map(tmp_path, monkeypatch, g, limit=-7)
    assert len(body["entities"]) == 1
    g.calls.clear()
    body = _spy_map(tmp_path, monkeypatch, g, limit=5)               # exactly the list: not clipped
    assert len(body["entities"]) == 5 and body["clipped"] is False
    assert ("r", 21) in g.calls


def test_map_route_flags_clipped_relations_only_past_the_cap(tmp_path, monkeypatch):
    ents = [{"name": "A", "type": "t"}]
    loop = {"source": "A", "relation": "r", "target": "A"}
    at_cap = _spy_map(tmp_path, monkeypatch, _SpyGraph(ents, [loop] * 4), limit=1)   # cap = 4
    assert at_cap["relations_clipped"] is False and len(at_cap["relations"]) == 4
    over = _spy_map(tmp_path, monkeypatch, _SpyGraph(ents, [loop] * 6), limit=1)
    assert over["relations_clipped"] is True and len(over["relations"]) == 4


def test_map_route_default_limit_and_nameless_entities(tmp_path, monkeypatch):
    g = _SpyGraph([{"name": "", "type": "t"}, {"type": "t"}, {"name": "A", "type": "t"}])
    body = _spy_map(tmp_path, monkeypatch, g, limit=10)
    assert [e["name"] for e in body["entities"]] == ["A"]
    g.calls.clear()
    orch, _, _ = _orch(tmp_path, g)
    monkeypatch.setattr(web, "orch", orch)
    _body(_run(memory_kg.kg_map()))
    assert ("e", 501) in g.calls                                      # default page is 500


def test_add_fact_refuses_nan_and_the_exact_limit_is_allowed(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    for key in ("valid_from", "ingested_at"):
        resp = _run(memory_kg.kg_add_fact(_Req({"subject": "A", "predicate": "p", "object": "B",
                                                key: float("nan")})))
        assert _status(resp) == 400, key
    assert bt.believed_as_of(10**12) == []
    ok = _run(memory_kg.kg_add_fact(_Req({"subject": "A", "predicate": "p", "object": "B",
                                          "valid_from": 8.64e12, "ingested_at": -8.64e12})))
    assert _status(ok) == 200


def test_as_of_route_limit_upper_bound_and_sorting(tmp_path, monkeypatch):
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    bt.add_fact("late", "p", "o", valid_from=50, ingested_at=10)
    bt.add_fact("early", "p", "o", valid_from=20, ingested_at=30)
    bt.add_fact("mid", "p", "o", valid_from=30, ingested_at=20)
    assert _status(_run(memory_kg.kg_facts_as_of(at=100, limit=1001))) == 422
    assert _status(_run(memory_kg.kg_facts_as_of(at=100, limit=1000))) == 200
    known = _body(_run(memory_kg.kg_facts_as_of(at=100, axis="known")))
    assert [f["subject"] for f in known["facts"]] == ["late", "mid", "early"]      # by ingestion
    valid = _body(_run(memory_kg.kg_facts_as_of(at=100, axis="valid")))
    assert [f["subject"] for f in valid["facts"]] == ["early", "mid", "late"]      # by valid_from
    only_limit = _body(_run(memory_kg.kg_facts_as_of(at=100, limit=2)))
    assert only_limit["axis"] == "valid" and "bounds" in only_limit and only_limit["clipped"] is True


def test_as_of_route_without_axis_stays_valid_time(tmp_path, monkeypatch):
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    bt.add_fact("andrei", "lives_in", "Bucharest", valid_from=100, ingested_at=100)
    bt.add_fact("andrei", "lives_in", "Cluj", valid_from=200, ingested_at=300)
    legacy = _body(_run(memory_kg.kg_facts_as_of(at=250)))
    assert [f["object"] for f in legacy["facts"]] == ["Cluj"] and "bounds" not in legacy
    explicit = _body(_run(memory_kg.kg_facts_as_of(at=250, axis="valid")))
    assert [f["object"] for f in explicit["facts"]] == ["Cluj"]


def test_map_route_is_registered_behind_the_user_guard():
    routes = [r for r in memory_kg.router.routes if getattr(r, "path", "") == "/api/kg/map"]
    assert len(routes) == 1 and "GET" in routes[0].methods
    guards = [d.dependency for d in routes[0].dependencies]
    assert memory_kg.user_guard in guards


def test_ingestion_works_with_a_graph_that_has_no_ensure_entity(tmp_path):
    class _Old:
        def __init__(self):
            self.added, self.rels = [], []

        def add_entity(self, name, entity_type, properties=None):
            self.added.append((name, entity_type))
            return True

        def add_relation(self, s, r, t, props=None):
            self.rels.append((s, r, t))
            return True

    old = _Old()
    IncrementalKGUpdater(old).ingest("Andrei works at Raiffeisen")
    assert ("Andrei", "unknown") in old.added and old.rels


def test_seed_creates_missing_entities_and_keeps_edited_ones_by_name():
    from agents.core.memory.seed_graph import seed_graph
    graph = InMemoryGraph()
    graph.add_entity("Bucharest", "capital", {"note": "edited"})
    calls = []
    real = graph.add_entity
    graph.add_entity = lambda n, t, p=None: (calls.append(n), real(n, t, p))[1]
    seed_graph(graph)
    assert "Bucharest" not in calls and "Andrei" in calls


def test_ingestion_collapses_whitespace_inside_a_name(tmp_path):
    graph = InMemoryGraph()
    IncrementalKGUpdater(graph).ingest("Andrei lives in Berlin \n  Paris is nice.")
    names = [e["name"] for e in graph.list_entities(50)]
    assert all("\n" not in n and "  " not in n for n in names)


def test_retract_entity_keeps_valid_time_and_transaction_time_apart(tmp_path):
    kg = BiTemporalKG(tmp_path / "bt.json")
    kg.add_fact("a", "p", "X", valid_from=100, ingested_at=100)
    assert kg.retract_entity("X", at=500, ingested_at=900) == 1
    assert len(kg.believed_as_of(700)) == 1        # still believed until the transaction time 900
    assert kg.believed_as_of(950) == []
    assert [f["object"] for f in kg.as_of(400)] == ["X"] and kg.as_of(600) == []   # valid-time end 500


# ── round 4: names, stored shapes and Neo4j fidelity ──────────────────────────

def _shape_stub(labels, keys):
    """A Neo4j transport stub whose lookup answers labels AND stored property keys."""
    g = Neo4jGraph()
    sent = []

    def _stub(statements):
        sent.extend(statements)
        stmt = statements[-1]["statement"]
        if stmt.startswith("MATCH (n {name: $name}) RETURN labels(n) AS labels"):
            if labels is None:
                return [{"columns": ["labels", "keys"], "data": []}]
            return [{"columns": ["labels", "keys"], "data": [{"row": [labels, keys]}]}]
        return [{"columns": ["n"], "data": [{"row": [{"name": "x"}]}]}]

    g._call_neo4j = _stub
    return g, sent


def test_neo4j_replace_keeps_stored_properties_it_cannot_write_back():
    g, sent = _shape_stub(["Reconwindow"], ["name", "aoi", "event-id", "geo.lat", "old"])
    assert g.replace_entity("W1", "reconwindow", {"aoi": "x", "event-id": "7"}) is True
    stmt = sent[-1]["statement"]
    assert "SET n = {" not in stmt                            # a full replace would wipe the unsafe keys
    assert "SET n += {name: $name, aoi: $p_aoi}" in stmt
    assert "REMOVE n.`old`" in stmt                           # a property the dialog removed really goes
    assert "event-id" not in stmt and "geo.lat" not in stmt  # unsafe keys are neither written nor removed
    assert "REMOVE n.`aoi`" not in stmt and "n.`name`" not in stmt


def test_neo4j_replace_of_a_new_node_still_merges_with_its_properties():
    g, sent = _shape_stub(None, [])
    g.replace_entity("W1", "reconwindow", {"aoi": "x"})
    assert sent[-1]["statement"] == "MERGE (n:Reconwindow {name: $name}) SET n += {name: $name, aoi: $p_aoi} RETURN n"


def test_neo4j_type_edit_that_keeps_the_type_does_not_relabel():
    g, sent = _shape_stub(["ReconWindow"], ["name"])
    g.replace_entity("W1", "reconwindow", {})                 # get_entity lower-cases the label; the dialog sends it back
    stmt = sent[-1]["statement"]
    assert "REMOVE n:" not in stmt and "SET n:" not in stmt
    g, sent = _shape_stub(["ReconWindow"], ["name"])
    g.replace_entity("W1", "person", {})
    assert "REMOVE n:`ReconWindow`" in sent[-1]["statement"] and "SET n:`Person`" in sent[-1]["statement"]


def test_neo4j_delete_of_a_node_that_is_not_there_is_false():
    g = Neo4jGraph()
    g._call_neo4j = lambda s: [{"columns": ["deleted"], "data": [{"row": [0]}]}]
    assert g.delete_entity("Ghost") is False
    g._call_neo4j = lambda s: [{"columns": ["deleted"], "data": [{"row": [1]}]}]
    assert g.delete_entity("Real") is True
    g._call_neo4j = lambda s: []
    assert g.delete_entity("Real") is False


def test_delete_with_an_unreachable_graph_leaves_the_timeline_alone(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    g = Neo4jGraph()
    g._connected = False                                      # Neo4j cannot be asked
    orch, _, bt = _orch(tmp_path, graph=g)
    monkeypatch.setattr(web, "orch", orch)
    bt.add_fact("Bob", "knows", "Eve", valid_from=100, ingested_at=100)
    resp = _run(memory_kg.kg_delete_entity("Bob", _Req()))
    assert _status(resp) == 503
    assert len(bt.believed_as_of(10**12)) == 1                # not half-applied: the graph may still hold Bob


def test_add_fact_refuses_names_that_are_not_text(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, _, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    for bad in (["x"], {"k": 1}, 7, True, "x" * 5000):
        for field in ("subject", "predicate", "object"):
            fact = {"subject": "A", "predicate": "p", "object": "B", field: bad}
            assert _status(_run(memory_kg.kg_add_fact(_Req(fact)))) == 400, (field, bad)
    assert bt.believed_as_of(10**12) == []


def test_map_survives_a_stored_fact_with_a_non_text_name(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_entity("A", "person")
    bt.add_fact(["x"], "p", {"k": 1}, valid_from=100, ingested_at=100)   # a row written before the route validated
    bt.add_fact("A", "p", "B", valid_from=100, ingested_at=100)
    assert bt.first_seen() == {"A": 100, "B": 100}
    resp = _run(memory_kg.kg_map(limit=10))
    assert _status(resp) == 200 and _body(resp)["entities"][0]["first_seen"] == 100


def test_upsert_refuses_a_name_with_leading_or_trailing_whitespace(tmp_path, monkeypatch):
    """The server used to strip it, so editing 'Foo ' silently overwrote 'Foo'."""
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph, _ = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_entity("Foo", "person", {"secret": "keep"})
    for padded in ("Foo ", " Foo", "\tFoo\n"):
        resp = _run(memory_kg.kg_upsert_entity(_Req({"name": padded, "type": "person", "properties": {"x": 1}})))
        assert _status(resp) == 400, padded
    assert graph.get_entity("Foo")["properties"] == {"secret": "keep"}


def test_entity_routes_carry_names_with_slashes_and_backslashes(tmp_path, monkeypatch):
    from urllib.parse import quote

    from fastapi.testclient import TestClient
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph, bt = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    names = ("AC/DC", "R&D / QA", "a\\b", "/lead", "trail/", "plain")
    for name in names:
        graph.add_entity(name, "company", {"k": "v"})
        bt.add_fact(name, "is", "loud", valid_from=100, ingested_at=100)
    web.app.dependency_overrides[memory_kg.user_guard] = lambda: None   # the guard has its own tests
    try:
        client = TestClient(web.app)                       # no lifespan: the orchestrator above stays in place
        for name in names:
            enc = quote(name, safe="")
            got = client.get("/api/kg/entities/" + enc)
            assert got.status_code == 200 and got.json()["entity"]["name"] == name, (name, got.status_code)
            gone = client.delete("/api/kg/entities/" + enc)
            assert gone.status_code == 200 and gone.json()["deleted"] == name, (name, gone.status_code)
            assert graph.get_entity(name) is None
            assert client.delete("/api/kg/entities/" + enc).status_code == 404
    finally:
        web.app.dependency_overrides.pop(memory_kg.user_guard, None)


def test_as_of_route_refuses_a_time_it_cannot_echo(tmp_path, monkeypatch):
    orch, _, _ = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    for at in (float("nan"), float("inf"), float("-inf"), 1e13):
        for axis in (None, "known", "valid"):
            assert _status(_run(memory_kg.kg_facts_as_of(at=at, axis=axis))) == 422, (at, axis)


def test_neo4j_list_relations_among_names_filters_in_the_query():
    g = Neo4jGraph()
    sent = []
    g._call_neo4j = lambda statements: sent.extend(statements) or []
    g.list_relations(25, names=["A", "B"])
    assert "WHERE a.name IN $names AND b.name IN $names" in sent[-1]["statement"]
    assert sent[-1]["parameters"] == {"limit": 25, "names": ["A", "B"]}


def test_in_memory_list_relations_among_names_drops_edges_leaving_the_set():
    g = InMemoryGraph()
    g.add_relation("A", "r", "B")
    for i in range(5):
        g.add_relation("X", "r", f"Y{i}")                 # a crowd of edges that never touch the listed names
    g.add_relation("B", "r", "A")
    assert [(r["source"], r["target"]) for r in g.list_relations(3, names=["A", "B"])] == [("A", "B"), ("B", "A")]


def test_map_route_asks_only_for_relations_among_the_listed_entities(tmp_path, monkeypatch):
    graph = _SpyGraph(entities=[{"name": "A", "type": "t"}, {"name": "B", "type": "t"}],
                      relations=[{"source": "A", "relation": "r", "target": "B"}])
    body = _spy_map(tmp_path, monkeypatch, graph, limit=10)
    assert graph.names == ["A", "B"] and len(body["relations"]) == 1
