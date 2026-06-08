# Jarvis Hub — Future Developments Report

> Generated: 2026-06-08 · Owner: Andrei · Horizon: v1.0.0 gate → post-1.0
> North star: [MOONSHOT.md](../MOONSHOT.md) · Plan of record: [BACKLOG.md](../BACKLOG.md) · Launch gate: [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md)
>
> Snapshot (reconciled 2026-06-08): **171/196 items, 912/1119 SP (~82%)** across H1–H17 (the v1.0 scope),
> **plus** O18 mobile (9/10) and O19 WorldView (33/33 ✅, standalone). Test suite: **1,764 passed / 1 skipped**.

## 1. Where we stand

Phase 0 (Foundation) and the bulk of Phase 1 (Complete & Trustworthy) are shipped. The 2026-06-03
competitive-edge + frontier wave landed H10 (29/30), H14/H16/H17 (4/4 each), and the H12 core. WorldView
(O19) shipped end-to-end as a standalone OSINT product with governed JARVIS integration, deep-reviewed and
merged. What stands between us and **v1.0.0 = entire backlog done** is a finite, well-scoped set of work —
mostly hardware/model-bound or external-surface — plus the manual-test runbook human gate
([docs/MANUAL_TESTING.md](MANUAL_TESTING.md) §0) and a near-term code-audit hardening sprint (§4).

## 2. Remaining 1.0.0-gate work (must ship before tag)

| Area | Items | SP | Nature | Notes |
|---|---|---|---|---|
| **H10 writebacks** | H10.30 (Notion/GitHub/GCal native writes) | 8 | Integration | Last open H10 item; Pepper/Hephaestus first. |
| **H11 Platform Parity** | H11.1 Tauri desktop · H11.2 Rust hot-path crates · H11.3 SFT/GRPO pipeline · H11.4 WASM sandbox | 55 | **High-cost** (GPU/Rust/native build) | The heaviest remaining block. H11.3 unblocks H12.14 + closes the learning loop. |
| **H12 open (incl. Track E)** | H12.7 passive capture · H12.8 mic-satellite split · H12.13 E2E device sync · H12.14 fine-tuned agentic model · H12.16–25 governed OpenClaw parity | 95 | Mixed (privacy-sensitive + reach/UX) | Track E (H12.16–25) is reach/UX parity under governance — none touch a non-negotiable. |
| **H13 model tier** | H13.1 strict-local VLM (Qwen3-VL-8B) · H13.3 speculative decoding · H13.4 MoE default refresh | 18 | **Hardware/model** | H13.1 is the largest *new* capability with no cloud; verify GGUF + KV-cache on 24GB. |
| **H15 computer-use** | H15.1 browser-use behind approval queue · H15.2 local screen-grounding · H15.3 isolated PiP operator | 29 | Frontier | H15.1 is the lowest-risk entry; H15.2 depends on H13.1. |

Already-done-in-scope (no action): H14 (living memory) 4/4, H16 (agentic-web) 4/4, H17 (provable trust) 4/4.
**Gate effort: ~205 SP open + the human runbook sign-off.**

## 3. WorldView (O19) — follow-ups & where it goes next

O19 is 33/33 and merged; the deep review is complete with two tracked follow-ups:

