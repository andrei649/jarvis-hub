"""Load-test rig + as-of-T query SLO (ticket H19.1.6).

A tool (NOT an ingestion worker) that drives synthetic telemetry at a target rate
and measures the backend ``/history`` as-of-T query latency SLO (p50/p95/p99).

The package is split into deterministic, heavily unit-tested PURE cores plus a thin
async harness:

* :mod:`worldview_ingest.loadtest.generator` — synthetic, seeded ``TelemetryEnvelope``
  generation (deterministic icao24/mmsi/geom within a bbox, monotonic ts).
* :mod:`worldview_ingest.loadtest.rate` — a drift-free rate scheduler (pure, injected
  clock) that yields how many messages to send per tick to hit a target msg/s.
* :mod:`worldview_ingest.loadtest.metrics` — pure latency statistics (p50/p95/p99/
  max/mean) and an SLO verdict (:func:`metrics.slo_check`).
* :mod:`worldview_ingest.loadtest.runner` — the async harness wiring a produce loop
  (generator + scheduler -> injectable producer) and an as-of-T ``/history`` probe
  loop (injectable async http client) that records real query latencies into the
  metrics, then returns an SLO report. Both degrade gracefully (no producer/client
  -> no-op). The rig measures REAL query latency; it never fabricates query results.
"""

from __future__ import annotations
