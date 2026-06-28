# Review Queue — manual-testing + product-review checklist

> The running log of everything shipped during the autonomous run that needs your eyes.
> Walk this top-to-bottom during the full manual-test / product-review pass. The codebase
> is green and merged at every step; this is about the things automated checks **can't**
> prove.

## How each item is verified

- **Automated, every PR (gates the merge):** `pytest` (full suite), `ruff`, the
  route/action/capability **auth-matrices**, OpenAPI/route parity, SAST (bandit/semgrep) +
  secret-scan (gitleaks), hash-pinned deps.
- **Scratch simulation (where possible):** I also boot the app and hit real endpoints — and
  load HUD pages headless in a real browser (Chromium/Playwright) — in a throwaway scratch
  dir (never committed) to catch obvious runtime bugs. Noted per item.
- **⚠️ NEEDS YOU:** real LLM / real channel / live HUD pixels / GPU / owner secrets — the
  things only a human + real hardware can confirm.

## Owner-only — I cannot do these (also in `docs/OWNER_TASKS.md`)

- GPU runs — 0.18 Howard fine-tune / speculative decoding.
- Publishing — PyPI / Docker / GPG-signing (your secrets).
- Recruiting design partners; GitHub settings (branch protection, CodeQL enablement).

## Conventions

- **Risky/new behavior ships behind a default-off flag** (e.g. `JARVIS_ACTION_KERNEL`) so it
  changes nothing at runtime until you enable it during testing.

---

## Items (newest first)

### HUD — type `shell.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `shell.tsx` (topbar, rail/tabs nav, ticker, right context column,
  ambient, palette). 9 errors, two patterns, both type-only:
  - the `MODES` nav array reads `m.locked` — a **forward-looking "soon"-disable flag** (the rail/tabs gray
    out and block locked modes) that **no MODES item currently sets**. Annotated the array element type with
    optional `locked?` (plus the other optional `id/icon/tkey/live/sep`) so the defensive read is honest.
  - the shared `Meter` primitive required `unit`, but 3 callers (the topbar gauges) omit it — and `Meter`
    renders `{unit||'%'}`, so it's optional. Marked it optional at `Meter`'s def in `primitives.tsx` (one
    cross-file fix, same shape as the `Icon` fix in #384).
  1 non-test source module remains on `@ts-nocheck` (the last one: `gap.tsx`).
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `app.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `app.tsx` (the root composition — state, the streaming-turn loop,
  the layout). The most complex slice; 11 errors → 5 root type-only fixes (bundle byte-identical):
  - `messages` state was inferred as a narrow 2-shape literal union, so the optimistic-update callbacks
    didn't type-match → `useState<any[]>` (clears 3 cascading `SetStateAction` errors at the source).
  - the `seq` staged-timer array was widened from `[number, fn]` tuples to a union, breaking `setTimeout` →
    annotated `Array<[number, () => void]>`.
  - `mark()`'s trailing `j, jstate` are optional (the body guards `j !== undefined`) → `j?, jstate?`.
  - `cog` from `apiGet('/api/cognition')` → `: any` boundary.
  - **a small dead-code find:** `const ia = 'rail'` is hardcoded, so the `ia === 'tabs'` (Tabs-layout)
    branch is unreachable. Typed it `'rail' as 'rail' | 'tabs'` so the comparison is valid **without
    changing behaviour** — Tabs stays unrendered exactly as today.
  2 non-test source modules remain on `@ts-nocheck` (the last two: `shell`/`gap`).
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you (informational, not a bug):** the **tabs information-architecture** is dead code — `ia`
  is pinned to `'rail'`, so the alternative `<Tabs>` top-nav layout (imported from `shell.tsx`) never
  renders. It was evidently an A/B layout that got fixed to the rail. No action needed for the typing pass;
  flagging in case you want to either wire `ia` to a real preference (and offer tabs again) or delete the
  dead `<Tabs>` path in a future cleanup.

### HUD — type `modes.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes.tsx` (Agents / Trust / Memory modes). 9 errors, all type-only:
  - three **API-response boundaries** — `decidePayment`, `setKillSwitch`, `memorySearch` all return
    `Promise<unknown>`; annotated their `.then`/`.map` callback params `: any` (the same arbitrary-backend-JSON
    boundary `live.ts` uses).
  - the **PAYMENTS-seed `.id` drift** (same shape as the plugin-registry case in #392): the payments ledger
    seeds from `V2.PAYMENTS` with no `id`, but `live.ts` swaps in real broker payments *with* `id`, and the
    approve/reject/settle lifecycle buttons render only when it's present (`{p.id && p.state==='pending' && …}`).
    Typed the map element with optional `id?` so the seed/live duality is honest.
  3 non-test source modules remain on `@ts-nocheck` (the last three: `app`/`shell`/`gap`).
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `modes3.tsx` + relax the `InputBar` contract (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes3.tsx` (Chat / Comms / Admin modes) — the richest mix in the
  sweep so far, 8 errors across 4 distinct patterns, **all type-only** (bundle byte-identical):
  1. `SubH3` — the recurring local-header optional-`style` fix.
  2. **`InputBar` contract** — modes3's distraction-free `ChatMode` renders `<InputBar>` *without*
     `voice/cfg/onCfg/micMuted`, which `InputBar` already guards (`voice && …`) but were inferred as
     required. Relaxed them to optional at `InputBar`'s definition in **`cockpit.tsx`** (one cross-file
     follow-up that unblocks any minimal InputBar caller).
  3. **plugin-registry `id` drift** — the Admin plugin list seeds from `V2.ADMIN.plugins` (no `id`), but
     `live.ts` swaps in the real registry *with* `id`, and the toggle handler keys off it
     (`if(!p.id) return` → demo rows flip locally; real rows POST `/plugins/{id}/toggle`). Typed the state
     with optional `id?` so the seed/live duality is honest.
  4. `togglePlugin`'s `Promise<unknown>` response → `: any` at the read boundary (codebase-consistent).
  4 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `modes4.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes4.tsx` (the Finance / Health / Knowledge / Family agent-home
  modes). All 8 errors were the same optional-prop fix: the local `SubH4` **already renders `style={style}`
  correctly** (no dropped-style drift, unlike modes2's `SubH`), it was merely inferred as *requiring*
  `style` while 8 callers omit it. One-line `{ children?: any; style?: any }`. Type-only; bundle
  byte-identical. 5 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `cockpit.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `cockpit.tsx` (the conversation + cognition-trace + input column).
  A clean **root-cause** fix: `buildTrace()` built its per-agent routing scores into an untyped `{}`
  accumulator, so `Object.entries(agentScore)` typed every value as `unknown` — which then broke the
  `.sort((a,b)=>b.v-a.v)`, the `s.v>=0.6` / `conf<0.6` comparisons, and the `scored[0].win=true` flag
  (5 errors, all the same origin). Typed the accumulator `Record<string, number>` and widened the
  scored-element type to carry the optional `win`. Type-only; bundle byte-identical. 6 non-test source
  modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only (the cognition trace is a deterministic client-side
  demo built from the seeded `COGNITION_SCORING`; no behaviour change).

### HUD — type `modes2.tsx` + fix a dropped-style drift ⚠️ FIRST VISUAL CHANGE (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes2.tsx` (the Autonomy / Build / Observe / Interop modes).
  Stripping it exposed a real **dropped-style bug**: this file's *local* `SubH` was
  `function SubH({ children })` rendering `<div className="sub-h">{children}</div>` — it accepted **no**
  `style` prop, yet **6 secondary section headers** pass `style={{marginTop:16}}` (or `14`):
  OBSERVER LOG, PER-AGENT SCOPE, MODEL ARENA, RESILIENCE, MCP SERVERS, WEBHOOKS. The margin was silently
  discarded. The **sibling `SubH` in `world-intelligence.tsx` renders `style={style}`** and applies the
  identical `marginTop:16` for the identical purpose — so modes2's headers have been missing the app-wide
  spacing the rest of the HUD uses. I made modes2's `SubH` match (`{ children, style }` → `style={style}`).
  Also narrowed `setAutonomyMode(m)`'s `Promise<unknown>` result where `.mode` is read (type-only).
- **⚠️ NEEDS YOU — this is the FIRST slice that changes the rendered bundle.** It adds ~16px top-margin to
  those 6 section headers in the Autonomy/Observe/Interop panels. **Eyeball those panels** to confirm the
  extra spacing looks right (it should — it matches how the same headers already render in the World
  Intelligence panel). If you'd rather keep them tight, it's a one-line revert (drop `style={style}` from
  modes2's `SubH`). Low-risk: the change brings modes2 *into consistency* with the rest of the app, it
  doesn't invent new styling.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `npm run build` rebuilt the
  bundle (new hash `index-C6ME69L3.js`, deterministic) — committed so the `hud-v2-build` parity guard
  matches. No backend/route change.

### HUD — type `voice.ts` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `frontend/src/voice.ts` (the browser-side hands-free voice loop:
  mic capture → VAD segmentation → `/api/voice/stt` → chat turn → server `/tts` playback with a
  `speechSynthesis` fallback). First file in the sweep with **substantive** type errors rather than the
  optional-prop pattern. Five fixes, **all type-only** (bundle byte-identical):
  1. `useVoice({ … onTurn })` — the `onTurn` callback was destructured but missing from the inferred
     options type; annotated the options shape.
  2. `tok(extra?)` — header helper with an `extra||{}` fallback, called once with no args; marked optional.
  3. `window.webkitAudioContext` — Safari/legacy `AudioContext` fallback; typed cast (not `any`).
  4. `new Blob([frame.audio])` — the TS-5.7 `Uint8Array<ArrayBufferLike>` → `BlobPart` lib quirk; cast.
  5. the `streamTts` `onFrame` callback returned `Promise<unknown>` vs the expected `Promise<void>|void`
     — `streamTts` **awaits** `onFrame` to keep sentence-by-sentence playback **in order**, so I
     cast-preserved the returned promise rather than dropping it (dropping it would desync playback).
  8 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed** (incl. `ttsStream.test`);
  `agents/web/v2` bundle **byte-identical**. No backend/route change.
- **⚠️ Needs you:** the voice loop is **typecheck/build-verified only** — live mic + audio playback need a
  real browser + device a headless CI can't provide (this was already the file's documented stance). A
  one-time hands-free smoke test on real hardware confirms the loop end-to-end; the typing change here is
  purely compile-time and behaviour-identical (playback ordering explicitly preserved — see fix #5).

### HUD — type `world-intelligence.tsx` + `modes_world.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from the WorldView pair — `world-intelligence.tsx` (the Signal-Layer
  intelligence panel: brief, top signals, recommendations, provider health) and `modes_world.tsx` (the mode
  wrapper that mounts it). Batched because they're one feature. `world-intelligence.tsx` hit the **same
  optional-prop pattern** as the `Icon` fix: a local `SubH({ children, style })` renders `style={style}`
  (an `undefined` style is a no-op in React), so `style` is optional — two call sites omit it. Marked it
  optional. `modes_world.tsx` needed **zero** changes — its earlier errors were all downstream of the
  `Icon` contract gap fixed in #386, so stripping the directive was enough. 9 non-test source modules remain.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical** (rebuilt to confirm — `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** the World Intelligence overlay (press `W` in the HUD) reads the optional external
  Signal-Layer service on `:8787` — its live data path is owner-runtime-gated like every panel, but the
  typing change here is compile-time only and behaviour-identical.