- **[#169](https://github.com/andrei649/jarvis-hub/issues/169) — MCP write-tool runtime transport.** The auth
  format for `watch_aoi`/`reconstruct_event` is closed and cross-language-pinned (shared fixtures asserted by both
  Python and TS suites in CI). What remains is the *transport*: spawning the stdio MCP server from
  `agents/core/mcp/client.py` and invoking write tools with the minted capability token at runtime. This is the
  same unbuilt stdio/SSE transport that H10.5 also defers.
- **[#170](https://github.com/andrei649/jarvis-hub/issues/170) — Neo4j property-search live validation.** Validate
  the KG property-search path against live Neo4j (it's currently unit-tested against mocked HTTP + in-memory parity).

**Next for WorldView (post-1.0 productionization):** turn the "delivered code, deploy-gated" workstreams into a
running deployment — the live-net egress hops (ADS-B/AIS/TLE/EW) + Kafka are coded but unproven at scale; prove
the WS1 SLO (50k msg/s, lag<60s, as-of-T p95<300ms) on real infra (KEDA + PgBouncer + replica); prove WS5 scale
(1M+ points @60fps via tiles, 10k concurrent WS, DR RPO≤5m/RTO≤30m). Then finish the JARVIS-side MCP transport
(#169). Productize the opt-in plugin so Argus/Athena/Stark query WorldView from natural language with provenance.

## 4. Open code-audit debt — near-term hardening track

From the 2026-06-04 audit, **re-baselined 2026-06-08** against current code (a full code review confirmed several
items already fixed). Risk is low on single-user/LAN but real under concurrency / non-LAN exposure.

| Item | Status (2026-06-08) | Risk | Fix |
|---|---|---|---|
| **`Orchestrator.process()` missing** (new) | Fixed in the 2026-06-08 hardening pass | HIGH (was silent no-op) | Implemented the method; LLM-backed autonomy tasks + nightly reflection now produce output. |
| **`_record_interactions` error heuristic** (new) | Fixed in the 2026-06-08 pass | MEDIUM | Structured `[agent error/timeout]` match, not substring `"error:"`. |
| **BUG-5** session_id race on shared orchestrator | Open (gated off by default) | HIGH under concurrency | Per-request `TurnContext` (scoped in O21 H21.0). |
| **BUG-7 / NEW-1** httpx/MCP/queue lifecycle | Fixed in the 2026-06-08 pass | MEDIUM | `orch.aclose()` wired into shutdown; all backends closed. |
| **BUG-11** edit-after-block re-gating | Fixed in the 2026-06-08 pass | MEDIUM | Re-run `policy.decide()` on the full edited payload. |
| **BUG-3 / BUG-6 / BUG-8 / BUG-9 / BUG-10** | Already fixed in code | — | Backlog corrected to ✅. |
| **BUG-12** residual thread-safety | Partial (embedder lock added) | LOW | Remaining: `_spent_today` atomicity (single-worker today). |
| **HF-3 / HF-6 / HF-7** scanner gaps · DEV_MODE sandbox · admin-behind-proxy | HF-6/HF-7 fixed; HF-3 partial | MEDIUM | Couples with the pre-1.0 security review (HF-2 manual gate). |
| **CLN-2 / CLN-3** god-object orchestrator · web.py (now 4636 LOC / 233 routes) | Open (P3) | — | Continue #118 split; APIRouter-per-domain. |

This is ~1–2 focused sprints and should land **before the manual-test security sign-off**, since several items
(BUG-5, HF-3) are exactly what a pen-test surfaces.

## 5. Post-1.0 horizons

- **O20 — Hermes Mining (0/6, ~47 SP).** Net capabilities from `hermes-agent` adopted *under governance*.
  Headline: **H20.1 Tool-RPC in sandbox (`execute_code`)** — zero-context-cost pipelines (a script orchestrates
  N tool-calls without per-step LLM round-trips), secrets never readable in-sandbox (over H15.4 secret broker).
  Then H20.2 OpenRouter + hot-swap, H20.3 runtime ContextCompressor (ties to sleep-time compute).
- **O21 — Cognition (0/10, ~64 SP) — the most important theme.** A cognitive cortex: unlimited append-only
  memory (forgetting = demotion, never deletion), consistent-but-alive personality anchored on honesty (HEXACO,
  structural anti-sycophancy), neuroplasticity (re-embedding on better models). Architecturally it lands as one
  `agents/core/cognition/` package behind a `CognitionFacade` (1 line in the orchestrator → does not grow the
  god-object), reuses the H14 primitives already shipped, and its **H21.0 skeleton fixes BUG-5** via per-request
  `TurnContext`. North metric is conjunctive and un-gameable (mastery↑ with calibration-error↓, gated by a
  truth-audit). The deepest expression of moonshot thesis #2 (proactivity compounds) and #3 (trust by inspectability).

## 6. Recommended sequencing (tied to phase gates)

**Track 1 — Close the v1.0 gate (Phase 1 → v1.0.0).** Sequence by mission-fit and dependency, not horizon order:

1. **Hardening sprint first** (§4): finish BUG-12/HF-3, then fold BUG-5 into O21 H21.0. *Rationale:* MOONSHOT §5.5
   (production-grade) + these block the manual-test security sign-off. ~20 SP, no new dependencies.
2. **H13.1 strict-local VLM** — largest *new* $0 capability; unblocks H15.2. *Rationale:* serves thesis #1
   (local-first moat) and the "% tasks served locally" counter-metric. ~8 SP, hardware-bound.
3. **H15.1 governed browser-use** — lowest-risk computer-use entry, behind the existing approval queue.
   *Rationale:* the governed inverse of OpenClaw's ungoverned shell — the defensible wedge. ~8 SP.
4. **H10.30 writebacks + H12 Track-B/E reach** — the remaining integration/parity surface. *Rationale:* moves
   "works for Andrei" → "complete"; H12.16–25 are reach without touching non-negotiables. ~50–95 SP, parallelizable.
5. **H11 (Tauri/Rust/SFT/WASM)** last — highest cost, lowest mission-leverage at the gate; H11.3 can run in
   parallel since it unblocks H12.14. ~55 SP.
6. **Manual-test runbook sign-off** (the human gate) → tag **v1.0.0**.

**Track 2 — WorldView productionization** runs in parallel (separate stack, separate operator): #169 + #170, then
the deploy-gated WS1/WS5 SLO proofs. Does not block the JARVIS v1.0 tag.

**Track 3 — Post-1.0:** **O21 Cognition** is the priority theme (deepens the memory/honesty wedge and runs on idle
compute = the literal moonshot slogan), with **O20 H20.1** as the complementary actuation primitive. Start O21
H21.0 *during* Track 1 if it absorbs the BUG-5 fix.

> **Honest effort note:** the ~205 SP of open v1.0 work is front-loaded with hardware/model and native-build cost
> (H11 + H13 ≈ 73 SP) that the $0/local-first ethos can't shortcut. The cheapest, highest-mission wins are the
> hardening sprint and the governed-frontier entries (H13.1, H15.1). H11 is the honest long pole.
