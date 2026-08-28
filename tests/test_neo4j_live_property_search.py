"""WV-170 — validate real Neo4j property-search against a LIVE server, not mocks.

GitHub issue #170: the sibling #169 (KG sync) was closed against a live Neo4j, but
`Neo4jGraph.search()`'s property-scanning Cypher (H19.3.5 — a node whose *properties*
match a keyword even when its name doesn't) had only ever been exercised against
httpx mocks or an intentionally-unreachable port (`tests/test_knowledge_graph.py`).
This is the real integration: it talks to an actual Neo4j server over the REST
transaction API `Neo4jGraph` already uses.

Gated on `JARVIS_NEO4J_LIVE=1` (mirrors the `JARVIS_REALITY_HARNESS` convention) so
it never silently runs against a stray local Neo4j and never touches the default PR
suite. CI provides the server via a `neo4j:5` service container on the same
schedule-only/dispatch-only lane as `.github/workflows/reality.yml` — never on the
pull_request path. Point `NEO4J_URL`/`NEO4J_USER`/`NEO4J_PASSWORD` at a different
instance to run this against one you own.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.memory.graph import Neo4jGraph  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("JARVIS_NEO4J_LIVE") != "1",
    reason="live Neo4j lane — set JARVIS_NEO4J_LIVE=1 with a real server reachable at NEO4J_URL",
)


@pytest.fixture
def live_graph():
    g = Neo4jGraph()
    if not g._check_connection():
        pytest.fail(
            f"JARVIS_NEO4J_LIVE=1 but no Neo4j reachable at {g.url} — "
            "start one (e.g. `docker compose up neo4j`) or point NEO4J_URL at a real server"
        )
    yield g


def test_live_property_search_finds_a_node_by_property_not_name(live_graph):
    """The exact WV-170 ask: a node whose NAME doesn't contain the keyword, but
    whose PROPERTY does, must still be found — against a real server."""
    marker = f"wv170-{uuid.uuid4().hex[:8]}"
    ok = live_graph.add_entity(
        f"ReconWindow-{marker[:6]}", "Event",
        {"aoi": f"Strait of Hormuz {marker}", "source": "wv170-live-test"},
    )
    assert ok is True

    results = live_graph.search(marker)

    assert len(results) >= 1
    match = next(r for r in results if marker in r["properties"].get("aoi", ""))
    assert match["properties"]["aoi"] == f"Strait of Hormuz {marker}"
    assert match["properties"]["source"] == "wv170-live-test"


def test_live_search_still_matches_by_name(live_graph):
    marker = f"wv170name-{uuid.uuid4().hex[:8]}"
    live_graph.add_entity(marker, "Person", {"role": "tester"})
    results = live_graph.search(marker)
    assert any(r["name"] == marker for r in results)


def test_live_add_relation_and_get_relations_round_trip(live_graph):
    a, b = f"wv170a-{uuid.uuid4().hex[:6]}", f"wv170b-{uuid.uuid4().hex[:6]}"
    live_graph.add_entity(a, "Person")
    live_graph.add_entity(b, "Person")
    assert live_graph.add_relation(a, "KNOWS", b) is True
    rels = live_graph.get_relations(a)
    assert any(r["target"] == b and r["relation"] == "KNOWS" for r in rels)


def test_live_search_is_case_insensitive_on_property_values(live_graph):
    marker = f"WV170CASE{uuid.uuid4().hex[:6]}"
    live_graph.add_entity(f"CaseNode-{marker[:6]}", "Event", {"detail": marker})
    results = live_graph.search(marker.lower())
    assert any(marker in r["properties"].get("detail", "") for r in results)
