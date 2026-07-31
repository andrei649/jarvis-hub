"""AUD-12 (F11): Cypher label / relationship-type / property-key injection guard.

Neo4j cannot parameterise node *labels*, relationship *types*, or property *keys*
— they are interpolated into the query string (``memory/graph.py``). These tests
prove a hostile value can never break out of the query:

* a legitimate identifier (incl. a free-form-but-safe predicate like ``DAUGHTER``)
  passes through unchanged, so no extracted fact is lost;
* a non-identifier value is coerced to a safe fallback on the graph write path;
* the direct write API rejects a non-identifier value with 400.

The graph-layer tests capture the exact Cypher statement that *would* be sent to
Neo4j (via a stubbed ``_call_neo4j``), so they assert on the real query string.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.graph import Neo4jGraph
from agents.core.memory.incremental import IncrementalKGUpdater
from agents.core.validation import (
    KG_LABELS,
    KG_REL_TYPES,
    coerce_kg_label,
    coerce_kg_rel_type,
    is_safe_kg_label,
    is_safe_kg_rel_type,
    is_safe_property_key,
)


# ── validators (unit) ─────────────────────────────────────────────────────────

def test_canonical_vocabulary_passes_through_unchanged():
    for label in KG_LABELS:
        assert is_safe_kg_label(label)
        assert coerce_kg_label(label) == label
    for rel in KG_REL_TYPES:
        assert is_safe_kg_rel_type(rel)
        assert coerce_kg_rel_type(rel) == rel


@pytest.mark.parametrize("evil", [
    "Person) DETACH DELETE n //",
    "X`}) DETACH DELETE (n) //",
    "rel-type",        # hyphen is not a Cypher identifier char
    "'; DROP",
    "{}",
    "",
])
def test_injection_payloads_are_coerced(evil):
    assert not is_safe_kg_label(evil)
    assert not is_safe_kg_rel_type(evil)
    assert coerce_kg_label(evil) == "Entity"
    assert coerce_kg_rel_type(evil) == "RELATED_TO"


def test_relation_type_folds_internal_spaces():
    # Rel-types fold spaces to underscores (UPPER_SNAKE convention), so a spaced
    # value normalises to a safe identifier rather than being rejected. Labels do
    # not fold spaces, so a multi-word label coerces to Entity.
    assert is_safe_kg_rel_type("works at")
    assert coerce_kg_rel_type("works at") == "WORKS_AT"
    assert not is_safe_kg_label("New York")
    assert coerce_kg_label("New York") == "Entity"


def test_freeform_but_safe_values_are_kept():
    # "Andrei's daughter is Cosmina" → DAUGHTER is a safe identifier, so the
    # ingest path keeps it (no information lost — the whole point of coerce-not-
    # reject on the LLM/ingest path).
    assert coerce_kg_rel_type("daughter") == "DAUGHTER"
    assert coerce_kg_rel_type("works_at") == "WORKS_AT"
    assert coerce_kg_rel_type("KNOWS") == "KNOWS"
    assert is_safe_kg_label("Spaceship") and coerce_kg_label("Spaceship") == "Spaceship"


def test_property_key_guard():
    assert is_safe_property_key("city")
    assert is_safe_property_key("_source")
    assert not is_safe_property_key("k}) DETACH DELETE (n) //")
    assert not is_safe_property_key("has space")
    assert not is_safe_property_key("")


# ── graph layer: assert on the actual Cypher sent to Neo4j ────────────────────

def _capturing_graph():
    """A Neo4jGraph whose ``_call_neo4j`` records statements instead of dialing."""
    g = Neo4jGraph()
    sent: list[dict] = []

    def _stub(statements):
        sent.extend(statements)
        return [{"columns": [], "data": [{"row": [1]}]}]

    g._call_neo4j = _stub
    return g, sent


def test_add_entity_label_injection_is_neutralised():
    g, sent = _capturing_graph()
    g.add_entity("x", "Person'); DROP ALL //", {"city": "Bucharest"})
    stmt = sent[-1]["statement"]
    assert "DROP" not in stmt and "//" not in stmt
    assert "(n:Entity " in stmt                       # label coerced
    # Property params are namespaced `p_<key>` so they cannot collide with the
    # structural `$name` / `$source` / `$target`.
    assert sent[-1]["parameters"].get("p_city") == "Bucharest"   # real prop survives


def test_add_relation_reltype_injection_is_neutralised():
    g, sent = _capturing_graph()
    g.add_relation("a", "KNOWS]->() DETACH DELETE (n) //", "b")
    stmt = sent[-1]["statement"]
    assert "DETACH" not in stmt and "//" not in stmt
    assert "[r:RELATED_TO " in stmt


def test_add_relation_safe_reltype_is_unchanged():
    g, sent = _capturing_graph()
    g.add_relation("Andrei", "works_at", "Raiffeisen")
    assert "[r:WORKS_AT " in sent[-1]["statement"]


def test_hostile_property_key_is_dropped():
    g, sent = _capturing_graph()
    g.add_entity("x", "Person", {"city": "B", "evil}) DETACH DELETE (n) //": 1})
    stmt = sent[-1]["statement"]
    assert "DETACH" not in stmt and "//" not in stmt
    assert "city: $p_city" in stmt
    # the hostile key reaches neither the query nor the parameters
    assert all("DETACH" not in k for k in sent[-1]["parameters"])


def test_delete_relation_refuses_unsafe_reltype():
    g, sent = _capturing_graph()
    assert g.delete_relation("a", "R]->() DELETE n //", "b") is False
    assert sent == []   # nothing was ever sent to Neo4j


# ── ingest path coerces (and keeps safe facts) ────────────────────────────────

def test_incremental_ingest_is_injection_safe():
    g, sent = _capturing_graph()
    IncrementalKGUpdater(g).ingest("Andrei works at Raiffeisen")
    stmts = " ".join(s["statement"] for s in sent)
    assert "[r:WORKS_AT " in stmts          # the real predicate is preserved
    assert "DETACH" not in stmts


# ── direct API: 400 on a non-identifier label / relationship type ─────────────

def test_direct_api_rejects_injection_with_400():
    from agents import web
    with TestClient(web.app) as c:
        if not web.orch or not getattr(web.orch, "memory", None):
            pytest.skip("orchestrator unavailable in this env")

        r = c.post("/api/kg/entities",
                   json={"name": "X", "type": "P) DETACH DELETE n //"})
        assert r.status_code == 400

        r = c.post("/api/kg/relations",
                   json={"source": "a", "relation": "R]->() //", "target": "b"})
        assert r.status_code == 400

        r = c.delete("/api/kg/relations",
                     params={"source": "a", "relation": "R //", "target": "b"})
        assert r.status_code == 400

        # a legitimate write still succeeds
        r = c.post("/api/kg/relations",
                   json={"source": "Andrei", "relation": "KNOWS", "target": "Bob"})
        assert r.status_code == 200 and r.json()["ok"] is True


# ── property names must not be able to hijack the structural parameters ───────
#
# Property params shared one flat namespace with the structural ones:
#   add_entity   -> {"name": name, **props}
#   add_relation -> {"source": source, "target": target, **props}
# so `**props` could REPLACE the values the MERGE patterns bind. Property keys
# come from LLM extraction and from ingested content, so a key called `name` or
# `source` is not an exotic input — and the corruption is silent: the write
# succeeds, against the wrong node.

def test_a_property_named_source_cannot_rewire_the_relation():
    g, sent = _capturing_graph()
    g.add_relation("Andrei", "KNOWS", "Maria",
                   {"source": "ATTACKER-NODE", "since": "2020"})
    params = sent[-1]["parameters"]

    assert params["source"] == "Andrei", "the relation was rewired to a different node"
    assert params["target"] == "Maria"
    # The property is still stored — it is a legitimate relation property, just not
    # one that is allowed to mean "which node".
    assert params["p_source"] == "ATTACKER-NODE"
    assert params["p_since"] == "2020"
    assert "source: $p_source" in sent[-1]["statement"]


def test_a_property_named_target_cannot_rewire_the_relation():
    g, sent = _capturing_graph()
    g.add_relation("Andrei", "KNOWS", "Maria", {"target": "ATTACKER-NODE"})
    params = sent[-1]["parameters"]
    assert params["target"] == "Maria"
    assert params["p_target"] == "ATTACKER-NODE"


def test_a_property_named_name_cannot_rename_the_entity():
    g, sent = _capturing_graph()
    g.add_entity("Andrei", "Person", {"name": "SOMEONE-ELSE", "city": "Bucharest"})
    params = sent[-1]["parameters"]

    assert params["name"] == "Andrei", "the entity was written under a different name"
    assert params["p_city"] == "Bucharest"
    # A `name` property is dropped rather than namespaced: the entity's name is
    # structural, and emitting both `name: $name` and `name: $p_name` would be a
    # duplicate key in the Cypher map.
    assert "p_name" not in params
    assert sent[-1]["statement"].count("name: $name") == 2   # MERGE pattern + SET


def test_the_property_namespace_mapping_cannot_collide_with_itself():
    """`key -> "p_" + key` is injective, so `x` and `p_x` stay distinct."""
    g, sent = _capturing_graph()
    g.add_entity("Andrei", "Person", {"city": "A", "p_city": "B"})
    params = sent[-1]["parameters"]
    assert params["p_city"] == "A"
    assert params["p_p_city"] == "B"


def test_every_parameter_in_the_statement_is_actually_bound():
    """A namespacing slip would leave a `$p_foo` in the Cypher with nothing bound
    to it — Neo4j would reject the whole statement at runtime."""
    import re

    g, sent = _capturing_graph()
    g.add_entity("Andrei", "Person", {"city": "Bucharest", "age": 30})
    g.add_relation("Andrei", "KNOWS", "Maria", {"since": "2020", "source": "x"})
    for msg in sent:
        referenced = set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", msg["statement"]))
        assert referenced <= set(msg["parameters"]), (
            f"unbound parameters {referenced - set(msg['parameters'])} in {msg['statement']}"
        )
