# Jarvis Signal Layer Runbook

## 1. Windows one-click startup

`START.bat` auto-starts the Jarvis Signal Layer in a separate window after the existing WorldView startup block and before `serve.py`.

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

Live WorldMonitor mode is opt-in. WorldMonitor should not use host port `:3000` because Jarvis's existing WorldView frontend owns that port. Use `:3100` by convention:

```bat
set JARVIS_SIGNAL_LAYER_MODE=live
set WORLDMONITOR_BASE_URL=http://localhost:3100
set WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp
START.bat
```

## 2. Linux/macOS startup

`start.sh` also starts the Signal Layer unless disabled:

```bash
./start.sh
```

Opt out:

```bash
JARVIS_SIGNAL_LAYER=0 ./start.sh
```

## 3. Replay mode

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

## 4. Live mode

Run WorldMonitor separately, mapped to host port `:3100`, then:

```bash
export JARVIS_SIGNAL_LAYER_MODE=live
export WORLDMONITOR_BASE_URL=http://localhost:3100
export WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp
cd services/signal-layer
npm start
```

`JARVIS_WORLDVIEW_MODE` is accepted only as a deprecated sprint fallback. Prefer `JARVIS_SIGNAL_LAYER_MODE`.

## 5. Optional live WorldMonitor contract check

This is not part of normal CI and should not block replay-mode demos. Use it only after starting a WorldMonitor sidecar on `:3100`:

```bash
cd services/signal-layer
JARVIS_SIGNAL_LAYER_MODE=live \
WORLDMONITOR_BASE_URL=http://localhost:3100 \
WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp \
npm run test:live-contract
```

The script checks WorldMonitor health, MCP tools, representative cache tools, country-risk resource reading, and normalizer output. If WorldMonitor is not running, it exits cleanly with a skipped JSON payload instead of failing the Sunday replay path.

## 6. Degraded provider behavior

The live provider should not crash the service. When WorldMonitor is down, routes should return:

```json
{
  "provider": "worldmonitor",
  "status": "degraded",
  "mode": "live"
}
```

## 7. Demo safety

Use replay mode during the Sunday demo unless live data has been verified immediately beforehand.

```bash
export JARVIS_SIGNAL_LAYER_MODE=replay
npm start
```

On Windows, this is already the default when launched from `START.bat`.

## 8. Jarvis agent integration

Agents should call the Python `SignalLayerPlugin` for evidence-backed world intelligence:

```python
from agents.core.plugins.signal_layer import SignalLayerPlugin

sl = SignalLayerPlugin()
await sl.world_brief()
await sl.signals(relevant_only=True)
await sl.country_assessment("RO")
await sl.ask_world("What changed overnight that matters to me?")
```

The existing `WorldViewPlugin` remains the bridge to the local WorldView 4D OSINT stack.

## 9. Jarvis Hub UI integration

For Vite HUD integration, prefer:

```bash
VITE_SIGNAL_LAYER_URL=http://localhost:8787
```

The active Sunday surface is the real Vite HUD Observe mode. The earlier `apps/jarvis-hub/src/features/worldview` scaffold remains a reference scaffold unless it is explicitly mounted later.
