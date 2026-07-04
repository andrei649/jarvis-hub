# ORIZONT 26 — "Bolt the train to the rails" (rest-of-development plan to 1.0)

> **Tracked in:** [`BACKLOG.md → ORIZONT 26`](../../../BACKLOG.md) — status cells live THERE; tick in
> the same PR as the work. The [ORIZONT 25 execution protocol](2026-07-02-orizont25-execution-blueprint.md)
> (§0: verify-before-claim, grep-the-symbol, one item = one PR, default-off, honesty contract, honest
> terminal states, never-touch list) applies verbatim to every item below. Owner-approved 2026-07-03.

## Context

A three-lens full-code deep dive (runtime intelligence · safety substrate · product surface/debt;
~400k tokens of agent reading, every load-bearing claim re-verified twice at `file:line`) found one
converging thesis: **the rails are magnificent, but the train isn't bolted to them.** The flagship
promises — "knows you", "every action governed", "one decision inbox", "works while you sleep" —
are structurally dormant or bypassed in a default install, for specific, fixable reasons. The
remaining road to 1.0 is therefore not more breadth: it is bolting the existing machinery into the
live product loop, then proving it with design partners.

Owner decisions taken (2026-07-03, via this planning session):
- **D1 Product Posture — APPROVED**: defaults stay off in code; the final onboarding step offers an
  informed-consent switch that wakes wave 1 (recall + embed-turns + KG-ingest + persona/honesty)
  then wave 2 (kernel + budgets + guardrails-REDACT). Exception recorded in AGENTS.md.
