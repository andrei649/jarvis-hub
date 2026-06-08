"""AISStream protocol helpers (Layer B) — the testable, network-free core of the AIS worker.

`build_subscription` constructs the AISStream subscribe message from config; `handle_frame`
turns one raw WebSocket frame into a normalized envelope (or None). The reconnecting connect
loop lives in worker.py.
"""

from __future__ import annotations

import json

from worldview_ingest.ais.normalize import normalize_aisstream
from worldview_ingest.config import Settings
from worldview_ingest.envelope import TelemetryEnvelope

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
WORLD_BBOX = [[[-90.0, -180.0], [90.0, 180.0]]]


def build_subscription(settings: Settings, api_key: str | None = None) -> dict:
    """Build the AISStream subscribe message; raises if no API key is configured."""
    key = api_key or settings.aisstream_api_key
    if not key:
        raise RuntimeError("AISSTREAM_API_KEY is required for the AIS worker")
    return {
        "APIKey": key,
        "BoundingBoxes": _bounding_boxes(settings.ais_bbox),
        "FilterMessageTypes": ["PositionReport"],
    }


def handle_frame(raw: str | bytes) -> TelemetryEnvelope | None:
    """Parse one AISStream frame to an envelope, or None if malformed / not a position report."""
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(msg, dict):
        return None
    return normalize_aisstream(msg)


def _bounding_boxes(raw: str) -> list:
    """AISStream wants [[[lat_sw, lon_sw], [lat_ne, lon_ne]]]; empty config = the whole world."""
    if not raw.strip():
        return WORLD_BBOX
    parts = [float(p) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"AIS_BBOX must be 'lat_sw,lon_sw,lat_ne,lon_ne', got {raw!r}")
    return [[[parts[0], parts[1]], [parts[2], parts[3]]]]
