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

The bottom of this file holds the OFFLINE regression tests for the connection probe
itself. They belong next to the live lane because they exist for one reason: the probe
was wrong (`GET` on a POST-only endpoint), so this lane failed against a healthy server
and never executed the Cypher it exists to prove. They run in the ordinary PR suite.
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.memory.graph import Neo4jGraph, _neo4j_property_value  # noqa: E402
from core.memory.worldview_sync import _details  # noqa: E402


@pytest.fixture
def live_graph():
    # The gate lives on the fixture rather than a module-level `pytestmark` so the
    # offline probe tests at the bottom of this file still run in the PR suite. Every
    # test that needs a real server takes this fixture, so none can escape the gate.
    if os.environ.get("JARVIS_NEO4J_LIVE") != "1":
        pytest.skip(
            "live Neo4j lane — set JARVIS_NEO4J_LIVE=1 with a real server reachable "
            "at NEO4J_URL"
        )
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


def test_live_property_search_finds_the_real_worldview_sync_shape(live_graph):
    """WV-170 leg 1: the writer path does NOT send flat strings.

    `worldview_sync._details` nests the ontology properties under a dict-valued
    `details` key, which real Neo4j rejects outright while `InMemoryGraph` accepts it
    — so the all-strings cases above would pass with the geo-event never having
    reached the server. The keyword here exists ONLY inside the nested map.
    """
    marker = f"wv170map-{uuid.uuid4().hex[:8]}"
    obj = {"properties": {"mmsi": marker, "status": "dark", "gapSeconds": 60}}
    name = f"DarkVesselEvent dv-{uuid.uuid4().hex[:6]} — Strait of Hormuz"
    ok = live_graph.add_entity(name, "geo_event", {
        "worldview_type": "DarkVesselEvent",
        "aoi": "Strait of Hormuz",
        "source": None,                 # provenance is routinely absent
        "valid_time": 1780865129.713659,
        "jarvis_tainted": True,
        **_details(obj),
    })
    assert ok is True, "real Neo4j refused the geo-event the WorldView sync writes"
    match = next(r for r in live_graph.search(marker) if r["name"] == name)
    assert marker in match["properties"]["details"]


def test_live_search_matches_a_non_string_property_via_tostring(live_graph):
    """Issue #170 leg 1 verbatim: `toString(n[k])` must make NON-STRING values
    matchable. This is stored as a Neo4j integer, not a string."""
    gap = 700000 + uuid.uuid4().int % 99999
    name = f"NumNode-{uuid.uuid4().hex[:6]}"
    assert live_graph.add_entity(name, "Event", {"gap_seconds": gap}) is True
    assert any(r["properties"].get("gap_seconds") == gap
               for r in live_graph.search(str(gap)))


def test_live_search_survives_a_list_valued_property(live_graph):
    """A stored array makes `toString(n[k])` raise on Neo4j 5 and takes the whole
    property scan down for every node; the boundary coercion stores it as text."""
    marker = f"wv170list-{uuid.uuid4().hex[:8]}"
    name = f"ListNode-{uuid.uuid4().hex[:6]}"
    assert live_graph.add_entity(name, "Event", {"tags": [marker, "dark"]}) is True
    assert any(marker in r["properties"].get("tags", "") for r in live_graph.search(marker))


# ── OFFLINE: the connection probe itself (no server, runs in the PR suite) ─────────
# These are the regression tests for the defect that kept the lane above from ever
# running: the probe GET-ed a POST-only endpoint, so a healthy Neo4j 5 answered 405
# and the backend was written off as unreachable.


def test_connection_probe_posts_a_statement_not_a_get():
    g = Neo4jGraph(url="http://mock")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": [], "errors": []}
    posted = []
    with patch.object(httpx, "Client") as mock_client:
        def _capture(url, json=None, auth=None):
            posted.append((url, json))
            return mock_response

        mock_client.return_value.__enter__.return_value.post.side_effect = _capture
        assert g._check_connection() is True
        mock_client.return_value.__enter__.return_value.get.assert_not_called()
    assert posted[0][0] == "http://mock/db/neo4j/tx/commit"
    assert posted[0][1]["statements"][0]["statement"] == "RETURN 1"


def test_connection_probe_fails_closed_on_unauthorized():
    g = Neo4jGraph(url="http://mock")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {
        "errors": [{"code": "Neo.ClientError.Security.Unauthorized"}]
    }
    with patch.object(httpx, "Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = mock_response
        assert g._check_connection() is False


def test_connection_probe_fails_closed_when_the_body_reports_errors():
    """A 200 whose body carries `errors` (e.g. no such database) is not a working
    backend — the probe must not wave it through."""
    g = Neo4jGraph(url="http://mock")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [], "errors": [{"code": "Neo.ClientError.Database.DatabaseNotFound"}]
    }
    with patch.object(httpx, "Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = mock_response
        assert g._check_connection() is False


def test_connection_probe_fails_closed_on_a_non_json_200():
    """Something that answers 200 with HTML is not Neo4j."""
    g = Neo4jGraph(url="http://mock")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("not json")
    with patch.object(httpx, "Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = mock_response
        assert g._check_connection() is False


def test_add_entity_serialises_a_map_valued_property():
    """Real Neo4j rejects a map property and drops the WHOLE node. The writer path
    sends one (`worldview_sync._details`), so coerce it at the boundary."""
    g = Neo4jGraph(url="http://mock")
    g._connected = True
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [{"columns": ["n"], "data": [{"row": [{}]}]}], "errors": []
    }
    posted = []
    with patch.object(httpx, "Client") as mock_client:
        def _capture(url, json=None, auth=None):
            posted.append(json)
            return mock_response

        mock_client.return_value.__enter__.return_value.post.side_effect = _capture
        ok = g.add_entity(
            "DarkVesselEvent 412331100 — Strait of Hormuz", "geo_event",
            {"aoi": "Strait of Hormuz", "source": None, "valid_time": 1780865129.7,
             "jarvis_tainted": True, "tags": ["dark", "ais"],
             "details": {"mmsi": "412331100", "status": "dark", "gapSeconds": 60}},
        )
    assert ok is True
    params = posted[0]["statements"][0]["parameters"]
    assert "412331100" in params["p_details"] and isinstance(params["p_details"], str)
    # toString() raises on a list in Neo4j 5, which would take the whole property
    # scan down for every node — arrays are serialised for that reason.
    assert isinstance(params["p_tags"], str)
    # Primitives are passed through untouched.
    assert params["p_aoi"] == "Strait of Hormuz"
    assert params["p_source"] is None
    assert params["p_valid_time"] == 1780865129.7
    assert params["p_jarvis_tainted"] is True


def test_worldview_sync_details_shape_survives_the_neo4j_boundary():
    """Pin the coupling: the sync's own output must be storable."""
    obj = {"properties": {"mmsi": "412331100", "status": "dark", "gapSeconds": 60}}
    coerced = {k: _neo4j_property_value(v) for k, v in _details(obj).items()}
    assert isinstance(coerced["details"], str)
    assert "412331100" in coerced["details"]
