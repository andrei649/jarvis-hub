"""Worker configuration, derived from environment (loads .env if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    kafka_brokers: str = os.getenv("KAFKA_BROKERS", "localhost:9092")
    schema_registry_url: str = os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")

    # --- ADS-B (Layer A) ---
    # Source: "opensky" (OAuth2 client-credentials, falls back to anonymous) | "adsbfi" (free).
    adsb_source: str = os.getenv("ADSB_SOURCE", "opensky")
    adsb_poll_seconds: int = int(os.getenv("ADSB_POLL_SECONDS", "15"))
    # OpenSky viewport filter "lamin,lomin,lamax,lomax" (empty = global; bbox cuts API credits).
    adsb_bbox: str = os.getenv("ADSB_BBOX", "")
    # ADSB.fi is centered: "lat,lon" + radius (nm). Defaults to the Strait of Hormuz AOI.
    adsb_center: str = os.getenv("ADSB_CENTER", "26.6,56.4")
    adsb_radius_nm: int = int(os.getenv("ADSB_RADIUS_NM", "250"))
    # OpenSky OAuth2 client credentials (the 2025+ auth model; basic auth is deprecated).
    opensky_client_id: str = os.getenv("OPENSKY_CLIENT_ID", "")
    opensky_client_secret: str = os.getenv("OPENSKY_CLIENT_SECRET", "")


settings = Settings()
