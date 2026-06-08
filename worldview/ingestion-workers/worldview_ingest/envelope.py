"""Canonical normalized event envelope (design doc §3).

Mirrors worldview/shared/schemas/telemetry.v1.schema.json. Every worker maps its source
format to this model before publishing, so downstream consumers are source-agnostic.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

Domain = Literal["adsb", "ais", "tle", "ew", "context"]


class TelemetryEnvelope(BaseModel):
    # `schema` is the wire field name; aliased to schema_ to avoid shadowing BaseModel APIs.
    schema_: Literal["worldview.telemetry.v1"] = Field(
        default="worldview.telemetry.v1", alias="schema"
    )
    domain: Domain
    source: str
    entity_id: str
    ts: float
    ingested_at: float = Field(default_factory=time.time)
    lon: float | None = None
    lat: float | None = None
    alt_m: float | None = None
    geom_wkt: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
