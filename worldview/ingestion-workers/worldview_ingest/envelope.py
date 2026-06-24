"""Canonical normalized event envelope (design doc §3).

Mirrors worldview/shared/schemas/telemetry.v1.schema.json. Every worker maps its source
format to this model before publishing, so downstream consumers are source-agnostic.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Domain = Literal["adsb", "ais", "tle", "ew", "context"]

_WKT_PREFIXES = ("POINT(", "POLYGON(", "MULTIPOLYGON(")


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

    @field_validator("geom_wkt")
    @classmethod
    def _validate_geom_wkt(cls, v: str | None) -> str | None:
        # AUD-12/F12: geom_wkt is built by string-formatting untrusted coordinates
        # (validated at the wkt.py chokepoint). This is a defence-in-depth backstop
        # so a value that isn't a known WKT geometry can never reach the database.
        if v is not None and not v.startswith(_WKT_PREFIXES):
            raise ValueError(f"geom_wkt must be a POINT/POLYGON/MULTIPOLYGON WKT, got {v[:32]!r}")
        return v
