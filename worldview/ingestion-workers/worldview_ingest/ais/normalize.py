"""Normalize AISStream position reports to the canonical envelope (Layer B)."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from worldview_ingest.envelope import TelemetryEnvelope


def normalize_aisstream(
    msg: dict[str, Any], source: str = "aisstream"
) -> TelemetryEnvelope | None:
    """Map an AISStream PositionReport message to a TelemetryEnvelope, or None if unusable."""
    if msg.get("MessageType") != "PositionReport":
        return None

    meta = msg.get("MetaData") or {}
    mmsi = meta.get("MMSI")
    lat = meta.get("latitude")
    lon = meta.get("longitude")
    if mmsi is None or lat is None or lon is None:
        return None

    report = (msg.get("Message") or {}).get("PositionReport") or {}
    ts = _parse_ais_time(meta.get("time_utc"))
    payload = {
        "sog_kt": report.get("Sog"),
        "cog_deg": report.get("Cog"),
        "heading_deg": report.get("TrueHeading"),
        "nav_status": report.get("NavigationalStatus"),
        "ship_name": (meta.get("ShipName") or "").strip() or None,
    }
    return TelemetryEnvelope(
        domain="ais",
        source=source,
        entity_id=str(mmsi),
        ts=ts,
        lon=float(lon),
        lat=float(lat),
        payload=payload,
    )


def _parse_ais_time(value: str | None) -> float:
    """Parse AISStream's `time_utc` (e.g. '2024-06-07 12:00:00.123 +0000 UTC').

    Falls back to current time when absent or unparseable.
    """
    if not value:
        return time.time()
    head = value.strip()
    for cut, fmt in ((26, "%Y-%m-%d %H:%M:%S.%f"), (19, "%Y-%m-%d %H:%M:%S")):
        try:
            return datetime.strptime(head[:cut], fmt).timestamp()
        except ValueError:
            continue
    return time.time()
