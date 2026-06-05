# Jarvis Hub — HUD v2 Implementation Plan (build‑it‑right)

> **Status:** detailed engineering plan for **confirmation before building**. No code yet.
> **Locked:** D1 rail+⌘K · **D2 = Vite + React + TypeScript** · D3 unify Admin · D4 all modes ·
> rollout = **`/v2` on the same FastAPI server** · **every capability surfaced** (parity gate).
> Companion: `HUD_V2_BRIEF.md` (north star) · `HUD_V2_COVERAGE_AND_PLAN.md` (the gap matrix this plan
> executes) · prototype in `design_handoff_jarvis_hub/pr-hud-v2/`.
> Generated 2026‑06‑05 · Owner: Andrei.

## 0 · Verified ground truth (so the plan isn't hand‑wavy)
- `agents/web.py` → `FastAPI(title="Jarvis", …)` with **`/openapi.json` enabled** (docs not disabled).
- **`response_model=` on 1 / 228 routes**, but **32 `BaseModel` request models** exist → OpenAPI yields
  solid **request/param** types, **thin response** types. (Drives §2.)
- Two `@app.middleware("http")` + opt‑in `CORSMiddleware`; per‑IP rate limit exempts localhost/valid token.
- **Node 22 + npm 10 available**; `vitest@2` already used for HUD tests.
- Root `package.json` is **dev‑test‑only** and states the HUD "ships as vendored globals, no bundler" →
  the Vite app must live in its **own package**, coexisting with the legacy HUD until cutover.

---

## 1 · Target architecture (Vite/TS ⟷ FastAPI at `/v2`)

**Repo layout** (isolates the Node/TS world from the Python tree):
```
frontend/                      # the Vite + React + TS app (its own package.json, node_modules)
  index.html                   # Vite entry; base '/v2/'
  package.json  vite.config.ts  tsconfig.json
  public/fonts/                # self-hosted Space Grotesk + JetBrains Mono (woff2) — no CDN
  src/
    main.tsx  App.tsx
    styles/v2-style.css        # ported as-is (framework-agnostic)
    api/{client.ts, schema.ts, loaders.ts}   # typed client (§2) + per-mode loaders
    state/  hooks/  i18n/       # store, hooks, EN+RO map (typed keys)
    shell/  cockpit/  network/  modes/<Mode>/   # primitives → shell → 15 modes
    pwa/sw.ts                  # service worker scoped to /v2
  dist/  → build.outDir = ../agents/web/v2     # build output committed for Python-only runtime
agents/web/v2/                 # COMMITTED built bundle (index.html + assets/*) served by FastAPI
```

**Dev workflow** (HMR + real backend): `python serve.py` (backend :8080) **and** `cd frontend && npm run
dev` (Vite :5173). `vite.config.ts` `server.proxy` forwards `/api`, `/chat`, `/status`, `/agents`,
`/dashboard`, `/ticker`, `/tasks`, `/memory`, `/autonomy`, `/heartbeat`, `/learning`, `/skills`,
`/plugins`, `/sandbox`, `/security`, `/tts`, `/.well-known` → `http://127.0.0.1:8080`. Same code, real data.

**Prod serving** (same origin, no CORS): Vite builds with `base:'/v2/'` → `agents/web/v2/`. Add to `web.py`:
```python
app.mount("/v2/assets", StaticFiles(directory=str(HERE/"web"/"v2"/"assets")), name="v2-assets")
@app.get("/v2", response_class=HTMLResponse)
@app.get("/v2/{path:path}", response_class=HTMLResponse)   # SPA fallback for client routes/deep links
async def hud_v2(path: str = ""):
    return HTMLResponse((HERE/"web"/"v2"/"index.html").read_text("utf-8"))
```
Current HUD at `/` is untouched. Cutover later = point `/` at the v2 shell (one line).

**Build‑artifact strategy (the key D2 issue — solved):** **commit the built `agents/web/v2/` bundle.**
Rationale: keeps the **local‑first / one‑command self‑host** promise — `python serve.py` needs **no Node**.
Developers/CI run `npm ci && npm run build`; a CI guard (`§11`) fails if the committed bundle is stale.
*(Alternative considered — build during install — rejected: puts Node on every self‑host host, violating
the pitch. We get B's DX without B's runtime cost.)*

