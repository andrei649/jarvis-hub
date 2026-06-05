# Jarvis Hub — HUD v2: Coverage Report & Integration Plan

> **Purpose:** verify the design session's HUD v2 prototype (`design_handoff_jarvis_hub/pr-hud-v2/`)
> covers **everything we've built**, and lay out how to **include it without dropping any capability**.
> This is the "plan first / gap report" deliverable — **no implementation here**; review, decide the
> two open points (§6), then I build in stages.
>
> Companion docs: `docs/design/HUD_V2_BRIEF.md` (the north‑star brief) · the prototype's own
> `pr-hud-v2/docs/design/HUD_V2_HANDOFF.md` + `HUD_V2_NAVIGATION_MAP.md`.
> Generated 2026‑06‑05 · Owner: Andrei.

---

## 1 · Executive summary

- **What it is:** a high‑fidelity, **mock** design prototype — 15 "modes" in a calm rail+⌘K shell,
  full design system (`v2-style.css`), EN/RO. **Zero of our 228 endpoints are wired** — every panel
  reads hard‑coded data on `window.V2`. The PR is explicitly a *handoff to Claude Code (Opus)* to
  graduate it into the real app.
- **Quality:** strong, and broader than my brief — it adds agent‑"home" modes (Finance, Health,
  Knowledge, Family) and a unified Comms + Admin. The IA is exactly the "calm rail of modes" we wanted.
- **Coverage verdict:** the **structure covers the big surface well**, but to "miss nothing" the
  implementation must (a) wire 15 modes to the real backend and (b) **add ~20 sub‑surfaces** for
  capabilities the prototype doesn't expose — *including several we just shipped* (Memory Data Spaces
  H10.26, signed/moderated marketplace H12.12, A2A approval inbox H16.2, AI step builder H10.7,
  governed‑payments lifecycle H16.3).
- **Decisions recorded by the design session:** D1 rail+⌘K · **D2 Vite+React+TS** · D3 unify Admin ·
  D4 all 15 modes. **D2 (a Node build step) conflicts with the current no‑build, Python‑served,
  local‑first model — open for your call (see §5).** Rollout = **`/v2` on the same server** (your pick).

---

## 2 · Method (so you can trust the gap list)

Coverage was assessed against the authoritative surface of the prototype — its **data contract**
(`window.V2` in `v2-data.jsx`), the **navigation map** (15 modes → component → data key), the
**handoff doc**, and a term‑by‑term **grep** of all `v2-*.jsx` for each capability we built — then
cross‑referenced against the **228 `agents/web.py` endpoints** and the feature set in
`docs/design/HUD_V2_BRIEF.md` §4–§6. A mode "covers" a capability only if it has a real surface for
it (a data key + panel), not merely an adjacent concept.

Legend: ✅ has a surface (needs wiring) · ⚠️ partial / adjacent only · ❌ no surface (must add).

---

## 3 · Coverage matrix (every capability → status → where it lands)

### Core (Cockpit / Chat / Agents)
| Capability | v2 | Home → endpoints to wire |
|---|---|---|
| Chat + **SSE streaming** | ✅ | Cockpit/Chat → `POST /chat/stream`, `/chat` |
| Cognition trace (classify→route→gather→synth) | ✅ | Cockpit → real orchestrator SSE (replace `setTimeout`) |
| Situation ticker | ✅ | shell → `GET /ticker` |
| Network brain / task fan | ✅ | Cockpit → `GET /tasks`, `/status` |
| Roster + status + tiers | ✅ | Agents/Cockpit → `GET /api/agents`, `/status` |
| Dossier (soul/model/plugins/memory) | ✅ | Agents → `GET /api/agents/{id}/soul`, `/memory/{id}` |
| Collab edges | ✅ | static `COLLAB` ok |
| Heartbeat feed (view) | ✅ | Cockpit → `GET /heartbeat/status` |
| Heartbeat **control** (run/start/stop) | ⚠️ | add to Agents/Admin → `POST /heartbeat/{id}/run|start|stop` |
| **Bench agents + promotion** (17 dormant) | ❌ | add Agents "bench" tab → `GET /learning`, `POST /learning/promote` |
| **Agent templates** (create agents) | ❌ | add Admin/Agents → `GET/POST /api/agent-templates` |

