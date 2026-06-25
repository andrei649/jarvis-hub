# Roadmap-vs-Codebase RE-AUDIT — Competitive-Gap themes 0.19–0.66, re-verified at HEAD

> Date: 2026-06-25 · Method: 3 parallel, read-only, **code-grounded** passes (one per theme cluster)
> re-verifying every Competitive-Gap theme against **HEAD** (`943fdf5`) — each pass checked both the
> status marker *and* whether every cited `file:line` actually exists. Owner: Andrei.
> **Supersedes** [`2026-06-21-roadmap-vs-codebase-audit.md`](2026-06-21-roadmap-vs-codebase-audit.md)
> (and its 2026-06-22 inline update), which is now the historical baseline.
>
> Folded into [`BACKLOG.md` → "Competitive-Gap Roadmap"](../../BACKLOG.md#-competitive-gap-roadmap-product-depth).
> Status keys: ✅ done · 🟢 in open PR · 🟡 partial · 🌱 seed (module exists, feature mostly unbuilt) · ⬜ missing.

## Why this re-audit

The 2026-06-25 getjarvis competitive-gap pass
([`2026-06-25-getjarvis-competitive-gap.md`](2026-06-25-getjarvis-competitive-gap.md)) folded themes
0.64–0.66 into the backlog but carried at least one citation that was asserted from a competitor scrape
rather than read from the tree (`frontend/src/app.tsx:714` — a line that does not exist; the file is
488 lines). This re-audit re-grounds **all 48 statuses** against current code to find every error of
that class and any status drift since the 2026-06-21 baseline.

## Delta vs the 2026-06-21 baseline

**45 of 48 statuses CONFIRMED unchanged.** The only corrections the code justifies:

| Theme | Change | Verified evidence at HEAD |
|-------|--------|---------------------------|
| **0.64** Floating Bar + Global Hotkey | **REF-FIX** (status `⬜` unchanged) | cited `frontend/src/app.tsx:714` **does not exist** (file is 488 lines). Real hotkey handler is `frontend/src/app.tsx:126–140` (`window.addEventListener('keydown', onKey)`) — fires only on browser-tab focus, not system-wide. `desktop/src-tauri/src/main.rs:9–22` setup stub (no `GlobalShortcutManager`) — confirmed. |
| **0.61** Database Future Check | `🌱 seed` → **`🟡 partial`** | schema-migration framework shipped (#305) → `agents/core/persistence/migrations.py`. Bounded gap is now only the Turso/libSQL eval (no such imports/code present). |
| **0.52** Product Demo Factory | `⬜ missing` → **`🌱 seed`** | `docs/marketing/TEASER_PACK.md` storyboard (lines 58–74) + shot-list (124–136) are complete; what is absent is the HUD-footage capture + assembly tooling (no ffmpeg/assembly code). Not greenfield. |
| **0.20** Jarvis Vault | **clarified, status `⬜` held** | `agents/core/secrets_vault.py` is a resolver skeleton; backup/at-rest-encryption/export shipped under their *own* H-items (#302 / AUD-1 / #303), but the vault *surface* (1 TB managed store + retention controls) is unstarted — so `⬜` is correct. (The 2026-06-21 cell's ✅-laden parenthetical made `⬜` *read* as self-contradictory; the BACKLOG cell is reworded to remove that.) |

**Explicitly re-confirmed (a prior suspicion that turned out wrong):** `0.36` Agent-Native Action
Manifest stays `✅ built · 🟡 unseamed`. The ORIZONT-24 K1 kernel (`agents/core/kernel/`, #328) mediates
privileged *actions* (brokers: `node.dispatch`, `call.outbound`, `social.*`, `writeback.*`); it does
**not** unify the MCP `route_tools` allow-list (`agents/core/mcp/route_tools.py:72`) with
`route_auth.json` (`tests/_snapshots/route_auth.json`). Those remain two separate registries — the
unseam is still open work.

## Full verified table (all themes at HEAD)

| Theme | Status | Verdict | Evidence (`file:line`) |
|-------|--------|---------|------------------------|
| 0.19 First-Run Command Center | 🟡 partial | confirm | `routers/onboarding.py:27`, `routers/status.py:34` + demo mode — unified install-health+model+first-action screen unbuilt |
| 0.20 Jarvis Vault | ⬜ missing | clarified | `secrets_vault.py` resolver skeleton — vault surface (1 TB + retention) unstarted; backup/encryption/export are adjacent H-items |
| 0.21 Offline Knowledge Packs | 🌱 seed | confirm | `local_docs.py:73` (LocalDocsIndexer) — no Kiwix-style installer |
| 0.22 Appliance Install/Update | 🟡 partial | confirm | `install.sh:1`, `start.sh` — uninstall + signed artifacts + no-telemetry proof missing |
| 0.23 Hardware Benchmark & Profiles | 🟡 partial | confirm | `bench.py:20`, `llm/model_manager.py:176` (VRAM) — RTX scoring + mode profiles missing |
| 0.24 Voice Hotkey & Dictation | 🟡 partial | confirm | `voice/wake_word.py:26`, `voice/pipeline.py:1` — hold-to-talk hotkey + filler removal missing |
| 0.25 Desktop Control Pack | 🌱 seed | confirm | `desktop_operator.py:37` (NullDesktopDriver), `screen_grounding.py:20`, `browser_agent.py` — OS control unwired |
| 0.26 Capture Inbox | 🟡 partial | confirm | `routers/capture.py:1`, `passive_capture.py:36` — phone export + transcript sync missing |
| 0.27 Local VLM Eyes | ✅ done | confirm | `llm/vlm.py:62` + `/api/vlm/describe` |
| 0.28 Voice Persona Studio | 🟡 partial | confirm | `cognition/persona.py:32`, `voice/tts.py:30`, `frontend/src/api/ttsStream.ts` — barge-in→HUD (BUG-2b.3) missing |
| 0.29 Native Launcher | 🟡 partial | confirm | `desktop/src-tauri/tauri.conf.json:1`, `src/main.rs:1` (setup stub) — PWA + signed installers missing |
| 0.30 Context Compression | ✅ done | confirm | `context_compressor.py:18` wired in `routers/tools.py:36` |
| 0.31 Code Intelligence MCP | 🌱 seed | confirm | `mcp/client.py:14`, `mcp/server.py:48` — code-indexing backend unwired |
| 0.32 Mission Workspaces | ✅ done | confirm | `autonomy/missions.py:49` + `routers/missions.py` (#301) |
| 0.33 Subagent Gateway | ✅ done | confirm | `subagents.py:28`, `a2a.py:67`, `autonomy_coordinator.py:30` |
| 0.34 Workflow Runtime Upgrade | 🟡 partial | confirm | `workflows/engine.py:24` (cap 8 / timeout 120s / depth 5) — persistent queue + pruning missing |
| 0.35 Prompt Registry | ✅ done | confirm | `soul_versioning.py:45` (commit/diff/rollback + A/B) |
| 0.36 Agent-Native Action Manifest | ✅ built · 🟡 unseamed | confirm | `mcp/route_tools.py:72` + `web.py:1232`; `route_auth.json` is a *separate* registry — unseam open |
| 0.37 Memory Ingestion Lab | 🟡 partial | confirm | `ingestion/pipeline.py:36` (7-phase) + `data_spaces.py:26` — ontology / cross-agent / provenance partial |
| 0.38 Today In Jarvis | 🟡 partial | confirm | `autonomy/digest.py:28`, `memory/digest.py:11` — unified chronological timeline missing |
| 0.39 Market Intel Pack | 🌱 seed | confirm | `plugins/balance.py:59`, `plugins/signal_layer.py:30` — watchlists / alerts / disclaimers scaffolding |
| 0.40 OSINT Investigator Pack | 🌱 seed | confirm | `plugins/worldview.py:35`, `argus.py` — SpiderFoot / correlation / evidence drawer missing |
| 0.41 World Signal Packs | 🌱 seed | confirm | `plugins/signal_layer.py:30` — per-domain signal routing not built |
| 0.42 Security Skills Pack | ⬜ missing | confirm | `security/` is infra (13 files) — no ATT&CK/ATLAS/D3FEND/NIST skill taxonomy |
| 0.43 Learning Coach Pack | 🌱 seed | confirm | `learning/scheduler.py:21` (promotions, not tutoring) — curriculum / spaced review missing |
| 0.44 Safe Comms Pack | 🟡 partial | confirm | `channels/telegram.py:20`, `channels/email.py`, `plugins/whatsapp_bridge.py`, `autonomy/action_approvals.py` — draft-before-send UI + per-channel rate limits partial |
| 0.45 High-Risk Automation Contracts | 🟡 partial | confirm | `plugin_gate.py`, `signal_governance.py`, `routers/payments.py` — reusable contract-template not extracted |
| 0.46 Media Library | 🟡 partial | confirm | `media_gen.py:25`, `media_skill.py:22` — catalog / searchable timeline / export bundles missing |
| 0.47 Creative Asset Pipeline | 🌱 seed | confirm | `video_prompt.py:19`, `image_gen.py:23`, `media_gen.py:25` — coordinated pipeline + provenance unwired |
| 0.48 Video Production Pipelines | ⬜ missing | confirm | `video_prompt.py:1` is a prompt builder only — assembly / effects / localization absent |
| 0.49 Timeline Adapter | 🟡 partial | confirm | `canvas.py:56` + worldview `timelineMarkers.ts` — interactive approval-gated timeline incomplete |
| 0.50 Publishing Studio | 🌱 seed | confirm | `writeback.py:73` (Notion/GitHub/Calendar), `social.py:54` (X) — export/render packs missing |
| 0.51 Reference-Driven Creation | 🟡 partial | confirm | `plugins/websearch.py:1` (SSRF-safe) — reference→grounded-plan choreography incomplete |
| 0.52 Product Demo Factory | 🌱 seed | **CHANGE ⬜→🌱** | `docs/marketing/TEASER_PACK.md:58` storyboard + `:124` shot-list complete — HUD-capture + assembly tooling absent |
| 0.53 Design System Manifest | 🟡 partial | confirm | `frontend/src/styles.css:1` tokens + `docs/BRAND_BOOK.md` — inspectable component library (Storybook) unbuilt |
| 0.54 Skill Operating System | ✅ done | confirm | `skills/loader.py`, `skills/importer.py`, `skills/skill_drift.py` + SKILL.md manifests |
| 0.55 Design Partner Kit | ⬜ missing | confirm | feedback/NPS widget + issue bundle + SLA — none present |
| 0.56 Trust Center | ✅ done (#300) | confirm | `security/audit.py`, `routers/security.py` (kill_switch / audit_verify), `frontend/src/gap.tsx` kill-switch UI, `hybrid_router.py:LOCAL_ONLY_AGENTS` — cloud-hop log + consent open |
| 0.57 Release Packaging | ⬜ missing | confirm | no signed-artifact tooling / SBOM / NOTICE / compat-matrix generation |
| 0.58 Pack Manager | 🟡 partial | confirm | `skills/marketplace.py` registry — model/domain/content packs + remove/rollback unbuilt |
| 0.59 Proof Assets | 🌱 seed | confirm | `marketing/` + `docs/marketing/{ANNOUNCEMENT,DESIGN_BRIEF,TEASER_PACK}.md` — landing / demo / SEO / comparison pages unbuilt |
| 0.60 Local Analytics | ✅ done (#300) | confirm | `observability/north_star.py:1` + `/api/metrics/north-star` + HUD meter (`frontend/src/modes4.tsx`) — activation funnel open |
| 0.61 Database Future Check | 🟡 partial | **CHANGE 🌱→🟡** | `settings_db.py:26` (WAL) + `persistence/migrations.py:1` (framework ✅ #305) — Turso/libSQL eval not done |
| 0.62 System Profiles | ⬜ missing | confirm | VRAM mgmt only — Gaming/AI/Multimedia/Admin modes absent |
| 0.63 Restore & Soak | 🟡 partial | confirm | `backup.py:1` (backup/restore/drill ✅ #302) + `resilience.py` (retry + circuit-breaker) — 72h soak + failure injection missing |
| 0.64 Floating Bar + Global Hotkey | ⬜ missing | **REF-FIX** | `desktop/src-tauri/src/main.rs:9` setup stub (no `GlobalShortcutManager`) + `frontend/src/app.tsx:126` (browser-focus keydown) — system-wide summon bar absent |
| 0.65 One-Hotkey Screen-Capture Reflex | 🌱 seed | confirm | `llm/vlm.py` ✅ + `screen_grounding.py:1` + `desktop_operator.py` — exist but unwired to a hotkey trigger (depends on 0.64) |
| 0.66 SaaS Connector Breadth | 🟡 partial | confirm | ~20 integrations; white-collar suite (Linear/Asana/Trello/Todoist/ClickUp/Figma/Obsidian/Sheets/M365/Apple) all absent; Todoist is a referenced target only (`autonomy/transcript_watcher.py:43`) |
| 0.90–1.0 gates | ⬜ pending | confirm | `AUDIT.md`, `MANUAL_TESTING.md`, parity/auth gates, north-star eval — promote eval→required gate; design partners; landing+demo |

## Bottom line

The earlier analysis's *substance* (the 0.64–0.66 gaps, the missing-connector list) held up — but it
carried a fabricated line citation and two stale statuses, exactly the kind of drift a code-grounded
re-audit exists to catch. With 0.52 and 0.61 corrected, the greenfield (⬜) count among the original
0.19–0.63 themes is **6**, not 7: 0.20 · 0.42 · 0.48 · 0.55 · 0.57 · 0.62.
