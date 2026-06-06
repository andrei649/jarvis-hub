# WorldView Ingestion Workers

Python workers that fetch OSINT sources, normalize them to the canonical telemetry
envelope, and publish to per-domain Kafka topics.

## Status

STEP 2 scaffold — the package layout, the canonical `TelemetryEnvelope` (pydantic, mirrors
`shared/schemas/telemetry.v1.schema.json`), the `TelemetryProducer` (aiokafka, topic per
domain), config, and per-domain worker stubs. The fetch/normalize logic for each source
(SGP4 propagation, H3 aggregation, AIS/ADS-B parsing) is implemented in **STEP 3**.

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m worldview_ingest          # scaffold: prints domain -> topic routing
```

## Layout

```
worldview_ingest/
  envelope.py     canonical normalized event envelope (design doc §3)
  kafka_io.py     async producer + DOMAIN_TOPICS map (§4)
  config.py       env-derived settings
  adsb/ ais/ tle/ ew/   per-domain workers (run() stubs -> STEP 3)
```

The `context` layer (NOTAMs / strike zones / events) is lower-cadence and ingested via a
parser added alongside these in STEP 3.
