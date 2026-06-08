"""Tests for the WorldView → JARVIS knowledge-graph sync (H19.3.5).

Proves the change-feed: WorldView ontology geo-events land in the graph and a
RRF-fused recall keyed on the location surfaces them via the graph source.
"""

from __future__ import annotations

from agents.core.memory.manager import MemoryManager
from agents.core.memory.worldview_sync import WorldViewKGSync


class FakeWorldView:
    """Stands in for WorldViewPlugin's ontology read methods."""

    def __init__(self, aois, events_by_type, links_by_id, status="ok"):
        self._aois = aois
        self._events = events_by_type
        self._links = links_by_id
        self._status = status

    async def ontology_objects(self, obj_type, limit=None):
        if self._status != "ok":
            return {"status": "unavailable", "error": "down"}
        objs = self._aois if obj_type == "Aoi" else self._events.get(obj_type, [])
        return {"status": "ok", "type": obj_type, "objects": objs}

    async def ontology_links(self, obj_type, obj_id):
        if self._status != "ok":
            return {"status": "unavailable", "error": "down"}
        return {"status": "ok", "type": obj_type, "id": obj_id, "links": self._links.get(obj_id, [])}


def _hormuz_fixture():
    aois = [{
        "id": "1", "type": "Aoi", "title": "Strait of Hormuz",
        "properties": {"category": "chokepoint"},
        "provenance": {"source": None, "ts": None, "ingestedAt": None},
    }]
    dv = {
        "id": "412331100:1780865129.713659", "type": "DarkVesselEvent",
        "title": "Dark vessel 412331100",
        "properties": {"mmsi": "412331100", "status": "dark", "gapSeconds": 60},
        "provenance": {"source": "demo", "ts": 1780865129.713659, "ingestedAt": 1780865200.0},
    }
    events = {"DarkVesselEvent": [dv], "ReconWindow": []}
    links = {"412331100:1780865129.713659": [
        {"type": "inGeofence", "fromType": "DarkVesselEvent",
         "fromId": "412331100:1780865129.713659", "toType": "Aoi", "toId": "1", "properties": {}},
    ]}
    return FakeWorldView(aois, events, links)


async def test_sync_ingests_geo_events_into_graph():
    mm = MemoryManager()
    summary = await WorldViewKGSync(mm, _hormuz_fixture()).sync()
    assert summary == {"aois": 1, "events": 1, "relations": 1}

    # The geo-event is in the graph and findable by the location keyword.
    hits = mm.graph.search("Hormuz")
    assert any(h["type"] == "geo_event" for h in hits)
    assert any(h["type"] == "geo_aoi" for h in hits)
    # Provenance rode along so the recalled event is still traceable to WorldView.
    ev = next(h for h in hits if h["type"] == "geo_event")
    assert ev["properties"]["source"] == "demo"
    assert ev["properties"]["aoi"] == "Strait of Hormuz"

    # The IN_AOI edge connects the event to the AOI.
    rels = mm.graph.get_relations("Strait of Hormuz")
    assert any(r["relation"] == "IN_AOI" for r in rels)


async def test_recall_returns_geo_event_via_rrf():
    mm = MemoryManager()
    await WorldViewKGSync(mm, _hormuz_fixture()).sync()

    # "what happened in Hormuz last Tuesday" — keyed on the extracted location.
    fused = await mm.recall("what happened in Hormuz last Tuesday", keyword="Hormuz")
    assert fused, "recall returned nothing"
    # At least one fused hit came from the graph source and is the geo-event.
    assert any("graph" in fh.sources for fh in fused)
    assert any("Hormuz" in fh.id and fh.payload.get("type") == "geo_event" for fh in fused)


async def test_sync_is_noop_when_worldview_unavailable():
    mm = MemoryManager()
    down = FakeWorldView([], {}, {}, status="down")
    summary = await WorldViewKGSync(mm, down).sync()
    assert summary == {"aois": 0, "events": 0, "relations": 0}
