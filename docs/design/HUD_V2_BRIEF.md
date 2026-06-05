# Jarvis Hub — HUD v2 Design Brief (for Claude · Design)

> **Audience:** a future *Claude design session* tasked with conceiving and then implementing
> the **next-generation HUD** for Jarvis Hub. This is the single, self-contained handoff: it
> carries the mission, the *complete* capability surface (every feature, every sub-product,
> every endpoint + the code it lives in), the design system, the hard constraints, and a
> ready-to-run "different port" test setup. **Read this top-to-bottom before designing.**
>
> **Status:** brief only — no v2 code exists yet. Owner: Andrei. Generated 2026-06-05.
> Prior art: the v0.3 prototype in [`design_handoff_jarvis_hub/`](../../design_handoff_jarvis_hub/)
> (open `design/index.html` in a browser to feel the current aesthetic). The *current shipping*
> HUD lives in `agents/web/` and already implements that v0.3 handoff — **v2 supersedes it.**

---

## 0 · TL;DR — what you're being asked to do

1. Design an **awesome new version of the Jarvis Hub HUD** — a redesign, not a reskin. The bar is
   *"a Bloomberg Terminal as Apple would have designed it in 2035, for one person who owns the
   whole machine."* Dark, geometric, calm, information-dense but never noisy.
2. It must **surface the entire product** — Jarvis is no longer "a chat box with a network graph."
   It is now **~30 capability areas / 228 HTTP endpoints / 16 live agents** (§4, §5). Your central
   design problem is **information architecture**: making that surface *legible and calm*, not a
   wall of panels. The current HUD has grown to ~80 components across 13 files and is starting to
   sprawl — fixing that coherence is the point of v2.
3. It must stay true to the **non-negotiables** (§8): local-first, private, inspectable,
   proactive-not-noisy, production-grade, bilingual RO/EN.
4. It must be **runnable on a separate port** alongside the current HUD so the two can be compared
   live during the build (§12).
5. Deliver: a working prototype (the design *is* the spec), then a production port into the repo's
   serving model (§11), with tests (§13).

If you only remember one sentence: **make the most capable local AI on earth feel like one calm,
trustworthy instrument — not a dashboard graveyard.**

---

## 1 · Mission & aesthetic north star

Jarvis Hub is a **personal AI operating system**: a persistent, proactive, *private* multi-agent
cortex that runs on the owner's own hardware, builds a growing model of their life, finds its own
work, and asks for a decision only when it truly needs one. (Full vision: [`MOONSHOT.md`](../../MOONSHOT.md).)

The HUD is the **face of that OS**. It is not a website; it is the cockpit of a living system the
user *owns*. Design implications:

- **Calm authority.** It runs 24/7 on a wall display / second monitor. It must be beautiful at a
  glance and at arm's length, and it must not flicker, nag, or churn. Motion is restrained and
  *meaningful* (a packet travels an edge because work is actually flowing).
- **Inspectability is the brand.** Every fact editable, every action audited, every cloud hop
  opt-in and visible. Trust is earned by *showing the work*: routing decisions, provenance of
  memories, the audit chain, the kill-switch. The UI should make "I can see exactly what it did
  and why" a first-class, delightful experience — this is the moat, not a settings page.
- **Proactive, not noisy.** Interrupts are budgeted (≤4 urgent/day). The HUD's notification surface
  must reflect that discipline: a few high-signal decision cards, not a feed.
- **One owner.** This is single-user, power-user software. Density is a feature. No onboarding
  wizards, no empty-state hand-holding for a mass market. Keyboard-first (command palette, hotkeys).

**Aesthetic tokens that define "the feel"** (current, to *evolve* not discard — §7): near-black
void background `#030810`, hairline cyan accent `#00AEEF`, translucent glass panels with corner
brackets, `Share Tech Mono` tabular numerals glowing softly, `Exo 2` for UI, scanline + dot-grid
ambient texture, status colors green/amber/red. The arc-reactor logo, the neural-network brain,
and the situation ticker are signature elements — treat them as brand equity to *reinterpret*.

---

## 2 · Who uses it, where, how

- **User:** Andrei (and, post-1.0, other privacy-first power users). Technical, fast, wants depth on
  demand and silence otherwise. Bilingual; UI ships **RO + EN** (`agents/web/static/i18n.js`,
  `window.setLocale('ro'|'en')`, persisted in `localStorage['hud.lang']`, auto-detected from
  browser). **Romanian copy is real product copy — never machine-translate it; keep RO strings
  intact.**
- **Surfaces:** primary is a desktop/large screen (3-column today). Also installed as a **PWA**
  (`manifest.json` + `sw.js` service worker) and used on mobile (`apple-mobile-web-app-capable`,
  `viewport-fit=cover`). v2 must have a *real* responsive story, not just two breakpoints.
- **Always-on ambient mode** is a legitimate use (glanceable clock, agent heartbeat, weather,
  pending decisions) — consider a dedicated low-motion "ambient/standby" view.
- **Latency context:** the LLM is local (LM Studio :1234), fast slot ~4–5s. Chat streams via SSE.
  The UI must feel instant for everything that isn't an LLM call, and make LLM waits legible
  (the orchestration "thinking trace").

---

## 3 · The baseline — what exists TODAY (so v2 misses nothing)

The current HUD is the thing you're replacing. Inventory it so no capability is dropped.

### 3.1 Serving model & files
- Entry: `serve.py` → `uvicorn.run(app, host=127.0.0.1, port=8080)` where `app` = `agents/web.py`
  FastAPI app. **Port 8080 is currently hardcoded** (see §12 to change it).
- `GET /` → `agents/web/templates/index.html` (the shell). `GET /admin` → a *separate* admin SPA
  rendered inline from `web.py` (`admin.js` / `admin.css`).
