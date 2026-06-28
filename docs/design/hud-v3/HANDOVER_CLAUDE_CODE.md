# Jarvis Hub — HUD v3 → Claude Code Handover

> **What this is.** `hud-v3/` is an **executable design spec** for the single-page HUD: a self-contained,
> browser-runnable prototype of the full IA, wired to a mock that speaks the **real** backend wire
> shapes. This doc is the bridge from that prototype to the production `frontend/src` HUD.
>
> **Synced to `main`** at commit `9ffeb8d…` (v0.11.0, ~342 routes, still developing). The design brief
> `docs/design/SINGLE_PAGE_HUD_BRIEF.md` (2026-06-27) is the **stable target** and is unchanged.
>
> **The one rule:** the prototype *is* the design contract. Match it; don't reinterpret it.

---

## 0 · The three anchors

Claude Code only needs three things to implement this end-to-end:

1. **Design source of truth** — `hud-v3/` (this prototype). Runs in any browser. Every surface is
   demonstrated; `hud-v3/v3-api.jsx` already maps each surface to its real route.
2. **The contract** — `frontend/src/api/{client,actions,live,loaders,types}.ts` (same-origin fetch,
   the three auth tiers open/user-guard/admin-guard, the honest LIVE/SEED/OFFLINE rule).
3. **The completion gate** — `tests/test_hud_v2_parity.py`. "Done" = every human-facing route resolves
   to a real `frontend/src` surface or an explicit `NOT_IN_HUD`.

---

## 1 · Prototype file map (`hud-v3/`)

| File | Role |
|---|---|
| `index.html` | Loads React 18 + Babel + all modules; `<template id="__bundler_thumbnail">` for offline splash. |
| `v3-data.jsx` | All seed data + i18n (EN/RO) + `window.V2` namespace. The **shapes** here mirror the API. |
| `v3-primitives.jsx` | Icons, Glyph, Reactor, Meter, hooks (`useClock`), `renderRich`. |
| `v3-api.jsx` | **The live data layer**: `xfetch` (abort+timeout+401 retry), telemetry bus (p50/p95), mode transport (live/demo/offline), endpoint bindings, mappers, and hooks `useConnection`/`useResource`/`useMutation`/`useStream`. |
| `v3-mock.jsx` | In-browser backend (DEMO only): real wire shapes, chaos (latency/jitter/error/drop), a mission **engine** + SSE-style event stream. |
| `v3-netpanel.jsx` | Network Inspector + Chaos console + telemetry strip (dev rig; press `g n`). |
| `v3-mesh.jsx` | **Native canvas Neural Mesh** (replaces the `/brain?embed=1` iframe). Cinema mode via `cinema` prop. |
| `v3-shell.jsx` | Command bar (6 trust badges), rail, mode-swapping context column, palette, ambient, onboarding, **cinema overlay**, honesty banners. |
| `v3-cockpit.jsx` | Conversation (streaming + thumbs), cognition trace, input bar (voice popover + image attach). |
| `v3-decisions.jsx` | Decision Inbox (north-star) + Missions board/drawer. |
| `v3-modes.jsx` `…2/3/4` | Agents, Trust, Memory / Autonomy, Build, Observe (+AI-OS roadmap), Interop / Chat, Comms (+Rooms), Admin / Life. |
| `v3-timeline.jsx` | "Today in Jarvis" live tail + per-agent scopes matrix. |
| `v3-worldview.jsx` | World / Argus signal layer. |
| `v3-app.jsx` | Orchestration: connection state machine, hotkeys (1–0 + g-chords), all wiring. |

---

## 2 · Surface → component → endpoint → parity map

Sequenced by ORIZONT-24 phase. Each row ships as **its own PR** (tsc + vitest + stale-bundle guard green).

### Phase B — substrate (P0, do first)
| Surface (hud-v3) | Target (`frontend/src`) | Endpoint(s) | Notes |
|---|---|---|---|
| Decision Inbox (`v3-decisions.jsx`) | `modes` Decisions view | `GET /tasks` · `POST /autonomy/tasks/{id}/decision` | The north-star. Optimistic resolve + dry-run preflight. |
| Action Kernel syscall table (`v3-modes2` AI-OS) | Observe "Kernel" tile | `GET /api/metrics/kernel` | grant/deny/queue per kind. |
| Verification Fabric readiness (`v3-modes2` AI-OS) | Observe "Readiness" board | `GET /api/metrics/capabilities` | SEAM→WIRED→VERIFIED→GA; never fake VERIFIED. |
| Kill-switch (live + halts) | Trust STOP | `GET/POST /api/security/kill-switch` (admin) | engaged ⇒ writes blocked (honest 423). |
| Audit chain + verify chip | Trust audit panel | `GET /api/security/audit/intent` · `/verify` | chain grows on resolve; verdict chip. |
| %-local locality | Trust ring + badge | `GET /api/analytics/locality` | never fabricate a split. |

