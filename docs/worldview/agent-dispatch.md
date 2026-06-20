# Jarvis World Intelligence — Parallel Agent Dispatch Board

_Last updated: 2026-06-20._

## Objective

Run independent work lanes in parallel while `main` keeps moving. Keep `feature/jarvis-signal-layer` as the integration spine and push isolated work into child branches or issue-scoped PRs.

## Non-negotiable boundaries

```text
WorldView    = Jarvis-owned 4D/geospatial OSINT surface (:3000 UI, :4000 API)
WorldMonitor = optional external public-world intelligence provider (:3100)
Signal Layer = Jarvis-owned fusion brain (:8787)
Argus        = governed agent interface over both
```

Do not copy WorldMonitor implementation code into Jarvis. Keep WorldMonitor behind MCP/HTTP/provider boundary.

## Operating model

```text
1. One lane = one agent = one branch/PR or one issue-scoped patch.
2. Target child work at feature/jarvis-signal-layer, not main.
3. Avoid conflict-heavy files unless the lane explicitly owns them.
4. Replay mode is the Sunday guarantee.
5. Live WorldMonitor is optional until validated by the contract test.
6. Recommendations remain preview-only unless routed through real approval/audit path.
```

## Current lane assignments

| Lane | Issue | Branch / Target | Status | Mission |
|---|---:|---|---|---|
| A — HUD Fusion/Polish | #254 / #265 | `feature/world-intelligence-hud-polish` | Active | Make Observe → World Intelligence clear, demo-safe, and buildable |
| B — Live Contract | #255 | future `feature/world-intelligence-live-contract` | Ready | Validate WorldMonitor MCP payloads and harden normalizers |
| C — Argus Fusion | #256 | future `feature/world-intelligence-argus-routing` | Partially done | Tighten SignalLayerPlugin routing and tests |
| D — Governance | #257 | future `feature/world-intelligence-governance-preview` | Ready | Keep recommendations honest or bridge to approval queue |
| E — Startup/Install | #258 | future `feature/world-intelligence-startup-verify` | Partially done | Validate Windows/Unix launchers and port boundaries |
| F — Demo/Product | #259 / PR #261 | `feature/world-intelligence-demo-freeze` | Active | Freeze deterministic Sunday story and fallback path |

## Dispatch packets

### Agent A — HUD Fusion/Polish

```text
Mission: Make the World Intelligence panel production-demo-safe in the real Vite HUD.
Files: frontend/src/world-intelligence.tsx, frontend/src/api/signalLayer.ts, frontend/src/modes2.tsx.
Avoid: app shell changes unless required.
Acceptance:
- Observe mode shows World Intelligence.
- :8787 down state is helpful.
- Replay state shows brief/signals/freshness/relevance.
- Recommendations are clearly preview-only.
- cd frontend && npm test && npm run build pass.
- Commit generated agents/web/v2 bundle if build changes it.
```

### Agent B — Live Contract

```text
Mission: Validate the live WorldMonitor MCP contract without blocking replay demos.
Files: services/signal-layer/test/live-contract.mjs, src/providers/*, src/normalizers/worldMonitor.mjs, docs/worldview/runbook.md.
Acceptance:
- npm run test:live-contract checks health, tools/list, world brief, conflict, aviation, market, country risk.
- Script exits skipped/0 when sidecar is down.
- Normalizers match real payloads once sidecar is available.
- Replay npm test remains unchanged and passing.
```

### Agent C — Argus Fusion

```text
Mission: Make Jarvis/Argus world questions consume SignalLayerPlugin through existing plugin-data path.
Files: agents/core/plugin_gatherer.py, agents/core/plugins/signal_layer.py, tests/test_signal_layer_gatherer.py.
Acceptance:
- “What changed overnight that matters to me?” triggers Signal Layer.
- “What is the country risk for Romania?” passes country=RO.
- Signal Layer unavailable returns structured unavailable data, not invented intel.
- Tests cover detection, country extraction, and formatted prompt block.
```

### Agent D — Governance

```text
Mission: Keep recommended actions governance-safe.
Files: services/signal-layer/src/core/assessment.mjs, src/agent/worldAnalyst.mjs, frontend/src/world-intelligence.tsx, docs.
Acceptance:
- User-visible copy says preview-only unless real approval queue bridge exists.
- All recommendation objects include/propagate requiresApproval when appropriate.
- No action is executed from raw OSINT.
- If bridge is added, it uses Jarvis approval/audit path only.
```

### Agent E — Startup/Install

```text
Mission: Validate launcher behavior and port boundaries.
Files: START.bat, start.sh, .env.worldview.example, docker-compose.worldview.yml, README.md, docs/worldview/runbook.md.
Acceptance:
- START.bat syntax valid.
- start.sh syntax valid.
- JARVIS_SIGNAL_LAYER=0 opt-out works.
- WorldView stays :3000/:4000.
- Signal Layer stays :8787.
- WorldMonitor docs default to :3100.
```

### Agent F — Demo/Product

```text
Mission: Freeze Sunday demo narrative and fallback path.
Files: docs/worldview/demo-script.md, docs/worldview/status-plan.md, README/PR copy if needed.
Acceptance:
- Five-minute script.
- Replay mode primary.
- Live WorldMonitor optional only.
- Explicit “what not to claim”.
- Direct curl fallback if HUD is unavailable.
```

## Conflict policy

When `main` changes:

```text
1. Do not immediately rebase every child lane.
2. Keep working on non-overlapping docs/frontend/service files.
3. Once main stabilizes, rebase feature/jarvis-signal-layer first.
4. Then merge child branches into the integration spine one at a time.
5. Run tests after each merge.
```

## Required pre-merge checks

```bash
cd services/signal-layer && npm test
cd frontend && npm test && npm run build
python -m pytest tests/test_signal_layer_plugin.py tests/test_signal_layer_gatherer.py tests/test_worldview_plugin.py
```

If `frontend` build changes `agents/web/v2`, commit the generated bundle.

## Sunday freeze rule

After Sunday morning:

```text
No architecture changes.
No live WorldMonitor dependency.
Only blocker fixes.
Use replay mode.
```