- Static mounted at `/static` → `agents/web/static/`.
- The page is **React 18 via local UMD bundles** (`static/react.production.min.js`,
  `react-dom.production.min.js`) + **plain `.js` files using `React.createElement`** (no JSX at
  runtime, **no bundler, no npm build step**). Scripts are loaded in order in `index.html`.
- PWA: `static/manifest.json`, `static/sw.js`, `favicon.svg`, custom fonts in `static/fonts/`
  (`fonts.css`).
- Pre-paint script in `index.html` applies persisted UI prefs (`data-density`, `data-scanline`,
  `data-dotgrid`, `data-theme`) before first paint to avoid flash.

### 3.2 Current component / panel inventory (the surface to re-home)
Grouped by file in `agents/web/static/`:

| File | Components / panels |
|------|---------------------|
| `app.js` | `App` (root: all state, hotkeys, submit/SSE flow, polling) |
| `components.js` | `TopBar`, `Clock`, `Badge`, `StatusDot`, `TrustIndicator`, `Bracket` (panel frame), `AgentList`, `AgentsGrid`, `SysRow`, `SysMeter`, `ConversationView`, `Message`, `ThinkingBubble`, `InputBar`, `WeatherCard`, `CalendarCard`, `HeartbeatFeed` |
| `network.js` | `NetworkBrain` (neural-net visualizer), `Hex`, `Packet` |
| `enhancements.js` | `SituationTicker`, `CommandPalette` (⌘K / Ctrl-K) |
| `cognition.js` | `CognitionPanel`, `IntentClassification`, `RoutingDecision`, `OrchestrationTrace` |
| `systems.js` | `SystemsPanel` + tabs: `MemoryTab`, `PluginsTab`, `LearningTab`, `SecurityBenchTab`, `OAuthTab`, `OracleTab`, `ResilienceTab`, `HeartbeatsTab`, `FusedRecallBox`, `SystemsTabBar` |
| `workflows.js` | `WorkflowsPanel`, `WorkflowCanvas`, `StepForm`, `ResultPanel` |
| `observability.js` | `ObservabilityPanel`, `TraceRow`, `TraceDetail`, `TimingBar` |
| `dossier-modal.js` | `DossierModal`, `DossierGlyph`, `DossierIdentity`, `DossierMemory`, `TierBadge`, `StatusIndicator` |
| `console.js` | `SettingsMenu`, `Toggle`, `Select`, `Row` (HUD settings overlay) |
| `tools.js` | **a "tools console" of ~30 panels** → `ActionsPanel`, `ArenaPanel`, `AuditPanel`, `CapabilitiesPanel`, `CostPanel`, `DecayPanel`, `DryRunPanel`, `EntitiesPanel`, `EscalationPanel`, `EvalPanel`, `GrammarPanel`, `HealthPanel`, `KGPanel`, `KillSwitchPanel`, `LearningPanel`, `LocalDocsPanel`, `MCPPanel`, `MemorySearchPanel`, `ModelsPanel`, `NotesPanel`, `QualityPanel`, `ReflectionPanel`, `ReviewPanel`, `RoomsPanel`, `SchedulePanel`, `SecretsPanel`, `TemplatesPanel`, `TrustScorecardPanel`, `WebhooksPanel`, `WidgetsPanel` (+ `ConsoleOverlay`) |
| `admin.js` (separate `/admin` SPA) | `AdminApp`, `AgentsPage`, `ChartsPage`, `CostPage`, `GlobalConfigPage`, `LocalModelsPage`, `MCPPage`, `OraclePage`, `RecallPage`, `SystemPage`, `AuditLog`, `LLMTest`, `Sparkline`, `BarChart`, … |
| `data.js` | live-data adapter + static lookups (`GLYPHS`, `COLLAB`, `TIERS`, ticker defaults) |
| `i18n.js` | RO/EN dictionary + `setLocale` |
| `auth.js` | token handling for guarded endpoints (see §8 auth) |

> **Read these files** — they are the *de facto* spec of "everything the product can do today."
> The current 3-column layout: TopBar → SituationTicker → grid [AgentList+SysStats | Network+Conversation+Input | Weather+Calendar+AgentsGrid+Heartbeat], with Cognition/Systems/Workflows/Observability/Tools/Dossier as overlays/expansions and ⌘K palette over everything. Full layout/spec of the *current* design: [`design_handoff_jarvis_hub/README.md`](../../design_handoff_jarvis_hub/README.md).

### 3.3 Honest critique of the baseline (your brief is to fix these)
- **Panel sprawl.** `tools.js` alone is 30+ panels bolted on as the backend grew. There's no
  coherent IA — capabilities accrete as overlays. v2's core job is to give all of §4 a *home* that
  scales.
- **Two disconnected apps.** The HUD (`/`) and Admin (`/admin`) are separate React apps with
  different visual languages. Decide: unify, or make the seam intentional.
- **Density controls are crude** (`data-density` compact/normal/comfy). v2 should treat density,
  motion, and "depth on demand" as a designed system.
- **Mobile/responsive is an afterthought** (two breakpoints). 
- **Trust/governance is buried** in tool panels though it's the *brand*. Promote it.

---

## 4 · The COMPLETE capability surface (every feature & sub-product)

This is the "won't miss anything" section. Every area below is real, shipped, and backed by
endpoints (§5) and code. v2 must give each a deliberate place (surface it, nest it, or consciously
hide it behind the palette — but *decide*).

### 4.1 Core conversation & orchestration
- **Chat** (`POST /chat`) + **streaming chat** (`POST /chat/stream`, SSE token stream). The heart.
- **Orchestration trace** — how a message is classified → routed → (multi-agent) synthesized.
  Backed by `Orchestrator.handle_input(_stream)` (`agents/core/orchestrator.py`). The "thinking
  trace" (classify → route pills → synthesize) is a signature UI moment.