- **D4 WorldView — KEEP ACTIVE** (owner overrode the park recommendation): the World-Intelligence
  issue lane (#254–259, #265), #169 MCP write transport, and #170 stay in scope as a parallel
  workstream.
- **D7 HUD — FINISH THE DESIGN**: build everything designed-but-unbuilt in the HUD/human interface
  (the 6 unwired modes + the HUD_V2_REMAINING punch-list); record blockers in BACKLOG rather than
  parking surfaces.

**Update (PR #492, merged `bb8863a` mid-planning, verified against main):** Codex delivered
**M1.1 K3** (BudgetLedger named dimensions ✅), **M1.2 Action.origin** (new `action_origin.py`
ContextVar, bound in `channel_handler` + `Gateway.route` — exactly the blueprint design ✅),
**M2.1 chat/voice flow E2E** ✅ and **M2.3 OpenAPI typegen + CI gate** ✅, plus a doc-truth pass;
M2.4 honestly re-marked partial (baseline persistence WIP). Verified: **F1 is still open** —
`_record_interactions` remains absent from the stream path on `bb8863a`. Plan items below are
annotated accordingly; a happy consequence: the SSE-parity oracle (M2.1) now exists BEFORE the
P1.1 refactor, exactly the ordering this plan wanted.

## Key insights from the deep dive (the "why" behind every phase)

1. **The owner's own dashboard is the least intelligent channel.** `/chat/stream` →
   `handle_input_stream` never calls `_record_interactions` (callers only at
   `orchestrator.py:768,832` in `handle_input`) — web chat produces **no** KG ingest, entity
   extraction, learning/bench records, or run-history, while Telegram does. Also skews the
   north-star %-local metric.
2. **The flagship layers can't be turned on from the product.** `cognition.*` and
   `memory.recall_enabled` are read default-False but absent from `settings_db.DEFAULTS`, and
   `put_category` (settings_db.py:389-407) only UPDATEs existing rows — enabling the "knows you"
   layer requires hand-editing SQLite. `MEMORY_EMBED_TURNS` also default-off → vector store never fills.
3. **The approval funnel is split.** Broker tasks (social/writeback/call/payment) enqueue as
   `proposed`, bypassing `policy.decide` (AUTO/ASK/OFF + money caps never run);
   `pending_decisions()` filters `status='blocked'` only (queue.py:253-254) → broker tasks never
   reach the Telegram/HUD decision inbox. With the kernel off (default), the kill-switch does not
   stop an approved broker task.
4. **The sycophancy axis scores the wrong string** — the user's input, not the assistant reply
   (`cognition_trace.py:93,124`).
5. **Common words silently reroute the model.** `JARVIS_AUTO_DEEP` default-ON sends any prompt
   containing "analyze/strategy/…" to hardcoded `deepseek-r1-distill-qwen-32b`
   (hybrid_router.py:413-417) — latency/failure on a one-model box.
6. **Two entry points, one enforced.** `serve.py:125` runs safe-bind + hardened-posture guards;
   the equally-documented `python -m uvicorn agents.web:app` bypasses them.
7. **Dormant crown jewels**: `cognition/memory.py` LivingMemory, `ensemble`, `profile_extractor`
   (zero callers ever), `memory/decay`+`consolidation` — and **no nightly consolidation/decay job**
   exists in `scheduler_service.py`. Persona mood is static (nudge never called); persona block
   only injects on the non-stream path; runtime-state block only on stream (3 divergent prompt
   builders — root cause of #1).
8. **Surface honesty vs first-run emptiness**: 58 Console panels are honest-empty with zero keys;
   6 of 12 nav modes are unwired design previews; `install.sh` runs the full 3,300-test suite
   mid-install and soft-continues on failure; the plugin gate declares 33 manifests but only ~22
   modules exist (11 ghosts); `balance` returns `mock:true` data.
9. **Tests are spine-deep, loop-shallow**: kernel/routing plumbing superbly covered; nothing would
   catch #1 (no test asserts memory grows after a web chat). Parity tests are source-regex
   analysis, not behavior.

## The plan

Ordering: **pin behavior with tests → tactical correctness → one turn pipeline → wake intelligence
under posture → finish the designed surface → proof.** Repo protocol applies throughout (one item
= one PR, BACKLOG sync in the same PR, default-off except the approved posture, snapshots via
`--update`). Register this plan as **ORIZONT 26** in BACKLOG.md in the first PR.

### Phase 0 — Truth & Correctness (≈1–1.5 wks)

| # | Item | Size | AC | Deps |
|---|------|------|----|------|
| P0.1 | **Golden-loop harness**: fake LLM at the `generate()` seam only; loop #1 skeleton (offline, default CI) | M | a full faked turn runs through `handle_input` in CI | — |
| P0.2 | **F1 fix (tactical)**: stream path calls `_record_interactions`; golden loop #1 = web chat → KG/learning/run-history grow | S | loop green via `/chat/stream`; %-local metric annotated with fix date | P0.1 |
| P0.3 | **F2 fix**: seed `cognition.*` + `memory.recall_enabled/recall_top_k` into DEFAULTS; `put_category` upserts known-spec keys | S | cognition/recall toggleable from admin UI, persists, takes effect | — |
| P0.4 | **F4 fix**: honesty/sycophancy scores the assistant reply (`output_preview`) | S | trace carries scored reply; unblocks Q2 | — |
| P0.5 | **F5 fix**: `JARVIS_AUTO_DEEP` off unless the deep slot is actually probed present | S | one-model box never routes to a missing model | — |
| P0.6 | **F6 fix**: move `assert_safe_bind`/`assert_hardened_posture` into the app lifespan; fix the Run-block docs | S | uvicorn entry enforces the same guards as serve.py | — |
| P0.7 | **F3 fix**: broker proposals run `policy.decide`; `pending_decisions()` includes broker-`proposed`; kill-switch enforced at the executor seam (kernel-independent); golden loops #2 (propose→inbox→approve→execute→audit) + #4 (kill-switch stops everything) | M | broker task appears in Telegram+HUD inbox; halt stops an approved broker task; digest/scheduler consumers of `proposed` regression-tested | P0.1 |

### Phase 1 — One Turn Pipeline (≈2 wks)

| # | Item | Size | AC | Deps |
|---|------|------|----|------|
| P1.1 | **AUD-13 promoted to pre-1.0**: unify `handle_input`/`handle_input_stream`; ONE prompt builder (persona + runtime-state in both paths); one record seam; wire `PersonaModule.nudge` per turn. *(Scope reduced: M1.2 origin threading already landed in #492 — preserve its `action_origin` ContextVar binding through the unification.)* | L | all 5 golden loops green in stream+non-stream; P0.2 tactical patch deleted; mood evolves across a session; SSE behavior equivalent (M2.1 E2E from #492 as oracle). Fallback if SSE parity is at risk: extract shared builder+record-seam piecemeal, keep dual paths | P0.* |
| P1.2 | ~~K3 budget unification~~ ✅ **done (#492)** — `BudgetLedger` named dimensions verified on `bb8863a`. Residual: confirm InterruptBudget/payment dims are consumed live under the Phase-2 posture | — | — | — |

### Phase 2 — Wake the Intelligence (≈2 wks)

| # | Item | Size | AC | Deps |
|---|------|------|----|------|
| P2.1 | **AUD-14 config consolidation** (pulled forward — posture prerequisite; 161 env reads, ≥3 truthy conventions) | M | one `env_config` + one `truthy()`; LOCAL_ONLY code floor kept (BUG-14 lesson) | — |
| P2.2 | **Nightly consolidation/decay job** in `scheduler_service` + LivingMemory wired at the (single) turn seam | M | after N faked turns + one nightly tick, consolidated memories retrievable; decay observable | P1.1 |
| P2.3 | **Dormant-module disposition**: wire-or-park `ensemble`/`learning`; park `profile_extractor` (zero callers) with a BACKLOG row | S | nothing both dormant and advertised | P2.2 |
| P2.4 | **Product Posture (D1, approved)**: settings-DB-backed named posture composing `JARVIS_HARDENED`; wave 1 = recall+embed+KG+persona/honesty, wave 2 = kernel+budgets+guardrails-REDACT; consent screen as the final onboarding step; exception recorded in AGENTS.md | M | golden loops green under BOTH postures; `GET /api/security/posture` shows named posture + per-flag provenance; companion-eval gate green; p95 latency AC | P0.3, P2.1, P2.2 |
| P2.5 | **Install smoke path**: ~30s boot + `/readyz` + one faked turn; full suite behind `--dev` | S | fresh install ≤5 min, never a mid-install wall of red | P0.6 |

### Phase 3 — Finish the Designed Surface (owner decision D7; ≈3–4 wks, agent-parallel)

| # | Item | Size | AC | Deps |
|---|------|------|----|------|
| P3.1 | **Wire the 6 design-preview modes live** (Build, Comms, Finance, Health, Knowledge, Family) — Build→workflows/marketplace/sandbox; Comms→channels+pairing+Discord/Slack threads; Finance→watchlist+balance (mock parked → honest SEED label); Health/Knowledge/Family→plugin-gated with honest empty states. **Any surface blocked on owner keys/hardware → a BACKLOG blocker row, not a silent stub** | L (≈1 PR/mode) | zero "no backend wired yet" modes; `MODE_LIVE_KEYS` covers all 12; ghost manifests removed from the plugin gate (~22 real modules only) | P0.7 |
| P3.2 | **HUD_V2_REMAINING punch-list**: §2 Console depth (Settings inline editor, Prompt A/B+diff+rollback UI, Data Spaces CRUD, Secrets store form, Rooms create/send) · §4 cockpit (network task-fan, per-message TTS + mic input, streaming cognition SSE) · §5 TweaksPanel · §6 self-hosted fonts | L (2–3 PRs) | punch-list doc emptied or each remaining line has a BACKLOG blocker | P3.1 |
| P3.3 | ~~M2.1 chat/voice flow E2E~~ ✅ **done (#492)** — 6 Playwright flow tests green; serves as the P1.1 oracle | — | — | — |
| P3.4 | ~~M2.3 OpenAPI→TS typegen + CI gate~~ ✅ **done (#492)** | — | — | — |
| P3.4b | **M2.4 completion** (re-marked partial in #492): persist the eval-store baseline across nightly runs (actions/cache or committed snapshot) so baseline-compare actually bites | S | scheduled run N+1 diffs against run N; regression turns the lane red | — |
| P3.5 | **M3.1 mobile approval queue** over the unified funnel | M | phone approve/reject of a broker task e2e; PARITY.md row | P0.7 |
| P3.6 | **Q2 persona-consistency rail** (now scoring the right text) + **Q3 caring follow-ups** in the morning brief (golden loop #3) | M | brief contains yesterday's failed/blocked + a memory-grounded follow-up | P0.4, P2.2 |
| P3.7 | **Landing page (dev half)** from marketing/ + BRAND_BOOK tokens | S | blueprint AC | — |

### Phase 4 — WorldView active workstream (owner decision D4; parallel agent lane)

Order: **#258** startup/install parity → **#255** live WorldMonitor MCP contract test → **#254**
Signal-Layer cockpit mounted into the real Vite HUD → **#256** SignalLayerPlugin wired for
Jarvis/Argus → **#257** governance-safe recommendations (preview-only or real approval-queue
bridge — pairs with P0.7) → **#259/#265** demo narrative + polish → **#169** MCP write transport
(unblocks the last K2 slice: fold WorldView HMAC tokens as a kernel Capability) → **#170** live
Neo4j validation. *Honest cost note:* this keeps a second stack in the release/support cycle
through the partner window; mitigation = it stays runtime-opt-in (`JARVIS_WORLDVIEW`), CI lanes
stay path-filtered, and partners get it only if they ask.

### Phase 5 — Proof (owner-led, starts in parallel at week 1 — the true critical path)

1. ⭐B0 governed-autonomy run on the RTX box + record **AUD-0** and **H23.23** decisions in BACKLOG.
2. GitHub settings batch + MIT→Apache-2.0 flip.
3. **Partner release channel** (new, S): partners pin tagged releases; upgrade drill via the
   migration framework — 40 PRs/week against `main` would burn partners in days.
4. Recruit 1–3 partners; north-star measured on a non-owner install ≥2 weeks — **re-baselined
   post-P0.2** (pre-fix metrics exclude all web-chat activity and are contaminated).
5. 72h unattended soak → tag **1.0.0**. MOONSHOT §4: no gate skipped.

### Phase 6 — Guard the freeze (continuous)

- **Park-list CI guard** (S): lint fails on diffs touching frozen modules (`image_gen`,
  `media_gen/media_skill`, `desktop_operator`, `browser_agent`, `screen_grounding`,
  `satellite_hub`, `node_mesh`, `e2e_sync`, `wyoming`, `training/`, `rust/`) without an `unpark:`
  tag — at 40 agent-PRs/week the freeze needs a machine, not a norm. (WorldView explicitly NOT on
  this list per D4.)
- BACKLOG sync per protocol; test-strategy note added to AGENTS.md: **new tests must be golden-loop
  behavioral by default; wiring/parity tests only for new route surfaces.**

## Verification

- Each Phase-0 fix ships with its golden loop; the 5 loops (chat→memory · propose→inbox→approve→
  execute→audit · brief-with-follow-up · kill-switch-halts-all · onboarding→posture→first-chat)
  run in default CI, twice (default + product posture), LLM faked only at `generate()`.
- P1.1 verified by golden loops + M2.1 Playwright E2E on the live SSE path.
- P2.4 verified by posture-doubled loops + companion-eval nightly gate + p95 latency budget.
- P3.x HUD work verified by vitest + `tsc` + `hud-v2-build` stale-bundle gate + the A11y/E2E lanes.
- Final: ⭐B0 manual runbook + 72h soak + a non-owner install reporting north-star for 2 weeks.

## Critical files

`agents/core/orchestrator.py` (F1/F7/AUD-13 — lines 699–1450) · `agents/core/autonomy/queue.py`
(+`worker.py`, F3) · `agents/core/settings_db.py` (F2) · `agents/core/cognition_trace.py` (F4) ·
`agents/core/llm/hybrid_router.py` (F5) · `serve.py`+`agents/web.py` lifespan (F6) ·
`agents/core/scheduler_service.py` (P2.2) · `agents/core/security/hardened.py` (P2.4 seed) ·
`frontend/src/app.tsx`+`modes*.tsx`+`gap.tsx` (P3.1/P3.2) · `docs/design/HUD_V2_REMAINING.md` ·
`BACKLOG.md` (ORIZONT 26 registration).

## Risks

- **P1.1 (AUD-13) breaks SSE subtly** → golden loops + M2.1 are the oracle; fallback = piecemeal
  extraction keeping dual paths.
- **Waking cognition hurts latency/quality on one-model boxes** → posture waves + eval gate +
  p95 AC; worst case ship wave 1 only for 1.0.
- **P0.7 blast radius** (digest/scheduler flows that read `proposed`) → named regression ACs.
- **WorldView active + partner window** → support surface doubles; keep it ask-only for partners.
- **Partner recruitment is calendar-bound** → Phase 5 starts week 1, never compressed.
