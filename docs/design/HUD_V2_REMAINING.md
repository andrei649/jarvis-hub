# HUD v2 — Remaining work (next PR)

> What's intentionally **left out** of the P0–P6 build (PR #156 / merged to `main`) and queued for
> the next pass. **Update 2026‑06‑08: the cutover happened — V2 is the default HUD at `/`** (legacy
> at `/v1`, override `JARVIS_HUD=v1`); §8 below is done, the rest is the depth punch‑list.
> Companion: `HUD_V2_IMPLEMENTATION_PLAN.md`, `HUD_V2_COVERAGE_AND_PLAN.md`. Generated 2026‑06‑05;
> **re‑audited 2026‑06‑10** (see §10).

## 0. Do this first
- **Runtime verification.** Nothing was verified against a *running* backend (the build sandbox has
  no `fastapi`). Run `python serve.py` → open `/v2`, click **every mode + every Console (▦) panel**,
  and compare against `/` (v1) / known values. The **mock‑fallback** design hides wrong‑but‑not‑
  failing wiring (a bad field map shows seed data, not an error), so this pass is essential. File
  shape‑mismatch fixes as found.

## 1. Make real‑vs‑mock visible
- Surface the loader's existing `live` flag as a **● LIVE / ○ SEED** indicator (top bar + per‑panel),
  so it's obvious when a panel is showing seed data because its fetch failed.

## 2. Deepen the P4c Console panels (read/basic → full)
- **Settings DB**: read‑only category tree → full inline editor (toggle/slider/select/text per key,
  save `PUT /api/admin/settings/{cat}`). Reference: v1 `admin.js` `GlobalConfigPage`.
- **Prompt versions**: history list → full **A/B + diff + rollback + commit + preview** UI
  (`/api/admin/prompts/{id}/*`).
- **Data Spaces**: list → create / assign / unassign CRUD (`/api/memory/spaces*`).
- **Secrets**: list + delete → add a store form. **Capabilities**: add a grants list + check UI.
- **Rooms**: list → create + open history + send with `@mentions`.

## 3. Per‑mode live‑wiring depth
`api/live.ts` wires the headline data for Memory / Observe / Interop / Autonomy / Trust / Admin.
Still on mock (wire to endpoints; some need plugins configured):
- **Build**: workflow DAG + skills marketplace + sandbox → `/api/workflows`, `/api/skills/marketplace`.
- **Memory**: `RECALLS` / `TOPICS` / `KG` live (recall search, decay ranking, bitemporal KG as‑of).
- **Trust**: capability grants list; real `%‑local` meter (needs a locality/cost summary endpoint, §6).
- **Autonomy**: per‑agent AUTO/ASK/OFF **policies** (settings‑backed).
- **Comms**: live threads + **Discord + Slack** channels (exist in backend; not in the inbox yet).
- **Finance / Health / Knowledge / Family**: plugin‑backed (balance / apple‑health / websearch /
  frigga) — wire when those plugins are configured.
- **Dossier**: wire to `/api/agents/{id}/soul` + `/memory/{id}` + run history `/api/agents/{id}/history`
  (currently reads the `DOSSIER` mock).

## 4. Cockpit / signature interactions
- **Network task‑fan**: v2 `NetworkBrain` doesn't render per‑agent task dots from `/tasks` (v1 did) —
  add the task layer + live collab edges.
- **Per‑message TTS** (🔊 → `/tts`) + **browser mic / SpeechRecognition** input + voice auto‑speak
  (v1 had these; dropped in the port).
- ~~**Sentence-level TTS streaming** (H5.16)~~ ✅ **DONE (verified 2026‑07‑02)** — `voice.ts`
  `speak()` tries `streamTts` first (framed chunks played back-to-back, `voice.ts:206`) and falls
  back to whole-reply `/tts` on 409 when the server opt-in is off. *Remaining H5.16 tail lives in
  BACKLOG (synthesize mid-stream; browser wake-word).*
- **Streaming cognition**: P2 pulls the `/api/cognition` snapshot after the turn; upgrade to a real
  **SSE** stream (`/api/cognition/stream`, a backend addition) with live scores + redactions.
- **Strict‑local / mic trust badge** (H12.10): wire `/api/trust/status` into the top bar (endpoint
  exists; topbar edit deferred).

## 5. Settings / preferences UI
- The design‑only `TweaksPanel` was dropped. Accent + language persist (palette toggles), but
  **look / density / motion / scanline / dotgrid** aren't user‑changeable in‑app (defaults only) —
  add a small settings menu (or a gated tweaks panel) that changes + persists them.

## 6. Toolchain / CI hardening
- ~~**CI frontend‑build + stale‑bundle guard**~~ ✅ **EXISTS** — the `hud-v2-build` job in
  `.github/workflows/ci.yml` runs `npm ci` → `tsc --noEmit` → vitest → `vite build` and fails
  if the committed `agents/web/v2` differs from a fresh build. *(This line was stale — noticed
  2026‑06‑10 while re‑checking the punch‑list.)*
- **OpenAPI types**: generate `src/api/schema.ts` from `/openapi.json` (`openapi-typescript`) + add a
  `tsc` gate; optionally backfill `response_model=` on the ~30 consumed endpoints. (Most ported files
  are `// @ts-nocheck` — drop that as types land.)