- **Cognition** (`GET /api/cognition`) — intent classification weights, routing decision +
  alternatives, orchestration timeline. The "show me the brain" view.
- **Situation ticker / live activity** (`GET /ticker`) — marquee of agent activity.
- **Tasks fan** (`GET /tasks`) — per-agent task dots in the network.

### 4.2 Agents (16 active + 17 bench, 4 tiers)
- **Roster** (`GET /agents`, `GET /api/agents`, `GET /status`) grouped by tier CNS/BIZ/SEC/FND (§6).
- **Agent dossier** — SOUL.md identity, model, plugins, skills, per-agent memory
  (`GET /api/agents/{id}/soul`, `GET /memory/{agent_id}`, `GET /api/agents/{id}/history`).
- **Per-agent glyphs** (geometric SVG marks, `data.js GLYPHS`) — brand element, reuse/redraw.
- **Collaboration edges** between agents (`data.js COLLAB`) shown in the network brain.
- **Bench agents & promotion** — dormant agents promotable at runtime (`POST /learning/promote`,
  `GET /learning`, suggestions). Learning loop reranks/(de)promotes by health.
- **Agent templates** (`GET /api/agent-templates`, `POST /api/agent-templates/instantiate`).
- **Heartbeats** — scheduled agent runs (`GET /heartbeat/status`, start/stop/run per agent).

### 4.3 Memory & knowledge (the "living memory")
- **Conversation + vector + graph memory** with **RRF fused recall** (`GET /api/memory/search`,
  `GET /api/memory/recall`, `POST /api/memory/remember`).
- **Memory profile** (`GET /api/memory/profile`) and **entities** (`GET /api/memory/entities`).
- **Memory spaces** — per-agent data scoping (`GET/POST /api/memory/spaces`, assign/unassign,
  delete). *Local-first data governance, surface it well.*
- **Memory decay / forgetting** — inspectable, editable, *forgettable* (`GET /api/memory/decay/
  candidates|ranking`, `POST /api/memory/decay/forget`). The "inspectable & forgettable" principle.
- **Consolidation** (`POST /api/memory/consolidate`) — nightly memory consolidation.
- **Memory-as-tool spec** + search-tool (`GET /api/memory/tool-spec`, `POST /api/memory/search-tool`).
- **Memory eval corpus / run** (`GET /api/memory/eval/corpus`, `POST /api/memory/eval/run`).
- **Knowledge graph (bitemporal!)** — entities/relations CRUD, fact ingest, and **as-of / history
  time-travel** (`GET/POST/DELETE /api/kg/entities|relations`, `POST /api/kg/facts|ingest`,
  `GET /api/kg/facts/as-of`, `GET /api/kg/facts/history`). A graph browser with a time slider is a
  killer v2 surface.
- **Local docs RAG** (`GET /api/local-docs`, `POST /api/local-docs/index`).

### 4.4 Autonomy / proactive cortex
- **Task queue & approvals** (`GET /autonomy/tasks`, `POST /autonomy/tasks`,
  `GET /autonomy/approvals`, `POST /autonomy/tasks/{id}/decision`). Risk-gated ACT/NOTIFY/ASK.
- **Decision cards** (`GET /api/actions/pending`, `POST /api/actions/request`,
  `POST /api/actions/{id}/decide`) — the budgeted, high-signal interrupt surface.
- **Morning brief / evening retro** (`GET /autonomy/brief`).
- **Observer** (host probes) + **watchers** (email/calendar/finance/health) — `GET /autonomy/observer`,
  `POST /autonomy/observer/run`.
- **Preference learning** (`GET /autonomy/preferences/suggestions`) — "learn to stop asking."
- **Escalation** (`GET /api/autonomy/escalation/targets`, `POST /api/autonomy/escalate`).
- **Dry-run / preview** of autonomous actions (`POST /api/autonomy/preview`,
  `GET /api/autonomy/tasks/{id}/preview`).
- **Nightly reflection** (`GET /api/reflection/status`, `POST /api/reflection/run`).

### 4.5 Security, trust & governance (THE BRAND — promote it)
- **Trust scorecard / status** (`GET /api/trust/status`) + `TrustIndicator` in the top bar.
- **Security posture & governance** (`GET /api/security/posture`, `/api/security/governance`).
- **Kill-switch** (`GET/POST /api/security/kill-switch`) — instant "stop everything." Make it a
  visible, reassuring, physical-feeling control.
- **Capabilities / object-capability tokens** (`GET /api/security/capabilities/check`,
  `POST /api/security/capabilities/issue`).
- **Audit chain (Merkle-anchored, non-repudiable)** — `GET /api/admin/audit`,
  `GET /api/security/audit/intent|anchors`, `POST /api/security/audit/action|anchor`. A beautiful,
  verifiable audit log is core to the trust story.
- **Prompt-injection scanning & spotlighting** (`POST /api/security/scan-injection`,
  `POST /api/security/spotlight`).
- **Secrets broker** (`GET/POST/DELETE /api/secrets/broker`, `POST /api/secrets/broker/redact`).
- **Guardrails** (WARN/REDACT/BLOCK) — PII/secret/injection (status via security surfaces).

### 4.6 Interop & "agentic web" (sub-products in their own right)
- **A2A (agent-to-agent)** — signed **Agent Card** (`GET /.well-known/agent-card`),
  peers (`GET/POST/DELETE /api/a2a/peers`), inbound task inbox + decide
  (`GET /api/a2a/inbox`, `POST /api/a2a/task`, `POST /api/a2a/inbox/{id}/decide`, `POST /api/a2a/card`).
- **MCP** — Jarvis as **MCP server** (`GET /api/mcp/server`, `POST /api/mcp/server/rpc`,
  `POST /api/mcp/token`) *and* MCP client manager (`GET /api/admin/mcp`, add/connect/disconnect).
