# SPRINT.md — stare partajată între agenți (sesiune curentă)

> Fișier viu. Actualizat de conductor agent sau lead agent după fiecare wave.
> La start de sesiune: copiază template-ul de mai jos și completează câmpurile.

---

## Sesiune curentă

**Data:** 2026-07-06 (AUD-14 task-budget env-float merged)
**Lead agent / Conductor:** Codex
**Obiectiv sesiune:** execute Fable audit safety hardening, fix eval workflow fallout, wire LivingMemory into live recall, finish the DailyReflector sleep-time memory seam, persist core/tier memory, keep explicit user-forget complete, wire re-projection maintenance + embedder handoff, make recall re-activate useful LivingMemory traces, stop exact duplicate turns from re-encoding, finish the H18 mobile parity tail through security posture, then harden the next external-host execution seams from the architecture audit.
**Branch:** `codex-docs-aud14-task-budget-merged`

**Scope decision (2026-07-04):** O26-P0, P1.1, P2.1, P2.2, P2.3, P2.4, P2.5, P3.1, P3.3, P3.4, P3.5, P3.6, the O26-P3.2 Data Spaces depth slice, the O26-P3.2 Rooms history drawer slice, the O26-P3.2 Capability issue/check UI slice, and the O26-P3.2 Current Mesh Task Fan slice are merged.
The O26-P3.2 Preferences Tweaks UI slice is merged. The O26-P3.2 Self-hosted Fonts slice is merged in #525. The 0.44 Safe Comms draft-before-send UI slice is merged in #527: frontend draft composition over existing governed social endpoints only. The 0.45 payment live-gate adoption is merged in #529: the existing mandate denial gate now evaluates `PAYMENT_CONTRACT` while preserving denial codes/order. The 0.45 signal governance live-gate adoption is merged in #531: actionable Signal Layer recommendations evaluate `SIGNAL_RECOMMENDATION_CONTRACT` before they can enter the preview-only approval queue. The 0.45 plugin permission live-gate adoption is merged in #533: `PermissionGate.check_call()` evaluates `PLUGIN_CALL_CONTRACT` while preserving boolean outcomes and warning reasons. The 0.45 social draft live-gate adoption is merged in #535: governed X post/reply/DM drafts evaluate `SOCIAL_DRAFT_CONTRACT` before preview/enqueue. The 0.45 write-back draft live-gate adoption is merged in #537: governed Notion/GitHub/Calendar drafts evaluate `WRITEBACK_DRAFT_CONTRACT` before preview/enqueue. The 0.45 outbound call live-gate adoption is merged in #539: Twilio/Telnyx outbound-call requests evaluate `CALL_REQUEST_CONTRACT` before preview/enqueue, after provider/field/interrupt-budget checks. The 0.45 Tool-RPC live-gate adoption is merged in #541: gated Tool-RPC calls evaluate `TOOL_RPC_CALL_CONTRACT` before kernel mediation and approval enqueue. The 0.45 NodeMesh dispatch live-gate adoption is merged in #543: governed node dispatch evaluates `NODE_DISPATCH_CONTRACT` before preview/enqueue. The 0.45 media-generation live-gate adoption is merged in #545: cloud image/thumbnail/video requests evaluate `MEDIA_GENERATION_CONTRACT` before approval enqueue. The 0.45 desktop-step live-gate adoption is merged in #547: mutating desktop operator steps evaluate `DESKTOP_STEP_CONTRACT` before approver callback or driver execution. H17.1a inbound-origin construction is merged in #549. 0.45 Batch B1 skill + host-control contracts are merged in #550. #551 adds Safe Comms channel inbox transport v0 for telegram/web. #552 fixes eval-nightly workflow validation by moving cache-hash expressions out of job-level `env`. #553 merges LivingMemory live recall ordering plus `/api/memory/eval/run?mode=recall`. #554 merges durable DailyReflector idempotency plus gated LivingMemory lesson handoff. #555 merges gated LivingMemory core prompt injection. #556 merges JsonStore-backed LivingMemory core persistence. #557 merges JsonStore-backed LivingMemory tier persistence. #558 keeps `/api/admin/forget` / `data_purge` complete for both new cognition stores. #559 wires the default-off LivingMemory re-projection maintenance hook. #560 connects that hook to `MemoryManager.embed` when available. #561 merges matched-hit recall reactivation. #562 gates exact duplicate LivingMemory turn digests before they create another tier/decay record. #564 closes H18.12 mobile channel inbox parity: native Comms reads `/api/channels/inbox*` and queues governed replies with `source:"mobile"`. #566 closes H18.13 mobile Tasks board parity: native Tasks reads `/tasks` and preserves the honest empty state. #568 closes H18.14 mobile status ambient/ticker parity. #570 closes H18.15 mobile Skills browser; #571 marks it merged in docs. #572 closes H18.16 mobile Memory/Notes parity with full PR CI green. #574 closes H18.17 mobile Knowledge Graph parity with full PR CI green. #576 closes H18.18 mobile Security Posture with full PR CI green: native Status gains a read-only Trust card over `/api/security/*` reads. #578 merges R1/R4 Oracle + MCP host-execution hardening. #580 merges R2 taint propagation teeth with full PR CI green: inbound queue intake/edit paths force ASK and persist taint, and inbound user-turn vector memory stays visibly tainted through recall provenance.

**Merged R3-B3 scope:** #584 adds `A2A_INBOUND_CONTRACT` before signed peer tasks enter the pending inbox and `ESCALATION_CONTRACT` before autonomy broadcasts call channel adapters. Local red/green, adjacent contract sweeps, and full PR CI are green.

**Merged R3-B4 scope:** #586 adds `MCP_MUTATING_ROUTE_CONTRACT` before mutating MCP route-tool adapters run. Local red/green, adjacent MCP/contract sweeps, and full PR CI are green.

**Merged R3-B5 scope:** #588 adds `CHANNEL_SEND_CONTRACT` before generic `ChannelManager.send()` adapter I/O. Local red/green, adjacent channel/comms sweeps, and full PR CI are green.

**Merged TASK-3 scope:** #590 marks untrusted inbound channel messages at `Gateway.route()` with private `_inbound_meta`, persists only public taint fields in `ChannelInboxStore`, and strips private gateway metadata in `Orchestrator.channel_handler()` before adapter sends. Local red/green, adjacent channel/taint sweeps, and full PR CI are green.

**Merged AUD-14 scope:** #592 routes the global outbound channel send-rate cap through `env_int()` and pins malformed/negative `JARVIS_CHANNEL_SEND_RATE` as unlimited. Local red/green, focused send-rate, adjacent env-config checks, and full PR CI are green.

**Merged M3.5 scope:** #594 wires JARVIS to WorldView's MCP write tools without changing the read-only HTTP bridge: `WorldViewMCPWriteClient` gates `watch_aoi`/`reconstruct_event` through plugin-gate, Action Kernel, per-agent `plugin:worldview` broker capability, and scoped HMAC token before stdio MCP tool calls. Local red/green, focused MCP/capability/write/Argus tests, adjacent WorldView/MCP sweeps, ruff, py_compile, and full PR CI are green.

**Merged AUD-14 LLM-model scope:** #596 centralizes LLM model-name defaults and the `JARVIS_DEEP_MODEL` override in `agents/core/llm/model_config.py`. `HybridRouter` consumes that shared module for deep-slot routing while preserving the public constants and the LOCAL_ONLY floor. Red/green guard, hybrid-router/config adjacent suites, CodeQL-safe import cleanup, and full PR CI are green.

