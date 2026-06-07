# WorldView Ingestion Workers

Python workers that fetch OSINT sources, normalize them to the canonical telemetry
envelope, and publish to per-domain Kafka topics.

## Status

STEP 3 implemented — fetch + normalize logic for every source, with the pure
transformation core unit-tested:

- **ADS-B** (`adsb/`) — production source layer (`sources.py`): **OpenSky** (OAuth2
  client-credentials → bearer, falls back to anonymous, optional viewport bbox, rate-limit
  aware) **or ADSB.fi** (free, AOI-centered, with real military tagging via `dbFlags`);
  adaptive polling + exponential backoff. Select with `ADSB_SOURCE=opensky|adsbfi`.
- **AIS** (`ais/`) — AISStream WebSocket with **reconnect + exponential backoff**; config-driven
  bounding box (`AIS_BBOX`); testable subscription + frame handling in `stream.py`.
- **TLE/SGP4** (`tle/`) — SGP4 propagation (TEME→WGS84), data-driven sensor footprints, and a
  pluggable catalog source (`sources.py`): **Celestrak** (GROUP, optional NORAD filter) or
  **Space-Track** (session login + `gp` query); periodic catalog refresh as TLEs age; a curated
  per-NORAD **sensor registry** (`sensors.py`) drives optical/SAR footprints + recon daylight.
- **EW/H3** (`ew/`) — **GPSJam** daily-heatmap parser (`gpsjam.py`, pre-binned H3 hexagons →
  `bad/(good+bad)` intensity) + H3 point-aggregation (`h3grid.py`) for raw sources (IODA).
- **Context** (`context/`) — NOTAM / strike-zone / geopolitical-event normalizers, fed from a
  configurable events GeoJSON feed + NOTAM feed (`CONTEXT_EVENTS_URL` / `CONTEXT_NOTAM_URL`).
- **Dark Vessel Detection** (`darkwatch/`) — geofenced AIS-gap detector with dead-reckoned
  extrapolation (design doc §9.1).

The async `run()` loops fetch live sources; the network wiring runs against real OSINT
endpoints in deployment. The persistence consumers (Redis live-state + TimescaleDB history)
are **STEP 4**.

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m worldview_ingest adsb     # run a worker: adsb | ais | tle | ew | context
```

## Test

```bash
pip install pytest
python -m pytest tests/ -o addopts=""   # 25 tests: geo, TLE/SGP4, H3, normalizers, darkwatch, context
```

## Layout

```
worldview_ingest/
  envelope.py     canonical normalized event envelope (design doc §3)
  kafka_io.py     async producer + DOMAIN_TOPICS map (§4)
  config.py       env-derived settings
  geo.py          shared geodesy (destination point, circle WKT, point-in-polygon)
  adsb/ ais/      normalize.py (pure) + worker.py (fetch loop)
  tle/            catalog.py, propagate.py (SGP4), footprint.py, worker.py
  ew/             h3grid.py (H3 aggregation) + worker.py
  context/        normalize.py (NOTAM/event -> envelope) + worker.py
  darkwatch/      detector.py (pure) + worker.py (Kafka consumer)
  wkt.py          GeoJSON geometry -> WKT;  timeutil.py  ISO-8601 -> UTC epoch
```
