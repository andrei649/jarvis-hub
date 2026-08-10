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
- ~~Surface the loader's existing `live` flag as a **● LIVE / ○ SEED** indicator (top bar + per‑panel).~~
  ✅ **DONE (verified 2026-07-04):** mode-level `LiveSourceChip` plus per-panel `PanelChip`
  make LIVE/SEED visible, and `panel-chip-coverage.test.ts` pins every Console card.

## 2. Deepen the P4c Console panels (read/basic → full)
- ✅ **Ambient Watch (H33.6):** the Home cluster now reads the redacted live ambient runtime,
  showing monitor/source health, last policy decision, rung counts, and the single global
  attention budget. Monitor administration remains in the separately authenticated admin API;
  event content, subjects, predicates, recipients, and delivery ids are never rendered.
- ✅ **Settings DB**: full inline editor (toggle/slider/select/text per key) saves through
  `PUT /api/admin/settings/{cat}` in `SettingsPanel`.
- ✅ **Prompt versions**: `PromptsPanel` has A/B, diff, rollback, edit, preview, and commit controls
  over `/api/admin/prompts/{id}/*`.
- ✅ **Data Spaces**: list/create/delete plus assign/unassign controls are live in `DataSpacesPanel`
  over `/api/memory/spaces` and `/api/memory/spaces/{assign,unassign}`.
- ✅ **Secrets / Capabilities**: the secret store form is live in `SecretsPanel`, and
  `CapabilitiesPanel` can issue tokens, keep recent grants visible, and check a
  token/capability pair through `GET /api/security/capabilities/check`.
- ✅ **Capability Registry**: `ReadinessPanel` reads canonical `GET /api/capabilities` and
  shows readiness, risk, supports, and confidence without fabricating verification.
- ✅ **Rooms**: create + send with `@mentions` are live in `RoomsPanel`, and the selected-room
  history drawer reads `GET /api/rooms/{id}/history`.

## 3. Per‑mode live‑wiring depth
`api/live.ts` wires the headline data for Memory / Observe / Interop / Autonomy / Trust / Admin.
PR #505 adds base LIVE/SEED gates for Build / Comms / Finance / Health / Knowledge / Family,
with plugin-configured checks instead of seeded success. Still open:
- **Build**: base live wiring reads workflow DAG + skills marketplace + sandbox from
  `/api/workflows`, `/api/skills/marketplace`, and `/sandbox/status`; deeper create/edit affordances
  remain in the Console panels.
- **Memory**: `RECALLS` / `TOPICS` / `KG` live (recall search, decay ranking, bitemporal KG as‑of).
- **Trust**: real `%‑local` meter (needs a locality/cost summary endpoint, §6).
- **Autonomy**: per‑agent AUTO/ASK/OFF **policies** (settings‑backed).
- **Comms**: rooms + registered **Discord/Slack** channel status now feed the mode. The Console now
  has a Safe Comms draft surface over `GET/POST /api/integrations/social`, so X post/reply/DM drafts
  enter the existing approval queue/preview path instead of sending directly. #551 adds
  channel inbox transport v0 for telegram/web: inbound threads persist through
  `GET /api/channels/inbox*`, live rows show a governed reply composer, and replies queue through
  `POST /api/channels/inbox/{thread_id}/reply` before approved sends use the live channel manager.
  Email/WhatsApp inbox transport remains deferred until their live send seams are proven.
- **Finance / Health / Knowledge / Family**: base mode switching is plugin-gated. Finance reads saved
  watchlist/payments and keeps `balance` mock payloads as SEED; Health waits for the Apple Health LAN
  bridge; Knowledge waits for configured websearch backend; Family waits for WhatsApp bridge/frigga
  live data.
- **Dossier**: wire to `/api/agents/{id}/soul` + `/memory/{id}` + run history `/api/agents/{id}/history`
  (currently reads the `DOSSIER` mock).