**Merged AUD-14 task-budget scope:** #598 routes the K3 per-task wall-time env knob `JARVIS_TASK_MAX_SECONDS` through shared `env_float(..., minimum=0.0)` instead of local parsing in `AutonomyCoordinator.build_executor`. Red/green guard, focused executor/env-config checks, and full PR CI are green.

**Previous session:** O26-P0.1 golden harness was merged via #496, with P0.2–P0.7 already completed on
main by parallel agents.

---

## Wave-uri active

| Wave | Branch | PR | Status | Agenți | Note |
|------|--------|----|--------|--------|------|
| O26-P1.1 / one-turn pipeline | `codex-o26-p1-1-one-turn-pipeline` | #498 | ✅ merged | Codex | Shared prompt wrapper + shared post-turn record seam |
| O26-P2.1 / env config consolidation | `claude/jarvis-hub-backlog-review-jx87gz` | #500 | ✅ merged | Claude/Fable | One `env_config.truthy()` and env parse ratchet |
| O26-P2.2 / memory consolidation | `codex-o26-p2-2-memory-consolidation` | #501 | ✅ merged | Codex | LivingMemory seam + nightly maintenance |
| O26-P2.3 / dormant disposition | `codex-o26-p2-3-dormant-disposition` | #502 | ✅ merged | Codex | Ensemble roster + learning proof + profile extractor parked |
| O26-P2.4 / Product Posture | `codex-o26-p2-4-product-posture` | #503 | ✅ merged | Codex | Settings-backed named posture, wave 1 only |
| O26-P2.5 / Install Smoke Path | `codex-o26-p2-5-install-smoke` | #504 | ✅ merged | Codex | ~30s boot + `/readyz` + faked turn |
| O26-P3.1 / Preview Modes | `codex-o26-p3-1-preview-modes` | #505 | ✅ merged | Codex | 6 live preview modes + honest blockers |
| O26-P3.3 / Eval Baseline Store | `codex-o26-p3-3-eval-baseline-store` | #506 | ✅ merged | Codex | Cache-backed companion eval DatasetStore |
| O26-P3.2 / HUD Reconciliation | `codex-o26-p3-2-hud-reconciliation` | #507 | ✅ merged | Codex | Stale punch-list claims guarded by Vitest |
| O26-P3.4 / Mobile Approval Queue | `codex-o26-p3-4-mobile-approval-queue` | #509 | ✅ merged | Codex | Phone-native unified approval funnel |
| O26-P3.5 / Persona Rail + Caring Follow-ups | `codex-o26-p3-5-persona-caring-brief` | #510 | ✅ merged | Codex | Versioned persona signal + brief follow-up recomposition |
| O26-P3.6 / Landing Page Dev Half | `codex-o26-p3-6-landing-dev-half` | #512 | ✅ merged | Codex | Static self-contained landing + owner demo shot-list support |
| O26-P3.2 / Data Spaces Depth | `codex-o26-p3-2-data-spaces-depth` | #515 | ✅ merged | Codex | Data Spaces assign/unassign controls + reconciliation guard |
| O26-P3.2 / Rooms History Drawer | `codex-o26-p3-2-rooms-history-drawer` | #517 | ✅ merged | Codex | Selected room opens `GET /api/rooms/{id}/history` drawer |
| O26-P3.2 / Capability Issue/Check UI | `codex-o26-p3-2-capability-check-ui` | #519 | ✅ merged | Codex | Capability token issue + recent grants + check endpoint |
| O26-P3.2 / Current Mesh Task Fan | `codex-o26-p3-2-mesh-task-fan` | #521 | ✅ merged | Codex | `NeuralMesh` renders live `/tasks` spokes + count |
| O26-P3.2 / Preferences Tweaks UI | `codex-o26-p3-2-preferences-tweaks` | #523 | ✅ merged | Codex | Command palette controls look/density/motion/texture prefs |
| O26-P3.2 / Self-hosted Fonts | `codex-o26-p3-2-self-hosted-fonts` | #525 | ✅ merged | Codex | Local Space Grotesk + JetBrains Mono WOFF2 assets |
| 0.44 / Safe Comms Draft UI | `codex-o44-safe-comms-draft-ui` | #527 | ✅ merged | Codex | Console panel queues X post/reply/DM drafts through `/api/integrations/social`; channel inbox transport remains open |
| 0.45 / Payment Contract Live Gate | `codex-o45-payment-contract-live-gate` | #529 | ✅ merged | Codex | `PaymentBroker` request/approve gates evaluate `PAYMENT_CONTRACT`; denial codes stay stable |
| 0.45 / Signal Governance Contract Gate | `codex-o45-signal-governance-contract-gate` | #531 | ✅ merged | Codex | `SignalGovernanceBridge` evaluates `SIGNAL_RECOMMENDATION_CONTRACT` before queueing preview-only approvals |
| 0.45 / Plugin Permission Contract Gate | `codex-o45-plugin-gate-contract` | #533 | ✅ merged | Codex | `PermissionGate.check_call()` evaluates `PLUGIN_CALL_CONTRACT`; existing allow/deny behavior stays stable |
| 0.45 / Social Draft Contract Gate | `codex-o45-social-draft-contract` | #535 | ✅ merged | Codex | `SocialBroker.request()` evaluates `SOCIAL_DRAFT_CONTRACT` before preview/enqueue; no channel inbox transport scope |
| 0.45 / Write-Back Draft Contract Gate | `codex-o45-writeback-contract-gate` | #537 | ✅ merged | Codex | `WriteBackBroker.request()` evaluates `WRITEBACK_DRAFT_CONTRACT` before preview/enqueue; no live host-write scope |
| 0.45 / Outbound Call Contract Gate | `codex-o45-call-contract-gate` | #539 | ✅ merged | Codex | `CallBroker.request()` evaluates `CALL_REQUEST_CONTRACT` before preview/enqueue; no live telephony scope |
| 0.45 / Tool-RPC Contract Gate | `codex-o45-tool-rpc-contract-gate` | #541 | ✅ merged | Codex | `ToolRPCServer.handle()` evaluates `TOOL_RPC_CALL_CONTRACT` before kernel mediation and approval enqueue |
| 0.45 / NodeMesh Dispatch Contract Gate | `codex-o45-node-dispatch-contract-gate` | #543 | ✅ merged | Codex | `NodeMesh.dispatch()` evaluates `NODE_DISPATCH_CONTRACT` before preview/enqueue |
| 0.45 / Media Generation Contract Gate | `codex-o45-media-gen-contract-gate` | #545 | ✅ merged | Codex | `MediaGenManager.generate(cloud=True)` evaluates `MEDIA_GENERATION_CONTRACT` before approval enqueue |
| 0.45 / Desktop Step Contract Gate | `codex-o45-desktop-step-contract-gate` | #547 | ✅ merged | Codex | `GovernedDesktop.run()` evaluates `DESKTOP_STEP_CONTRACT` before approver callback/driver execution |
| H17.1a / Origin By Construction | `codex-h17-origin-by-construction` | #549 | ✅ merged | Codex | Public turn entrypoints bind origin; plugin egress uses current origin |
| 0.45 / Skill + Host-Control Contract Gates | `codex-o45-b1-contracts` | #550 | ✅ merged | Codex | `SKILL_INSTALL_CONTRACT`, `SKILL_GENERATION_CONTRACT`, shared `HOST_CONTROL_CONTRACT` |
| 0.44 / Safe Comms Channel Inbox Transport v0 | `codex-safe-comms-channel-inbox` | #551 | ✅ merged | Codex | Bounded telegram/web inbox + governed `channel.reply` approval/send loop |
| Eval Nightly Cache-Key Parser Hotfix | `codex-fix-eval-nightly-cache-context` | #552 | ✅ merged | Codex | `hashFiles()` moved from job `env` into cache action keys; Eval Nightly green |
| H21.3 / LivingMemory Live Recall + Eval Mode | `codex-living-memory-recall-eval` | #553 | ✅ merged | Codex | Post-fusion LivingMemory TCM re-rank + `/api/memory/eval/run?mode=recall` |
| H21.3 / DailyReflector LivingMemory Handoff | `codex-living-memory-daily-reflector` | #554 | ✅ merged | Codex | Durable reflection idempotency + gated lesson handoff to LivingMemory/core |
| H21.3 / LivingMemory Core Prompt Injection | `codex-living-core-prompt-injection` | #555 | ✅ merged | Codex | Gated bounded `living.core` facts in shared plain/stream prompt path |
| H21.3 / LivingMemory Core Persistence | `codex-living-core-persistence` | #556 | ✅ merged | Codex | JsonStore-backed bounded `living.core` under runtime data root |
| H21.3 / LivingMemory Tier Persistence | `codex-living-tier-persistence` | #557 | ✅ merged | Codex | JsonStore-backed tier metadata under runtime data root |
| H21.3 / Cognition Forget Purge | `codex-cognition-forget-purge` | #558 | ✅ merged | Codex | Explicit user-forget clears durable LivingMemory core/tier state live and at rest |
| H21.3 / Re-projection Maintenance | `codex-living-reprojection-maintenance` | #559 | ✅ merged | Codex | Nightly memory maintenance reports and runs default-off stale tier re-projection |
| H21.3 / Re-projection Embedder Wiring | `codex-living-reprojection-embedder` | #560 | ✅ merged | Codex | Nightly maintenance passes `MemoryManager.embed` when available and serializes structured tier content |
| H21.3 / Recall Reactivation | `codex-living-recall-reactivation` | #561 | ✅ merged | Codex | Matched recall hits refresh LivingMemory tier activation + decay access ledger |
| H21.3 / Duplicate Encoding Gate | `codex-living-memory-duplicate-gate` | #562 | ✅ merged | Codex | Exact duplicate turn digests skip another LivingMemory tier/decay write |
| H18.12 / Mobile Channel Inbox | `codex-mobile-channel-inbox` | #564 | ✅ merged | Codex | Native Comms tab lists Safe Comms threads, reads messages, queues governed replies |
| H18.13 / Mobile Tasks Board | `codex-mobile-tasks-board` | #566 | ✅ merged | Codex | Native Tasks tab reads `/tasks`, shows state counts, and keeps empty queues honest |
| H18.14 / Mobile Status Ambient + Ticker | `codex-mobile-status-ambient-ticker` | #568 | ✅ merged | Codex | Native Status reads `/dashboard` + `/ticker`; full PR CI green |
| H18.15 / Mobile Skills Browser | `codex-mobile-skills-browser` | #570 | ✅ merged | Codex | Native Skills tab reads `/skills` as a read-only catalog |
| H18.16 / Mobile Memory + Notes | `codex-mobile-memory-notes` | #572 | ✅ merged | Codex | Native Memory tab reads `/memory` + `/api/notes`; read-only |
| H18.17 / Mobile Knowledge Graph | `codex-mobile-knowledge-graph` | #574 | ✅ merged | Codex | Memory tab Graph view reads `/api/kg/*`; read-only |
| H18.18 / Mobile Security Posture | `codex-mobile-security-posture` | #576 | ✅ merged | Codex | Status Trust card reads `/api/security/*`; read-only |
| R1/R4 / Oracle + MCP Host-Exec Gate | `codex-r1-oracle-mcp-host-exec-gate` | #578 | ✅ merged | Codex | Oracle repo-sync contract/kernel gate + MCP argv/no-shell + MCP tool-call contract |
| R2 / Taint Propagation Teeth | `codex-r2-taint-propagation-teeth` | #580 | ✅ merged | Codex | Worker intake/edit taint + user-turn memory metadata + recall provenance |
| R3-B2 / Memory + Forget Contracts | `codex-r3-b2-memory-forget-contracts` | #582 | ✅ merged | Codex | KG write contract + destructive purge contract |
| R3-B3 / A2A + Escalation Contracts | `codex-r3-b3-a2a-escalation-contracts` | #584 | ✅ merged | Codex | A2A inbound contract + escalation broadcast contract; full PR CI green |
| R3-B4 / MCP Route-Tool Contracts | `codex-r3-b4-mcp-route-tool-contracts` | #586 | ✅ merged | Codex | Mutating MCP route tools evaluate a reusable contract before kernel/adapters; full PR CI green |
| R3-B5 / Channel-Send Contracts | `codex-r3-b5-channel-send-contracts` | #588 | ✅ merged | Codex | Generic ChannelManager sends evaluate a shape-only contract before adapter I/O; full PR CI green |
| TASK-3 / Channel Ingress Taint | `codex-task3-channel-ingress-taint` | #590 | ✅ merged | Codex | Gateway marks inbound channel metadata, inbox persists public taint fields, outbound sends strip private metadata; full PR CI green |
| AUD-14 / Channel Send-Rate Env-Int | `codex-aud14-channel-rate-env-int` | #592 | ✅ merged | Codex | `JARVIS_CHANNEL_SEND_RATE` global cap uses `env_int`; full PR CI green |
| M3.5 / WorldView MCP Write Transport | `codex-m35-worldview-mcp-write-transport` | #594 | ✅ merged | Codex | Argus reaches `watch_aoi`/`reconstruct_event` only through plugin-gate + Action Kernel + scoped HMAC MCP token; full PR CI green |
| AUD-14 / LLM Model Config | `codex-aud14-llm-model-config` | #596 | ✅ merged | Codex | Model-name defaults + `JARVIS_DEEP_MODEL` moved behind shared `llm/model_config.py`; full PR CI green |
| AUD-14 / Task Budget Env-Float | `codex-aud14-task-budget-env-float` | #598 | ✅ merged | Codex | `JARVIS_TASK_MAX_SECONDS` uses shared `env_float` parser; full PR CI green |

