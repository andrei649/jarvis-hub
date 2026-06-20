# Sunday Demo Script — Jarvis World Intelligence

## Demo title

Jarvis World Intelligence: from external-world signals to personal relevance.

## Demo rule

Use replay mode unless live WorldMonitor has been verified immediately before the demo.

```text
Replay mode = guaranteed demo path.
Live WorldMonitor = optional upgrade path.
```

## Pre-flight

### Windows

```bat
START.bat
```

Expected surfaces:

```text
Jarvis Hub:     http://127.0.0.1:8080
WorldView:      http://localhost:3000, when installed
Signal Layer:   http://127.0.0.1:8787/healthz
```

### Linux/macOS

```bash
./start.sh
```

### Quick checks

```bash
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8787/briefs/world
curl "http://127.0.0.1:8787/signals?limit=8&relevantOnly=true"
```

Expected: replay-mode JSON with `ok`, `brief`, and relevant signals.

## 1. Open Jarvis HUD

Open:

```text
http://127.0.0.1:8080/
```

Narrative:

> Jarvis now has a provider-neutral Signal Layer. It turns external-world feeds into evidence, signals, relevance, assessments, and governed recommendations.

## 2. Open Observe mode

Navigate to:

```text
Observe
```

Show the **World Intelligence** panel at the top of Observe.

Point out:

```text
Signal Layer status
mode/provider
Global status
Relevant signals
Global Intelligence Brief
Freshness/source labels
```

Narrative:

> WorldView remains the 4D/geospatial OSINT surface. The Signal Layer is the fusion brain. WorldMonitor is an optional live provider behind that boundary.

## 3. Show top signals

Show the `TOP SIGNALS` section.

Point out for each row:

```text
signal type
severity
confidence
claim status
relevance score
source family / stale flag
```

Narrative:

> Jarvis does not treat every external event as equal. It scores relevance against watch targets and carries the evidence state forward.

## 4. Show recommendations

Show `RECOMMENDATIONS · preview`.

Narrative:

> These are recommendations, not autonomous actions. Anything external or high-impact must go through Jarvis approval before execution.

Use this sentence exactly if asked whether it acted:

```text
No action was taken. This is a preview recommendation requiring approval.
```

## 5. Ask Jarvis / Argus

Prompt:

```text
What changed overnight that matters to me?
```

Expected behavior:

```text
Jarvis/Argus routes the world-intel prompt through SignalLayerPlugin.
Signal Layer returns a replay-backed answer.
The response is injected as REAL-TIME DATA — SIGNAL-LAYER.
```

Expected answer qualities:

```text
brief summary
why it matters
confidence/freshness note
recommended next action
no unsupported claims
```

## 6. Country-risk prompt

Prompt:

```text
What is the current country risk for Romania?
```

Expected:

```text
country assessment
risk level
drivers
recommendations
freshness/confidence note
```

## 7. Optional WorldView surface

Open:

```text
http://localhost:3000
```

Narrative:

> This is the existing Jarvis WorldView 4D OSINT surface. It remains separate from WorldMonitor. The fused product is WorldView for spatial awareness plus Signal Layer for evidence-backed intelligence.

## 8. Optional live WorldMonitor contract

Only if WorldMonitor is already running on `:3100`:

```bash
cd services/signal-layer
JARVIS_SIGNAL_LAYER_MODE=live \
WORLDMONITOR_BASE_URL=http://localhost:3100 \
WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp \
npm run test:live-contract
```

Narrative:

> Live WorldMonitor is an optional provider mode. Replay remains the deterministic demonstration path.

## Fallback script

If the HUD does not show the panel, use direct endpoints:

```bash
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8787/briefs/world
curl "http://127.0.0.1:8787/signals?limit=8&relevantOnly=true"
```

Narrative:

> The Signal Layer is running and returning evidence-backed world intelligence. The HUD integration is the visual surface over the same API.

## What not to claim

Do not say:

```text
WorldMonitor is fully live-validated.
Jarvis executed an action.
Raw OSINT is confirmed truth.
The approval queue is fully wired for these recommendations.
```

Say instead:

```text
Replay mode is demo-safe and deterministic.
Live WorldMonitor has a contract test path.
Recommendations are preview-only until submitted through approval.
Raw OSINT, inference, forecast, and confirmed facts stay separated.
```

## Five-minute timing

```text
00:00–00:45  Open Jarvis HUD and Observe mode
00:45–01:45  Show World Intelligence brief and top signals
01:45–02:30  Explain evidence/freshness/confidence/relevance
02:30–03:15  Show recommendations preview and governance boundary
03:15–04:15  Ask “What changed overnight that matters to me?”
04:15–05:00  Show WorldView split and optional live contract path
```

## Closing line

> Jarvis can now observe external reality, convert it into evidence-backed signals, decide what matters, explain why, and recommend safe next actions without confusing raw OSINT for truth.