### HUD — type `world_app.tsx` + fix the `Icon` optional-props contract (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `frontend/src/world_app.tsx` (the "World Intelligence" overlay shell —
  the `W`-key fullscreen panel that wraps `<App/>` and mounts `WorldIntelligenceMode`). The two tsc errors it
  surfaced were a real **contract gap** in the shared `Icon` primitive (`primitives.tsx`): `Icon` is
  `function Icon({ d, size, sw })` where `size`/`sw` both have runtime fallbacks (`size||16`, `sw||1.6`) —
  genuinely optional — but once `primitives.tsx` was type-checked (PR #384), TS inferred all three params as
  *required*, so any caller omitting `sw`/`size` (which is most of them) failed. Marked `size`/`sw` optional
  in `Icon`'s signature — the honest contract. This is a **one-line fix that unblocks every `Icon` caller
  across the HUD**, not just `world_app`. Type-only, so the bundle is byte-identical.
  11 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical** (rebuilt to confirm — `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only. (`Icon` rendering is unchanged; the fix only relaxes the
  *type*, the runtime already defaulted `size`/`sw`.)

### HUD — type `network.tsx` + remove a dead `_wrap` write (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `frontend/src/network.tsx` (the agent-mesh "network brain"
  visualizer). The one tsc error it surfaced was a real **dead write**: `NetworkBrain._wrap = el` — a
  `ref` callback stashing the wrapper DOM node onto the component *function object*, never read anywhere
  in the codebase (grep-confirmed across `src/`). Removed the whole dead `ref` callback rather than papering
  over it with a cast — that dead-wiring is exactly the drift CDX-9 exists to catch. The production
  minifier had **already** eliminated the write, so the bundle is byte-identical despite the source change.
  12 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical** (`index-CwY1ye9O.js`, rebuilt to confirm — `hud-v2-build` guard matches). No
  backend/route change.
- **⚠️ Needs you:** glance at the agent-network panel once (it renders the orbiting agent mesh) to confirm
  it still draws — purely to double-check the removed `ref` truly had no effect (it shouldn't; nothing read
  it). Compile-time + behaviour-identical otherwise.

### HUD — type the `data.ts` keystone + leaf modules (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from the **keystone** `frontend/src/data.ts` (the pure `V2` seed object
  every capability mode reads via `V2.<KEY>`) plus its barrel `ui.ts`, the shared `primitives.tsx` UI
  symbols, and `LiveSourceChip.tsx`. Typing `data.ts` is the unblock: the big components read off `V2`, so
  they couldn't be type-checked until the seed's own shape compiled clean. These 4 came off with **zero**
  added annotations — the literals/JSX already inferred correctly. 17→13 non-test source modules on
  `@ts-nocheck` (remaining: `app`/`shell`/`gap`/`cockpit`/`modes`/`modes2-4`/`modes_world`/`voice`/
  `network`/`world-intelligence`/`world_app`, to be done smallest-tsc-error-first, each its own PR).
- **Verified (automated):** `tsc --noEmit` clean; full frontend **vitest 73 passed** (unchanged — types
  erase, behaviour-identical); `agents/web/v2` bundle **byte-identical** (`index-CwY1ye9O.js`, rebuilt to
  confirm — the `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only.

### HUD — type the whole api/ data layer (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from **all** of `frontend/src/api/` — `actions.ts`, `signalLayer.ts`,
  and `live.ts` — so the entire HUD data layer is now type-checked. `actions.ts` declares response
  interfaces (`NorthStarMetrics`, `KillSwitchState`, `AuditVerifyResult`, `PluginList`, …) threaded
  through the client's existing `apiGet<T>` generic, so a backend shape change is caught at the call
  boundary (the core CDX-9 "live-wiring hides shape drift" complaint). `signalLayer.ts` got a typed
  `WorldIntelligence` return + a `PromiseRejectedResult` guard. `live.ts` keeps `any` only at its genuine
  heterogeneous ingestion points (varied backend shapes normalized onto `V2` before render — tightening
  those wants `data.ts` typed first). 22→19 source modules on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; full frontend **vitest 73 passed** (unchanged — types
  erase, so it's behaviour-identical); `agents/web/v2` bundle is **byte-identical** (no rebuild needed —
  the `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only. The big HUD components (`app.tsx`/`gap.tsx`/`modes*.tsx`)
  remain on `@ts-nocheck`; those are the heavier, incremental follow-ups (each its own PR).

### Security — cover the audit-log query/read path (coverage hardening)
- **What:** `security/audit.py` `query()` — the read path the admin audit page uses to reconstruct
  `SecurityEvent`s (incl. findings) from the tamper-evident chain — was **untested** (81% file). Added a
  round-trip test (log → query, newest-first, findings reconstructed with the right type/threat/offsets)
  and a filter test (`event_type` / `since` / `limit`). The round-trip also **re-confirms AUD-12**: the
  stored `matched_text` comes back as the `[REDACTED:<pattern>]` marker, never the raw secret.
- **Verified (automated):** `tests/test_audit_hardening.py` (+2) — covers audit.py lines 134-169. Full
  suite **3,036 passed**; `ruff` + `bandit` clean. No behaviour change.
- **⚠️ Needs you:** nothing — offline coverage hardening of an already-correct read path.

### Security — cover the guardrails scan/redact/block + streaming path (coverage hardening)
- **What:** `security/guardrails.py` (the LLM-call wrapper that scans prompts/responses for secrets &
  PII) was 77% covered — the **entire `generate_stream` path was untested**, along with the system-prompt
  scan and the redact/block-on-finding branches. Added tests that drive a real finding (an email PII)
  through **REDACT** (input + system + output all scrubbed) on both `generate` and `generate_stream`,
  assert **BLOCK** raises `SecurityBlockError`, and cover the defensive unknown-mode passthrough.
- **Verified (automated):** `tests/test_guardrails_generate_kwargs.py` (+4) — covers guardrails.py lines
  68/80/99-120. The existing kwarg tests only ran WARN-mode passthrough; these exercise the parts that
  actually act on a finding. Full suite **3,034 passed**; `ruff` + `bandit` clean. No behaviour change.
- **⚠️ Needs you:** nothing — offline coverage hardening of an already-correct redaction path.

### Security — pin the SSRF IPv6-mapped/embedded-IPv4 bypass defense (coverage hardening)
- **What:** `security/ssrf.py` was the lowest-covered file in the safety-critical core (85%) — and the
  uncovered branches were exactly the **IPv6-mapped / embedded-IPv4 unwrap** logic (`::ffff:a.b.c.d`,
  `::a.b.c.d`), the notation attackers use to wrap `169.254.169.254` / `127.0.0.1` / RFC1918 in IPv6 and
  slip past a naive host filter. I **scratch-simulated** every bypass first to confirm the filter actually
  blocks them (it does — no bug; mapped-public still passes), then added tests that **pin** that property
  so a future refactor can't silently reopen the hole.
- **Verified (automated):** `tests/test_ssrf.py` (+5) — `is_private_ip` unwraps mapped loopback/metadata/
  RFC1918 (and the deprecated `::a.b.c.d` form) → blocked, mapped-public → allowed, garbage → False;
  `resolve_and_validate` + `check_ssrf` block bracketed-IPv6 metadata/private URLs; empty `getaddrinfo`
  fails closed. Covers ssrf.py lines 38/41/47-48/52/80-82/98-99. Full suite **3,030 passed**; `ruff` +
  `bandit` clean.
- **⚠️ Needs you:** nothing — pure offline security-coverage hardening; behaviour unchanged (it was already
  correct, just untested).

### HUD — visible LIVE/SEED chip per mode (CDX-9 slice)
- **What:** the HUD modes stream real backend data when a source responds and fall back to a seeded mock
  otherwise — but nothing told you which, so live-wiring quietly hid shape drift. A new `LiveSourceChip`
  (driven by a pure `liveSourceState()` over the existing `useLiveModes()` live-map + the demo flag) now
  labels each mode **LIVE** (green, real backend) / **SEED** (amber, demo/mock) / hidden (mode has no
  backend source or nothing's showing). Rendered once at the workzone in `app.tsx`.
- **Verified (automated):** `frontend/src/test/live-source-chip.test.tsx` (+7) — the state logic (live /
  seed / null across the cases) and the chip render (LIVE / SEED / nothing). Full frontend **vitest 73
  passed**; `tsc --noEmit` clean; HUD-v2 parity green; `agents/web/v2` rebuilt + committed.
- **⚠️ Needs you (live pixels — CDX-9):** open each mode in a real browser and confirm the LIVE/SEED chip
  reads correctly (LIVE when a backend source is up, SEED under DEMO) and sits well in the layout. *(The
  larger CDX-9 half — OpenAPI-generated types + removing `@ts-nocheck` per module — is left as its own
  slice, not attempted here.)*

### Cleanup — per-agent call timeout is now a tunable setting (CDX-6)
- **What:** `_call_agents_parallel` hard-coded a `120.0`s per-agent LLM-call timeout — one invisible
  ceiling shared across chat / deep-research / autonomy / eval. Extracted to
  `Orchestrator._agent_call_timeout()`, which reads the **`agents.agent_timeout_seconds`** setting
  (default 120), clamps it to **≥1s**, and falls back to 120 on a non-numeric value so a bad config can
  never disable the timeout. The ceiling is now visible and per-context tunable.
- **Verified (automated):** `tests/test_orchestrator_process_record.py` (+4) — default 120, honors a set
  value, clamps 0/negative → 1s, and a non-numeric value → safe 120 (never raises). Full suite **3,025
  passed**; `ruff` + `bandit` clean. Behavior-preserving by default (still 120s until you set it).
- **⚠️ Needs you:** nothing. Optional: set `agents.agent_timeout_seconds` lower for snappy chat or higher
  for long deep-research runs. *(Full per-task budget-object integration into the chat pipeline remains a
  larger refactor — flagged, not attempted, since the request pipeline isn't safely extractable yet.)*

### Privacy — CLI "forget me" now erases memory at rest (AUD-2 completeness)
- **What:** the **CLI** forget (`python -m agents.core.data_purge --confirm`) now defaults to
  `memory=True`, so it erases the memory subsystem at rest (knowledge graph / entities / decay stores,
  embedding cache, session transcripts) — closing a real **PII-retention gap**. AUD-2 (#315) had brought
  only the `/api/admin/forget` *endpoint* to parity; the offline CLI still left memory behind. A
  `--no-memory` escape mirrors the existing `--no-backup`. Also documents (in the module docstring) that
  the backup-first snapshot is plaintext PII until a backup key is set (AUD-1) — secure/remove it after a
  forget, or use `--no-backup`.
- **Verified (automated):** `tests/test_data_purge.py` (+1) — the CLI erases the memory stores by default
  and `--no-memory` leaves them; the function-level memory purge stays covered by
  `tests/test_data_purge_memory.py` (I dropped the redundant duplicates). Full suite **3,027 passed**;
  `ruff` + `bandit` clean.
- **⚠️ Needs you:** nothing code-side. *Operational note:* the live Qdrant/Neo4j wipe is best-effort via
  each store's `clear()` (the endpoint clears live stores first); a true external-service purge for those
  remains an ops step on a real deployment.

### V-track — reality harness now proves the kernel capability-token rail
- **What:** a fourth **hermetic** reality case completes the proof of the Action-Kernel's *gate-1*: the
  **capability-token path** (alongside the kill-switch rail from the prior PR). With a real
  `CapabilityBroker`, a valid minted token clears the kernel gate (the action reaches policy), and a
  missing/unknown token makes `kernel.authorize` return **DENY** ("no valid capability token"). A green
  probe promotes `component:capabilities` to **VERIFIED**. Both halves of the kernel's first gate
  (kill-switch + capability) are now harness-backed.
- **Verified (automated):** scratch-simulated first (valid→queue, missing→deny). `tests/test_reality_harness.py`
  (+1, now 8): the seeded-cases test asserts both `component:kill_switch` and `component:capabilities`
  promote; a focused test runs the capability case in isolation. Full suite **3,020 passed**; `ruff` +
  `bandit` clean — bandit flagged the deliberately-invalid token literal as a hardcoded-credential false
  positive (B106), so it's bound to a named variable rather than growing the baseline (the trivial-refactor
  fix, since it's avoidable unlike the status_sync subprocess findings).
- **⚠️ Needs you:** nothing — hermetic, offline. (Live keyed per-capability cases remain the owner-gated
  nightly-lane follow-up.)

### V-track — reality harness now proves the Action-Kernel kill-switch rail
- **What:** a third **hermetic** reality case (`reality_harness.py:CASES`) proves the most safety-critical
  Track-K rail end-to-end with **real primitives** — not a mock: an engaged `KillSwitch` makes
  `kernel.authorize` return **DENY**, and disengaging lets the same action past the kill-switch gate
  (it reaches policy). A green probe promotes `component:kill_switch` to **VERIFIED** in the V2 registry.
  Extends the harness beyond the egress rail to the kernel's deny path, advancing Gate-V ("nothing
  VERIFIED without a green harness").
- **Verified (automated):** scratch-simulated against the real `KillSwitch`/`authorize` first (engaged→deny,
  disengaged→queue, and the **live kill-switch left untouched** — the probe uses a throwaway temp store).
  `tests/test_reality_harness.py` (+1, now 7): the kill-switch case passes + promotes, and a guard asserts
  `KillSwitch().is_halted("global")` stays False (isolation proof). Full suite **3,019 passed**; `ruff` +
  `bandit` clean (mkdtemp is the safe-tmp pattern — no new findings).
- **⚠️ Needs you:** nothing — it's a hermetic, offline proof. (The *live*, keyed per-capability cases remain
  the owner-gated nightly-lane follow-up, as before.)

### Tooling — `scripts/status_sync.py` ends the STATUS.md count drift (CDX-5)
- **What:** a small CLI that derives the two STATUS.md header numbers that drift on nearly every PR —
  the **test count** (`pytest --collect-only`) and the **HTTP-route count** (the parity snapshot) — and
  either `--check`s STATUS.md against them or `--write`s them in place. Replaces the hand-bumped "~N
  passed" step (which had already silently drifted to **327 routes / 3,011 tests**; the tool corrected
  it to **328 / 3,024**). Closes the "Remaining" half of CDX-5. Deliberately **not** a blocking CI gate
  (the header `~` signals approximate) — `--check` is an optional nudge, not a merge wall.
- **Verified (automated):** `tests/test_status_sync.py` (+7) — route count matches the snapshot, the
  STATUS rewrite is anchored (touches only the two tokens, leaves version strings / "45 routers" prose
  intact), each token rewrites independently, and the live STATUS.md parses. The heavy `count_tests()`
  (shells out to a full collection) is left out of the unit tests on purpose. Dogfooded end-to-end
  (`--write` then `--check` clean). Full suite + `ruff` + `bandit` clean.
- **⚠️ Needs you:** nothing — pure dev tooling. Optionally run `python scripts/status_sync.py --check`
  before a release to confirm STATUS.md isn't stale.

### HUD — north-star meter now surfaces the P1 proactive metrics
- **What:** the ObserveMode **`NorthStarMeter`** (`modes2.tsx`) gained a third **PROACTIVE** row that
  renders the metrics shipped in #369/#370 but previously invisible in the HUD: **done overnight** +
  **night share** (`night_shift.done` / `.pct`) and **surfaced/proposed** + **accept rate**
  (`proposal_funnel.surface_rate` / `.accept_rate`). Closes the value loop — the proof-gap numbers are
  now *seen*, not just served on `/api/metrics/north-star`. Same single-user honesty as the rest of the
  meter: a null block renders **"—"**, never a fabricated `0%`.
- **Verified (automated):** `frontend/src/test/trust-analytics.test.tsx` (+2) — the proactive row
  renders night-share 50% / surface 75% / accept 67% from a populated payload, and honest "—" when the
  blocks are null. Full frontend **vitest 66 passed**; `tsc --noEmit` clean; `agents/web/v2` rebuilt +
  committed (the `hud-v2-build` guard). Frontend-only — no backend/route change.
- **⚠️ Needs you (live pixels — CDX-9):** open the HUD *Observe* mode and confirm the PROACTIVE row
  shows the overnight count + night share + funnel rates once there's real autonomy activity.

### HUD — "Today in Jarvis" cockpit panel (P1 G1 UI)
- **What:** a Console *Autonomy & Agents* panel (`TodayPanel`) that renders the unified-timeline
  endpoint (`GET /api/dashboard/today`): each row is a **did** (autonomy action, green) or **learned**
  (memory fact, accent) tag + label + local time, newest-first, under a `"N did · M learned"` header.
  Closes the UI half of P1 G1 (the backend feed shipped in the prior item).
- **Verified (automated):** `frontend/src/test/today-panel.test.tsx` (+2, fetch-mocked) — did/learned
  rows + summary render, and a clean empty state. Full frontend **vitest 64 passed**; `tsc --noEmit`
  clean; backend HUD-v2 parity green; `agents/web/v2` rebuilt + committed (the `hud-v2-build` guard).
- **⚠️ Needs you (live pixels — CDX-9):** open Console → *Autonomy & Agents* in a real browser after
  some autonomy + a few remembered facts, and confirm the did/learned items interleave by time and the
  header count matches.

### Dashboard — P1 unified "Today in Jarvis" timeline (proof-gap 3/3)
- **What:** new `memory/timeline.py:build_unified_digest(queue, memory_entries, …)` fuses what Jarvis
  **did** (autonomy tasks that reached `done`) and what it **learned** (new / updated memory facts &
  preferences) into **one timestamp-ordered feed** — closing the gap where the task recap
  (`autonomy/digest.py`) and learnings (`memory/digest.py`) lived in separate places. Served at
  **`GET /api/dashboard/today?days=1`** (`user_guard`'d — it surfaces personal facts; `days` clamped
  1–30). Pure builder over existing rows (a `TaskQueue` + the SQLite fact store via `MemoryStore()`):
  no new capture, no schema. This closes the **third and last P1 proof-gap** — all three are now done.
- **Verified (automated):** `tests/test_timeline.py` (+9) — fusion + newest-first ordering, window
  exclusion, `days` widening, `limit` truncation (counts reflect the *full* in-window set), honest
  empty/None state, unparseable-timestamp rows kept (never dropped), and the endpoint (fuse + 422
  clamp + 503). Route-surface / OpenAPI / route-auth / HUD-v2 parity snapshots reseeded (one route
  added: `GET /api/dashboard/today` → `user` guard, cockpit surface). **Full suite 3,011 passed**;
  `ruff` + `bandit` clean.
- **⚠️ Needs you (CDX-9 — live pixels, deferred):** this PR is **backend-only** — there's no HUD panel
  yet (a *cockpit* "Today" panel reading this endpoint is the follow-up UI slice, same rhythm as the
  feedback/onboarding panels). Eyeball the data now: `curl localhost:<port>/api/dashboard/today | jq`
  after some autonomy + a few remembered facts, and confirm the did/learned items interleave by time.

### Metrics — P1 night-shift north-star split ("works while you sleep" as a number)
- **What:** `compute_north_star` now returns a **`night_shift`** block — `{done, pct, window}` —
  measuring, of the accepted actions, how many **completed during the local night window**. It buckets
  each `done` task by the *local* hour of its `updated_at` (the stored UTC stamp converted to the
  server's zone — the user's clock on a single-user box), reusing the worker's **`is_night_window()`**
  so the split matches the same window that gates the overnight tier caps. The endpoint threads the
  configured `autonomy.night_start`/`night_end` (default 23→6). Turns the headline P1 claim into a
  reported number. Auto-exposed via `GET /api/metrics/north-star`; docs in `docs/METRICS.md`. Second of
  the three P1 proof-gaps.
- **Verified (automated):** `tests/test_north_star.py` (+3) — a 3-accepted split (02:00 + 23:00 → night,
  14:00 → day ⇒ `done`=2, `pct`=2/3), a custom-window case, and an empty `pct`=null honest case. The
  helper writes each timestamp as today's local hour stored back as UTC, so the split is **TZ-robust**
  (deterministic in CI's UTC and on a dev box alike). **Full suite 3,002 passed**; `ruff` + `bandit`
  clean. Backend-only — no HUD build artifact touched.
- **⚠️ Needs you:** nothing owner-only. The night window is the server's *local* clock — if you run the
  box in a different TZ than you sleep in, set `autonomy.night_start`/`night_end` to match. Eyeball:
  `curl localhost:<port>/api/metrics/north-star | jq .night_shift` after some overnight autonomy.

### Metrics — P1 proposal-funnel diagnostic on the north-star
- **What:** `compute_north_star` now also returns a **`proposal_funnel`** block — a *cohort*
  over the proposals **created** in the window: `proposed → surfaced` (a decision card reached
  the inbox / `pushed`) `→ accepted` (`done`) / `rejected` / `pending`, plus `surface_rate` and
  `accept_rate`. It localizes *where* a low north-star comes from (too few proposed? proposed
  but never surfaced? surfaced but rejected?). Auto-exposed read-only via
  `GET /api/metrics/north-star` — no new endpoint, no new storage, pure function over the
  existing autonomy `TaskQueue`. First of the three P1 proof-gaps (the pack that moves the
  north-star). Docs in `docs/METRICS.md`.
- **Verified (automated):** `tests/test_north_star.py` (+3) — a 4-proposal cohort
  (2 accepted / 1 rejected / 1 pending, 2 surfaced; `accept_rate`=2/3, `surface_rate`=0.5) with a
  30-day-old proposal proving the created-in-window cohort excludes it; plus empty-honest and
  None-queue cases. **Full suite 2,999 passed**, `ruff` + `bandit` clean. Backend-only — no HUD
  build artifact touched.
- **⚠️ Needs you:** nothing owner-only here — it's pure aggregate metrics over existing rows. If
  you want to eyeball it, `curl localhost:<port>/api/metrics/north-star | jq .proposal_funnel`
  after some real autonomy activity and sanity-check the drop-off story against what you saw.

### HUD — Onboarding panel (H23.20 UI)
- **What:** a Console *Observe* panel that drives the first-run wizard: it reads
  `GET /api/onboarding/wizard` and renders the ordered steps (intro → model → say-hello →
  autonomy-budget) with **done/pending** state + progress + the **cold-start hint** (shown when
  no model backend is reachable), and a per-step **done** button records the funnel event
  (`POST /api/onboarding/funnel`) so completion **persists across reloads**. Closes the UI half
  of H23.20 (backend already shipped).
- **Verified (automated):** `frontend/src/test/onboarding-panel.test.tsx` (+2, fetch-mocked) —
  steps render with completed-marking + the mark-done control, and the cold-start hint surfaces.
  Full frontend **vitest 62 passed**; `tsc --noEmit` clean; backend HUD-v2 parity green;
  `agents/web/v2` rebuilt + committed.
- **⚠️ Needs you (live pixels — CDX-9):** on a fresh install, open Console *Observe* and confirm
  the onboarding steps + cold-start hint render and that marking a step done sticks across reload.

### HUD — Feedback / NPS panel (H23.21 UI)
- **What:** a Console *Observe* panel that surfaces the design-partner feedback loop: it reads
  the **NPS summary** (`GET /api/feedback/summary`, admin — promoters/detractors + per-kind counts
  + recent comments) and carries a **submit form** (score 0–10 + comment → `POST /api/feedback`).
  Closes the UI half of H23.21 (the backend feedback store + endpoints already shipped).
- **Verified (automated):** `frontend/src/test/feedback-panel.test.tsx` (+2, fetch-mocked) — the
  NPS/promoters/detractors + a recent item render and the submit control is present; clean
  empty-state. Full frontend **vitest 60 passed**; `tsc --noEmit` clean; backend HUD-v2 parity
  green; `agents/web/v2` rebuilt + committed (the `hud-v2-build` guard).
- **⚠️ Needs you (live pixels — CDX-9):** open Console *Observe* in a real browser, submit an NPS
  score, and confirm it appears in the summary. (Recruiting the actual design partners is your call.)

### K3 (recursion-depth cap) — sub-agent delegation can't tower up unbounded
- **What:** `SubAgentManager` already capped how *wide* an agent forks (concurrency); this caps
  how *deep* — a sub-agent that spawns a sub-agent that spawns a sub-agent now hits a
  **recursion-depth cap** (OWASP unbounded-consumption). Depth is inferred from the recorded
  parent-chain, so no runner change is needed. Default **8** (a real guard out of the box;
  configurable via the `autonomy.max_subagent_depth` setting; `None`/≤0 = unbounded).
- **Verified (automated):** `tests/test_subagent_depth.py` (+4) — a deep chain is rejected at the
  cap with a clean `recursion_depth_cap` reason, flat (top-level) spawns never hit it, `None` is
  unbounded, and the `≤0 → unbounded` normalization + default-8 hold. Existing subagent tests still
  green. Full suite **2,996 passed**; ruff + bandit clean.
- **⚠️ Needs you:** nothing urgent — the default 8 is deep enough for any real delegation. If you
  build deeply-nested agent workflows, raise `autonomy.max_subagent_depth`.

### K3 (per-task wall-time budget) — a task can't run forever
- **What:** the autonomy worker's `TaskExecutor` now supports a per-task **wall-time budget**
  (`JARVIS_TASK_MAX_SECONDS`). A task whose handler overruns is **cancelled** at the dispatch
  point and returns a clean `{"status":"failed","reason":"wall_time_budget_exceeded"}` — an
  OWASP unbounded-consumption guard. **Default-off** (unset / ≤0 = unbounded → byte-identical).
- **Verified (automated):** `tests/test_executor_budget.py` (+5) — unbounded default runs
  normally, a within-budget task completes, an **overrunning task is cancelled** (its handler
  body provably does *not* finish) and returns the clean failed result, non-dict results still
  wrap, and the env parsing handles blank/zero/garbage. Full suite **2,992 passed**; ruff + bandit clean.
- **⚠️ Needs you:** if you enable `JARVIS_TASK_MAX_SECONDS`, pick a value above your **legitimate**
  longest task (deep-research / long autonomy runs can be minutes) — too low will cancel real work.
  The token + recursion-depth budget dimensions are still pending (they need handler-level hooks).

### HUD — Track-K safety panels (H23.3 + this session's backends)
- **What:** the Console *Trust* section now surfaces the kernel safety controls so an operator
  doesn't need `curl`. The **kill-switch one-tap** (HALT-ALL / disengage) was already there;
  this adds **`KernelMetricsPanel`** (`GET /api/metrics/kernel` — grant/queue/deny tallies + the
  recent denials with reasons; a default-off hint when the meter is empty) and **`LoopBreakerPanel`**
  (`GET /api/security/loop-breaker` — tripped/closed + threshold/window, with a **reset** button shown
  only when tripped). Frontend-only — all three endpoints already shipped this session.
- **Verified (automated):** `frontend/src/test/kernel-safety-panels.test.tsx` (+4, fetch-mocked) —
  verdict tallies + a denial render, the empty-meter hint, reset-only-when-tripped, no-reset-when-healthy.
  Full frontend vitest **58 passed**; `tsc --noEmit` clean; backend HUD-v2 parity guard still green.
- **⚠️ Needs you (live pixels — CDX-9):** open the Console *Trust* section in a real browser and
  confirm the three panels render and the buttons work — with `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch and watch the deny tally tick up on the kernel panel; trip the loop breaker (or its test
  hook) and confirm **reset** closes it. This is the operator cockpit for everything Track-K — worth a
  real look.

### Gate-K observability — `GET /api/metrics/kernel`
- **What:** now that every privileged action crosses `kernel.authorize`, there's a single
  place to see what the kernel is doing. An in-process meter tallies **grant/deny/queue per
  action kind** + a deny-rate + the **recent denials with reasons** (so a halt / runaway /
  over-budget is visible), served at `GET /api/metrics/kernel` (open, like the north-star /
  capabilities meters). In-memory only (resets on restart; the IntentLog audit chain is the
  durable record). **No runtime behavior change** — it only tallies what already happens, and
  stays empty until `JARVIS_ACTION_KERNEL` is on (brokers/routes don't call `authorize` when off).
- **Verified (automated):** `tests/test_kernel_metrics.py` (+5) — meter unit (record/snapshot/
  reset, bounded denials ring, unknown-verdict ignored), the kernel tallies grant/queue/deny
  through a real `authorize` (incl. a halted-kill-switch deny captured with its reason), and the
  endpoint returns the snapshot. Full suite **2,987 passed**; ruff + bandit clean; route/auth/
  OpenAPI parity snapshots reseeded (+1 open route).
- **⚠️ Needs you:** nothing — pure observability. During manual testing with the kernel flag on,
  `GET /api/metrics/kernel` is the quickest way to confirm the kill-switch/loop-breaker/budget
  denials are firing as expected (and a HUD panel for it is a natural future add).

### K3 (loop-breaker slice) — loop circuit breaker bound to the agent-action path
- **What:** the kernel's loop-wide circuit breaker (`LoopDetector`, an OWASP
  unbounded-consumption guard) is now wired in. The orchestrator owns one shared
  `self.loop_detector`, and the autonomy coordinator binds it into the **broker-mediated**
  kernel — so with `JARVIS_ACTION_KERNEL=1`, a runaway agent that re-requests the **same**
  governed action (call/social/writeback/node/payment) past the threshold (default 10 in
  60s) is **denied** at the kernel front door. **Default-off.**
- **The key design call:** it is bound **only** to the broker path, **not** routes/egress/
  MCP/KG. The breaker keys on `action.kind`, and those paths legitimately repeat one kind
  (many egress calls, many KG writes), so a fleet-wide binding would **false-trip** on
  normal traffic. `make_action_kernel(orch)` (used by routes/egress) omits the detector;
  only the autonomy coordinator passes it.
- **Verified (automated):** `tests/test_kernel_loop_breaker_wave.py` (+5): trips on a
  runaway · counts **per-signature, not total** · the route/egress kernel never carries it
  (20 identical `kg.write` never trip) · a None detector is inert · a **real `CallBroker`
  end-to-end** refuses the runaway. Full suite **2,978 passed**; ruff + bandit clean.
- **⚠️ Needs you:** the breaker threshold is **10 identical governed actions in 60s** — a
  conservative default. During testing with the kernel flag on, confirm your **legitimate**
  workloads (e.g. a pipeline dispatching many `node.dispatch` subtasks) don't hit it; if
  they do, that threshold should become configurable (a tracked follow-up). The breaker
  stays open until reset — the API for that now exists: `GET /api/security/loop-breaker`
  (status) + `POST /api/security/loop-breaker/reset` (admin; **not** kernel-mediated, so a
  tripped breaker can't block its own reset). A HUD button for it is still a future add.

### V3 — cross-agent interface-contract drift gate
- **What:** a new CI gate (`tests/test_interface_contract_drift.py`) snapshots the **shared
  schemas that cross agent boundaries** — the kernel `Action`/`Decision`/`Capability`/`Budget`
  dataclasses (the contract every Gate-K-mediated action is built as), the `Verdict`/`Mediation`
  enums, and the A2A pydantic wire bodies — and fails CI if any field is added/removed/renamed/
  retyped or an enum value changes. Pure test/guard addition; **no runtime behavior change**.
- **Verified (automated):** the 3 guard tests pass; full suite **2,973 passed**; `ruff` + `bandit`
  clean. I also confirmed it actually bites (a field rename would fail with a precise message and
  the `--update` regenerate hint).
- **⚠️ Needs you:** nothing — it's a fleet-coordination safety net. (Remaining V3 tail: extending
  the readiness matrix to components/skills needs a booted fixture; subagent return-dict shapes
  are ad-hoc dicts that aren't statically introspectable.)

### K1 (wave-3, kg.write slice) — externally-driven KG writes route through the Action Kernel — **Gate-K COMPLETE** 🎉
- **What:** the 6 externally-driven `/api/kg/*` mutating HTTP handlers (entity upsert/delete,
  relation add/delete, fact add, ingest) now pass `kernel.authorize` (default-off). With
  `JARVIS_ACTION_KERNEL=1`, a halted kill-switch → **403**. This is the **last** Track-K
  slice: **every one of the 11 privileged action kinds is now KERNEL-mediated** — a halt
  uniformly denies payments, plugin egress, MCP writes, gated Tool-RPC, admin escalations,
  and external KG writes.
- **The boundary is the whole point** (workflow-verified, 8 agents, no blockers): only the
  *external* HTTP handlers are gated. The **internal, high-frequency** ingestion path
  (`IncrementalKGUpdater.ingest` from `orchestrator._record_interactions`, `seed_graph`,
  reflection) writes graph methods **directly** and is **never** gated — so **a halt does
  NOT freeze per-turn memory**. A dedicated test pins this: while halted, external
  `/api/kg/ingest` returns 403 *and* internal `kg_updater.ingest` / `graph.add_entity` still
  write. `memory.remember` (vector write), `/consolidate` (plan-only), `/decay/forget`
  (ACT-R op) are not KG writes → intentionally out of scope.
- **Verified (automated + scratch):** `tests/test_kg_kernel_wave.py` (+9) over real
  `InMemoryGraph`+`BiTemporalKG`+`IncrementalKGUpdater`+`KillSwitch`+`AutonomyPolicy`+real
  `make_action_kernel`: default-off byte-identical · clean→200 · halt→403 on all 6 handlers
  · **boundary proof** · disengage recovers · presented-bad-token→403 · deny-precedes-lookup
  (403 not 404) · keys-only payload (no PII values). The action-auth matrix proves `kg.write`
  routes through the kernel when on / not when off. Full suite green (2,970 passed).
- **⚠️ Needs you:** with `JARVIS_ACTION_KERNEL=1`, engage the kill-switch and confirm an
  `/api/kg/*` write (e.g. `POST /api/kg/entities`) returns 403 **while normal conversation
  still builds memory** (the internal KG keeps updating per turn — this is the critical
  boundary; please verify a real chat still remembers facts during a halt). Then disengage
  and confirm external KG writes resume. Note no-token requests are still allowed by design
  (wave-4b/K2 makes capability tokens mandatory).

### K1 (wave-4a) — admin kill-switch + capability-issue route through the Action Kernel (B1 structural)
- **What:** the two admin escalation routes — engaging the kill-switch and minting a
  capability token — now pass `kernel.authorize` **in addition to** today's `admin_guard`.
  With `JARVIS_ACTION_KERNEL=1`: a halted kill-switch (or a *presented* capability token
  that lacks the named capability) → **403**; the clean path (unknown admin kind → policy
  QUEUE) is treated as **allow-through** so there's no approval-UX regression. **Default-off.**
- **Designed + adversarially verified by a workflow** (8 agents) that caught two real
  blockers before any code:
  - **Bootstrap lock-out:** if disengage were mediated, a halt would deny its own release
    and the operator could never recover. **Fix shipped:** *disengage bypasses the kernel*
    (stays `admin_guard`-only) — recovery always works. A test pins exactly this
    (halt → engage/issue 403, but disengage 200 → released → mint works again).
  - **Honest scope:** the `Capability` is K1-tolerant, so a *no-token* admin request still
    falls through (QUEUE→allow). So this is the **structural** half of B1 (route through the
    kernel + cross-check a *presented* token + kill-switch gate); making a token **mandatory**
    is **wave-4b/K2**. The PR/BACKLOG say so explicitly — I did **not** overclaim "closes B1".
- **Verified (automated + scratch):** `tests/test_admin_kernel_wave.py` drives the **real
  handlers** over a real `KillSwitch`+`CapabilityBroker`+`AutonomyPolicy`+real
  `make_action_kernel`: default-off byte-identical · clean→200 · halt→403 + disengage
  recovers · presented-bad-token→403 · each handler emits its own kind. The action-auth
  matrix proves both admin kinds route through the kernel when on / not when off. Full
  suite green (2,961 passed; the last kernel xfail scaffold is now a real pass).
- **⚠️ Needs you:** with `JARVIS_ACTION_KERNEL=1`, (1) confirm engaging the kill-switch and
  minting a capability still work normally (200) on a clean system; (2) engage a halt, then
  confirm a *second* engage and a capability-mint return 403 **but disengage still works**
  (this is the safety-critical recovery path — please exercise it for real); (3) note that a
  no-token admin request is still allowed today by design — wave-4b will make tokens mandatory.

### K1 (wave-3, Tool-RPC slice) — gated Tool-RPC calls route through the Action Kernel
- **What:** a *gated* (external/mutating) Tool-RPC call — the path a sandboxed agent
  script uses to reach a mutating tool — now passes the **kernel** before it can even
  enqueue its approval task. With `JARVIS_ACTION_KERNEL=1`, a **halted kill-switch
  blocks gated Tool-RPC calls** (plus over-budget / runaway-loop denials), returning
  `kernel_denied`. Read-only inline tools are untouched (they run with no side effects).
  **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests (flag-off skips the kernel even when
  bound, DENY blocks before the enqueue + audited, GRANT still enqueues, **read-only
  tools never consult the kernel**, args *keys* only in the payload — no values) **plus
  a real-primitives integration**: the production `kernel.authorize` over a real
  `AutonomyPolicy` + real `KillSwitch` — engage → not enqueued, release → enqueued. The
  action-auth matrix proves `tool.rpc` routes through the kernel when on / not when off.
  Full suite green (2,953 passed).
- **⚠️ Needs you:** Tool-RPC gated tools are an internal sandbox surface (no gated tool
  is registered by default beyond the `echo`/`time` read-only built-ins). When you wire
  a real gated tool, enable the kernel flag, engage the kill-switch, and confirm the
  gated call returns `kernel_denied` rather than enqueuing.

### K1 (wave-3, MCP slice) — MCP mutating tools route through the Action Kernel
- **What:** the MCP write surface (`MutatingRouteTool` — today just
  `route_memory_remember`, double-kill-switched off by default) now also passes the
  **kernel** after the existing per-identity gate. With `JARVIS_ACTION_KERNEL=1`, a
  **halted kill-switch blocks MCP writes** (plus over-budget / runaway-loop denials):
  identity proves *who*, the kernel decides *whether the write may run now*. A denial
  raises `MutatingKernelError`, is audited `refused-kernel`, and the write never runs.
  **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests (flag-off skips the kernel even when
  bound, no-kernel writes, DENY blocks + audits + no write, GRANT writes, **identity
  failure precedes the kernel**, builder threads the kernel) **plus a real-primitives
  integration**: the production `kernel.authorize` over a real `AutonomyPolicy` + real
  `KillSwitch` — engage → write blocked, release → write runs. The action-auth matrix
  now proves `mcp.mutating` really routes through the kernel when on / not when off.
  Full suite green (2,947 passed).
- **⚠️ Needs you:** this surface is reachable only with BOTH `JARVIS_MCP_ROUTE_TOOLS`
  and `JARVIS_MCP_MUTATING_TOOLS` on (default off). During testing, with those + the
  kernel flag on, drive `route_memory_remember` over MCP, engage the kill-switch, and
  confirm the write is refused (`blocked by kernel`) with a `refused-kernel` audit row.

### K1 (wave-2) — plugin egress routes through the Action Kernel
- **What:** policy-passing plugin egress (an HTTP call the plugin's manifest already
  allows) now also passes the **kernel**. With `JARVIS_ACTION_KERNEL=1`, a **halted
  kill-switch blocks all outbound plugin calls** (plus over-budget / runaway-loop
  denials) — the manifest decides *where* a plugin may reach, the kernel can veto *that
  it reaches at all right now*. `http_client` stays fully decoupled: the orchestrator
  injects a plain `(plugin, method, url, host) → reason|None` hook bound to
  `kernel.authorize`. A buggy hook **fails open** (the manifest policy already ran), so
  the experimental gate can never brick egress. **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests for the hook contract (deny blocks,
  allow passes, no-hook no-op, exception fails-open, **manifest block precedes the
  kernel**) + the production hook (default-off, deny-when-on, none-kernel-allows) **plus
  a real-primitives integration**: the production `kernel.authorize` over a real
  `AutonomyPolicy` + real `KillSwitch` — engage → egress raises `PluginEgressError`,
  release → egress allowed. The action-auth matrix now proves `plugin.egress` really
  routes through the kernel when on / not when off. Full suite green (2,938 passed); the
  old B3 xfail scaffold is now a real passing regression.
- **⚠️ Needs you:** during manual testing, set `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch from the HUD/API, and confirm a plugin that makes outbound calls (e.g. a
  weather/news plugin) is blocked while halted, then released. Also confirm the
  network-monitor panel records the blocked attempt (reason mentions the kernel).

### K1 (payment micro-wave) — payments route through the Action Kernel
- **What:** an *admissible* `request_payment` (one the mandate's hard caps already
  accept) now passes through `kernel.authorize`. A kernel **DENY** — kill-switch
  engaged, over-budget, or a runaway loop — refuses the payment **before** it can
  become `pending`; GRANT/QUEUE fall through to the existing always-approval flow.
  The kernel can only *add* a hard deny; it can't relax the rule that every payment
  needs explicit owner approval. The binding (`kernel/binding.py`) is now shared with
  the wave-1 brokers, so there's one definition of what the kernel front door is bound
  to. **Default-off** behind `JARVIS_ACTION_KERNEL` — zero behavior change until enabled.
- **Verified (automated + scratch):** unit tests (deny-before-pending, flag-off skips
  the kernel even when bound, inadmissible never reaches it, GRANT/QUEUE stay pending)
  **plus a real-primitives integration test**: the production `kernel.authorize` bound
  over a real `AutonomyPolicy` + real `KillSwitch` — halting the switch denies a
  payment (nothing becomes pending), releasing it lets the admissible payment proceed.
  Full suite green (2,928 passed).
- **⚠️ Needs you:** during manual testing, set `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch, and confirm a `request_payment` is refused (`kernel_denied`) and shows a
  `deny_payment` row in the payments audit; then release and confirm it goes to pending.

### H23.17 (slice) — i18n completeness gate
- **What:** `frontend/src/test/i18n-completeness.test.ts` fails CI if any locale (en/ro)
  is missing a key the reference has, has an extra key, or has a blank string. Runs in the
  existing CI vitest job.
- **Verified (automated):** ran the full frontend vitest suite locally — 54 tests pass
  including the 5 new i18n checks; en/ro are complete today.
- **⚠️ Needs you:** nothing. Remaining H23.17 slices (Playwright E2E, a11y, soak,
  browser/mobile matrix) are pending — E2E is feasible to build + simulate here.

### K2 — least-privilege capability set per agent (issuance)
- **What:** `kernel/capabilities.py` derives each agent's capability set from its declared
  config (plugins/channel/policy), and the orchestrator issues a scoped `CapabilityBroker`
  token per agent at boot (`orch.agent_capabilities`). Strict-local agents (frigga/ultron/
  howard) never get a cloud capability. **Inert** — nothing checks per-agent tokens yet
  (the per-action enforcement waves do), so zero behavior change.
- **Verified (automated + scratch):** unit tests (derivation least-privilege, real-broker
  issuance) + a scratch run over the **real 17-agent roster** confirming every agent gets a
  least-privilege token and the three local-only agents have no cloud cap.
- **⚠️ Needs you:** nothing yet. The enforcement half (B1 — admin actions require a
  capability; folding WorldView HMAC tokens) is a deliberate later wave.

### H23.6 — minimal taint flag + kernel escalation (indirect-injection guard)
- **What:** `security/taint.py` marks content from untrusted sources (web/OSINT/RSS/inbound)
  as tainted; the action kernel **escalates a tainted action from GRANT → QUEUE** (approval),
  so injected content can't auto-execute. Default-off effect: only fires for actions
  explicitly carrying the taint flag (nothing marks them yet — see pending).
- **Verified (automated + scratch):** unit tests (classifier, mark/is_tainted, kernel
  escalation) + scratch run against the **real** `AutonomyPolicy` confirming clean→GRANT,
  tainted→QUEUE.
- **⚠️ Needs you:** nothing yet — but note the producer side (marking ingested web/OSINT
  content tainted) and full data-flow propagation are a deliberate **deferred** follow-up,
  so this guard is mechanism-only until those land.

### B3 — strict-egress downgrade is now durably audited
- **What:** the `JARVIS_STRICT_EGRESS=0` escape hatch (allows a blocked-by-default egress
  host) was a *silent* log line. Now a decoupled audit sink (`http_client.set_egress_audit_sink`,
  wired by the orchestrator to an `AuditLogger` adapter) records a durable `EGRESS_DOWNGRADE`
  security event. No-op in strict mode (the default) — so no behavior change unless you've
  set `JARVIS_STRICT_EGRESS=0`.
- **Verified (automated):** unit tests — downgrade audits, strict mode blocks (no audit),
  no-sink no-op, a throwing sink never breaks egress, http_client stays decoupled from the
  security types. **Scratch:** real `AuditLogger` — a downgrade lands a durable row and
  `verify_chain()` returns valid (HMAC chain intact).
- **⚠️ Needs you:** nothing specific — but during testing, set `JARVIS_STRICT_EGRESS=0`,
  trigger a cross-host plugin call, and confirm the event shows in `GET /api/admin/audit`.

### K4 — kill-switch + credential-quarantine syscalls
- **What:** `kernel/syscalls.py` — `halt()` / `release()` promote the existing `KillSwitch`
  to a kernel call, and `inject_guarded()` makes secret injection **quarantine-aware** (while
  halted, injection is forced blocked regardless of approval). Folds H23.3. Composes existing
  primitives; no behavior change until a caller uses it.
- **Verified (automated):** unit tests — halt→quarantine→release, injection blocked while
  halted even when approved, `kernel.authorize` denies new grants when halted, audit emitted.
- **⚠️ Needs you:** the **one-tap kill-switch HUD control** (frontend) is not built yet — this
  is the backend syscall only. (HUD comes in the productionization-tail phase.)
