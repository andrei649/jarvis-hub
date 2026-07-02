# Fresh-Eyes Backlog Re-Verification — 2026-07-02

> **What this is:** a code-grounded re-verification of every item BACKLOG.md claims is still open,
> plus the GitHub in-flight state and a recommended sequencing for July 2026. Complements (does not
> supersede) the [2026-06-25 roadmap-vs-codebase re-audit](2026-06-25-roadmap-vs-codebase-reaudit.md)
> and the [2026-06-24 Codex review](2026-06-24-codex-review.md).
>
> **Method:** 5 parallel verification agents over HEAD (`ef2cc21`, 2026-07-02) — one per cluster
> (AUD-\*, H23/ORIZONT-24, TASK/BUG/theme tail, GitHub state, planning-doc sequencing). Every verdict
> below was checked against source with `file:line` evidence, not against status labels. Corrections
> landed in the same PR as this doc (#479).

---

## 1. Snapshot (verified)

| Signal | Value |
|--------|-------|
| Version | v0.11.0 (feature horizons H1–H22 + WorldView O19 all delivered) |
| CI on `main` | **green** — all 6 workflows (CI, Smoke, Security, CodeQL, HUD E2E, dep-submission); no red run in recent history |
| Backend tests | ~3,215 passing (static count: 3,261 `def test_` across 347 files) |
| Frontend tests | ~145 vitest (HUD v2) + 199 legacy-v1 harness + 4 Playwright e2e |
| HTTP surface | 354 routes across 45 per-domain routers |
| Velocity | ~40 PRs merged in the last 7 days (2026-06-25 → 07-02) |
| Kernel | **Gate-K complete** — all 11 privileged-action kinds `KERNEL`-mediated, zero `pending` in the action-auth snapshot |
| Packs | P1–P4 offline rails all VERIFIED via hermetic reality cases |

**Headline:** the backlog is *honest* — 12 of 16 spot-checked H23/O24 sub-items verified exactly as
claimed. The drift that exists runs in the **pessimistic** direction: 8 rows said "open/partial" for
work that had already shipped (fixed in this PR, §2). The bottleneck to 1.0 is no longer engineering
volume; it is **proof** (⭐B0 manual test, design partners) plus a short list of substrate close-outs.

---

## 2. Stale rows corrected in this PR (work shipped, rows not refreshed)

| Row | Was | Verified reality |
|-----|-----|------------------|
| H23.5 caveat | "chain is plain SHA-256, scanner stores raw `matched_text`" | AUD-9 keyed HMAC shipped (`JARVIS_AUDIT_KEY`, per-row `hash_algo` migration — `security/audit.py:35-41,59,121`) and AUD-12 F13 shipped (`matched_text` stored `[REDACTED:<pattern>]` — `audit.py:112`) |
| H23.16 | PARTIAL | Complete: egress data layer (`observability/egress_monitor.py` at the `http_client.py:114` choke point) + `GET /api/admin/network/calls` + HUD `NetworkMonitorPanel` (`gap.tsx:1025`, Trust cluster) |
| V2 pending | "HUD readiness board render" pending | `ReadinessPanel` shipped (`gap.tsx:312` + fetch-mocked test); V3's enforcement gate also exists |
| H5.16 sub-item | "wire `voice.ts` to `/tts/stream`" TODO | Wired: `speak()` tries `streamTts` first (`voice.ts:206-215`), 409-fallback to whole-reply `/tts` |
| BUG-12 residual | `_PROC_CACHE` unlocked | `_PROC_CACHE_LOCK` guards get/put incl. LRU ops (`ingestion/embedder.py:60`); residual narrowed to `InMemoryVectorStore` only |
| Run-block test counter | ~2,814 | ~3,215 (matches STATUS.md / `status_sync.py`) |
| HUD_V2_REMAINING tail | listed stale-bundle guard, locality endpoint, BUG-17 chip as open | All three since-closed (`ci.yml` `hud-v2-build`; `GET /api/analytics/locality` consumed in `app.tsx`/`shell.tsx`; audit-verify chip in `modes.tsx:117-165`) |
| HUD_V2_REMAINING §4 | tts-stream wiring open | Done (same as H5.16 above) |

---

## 3. Verified-open engineering map

Ordered by leverage. **Effort:** S ≈ ≤half-day · M ≈ 1–3 days · L ≈ week+.

### 3.1 Substrate close-out (ORIZONT 24 Track K/V — the "AI-OS" bet)

| Item | What's actually left (evidence) | Effort |
|------|--------------------------------|--------|
| **K2 wave-4b — token enforcement** | Issuance is real (`kernel/capabilities.py:23-56`; orchestrator issues per-agent tokens at boot into `orch.agent_capabilities`) but **nothing ever reads them back**; `kernel/__init__.py:61-64` says it itself: "K1 tolerates an empty token… K2 makes a valid token mandatory". B1 is only *structurally* closed. Folding WorldView HMAC tokens in = same wave. | **L** |
| **K3 — budget unification** | `kernel/budget.py:7-9` docstring: unifying InterruptBudget (≤4/day), mission step/time caps, payment caps into `BudgetLedger` is "a later K3 slice". Only token-accrual site is `call_broker.py:252` (coarse byte count) — no handler-level token reporting. | M |
| **V3 — components/skills readiness coverage** | `test_capability_readiness_matrix.py` covers only the statically-enumerable **plugin** set (33 records, all `plugin:` ids); components/skills need a booted fixture. | M |
| **V1 — live contracts + durable promotion** | All 7 reality-harness cases hermetic (`reality_harness.py:317-339`, none `live=True`); promotion is in-process only. Live half needs keys/network (owner) + the nightly lane. | L (part owner) |
| **V4/H23.4 — eval as a blocking gate** | No workflow mentions eval/regression; `test_h9_3b_dataset_regression.py` proves the *machinery* with a fake runner, not model quality. Real gate needs the GPU/networked nightly lane. | M (part owner) |

### 3.2 Trust the inputs

| Item | What's actually left (evidence) | Effort |
|------|--------------------------------|--------|
| **TASK-3/H23.6 — taint propagation** | Only producer marking taint is `osint/correlate.py:204`; websearch/news/RSS plugins, inbound channel handlers, and `ingestion/pipeline.py` never call `taint.mark`. Kernel escalation already works — the inputs just aren't marked. | M |
| 0.28 persona consent gate | Barge-in exists (opt-in, `voice.ts:26-27,190-200`); zero `consent` hits in `cognition/persona.py` / `voice/tts.py`. | S |
| 0.51 draft choreography | `ground_plan()` validator shipped; nothing drives an LLM to draft cited steps into it (host/LLM seam). | M |

### 3.3 HUD depth + quality gates

| Item | What's actually left (evidence) | Effort |
|------|--------------------------------|--------|
| **TASK-2 tail** (smaller than documented) | Plugin-gated mode wiring (Finance/Health/Knowledge/Family, Comms threads), per-panel LIVE/SEED chips, **0.39 `WatchlistPanel`** (backend shipped #472, panel deferred), OpenAPI types, self-hosted fonts. | M (1–2 PRs) |
| **TASK-4 P1s** | All 3 still unfixed: chat **double-submit** (no in-flight guard, `app.tsx:198-238`), muted-mic affordance (`cockpit.tsx:210` opacity-only), admin-token one-shot prompt. Double-submit is unambiguous — fixable now; other two confirm cheapest on hardware. | S each |
| **H23.17 remainder** | e2e = boot/paint/a11y only (no chat/voice flow specs); single-browser project; `e2e.yml` has no `schedule:`; zero soak infra. | M–L |
| BUG-2b | 2b.1 chat-flow specs on the existing harness (M); 2b.2 drag-drop canvas tests (M, zero pointer tests exist); 2b.3 `useVoice` hook tests (S–M — `ttsStream` half already covered). | S–M each |
| AUD-16 — OpenAPI typegen | Exactly **1** `response_model=` across all routers; `types.ts` hand-written; no `openapi-typescript` anywhere; CI has tsc+bundle gates but no OpenAPI→TS diff gate. CI can boot the server the way `e2e.yml` already does. | M |

### 3.4 Structural debt (post-1.0 unless it starts hurting)

| Item | Verified state | Effort |
|------|---------------|--------|
| AUD-13 turn-pipeline dedup | Prompt assembly duplicated in **3** places (`agent.py:136-144`, `orchestrator.py:947-951`, `:985-989`); Howard RAG block copy-pasted; pre-turn pipeline duplicated between `handle_input`/`handle_input_stream`; `sys.modules` indirection in ~12 routers. | L |
| AUD-14 config consolidation | **Compounding**: env reads grew ~121 → **161** since the audit (top: `plugin_manager.py` 22, `web.py` 21); ≥3 truthy conventions; policy sets still hardcoded (`hybrid_router.py:84,114`). | M |
| AUD-15 client consolidation | v2 is default at `/` and the Tauri target ✅; but v1 still served at `/v1` + full legacy static bundle; no `@jarvis/client`; `client.ts:40` bare fetch without timeout; 38 `@ts-nocheck` files (34 test fixtures); `strict:false`. | L |
| AUD-18 tail | Qdrant NOT default (`VECTOR_BACKEND=memory`; compose runs qdrant but never points the hub at it); ~20 plugins eagerly built at boot; no Vite code-split; F28 skill-importer slug lacks traversal guard; F30 CORS values unvalidated. | M |
| BUG-12 residual | Only `InMemoryVectorStore` (`store.py:76-82,152-158` unguarded; safe today because every access routes through `MemoryManager`'s `asyncio.Lock`). Add a lock or pin the invariant. | S |

### 3.5 Reach (mobile parity debt)

`mobile/PARITY.md`: 10 surfaces at parity, 2 intentionally n/a, **9 behind** — Dashboard, Tasks
board, Ticker, Skills browser, Memory/notes, Knowledge graph, **Action approval queue**, Chat rooms,
Security posture. The approval queue is the north-star surface (decision inbox on the phone drives
accepted-actions/week) — do it first. S per surface, L for all nine.

---

## 4. Owner/GPU-gated cluster (nothing repo-side can close these)

| Item | Gate |
|------|------|
| ⭐B0 governed-autonomy run + MANUAL_TESTING sign-off | **THE 1.0 gate** — also unblocks TASK-4 P1 confirmations + CLN follow-up green-light |
| Design partners (recruit 1–3) + north-star on real usage | H23.21 / Phase D — feedback widget + program doc already shipped |
| GitHub settings (~15 min) | #242 code-scanning toggle (intermittently blocks CI), CQ-2 FP dismissals, CQ-3 alert paste, SEC-4 required checks |
| Decisions to record | **AUD-0** (breadth→depth scope) + **H23.23** (single-user for 1.0) — both one-paragraph, both still unrecorded; FAQ already documents 90% of the H23.23 answer |
| License flip MIT → Apache-2.0 (+TRADEMARKS.md) | decided 2026-06-04, pre-1.0 |
| GPU-host items | H12.14 fine-tune (L), **H13.3 speculative decoding (S, config-only)**, TASK-1 Howard first run (routing infra already in `hybrid_router.py:110-114,353-354` — the named `ollama_howard.py` was absorbed), H22.4 `OLLAMA_NUM_PARALLEL` |
| H23.22 landing page + demo | dev-supportable (TEASER_PACK storyboard + shot-list exist); no landing code anywhere yet |
| Dependabot | 19 vulns on default branch (4 high) — mobile/worldview holds are known & deliberate |

---

## 5. GitHub in-flight state (2026-07-02)

- **1 open PR:** #478 "stop generating" button (non-draft, tests green) — merge-ready.
- **12 open issues** in 4 clusters: 7× World-Intelligence lanes (#254–259, #265 — execute or close),
  2× CI/security (#241 SEC-5b *appears shipped in BACKLOG — verify then close*, #242 required-checks
  drift), 2× WorldView deep-review follow-ups (#169 MCP write-tool transport, #170 live-Neo4j
  validation), 1× owner gate (#182).

---

## 6. Cross-doc sequencing consensus

All four planning docs agree (blueprint Phase A→E · REVIEW_YEAR_ONE 90-day plan · OWNER_TASKS ·
GO_LIVE_PLAN, stalest): **Phase A hardening is done** → finish K/V substrate → productionization
tail → product proof. REVIEW_YEAR_ONE's core thesis stands verified: *engineering gaps are a few
focused weeks; the real frontier is product* (no user but the owner, unproven headline loop, no
distribution). North-star is mechanically measurable end-to-end but statistically n=1 until a
non-owner install exists.

## 7. Recommended plan — July 2026

- **Week 1 — bank the tail:** merge #478 + #479 · `WatchlistPanel` · double-submit guard ·
  per-panel LIVE/SEED chips · `InMemoryVectorStore` lock. Closes TASK-2 tail + BUG-12 + a TASK-4 P1.
- **Week 2 — substrate close-out:** K2 wave-4b token enforcement (admin + KG writes mandatory,
  fold WorldView HMAC — truly closes B1) · K3 budget unification. Finishes Track K engineering.
- **Week 3 — trust the inputs:** TASK-3 taint marking at every ingestion choke point · chat-flow
  E2E + nightly soak lane (H23.17) · AUD-16 OpenAPI typegen gate.
- **Week 4 — product-proof prep:** H23.22 landing skeleton + demo support (0.52) · 2–3 mobile
  parity surfaces (approval queue first) · issue-lane cleanup (#254–259: execute or close).
- **Owner lane (parallel, critical path):** ⭐B0 on the RTX box · GitHub settings · record AUD-0 +
  H23.23 · license flip · start partner recruitment · H13.3 while at the GPU box.

**Non-goals this month** (Phase E / post-1.0 per the blueprint): 0.20 Vault, 0.48 video production,
0.64/0.65 desktop overlay + capture reflex, multi-user.
