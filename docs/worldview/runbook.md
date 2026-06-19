# Jarvis Signal Layer Runbook

## 1. Windows one-click startup

`START.bat` now auto-starts the Jarvis Signal Layer in a separate window after the existing WorldView startup block and before `serve.py`.

Default behavior:

```bat
START.bat
```

Starts:

```text
Jarvis Hub:     http://127.0.0.1:8080
Signal Layer:   http://127.0.0.1:8787/healthz
WorldView:      http://localhost:3000, when enabled and installed
```

The Signal Layer defaults to replay mode so Windows startup works without WorldMonitor or API keys.

Opt out:

```bat
set JARVIS_SIGNAL_LAYER=0
START.bat
```

Live WorldMonitor mode is opt-in:

```bat
set JARVIS_WORLDVIEW_MODE=live
set WORLDMONITOR_BASE_URL=http://localhost:3000
set WORLDMONITOR_MCP_URL=http://localhost:3000/api/mcp
START.bat
```

## 2. Replay mode

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

## 3. Live mode

Run WorldMonitor separately, then:

```bash
export JARVIS_WORLDVIEW_MODE=live
export WORLDMONITOR_BASE_URL=http://localhost:3000
export WORLDMONITOR_MCP_URL=http://localhost:3000/api/mcp
cd services/signal-layer
npm start
```

## 4. Degraded provider behavior

The live provider should not crash the service. When WorldMonitor is down, routes should return:

```json
{
  "provider": "worldmonitor",
  "status": "degraded",
  "mode": "live"
}
```

## 5. Demo safety

Use replay mode during the Sunday demo unless live data has been verified immediately beforehand.

```bash
export JARVIS_WORLDVIEW_MODE=replay
npm start
```

On Windows, this is already the default when launched from `START.bat`.

## 6. Jarvis Hub UI integration

Set:

```bash
NEXT_PUBLIC_SIGNAL_LAYER_URL=http://localhost:8787
```

Mount `WorldViewPage` under the Jarvis route you want, for example:

```text
/jarvis/worldview
```
