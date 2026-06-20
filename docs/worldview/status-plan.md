# Jarvis World Intelligence — Status and Execution Plan

_Last updated: 2026-06-20, sprint branch `feature/jarvis-signal-layer`._

## Product thesis

Jarvis should fuse the strongest parts of the existing Jarvis WorldView stack and WorldMonitor without collapsing their boundaries.

```text
WorldView    = Jarvis-owned 4D/geospatial OSINT surface (:3000 UI, :4000 API)
WorldMonitor = optional external public-world intelligence provider (:3100 by Jarvis convention)
Signal Layer = Jarvis-owned fusion brain (:8787)
Argus        = governed agent interface over both
```

The durable Jarvis asset is the Signal Layer pipeline:

```text
provider data → evidence → signals → relevance → assessments → brief → governed recommendations
```

## Current branches and PRs

| Branch / PR | Purpose | Status |
|---|---|---|
| `feature/jarvis-signal-layer` / PR #248 | Integration spine | Open draft; main is moving; mergeability not yet resolved |
| `feature/world-intelligence-demo-freeze` / PR #261 | Isolated Sunday demo script | Small child PR against #248 |
| `feature/world-intelligence-hud-polish` | Safe child branch for frontend polish | Created; use for non-conflict HUD improvements |

## Current implementation status

| Area | Status | Notes |
|---|---:|---|
| Signal Layer service | Strong v0.1 | Replay provider, provider health, routes, brief, signals, assessments, watchlist |
| Replay/demo path | Strong | Deterministic fixtures; does not require WorldMonitor, Docker, or API keys |
| Windows startup | Good | `START.bat` launches Signal Layer by default unless `JARVIS_SIGNAL_LAYER=0` |
| Unix startup | Good | `start.sh` launches Signal Layer by default unless `JARVIS_SIGNAL_LAYER=0` |
| Jarvis-native HUD | Medium-good | Real Vite HUD Observe mode now includes World Intelligence panel |
| Agent bridge | Medium-good | `SignalLayerPlugin` exists; `plugin_gatherer` routes world-intel prompts into it |
| Live WorldMonitor | Medium-low | Optional live contract check exists; payload normalizers still need validation against real sidecar |
| Governance bridge | Medium-low | Recommendations are preview-only; not yet submitted into real approval queue |
| Merge readiness | Blocked | Branch/main drift plus latest CI visibility must be resolved before undraft/merge |

## Current user-visible Sunday path

```text
START.bat / start.sh
→ Jarvis Hub (:8080)
→ existing WorldView (:3000/:4000, when installed)
→ Signal Layer replay mode (:8787)
→ HUD Observe mode shows World Intelligence
→ Jarvis/Argus prompts consume Signal Layer data
```

## Completed work

### Signal Layer backend

- Added `services/signal-layer` service.
- Added replay provider and deterministic fixtures.
- Added WorldMonitor live provider skeleton using MCP JSON-RPC.
- Added evidence, relevance, assessment, brief, watchlist, and World Analyst endpoint.
- Added routes:

```text
GET  /healthz
GET  /provider-health/worldmonitor
GET  /signals
GET  /briefs/world
GET  /assessments/country/:iso2
GET  /watchlist
POST /watchlist
POST /ask/world
```

### Shared types

- Added `packages/worldview-core` with provider-neutral types:

```text
Signal
Evidence
Assessment
Brief
ProviderHealth
WatchTarget
ActionRecommendation
```

### Startup

- Updated `START.bat` to start Signal Layer on `:8787` in replay mode by default.
- Updated `start.sh` to start Signal Layer on `:8787` in replay mode by default.
- Added opt-out:

```text
JARVIS_SIGNAL_LAYER=0
```

### HUD

- Added `frontend/src/api/signalLayer.ts`.
- Added `frontend/src/world-intelligence.tsx`.
- Integrated World Intelligence into Vite HUD Observe mode.
- Signal Layer health can mark Observe mode live so replay mode appears in the Sunday path.

### Agent bridge

- Added `agents/core/plugins/signal_layer.py`.
- Registered `signal-layer` plugin as LAN-only/local-only.
- Updated `plugin_gatherer` to detect world-intelligence prompts and inject Signal Layer data.
- Added tests for the gatherer path.

### Live validation

- Added optional live contract check:

```bash
cd services/signal-layer
JARVIS_SIGNAL_LAYER_MODE=live \
WORLDMONITOR_BASE_URL=http://localhost:3100 \
WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp \
npm run test:live-contract
```

This is not normal CI and should not block replay-mode demos.

### Docs

