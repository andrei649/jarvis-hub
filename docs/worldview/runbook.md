# Jarvis Signal Layer Runbook

## 1. Replay mode

Use this for development, demos, and tests.

```bash
cd services/signal-layer
npm test
npm start
```

Expected:

```bash
curl http://localhost:8787/healthz
curl http://localhost:8787/signals
curl http://localhost:8787/briefs/world
curl http://localhost:8787/assessments/country/RO
```

## 2. Live mode

Run WorldMonitor separately, then:

```bash
export JARVIS_WORLDVIEW_MODE=live
export WORLDMONITOR_BASE_URL=http://localhost:3000
export WORLDMONITOR_MCP_URL=http://localhost:3000/api/mcp
cd services/signal-layer
npm start
```

## 3. Degraded provider behavior

The live provider should not crash the service. When WorldMonitor is down, routes should return:

```json
{
  "provider": "worldmonitor",
  "status": "degraded",
  "mode": "live"
}
```

## 4. Demo safety

Use replay mode during the Sunday demo unless live data has been verified immediately beforehand.

```bash
export JARVIS_WORLDVIEW_MODE=replay
npm start
```

## 5. Jarvis Hub UI integration

Set:

```bash
NEXT_PUBLIC_SIGNAL_LAYER_URL=http://localhost:8787
```

Mount `WorldViewPage` under the Jarvis route you want, for example:

```text
/jarvis/worldview
```
