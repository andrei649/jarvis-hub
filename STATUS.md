# Jarvis Hub — Status Snapshot

> **Current version:** v0.11.0 (feature-complete + refactor done; productionizing toward 1.0) · **Tests:** ~3,645 passed (6 skipped) + frontend **172 vitest** + mobile **22 jest** + Playwright HUD/flow suites (HUD-v3 Console port complete: every blueprint surface + the north-star Decision Inbox + native Neural-Mesh canvas + cinema mode) · **Agents:** 17 active (16 cabinet incl. Howard + Argus, the WorldView bridge; + 17 bench) · **HTTP routes:** 367 (+ feedback widget/summary, H23.21; + onboarding, H23.20; +`/api/metrics/capabilities`, V2; + `/api/security/loop-breaker` status/reset, K3; + `/api/metrics/kernel`, Gate-K observability) — `web.py` decomposed into **45 per-domain routers** (CLN-3, #296); only 9 app-shell/chat/admin routes remain inline (4,636→1,282 LOC)
> **The version is the roadmap.** Every feature horizon (H1–H22 + WorldView O19) is delivered — that's **0.10.0**; the **0.11.0** refactor (CLN-3 `web.py` split + CLN-2 `orchestrator.py` managers) is done (#293/#296). There is no "audit gate" version: 1.0 is a real destination reached by finishing the productionization layer (**H23**: agentic-safety budgets, DB migrations, backup/restore + export-delete, operability, quality + user docs) **and** proving it with real design-partner users. The plan is the version line in [BACKLOG.md](BACKLOG.md#version-roadmap); strategy in [MOONSHOT.md](MOONSHOT.md) §4. Manual testing/audit ([docs/MANUAL_TESTING.md](docs/MANUAL_TESTING.md), [docs/AUDIT.md](docs/AUDIT.md)) is the release step that tags a version. GPU-gated dev (H12.14, H13.3, Howard) is its own minor (0.18). HUD deep write-controls tracked in [docs/design/HUD_V2_REMAINING.md](docs/design/HUD_V2_REMAINING.md).
>
> The version labels in the feature tables below (`v0.2.0`, `v0.2.1`) record *when* each capability first
> landed (provenance), not the current release. For live priorities and the version roadmap, BACKLOG.md is the source of truth.
>
> **Year-one review (candid, owner-facing):** [docs/REVIEW_YEAR_ONE.md](docs/REVIEW_YEAR_ONE.md) — status, the 12 learnings, the gap between *code-complete* and *desirable product*, and the next-90-days plan.

---

## ORIZONT 26 Update — 2026-07-04

O26 Phase 0, P1.1, P2.1, P2.2, P2.3, P2.4, and P2.5 are complete on `main`.
O26-P3.1 preview modes is merged in #505; O26-P3.3 eval-baseline persistence is delivered in #506.
O26-P3.2 HUD punch-list reconciliation is merged in #507.
O26-P3.4 mobile approval queue is delivered in #509.
O26-P3.5 persona rail + caring follow-ups is delivered in #510.
O26-P3.6 landing page dev half is delivered in #512.
O26-P3.2 HUD depth tail delivered Data Spaces assign/unassign controls in #515; #517 adds the Rooms selected-history drawer; #519 adds capability issue/check UI; #521 adds current-mesh task fan; #523 adds preferences/tweaks UI; #525 adds self-hosted HUD fonts. The 0.44 Safe Comms draft-before-send UI is merged in #527 as a governed social-draft surface. #551 adds channel inbox transport v0 for telegram/web; owner live-data setup and non-v0 inbox channels remain partial.
0.45 High-Risk Automation Contracts now has ten merged live adoptions: #529 moves `PaymentBroker` request/approval admissibility onto `PAYMENT_CONTRACT`, #531 moves actionable Signal Layer recommendation queueing onto `SIGNAL_RECOMMENDATION_CONTRACT`, #533 moves plugin-known/enabled/agent/network checks onto `PLUGIN_CALL_CONTRACT`, #535 moves governed social draft-before-send requests onto `SOCIAL_DRAFT_CONTRACT`, #537 moves governed Notion/GitHub/Calendar write-back drafts onto `WRITEBACK_DRAFT_CONTRACT`, #539 moves outbound call requests onto `CALL_REQUEST_CONTRACT` before preview/enqueue, #541 moves gated Tool-RPC calls onto `TOOL_RPC_CALL_CONTRACT` before kernel mediation and approval enqueue, #543 moves governed NodeMesh dispatch onto `NODE_DISPATCH_CONTRACT` before preview/enqueue, #545 moves cloud media generation onto `MEDIA_GENERATION_CONTRACT` before approval enqueue, and #547 moves mutating desktop operator steps onto `DESKTOP_STEP_CONTRACT` before approver/driver execution.
H17.1a inbound-origin construction is merged in #549: direct public turn entrypoints now bind origin, internal orchestrator channels stay trusted, inbound parent contexts are monotone, and plugin-egress actions no longer hard-code `origin="generated"`.
0.45 Batch B1 is merged in #550: `contract_denial()` centralizes denial reason fallback, skill marketplace publish/install/uninstall use `SKILL_INSTALL_CONTRACT`, LLM-authored skill creation/approval uses `SKILL_GENERATION_CONTRACT`, and remediation/LM Studio subprocess controls share `HOST_CONTROL_CONTRACT`.

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
| Safe Comms channel inbox transport v0 | ✅ delivered (#551) | `ChannelInboxStore` persists bounded telegram/web inbound threads after sender pairing allows them; `Gateway.route` records live inbox messages; `ChannelReplyBroker` gates replies through `CHANNEL_REPLY_CONTRACT`, queues `channel.reply` tasks into the existing approval funnel, and approved tasks send through `ChannelManager.send` while recording the outbound message. HUD Comms reads `/api/channels/inbox` and enables the governed reply form only for live inbox rows; seeded preview rows stay disabled. Local verification: Safe Comms backend (+8), route/OpenAPI/type gates, adjacent backend sweep, frontend typecheck, full Vitest (172), HUD build, and full PR CI green. Mobile parity is tracked as H18.12. |
| Local verification | ✅ targeted green | P2.2 focused sweep was 33 passed before #501 merge; P2.3 red/green tests (+4) plus ensemble, governed learning, persona, and memory-store suites are 48 passed before #502 merge. P2.4 focused posture/onboarding/security/support/lifespan/settings sweep was 39 passed locally; PR #503 full CI matrix green before merge. P2.5 smoke tests were green, `python scripts/install_smoke.py --json` exited 0 locally, and PR #504 full CI matrix was green before merge. P3.1 focused checks and full PR CI were green. P3.3 companion eval suites are green (19 passed), CLI store-root gate exits 0, and ruff/py_compile are clean. P3.2 red doc-guard is green locally and #507 full GitHub Actions passed before merge. P3.4 mobile Jest suite is green (22 passed) and mobile typecheck is clean. P3.5 local suite was green (6 passed), adjacent quality/digest/timeline/autonomy endpoint suites were green (41 + 37 passed), touched-file ruff/py_compile were clean, and #510 full GitHub Actions passed before merge. P3.6 landing contract was green locally (4 passed), visual local-file smoke passed at desktop/mobile viewports, and #512 full GitHub Actions passed before merge. P3.2 Data Spaces depth: focused HUD tests green (8 passed), full frontend Vitest green (164 passed), typecheck/status-sync/diff-check clean, and #515 full GitHub Actions passed before merge. P3.2 Rooms history drawer: focused HUD panel test green (5 passed), full frontend Vitest green (165 passed), typecheck/build/status-sync/diff-check clean, and #517 full GitHub Actions passed before merge. P3.2 Capability issue/check UI: focused HUD panel test green (6 passed), focused HUD sweep green (10 passed), full frontend Vitest green (166 passed), typecheck/build/status-sync/diff-check clean, and #519 full GitHub Actions passed before merge. P3.2 mesh task fan: red-proved `NeuralMesh` did not surface `/tasks`; focused mesh test green (4 passed), adjacent mesh/cinema sweep green (8 passed), full frontend Vitest green (167 passed), typecheck/build/status-sync/diff-check clean, and #521 full GitHub Actions passed before merge. P3.2 preferences/tweaks UI: red-proved the command palette had no Look/Motion/Comfy controls; focused palette test green (1 passed), full frontend Vitest green (168 passed), typecheck/build/status-sync/diff-check clean, and #523 full GitHub Actions passed before merge. P3.2 self-hosted fonts: red-proved missing local WOFF2 assets and CSS declarations; focused font guard green (2 passed), full frontend Vitest green (170 passed), typecheck/build clean, and #525 full GitHub Actions passed before merge. Safe Comms draft UI: red-proved no panel existed, then focused Vitest green (1 passed) for catalog load + queued reply payload; full frontend Vitest green (171 passed), typecheck/build/status-sync/diff-check clean, and #527 full GitHub Actions passed before merge. 0.45 payment contract live gate: red-proved the request/approve paths ignored a patched contract, then targeted payment/contract/kernel/auth sweep green (76 passed), ruff/py_compile clean, and #529 full GitHub Actions passed before merge. 0.45 signal governance contract gate: red-proved the bridge had no live contract, then signal/contract/payment parity sweep green (48 passed), ruff/py_compile clean, and #531 full GitHub Actions passed before merge. 0.45 plugin permission contract gate: red-proved `PermissionGate` had no live plugin-call contract, then plugin/startup/integration/contract sweep green (186 passed), ruff/py_compile clean, and #533 full GitHub Actions passed before merge. |

---

## ORIZONT 25 Update — 2026-07-03

Integrated Codex development batch for the M1/M2 substrate and truth gates:

| Item | Status | Verified result |
|------|--------|-----------------|
| M1.1 K3 budget unification | ✅ done | Shared `BudgetLedger` now reports named dimensions; interrupt, mission, payment, and handler token usage feed the kernel view. |
| M1.2 `Action.origin` threading | ✅ done | `Gateway.route` classifies trusted web/voice vs inbound channels; brokers carry the current origin so inbound actions escalate through the kernel. |
| M2.1 chat/voice flow E2E | ✅ done | Playwright covers chat send→SSE→stop plus mocked voice push-to-talk into a chat turn. |
| M2.3 OpenAPI→TS typegen | ✅ done | Generated `frontend/src/api/schema.gen.ts`; CI regenerates from live `/openapi.json` and fails on diff. |
| M2.4 scheduled eval gate | 🟡 partial | Deterministic `companion_eval --ci-gate`, the schedule, and cache-backed persistent eval storage are wired, so baseline compare bites after the first successful scheduled/manual run. Live-model mode still needs a persistent/live runner. |

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
