# WorldView Ingestion Workers

Python workers that fetch OSINT sources, normalize them to the canonical telemetry
envelope, and publish to per-domain Kafka topics.

## Status

STEP 3 implemented — fetch + normalize logic for every source, with the pure
transformation core unit-tested:

- **ADS-B** (`adsb/`) — OpenSky state-vector normalizer + polling loop.
- **AIS** (`ais/`) — AISStream position-report normalizer + WebSocket loop.
- **TLE/SGP4** (`tle/`) — catalog parsing, SGP4 propagation (TEME→WGS84 geodetic), and
  data-driven sensor footprints (optical cone / SAR swath / coverage circle).
- **EW/H3** (`ew/`) — Uber H3 aggregation of jamming/interference observations into cells.
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
python -m worldview_ingest adsb     # run a worker: adsb | ais | tle | ew
```

## Test

```bash
pip install pytest
python -m pytest tests/ -o addopts=""   # 18 tests: geo, TLE/SGP4, H3, normalizers, darkwatch
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
  darkwatch/      detector.py (pure) + worker.py (Kafka consumer)
```

The `context` layer (NOTAMs / strike zones / events) is lower-cadence; its parser is added
alongside the STEP 4 API work.