Status legend: ⏳ in progress · 🟡 draft PR · 🟢 CI green · ✅ merged · 🔴 conflict

---

## Fișiere blocate (în PR activ)

No active PR locks after #598 merge. Docs sync is on `codex-docs-aud14-task-budget-merged`.

---

## Ordine de merge (Wave 1 — de venit)

```
Current order:
  1. O26-P2.2 living-memory turn seam + nightly maintenance (#501) ✅
  2. O26-P2.3 dormant-module disposition (#502) ✅
  3. O26-P2.4 Product Posture (#503) ✅
  4. O26-P2.5 Install Smoke Path (#504) ✅
  5. O26-P3.1 Preview Modes (#505) ✅
  6. O26-P3.3 Eval Baseline Store (#506) ✅
  7. O26-P3.2 HUD Punch-List Reconciliation (#507) ✅
  8. O26-P3.4 Mobile Approval Queue (#509) ✅
  9. O26-P3.5 Persona Rail + Caring Follow-ups (#510) ✅
  10. O26-P3.6 Landing Page Dev Half (#512) ✅
```

Current backlog state: **0.45 High-Risk Automation Contracts — payment + signal + plugin + social + write-back + outbound call + Tool-RPC + NodeMesh + media-generation + desktop-step + B1 skill/host-control live gate adoption** is merged in #529/#531/#533/#535/#537/#539/#541/#543/#545/#547/#550. Safe Comms channel inbox transport v0 is delivered in #551; eval-nightly parser hotfix #552 is merged; H21.3 live recall integration is merged in #553; H21.3 DailyReflector durable LivingMemory handoff is merged in #554; H21.3 core prompt injection is merged in #555; H21.3 core persistence is merged in #556; H21.3 tier persistence is merged in #557; H21.3 forget-purge completeness is merged in #558; H21.3 re-projection maintenance is merged in #559; H21.3 re-projection embedder wiring is merged in #560; H21.3 recall reactivation is merged in #561; H21.3 duplicate encoding gate is merged in #562. H18.12 mobile Safe Comms inbox parity is merged in #564 with full PR CI green. H18.13 mobile Tasks board is merged in #566 with full PR CI green. H18.14 mobile status ambient/ticker is merged in #568 with full PR CI green. H18.15 mobile Skills browser is merged in #570 with full PR CI green. H18.16 mobile Memory/Notes is merged in #572 with full PR CI green. H18.17 mobile Knowledge Graph is merged in #574 with full PR CI green. H18.18 mobile Security Posture is merged in #576 with full PR CI green. R1/R4 Oracle + MCP host-execution hardening is merged in #578. R2 taint propagation teeth is merged in #580 with full PR CI green. R3-B2 memory/forget contracts is merged in #582 with full PR CI green. R3-B3 A2A/escalation contracts is merged in #584 with full PR CI green. R3-B4 MCP route-tool contracts are merged in #586 with full PR CI green. R3-B5 channel-send contracts are merged in #588 with full PR CI green. TASK-3 channel ingress taint is merged in #590 with full PR CI green. AUD-14 channel send-rate env-int is merged in #592 with full PR CI green. M3.5/#169 WorldView MCP write transport is merged in #594 with full PR CI green. AUD-14 LLM model-name config is merged in #596 with full PR CI green. AUD-14 task-budget env-float is merged in #598 with full PR CI green.