### Phase C — the ~37 deep write-controls (P1)
| Surface | Endpoint(s) |
|---|---|
| Missions board/drawer (pause/resume/accept) | `GET /autonomy/missions` · `POST …/{id}/{action}` |
| Autonomy AUTO/ASK/OFF + policies | `GET/POST /autonomy/mode` · `/autonomy/policy` |
| Memory recall search · remember · forget · KG edit/delete · ingest · local-docs | `/api/memory/search` · `/remember` · `/decay/forget` · `/api/kg/*` · `/api/local-docs/index` |
| Cockpit streaming + feedback + voice + VLM | `POST /chat/stream` · `/api/feedback` · `/api/voice/capabilities` · `/tts(/stream)` · `/api/vlm/describe` |
| A2A approval inbox · Rooms | `/api/a2a/inbox*` · `/api/rooms` |
| Governance / posture / loop-breaker | `/governance` · `/posture` · `/api/security/loop-breaker(/reset)` |
| Build: workflows · skills · sandbox · templates | `/api/workflows` · `/api/skills/marketplace*` · `/sandbox/execute` |
| Observe: quality-threshold · arena · evals · review | `/api/quality/threshold` · `/api/arena/*` · eval/review routes |
| Backup / export / forget-me · onboarding | `/api/admin/export` · `/forget` · onboarding route |
| Mesh devices / sync | `/api/a2a/peers` · mesh routes |

### Phase D — tail (P2) + WorldView / Life packs as plugins land.

---

## 3 · Translation rules (hand these to Claude Code explicitly)

1. **The prototype is the contract** — pixel/IA fidelity to `hud-v3/`, not a reinterpretation.
2. **Mock → real** — `v3-mock.jsx` exists only to demo; in `frontend/src` every "live" surface gets a
   **runtime check against the real backend** (year-one learning #3: mocks hide bugs).
3. **Hooks map 1:1** — `useResource`/`useMutation`/`useStream` → your loaders/SWR pattern; keep the
   loading→data→stale→honest-error lifecycle and the telemetry bus (p50/p95 is a real guardrail).
4. **Honesty contract** — LIVE shows real data, DEMO is watermarked, OFFLINE shows nothing stale.
   Never fabricate a %-local split or a VERIFIED state.
5. **Neural Mesh is native now** — `v3-mesh.jsx` is a `<canvas>` brain (no iframe). It shares the data
   layer and pulses on real stream events; port it as a component, drop the `/brain?embed=1` iframe.
6. **Auth tiers** — handle 401/403 with in-app token entry (not `window.prompt`); admin/payments/
   kill-switch-engage are admin-guarded.

---

## 4 · Competition-inspired improvement backlog (prioritized)

From the year-one review + `docs/research/2026-06-25-getjarvis-competitive-gap.md`. On-brand picks
(the 5-axis wedge: local-first · proactive · living memory · observability · governance):

1. **Frictionless onboarding (P0 product gap).** ✅ **Built in hud-v3** — `Onboarding` is now a real
   4-step wizard (connect live/demo → pull a local model → grant first capabilities → seed standing
   notes, persisted to `localStorage.jarvis_onb`). Port to `frontend/src`; wire model-pull to
   `/api/models/local` and capabilities to the kernel issuance.
2. **Polished local-model management (Jan.ai).** ✅ **Built in hud-v3** — Admin → Local Models:
   load / unload / set-default per model + a "pull a model" browser. Wire to `/api/models/local`
   + LM Studio server/load/unload.
3. **Multi-surface ambient capture (Pieces.app).** Extend Memory→Capture into an opt-in capture stream
   (clipboard/browser/screenshot → KG), each item deletable (the privacy promise made visible).
4. **Satellite-mic / Wyoming (Home Assistant).** Mesh→Devices "pair a phone as a mic satellite" is
   stubbed; make pairing a real flow.
5. **The "felt-value" loop (the real frontier).** Lead the demo with ONE undeniable proactive loop
   (morning brief + one reversible remediation) end-to-end — Direction C in the review. The cinema mode
   is the shareable artifact for it.

---

## 5 · Kickoff prompt for Claude Code

> Implement the hud-v3 prototype into `frontend/src` against the live backend. First, generate
> `docs/design/2026-06-28-hud-v3-impl-blueprint.md` in our standard format — one row per surface:
> *prototype component (`hud-v3/` file) → target `frontend/src` component → real endpoint(s) →
> acceptance → parity-gate row*. Then execute it **one PR per surface**, Phase-B substrate first
> (Action Kernel / Verification Fabric / readiness / kill-switch / audit-verify), then the ~37 deep
> write-controls, then the P2 tail. Rules: the prototype is the design contract (match it); every
> "live" surface gets a runtime check, not a mock; keep the LIVE/DEMO/OFFLINE honesty and the telemetry
> guardrails; port the native canvas Neural Mesh (`v3-mesh.jsx`) and drop the `/brain?embed=1` iframe.
> Each PR must be green on `tsc --noEmit` + vitest + the `hud-v2-build` stale-bundle guard.

---

*Open `hud-v3/index.html` to explore. Keyboard: 1–0 modes · g+L/W/T/C/N/D/M clusters · ⌘K palette ·
A ambient · ? shortcuts · g m cinema. Toggle DATA (badge) for live/demo/offline; open the Network
inspector with g n to pressure-test the data layer.*
