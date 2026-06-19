# Jarvis Signal Layer Sprint

A drop-in starter implementation for **Jarvis Situational Awareness** using **WorldMonitor as provider #1** and the existing Jarvis **WorldView** stack as the geospatial surface.

This repo is intentionally structured as a bounded integration layer, not a fork of WorldMonitor. It gives Jarvis a durable internal model:

```text
provider data → evidence → signals → relevance → assessments → brief → action queue
```

## Fusion model

```text
WorldView    = Jarvis-owned 4D geospatial OSINT UI/API (:3000 frontend, :4000 API)
WorldMonitor = external public-world intelligence provider (:3100 by Jarvis convention)
Signal Layer = Jarvis-owned fusion brain (:8787)
Argus        = agent interface over both WorldView and Signal Layer
```

See `docs/worldview/worldview-worldmonitor-fusion.md` for the product/architecture strategy.

## What is included

- `services/signal-layer` — runnable Node.js service with no runtime dependencies.
- `WorldMonitorProvider` — MCP/HTTP adapter for a self-hosted WorldMonitor sidecar.
- `ReplayProvider` — deterministic fixture mode for demos, tests, and offline work.
- Evidence ledger, relevance scoring, assessment builder, World Analyst response layer.
- Jarvis-native schemas for `Signal`, `Evidence`, `Assessment`, `Brief`, `WatchTarget`, and `ActionRecommendation`.
- Agent-facing `SignalLayerPlugin` for Jarvis/Argus calls.
- React/Next-style WorldView cockpit scaffold for later HUD integration.
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

Run WorldMonitor separately as a sidecar, mapped away from Jarvis WorldView's `:3000` frontend. Jarvis convention is host port `:3100`:

```bash
export JARVIS_SIGNAL_LAYER_MODE=live
export WORLDMONITOR_BASE_URL=http://localhost:3100
export WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp
cd services/signal-layer
npm start
```

The live provider uses MCP JSON-RPC first and HTTP health checks as fallback. If WorldMonitor is unavailable or returns an unexpected shape, the service returns a degraded provider state rather than crashing.

`JARVIS_WORLDVIEW_MODE` is accepted only as a deprecated fallback during the sprint. Prefer `JARVIS_SIGNAL_LAYER_MODE`.

## Design principle

WorldMonitor is the first external-world signal provider. Jarvis owns the schemas, evidence ledger, relevance engine, assessments, and action policy.

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
Jarvis Hub UI / Argus → Signal Layer HTTP API → WorldMonitorProvider → WorldMonitor /api/mcp
```

The current React scaffold under `apps/jarvis-hub/src/features/worldview` is not yet the active Vite HUD surface. The next UI step is to mount or port this cockpit into the real `frontend/` app.