---

## Recomandare — următorul thread (drum spre 1.0)

> Cântărit față de north-star (MOONSHOT §1/§3/§5) și ce s-a livrat în Wave 0 (securitatea H12.1).
> Acum că **1.0 = tot backlogul**, secvențierea contează: alegem ce ridică cel mai mult valoarea pe-misiune.

**Prioritate 1 — H17 Provable Trust (continuă Wave 0).** AgentDojo + AgentHarm ca poartă CI (H17.2, 5 SP) +
dual-LLM / Plan-Then-Execute quarantine pentru conținut tool/web/email (H17.1, 13 SP). Convertește „alternativa
guvernată la OpenClaw" dintr-un *claim* într-un *badge CI verde*; rupe „lethal trifecta" pe agenții email/calendar.
Construiește direct pe SecretStore + skill signing din H12.1.

**Prioritate 2 — H14 Living Memory (cea mai on-mission).** Întâi harness-ul de eval memorie (H14.2, 5 SP, măsoară),
apoi KG bi-temporal (H14.1, 8 SP) + agent de consolidare „sleep-time" cu operații explicite (H14.3, 8 SP).
Generalizează reflecția nocturnă din *rezumă-ziua* în *pre-raționează-pentru-mâine* — chiar sloganul moonshot.

**Apoi:** H13 (plafon capabilitate locală, $0) → H10 competitive edge / H16 (MCP server mode) → H15 computer-use guvernat.

**Temă-flagship transversală:** *sleep-time compute* (H13/H14) + *guvernanță măsurabilă* (H17).

---

## Checklist post-merge (conductor)

### ORIZONT 26 P2.2 — COMPLET

- [x] `main` fetched/rebased from `origin/main`
- [x] Branch created from current main
- [x] Red tests added for default-off seam, enabled turn records, scheduler registration, disabled job no-op
- [x] `_complete_llm_turn()` feeds LivingMemory + decay records when cognition memory is enabled
- [x] `SchedulerService` registers and runs nightly memory maintenance
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused backend verification green
- [x] Ruff / final compile pass
- [x] Branch pushed / PR #501 opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P2.3 — COMPLET

- [x] `main` synced after #501 merge
- [x] Branch rebased onto current `origin/main`
- [x] Red tests added for active roster disposition and parked legacy extractor
- [x] PersonaModule + EnsembleModule populated from active agents after `load_agents()`
- [x] Governed learning verified through the autonomy calibration hook
- [x] `profile_extractor.legacy_status()` marks the legacy extractor parked
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused backend verification green
- [x] Ruff / final compile pass
- [x] Branch pushed / PR #502 opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P2.4 — COMPLET

- [x] `main` synced after #502 merge
- [x] Branch created from current main
- [x] Design/tests for settings-backed named posture
- [x] Product posture implementation
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused posture/onboarding/security slice green
- [x] Full focused backend verification green
- [x] Branch pushed / PR #503 opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P2.5 — COMPLET

- [x] `main` synced after #503 merge
- [x] Branch created from current main
- [x] Design/tests for install smoke path
- [x] Install smoke implementation
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused backend verification green
- [x] Branch pushed / PR #504 opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P3.1 — MERGED IN #505

- [x] `main` synced after #504 merge
- [x] Branch created from current main
- [x] Design/tests for live preview modes
- [x] Preview-mode implementation
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused verification green
- [x] Branch pushed / PR #505 opened
- [x] GitHub Actions green, including HUD bundle freshness and Windows test lanes
- [x] PR merged

### ORIZONT 26 P3.3 — DELIVERED IN #506

- [x] `main` synced after #505 merge
- [x] Branch created from current main
- [x] Red tests for explicit eval store root + workflow cache wiring
- [x] `companion_eval --ci-gate --store-root` writes to an explicit DatasetStore
- [x] Eval nightly restores/saves the DatasetStore through pinned `actions/cache`
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused companion eval verification green
- [x] Branch pushed / PR #506 opened
- [x] Rebased after #505 merge and pushed
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P3.2 — COMPLET ✅

- [x] `main` synced after #506 merge
- [x] Branch created from current main
- [x] Red Vitest guard for stale HUD remaining-work claims
- [x] HUD_V2_REMAINING reconciled against actual shipped controls
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused frontend verification green
- [x] Branch pushed / PR opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P3.4 — COMPLET ✅

- [x] `main` synced after #508 merge
- [x] Branch created from current main
- [x] Red mobile API contract test for approvals/admin auth
- [x] Mobile API client + admin-token settings support
- [x] Mobile Approvals tab over `/autonomy/approvals`
- [x] `mobile/PARITY.md`, `BACKLOG.md`, `STATUS.md`, and README updated
- [x] Mobile focused verification green (`npm test`, `npx tsc --noEmit`)
- [x] Branch pushed / PR opened
- [x] GitHub Actions green; PR merged

### Wave 0 — COMPLET ✅

- [x] `BACKLOG.md` actualizat (H12.1 ✅, H12.9 ✅, H12.10 ✅)
- [x] Test count actualizat în BACKLOG (1184+ passed)
- [x] `docs/SPRINT.md` marcat wave ca ✅ merged
- [x] PR #54 cu toate detaliile pentru PM (deploy instructions, env vars, metrici)
- [x] Branches stale șterse (claude/h12.1-security, claude/h12.10-mute-indicator, claude/h12.9-local-model-ux) — confirmate absente pe origin 2026-06-03

### Wave 1 — PENDING ⏳

- [ ] Wave 1 dispatched (6 agenți în paralel)
- [ ] PR-uri create (draft)
- [ ] CI verde pe toate
- [ ] Merge în ordine (fără conflicte pe BACKLOG.md)
- [ ] BACKLOG.md actualizat

---

## Log sesiune