### Memory & Knowledge
| Capability | v2 | Home → endpoints |
|---|---|---|
| Stats + fused recall | ✅ | Memory → `GET /api/memory/search`, `/memory/stats` |
| **Bitemporal KG** + as‑of slider | ✅ | Memory → `GET /api/kg/*`, `/api/kg/facts/as-of`, `/history` |
| KG **edit** (entities/relations/facts) | ⚠️ | add edit affordances → `POST/DELETE /api/kg/*` |
| Topic decay → **forget** action | ⚠️ | Memory shows decay; add forget → `/api/memory/decay/*` |
| **Data Spaces (H10.26)** per‑agent read scope | ❌ | add Memory/Trust "data scope" tab → `/api/memory/spaces*`, `profile?agent=` |
| Memory **consolidation** | ❌ | add Autonomy/Memory → `POST /api/memory/consolidate` |
| **Local‑docs RAG** | ❌ | add Memory/Build → `GET /api/local-docs`, `/index` |
| Memory eval corpus/run | ❌ | Observe → `/api/memory/eval/*` |

### Trust · Security · Governance (the brand)
| Capability | v2 | Home → endpoints |
|---|---|---|
| Merkle **audit chain** | ✅ | Trust → `GET /api/admin/audit`, `/api/security/audit/*` |
| **Kill‑switch** | ✅ | Trust → `GET/POST /api/security/kill-switch` |
| **% local** meter | ✅ | Trust → compute‑locality telemetry / `/api/analytics/model-tiers` |
| Capability grants | ✅ | Trust → `/api/security/capabilities/{check,issue}` |
| **Governed payments lifecycle (H16.3)** | ⚠️ | Trust+Finance show ledger/chip only → wire full `/api/payments/*` (mandate/cap/approve/reject/settle) |
| **Secrets broker** | ❌ | add Trust → `/api/secrets/broker*` |
| **Prompt‑injection scan + spotlight** | ❌ | add Trust → `/api/security/scan-injection`, `/spotlight` |
| Security posture / governance summary | ⚠️ | Trust header → `/api/security/posture`, `/governance` |
| **Guardrails** WARN/REDACT/BLOCK config | ❌ | Admin/Trust setting → `security.guardrails_mode` |

### Autonomy
| Capability | v2 | Home → endpoints |
|---|---|---|
| Morning brief · observer · AUTO/ASK/OFF policies | ✅ | Autonomy → `/autonomy/brief`, `/observer`, `/autonomy/tasks` |
| Decision cards | ✅ | Cockpit → `/api/actions/*` |
| **Preference learning** ("learn to stop asking") | ❌ | add Autonomy → `/autonomy/preferences/suggestions` |
| Action **dry‑run / preview** | ❌ | add Autonomy → `POST /api/autonomy/preview` |
| **Escalation** flow | ⚠️ | metric only → add `/api/autonomy/escalate`, `/escalation/targets` |
| Nightly **reflection** | ❌ | add Autonomy/Observe → `/api/reflection/*` |

### Build (workflows · skills · sandbox)
| Capability | v2 | Home → endpoints |
|---|---|---|
| Workflow **DAG** + run | ✅ | Build → `/api/workflows*`, `/run`, `/hierarchical` |
| **AI step builder (H10.7)** | ❌ | add Build affordance → `POST /api/workflows/step/generate` |
| Skills marketplace (install) | ✅ | Build → `GET /api/skills/marketplace`, `/install` |
| **Marketplace signing + moderation (H12.12)** | ❌ | add signed/review badges + review action → `/marketplace/review`, list `signed`/`review_status` |
| **Code‑exec sandbox** | ❌ | add Build (proto "sandbox" is routing‑sim) → `POST /sandbox/execute` |

### Observe (eval · quality · arena · review)
| Capability | v2 | Home → endpoints |
|---|---|---|
| Quality · traces+stages · arena · latency · resilience | ✅ | Observe → `/api/traces`, `/api/quality`, `/api/arena/*`, `/api/resilience`, `/api/health/components` |
| **Eval datasets + regression runs** | ❌ | add Observe → `/api/eval/datasets*` |
| **Human review queue** | ❌ | add Observe → `/api/review/*` |
| Cost analytics dashboard | ⚠️ | add Observe/Trust → `/api/cost`, `/api/analytics/*`, `/api/admin/stats` |

