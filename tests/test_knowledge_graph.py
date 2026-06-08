"""Tests for the knowledge graph module (H3.2)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.memory.graph import (
    InMemoryGraph,
    KnowledgeGraph,
    Neo4jGraph,
    create_graph,
)


class TestInMemoryGraph:
    def test_add_entity(self):
        g = InMemoryGraph()
        assert g.add_entity("Andrei", "Person", {"city": "Bucharest"})
        ent = g.get_entity("Andrei")
        assert ent["name"] == "Andrei"
        assert ent["type"] == "Person"
        assert ent["properties"]["city"] == "Bucharest"

    def test_add_entity_no_properties(self):
        g = InMemoryGraph()
        assert g.add_entity("Bucharest", "City")
        ent = g.get_entity("Bucharest")
        assert ent["type"] == "City"
        assert ent["properties"] == {}

    def test_get_entity_missing(self):
        g = InMemoryGraph()
        assert g.get_entity("Nobody") is None

    def test_add_relation(self):
        g = InMemoryGraph()
        g.add_entity("Andrei", "Person")
        g.add_entity("Raiffeisen", "Organization")
        assert g.add_relation("Andrei", "WORKS_AT", "Raiffeisen")
        rels = g.get_relations("Andrei")
        assert len(rels) == 1
        assert rels[0]["source"] == "Andrei"
        assert rels[0]["relation"] == "WORKS_AT"
        assert rels[0]["target"] == "Raiffeisen"

    def test_add_relation_auto_creates_missing(self):
        g = InMemoryGraph()
        assert g.add_relation("Andrei", "KNOWS", "Bogdan")
        assert g.get_entity("Bogdan")["type"] == "unknown"

    def test_get_relations_direction_outgoing(self):
        g = InMemoryGraph()
        g.add_relation("A", "KNOWS", "B")
        g.add_relation("C", "KNOWS", "A")
        rels = g.get_relations("A", direction="outgoing")
        assert len(rels) == 1
        assert rels[0]["target"] == "B"

    def test_get_relations_direction_incoming(self):
        g = InMemoryGraph()
        g.add_relation("A", "KNOWS", "B")
        g.add_relation("C", "KNOWS", "A")
        rels = g.get_relations("A", direction="incoming")
        assert len(rels) == 1
        assert rels[0]["source"] == "C"

    def test_get_relations_both(self):
        g = InMemoryGraph()
        g.add_relation("A", "KNOWS", "B")
        g.add_relation("C", "KNOWS", "A")
        rels = g.get_relations("A")
        assert len(rels) == 2

    def test_query_returns_empty(self):
        g = InMemoryGraph()
        assert g.query("MATCH (n) RETURN n") == []

    def test_search_by_name(self):
        g = InMemoryGraph()
        g.add_entity("Andrei", "Person")
        g.add_entity("Alexandra", "Person")
        results = g.search("Andrei")
        assert len(results) == 1
        assert results[0]["name"] == "Andrei"

    def test_search_by_property(self):
        g = InMemoryGraph()
        g.add_entity("Andrei", "Person", {"city": "Bucharest"})
        g.add_entity("Maria", "Person", {"city": "Cluj"})
        results = g.search("Bucharest")
        assert len(results) == 1
        assert results[0]["name"] == "Andrei"

    def test_search_case_insensitive(self):
        g = InMemoryGraph()
        g.add_entity("Andrei", "Person", {"city": "BUCHAREST"})
        results = g.search("bucharest")
        assert len(results) == 1

    def test_search_finds_geo_event_by_aoi_property(self):
        # Contract (H19.3.5): a geo-event whose AOI lives only in a property must be
        # findable by the location keyword — mirrors the Neo4j property scan below.
        g = InMemoryGraph()
        g.add_entity(
            "ReconWindow rw-77",
            "geo_event",
            {"worldview_id": "rw-77", "aoi": "Strait of Hormuz", "source": "demo"},
        )
        results = g.search("Hormuz")
        assert len(results) == 1
        assert results[0]["properties"]["aoi"] == "Strait of Hormuz"


class TestNeo4jGraph:
    def test_init_defaults(self):
        g = Neo4jGraph()
        assert "localhost" in g.url
        assert g.user == "neo4j"

    def test_init_custom(self):
        g = Neo4jGraph(
            url="http://neo4j.local:7474",
            user="admin",
            password="secret",
        )
        assert g.url == "http://neo4j.local:7474"
        assert g.user == "admin"
        assert g.password == "secret"

    def test_connection_refused_graceful(self):
        g = Neo4jGraph(url="http://127.0.0.1:19999")
        assert g._check_connection() is False
        assert g._connected is False

    def test_add_entity_connection_refused(self):
        g = Neo4jGraph(url="http://127.0.0.1:19999")
        g._connected = False
        assert g.add_entity("Test", "Person") is False

    def test_add_relation_connection_refused(self):
        g = Neo4jGraph(url="http://127.0.0.1:19999")
        g._connected = False
        assert g.add_relation("A", "KNOWS", "B") is False

    def test_get_entity_connection_refused(self):
        g = Neo4jGraph(url="http://127.0.0.1:19999")
        g._connected = False
        assert g.get_entity("Nobody") is None

    def test_search_connection_refused(self):
        g = Neo4jGraph(url="http://127.0.0.1:19999")
        g._connected = False
        assert g.search("Test") == []

    def test_successful_query_mock(self):
        g = Neo4jGraph(url="http://mock")
        g._connected = True
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "columns": ["n", "labels"],
                    "data": [
                        {"row": [{"name": "Andrei", "city": "Bucharest"}, ["Person"]]}
                    ],
                }
            ]
        }
        with patch.object(httpx, "Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            entity = g.get_entity("Andrei")
            assert entity is not None
            assert entity["name"] == "Andrei"
            assert entity["type"] == "person"

    def test_query_transport_error(self):
        g = Neo4jGraph(url="http://127.0.0.1:19999")
        g._connected = True
        with patch.object(httpx, "Client", side_effect=httpx.ConnectError("refused")):
            rows = g.query("MATCH (n) RETURN n")
            assert rows == []

    def test_relation_mock(self):
        g = Neo4jGraph(url="http://mock")
        g._connected = True
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"results": [{"columns": ["source", "relation", "target", "properties"], "data": []}]}
        with patch.object(httpx, "Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            rels = g.get_relations("Andrei")
            assert rels == []

    def test_search_cypher_scans_properties_injection_safe(self):
        """Neo4j search must match name OR any string property (H19.3.5 contract),
        with the keyword parameterised (no string interpolation = injection-safe)."""
        g = Neo4jGraph(url="http://mock")
        g._connected = True
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"results": [{"columns": ["n", "labels"], "data": []}]}
        with patch.object(httpx, "Client") as mock_client:
            posted = {}

            def _capture(url, json=None, auth=None):
                posted.update(json)
                return mock_response

            mock_client.return_value.__enter__.return_value.post.side_effect = _capture
            g.search("Hormuz")

        stmt = posted["statements"][0]
        cypher = stmt["statement"]
        # Scans node properties (not just n.name) so AOI/source/details are findable.
        assert "keys(n)" in cypher and "CONTAINS toLower($keyword)" in cypher
        # Keyword is bound as a parameter, never inlined into the query string.
        assert "Hormuz" not in cypher
        assert stmt["parameters"]["keyword"] == "Hormuz"

    def test_search_property_match_mock(self):
        """End-to-end (mocked): a node returned by the property-scan query is parsed
        into a result with its properties intact."""
        g = Neo4jGraph(url="http://mock")
        g._connected = True
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "columns": ["n", "labels"],
                    "data": [
                        {"row": [
                            {"name": "ReconWindow rw-77", "aoi": "Strait of Hormuz"},
                            ["Geo_event"],
                        ]}
                    ],
                }
            ]
        }
        with patch.object(httpx, "Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            results = g.search("Hormuz")
        assert len(results) == 1
        assert results[0]["properties"]["aoi"] == "Strait of Hormuz"


class TestCreateGraph:
    def test_create_memory_backend(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_GRAPH_BACKEND", "memory")
        g = create_graph()
        assert isinstance(g, InMemoryGraph)

    def test_create_neo4j_unreachable(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_GRAPH_BACKEND", "neo4j")
        monkeypatch.setenv("NEO4J_URL", "http://127.0.0.1:19999")
        g = create_graph()
        assert isinstance(g, InMemoryGraph)

    def test_factory_defaults_to_memory(self, monkeypatch):
        monkeypatch.delenv("KNOWLEDGE_GRAPH_BACKEND", raising=False)
        g = create_graph()
        assert isinstance(g, InMemoryGraph)


class TestSeedGraph:
    def test_seed_graph_populates(self):
        from agents.core.memory.seed_graph import seed_graph
        g = InMemoryGraph()
        count = seed_graph(g)
        assert count > 0
        # Core entities should exist
        assert g.get_entity("Andrei") is not None
        assert g.get_entity("Alexandra") is not None
        assert g.get_entity("Max") is not None
        assert g.get_entity("Bucharest") is not None
        # Core relations
        rels = g.get_relations("Andrei")
        assert any(r["relation"] == "WORKS_AT" for r in rels)
        assert any(r["relation"] == "MARRIED_TO" for r in rels)

    def test_seed_idempotent(self):
        from agents.core.memory.seed_graph import seed_graph
        g = InMemoryGraph()
        count1 = seed_graph(g)
        count2 = seed_graph(g)
        assert count2 == 0

    def test_usage_scenario_unde_lucreaza(self):
        """Acceptance criteria: 'Unde lucrează Andrei?' → răspunde din graph."""
        from agents.core.memory.seed_graph import seed_graph
        g = InMemoryGraph()
        seed_graph(g)
        entity = g.get_entity("Andrei")
        assert entity is not None
        assert entity["properties"].get("works_at") == "Raiffeisen"
        rels = g.get_relations("Andrei")
        work_rel = [r for r in rels if r["relation"] == "WORKS_AT"]
        assert len(work_rel) == 1
        assert work_rel[0]["target"] == "Raiffeisen"
