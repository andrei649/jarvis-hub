"""Normalize contextual intel (NOTAMs, strike zones, events) to context envelopes (Layer E).

Context envelopes carry a `payload.kind` (event | notam) so the history-writer routes them to
the right table (geopolitical_events / notams). Polygon geometries travel as geom_wkt; point
events travel as lon/lat.
"""

from __future__ import annotations

import time
from typing import Any

from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.timeutil import parse_iso_utc
from worldview_ingest.wkt import geojson_geometry_to_wkt


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

    if geometry["type"] == "Point":
        lon, lat = geometry["coordinates"][0], geometry["coordinates"][1]
        return TelemetryEnvelope(
            domain="context", source=source, entity_id=entity_id, ts=ts,
            lon=float(lon), lat=float(lat), payload=payload,
        )
    return TelemetryEnvelope(
        domain="context", source=source, entity_id=entity_id, ts=ts,
        geom_wkt=geojson_geometry_to_wkt(geometry), payload=payload,
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
    return TelemetryEnvelope(
        domain="context",
        source=source,
        entity_id=notam_id,
        ts=effective_from,
        geom_wkt=geojson_geometry_to_wkt(geometry),
        payload={
            "kind": "notam",
            "notam_type": record.get("type"),
            "effective_from": effective_from,
            "effective_to": parse_iso_utc(record.get("effective_to")),
        },
    )
