"""worldview_sync.py — change-feed from the WorldView ontology into the JARVIS
knowledge graph (ticket H19.3.5).

Pulls the WorldView ontology (Areas of Interest + the geo-events linked to them —
dark-vessel detections, recon windows) through the gated read-only ``WorldViewPlugin``
and upserts them into the JARVIS :class:`KnowledgeGraph` as entities + relations, so a
normal JARVIS recall ("what happened in Hormuz last Tuesday") surfaces geo-events via
the *graph* arm of the RRF fusion (``memory/fusion.py``).

Design
------
- AOIs become ``geo_aoi`` entities named by their human title ("Strait of Hormuz").
- Each event becomes a ``geo_event`` entity whose NAME and properties embed the AOI
  title, so ``InMemoryGraph.search(location)`` matches it; plus an ``IN_AOI`` relation
  to the AOI entity (the graph edge).
- Provenance (source + valid/transaction time) rides along in the entity properties,
  so a recalled geo-event is still traceable to its WorldView source.

Fail-safe: if WorldView is unreachable the sync is a no-op (zero summary), never raises
into the JARVIS loop, and never fabricates events (it's an OSINT surface).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("jarvis.memory.worldview_sync")

# Ontology object types that represent geo-events worth surfacing in recall.
EVENT_TYPES = ("DarkVesselEvent", "ReconWindow")


def _details(obj: dict) -> dict[str, Any]:
    """A compact, search-visible snapshot of the object's ontology properties."""
    props = obj.get("properties")
    return {"details": props} if isinstance(props, dict) else {}


class WorldViewKGSync:
    """Syncs WorldView ontology objects/links into the JARVIS knowledge graph."""

    def __init__(self, memory, plugin):
        self.memory = memory  # MemoryManager (async add_fact / .graph)
        self.plugin = plugin  # WorldViewPlugin (ontology_objects / ontology_links)

    async def sync(self) -> dict[str, int]:
        """Pull AOIs + their linked geo-events and upsert them into the graph.

        Returns a summary ``{"aois", "events", "relations"}``. A no-op (all zeros)
        when WorldView is unavailable.
        """
        summary = {"aois": 0, "events": 0, "relations": 0}
        aoi_titles = await self._load_aois(summary)
        for obj_type in EVENT_TYPES:
            await self._sync_events(obj_type, aoi_titles, summary)
        if summary["aois"] or summary["events"]:
            logger.info("WorldView KG sync: %s", summary)
        return summary

    async def _load_aois(self, summary: dict[str, int]) -> dict[str, str]:
        """Add each AOI as a ``geo_aoi`` entity; return a map of {worldview id -> title}."""
        res = await self.plugin.ontology_objects("Aoi")
        titles: dict[str, str] = {}
        if not isinstance(res, dict) or res.get("status") != "ok":
            return titles
        for obj in res.get("objects", []) or []:
            oid = str(obj.get("id", ""))
            if not oid:
                continue
            title = str(obj.get("title") or oid)
            titles[oid] = title
            await self.memory.add_fact(
                name=title,
                entity_type="geo_aoi",
                properties={"worldview_type": "Aoi", "worldview_id": oid, **_details(obj)},
            )
            summary["aois"] += 1
        return titles

    async def _sync_events(
        self, obj_type: str, aoi_titles: dict[str, str], summary: dict[str, int]
    ) -> None:
        res = await self.plugin.ontology_objects(obj_type)
        if not isinstance(res, dict) or res.get("status") != "ok":
            return
        for obj in res.get("objects", []) or []:
            oid = str(obj.get("id", ""))
            if not oid:
                continue
            aoi_label = await self._aoi_for(obj_type, oid, obj, aoi_titles)
            base_title = str(obj.get("title") or f"{obj_type} {oid}")
            # Node identity is the STABLE worldview_id, not the display title — so two
            # sync passes of the same logical event UPSERT one node instead of minting
            # a new node per pass (unbounded graph growth). We still embed the AOI label
            # in the NAME (and as a property) so a location keyword ("Hormuz") finds it;
            # the human display title rides along in `title`.
            name = self._event_name(obj_type, oid, aoi_label)
            prov = obj.get("provenance") if isinstance(obj.get("provenance"), dict) else {}
            await self.memory.add_fact(
                name=name,
                entity_type="geo_event",
                properties={
                    "worldview_type": obj_type,
                    "worldview_id": oid,
                    "title": base_title,
                    "aoi": aoi_label,
                    "source": prov.get("source"),
                    "valid_time": prov.get("ts"),
                    "transaction_time": prov.get("ingestedAt"),
                    **_details(obj),
                },
            )
            summary["events"] += 1
            if aoi_label:
                # Ensure the AOI entity exists (recon AOIs aren't geofence AOIs), then link.
                if aoi_label not in aoi_titles.values():
                    await self.memory.add_fact(
                        name=aoi_label, entity_type="geo_aoi", properties={"worldview_type": "Aoi"}
                    )
                await self.memory.add_fact(
                    name=None, source=name, relation="IN_AOI", target=aoi_label
                )
                summary["relations"] += 1

    @staticmethod
    def _event_name(obj_type: str, oid: str, aoi_label: str) -> str:
        """Stable, search-friendly entity name for a geo-event.

        Anchored on the WorldView object id (the dedup/MERGE key) so re-syncs of the
        same logical event collapse to ONE node, while still embedding the AOI label
        so an ``InMemoryGraph.search("Hormuz")`` (and the Neo4j property scan) matches.
        """
        anchor = f"{obj_type} {oid}"
        return f"{anchor} — {aoi_label}" if aoi_label else anchor

    async def _aoi_for(
        self, obj_type: str, oid: str, obj: dict, aoi_titles: dict[str, str]
    ) -> str:
        """Resolve a human AOI label for an event: a DarkVesselEvent via its inGeofence
        link → AOI title; a ReconWindow via its ``aoiId`` property."""
        if obj_type == "DarkVesselEvent":
            res = await self.plugin.ontology_links(obj_type, oid)
            if isinstance(res, dict) and res.get("status") == "ok":
                for link in res.get("links", []) or []:
                    if link.get("type") == "inGeofence":
                        to_id = str(link.get("toId", ""))
                        return aoi_titles.get(to_id, to_id)
            return ""
        props = obj.get("properties") if isinstance(obj.get("properties"), dict) else {}
        return str(props.get("aoiId") or props.get("aoi_id") or props.get("aoi") or "")
