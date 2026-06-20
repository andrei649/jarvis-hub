# Jarvis World Intelligence — Status and Execution Plan

_Last updated: 2026-06-20, HUD polish branch `feature/world-intelligence-hud-polish`._

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

## HUD polish scope

This child branch is intentionally low-conflict and frontend-focused.

Target files:

```text
frontend/src/world-intelligence.tsx
frontend/src/api/signalLayer.ts
frontend/src/modes2.tsx
docs/worldview/hud-polish-*.md
```

Avoid touching conflict-heavy integration files while `main` is moving.

## Current Sunday path

```text
START.bat / start.sh
→ Jarvis Hub (:8080)
→ existing WorldView (:3000/:4000, when installed)
→ Signal Layer replay mode (:8787)
→ HUD Observe mode shows World Intelligence
→ Jarvis/Argus prompts consume Signal Layer data
```

## Current implementation status

| Area | Status | Notes |
|---|---:|---|
| Signal Layer service | Strong v0.1 | Replay provider, routes, brief, signals, assessments |
| Replay/demo path | Strong | Deterministic; no WorldMonitor/API keys required |
| Jarvis-native HUD | Improving | Observe mode has World Intelligence panel and polished fallback states |
| Agent bridge | Medium-good | `SignalLayerPlugin` + `plugin_gatherer` route world prompts |
| Live WorldMonitor | Optional | Contract test exists; not the Sunday guarantee |
| Governance bridge | Preview-only | Recommendations are labelled preview/approval-required |
| Merge readiness | Blocked upstream | Main/integration drift must be resolved after main stabilizes |

## HUD polish acceptance criteria

```text
Open Jarvis HUD → Observe mode → World Intelligence panel is visible.
If :8787 is down, fallback explains how to start/check it.
If :8787 is running, replay brief and signals appear.
Recommendations are labelled preview-only.
No copy claims live WorldMonitor validation or executed actions.
```

## Pre-merge build requirement

```bash
cd frontend
npm test
npm run build
```

If generated `agents/web/v2` files change, commit them before merging this branch into `feature/jarvis-signal-layer`.