### Interop
| Capability | v2 | Home → endpoints |
|---|---|---|
| A2A peers + signed Agent Card | ✅ | Interop → `/api/a2a/peers`, `/.well-known/agent-card` |
| **A2A approval inbox (H16.2)** | ❌ | add Interop → `/api/a2a/inbox`, `/inbox/{id}/decide` |
| MCP **clients** | ✅ | Interop → `/api/admin/mcp` |
| MCP **server mode** + token | ⚠️ | add Interop → `/api/mcp/server`, `/api/mcp/token` |
| Widgets (embeddable) | ✅ | Interop → `/api/admin/widgets`, `/api/widget/*` |
| Webhooks | ✅ | Interop → `/api/webhooks*` |

### Models · LLM control
| Capability | v2 | Home → endpoints |
|---|---|---|
| Local models list | ✅ | Admin → `GET /api/models/local` |
| LM Studio **load/unload/start** | ⚠️ | add Admin control → `POST /api/llm/server/start|load|unload` |
| Constrained decoding / grammar | ❌ (opt) | Admin (dev) → `POST /api/llm/grammar` |

### Admin · Settings
| Capability | v2 | Home → endpoints |
|---|---|---|
| Models · plugins · keys · channels · backups · host | ✅ | Admin → `/plugins`, `/plugins/{id}/toggle`, `/api/oauth/*`, `/api/admin/env` |
| **Runtime settings DB** (llm/memory/security/system/autonomy tunables) | ❌ | add Admin settings editor → `/api/admin/settings*` |
| **Prompt versioning / A‑B / diff / rollback** | ❌ | add Admin → `/api/admin/prompts/{id}/*` |
| Agent config edit | ⚠️ | Admin → `PUT /api/admin/agents/{id}` |
| Stats / APM | ⚠️ | Observe/Admin → `/api/admin/stats`, `/apm` |

### Life · Comms · misc
| Capability | v2 | Home → endpoints |
|---|---|---|
| Finance / Health / Knowledge / Family | ✅ | modes → balance · apple‑health · websearch · frigga (local) |
| Comms unified inbox (TG/email/WA/voice) | ✅ | Comms → channel adapters |
| **Notes** (+ AI rewrite) | ❌ | add Cockpit/Comms → `/api/notes*`, `/rewrite` |
| **Rooms** (multi‑agent chat rooms) | ❌ | add Chat/Comms → `/api/rooms*` |
| Schedule NL parse | ⚠️ | `/api/schedule/parse` |
| Voice / TTS / wake config | ⚠️ | Admin/Comms → `/api/voice/wyoming`, `/tts` |

**Tally:** ✅ ~22 areas have a surface (need wiring) · ⚠️ ~12 partial · **❌ ~18 must‑add surfaces.**
The ❌ list is the literal answer to "what would we miss" — and it's where our newest work sits.

---

## 4 · The "don't‑miss" shortlist (recent features, prioritized)

These are shipped, differentiating, and **absent** from the prototype — implement them as part of v2,
not "later":
1. **Memory Data Spaces (H10.26)** — per‑agent read‑scope governance → Memory/Trust.
2. **Signed + moderated marketplace (H12.12)** — the anti‑ClawHub trust metadata → Build.
3. **A2A approval inbox (H16.2)** — the inbound‑task safety gate → Interop.
4. **AI workflow step builder (H10.7)** — "describe the step" → Build.
5. **Governed‑payments lifecycle (H16.3)** — mandate/cap/approve/reject/settle → Trust+Finance.
6. **Autonomy preference‑learning** — "learn to stop asking" (north‑star) → Autonomy.
7. **Bench‑agent promotion + learning loop** — the 17 dormant agents → Agents.
8. **Full settings DB + prompt A‑B/rollback** — the real admin depth → Admin.

---

## 5 · Open decision: D2 build stack (your call)

| Option | Runtime needs | Pros | Cons |
|---|---|---|---|
| **A — No‑build (CDN), keep** | Python only | matches current app + local‑first; add `/v2` route + static files; hand‑editable | no types; manual `React.createElement`; no lazy‑load/tree‑shake |
| **B — Vite + React + TS** | Node to build (+ host if not committing bundle) | types over 228 endpoints; ES modules; lazy‑load 15 modes; standard tooling | adds Node toolchain + build to a pure‑Python repo; reverses "no npm build"; bundle in git or Node on host; heavier CI/self‑host |
| **C — Build offline, commit static** | Python only at runtime | types + bundling + lazy‑load **without** Node at runtime/self‑host | still need Node to *develop*; committed `dist/` diffs |

