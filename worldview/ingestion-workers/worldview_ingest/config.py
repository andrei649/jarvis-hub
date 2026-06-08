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

    # --- Recon (Layer C insight) ---
    # Predicts AOI coverage windows over the TLE catalog (reuses the tle_* source settings)
    # and publishes them to its own topic. Set TLE_NORAD_IDS to a curated recon set to bound
    # the CPU cost (build_source filters the catalog when it is set).
    recon_topic: str = os.getenv("RECON_TOPIC", "osint.recon")
    recon_interval_seconds: int = int(os.getenv("RECON_INTERVAL_SECONDS", "300"))
    recon_horizon_seconds: int = int(os.getenv("RECON_HORIZON_SECONDS", str(24 * 3600)))
    recon_step_seconds: int = int(os.getenv("RECON_STEP_SECONDS", "30"))
    # AOIs to predict: "id:lon,lat,radius_km;id2:..." (empty = a single Strait-of-Hormuz AOI).
    aois: str = os.getenv("AOIS", "")

    # --- CEP (insight engine) ---
    # Windowed-keyed complex-event-processing over the recon stream. The engine buffers events
    # into per-key tumbling windows of cep_window_seconds and fires the tipping detector once
    # the watermark (= max_event_ts - cep_lateness_seconds) passes a window's close; events older
    # than the watermark are dropped as too-late. Consumes the recon topic(s); emits to its own
    # output topic. cep_tipping_* are the reused detector thresholds (see cep.tipping).
    cep_input_topics: str = os.getenv("CEP_INPUT_TOPICS", "osint.recon")
    cep_output_topic: str = os.getenv("CEP_OUTPUT_TOPIC", "osint.events")
    cep_window_seconds: int = int(os.getenv("CEP_WINDOW_SECONDS", "600"))
    cep_lateness_seconds: int = int(os.getenv("CEP_LATENESS_SECONDS", "120"))
    cep_tipping_delta_seconds: int = int(os.getenv("CEP_TIPPING_DELTA_SECONDS", "600"))
    cep_tipping_min_count: int = int(os.getenv("CEP_TIPPING_MIN_COUNT", "3"))

    # --- Capture swarm (governed OSINT capture, ticket H19.5.7) ---
    # A governed set of capture tasks that snapshot EPHEMERAL signals (a transient ADS-B squawk,
    # an AIS gap, a short-lived RF/jamming spike, a NOTAM about to expire) to a TTL'd ephemeral
    # cache so they aren't lost, each snapshot stamped with provenance, under a token-bucket
    # rate-limit (per-source AND global) so the swarm can't hammer sources or explode. Owns its
    # own producer/topic (osint.capture). The *_global_* limits default to the per-source values.
    capture_topic: str = os.getenv("CAPTURE_TOPIC", "osint.capture")
    capture_interval_seconds: int = int(os.getenv("CAPTURE_INTERVAL_SECONDS", "30"))
    capture_rate_per_sec: float = float(os.getenv("CAPTURE_RATE_PER_SEC", "5"))
    capture_burst: float = float(os.getenv("CAPTURE_BURST", "10"))
    capture_global_rate_per_sec: float = float(os.getenv("CAPTURE_GLOBAL_RATE_PER_SEC", "20"))
    capture_global_burst: float = float(os.getenv("CAPTURE_GLOBAL_BURST", "40"))
    capture_cache_ttl_seconds: float = float(os.getenv("CAPTURE_CACHE_TTL_SECONDS", "300"))
    capture_cache_capacity: int = int(os.getenv("CAPTURE_CACHE_CAPACITY", "10000"))

    # --- EW / Cyber (Layer D) ---
    ew_source: str = os.getenv("EW_SOURCE", "gpsjam")
    gpsjam_base_url: str = os.getenv("GPSJAM_BASE_URL", "https://gpsjam.org/data")
    ew_poll_seconds: int = int(os.getenv("EW_POLL_SECONDS", "900"))

    # --- Context (Layer E) ---
    # A GeoJSON FeatureCollection of events, and a NOTAM records feed (both deployment-specific).
    context_events_url: str = os.getenv("CONTEXT_EVENTS_URL", "")
    context_notam_url: str = os.getenv("CONTEXT_NOTAM_URL", "")
    context_poll_seconds: int = int(os.getenv("CONTEXT_POLL_SECONDS", "300"))

    # --- Load-test rig + as-of-T SLO (TOOL, not a worker; ticket H19.1.6) ---
    # Pumps synthetic telemetry at LOADTEST_TARGET_RATE msg/s for LOADTEST_DURATION_S
    # seconds across LOADTEST_LAYERS, simulating LOADTEST_ENTITIES tracks per layer,
    # then fires as-of-T GET {LOADTEST_API_URL}/history/:layer?t=&bbox= queries and
    # measures the latency SLO (p95 < LOADTEST_SLO_P95_S). Run via `python -m
    # worldview_ingest.loadtest`; it is NOT in WORKERS — it is a measurement tool.
    loadtest_target_rate: float = float(os.getenv("LOADTEST_TARGET_RATE", "100"))
    loadtest_duration_s: float = float(os.getenv("LOADTEST_DURATION_S", "60"))
    loadtest_entities: int = int(os.getenv("LOADTEST_ENTITIES", "500"))
    # Comma-separated domains to load (adsb,ais,tle,ew,context).
    loadtest_layers: str = os.getenv("LOADTEST_LAYERS", "adsb,ais")
    loadtest_probe_count: int = int(os.getenv("LOADTEST_PROBE_COUNT", "200"))
    loadtest_slo_p95_s: float = float(os.getenv("LOADTEST_SLO_P95_S", "0.5"))
    loadtest_api_url: str = os.getenv("LOADTEST_API_URL", "http://localhost:8080")


settings = Settings()
