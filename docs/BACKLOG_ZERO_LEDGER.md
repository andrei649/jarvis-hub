# Backlog Zero — Execution Ledger

> **Purpose.** This ledger is the Phase 0 inventory for the "Backlog Zero" autonomous execution
> protocol: a structured, one-row-per-open-item breakdown of every item in `BACKLOG.md` that is
> not fully `✅ DONE` — i.e. everything marked `🟡 PARTIAL`, `🌱 SEED`, `⬜ MISSING`, `🔨` (code
> delivered but live/scale proof outstanding), or carrying an explicit unresolved "remaining"/
> "rămâne"/"still open" tail, plus items with no status marker that read as not-yet-done. Fully
> `✅ DONE` items with no residual tail were swept and excluded. The goal is to drain this list to
> zero, ending every row in one of three terminal states: **SHIPPED** (a merged PR closes it),
> **OWNER-PACKET** (a complete, actionable decision/config packet has been handed to the owner —
> the ledger row's job is done even though the owner's own action is still pending), or
> **RESCOPED** (the owner explicitly re-scoped, deferred, or rejected it in writing).
>
> **Recount rule.** Re-verify every row's status against the current `BACKLOG.md` and `main` at
> the start of every run — a PR merged since this ledger was generated may have already closed a
> row. Do not trust this snapshot beyond a spot-check; `BACKLOG.md` itself is the source of truth.
> Rows flagged `NEEDS-RECOUNT` below are cases where this sweep found internally conflicting
> status markers in `BACKLOG.md` itself (e.g. one section claims a sub-item done, another still
> lists it pending) — verify those first.
>
> **Generated:** 2026-08-28T06:22:41Z · **Branch:** `claude/nerva-backlog-zero-0k83jc` ·
> **Head SHA:** `3dbf7e378c332fd03fd9f6eb045b54aed1b5fcbd` · Source: `BACKLOG.md` (2938 lines) swept
> top to bottom in full against the vocabulary in `AGENTS.md`, `MAX.md`, `MOONSHOT.md` §4/§5,
> `.github/ai-development-policy.json`, and `docs/MAX_RUNS.md` (rows 000–013).
>
> **Ordering** follows `MAX.md` §3.1: (a) 1.0 proof-track blockers first, (b) `PARTIAL` before
> `MISSING`/`SEED`, (c) small quick wins, (d) blocking debt, then the rest in roughly `BACKLOG.md`'s
> own order. Sections below are priority tiers, not BACKLOG.md headings.

---

## Tier 1 — 1.0 proof-track blockers (Lane A critical path + direct dependents)

