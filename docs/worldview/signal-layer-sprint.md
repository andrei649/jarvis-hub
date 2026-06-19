# Jarvis Signal Layer Sprint

A drop-in starter implementation for **Jarvis Situational Awareness** using **WorldMonitor as provider #1**.

This repo is intentionally structured as a bounded integration layer, not a fork of WorldMonitor. It gives Jarvis a durable internal model:

```text
provider data → evidence → signals → relevance → assessments → brief → action queue
```

## What is included

- `services/signal-layer` — runnable Node.js service with no runtime dependencies.
- `WorldMonitorProvider` — MCP/HTTP adapter for a self-hosted WorldMonitor sidecar.
- `ReplayProvider` — deterministic fixture mode for demos, tests, and offline work.
- Evidence ledger, relevance scoring, assessment builder, World Analyst response layer.
- Jarvis-native schemas for `Signal`, `Evidence`, `Assessment`, `Brief`, `WatchTarget`, and `ActionRecommendation`.
- React/Next-style WorldView cockpit components for Jarvis Hub integration.
- Architecture decision record, runbook, demo script, smoke tests, and Docker examples.

## Fast start: replay mode

Replay mode works without WorldMonitor or API keys.

```bash
cd services/signal-layer
npm test
npm start
```

Then open:

```text
http://localhost:8787/healthz
http://localhost:8787/signals
http://localhost:8787/briefs/world
http://localhost:8787/assessments/country/RO
```

## Live mode with WorldMonitor

Run WorldMonitor separately as a sidecar, then start the signal layer:

```bash
export JARVIS_WORLDVIEW_MODE=live
export WORLDMONITOR_BASE_URL=http://localhost:3000
export WORLDMONITOR_MCP_URL=http://localhost:3000/api/mcp
cd services/signal-layer
npm start
```

The live provider uses MCP JSON-RPC first and HTTP health checks as fallback. If WorldMonitor is unavailable or returns an unexpected shape, the service returns a degraded provider state rather than crashing.

## Design principle

WorldMonitor is the first signal provider. Jarvis owns the schemas, evidence ledger, relevance engine, assessments, and action policy.

That means future providers can plug into the same contract:

```text
EmailProvider
CalendarProvider
GitHubProvider
FinanceProvider
SecurityProvider
WorldMonitorProvider
```

## Key routes

| Route | Purpose |
|---|---|
| `GET /healthz` | Signal Layer health |
| `GET /provider-health/worldmonitor` | Provider health and freshness |
| `GET /signals` | Normalized, relevance-scored signals |
| `GET /briefs/world` | Global Jarvis brief |
| `GET /assessments/country/:iso2` | Country assessment |
| `POST /ask/world` | World Analyst structured response |
| `GET /watchlist` | Default/demo watch targets |
| `POST /watchlist` | Add an in-memory watch target |

## Integration target

Use this service behind Jarvis Hub:

```text
Jarvis Hub UI → Signal Layer HTTP API → WorldMonitorProvider → WorldMonitor /api/mcp
```

The React components under `apps/jarvis-hub/src/features/worldview` expect the signal layer at `NEXT_PUBLIC_SIGNAL_LAYER_URL`.