---

## 2 · Type safety across 228 endpoints (the response_model gap — solved)
1. **Generate request/param types** from `/openapi.json` via `openapi-typescript` → `src/api/schema.ts`
   (CI regenerates + git‑diffs to catch drift). The 32 `BaseModel`s make request bodies fully typed.
2. **Hand‑write response types** for the ~30 endpoints v2 actually consumes in `src/api/types.ts`
   — shapes are already known (prototype `v2-data.jsx` + live capture from the running server). One typed
   `apiGet/apiPost<T>()` wrapper binds them.
3. **Optional backfill:** add `response_model=` to the hot endpoints over time → those collapse into the
   generated client and improve `/docs` for free. Not a blocker; tracked as a fast‑follow.
> Net: end‑to‑end types on everything v2 touches, without waiting on a 228‑route annotation sweep.

---

## 3 · Design‑system & component port
- **`v2-style.css` ported verbatim** (it's framework‑agnostic) → locks the look on day one. Keep the
  `data-look/accent/density/motion/scanline/dotgrid` token system; Admin folds in with **zero new colors**.
- **Fonts self‑hosted** (woff2 under `public/fonts/`, `@font-face` in CSS) — no Google CDN (offline/local‑first).
- **Component port:** drop the prototype's Babel `Object.assign(window,…)` / re‑import hack → real ES
  modules + TS. Keep boundaries 1:1 (primitives → shell → modes; they're already clean). `React.createElement`
  becomes JSX. **Lazy‑load each mode** (`React.lazy` + route split) so the 15 modes don't ship as one bundle.

---

## 4 · Data layer
- **`loaders.ts`** = one typed loader per mode (maps real responses → component props), replacing every
  `window.V2.*` read. Initial fetch set already known to work: `/api/agents`, `/status`, `/dashboard`,
  `/tasks`, `/ticker`.
- **Streaming:** Cockpit chat over `POST /chat/stream` (token‑by‑token) and a **real cognition SSE**
  (classify→route→gather→synthesize) replacing the prototype `setTimeout`. Abort on unmount; keep the
  4‑stage visual.
- **Polling:** live tiles ≥30s (respect the existing `_NO_STORE_PATHS`); pause when tab/wall‑display idle.
- **Auth:** token store (localStorage, mirroring `auth.js`); a fetch interceptor surfaces a token‑entry
  modal on **401**; **admin‑guarded** modes (Admin, payments, kill‑switch, secrets, prompts) render a
  locked state without an admin token. Never expose admin calls cross‑network.
- **Degraded states:** every loader has loading / empty / error / offline branches (recall‑never‑hard‑fails
  ethos); a partial backend never blanks the HUD.

---

## 5 · Mode wiring + the ~18 gap surfaces (the parity work)
Execute the `HUD_V2_COVERAGE_AND_PLAN.md` matrix. Existing‑surface modes get wired; the ❌ items get built
into their home mode:

| Home mode | Wire (✅) | **Add (❌/⚠️ gap surfaces)** |
|---|---|---|
| Cockpit/Chat | chat SSE, cognition, ticker, network, decisions, weather/cal/heartbeat | provenance modal (real), **notes**, **rooms** |
| Agents | roster, dossier, collab | **bench + promotion**, heartbeat control, **agent templates** |
| Trust | audit chain, kill‑switch, %local, capabilities | **payments lifecycle (H16.3)**, **secrets broker**, **injection scan/spotlight**, posture/governance, guardrails mode |
| Memory | stats, recall, bitemporal KG | **Data Spaces (H10.26)**, KG edit, decay→forget, consolidation, local‑docs RAG, memory‑eval |
| Autonomy | brief, observer, policies | **preference‑learning**, dry‑run/preview, escalation, reflection |
| Build | workflow DAG, skills, sandbox(routing) | **AI step builder (H10.7)**, **marketplace signing/moderation (H12.12)**, **code‑exec sandbox** |
| Observe | quality, traces, arena, latency, resilience | **eval datasets + runs**, **review queue**, cost analytics |
| Interop | A2A peers, MCP clients, widgets, webhooks | **A2A approval inbox (H16.2)**, MCP server mode + token |
| Admin | models, plugins, keys, channels, backups, host | **settings DB editor**, **prompt A/B/diff/rollback**, LM load/unload, agent‑config edit |
| Life/Comms | finance, health, knowledge, family, unified inbox | voice/wake config, schedule NL parse |

Each gap surface follows the prototype's `ModePanel + SubH + two‑column` template — additive, no new design.

---

## 5b · Backlog cross‑check — surfaces the prototype/plan missed
A round‑2 pass over `BACKLOG.md` (H8–H17, mostly ✅‑built) found these **shipped‑but‑unsurfaced** or
under‑weighted items. Folding them in now so v1 can't drop them (all enter the §8 parity gate):

| Surface | Backlog | Why it matters | Home → endpoint |
|---|---|---|---|
| **User Profile — "what Jarvis knows about you"** (facts/prefs/people/projects · inspect·edit·**export JSON**·forget) | H8.1 / H8.2 | the **flagship personalization** feature; prototype has no profile view | Memory (first‑class panel) → `GET /api/memory/profile` + forget/export |
| **Strict‑local / mic‑mute trust badge** | H12.10 | a shipped, explicit HUD trust signal (endpoint at `web.py:3013` → `mic`,`strict_local`) | TopBar/Trust badge |
| **Discord + Slack channels** | H12.11 | both exist + wired; prototype Comms only has TG/email/WA/voice | Comms inbox + Admin channels + escalation targets |
| **Sessions browser + resume (+ clear)** | core | current HUD has it; v2 prototype dropped it | Cockpit/Chat → `/sessions`, `/sessions/resume`, `/memory/clear` |
| **Model browse / download / switch** (not just view) | H12.9 | Jan‑style one‑click model mgmt | Admin models → `/api/models/local`, `/switch` |
| **Backup trigger + restore** (not just list) | H12.15 | the only real state is git‑ignored — restore matters | Admin backups (scripts) |
| **NL scheduling** ("every weekday 7am"→cron) | H10.27 | quick proactive affordance | Autonomy/Pepper → `POST /api/schedule/parse` |
| **Voice satellites (Wyoming) + wake/mute config** | H12.4 / H12.10 | Home‑Assistant voice ecosystem | Voice surface (Admin/Comms) → `/api/voice/wyoming` |
| **Per‑agent run history timeline** | H10.17 | timeline of runs/cost/route per agent | Dossier (confirm) → `/api/agents/{id}/history` |
| **APM org dashboard** | H10.16 | tokens/cost/runs by agent+model | Admin/Observe → `/api/admin/apm` |

**Backend‑only (no HTTP surface yet) — decide reserve vs `NOT_IN_HUD`:**
- **Howard digital‑twin ingestion** — `core/ingestion/` (Facebook/WhatsApp archives → vectors, **stylometry**
  voice profiling, continuous watcher). **No endpoints today** (only `/api/kg/ingest`). **Decision (owner):
  `NOT_IN_HUD` for v1 of v2** — recorded in the parity‑gate allowlist (§8); revisit when an ingestion API +
  VLM screen/doc understanding (H13.1) land, then add a Memory/Howard panel.

**Reserve IA space for in‑scope‑v1.0 frontiers (planned, not built):**
- **Computer‑Use (H15)** — browser/desktop operation **behind the approval queue** + egress allowlist +
  screen‑understanding. A *major* future surface with no home in the 15 modes → reserve a **"Control"** mode
  slot (or fold into Autonomy) **now**, so adding it later isn't a restructure.
- **Passive multi‑surface capture (H12.7)** + **E2E device sync (H12.13)** — future opt‑in → Memory/Settings.
- **Onboarding / first‑run (H12.2)** — drop‑folder index + personalization setup; low priority for the single
  owner but real.

**Deployment note:** D2 = Vite/React makes a future **Tauri desktop wrapper (H11.1)** straightforward (vs the
old no‑build globals) — a side‑benefit of choosing B.

**Prototype bug to fix during the port (P2):** the NEURAL NETWORK renders **Jarvis twice** — once as the
central `JARVIS · CORE` (`v2-network.jsx:126‑133`) and again as a CNS ring node, because the node loop
iterates *all* agents incl. `jarvis` (`v2-network.jsx:136‑150`). Fix: exclude the orchestrator from the
orbiting nodes / layout / spokes (`agents.filter(a => a.id !== 'jarvis')`) so it appears only as the core.
*(Spotted by owner — sweep for other "core vs. agent" double‑counts when wiring the live roster.)*

---

## 6 · Backend additions needed (anticipated, minimal, non‑breaking)
Most ❌ items already have endpoints. The few that need backend work:
1. **Streaming cognition SSE** (`GET /api/cognition/stream`) emitting classify→route(scores)→plugin‑reads→
   synthesize, + **provenance** (agents/plugins/local/conf) on the chat stream. *(Today `/api/cognition` is a
   GET snapshot.)*
2. **Compute‑locality / cost summary** (`GET /api/analytics/locality`) to back the real **% local** meter +
   cost tile (compose from `/api/analytics/model-tiers` + `/api/cost`).
3. **Optional `response_model=`** on the ~30 consumed endpoints (improves types + `/docs`).
4. **Howard ingestion API** — *only if* we surface the digital twin (§5b): endpoints for archive ingest +
   stylometry profile + twin/watcher status (the `core/ingestion/` subsystem is daemon‑only today).
All via the `docs/ARCHITECTURE.md §8` recipe; new polling paths → `_NO_STORE_PATHS`; no shape changes to
existing responses.

---

## 7 · Cross‑cutting
- **i18n:** port `V2.I18N.{en,ro}` to a typed key union (lint for missing keys); RO copy **verbatim**; default
  `localStorage['hud.lang']`→browser→`ro`.
- **PWA/SW:** Vite‑PWA service worker **scoped to `/v2`** with distinct cache names — must not clobber the
  existing SW at `/`. Offline shell preserved.
- **A11y:** finish keyboard nav for network nodes + palette; ARIA on meters/status dots; focus traps in
  modals; contrast audited on the dark theme.
- **Motion/perf:** honor `prefers-reduced-motion` in **JS timers too** (clock/ticker/packets); pause on
  `document.hidden` / idle for the 24/7 wall display; per‑mode code‑split; lazy network/KG SVG; perf budget.
- **Responsive:** define breakpoints < ~1100px (cockpit 3‑col → stacked).

---

## 8 · Testing ("first time right")
- **vitest@2 + jsdom** for component + loader tests (the runner is already in the repo). Test each mode's
  loading/empty/error branches with mocked typed responses.
- **Type check** (`tsc --noEmit`) in CI = a wall against shape drift.
- **Parity‑gate test:** a checklist test asserting **every one of the 228 endpoints** is either referenced by
  a loader **or** in an explicit `NOT_IN_HUD` allowlist (machine‑facing specs). This is the automated
  "nothing missed" guard.
- **Keep the legacy `tests/frontend/` suite** green until cutover (current HUD unchanged).

---

## 9 · CI/CD + self‑host
- New CI job: `frontend` → `npm ci` → `tsc --noEmit` → `vitest run` → `npm run build` → **assert the
  committed `agents/web/v2/` bundle matches the fresh build** (stale‑bundle guard).
- Regenerate `schema.ts` from `/openapi.json` in CI; fail on diff.
- **Self‑host unchanged for end users** (Python‑only runtime, committed bundle). `INSTALL`/`start.sh` get a
  one‑line note for contributors who rebuild the front‑end.
- Side note: the **`Smoke Test` workflow is currently failing on `main`** (pre‑existing) — I'll diagnose it
  separately so it isn't confused with v2 CI.

---

## 10 · Risks & mitigations (anticipated up front)
| # | Risk / issue | Mitigation |
|---|---|---|
| 1 | Node toolchain breaks "pure‑Python / one‑command self‑host" | Commit built bundle; runtime needs no Node; CI builds + stale‑bundle guard |
| 2 | OpenAPI response types thin (1/228 `response_model`) | Generate request types; hand‑write response types for consumed endpoints; optional `response_model` backfill |
| 3 | SSE buffered/broken by the 2 http middlewares | Verify `StreamingResponse` passes unbuffered; no‑store middleware must not read body; add an SSE smoke test |
| 4 | Admin endpoints exposed / 401‑403 mishandled | Token interceptor + locked admin modes; never call admin cross‑network; localhost default |
| 5 | SPA deep links 404 at `/v2/...` | FastAPI `GET /v2/{path:path}` fallback + Vite `base:'/v2/'` |
| 6 | v2 service worker clobbers `/` PWA | Scope SW to `/v2`, distinct cache names; test both installable |
| 7 | Mock→real shape mismatches | Loader adapter layer + types + per‑mode integration tests |
| 8 | Gap surface lacks backend data | §6 pre‑list; add via recipe; non‑breaking; most already exist |
| 9 | 15 heavy modes = huge bundle | Route‑based code splitting, React vendor chunk, lazy SVG, perf budget |
| 10 | 24/7 wall display burn‑in / churn | Idle‑pause timers (Page Visibility), reduced‑motion in JS, ambient mode |
| 11 | i18n key drift EN/RO | Typed key union + missing‑key lint; RO verbatim |
| 12 | Two front‑end stacks during transition | `/v2` fully independent of `/`; documented; cutover removes legacy |
| 13 | Sensitive data on screen (audit/memory/family) | Family local‑only; secrets masked via broker; respect guardrails; no telemetry/logging of bodies |
| 14 | Large unreviewable PRs | Phased PRs (§11), each green + independently reviewable |
| 15 | Babel→Vite port regressions | Mechanical ES‑module port; TS + tsc catches most; component tests |
| 16 | Bundle in git noise | Bundle isolated under `agents/web/v2/`; source diffs are the review surface; guard ensures freshness |
| 17 | Dev/prod drift | Vite proxy mirrors prod mounting; single `API_BASE`; same‑origin in prod |
| 18 | Cutover risk | Ship behind `/v2`; flip `/` only on your word; rollback = remove route |

---

## 11 · Phased delivery (each = one green, reviewable PR)
- **P0 Scaffold:** `frontend/` Vite+React+TS, `base:'/v2/'`, self‑hosted fonts, ported `v2-style.css`,
  `web.py` `/v2` mount + SPA fallback, committed bundle + CI guard. Renders the shell with mock data at `/v2`.
- **P1 Typed data layer:** `schema.ts` gen + typed client + loaders; wire `/api/agents`,`/status`,
  `/dashboard`,`/tasks`,`/ticker`; auth interceptor + degraded states.
- **P2 Hero:** cockpit chat SSE + real cognition stream + provenance; live network.
- **P3 Wire capability modes:** Trust, Memory, Autonomy, Build, Observe, Interop, Comms, Admin, Life modes
  → existing endpoints.
- **P4 Gap surfaces (parity gate):** build every ❌ from §5 into its home mode; backend additions from §6;
  **parity‑gate test must be 100%**.
- **P5 Polish:** real settings (replace tweaks panel), a11y, responsive, motion/idle, ambient depth.
- **P6 Cutover (on your word):** `/` → v2; archive legacy HUD; update `STATUS.md`, `JARVIS.md`,
  `docs/ARCHITECTURE.md`.

---

## 12 · Definition of done ("first time right")
Every §5 row wired or in the signed `NOT_IN_HUD` allowlist · all 8 coverage‑shortlist features shipped ·
`tsc` clean · vitest + parity‑gate green · EN/RO parity · PWA installable + offline shell (both `/` and `/v2`)
· self‑host still Python‑only one‑command · local‑first respected (frigga/ultron/howard never cloud; Family
local‑only) · zero console errors · committed bundle fresh.

## 13 · Confirm to start
Please confirm: **(a)** repo layout (`frontend/` source + committed `agents/web/v2/` bundle), **(b)**
build‑artifact strategy (commit the bundle), **(c)** the P0→P6 sequencing. On your "go", I start **P0** and
open a draft PR.