| id | section | bucket | size | dependencies | terminal-state target |
|----|---------|--------|------|---------------|------------------------|
| A1 | Handoff Fable — Lane A, line 1059 | OWNER-DECISION | XL | Real RTX hardware; chapter-15 ADV manual pass; is **the** 1.0 gate | OWNER-PACKET |
| A8 | Handoff Fable — Lane A, line 1066 | OWNER-DECISION (hardware) | XL | Real HA install, Frigate hardware, media-output devices | OWNER-PACKET |
| A8-iv | Handoff Fable — Lane A, line 1066 sub-item | AI-EXEC | M | Redesign per `docs/superpowers/plans/2026-08-02-qa4-ungoverned-counter-park.md`: persist kernel decision at `govern_enqueue`, read at worker seam | **CLOSED** — persisted-stamp redesign shipped in #946 (2026-08-26, pre-dates this ledger's generation but was missed by the initial sweep); the two still-missing snapshot fields (`enabled`, scalar `ungoverned_actions`) shipped this run (2026-08-28, `agents/core/kernel/metrics.py`) — see `BACKLOG.md` line 1066 and `docs/MAX_RUNS.md` |
| H23.23 | H23 table, line 1316 | OWNER-DECISION | S | Blocks A2; decision already drafted at `docs/decisions/2026-07-11-single-user-1.0.md`, needs owner ratification only | OWNER-PACKET |
| AUD-0 | Hardening audit, line 1965 | OWNER-DECISION | S | Same underlying ask as A2/H23.23 ("record AUD-0"); not separately actionable | OWNER-PACKET |
| A2 | Handoff Fable — Lane A, line 1060 | OWNER-CONFIG (hardware/time) | L | H23.23 ratification; `scripts/soak_report.py` tooling already ✅ done | OWNER-PACKET |
| H23.4 | H23 table, line 1296 | OWNER-CONFIG | S | Same shape as A2 — run `--live-gate` on owner box against real local model | OWNER-PACKET |
| T-0.63 | Competitive-Gap, line 1248 | OWNER-CONFIG | M | Duplicate of A2 (72h soak) + failure injection | OWNER-PACKET |
| A3 | Handoff Fable — Lane A, line 1061 | OWNER-CONFIG | S | Owner tail only: dismiss stale Dependabot alerts in GitHub UI, wait on next.js for worldview moderates, Expo SDK bump on device | OWNER-PACKET |
| A4 | Handoff Fable — Lane A, line 1062 | OWNER-CONFIG | S | GitHub org settings batch | OWNER-PACKET |
| SEC-4 | Security route-policy gate, line 1831 | OWNER-CONFIG | S | Same task as A4 (promote matrix/parity to required branch-protection checks) | OWNER-PACKET |
| CQ-2 | CodeQL alerts, line 1881 | OWNER-CONFIG | S | Same GitHub-settings batch as A4 | OWNER-PACKET |
| CQ-3 | CodeQL alerts, line 1882 | OWNER-CONFIG | S | Needs an owner paste of the ~12 untriaged alerts (no MCP code-scanning-list tool available) | OWNER-PACKET |
| A5 | Handoff Fable — Lane A, line 1063 | OWNER-DECISION | S | Prep (TRADEMARKS.md, Apache-2.0 staged) already done; flip = 3 owner commands at the LICENSE_DECISION-specified time | OWNER-PACKET |
| A6 | Handoff Fable — Lane A, line 1064 | OWNER-DECISION | M | Dev half (#512) done; owner must record the actual demo video | OWNER-PACKET |
| H23.22 | H23 table, line 1315 | OWNER-DECISION | S | Duplicate of A6 | OWNER-PACKET |
| T-0.59 | Competitive-Gap, line 1244 | OWNER-DECISION | S | Duplicate of A6, plus README hero image | OWNER-PACKET |
| GAP-0 | Nerva vs Hermes gap analysis, line 604 | OWNER-DECISION | — | "Distribution is the binding constraint" — feeds directly into A7; no code fix, a GTM/positioning call | OWNER-PACKET |
| A7 | Handoff Fable — Lane A, line 1065 | OWNER-DECISION | XL | Depends on A1 confidence + A6 demo + GAP-0 positioning | OWNER-PACKET |
| A9 | Handoff Fable — Lane A, line 1067 | OWNER-DECISION | — | Terminal gate: only after A1, A7, A8, and every other owner gate | OWNER-PACKET |

---

## Tier 2 — Immediate quick wins (small, mostly config, minutes of owner time)

| id | section | bucket | size | dependencies | terminal-state target |
|----|---------|--------|------|---------------|------------------------|
| H22.4 | ORIZONT 22, line 2869 | OWNER-CONFIG | XS | Runbook already written (`docs/GPU_RUNBOOK.md` §H22.4); just needs a GPU-box validation run | OWNER-PACKET |
| H22.7 | ORIZONT 22, line 2872 | OWNER-CONFIG | XS | SKILL.md files delivered; `superpowers` plugin install = 1 host command | OWNER-PACKET |
| H22.8 | ORIZONT 22, line 2873 | OWNER-CONFIG | XS | Scaffold delivered; install `codebase-memory-mcp` binary + trial `index_repository` | OWNER-PACKET |
| LMS-VALIDATE | LM Studio control, line 2024 | OWNER-CONFIG | XS | Validate end-to-end against a real `lms` binary on the RTX 5090 box (current tests are mock-only) | OWNER-PACKET |
| LMS-GEMMA-ID | LM Studio control, line 2033 | OWNER-CONFIG | XS | Confirm the real LM Studio id for Gemma 4 12B (`google/gemma-4-12b` is a placeholder) | OWNER-PACKET |
| FB4-BENCHMARK | Alpha signals, line 1100 | OWNER-CONFIG | S | Skeleton table exists (`docs/HARDWARE_BENCHMARKS.md`); owner fills measured 8/12/16/24GB numbers | OWNER-PACKET |
| H23.2 | H23 table, line 1294 | OWNER-CONFIG | S | Allowlist/pinning/reproducibility rail all done; only the live `/v1/models` fetch is a host seam | OWNER-PACKET |

---

## Tier 3 — Highest-leverage AI-buildable work (explicit next-pointer first, then security/authority items needing R3 review, then stale-status items needing recount)

| id | section | bucket | size | dependencies | terminal-state target |
|----|---------|--------|------|---------------|------------------------|
| T-0.22 | Competitive-Gap, line 1199 | AI-EXEC | M | **Explicit next-pointer from `docs/MAX_RUNS.md` row 013** ("Finish 0.22's last item: uninstall"). No-telemetry gate + install/update all done; needs a provable **uninstall** path, mirroring the forget/export erasure invariant | **CLOSED** — shipped in #971 (run 014, 2026-08-28) |
| SEC-B6 | Governance-rails audit, line 770 | R3-REVIEW-GATED | S | Code landed via #896 with green CI, but zero independent review was ever submitted; needs a fresh exact-head R3 review only, no new code | SHIPPED (after review) |
| K2-ENFORCEMENT | ORIZONT 24 Track K, line 1382 | R3-REVIEW-GATED | M | Per-action enforcement of already-issued capability tokens + fold WorldView HMAC tokens in as one kind; closes B1; touches kernel authority surface | SHIPPED (after R3 review) |
| SEC-B4 | Governance-rails audit, line 723 | R3-REVIEW-GATED | M | SSRF IP-pinning for the Playwright path + central `PluginHTTPClient`; needs a live network/browser host to demonstrate (chapter 15 ADV-142) | SHIPPED (after R3 review) |
| SEC-B5 | Governance-rails audit, line 725 | R3-REVIEW-GATED | M | Taint by dataflow, not just declared origin — proactive/recall/ambient payloads rebuilt outside an inbound turn drop ingress taint | SHIPPED (after R3 review) |
| B7-TASK-MEDIATION | Nerva 2.0 program control, ~line 225–241 | OWNER-DECISION | — | PR #918 merged under an integrator HOLD that still stands; #818 remains `owner_hold`; owner must record a retain/revert decision + reconcile the ledgers (#757/#778/#818) | OWNER-PACKET |
| GOVERNANCE-WAVE-HOLD | Nerva 2.0 program control, line 162 | OWNER-DECISION | — | #911 (SEC-B8) and #916 landed with green CI but each carries a recorded post-merge integration HOLD; owner retain/revert decision needed | OWNER-PACKET |
| E1/E6/E9-AUTHORITY-CEILING | Nerva 2.0 program control, line 151 | R3-REVIEW-GATED | M | #859/#860/#861/#864 merged before their #856 predecessor was validated; #913 now satisfies the predecessor but retained bytes still need fresh post-B2 acceptance decisions | SHIPPED (after R3 review) |
| K4-HUD | ORIZONT 24 Track K, line 1384 | — | S | **NEEDS-RECOUNT**: K4's own row says "Pending: one-tap HUD control" but H23.3 (line 1295) says the HUD kill-switch panel is already done. Re-verify against current `frontend/src` before treating as open | NEEDS-RECOUNT first |
| V1-LIVE-CONTRACTS | ORIZONT 24 Track V, line 1395 | AI-EXEC | M | Per-capability LIVE reality-harness contracts (real key/network, networked nightly lane) + durable cross-process promotion (folds into V3) | SHIPPED |
| V3-SUBAGENT-CONTRACTS | ORIZONT 24 Track V, line 1397 | AI-EXEC | S | Subagent ad-hoc return-dict shapes aren't statically introspectable; needs a runtime-capture variant of the interface-contract drift gate | SHIPPED |
| V4-LIVE-EVAL-GATE | ORIZONT 24 Track V, line 1398 | OWNER-CONFIG | M | Live-model eval on a persistent owner/live runner + hard merge-blocking on real-usage north-star data (offline CI has none) | OWNER-PACKET |
| H20.R1-RESIDUAL | ORIZONT 20 Agent Runtime v2, line 2784 | AI-EXEC | M | **NEEDS-RECOUNT**: "still open" list (governed file/process tools, multimedia/binary tools, browser SSE tool-lifecycle rendering, cloud-provider tool-call transports, model-directed MCP discovery/subagent delegation) predates ORIZONT 28's H28.1–6, which may have closed the browser/desktop-control portion. Re-verify against current code first | NEEDS-RECOUNT first |
| BUG-2b.2 | Bugs & Hot Fixes, line 2206 | AI-EXEC | S | **NEEDS-RECOUNT**: drag-drop canvas workflow frontend tests (pointer events/SVG/layout/edges) — status ambiguous; 2b.1 (E2E) confirmed done via H23.17, 2b.3 (voice) confirmed done via M2.6, but 2b.2 has no explicit closure note anywhere in the file | NEEDS-RECOUNT first |

---

## Tier 4 — Other PARTIAL items, AI-buildable (Competitive-Gap themes + scattered residuals, roughly BACKLOG.md order)

| id | section | bucket | size | dependencies | terminal-state target |
|----|---------|--------|------|---------------|------------------------|
| T-0.20 | Competitive-Gap, line 1197 | AI-EXEC | M | Vault core done; needs router/HUD surface + wiring into export (#303) and the forget flow, same governed pattern as Canvas | SHIPPED |
| T-0.21 | Competitive-Gap, line 1198 | AI-EXEC (catalog) + OWNER-CONFIG (fetch source) | M | Pack manifest/verify/install done; needs a curated pack catalog + owner-gated fetcher | SHIPPED + OWNER-PACKET |
| T-0.25 | Competitive-Gap, line 1202 | AI-EXEC | S | Mostly superseded by H28.4 (line 1257) — only remaining boundary is owner-host validation with real Windows UIA + installed Playwright Chromium (dup of A8) | OWNER-PACKET |
| T-0.26 | Competitive-Gap, line 1203 | AI-EXEC + OWNER-CONFIG | M | Host-side phone transfer + transcript sync | SHIPPED |
| T-0.28 | Competitive-Gap, line 1205 | AI-EXEC | S | Consent + barge-in→HUD wiring (BUG-2b.3 dependency now closed via M2.6) | SHIPPED |
| T-0.29 | Competitive-Gap, line 1206 | AI-EXEC | M | PWA + signed installers | SHIPPED |
| T-0.37 | Competitive-Gap, line 1214 | AI-EXEC | M | Ontology + cross-agent sharing; provenance for the derived knowledge/embedding phases | SHIPPED |
| T-0.41 | Competitive-Gap, line 1218 | AI-EXEC | S | Wire a live sidecar signal feed through the router into per-agent digests | SHIPPED |
| T-0.45 | Competitive-Gap, line 1222 | AI-EXEC | S | Apply contract templates to richer draft-before-send contracts beyond payments/signal/plugin | SHIPPED |
| T-0.49 | Competitive-Gap, line 1234 | AI-EXEC | M | Interactive approval-gated timeline over `canvas.py`/`timelineMarkers.ts`; no explicit remaining spec — needs its own scoping pass | SHIPPED |
| T-0.50 | Competitive-Gap, line 1235 | AI-EXEC | M | Visual studio surface + governed platform-executor integration (publication stays kernel-held) | SHIPPED |
| T-0.51 | Competitive-Gap, line 1236 | AI-EXEC | M | Model-side draft generation + fetch choreography feeding `grounded_plan.py` (host/LLM seam) | SHIPPED |
| T-0.52 | Competitive-Gap, line 1237 | AI-EXEC + OWNER-CONFIG | M | HUD-footage capture + assembly tooling (storyboard/shot-list already done) | SHIPPED |
| T-0.53 | Competitive-Gap, line 1238 | AI-EXEC | S | Expose the design manifest via a route/HUD panel + Figma token sync | SHIPPED |
| T-0.55 | Competitive-Gap, line 1240 | OWNER-DECISION | S | SLA definition — a doc/owner artifact, not code | OWNER-PACKET |
| T-0.58 | Competitive-Gap, line 1243 | AI-EXEC | M | Model/domain/content pack types (separate from the skill-marketplace pack type already shipped) | SHIPPED |
| T-0.64 | Competitive-Gap, line 1249 | AI-EXEC + OWNER-CONFIG | M | Command-service core done; needs Tauri host overlay + global shortcut registration (owner-gated) and wiring plan kinds into the live HUD (AI-side) | SHIPPED + OWNER-PACKET |
| T-0.66 | Competitive-Gap, line 1251 | AI-EXEC + OWNER-CONFIG | M | Wire connector builders into the executor behind the approval queue (AI-side) + owner OAuth setup per provider | SHIPPED + OWNER-PACKET |
| H5.16 | ORIZONT 5, line 2250 | AI-EXEC | S | Synthesize TTS *while* the chat streams (the `SentenceAggregator` building block is ready) | SHIPPED |
| H18.24 | ORIZONT 18 mobile, line 2574 | AI-EXEC | M | Native voice orb — port `frontend/src/orb.tsx`'s state→visual contract to the native mic surface | SHIPPED |
| H18.25 | ORIZONT 18 mobile, line 2575 | AI-EXEC | M | Native briefing wall — port `wall.tsx`/`burst.tsx` chrome + push-to-talk, same fail-closed mic rule | SHIPPED |
| H30.8 | ORIZONT 30, line 1705 | AI-EXEC | M | Ambient light bridge (assistant state → LAN strip, WLED first); code buildable, real device is owner-side validation | SHIPPED |
| WV-170 | ORIZONT 19 WorldView, line 2593 | AI-EXEC | S | GitHub issue #170: validate real Neo4j property-search from KG sync (only #169 was closed via #594) | SHIPPED |
| H34.3 | ORIZONT 34 Mission Control, line 1808 | AI-EXEC | S | Dev-swarm PR/CI feed (open PRs + check status) next to the lock panel, via `oracle_bridge` plugin + `GITHUB_TOKEN` | SHIPPED |
| TASK-3 | Bugs & Hot Fixes, line 2209 | OWNER-DECISION | M | Residual defense-in-depth: wrap email/web-webhook input in `TaintedValue` at the channel boundary + gate irreversible tool calls through `QuarantinePolicy.check_step` — explicitly an "owner architecture call" (distinct from the already-shipped H23.6 channel-ingress taint) | OWNER-PACKET |
| GAP-1 | Nerva vs Hermes gap analysis, line 609 | AI-EXEC | L | A8 sequencing note: media is driver-missing (no `MediaDriver` impl / injection point), acquisition is caller-missing (needs a contract factory + trigger) | SHIPPED |
| GAP-6 | Nerva vs Hermes gap analysis, line 658 | AI-EXEC | S | Cheapest real win: the 5 governed webhook channels need no extra pip dep, only `JARVIS_WEBHOOK_CHANNELS` set — surface this more prominently | SHIPPED (doc/config surfacing) |
| GAP-7 | Nerva vs Hermes gap analysis, line 664 | AI-EXEC | S | Restate the Hermes verdict in `NERVA_VISION.md` §8 (doc correction, two overclaims to drop) | SHIPPED |
| GAP-8 | Nerva vs Hermes gap analysis, line 671 | AI-EXEC | S | Re-baseline `NERVA_VISION.md` §3/§4 percentages + §98's action-kind count (doc correction) | SHIPPED |
| GAP-9 | Nerva vs Hermes gap analysis, line 674 | AI-EXEC | M | Honesty debt: `/api/house/state.presence` always `[]` in prod; ONVIF needs undeclared `wsdiscovery`; camera VLM needs a self-hosted server; `environments/` never executes (no SSH transport exists); README voice-stack overclaim | SHIPPED |
| MOBILE-PHONE-SURFACE | Governance-rails audit, line 883 | OWNER-DECISION | M | Web HUD isn't reachable from a phone by design; the supported LAN path is undocumented; 26/26 scheduled mobile-chrome E2E runs have failed. Owner must decide: native `mobile/` app is the phone story (drop `mobile-chrome` from the matrix) OR make the web HUD genuinely responsive | OWNER-PACKET |
| E731-CONTINUITY-IDENTITY | B3/Continuity Core mapping, line 250 | AI-EXEC | M | Jarvis's own Identity Manifest has no destination issue — #762/E4 only covers Howard's preference prediction, not Jarvis's continuity identity | SHIPPED |
| ACTION-KERNEL-FLIP-CRITERIA | Docs-vs-code accuracy pass, line 571 | OWNER-DECISION | S | Define the flip-on criteria for `JARVIS_ACTION_KERNEL` + `JARVIS_UNIFIED_ACTION_API` — when does the kernel become the default rail? | OWNER-PACKET |
| H18.10 | ORIZONT 18 mobile, line 2562 | AI-EXEC | — | Perpetual bridge-parity task by design ("mereu deschis") — not a discrete deliverable; keep `mobile/PARITY.md` current whenever a browser feature ships | ongoing (never terminal) |

---

## Tier 5 — MISSING / SEED items and owner-config-only "flip a switch" wins

| id | section | bucket | size | dependencies | terminal-state target |
|----|---------|--------|------|---------------|------------------------|
| LVP-GOOGLE-OAUTH | Live-vs-Plumbing, line 924 | OWNER-CONFIG | XS | Google OAuth → real email + calendar | OWNER-PACKET |
| LVP-SPOTIFY-OAUTH | Live-vs-Plumbing, line 925 | OWNER-CONFIG | XS | Spotify OAuth → real playback control | OWNER-PACKET |
| LVP-INSTALL-ENGINES | Live-vs-Plumbing, line 926 | OWNER-CONFIG | S | `faster-whisper`/`edge-tts`/`kokoro`/`playwright`/`beautifulsoup4`/`discord.py`/`slack_sdk` | OWNER-PACKET |
| LVP-HOME-ASSISTANT | Live-vs-Plumbing, line 927 | OWNER-CONFIG | S | LAN Home Assistant + `JARVIS_HOUSE_BRAIN`/`JARVIS_HOME_ASSISTANT` | OWNER-PACKET |
| LVP-FRIGATE | Live-vs-Plumbing, line 928 | OWNER-CONFIG | S | Frigate NVR + household consent | OWNER-PACKET |
| LVP-COGNITION-FLIP | Live-vs-Plumbing, line 929 | OWNER-CONFIG | XS | Flip cognition master posture + a local LLM | OWNER-PACKET |
| LVP-TELEGRAM-TOKEN | Live-vs-Plumbing, line 930 | OWNER-CONFIG | XS | Telegram bot token → `channel.reply` | OWNER-PACKET |
| LVP-ING-LIBRA-FETCH | Live-vs-Plumbing, line 934 | AI-EXEC | M | Extend balance burn-rate to a real ING/Libra transaction-fetch API (CSV path already done) | SHIPPED |
| LVP-PAYMENT-RAIL | Live-vs-Plumbing, line 964 | OWNER-DECISION | XL | Real payment adapter (AP2/ACP/x402) at `payments.settle()` — explicitly "moves money", owner decision required | OWNER-PACKET |
| LVP-MEDIA-DESKTOP-NODE-ACTUATORS | Live-vs-Plumbing, line 965 | AI-EXEC + OWNER-CONFIG | L | Media/desktop/node actuators, owner-wired host seams (largely superseded by ORIZONT 28/29 — re-verify residual scope) | SHIPPED + OWNER-PACKET |
| LVP-VISION-ARGUS-CODE | Live-vs-Plumbing, line 966 | AI-EXEC | L | `agents/vision`, `agents/argus` real implementation — currently persona markdown only, zero code | SHIPPED |
| LVP-HESTIA-WIRING | Live-vs-Plumbing, line 969 | AI-EXEC | M | Wire `agents/hestia`'s reads/proposals onto the already-shipped `agents/core/house/**` modules | SHIPPED |
| B7-HERMES-WIRING | Handoff Fable — Lane B, line 1079 | AI-EXEC | L | Hermes v3 Phases 3/5/6 live wiring (file-RPC exec, gateway sessions, cron) — primitives merged, on-demand only | SHIPPED |
| H12.26 | ORIZONT 12, line 2458 | AI-EXEC | L | Binary artifact store (visual-artifact lane wave 2) — explicitly "Not started"; design spec exists at `docs/superpowers/specs/2026-07-11-artifact-store-wave2.md` | SHIPPED |
| T-0.90-1.0 | Competitive-Gap, line 1255 | mixed | XL | Freeze/RC/Partner/Burn-In/Owned release gates; promote eval→required gate; ties directly to A6/A7 | OWNER-PACKET |
| H12.14 | ORIZONT 12, line 2437 | OWNER-CONFIG | M | Model agentic mic fine-tuned — GPU-host runbook exists (`docs/GPU_RUNBOOK.md`), not yet run | OWNER-PACKET |
| H13.3 | ORIZONT 13, line 2485 | OWNER-CONFIG | S | Speculative decoding — GPU-host runbook exists, config-only, not yet run (part of M4's GPU-opportunistic list) | OWNER-PACKET |

---

## Tier 6 — Blocking/architectural debt (post-1.0, P2, large)

| id | section | bucket | size | dependencies | terminal-state target |
|----|---------|--------|------|---------------|------------------------|
| AUD-13 | Hardening audit, line 1988 | AI-EXEC | L | Turn-pipeline de-dup + service container: one `PromptBuilder`+`_preprocess_turn`; extract context/dispatch/persist; retire `orch` back-refs + `sys.modules` indirection. Continues CLN-2 | SHIPPED |
| AUD-15 | Hardening audit, line 1990 | AI-EXEC | L | Client consolidation: retire HUD v1, make v2 the Tauri target, extract shared `@jarvis/client`; remove remaining `@ts-nocheck`, move toward `strict` | SHIPPED |
| AUD-18 | Hardening audit, line 1993 | AI-EXEC | M | Remaining scale/DX polish: Qdrant-by-default at scale, lazy plugin instantiation, Vite code-split, CORS/loaders polish (several sub-items already done) | SHIPPED |
| AUD-14 | Hardening audit, line 1989 | AI-EXEC | S | ~104 remaining plain `env_str`-equivalent reads — cosmetic, migrate opportunistically in files already touched | SHIPPED |

---

## Tier 7 — Standalone side-product, lower priority (WorldView scale/infra proof)

| id | section | bucket | size | dependencies | terminal-state target |
|----|---------|--------|------|---------------|------------------------|
| WV-SCALE-PROOF | ORIZONT 19 WorldView WS1–WS5, lines 2632–2687 | OWNER-CONFIG | XL | Every `H19.1.x`–`H19.5.x` item has its algorithm/code delivered, but the "Rămâne" tail is real-scale/live-infra proof: live Kafka egress hop for ADS-B/AIS/TLE/EW sources, KEDA 50k msg/s load test, UI provenance surface, 1M-point@60fps tiles, 10k concurrent WS clients, multi-AZ DR game-day. Needs live cloud/K8s infra + load-test hardware. Standalone product (`worldview/`), not on the core Nerva critical path — candidate for explicit owner re-scope/deprioritization rather than execution | RESCOPED (recommend) or OWNER-PACKET |

---

## Notes on aggregation

Several BACKLOG.md IDs name the *same* underlying piece of work under different headings (the file
has accreted parallel audit passes over months). Rather than silently merging them — which would
violate "the item's own identifier as BACKLOG.md names it" — every such ID gets its own row above,
with the duplicate relationship called out in its `dependencies` column. The known duplicate
clusters are:

- **72h soak / AUD-0 / H23.23 / H23.4 / T-0.63** — all the same owner-run soak-and-live-gate work.
- **A4 / SEC-4 / CQ-2 / CQ-3** — all the same GitHub-settings-and-triage owner batch.
- **A6 / H23.22 / T-0.59** — all the same "record the demo video" owner task.
- **T-0.25 / A8** — desktop-operator owner-host validation, now largely superseded by H28.4.
- **TASK-2** — its remaining tail is itself a duplicate of the `LVP-*` owner-config cluster and is
  not given its own Tier row; see the `LVP-*` rows in Tier 5.

Closing one member of a cluster should prompt closing the others in the same PR/decision, or the
recount pass will keep re-surfacing them as separate open rows.

## Recount log

- **2026-08-28 (run 015):** re-verified the rows referenced by `docs/MAX_RUNS.md` row 014's
  next-pointer against current `main` before picking new work. Two rows closed: **T-0.22**
  (shipped in #971, already landed on `main` before this recount) and **A8-iv** (the persisted-
  stamp redesign had already shipped in #946 — pre-dating this ledger's own generation timestamp,
  so the initial Phase 0 sweep missed it by trusting `BACKLOG.md`'s stale prose over the code; this
  run closed the remaining "sound and reusable" snapshot-field gap and corrected `BACKLOG.md`).
  Lesson for future recounts: grep the code/tests for a row's own keywords (e.g. `govern_enqueue`,
  `uninstall.py`) before trusting a BACKLOG.md status marker — prose can lag a merged PR.
