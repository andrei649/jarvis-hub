# Jarvis Hub — Status Snapshot

> **Current version:** v0.11.0 (feature-complete + refactor done; productionizing toward 1.0) · **Tests:** ~3,848 passed (6 skipped; +79 from the H20 learning-loop merge and the migration-plan Phase 3/4/5 primitives, 2026-07-06) + frontend **183 vitest** + mobile **49 jest** + Playwright HUD/flow suites (HUD-v3 Console port complete: every blueprint surface + the north-star Decision Inbox + native Neural-Mesh canvas + cinema mode) · **Agents:** 17 active (16 cabinet incl. Howard + Argus, the WorldView bridge; + 17 bench) · **HTTP routes:** 368 (+ feedback widget/summary, H23.21; + onboarding, H23.20; +`/api/metrics/capabilities`, V2; + `/api/security/loop-breaker` status/reset, K3; + `/api/metrics/kernel`, Gate-K observability) — `web.py` decomposed into **45 per-domain routers** (CLN-3, #296); only 9 app-shell/chat/admin routes remain inline (4,636→1,282 LOC)
> **The version is the roadmap.** Every feature horizon (H1–H22 + WorldView O19) is delivered — that's **0.10.0**; the **0.11.0** refactor (CLN-3 `web.py` split + CLN-2 `orchestrator.py` managers) is done (#293/#296). There is no "audit gate" version: 1.0 is a real destination reached by finishing the productionization layer (**H23**: agentic-safety budgets, DB migrations, backup/restore + export-delete, operability, quality + user docs) **and** proving it with real design-partner users. The plan is the version line in [BACKLOG.md](BACKLOG.md#version-roadmap); strategy in [MOONSHOT.md](MOONSHOT.md) §4. Manual testing/audit ([docs/MANUAL_TESTING.md](docs/MANUAL_TESTING.md), [docs/AUDIT.md](docs/AUDIT.md)) is the release step that tags a version. GPU-gated dev (H12.14, H13.3, Howard) is its own minor (0.18). HUD deep write-controls tracked in [docs/design/HUD_V2_REMAINING.md](docs/design/HUD_V2_REMAINING.md).
>
> The version labels in the feature tables below (`v0.2.0`, `v0.2.1`) record *when* each capability first
> landed (provenance), not the current release. For live priorities and the version roadmap, BACKLOG.md is the source of truth.
>
> **Year-one review (candid, owner-facing):** [docs/REVIEW_YEAR_ONE.md](docs/REVIEW_YEAR_ONE.md) — status, the 12 learnings, the gap between *code-complete* and *desirable product*, and the next-90-days plan.
> **Hermes migration v3 plan (reviewed by Fable 2026-07-07 — APPROVED with notes; Phase 0–1 merged, Phase 2 delivered in #634):** [docs/research/2026-07-06-hermes-agent-migration-plan.md](docs/research/2026-07-06-hermes-agent-migration-plan.md) · verdict in [docs/handoff-fable-2026-07-07.md](docs/handoff-fable-2026-07-07.md) §5 · Phase 2 = context-compression maturity (`keep_first` + structured template + iterative merge + opt-in strict-local summarizer, defaults byte-identical)

---

## ORIZONT 26 Update — 2026-07-04

O26 Phase 0, P1.1, P2.1, P2.2, P2.3, P2.4, and P2.5 are complete on `main`.
O26-P3.1 preview modes is merged in #505; O26-P3.3 eval-baseline persistence is delivered in #506.
O26-P3.2 HUD punch-list reconciliation is merged in #507.
O26-P3.4 mobile approval queue is delivered in #509.
H18.12 mobile channel inbox parity is merged in #564: the native Comms tab reads Safe Comms inbox threads/messages and queues governed replies back into the existing approval funnel with `source:"mobile"`.
H18.13 mobile tasks parity is merged in #566: the native Tasks tab reads `GET /tasks`, preserves the honest empty state, and renders active/waiting/done counts plus owner/project/state cards.
H18.14 mobile status ambient/ticker parity is merged in #568: the native Status tab reads `GET /dashboard` and `GET /ticker` for ambient dashboard context plus live activity rows.
H18.15 mobile skills browser parity is merged in #570: the native Skills tab reads `GET /skills`, normalizes the skills map into a sorted read-only catalog, and excludes install/import/admin controls from the phone.
H18.16 mobile memory/notes parity is merged in #572: the native Memory tab reads `GET /memory` and `GET /api/notes`, rendering recent turns plus session notes without clear/save/rewrite controls.
H18.17 mobile knowledge graph parity is merged in #574: the native Memory tab now has a Graph view over `GET /api/kg/*`, rendering entity search/list, relations, current facts, and subject history without KG write/delete controls.
H18.18 mobile security posture parity is merged in #576: the native Status tab now has a read-only Trust card over governance, posture, kill-switch, and loop-breaker security reads without halt/reset/capability-write controls.
O26-P3.5 persona rail + caring follow-ups is delivered in #510.
O26-P3.6 landing page dev half is delivered in #512.
O26-P3.2 HUD depth tail delivered Data Spaces assign/unassign controls in #515; #517 adds the Rooms selected-history drawer; #519 adds capability issue/check UI; #521 adds current-mesh task fan; #523 adds preferences/tweaks UI; #525 adds self-hosted HUD fonts. The 0.44 Safe Comms draft-before-send UI is merged in #527 as a governed social-draft surface. #551 adds channel inbox transport v0 for telegram/web; owner live-data setup and non-v0 inbox channels remain partial.
0.45 High-Risk Automation Contracts now has ten merged live adoptions: #529 moves `PaymentBroker` request/approval admissibility onto `PAYMENT_CONTRACT`, #531 moves actionable Signal Layer recommendation queueing onto `SIGNAL_RECOMMENDATION_CONTRACT`, #533 moves plugin-known/enabled/agent/network checks onto `PLUGIN_CALL_CONTRACT`, #535 moves governed social draft-before-send requests onto `SOCIAL_DRAFT_CONTRACT`, #537 moves governed Notion/GitHub/Calendar write-back drafts onto `WRITEBACK_DRAFT_CONTRACT`, #539 moves outbound call requests onto `CALL_REQUEST_CONTRACT` before preview/enqueue, #541 moves gated Tool-RPC calls onto `TOOL_RPC_CALL_CONTRACT` before kernel mediation and approval enqueue, #543 moves governed NodeMesh dispatch onto `NODE_DISPATCH_CONTRACT` before preview/enqueue, #545 moves cloud media generation onto `MEDIA_GENERATION_CONTRACT` before approval enqueue, and #547 moves mutating desktop operator steps onto `DESKTOP_STEP_CONTRACT` before approver/driver execution.
H17.1a inbound-origin construction is merged in #549: direct public turn entrypoints now bind origin, internal orchestrator channels stay trusted, inbound parent contexts are monotone, and plugin-egress actions no longer hard-code `origin="generated"`.
0.45 Batch B1 is merged in #550: `contract_denial()` centralizes denial reason fallback, skill marketplace publish/install/uninstall use `SKILL_INSTALL_CONTRACT`, LLM-authored skill creation/approval uses `SKILL_GENERATION_CONTRACT`, and remediation/LM Studio subprocess controls share `HOST_CONTROL_CONTRACT`.
Eval Nightly parser hotfix #552 is merged: cache-key `hashFiles(...)` now lives in the cache action keys instead of job-level `env`, so GitHub creates real eval jobs again. LivingMemory recall + real eval mode is merged in #553: already-fused hits can be TCM re-ranked by LivingMemory `turn_ref` metadata, and `mode=recall` exercises a real `MemoryManager.remember()`/`recall()` eval path. DailyReflector durable LivingMemory handoff is merged in #554. LivingMemory core prompt injection is merged in #555. LivingMemory core persistence is merged in #556. LivingMemory tier persistence is merged in #557. LivingMemory forget-purge completeness is merged in #558. LivingMemory re-projection maintenance is merged in #559. LivingMemory re-projection embedder wiring is merged in #560. LivingMemory recall reactivation is merged in #561. LivingMemory duplicate encoding gate is merged in #562. R1/R4 Oracle + MCP host-execution hardening is merged in #578. R2 taint propagation teeth is merged in #580. R3-B2 memory/forget contracts are merged in #582. R3-B3 A2A/escalation contracts are merged in #584. R3-B4 MCP route-tool contracts are merged in #586. R3-B5 channel-send contracts are merged in #588. TASK-3 channel-ingress taint is merged in #590. AUD-14 channel send-rate env-int is merged in #592. M3.5/#169 WorldView MCP write transport is merged in #594. AUD-14 LLM model-name config is merged in #596. AUD-14 task-budget env-float is merged in #598. AUD-14 analytics max-events env-int is merged in #600. AUD-14 STT beam-size env-int is merged in #602. AUD-14 log rotation env-int is merged in #604. AUD-14 call-config env-json is merged in #606. AUD-14 channel-rates env-map is merged in #608. AUD-14 email-port env-int is merged in #610. AUD-14 vector-dimension env-int is merged in #612. AUD-14 skill-history env-flag is merged in #614. AUD-14 webhook-channels env-json is merged in #616. AUD-14 CORS-origins env-list is merged in #618. AUD-14 plugin-grants env-list is merged in #620. AUD-14 trust env-flags is merged in #622. Hermes migration v3 was reviewed by Fable on 2026-07-07 — APPROVED with notes (Phase 0–1 already merged; remaining-phase order in docs/handoff-fable-2026-07-07.md §5).

| Item | Status | Verified result |
|------|--------|-----------------|
| O26-P1.1 one-turn pipeline | ✅ merged | `Agent.build_prompt()` is shared by plain/stream paths; `_build_agent_turn_text()` injects persona + runtime truth + history/plugins/recall for both; `_complete_llm_turn()` centralizes memory/checkpoint/log/learning+bench/run-history/audit/cognition; `PersonaModule.nudge()` runs once per completed LLM turn when affect is enabled. |
| O26-P2.1 config consolidation | ✅ merged | `agents/core/env_config.py` is now the single boolean/env parsing leaf; ad-hoc env truthiness is ratcheted by tests. |
| O26-P2.2 memory consolidation | ✅ merged (#501) | `_complete_llm_turn()` records LivingMemory + decay entries only when `cognition.enabled && cognition.memory_enabled`; LivingMemory stores session/agent/channel, a turn reference, text digest, and size counters rather than duplicating raw transcript text. `SchedulerService` registers `memory-consolidation-decay` and `run_memory_maintenance()` performs NREM/REM consolidation plus decay candidate inspection without auto-deletion. |
| O26-P2.3 dormant disposition | ✅ merged (#502) | `load_agents()` now registers active agents into `PersonaModule` + `EnsembleModule`; `cognition.learning_enabled` is proven live through the autonomy calibration hook; `profile_extractor.legacy_status()` marks the old regex extractor parked with no production callers. |
| O26-P2.4 product posture | ✅ merged (#503) | `product.posture` defaults OFF; selecting `companion_wave1` or `design_partner` overlays wave-1 memory/cognition flags at runtime and surfaces provenance in security posture, onboarding wizard, and support bundle. Wave 2 kernel/budget/REDACT hardening remains future scope. |
| O26-P2.5 install smoke | ✅ merged (#504) | `scripts/install_smoke.py` provides the fast install path: real orchestrator boot with one fake local LLM backend, `/readyz` check, deterministic chat turn; `--dev` runs the full pytest suite after the smoke succeeds. |
| O26-P3.1 live preview modes | ✅ merged (#505) | The six preview modes now feed LIVE/SEED mode keys: Build reads workflows/marketplace/sandbox; Comms reads rooms plus registered Discord/Slack channel status and renders an honest empty state; Finance reads saved watchlist/payments while refusing mock balances; Health/Knowledge/Family require configured Apple Health/websearch/WhatsApp plugins. `/plugins` now reports runtime `configured`; `/status` reports channels. Owner live-data/plugin setup remains. |
| O26-P3.3 eval baseline persistence | ✅ delivered (#506) | `.github/workflows/eval-nightly.yml` restores/saves the companion eval `DatasetStore` via pinned `actions/cache/{restore,save}` and an explicit `JARVIS_EVAL_STORE`; `companion_eval --ci-gate --store-root` records to that store, so baseline compare is no longer inert after the first successful scheduled/manual run. |
| O26-P3.2 HUD punch-list reconciliation/depth | 🟡 partial (#507 + #515 + #517 + #519 + #521 + #523 + #525 + #527) | `docs/design/HUD_V2_REMAINING.md` now distinguishes shipped controls from real remaining work, and `hud-p3-2-reconciliation.test.ts` pins that shipped TTS/mic/cognition/trust and Console controls are not re-listed as missing. #515 wires Data Spaces assign/unassign in `DataSpacesPanel`; #517 wires the selected-room history drawer in `RoomsPanel`; #519 wires capability issue/check UI in `CapabilitiesPanel`; #521 wires live `/tasks` spokes/dots into `NeuralMesh`; #523 wires look/density/motion/texture preferences into the command palette; #525 vendors Space Grotesk + JetBrains Mono WOFF2 assets and pins local font loading; #527 adds the Safe Comms draft panel to queue governed X post/reply/DM drafts through `/api/integrations/social`. #551 adds channel inbox transport v0 for telegram/web; remaining tail is owner live-data/plugin setup plus non-v0 inbox channels. |
| O26-P3.4 mobile approval queue | ✅ delivered (#509) | Mobile gains an Approvals tab over the unified autonomy queue, optional `X-Admin-Token` persistence, approve/reject/defer calls, README/PARITY updates, and a mobile API contract test. |
| H18.13 mobile tasks board | ✅ merged (#566) | Native Tasks tab reads the read-only `/tasks` HUD task-fan surface, uses the existing user-token path, shows active/waiting/done counts and task cards, and keeps empty queues visibly empty. Local red/green: the new mobile API test first failed on missing `fetchTasks`, then full mobile Jest passed (28), mobile `tsc --noEmit` passed, and full PR CI went green before merge. |
| H18.14 mobile status ambient/ticker | ✅ merged (#568) | Native Status tab reads the read-only `/dashboard` and `/ticker` HUD surfaces, keeps those companion loads non-fatal, and renders honest empty states. Local red/green: the new mobile API test first failed on missing `fetchDashboard`/`fetchTicker`, then full mobile Jest passed (32), mobile `tsc --noEmit` passed, and full PR CI went green before merge. |
| H18.15 mobile skills browser | ✅ merged (#570) | Native Skills tab reads the read-only `/skills` catalog, normalizes the backend map into a sorted array, shows skill metadata without write controls, and keeps empty catalogs visibly empty. Local red/green: the new mobile API test first failed on missing `fetchSkills`, then full mobile Jest passed (35), mobile `tsc --noEmit` passed, and full PR CI went green before merge. |
| H18.16 mobile memory + notes | ✅ merged (#572) | Native Memory tab reads the read-only `/memory` and `/api/notes` surfaces, shows recent turns plus session notes without write controls, and keeps empty histories visibly empty. Local red/green: the new mobile API test first failed on missing `fetchMemory`/`fetchNotes`, then full mobile Jest passed (38), mobile `tsc --noEmit` passed, and #572 full GitHub Actions passed before merge. |
| H18.17 mobile knowledge graph | ✅ merged (#574) | Native Memory tab adds a read-only Graph view over `/api/kg/entities`, `/api/kg/entities/{name}`, `/api/kg/facts/as-of`, and `/api/kg/facts/history`, showing entity search/list, selected relations, current facts, and subject history without write/delete controls. Local red/green: the new mobile API test first failed on missing `fetchKg*` helpers, then full mobile Jest passed (42), mobile `tsc --noEmit` passed, and #574 full GitHub Actions passed before merge. |
| H18.18 mobile security posture | ✅ merged (#576) | Native Status tab adds a read-only Trust card over `/api/security/governance`, `/api/security/posture`, `/api/security/kill-switch`, and `/api/security/loop-breaker`, using the existing admin token for posture and keeping operator write controls off mobile. Local red/green: the new mobile API test first failed on missing `fetchSecurity*` helpers, then full mobile Jest passed (46), mobile `tsc --noEmit` passed, and full PR CI went green before merge. |
| O26-P3.5 persona rail + caring follow-ups | ✅ delivered (#510) | `QualityMonitor` now scores optional versioned persona profiles against assistant `output_preview`, stores `persona_score`/`soul_version`, and exposes persona drift stats. The live cognition trace seam derives a compact profile from the current SOUL version without storing full SOUL text. Morning brief + unified digest now surface caring follow-ups from existing failed/blocked tasks, open-concern memory facts, and upcoming/date facts. |
| O26-P3.6 landing page dev half | ✅ delivered (#512) | `marketing/landing/index.html` is a self-contained static landing page built from the marketing copy spine and Brand Book tokens, with `demo-shot-list.md` carrying the owner-recorded M4 capture checklist. Full GitHub Actions passed before merge; owner-recorded video remains M4. |
| 0.45 social draft contract gate | ✅ merged (#535) | `agents/core/social.py` now exposes `SOCIAL_DRAFT_CONTRACT`; valid X post/reply/DM drafts still queue through the ask-tier approval path, while a denied live contract decision returns a controlled reason before preview/enqueue. Local red/green: the new regression first proved patched contracts were ignored, then `tests/test_social_h12_21.py` passed (16 passed). Full GitHub Actions passed before merge. |
| 0.45 write-back draft contract gate | ✅ merged (#537) | `agents/core/writeback.py` now exposes `WRITEBACK_DRAFT_CONTRACT`; valid Notion/GitHub/Google Calendar drafts still queue through the ask-tier approval path, while a denied live contract decision returns a controlled reason before preview/enqueue. Local red/green: the new regression first proved patched contracts were ignored, then `tests/test_writeback_h10_30.py` passed (19 passed); adjacent writeback/social/contracts/action-auth/funnel sweep, ruff, py_compile, and status sync are green. Full GitHub Actions passed before merge. |
| 0.45 outbound call contract gate | ✅ merged (#539) | `agents/core/autonomy/call_broker.py` now exposes `CALL_REQUEST_CONTRACT`; valid Twilio/Telnyx outbound call requests still queue through the ask-tier approval path after the interrupt-budget gate, while a denied live contract decision returns a controlled reason before preview/enqueue. Local red/green: the new regression first proved patched contracts were ignored, then `tests/test_call_broker_h12_22.py` passed (16 passed); adjacent call/writeback/social/contracts/action-auth/budget/loop-breaker sweep, ruff, py_compile, and status sync are green. Full GitHub Actions passed before merge. |
| 0.45 Tool-RPC contract gate | ✅ merged (#541) | `agents/core/tool_rpc.py` now exposes `TOOL_RPC_CALL_CONTRACT`; gated Tool-RPC calls evaluate it after allowlist/args validation but before Action Kernel mediation and approval enqueue. Local red/green: the new regression first proved patched contracts were ignored, then passed; focused Tool-RPC/kernel/contracts/action-auth sweep, ruff, py_compile, and status sync are green. Full GitHub Actions passed before merge. |
| 0.45 NodeMesh dispatch contract gate | ✅ merged (#543) | `agents/core/node_mesh.py` now exposes `NODE_DISPATCH_CONTRACT`; governed node dispatches evaluate it after node/capability authorization but before preview/enqueue. Local red/green: the new regression first proved patched contracts were ignored, then passed; focused NodeMesh/action-auth/contracts/kernel sweep, ruff, py_compile, and status sync are green. Full GitHub Actions passed before merge. |
| 0.45 media generation contract gate | ✅ merged (#545) | `agents/core/media_gen.py` now exposes `MEDIA_GENERATION_CONTRACT`; cloud image/thumbnail/video generation evaluates it before approval enqueue. Local red/green: the new regression first proved patched contracts were ignored, then passed; focused media/contracts/funnel sweep, ruff, py_compile, and status sync are green. Full GitHub Actions passed before merge. |
| 0.45 desktop step contract gate | ✅ merged (#547) | `agents/core/desktop_operator.py` now exposes `DESKTOP_STEP_CONTRACT`; mutating desktop steps evaluate it before approver callback or driver execution. Local red/green: the new regression first proved patched contracts were ignored, then passed; focused desktop/contracts/funnel sweep, ruff, py_compile, and status sync are green. Full GitHub Actions passed before merge. |
| H17.1a inbound origin by construction | ✅ merged (#549) | `agents/core/action_origin.py` now classifies operator/internal turn channels as trusted and exposes monotone `bind_turn_action_origin()`; `Orchestrator.handle_input()` and `handle_input_stream()` bind/reset origin at the public chokepoint so direct MCP/webhook/router calls cannot bypass provenance; plugin-egress actions use `current_action_origin()`. Red/green: `tests/test_h17_origin_by_construction.py` first failed across channel classification, direct entrypoint binding, and hard-coded egress origin, then passed (+8). Full GitHub Actions passed before merge. |
| 0.45 Batch B1 skill + host-control contract gates | ✅ merged (#550) | `agents/core/automation_contracts.py` adds `contract_denial()`; `SkillMarketplace` gates publish/install/uninstall through `SKILL_INSTALL_CONTRACT`; `SkillLoader` gates generated-skill creation and owner promotion through `SKILL_GENERATION_CONTRACT`; `RemediationRunner.restart()` and `LMStudioController` start/load/unload use shared `HOST_CONTROL_CONTRACT` before host subprocess control. Red/green: `tests/test_o45_b1_contracts.py` first proved patched contracts were ignored at all four seams, then passed (+8). Full GitHub Actions passed before merge. |
| Safe Comms channel inbox transport v0 | ✅ delivered (#551 + #564) | `ChannelInboxStore` persists bounded telegram/web inbound threads after sender pairing allows them; `Gateway.route` records live inbox messages; `ChannelReplyBroker` gates replies through `CHANNEL_REPLY_CONTRACT`, queues `channel.reply` tasks into the existing approval funnel, and approved tasks send through `ChannelManager.send` while recording the outbound message. HUD Comms reads `/api/channels/inbox` and enables the governed reply form only for live inbox rows; seeded preview rows stay disabled. The native mobile Comms tab now lists those threads, reads selected-thread messages, and queues governed replies through `POST /api/channels/inbox/{thread_id}/reply` with `source:"mobile"`. Local verification: Safe Comms backend (+8), route/OpenAPI/type gates, adjacent backend sweep, frontend typecheck, full Vitest (172), HUD build, full PR CI green for #551, plus mobile Jest (26), clean mobile `tsc --noEmit`, and full PR CI green for #564. |
| LivingMemory recall + real eval mode | ✅ merged (#553) | `agents/core/memory/living_recall.py` post-fusion re-ranks only hits whose ids match LivingMemory `turn_ref`, annotates non-private provenance, then preserves the existing `rag_guard` prompt fence. `run_recall_eval()` ingests eval facts into a deterministic real `MemoryManager` and `/api/memory/eval/run?mode=recall` exposes the mode while keyword remains default. Focused red/green suite was 6 passed; adjacent memory/eval suite was 44 passed; full PR CI went green before merge. |
| DailyReflector durable LivingMemory handoff | ✅ merged (#554) | `ReflectionRunStore` gives nightly reflection durable same-day idempotency across restarts, `/api/reflection/run` now uses `force=True` for manual reruns, and extracted lessons encode into LivingMemory/core only when `cognition.memory_enabled` is active. Tier records store lesson digest/length metadata, not raw conversation text. Full PR CI went green before merge. |
| LivingMemory core prompt injection | ✅ merged (#555) | `_build_agent_turn_text()` now receives a gated `[core memory]` block from `living.core.list()` even when vector recall is disabled. Facts are whitespace-normalized, capped per line, and labeled as background facts, not instructions. Full PR CI went green before merge. |
| LivingMemory core persistence | ✅ merged (#556) | `CoreMemory(path=...)` persists its bounded de-duplicated fact ring via `JsonStore`, `LivingMemory(core_path=...)` reloads it, and production Orchestrator registers LivingMemory with `memory_logs/cognition/core_memory.json` under `JARVIS_HOME`. Full PR CI went green before merge. |
| LivingMemory tier persistence | ✅ merged (#557) | `TieredMemory(path=...)` persists metadata records through add/access/maintenance/explicit forget, `LivingMemory(tiers_path=...)` reloads them, and production Orchestrator registers LivingMemory with `memory_logs/cognition/living_tiers.json` under `JARVIS_HOME`. Full PR CI went green before merge. |
| LivingMemory forget purge completeness | ✅ delivered (#558) | `purge_data(memory=True)` now deletes `memory_logs/cognition/core_memory.json` and `memory_logs/cognition/living_tiers.json`, and `clear_live_memory()` clears live `LivingMemory` core/tier state before at-rest deletion so a running process cannot re-save forgotten facts. Red/green focused purge suite is 5 passed; adjacent LivingMemory/consolidation sweep is 29 passed. |
| LivingMemory re-projection maintenance | ✅ delivered (#559) | `LivingMemory.reproject_stale(embedder=...)` persists upgraded vector/embed-version fields for stale tier records, and `SchedulerService.run_memory_maintenance()` now includes a best-effort `reprojection` section. The hook remains best-effort and reports `embedder_unavailable` when no embedder is provided. |
| LivingMemory re-projection embedder wiring | ✅ merged (#560) | `SchedulerService.run_memory_maintenance()` passes `orch.memory.embed` into `LivingMemory.reproject_stale()` when available, and re-projection serializes structured tier content deterministically before embedding. Full PR CI went green before merge. |
| LivingMemory recall reactivation | ✅ merged (#561) | Matched LivingMemory recall hits now refresh `LivingMemory.access()` and optional `DecayMemory.access()` so useful recalled traces get warmer instead of remaining read-only ranking hints. |
| LivingMemory duplicate encoding gate | ✅ merged (#562) | Exact duplicate completed-turn digests map to zero surprise, skip another LivingMemory tier record, and avoid an extra decay entry. |
| R1/R4 Oracle + MCP host-execution gate | ✅ merged (#578) | Oracle external commits now have a repo-sync contract + Action Kernel chokepoint before pull/test, kernel-off default-refuses, queued decisions do not pull, MCP stdio startup uses argv exec instead of shell, and outbound MCP tool calls evaluate a live contract before JSON-RPC send. |
| R2 taint propagation teeth | ✅ merged (#580) | Inbound autonomy tasks now get tainted at worker intake and forced to ASK even when policy would ACT; edited inbound payloads are re-tainted before policy re-evaluation; inbound user-turn embeddings carry taint metadata; recall provenance prefers taint source over generic vector source. Full PR CI green before merge. |
| R3-B2 memory/forget contracts | ✅ merged (#582) | External KG writes now evaluate `KG_WRITE_CONTRACT` before kernel mediation/mutation; destructive `purge_data` and `/api/admin/forget` evaluate `DATA_PURGE_CONTRACT` before live-memory clear or at-rest deletion. Full PR CI green before merge. |
| R3-B2 local verification | ✅ targeted green | Red/green: patched denying contracts first failed across KG write, purge, and forget-route seams, then passed (4). Adjacent KG kernel/editor/bitemporal/ingest sweep passed (33); data purge + old O45 contract sweep passed (21); touched-file ruff and py_compile were clean. |
| R3-B3 A2A/escalation contracts | ✅ merged (#584) | Inbound A2A tasks now evaluate `A2A_INBOUND_CONTRACT` after enable/allowlist/HMAC/JSON validation but before pending-inbox writes; escalation fan-out now evaluates `ESCALATION_CONTRACT` after target resolution but before adapter sends. Full PR CI green before merge. |
| R3-B3 local verification | ✅ targeted green | Red/green: patched denying contracts first failed because A2A still wrote to the inbox and escalation still sent to channels, then passed (2). Focused + adjacent A2A/escalation/automation-contract sweep passed (55); touched-file ruff and py_compile were clean. |
| R3-B4 MCP route-tool contracts | ✅ merged (#586) | Mutating MCP route tools now evaluate `MCP_MUTATING_ROUTE_CONTRACT` after identity succeeds and before Action Kernel mediation or the write adapter. Denied contracts audit `refused-contract`, return a controlled MCP tool error, and never call the route writer. Full PR CI green before merge. |
| R3-B4 local verification | ✅ targeted green | Red/green: a patched denying contract first failed because `route_memory_remember` still wrote, then passed (2). Focused MCP route-tool tests passed; adjacent MCP client/kernel/bypass/automation-contract/Oracle contract sweep passed; touched-file ruff, py_compile, and status-sync are clean. |
| R3-B5 channel-send contracts | ✅ merged (#588) | Generic `ChannelManager.send()` now evaluates `CHANNEL_SEND_CONTRACT` after adapter lookup and before telegram/web/voice adapter I/O. The payload is shape-only: channel id, message length, kwarg keys, and counts; denied contracts return `False` and never call the adapter. Full PR CI green before merge. |
| R3-B5 local verification | ✅ targeted green | Red/green: patched denying/capturing contracts first failed because `ChannelManager.send()` ignored the contract, then passed (2). Focused Safe Comms/send-rate-limit suite passed (22); adjacent cross-channel/webhook/escalation/origin sweep passed (57); touched-file ruff and py_compile were clean. |
| TASK-3 channel ingress taint | ✅ merged (#590) | `Gateway.route()` now marks untrusted inbound channel messages with private `_inbound_meta` while preserving plain `str` handler text; `ChannelInboxStore` persists only public `tainted`, `taint_source`, and `injection_flags` fields; `Orchestrator.channel_handler()` strips private gateway metadata before outbound adapter sends. Full PR CI green before merge. |
| TASK-3 local verification | ✅ targeted green | Red/green: the new channel-ingress tests first failed because telegram lacked `_inbound_meta` and inbox rows lacked public taint fields, then passed (+2). Focused TASK-3 + Safe Comms inbox sweep passed (10); adjacent pairing/cross-channel/action-origin/R2 taint/quarantine sweep passed (49); touched-file ruff, py_compile, and status-sync were clean. |
| AUD-14 channel send-rate env-int | ✅ merged (#592) | `agents/core/channels/send_rate_limit.py` now reads the global `JARVIS_CHANNEL_SEND_RATE` cap through `env_int("JARVIS_CHANNEL_SEND_RATE", 0, minimum=0)` via a single `_global_cap()` helper reused by `limit_for()` and `configured_rates()`. Per-channel overrides remain unchanged. Full PR CI was green before merge. |
| AUD-14 local verification | ✅ targeted green | Red/green: the new static ratchet first failed because `send_rate_limit.py` still lacked `env_int`, while malformed/negative cap behavior was pinned as unlimited. Focused send-rate suite passed (15); adjacent AUD-14 env-config + send-rate sweep passed (51); touched-file ruff and py_compile were clean. |
| AUD-14 LLM model-name config | ✅ merged (#596) | `agents/core/llm/model_config.py` centralizes default model IDs plus the `JARVIS_DEEP_MODEL` override; `HybridRouter` now reads the shared deep-model config per instance/detect and no longer owns the direct env read. New guard tests pin the override helper and router integration (+3). Full PR CI was green before merge. |
| AUD-14 task-budget env-float | ✅ merged (#598) | `JARVIS_TASK_MAX_SECONDS` now uses shared `env_float(..., minimum=0.0)` instead of local try/except parsing in `AutonomyCoordinator.build_executor`; full PR CI was green before merge. |
| AUD-14 analytics max-events env-int | ✅ merged (#600) | `JARVIS_ANALYTICS_MAX_EVENTS` now uses shared `env_int(..., minimum=0)` instead of import-time `int(os.environ...)`, so malformed values fall back to the bounded default instead of crashing analytics import; full PR CI was green before merge. |
| AUD-14 STT beam-size env-int | ✅ merged (#602) | `JARVIS_STT_BEAM_SIZE` now uses shared `env_int(..., minimum=1)` instead of local `int(os.environ...)`; malformed and non-positive values fall back to the greedy decode default. Full PR CI was green before merge. |
| AUD-14 log rotation env-int | ✅ merged (#604) | `JARVIS_LOG_MAX_MB` and `JARVIS_LOG_BACKUPS` now use shared `env_int()` parsing while preserving settings-DB fallback before hardcoded defaults; full PR CI was green before merge. |
| AUD-14 call-config env-json | ✅ merged (#606) | `JARVIS_CALL_CONFIG` now uses shared `env_json_object()` parsing instead of local `json.loads(os.environ...)` in `AutonomyCoordinator.build_executor`; full PR CI was green before merge. |
| AUD-14 channel-rates env-map | ✅ merged (#608) | `JARVIS_CHANNEL_SEND_RATES` now uses shared `env_int_map()` parsing instead of a module-local parser in `channels/send_rate_limit.py`; full PR CI was green before merge. |
| AUD-14 email-port env-int | ✅ merged (#610) | `SMTP_PORT` and `IMAP_PORT` now use shared `env_int()` parsing instead of raw `int(os.environ...)` in `web.py`; full PR CI was green before merge. |
| AUD-14 vector-dimension env-int | ✅ merged (#612) | `VECTOR_DIMENSION` now uses shared `env_int(..., minimum=1)` parsing instead of raw `int(os.getenv...)` in `memory/manager.py`; full PR CI was green before merge. |
| AUD-14 skill-history env-flag | ✅ merged (#614) | `JARVIS_SKILL_HISTORY` now uses shared `env_flag()` parsing instead of presence-check truthiness in `orchestrator.py`; full PR CI was green before merge. |
| AUD-14 webhook-channels env-json | ✅ merged (#616) | `JARVIS_WEBHOOK_CHANNELS` now uses shared `env_json_object()` parsing instead of local `json.loads()` in `web.py`; full PR CI was green before merge. |
| AUD-14 CORS-origins env-list | ✅ merged (#618) | `JARVIS_CORS_ORIGINS` now uses shared `env_list()` parsing instead of local split/strip parsing in `web.py`; full PR CI was green before merge. |
| AUD-14 plugin-grants env-list | ✅ merged (#620) | `JARVIS_PLUGIN_GRANTS` now uses shared `env_list()` parsing instead of local comma splitting in `plugin_gate.py`; full PR CI was green before merge. |
| AUD-14 trust env-flags | ✅ merged (#622) | `JARVIS_MIC_MUTED` and `JARVIS_STRICT_LOCAL` now use shared `env_flag()` parsing instead of direct router env reads; full PR CI was green before merge. |
| M3.5 WorldView MCP write transport | ✅ merged (#594) | `WorldViewMCPWriteClient` registers the WorldView stdio MCP server with per-process `WORLDVIEW_MCP_SECRET`, gates `watch_aoi`/`reconstruct_event` through `PermissionGate`, Action Kernel, and per-agent `plugin:worldview` broker capability, then mints the scoped HMAC token only after gates pass. `ArgusInterface` delegates write calls through that client while `WorldViewPlugin` stays read-only. Full PR CI was green before merge. |
| M3.5 local verification | ✅ targeted green | Red/green: the new MCP process-options test first failed on missing `cwd` support; the WorldView write transport tests first failed on missing module; Argus tests first failed on missing write wiring. Focused MCP/capability/write/Argus suite passed (31); adjacent WorldView plugin/bridge/Argus/MCP host-exec sweep passed (24); touched-file ruff and py_compile were clean. |
| Local verification | ✅ targeted green | R2 red/green: the new queue/memory/provenance tests first failed across auto-approval, missing `channel`, and generic vector provenance, then passed (5). R2 adjacent origin/taint sweep passed (39), autonomy worker/queue/API sweep passed (84), memory/RAG/living-recall sweep passed (37), touched-file ruff and py_compile were clean. R1/R4 red/green: the new Oracle/MCP safety tests first failed on missing Oracle kernel/contract mediation plus MCP shell/contract bypasses, then `tests/test_oracle_mcp_host_exec_gate.py`, `tests/test_mcp_client.py`, and `tests/test_action_auth_matrix.py` passed (24). The adjacent R1/R4 sweep with O45 and MCP API/admin tests passed (53), touched-file ruff and py_compile were clean. P2.2 focused sweep was 33 passed before #501 merge; P2.3 red/green tests (+4) plus ensemble, governed learning, persona, and memory-store suites are 48 passed before #502 merge. P2.4 focused posture/onboarding/security/support/lifespan/settings sweep was 39 passed locally; PR #503 full CI matrix green before merge. P2.5 smoke tests were green, `python scripts/install_smoke.py --json` exited 0 locally, and PR #504 full CI matrix was green before merge. P3.1 focused checks and full PR CI were green. P3.3 companion eval suites are green (19 passed), CLI store-root gate exits 0, and ruff/py_compile are clean. P3.2 red doc-guard is green locally and #507 full GitHub Actions passed before merge. P3.4 mobile Jest suite is green (22 passed) and mobile typecheck is clean. H18.12 mobile channel inbox parity is green locally: red API test first failed on missing client functions, then full mobile Jest passed (26) and `npx tsc --noEmit` passed. H18.13 mobile tasks board is green locally: red API test first failed on missing `fetchTasks`, then full mobile Jest passed (28) and `npx tsc --noEmit` passed. H18.14 mobile status ambient/ticker is green: red API test first failed on missing `fetchDashboard`/`fetchTicker`, then full mobile Jest passed (32), `npx tsc --noEmit` passed, and #568 full GitHub Actions passed before merge. H18.15 mobile skills browser is green locally: red API test first failed on missing `fetchSkills`, then full mobile Jest passed (35), and `npx tsc --noEmit` passed. H18.16 mobile memory/notes is green: red API test first failed on missing `fetchMemory`/`fetchNotes`, then full mobile Jest passed (38), `npx tsc --noEmit` passed, and #572 full GitHub Actions passed before merge. H18.17 mobile knowledge graph is green: red API test first failed on missing `fetchKg*` helpers, then full mobile Jest passed (42), `npx tsc --noEmit` passed, and #574 full GitHub Actions passed before merge. H18.18 mobile security posture is green: red API test first failed on missing `fetchSecurity*` helpers, then full mobile Jest passed (46), `npx tsc --noEmit` passed, and #576 full GitHub Actions passed before merge. P3.5 local suite was green (6 passed), adjacent quality/digest/timeline/autonomy endpoint suites were green (41 + 37 passed), touched-file ruff/py_compile were clean, and #510 full GitHub Actions passed before merge. P3.6 landing contract was green locally (4 passed), visual local-file smoke passed at desktop/mobile viewports, and #512 full GitHub Actions passed before merge. P3.2 Data Spaces depth: focused HUD tests green (8 passed), full frontend Vitest green (164 passed), typecheck/status-sync/diff-check clean, and #515 full GitHub Actions passed before merge. P3.2 Rooms history drawer: focused HUD panel test green (5 passed), full frontend Vitest green (165 passed), typecheck/build/status-sync/diff-check clean, and #517 full GitHub Actions passed before merge. P3.2 Capability issue/check UI: focused HUD panel test green (6 passed), focused HUD sweep green (10 passed), full frontend Vitest green (166 passed), typecheck/build/status-sync/diff-check clean, and #519 full GitHub Actions passed before merge. P3.2 mesh task fan: red-proved `NeuralMesh` did not surface `/tasks`; focused mesh test green (4 passed), adjacent mesh/cinema sweep green (8 passed), full frontend Vitest green (167 passed), typecheck/build/status-sync/diff-check clean, and #521 full GitHub Actions passed before merge. P3.2 preferences/tweaks UI: red-proved the command palette had no Look/Motion/Comfy controls; focused palette test green (1 passed), full frontend Vitest green (168 passed), typecheck/build/status-sync/diff-check clean, and #523 full GitHub Actions passed before merge. P3.2 self-hosted fonts: red-proved missing local WOFF2 assets and CSS declarations; focused font guard green (2 passed), full frontend Vitest green (170 passed), typecheck/build clean, and #525 full GitHub Actions passed before merge. Safe Comms draft UI: red-proved no panel existed, then focused Vitest green (1 passed) for catalog load + queued reply payload; full frontend Vitest green (171 passed), typecheck/build/status-sync/diff-check clean, and #527 full GitHub Actions passed before merge. 0.45 payment contract live gate: red-proved the request/approve paths ignored a patched contract, then targeted payment/contract/kernel/auth sweep green (76 passed), ruff/py_compile clean, and #529 full GitHub Actions passed before merge. 0.45 signal governance contract gate: red-proved the bridge had no live contract, then signal/contract/payment parity sweep green (48 passed), ruff/py_compile clean, and #531 full GitHub Actions passed before merge. 0.45 plugin permission contract gate: red-proved `PermissionGate` had no live plugin-call contract, then plugin/startup/integration/contract sweep green (186 passed), ruff/py_compile clean, and #533 full GitHub Actions passed before merge. H20 migration-plan Phase 4 (LLM provider profile registry) is merged in #625: `agents/core/llm/providers/` adds a declarative `ProviderProfile`/`ProviderRegistry` (6 built-in profiles: lm-studio, ollama, gemini, anthropic, openrouter, openai-compatible) and `HybridRouter.provider_catalog()` as a read-only status accessor; routing decisions are unchanged. H20 migration-plan Phase 5 preliminary (channel session primitives) is merged in #626: `agents/core/channels/session.py` adds pure `SessionSource`/`DeliveryTarget`/`build_session_key()`/`DeliveryRouter` helpers; live gateway routing is unchanged. H20 migration-plan Phase 3 preliminary (execution environment primitives) is merged in #627: `agents/core/environments/` describes local/docker/ssh backend profiles plus `scrub_child_env`/`prepare_python_child_env` (secret-name filtering, safe-prefix allowlist, `WINDOWS_ESSENTIAL_ENV_VARS`). H20 migration-plan Phase 3 (file-RPC primitives) is merged in #628: `environments/file_rpc.py`'s `FileRPCStore` is a UTF-8 JSON request/response store with an atomic tmp+replace write and a tool-call budget, the foundation for a remote Docker/SSH `execute_code` transport (not yet wired into `tool_rpc.py`). H20 migration-plan Phase 3 (output-limit helpers) is merged in #629: `truncate_text()` keeps head+tail content under a byte budget with an explicit, non-hidden truncation notice. #630 wires the Phase-3 env-scrub LIVE into `Sandbox`: `_run_python`/`_run_shell` now spawn every subprocess/Docker child via `prepare_python_child_env(os.environ)` instead of the raw host environment. #631 wires the Phase-3 output cap LIVE: `Sandbox(max_output_bytes=50_000)` truncates stdout/stderr through `truncate_text()` before returning `SandboxResult`, closing the DoS-via-output vector. Hermes migration plan Phase 0–1 (the closed per-turn learning loop) is merged to `main`: `agents/core/learning/background_review.py` fires a strict-local, structured-JSON review after every completed turn (`_complete_llm_turn`), distilling durable facts into a bounded, injection-scanned `CoreMemory` core + `user_core` ring (frozen-snapshot per session for LM Studio prefix-cache stability), routing corrections into `LearningModule` (H21.4's signals), routing new skills through the existing CDX-8 quarantine, and routing skill patches through a new hash-anchored `skills/proposals.py` ledger + `ActionApprovalQueue`; `skills/usage.py` + `skills/curator.py` add usage telemetry, provenance, and a nightly active→stale(30d)→archived(90d) lifecycle pass that applies owner-approved patches with a reversible backup. A pre-merge 3-lens adversarial review caught and fixed a critical strict-local violation (`HybridRouter.backend` prefers cloud when keys are configured; fixed via a fail-closed `LLMRouter.local_backend`) plus three lesser findings (documented in BACKLOG.md's H20 live-wave section). Default-OFF behind `cognition.enabled` + `cognition.review_enabled` (Product Posture O26-P2.4). Zero file overlap with #625–#631 (verified before merge); full offline suite green. |
| H20 live-wave — per-turn learning loop | ✅ merged to `main` | Background review distiller (`agents/core/learning/background_review.py`) fires after every completed turn, strict-local by construction (`LLMRouter.local_backend` — never the cloud-preferring `HybridRouter.backend`), distilling facts into a bounded/injection-scanned `CoreMemory` + `user_core` ring (frozen-snapshot per session), routing corrections into `LearningModule`, new skills through CDX-8 quarantine, and skill patches through a new hash-anchored `skills/proposals.py` ledger + `ActionApprovalQueue`. `skills/usage.py` + `skills/curator.py` add usage telemetry, provenance, and a nightly active→stale(30d)→archived(90d) lifecycle pass. Default-OFF (`cognition.enabled` + `cognition.review_enabled`, Product Posture O26-P2.4). Full detail + adversarial-review findings: BACKLOG.md's H20 live-wave section. |
| H20 live-wave local verification | ✅ targeted green | +79 new offline tests across 7 new suites (`test_iteration_budget.py`, `test_subagents_scoping.py`, `test_core_block_injection.py`, `test_background_review.py`, `test_skill_lifecycle_curator.py`, `test_review_strict_local.py`, `test_review_findings_regressions.py`) plus Codex's migration-plan-primitive suites (`test_channel_sessions.py`, `test_environment_primitives.py`, `test_environment_file_rpc.py`, `test_environment_output_limits.py`, `test_sandbox_child_env.py`, `test_llm_provider_profiles.py`). Full offline suite (~3,806) green on the rebased branch before merge, modulo 4 known-environmental flakes unrelated to this work and unchanged by it: `test_sys_info_honest.py` and `test_h10_11_hierarchical.py` (pre-existing, reproduce on clean main), plus `test_input_validation.py::test_chat_message_valid_returns_non_422` and `test_h10_20_chat_rooms.py::test_room_endpoints` (intermittent live-LM-Studio/Windows-file-lock timing, confirmed passing in isolation via a throwaway `git worktree` on clean `origin/main`, files untouched by any recent commit). A pre-merge 3-lens adversarial review (separate from this test pass) is detailed in BACKLOG.md. |

---

## ORIZONT 25 Update — 2026-07-03

Integrated Codex development batch for the M1/M2 substrate and truth gates:

| Item | Status | Verified result |
|------|--------|-----------------|
| M1.1 K3 budget unification | ✅ done | Shared `BudgetLedger` now reports named dimensions; interrupt, mission, payment, and handler token usage feed the kernel view. |
| M1.2 `Action.origin` threading | ✅ done | `Gateway.route` classifies trusted web/voice vs inbound channels; brokers carry the current origin so inbound actions escalate through the kernel. |
| M2.1 chat/voice flow E2E | ✅ done | Playwright covers chat send→SSE→stop plus mocked voice push-to-talk into a chat turn. |
| M2.3 OpenAPI→TS typegen | ✅ done | Generated `frontend/src/api/schema.gen.ts`; CI regenerates from live `/openapi.json` and fails on diff. |
| M2.4 scheduled eval gate | 🟡 partial | Deterministic `companion_eval --ci-gate`, the schedule, and cache-backed persistent eval storage are wired, so baseline compare bites after the first successful scheduled/manual run. #552 fixed the eval-nightly workflow parser so the cache-backed job now creates real GitHub runs again. Live-model mode still needs a persistent/live runner. |

The 2026-07-03 local batch that bundled M1.3/M1.4/M1.5/M2.2/M2.4/M2.6 is recorded in `BACKLOG.md` as a protocol exception, not a precedent. Future ORIZONT 25 work returns to one item = one PR.

---

## ✅ Agents — 17 active (15 classic cabinet + Howard emerging + Argus WorldView bridge)

| Agent | Role | Tier | SOUL.md | HEARTBEAT.md |
|-------|------|------|---------|-------------|
| Jarvis | Prime Orchestrator | command | ✅ | ✅ morning |
| Friday | Daily Intel | command | ✅ | ✅ morning |
| Pepper | Chief of Staff | command | ✅ | ✅ morning + weekly |
| Jerome | Leisure & DJ | command | ✅ | ❌ reactive |
| Athena | External Strategy | business | ✅ | ✅ weekly |
| Stark | Corporate Intel | business | ✅ | ✅ morning |
| Veronica | The Voice | business | ✅ | ❌ reactive |
| Vision | Deep Research | business | ✅ | ✅ weekly |
| Steve | CTO & Builds | tech | ✅ | ✅ 5-min health |
| Oracle | n8n Workflows | tech | ✅ | ❌ reactive |
| Ultron | Security | tech | ✅ | ✅ hourly |
| Gecko | Finance | foundation | ✅ | ✅ daily |
| Hercules | Fitness | foundation | ✅ | ✅ daily |
| Hephaestus | Builder | foundation | ✅ | ✅ daily |
| Frigga | Family | foundation | ✅ | ✅ daily |
| Argus | Geoint (WorldView bridge, read-only) | business | ✅ | ❌ reactive |
| Howard | Digital Twin (emerging, local-only) | foundation | ✅ | ❌ reactive |

---

## ✅ Core Features (since v0.2.0)

| Feature | Module | Status |
|---------|--------|--------|
| Config loader | `core/config.py` | ✅ |
| Agent runtime | `core/agent.py` | ✅ |
| Orchestrator (full rewrite) | `core/orchestrator.py` | ✅ |
| Intent router | `core/router.py` | ✅ |
| Heartbeat scheduler | `core/heartbeat.py` | ✅ |
| Permission Gate | `core/plugin_gate.py` | ✅ |
| LLM backends (Ollama + LM Studio) | `core/llm/` | ✅ |
| Memory (conversation + vector + persistence) | `core/memory/` | ✅ |
| Voice pipeline | `core/voice/` | ✅ |
| MCP client | `core/mcp/client.py` | ✅ |

### New in v0.2.0

| Feature | Module | Status |
|---------|--------|--------|
| Skills System (discover, execute, generate, parse) | `core/skills/loader.py` | ✅ |
| Checkpointing (SQLite, WAL mode) | `core/checkpoint.py` | ✅ |
| Structured Session Storage | `core/checkpoint.py` (sessions table) | ✅ |
| Unified Gateway (rate limit, health) | `core/channels/gateway.py` | ✅ |
| Agent-to-Agent Handoff (`[handoff:agent_id]`) | `core/orchestrator.py` | ✅ |
| Promotion/Demotion Engine (5-failure threshold) | `core/agent.py` | ✅ |
| Parallel Agent Calls (per-model timeout) | `core/orchestrator.py` | ✅ |
| Graceful LLM Unavailability | `core/orchestrator.py` + `core/agent.py` | ✅ |
| Learning Loop (DSPy-style optimization) | `core/learning/loop.py` | ✅ |

### Ported from OpenJarvis v0.2.1

| Feature | Module | Status |
|---------|--------|--------|
| Security Guardrails (PII/secret scanner, SSRF, audit) | `core/security/` | ✅ |
| Skills Import (Hermes/OpenClaw/GitHub/agentskills.io) | `core/skills/importer.py` | ✅ |
| Sandboxed Code Execution (Docker + subprocess) | `core/sandbox.py` | ✅ |
| Discord Channel Adapter | `core/channels/discord.py` | ✅ |
| Email Channel Adapter (SMTP + IMAP) | `core/channels/email.py` | ✅ |
| Slack Channel Adapter | `core/channels/slack.py` | ✅ |
| Benchmark System (latency/throughput/success) | `core/bench.py` | ✅ |

### Channel Adapters

| Channel | File | Status |
|---------|------|--------|
| Base adapter | `core/channels/base.py` | ✅ |
| Telegram (long-poll) | `core/channels/telegram.py` | ✅ |
| Voice (wake → STT → TTS) | `core/channels/voice.py` | ✅ |
| Web (SSE, multi-client) | `core/channels/web.py` | ✅ |
| Discord | `core/channels/discord.py` | ✅ |
| Email (SMTP + IMAP) | `core/channels/email.py` | ✅ |
| Slack | `core/channels/slack.py` | ✅ |

### Plugin Implementations

| Plugin | File | Status |
|--------|------|--------|
| Weather (wttr.in) | `core/plugins/weather.py` | ✅ |
| News (BBC RSS) | `core/plugins/news.py` | ✅ |
| Cloud LLM (Anthropic/OpenAI) | `core/plugins/cloud_llm.py` | ✅ |
| Telegram bot | `core/plugins/telegram_bot.py` | ✅ |
| Gmail API | `core/plugins/gmail_plugin.py` | ✅ |
| WhatsApp local bridge | `core/plugins/whatsapp_bridge.py` | ✅ |
| Spotify control | `core/plugins/spotify_plugin.py` | ✅ |

---

## ✅ Web Endpoints (17) — All Smoke Tested PASS *(historical v0.2 snapshot — the current surface is ~299 routes; full index in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))*

| Endpoint | Route | Status |
|----------|-------|--------|
| Index | `GET /` | ✅ HTML served |
| Chat | `POST /chat` | ✅ (graceful LLM-down fallback) |
| Chat Stream | `POST /chat/stream` | ✅ |
| Status | `GET /status` | ✅ (includes learning, bench, security) |
| Agents | `GET /agents` | ✅ |
| Skills | `GET /skills` | ✅ |
| Skills Import | `POST /skills/import` | ✅ (hermes/openclaw/github) |
| Skills Imported | `GET /skills/imported` | ✅ (list imported) |
| Sessions | `GET /sessions` | ✅ |
| Memory | `GET /memory` | ✅ |
| Memory Clear | `POST /memory/clear` | ✅ |
| Learning | `GET /learning` | ✅ (stats + optimizations) |
| Security | `GET /security` | ✅ (guardrails, scanners, audit) |
| Bench | `GET /bench` | ✅ (latency, throughput, success rate) |
| Sandbox Status | `GET /sandbox/status` | ✅ (docker availability) |
| Sandbox Execute | `POST /sandbox/execute` | ✅ (Python + shell) |
| Dashboard | `GET /dashboard` | ✅ (cached plugin data + learning) |

---

## ✅ QA — Phases 1-3

| Phase | Scope | Result |
|-------|-------|--------|
| Phase 1 | 41/41 Python files compile, 21/21 module imports, 5/5 instantiation | ✅ PASS |
| Phase 2 | 8/8 integration suites (checkpoint, skill, gateway, memory, config, orchestator, agent, filesystem) | ✅ PASS |
| Phase 3b | 7/7 edge case suites (conversation memory, vector store, persistence, plugin gate, heartbeat, serialization, config) | ✅ PASS |
| Web smoke | Server starts, 8/8 endpoints respond (no LLM backend) | ✅ PASS |

---

## 🐛 Bugs Found & Fixed (3)

| Bug | File | Fix |
|-----|------|-----|
| `core/plugins.py` shadowed by `core/plugins/` package | `core/plugins.py` | Renamed to `plugin_gate.py`, re-exported via `__init__.py` |
| `ConversationMemory.get_history(last_n=0)` returned all turns | `core/memory/conversation.py` | Changed `if last_n:` to `if last_n is not None:` |
| `HeartbeatScheduler.load_all()` crashed on missing directory | `core/heartbeat.py` | Added `exists()` guard |

---

## 🟡 Known Gaps

| Gap | vs | Impact |
|-----|----|--------|
| ✅ Security Guardrails (v0.2.1) | OpenJarvis | Pure-Python PII/secret scanner, SSRF, audit |
| ✅ Sandbox (v0.2.1) | OpenJarvis (Docker + WASM) | Docker + subprocess execution |
| ✅ Skills Import (v0.2.1) | OpenJarvis (agentskills.io) | Hermes/OpenClaw/GitHub import |
| ✅ Multi-Channel (v0.2.1) | OpenJarvis (18+) | Now 6 channels (web, voice, telegram, discord, email, slack) |
| ✅ Bench System (v0.2.1) | OpenJarvis | Latency/throughput/success tracking |
| ❌ Desktop App | OpenJarvis (Tauri) | No native desktop UI |
| ❌ Rust Extension | OpenJarvis (14 crates) | No Rust — pure Python only |
| ❌ SFT/GRPO Training | OpenJarvis | No model fine-tuning (needs GPU) |
| ❌ WASM Sandbox | OpenJarvis (wasmtime) | Docker-only sandbox |

> **Real-category parity (2026-06-02 — vs personal/proactive/private AI competitors, not just the OpenJarvis ancestor; full analysis: `docs/research/2026-06-02-personal-ai-competitors.md`):**

| Gap | vs | Impact |
|-----|----|--------|
| ⚠️ Direct rival — governance wedge | **OpenClaw** | Same thesis (self-hosted, proactive, local-capable); we are the *governed/secure* alternative (H12.1) |
| ❌ Multi-surface passive capture | **Pieces.app** | Only text conversations ingested; no opt-in browser/clipboard/files → KG (H12.7) |
| ❌ Frictionless folder → doc-chat onboarding | **GPT4All / Khoj** | Config-heavy first run (H12.2) |
| ❌ Polished local-model management UX | **Jan.ai** | No one-click model browse/download/switch (H12.9) |
| ❌ Local voice hardware + Wyoming interop | **Home Assistant** | No satellite-mic / Wyoming support (H12.4, H12.8) |

---

## Decisions — resolved 2026-05-11

1. Wake words: **both** `jarvis` + `hub` ✅
2. Addressing: **"sir"** ✅
3. Frigga WhatsApp: **local bridge + manual entry fallback** ✅
4. Cloud LLM: **local by default, on-demand cloud for approved agents** ✅
   - Approved for cloud fallback: Jarvis, Athena, Stark, Vision, Veronica