- **Embeddable widget** — third-party embed (`GET /api/widget/{token}`, `/config`,
  `POST /api/widget/{token}/message`; manage via `/api/admin/widgets`). A *separate, themeable
  surface* — design it as a product, not an afterthought.
- **Webhooks** (`GET/POST/DELETE /api/webhooks`, `POST /api/webhooks/{id}`).
- **OAuth-protected resource metadata** (`GET /.well-known/oauth-protected-resource`).

### 4.7 Governed payments (H16.3 — just shipped)
- **Mandate/cap/approval/audit** governance for agent-initiated spending (it does **not** move
  money — it's the safety layer). `GET/POST /api/payments/mandates`, `POST /api/payments/request`,
  approve/reject/settle. Surface: mandates with hard caps, a pending-approval queue, an audit of
  every decision. (Admin-guarded.)

### 4.8 Workflows (visual multi-agent pipelines)
- **Pipelines** CRUD + run (`GET/POST/PUT/DELETE /api/workflows`, `POST /api/workflows/run`,
  `POST /api/workflows/hierarchical`), **AI-assisted step builder**
  (`POST /api/workflows/step/generate`), and **workflow traces** (`GET /api/workflows/traces`).
  The `WorkflowCanvas` is a real node-graph editor — a flagship interactive surface for v2.

### 4.9 Observability, eval, quality, review, arena (the "trust the quality" cluster)
- **Request traces** (`GET /api/traces`, `/api/traces/{id}`, clear) — timeline/timing bars.
- **APM / health** (`GET /api/admin/apm`, `GET /api/health/components`, `GET /api/resilience` —
  circuit breakers, retries).
- **Eval datasets & regression runs** (`GET /api/eval/datasets`, runs, compare, `POST .../run`).
- **Live quality monitor** (`GET /api/quality`, `/api/quality/scores`, `POST /api/quality/threshold`).
- **Human review queue** (`GET /api/review/queue|stats`, flag/vote/→dataset).
- **Arena** — model/agent A/B with leaderboard + voting (`GET /api/arena/leaderboard`,
  `match/{id}`, `POST /api/arena/run|vote`).

### 4.10 Models & LLM control
- **Local models** (`GET /api/models/local`, `POST /api/models/local/switch`).
- **LM Studio lifecycle control** (kill-switch-gated): `POST /api/llm/server/start|load|unload`.
  Also controllable from chat ("load gemma", "what model?"). Surface current model + a safe control.
- **Constrained decoding / grammar** (`POST /api/llm/grammar`).
- **Cost & model tiering analytics** (`GET /api/cost`, `/api/analytics/cost`,
  `/api/analytics/model-tiers`, `GET /api/admin/stats`) — local vs cloud %, monthly cost estimate.
  (Counter-metric: % served locally — a first-class number in the moonshot.)

### 4.11 Skills & marketplace
- **Loaded/imported skills** (`GET /skills`, `/skills/imported`, `POST /skills/import`).
- **Signed + moderated marketplace** (anti-"ClawHub"): `GET /api/skills/marketplace`,
  install / install-zip / publish / review. Trust/signing is the differentiator — show it.

### 4.12 Plugins & integrations (per-agent, permissioned)
- **Plugin registry + toggles** (`GET /plugins`, `PUT /plugins/{id}/toggle`) — each plugin has
  network scope (NONE/LAN/RESTRICTED/FULL), data scope, and an `agents_served` list (the
  `PermissionGate`). ~17 plugins: weather, news, cloud-llm, telegram, gmail, google-calendar,
  whatsapp-bridge (Frigga, LAN-only), spotify, apple-health, homebridge, oracle-bridge (GitHub),
  analytics (GA4), balance (bank), n8n, iot (Tuya), sms (Twilio), crm (Notion).
- **OAuth** (`GET /api/oauth/auth-url|status`, callback, refresh) for Google/Spotify/etc.
- **Oracle / GitHub** watcher (`GET /api/oracle/status|conflicts`, sync, resolve).

### 4.13 Ambient / personal widgets
- **Weather, calendar, heartbeat feed, agents grid** (`GET /dashboard`), **notes**
  (`GET/PUT/DELETE /api/notes`, `POST /api/notes/rewrite`), **rooms** (multi-agent chat rooms:
  `GET/POST/DELETE /api/rooms`, history, message), **schedule NL parsing** (`POST /api/schedule/parse`),
  **voice** (`GET /api/voice/wyoming`, `POST /tts`).

### 4.14 Admin (a full sub-product at `/admin`)
- **Runtime settings DB** (`GET/PUT /api/admin/settings[/{category}]`, reseed) — toggles, numbers,
  selects, text; loaded every 30s. Categories incl. general, llm, memory, security, system,
  autonomy, learning, plugins.
- **Env vars (masked)** (`GET /api/admin/env`), **LLM test** (`POST /api/admin/llm/test`),
  **agent config** (`GET /api/admin/agents/stats`, `PUT /api/admin/agents/{id}`),
  **prompt versioning / A-B / diff / rollback / commit** (`/api/admin/prompts/{id}/...`),
  **charts & stats** (`GET /api/admin/stats`, `/api/admin/apm`), **memory clear**,
  **dashboard widgets** (`/api/admin/widgets`).
- Current admin tabs (RO): *Statistici & Analize · Cost & Modele · Modele Locale · Integrare Claude ·
  Servere MCP · Memorie Utilizator · Sistem & Depanare · Resilience Metrics · Circuit Breakers.*

> **Sub-products to treat as first-class** (each could be its own screen/mode): ① the Conversation
> cockpit, ② the Agent network + dossiers, ③ Memory & Knowledge-graph browser, ④ Autonomy /
> decision inbox, ⑤ Trust & Security center (audit, kill-switch, capabilities, payments), ⑥
> Workflows builder, ⑦ Observability/Eval/Quality/Arena, ⑧ Interop (A2A/MCP/Widget/Webhooks), ⑨
> Skills marketplace, ⑩ Admin/Settings, ⑪ the embeddable Widget, ⑫ Command palette as the
> connective tissue.

---

## 5 · Full backend API contract (don't change shapes without reason)

**228 routes** in `agents/web.py`. The frontend is a *client of this API* — v2 reuses it. Treat
existing response shapes as fixed; if v2 needs new shapes, add endpoints (recipe in
[`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) §8) rather than breaking old ones. Path-prefix map of
the surface:

```
/                       HUD shell (HTML)            /admin                   Admin SPA (HTML)
/chat , /chat/stream    chat (JSON / SSE)           /status , /api/status    system + agents
/agents , /api/agents   agent roster               /api/agents/{id}/soul    SOUL.md
/dashboard              weather/news/sys/convo      /ticker , /tasks         live activity / task fan
/api/cognition          intent/routing/trace        /memory/{agent_id}       per-agent memory
/api/memory/*           search,recall,remember,profile,entities,spaces,decay,consolidate,tool-spec,eval
/api/kg/*               entities,relations,facts,ingest,facts/as-of,facts/history   (bitemporal KG)
/api/local-docs[/index] local RAG
/autonomy/*             tasks,approvals,brief,observer,preferences/suggestions,status
/api/autonomy/*         escalate,preview,escalation/targets,tasks/{id}/preview
/api/actions[/pending|/request|/{id}/decide]        decision cards
/api/reflection/*       status,run
/api/trust/status       /api/security/*  posture,governance,kill-switch,capabilities/{check,issue},
                                          audit/{intent,anchors,action,anchor},scan-injection,spotlight
/api/secrets/broker*    secrets broker (+ redact)
/api/payments/*         mandates,request,{id}/approve|reject|settle      (governed payments)
/api/a2a/*              peers,inbox,task,card,inbox/{id}/decide          /.well-known/agent-card
/api/mcp/*              server,server/rpc,token          /api/admin/mcp* client manager
/api/widget/{token}*    embeddable widget (+config,+message)            /api/admin/widgets*
/api/webhooks*          webhooks
/api/workflows*         CRUD,run,hierarchical,step/generate,traces       (visual pipelines)
/api/traces*            request traces (+clear)         /api/health/components , /api/resilience
/api/eval/datasets*     datasets,runs,compare,run        /api/quality* scores,threshold
/api/review/*           queue,stats,flag,{id}/vote,{id}/dataset          /api/arena/* leaderboard,run,vote
/api/models/local*      list,switch          /api/llm/* server/start,load,unload,grammar
/api/cost , /api/analytics/{cost,model-tiers}           /api/admin/stats , /api/admin/apm
/skills* , /api/skills/marketplace*          /plugins , /plugins/{id}/toggle
/api/oauth/*            auth-url,status,callback,refresh /api/oracle/* status,conflicts,sync,resolve
/api/notes*             notes (+rewrite)     /api/rooms*  multi-agent rooms (+history,+message)
/api/schedule/parse     NL → schedule        /api/voice/wyoming , /tts
/heartbeat/*            status,{id}/run|start|stop       /learning* , /api/learning/propose
/bench* , /sandbox/*    benchmarks / code sandbox        /sessions[/resume] , /memory[/clear]
/api/admin/*            settings[/{cat}],env,audit,llm/test,agents[/{id}],prompts/{id}/*,widgets,stats,apm
/.well-known/oauth-protected-resource        /favicon.ico , /sw.js , /static/*
```
> Full list with methods + line numbers: `grep -nE '^@app\.(get|post|put|delete|patch)' agents/web.py`.

---

## 6 · Agent roster (tiers, glyphs, plugins)

**Tier codes (UI ↔ backend):** CNS=command, BIZ=business, SEC=tech, FND=foundation. Source of
truth: `agents/_system/agents.yaml`; identities in `agents/<id>/SOUL.md`.

| Tier | Agents (id · archetype · channel · key plugins / policy) |
|------|---------|
| **CNS** Command | jarvis (Prime Orchestrator · voice · cloud-llm,telegram) · friday (Daily Intel · voice) · pepper (Chief of Staff · voice · google-calendar,gmail,telegram) · jerome (Leisure/DJ · voice · spotify) |
| **BIZ** Business | athena (External Strategist · web · **cloud**) · stark (Biz Intel · telegram · gmail,analytics) · veronica (Content/Comms · telegram · cloud-llm) · vision (Deep Research/OSINT · web · **claude** · websearch) |
| **SEC** Tech | steve (CTO/Builds · telegram · **claude**) · oracle (n8n Workflows · web · oracle-bridge) · ultron (Security/Automation · log-only · **local**) |
| **FND** Foundation | gecko (Markets/Capital · telegram · balance) · hercules (Fitness · telegram · apple-health) · hephaestus (Builder · telegram) · frigga (Family Matriarch · **local-only, LAN, cloud_fallback:false** · whatsapp-bridge) · howard (Digital Twin · telegram · **local**) |

**Bench (17, dormant, promotable):** bruce, wanda, shuri, natasha, thor, loki, heimdall, happy,
bucky, apollo, hermes, atlas, prometheus, artemis, demeter, aria, hera (Marvel/myth universe;
each with a promotion trigger). Cardinality cap 18.

> Each agent has a 14×14 geometric **glyph** (`data.js GLYPHS`) used in the list, network nodes,
> ticker, palette, dossier. Glyphs are brand equity — redraw as a coherent set for v2.

---

## 7 · Design system (current → evolve)

Tokens (from the current build; keep the *language*, push the craft):

```css
--bg-void:#030810; --bg-surface:#07111f; --bg-glass:rgba(0,174,239,.04);
--border-glass:rgba(0,174,239,.12); --border-active:rgba(0,174,239,.35);
--accent:#00AEEF; --accent-light:#7FDBFF; --accent-glow:rgba(0,174,239,.35);
--green-active:#39FF8B; --amber-warn:#FFB23F; --red-alert:#FF453A;
--text-primary:#E8F4FD; --text-secondary:rgba(232,244,253,.6); --text-dim:rgba(232,244,253,.28);
--font-ui:'Exo 2'; --font-mono:'Share Tech Mono';
```
- **Switchable accent themes** (cyan default; amber/green/violet) via `data-theme` + localStorage.
- **Ambient texture toggles:** `data-scanline`, `data-dotgrid`; **density:** `data-density`
  (compact/normal/comfy). v2: make these a real *adaptive density + motion* system.
- **Signature elements:** corner-bracket panels (`Bracket`), arc-reactor logo (rotating SVG),
  glowing mono numerals, the neural-network brain, the situation ticker, clip-path notched message
  bubbles, SVG `<animateMotion>` packets on live edges.
- **Motion principles to keep:** motion = real activity; ≤ a few always-on animations; respect
  `prefers-reduced-motion` (currently weak — fix in v2). Don't poll faster than 30s.
- **Fonts** are self-hosted in `static/fonts/` (no external Google Fonts dependency at runtime —
  keep it offline-clean for local-first).

You may evolve the palette/type, but justify departures against §1 (calm authority) and keep the
offline/self-hosted-assets rule.

---

## 8 · Hard constraints (non-negotiable)

1. **Local-first & offline-clean.** No required external CDN/fonts/analytics at runtime. Everything
   self-hosted under `static/`. Must render and degrade gracefully with the backend partially down
   (recall/never-hard-fail ethos). `frigga/ultron/howard` are local-only — never imply cloud for them.
2. **Privacy & inspectability.** Don't add telemetry. Surfaces that show data must also let the user
   *edit/forget* it (memory decay, KG edits). Cloud hops are opt-in and must be *visible*.
3. **Serving model.** Production target is the existing FastAPI app serving static files — **no
   mandatory build step**. Default v2 stack = React 18 (local UMD) + plain `.js` `React.createElement`
   modules, same as today. *(Optional alt, requires explicit owner approval: a Vite/TS build that
   compiles to committed static assets still served by FastAPI — see §9 open decision D2.)*
4. **Auth model.** Three guards in `web.py`: open, `_user_guard` (personal data / runs code —
   localhost by default, `X-User-Token`/`JARVIS_USER_TOKEN` to expose on a network), `_admin_guard`
   (`JARVIS_ADMIN_TOKEN`). `auth.js` holds the client side. v2 must handle 401/403 and a token entry
   gracefully (admin/payments/kill-switch are admin-guarded).
5. **i18n RO+EN.** Every string through `i18n.js`. Keep Romanian copy verbatim. Default follows
   `localStorage['hud.lang']` → browser → `ro`.
6. **PWA.** Keep installability + service worker (offline shell). Don't break `manifest.json`/`sw.js`.
7. **Accessibility.** Keyboard-first (palette + hotkeys), focus states, contrast on the dark theme,
   `prefers-reduced-motion`, reduced-density mode. This is currently weak — make it a v2 goal.
8. **Performance.** Instant for non-LLM interactions; stream LLM output; never block paint; respect
   the ≥30s polling floor; lazy-load heavy surfaces (network brain, workflow canvas, KG browser).
9. **Production-grade.** Ships with tests (frontend harness already exists — §13) and updates the
   docs it makes stale ([`AGENTS.md`](../../AGENTS.md) convention).

---

## 9 · The v2 brief — goals, opportunities, open decisions

### 9.1 Goals
- **G1 — Coherent IA.** Give all ~30 capability areas (§4) a calm home. Propose a primary
  navigation model (recommendation in §10) instead of accreting overlays.
- **G2 — Trust made beautiful.** Promote Security/Trust/Governance (audit chain, kill-switch,
  capabilities, payments, % local) from buried tool-panels to a first-class **Trust Center**.
- **G3 — The cockpit, elevated.** The chat + orchestration trace + network brain remains the hero.
  Make "watch it think and route" genuinely delightful and informative.
- **G4 — Living memory.** A first-class **Memory & Knowledge** surface: fused recall, profile,
  spaces, decay/forget, and a **bitemporal KG browser with a time slider**.
- **G5 — Calm autonomy.** A budgeted **decision inbox** (cards) + morning brief / evening retro,
  reflecting "proactive, not noisy."
- **G6 — Adaptive surface.** Real responsive + ambient/standby mode + designed density/motion.
- **G7 — Unify or intentionally separate** HUD and Admin.

### 9.2 Concrete opportunities (non-exhaustive)
- A **time-travel KG/audit** view (the bitemporal `as-of`/`history` endpoints are begging for a
  scrubber). • A **provenance popover** on any agent message (which memories/plugins/route produced
  it — data is in cognition + traces). • A **kill-switch** that feels physical and reassuring. • A
  **cost/locality meter** (% local vs cloud, live) as a persistent trust signal. • The **embeddable
  widget** as a themable mini-HUD. • The **workflow canvas** as a flagship node editor. • An
  **arena** view for model A/B. • A redrawn, coherent **glyph + iconography** set.

### 9.3 Open design decisions (resolve early; recommendations given)
- **D1 — IA model.** Recommend: a left **rail of "modes"** (Cockpit · Agents · Memory · Autonomy ·
  Trust · Build/Workflows · Observe · Interop · Admin) with the ⌘K palette as the universal jump;
  the Cockpit (chat+network+ambient) is home. *(Alt: keep single dense dashboard. Decide.)*
- **D2 — Stack.** Recommend: keep **no-build React-via-CDN** for production consistency &
  local-first simplicity. Prototype may use anything; the *committed* result must fit §8.3. If a
  modern build (Vite/TS) is wanted, that's an **owner decision** — flag it, don't assume it.
- **D3 — HUD/Admin unification** (G7). Recommend: unify under one shell with an "Admin" mode behind
  the admin guard.
- **D4 — Scope of v1 of v2.** Recommend shipping the Cockpit + Agents + Trust + Memory modes first;
  fold the rest of the tool panels in over follow-ups. Confirm scope with owner.

> **D1–D4 change the deliverable materially.** Surface them to the owner (Andrei) before deep
> visual work — ideally as a one-screen options doc — rather than guessing.

---

## 10 · Recommended information architecture (a starting point)

```
┌ TOPBAR  logo · live clock · model/locality/trust/voice badges · ⌘K · lang · theme ┐
├ (optional) SITUATION TICKER — live agent activity, severity-tinted                ┤
├ RAIL ─┬──────────────── STAGE (mode-dependent) ─────────────────┬ CONTEXT (right) ┤
│ ◉ Cockpit   │  Cockpit: NetworkBrain + Conversation + Input      │ ambient widgets │
│ ◇ Agents    │  Agents: roster → Dossier; collab graph            │ weather/cal/    │
│ ◇ Memory    │  Memory: recall · profile · spaces · decay · KG⌚   │ heartbeat /     │
│ ◇ Autonomy  │  Autonomy: decision inbox · brief · observer       │ decision cards  │
│ ◇ Trust     │  Trust: audit chain · kill-switch · caps · payments│ (context-aware) │
│ ◇ Build     │  Workflows canvas · skills marketplace · sandbox   │                 │
│ ◇ Observe   │  Traces · eval · quality · arena · resilience      │                 │
│ ◇ Interop   │  A2A peers/inbox · MCP server · widgets · webhooks │                 │
│ ◇ Admin 🔒  │  settings · env · prompts A/B · models · cost      │                 │
└───────────┴───────────────────────────────────────────────────┴─────────────────┘
   ⌘K Command Palette overlays everything (agents, tasks, settings, jump-to-mode, actions)
```
This is a *proposal*, not a mandate — the IA is the core creative problem; improve on it. Whatever
you choose, **every item in §4 must be reachable** (surfaced, nested, or palette-only) and the
result must feel calmer than today, not busier.

---

## 11 · Deliverables & file layout

1. **Prototype** (the visual + interaction spec): a self-contained `design/index.html` you can open
   in a browser, in the spirit of the existing `design_handoff_jarvis_hub/design/`. Include all
   modes you're proposing, real interactions (palette, focus mode, KG time slider, decision cards),
   and the design tokens. *The prototype IS the spec.*
2. **A short decisions doc** resolving D1–D4 (§9.3) with rationale — for owner sign-off.
3. **Production port** into the repo (after sign-off), following §8.3:
   ```
   agents/web2/                      # v2 lives beside the current agents/web/ during the transition
     templates/index.html           # shell: prefs pre-paint, react UMD, ordered module scripts
     static/
       style.css, fonts.css, fonts/ # self-hosted; tokens + components
       data.js                      # live-data adapter over the §5 API (reuse shapes)
       i18n.js                      # RO+EN (port existing strings; don't retranslate)
       auth.js                      # token handling (user/admin guards)
       app.js                       # root: state, hotkeys, SSE submit flow, polling
       shell.js / rail.js           # new IA shell + mode rail
       cockpit.js, network.js       # hero: brain + conversation + input
       agents.js, dossier.js        # roster + dossier
       memory.js, kg.js             # recall/profile/spaces/decay + bitemporal KG browser
       autonomy.js                  # decision inbox + brief + observer
       trust.js                     # audit chain + kill-switch + capabilities + payments
       build.js                     # workflows canvas + skills marketplace + sandbox
       observe.js                   # traces + eval + quality + arena + resilience
       interop.js                   # a2a + mcp + widgets + webhooks
       admin.js                     # settings/env/prompts/models/cost (or unified per D3)
       palette.js                   # ⌘K
       sw.js, manifest.json, favicon.svg
   ```
4. **Backend:** reuse the §5 API. Add endpoints only where a surface genuinely needs new data
   (recipe: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) §8 "Add a web endpoint"); never break
   existing shapes. New polling endpoints → add to `_NO_STORE_PATHS`.
5. **Tests** (§13) + doc updates (this file, `STATUS.md`, `docs/ARCHITECTURE.md` §9 filesystem map).

> Keeping v2 under `agents/web2/` (not overwriting `agents/web/`) is what makes the **side-by-side,
> different-port** comparison in §12 possible until v2 is ready to become the default.

---

## 12 · Running v2 on a different port for testing (the requirement)

Goal: run the **current HUD on :8080** and the **new HUD on a second port** at the same time,
against the **same backend/API**, so they can be compared live. Three options, easiest first.

### Option A — `serve_hud_v2.py`: a thin app on :8090 that serves v2 statics + proxies the API ✅ recommended
No CORS, no backend edits, same-origin API. Spec to drop at repo root:

```python
# serve_hud_v2.py — run the v2 HUD on :8090, proxy all API/chat to the real backend on :8080
import httpx, uvicorn
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

WEB2 = Path(__file__).parent / "agents" / "web2"
BACKEND = "http://127.0.0.1:8080"           # the real Jarvis API (serve.py)
# Anything the frontend fetches that must hit the real backend:
PROXY_PREFIXES = ("/api", "/chat", "/status", "/agents", "/dashboard", "/ticker",
                  "/tasks", "/memory", "/autonomy", "/heartbeat", "/learning",
                  "/skills", "/plugins", "/sandbox", "/sessions", "/bench",
                  "/security", "/tts", "/.well-known")

app = FastAPI(title="Jarvis HUD v2 (dev)")
app.mount("/static", StaticFiles(directory=str(WEB2 / "static")), name="static")

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((WEB2 / "templates" / "index.html").read_text("utf-8"))

@app.get("/sw.js")
async def sw():
    return FileResponse(str(WEB2 / "static" / "sw.js"), media_type="application/javascript")

@app.api_route("/{path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    if not any(("/" + path).startswith(p) for p in PROXY_PREFIXES):
        return Response(status_code=404)
    url = f"{BACKEND}/{path}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.request(request.method, url, params=request.query_params,
                                 content=body, headers=headers)
    # stream-friendly passthrough (SSE for /chat/stream works because we don't buffer-transform)
    return Response(content=r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items()
                             if k.lower() not in ("content-encoding", "transfer-encoding", "connection")})

if __name__ == "__main__":
    print("Jarvis HUD v2 (dev) on http://127.0.0.1:8090  → proxying API to", BACKEND)
    uvicorn.run(app, host="127.0.0.1", port=8090, log_level="info")
```
Run both: `python serve.py` (backend+old HUD :8080) and `python serve_hud_v2.py` (v2 :8090).
*(For true SSE streaming through the proxy, switch the `/chat/stream` branch to
`client.stream(...)` + `StreamingResponse`; left simple here for clarity.)*

### Option B — pure static dev server + CORS (zero proxy code)
Serve the v2 folder directly: `python -m http.server 8090 --directory agents/web2`, point v2
`data.js` `API_BASE` at `http://127.0.0.1:8080`, and enable CORS for the dev origin in `web.py`
(add `CORSMiddleware` allowing `http://127.0.0.1:8090`, dev-only). Simplest, but cross-origin (auth
cookies/tokens + SSE need care).

### Option C — same server, second port via env (production cutover path)
Make the real server's port configurable and optionally serve v2 at `/` when a flag is set:
`uvicorn.run(app, port=int(os.environ.get("JARVIS_PORT", "8080")))` in `serve.py`, and a
`JARVIS_HUD=v2` switch in `web.py`'s `GET /` to return the v2 shell. Good for the eventual flip;
less convenient for true side-by-side than A.

> Recommend **A** for the design/build phase (clean same-origin, no backend changes), then **C** to
> cut over once v2 is the default. None of these touch the current HUD until you choose to.

---

## 13 · Acceptance criteria & checklist

**Done (v1 of v2) =** with the backend running, the v2 HUD on its own port shows:
- [ ] A coherent IA (the chosen mode model) where **every §4 capability is reachable**; feels
      calmer than today.
- [ ] Working chat → real LM Studio responses, streamed, with a legible orchestration/cognition
      trace (classify → route → synthesize).
- [ ] All 16 agents grouped by tier with glyphs; dossier on demand; live network brain with
      activity-driven pulses + collab edges; focus mode.
- [ ] A **Trust Center**: audit chain view, working kill-switch, capabilities, payments mandates +
      pending-approval queue, and a live **% local vs cloud** signal.
- [ ] A **Memory & Knowledge** surface: fused recall, profile, spaces, decay/forget, and a
      **bitemporal KG browser with a time slider** (`as-of`/`history`).
- [ ] A budgeted **decision inbox** (autonomy cards) + morning brief.
- [ ] ⌘K palette (agents/tasks/settings/jump-to-mode/actions), hotkeys, RO/EN toggle, theme +
      density + reduced-motion controls.
- [ ] PWA installable; offline shell; graceful 401/403 + degraded-backend states; zero console
      errors; self-hosted assets only.
- [ ] Runs on a **separate port** beside the current HUD (§12) for side-by-side review.
- [ ] Frontend tests pass. The repo already has a vitest-based harness in `tests/frontend/`
      (`harness.js`, `*.test.js`, run via `vitest.config.js` / `npm test`); add v2 coverage there.
- [ ] Docs updated (this brief, `STATUS.md`, `docs/ARCHITECTURE.md` filesystem map).

**Suggested build order:** decisions doc (D1–D4) → prototype `design/index.html` → shell + rail +
palette → Cockpit (network + chat) → Agents/Dossier → Trust Center → Memory/KG → Autonomy inbox →
remaining modes → port to `agents/web2/` + `serve_hud_v2.py` → tests → cutover plan.

---

## 14 · Appendix — key files to read & glossary

**Read first (in order):** `MOONSHOT.md` (why) → `docs/ARCHITECTURE.md` (where code lives,
lifecycle, recipes) → `agents/web.py` (the whole API) → `agents/web/static/*.js` (today's UI as a
spec) → `agents/_system/agents.yaml` (+ a few `agents/<id>/SOUL.md`) → `design_handoff_jarvis_hub/`
(current aesthetic + prototype) → `agents/core/settings_db.py` (runtime settings the admin edits).

**Data shapes:** `data.js` (frontend adapter + `GLYPHS`/`COLLAB`/`TIERS`), and the JSON returned by
`/status`, `/dashboard`, `/api/cognition`, `/api/memory/*`, `/api/kg/*`, `/api/traces`, etc. — hit
them live against a running server to capture exact shapes.

**Glossary:** *Horizon (H#)* = a roadmap epic (e.g. H16.3 payments) in `BACKLOG.md`. *Tier* =
CNS/BIZ/SEC/FND. *Bench* = dormant promotable agents. *Soul* = an agent's `SOUL.md` identity prompt.
*Bitemporal KG* = facts stored with both valid-time and transaction-time → `as-of`/`history`
queries. *Guards* = open / `_user_guard` / `_admin_guard`. *Local-only agents* = frigga/ultron/howard
(never cloud). *Counter-metrics* = guardrail metrics (interrupt rate, % local, p95 latency, reject
rate) — good candidates for persistent HUD signals.

---

*North star for this brief: the new HUD should make a person feel they are sitting at the controls
of a private intelligence they fully own and fully trust — calm, legible, and a little bit awe-
inspiring. Everything above is in service of that.*
