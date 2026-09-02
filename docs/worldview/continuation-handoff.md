# Jarvis World Intelligence — Continuation Handoff

_Last updated: 2026-06-20 — **Signal Layer shipped to `main`** (PR #248 + child lanes). Primary branch is now `main`. Only open item: governance bridge **#280 (draft, awaiting owner review)**._

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

| PR | Purpose | Status |
|---|---|---|
| #248 | Signal Layer integration spine | ✅ **merged to `main`** |
| #261 / #267 / #268 / #269 / #270 | demo-freeze, HUD polish, startup-verify, service hardening, docs | ✅ merged |
| #275 / #277 / #278 / #283 | robustness+tests, live-feed readiness, Argus facade, mock WorldMonitor (CI live-path) | ✅ merged to `main` |
| #287 / #288 | orchestrator wiring (Signal Layer + Argus), richer replay fixtures | ✅ merged / landing |
| **#280** | governance bridge — recs → approval inbox (**default-off, preview-only**) | 🟡 **draft — awaiting owner review** |

Remaining future lanes (not started):

```text
feature/world-intelligence-argus-routing       # = roadmap Phase-4 `agents/argus real implementation` slice, unscheduled (refreshed 2026-09-01; #287 already routes world queries via ArgusInterface)
feature/world-intelligence-governance-enable   # owner decision to enable #280
```

## 5. Current implementation status

| Area | Status | Notes |
|---|---:|---|
| Signal Layer service | Strong v0.1 | Replay provider, routes, evidence, relevance, briefs, assessments |
| Replay/demo path | Strong | Deterministic; 18 signals / 8 countries (#288); no WorldMonitor/API keys |
| Windows / Unix startup | Validated (#268) | `START.bat` / `start.sh` opt-out + port boundaries verified |
| Jarvis-native HUD | Good (#267) | Observe-mode World Intelligence panel + fallback states; bundle current |
| Agent bridge | **Wired (#287)** | `SignalLayerPlugin` registered at startup + `ArgusInterface` facade in the orchestrator; `plugin_gatherer` grounding live |
| Service security | Hardened (#269) | Default bind 127.0.0.1, optional bearer-token gate, scoped CORS |
| Live WorldMonitor | Code-path validated (#283) | Mock-sidecar live path runs in CI; **real `:3100` sidecar still needed** to validate the actual feed |
| Governance bridge | Built, **default-off** (#280 draft) | Preview-only: recs → existing approval inbox, never executes; awaiting owner enable decision |
| Ship status | **Shipped to `main`** | Signal Layer + bridge + HUD + launchers all on `main`; only #280 (governance) remains a draft |

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

`SignalLayerPlugin` is the only agent-facing Signal Layer client, and `ArgusInterface`
(`agents/core/argus.py`, wired as `orch.argus` in #287) is the governed facade over it +
WorldView. Both are registered in the orchestrator at startup.

Do not bypass them with raw HTTP calls in agent code.

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

## 12. Standing CI gate (was: checks before undrafting #248 — now merged)

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

Shipped to `main`: the whole Signal Layer (#248), demo-freeze/HUD/startup/hardening/docs
(#261/#267/#268/#269/#270), robustness+tests (#275), live-feed readiness (#277), Argus
facade (#278), mock-WM CI live-path (#283), orchestrator wiring (#287), richer fixtures (#288).

Remaining (owner / needs a real service):

1. **Review & enable governance #280** (owner) — it's a draft, default-off, preview-only. Flip
   `JARVIS_SIGNAL_GOVERNANCE` to route recs into the approval inbox once happy.
2. **Validate the real WorldMonitor feed** — run `npm run test:live-contract` against a real
   `:3100` sidecar (CI already exercises the code path via the mock: `npm run test:live-contract:mock`).
3. **Deeper Argus agent-dispatch routing** — *refreshed 2026-09-01 (no owner decision taken):*
   #287 already routes world-intelligence queries through `ArgusInterface` via
   `plugin_gatherer._signal_layer_answer` (the facade is wired at startup as `orch.argus`). What
   remains is the `argus` *agent* itself, persona-only today (`agents/argus/SOUL.md`, zero code):
   that is the roadmap's Phase-4 "`agents/vision` + `agents/argus` real implementation" slice
   (`docs/DEVELOPMENT_ROADMAP.md` Phase 4; no dedicated BACKLOG row yet), still unscheduled; it
   changes conversational behavior and needs owner verification at the box before it lands.
