"""Normalize contextual intel (NOTAMs, strike zones, events) to context envelopes (Layer E).

Context envelopes carry a `payload.kind` (event | notam) so the history-writer routes them to
the right table (geopolitical_events / notams). Polygon geometries travel as geom_wkt; point
events travel as lon/lat.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.timeutil import parse_iso_utc
from worldview_ingest.wkt import geojson_geometry_to_wkt
from worldview_ingest.wkt_guard import WktBoundsError, coerce_coord

logger = logging.getLogger(__name__)


def normalize_event(feature: dict[str, Any], source: str = "osint") -> TelemetryEnvelope | None:
    """Map a GeoJSON event feature to a context envelope (kind=event)."""
    geometry = feature.get("geometry")
    if not geometry:
        return None
    props = feature.get("properties") or {}
    entity_id = str(props.get("id") or props.get("event_id") or "")
    if not entity_id:
        return None
    ts = parse_iso_utc(props.get("time") or props.get("ts")) or time.time()
    payload = {
        "kind": "event",
        "category": props.get("category", "event"),
        "severity": props.get("severity", 1),
    }

    try:
        if geometry["type"] == "Point":
            lon, lat = coerce_coord(geometry["coordinates"][0], geometry["coordinates"][1])
            return TelemetryEnvelope(
                domain="context", source=source, entity_id=entity_id, ts=ts,
                lon=lon, lat=lat, payload=payload,
            )
        geom_wkt = geojson_geometry_to_wkt(geometry)
    except (WktBoundsError, IndexError, TypeError, KeyError) as exc:
        # AUD-12/F12: drop a feature whose coordinates are out of bounds or
        # malformed rather than emit a bad envelope or crash the worker.
        logger.warning("normalize_event: dropping feature %s: %s", entity_id, exc)
        return None
    return TelemetryEnvelope(
        domain="context", source=source, entity_id=entity_id, ts=ts,
        geom_wkt=geom_wkt, payload=payload,
    )


def normalize_notam(record: dict[str, Any], source: str = "faa") -> TelemetryEnvelope | None:
    """Map a NOTAM record (id, type, effective_from/to, geometry) to a context envelope."""
    notam_id = str(record.get("id") or "")
    geometry = record.get("geometry")
    if not notam_id or not geometry:
        return None
    effective_from = parse_iso_utc(record.get("effective_from"))
    if effective_from is None:
        return None
    try:
        geom_wkt = geojson_geometry_to_wkt(geometry)
    except (WktBoundsError, IndexError, TypeError, KeyError) as exc:
        # AUD-12/F12: drop a NOTAM with out-of-bounds / malformed geometry.
        logger.warning("normalize_notam: dropping NOTAM %s: %s", notam_id, exc)
        return None
    return TelemetryEnvelope(
        domain="context",
        source=source,
        entity_id=notam_id,
        ts=effective_from,
        geom_wkt=geom_wkt,
        payload={
            "kind": "notam",
            "notam_type": record.get("type"),
            "effective_from": effective_from,
            "effective_to": parse_iso_utc(record.get("effective_to")),
        },
    )