```
[H18.13]  2026-07-05 — started mobile Tasks board parity on `codex-mobile-tasks-board`
[H18.13]  Red test: mobile client had no `fetchTasks()` helper for the read-only `/tasks` surface
[H18.13]  Implemented typed mobile tasks client, native Tasks tab, state counts, task cards, and honest empty state
[Verify]  H18.13 mobile Jest green (28 passed); mobile typecheck clean
[PR]      #566 full GitHub Actions green and squash-merged
[H18.14]  2026-07-05 — started mobile Status ambient/ticker parity on `codex-mobile-status-ambient-ticker`
[H18.14]  Red test: mobile client had no `fetchDashboard()` / `fetchTicker()` helpers for `/dashboard` and `/ticker`
[H18.14]  Implemented typed mobile dashboard/ticker client and native Status Today/Ticker cards with honest empty states
[Verify]  H18.14 focused dashboard/ticker Jest green (4 passed); mobile typecheck clean
[PR]      #568 opened as draft
[PR]      #568 full GitHub Actions green (15/15); marked ready and squash-merged
[H18.12]  2026-07-05 — started mobile Safe Comms inbox parity on `codex-mobile-channel-inbox`
[H18.12]  Red test: mobile client had no `/api/channels/inbox*` helpers and no `source:"mobile"` governed-reply payload
[H18.12]  Implemented typed mobile inbox client, native Comms tab, selected-thread messages, and governed reply queueing
[Verify]  H18.12 mobile Jest green (26 passed); mobile typecheck clean
[PR]      #564 full GitHub Actions green and squash-merged
[H17.1a] 2026-07-05 — started inbound-origin-by-construction hardening on `codex-h17-origin-by-construction`
[H17.1a] Red tests: internal turn channels were misclassified inbound; direct `handle_input`/stream callers bypassed turn-origin binding; plugin egress hard-coded `generated`
[H17.1a] Implemented monotone turn-origin binding at public orchestrator entrypoints plus current-origin plugin egress
[Verify]  H17.1a/origin/taint/kernel/chat-stream targeted sweeps green; ruff and py_compile clean
[PR]      #549 full GitHub Actions green and squash-merged
[0.45-B1] Started skill + host-control contract gates on `codex-o45-b1-contracts`
[0.45-B1] Red tests: marketplace publish/install/uninstall, generated-skill create/approve, remediation restart, and LM Studio start ignored patched contracts
[0.45-B1] Implemented `contract_denial()`, `SKILL_INSTALL_CONTRACT`, `SKILL_GENERATION_CONTRACT`, and shared `HOST_CONTROL_CONTRACT`
[Verify]  B1 focused/adjacent sweep green: 121 passed; ruff and py_compile clean
[CI]      #552 merged: eval-nightly workflow validation fixed by moving cache hash expressions from job env into cache action keys
[H21.3]   Started LivingMemory live recall + real recall eval mode on `codex-living-memory-recall-eval`
[H21.3]   Red tests: no `memory.living_recall` helper, `_recall_block()` rendered old fused order, eval endpoint ignored `mode=recall`
[H21.3]   Implemented post-fusion LivingMemory TCM re-rank before `rag_guard`, plus async `run_recall_eval()` over real `MemoryManager.remember()`/`recall()`
[Verify]  LivingMemory focused suite green: 6 passed; adjacent memory/eval/recall sweep green: 44 passed; OpenAPI TS regenerated
[PR]      #553 full GitHub Actions green and squash-merged
[H21.3]   Started DailyReflector durable LivingMemory handoff on `codex-living-memory-daily-reflector`
[H21.3]   Red tests: reflection idempotency vanished after restart; manual rerun had no durable force path; lessons never reached LivingMemory; cognition-memory off had no explicit no-op proof
[H21.3]   Implemented `ReflectionRunStore`, `run(force=True)`, Orchestrator gated LivingMemory provider, and metadata-only lesson tier records plus bounded core-memory lessons
[Verify]  DailyReflector focused suite green: 14 passed
[PR]      #554 full GitHub Actions green and squash-merged
[H21.3]   Started LivingMemory core prompt injection on `codex-living-core-prompt-injection`
[H21.3]   Red tests: `living.core` facts stayed out of `_build_agent_turn_text()` even with cognition memory enabled
[H21.3]   Implemented gated `[core memory]` block in the shared plain/stream prompt path, with line normalization and background-facts label
[Verify]  LivingMemory recall/core focused suite green: 8 passed
[PR]      #555 full GitHub Actions green and squash-merged
[H21.3]   Started LivingMemory core persistence on `codex-living-core-persistence`
[H21.3]   Red tests: `CoreMemory(path=...)` and `LivingMemory(core_path=...)` were unsupported; Orchestrator core facts stayed process-local
[H21.3]   Implemented JsonStore-backed bounded `CoreMemory`, `LivingMemory(core_path=...)`, and production `memory_logs/cognition/core_memory.json` wiring
[Verify]  LivingMemory/core persistence focused suite green: 26 passed
[PR]      #556 full GitHub Actions green and squash-merged
[H21.3]   Started LivingMemory tier persistence on `codex-living-tier-persistence`
[H21.3]   Red tests: `TieredMemory(path=...)` and `LivingMemory(tiers_path=...)` were unsupported; Orchestrator tier metadata stayed process-local
[H21.3]   Implemented JsonStore-backed tier records, persistence on add/access/maintain/forget, and production `memory_logs/cognition/living_tiers.json` wiring
[Verify]  LivingMemory/tier persistence focused suite green: 29 passed
[PR]      #557 full GitHub Actions green and squash-merged
[H21.3]   Started cognition forget-purge completeness on `codex-cognition-forget-purge`
[H21.3]   Red tests: `purge_data(memory=True)` left `cognition/core_memory.json` and `cognition/living_tiers.json` on disk; live `LivingMemory` could still hold forgotten facts
[H21.3]   Implemented explicit clear seams for `CoreMemory`, `TieredMemory`, and `LivingMemory`, plus exact-path purge coverage for cognition stores
[Verify]  Forget-purge focused suite green: 5 passed; adjacent LivingMemory/consolidation sweep green: 29 passed
[PR]      #558 opened as draft
[PR]      #558 full GitHub Actions green and squash-merged
[H21.3]   Started LivingMemory re-projection maintenance on `codex-living-reprojection-maintenance`
[H21.3]   Red tests: `LivingMemory` had no stale-record persistence method, and nightly maintenance never reported/called a re-projection hook
[H21.3]   Implemented `LivingMemory.reproject_stale(embedder=...)`, `TieredMemory.update_records()`, and best-effort scheduler reporting (`reprojection`)
[Verify]  LivingMemory re-projection maintenance focused suite green: 31 passed; ruff/py_compile/bandit/status-sync clean
[PR]      #559 full GitHub Actions green and squash-merged
[H21.3]   Started LivingMemory re-projection embedder wiring on `codex-living-reprojection-embedder`
[H21.3]   Red tests: nightly maintenance did not pass `orch.memory.embed`, and structured tier content reached embedders as raw dictionaries
[H21.3]   Implemented scheduler embedder handoff plus deterministic JSON serialization for structured re-projection content
[PR]      #560 opened as draft
[PR]      #560 full GitHub Actions green and squash-merged
[H21.3]   Started LivingMemory recall reactivation on `codex-living-recall-reactivation`
[H21.3]   Red tests: matched LivingMemory recall hits did not refresh tier activation/accesses, and orchestrator did not pass the decay store into recall rerank
[H21.3]   Implemented `LivingMemory.access()`, best-effort matched-hit access in `living_recall`, and decay-store handoff from Orchestrator
[PR]      #561 opened as draft
[PR]      #561 merged after full GitHub Actions passed
[H21.3]   Started LivingMemory duplicate encoding gate on `codex-living-memory-duplicate-gate`
[H21.3]   Red tests: `LivingMemory` could not find existing turn digests, and two identical completed turns created two tier records plus two decay entries
[H21.3]   Implemented bounded `LivingMemory.has_text_digest()` and maps exact duplicate turn digests to zero surprise before encoding
[Verify]  LivingMemory duplicate gate adjacent suite green: 51 passed; py_compile, ruff, bandit, status-sync, and diff-check clean
[PR]      #562 opened as draft
[PR]      #562 merged after full GitHub Actions passed
[ORIZONT 25] 2026-07-03 — created `codex-integrate-verified-developments` from `origin/main`
[ORIZONT 25] merged #487 M1.1, #488 M1.2, #489 M2.3, #490 M2.1, #491 status correction locally
[Docs]        BACKLOG/STATUS/ARCHITECTURE/HUD remaining/SPRINT refreshed: M1.1,M1.2,M2.1,M2.3 done; M2.4 partial
[Verify]      backend targeted pytest 22 passed; companion eval gate passed 48/48; py_compile passed with cache redirected
[Verify]      frontend typecheck passed; vitest 155 passed; Playwright Chromium HUD/flow 6 passed after fixing Windows venv path
[Wave 0] H12.1 dispatched (P0 securitate — anti-OpenClaw differentiator)
[Wave 0] H12.10 dispatched (trust indicator HUD)
[Wave 0] H12.9 dispatched (local model UX)
[Wave 0] PR #55 (H12.1) — CI CodeQL 4 findings → fixat → merged
[Wave 0] PR #53 (H12.10) — CI CodeQL false positive → fixat (De Morgan) → merged
[Wave 0] PR #54 (H12.9) — 3 runde conflicte BACKLOG.md → rezolvate; error_logger.py stale → restaurat
[Wave 0] PR #54 merged @ 050f88a — Wave 0 COMPLET
[Wave 0] PR #54 title/body actualizat cu toate detaliile pentru PM
[Wave 1] ⏳ Așteptând confirmare user pentru dispatch
[Docs]   2026-06-03 — formalizat ORIZONT 13–17 în BACKLOG (PR #60)
[Docs]   Decizie: v1.0 = tot backlogul (H10+H11+H12+H13–17); MOONSHOT §4 aliniat
[Docs]   Reconciliate README + GO_LIVE_PLAN + STATUS + gap-analysis-1.0
[Docs]   PR #60 ready for review, CI verde (CI #94 ✅ + CodeQL #72 ✅)
[Docs]   Audit branches: 2 fully-merged (lm-studio-setup, v1.0-release-prep) — ștergere blocată de proxy git
[Next]   Recomandare thread: H17 (trust scorecard) + H14 (living memory) — vezi secțiunea de mai sus
[ORIZONT 26] 2026-07-04 — P0.7 confirmed already done on main; started O26-P1.1 on `codex-o26-p1-1-one-turn-pipeline`
[O26-P1.1] Red tests: plain path lacked runtime truth, stream path lacked persona, completed turns did not nudge affect
[O26-P1.1] Implemented shared Agent prompt wrapper, shared turn enrichment, shared post-LLM record/audit/cognition seam
[Verify]   P1.1/golden chat/stream abort/concurrent stream/chat HTTP/prompt guard/agent integration/token budget/bench/persona/cognition targeted suites green
[PR]       #498 opened, full GitHub Actions green, marked ready for review
[O26-P1.1] #498 independently reviewed (truncation + CDX-7 suspicions cleared, 154 tests re-run on Linux) and MERGED @ 766d15e; e2e path-filter oracle gap -> #499 merged @ 644ace3
[ORIZONT 26] 2026-07-04 — Phase 2 started; O26-P2.1 (AUD-14 env consolidation) claimed on `claude/jarvis-hub-backlog-review-jx87gz`
[O26-P2.1] Workflow inventory: 163 env-read sites / 55 files / 122 vars / EIGHT truthy conventions (not 3) incl. the JARVIS_WORKFLOW_PERSIST=0-enables-the-drain footgun
[O26-P2.1] agents/core/env_config.py (stdlib leaf, one truthy(), unknown->declared-default) + 29 bool sites migrated + ratchet test (red-proved 35 hits); LOCAL_ONLY floor + hardened layering untouched
[ORIZONT 26] 2026-07-04 — main synced at #500; started O26-P2.2 on `codex-o26-p2-2-memory-consolidation`
[O26-P2.2] Red tests: enabled LivingMemory received zero turn records; scheduler had no memory-maintenance registration/body
[O26-P2.2] Implemented default-off LivingMemory turn references at `_complete_llm_turn()` plus decay tracking and 02:40 NREM/REM maintenance with no auto-delete
[Verify]   P2.2/LivingMemory/decay/P1.1/lifespan targeted suites green: 33 passed; STATUS count synced to ~3,584
[O26-P2.2] CodeQL merge blockers addressed: memory-maintenance warnings avoid exception text, completion logging emits counters instead of the whole result payload, and LivingMemory/decay records avoid duplicating raw transcript text
[PR]       #501 opened as draft
[ORIZONT 26] 2026-07-04 — started O26-P2.3 on stacked `codex-o26-p2-3-dormant-disposition` while #501 CI finished
[O26-P2.3] Red tests: active-agent cognition roster was empty; legacy profile extractor had no explicit parked status
[O26-P2.3] Implemented active roster configuration for PersonaModule + EnsembleModule; governed learning proven live at the autonomy calibration hook; profile_extractor parked via legacy_status()
[Verify]   P2.3/ensemble/persona/governed-learning/profile targeted sweep green: 48 passed; STATUS count synced to ~3,588
[O26-P2.4] #503 merged: settings-backed Product Posture with OFF/companion_wave1/design_partner overlays and wave-2 hardening explicitly deferred
[O26-P2.5] #504 merged: fast install smoke path (`scripts/install_smoke.py --json`) with real boot, `/readyz`, and one faked local turn
[ORIZONT 26] 2026-07-04 — started O26-P3.1 on `codex-o26-p3-1-preview-modes`
[O26-P3.1] Red tests: six preview modes lacked LIVE key coverage; plugin `enabled` alone looked live; `balance` mock payloads could be mistaken for live; empty Comms channels crashed
[O26-P3.1] Implemented six-mode live gates, `/plugins.configured`, `/status.channels`, Build/Comms/Finance data ingestion, and plugin-gated Health/Knowledge/Family empty states
[Verify]   P3.1 focused `/plugins` + `/status` backend checks green; preview-mode Vitest suite green (5 passed)
[Verify]   P3.1 CI green after refreshing the committed HUD V2 bundle and matching Linux Vite output
[PR]       #505 merged
[ORIZONT 26] 2026-07-04 — started O26-P3.3 on `codex-o26-p3-3-eval-baseline-store`
[O26-P3.3] Red tests: CLI ignored explicit eval-store root; nightly workflow had no cache-backed baseline persistence
[O26-P3.3] Implemented `--store-root` / `JARVIS_EVAL_STORE`, summary store-root reporting, and pinned `actions/cache/restore` + `save` with run-id keys and dataset/source restore prefix
[Verify]   P3.3 companion eval suites green: 19 passed; CLI store-root gate exits 0; ruff + py_compile clean
[Verify]   P3.3 rebased cleanly after #505; STATUS counter synced to ~3,600
[PR]       #506 merged
[ORIZONT 26] 2026-07-04 — started O26-P3.2 on `codex-o26-p3-2-hud-reconciliation`
[O26-P3.2] Red test: HUD_V2_REMAINING still claimed shipped TTS/mic/cognition/trust and Console controls were missing
[O26-P3.2] Reconciled HUD_V2_REMAINING; remaining tail is Data Spaces assign/unassign, capability grants/check UI, room history drawer, current-mesh task fan, preferences/tweaks UI, fonts, and owner live-data/plugin setup
[Verify]   P3.2 focused frontend checks green: 19 passed; typecheck, diff-check, and status-sync clean
[PR]       #507 opened as draft
[PR]       #507 full GitHub Actions green; PR marked ready and squash-merged
[PR]       #508 status-sync follow-up merged after protected-main direct push was rejected
[ORIZONT 26] 2026-07-04 — started O26-P3.4 on `codex-o26-p3-4-mobile-approval-queue`
[O26-P3.4] Red test: mobile client had no approval API and no admin-token path for admin-gated decisions
[O26-P3.4] Implemented mobile Approvals tab, `X-Admin-Token` settings, unified queue fetch, approve/reject/defer posts, README + PARITY updates
[Verify]   P3.4 mobile Jest suite green: 22 passed; mobile typecheck clean
[PR]       #509 opened as draft
[PR]       #509 full GitHub Actions green; PR marked ready and prepared for squash merge
[PR]       #509 merged
[ORIZONT 26] 2026-07-04 — started O26-P3.5 on `codex-o26-p3-5-persona-caring-brief`
[O26-P3.5] Red tests: persona rail lacked SOUL-derived profile scoring and drift stats; cognition trace did not pass versioned persona metadata; morning/today digests had no caring follow-ups from failed/blocked tasks or memory facts
[O26-P3.5] Implemented compact SOUL persona profiles at the live quality seam, `signals.persona` + persona drift stats, and shared caring follow-up extraction for morning brief + unified digest
[Verify]   P3.5 local suite green: 6 passed; adjacent quality/digest/timeline/autonomy endpoint suites green: 41 + 37 passed; touched-file ruff + py_compile clean; STATUS counter synced to ~3,606
[PR]       #510 opened as draft
[PR]       #510 full GitHub Actions green; PR marked ready and squash-merged
[ORIZONT 26] 2026-07-04 — started O26-P3.6 on `codex-o26-p3-6-landing-dev-half`
[O26-P3.6] Red test: no static landing surface, no owner demo checklist, and no self-contained marketing contract existed
[O26-P3.6] Implemented `marketing/landing/index.html`, `demo-shot-list.md`, and README wiring from `docs/marketing/` + Brand Book tokens
[Verify]   P3.6 landing contract green: 4 passed locally; status sync and static checks clean; local-file visual smoke passed on desktop/mobile; #512 full GitHub Actions green
[PR]       #512 opened as draft
[PR]       #512 full GitHub Actions green; PR marked ready and squash-merged
[ORIZONT 26] 2026-07-04 — started O26-P3.2 Data Spaces depth on `codex-o26-p3-2-data-spaces-depth`
[O26-P3.2] Red test: `DataSpacesPanel` listed/created/deleted spaces but had no agent assignment UI and was not exported for focused testing
[O26-P3.2] Implemented Data Spaces assignment rows, agent→space assign control, row-level unassign, and a reconciliation guard so the HUD punch-list cannot re-list it as missing
[Verify]   P3.2 Data Spaces depth: focused HUD tests green (8 passed); full frontend Vitest green (164 passed); typecheck/status-sync/diff-check clean
[PR]       #515 full GitHub Actions green; PR marked ready and squash-merged
[ORIZONT 26] 2026-07-04 — started O26-P3.2 Rooms history drawer on `codex-o26-p3-2-rooms-history-drawer`
[O26-P3.2] Red test: `RoomsPanel` selected a room but did not call `/api/rooms/{id}/history` or show saved room turns
[O26-P3.2] Implemented selected-room history drawer and post-send history refresh in `RoomsPanel`
[Verify]   P3.2 Rooms history drawer: focused HUD panel test green (5 passed)
[PR]       #517 full GitHub Actions green; PR marked ready and squash-merged
[ORIZONT 26] 2026-07-04 — started O26-P3.2 Capability issue/check UI on `codex-o26-p3-2-capability-check-ui`
[O26-P3.2] Red test: `CapabilitiesPanel` was not exported and could not check a token/capability pair
[O26-P3.2] Implemented recent issued grants plus `GET /api/security/capabilities/check` controls in `CapabilitiesPanel`
[Verify]   P3.2 Capability issue/check UI: focused HUD panel test green (6 passed)
[PR]       #519 full GitHub Actions green; PR marked ready and squash-merged
[ORIZONT 26] 2026-07-04 — started O26-P3.2 Current Mesh Task Fan on `codex-o26-p3-2-mesh-task-fan`
[O26-P3.2] Red test: `NeuralMesh` accepted task data but did not surface any live `/tasks` count in the active mesh legend
[O26-P3.2] Implemented live task spokes/dots in `NeuralMesh` and passed already-loaded `/tasks` state from `app.tsx`
[Verify]   P3.2 mesh task fan: focused mesh test green (4 passed); adjacent mesh/cinema sweep green (8 passed); full frontend Vitest green (167 passed); typecheck/build/status-sync/diff-check clean
[PR]       #521 full GitHub Actions green; PR marked ready and squash-merged
[ORIZONT 26] 2026-07-04 — started O26-P3.2 Preferences Tweaks UI on `codex-o26-p3-2-preferences-tweaks`
[O26-P3.2] Red test: command palette did not expose Look, Motion, or Comfy density controls for the dropped TweaksPanel surface
[O26-P3.2] Implemented command-palette controls for look, density, motion, scanline, and dotgrid; motion now persists as `hud.motion`
[Verify]   P3.2 preferences/tweaks UI: focused palette test green (1 passed); full frontend Vitest green (168 passed); frontend typecheck clean
[PR]       #523 full GitHub Actions green; PR marked ready and squash-merged
[ORIZONT 26] 2026-07-04 — started O26-P3.2 Self-hosted Fonts on `codex-o26-p3-2-self-hosted-fonts`
[O26-P3.2] Red test: HUD v2 stylesheet had no local `@font-face` declarations and no committed WOFF2 assets
[O26-P3.2] Implemented local Space Grotesk + JetBrains Mono WOFF2 assets and CSS font-face wiring
[Verify]   P3.2 self-hosted fonts: focused font guard green (2 passed); full frontend Vitest green (170 passed); typecheck/build clean
[PR]       #525 full GitHub Actions green; PR marked ready and squash-merged
[0.44]     Started Safe Comms draft UI on `codex-o44-safe-comms-draft-ui`
[0.44]     Red test: no Console panel existed for draft-before-send social writes
[0.44]     Implemented `SafeCommsDraftPanel` over `/api/integrations/social`; drafts queue for approval and do not send directly
[Verify]   Safe Comms draft UI focused Vitest green (1 passed); full frontend Vitest green (171 passed); typecheck/build/status-sync/diff-check clean
[PR]       #527 opened as draft
[PR]       #527 full GitHub Actions green (16/16); PR marked ready and squash-merged @ ef088c4
[Docs]     #528 marked #527 merged in BACKLOG/STATUS/SPRINT/HUD docs; full GitHub Actions green and squash-merged @ 993b110
[0.45]     Started payment contract live gate on `codex-o45-payment-contract-live-gate`
[0.45]     Red tests: `PaymentBroker.request_payment()` / `approve()` ignored a patched payment contract
[0.45]     Implemented `PAYMENT_CONTRACT` in `payments.py`; `_deny_reason()` delegates to the contract while preserving denial codes/order
[Verify]   0.45 payment live gate sweep green: 76 passed across live-gate/parity/contracts/payments/kernel/action-auth; ruff + py_compile clean
[PR]       #529 opened as draft
[PR]       #529 full GitHub Actions green (17/17); marked ready and squash-merged @ 4ac9049
[Docs]     #530 marked #529 merged in STATUS/SPRINT; full GitHub Actions green (15/15) and squash-merged @ e200bf7
[0.45]     Started signal governance contract gate on `codex-o45-signal-governance-contract-gate`
[0.45]     Red test: `SignalGovernanceBridge` had no live contract seam, so a patched contract could not deny an actionable recommendation
[0.45]     Implemented `SIGNAL_RECOMMENDATION_CONTRACT`; denied decisions skip queueing and emit a denial audit event
[Verify]   0.45 signal governance sweep green: 48 passed across signal/contract/payment parity suites; ruff + py_compile clean
[PR]       #531 opened as draft
[PR]       #531 full GitHub Actions green (17/17); marked ready and squash-merged @ c2e828c
[Docs]     #532 marked #531 merged in STATUS/SPRINT; full GitHub Actions green (15/15) and squash-merged @ b66c39d
[0.45]     Started plugin permission contract gate on `codex-o45-plugin-gate-contract`
[0.45]     Red test: `PermissionGate` had no live plugin-call contract seam, so a patched contract could not deny an otherwise allowed plugin call
[0.45]     Implemented `PLUGIN_CALL_CONTRACT`; `check_call()` delegates plugin-known/enabled/agent/network admissibility while preserving warning reasons
[Verify]   0.45 plugin gate sweep green: 186 passed across plugin/startup/integration/contract suites; ruff + py_compile clean
[PR]       #533 opened as draft
[PR]       #533 full GitHub Actions green (17/17); marked ready and squash-merged @ df111c7
[0.45]     Started social draft contract gate on `codex-o45-social-draft-contract`
[0.45]     Red test: `SocialBroker.request()` ignored a patched social-draft contract, so a denied draft could still enqueue
[0.45]     Implemented `SOCIAL_DRAFT_CONTRACT`; valid X post/reply/DM drafts still queue ask-tier, denied contract decisions return before preview/enqueue
[Verify]   Focused social governance suite green: 16 passed in `tests/test_social_h12_21.py`
[PR]       #535 opened as draft
[PR]       #535 full GitHub Actions green (16/16); marked ready and squash-merged @ 543e729
[Docs]     #536 marked #535 merged in BACKLOG/STATUS/SPRINT; full GitHub Actions green (15/15) and squash-merged @ 5fc8ccb
[0.45]     Started write-back draft contract gate on `codex-o45-writeback-contract-gate`
[0.45]     Red test: `WriteBackBroker.request()` ignored a patched write-back contract, so a denied GitHub issue draft could still enqueue
[0.45]     Implemented `WRITEBACK_DRAFT_CONTRACT`; valid Notion/GitHub/Calendar drafts still queue ask-tier, denied contract decisions return before preview/enqueue
[Verify]   Write-back contract sweep green: `tests/test_writeback_h10_30.py` 19 passed; adjacent writeback/social/contracts/action-auth/funnel sweep, ruff, py_compile, and status-sync clean
[PR]       #537 opened as draft
[PR]       #537 full GitHub Actions green (16/16); marked ready and squash-merged @ a9dbff9
[Docs]     #538 marked #537 merged in BACKLOG/STATUS/SPRINT; full GitHub Actions green (15/15) and squash-merged @ a3b7b22
[0.45]     Started outbound call contract gate on `codex-o45-call-contract-gate`
[0.45]     Red test: `CallBroker.request()` ignored a patched call contract, so a denied outbound-call proposal could still enqueue
[0.45]     Implemented `CALL_REQUEST_CONTRACT`; valid Twilio/Telnyx requests still queue ask-tier after interrupt-budget checks, denied contract decisions return before preview/enqueue
[Verify]   Call contract sweep green: `tests/test_call_broker_h12_22.py` 16 passed; adjacent call/writeback/social/contracts/action-auth/budget/loop-breaker sweep, ruff, py_compile, and status-sync clean
[PR]       #539 opened as draft
[PR]       #539 full GitHub Actions green (16/16); marked ready and squash-merged @ 7545485
[Docs]     #540 marked #539 merged in BACKLOG/STATUS/SPRINT; full GitHub Actions green and squash-merged @ 7794cec
[0.45]     Started Tool-RPC contract gate on `codex-o45-tool-rpc-contract-gate`
[0.45]     Red test: gated `ToolRPCServer.handle()` ignored a patched Tool-RPC contract, so a denied call could still enqueue
[0.45]     Implemented `TOOL_RPC_CALL_CONTRACT`; gated Tool-RPC calls now evaluate it before Action Kernel mediation and approval enqueue
[Verify]   Tool-RPC contract sweep green: focused Tool-RPC/kernel/contracts/action-auth sweep, ruff, py_compile, and status-sync clean
[PR]       #541 opened as draft
[PR]       #541 full GitHub Actions green (17/17); marked ready and squash-merged @ 16c0acd
[Docs]     #542 marked #541 merged in BACKLOG/STATUS/SPRINT; full GitHub Actions green and squash-merged @ d34dea8
[0.45]     Started NodeMesh dispatch contract gate on `codex-o45-node-dispatch-contract-gate`
[0.45]     Red test: `NodeMesh.dispatch()` ignored a patched node-dispatch contract, so a denied dispatch could still enqueue
[0.45]     Implemented `NODE_DISPATCH_CONTRACT`; valid governed node dispatches still ask-tier, denied contract decisions return before preview/enqueue
[Verify]   NodeMesh contract sweep green: focused NodeMesh/action-auth/contracts/kernel/tool-rpc sweep, ruff, py_compile, and status-sync clean
[PR]       #543 opened as draft
[PR]       #543 full GitHub Actions green (17/17); marked ready and squash-merged @ 550696a
[Docs]     #544 marked #543 merged in BACKLOG/STATUS/SPRINT; full GitHub Actions green (15/15) and squash-merged @ edf3dbb
[0.45]     Started media generation contract gate on `codex-o45-media-gen-contract-gate`
[0.45]     Red test: cloud `MediaGenManager.generate()` ignored a patched media-generation contract, so a denied cloud request could still enqueue
[0.45]     Implemented `MEDIA_GENERATION_CONTRACT`; cloud image/thumbnail/video requests now evaluate it before approval enqueue
[Verify]   Media-generation contract sweep green: focused media/contracts/funnel sweep, ruff, py_compile, and status-sync clean
[PR]       #545 opened as draft
[PR]       #545 full GitHub Actions green (17/17); marked ready and squash-merged @ fdc8246
[Docs]     #546 marked #545 merged in BACKLOG/STATUS/SPRINT; full GitHub Actions green (15/15) and squash-merged @ cf37e75
[0.45]     Started desktop step contract gate on `codex-o45-desktop-step-contract-gate`
[0.45]     Red test: mutating `GovernedDesktop.run()` ignored a patched desktop-step contract, so an approved click could still reach the driver
[0.45]     Implemented `DESKTOP_STEP_CONTRACT`; mutating desktop steps now evaluate it before approver callback or driver execution
[Verify]   Desktop-step contract sweep green: focused desktop/contracts/funnel sweep, ruff, py_compile, and status-sync clean
[PR]       #547 opened as draft
[PR]       #547 full GitHub Actions green (17/17); marked ready and squash-merged @ 3ac6ffb
```

---

## Metrici Wave 0

| Metric | Valoare |
|--------|---------|
| Story Points livrate | 15 SP |
| Teste noi | 45 |
| Total teste (main) | 1184+ passed, 8 skipped |
| PRs merguite | 3 (#53, #54, #55) |
| Buguri rezolvate | BUG-4 (diagnostics.md separat de BACKLOG.md) |
| Timp (estimat) | 1 sesiune |

---

> Template creat: 2026-06-02. Ultima actualizare: 2026-06-03 (docs/roadmap: v1.0 = tot backlogul; next thread = H17 + H14).
