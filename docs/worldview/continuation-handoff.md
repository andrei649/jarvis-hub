# Jarvis World Intelligence — Continuation Handoff

_Last updated: 2026-06-20 (post #261/#267/#268 merge + main-merge + hardening #269). Primary branch: `feature/jarvis-signal-layer`. Primary PR: #248._

This document is the handoff point for Claude, Codex, local agents, or any future contributor continuing the World Intelligence sprint without reading the full chat history.

## 1. Current decision

Do **not** merge WorldMonitor into Jarvis as copied source code.

Build Jarvis World Intelligence as a provider-neutral architecture:

```text
WorldView    = Jarvis-owned 4D/geospatial OSINT surface (:3000 UI, :4000 API)
WorldMonitor = optional external public-world intelligence provider (:3100 by Jarvis convention)
Signal Layer = Jarvis-owned fusion brain (:8787)
Argus        = governed agent interface over WorldView + Signal Layer
```

The durable Jarvis architecture is:

```text
provider data
→ evidence
→ signals
→ relevance
→ assessments
→ brief
→ governed recommendations
```

WorldMonitor can be provider #1, but Jarvis owns the Signal Layer and the user-facing intelligence contract.

## 2. Primary product outcome

By Sunday, the demo should show:

```text
START.bat / start.sh
→ Jarvis Hub (:8080)
→ existing WorldView (:3000/:4000, when installed)
→ Signal Layer replay mode (:8787)
→ HUD Observe mode shows World Intelligence
→ Jarvis/Argus world prompts consume Signal Layer data
```

Replay mode is the guaranteed demo path. Live WorldMonitor is optional until validated.

## 3. Repository map

### Signal Layer service

```text
services/signal-layer/
  package.json
  src/index.mjs
  src/server.mjs
  src/config.mjs
  src/providers/
  src/normalizers/worldMonitor.mjs
  src/core/
  src/agent/worldAnalyst.mjs
  fixtures/worldmonitor/
  test/smoke.mjs
  test/live-contract.mjs
```

### Shared contracts

```text
packages/worldview-core/src/types.ts
packages/worldview-core/src/index.ts
```

### Jarvis agent bridge

```text
agents/core/plugins/signal_layer.py
agents/core/plugins/worldview.py
agents/core/plugin_gatherer.py
agents/core/plugin_gate.py
tests/test_signal_layer_plugin.py
tests/test_signal_layer_gatherer.py
tests/test_worldview_plugin.py
```

### HUD surface

```text
frontend/src/api/signalLayer.ts
frontend/src/world-intelligence.tsx
frontend/src/modes2.tsx
agents/web/v2/          # generated Vite output; update after frontend build if changed
```

### Startup/docs

```text
START.bat
start.sh
.env.worldview.example
docker-compose.worldview.yml
README.md
docs/worldview/status-plan.md
docs/worldview/agent-dispatch.md
docs/worldview/runbook.md
docs/worldview/demo-script.md
docs/worldview/worldview-worldmonitor-fusion.md
```

## 4. Key branches and PRs

| Branch / PR | Purpose | Status |
|---|---|---|
| `feature/jarvis-signal-layer` / PR #248 | Integration spine | **draft** — `main` merged in; awaiting hardening before undraft |
| `feature/world-intelligence-demo-freeze` / PR #261 | Sunday demo script | ✅ merged into spine |
| `feature/world-intelligence-hud-polish` / PR #267 | HUD polish + rebuilt bundle | ✅ merged into spine |
| `feature/world-intelligence-startup-verify` / PR #268 | Launcher + replay validation | ✅ merged into spine |
| `feature/world-intelligence-service-hardening` / PR #269 | Local bind, token gate, scoped CORS | in review → spine |

Recommended future child branches:

```text
feature/world-intelligence-live-contract
feature/world-intelligence-argus-routing
feature/world-intelligence-governance-preview
```

## 5. Current implementation status

| Area | Status | Notes |
|---|---:|---|
| Signal Layer service | Strong v0.1 | Replay provider, routes, evidence, relevance, briefs, assessments |
| Replay/demo path | Strong | Deterministic; no WorldMonitor/API keys required |
| Windows startup | Validated (#268) | `START.bat` starts Signal Layer unless `JARVIS_SIGNAL_LAYER=0`; syntax + ports verified |
| Unix startup | Validated (#268) | `start.sh` passes `bash -n`; opt-out + port boundaries verified |
| Jarvis-native HUD | Good (#267) | Observe mode World Intelligence panel + fallback states; bundle current |
| Agent bridge | Medium-good | `SignalLayerPlugin` and `plugin_gatherer` integration exist |
| Service security | Hardened (#269, in review) | Default bind 127.0.0.1, optional bearer-token gate, scoped CORS |
| Live WorldMonitor | Medium-low | Optional contract test exists; real sidecar payloads still need validation |
| Governance bridge | Medium-low | Recommendations are preview-only, not real approval queue items yet |
| Merge readiness | Unblocking | `main` merged into spine (0 behind, CI green); SEC-5b de-duplicated; remaining gate: land hardening (#269), then undraft #248 |

## 6. Signal Layer API contract

Replay mode must work without external dependencies.

Routes:

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

Core env:

```text
JARVIS_SIGNAL_LAYER_MODE=replay|live
SIGNAL_LAYER_HOST=127.0.0.1          # local-only default; set 0.0.0.0 for LAN (use a token!)
SIGNAL_LAYER_PORT=8787
SIGNAL_LAYER_API_TOKEN=              # optional bearer token; when set, required on all routes except GET /healthz
SIGNAL_LAYER_ALLOWED_ORIGINS=       # extra CORS origins beyond localhost/127.0.0.1/::1 (comma-separated)
WORLDMONITOR_BASE_URL=http://localhost:3100
WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp
VITE_SIGNAL_LAYER_URL=http://localhost:8787
```

Security posture (#269): the service binds local-only by default, scopes CORS to local
origins, and enforces the bearer token when one is set. The browser HUD runs tokenless and
relies on the local bind; token mode is for hardened/headless use.

Deprecated fallback:

```text
JARVIS_WORLDVIEW_MODE
```

Only keep it as a sprint fallback; prefer `JARVIS_SIGNAL_LAYER_MODE`.

## 7. Live WorldMonitor contract

Live mode is optional. Run only when WorldMonitor is already running on host port `:3100`:

```bash
cd services/signal-layer
JARVIS_SIGNAL_LAYER_MODE=live \
WORLDMONITOR_BASE_URL=http://localhost:3100 \
WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp \
npm run test:live-contract
```

Expected behavior:

```text
- Checks /api/health.
- Checks MCP tools/list.
- Calls representative tools: world brief, conflict, aviation, market.
- Reads country risk resource for RO.
- Validates normalizer output.
- Exits skipped/0 if sidecar is unavailable.
```

Do not make this normal CI until the live sidecar contract is stable.

## 8. HUD continuation guidance

Current active HUD path:

```text
frontend/src/main.tsx → frontend/src/app.tsx → modeComponent(...) → ObserveMode → WorldIntelligencePanel
```

Current panel file:

```text
frontend/src/world-intelligence.tsx
```

Current client file:

```text
frontend/src/api/signalLayer.ts
```

Before merging HUD work:

```bash
cd frontend
npm test
npm run build
```

If build changes `agents/web/v2`, commit the generated output.

The HUD must not claim:

```text
- WorldMonitor live mode is validated.
- Recommendations are real approval queue items.
- Jarvis executed an action.
- Raw OSINT is confirmed truth.
```

The HUD may claim:

```text
- Replay mode is deterministic and demo-safe.
- Signal Layer returned evidence-backed signals/briefs.
- Recommendations are preview-only until approved.
- Live WorldMonitor can be validated by optional contract test.
```

## 9. Agent bridge continuation guidance

`SignalLayerPlugin` is the only agent-facing Signal Layer client.

Do not bypass it with raw HTTP calls in agent code.

Current prompt grounding path:

```text
Orchestrator.handle_input(...)
→ plugin_gatherer.gather_plugin_data(...)
→ wants_signal_layer(...)
→ SignalLayerPlugin.ask_world(...)
→ prompt block: REAL-TIME DATA — SIGNAL-LAYER
```

Current triggers include:

```text
what changed overnight
world brief
global brief
world intelligence
country risk
Romania risk
UAE risk
Suez
chokepoint
OSINT
global status
```

Existing tests:

```bash
python -m pytest tests/test_signal_layer_plugin.py tests/test_signal_layer_gatherer.py tests/test_worldview_plugin.py
```

## 10. Governance continuation guidance

Current recommendation state is preview-only.

If adding real approval queue integration:

```text
- Submit recommendations into existing Jarvis approval queue only.
- Add audit log record.
- Preserve reversible/irreversible action policy.
- Do not execute external/high-impact actions from raw OSINT.
- Keep facts, raw leads, model inference, forecast, and recommendation separate.
```

Safe current copy:

```text
Preview only. Route through Jarvis approval before action.
```

## 11. Startup continuation guidance

Ports must remain:

```text
Jarvis Hub:    :8080
WorldView UI:  :3000
WorldView API: :4000
Signal Layer:  :8787
WorldMonitor:  :3100 host convention, optional/live only
```

Do not claim WorldMonitor is started automatically by default.

WorldMonitor is a sidecar that must be started separately for live mode.

## 12. Required checks before undrafting PR #248

Minimum:

```bash
cd services/signal-layer && npm test
python -m pytest tests/test_signal_layer_plugin.py tests/test_signal_layer_gatherer.py tests/test_worldview_plugin.py
```

HUD merge readiness:

```bash
cd frontend
npm test
npm run build
```

Optional live validation:

```bash
cd services/signal-layer
npm run test:live-contract
```

Only run the live contract check when WorldMonitor is actually running on `:3100`.

## 13. Conflict strategy

`main` is moving. Do not chase it with every child branch.

Recommended order:

```text
1. Keep PR #248 as draft integration spine.
2. Continue isolated child PRs against feature/jarvis-signal-layer.
3. When main stabilizes, rebase/merge main into feature/jarvis-signal-layer.
4. Resolve conflicts once.
5. Merge child PRs into feature/jarvis-signal-layer one at a time.
6. Run checks after each merge.
7. Commit Vite generated bundle if changed.
8. Undraft PR #248 only after CI/build/mergeability is clean.
```

## 14. Sunday demo script summary

Primary demo:

```text
1. START.bat or ./start.sh.
2. Open http://127.0.0.1:8080/.
3. Open Observe mode.
4. Show World Intelligence panel.
5. Show brief, top signals, freshness, source, confidence, relevance.
6. Show recommendations as preview-only.
7. Ask: “What changed overnight that matters to me?”
8. Ask: “What is the current country risk for Romania?”
9. Optionally open WorldView at http://localhost:3000.
```

Fallback if HUD fails:

```bash
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8787/briefs/world
curl "http://127.0.0.1:8787/signals?limit=8&relevantOnly=true"
```

Closing line:

```text
Jarvis can now observe external reality, convert it into evidence-backed signals, decide what matters, explain why, and recommend safe next actions without confusing raw OSINT for truth.
```

## 15. Next best actions

Done since the first handoff: HUD polish + bundle (#267), demo-script freeze (#261),
startup-verify (#268) — all merged into the spine; `main` merged into the spine and the
SEC-5b `plugin_gate.py` duplication de-duplicated; service hardening (#269) in review.

Remaining:

1. Land service hardening (#269) into `feature/jarvis-signal-layer`.
2. Undraft PR #248 into `main` once CI/build/mergeability are confirmed clean (owner decision).
3. Start `feature/world-intelligence-live-contract` only when WorldMonitor can run locally on `:3100`.
4. Re-merge `main` into the spine if `main` advances again before #248 lands.
5. Later lanes: `argus-routing`, `governance-preview` (real approval-queue integration).