**Recommendation:** given `/v2`‑same‑server, **A** is least friction and most on‑pitch; choose **C** if
you want type‑safety + lazy‑loading at this scale without putting Node in the runtime. The plan below
is written to work with any of the three (only Phase 0 differs).

---

## 6 · Integration plan (staged; `/v2` same server)

Rollout target (your pick): the existing FastAPI app serves the new HUD at **`GET /v2`** with its own
static mount, alongside the current HUD at `/`. No cutover until parity is signed off. Each phase is
one reviewable PR.

- **Phase 0 — Scaffold `/v2` (depends on D2).** Bring the prototype into the repo (e.g.
  `agents/web/v2/` + `static/v2/`), add `GET /v2` + static mount in `web.py`, port `v2-style.css`,
  render with mock data. *(A→ port `.jsx`→`.js` React.createElement; B/C→ scaffold Vite/TS, port
  `v2-style.css` as‑is.)* Self‑host the fonts (Space Grotesk + JetBrains Mono) — no Google CDN.
- **Phase 1 — Live data adapter.** Replace `window.V2.*` with a `loadJarvisData()` that fetches the
  real endpoints; (TS: type the agent/dossier/trace/KG shapes). Wire the already‑known set first
  (`/api/agents`, `/status`, `/dashboard`, `/tasks`, `/ticker`). Handle 401/403 + degraded backend.
- **Phase 2 — Hero flows.** Cockpit chat over `/chat/stream` (token‑by‑token) + **real cognition
  stream** (SSE) keeping the 4‑stage visual; network from live `/tasks`.
- **Phase 3 — Wire the existing capability modes.** Trust, Memory, Autonomy, Build, Observe, Interop,
  Comms, Admin, Finance/Health/Knowledge/Family → their ✅ endpoints (§3).
- **Phase 4 — Add the ❌/⚠️ gap surfaces (the "miss‑nothing" gate).** Implement every ❌ row from §3
  into its home mode (Data Spaces, marketplace signing, A2A inbox, AI step builder, payments
  lifecycle, secrets broker, injection scan, guardrails, preferences, dry‑run, escalation,
  reflection, eval datasets, review queue, bench promotion, settings DB, prompt A‑B/rollback, agent
  templates, notes, rooms, local‑docs, code‑exec sandbox, MCP server, LM load/unload, cost). **Gate:
  the §7 parity checklist must be 100% before cutover is offered.**
- **Phase 5 — Settings & polish.** Replace `tweaks-panel.jsx` with real persisted prefs
  (accent/density/motion/lang/texture → `/api/admin/settings` or user prefs); a11y (keyboard nav for
  network + palette, ARIA on meters/dots); responsive < ~1100px; reduced‑motion JS + idle‑pause for
  the 24/7 wall display; deepen ambient mode.
- **Phase 6 — Cutover (only on your word).** Flip `/` → v2 (or keep `/v2` as opt‑in). Archive the old
  HUD. Update `STATUS.md`, `docs/ARCHITECTURE.md` filesystem map, `JARVIS.md` web‑endpoints.

Backend: reuse the 228 endpoints; add new ones only where a gap surface needs data (recipe:
`docs/ARCHITECTURE.md` §8). New polling endpoints → `_NO_STORE_PATHS`. Frontend tests go in
`tests/frontend/` (vitest harness already exists).

---

## 7 · "Nothing missed" acceptance gate

Before any cutover, a **parity checklist** maps **every one of the 228 endpoints** to one of:
(a) wired to a v2 surface, or (b) an explicit, signed‑off "not surfaced in HUD" list (e.g.
machine‑facing specs like `/api/memory/tool-spec`, `/.well-known/*`). Plus: all 8 §4 shortlist items
shipped; EN/RO parity; local‑first respected (frigga/ultron/howard never implied cloud; Family is
local‑only); zero console errors; offline shell intact.

---

## 8 · What I need from you to start

1. **D2 build stack** — A (no‑build), B (Vite/TS), or C (build‑offline/commit‑static). *(§5; rec A or C.)*
2. **Go / no‑go on this plan** — approve §6 and I start Phase 0; or tell me what to re‑scope.

*(Rollout `/v2`‑same‑server and "all capabilities surfaced" are already locked from your answers.)*