## 4. Cockpit / signature interactions
- ~~**Network task‑fan**: v2 `NetworkBrain` doesn't render per‑agent task dots from `/tasks` (v1 did) —
  the old task fan exists in `network.tsx`, but the current cockpit renders `NeuralMesh`; integrate
  live `/tasks` dots into the current mesh or retire the stale `NetworkBrain`.~~
  ✅ **DONE (2026-07-04, #521):** `app.tsx` passes the existing live `/tasks` state into
  `NeuralMesh`, which renders honest task spokes/dots plus a visible task count; empty or
  unknown-owner queues render no invented fan.
- ~~**Per‑message TTS** (🔊 → `/tts`) + **browser mic / SpeechRecognition** input + voice auto‑speak.~~
  ✅ **DONE (verified 2026-07-04):** `cockpit.tsx` renders per-message replay via `playTts`,
  `InputBar` toggles the `useVoice` loop, and `app.tsx` wires mic → local STT → turn → speak.
- ~~**Sentence-level TTS streaming** (H5.16)~~ ✅ **DONE (verified 2026‑07‑02)** — `voice.ts`
  `speak()` tries `streamTts` first (framed chunks played back-to-back, `voice.ts:206`) and falls
  back to whole-reply `/tts` on 409 when the server opt-in is off. *Remaining H5.16 tail lives in
  BACKLOG (synthesize mid-stream; browser wake-word).*
- ~~**Streaming cognition**: upgrade to a real SSE stream.~~ ✅ **DONE (verified 2026-07-04):**
  `app.tsx` subscribes to `/api/cognition/stream` and maps cognition frames into the cockpit trace.
- ~~**Strict-local / mic trust badge** (H12.10).~~ ✅ **DONE (verified
  2026-07-04):** `shell.tsx` renders strict-local and mic-muted badges from the live trust payload.

## 5. Settings / preferences UI
- ~~The design‑only `TweaksPanel` was dropped. Accent + language persist (palette toggles), but
  **look / density / motion / scanline / dotgrid** aren't user‑changeable in‑app (defaults only) —
  add a small settings menu (or a gated tweaks panel) that changes + persists them.~~
  ✅ **DONE (2026-07-04, #523):** the command palette now exposes look, density
  (compact/normal/comfy), motion (lively/calm), scanline, and dotgrid controls; all are
  client-side HUD preferences persisted by `App`.

## 6. Toolchain / CI hardening
- ~~**CI frontend‑build + stale‑bundle guard**~~ ✅ **EXISTS** — the `hud-v2-build` job in
  `.github/workflows/ci.yml` runs `npm ci` → `tsc --noEmit` → vitest → `vite build` and fails
  if the committed `agents/web/v2` differs from a fresh build. *(This line was stale — noticed
  2026‑06‑10 while re‑checking the punch‑list.)*
- ~~**OpenAPI types**~~ ✅ **DONE 2026-07-03** — `frontend/src/api/schema.gen.ts` is generated from
  the live FastAPI `/openapi.json` via pinned `openapi-typescript`; CI boots the backend,
  regenerates, and fails on a schema diff. Consumer migration remains gradual by design.
- ~~**Self‑host fonts**~~ ✅ **DONE (2026-07-04, #525):** HUD v2 now vendors
  local Latin-variable WOFF2 assets for Space Grotesk + JetBrains Mono and loads them
  through `@font-face` in `frontend/src/styles.css`; runtime font-network dependency is removed.
- **ESM cleanup**: the ported prototype files keep an `import { … } from './ui'` barrel + loose types;
  tighten to real per‑module imports + TS types over time.

## 7. Backend additions (from the plan §6)
- ~~`GET /api/cognition/stream` (SSE)~~ ✅ **DONE** and consumed by the cockpit. Provenance on the
  chat stream is already surfaced via the existing provenance chip/modal.
- ~~`GET /api/analytics/locality`~~ ✅ **DONE 2026‑06‑10** — computes %‑local from the run‑history route field; HUD Trust meter prefers it, falls back to strict‑local proof, never fabricates a split (`local_pct` null until real routed runs exist).
- Howard ingestion API — only if we ever surface the digital twin (currently `NOT_IN_HUD`).

## 8. Cutover (P6 follow‑through)
- Once verified, flip the default: `JARVIS_HUD=v2` (or hardcode) so `/` serves v2; keep `/v1` as the
  escape hatch; then archive the old `agents/web/` HUD and update `README` / `STATUS.md` / `NERVA.md`.

## 9. Known infra issue (not a code fix)
- CI **`Analyze (python)` (CodeQL)** intermittently fails with *"Code scanning is not enabled for this
  repository"* — a repo **Settings → Code security** toggle (or GHAS availability), owner‑controlled.
  Unrelated to the HUD; `test` + `frontend` are green. Enable code scanning, or make that check
  non‑required.

## 10. Parity re‑audit — 2026‑06‑10 (backend moved ahead again)

The 2026‑06‑09 backend waves (PR #178/#180) shipped new surfaces **with no HUD controls**, on top of
the still‑open depth items above. Snapshot: backend ≈299 routes; HUD v2 actively calls ~50, partially
~10; **~37 write/recent endpoints lack any UI control**. New since the 2026‑06‑05 plan:

- `GET /api/cognition/stream` (SSE, NTH‑1 ✅ backend) — ✅ consumed by the cockpit trace.
- Sender pairing gate (H12.19, 4 routes) — not in Comms.
- Cloud auth‑profile rotation (H12.20, `GET /api/llm/auth-profiles`) — not in Admin.
- Transcript → governed tasks (H12.25, `POST /api/transcripts/ingest`) — no surface.
- A2A approval inbox (H16.2 `/api/a2a/inbox*`), payments lifecycle actions (H16.3
  approve/reject/settle), marketplace review (H12.12) — read‑only or absent in Trust/Build.
- Still missing interactive controls (carried from §2–§5): preference-learning suggestions.

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

**Still open (the tail of TASK‑2, re‑verified 2026‑07‑05):** O26-P3.1 closes the §3 plugin-gated
base wiring in #505 (Build/Comms/Finance/Health/Knowledge/Family), and the Safe Comms draft panel (#527)
closes the draft-before-send UI over existing governed social actions. #551 adds
channel inbox transport v0 for telegram/web. Remaining:
owner live-data/plugin setup (bank/broker/quotes, Apple Health bridge, websearch backend, WhatsApp
bridge/frigga live data) and non-v0 inbox channels.
Estimated 1–2 PRs after #505 for owner-gated/plugin work.
*Since‑closed items previously listed here:* CI stale‑bundle guard ✅ (`hud-v2-build` in `ci.yml`),
§7 locality endpoint ✅ (`GET /api/analytics/locality`, consumed in `app.tsx`/`shell.tsx`), and the
BUG‑17 audit‑verify Trust chip ✅ (`modes.tsx:117-165` renders the live
`GET /api/security/audit/verify` verdict), the 0.39 saved‑watchlist `WatchlistPanel` ✅, and
per-panel LIVE/SEED chips ✅ (58/58 Console cards declare a `PanelChip` signal). Data Spaces
assign/unassign controls ✅. Rooms selected-history drawer ✅. Capability issue/check UI ✅.
Current-mesh task fan ✅. Preferences/tweaks UI ✅. Self-hosted fonts ✅. Safe Comms draft UI ✅ (#527).
Safe Comms channel inbox transport v0 ✅ (#551).
O26-P3.2 adds a Vitest reconciliation guard so this document cannot re-list shipped
TTS/mic/cognition/trust or Console controls as missing.

**O29 Media Director (2026-07-13):** the default-off `/api/media/*` device, session, present,
and restore surface is live in the Console Build cluster. `MediaDirectorPanel` separates the
read board, explicit user presentation/restore controls, and admin-authenticated registry
controls; queued approval, kernel refusal, nested `output.ok=false`, and driver-verified success
are rendered as distinct outcomes. The panel displays bounded metadata only and never embeds
remote media. `tests/test_hud_v2_parity.py` pins every Director route to the live Build surface.

**H30.5 House Brain (2026-07-13):** the default-off `/api/house/*` surface is live in the new
Console Home cluster. `HousePanel` renders bounded topology and pseudonymous presence, pauses
controls whenever live Home Assistant state is unavailable, and exposes only narrow governed
light/climate/security proposals. Security proposals remain visually distinct and use an
admin-authenticated two-step challenge bound to the durable task; success is never shown for a
queued, denied, or unverified outcome. Native mobile parity is read-first with an Approvals handoff
and intentionally has no security confirmation shortcut. The HUD parity gate pins every user route
to the Home surface.

**H31.5 Camera Intelligence (2026-07-13):** the default-off `/api/cameras/*` surface is live in
the Home cluster. `CameraPanel` shows only bounded time/type/camera/zone/confidence metadata and
optional strict-local description provenance, with deterministic temporal search. It creates no
image/video/embed or private media request. Admin-authenticated ONVIF discovery is onboarding-only;
native parity covers status, recent events, and private-body search without an admin shortcut.

**H32.6 Capability Acquisition (2026-07-13):** the default-off `/api/acquisition/*` surface is
live in the Build cluster. `AcquisitionPanel` separates user-readable lifecycle/reuse/package and
hash-only audit state from the admin-authenticated revoke, rollback, export, and exact-confirmation
purge controls. It never renders request goals, source extracts, receipt bodies, package paths, or
full correlation hashes. Native parity is deliberately read-only over the same bounded user APIs.

**H28.4 Operator depth (completed 2026-07-14):** Console → Build now hosts a dedicated
`OperatorPanel` over the four existing browser check/plan-preview and desktop preview/run routes;
no route or governance bypass was added. Browser policy and plan checks are dry-run only and expose
no Run control. Desktop submission is preview-first: editing invalidates the preview, and submit
uses the deep-cloned canonical snapshot. The result reducer distinguishes proposed, queued,
blocked, failed, partial, and executed outcomes, with an explicit warning against whole-plan retry
after partial execution. Native mobile hides `toolrpc.desktop_run` payloads and omits Approve while
retaining Reject/Defer. Evidence: `operator-contract.test.ts`, `operator-panel.test.tsx`,
`gap-panels.test.tsx`, `approvalsDesktopBoundary.test.ts`, and the strengthened
`tests/test_hud_v2_parity.py` caller gate.

**H34.1 Mission Control (2026-07-24):** the swarm cockpit ships as a **standalone
brain.html-pattern page** at `/mission-control` (self-contained dark HUD; polls the new read-only
`GET /api/swarm/summary`; steering reuses the existing governed autonomy/missions/A2A endpoints
with the shared `hud.admin_token`). Both routes are mapped to `observe` in the parity RULES.

**H34.4 SwarmPanel (2026-08-10, done):** a React `SwarmPanel` inside Console → Observe reads the
same `GET /api/swarm/summary` feed read-only — kernel halt/armed status, the autonomy funnel,
workspace counts (missions/workflow runs/sub-agents), the A2A inbox when enabled, and which
dev-swarm agent (`claude`/`codex`/`opencode`/`antigravity`) currently holds a `lock.py` lock — then
links out to the standalone `/mission-control` page for the full HITL controls. Zero new backend
route; the cockpit is now one keystroke from chat, and the standalone page stays either way.

---
*Parity gate (`tests/test_hud_v2_parity.py`) tracks all routes → every one is mapped to a v2
surface or `NOT_IN_HUD`, so nothing above can silently disappear — these items are about depth, not
coverage.*