- Added/updated fusion strategy, runbook, demo script, status/plan, backlog.
- Added child PR #261 to freeze the Sunday demo script separately.

## Known risks and drifts

### 1. `main` is moving

PR #248 currently has `mergeable: false` from GitHub metadata. Treat this as a branch-drift/merge-readiness blocker, not a Sunday replay-demo blocker.

Mitigation:

```text
Keep PR #248 as integration spine.
Create small child PRs against #248 for isolated work.
Resolve conflicts after main stabilizes.
```

### 2. Vite source vs built bundle

Jarvis serves the committed Vite bundle from `agents/web/v2`. Source changes under `frontend/` may require:

```bash
cd frontend
npm run build
```

and then committing the generated `agents/web/v2` changes.

Mitigation:

```text
Before undrafting/merging, run frontend build and commit generated bundle if changed.
```

### 3. Live WorldMonitor contract is unvalidated

The live provider is present but not trusted until tested against a running WorldMonitor sidecar on `:3100`.

Mitigation:

```text
Keep replay as demo default.
Use `npm run test:live-contract` as optional validation.
```

### 4. Recommendations are not real approval queue items yet

The HUD labels recommendations as preview-only. This is intentional.

Mitigation:

```text
Do not claim actions were submitted or executed.
Future PR should bridge recommendations into Jarvis approval/audit path.
```

### 5. AGPL boundary

WorldMonitor should not be copied into Jarvis source.

Mitigation:

```text
Keep WorldMonitor as sidecar/provider.
Use MCP/HTTP boundary.
If copying code becomes necessary, resolve license strategy first.
```

## Execution lanes

### Lane A — HUD polish

Branch:

```text
feature/world-intelligence-hud-polish
```

Scope:

```text
frontend/src/world-intelligence.tsx
frontend/src/api/signalLayer.ts
frontend/src/modes2.tsx
```

Goals:

```text
- Make World Intelligence panel clear and demo-safe.
- Improve loading/error states.
- Avoid touching app shell unless necessary.
- Ensure Vite build updates generated bundle before merge.
```

### Lane B — Demo freeze

Branch/PR:

```text
feature/world-intelligence-demo-freeze / PR #261
```

Goals:

```text
- Keep deterministic Sunday demo script stable.
- Avoid conflicts with code changes.
- Keep claims honest: replay is guaranteed, live is optional.
```

### Lane C — Live contract

Future branch:

```text
feature/world-intelligence-live-contract
```

Goals:

```text
- Run WorldMonitor on :3100.
- Validate MCP tools and resource payloads.
- Harden normalizers.
- Keep live test optional.
```

### Lane D — Argus/Jarvis bridge

Future branch:

```text
feature/world-intelligence-argus-routing
```

Goals:

```text
- Tighten prompt routing to SignalLayerPlugin.
- Add better tests around plugin_gatherer.
- Avoid direct HTTP calls outside plugin.
```

### Lane E — Startup verify

Future branch:

```text
feature/world-intelligence-startup-verify
```

Goals:

```text
- Validate START.bat syntax and messaging.
- Validate start.sh syntax and messaging.
- Ensure no default WorldMonitor :3000 collision.
```

## Sunday demo checklist

### Pre-flight

```bash
cd services/signal-layer
npm test
npm start
```

In another shell:

```bash
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8787/briefs/world
curl "http://127.0.0.1:8787/signals?limit=8&relevantOnly=true"
```

### Demo path

```text
1. Open http://127.0.0.1:8080/
2. Open Observe mode.
3. Show World Intelligence panel.
4. Show brief, signals, evidence/freshness/confidence/relevance.
5. Show recommendations as preview-only.
6. Ask: “What changed overnight that matters to me?”
7. Ask: “What is the current country risk for Romania?”
8. Optionally show WorldView at http://localhost:3000.
```

## What not to claim

Do not say:

```text
WorldMonitor live mode is fully validated.
Jarvis executed an action.
Raw OSINT is confirmed truth.
Recommendations are already in the real approval queue.
```

Say instead:

```text
Replay mode is deterministic and demo-safe.
Live WorldMonitor has an optional contract test path.
Recommendations are preview-only until approved.
Raw OSINT, model inference, forecast, and confirmed facts remain separate.
```

## Next immediate actions

1. Keep #248 as draft until branch/main drift is resolved.
2. Merge child PR #261 into #248 when convenient.
3. Use `feature/world-intelligence-hud-polish` for visible UI refinements.
4. Before final merge, run Vite build and commit generated bundle changes.
5. Resolve main conflicts only after main stabilizes.
