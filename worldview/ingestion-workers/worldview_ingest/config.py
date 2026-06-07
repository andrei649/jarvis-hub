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

    # --- AIS (Layer B) ---
    aisstream_api_key: str = os.getenv("AISSTREAM_API_KEY", "")
    # AISStream bounding box "lat_sw,lon_sw,lat_ne,lon_ne" (empty = world; a box cuts volume).
    ais_bbox: str = os.getenv("AIS_BBOX", "")
    ais_reconnect_max_seconds: int = int(os.getenv("AIS_RECONNECT_MAX_SECONDS", "60"))

    # --- TLE / Space (Layer C) ---
    tle_source: str = os.getenv("TLE_SOURCE", "celestrak")  # celestrak | spacetrack
    tle_group: str = os.getenv("TLE_GROUP", "active")  # Celestrak GROUP (active|visual|...)
    # Optional comma-separated NORAD ids — a curated recon set; filters the fetched catalog.
    tle_norad_ids: str = os.getenv("TLE_NORAD_IDS", "")
    tle_propagate_seconds: int = int(os.getenv("TLE_PROPAGATE_SECONDS", "60"))
    tle_refresh_seconds: int = int(os.getenv("TLE_REFRESH_SECONDS", str(3 * 3600)))
    spacetrack_username: str = os.getenv("SPACETRACK_USERNAME", "")
    spacetrack_password: str = os.getenv("SPACETRACK_PASSWORD", "")


settings = Settings()