- **Self‑host fonts**: vendor Space Grotesk + JetBrains Mono as woff2 (currently system‑font
  fallback — offline‑clean but off‑brand).
- **ESM cleanup**: the ported prototype files keep an `import { … } from './ui'` barrel + loose types;
  tighten to real per‑module imports + TS types over time.

## 7. Backend additions (from the plan §6)
- `GET /api/cognition/stream` (SSE) + provenance on the chat stream.
- ~~`GET /api/analytics/locality`~~ ✅ **DONE 2026‑06‑10** — computes %‑local from the run‑history route field; HUD Trust meter prefers it, falls back to strict‑local proof, never fabricates a split (`local_pct` null until real routed runs exist).
- Howard ingestion API — only if we ever surface the digital twin (currently `NOT_IN_HUD`).

## 8. Cutover (P6 follow‑through)
- Once verified, flip the default: `JARVIS_HUD=v2` (or hardcode) so `/` serves v2; keep `/v1` as the
  escape hatch; then archive the old `agents/web/` HUD and update `README` / `STATUS.md` / `JARVIS.md`.

## 9. Known infra issue (not a code fix)
- CI **`Analyze (python)` (CodeQL)** intermittently fails with *"Code scanning is not enabled for this
  repository"* — a repo **Settings → Code security** toggle (or GHAS availability), owner‑controlled.
  Unrelated to the HUD; `test` + `frontend` are green. Enable code scanning, or make that check
  non‑required.

## 10. Parity re‑audit — 2026‑06‑10 (backend moved ahead again)

The 2026‑06‑09 backend waves (PR #178/#180) shipped new surfaces **with no HUD controls**, on top of
the still‑open depth items above. Snapshot: backend ≈299 routes; HUD v2 actively calls ~50, partially
~10; **~37 write/recent endpoints lack any UI control**. New since the 2026‑06‑05 plan:

- `GET /api/cognition/stream` (SSE, NTH‑1 ✅ backend) — cockpit still polls the static snapshot (§4).
- Sender pairing gate (H12.19, 4 routes) — not in Comms.
- Cloud auth‑profile rotation (H12.20, `GET /api/llm/auth-profiles`) — not in Admin.
- Transcript → governed tasks (H12.25, `POST /api/transcripts/ingest`) — no surface.
- A2A approval inbox (H16.2 `/api/a2a/inbox*`), payments lifecycle actions (H16.3
  approve/reject/settle), marketplace review (H12.12) — read‑only or absent in Trust/Build.
- Still missing interactive controls (carried from §2–§4): preference‑learning suggestions,
  reflection run/status, bench promotion (`/learning/promote`), heartbeat start/stop/run, sandbox
  execute, prompt rollback/commit, Data Spaces CRUD, secrets store form, LM Studio model controls.

**Conclusion:** coverage gate still green (nothing silently dropped), but the *depth* gap regrew.
Tracked as **TASK‑2** in `BACKLOG.md`; estimated 3–5 PRs (~2–3 weeks part‑time) to "nothing missed".

### 2026‑06‑10 depth pass (same day, PR #181) — the control gap is CLOSED

All ~37 missing **write/recent controls** above now have live HUD surfaces (Console panels in
`frontend/src/gap.tsx` + Trust mode + cockpit):
cognition SSE stream (cockpit live trace) · payments approve/reject/settle (Trust) · sender
pairing approve/reject/block + code (H12.19) · injection scan (H17.1) · transcript→tasks ingest
(H12.25) · escalation targets+send (H12.11) · reflection status+run · heartbeat run/start/stop ·
bench promotion (`/learning/promote`) · marketplace review ✓/✕ (H12.12) · eval runs + compare ·
AI step builder (H10.7) · sandbox execute (DEV_MODE‑gated, honest 403) · agent templates
(H10.29) · LM Studio server/load/unload · cloud auth profiles (H12.20). Admin‑guarded calls now
send the admin token (`actA`). +7 frontend tests (19 total).

**Still open (the tail of TASK‑2, re‑verified 2026‑07‑03):** §3 plugin‑gated mode wiring
(Finance/Health/Knowledge/Family, Comms Discord/Slack threads) and §6 toolchain remainder
(OpenAPI types, self‑hosted fonts). Estimated 1–2 PRs.
*Since‑closed items previously listed here:* CI stale‑bundle guard ✅ (`hud-v2-build` in `ci.yml`),
§7 locality endpoint ✅ (`GET /api/analytics/locality`, consumed in `app.tsx`/`shell.tsx`), and the
BUG‑17 audit‑verify Trust chip ✅ (`modes.tsx:117-165` renders the live
`GET /api/security/audit/verify` verdict), the 0.39 saved‑watchlist `WatchlistPanel` ✅, and
per-panel LIVE/SEED chips ✅ (58/58 Console cards declare a `PanelChip` signal).

---
*Parity gate (`tests/test_hud_v2_parity.py`) tracks all routes → every one is mapped to a v2
surface or `NOT_IN_HUD`, so nothing above can silently disappear — these items are about depth, not
coverage.*

<!-- ci trigger: hud bundle refreshed -->
