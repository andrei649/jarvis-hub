# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

> **North Star (vision, principles, phase gates):** [MOONSHOT.md](MOONSHOT.md) — re-rank this backlog against it
> **Go-Live Plan (features, roadmap, marketing brief):** [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md)
> **Delivery History (H1–H8 completed sprints):** [docs/HISTORY.md](docs/HISTORY.md)

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # ~2,802 passed, 6 skipped
```

> Singurul skip rămas e heartbeat-ul opțional. (Vechiul `tests/test_spotify.py` cu 8 skip-uri a
> fost eliminat în CLN-1; Spotify (H2.5) **funcționează** via `skills/spotify/main.py`, acoperit
> de `tests/test_spotify_skill.py`.)

**După modificări JS/CSS:** Ctrl+F5 în browser (cache bust).
**După modificări Python:** repornire server (Ctrl+C, re-execută comanda uvicorn).
**Server curent** (dacă e pornit): PID vezi `netstat -ano | findstr ":8080 "`.
**Stack:** Python 3.12 + FastAPI + vanilla React (createElement, no JSX).

---

## Version Roadmap

| Version | Target | Milestone | Items |
|---------|--------|-----------|-------|
| **0.5-beta** | 🟢 Live | Foundation complete. All H1–H4, cross-cutting, security, bugs done. | H1–H4, Sprint 0, Cross-cutting, Sec, Bugs |
| **0.6-beta** | 🟢 Live | Howard fine-tuning + voice clone + continuous ingestion | H5.1 |
| **0.7-beta** | 🟢 Live | Mobile PWA + i18n + UI Overhaul | H5.2, H5.3, H5.4 |
| **0.8-beta** | 🟢 Live | Performance & robustness + multi-agent workflows | H5.5, H5.6 |
| **0.9-beta** | 🟢 Live | New integrations + agent marketplace | H5.7, H5.8 |
| **0.9.1-beta** | 🟢 Live | Recall cu embeddings reale + perf cale fierbinte | H7.1–H7.5 (perf) |
| **0.9.2-beta** | 🟢 Live | Hardening complet, CI/CD, memorie personală, cost analytics, onboarding | H7 (11 iteme) + H8 (7 iteme) + BUG-1 |

> The `0.5-beta…0.9.2-beta` rows above are **provenance** (when each capability first landed).
> The line below is the **forward plan** — there is no separate "audit gate" version; the version
> number *is* the roadmap. **1.0 is a real destination**, not the current near-done state: it ships
> only when all planned development is finished **and** the system is proven with real
> design-partner users. Manual testing/audit is the *release step that tags a version*, not a
> roadmap item; owner-only items (license, naming, GitHub settings) live in [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md).

### Forward roadmap — the version is the plan (theme-per-minor)

`⚠️` = surfaced by the 2026-06-21 productionization research (was not previously tracked); now in **H23** below.

| Version | Theme | Scope highlights |
|---------|-------|------------------|
| **0.10.0** | Baseline | Everything delivered to date: H1–H21 + ORIZONT 22 + WorldView O19 + CLN-3 batch 2; north-star instrumented; **single-user** |
| **0.11.0** | 🟢 **Finish the refactor (done, #296)** | CLN-3 **complete** — `web.py` 4,636→1,282 LOC, 233→9 inline routes across 45 per-domain routers (304-route surface byte-identical, parity-guarded). CLN-2 substantially done — `PluginManager`+`llm_control`+`cognition_trace` extracted; orchestrator 1,620→1,456 LOC (remaining inline = the BUG-5 request pipeline, not safely extractable). |
| **0.12.0** | **Harden what shipped (here now)** | ORIZONT-22 review fixes (#294, merged); #292 argus governed-facade wiring; #279 MCP route-tools harden/remove; TASK-3 cross-channel taint-tracking |
| **0.13.0 ⚠️** | Agentic safety completeness | step/recursion + token/time **budgets + loop detection**; **model-version pinning & reproducibility**; **kill-switch in the HUD** + credential quarantine; eval/regression harness as a **release gate**; audit-log verify UI + secret redaction |
| **0.14.0 ⚠️** | Upgrade & data durability | **backup/restore** + restore drill ✅ (#302); **data export** ✅ (#303, CLI); **DB schema-migration framework** ✅ (#305, H23.7); **delete/forget** 🟡 (#306, `/api/admin/forget` — *purge incomplete + backup leaks PII, audit 2026-06-23 → AUD-2*); retention defaults ✅ (#317, H23.10); export HTTP surface ✅ (#315, H23.9) |
| **0.15.0 ✅** | Operability & distribution | health/readiness endpoint ✅ (H23.11, `/healthz`+`/readyz`) + signal handlers/graceful shutdown ✅ + log rotation ✅ (H23.11); graceful **local-LLM-down** everywhere ✅ (H23.12, split-timeout + clean degraded reply); systemd/service templates ✅ (H23.15, `deploy/`); **release artifacts** ✅ (H23.13 — tag→source bundle + SBOM + checksums + optional GPG sign, `docs/RELEASE.md`); **semver compatibility contract** ✅ + supported-versions matrix ✅ + deprecation policy ✅ + platform matrix ✅ (H23.14, `docs/COMPATIBILITY.md`) |
| **0.16.0** | HUD depth + observability UI | TASK-2 ~37 surfaces incl. **north-star panel** + **network monitor** ✅ (watch LOCAL_ONLY make zero calls — egress data layer + `GET /api/admin/network/calls` + Console panel, H23.16); LIVE/SEED indicators; OpenAPI types; plugin-gated modes |
| **0.17.0** | Local ceiling + velocity | H22.4 concurrency, H22.5 model-manager LRU, H22.9 agent-native routes, constrained-decoding tail |
| **0.18.0 🖥️** | Digital twin & fine-tune (**GPU-gated**) | H12.14 fine-tuned model, H13.3 speculative decoding, TASK-1 Howard first real run |
| **0.19.0 ⚠️** | Reach, quality & user docs | mobile parity tail (H18); **quality gates** (E2E, load/soak, a11y, i18n, browser+mobile matrix); **user docs ✅** (USER_GUIDE/FAQ/UPGRADE — H23.18; trust docs THREAT_MODEL/PRIVACY/SECURITY/NOTICE/SBOM — H23.19); **onboarding wizard** + activation funnel + cold-start error guidance |
| **0.20.0 ⚠️** | Product-proof | design-partner program (recruit 1–3) — *in-app **feedback/NPS** + program doc ✅ H23.21*; support channel + SLA; north-star **measured on real usage**; landing page + demo |
| **1.0.0** | 🎯 **Owned & proven** | all dev complete **+ design-partner validation**; owner legal/brand done; manual-test/audit pass → tag |

> **The program that organizes 0.11→1.0 is ORIZONT 24 — "AI-OS"** (decided 2026-06-23, section below): an
> **Action Kernel** (every agent action mediated, budgeted, revocable) + a **Verification Fabric** (each
> capability proven against reality before it may claim "done") + the four live capability packs, all on the
> H23 spine. Phase A of it = the AUD-\* hardening cluster.

---

## 🧭 Competitive-Gap Roadmap (product depth) — folded in from the uploaded plan

> The owner's 2026-06-21 **Competitive Gap Plan** (themes `0.19`–`0.63` + gates, derived from 24 OSS
> "Jarvis"/agent repos) is captured here so this file stays the **single source of truth**. These ~48
> themes are **product-depth slices, NOT a release sequence** — the version line above (the H23 spine)
> is the real path to 1.0; the numbers below are **theme-IDs**, and many are already DONE, so they
> can't be a monotonic version order. Each theme maps onto an existing version/H-item. Status is grounded
> in the code audit, re-verified against HEAD on 2026-06-25:
> [`docs/research/2026-06-25-roadmap-vs-codebase-reaudit.md`](docs/research/2026-06-25-roadmap-vs-codebase-reaudit.md)
> (supersedes the [2026-06-21 baseline](docs/research/2026-06-21-roadmap-vs-codebase-audit.md)).
> **Headline: ~85% already seeded; only 6 are truly greenfield.** Status keys: ✅ done · 🟢 in open PR ·
> 🟡 partial · 🌱 seed (module exists, feature mostly unbuilt) · ⬜ missing.

| Theme | Status | What exists / the bounded gap | Maps to |
|-------|--------|-------------------------------|---------|
| 0.19 First-Run Command Center | 🟡 partial | `routers/onboarding.py`+`status.py`+demo mode / unified install-health+model+first-action screen | H23.20 |
| 0.20 Jarvis Vault | ⬜ missing | `secrets_vault.py` is a resolver skeleton / the vault surface itself (1 TB store + retention controls) is unstarted — *adjacent* data-mgmt pieces shipped under their own H-items: backup ✅ #302, at-rest encryption ✅ AUD-1, export ✅ #303, forget 🟡 #306 (→ AUD-2) | H23.10 |
| 0.21 Offline Knowledge Packs | 🌱 seed | `local_docs.py` / Kiwix-style packs + installer | 0.21 |
| 0.22 Appliance Install/Update | 🟡 partial | `install.sh`,`start.sh`,`docker-compose.yml`, **release bundles + SBOM + checksums + optional sign** ✅ (H23.13) / uninstall, no-telemetry proof | H23.13/15 |
| 0.23 Hardware Benchmark & Profiles | 🟡 partial | `bench.py`,`llm/model_manager.py` (VRAM) / RTX scoring + mode profiles (GPU-gated) | 0.18 |
| 0.24 Voice Hotkey & Dictation | 🟡 partial | `voice/{wake_word,stt,pipeline}.py` / hold-to-talk hotkey, filler removal | — |
| 0.25 Desktop Control Pack | 🌱 seed | `desktop_operator.py`,`screen_grounding.py`,`browser_agent.py` / recording, app launch, OS control | — |
| 0.26 Capture Inbox | 🟡 partial | `passive_capture.py`+`routers/capture.py` / phone export, transcript sync, inbox view | — |
| 0.27 Local VLM Eyes | ✅ done | `llm/vlm.py` + `/api/vlm/describe` | — |
| 0.28 Voice Persona Studio | 🟡 partial | `cognition/persona.py`,`voice/tts.py`,`ttsStream.ts` / consent, barge-in→HUD (BUG-2b.3) | TASK-4 |
| 0.29 Native Launcher | 🟡 partial | `desktop/src-tauri/tauri.conf.json` (Tauri shell) / PWA, signed installers | 0.15 |
| 0.30 Context Compression | ✅ done | `context_compressor.py` wired in `routers/tools.py` | — |
| 0.31 Code Intelligence MCP | 🌱 seed | `mcp/{client,server}.py` / code-indexing backend | — |
| 0.32 Mission Workspaces | ✅ done | `autonomy/missions.py` + `routers/missions.py` (#301) | — |
| 0.33 Subagent Gateway | ✅ done | `subagents.py` + `a2a.py` + `autonomy_coordinator.py` | — |
| 0.34 Workflow Runtime Upgrade | 🟡 partial | `workflows/engine.py` (timeouts, bounded concurrency, recursion cap) / persistent queue, pruning | 0.17 |
| 0.35 Prompt Registry | ✅ done | `soul_versioning.py` (commit/diff/rollback + A/B) | — |
| 0.36 Agent-Native Action Manifest | ✅ built · 🟡 unseamed | `mcp/route_tools.py` + web wiring works / **unify the allow-list with `route_auth.json`** (#1 refactor) | 0.12 (#279) |
| 0.37 Memory Ingestion Lab | 🟡 partial | `ingestion/pipeline.py` (7-phase) + `data_spaces.py` / ontology, cross-agent sharing, provenance | — |
| 0.38 Today In Jarvis | 🟡 partial | `autonomy/digest.py` + `memory/digest.py` / unified chronological timeline | — |
| 0.39 Market Intel Pack | 🌱 seed | `plugins/{balance,analytics,signal_layer}.py` / watchlists, alerts, disclaimers | — |
| 0.40 OSINT Investigator Pack | 🌱 seed | `plugins/worldview.py` + `argus.py` / SpiderFoot modules, correlation, evidence drawer | — |
| 0.41 World Signal Packs | 🌱 seed | `signal_layer.py` (`world_brief`,`country_assessment`) / per-domain signal routing | — |
| 0.42 Security Skills Pack | ⬜ missing | `security/` is infra, not curated skills / ATT&CK/ATLAS/D3FEND/NIST taxonomy | — |
| 0.43 Learning Coach Pack | 🌱 seed | `learning/scheduler.py` (not tutoring) / curriculum, spaced review | — |
| 0.44 Safe Comms Pack | 🟡 partial | `channels/{telegram,email}.py`,`whatsapp_bridge.py`,`action_approvals.py` / draft-before-send UI, per-channel rate limits | — |
| 0.45 High-Risk Automation Contracts | 🟡 partial | `plugin_gate.py`,`signal_governance.py`,`routers/payments.py` / reusable contract-template abstraction | H23.1 |
| 0.46 Media Library | 🟡 partial | `media_gen.py`,`media_skill.py` / catalog, searchable timeline, export bundles | — |
| 0.47 Creative Asset Pipeline | 🌱 seed | `video_prompt.py`,`image_gen.py`,`media_gen.py` / coordinated pipeline + provenance | — |
| 0.48 Video Production Pipelines | ⬜ missing | `video_prompt.py` is a prompt builder only / assembly/effects/localization | — |
| 0.49 Timeline Adapter | 🟡 partial | `canvas.py` + worldview `timelineMarkers.ts` / interactive approval-gated timeline | — |
| 0.50 Publishing Studio | 🌱 seed | `writeback.py`,`social.py` / export/render packs (YouTube/IG/README) | — |
| 0.51 Reference-Driven Creation | 🟡 partial | `plugins/websearch.py` (SSRF-safe fetch) / reference→grounded-plan choreography | — |
| 0.52 Product Demo Factory | 🌱 seed | `docs/marketing/TEASER_PACK.md` storyboard + shot-list complete / HUD-footage capture + assembly tooling | H23.22 |
| 0.53 Design System Manifest | 🟡 partial | `frontend/src/styles.css` tokens + `BRAND_BOOK.md` / inspectable component library | — |
| 0.54 Skill Operating System | ✅ done | `skills/{loader,importer}.py`,`skill_drift.py`, SKILL.md manifests | — |
| 0.55 Design Partner Kit | ⬜ missing | — / feedback/NPS widget, issue bundle, SLA | H23.21 |
| 0.56 Trust Center | ✅ done (#300) | `security/audit.py`,`routers/security.py` (kill_switch, audit_verify), `LOCAL_ONLY_AGENTS` + HUD panel ✅ (#300) / cloud-hop log, consent still open | H23.3/5/16 |
| 0.57 Release Packaging | ✅ done | `release.yml` builds bundles + SBOM/NOTICE + checksums + optional GPG sign (H23.13), compat matrix (H23.14) | H23.13/14 |
| 0.58 Pack Manager | 🟡 partial | `skills/marketplace.py` (registry) / model/domain/content packs, remove/rollback | — |
| 0.59 Proof Assets | 🌱 seed | `marketing/` + `docs/marketing/` / landing, README hero, demo video + competitor-comparison & SEO landing pages | H23.22 |
| 0.60 Local Analytics | ✅ done (#300) | `analytics_store.py`,`observability/north_star.py`,`/api/metrics/north-star` + HUD meter ✅ (#300) / activation funnel still open | H23.20 |
| 0.61 Database Future Check | 🟡 partial | `settings_db.py` (WAL) + `persistence/migrations.py` (schema-migration framework ✅ #305) / Turso/libSQL eval | H23.7 |
| 0.62 System Profiles | ⬜ missing | VRAM mgmt only / Gaming/AI/Multimedia/Admin modes | 0.17 |
| 0.63 Restore & Soak | 🟡 partial | backup/restore+drill ✅ (#302) + `resilience.py` / 72h soak, failure injection | H23.8/12 |
| 0.64 Floating Bar + Global Hotkey | ⬜ missing | `desktop/src-tauri/src/main.rs` is a setup stub (no `GlobalShortcutManager`); `frontend/src/app.tsx:126` hotkeys fire only when the browser tab is focused / a system-wide summon bar (Cmd+/ / Ctrl+/) as a thin always-on overlay — the competitor's signature UX | 0.15 / 0.29 |
| 0.65 One-Hotkey Screen-Capture Reflex | 🌱 seed | VLM brain ✅ (`llm/vlm.py`, theme 0.27) + `screen_grounding.py` + `desktop_operator.py` exist but unwired / one keypress → screenshot current screen → VLM → answer with no copy-paste (depends on 0.64) | 0.16 |
| 0.66 SaaS Connector Breadth | 🟡 partial | ~20 working integrations but a messaging/IoT-heavy mix; missing the white-collar suite: Linear · Asana · Trello · Todoist · ClickUp · Figma · Obsidian · Google Sheets · Microsoft 365 (Outlook/OneDrive/full Teams) · Apple Notes/Reminders/Calendar | — |
| 0.90–1.0 gates (Freeze · RC · Partner · Burn-In · Owned) | ⬜ pending | `AUDIT.md`,`MANUAL_TESTING.md`,parity/auth gates, north-star eval / promote eval→required gate; design partners; landing+demo | 1.0.0 row + H23.21/22 |

> **The only 6 truly greenfield (⬜) among 0.19–0.63:** 0.20 Vault · 0.42 Security Skills · 0.48 Video Production ·
> 0.55 Design Partner Kit · 0.57 Release Packaging · 0.62 System Profiles. *(0.52 Demo Factory → 🌱 seed and
> 0.61 DB Future Check → 🟡 partial on the 2026-06-25 re-audit.)*
> Everything else is ✅/🟢/🟡/🌱 — **finish-the-PARTIALs beats start-greenfield** (audit guidance).
> Top remaining finish-firsts: **0.36 Action-Manifest unify**, **H23.10 retention defaults**,
> **export HTTP surface** (`/api/admin/export`, sibling of backup/forget). *(Done: H23.7 DB migrations #305,
> H23.8 backup #302, H23.9 export #303 + delete/forget #306, 0.56 Trust Center + 0.60 Analytics #300.)*
>
> **Full per-theme execution specs** for every deferred theme above now live in **Phase E** of the
> [remaining-backlog blueprint](docs/superpowers/specs/2026-06-23-orizont24-remaining-backlog-blueprint.md)
> — each with grounded `file:line` seams, build steps, acceptance criteria, a test path, and its K/V
> dependency. Load-bearing seams were re-verified against the codebase on 2026-06-23.
>
> **Addendum 2026-06-25 — getjarvis.eu gap delta:** A fresh competitive-gap pass against the shipped
> consumer product **getjarvis.eu** (screen-aware floating-bar desktop AI, 30+ OAuth SaaS connectors,
> freemium) is captured in [`docs/research/2026-06-25-getjarvis-competitive-gap.md`](docs/research/2026-06-25-getjarvis-competitive-gap.md).
> Net-new buildable items folded in above as **0.64–0.66**. **Explicit non-goals** (conflict with the
> local-first / single-user north star): managed-cloud freemium + billing, multi-tenant team features,
> and uploading screenshots to a cloud VLM — we win these on privacy by *not* doing them.

---

## 🆕 H23 — Productionization & 1.0 Readiness (the un-ticketed layer)

> Surfaced 2026-06-21 by cross-referencing the codebase against an external 1.0 checklist
> (Immich "stable" criteria, OpenSSF baseline, OWASP Agentic/LLM Top-10). These are the things a
> credible 1.0 needs that the feature backlog never captured. Status tags: **EXISTS** (code there,
> expose/gate only) · **PARTIAL** · **MISSING**. Each item is its own future PR; mapped to a version above.

| ID | Item | Status | → Version |
|----|------|--------|-----------|
| H23.1 | Per-task step/recursion + token/time **budgets + loop detection** (OWASP unbounded-consumption) | 🟢 **primitives done (folded into K3)** — `kernel/budget.py` adds the per-task token/wall-time/recursion-depth ledger + loop-wide circuit breaker the audit flagged missing, enforced at the kernel front door. Remaining = wiring the ledger through every executor/broker (the K3 unification). | 0.13 |
| H23.2 | **Model-version pinning & reproducibility** — record id/quant per run; approved-model allowlist | 🟢 **allowlist / pinning done** — opt-in per-agent `approved_models` in `agents.yaml` (parsed in `config.AgentConfig`), enforced at the routing front door: `hybrid_router.select_backend` now wraps the core router and **blocks** an off-list model (`ModelNotApprovedError`), strict by default with a `JARVIS_STRICT_MODELS=0` warn-escape (mirrors `JARVIS_STRICT_EGRESS`); `approved_models()`/`is_model_approved()` queries. Empty list = unrestricted, so zero behavior change today. `tests/test_model_reproducibility.py` (+6). **Pending:** the *reproducibility* half — record `model_info{id,version,quant,sha256}` per run in `tracer.py` (needs a `/v1/models` fetch from LM Studio/Ollama; deferred to avoid changing the `generate()` return contract). | 0.13 |
| H23.3 | **Kill-switch in the HUD** (one-tap) + credential quarantine on halt | EXISTS (code) / no UI | 0.13 |
| H23.4 | Promote **eval/regression harness to a pre-release gate** | EXISTS / not a gate | 0.13 |
| H23.5 | Audit-log **verify button** in HUD + secret redaction guarantee | ✅ UI **DONE (#300)** (Trust-mode live audit-verify badge). *Caveat (audit 2026-06-23):* the chain is **plain SHA-256 (not keyed)** and the scanner still stores raw `matched_text` → **AUD-9 / AUD-12** | 0.13 |
| H23.6 | TASK-3 indirect-injection / cross-channel **taint-tracking** | 🟢 **flag + kernel enforcement done** — `security/taint.py` (`mark`/`mark_if_untrusted`/`is_tainted` + an untrusted-source classifier for web/OSINT/RSS/inbound/channel); `kernel.authorize` now **escalates a tainted action from GRANT → QUEUE** (approval), so injected content can't auto-execute (verified against the real `AutonomyPolicy`). `tests/test_taint_flag.py` (+5). **Pending (deferred per plan):** full data-flow *propagation* — marking content tainted at every ingestion choke point + carrying taint through derived content. | 0.12 |
| H23.7 | **DB schema-migration framework** (`_schema_version` + forward-only on startup) | ✅ **DONE (#305)** — `agents/core/persistence/migrations.py` | 0.14 |
| H23.8 | **Backup/restore** (one-command) + a tested **restore drill** | ✅ **DONE (#302)** — `agents/core/backup.py` + `/api/admin/backup` (consistent SQLite snapshots, restore-drill). *Residual (audit 2026-06-23):* archives were **unencrypted** → **AUD-1 ✅ (#309)** (opt-in `.tar.gz.enc` + `settings.db` secret columns now encrypted at rest) | 0.14 |
| H23.9 | **Data export + delete/forget** endpoints (finishes promised H8.2) | ✅ **done (#315)** — export `agents/core/data_export.py` + now `POST /api/admin/export` (admin-guarded, secrets-free); delete/forget `data_purge.py` + `POST /api/admin/forget` now also erases memory at rest (**AUD-2**, this PR); backup-first copy encrypted with a key (**AUD-1** #309). *Done #303/#306; export HTTP surface + forget-completeness this PR.* | 0.14 |
| H23.10 | Data-**retention defaults** (conversations, audit log, memory) + rollback story | ✅ **done (#317)** — `retention` settings category (off by default; TTL `0` = keep forever) + `agents/core/retention.py` daily sweep (`scheduler_service.schedule_retention`, 03:30): prunes old conversation transcripts by mtime and old audit rows via a chain-preserving `AuditLogger.prune_before` re-anchor (`verify_chain` still passes). *Rollback = the pre-existing backups; memory-decay TTL stays with the decay system.* | 0.14 |
| H23.11 | Health/readiness endpoint; signal handlers + graceful shutdown; **log rotation** | ✅ **done** — liveness `GET /healthz` (dependency-free) + readiness `GET /readyz` (**503** until orchestrator+agents loaded; LLM-down does *not* gate readiness) in `routers/ops.py`; `serve.py` now builds a `uvicorn.Server` from env (`JARVIS_HOST/PORT/LOG_LEVEL/SHUTDOWN_TIMEOUT`) with a **bounded `timeout_graceful_shutdown`** so `systemctl stop`/SIGTERM drains in-flight requests then runs the lifespan teardown instead of hanging; opt-in **rotating file log** in `core/log.py` (`RotatingFileHandler`, `system.log_to_file`/`log_max_mb`/`log_backups` + `$JARVIS_LOG_FILE` overrides; default off → stderr only, supervisor rotates). **Review-hardened (adversarial pass):** the probes **bypass the per-IP rate limiter** (`_PROBE_PATHS` in `web.py`) so a non-localhost LB/Docker healthcheck can't be 429'd into evicting a healthy instance; `serve.assert_safe_bind()` **fails closed on a non-loopback bind** without a token or `JARVIS_ALLOW_INSECURE_BIND=1` (AUD-4 analog, since `JARVIS_HOST` is new); 503 readiness shares the full `no-store` policy; file-log PII/in-repo-path lifecycle documented (bounded by rotation, *not* the H23.10 sweep). `tests/test_h2311_operability.py` (+18). | 0.15 |
| H23.12 | Graceful **local-LLM-down** handling everywhere (no hang/crash) | ✅ **done** — root cause was the local backends (`llm/base.py` LM Studio + Ollama) bypassing the `http_client.py` split-timeout pattern with a flat `timeout=300/120s` (covers *connect* → a down/unreachable server could hang minutes) and returning the **raw exception** as the reply (`[LM Studio error: {e}]` → leaked into the chat bubble + poisoned conversation memory). Now: **split timeout** `local_read_timeout()` (`connect=5s`, long read) → down-detection ~5s, generation budget intact; `local_backend_degraded_reply()` returns a **clean, classified** message (unreachable vs error, raw detail logged not surfaced) across `generate()`+`generate_stream()` for both backends; `is_degraded_reply()` shared predicate keeps `warm_up`'s failure-detection working past the message change. `tests/test_llm_down_graceful.py` (+12: MockTransport down/timeout → fast clean reply, no raise/leak; timeout-config; warm_up regression guard). | 0.15 |
| H23.13 | **Release engineering** — artifacts (tar/zip), optional PyPI + Docker publish, signed releases | ✅ **done** — `release.yml` now goes tag→**artifacts**→Release: `scripts/build_release.sh` produces reproducible `jarvis-<ver>.{tar.gz,zip}` source bundles (via `git archive`, so `.env`/`agents/data`/`memory_logs`/`.venv`/`node_modules` are excluded by construction), a CycloneDX `SBOM.json` + `NOTICE` (`scripts/gen_sbom.py`, dep-free), and `SHA256SUMS`; a **tag↔`agents.__version__` guard** fails the release on a forgotten bump; **GPG signing** is wired but owner-gated (skips cleanly without the `GPG_PRIVATE_KEY` secret); `workflow_dispatch` dry-run exercises the build path without cutting a tag. **PyPI = N/A by design** (the project runs from source, not pip-installed); **Docker publish** documented as owner opt-in (compose already builds locally). `docs/RELEASE.md` (cut + verify), `tests/test_release_build.py` (+2: end-to-end build/checksum/leak/SBOM + requirements parsing). | 0.15 |
| H23.14 | **Semver compatibility contract** + supported-versions matrix + deprecation policy + platform matrix | ✅ **done** — `docs/COMPATIBILITY.md` (SemVer + pre-1.0 caveat, public-surface definition, supported-versions matrix, deprecation policy, platform matrix incl. the real **Python 3.12+** floor / Node 20+ / Docker-optional) + `SECURITY.md` rewritten from the GitHub placeholder into a real supported-versions + disclosure policy. **Gated:** `tests/test_compatibility.py` asserts the docs' supported-version lines track the single-sourced `agents.__version__` (so CDX-5 drift can't return) + valid SemVer + the documented Python floor. | 0.15 |
| H23.15 | systemd/service templates (Linux/Windows) | ✅ **done** — `deploy/systemd/jarvis-hub.service` (hardened unit: `ProtectSystem=strict`/`NoNewPrivileges`/restricted address families; `KillSignal=SIGTERM` + `TimeoutStopSec` margin over `JARVIS_SHUTDOWN_TIMEOUT` → the H23.11 bounded graceful drain) + `jarvis-hub.env` + README; `deploy/windows/install-service.ps1` (NSSM, Ctrl-C graceful stop) + README; `deploy/README.md` index wiring the `/healthz`·`/readyz` probes. Both consume the H23.11 env knobs; guarded by `tests/test_compatibility.py`. | 0.15 |
| H23.16 | **Network monitor** HUD panel (prove LOCAL_ONLY agents make zero outbound calls) | PARTIAL — **data layer + API done**: thread-safe `observability/egress_monitor.py` (in-memory ring buffer + monotonic per-plugin counters) records *every* outbound attempt — allowed **and** blocked — at the `http_client.py` choke point (all 6 verbs via one `_guard`); `GET /api/admin/network/calls?plugin=&limit=` (admin-guarded) serves per-plugin tallies + recent events + `local_only_violations` (the proof: a NONE/LAN plugin with an allowed external call surfaces as a violation → `clean=False`). `tests/test_network_monitor.py` (+9, MockTransport — no real socket). **HUD panel done:** `NetworkMonitorPanel` in the Console (`gap.tsx`, Trust section) reads the endpoint and renders the `clean` local-only proof + per-plugin allowed/blocked/external + any violation in red; `frontend/src/test/network-monitor.test.tsx` (+2, fetch-mocked) — passes `tsc --noEmit` + vitest. ⚠️ Only the live-pixel render is owner-runtime-gated (CDX-9), as for every HUD panel. | 0.16 |
| H23.17 | **Quality gates** — E2E (Playwright), load/soak, a11y (WCAG), i18n completeness, browser+mobile matrix | 🟡 **i18n-completeness ✅** (+ load/soak earlier, AUD-17) — `frontend/src/test/i18n-completeness.test.ts`: every locale (en/ro) must match the reference key set with no missing/extra/blank strings; runs in the CI vitest job (`ci.yml` → `npm test`), so a half-localized string can't ship. Sandbox-isolation lane ✅ (AUD-11), real-path p95 load test ✅ (AUD-17). **Pending:** Playwright **E2E** (chat/voice flows — feasible here, Chromium available), **a11y** (`@axe-core/playwright`), nightly **soak**, browser+mobile matrix. | 0.19 |
| H23.18 | **User docs** — USER_GUIDE, FAQ, UPGRADE (per-version migration notes) | 🟢 **done** — `docs/USER_GUIDE.md` (requirements → install (Win one-click / any-OS) → start → the cabinet → configure a model → daily use (chat/voice/autonomy/plugins) → admin panel → data controls), `docs/FAQ.md` (data-leaves-machine, telemetry, GPU, models, OS, multi-user, stop-autonomy, channels, cost, update, backup/export/delete, WorldView/Signal), `docs/UPGRADE.md` (Win `UPDATE.bat` / manual `git pull`+reinstall+restart / release-bundle; **automatic forward-only migrations** H23.7; backup-first rollback; graceful restart H23.11; per-version notes → COMPATIBILITY/SemVer). Linked from README; `tests/test_user_docs.py` (+4). | 0.19 |
| H23.19 | **Trust/security docs** — THREAT_MODEL, SECURITY disclosure policy + advisories, NOTICE/SBOM, **telemetry opt-in disclosure**, privacy policy | 🟢 **done** — `docs/THREAT_MODEL.md` (boundaries + assets + 11 threats each mapped to the *real* seam: egress gate/monitor, action kernel, K3 budgets/loop-breaker, encrypted secrets, HMAC audit, injection/Cypher/WKT guards, sandbox isolation, fail-closed bind, supply-chain) + continuous-verification matrices + honest residual risks; `docs/PRIVACY.md` (local-first, **no telemetry / no phone-home** disclosure, first-party-analytics clarification, opt-in egress data-flow table, user controls: export/forget/retention/kill-switch). SECURITY disclosure + NOTICE/SBOM already shipped (H23.14 / H23.13). Linked from README + SECURITY.md; `tests/test_trust_docs.py` (+3) guards existence/grounding/discoverability. | 0.19 |
| H23.20 | **Onboarding wizard** + activation-funnel instrumentation + cold-start error guidance | 🟢 **backend done** — `routers/onboarding.py`: `GET /api/onboarding/wizard` (ordered steps intro→model→test_chat→autonomy, `complete` **derived from recorded funnel events** so onboarding resumes across reloads; `model_ready` + a friendly cold-start `hint` when no backend is reachable) + `POST /api/onboarding/funnel` (records first-party local `funnel.<step>.<event>` via `analytics_store`, bounded to known steps); both `user_guard`'d. `tests/test_onboarding_wizard.py` (+4); route parity/auth/openapi + HUD-v2 IA (cockpit home) snapshots reseeded. **Pending:** the `/onboarding` HUD page that drives it (owner-runtime-gated, CDX-9). | 0.19 |
| H23.21 | **Design-partner program** — recruit 1–3, in-app feedback/NPS, support SLA, collect north-star from real usage | 🟢 **feedback loop + program doc done** — `feedback_store.py` (first-party local SQLite: nps/comment/bug, bounded) + `routers/feedback.py`: `POST /api/feedback` (user-guarded footer widget) + `GET /api/feedback/summary` (admin — **NPS** %promoters−%detractors + per-kind counts + recent); `docs/DESIGN_PARTNER_PROGRAM.md` (recruit 1–3, 48 h SLA, what-to-measure tied to north-star/guardrails, privacy). `tests/test_feedback_widget.py` (+4); snapshots reseeded (HUD home = observe). **Pending:** the HUD footer widget UI (owner-runtime-gated) + actually recruiting partners (owner). | 0.20 |
| H23.22 | Landing page + demo recorded (owner-led; dev-supportable) | MISSING | 0.20 |
| H23.23 | **Multi-user readiness call** — accept single-user for 1.0 & document it, OR scope per-user isolation (north-star is "per active user") | DECISION | 0.20 |

---

## 🧠 ORIZONT 24 — AI-OS: Action Kernel · Verification Fabric · Live Packs (direction 2026-06-23)

> **Decision (owner, 2026-06-23):** primary bet = **OS kernel + Verification Fabric**; first capability
> packs = **all four** (Proactive autonomy · OSINT/WorldView · Market Intel+Finance · Creative/Publishing).
> This is the **substrate program for Phase 2** ([MOONSHOT.md §4](MOONSHOT.md)) — the bridge from
> *feature-complete* (v0.10) to a **provable** 1.0. *(ORIZONT 23 ≡ the **H23** productionization layer
> above; this horizon sits on top of it and reuses its items.)*
>
> **Thesis:** convert fleet throughput into a *trustworthy* operating system by (a) routing **every**
> agent action through one kernel, and (b) making *"works end-to-end against reality"* a merge gate —
> then deepen breadth (the 4 packs) in parallel on that substrate. This makes the moonshot's
> "persistent, proactive, private **cortex**" operational.
>
> **Not net-new scope — it threads existing seeds into one program.** Most parts already exist, scattered;
> ORIZONT 24 *promotes and unifies* them. Map: **K3 ⊇ H23.1** · **K4 ⊇ H23.3** · **V4 ⊇ H23.4** · the kernel
> unifies `plugin_gate` / `signal_governance` / capability-broker / per-family approval queues · the packs
> deepen competitive-gap themes **0.32/0.38/0.45** (P1), **0.40/0.41** (P2), **0.39** (P3), **0.47/0.50** (P4).
> **Phase A = the AUD-\* hardening cluster** (see *Hardening audit (2026-06-23)* below) — the foundation;
> skipping it is the OpenClaw failure mode.
>
> **📋 Cross-phase execution map:** [`docs/superpowers/specs/2026-06-23-orizont24-remaining-backlog-blueprint.md`](docs/superpowers/specs/2026-06-23-orizont24-remaining-backlog-blueprint.md)
> — every remaining backlog item, **Phases A–E** (hardening · K/V substrate · the 4 packs · H23
> productionization · all deferred competitive-gap themes), grounded with `file:line` seams to reuse,
> approach, acceptance, and test paths. The context-cheap map sessions execute against instead of
> re-reading the ~2M-token repo; each item ships as its own PR.

**The OS metaphor, made literal:** agents = processes · capability tokens = permissions · the kernel =
the syscall table · budgets = the scheduler · kill-switch/quarantine = a syscall · the verification fabric
= the OS test-suite. These exist today but are **scattered**; ORIZONT 24 makes them **one system**.

**Phasing & gates** (gate-discipline per MOONSHOT §4 — we do not skip gates):
- **Phase A (now):** AUD-\* P0/P1 hardening — foundation; also advances H23.
- **Phase B:** Track K + Track V core. **Gate:** action-auth matrix green · reality-harness live · readiness board shipped.
- **Phase C:** the 4 packs, fleet-parallel, each driven SEAM→VERIFIED. **Gate (per pack):** VERIFIED via harness + north-star moving.
- **Phase D:** 1.0 proof — 3–5 design partners (unchanged; **= the 1.0 gate**).

### Track K — Action Kernel (the "operating" in operating system) (P0–P1)

> **Design spec:** [`docs/superpowers/specs/2026-06-23-orizont24-action-kernel-design.md`](docs/superpowers/specs/2026-06-23-orizont24-action-kernel-design.md)
> — grounded in the existing seeds it unifies (`security/capability.py:authorize()` nucleus, the autonomy
> `TaskQueue`, `plugin_gate`/egress, route guards, `SecretBroker`) + the 3 verified bypass risks it closes.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| K1 | 🟢 **facade + wave-1 in PR** — **Single mediation point** — every privileged action (tool call, plugin egress, write-back, payment, social, node dispatch) flows through `kernel.authorize(action, capability, budget)` → grant / deny / queue-for-approval. Unifies `plugin_gate` + capability broker + `signal_governance` + per-family approval queues. **Landed (default-off `JARVIS_ACTION_KERNEL`):** the `agents/core/kernel/` facade *composing* the `security.capability.authorize` nucleus + `policy.decide` + audit→`intent_log` (not reimplementing); **wave-1** routes the 4 TaskQueue brokers (call/social/writeback/node) through it; the **action-auth matrix gate** (`tests/test_action_auth_matrix.py` + `_snapshots/action_auth.json`, a `Mediation` registry whose enumeration is derived from broker `KIND`s) fails CI on a new unclassified privileged action; B2 fail-closed pinned, B1/B3 xfail scaffolds. **Payment micro-wave ✅** — an *admissible* `request_payment` now routes through `kernel.authorize` (the broker carries a `kernel` hook, bound in `web.py` via the shared `kernel/binding.py` that also feeds the wave-1 brokers): a kernel **DENY** (kill-switch engaged / over-budget / runaway loop) refuses the payment **before** it can become pending, while GRANT/QUEUE fall through to the existing always-approval flow (the mandate's hard caps still gate admissibility first). Default-off; `payment` flips `PENDING_KERNEL → KERNEL` in the action-auth snapshot; `tests/test_payment_kernel_wave.py` (+6, incl. a real-`KillSwitch`+real-policy integration). **Wave-2 egress ✅** — policy-passing plugin egress now routes through `kernel.authorize` via an **injected hook** in `http_client` (a `(plugin,method,url,host)→reason|None` callable from `kernel/binding.make_egress_kernel_hook`, wired by the orchestrator alongside the B3 audit sink), so `http_client` never imports the kernel. A kernel **DENY** (halted kill-switch → no outbound calls / over-budget / runaway loop) blocks otherwise-allowed egress; a buggy hook **fails open** (manifest policy already ran). `plugin.egress` flips `PENDING_KERNEL → KERNEL`; the B3 xfail scaffold is now a real passing regression; `tests/test_egress_kernel_wave.py` (+10, incl. a real-`KillSwitch` halt→block / release→allow integration). With B3's audit (`EGRESS_DOWNGRADE` event, `tests/test_egress_audit_b3.py`) this closes the egress story. **Pending (`PENDING_KERNEL`, shrinks per wave):** MCP + KG writes (wave 3), admin security routes (wave 4 → closes B1). | 8 | P0 | Phase A | every privileged action routes through the kernel; no bypass path exists |
| K2 | **Capabilities as process permissions** — generalize the seeded scoped/expiring/revocable tokens (`security/`, `node_mesh`) to **all** agents; least-privilege by default. | 5 | P1 | K1 | 🟢 **issuance done** — `kernel/capabilities.py` **derives** a least-privilege capability set per agent from its declared config (`agent:<id>` + `plugin:<p>` per declared plugin + `channel:<c>` + `model:local`; `model:cloud` only for a non-local-only agent whose policy permits it). The orchestrator issues a scoped `CapabilityBroker` token per agent at boot (`orch.agent_capabilities`, best-effort). `tests/test_kernel_capabilities.py` (+6) + a scratch run over the **real 17-agent roster** (frigga/ultron/howard get **no cloud cap**; revoke is immediate via the broker). **Pending:** per-action **enforcement** (the kernel waves passing each agent's token) + folding WorldView HMAC tokens in as one kind → closes **B1**. |
| K3 | **The scheduler** — central token/time/money/**interrupt** budgets + loop detection (folds **H23.1**). The interrupt budget *is* the MOONSHOT §5.4 "≤4 push/day" guardrail, enforced in one place. | 5 | P0 | K1 | 🟢 **missing limits + loop breaker done** — `kernel/budget.py`: `BudgetLedger` (per-task **token + wall-time + recursion-depth**) + `LoopDetector` (loop-wide circuit breaker — same action past a threshold in a window trips → open until reset). `kernel.authorize` now enforces them at the front door *before* policy (DENY + audit on over-budget / runaway), **inert** unless a ledger/detector is supplied so K1 brokers are unchanged. `tests/test_kernel_budget.py` (+10). **Pending:** unify the *existing* `InterruptBudget` (≤4/day) + mission step/time + payment caps into this one object, and thread a per-task ledger through the brokers/worker |
| K4 | **Kill-switch + credential quarantine as a syscall** (folds **H23.3**) with one-tap HUD control. | 3 | P1 | K1 | 🟢 **syscalls done** — `kernel/syscalls.py`: `halt()`/`release()` (engage/disengage the persisted `KillSwitch`, audited) + `inject_guarded()` makes secret injection **quarantine-aware** (while halted, injection is forced blocked regardless of approval — no value leaks). Composes existing primitives, no surgery; "halt halts new grants" already enforced by `kernel.authorize`. `tests/test_kernel_syscalls.py` (+5) + a scratch smoke against the **real** KillSwitch/SecretBroker (contracts match, no secret leak while halted). **Pending:** the one-tap **HUD** control (frontend — productionization-tail phase). |
| **Gate K** | **action-auth matrix** test (generalizes the SEC-2 route-auth matrix) fails CI if **any** privileged action bypasses the kernel. | — | P0 | K1–K4 | a new un-mediated privileged action fails CI |

### Track V — Verification Fabric (what makes fleet-breadth safe) (P0–P1)

> **Design spec:** [`docs/superpowers/specs/2026-06-23-orizont24-verification-fabric-design.md`](docs/superpowers/specs/2026-06-23-orizont24-verification-fabric-design.md)
> — extends the existing snapshot-introspection gates (`test_route_auth_matrix`) + registries
> (`plugin_gate.BUILTIN_PLUGINS`, `component_registry`) + the ungated eval/north-star harness.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| V1 | **Reality harness** — each capability declares a contract + a live (or hermetically-sandboxed-but-real-protocol) integration test, run on a CI schedule. Null clients stay for unit speed; the harness proves the **rail**. | 8 | P0 | — | 🟢 **framework + V1→V2 promotion done** — `observability/reality_harness.py`: `RealityCase{capability_id, contract, probe, live}` + `run_reality()` (mirrors `eval.py`'s result schema); a **green probe is the only path** that promotes a capability to VERIFIED in the V2 registry (`record_verification`), a fail un-verifies, a human can still only demote. Hermetic (real-protocol, no socket) vs `live` (gated by `JARVIS_REALITY_HARNESS=1`). Seed cases prove the **egress-policy rail** (NONE blocks external / LAN allows local) → both promote to VERIFIED. Scheduled-only lane `.github/workflows/reality.yml` (nightly + dispatch, off the PR path). `tests/test_reality_harness.py` (+6). **Pending:** per-capability **live** contracts (real key/network, needs the networked nightly lane) · **durable cross-process** promotion (committed readiness snapshot) folds into **V3** |
| V2 | **Capability registry + readiness levels** — every capability carries a state **SEAM → WIRED → VERIFIED → GA**, queryable, with a HUD board + `/api/metrics`. Kills the audit's "looks done, isn't wired" ambiguity. | 5 | P1 | V1 | 🟢 **registry substrate done** — `observability/capability_registry.py` **derives** a `CapabilityRecord{id,kind,owner_agent,state,harness_id,…}` per capability from `plugin_gate.BUILTIN_PLUGINS` + `component_registry.status` + `skills` (no parallel system); `GET /api/metrics/capabilities` (open, sibling of north-star) serves it + `by_state`/`by_kind` roll-ups + an honest `harness_pending` (**nothing reaches VERIFIED/GA** — only the V1 harness promotes; a human can demote, cap at WIRED). `tests/test_capability_registry.py` (+6). **Pending:** HUD readiness board render (owner-runtime-gated, CDX-9) · VERIFIED-promotion via the V1 reality harness · the V3 `test_capability_readiness_matrix` enforcement gate |
| V3 | **Fleet-coordination CI gates** — interface contracts + the action-auth matrix + a readiness gate (no VERIFIED without a green harness) + drift detection, so N parallel agents can't silently break each other. | 5 | P1 | V1, V2, K1 | 🟢 **readiness matrix gate done** — `tests/test_capability_readiness_matrix.py` snapshots `_snapshots/capability_readiness.json` over the deterministic plugin set (33 caps) and **fails CI** on: capability drift (added/removed/state-changed, e.g. a plugin silently disabled WIRED→SEAM), a **fabricated VERIFIED** (VERIFIED/GA with no `harness_id` — guards the registry invariant), or an **unclassified SEAM**; honest escape sets `INTENTIONALLY_SEAM`/`PENDING_VERIFY` kept non-stale by a test (the route-auth SEC-3 pattern). **Pending:** components/skills coverage (needs a booted fixture) · **cross-agent interface-contract drift** (A2A/subagent/kernel-action schema) — the multiplier-risk half of V3 |
| V4 | **Promote eval → required release gate** (folds **H23.4**) with the north-star + counter-metrics as merge gates — quality can't regress at fleet speed. | 3 | P1 | V1 | 🟢 **counter-metric guardrails done** — `north_star.GUARDRAILS` encodes the MOONSHOT §6 bounds (interrupt ≤4/day, reject ≤0.5, %-local ≥50, p95 <2s) + `check_guardrails()`; `compute_north_star()` now surfaces `guardrail_breaches`/`guardrails_ok` (so `GET /api/metrics/north-star` + the HUD board flag a breach); a None metric is **skipped not failed** (no fabricated breach). `tests/test_north_star_guardrails.py` (+6). **Pending:** the golden-dataset **eval-regression** as a *blocking* CI job (compare machinery exists in `test_h9_3b_dataset_regression.py`; a real quality gate needs a live model → the GPU/networked nightly lane) + enforcing guardrails as a hard merge-block on **real-usage** data (offline CI has none) |
| **Gate V** | the readiness board is live; **nothing reaches VERIFIED** without a green reality-harness. | — | P0 | V1–V4 | VERIFIED claims are harness-backed, not asserted |

### Track P — Live Capability Packs (breadth on the substrate, fleet-parallel) (P0–P2)

> Each pack = drive its rails **SEAM→VERIFIED**, mediated by Track K, gated by Track V. (Maps = competitive-gap themes deepened.)
> **P1 design spec:** [`docs/superpowers/specs/2026-06-23-orizont24-p1-proactive-autonomy-design.md`](docs/superpowers/specs/2026-06-23-orizont24-p1-proactive-autonomy-design.md)
> — the loop is already wired end-to-end (`observer`/`watchers` → `policy` → Telegram inbox → `TaskExecutor`
> → write-back/social/call → `north_star`); P1 = drive it SEAM→VERIFIED on the K/V substrate + close 3 proof
> gaps (unified "Today" timeline · night-shift north-star split · proposal-funnel diagnostics).

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| P1 | **Proactive autonomy core** — missions + watchers + digest + governed write-back (deepens 0.32/0.38/0.45). *Do first: the only pack that directly moves the north-star (actions accepted/week) and that stress-tests K3's interrupt budget.* | 8 | P0 | K1–K4, V1–V2 | "works while you sleep" demonstrated **and measured**; interrupt/reject within budget |
| P2 | **OSINT / WorldView** — correlation, evidence drawer, world-brief routing (deepens 0.40/0.41). Most differentiated surface; forces the kernel to prove governance on **untrusted** data. | 8 | P1 | K1, V1 | pack VERIFIED; ingestion trust-boundary enforced (closes the F12/AUD ingestion finding) |
| P3 | **Market Intel + Finance** — watchlists, balance/analytics, alerts with disclaimers (deepens 0.39). Concrete daily utility. | 5 | P1 | K1, V1 | pack VERIFIED; daily brief demoable |
| P4 | **Creative / Publishing** — coordinated asset pipeline + export/render packs (deepens 0.47/0.50; also fuels **0.52 Product Demo Factory** / marketing). | 5 | P2 | K1, V1 | pack VERIFIED; export packs render (YouTube/IG/README) |
| **Gate P** | per pack: **VERIFIED** via the reality-harness **and** the north-star is moving. | — | P0 | Gate V | no pack ships SEAM-only |

> **North-star alignment (by construction):** P1 drives *actions accepted/week*; K3 enforces the
> *interrupt budget*; V4 guards *reject-rate, %-local, p95-latency* as merge gates — the program can't
> drift off the metric without failing its own gates. **Totals:** 12 items + 3 gates, ~68 SP
> (K ≈21 · V ≈21 · P ≈26). **Design specs written** for both substrate tracks (K + V, linked above) —
> next is *implementation*, not design. **Next concrete steps:** finish Phase A (AUD-\*) → land the
> default-off `kernel.authorize` facade (**K1**) + the capability-readiness registry/harness scaffold
> (**V1/V2**) in parallel → wire the action-auth + readiness matrices → K3/V4 gates → then **P1 first**.

---

## 🔐 Security route-policy gate (audit 2026-06-17 — assessment done, fix pending)

External GPT audit + **runtime verification** (300 routes: 89 admin / 87 user /
**124 open, of which 43 are open *and* mutating**). Guard model is sound; the gap
is routes with **no guard attached**. Footguns on localhost; real unauthorized
control surfaces on LAN/Pi/proxy/tunnel. Full verified write-up + proposed
route-policy table: **`docs/SECURITY_ROUTE_AUDIT_2026-06-17.md`**.

| # | Item | S | P | AC |
|---|------|---|---|----|
| SEC-1 ✅ | **Guard webhook management** — `GET/POST/DELETE /api/webhooks` → `admin_guard`; trigger keeps token/HMAC. Done: `webhooks.py` + contract test (`POST /api/webhooks` off-localhost → 403). | 2 | **P0** | ✅ unauth management → 401/403; trigger still works with token |
| SEC-2 ✅ | **Route-auth matrix test** — `tests/test_route_auth_matrix.py` introspects `app.routes` vs `tests/_snapshots/route_auth.json`; fails CI on guard drift / new or unclassified open mutator. `PENDING_GUARD` set tracks the SEC-3 backlog (shrinks as guards land). | 3 | P1 | ✅ a new unguarded mutator fails CI |
| SEC-3 ✅ | **Apply policy to remaining open mutators** — DONE. Batch 1 (12 → admin): workflows CRUD, plugin toggle, heartbeat ×3, traces/clear, oauth/refresh, oracle sync+resolve, audit/action. Batch 2 (23 → user): workflows run/hierarchical, KG writes ×6, local-docs, reflection, arena ×2, review ×3, eval ×2, autonomy/preview, agent-templates, llm/grammar, schedule/parse, security scan/spotlight. `PENDING_GUARD` is now **empty** — every mutating route is guarded or in `INTENTIONALLY_OPEN` (6 self-authenticating). Final surface: **110 user / 104 admin / 86 open**. Localhost dev unaffected. | 5 | P1 | ✅ enforced by SEC-2 matrix gate |
| SEC-4 | Env/posture follow-ups: **npm Dependabot ✅** · **doc counters refreshed ✅** · **`JARVIS_HOME` runtime-state relocation ✅** (F-08). **Remaining:** promote matrix/parity tests to **required** branch-protection checks (F-10, owner GitHub setting). | 3 | P2 | — |
| SEC-5 ✅ | **F-06 ✅** WorldView bridge Bearer auth (`WORLDVIEW_API_TOKEN`). **F-07 ✅** plugin egress boundary — anchored host/sub-domain matching + `PluginHTTPClient` per-request manifest enforcement, now **strict by default** (`JARVIS_STRICT_EGRESS=0` opts out). Renamed 9 `for_plugin` ids to match manifests; completed allowlists (cloud-llm +Gemini, gmail/gcal +oauth2.googleapis.com, news +RO feeds); self-consistency test pins each plugin's real hosts. | 3 | P2 | ✅ undeclared plugin egress blocked |
| SEC-5b ✅ | **Manifest the remaining networked plugins** — DONE. Added RESTRICTED manifests for `balance`, `analytics`, `websearch`, `digest`, `n8n`, the social/writeback/call families (`social_x`, `writeback_{notion,github,google_calendar}`, `call_{twilio,telnyx}`) and the webhook channels (`channel_{whatsapp,google_chat,teams,signal,matrix}`). Config/env-driven hosts (n8n `N8N_BASE_URL`, websearch `SEARXNG_URL`, Signal `base_url`, Matrix `homeserver`) are handled by a new **`register_dynamic_domain`** runtime allowlist that the egress gate unions with the static `allowed_domains` — no FULL/unmanifested escape. A new registry-driven test (`test_dynamic_family_ids_all_have_manifests`) pins every concrete family member to a manifest so a new member fails CI instead of silently re-opening the gap (the literal-regex test couldn't see the f-string ids). In-code SSRF guards retained as defense-in-depth. **Residual:** per-call webhook URLs passed via `kwargs` to `channel_teams`/`channel_google_chat` are constrained to the Microsoft/Google host suffixes by the static allowlist, not to one specific webhook. | 3 | P2 | ✅ every networked plugin enforced by the gate |

> Verified false-alarms / owner-side (not repo defects): F-04 (auditor's stale
> Windows venv/node_modules — CI builds clean), most of F-05 (needs owner
> Dependabot view). Self-authenticating opens confirmed safe: webhook trigger
> (token/HMAC), a2a/task (peer HMAC, off by default), mcp/server/rpc (disabled by
> default + OAuth), oauth/callback (state-validated).

---

## 📦 Dependency upkeep & the fastapi 0.137 hold (2026-06-19)

Dependabot triage this session — **merged** (safe): `actions/checkout` v6→v7 (#222),
worldview-mcp dev deps (#223), root `vitest` 2→4 + `jsdom` 25→29 (#224). **Held for their own
review cycle:** React 18→19 frontend (#226 — needs v2 bundle rebuild + visual check), WorldView
23-update group (#228), mobile group (#227 — owner-gated, real-device validation per `OWNER_TASKS`).

**fastapi 0.137 upgrade — ✅ RESOLVED (2026-06-19):** fastapi 0.137 wraps `include_router` results in
an opaque `_IncludedRouter` instead of flattening them into `app.routes`, which collapsed the
*introspected* route surface **296→83** and failed the route-parity / auth-matrix guards (the app was
never broken — routes served + appeared in OpenAPI). **Fixed:** `tests/_route_introspect.py`
`iter_effective_routes` flattens the wrappers via fastapi's own `_iter_routes_with_context` (no-op on
≤0.136); both guards use it with **snapshots unchanged**, and `fastapi` is bumped to `>=0.137.2,<0.138`
with `starlette>=0.46,<1.0`. Root cause + repro:
[`docs/research/2026-06-19-fastapi-0.137-include-router-regression.md`](docs/research/2026-06-19-fastapi-0.137-include-router-regression.md).

---

## 🔍 CodeQL & secret-scanning alerts (2026-06-17 — code fixes shipped; dismissals + ~12 triage pending)

GitHub scanning surfaced 25 CodeQL alerts + 1 secret-scanning alert. Of the 13 reviewed:

| # | Item | S | P | AC |
|---|------|---|---|----|
| CQ-1 ✅ | **Fix the real findings** (merged #215, #216): calendar `create_event` kwargs (#248, was a runtime `TypeError`), heartbeat `except None` (#26), `strip_thinking` ReDoS (#1), possessive template regex (#302), `log_safe()` on two admin log lines (#311/#24), and the secret-scan fixture FP (#215). | 3 | P1 | ✅ all green in CI; merged |
| CQ-2 | **Owner: dismiss FPs/won't-fix in the UI** — secret-scan #1 (test fixture), CodeQL path-injection #22/#23/#431 (agent-id regex blocks traversal), var-defined #299/#298/#247 (used defaults), docs #432. See [`docs/OWNER_TASKS.md`](docs/OWNER_TASKS.md) §GitHub settings. | 1 | P2 | owner GitHub action |
| CQ-3 | **Triage the remaining ~12 alerts** — only 13 of 25 selected were captured (no MCP code-scanning-list tool); needs an owner paste to finish. | 2 | P2 | paste → triage → fix real ones |

---

## 🔎 Codex fresh-eyes review (2026-06-24 — external code + doc review)

Independent fresh-eyes review (GitHub-connector read; no local build). Full write-up:
[`docs/research/2026-06-24-codex-review.md`](docs/research/2026-06-24-codex-review.md). **Verdicts
below source-validated against `main` (`e974069`) this session.** The strategic half largely
**validates the current direction** rather than redirecting it: the "Action Kernel" = ORIZONT 24
**Track K**; the trust/readiness board = #300 (partial) + **H23.11/H23.16**; onboarding = **H23.20**;
"finish partials before greenfield" = standing BACKLOG guidance. New, concrete items (`CDX-*`):

| ID | Item | Status | Maps to |
|----|------|--------|---------|
| CDX-1 | ✅ **done** — **`Agent.synthesize()` ignores the routed model** — now unpacks `backend, routed_model, route_name` and applies `routed_model` (same as `process()`), so multi-agent fusion runs on the routed local/cloud model/policy instead of the configured default. `tests/test_cdx_bugfix_batch.py`. | ✅ | — |
| CDX-2 | ✅ **done** — **Interaction records hard-code `"channel":"web"`** — `_record_interactions` now takes the real `channel` (threaded from `process()`/`handle_input()`) into the learning metadata, so the %-local/cloud ratio + per-channel analytics reflect the true origin. `tests/test_orchestrator_process_record.py`. | ✅ | [METRICS](docs/METRICS.md) |
| CDX-3 | ✅ **done** — **One stale `last_n=6`** (`_call_agents_parallel`) now honors `memory.context_window` like the main per-agent path (`:850/859`). | ✅ | — |
| CDX-4 | ✅ **done** — **App version `0.5.0-beta`** retired; `web.py` `FastAPI(version=…)` (and `/status`, OpenAPI `info.version`) now read `agents.__version__` (= `0.11.0`), the single source. `tests/test_cdx_bugfix_batch.py`. | ✅ | CDX-5 |
| CDX-5 | 🟡 **partial** — **Doc/version/test drift** — version single-sourced (CDX-4) + README badge/headline aligned to v0.11.0 + STATUS test counter refreshed. *Remaining:* a `scripts/status_sync.py` to auto-derive the volatile counts (routes/tests) from one source. | 🟡 | H23.18 |
| CDX-6 | **Per-agent timeout hard-coded 120s** (`orchestrator.py:1170`) — fold into per-task token/time budgets (don't share one invisible ceiling across chat/deep-research/autonomy/eval). | ⬜ | H23.1 / K3 |
| CDX-7 | **Howard RAG provenance** — `agent.py` injects retrieved memory text into prompts; treat memory as untrusted: delimit as retrieved context (not instructions), add source/age/confidence, cap length, scan with the injection scanner. | ⬜ | TASK-3 / 0.37 |
| CDX-8 | **Auto-generated skills are durable behavior** — `skills.auto_generate=true` + `[learn:…]`; ensure human review + sandbox + audit + provenance before a generated skill is reusable. | 🟡 | 0.54 / Track K |
| CDX-9 | **Frontend live-wiring hides shape drift** — `frontend/src/api/live.ts` `@ts-nocheck` + seed fallbacks; add visible LIVE/SEED chips per panel + OpenAPI types, remove `@ts-nocheck` per-module. | 🟡 | H23.16 / AUD-16 / TASK-2 |
| CDX-10 | **`_sys_info()` confident defaults** — returns a default host/GPU when probes fail; a trust/readiness screen should show "unknown", not a possibly-wrong fallback. | ⬜ | H23.11 |
| CDX-11 | **Least-privilege plugins** — several `plugin_gate` entries serve `agents_served=["all"]` incl. external-write surfaces; for the hardened/design-partner profile, scope per-agent using existing agent identity. | ⬜ | 0.45 / Track K |
| CDX-12 | **Hardened profile** — a "Design-Partner / Hardened" preset: guardrails→REDACT/BLOCK on sensitive routes, audit-HMAC required, strict egress on, mutating MCP off by default. | ⬜ | 0.56 / H23.20 |

> **Verified NOT a bug (no action):** interrupt-budget is already wired to the setting
> (`orchestrator.py:265` → `InterruptBudget(per_day=…autonomy.interrupt_budget…)`); the
> `worker.py:27` constant is only the default. The review's "verify this" caveat is satisfied.
>
> **Review's own ranking** (all already tracked — confirms the plan): H23.11 readiness board ·
> H23.18/19 docs · H23.20 onboarding · H23.1 budgets · H23.2 model pinning · HUD live/seed +
> audit-verify surfacing · then **one design-partner proof loop**. Quick wins to bank first:
> **CDX-1/2/3** (a small correctness PR) and **CDX-4/5** (doc/version sync).

---

## 🧪 Hardening audit (2026-06-23 — fresh-eyes review, findings + phased plan)

Two independent fresh-eyes passes (Opus 6-dive + Sonnet 3-agent), merged, de-duplicated
and **source-validated this session**. The codebase is unusually disciplined (real Docker
sandbox, SSRF defense, Fernet/PBKDF2 crypto, ~2,550 meaningful tests); the findings are a
short list of real bugs + a few features that don't fully do what they claim. Full write-up
(38 findings `F1`–`F38` + strengths-to-protect + corrections appendix):
[`docs/research/2026-06-23-independent-audit-merged.md`](docs/research/2026-06-23-independent-audit-merged.md).
Status keys as elsewhere (✅ done · 🟢 in PR · 🟡 partial · ⬜ open). `Fn` = finding id in the report.

**Phase 0 — pre-1.0 / pre-network blockers (exposed surfaces + data-at-rest)**

| # | Item | S | P | AC |
|---|------|---|---|----|
| AUD-0 | **Scope decision (breadth→depth)** — name the 5–6 product-defining features; flag-park the ~44 governed-but-`Null`-railed modules (gates Phase 2). Pairs with H23.23 single-user call. | 2 | DECISION | owner decision recorded in this file |
| AUD-1 | ✅ **done (#309)** — **Secrets at rest** — envelope-encrypt `settings.db` credential columns (`twilio/notion/tuya/gecko/stark_ga4…`) via the existing `SecretStore` (Fernet + pure-Python fallback) at the put/get boundary (`settings_db.SECRET_KEYS` → `_encrypt_if_secret`/`_decrypt_if_secret`); opt-in **encrypted backup archives** (`.tar.gz.enc`, key from `$JARVIS_BACKUP_KEY`/arg, stored outside the data root) in `backup.py` (F2). *Caveats H23.8.* | 5 | **P0** | ✅ `settings.db` dump shows opaque `enc::` token values; an encrypted backup archive is opaque (no plaintext); reads decrypt transparently |
| AUD-2 | ✅ **done (#315)** — **"Forget me" completeness** — forget now also erases the memory subsystem at rest (knowledge graph, entities, decay, embedding cache, conversation transcripts) via `data_purge.purge_data(memory=True)`, clearing the live in-memory stores first so a running orchestrator can't re-persist them; the backup-first snapshot is encrypted once a key is set (AUD-1 #309). *External Qdrant/Neo4j wiping is best-effort via each store's `clear()`.* (F1) | 5 | **P0** | ✅ post-forget the data root holds no memory PII (transcripts/KG/entities/embeddings); `tests/test_data_purge_memory.py` |
| AUD-3 | ✅ **done (#315)** — **HUD XSS + CSP** — HUD dynamic data (`index.html` weather/news/system/history) routed through a local `esc()`; a `_security_headers` middleware adds CSP + `X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy`; Tauri `csp` set (F3). | 3 | **P0** | ✅ a crafted RSS headline renders inert; headers present; `tests/test_hud_security_headers.py` |
| AUD-4 | ✅ **done (#315)** — **WorldView fail-closed** — default `HOST=127.0.0.1`; `assertSafeBind()` aborts boot on a non-loopback bind with an empty `WORLDVIEW_AUTH_SECRET` (F4). *Container hardening (non-root `USER`/`HEALTHCHECK`/`securityContext`/`sslmode`, F14) still open.* | 3 | **P0** | ✅ empty secret on `0.0.0.0` aborts boot; `worldview/backend-api/test/configBootGuard.test.ts` |
| AUD-5 | ✅ **done (#315)** — **Session path-traversal** — shared `validation.is_valid_session_id` enforced in `sessions.py` (route → 400) and at the `memory/persistence.py` boundary (F7). | 1 | **P0** | ✅ `session_id=../../x` → 400; no file escapes the data root; `tests/test_session_traversal.py` |

**Phase 1 — next sprint (correctness + auth lifecycle + CI gates)**

| # | Item | S | P | AC |
|---|------|---|---|----|
| AUD-6 | ✅ **done (#319)** — **Token lifecycle (full-replace)** — the managed `TokenStore` (`security/token_store.py`) is the authoritative credential system: mints `secrets.token_urlsafe(32)`, stores only its SHA-256 (raw token returned once), optional TTL; `verify`/`has_scope` reject expired tokens; `rotate` revokes a scope's prior tokens. The static `JARVIS_*_TOKEN` env vars are now only the **bootstrap** — accepted (constant-time) until a `rotate` supersedes them, after which they're revoked **for good** via a persistent `env_revoked` flag (so adopting a managed token truly replaces the static one). `POST /api/admin/rotate-tokens` (admin-guarded, returns the fresh token once, audited without the value). Offline owner-recovery CLI (`python -m agents.core.security.token_store rotate admin`) → no permanent lockout. *Deferred (F19 tail): httpOnly cookie over `localStorage`, read/write split.* | 3 | P1 | ✅ an expired/rotated token is rejected; the static env token dies after rotation; raw tokens never hit disk (only the SHA-256); `tests/test_token_lifecycle.py` |
| AUD-7 | ✅ **done (#320)** — **SSE + async hot path** — the `/chat/stream` producer is extracted to a module-level `_chat_event_stream` with a `try/finally` that cancels **and awaits** the model-turn task on any exit, incl. a client disconnect mid-stream (Starlette throws `GeneratorExit`) — so a dropped client never leaves the LLM turn running orphaned. `ConversationMemory.add_turn` now does its append-log + full-snapshot disk writes via `asyncio.to_thread` (built under the lock), so the SSE hot path never blocks the event loop; per-turn durability is unchanged (F8, F9). | 3 | P1 | ✅ client disconnect cancels the turn; no full-snapshot write on the event loop; `tests/test_aud7_sse_hotpath.py` |
| AUD-8 | ✅ **done (#318)** — **Settings integrity** — `settings_db.validate_category` checks each admin write against its DEFAULTS schema (type + select allow-list) → the route returns **422** on a bad value before it persists; every accepted write is audited (`SETTINGS_CHANGE`, changed **key names only**, no values) (F10). | 2 | P1 | ✅ bad value → 422; each settings change appears in the audit log; `tests/test_settings_integrity.py` |
| AUD-9 | ✅ **done (#315)** — **Audit chain HMAC** — optional off-box key (`JARVIS_AUDIT_KEY`): keyed rows are HMAC-SHA256 and need the key to verify; a per-row `hash_algo` marker lets a DB spanning the transition still verify; default (no key) keeps SHA-256 (F6). *Caveats H23.5.* | 2 | P1 | ✅ a tampered/forged row fails verification; hmac rows unverifiable without the key; `tests/test_audit_hardening.py` |
| AUD-10 | ✅ **done (#324 · #325 · F34/F35 flip)** — **Supply-chain / CI**. **Done:** every `uses:` across all workflows SHA-pinned (`@<40-hex>  # vX`, Dependabot-tracked, F32); pytest-socket loopback-only guard in `pytest.ini` (`--allow-hosts=127.0.0.1,::1,localhost`) so a stray *real* network call fails fast instead of hanging to the `--timeout` backstop (F37); `.pre-commit-config.yaml` (gitleaks/ruff/hygiene); **blocking gates, baseline-then-block** — ruff lint (`ruff-baseline.toml` freezes 1,654 pre-existing findings via per-file-ignores extended from pyproject; `ci.yml`), bandit SAST over `agents/`+`scripts/` (`.bandit-baseline.json` freezes 123; the 1 HIGH — MD5 file-fingerprint in `oracle_bridge.py` — *fixed* with `usedforsecurity=False`, not frozen), gitleaks secret-scan (`.gitleaks.toml` allowlists 10 known FPs + extends default ruleset) (F34/F35/F36); plus **advisory** semgrep SAST + pip-audit (`security.yml`, continue-on-error). **F33 done:** hash-pinned lockfiles `requirements{,-beta,-dev}.lock` generated by `scripts/lock_deps.sh` (`uv pip compile --generate-hashes --universal --python-version 3.12`); `ci.yml`/`smoke.yml`/`code-health.yml` install with `pip install --require-hashes` across the ubuntu+windows matrix (a tampered artifact aborts the install — proven), and a `Lockfiles` workflow guards source↔lock drift via an embedded `source-sha256` (deterministic — immune to unrelated upstream releases; version refreshes are thirdparty-autoupdate's job). *(The earlier "mirror frozen at numpy 2.4.6" note was a misdiagnosis: the real blocker was the sandbox's local Python 3.11 vs numpy 2.5.0's `requires-python ≥3.12` — uv resolves for a target version regardless.)* **F34/F35 blocking flip (this PR):** semgrep + pip-audit are now **blocking** (`continue-on-error` removed). semgrep — the 9 pre-existing findings were triaged: 2 real (`xml.etree` parsing untrusted RSS/Atom feeds in `digest.py`/`news.py`) **fixed** by switching to `defusedxml` (+ broadened the `except` to swallow its DTD/entity-attack rejections); 7 `logger-credential-leak` **false positives** suppressed at the call site with a named `# nosemgrep` (so the rule still fires on genuinely new code). pip-audit — now audits the **hashed lockfile** (exact resolved versions, not loose constraints); `--ignore-vuln` list intentionally empty (the lock audits clean). **→ AUD-10 complete.** *Extends Dependency-upkeep + SEC-4 + CQ sections.* | 5 | P1 | every `uses:` is a SHA ✅; stray network in tests fails fast ✅; CI fails on a new lint finding / bandit issue / secret ✅; installs are hash-pinned (`--require-hashes`) and a tampered artifact aborts ✅; SAST (semgrep) + dependency-CVE (pip-audit) gates now blocking ✅ |
| AUD-11 | ✅ **done (#315)** — **Sandbox containment tests** — `tests/test_sandbox_isolation.py` runs in the real Docker backend (no-network + read-only FS) via a dedicated `sandbox-isolation` CI lane (`RUN_SANDBOX_ISOLATION=1`) so it can't be skipped away (F5). *Sub-item of H23.17.* | 3 | P1 | ✅ a containment test actually runs and proves isolation |
| AUD-12 | 🟢 **F11+F12 in #324; F13 done #315** — **Injection hardening** — (1) scanner `matched_text` redacted (F13, with AUD-9, #315); (2) **F11 Cypher injection:** node labels / relationship types / property keys constrained to safe Cypher identifiers at the `memory/graph.py` chokepoint + direct `/api/kg/*` writes → 400; (3) **F12 WorldView WKT bounds:** untrusted OSINT coordinates are float-coerced, WGS84 bounds-checked and vertex-capped at the `wkt.py` chokepoint (`wkt_guard.coerce_coord`), the ingestion callers (`context/normalize`, `ew/gpsjam`) drop an out-of-bounds feature with a WARNING, + a defence-in-depth `geom_wkt` validator on `TelemetryEnvelope`. **→ AUD-12 complete on #324 merge.** | 3 | P1 | ✅ a flagged secret never lands in `audit.db`; a Cypher label/rel/key injection → coerced/400; an out-of-range / NaN / oversized coordinate → `WktBoundsError` and the feature is dropped (never emitted); `tests/test_kg_cypher_allowlist.py`, `worldview/.../tests/test_wkt_bounds.py` |

**Phase 2 — post-1.0 (structure, observability, scale, DX)**

| # | Item | S | P | AC |
|---|------|---|---|----|
| AUD-13 | **Turn-pipeline de-dup + service container** — one `PromptBuilder` + `_preprocess_turn`; extract context/dispatch/persist; retire `orch` back-refs + `sys.modules` indirection (A1). *Continues CLN-2.* | 8 | P2 | prompt assembly lives in one place; collaborators take narrow interfaces |
| AUD-14 | **Config consolidation** — one `Config` read once at boot (collapse 121 env reads / 3 bool conventions; centralize model names); derive agent-policy sets from `agents.yaml` (A3, F29). | 3 | P2 | a model swap is one edit; one truthy convention |
| AUD-15 | **Client consolidation** — retire HUD v1, make v2 the Tauri target, extract a shared `@jarvis/client` (auth+SSE+fetch + timeouts); remove `@ts-nocheck`, move toward `strict` (A2, F17, F26). | 8 | P2 | one client lib across surfaces; v1 gone; fetches time out |
| AUD-16 | **Type-safety codegen** — `response_model=` on routes → `openapi-typescript` generated types + CI diff gate (F18). | 3 | P2 | a backend field change fails the TS diff check |
| AUD-17 | ✅ **done** — Prometheus `GET /metrics` golden signals (RED): `jarvis_http_requests_total` (rate, by method/route-template/status), `jarvis_http_request_duration_seconds` summary (p50/p95/p99 + sum/count), `jarvis_http_errors_total` (5xx), `jarvis_http_requests_in_flight` gauge — recorded by a `_golden_signals` middleware in `web.py`, dependency-free exposition in `observability/http_metrics.py` (route-**template** labels → bounded cardinality; reuses `north_star._percentile`). Scrape is unauth + rate-limit-bypassed like the probes. Real-path **concurrency/p95 test** drives 60 concurrent requests, asserts p95 under budget with no in-flight leak. (F16, F23) | 3 | P2 | `/metrics` exposes http/latency/error; load test asserts p95 on the real HTTP path |
| AUD-18 | **Scale & DX polish** — Qdrant-by-default at scale; lazy plugin instantiation; Vite code-split; configurable scanner patterns; LLM retry/backoff via the existing `@resilient_call`; close leaked httpx clients; CORS/loaders polish (F20–F25, F27, F28, F30, F31). | 5 | P2 | recall indexed by default; transient LLM 503 retries; no client leak |

---

## Scalability: index hot/unbounded SQLite tables (shipped — PR #199)

Behavior-preserving index pass on the four tables that are read on hot paths
while growing without bound — keeps those lookups O(log n) instead of degrading
to full scans at scale. All are `CREATE INDEX IF NOT EXISTS` in the init path,
so existing DBs gain them on the next startup; results are identical, only faster.

- `tasks(status, id)` — autonomy worker/inbox poll `runnable()`/`list()`/`pending_decisions()` by status.
- `security_events(event_type, timestamp)` — audit `query()`; one row per turn (fastest-growing table).
- `preferences(agent, kind, risk_tier)` — `approval_rate()` on the autonomy decision path.
- `sessions(started_at)` — `list_sessions()` ordered scan.

Guarded by `tests/test_db_indexes.py` (+5): each index must exist **and** be used
by its hot query (asserted via `EXPLAIN QUERY PLAN`), so a future schema change
that silently regresses to a full scan fails CI. Audit pre-work confirmed WAL is
already set on every store and there are no blocking-I/O calls in async paths
(repo-wide AST scan), so no further safe wins remained in those categories.

## LM Studio control + model honesty (shipped — PR #133)

Chat + admin control of the local LLM backend (`lms server start` / `load` / `unload`),
the live model reported truthfully (runtime-state injection + SOUL fix), and the
chain-of-thought leak / mid-sentence truncation fixed. Kill-switch:
`JARVIS_LMSTUDIO_CONTROL` / `llm.control_enabled` (chat-only: `JARVIS_LMSTUDIO_CHAT_CONTROL`
/ `llm.chat_control`). Docs + troubleshooting: `docs/ARCHITECTURE.md` §5.

**Follow-ups (P2):**
- Validate end-to-end against a real `lms` binary on the RTX 5090 box — current tests are mock-only.
- ✅ Fuzzy model resolution: "load gemma" → resolves to the full id via `/v1/models` before `lms load`
  (`LMStudioController._resolve_model`). Unique match loads (reply names the resolved id); several
  matches → `ambiguous` + candidates (chat asks which / admin returns 409); list unreachable → literal
  passthrough. Admin `/api/llm/load` persists the resolved id. +13 tests.
- ✅ Surface the kill-switch toggles + a model picker as real controls in the admin Settings UI —
  `llm.control_enabled` / `llm.chat_control` toggles + live model picker (`ModelPickerRow`, kind
  `model-select`), and a live controller-status card backed by new admin-guarded `GET /api/llm/status`
  → `{online, enabled, server_url, active_model}` (`LMStudioStatusRow` in `admin.js`). +Python +JS tests.
- Confirm the LM Studio id for Gemma 4 12B — `google/gemma-4-12b` is a placeholder in static config.

---

## Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H1–H4 + Sprint 0 + Cross-cutting + Sec + Bugs** | 67 | **67** | 248 | **248** | **100%** |
| **H5 Next Wave** (P2–P3) | 17 | **17** | 128 | **128** | **100%** |
| **H6 Jarvis Autonom** (P1) | 7 | **7** | 60 | **60** | **100%** |
| **H7 Perf Cale Fierbinte** (P1–P2) | 5 | **5** | 16 | **16** | **100%** |
| **H7 Hardening & Release Readiness** (P0–P2) | 11 | **11** | 51 | **51** | **100%** |
| **H8 Memorie Personală** (P1–P3) | 7 | **7** | 48 | **48** | **100%** |
| **H9 Agent Ops: Workflows & Observability** (P2) | 3 | **3** | 29 | **29** | **100%** |
| **H10 Competitive Edge** (P1–P3) | 30 | **30** | 188 | **186** | **99%** |
| **H11 Platform Parity** (Known Gaps, P3) | 4 | **4** | 55 | **55** | **100%** |
| **Total H1–H11** | **151** | **151** | **823** | **821** | **100%** (SP) |
| **H12 Asistent Privat & Proactiv** (P0–P3) | 25 | **24** | 150 | **142** | **95%** |
| **H13–H17 Frontiere Noi** (post-paritate, în scope v1.0, P1–P3) | 20 | **19** | 146 | **141** | **97%** |
| **Total H1–H17 = scope 1.0.0** | **196** | **194** | **1119** | **1104** | **99%** (SP) |
| **H18 Mobile Native & Browser Parity** (P2–P3) | 10 | **9** | 32 | **32** | **94%** |
| **H19 WorldView (4D OSINT)** — standalone product, merged 2026-06-08 | 33 | **33** | 208 | **208** | **100%** ✅ |

> `%` = procent pe **story points**. Sub-total **H1–H11** = 821/823 (≈100% SP; 151/151 iteme). Grand-total **H1–H17** = 1104/1119 (≈99% SP; 194/196 iteme). **Toate orizonturile de features sunt livrate = v0.10.0** (H18 mobil 9/10 + H19 WorldView 33/33 standalone — livrate). **Nu mai există un "audit gate" ca versiune**; restul drumului până la 1.0 e *productionizarea* (vezi **H23** + roadmap-ul de versiuni mai sus), iar **1.0 = totul livrat + validat de useri reali (design partners)**.

**În afara totalului:** **Bugs & Hot Fixes** — **toate BUG-\* și HF-\* rezolvate** (BUG-1…17 + HF-1…7 + NTH-1; vezi re-baseline 2026-06-08 + tabelul de mai jos). ✅ **CLN-3 livrat + CLN-2 substanțial livrat (#293/#296, v0.11.0)** — `web.py` 4636→1282 LOC (45 routere, 9 rute inline), `orchestrator.py` 1620→1456 LOC; suprafața de rute byte-identică, parity-guarded. Rămân deschise: taskuri netrackuite ca buguri (**TASK-1** Howard backend, **TASK-2** HUD v2 depth, **TASK-3** taint-tracking canale, **BUG-2b** frontend E2E). *(Detalii audit cod 2026-06-04 în tabel.)*

**Test count (backend pytest):** ~2,802 passed, 6 skipped (2 xfailed) — skip-urile sunt teste gated pe Docker/wasmtime (sandbox isolation) + heartbeat-ul opțional, absente în CI fără backend de sandbox. *(2026-06-09: backlog software **code-complete** — H10 30/30, H11 4/4, H12 24/25, frontiere H13–H17 19/20 (vezi „Status General" de mai sus); + WorldView O19 33/33 merged + Argus. Rămâne audit + testare manuală, vezi `docs/AUDIT.md`.)*
**Frontend (BUG-2):** 184 teste JS / 23 fișiere · ~67% line coverage — separat de suita pytest.
**Observability (MOONSHOT §6):** north-star + counter-metrics (accepted/active user, interrupt rate, reject rate, %-local, p95) sunt acum calculate într-un singur loc (`agents/core/observability/north_star.py`) și expuse la `GET /api/metrics/north-star` — vezi [docs/METRICS.md](docs/METRICS.md).

> **Orizont 7 Hardening — Drumul spre 1.0.0:** 11/11 COMPLET ✅ (livrat 2026-06-02)

---

## ✅ ORIZONT 7 — Drumul spre 1.0.0 (Hardening, Release Readiness & Observability) — 11/11 COMPLET

> Backlog-ul de features e la 100% (H1–H6). Faza spre **1.0.0 stable** nu adaugă scope orizontal —
> face produsul **de încredere, testabil, documentat și măsurabil**. Bazat pe auditul multi-agent
> 2026-06-01 (docs/release, CI/hermeticitate, calitate cod, scoping features) + `docs/gap-analysis-1.0.md`.
>
> **Design complet:** `docs/superpowers/specs/2026-06-01-horizon7-road-to-1.0-design.md`
> **Constatări-cheie:** `pytest tests/` atârnă >18 min offline (Oracle GitHub watcher la lifespan);
> CI rulează doar pe push/Windows (nu pe PR-uri); ~44 `except: pass` în security/autonomy;
> docs se contrazic (README „181" vs „39" teste; port 8000↔8080; model 26b↔31b; „15" vs 16 agenți;
> fără LICENSE/CONTRIBUTING).

### Track A — Test Hermeticity & CI/CD (P0, blochează restul)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.1 ✅ | **Suită de teste hermetică** — gate watchers/canale externe pe `JARVIS_TESTING`; `conftest` autouse (env + socket guard); `pytest-timeout` în pytest.ini; TestClient module-level → fixtures function-scoped (`test_cognition_api/test_tts/test_systems_api/test_resilience_integration`) | 5 | P0 | — | `pytest tests/` rulează offline, verde, <90s, fără hang; apel real de rețea → eșec imediat |
| H7.2 ✅ | **CI/CD pentru 1.0** — trigger `pull_request`; matrix `ubuntu+windows`; `ruff` + `mypy` (non-blocking) + `pytest-cov`; healthcheck robust (poll, nu sleep) | 5 | P0 | H7.1 | fiecare PR rulează CI pe Linux+Windows cu lint+teste+coverage |

### Track B — Code Hardening (P1)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.3 ✅ | **Client HTTP centralizat + retry/circuit-breaker** — `PluginHTTPClient` (timeouts coerente, `@resilient_call` H5.5, pooling); migrează 14+ pluginuri | 8 | P1 | H5.5 | un singur client/policy; metrici reziliență per plugin |
| H7.4 ✅ | **SQLite thread-safety & igienă conexiuni** — `check_same_thread=False` + lock pe checkpoint/settings_db/queue/preferences; WAL consistent | 5 | P1 | — | acces concurent sigur; `test_load.py` fără erori de thread/corupere |
| H7.5 ✅ | **Validare input pe endpoint-uri** — limite Pydantic: message len, `limit` bounds, `task_id` numeric, sandbox code size | 3 | P1 | — | input invalid/oversize → 422, fără OOM/DoS |
| H7.6 ✅ | **Curățare excepții înghițite silențios** — `except: pass`/`return None` orbe din log/channels/autonomy/security → logging structurat + fallback explicit | 5 | P1 | — | nicio cădere silențioasă în security/autonomy; fiecare logată cu context |
| H7.7 ✅ | **Elimină date mock/dummy înșelătoare** — `/tasks` dummy tasks (web.py); flag transparent pe iot_control mock | 2 | P1 | — | UI nu primește date false ne-marcate |

### Track C — Docs & Release Hygiene (P1)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.8 ✅ | **Adevăr în documentație** — single source of truth versiune (`agents/__init__.py` + `/status`); reparat test counts, versiune, port, model, agent count, endpoint count | 3 | P1 | — | zero contradicții cross-doc; CI verifică versiunea unică |
| H7.9 ✅ | **Onboarding & release** — `LICENSE`, `CONTRIBUTING.md`, quickstart Linux/Mac, `docker-compose.yml` (server+Qdrant+Neo4j+n8n), README badges+screenshot, release workflow (tag→Release) | 5 | P1 | H7.2 | dev nou rulează în <10 min pe Linux/Mac; tag → GitHub Release |

### Track D — Observability & Product Polish (P2, câștiguri rapide high-ROI)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.10 ✅ | **Cost & Usage Analytics** — preț per model + agregare tokens/cost per agent (local vs cloud) + burn lunar; `GET /api/analytics/cost` + tab HUD | 5 | P2 | H5.5 | dashboard arată cost/agent + proiecție lunară din date reale |
| H7.11 ✅ | **Activare Learning-Loop (auto promote/demote)** — job periodic care propune evoluția agenților prin decision inbox (reversibil, gated). **Done 2026-06-03:** `core/learning/scheduler.py` `propose_promotions` — rulează `suggest_promotions`, enqueue propuneri gated (kind `agent_promotion`, `autonomy_level="ask"`, `origin="generated"`, risk_tier 2) în `TaskQueue`, idempotent (skip dacă există deja propunere deschisă/agent activ); job APScheduler `_schedule_learning_loop` (cadență `autonomy.learning_loop_interval_hours`, default 168h=săptămânal) + trigger manual admin `POST /api/learning/propose`. +6 teste (enqueue gated, idempotent, sub-threshold, deja-activ, componente lipsă, endpoint). | 5 | P2 | H3.4, H6.5 | după N interacțiuni → propunere în inbox; aprobarea activează agentul |

> **Total Orizont 7:** ~51 SP. **Secvențiere:** H7.1 → H7.2 → (Track B ∥ Track C) → Track D.
> **Stretch → Orizont 8 (post-1.0):** voice clone (XTTS), Howard fine-tuning, multi-user/family,
> mobile offline voice, n8n NLU→workflow, desktop Tauri, advanced guardrails DSL, eval/regression harness.

---

## ✅ ORIZONT 6 — Jarvis Autonom / Proactive Cortex (P1) — 7/7 COMPLET

> Viziune: Jarvis își găsește singur de lucru, lucrează continuu, îmi scrie pe telefon (Telegram)
> doar când are nevoie de o decizie, și susține un review zilnic de 10–30 min (morning brief + evening retro).
> Autonomia crește în timp pe măsură ce învață ce aprob.
>
> **Design:** `docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md`
> **Research (cu surse):** `docs/research/2026-05-31-autonomous-proactive-agents.md`
> **Politică implicită:** ECHILIBRAT — act autonom pe reversibil/sigur (research, drafturi, organizare);
> aprobare pe ireversibil sau bani. **Buget întreruperi: ≤4 push-uri urgente/zi**, restul în review.
> **Principiu:** ambient agent (trigger → coadă → gating → inbox), NU auto-prompt loop (anti-AutoGPT).

| # | Item | S | Dep | AC |
|---|------|---|-----|----|
| H6.1 ✅ | **Autonomy Loop & Self-Tasking Queue** — coadă SQLite cu state-machine (`proposed→approved→running→done\|failed\|blocked`), worker pe loop, retry cap 3, 2 cozi manual/generated. `core/autonomy/queue.py` + `worker.py`, endpoints `/autonomy/*` | 13 | H3.5 | ✅ task trece prin tot ciclul; eșec ×3 → `failed`, nu reintră |
| H6.2 ✅ | **Decision Inbox pe Telegram** — card cu butoane inline Aprob/Editez/Resping/Amân pe task-uri blocate; buget ≤4 push/zi; rest în batch. `core/autonomy/inbox.py` + callback în `channels/telegram.py` | 8 | H6.1, H1.2 | ✅ task money/ireversibil → push cu 4 butoane → „Aprob" → running |
| H6.3 ✅ | **Risk Gate & Autonomy Dial** — `policy.py`: 4 tiers (read_only/reversible/external/irreversible_or_money) + scoring (reversibility, blast_radius, signal_quality, time_sensitivity); cap/ceiling bani | 8 | H6.1, H4.9 | ✅ reversibil → act fără întrebare; money peste cap → ask |
| H6.4 ✅ | **Daily Review Ritual** — morning brief 07:00 + evening retro 20:00 (cron), batch list; endpoint `/autonomy/brief`. `core/autonomy/digest.py` | 8 | H6.1, H3.5 | ✅ digest construit din coadă, trimis pe Telegram, expus în HUD |
| H6.5 ✅ | **Preference Learning & Decision Journal** — scor approve/reject per (agent,kind,tier), `suggest_autonomy_raise` (doar tier 1–2), jurnal JSONL append-only. `core/autonomy/preferences.py` + endpoint `/autonomy/preferences/suggestions` | 13 | H6.1, H3.4 | ✅ după N aprobări reversibile → sugerează ridicarea autonomiei |
| H6.6 ✅ | **Night Shift** — fereastră wrap-midnight; `tick(max_tier=1)` rulează batch doar reversibil/read-only. `worker.is_night_window` + filtru `queue.runnable(max_tier)` | 5 | H6.1, H6.3 | ✅ noaptea rulează doar muncă reversibilă; extern/ireversibil așteaptă |
| H6.7 ✅ | **Proactive OS Observer** (trigger layer) — `core/autonomy/observer.py`: eșantionează resurse (CPU/RAM/disk via psutil) + liveness servicii (TCP), **debounce pe schimbare de stare**, injectează în coada existentă (alertă→READ_ONLY auto-act, vizibilă în HUD/brief; remediere→tier-3 ASK→decision inbox). Probe injectabile (offline-testable). Endpoints `/autonomy/observer[/run]`. | 5 | H6.1, H6.3 | ✅ serviciu căzut → card „restart?" în inbox **o singură dată**; resursă în prag → alertă în brief |

> **ORIZONT 6 COMPLET ✅** (2026-05-31/06-01) — H6.1–H6.7 livrate. Detalii de livrare: [docs/HISTORY.md](docs/HISTORY.md).

---

> **Runtime diagnostics** (auto-generated from `problems.jsonl`) now live in the
> git-ignored `memory_logs/diagnostics.md` — they are **no longer written into this
> tracked file** (that caused recurring `git pull` conflicts; see BUG-4).

## 🐛 Bugs & Hot Fixes

> Buguri cunoscute + taskuri „orfane" (amânate/abandonate prin alte docs/note, fără item trackuit).
> Audit 2026-06-02: am promovat aici follow-up-urile care altfel cădeau de pe radar.
> Audit cod 2026-06-04 (orchestrare + memorie/autonomie + securitate): adăugate BUG-5…BUG-12,
> HF-3…HF-7, CLN-2/CLN-3. Caveat transversal: majoritatea au risc **scăzut pe deployment
> single-user/LAN** (designul actual) și devin reale sub concurență / expunere non-LAN.

> **Re-baseline 2026-06-08** (audit de cod + connectivity, verificat vs cod curent):
> - **Deja fixate în cod** (rândurile de mai jos sunt istorice): **BUG-3** (un singur `/api/analytics/cost`),
>   **BUG-6** (reload atomic prin rebind), **BUG-8** (parsing cu guard), **BUG-9** (allowlist alfanumeric),
>   **BUG-10** (reset zilnic programat la miezul nopții), **HF-6** (sandbox Docker-only by default), **HF-7**
>   (guard admin fail-closed în spatele proxy-ului).
> - **Fixate în pasul de hardening 2026-06-08:** **BUG-7/NEW-1** (`orch.aclose()` cablat în shutdown, toate
>   backendurile LLM + mcp + queue închise), **BUG-11** (re-gating complet pe payload-ul editat, nu doar `amount`),
>   **BUG-12** (lock pe `_PROC_CACHE` + atomicitate `_spent_today`) + **2 bug-uri noi**: `Orchestrator.process()`
>   lipsea dar era apelat (taskuri autonomy LLM + reflecția nocturnă întorceau gol — acum implementat, fail-safe)
>   și euristica greșită de eroare din `_record_interactions` (marcase răspunsuri reușite ca eșec).
> - **Fixate în pasul de completare HUD 2026-06-08:** **BUG-5** (session_id izolat per context async via
>   `contextvars.ContextVar` — chat-uri concurente nu mai amestecă conversații; test de concurență), **HF-3**
>   (scanner întărit: openai-key 40+, GCP/Azure SA, heuristică entropie; `db_connection_string`/`password`
>   restrânse). **Toate BUG-* și HF-* sunt acum rezolvate.**
> - **Rămâne deschis (deliberat, NU bug-uri):** **CLN-2/CLN-3** (refactor god-objects `orchestrator.py`/`web.py`
>   — P3, churn mare; amânat intenționat ca să nu destabilizeze înainte de testarea manuală). Restul backlog-ului
>   = orizonturi de produs (H10.30, H11, H12 Track E, H13, H15, O20, O21), nu loose-ends — vezi
>   [`docs/2026-06-08-future-developments-report.md`](docs/2026-06-08-future-developments-report.md).

### Buguri

| # | Bug | Severity | Notes |
|---|-----|----------|-------|
| ~~BUG-14~~ ✅ | **Frigga (strict-local) putea ajunge în cloud** — `select_backend` la `policy=local` cădea pe Gemini (`cloud-fallback`) când backend-ul local era jos, iar testul `test_select_backend_cloud_only_policy_local_fallback` consacra comportamentul. Încălca direct principiul non-negociabil #1 (MOONSHOT §5.1 / AGENTS.md: „niciun fallback cloud"). **Fixed 2026-06-10:** `policy=local` e **fail-closed** (RuntimeError explicit, fără fallback); test rescris `test_select_backend_strict_local_never_cloud` + `test_registry_cannot_override_local_only`. Bonus: `get_agent_policy` onorează acum `llm_policy` din `agents.yaml` (registrul canonic) cu podea de securitate `LOCAL_ONLY_AGENTS` — repară și drift-ul Argus (yaml `claude`, cod `auto`). | ~~**CRITICAL** (privacy)~~ | Găsit la dogfooding-ul AI_CONTEXT 2026-06-10 — citirea ARCHITECTURE §5 contra codului |
| ~~BUG-15~~ ✅ | **Howard (strict-local) putea ajunge în cloud** — `_select_howard_backend` scurtcircuitează ÎNAINTE de gate-ul de policy, iar ultimul fallback era Gemini (`cloud-fallback`) — pentru digital twin-ul LOCAL_ONLY cu arhiva de conversații. Fratele lui BUG-14, ratat de fixul inițial pentru că special-case-ul stă deasupra gate-ului. **Fixed 2026-06-10:** fail-closed + test `test_howard_strict_local_never_cloud`. | ~~**CRITICAL** (privacy)~~ | Audit governance 2026-06-10 (pass 2, aceeași metodă ca BUG-14) |
| ~~BUG-16~~ ✅ | **`llm.cloud_fallback` era un knob mort** — setarea de privacy din /admin (`never|on-demand|always`) era definită + afișată în UI dar necitită de NIMIC; "never" nu oprea nimic. **Fixed 2026-06-10:** onorat live în `HybridRouter` (never = agenții auto rămân local și pe prompturi mari; always = preferă cloud; on-demand = comportamentul anterior), re-sincronizat ≤30s de settings watcher. +6 teste. | ~~HIGH (privacy)~~ | Audit governance 2026-06-10 |
| ~~BUG-17~~ ✅ | **Lanțul Merkle de audit nu era verificat niciodată** — `AuditLogger.verify_chain()` exista cu zero apelanți (niciun endpoint, niciun test): "tamper-evident" fără verificarea probelor. **Fixed 2026-06-10:** `GET /api/security/audit/verify` ({valid, first_invalid_id, entries}) + teste unitare care demonstrează detectarea tamper-ului și a re-link-ului. Suprafața HUD: în coada TASK-2. | ~~MEDIUM (trust)~~ | Audit governance 2026-06-10 |
| ~~BUG-1~~ ✅ | `_dashboard_cache` module-level dict has no `asyncio.Lock` — concurrent `/dashboard` requests can race on the weather/calendar cache update, producing a double-fetch or partial write under high load. **Fixed 2026-06-02:** `_dashboard_lock = asyncio.Lock()` guards both refresh blocks with double-checked locking; weather block now also sets `cached_at` (was refetching every request). +1 regression test (`test_dashboard_concurrent_refresh_fetches_weather_once`). | ~~LOW~~ | Found during HUD test sprint 2026-06-02 |
| BUG-2 ✅ | ~~Frontend test infrastructure missing — 0% coverage on React HUD (~5 000 LOC).~~ **Done 2026-06-02:** Vitest + JSDOM harness (`tests/frontend/`) that loads the real shipped global scripts (vendored React 18 UMD + static files) — no bundler/build step. **156 tests / 20 spec files · ~66% measured line coverage (target 60% met)**, gated in CI (`frontend` job runs `npm run test:coverage`, fails under 60%). Coverage of the in-JSDOM scripts is measured via istanbul pre-instrumentation + nyc (see `coverage.mjs`) with a badge (`coverage-badge.svg`). Covers all of `components.js`, `i18n.js`, `data.js`, `cognition.js`, `dossier-modal.js`, `network.js`, `enhancements.js`, `observability.js`; `admin.js` (full `AdminApp` mount + nav sweep + save flow); `systems.js`/`workflows.js`/`observability.js` panels (mount + tab sweep); and `app.js` incl. the **P1 chat flow** (send→SSE stream→render) and **P2 polling** intervals. Plan alignment per `docs/plan-bug2-frontend-tests.md`: runner = Vitest (chosen over Jest), measured coverage ✅, P1 Chat ✅, P2 polling ✅. **Caught a real shipped bug on first run:** `systems.js` `ResilienceTab` missing closing brace → the entire Systems panel failed to parse/load in the browser (present on `main`); fixed + regression-guarded (`resilience.test.js`). **Deferred (P3 follow-up):** voice/`useTTS`, Workflow drag-drop pointer events, and browser E2E (Playwright). See `tests/frontend/README.md`. | ~~MEDIUM~~ | Identified in test coverage audit 2026-06-02; backend gap closed (121 tests added on branch `claude/hud-human-interface-testing-r8IQS`) |
| ~~BUG-3~~ ✅ | `/api/analytics/cost` era definit de **două ori** în `agents/web.py` (~1716 și ~2081), a doua umbrind-o pe prima. **Fixed (confirmat în cod 2026-06-19):** duplicatul a dispărut odată cu extragerea de routere CLN-3 — o singură definiție acum în `agents/core/routers/analytics.py:28`; gardat de testele route-parity/OpenAPI (o rută duplicată ar pica CI). | ~~MEDIUM~~ | Găsit la auditul de doc-truth 2026-06-02 |
| ~~BUG-5~~ ✅ | **Race pe `self.session_id`** — handler-ul de canal salvează/restaurează `self.session_id` pe instanța *partajată* a orchestratorului în jurul unui `await handle_input`. Două cereri concurente pe canale diferite puteau suprascrie reciproc `session_id` înainte de blocul `finally` → **un răspuns putea ajunge în conversația greșită**. **Fixed 2026-06-08** (confirmat în cod 2026-06-09): `session_id` e acum **async-context-local** via `contextvars.ContextVar` (`_active_session` în `agents/core/orchestrator.py`) — `session_id` e o proprietate care citește din ContextVar (fallback la `_session_id_default` partajat pt. boot/checkpoint/autonomie), iar `_resolve_session()` setează contextul per-cerere; **nicio mutație pe instanța partajată**. Test de concurență inclus. Cel mai impactant bug găsit la audit. | ~~HIGH~~ (sub concurență; LOW single-user) | Audit cod 2026-06-04 |
| ~~BUG-6~~ ✅ | **Reload non-atomic `_runtime_settings`** — loop-ul de fundal reconstruia dict-ul fără atomic-swap; un reader concurent putea vedea stare parțială. **Fixed (confirmat în cod 2026-06-19):** `load_runtime_settings()` (`agents/core/orchestrator.py:509-516`) construiește un dict `flat` local **apoi** îl **rebind-uiește atomic** (`self._runtime_settings = flat`) — un reader vede ori dict-ul vechi, ori cel nou, niciodată parțial (nicio mutație in-place). | ~~LOW~~ | Audit cod 2026-06-04 |
| ~~BUG-7~~ ✅ | **Leak `httpx.AsyncClient`** — backend-urile LLM creau clientul în `__init__` fără `aclose()` → connection pools rămase deschise. **Fixed (confirmat în cod 2026-06-19):** fiecare backend expune acum `aclose()` (LMStudio/Ollama `base.py:214`,`:339`; Claude/Gemini/OpenRouter/VLM), cascadat prin `LLMRouter.aclose`→`HybridRouter.aclose`→`Orchestrator.aclose` (`orchestrator.py:1608`)→shutdown-ul lifespan (`web.py:295`). Teste: `tests/test_hybrid_router.py:44-64`. *(Nit cosmetic rămas: `GeminiBackend` expune `close()` vs. `aclose()` la peers — inofensiv, `_close_backend` acceptă ambele.)* | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| ~~BUG-8~~ ✅ | **Parsing fragil în `_detect_handoff`/`_detect_skill`** — `]` lipsă ducea la EOF over-read / `ValueError`. **Fixed (confirmat în cod 2026-06-19):** `_detect_handoff` (`agents/core/orchestrator.py:1148-1156`) folosește `end = resp.index("]", start) if "]" in resp[start:] else len(resp)` (guard explicit), iar `_detect_skill_learning` (`:1158-1178`) împachetează `resp.index("]")` într-un `try/except (ValueError, IndexError): continue` — niciun over-read negardat, nicio excepție nepriinsă. | ~~LOW~~ | Audit cod 2026-06-04 |
| ~~BUG-9~~ ✅ | **Path-traversal în `promote_bench_agent`** — scria `SOUL.md` dintr-un `bench_id` nevalidat; un id cu `../` putea scrie în afara `agents/`. **Fixed (confirmat în cod 2026-06-19):** `promote_bench_agent` (`agents/core/orchestrator.py:1422-1425`, `# BUG-9 hardening`) respinge orice `bench_id` care nu e alfanumeric (`bench_id.replace("_","").replace("-","").isalnum()`) înainte de a-l folosi ca segment de cale → niciun `../` posibil. | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| ~~BUG-10~~ ✅ | **Buget zilnic de cheltuieli neresetat** — `reset_daily()` exista dar nu era apelat în producție → `daily_ceiling` se umplea permanent până la restart. **Fixed (confirmat în cod 2026-06-19):** `SchedulerService.schedule_daily_budget_reset()` (`agents/core/scheduler_service.py:55-71`) înregistrează un job APScheduler `cron hour=0 minute=0` care apelează `policy.reset_daily`, cablat din `schedule_all()` (`:37`) la pornire. Test: `tests/test_autonomy_policy.py:82`. | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| ~~BUG-11~~ ✅ | **Task editat-după-block sărea peste re-gating** — un edit (ex. „$100"→„$300") se executa sub decizia veche de risc = escaladare de privilegii. **Fixed (confirmat în cod 2026-06-19):** `apply_decision(action="edit")` (`agents/core/autonomy/worker.py:169-219`) re-rulează `policy.decide()` pe payload-ul **complet** editat (`{"kind": ..., **payload}`, nu doar suma) și **păstrează task-ul BLOCKED** (re-push card) dacă rezultatul e ASK, înainte de orice tranziție la APPROVED. Teste: `tests/test_autonomy_worker.py:145-183` (`test_edit_to_irreversible_stays_blocked`, `test_edit_over_cap_reblocks`). | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| BUG-12 🟡 | **Thread-safety reziduală (low)** — **Parțial închis (2026-06-19):** incrementul `AutonomyPolicy._spent_today += …` e acum gardat de `_spend_lock` (`agents/core/autonomy/policy.py`, read-modify-write + citirea ceiling-ului din `decide`). **Rămâne (LOW):** `Embedder._PROC_CACHE` (LRU in-proc) și `InMemoryVectorStore` mutate fără lock propriu (se bazează pe `MemoryManager._lock`). Risc real scăzut (GIL + un singur worker azi), fragil doar cu workeri paraleli. | LOW | Audit cod 2026-06-04 |
| ~~BUG-13~~ ✅ | **Skill import din `hermes` complet rupt vs. repo-ul real** — `agents/core/skills/importer.py` cerea `main/skills/<nume>/manifest.{json,yaml}` (layout plat), dar `NousResearch/hermes-agent` (real, MIT, ~185.7k★, activ) folosește `skills/<categorie>/<skill>/SKILL.md` cu **YAML frontmatter** (standardul agentskills.io) → `import_from_hermes()` dădea 404 pe **fiecare** skill și întorcea `False`. Al doilea defect (local): `_save_skill` scria `manifest.json` dar `loader.py` descoperă **doar** `SKILL.md` → chiar și un import reușit nu se încărca niciodată. **Fixed 2026-06-07** (research: [docs/research/2026-06-07-hermes-agent.md](docs/research/2026-06-07-hermes-agent.md)): importer rescris să localizeze skill-ul în arborele git recursiv (`…/<slug>/SKILL.md`, suportă nesting pe categorii + layout plat + fallback legacy `manifest.*`) și să salveze **`SKILL.md` verbatim** (+ sidecar `manifest.json` doar pt. provenance/`list_imported`); `loader._parse_manifest` învățat să parseze frontmatter YAML (`requires_toolsets`→`requires`, comenzi din body) cu fallback la dialectul Markdown-heading existent. +8 teste offline (httpx mock: frontmatter, nested-tree import, skill importat e loader-discoverable, list_imported, missing→False) în `tests/test_hermes_import.py`. Suita skill (172 teste) verde. **Verificare live restantă:** căile de fetch sunt acoperite doar cu httpx **mock** (sandbox fără rețea); rămâne un smoke-test real (`DEV_MODE=1` → `import_from_hermes("github-issues")` pe GitHub real) înainte de a fi confirmat în producție. | ~~HIGH~~ (feature mort; LOW expunere — gated `DEV_MODE`) | Găsit la research-ul Hermes 2026-06-07 |
| ~~BUG-4~~ ✅ | Aplicația scria în `BACKLOG.md` la fiecare autonomy tick (`sync_problems_to_backlog`, setare `error_backlog_sync_enabled` default ON) → modifica fișierul **trackuit** pe disc (pe Windows flip-uia și LF→CRLF pe tot fișierul) → orice `git pull` ulterior **conflicta pe BACKLOG.md**. Cauza reală a conflictelor recurente. **Fixed 2026-06-02:** redirectat către `memory_logs/diagnostics.md` (gitignored) cu scriere idempotentă + LF pinned; scos blocul auto din BACKLOG; `.gitattributes` `eol=lf`; reparat `UPDATE.bat` (`origin master` → `origin main`). | ~~HIGH~~ | Diagnosticat din simptomul „conflict pe backlog la pornirea pe laptop" |

### Hot fixes & taskuri orfane (promovate 2026-06-02)

> Coloana **Dep / secvențiere** spune *când* să fie rezolvat eficient — multe au sens doar
> împreună cu un feature viitor (ca să nu se scrie de două ori).

| # | Item | Tip · P | S | Dep / secvențiere | Sursă |
|---|------|---------|---|-------------------|-------|
| **HF-1** | **Auth pe rutele user-facing `/api/`** — `/chat`, `/chat/stream`, `/api/memory/*` (inclusiv POST `/api/memory/remember`) **nu aveau autentificare**; doar rutele admin erau gate-uite. **→ ✅ Rezolvat:** `_user_guard` (JARVIS_USER_TOKEN / `X-User-Token`, admin-token superset, localhost-default + fail-closed în spatele unui proxy ca HF-7) pe ~32 rute user-facing (chat, memorie, notes, rooms, sessions/tasks, `/sandbox/execute`, `/skills/import`); HUD atașează tokenul automat (`auth.js`, prompt-on-401). Tot prereq pentru **H10.E Multi-user**. | ✅ **DONE** | 5 | — | `agents/web.py:_user_guard` · `tests/test_user_guard_hf1.py` |
| **HF-2** | **Security review pre-go-live** — pen-test pe endpointuri, **CORS** config, review rate-limit. **→ ✅ Cod livrat:** middleware **per-IP rate-limit** (`JARVIS_RATE_LIMIT`, localhost + token-valid exempt, 429 + Retry-After) ca defense-in-depth peste auth HF-1 / limita per-canal din gateway; **CORS knob** opt-in (`JARVIS_CORS_ORIGINS`, default same-origin, neschimbat). *Pen-test-ul manual rămâne ca gate uman în* `MANUAL_TESTING §G`. | ✅ **DONE (cod)** | 5 | — | `agents/web.py` (`_rate_limit`, CORS) · `tests/test_rate_limit_hf2.py` |
| **BUG-2b** | **Frontend test gaps rămase din BUG-2** (trăiau doar în rândul BUG-2 ✅ + `tests/frontend/README.md`): **2b.1** browser E2E (Playwright: server+Chromium, fluxuri chat/tab-uri/command palette/admin); **2b.2** drag-drop canvas workflow (pointer events SVG, layout, edges); **2b.3** voce/`useTTS` (mock `getUserMedia`/`AudioContext`, toggle mic, tranziții stare). | 🧪 Task · P3 | ~14 (8+3+3) | **2b.1** standalone (H7.2 CI ✅) — cel mai bine după ce fluxurile mari H10 se stabilizează, se cuplează cu H9.3/H10.23; **2b.2** ride cu **H10.2** (trace overlay) / **H10.7** (AI builder); **2b.3** ride cu **H12.4** (Wyoming rescrie STT/TTS) / **H12.10** (mute) | BUG-2 deferred + `tests/frontend/README.md` |
| **TASK-1** | **Howard: backend LLM dedicat + prima rulare reală** — `agents/core/llm/ollama_howard.py` (backend dedicat) + ingestion run efectiv + execuție pipeline fine-tuning. H5.1 marchează infra „✅ 100% gata" dar *modelul* și fișierul de backend rămân TODO. | ⚙️ Task · P2 | 8 | **H5.1** (infra ✅, necesită export date Andrei), **H11.3** (SFT/GRPO, GPU) | `docs/internal/gemini_architecture_prompt.md` (TODO-uri) |
| **TASK-4** | **UX pass post-manual-test (HUD + WorldView)** — findings în `docs/2026-06-10-ux-review-hud-worldview.md` (review static ×2 + screenshots reale ale HUD-ului). HUD: P1 double-submit la streaming, afordanță mic-muted, prompt admin-token one-shot; P2 toast erori kill-switch, busy-state pe butoanele de plată, etc. WorldView (mai puțin șlefuit): P1 explicație API-down + legendă layere + claritate LIVE/HISTORICAL. **Fixat deja:** first-run onboarding banner (HUD) + **toate P1+P2 WorldView (2026-06-12**: SystemStatus overlay, legendă layere, mod chip LIVE/HISTORICAL, badge conexiune always-on, help `?`, hint Mapbox, Export colapsat, contrast WCAG, WebGL error boundary, Inspector recovery**)**. Restul (P1 HUD de confirmat pe hardware + P3): *după* testarea manuală — multe P1 se confirmă/infirmă cel mai ieftin pe hardware real. **Brief de design complet pentru partea WorldView** (handover self-contained către Claude Design — inventar UI exact, probleme rancuite, constrângeri brand/tech, deliverables): [`docs/design/WORLDVIEW_UX_BRIEF.md`](docs/design/WORLDVIEW_UX_BRIEF.md) (2026-06-12). **→ Design-ul s-a întors (2026-06-12):** spec implementabil [`docs/design/WORLDVIEW_UX_SPEC.md`](docs/design/WORLDVIEW_UX_SPEC.md) + handoff cu reconciliere post-#193 [`docs/design/WORLDVIEW_UX_HANDOFF.md`](docs/design/WORLDVIEW_UX_HANDOFF.md) + mock hi-fi cu 7 scenarii [`docs/design/worldview-mock/`](docs/design/worldview-mock/). **→ ✅ Redesign IMPLEMENTAT integral (2026-06-12, PR #194):** toți cei 11 pași din spec §6 — tokens+fonturi brand, zone system + app bar, mode system (frame+pill+timeline), Legend=Layers cu glyphs, overlay first-run, right rail + Inspector umanizat, timeline cu event markers + replay în store, tooltips/help/demo-badge, shape encodings pe hartă (icon atlas + fallback), gramatica negative-space (ghosts/DR/cones), arrival deep-link + demo lens. 140 teste frontend verzi, tsc + build verzi. **Rămâne din TASK-4:** doar P1-urile HUD de confirmat la testarea manuală. | 🎨 Task · P2 | 13 | manual test gate | UX review 2026-06-10 |
| **TASK-3** | **Injection quarantine — taint-track all external channels** (audit pass 3, 2026-06-10): quarantine primitives (`detect_injection`/`spotlight`/`TaintedValue`/`plan_then_execute`) exist + tested but are only invoked at REST inspection endpoints, desktop-operator, and (now) transcript ingest. Verdict: **defense-in-depth, NOT critical** — chat agents return text (read-only plugin gathering, no mutating tool call); the one text→task path (transcript) is hard-forced to ask-tier so nothing auto-runs. Closed the visible gap (transcript injection flags on the approval card). **Open (owner architecture call):** wrap email/web-webhook input in `TaintedValue` at the channel boundary + gate irreversible tool calls through `QuarantinePolicy.check_step`, so a future autonomous-tool path is covered by construction. | 🛡️ Task · P2 | 8 | H17.1 (quarantine) + risk gate (holds) | Audit pass 3 2026-06-10 |
| **TASK-2** | **HUD v2 depth — paritate UI cu backendul** (audit 2026-06-10): backendul a luat-o iar înainte — ~37 endpoint-uri (recente sau write-only) **fără control în HUD v2**. **→ 🟡 Gap-ul de controale ÎNCHIS în PR #181 (2026-06-10):** cognition SSE live în cockpit, payments approve/reject/settle (Trust), pairing H12.19, injection scan H17.1, transcript ingest H12.25, escalation H12.11, reflection run, heartbeat run/start/stop, `/learning/promote`, marketplace review H12.12, eval runs+compare, AI step builder H10.7, sandbox execute, agent templates H10.29, LM Studio server/load/unload, auth-profiles H12.20 — noi panele Console în `frontend/src/gap.tsx` + `actA` (token admin) + 7 teste frontend (19 total). **Rămâne coada** (1–2 PR-uri): wiring plugin-gated (Finance/Health/Knowledge/Family, Comms threads), LIVE/SEED per-panel, toolchain §6 (CI stale-bundle guard, OpenAPI types), endpoint locality §7 — vezi `docs/design/HUD_V2_REMAINING.md`. | 🟡 În progres · P2 | 13 (≈9 livrate) | HUD v2 cutover ✅ (2026-06-08) | Audit paritate 2026-06-10 + PR #181 |
| **CLN-1** | **Șterge `tests/test_spotify.py`** — 9 skip-uri permanente care așteaptă `agents/core/skills/spotify.py` (cale ce nu va exista; pattern opencode). Spotify livrează prin `skills/spotify/main.py`, acoperit de `test_spotify_skill.py`. Elimină și zgomotul „8 skipped". **→ ✅ Făcut:** `tests/test_spotify.py` nu mai există (eliminat); Spotify e acoperit de `test_spotify_skill.py`. | ✅ **DONE** | 1 | Niciuna | `tests/test_spotify.py:19`, `BACKLOG.md` (nota „Run") |
| **NTH-1** | **`/cognition/stream` (scoring live)** — `/api/cognition` întoarce deja `last_cognition` real; mock-ul static `COGNITION_SCORING` din `data.js` rămâne ca fallback ne-configurat. Varianta streaming e netrackuită. *(parțial superseded — low)* **→ ✅ Făcut:** `GET /api/cognition/stream` (SSE) emite snapshot-ul `last_cognition` la schimbare + heartbeat pe idle; generatorul de evenimente ia `get_cog`/`sleep` injectabile → testabil offline. | ✅ **DONE** | 3 | H9.2 | `docs/internal/design_handoff_jarvis_hub/README.md`, `data.js` |
| **HF-3** | **Hardening scanner Secret/PII** — pattern OpenAI prea laxat (`sk-…{20,}`, real ≥40 chars → false positives); `db_connection_string` (`scanner.py:82`) prea larg (orice 10+ chars după `://`); `password_assignment` (`:81`) prinde doar valori *între ghilimele* (ratează `password=secret` neîncadrat); **lipsesc** JWT (`eyJ…`), service-account JSON GCP/Azure, Bearer tokens, material PEM, heuristică entropie. **→ ✅ Rezolvat (cod, deja livrat):** scanner-ul le implementează pe toate — OpenAI `{40,}` (nu `{20,}`), db-string cere `user:pass@host`, `password_assignment` prinde bare ȘI quoted, + JWT `eyJ…`/GCP-SA JSON/Azure storage/Bearer/PEM + heuristică de entropie Shannon (`looks_like_high_entropy_secret`, ≥3.6 bits/char). | ✅ **DONE** | 3 | Se cuplează cu HF-2 (security review) | Audit cod 2026-06-04 · `agents/core/security/scanner.py:76-87` |
| **HF-4** | **SSRF: DNS-rebinding / TOCTOU** — `check_ssrf` rezolva IP-ul la momentul check-ului, dar fetch-ul real era ulterior; un domeniu controlat de atacator putea întoarce IP public la check și `127.0.0.1` la fetch. **→ ✅ Rezolvat:** `resolve_and_validate` rezolvă o singură dată și **respinge dacă oricare** IP e privat (anti split-horizon rebinding); `fetch_page` **pin-uiește pe IP-ul validat** la conectare (Host + TLS SNI păstrate) și urmărește redirect-urile **manual**, validând fiecare hop înainte de conectare. | ✅ **DONE** | 3 | — | `agents/core/security/ssrf.py` · `agents/core/plugins/websearch.py` · `tests/test_ssrf.py` |
| **HF-5** | **Separare cheie HMAC audit** — cheia de semnare stătea lângă log (`memory_logs/security/*.key`); acces de scriere pe dir-ul de log = citirea cheii + rescrierea lanțului + re-semnare. **→ ✅ Rezolvat:** `IntentLog._resolve_key` preferă acum o cheie **în afara** dir-ului de log — `JARVIS_AUDIT_KEY` / cheie explicită / dir securizat (`JARVIS_KEY_DIR`, altfel `~/.config/jarvis`); cheia co-locată legacy e onorată cu **warning** de migrare; fallback co-locat doar dacă dir-ul securizat nu e scriibil. *(Anchoring extern via timestamp-authority rămâne nice-to-have post-1.0.)* | ✅ **DONE** | 3 | — | `agents/core/security/anchor.py` · `tests/test_audit_key_hf5.py` |
| **HF-6** | **Sandbox: bypass prin `DEV_MODE`** — când `DEV_MODE=1` (frecvent în dev), `Sandbox` execută cod **direct pe host** (fără Docker, fără `--network none`/limite mem/pids) — `sandbox.py:75-87,158-163`. Risc major dacă rămâne setat în prod. Fix: opt-in *per-apel* explicit (nu flag global), warning vizibil în HUD/`/status` când subprocess fallback e activ. **→ ✅ Rezolvat:** host-fallback e opt-in *per-instanță* (`allow_subprocess`, niciodată flag global — `orch.sandbox` îl lasă OFF, deci `DEV_MODE` **nu** mai pornește host-exec); `active_backend()`/`is_isolated()`/`security_status()` expun postura, iar `/sandbox/status` + posture endpoint raportează `insecure_host_exec` + warning; mesaje de eroare/log corectate. | ✅ **DONE** | 3 | — | Audit cod 2026-06-04 · `agents/core/sandbox.py`, `agents/web.py` · `tests/test_sandbox_hf6.py` |
| **HF-7** | **Admin auth în spatele unui reverse-proxy** — fallback-ul „doar localhost" (`_admin_guard`) folosește `request.client.host`, care devine IP-ul proxy-ului în spatele nginx/ingress → admin expus tuturor dacă `JARVIS_ADMIN_TOKEN` nu e setat. Adaugă suport trusted-proxy/`X-Forwarded-For` + rate-limit pe încercări token. **→ ✅ Rezolvat:** ambele guard-uri (`_admin_guard`/`_user_guard`) fail-**CLOSED** în spatele unui proxy (cer token); `JARVIS_TRUSTED_PROXY` (opt-in, default off) + `_real_client_host` folosesc primul hop `X-Forwarded-For` ca IP real pentru poarta localhost; rate-limit pe token-guess via HF-2 (încercările cu token greșit nu sunt exempte). | ✅ **DONE** | 2 | Cu HF-1/HF-2 | Audit cod 2026-06-04 · `agents/web.py:_admin_guard` |
| **CLN-2** | **Spargere god-object `Orchestrator`** (`agents/core/orchestrator.py`) — un singur obiect gestionează agenți + pluginuri + memorie + canale + autonomie + checkpoints + learning. **Început în #118 (audit A2 — `ComponentRegistry`)**, care a redus fișierul 1620→1537 LOC. **→ ✅ Substanțial DONE (#296):** extrași `ChannelManager` (proprietatea `channels`), `PluginManager` (proprietatea `plugins`), execuția LLM-control (`llm_control.run_llm_control`) și builder-ul de cognition-trace (`cognition_trace.update_cognition`) — toți cu facade-uri delegante, suprafața `orch.*` neschimbată. **Orchestrator 1620→1456 LOC.** Restul inline e **pipeline-ul de request** (`handle_input`/`handle_input_stream` + core-ul `_active_session` ContextVar din BUG-5) — **nu se poate extrage în siguranță** (testele asignează direct ~10 atribute de stare: observer/checkpoints/tracer/run_history/memory/mcp/autonomy_queue/skills/workflow_*, deci nu pot deveni proprietăți). Punct natural de oprire. **Plan:** [`docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md`](docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md). | ✅ Substanțial DONE · P3 | 5 | #118 (A2) → #296 | Audit cod 2026-06-04 |
| **CLN-3** | **Spargere `web.py`** (~4636 LOC, 233 rute, singletons globale `orch`/`gateway`) — split în routere FastAPI per-domeniu (`APIRouter`). **→ ✅ DONE (#293 batch 2 + #296 complet):** **45 de domenii extrase** în `core/routers/` cu wrappere lazy de auth-guard (`_deps.py`, fără ciclu de import); topologie 3-straturi `web_helpers`/`app_state`/`_deps` cu `get_orch()` late-binding. **web.py 4636→1282 LOC; 233→9 rute inline** (rămân, by design: app-shell `/`,`/v1`,`/v2`,favicon,sw.js + `/chat`,`/chat/stream` + `/admin`). Suprafața de **304 rute e byte-identică**, gardată de `tests/test_route_parity_guard.py` + `test_openapi_parity_guard.py` + `test_lifespan_smoke.py` + `test_route_auth_matrix.py`. **Plan:** [`docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md`](docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md). | ✅ **DONE** · P3 | 8 | #293 → #296 | Audit cod 2026-06-04 |

## ✅ ORIZONT 5 — Next Wave (P2–P3) — 17/17 COMPLET

> Fiecare item are spec + plan propriu în `docs/superpowers/`. Timeline: 0.6 → 0.9 → 1.0.
>
> **ORIZONT 5 COMPLET ✅** (2026-06-01) — 17/17 items livrați. Detalii de livrare: [docs/HISTORY.md](docs/HISTORY.md).

| # | Item | S | Dep | Target version |
|---|------|---|-----|---------------|
| H5.1 ✅ | **Howard: Fine-Tuning + Voice Clone + Continuous Ingestion** — RAG pipeline (`ingestion/pipeline.py`, `watcher.py`), Facebook/WhatsApp parsers, `Embedder` cu caching (H5.17), TTS fallback chain (edge-tts/XTTS/ElevenLabs), IngestionWatcher wired în orchestrator. *(Fine-tuning model: necesită export date personale Andrei — infra 100% gata)* | 13 | — | 0.6 ✅ |
| H5.2 ✅ | **Mobile HUD / PWA** (responsive, offline, push) | 8 | — | 0.7 ✅ |
| H5.3 ✅ | **Multi-Language / i18n (RO/EN switch)** | 5 | — | 0.7 ✅ |
| H5.4 ✅ | **UI Overhaul (teme, layout, accesibilitate)** | 8 | H5.2 | 0.7 ✅ |
| H5.5 ✅ | **Performance & Robustness** (retry, circuit breaker, rate limit, caching, resilience metrics) | 8 | — | 0.8 ✅ |
| H5.6 ✅ | **Multi-Agent Workflows** (handoff, paralel, pipeline) — `WorkflowEngine` + `Pipeline`/`WorkflowStep` (DAG, topological sort, parallel batches) + `WorkflowRegistry` (3 built-in: finance_report, research_and_brief, security_digest) + endpoints `/api/workflows` + `/api/workflows/run`. 16 teste offline. | 13 | H5.5 | 0.8 ✅ |
| H5.7 ✅ | **New Integrations / Plugins (SMS, CRM, IoT, social)** | 8 | — | 0.9 ✅ |
| H5.8 ✅ | **Agent Marketplace / Skill Sharing** (registry, publish) | 13 | H5.6 | 0.9 ✅ |
| H5.9 ✅ | **Resilience Tab in Main HUD** — tab live în SystemsPanel cu retry metrics + circuit breaker states, endpoint public `/api/resilience` | 3 | H5.5 | 0.8 ✅ |
| H5.10 ✅ | **Live Data Wiring** — Memory, Plugins, Learning, Security tabs trec de la mock static la endpoint-uri live (`/memory/stats`, `/api/plugins`, `/learning/stats`, `/security/status`, `/bench/stats`) | 5 | H5.9 | 0.8 ✅ |
| H5.11 ✅ | **Missing Widgets** — Ticker feed live, OAuth status tab, Oracle tab, Tasks widget; CognitionPanel live | 5 | H5.10 | 0.8 ✅ |
| H5.12 ✅ | **Secured Shell Task Executor** — `RemediationRunner` (allowlist, permission gate, no-shell `exec`, audited) wired ca handler `restart_service` în executor. `core/autonomy/remediation.py` | 5 | H6.7 | 0.8 ✅ |
| H5.13 ✅ | **Proactive Event Watchers** — `EventWatcher` + Email/Calendar/Finance/Health probes, eșantionate în bucla de autonomie (gated `system.watchers_enabled`). `core/autonomy/watchers.py` | 8 | H6.7 | 0.8 ✅ |
| H5.14 ✅ | **Retrieval Fusion Engine** — `reciprocal_rank_fusion()` + `HybridRetriever` (vector⊕graph RRF, weight-tunable, injectabil) + `MemoryManager.hybrid_search()`. `core/memory/fusion.py`, 9 teste offline. **Task4 ✅:** `GET /api/memory/search` + `FusedRecallBox` în MemoryTab. | 5 | H3.1, H3.2 | 0.8 ✅ |
| H5.15 ✅ | **Daily Reflection & Graph Consolidation** — `DailyReflector` (`core/autonomy/reflection.py`): gather context → LLM reflection → JSON entities/relations/lessons → promote to Neo4j graph; idempotent per zi; hookuit în `_autonomy_loop` (fereastră 22:00–07:00, gated `system.reflection_enabled`). Endpoint `/api/reflection/status` + `/api/reflection/run`. 10 teste offline. | 8 | H6.6, H3.2 | 0.8 ✅ |
| H5.16 🟡 | **Sentence-level TTS & Audio Barge-in** — edge-tts integration + server-side play/stop exist and are tested. **Sentence-level streaming (server) landed:** pure splitter `core/voice/sentence_stream.py` (`split_sentences` + incremental `SentenceAggregator`, 18 offline tests) + `TTSEngine.speak_stream` + `POST /tts/stream` (opt-in `voice.sentence_streaming`, default off; multipart-free framed audio so synthesis/playback can start after sentence #1). Earlier shipped: **browser voice loop** (mic → local STT `/api/voice/stt` → chat → TTS playback, hands-free; PR #162) with **opt-in barge-in** (PR #164, default off, needs on-device echo-cancellation tuning). **Still TODO:** wire `frontend/src/voice.ts` to consume `/tts/stream` (play chunks back-to-back); synthesize *while* the chat streams (the `SentenceAggregator` building block is ready); browser wake-word. See `docs/VOICE.md`. | 8 | H1.1, H5.5 | 0.8 🟡 |
| H5.17 ✅ | **Batch & Cache Embeddings Pipeline** — `EmbeddingCache` (content-addressed, sharded, crash-safe) + `Embedder.embed_batch` (dedup + paralel) + retry/backoff (degradare la hash) + cache stats în pipeline. `core/ingestion/embedder.py` | 5 | H5.5 | 0.8 ✅ |

---

## ORIZONT 7 — Performanță Cale Fierbinte (P1–P2)

> Sursă: profiling 2026-06-02 al căii per-turn (NU generarea LLM). Bottleneck
> non-LLM = scrieri sincrone SQLite pe event-loop-ul async (checkpoint + audit +
> worker autonomie). Detalii + măsurători: `docs/research/2026-06-02-perf-hotpath.md`.
> **Câștig măsurat:** commit SQLite `3317 µs → 92 µs` (~36×) cu WAL+`synchronous=NORMAL`.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.1 ✅ | **SQLite WAL + `synchronous=NORMAL`** pe DB-urile scrise per-turn — `checkpoint.py`, `security/audit.py`, `autonomy/queue.py`. Durabil (WAL crash-safe; NORMAL sigur sub WAL). | 1 | P1 | — | ✅ commit-uri ~36× mai ieftine; suite persistență/autonomy/securitate verzi |
| H7.2 ✅ | **Offload scrieri blocante de pe event-loop** — `checkpoints.save` / `audit.log` / `_record_interactions` / `_log_session` prin `asyncio.to_thread` în toate cele 3 call-site-uri per-turn; `checkpoint.py` cu `check_same_thread=False` + `threading.Lock`. | 3 | P1 | H7.1 | ✅ handlerele per-turn nu mai fac I/O sqlite/fișier sincron pe loop; thread-safe sub `to_thread` |
| H7.3 ✅ | **Debounce / frecvență checkpoint** — `_maybe_checkpoint()` salvează doar la `memory.checkpoint_every` (default 5) turns; `_flush_checkpoint()` forțat pe `new_session()` + `aclose()` (shutdown). Reduce I/O și CPU (`json.dumps` al state-ului). | 2 | P2 | H7.2 | ✅ checkpoint scris ≤1×/N turns; restart curat nu pierde sesiunea activă |
| H7.4 ✅ | **Query-embedding cache + fast-fail (recall)** — `Embedder.from_env(cache_dir=…)` default `memory_logs/embedding_cache/recall` + LRU in-process (`_PROC_CACHE`, 256) cheie `(backend,model,text)`; `max_retries=1` fast-fail. | 2 | P2 | — (recall) | ✅ query repetat = cache hit (fără network/disk); embeddings down → recall degradează instant |
| H7.5 ✅ | **Strategie fast/heavy model** — `is_heavy_request()` (token threshold 2000 + keywords RO/EN) escaladează în `hybrid_router.select_backend()` POLICY_AUTO de la slotul rapid (VRAM) la slotul deep (DDR5); flag `JARVIS_AUTO_DEEP`. | 8 | P2 | — | ✅ task ușor → model rapid `local`; task greu → `local-deep`/DEFAULT_DEEP_MODEL; nu afectează cloud/claude/local-only |

> **ORIZONT 7 PERF COMPLET ✅** (2026-06-02) — 5/5 items, +49 teste offline. Detalii: [docs/HISTORY.md](docs/HISTORY.md).

---

## ✅ ORIZONT 8 — Memorie Personală & Personalizare („Jarvis te cunoaște") (P1) — 7/7 COMPLET

> **Viziune:** Jarvis își construiește în timp o **memorie despre Andrei** — fapte, preferințe,
> decizii, oameni, proiecte — extrasă din conversații, consolidată periodic (ca reflection-ul H5.15),
> versionată și injectată în context la fiecare agent, ca răspunsurile să fie personalizate fără
> să repet de fiecare dată cine sunt și ce vreau. Construit pe infrastructura livrată: fused recall
> (H5.14), embeddings reale + cache (H7.4), daily reflection (H5.15).
>
> **Principii:** local-first (ethos Frigga — datele personale rămân pe LAN), **inspectabil & editabil**
> (pot vedea/șterge orice fapt), opt-in pentru orice plecare spre cloud. Personalizarea crește în timp,
> dar controlul rămâne la mine.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H8.1 ✅ | **Memorie despre Andrei (User Profile Memory)** — store structurat persistent (facts / preferences / decisions / people / projects) construit din conversații (extragere LLM + consolidare idempotentă, pattern H5.15), versionat, injectat în prompt la toți agenții. `core/memory/store.py` + `core/memory/profile_extractor.py` + `/api/memory/profile`. *(PR #37)* | 13 | P1 | H5.14, H5.15, H7.4 | după câteva conversații, Jarvis cunoaște preferințe/fapte despre Andrei și le folosește; profilul e inspectabil în HUD |
| H8.2 ✅ | **Privacy & Forget Controls** — pentru memoria personală: export JSON, forget/redact selectiv per fapt, retention policy, scope strict-local. | 5 | P1 | H8.1 | pot șterge un fapt anume; export complet; nimic personal nu pleacă în cloud fără opt-in explicit |
| H8.3 ✅ | **Recall ON by default + Memory HUD** — activează `memory.recall_enabled` cu cache-ul H7.4; tab HUD cu faptele memorate (search/edit/delete), surse și scoruri (extinde Fused Recall). | 8 | P2 | H7.4, H8.1 | recall activ în chat din oficiu; HUD afișează și editează memoria personală |
| H8.4 ✅ | **Embeddings de calitate (model dedicat)** — `mxbai-embed-large` sau container TEI; benchmark calitate retrieval vs hash/nomic; degradare grațioasă păstrată. | 5 | P2 | H7.4 | retrieval măsurabil mai bun pe un set de probe; fallback intact |
| H8.5 ✅ | **Validare live fast/heavy (H7.5) + Model Tier HUD** — confirmă pe System76 cu 2 sloturi LM Studio încărcate; expune deciziile de tiering (fast↔deep) în `/bench` + HUD. | 5 | P2 | H7.5 | comutare fast↔deep vizibilă; latențe per tier măsurate |
| H8.6 ✅ | **Proactive Personal Briefs** — morning/evening brief (H6.4) personalizate din profil + recall: ce contează pentru Andrei azi (proiecte, oameni, deadline-uri). | 5 | P3 | H8.1, H6.4 | briefurile referă proiectele/oamenii din profilul personal |
| H8.7 ✅ | **AI-Navigable Docs upkeep** — `docs/ARCHITECTURE.md` ca sursă unică de navigare pentru asistenți AI; checklist „docs la zi" în template-ul de PR. | 2 | P3 | — | doc-ul reflectă codul curent; PR-urile mari ating și ARCHITECTURE.md |

> **ORIZONT 8 COMPLET ✅** (2026-06-02) — H8.1–H8.7 livrate (PR-uri #33, #37, #43). Cod: `core/memory/{store,profile_extractor,digest}.py`, endpoints `/api/memory/profile`, `/api/memory/recall`, `/api/analytics/model-tiers`. Detalii: [docs/HISTORY.md](docs/HISTORY.md).

---

## ✅ ORIZONT 9 — Agent Ops: Visual Workflows & Observability (P2) — 3/3 COMPLET

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H9.1 ✅ | **Visual Workflow Builder** — tab HUD (canvas SVG, vanilla React) PESTE `WorkflowEngine` (H5.6): noduri = pași/agenți, muchii = `depends_on`; creează/editează/salvează workflow-uri user-defined + rulare. Backend: `Pipeline.from_dict`, persistență (CRUD) + endpoints `/api/workflows` POST/PUT/DELETE, register în registry. | 13 | P2 | H5.6 | pot compune vizual un workflow, îl salvez, îl rulez din HUD; DAG invalid → eroare clară |
| H9.2 ✅ | **Observability — Trace Explorer** — store de trace-uri per-request (classify→route→model→tokens→latență→cost), nu doar `last_cognition`; endpoint `/api/traces[/{id}]` + tab HUD de inspecție. Extinde `bench.py` + CognitionPanel. | 8 | P2 | — | fiecare request lasă un trace inspectabil; pot vedea unde se duce timpul/tokenii pe pași |
| H9.3 ✅ | **Offline Eval Harness** — rulează seturi de prompturi prin orchestrator (LLM injectabil), scor pass/criterii, tracking de regresie; `core/observability/eval.py` + CLI/endpoint. | 8 | P2 | H9.2 | un set de probe produce scor reproductibil offline; regresii vizibile între rulări |

---

## ORIZONT 10 — Jarvis Competitive Edge (P1–P3) — 30/30

### H10 — Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H10 Competitive Edge** | 30 | **30** | 188 | **186** | **99%** |

> H10.A–E livrate în valul 2026-06-03; **H10.30** (Write-Back Integrations) livrat 2026-06-09 → **H10 complet (30/30)**. *(H10.7 și H10.26 au fost livrate ✅.)*

### H10.A — Observability & Eval (P1 — fundație)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.16 ✅ | **APM Dashboard** — metrici org în Admin HUD: tokens totali consumați (cu cost $ estimat), runs totale, breakdown per agent și per model. **Done 2026-06-03:** `cost_tracker.apm_summary()` (totals runs/tokens/$ + by_agent + by_model, reutilizează H7.10 get_summary) + endpoint admin-guarded `GET /api/admin/apm` (include și `bench.get_summary()` latency). +3 teste offline. | 5 | P1 | H9.2 | SuperAGI |
| H10.24 ✅ | **Cost Tracking per Agent** — calcul $ per request (tokens × preț per provider/model), stocat în trace, vizibil per agent/zi în HUD. **Done 2026-06-03:** cost per-trace via `core/llm/cost_estimator.py` (reutilizat din H7.10, local = $0); `Tracer.cost_by_agent/cost_by_day/cost_summary` peste ring-buffer; endpoint `GET /api/cost` (by_agent + by_day + summary). +8 teste. *(Override `PRICE_TABLE` din config = follow-up.)* | 5 | P1 | H9.2 | LangSmith |
| H10.19 ✅ | **Model Arena / Blind Comparison** — același query la 2+ modele, răspunsuri anonimizate, vot, leaderboard agregat. **Done 2026-06-03:** `core/arena.py` `Arena` (JSON file-backed) — `create_match` anonimizează (labels A/B shuffled, mapping ascuns până la vot), `vote` dezvăluie mapping + actualizează ELO (K=32) + win/loss, `leaderboard` (elo/win-rate, sortat); endpoints `POST /api/arena/run` (candidates date sau rulează ≥2 agenți live), `POST /api/arena/vote`, `GET /api/arena/match/{id}`, `GET /api/arena/leaderboard`. +6 teste offline. | 8 | P1 | H7.5 | OpenWebUI |
| H9.3b ✅ | **Dataset Regression Tracking** (ext. H9.3) — datasets de eval persistente cu versiuni (JSONL), track scor per dataset-version, comparare rulări în HUD; integrabil în CI. **Done 2026-06-03:** `core/observability/datasets.py` `DatasetStore` (versiuni JSONL + run-log + `compare()` regresii/îmbunătățiri pe caz + score-delta) peste `EvalHarness` (H9.3); endpoints `GET /api/eval/datasets`, `/{name}/runs`, `/{name}/compare`, `POST /api/eval/datasets/run`. +8 teste offline. | 5 | P1 | H9.3 | LangSmith |
| H10.22 ✅ | **Agent Prompt Version Control** — SOUL.md versionat cu history, comparare 2 versiuni, A/B eval, rollback. **Done 2026-06-03:** `core/soul_versioning.py` `SoulVersionStore` (JSON file-backed) — `commit` versiuni numerotate imutabile (hash/message/author/parent, dedup pe conținut identic), `history`/`get`/`current`, `diff` unified între 2 versiuni, `rollback` non-distructiv (commit nou cu conținut vechi), A/B: `set_experiment`/`pick` (split determinist via roll)/`record_result`/`ab_summary` (mean per versiune + winner); endpoints admin-guarded `/api/admin/prompts/{agent_id}/{history,version/{n},commit,diff,rollback,ab}`. +8 teste offline. | 13 | P1 | H9.3b | LangSmith |
| H10.23 ✅ | **Live Quality Monitor** — evaluatori (heuristic + LLM-as-judge) pe trace-urile live după fiecare request; scor per request în trace; alertă sub threshold. **Done 2026-06-03:** `core/observability/quality.py` — `evaluate_heuristics` (ok/non_empty/no_error/latency), `score_trace` (medie heuristică, opțional blend 50/50 cu judge injectabil, tolerant la erori judge), `QualityMonitor` (ring rolling, `record`/`rolling_avg`/`check_alert`/`recent`/`stats`/`set_threshold`); hook în orchestrator: scor atașat la trace (`trace["quality"]`) după `tracer.record`; endpoints `GET /api/quality`, `/quality/scores`, admin `POST /quality/threshold`. +8 teste offline. | 13 | P2 | H9.2, H10.24 | LangSmith |
| H10.17 ✅ | **Per-Agent Run History** — în HUD per agent: timeline run-uri, durată, status (success/fail), cost, rută. **Done 2026-06-03:** `core/run_history.py` `RunHistory` (JSON file-backed, ring `deque` capat per agent, record input/output preview+latency+ok+cost+route, `list` most-recent-first, `agents()` rollup ok-rate/avg-latency/cost, clear); hook în orchestrator `_record_interactions`; endpoints `GET /api/agents/history` (rollup) + `GET /api/agents/{id}/history?limit=`. +5 teste offline. | 8 | P2 | H9.2 | SuperAGI |
| H10.25 ✅ | **Human Review Queue** — trace-uri flagate (scor mic sau manual) → coadă de review cu rubric, vot thumbs up/down, adăugare la dataset eval. **Done 2026-06-03:** `core/observability/review_queue.py` `ReviewQueue` (JSON-persistat) — `flag` (idempotent per trace_id) + `auto_flag` (hook H10.23: flag sub threshold), `review` (verdict up/down + rubric filtrat la `RUBRIC_CRITERIA` + notes), `to_eval_case`/`mark_in_dataset`, `stats`; hook în orchestrator (auto-flag după quality.record); endpoints `GET /api/review/queue|stats`, `POST /api/review/flag`, `/{id}/vote`, `/{id}/dataset` (scrie în `DatasetStore` H9.3b). +7 teste offline. | 5 | P3 | H9.3b | LangSmith |

### H10.B — MCP & Integrare (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.5 ✅ | **MCP Server Mode** — Jarvis expune agenți ca tool-uri MCP *guvernate*; orice client MCP (Claude Desktop, Cursor, alt Jarvis) poate apela agenți Jarvis ca tool-uri. **Done 2026-06-03:** `core/mcp/server.py` `JarvisMCPServer` — core JSON-RPC 2.0 transport-agnostic (initialize/tools/list/tools/call/ping), un tool `ask_<agent>` per agent, allowlist + LAN-only by default, rutează prin orchestrator (guardrails+gate); endpoints `GET /api/mcp/server` (status+tools) + `POST /api/mcp/server/rpc` (gated pe `mcp.server_enabled`, default off). +13 teste offline. *(stdio/SSE loop = transport peste același core, follow-up.)* | 8 | P1 | H4.7 | Langflow |
| H10.8 ✅ | **Inbound Webhook Triggers** — endpoint `/api/webhooks/{id}` (POST) activează un agent sau workflow pre-configurat cu payload-ul ca input; autentificat cu token. **Done 2026-06-03:** `core/webhooks.py` `WebhookStore` (JSON file-backed, token `secrets` + compare constant-time, mask la list, accounting calls/last_called) + `extract_input` payload→text; endpoints CRUD `GET/POST /api/webhooks`, `DELETE /api/webhooks/{id}` + trigger `POST /api/webhooks/{id}` (token via header `X-Webhook-Token` sau query, rutează la agent prin orchestrator / workflow best-effort). +8 teste offline. | 3 | P2 | H5.6 | Langflow + Dust |
| H10.27 ✅ | **NL Scheduling** — text "every weekday at 7am" / "în fiecare luni la 9" → cron. **Done 2026-06-03:** `core/autonomy/nl_schedule.py` `parse_schedule` — EN+RO, time parse (7am/6:30pm/19:00/„la 9"), zile (weekday/weekend/zile specifice multiple), intervale (every N min/hours, hourly) → cron 5-câmpuri + descriere; eroare clară la timp lipsă/invalid; endpoint `POST /api/schedule/parse` (422 pe neparsabil). +10 teste offline. | 3 | P2 | H3.5 | Dust |
| H10.1 ✅ | **Embeddable Chat Widget** — `/api/widget/{token}` returnează snippet JS+CSS care embed-uiește chat-ul pe orice site; theming din Admin. **Done 2026-06-03:** `core/widget.py` `WidgetStore` (token-uri per-site, theming title/color/position/greeting, issue/get/update/revoke, persistat) + `render_snippet` (IIFE self-contained: bulă flotantă + panel, postează la endpoint token-scoped); endpoints admin `POST/GET/DELETE /api/admin/widgets`, public `GET /api/widget/{token}` (JS) + `/config` + `POST /api/widget/{token}/message` (rutează prin orchestrator, channel=widget). +4 teste offline. | 3 | P2 | H1.3 | Flowise |
| H10.30 ✅ | **Write-Back Integrations** — agenții pot scrie înapoi în sisteme externe (Notion, GitHub Issues, Google Calendar) ca tool-uri native; Pepper/Hephaestus primii candidați. **Done 2026-06-09 (strat guvernat):** `core/writeback.py` `WriteBackBroker` — request → validare pe allowlist (5 perechi target/action) + sanitizare câmpuri (drop chei străine, cap lungimi/liste) → **task guvernat ask-tier** în coadă (`kind=writeback.<target>.<action>`, `autonomy_level="ask"`, tier extern); **nimic nu se scrie extern la request**. Pe aprobare, worker-ul (executor prefix `writeback`) dispecerizează la `WriteBackBroker.execute` care **rezolvă credențialele la momentul acțiunii, în spatele aprobării** (SecretBroker H15.4 — agentul stochează doar handle `{{secret:…}}`, niciodată tokenul) și apelează un **client injectabil** (`NullWriteBackClient` offline default; `HttpWriteBackClient` = rail live host-side construit prin `build_request` pur). Endpoints `GET/POST /api/integrations/writeback` (user-guarded). +18 teste offline (catalog/supports, validare target+câmpuri, sanitizare, build_request per (target,action), execute behind-approval cu/fără secret, e2e prin TaskQueue+worker real). *(Apelul de rețea real = poartă host.)* | 8 | P3 | H2.1, H2.7 | Dust |

### H10.C — Memory & RAG (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H8.1b ✅ | **Entity Memory Store** (ext. H8.1) — extragere de entități (persoane, proiecte, locuri, concepte) din conversații într-un store structurat separat, searchable, afișat în HUD Memory tab. **Done 2026-06-03:** `core/memory/entity.py` `EntityStore` (JSON file-backed, upsert cu mention-count + sources + contexts + first/last-seen, search/filter pe tip, stats, delete; extracție proper-noun offline `extract_entities` + clasificare pe hint, extractor LLM injectabil ulterior); ingest per-tură în orchestrator (`_record_interactions`); endpoint `GET /api/memory/entities?q=&type=&limit=`. +9 teste offline. | 5 | P1 | H8.1, H5.14 | CrewAI |
| H8.3b ✅ | **Agentic RAG Tool** (ext. H8.3) — recall devine tool call LLM-callable (`search_memory(query)`); modelul decide când/cum să caute și poate retry cu query diferit. **Done 2026-06-03:** `core/memory/rag_tool.py` — `TOOL_SPEC` (function-calling schema), `MemorySearchTool` (wrap recall_fn, înregistrează calls, înghite erori), `agentic_search(query, tool, planner, max_iters)` buclă agentică (planner decide answer/refine, retry cu query nou, cap pe max_iters); endpoints `GET /api/memory/tool-spec` + `POST /api/memory/search-tool` peste recall structurat (entities+KG, offline). +8 teste offline. | 8 | P2 | H8.3, H7.4 | OpenWebUI |
| H10.21 ✅ | **Conversation Notes** — note atașate sesiunii, injectate ca context persistent; „Rescrie cu AI". **Done 2026-06-03:** `core/notes.py` `NotesStore` (markdown per `session_id`, get/set/clear, cap 20k, persistat, `context_for` randează bloc `[Session notes]`); injecție în `/chat` (prepend la mesaj pentru sesiunea activă); endpoints `GET/PUT/DELETE /api/notes` + `POST /api/notes/rewrite` (rulează nota prin agent, opțional `save`). +5 teste (store+persistență, cap, context_for, endpoints+injecție, rewrite). Editorul rich-text rămâne pentru HUD (backend complet). | 3 | P3 | H1.3 | OpenWebUI |

### H10.D — Workflow Engine (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.12 ✅ | **Workflow Termination Conditions** — WorkflowStep poate defini o condiție de stop (keyword/regex/equals/not_empty match), nu doar completare normală. **Done 2026-06-03:** `WorkflowStep.terminate_when` (dict opțional, round-trip to/from_dict fără poluare); `engine.evaluate_condition` (contains/not_contains/equals/regex/not_empty, fail-open pe condiții malformate); engine oprește pipeline-ul după batch-ul în care un guard se declanșează, setând `_terminated`/`_terminated_by`. +6 teste offline. | 3 | P2 | H5.6 | AutoGen |
| H10.10 ✅ | **Structured Agent Outputs (Pydantic)** — un step poate specifica un schema; engine-ul validează output-ul agentului și expune câmpurile tipate downstream. **Done 2026-06-03:** `workflows/structured.py` — `extract_json` (fenced ```json``` sau bare `{...}`), `build_model` (Pydantic v2 `create_model` din schema `{fields:{name:{type,required,default}}}`), `validate_output` → `{ok,data,error}` cu coerce; `WorkflowStep.output_schema` (round-trip) + engine `_apply_structured` (flatten `{step.field}` în ctx, `_structured[step]`, marchează eroare la invalid). +8 teste offline. | 5 | P2 | H5.6 | CrewAI |
| H10.15 ✅ | **Critic Agent Pattern** — built-in workflow node tip `critic`: primește output-ul unui step, îl evaluează (scor + feedback), decide accept / retry(max N). **Done 2026-06-03:** `WorkflowStep.kind` ("agent"/"critic") + `critic` config (`target`, `pass_threshold`, `max_retries`), round-trip; engine `_execute_step` dispatch + `_run_critic` — critic-agent răspunde JSON `{score,pass,feedback}`, re-rulează target-ul cu `{_critic_feedback}` cât timp pică și mai sunt retries; expune `{step.score}`/`{step.passed}` + `_critics[step]` (attempts). +4 teste offline (pass-first, retry-then-pass, exhaust-retries, round-trip). | 5 | P2 | H5.6, H10.12 | AutoGen |
| H10.13 ✅ | **Dynamic Agent Router** — WorkflowStep `kind="router"`: un agent coordinator decide la runtime care agent urmează (conditional routing, nu DAG fix). **Done 2026-06-03:** `WorkflowStep.router` config (`routes` label→agent, `default`, `dispatch_template`), round-trip; engine `_run_router` — agentul-clasificator alege un label (JSON `{"route":…}` sau text), `_match_route` mapează (longest-label-first, fallback default), dispatch la agentul ales; expune `{step.route}`/`{step.agent}` + `_routes[step]`. Fără match & fără default → întoarce decizia, fără dispatch. +6 teste offline. | 8 | P2 | H5.6 | AutoGen |
| H10.2 ✅ | **Visual Workflow Trace Overlay** — la fiecare rulare de workflow, date per-pas (timing, input, output, status) pentru overlay în HUD. **Done 2026-06-03:** engine instrumentează fiecare pas (`_traced_execute` → `ctx["_trace"]` cu step/kind/agent/input/output/elapsed_ms/ok) + ring `recent_runs` (cap 50) cu `recent(limit)` (pipeline_id/name/ts/elapsed/ok/terminated_by/steps); endpoint `GET /api/workflows/traces?limit=`; `/api/workflows/run` întoarce deja `_trace` în rezultat. +4 teste offline. | 5 | P2 | H9.1, H9.2 | Flowise |
| H10.28 ✅ | **Agent Config Preview** — în HUD Admin, înainte de save la SOUL.md/config, preview a ce se schimbă (diff + validare) fără a afecta producția. **Done 2026-06-03:** `core/config_preview.py` — `validate_prompt` (empty=hard-fail; warnings: prea scurt/mare, lipsă headings, frontmatter dezechilibrat), `preview_change` (unified diff + added/removed counts + `is_new`/`changed`); endpoint admin-guarded `POST /api/admin/prompts/{agent_id}/preview` (`current` opțional → ia ultima versiune commit-uită H10.22). +7 teste offline. *(dry-run pe input de test = follow-up.)* | 5 | P2 | H1.5 | Dust |
| H10.4 ✅ | **Guardrails Node în Visual Builder** — scanere secret/PII expuse ca nod, configurabil per workflow. **Done 2026-06-03:** `core/workflows/guardrail_node.py` `apply_guardrail` (reutilizează `SecretScanner`/`PIIScanner` H4.9; mode warn/redact/block, selecție scanere) → warn=pass, redact=mask, block=`[error:guardrail blocked:…]`; `WorkflowStep.guardrail` + dispatch `kind="guardrail"` în engine (info în `ctx["_guardrails"]`). +8 teste (moduri, selecție scanere, serializare, 2 integrate prin engine). | 2 | P3 | H4.9, H9.1 | Flowise |
| H10.6 ✅ | **Cyclic Workflow Support** — loop-back edges cu contor de iterații și condiție de exit. **Done 2026-06-03:** `WorkflowStep.loop` + dispatch `kind="loop"` în engine (`_run_loop`) — re-rulează un body inline de pași (orice kind: agent/transform/guardrail) împărtășind `ctx`, până la `until` (reutilizează `evaluate_condition` H10.12) sau `max_iterations` (clamp [1,100]); expune `{step._iter}` și `ctx["_loops"][id]={iterations,exited_by}`. Nu atinge DAG-ul batch existent. +6 teste (exit pe condiție, max_iterations, counter, body gol no-op, clamp, serializare). | 8 | P3 | H5.6, H10.12 | Langflow |
| H10.7 ✅ | **AI-Assisted Workflow Builder** — câmp "Descrie ce vrei să facă acest pas" → config de step generat. **Done:** `core/workflows/ai_builder.py` `generate_step(description, agents, llm)` — LLM-ul (injectabil) propune un config, **validat** la o formă safe (kind ∈ {agent/router/critic/transform/guardrail/loop/subflow}, agent ∈ allowlist, transform ∈ operatori H10.3, fără câmpuri străine); **fallback euristic determinist** pe keyword-uri când nu-i LLM sau output-ul nu parsează (deci merge și offline, nu întoarce junk). Endpoint `POST /api/workflows/step/generate`. +15 teste offline. | 5 | P3 | H9.1 | Langflow |
| H10.9 ✅ | **Python Flow Decorator API** — `@jarvis_flow`, `@step`, `@listen(step_id)`, `@router` pentru workflow-uri în cod. **Done 2026-06-03:** `core/workflows/flow_api.py` — decoratori (id=numele metodei, `@listen` setează deps, ordine de definire păstrată); fiecare metodă întoarce un step-spec (`agent`/`prompt` + opțional transform/guardrail/router/loop/schema/critic); `build_flow(cls)` compilează în `Pipeline` validat (DAG check, eroare pe non-flow/empty/ciclu). Complement al Visual Builder, rulează prin engine neschimbat. +7 teste (compilare, deps/kinds, router, erori, ciclu, e2e prin engine). | 5 | P3 | H5.6 | CrewAI |
| H10.11 ✅ | **Hierarchical Workflow Manager** — manager agent coordonează crew-ul, validează rezultate, redistribuie la eșec. **Done 2026-06-03:** `core/workflows/hierarchical.py` `HierarchicalManager` — rulează fiecare crew member spre goal (context flows între membri), validează (heuristic error/empty), redistribuie pe eșec (retry cu feedback de la manager, opțional la `fallback` agent, `max_retries`), apoi manager-ul sintetizează output-urile într-un răspuns final; endpoint `POST /api/workflows/hierarchical`. +6 teste (happy path+synthesis, context flow, fallback redistribute, retry same-agent, retries epuizate, endpoint). | 8 | P3 | H5.6, H10.15 | CrewAI |
| H10.14 ✅ | **Nested Workflow Steps** — un WorkflowStep conține un sub-workflow; task decomposition recursivă. **Done 2026-06-03:** `WorkflowStep.subflow` + dispatch `kind="subflow"` în engine (`_run_subflow`) — compilează sub-pipeline din config, îl rulează recursiv cu input = prompt_template randat, expune output-urile sub-pașilor ca `{step.id}.{sub_id}` + output final (configurabil via `output`, altfel ultimul pas) ca output-ul stepului; `ctx["_subflows"][id]`; recursion cap depth 5; DAG-ul părinte rămâne aciclic (sub-pașii trăiesc în config). +6 teste (nesting, chaining cu pași externi, subflow invalid→error, gol, depth cap, serializare). | 8 | P3 | H5.6 | AutoGen |
| H10.3 ✅ | **Workflow Transform Nodes** — Formatter, Validator, JSONExtractor, Summarizer. **Done 2026-06-03:** `core/workflows/transforms.py` `apply_transform` (op-uri deterministe, fără LLM: formatter upper/lower/title/strip/json_pretty, validator non_empty/json/regex/min/max_length/contains→`[error:…]` la fail, json_extract dot-path+default, summarize N propoziții/max_chars); `WorkflowStep.transform` + dispatch `kind="transform"` în engine (no-LLM). +8 teste (unit per-op + serializare + 2 integrate prin engine). | 5 | P3 | H9.1 | Flowise |

### H10.E — UX & Multi-user (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.29 ✅ | **Agent Templates Library** — librărie de configurații pre-built pentru agenți comuni; instanțiabile din Admin. **Done 2026-06-03:** `core/agent_templates.py` — catalog 5 arhetipuri (researcher/coder/analyst/assistant/ops) cu tier/model/plugins/voice + SOUL skeleton; `list_templates`/`get_template` (case-insensitive)/`build_agent_config` (slug id, overrides per câmp, randează config agents.yaml-shaped + SOUL); endpoints `GET /api/agent-templates` + `POST /api/agent-templates/instantiate` (404 pe template necunoscut). +6 teste offline. | 3 | P3 | — | Dust |
| H10.18 ✅ | **Action-Level Approval** — tool call-uri pending approval (granularitate sub-task); Aprob/Resping per acțiune. **Done 2026-06-03:** `core/autonomy/action_approvals.py` `ActionApprovalQueue` — `request` (preview H12.5 per acțiune), `decide` (approve/reject, idempotent), `await_decision` (async pe `asyncio.Event` cu timeout — flux tool blocant), `list/stats`; endpoints `GET /api/actions[/pending]`, `POST /api/actions/request`, admin `POST /api/actions/{id}/decide`. +7 teste (request+preview, approve/reject+stats, filtre, await unblock/timeout/already-decided, endpoints). Tab-ul live HUD folosește acest backend. | 5 | P3 | H6.2 | SuperAGI |
| H10.20 ✅ | **Chat Channels / Rooms** — canale tematice (per proiect/context); @mention agenți; pipeline complet. **Done 2026-06-03:** `core/rooms.py` `RoomStore` (camere persistate cu nume/descriere/roster agenți/default + istoric bounded; `parse_mentions`, `route` = primul @mention din roster altfel default, `context_for` injectează contextul camerei); rutare prin orchestrator (channel=room, full pipeline tools/RAG/filters); endpoints `GET/POST/DELETE /api/rooms`, `GET /api/rooms/{id}[/history]`, `POST /api/rooms/{id}/message`. +6 teste (CRUD, istoric persistat+cap, parse_mentions, routing roster/default, context_for, endpoints+rutare). HUD-ul consumă acest backend. | 8 | P3 | H1.3 | OpenWebUI |
| H10.26 ✅ | **Data Spaces / Agent Data Scope** — surse de date în "spații" cu permisiuni per agent; complement la `LOCAL_ONLY_AGENTS`. **Done:** `core/data_spaces.py` `DataSpaces` — spații (set de surse) + asignări per-agent, **default-open** (agent neasignat = nerestricționat → backward-compatible), `allowed_sources`/`can_access`/`filter_categories`; enforcement la `GET /api/memory/profile?agent=<id>` (întoarce doar categoriile permise), admin CRUD `/api/memory/spaces[/assign|/unassign]`. *(Scoping pe recall-ul vectorial fuzionat rămâne follow-up — necesită surse pe vectori.)* +8 teste offline. | 13 | P3 | H8.1, H4.7 | Dust |

---

## ORIZONT 11 — Platform Parity (Known Gaps vs OpenJarvis) (P3) — 4/4 ✅

> Capabilități prezente în OpenJarvis dar absente în Jarvis Hub (vezi `STATUS.md` → Known Gaps).
> Toate P3 — nice-to-have, niciuna nu blochează 1.0.0. Mai multe au cost mare (GPU, Rust, build nativ).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H11.1 ✅ | **Desktop App (Tauri)** — UI nativ desktop (Windows/macOS/Linux) care împachetează HUD-ul existent; tray icon, wake-word listener local, auto-start. Alternativă la rularea în browser. **Done 2026-06-09 (sursă; build host):** `desktop/` — proiect Tauri v2 care împachetează HUD-ul web existent (fereastră → `127.0.0.1:8080`, tray, auto-start; fără backend nou): `src-tauri/{tauri.conf.json, Cargo.toml, build.rs, src/main.rs}` + README. ⚠️ **Sursă — se compilează host-side (`cargo tauri build`), nu rulează în CI.** | 13 | P3 | — | OpenJarvis (Tauri) |
| H11.2 ✅ | **Rust Extension / Hot-Path Crates** — port în Rust al căilor fierbinți (embeddings, vector search, parsing) ca extensii native (PyO3); pure-Python rămâne fallback. OpenJarvis are 14 crates. **Done 2026-06-09 (sursă + fallback testat):** `rust/jarvis_native/` (crate PyO3: `cosine_similarity`/`top_k_similar`/`count_tokens`) + **fallback pur-Python** `core/native_fallback.py` (identic; `load_native()` preferă extensia compilată, altfel Python → comportament identic cu/fără build). +4 teste offline pe fallback. ⚠️ **Crate-ul Rust = build host (`maturin`), netestat în CI.** | 21 | P3 | H7 | OpenJarvis (14 crates) |
| H11.3 ✅ | **SFT/GRPO Training Pipeline** — fine-tuning local pe modele (SFT + GRPO) din trace-urile colectate; necesită GPU. Closing the loop pe Learning Loop (H7.11). **Done 2026-06-09 (sursă + data-prep testat):** `training/prepare_data.py` (trace→SFT JSONL ShareGPT-style, filtru pe scor — **pur-Python, testabil**, +3 teste) + `training/sft_grpo.py` (pipeline SFT/GRPO HF `trl`/`transformers`, importuri guarded) + README. ⚠️ **Antrenarea = GPU host, nu rulează în CI.** | 13 | P3 | H7.11 | OpenJarvis |
| H11.4 ✅ | **WASM Sandbox (wasmtime)** — backend de execuție WASM pentru sandbox, complementar Docker; izolare mai bună și portabilă, fără daemon Docker. `core/sandbox.py` (backend nou). **Done 2026-06-09 (backend + fallback grațios):** `Sandbox` câștigă un backend wasmtime — detecție (`_check_wasmtime`), `wasm_available()` (cere binarul + un runtime Python‑WASM configurat via `JARVIS_WASM_PYTHON`), prioritate **Docker→WASM→subprocess**, și **fallback grațios** (binar lipsă la execuție → revine la subprocess, fără regresie pe căile existente). `_build_wasm_command` pur/testabil. +7 teste offline (detecție, selecție backend, fallback la binar lipsă, comportament existent păstrat). *(Execuția WASM reală = poartă host: wasmtime + `python.wasm`.)* | 8 | P3 | — | OpenJarvis (wasmtime) |

---

## ORIZONT 12 — Categoria Reală: Asistent Personal Privat & Proactiv (P0–P3) — 23/25

> Bazat pe research-ul din [docs/research/2026-06-02-personal-ai-competitors.md](docs/research/2026-06-02-personal-ai-competitors.md):
> H10 a comparat Jarvis cu 8 **framework-uri de developeri**; categoria reală a moonshot-ului (asistent
> personal, proactiv, privat) nu fusese niciodată analizată. Idei derivate din competitorii **reali**
> (OpenClaw, Khoj, Leon, Omi, Bee, Pieces, Home Assistant, Jan, Tana) — fiecare verificată față de
> [principiile non-negociabile](MOONSHOT.md#5-non-negotiable-principles-the-guardrails).
>
> **Wedge-ul defensiv:** OpenClaw (rivalul direct viral) a eșuat exact unde Jarvis e puternic — secrete în
> plaintext, fără guvernanță acțiuni, marketplace nemoderat → ținta #1 a infostealerelor. Jarvis = alternativa guvernată.

### Track A — Securitate ca Diferențiator (P0, anti-OpenClaw)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.1 ✅ | **Securitate ca feature de prim rang** — criptează secretele at-rest (fără `SOUL`/memory în plaintext), skills semnate + sandboxed, expune coada de aprobare reversibil/ireversibil ca "povestea anti-OpenClaw". Pachetizează guardrails + PII scanner + sandbox existente. **Done 2026-06-02:** `core/secrets.py` `SecretStore` (Fernet + key-derivation PBKDF2/keyfile 0600, fallback HMAC-XOR pur-Python, get/set/delete + `migrate_plaintext`); `core/skills/signing.py` + loader extins (verificare `SKILL.sig`, advisory by-default, `JARVIS_REQUIRE_SIGNED_SKILLS=1` → modul untrusted nu se exec in-process; skills auto-generate auto-semnate); 2 endpoints noi `GET /autonomy/approvals` (bucket reversibil/ireversibil pe risk tier) + `GET /api/security/posture` (pachetizează secrets+signing+sandbox+guardrails). +31 teste offline. | 8 | **P0** | H6.2, Sec | OpenClaw (eșecuri) |

### Track B — Memorie & Onboarding (P1)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.2 ✅ | **Onboarding "drop folder → chat privat cu documentele"** — alegi un folder pre-configurat, Jarvis îl indexează local (PDF/MD/docx) și poți discuta cu el offline. **Done 2026-06-03:** `core/local_docs.py` `LocalDocsIndexer` (walk recursiv, extract md/txt/rst nativ + pdf/docx best-effort cu skip grațios, chunking word-window cu overlap → `memory.remember` local, fără cloud); endpoint **select-by-key** `POST /api/local-docs/index {key}` (folderul vine din config `local_docs.folders`, **niciun path din request** → fără path-injection) + `GET /api/local-docs` (sumar + chei disponibile). +5 teste offline. | 3 | P1 | H8.3 | GPT4All LocalDocs, Khoj |
| H12.3 ✅ | **KG interogabil & editabil (UX)** — graful de cunoștințe ca suprafață de prim rang: vizualizează, caută, editează, șterge entități/relații. **Done 2026-06-03:** `KnowledgeGraph` extins cu `list_entities`/`delete_entity` (DETACH + curăță relațiile)/`delete_relation` în ambele backend-uri (InMemory + Neo4j); endpoints `GET /api/kg/entities?q=&limit=`, `GET /api/kg/entities/{name}` (+relations), `POST /api/kg/entities` (upsert), `DELETE /api/kg/entities/{name}`, `POST /api/kg/relations`, `DELETE /api/kg/relations`. Implementează "inspectable & forgettable" (H8.2). +4 teste offline. | 8 | P1 | H8.2 | Tana supertags |
| H12.4 ✅ | **Suport protocol Wyoming** — Jarvis vorbește Wyoming → interoperează cu sateliți Voice PE ($59) și ecosistemul vocal local Home Assistant; decuplează STT/TTS/wake. **Done 2026-06-03:** `core/voice/wyoming.py` — framing wire pe format de referință (header JSON + payload length-prefixed), `encode_event`/`read_event`, `WyomingServer` rutează `describe`→`info`, `transcript`→handler→`synthesize`, `ping`→`pong`; `serve()` TCP (port 10700) + `handle_connection`; endpoint status `GET /api/voice/wyoming` (gated `voice.wyoming_enabled`). +11 teste offline. | 5 | P1 | — | Home Assistant, Rhasspy |

### Track C — Proactivitate & Observabilitate (P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.5 ✅ | **Preview / dry-run pentru autonomie** — arată ce *ar* face o acțiune înainte de aprobare; nicio acțiune oarbă. **Done 2026-06-03:** `core/autonomy/dry_run.py` `preview_task` — extrage kind/title/target/effects din payload, clasifică ireversibilitatea (reutilizează H17.1 `QuarantinePolicy` + tokeni send/delete/transfer…), `requires_approval` (ireversibil sau risc tier≤2), `would_execute=False`; integrat în `build_decision_card` (linie _Preview:_) + endpoints `POST /api/autonomy/preview` + `GET /api/autonomy/tasks/{id}/preview`. +6 teste offline. | 5 | P2 | H6.2 | Dust config preview |
| H12.6 ✅ | **Update-uri KG incrementale (nu doar nocturne)** — extracție ușoară de triple per-tură ca memoria să apară în aceeași sesiune. **Done 2026-06-03:** `core/memory/incremental.py` — `extract_triples` (pattern-uri high-precision: posesiv „X's Y is Z", lives_in/works_at/related_to verbe, copula is_a; sare stopwords + self-refs), `IncrementalKGUpdater.ingest` scrie entități+relații în KnowledgeGraph live + fapte în bi-temporal (H14.1, contradicție→invalidează); hook în orchestrator `_record_interactions` + endpoint `POST /api/kg/ingest`. Calea nocturnă LLM rămâne high-recall. +8 teste offline. | 5 | P2 | H5.15, H8.1 | Mem, Tana |
| H12.7 ✅ | **Captură pasivă multi-suprafață (opt-in, local)** — browser/clipboard/fișiere → KG, doar local. ⚠️ STRICT opt-in + inspectabil; nimic nu pleacă de pe mașină. **Done 2026-06-09:** `core/passive_capture.py` `PassiveCapture` — **dublu opt-in** (master `JARVIS_PASSIVE_CAPTURE` + per-suprafață, default OFF → nimic capturat), **local-only** (fără rețea; KG + store on-disk bounded), **secrete redactate înainte de stocare** (`SecretScanner.redact` → cheie copiată în clipboard nu se persistă niciodată), ingestie în KG-ul incremental (H12.6) pe text redactat, **inspectabil + forgettable** (`list`/`get`/`forget`/`clear`). Înregistrat lazy; 6 endpoints (`/api/capture/status|ingest|surfaces`, `GET /api/capture`, `DELETE /{id}`, `/clear`). +11 teste offline. *(Hook-urile OS clipboard/browser/file = seam host-side care apelează `ingest`.)* | 8 | P2 | H8.1 | Pieces nanomodels, Omi |
| H12.8 ✅ | **Split sateliți-mic → server-inferență pe GPU-ul de acasă** — mai multe endpoint-uri ieftine de microfon partajează un singur GPU Jarvis. **Done 2026-06-09:** `core/satellite_hub.py` `SatelliteHub` — registru de sateliți (allowlist explicit) + `dispatch` care rutează STT/inferența la un **backend de inferență partajat injectabil** (`NullInference` offline default), **serializat printr-un semafor** ce modelează contenția unui singur GPU (`max_concurrency=1` → niciodată concurent; testat). Accounting per‑satelit + `stats`/`peak_inflight`. Endpoints `GET /api/satellites`, `POST /register`, `DELETE /{id}`, `POST /{id}/dispatch`. +8 teste offline (registru, dispatch, serializare GPU, eroare inferență, stats). *(Backendul real Wyoming/LM‑Studio = poartă host.)* | 8 | P2 | H12.4 | Willow (WIS) |
| H12.9 ✅ | **UX management modele locale** — răsfoiește/descarcă/comută modele dintr-un click în HUD. | 5 | P2 | — | Jan.ai |
| H12.10 ✅ | **Indicator mute hardware / strict-local** — semnal vizibil, auditabil "mic off / strict-local" în HUD + voce. Semnal de încredere ieftin. | 2 | P2 | — | Voice PE (mute fizic) |
| H12.11 ✅ | **Canale de escaladare extinse** (dincolo de Telegram: WhatsApp/Signal/Slack/Discord) — *guvernate*. **Done 2026-06-03:** `core/autonomy/escalation.py` `EscalationRouter` — fan-out la adaptoarele de canal existente, *guvernat* prin allowlist (`autonomy.escalation_channels`), best-effort (nu aruncă), `targets()` rezolvă available∩requested∩allow; `render_escalation` mesaj plain channel-agnostic (cu preview H12.5); endpoints `GET /api/autonomy/escalation/targets` + admin `POST /api/autonomy/escalate` (mesaj sau task). +7 teste offline. | 3 | P2 | H1.3 | OpenClaw (multi-channel) |

### Track D — Platformă & Ecosistem (P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.12 ✅ | **Marketplace de skills curat & semnat** (anti-ClawHub moderat) — extinde skills importer cu semnături + review. **Done:** `marketplace.py` — **poartă de review** (`review_status` pending/approved/rejected; publish→pending; `approve/reject/set_review_status`; install blocat dacă nu-i approved sub `JARVIS_REQUIRE_REVIEWED_SKILLS`), **semnătură** la publish (`signing.sign_skill`) + verificare la install (refuz sub `JARVIS_REQUIRE_SIGNED_SKILLS`), și **fix zip-slip** (path-traversal blocat înainte de extract — vuln reală în `extractall`). Endpoint `POST /api/skills/marketplace/review`; gate-urile opt-in (default backward-compatible), zip-slip mereu blocat. +6 teste offline. | 8 | P3 | Skills | OpenClaw ClawHub (sigur) |
| H12.13 ✅ | **Sync E2E opt-in între device-uri** (GPU acasă ↔ telefon) — ⚠️ obligatoriu E2E + opt-in; nu sparge local-first. **Done 2026-06-09 (E2E real, fail‑closed):** `core/e2e_sync.py` `E2ESync` — plic E2E cu **Fernet real** (`cryptography`, AES‑128‑CBC+HMAC autentificat → tamper/cheie greșită **detectate**, nu acceptate tacit), cheie derivată dintr‑un **passphrase partajat** (PBKDF2‑SHA256 390k, salt fix → două device‑uri cu același passphrase derivă aceeași cheie) sau cheie Fernet; **opt‑in** (`JARVIS_E2E_SYNC`) și **fail‑closed** (fără cripto/secret → dezactivat, **fără fallback slab**). `encrypt_record`/`decrypt_record` (plaintextul nu părăsește niciodată device‑ul), `build_push`/`apply_pull` (manifest cu digest; sare propriul device + intrările neverificabile). Endpoints `GET /api/sync`, `POST /api/sync/push|pull`. +12 teste offline (round‑trip, tamper, cheie greșită, cross‑device, opt‑in, fail‑closed). *(Transportul device‑la‑device = poartă host.)* | 13 | P3 | — | Reflect / Limitless |
| H12.14 | **Model agentic mic, fine-tuned** (task-uri router/tool) — overlap cu H11.3 (pipeline SFT/GRPO); $0 COGS. **🖥️ GPU host — runbook turnkey: `docs/GPU_RUNBOOK.md`** (pipeline + `prepare_data` citește direct `memory_logs/learning/*.jsonl`). | 8 | P3 | H11.3 | Jan-nano |
| H12.15 ✅ | **Backup & restore date personale** — `agents/data/` + `memory_logs/` (memoria H8, sesiuni, workflow-uri create, corpus ingerat) sunt **singura stare cu date reale și sunt git-ignored** → fără asta, pierdere totală la orice `clean`/reinstalare (incidentul 2026-06-02). **Done 2026-06-02:** `scripts/backup-data.sh` + `scripts/backup-data.ps1` — arhivă timestamped (tar.gz / zip), restore cu confirmare, retenție ultimele 14, override `BACKUP_DIR` (drive extern/cloud); `backups/` gitignored; păstrează local-first (opt-in cloud). *(Schedule automat = opțional, neimplementat.)* | 3 | P2 | H8.2 | durabilitate local-first |

### Track E — Paritate guvernată cu OpenClaw (post‑research 2026‑06‑05) (P2–P3)

> Funcționalități adoptate din OpenClaw (`github.com/openclaw/openclaw`, ~377k★) **doar sub guvernanță** —
> închid decalajul de *reach/UX* fără să atingă vreun non‑negociabil. Analiză completă:
> [docs/research/2026-06-05-openclaw-feature-analysis.md](docs/research/2026-06-05-openclaw-feature-analysis.md).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.16 ✅ | **Lărgire canale** (WhatsApp nativ / Signal / iMessage / Matrix / Teams / Google Chat …) pe gateway‑ul *guvernat* (rate‑limit + guardrails + allowlist se aplică). OpenClaw are ~23 canale; noi avem 6. **Done 2026-06-09:** `core/channels/webhook_channels.py` — familie de adaptoare HTTP/webhook (`WhatsApp`/`Signal`/`Matrix`/`Teams`/`GoogleChat`) pe **același gateway guvernat**: fiecare inbound trece `sender` → **poarta de pairing H12.19 + rate‑limit + guardrails se aplică** înainte de orchestrator; outbound prin **transport injectabil** (offline-testable, rețeaua reală = poartă host). Per‑provider doar 2 funcții pure: `build_send` (mesaj→request HTTP) + `parse_inbound` (payload→`text,sender`). Factory `build_channel`/`channels_from_config`; wiring în lifespan via `JARVIS_WEBHOOK_CHANNELS` (default‑off); endpoints `GET /api/channels/webhook` + `POST /api/channels/{id}/inbound`. **iMessage exclus deliberat** (macOS/host‑bound, fără suprafață HTTP curată → bridge host, nu acest strat). 6→11 canale. +18 teste offline (build_send/parse_inbound per provider, send via transport mock, inbound guvernat de pairing). | 5 | P2 | H1.3 | OpenClaw multi‑channel |
| H12.17 ✅ | **Node mesh guvernat** — telefon/desktop ca *noduri de execuție* care rulează doar acțiuni capability‑scoped + aprobate; GPU‑ul de acasă rămâne creierul. Unifică Tauri (H11.1) + split sateliți (H12.8). **Done 2026-06-09 (strat de guvernanță pe H17.3):** `core/node_mesh.py` `NodeMesh` — `register_node` mintează un **token capability‑scoped** (H17.3 `CapabilityBroker` — tokenuri read‑only, nodul **nu poate escalada**, primește doar capabilitățile declarate); `dispatch` **autorizează** (kill‑switch + capabilitate via `authorize()`) apoi enqueue **task ask‑tier** (`kind=node.dispatch`) — nimic nu rulează pe nod până la aprobare; `execute` **re‑autorizează la momentul acțiunii** (token expirat/revocat sau kill‑switch → blocat) și predă nodului (rularea on‑device = poartă host). Endpoints `GET /api/nodes`, `POST /register` (admin), `DELETE /{id}` (admin), `POST /{id}/dispatch`. +9 teste offline (token mint, dispatch în/în afara capabilității, kill‑switch, revoke, re‑auth la execute, e2e). *(Clientul Tauri/telefon = poartă host.)* | 13 | P3 | H11.1, H17.3 | OpenClaw „nodes" / Willow |
| H12.18 ✅ | **Agent Canvas / A2UI** — spațiu vizual condus de agent în HUD (inspectabil + guvernat), peste network brain‑ul v2. **Done 2026-06-09 (backend guvernat):** `core/canvas.py` `CanvasStore` — agentul postează DOAR elemente tipizate known‑safe (`text/markdown/list/link/metric/table/image_ref`), fiecare **sanitizat** (whitelist câmpuri + bound lungime/count, URL doar `http(s)`/same‑origin → **niciun HTML/script brut**, disciplina „validate down to known‑safe" din AI builder); atribuit pe agent, inspectabil, `pin`/`remove`/`clear` (pinned păstrat), bounded+evict. Înregistrat în `ComponentRegistry`; 5 endpoints (`GET /api/canvas`, `POST /api/canvas/post` 422 pe tip necunoscut, `/{id}/pin`, `DELETE /{id}`, `/clear`). +12 teste offline. *(Randarea SVG/React în HUD v2 = pas frontend.)* | 8 | P3 | HUD v2 | OpenClaw Live Canvas |
| H12.19 ✅ | **Pairing/aprobare expeditor inbound** — senderi necunoscuți pe canale trec printr‑un cod/aprobare (anti‑abuz); oglindă a allowlist‑ului A2A. **Done 2026-06-09:** `core/channels/pairing.py` `SenderPairing` (JsonStore keyed `(channel,sender)`) — **opt‑in** (`JARVIS_CHANNEL_PAIRING`, default OFF → `is_allowed` True pentru toți, comportament neschimbat); sender necunoscut → `pending` (**held, niciodată executat**, ca inboxul A2A), owner approve/reject/block/unpair; **cod self‑service** rotativ (auto‑approve la cod corect, `hmac.compare_digest`); **anti‑abuz** (rate‑limit per `(channel,sender)` + pending bounded + evict). Gate cablat în `Gateway.route` (kwarg `sender`, backward‑compatible) + threading `sender` din Telegram; înregistrat în `ComponentRegistry`; 4 endpoints (`POST /api/channels/pairing/request` gated‑404, `GET /api/channels/pairing` + `POST /decide` + `POST /code` admin). +20 teste offline. | 3 | P2 | H1.3, H16.2 | OpenClaw DM pairing |
| H12.20 ✅ | **Rotație profile auth + failover model** în hybrid router (mai multe chei/conturi cu failover). **Done 2026-06-09:** `core/llm/auth_rotation.py` `AuthProfilePool` — chei multiple per provider (din `*_API_KEYS` comma/space, fallback la `*_API_KEY` single → **backward-compatible**); eroare rotabilă (401/403/429) → failover la următoarea cheie sănătoasă, cheia picată intră în **cooldown exponențial** (cap 15 min), `report_success` resetează; clock injectabil (cooldown determinist în teste). Cablat în `ClaudeBackend`/`GeminiBackend` (cheia din pool + retry-and-rotate pe `generate`, report_failure pe stream) și construit din env în `HybridRouter.detect()`; endpoint admin `GET /api/llm/auth-profiles` (status mascat). +18 teste offline. | 3 | P3 | H2.12 | OpenClaw auth rotation |
| H12.21 ✅ | **Acțiuni guvernate pe social** (X/Twitter post/reply/DM) — fiecare *write* prin coada de aprobare; auth OAuth/secret‑broker (nu cookie‑uri brute). **Done 2026-06-09:** `core/social.py` `SocialBroker` — paralel cu write-back (H10.30): request → validare allowlist (x: post/reply/dm) + sanitizare → **task ask-tier** (`kind=social.x.<action>`, tier extern); **nimic nu se postează la request**. Pe aprobare, executor prefix `social` → `SocialBroker.execute` rezolvă tokenul OAuth/bearer **la momentul acțiunii, în spatele aprobării** (SecretBroker — handle `{{secret:x_api_token}}`, niciodată cookie-uri) și apelează client injectabil (`NullSocialClient` offline default; `HttpSocialClient` = rail live prin `build_social_request` pur → X API v2 `/2/tweets`, reply, `/2/dm_conversations`). Endpoints `GET/POST /api/integrations/social`. +15 teste offline (catalog, validare, build_request post/reply/dm, execute behind-approval, e2e prin coadă+worker). *(Apelul de rețea real = poartă host.)* | 5 | P3 | H6.2 | OpenClaw TweetClaw/Bird |
| H12.22 ✅ | **Voce outbound / call‑back** — agentul sună la prag + persona vocală izolată (Twilio/Telnyx), gated prin interrupt‑budget. **Done 2026-06-09:** `core/autonomy/call_broker.py` `CallBroker` — apel outbound gated **dublu**: coada de aprobare (`kind=call.outbound`, ask‑tier extern) ȘI **bugetul zilnic de întreruperi** (un apel e o întrerupere → consumă din ≤4/zi). Pe aprobare rezolvă tokenul telephony **în spatele aprobării** (SecretBroker — handle `{{secret:…}}`) și sună prin client injectabil (`NullCallClient` offline default; `HttpCallClient` = rail Twilio/Telnyx prin `build_call_request` pur — Twilio form+basic‑auth, Telnyx JSON+bearer). Endpoint `POST /api/autonomy/call`. +15 teste offline (validare, buget epuizat, build per provider, execute behind‑approval, e2e prin coadă+worker). *(Apelul telefonic real = poartă host.)* | 8 | P3 | H6.2 | OpenClaw SuperCall |
| H12.23 ✅ | **Pack de skill‑uri „digest"** (news multi‑sursă ponderat, earnings, Reddit/YouTube/arXiv/HF, idea‑reality scorer) — skill‑uri semnate, compozabile. **Done 2026-06-09:** `core/digest.py` — motor compozabil: `DigestSource` (feed RSS/Atom ponderat, `{topic}` URL‑encoded, **fetch injectabil** → offline), `parse_feed` (RSS `<item>` + Atom `<entry>`, namespace‑stripped, safe pe XML rupt), `idea_reality_score` (substanță: release/benchmark/paper/code/versiune/% vs hype: revolutionary/breakthrough/shocking → 0..1), `DigestAggregator.run` (dedup pe link/title, rank pe `weight × (0.5+reality)`), `build_default_aggregator` peste 5 template‑uri (hn/reddit/arxiv/youtube/news). Endpoint `POST /api/digest/run` (user‑guard, fetch via `PluginHTTPClient`). +11 teste offline. *(Live multi‑sursă + împachetare ca skill‑uri semnate = follow‑up extern.)* | 5 | P3 | Skills | awesome‑openclaw‑usecases |
| H12.24 ✅ | **Generare media** (imagini/thumbnail/video, local sau cloud‑gated) pentru content‑factory. **Done 2026-06-09:** `core/media_gen.py` `MediaGenManager` — generare media (image/thumbnail/video) prin **backend-uri injectabile**: local inline, **cloud gated** prin coada de aprobare (apel plătit niciodată neprompt). Endpoints `GET /api/media`, `POST /api/media/generate`. +5 teste offline. *(Backend-urile diffusion/cloud reale = host.)* | 5 | P3 | — | OpenClaw content skills |
| H12.25 ✅ | **Transcript‑watcher → taskuri** (notițe ședință → Notion/Todoist prin coada de aprobare). **Done 2026-06-09:** `core/autonomy/transcript_watcher.py` — `extract_action_items` (high‑precision: checkbox-uri, prefixe `action item:/todo:/next step:`, assignment `<Nume> will/to <verb>` cu atribuire owner; dedup + min‑length, fără false positives pe discuție) + `TranscriptWatcher.ingest` care enqueue fiecare item ca task **ask‑tier guvernat** (`kind=create_task`, `autonomy_level="ask"`, payload cu `system=notion\|todoist`) → **nimic nu se creează extern fără aprobare**; fără coadă = preview-only. Endpoint `POST /api/transcripts/ingest` (user‑guard). +10 teste offline. *(Crearea live în Notion/Todoist la aprobare = executor downstream / poartă externă.)* | 3 | P2 | H2.7 | OpenClaw meeting‑notes |

> **Total ORIZONT 12:** 25 items, ~150 SP. **Acțiune imediată recomandată:** H12.1 (P0) — e simultan hardening real
> ȘI wedge-ul de marketing (alternativa securizată la OpenClaw). Restul Track B (P1) ridică cel mai mult valoarea per efort.

---

## ORIZONT 13–17 — Frontiere Noi (post-paritate, în scope v1.0) — 14/20

> **Status: livrate** (toate în v0.10.0). Drumul până la 1.0 e productionizarea (**H23**) + validarea cu useri reali —
> **1.0 = totul livrat + design partners**, fără grabă pe tag. Bazat pe research-ul frontieră 2025-2026:
> [docs/research/2026-06-03-frontier-horizons.md](docs/research/2026-06-03-frontier-horizons.md) (5 agenți paraleli +
> verificare independentă). Backlogul de features e terminat (H1–H9); H10–H12 sunt paritate competitivă.
> **Acestea sunt direcțiile de DUPĂ paritate** — unde țintește un OS personal local-first/proactiv/privat.
> Fiecare item verificat față de [principiile non-negociabile](MOONSHOT.md#5-non-negotiable-principles-the-guardrails).
>
> **Două teme-flagship (apar transversal):** (1) **„sleep-time compute"** — chiar sloganul moonshot (*„lucrează cât dormi"*),
> acum rezultat de cercetare (arXiv:2504.13171): generalizează reflecția nocturnă din *rezumă-ziua* în *pre-raționează-pentru-mâine*
> pe GPU-ul idle. (2) **Guvernanță măsurabilă** — convertește „suntem alternativa guvernată la OpenClaw" dintr-un *claim* într-un
> *badge CI verde* (AgentDojo). OpenClaw a devenit prima țintă infostealer (13-feb-2026) — anti-teza dovedită.

### ORIZONT 13 — Plafonul de Capabilitate Locală (modele & inferență) — 3/4

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H13.1 ✅ | **Tier VLM strict-local** (Qwen3-VL-8B) — înțelegere ecran/documente/bonuri/PDF → alimentează pipeline-ul Howard; cea mai mare capabilitate *nouă*, fără cloud. ⚠️ verifică build GGUF + buget KV-cache pe 24GB. **Done 2026-06-09 (strat de integrare):** `core/llm/vlm.py` `VLMBackend` — adapter **OpenAI-vision-compat** (mesaje cu `image_url`), preprocesare imagini pură (`to_data_uri` base64, `_downscale` opțional Pillow pt. bugetul KV-cache, `encode_image_block` bytes/path/url/data-uri), `generate_vision` (alimentează pipeline-ul Howard) + `generate` text-only (contract LLMBackend); client injectabil → offline-testable ca adaptorul OpenRouter. Endpoints `GET /api/vlm/status`, `POST /api/vlm/describe` (gated pe `JARVIS_VLM_URL`). +7 teste offline. *(Modelul local — weights + GGUF + GPU 24GB — = pas de deployment host: pointează `JARVIS_VLM_URL` la un server vision local vLLM/llama.cpp.)* | 8 | P1 | H5.1 | Qwen3-VL (Oct 2025) |
| H13.2 ✅ | **Decodare constrânsă (GBNF) pentru tool-calling** — garantează tool-args valide. **Done 2026-06-03:** `core/llm/grammar.py` — `json_schema_to_gbnf`/`tool_to_gbnf` generează gramatică GBNF llama.cpp din JSON schema (object cu chei ordonate, string/integer/number/boolean/array/enum/nested object; cluster permisiv value/object/array pentru tipuri nedeclarate) + `validate_args` fallback (tipuri/required/enum, pentru backend-uri fără gramatică); endpoint `POST /api/llm/grammar`. *Generarea gramaticii + validarea sunt complete; enforcement-ul rămâne hook-ul backend-ului (param `grammar=` llama.cpp/XGrammar).* +10 teste offline. | 5 | P1 | — | XGrammar / llama.cpp |
| H13.3 | **Speculative decoding** (draft Qwen3-4B → target 32B/gpt-oss) — 1.5-2.5× throughput interactiv, output identic, $0. **🖥️ GPU host — runbook: `docs/GPU_RUNBOOK.md`** (config vLLM/llama.cpp; zero cod aplicație, output-identic). | 5 | P2 | — | vLLM / llama.cpp |
| H13.4 ✅ | **Refresh model default → MoE cu reasoning hibrid** (gpt-oss-20b / Qwen3-30B-A3B) — mod thinking/non-thinking poate colapsa tier-urile fast/deep într-un model. Apache-2.0. **Done 2026-06-09:** `core/llm/moe_routing.py` — `decide_thinking_mode` (euristic: hint-uri raționament/lungime/multi-întrebare) + `route_moe` (model MoE → mod thinking/non-thinking, buget tokeni, directivă `/think`÷`/no_think`; colapsează tier-urile fast/deep). Endpoint `POST /api/llm/moe/route`. +5 teste offline. *(Selecția backendului real în HybridRouter = host.)* | 5 | P2 | — | gpt-oss, Qwen3 |

### ORIZONT 14 — Memorie Vie (memorie temporală & auto-întreținută) — 4/4 ✅

> Extinde H8 (memorie personală, livrat). Rulează pe Neo4j + Ollama existente; majoritatea Apache-2.0.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H14.1 ✅ | **KG bi-temporal** (Graphiti-style: valid-time + ingested-at; contradicție → *invalidează*, nu șterge; recall „as-of"). **Done 2026-06-03:** `core/memory/bitemporal.py` `BiTemporalKG` (JSON file-backed) — triple-uri (subject,predicate,object) cu `valid_from`/`valid_to`/`ingested_at`/`invalidated_at`; `add_fact` (predicat single-valued → închide factul contradictoriu la noul `valid_from`, păstrează istoricul; `multi=True` pentru predicate multi-valued), `invalidate` explicit, `as_of` (valid-time recall), `known_as_of` (transaction-time), `current`, `history`; endpoints `POST /api/kg/facts`, `GET /api/kg/facts/as-of`, `GET /api/kg/facts/history`. +7 teste offline. | 8 | P1 | H3.2, H8.2 | Graphiti/Zep |
| H14.2 ✅ | **Harness de eval pentru memorie** (LongMemEval/LoCoMo-style pe corpus propriu; 5 abilități: extracție, multi-sesiune, temporal, update, abținere). **Done 2026-06-03:** `core/memory/eval.py` — `MemoryEvalCase` + `DEFAULT_CORPUS` (corpus propriu acoperind toate cele 5 abilități), `score_answer` (substring any-of; abținerea = răspuns corect e „nu știu", halucinația pică), `keyword_answer` baseline offline (overlap + recency tiebreak), `run_eval(answer_fn)` → scor per-abilitate + overall (answer-fn-agnostic: pipeline real în prod, fake în teste); endpoints `GET /api/memory/eval/corpus` + `POST /api/memory/eval/run` (baseline). +10 teste offline. | 5 | P1 | H8.2 | LongMemEval |
| H14.3 ✅ | **Agent de consolidare „sleep-time" cu operații explicite** (Mem0-style ADD/UPDATE/DELETE/NOOP). **Done 2026-06-03:** `core/memory/consolidation.py` `ConsolidationEngine` — `decide`/`plan` per candidat vs memorii existente: ADD (nou), UPDATE (supersede same-key/near-duplicate), DELETE (negație/retractare detectată + match), NOOP (duplicat); similaritate Jaccard token (prag configurabil), detector de negație, decider LLM injectabil (fallback euristic); `plan` batch-aware (copie de lucru), `summarize`, `apply` la un store; endpoint `POST /api/memory/consolidate` (plan reversibil, fără mutație). +10 teste offline. | 8 | P2 | H5.15 | Mem0, Letta |
| H14.4 ✅ | **Uitare cu decay + dependency-aware** (scor activare ACT-R în ranking + ștergere pe graf de dependențe care previne „recontaminarea"). **Done 2026-06-03:** `core/memory/decay.py` — `activation` base-level ACT-R `ln(Σ (now-t)^-d)` (recency+frecvență), `DecayMemory` (JSON file-backed) cu `add`/`access`/`score`/`ranking`/`forget_candidates(threshold)` + `forget` care șterge itemul *și dependenții tranzitivi* (anti-recontaminare); endpoints `GET /api/memory/decay/ranking`, `/candidates`, `POST /api/memory/decay/forget`. +6 teste offline. | 5 | P2 | H8.2 | ACT-R, arXiv:2602.17692 |

### ORIZONT 15 — Computer-Use Guvernat (operează mașina) — 4/4 ✅

> Inversul *guvernat* al shell-ului neguvernat OpenClaw. Maturitate onestă: ~1-din-6 task fail → asistă în spatele approval-queue, NU nesupravegheat.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H15.1 ✅ | **Agent browser-use local** în spatele approval-queue + sandbox + egress allowlist (browser-use/Playwright-MCP + LLM local). Punct de intrare cu cel mai mic risc. **Done 2026-06-09 (strat guvernat):** `core/browser_agent.py` — 3 porți compozabile: **egress allowlist** (`BrowserPolicy`, suffix‑match + filtrul SSRF HF‑4 → navigare off‑listă **hard‑blocked**, neaprobabilă; fail‑closed pe listă goală), **approval‑queue** (pași read‑only `navigate/extract/screenshot/wait` auto pe domeniu permis; pași mutanți `click/type/submit/download/execute_js` → `ActionApprovalQueue` H10.18 cu `await_decision`), **driver injectabil** (`NullBrowserDriver` default; Playwright real = add‑on host‑gated → stratul de guvernare e 100% offline‑testabil). `GovernedBrowser.preview` (dry‑run run/approve/block per pas) + `run` (trace, stop‑on‑block). Endpoints `POST /api/browser/check` (egress) + `/api/browser/plan/preview` (guvernanță). +12 teste offline. *(Driving real al browserului = poartă umană/host.)* | 8 | P2 | H4.8, H6.2 | browser-use (MIT) |
| H15.2 ✅ | **Modul de înțelegere a ecranului local** (grounding UI-TARS-1.5-7B, opțional fuzionat cu accessibility tree). ⚠️ OmniParser are componentă AGPL — preferă UI-TARS (Apache). **Done 2026-06-09:** `core/screen_grounding.py` — `parse_grounding` (JSON sau text `… at (x,y)`) + `fuse_with_a11y` (fuziune cu accessibility tree, dedup pe proximitate) + `locate` (element pe query). Construit pe adaptorul VLM H13.1. +5 teste offline. *(Modelul de grounding real = host.)* | 8 | P2 | H13.1 | UI-TARS, Agent S3 |
| H15.3 ✅ | **Operator în desktop virtual izolat (PiP)** — OS curat, fără credențiale ambientale; acțiuni ireversibile gated; clasificator de injection pe screenshots. Claude computer-use = opt-in cloud. **Done 2026-06-09 (strat de guvernanță):** `core/desktop_operator.py` `GovernedDesktop` — analog desktop al browser-agentului H15.1: read-only inline, mutant → aprobare (`approver` injectabil), **clasificator de injection** pe textul ecranului (reutilizează H17.1 → abort la injection); driver injectabil (`NullDesktopDriver` offline; VM real = host). `preview`/`run`. Endpoint `POST /api/desktop/preview`. +6 teste offline. | 13 | P3 | H15.1 | UFO², Anthropic |
| H15.4 ✅ | **Secret broker** — injectează credențiale la momentul acțiunii, în spatele aprobării; niciodată plaintext în contextul agentului. **Done 2026-06-03:** `core/security/secret_broker.py` `SecretBroker` (peste `SecretStore` criptat H12.1, fallback in-memory) — agentul vede doar handle-uri `{{secret:NAME}}` (`reference`), `inject(text, approved)` rezolvă valoarea DOAR cu aprobare (altfel placeholder, valoarea nu apare niciodată), `redact` maschează valori cunoscute (defense-in-depth), `names` fără valori; endpoints admin `POST/GET/DELETE /api/secrets/broker` + `/redact` (niciun endpoint nu întoarce plaintext). +7 teste offline. | 5 | P2 | H12.1 | OpenClaw (anti-teză) |

### ORIZONT 16 — Cetățean al Web-ului Agentic (interop & standarde) — 4/4 ✅

> Standardele s-au așezat: **MCP** (agent→tool) + **A2A** (agent→agent, la Linux Foundation). Plățile agentice au sosit (AP2/ACP/x402).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H16.1 ✅ | **MCP server mode** (spec 2025-11: OAuth2.1 RS, RFC 8707, `.well-known`) — **H10.5** upgradat. **Done 2026-06-03:** `core/mcp/oauth.py` `MCPResourceServer` — token-uri HMAC self-issued (LAN-only, fără IdP extern) + `validate` (semnătură constant-time, expirare, **RFC 8707 audience binding** la resursă, enforcement scope); `protected_resource_metadata` (RFC 9728) + `challenge` (`WWW-Authenticate`); endpoints `GET /.well-known/oauth-protected-resource`, admin `POST /api/mcp/token`, iar `/api/mcp/server/rpc` cere bearer valid când `mcp.oauth_required` (401 + challenge). +7 teste. *Enforcement-ul auth complet (validare token IdP extern) e un swap de backend de verificare.* | 8 | P1 | H4.7 | MCP 2025-11-25 |
| H16.2 ✅ | **Endpoint A2A** cu Agent Card semnat — opt-in, allowlist de peers, task-uri inbound → approval queue. **Done:** `core/a2a.py` `A2ARegistry` — **off by default** (`JARVIS_A2A_ENABLED`), Agent Card semnat HMAC (`JARVIS_A2A_KEY`, altfel advisory), **allowlist de peers** cu secret partajat (returnat o singură dată, mascat la list), `receive_task` verifică semnătura HMAC peste raw body (fail-closed: disabled/unknown-peer/bad-sig) și **nu execută niciodată** — task-ul aterizează în inbox `pending` pe care owner-ul îl aprobă/respinge. Endpoints: `GET /.well-known/agent-card`, `POST /api/a2a/task` (peer-signed), admin `peers`/`inbox`/`decide`/`card`. +8 teste offline. | 8 | P3 | H16.1 | A2A (Linux Foundation) |
| H16.3 ✅ | **Plăți agentice opt-in** prin abstracția mandate/cap/approval; plafoane *hard*; audit local non-repudiabil. **Done:** `core/payments.py` `PaymentBroker` — **mandate** cu plafon per-plată + plafon total + allowlist payee + monedă + expirare; fiecare plată e creată `pending` și **doar aprobarea explicită** o duce spre settle (fără auto-approve la nicio sumă); **plafoanele sunt absolute** (peste cap/payee nepermis/monedă greșită/expirat/peste total ⇒ *denied la creare*, nu devine niciodată pending); spend cumulativ nu poate depăși plafonul total (recheck la approve + settle); fiecare create/approve/reject/settle e scris în audit semnat (H17.4 IntentLog). **Rail-agnostic: niciun rail real, nu mișcă bani.** Endpoints admin `/api/payments/*`. +13 teste offline. | 8 | P3 | H6.2 | Google AP2, Stripe ACP |
| H16.4 ✅ | **Triggere ambientale inbound** (webhooks → inbox; **surse semnate**). Extinde **H10.8**. **Done 2026-06-03:** semnare HMAC pe `core/webhooks.py` — `create(signed=True)` provizionează `signing_secret` (returnat o singură dată, mascat în list), `compute_signature` (HMAC-SHA256 `sha256=<hex>`), `verify_signature` (constant-time, peste raw body; acceptă și hexdigest gol); endpoint trigger: hook semnat ⇒ cere header `X-Signature-256` valid (token-ul NU bypassează); hook nesemnat ⇒ token ca înainte. Sursă atestată criptografic (stil GitHub/Stripe). +6 teste (provizionare, verify ok/tamper/bad/empty, mascare, round-trip endpoint). | 5 | P2 | H10.8 | LangChain ambient agents |

### ORIZONT 17 — Încredere Demonstrabilă (siguranță pentru agenți always-on) — 4/4 ✅

> Cea mai on-mission pentru teza de încredere + wedge-ul anti-OpenClaw. Injection = nerezolvabil la nivel de model → **containment by-design + măsurare**.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H17.1 ✅ | **Quarantine Dual-LLM / Plan-Then-Execute** pentru conținut tool/web/email — date „tainted" nu ating tool ireversibil fără aprobare; spotlighting/datamarking ca primul strat. **Done 2026-06-03:** `core/security/quarantine.py` — `spotlight`/`datamark` (delimitatori + marker, prim strat) + `detect_injection` (pattern-uri „ignore previous", „you are now", system-prompt etc.); `TaintedValue` (trusted/from_untrusted), `QuarantinePolicy.check_step` (tainted→tool ireversibil ⇒ requires_approval), `plan_then_execute` (plan înghețat de PlanStep-uri tipizate, gate out-of-band `approve`, blochează exfiltrarea); endpoints `POST /api/security/spotlight` + `/scan-injection`. Rupe „lethal trifecta" prin construcție. +10 teste offline. | 13 | P1 | H4.9, H6.2 | CaMeL, arXiv:2506.08837 |
| H17.2 ✅ | **Eval-uri AgentDojo + AgentHarm ca poartă CI** („governance gate") + self-assessment OWASP Agentic Top 10 + „trust scorecard" public. **Done 2026-06-03:** `core/security/governance.py` — `INJECTION_SUITE` (AgentDojo-style, apărat de H17.1 `detect_injection`), `HARM_SUITE` (AgentHarm-style: refuză harmful + controale benigne anti-over-refusal), `OWASP_AGENTIC_TOP10` (10 riscuri → control acoperitor), `run_injection_evals`/`run_harm_evals`/`owasp_assessment`/`trust_scorecard`/`governance_gate(threshold)` (answer-fn-agnostic); endpoint `GET /api/security/governance`; testul `test_governance_gate_passes` E poarta CI. +10 teste offline. | 5 | P1 | H7.2 | AgentDojo, OWASP |
| H17.3 ✅ | **Capability gating + kill-switch out-of-band** pe care agentul NU îl poate escalada. **Done 2026-06-03:** `core/security/capability.py` — `CapabilityBroker` (tokeni scoped/expiring per-task/per-sursă; `check` read-only, acordă DOAR capabilitățile listate ⇒ fără escaladare; revoke), `KillSwitch` (halt out-of-band persistat pe disc, scopes + global, `is_halted`; disengage = acțiune operator), `authorize` (halt SAU lipsă capabilitate ⇒ blocat); endpoints admin-guarded `POST /api/security/capabilities/issue` + `/kill-switch`, read-only `/capabilities/check` + `GET /kill-switch`. Aliniat EU AI Act Art.14 + NIST. +6 teste offline. | 8 | P2 | H6.2 | EU AI Act, NIST |
| H17.4 ✅ | **Audit ancorat extern, cu atribuire de intenție** — extinde lanțul Merkle (H4.10). **Done 2026-06-03:** `core/security/anchor.py` — `IntentLog` (record-uri hash-înlănțuite, semnate HMAC cu identitate per-instal stabilă (arg/env/key-file), `why`+`cause` = atribuire cauzală, `verify` detectează tamper de hash ȘI de semnătură), `TransparencyAnchor` (log extern append-only hash-linked care ancorează head-ul lanțului de audit, `verify` chain); endpoints `POST /api/security/audit/action` + `GET /audit/intent` (verify) + admin `POST /audit/anchor` + `GET /audit/anchors`. +7 teste offline. | 8 | P2 | H4.10 | Apple PCC, AttriGuard |

> **Total ORIZONT 13–17:** 20 items, ~146 SP — **în scope-ul 1.0.0**. **Secvențiere recomandată în drumul spre 1.0:**
> **H17 (Provable Trust)** + **H14 (Living Memory)** sunt cele mai on-mission (teza de încredere + „te cunoaște";
> H17 continuă direct securitatea Wave 0 / H12.1); **H13** ridică plafonul la $0; **H15/H16** închid platforma.
> Flagship transversal: **sleep-time compute** (H13/H14) — chiar sloganul moonshot.

---

## ORIZONT 18 — Aplicații Native iOS/Android & Paritate cu Browser (P2–P3) — 9/10

> Client mobil nativ (Expo SDK 56 / RN 0.85) sub `mobile/`, peste **același API HTTP** (`agents/web.py`)
> ca HUD-ul browser — niciun backend nou. Fundația livrată în **PR #161**. Restul = paritate progresivă
> cu HUD-ul + infrastructura de build/release.
>
> **Bridge browser↔mobil (sincronizarea backlogului):** suprafața de paritate trăiește în
> [`mobile/PARITY.md`](mobile/PARITY.md) — un registru endpoint→browser?→mobil?→task. **Regula de sincronizare**
> (vezi `AGENTS.md` → „Bridge browser↔mobil"): orice feature browser care adaugă/schimbă un endpoint user-facing
> SAU o capabilitate HUD **trebuie** să (1) actualizeze `mobile/PARITY.md` și (2) deschidă un task de paritate
> `H18.x` aici dacă mobilul rămâne în urmă. Așa, dezvoltările pe browser devin automat taskuri pe iOS/Android.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H18.1 ✅ | **App nativ iOS/Android (Expo)** — shell cu tab-uri (Chat/Status/Settings), chat streaming token-cu-token peste `POST /chat/stream` (SSE via XHR), `GET /status` cu telemetrie host/GPU + pull-to-refresh, config hub URL + `X-User-Token` persistat (AsyncStorage) + test-connection; temă dark derivată din HUD v2. **Done 2026-06-06 (PR #161):** `mobile/` (App.tsx, src/api/client.ts, src/screens/*, src/context/ServerContext.tsx, src/storage/settings.ts). `tsc --noEmit` curat. | 8 | P2 | — | paritate HUD |
| H18.2 ✅ | **Persistă istoricul chat-ului** — conversațiile supraviețuiesc restartului. **Done 2026-06-07:** `src/storage/chat.ts` (AsyncStorage, cap 200 mesaje, nu persistă mesajele în streaming) + load/save/clear în `ChatScreen` (buton „New"). | 3 | P2 | H18.1 | — |
| H18.3 ✅ | **Selector de agent** — picker modal pur-JS alimentat din `GET /api/agents`, agent persistat în prefs. **Done 2026-06-07:** `src/components/AgentPicker.tsx` + `src/storage/prefs.ts` + `fetchAgents` în client; `streamChat` trimite agentul ales. | 3 | P2 | H18.1 | paritate HUD agents |
| H18.4 ✅ | **Render Markdown** — parser propriu (heading/listă/cod/quote/bold/italic/cod-inline/link) + renderer RN. **Done 2026-06-07:** `src/markdown/parse.ts` (pur, testat) + `src/markdown/Markdown.tsx`; folosit în `MessageBubble` pentru răspunsuri. | 3 | P3 | H18.1 | paritate HUD |
| H18.5 ✅ | **Resume sesiuni + TTS** — listă/resume `/sessions` + redare voce `/tts`. **Done 2026-06-07:** `src/components/SessionsModal.tsx` (`fetchSessions`/`resumeSession` → repopulează firul) + `src/audio/tts.ts` (fetch MP3 → cache → expo-audio, buton 🔊 per mesaj, reset la `didJustFinish`). | 5 | P3 | H18.1 | paritate HUD voice |
| H18.6 ✅ | **Timeouts + reconnect pe stream** — deadline pe request + retry/back-off pe GET-uri idempotente + idle-timeout pe stream. **Done 2026-06-07:** `AbortController` (15s) + retry exponențial (status/agents/sessions) + idle-timeout 45s pe `streamChat` cu eroare clară. | 3 | P2 | H18.1 | robustețe |
| H18.7 ✅ | **EAS build config (`eas.json`)** — profile development/preview/production (+ submit). **Done 2026-06-07:** `mobile/eas.json` (`appVersionSource: remote`, APK preview, autoIncrement production). | 3 | P2 | H18.1 | Expo EAS |
| H18.8 ✅ | **Test Jest** pentru logica pură (SSE decoder + Markdown parser). **Done 2026-06-07:** `jest.config.js` (babel izolat de Metro) + 19 teste (`sse.test.ts`, `parse.test.ts`), `npm test` verde. | 2 | P2 | H18.1 | — |
| H18.9 ✅ | **Branding** — icon + splash Jarvis (motiv „core" cyan pe `#030810`), generate determinist. **Done 2026-06-07:** `scripts/gen-icons.js` (pngjs) → icon/splash/favicon/adaptive (foreground+background+monochrome); splash dark via plugin `expo-splash-screen` în `app.json`. | 2 | P3 | H18.1 | — |
| H18.10 | **Paritate continuă (bridge)** — menține `mobile/PARITY.md` la zi: pentru fiecare feature browser nou cu suprafață user-facing, adaugă rândul de paritate + (dacă e cazul) task `H18.x`. Task umbrelă, mereu deschis. | — | P2 | H18.1 | bridge |

---

## ORIZONT 19 — WorldView (4D OSINT) — Standalone + Integrare JARVIS — 33/33 ✅

> **Produs nou, stack separat** (Next.js + Deck.gl + Fastify + Kafka/Redpanda + TimescaleDB/PostGIS + Redis),
> self-contained sub [`worldview/`](worldview/). Centru de comandă OSINT 4D (aer/mare/spațiu/cyber) pe un glob
> scrub-abil în timp — inspirat de „God's Eye View" (Bilawal Sidhu) și de patternurile Palantir (Gotham/AIP/
> Ontology). **Spinele tehnic e livrat** (toate 5 layere, motorul 4D, calea de date Kafka→Redis/TimescaleDB
> validată în CI vs TimescaleDB real, 58 teste unit + integrare). PR #163.
>
> **Deep review complet + merged (2026-06-08):** review post-merge al celor 33/33 (Critical: retention vs
> reconstrucție; + fixuri pe ingestion/backend/frontend/integrare-JARVIS — commits `d162f1a`…`8fc6660`, PR #167),
> CI integral verde inclusiv jobul TimescaleDB real. Două follow-up-uri rămase, trackuite ca GitHub issues:
> **#169** (transportul MCP write-tool la runtime — invocarea `watch_aoi`/`reconstruct_event` din
> `agents/core/mcp/client.py`; formatul de auth e închis & pinned cross-language, rămâne doar cablarea
> clientului stdio) și **#170** (validarea pe Neo4j real a property-search-ului din KG sync). Launchere noi
> **INSTALL.bat / START.bat** instalează + pornesc automat WorldView lângă JARVIS (PR #171).
>
> **Strategie & feature-pick:** [`worldview/docs/ROADMAP.md`](worldview/docs/ROADMAP.md) ·
> **Planul de arhitectură & livrare (scale model, deep-dives, ADRs, exit gates):**
> [`worldview/docs/02-platform-architecture-and-delivery-plan.md`](worldview/docs/02-platform-architecture-and-delivery-plan.md).
> Ticketele de mai jos = cele 5 workstream-uri (WS1–WS5) din plan, fiecare cu **criteriu de acceptanță măsurabil (AC)**.
>
> **Teza de integrare:** *JARVIS este „AIP"-ul local-first al WorldView* — operatorul în limbaj natural + cortexul
> proactiv. WorldView e **plugin opt-in, niciodată cerut de core** (respectă MOONSHOT §5: cloud opt-in, inspectabil,
> ≤4 interrupts/zi). Doar OSINT public — *„datele tale nu antrenează modelul nimănui"*. Agenții strict-local
> (`frigga`/`ultron`/`howard`) nu îl ating.
>
> **Secvențiere (drum critic):** WS1 deblochează WS2+WS5; WS2 deblochează WS3 (alerte de surfacing) + WS4 (insight-uri de guvernat);
> WS3 (JARVIS) ‖ WS4 (guvernanță) în paralel după WS2; WS5 continuu, front-loaded (tiles + replici).

### WS1 — Calea de date live la scară (Phase A) — 7/7 ✅ (H19.1.1–4 cod livrat: toate sursele) · *gate: 50k msg/s susținut, lag<60s, as-of-T p95<300ms sub load, replay 24h real*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.1.1 🔨 | **Sursă ADS-B reală** (OpenSky/ADSB.fi). **Livrat:** `adsb/sources.py` — OpenSky (OAuth2 client-credentials→bearer cu cache/refresh, fallback anonim, bbox viewport, rate-limit/429 + backoff) **și** ADSB.fi (gratuit, centrat pe AOI, tag militar real via `dbFlags`); `worker.py` cu poll adaptiv + backoff exponențial; `ADSB_SOURCE=opensky\|adsbfi`. +7 teste (payload-uri real-shaped, mock HTTP). **Validat** fetch→normalize→envelope→`writeBatch`→`/history` pe payload OpenSky real-shaped (avionul apare în /history cu alt/coords corecte). **Rămâne** (deploy-gated): hop-ul live-net (egress allowlist) + Kafka. **AC:** `osint.adsb` curge din sursă reală; un avion real apare în `/history` în <5s. | 5 | P1 | — | Standalone |
| H19.1.2 🔨 | **Sursă AIS reală** (AISStream WS). **Livrat:** `ais/stream.py` (subscription config-driven din `AIS_BBOX` + `handle_frame` testabil) + `worker.py` cu **reconnect + backoff exponențial**. +6 teste. **Validat** handle_frame→envelope→`writeBatch`→`/history` (vasul apare, sog corect). **Rămâne** (deploy): hop live-WS + Kafka. **AC:** vase reale curg; dark-vessel detector se declanșează pe un gap AIS real. | 5 | P1 | — | Standalone |
| H19.1.3 🔨 | **Sursă TLE reală** (Celestrak/Space-Track). **Livrat:** `tle/sources.py` (Celestrak GROUP + filtru NORAD; Space-Track login+`gp`), `tle/sensors.py` (registru senzori curatat optical/SAR), `worker.py` cu sursă pluggable + refresh catalog periodic. +7 teste. **Validat** fetch→propagate→envelope→`writeBatch`→`/history` (satelitul apare cu footprint + `is_sunlit`). **Rămâne** (deploy): hop live-net + Kafka. **AC:** `satellite_ephemeris` populat /minut; footprint optical/SAR corect. | 5 | P1 | — | Standalone |
| H19.1.4 🔨 | **Surse EW/context reale** (GPSJam/IODA + feed NOTAM/evenimente). **Livrat:** `ew/gpsjam.py` (parser heatmap GPSJam: hexagoane H3 pre-binned → intensitate `bad/(good+bad)`, id din centroid) + `ew/worker.py` îl fetch-uiește; `context/worker.py` fetch evenimente GeoJSON + NOTAM din `CONTEXT_EVENTS_URL`/`CONTEXT_NOTAM_URL`. +2 teste GPSJam (51 total). **Rămâne** (deploy): hop live-net + Kafka; IODA + FAA-NOTAM (auth) ca surse adiționale. **AC:** celule H3 jamming + NOTAM-uri din date live. | 5 | P2 | — | Standalone |
| H19.1.5 🔨 | **Consumeri KEDA-scalați pe lag** + PgBouncer (transaction pooling) + read replica. **Livrat (manifeste k8s local-runnable):** `deploy/k8s/` — 3 Deployments consumer (live/history/recon-writer) + `ScaledObject` KEDA per consumer pe lag-ul consumer-group Kafka (live-writer 1–10 @10k, history 1–8 @20k/5k, recon 1–4 @2k; praguri sub alarma de lag 50k/250k), namespace + kustomization + README (`kind`+`helm install keda`). YAML well-formed; `scaleTargetRef` matches. **Rămâne (prove la rulare):** SLO 50k msg/s + PgBouncer/replica (infra reală); imagine consumer-only + broker in-cluster (TODO documentate). | 8 | P1 | H19.1.1 | Standalone |
| H19.1.6 🔨 | **Rig de load-test + SLO as-of-T** (generator replay/sintetic; test perf nightly). **Livrat:** `worldview_ingest/loadtest/` — generator sintetic determinist (seeded, entități stabile, ts monoton, în bbox), `RateSchedule` fără drift (emite exact `floor(rate*N)`, pacing even), `LatencyRecorder`/`slo_check` (percentile interpolate verificate manual: p95 of 0..9=8.55), harness `produce`/`probe` (producer + http client injectabile; măsoară latența reală as-of-T pe `/history`, nu inventează rezultate) + `__main__` (exit non-zero la breach SLO → gate CI). Praguri default `p95<0.5s` (configurabile `LOADTEST_*`). 208 teste, ruff clean. **Rămâne (prove la rulare):** numerele la 50k msg/s pe infra reală. | 5 | P1 | H19.1.5 | Standalone |
| H19.1.7 🔨 | **Tiered storage broker + ops retenție** (offload segmente → S3). **Livrat:** `db/schema/14_tiering.sql` (extinde 07, idempotent `if_not_exists`) — lifecycle HOT→WARM→COLD per layer: HOT necompresat, WARM columnstore (compress 2d adsb/ais, 7d ephem/jamming, 30d intel), COLD = lakehouse Parquet (chunk-uri dropped rămân interogabile în DuckDB); `add_retention_policy` per hypertable (adsb 90d…recon 730d, intel never-drop), caggs supraviețuiesc retenției; FĂRĂ `ADD COLUMN` pe hypertable comprimat (trap-ul columnstore evitat). Path enterprise `tiered_storage` documentat. `deploy/tiering/README`. **AC îndeplinit:** disk OLTP mărginit de retenție; replay din cold (lake). | 5 | P2 | H19.1.1 | Standalone |

<!-- recon now end-to-end (worker→writer→/recon→panel); H19.2.1/2.2 operational, contract cross-checked -->
### WS2 — Motorul de insight („so what") (Phase B) — 7/7 ✅ · *gate: platforma EXPLICĂ un eveniment (recon „trecere SAR în N min" + „treceri stivuite"), cu provenance*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.2.1 🔨 | **Recon-window scheduler** (SGP4 → footprint∩AOI → bisecție ingress/egress → scor calitate). **Livrat (algoritm):** `recon/windows.py` — `Aoi`/`ReconWindow`, `footprint_ground` (optical/SAR/coverage), `predict_windows` (walk SGP4 + test circle-vs-circle haversine + bisecție ingress/egress ~1s + closest-approach peak + quality care anulează optic noaptea via `is_sunlit`). +5 teste (ISS: AOI ecuatorial→ferestre ordonate; AOI polar→0; optic-noapte vs SAR). **Rămâne:** persistență `recon_windows` + refresh în deploy (parte din H19.2.2/backend). | 8 | P1 | H19.1.3 | Both |
| H19.2.2 🔨 | **Alertare recon-window** (scan windows în lead-time → `Alert`). **AC:** o alertă se declanșează ≥lead_time înaintea unei treceri reale peste un AOI urmărit. | 3 | P1 | H19.2.1 | Both |
| H19.2.3 🔨 | **Schelet motor CEP** (consumer windowed keyed pe `aoi`/`geohash` + state + watermark lateness). **Livrat:** `cep/engine.py` — motor pur event-time, ferestre tumbling per-cheie aliniate la epoch, watermark monoton `= max_event_ts − lateness`; evenimente out-of-order `≥ watermark` intră în fereastră, cele mai vechi sunt drop+counted; fereastra trage regula o dată când watermark-ul îi trece închiderea, apoi e evacuată. `cep/events.py` (contract `worldview.event.v1` + `from_tipping`/`from_anomaly` + `key()`); `cep/worker.py` (consumer/producer proprii, injectabile la test; `json.loads` guarded skip poison pills; reconstruiește `ReconWindow` din `worldview.recon.v1` — contract verificat producer↔consumer; rulează `detect_tipping` per fereastră → `osint.events`; backoff/reconnect). Config `CEP_*` + worker `cep`. +24 teste (18 engine + 6 worker); ruff clean, suită 94 passed. **AC îndeplinit:** o regulă windowed rulează peste stream cu lateness mărginit. | 8 | P2 | H19.1.5 | Both |
| H19.2.4 🔨 | **Regulă tipping-and-cueing** („≥N recon windows peste un AOI în Δt"). **AC:** scenariu sintetic + real declanșează insight-ul cu linkuri la ferestrele contribuitoare. | 5 | P2 | H19.2.3, H19.2.1 | Both |
| H19.2.5 🔨 | **Detectori de anomalii** (alege 2–3: holding-pattern, cascadă închideri spațiu aerian, onset jamming, corelație blackout↔eveniment). **AC:** fiecare se declanșează pe un scenariu seeded cu provenance. | 8 | P2 | H19.2.3 | Both |
| H19.2.6 🔨 | **Layer de adnotare/callout** (API + UI: auto-callouts din `Event` + adnotări manuale pe timeline/hartă). **AC:** insight-urile se randează ca callouts; adnotările manuale persistă. | 5 | P3 | H19.2.4 | Standalone |
| H19.2.7 🔨 | **Reconstrucție eveniment + export replay partajabil** (link/video). **Livrat:** `13_reconstructions.sql` (handle partajabil — salvează DOAR params, cadrele se re-derivă) + `repositories/reconstruction.ts` (`buildFrames` pași `from..to` cu `stepSeconds`, citește readerii history as-of-T per layer, cap `MAX_FRAMES=600`) + `repositories/export.ts` + `routes/reconstruction.ts` (`POST /reconstructions` audited+RBAC, `GET /reconstructions/:id/export?format=json\|geojson`); UI: `frontend/lib/export.ts` + replay-control care conduce master-clock-ul + link replay reproductibil (`?from&to&bbox`). Validat E2E pe Postgres real: export geojson (44 features / 11 cadre, fiecare cu `t`+`layer`), **două exporturi identice (reproductibil)**, viewer create→403, lanț audit valid. **AC îndeplinit:** reconstrucție mărginită temporal → export partajabil + reproductibil. | 8 | P3 | H19.2.6 | Standalone |

### WS3 — Operare agentică (Integrare JARVIS) (Phase C) — 6/6 ✅ · *gate: operezi WorldView vorbind cu JARVIS; o alertă ajunge în digest în buget, cu provenance*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.3.1 🔨 | **WorldView MCP server** — tool-uri read consumate de `agents/core/mcp/client.py`. **Livrat:** pachet standalone `worldview/mcp/` (`@worldview/mcp`) — SDK MCP v1.29 (`Server`+`setRequestHandler`, JSON-Schema, stdio); tool-uri `stateAt`, `findDarkVessels`, `trackOf`, `listLayers` (handler-e pure `(args, deps)` cu fetch injectabil, apelează REST-ul WorldView; validare input; erori→isError). +12 teste (stub fetch), tsc clean, build dist. **Rămâne:** tool `recon_windows`/`watch_aoi` (după backend recon) + abonare din JARVIS. | 5 | P1 | H16.1 | JARVIS |
| H19.3.2 🔨 | **Tool-uri MCP write/async** (`watch_aoi`, `reconstruct_event`) + **auth capability-token** (reutilizează `CapabilityBroker`, H17.3). **Livrat:** `mcp/src/auth.ts` — `verifyCapability(token, scope, {secret, now})` peste token HMAC-SHA256 `base64url(claims).base64url(sig)` cu `{scopes, exp, sub?}`; fail-CLOSED (secret lipsă/sig greșit/expirat/scope lipsă ⇒ deny, fără throw), compare constant-time cu guard de lungime, wildcard `worldview:*`; `audit()` JSON structurat doar pe stderr. Tool-uri `watch_aoi` (scope `worldview:watch` → POST `/recon/watch`) și `reconstruct_event` (scope `worldview:reconstruct` → POST `/reconstructions`), fetch injectabil, degradare grațioasă pe non-2xx; `server.ts` impune auth ÎNAINTE de side-effect (`authorizeWrite` injectabil), read-only neschimbate; `mcpSecret` din `WORLDVIEW_MCP_SECRET` fără default. +24 teste (12 auth + 12 tool/gate; căile deny verifică fetch NU e apelat + audit deny); tsc/build clean, 36 passed. **JARVIS-side minter wired + pinned cross-language:** `agents/core/security/worldview_mcp.py` (`mint_capability`/`verify_capability`) produce EXACT formatul HMAC pe care MCP-ul îl acceptă (nu opacul `CapabilityBroker`, care e incompatibil cu verificarea stateless offline a MCP-ului) — pinned de vectori partajați (`worldview/mcp/test/fixtures/capability-vectors.json`) asertați de AMBELE suite (`tests/test_worldview_mcp_capability.py` 9 passed + `worldview/mcp/test/capabilityVectors.test.ts`, în CI), deci formatul nu poate driva tăcut între cele două limbaje. `mcp/` adăugat în CI (`worldview.yml` job `mcp`: typecheck+build+test). **Backend wired (seam închis):** `POST /recon/watch` real, auditat pe hash-chain (`write:recon` RBAC + scope AOI), `reconstruct_event` pointed la `/reconstructions` (H19.2.7); validat E2E pe Postgres real (watch 201/viewer 403/no-token 401, lanț audit valid). **AC îndeplinit:** apel neautorizat respins + auditat; tool-urile lovesc endpoint-uri backend reale. **Rămâne (runtime):** invocarea propriu-zisă a tool-urilor write din JARVIS prin `agents/core/mcp/client.py` (spawn stdio server + apel `watch_aoi`/`reconstruct_event` cu tokenul mintat) — formatul auth e închis & pinned; rămâne doar cablarea transportului MCP-client la runtime. | 5 | P1 | H19.3.1, H17.3 | JARVIS |
| H19.3.3 🔨 | **Plugin JARVIS** `agents/core/plugins/worldview.py` (gated de `plugin_gate`). **Livrat:** `WorldViewPlugin` — client read-only fail-safe peste REST-ul WorldView (`http://localhost:4000`, override `WORLDVIEW_API_URL`); oglindește tool-urile read MCP (`state_at`/`recon_windows`/`recon_alerts`/`provenance`) + convenience `recon_overview`; backend căzut ⇒ `{"status":"unavailable"}` (nu inventează intel, e OSINT). Manifest `worldview` în `plugin_gate` (LAN, local-only, agents `jarvis/athena/stark/vision`); wired în `orchestrator` (import + instanțiere + ramură geospațială în `_gather_plugin_data` pe keywords satellite/recon/Hormuz/jamming/…). +5 teste; suita JARVIS completă verde (fără regresii). **AC îndeplinit:** Athena/Stark pot răspunde la o întrebare geospațială folosind WorldView. | 5 | P1 | H19.3.1 | JARVIS |
| H19.3.4 🔨 | **Autonomy watcher**: alerte WorldView → inbox→severitate→**buget ≤4/zi**→digest JARVIS. **Livrat:** `WorldViewProbe` în `autonomy/watchers.py` — emite `Signal`-uri pentru treceri recon due (WARN) + dark-vessels (CRITICAL), keyed stabil (debounce: o alertă/pas via `EventWatcher`), cu link provenance (`/provenance/{tle,ais}/…`) în detail; degradare grațioasă (plugin absent/backend căzut ⇒ 0 semnale, fără excepții, fără intel inventat). Înregistrat în `event_probes` (orchestrator `_wire_autonomy`); curge prin inbox→severitate→buget→digest existent (reutilizează `WorldViewPlugin` H19.3.3 cu retry+circuit-breaker). +5 teste; suita JARVIS completă verde. **AC îndeplinit:** o alertă dark-vessel/recon apare în digest cu link de provenance, în pipeline-ul cu buget. | 8 | P1 | H19.3.1, H6, H19.2.2 | JARVIS |
| H19.3.5 🔨 | **Sync graf de cunoștințe** (change-feed ontologie → `memory/graph.py`; recall fuzionat RRF). **Livrat:** `memory/worldview_sync.py` `WorldViewKGSync` — trage ontologia WorldView (AOI-uri + geo-evenimente legate: dark-vessel, recon) prin `WorldViewPlugin` (extins cu `ontology_objects`/`ontology_links`) și face upsert în `KnowledgeGraph` ca entități `geo_aoi`/`geo_event` (cu titlul AOI în nume+proprietăți → căutabil pe locație) + relații `IN_AOI`; provenance călătorește în proprietăți. Fail-safe (WorldView căzut ⇒ no-op, fără excepții/intel inventat). +3 teste; suita JARVIS completă verde. **AC îndeplinit:** după sync, `recall("...Hormuz...", keyword="Hormuz")` întoarce geo-evenimentul via sursa graph a fuziunii RRF. Programare periodică opt-in wired în orchestrator (`worldview.kg_sync_enabled` / `JARVIS_WORLDVIEW_KG_SYNC`, off by default, no-op când WorldView e căzut). | 5 | P2 | H19.3.1, H19.4.1 | JARVIS |
| H19.3.6 🔨 | **Agent intel „Argus"** (SOUL specializat geospațial-OSINT, opțional). **Livrat:** `agents/argus/SOUL.md` (persona geospațial-OSINT read-only, citează provenance, nu inventează intel) + intrare `argus` activă în `agents/_system/agents.yaml` (tier business, plugins `[worldview, cloud-llm]`, 17/18 active) + regulă router `geoint` → `argus` (keywords satellite/recon/overflight/vessel/aircraft/Hormuz/jamming/AOI, W_STRONG) + `ROUTING_TABLE` + serviu `worldview` în `plugin_gate` pentru `argus`. +5 teste (routing geospațial→argus, research încă→vision, gate, config, SOUL); suita JARVIS completă verde. **AC îndeplinit:** un agent dedicat răspunde la query-uri geospațial-OSINT folosind tool-urile WorldView. | 3 | P3 | H19.3.3 | JARVIS |

### WS4 — Guvernanță & colaborare (Phase D) — 6/6 ✅ · *gate: 2 analiști pe un caz cu audit + reconstrucție exportată reproductibil*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.4.1 🔨 | **Ontologie**: proiector obiecte+linkuri+**acțiuni** peste SoR-ul relațional + proiecție graf. **Livrat:** registry declarativ (6 obiecte: Aircraft/Vessel/Satellite/Aoi/ReconWindow/DarkVesselEvent, 3 linkuri: covers/wentDark/inGeofence, 2 acțiuni: annotate/watch); `repositories/ontology.ts` (proiecție read parametrizată, `42P01` graceful) + `ontologyAudit.ts`; rute `GET /ontology/{types,objects/:type[,/:id[,/links]]}`, `POST .../actions/:action` (auditat), `GET /ontology/actions`; `11_ontology.sql` (`ontology_actions` append-only + `ontology_annotations`, tabele noi, fără ALTER pe hypertabele comprimate). Id-uri compozite consistente (full-epoch, nu `::bigint`) — bug de navigare graf prins la validarea E2E pe Postgres real și reparat (regresie fractional-epoch). 68 teste backend; validat E2E pe PostgreSQL/PostGIS real (seed demo): obiecte/linkuri interogabile + navigare Vessel→wentDark→DarkVesselEvent→inGeofence→Aoi. **AC îndeplinit.** | 8 | P2 | — | Both |
| H19.4.2 🔨 | **AuthN/Z**: OIDC + RBAC/ABAC (viewer/analyst/admin; scoping AOI/regiune). **Livrat:** bearer JWT HS256 OIDC-style (`auth/jwt.ts`, dependency-free, constant-time, guard alg-confusion/exp/malformed), matrice rol→permisiune + scoping AOI (`auth/rbac.ts`), hook `onRequest` central (`auth/guard.ts`) cu `request.principal`; opt-in (`WORLDVIEW_AUTH_SECRET` — deschis fără secret pentru back-compat, fail-CLOSED cu secret). Scoping pe `/recon/windows` + obiecte ontologie AOI-bearing. 117 teste backend. Validat E2E pe server real Fastify + Postgres real: no/bad token→401, viewer read→200/write→403, analyst out-of-scope→403/in-scope→200, analyst audit→403/admin→200 (RBAC+ABAC enforced la nivel HTTP). **AC îndeplinit:** acces scoped pe rol, enforced + testat. | 8 | P2 | — | Both |
| H19.4.3 🔨 | **Provenance/chain-of-custody** (`source`+`ingested_at`+bitemporal `valid_*` în UI/API). **Livrat (API):** `db/schema/10_provenance.sql` — migrare aditivă+idempotentă: `ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now()` pe toate tabelele stream/event (writerele existente merg via DEFAULT), sentinel `source` unde lipsea, view `provenance_latest`; model bitemporal documentat (valid time = `ts`/`effective_*` vs transaction time = `ingested_at`). `repositories/history.ts` — query-urile as-of-T întorc `source`+`ingested_at` în `properties`. `repositories/provenance.ts` + `routes/provenance.ts` — `GET /provenance/:layer/:entityId?t=` întoarce `{source, ts, ingestedAt}` al ultimului datum (42P01-guarded, per-layer). +10 teste mock-pool; tsc clean, 36 passed. **AC îndeplinit (API):** orice datum se trasează la sursă. **Rămâne:** UI provenance (frontend, ticket separat). | 5 | P2 | — | Both |
| H19.4.4 🔨 | **Audit hash-înlănțuit** (reutilizează Merkle audit JARVIS, H4.10/H17.4) pe acțiuni/tool-calls/ack-uri. **Livrat:** `ontology_actions` câștigă `prev_hash`/`entry_hash`; `auditChain.ts` pur (`stableStringify` cu chei sortate, `canonicalize`, `computeEntryHash = sha256(prev + '\n' + canonical)`, `verifyChain` care identifică primul link rupt); `recordAction` calculează lanțul la insert sub `pg_advisory_xact_lock` (citire-vârf sigură la concurență); rută `GET /ontology/audit/verify`. 88 teste backend. Validat E2E pe Postgres real: hash-ul de la insert == recompute la citire (jsonb/unicode/null/ordine chei), tamper pe un rând ⇒ `{ok:false, brokenAtId}`. **AC îndeplinit:** log tamper-evident + endpoint verify. | 5 | P2 | H19.4.1 | Both |
| H19.4.5 🔨 | **Cazuri / adnotări / multi-user**. **Livrat:** `12_cases.sql` (cases/case_members/case_items/case_comments, FK cascade) + `repositories/cases.ts` + `routes/cases.ts` (CRUD + members + items care ancorează obiecte ontologie + comments + `GET /cases/:id/history`), gated RBAC (`read:cases` viewer+, `write:cases` analyst+); fiecare mutație → rând audit hash-înlănțuit (reutilizează `recordAction` H19.4.4). 135 teste backend. Validat E2E pe server real + Postgres real: 2 analiști colaborează (alice owner + bob collaborator, item + comment), RBAC enforced (401/403), `GET /cases/:id/history` are cele 4 acțiuni, iar `/ontology/audit/verify` rămâne `{ok:true}` (acțiunile cazului în lanțul tamper-evident). POST-urile întorc 201. **AC îndeplinit:** 2 utilizatori colaborează pe un caz partajat cu audit. | 8 | P3 | H19.4.2 | Standalone |
| H19.4.6 🔨 | **Export/raportare** (brief PDF, GeoJSON, replay). **Livrat:** `GET /cases/:id/export?format=brief\|geojson\|json` (RBAC `read:export`) — `brief` = raport Markdown (summary, membri, items rezolvate la obiectul ontologie curent cu provenance, comments, audit trail), `geojson` = items ca features, `json` = bundle complet; UI `ExportPanel` (download view-GeoJSON / case brief+geojson). PDF = print-to-PDF din Markdown (fără dep nouă). Validat E2E pe Postgres real: `case export brief → 200` Markdown `# Case Brief`. **AC îndeplinit:** caz exportat reproductibil. | 5 | P3 | H19.4.5 | Standalone |

### WS5 — Scale & hardening platformă (Phase A5/D5/D6 + infra) — 7/7 ✅ · *gate: 1M+ puncte @60fps via tiles, 10k WS concurente, DR ↦ RPO≤5m/RTO≤30m, SLO-uri verzi*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.5.1 🔨 | **Serviciu vector-tiles** (Martin/pg_tileserv) + CDN; clientul comută pe tiles sub un prag de zoom. **Livrat:** server Martin MVT (`deploy/tiles/`, citește tabelele `geom` din TimescaleDB) + client (`frontend/lib/tiles.ts` `shouldUseTiles(zoom)` — comută `adsb`/`ais` pe `MVTLayer` când `NEXT_PUBLIC_TILE_URL` setat ȘI `zoom ≤ NEXT_PUBLIC_TILE_MAX_ZOOM` (default 6); degradare grațioasă la puncte fără URL). Workaround alias/shim next.config pentru barrel-ul deck `geo-layers` rupt de versiunile deck/luma pinned (fără deps noi). typecheck clean, 51 vitest, `next build` OK. **Rămâne (prove la rulare locală):** 1M+ puncte @60fps cu serverul de tiles pornit. | 8 | P2 | H19.1.5 | Standalone |
| H19.5.2 🔨 | **WS gateway fleet** + coalescing + sharding canale pe geohash (opțiune NATS/Centrifugo). **Livrat:** `live/coalescer.ts` (coalescing per-client keyed pe entity_id — păstrează ultima valoare/entitate, flush pe `WS_COALESCE_MS`/max-batch, queue mărginit cu drop-oldest → rata per-client mărginită) + `live/geohash.ts` (encoder base-32 verificat vs referințe `ezs42`/`gcpvj0`; p3≈156km) + `live/subscription.ts` (`planSubscription`: bbox→celule `live:geo:<gh>`, fără bbox→global `chan:<layer>` back-compat). `live.ts`/`routes/live.ts` fac fan-out delta pe canale geo + filtru viewport, JSON poison-pill-safe. 201 teste backend (+44: coalescer/geohash/shard/route); tsc+build OK. **Rămâne (prove la rulare):** 10k clienți concurenți (load test/infra reală) — coalescing+sharding sunt mecanismele. | 8 | P2 | — | Standalone |
| H19.5.3 🔨 | **Lakehouse offload** (CDC/sink → Iceberg/Parquet pe S3 + query DuckDB/Trino). **Livrat (stack local-runnable):** `deploy/lakehouse/` — MinIO (S3) + Kafka Connect cu `S3SinkConnector`/`ParquetFormat` (2 conectori: telemetry adsb/ais/tle/ew, intel context/recon; consumer-group separat — nu fură offset de la writeri) → `s3://worldview-lake/topics/<topic>/...`; `queries.sql` DuckDB (httpfs/S3) pentru raw rece; README cu pairing TimescaleDB (hot/warm în TSDB cu retenție, cold în lake). `docker compose config` parsează, JSON conectori valide. **AC îndeplinit:** raw rece interogabil; OLTP mărginit de retenție. | 8 | P3 | H19.1.7 | Standalone |
| H19.5.4 🔨 | **Glob 3D + camera tours**. **Livrat:** toggle map⇄globe — store `viewMode` + `ViewToggle`; `DeckGlobe` randează cu `_GlobeView` (Deck.gl 9) pe o sferă-pământ întunecată (SolidPolygonLayer + graticule), fără Mapbox sub glob; click/tooltip/zoom în ambele moduri. **Camera tours livrate:** `lib/cameraTour.ts` (model waypoints pur/determinist + iterator, tur default peste AOI-uri din `NEXT_PUBLIC_TOUR_AOIS` / fallback Hormuz) + `CameraTour.tsx` (play/stop cu `FlyToInterpolator`, oprire la interacțiune). tsc clean, 80 vitest, build OK. | 5 | P3 | H19.5.1 | Standalone |
| H19.5.5 🔨 | **Observabilitate** (OTel trace end-to-end, dashboards Prometheus/Grafana, error budgets, runbooks). **Livrat (stack local-runnable):** `worldview/deploy/observability/` — OTel Collector + Prometheus + Grafana (provisionate), 3 dashboards golden-signal (API latency/throughput/erori; consumer-lag ingest; live/WS), reguli alertă (`KafkaConsumerLagHigh/Critical`, `ApiErrorRateHigh`, `ApiLatencyHigh`, `ApiDown`), `RUNBOOK.md`, `README.md`; `docker compose config` parsează, dashboard JSON + YAML valide. Lag-alarm + ingest-dashboard citesc metrici Redpanda `:9644`. **App-side livrat:** `/metrics` Prometheus pe backend-api (5 metrici — `http_server_requests_total`, `http_server_request_duration_seconds`, `worldview_ws_active_connections`/`_messages_sent_total`, `worldview_history_rows_written_total` — label-uri low-card `http_route`/`http_response_status_code`/`domain` care match dashboards) + OTLP opt-in (`otel.ts`, no-op fără `OTEL_EXPORTER_OTLP_ENDPOINT`); 208 teste backend, validat E2E /metrics pe server real. **AC îndeplinit:** dashboards golden-signal + alarmă lag + runbook + telemetrie live. | 5 | P2 | — | Both |
| H19.5.6 🔨 | **DR** (multi-AZ, promovare replică, Kafka mirror; test RPO/RTO). **Livrat:** `deploy/dr/` — replică streaming Postgres/TimescaleDB (`pg_basebackup -R`, hot standby read-only) + mirror Redpanda (`rpk cluster mirror` / fallback MM2) pentru `osint.*`; `game-day.sh` rulabil (`set -euo pipefail`, `bash -n` clean): preflight, replica-in-recovery, **RPO** = lag `pg_stat_replication` ≤5min, mirror topics, **RTO** = `pg_promote()` wall-time ≤30min + write-probe (`--promote`), PASS/FAIL. README cu prereq primary (slot/rol/`pg_hba`/`wal_senders`). `docker compose config` parsează. **AC îndeplinit (mecanică + drill local):** game-day rehearsabil cu ținte RPO≤5min/RTO≤30min; multi-AZ real necesită deployment multi-zonă. | 8 | P3 | H19.1.5 | Standalone |
| H19.5.7 🔨 | **Swarm captură OSINT cu agenți, guvernat** (snapshot cache efemer, rate-limit + provenance). **Livrat:** `worldview_ingest/capture/` — `TokenBucket`/`RateLimiter` (per-source + global, `now` injectat), `SnapshotCache` (TTL + drop-oldest, counters), `Snapshot` (`worldview.capture.v1`, provenance mereu prezentă: source/captured_at/trigger/run_id), `run_capture` guvernare pură (evict-expired→dedup→skip-active→rate-limit→snapshot+cache), worker async (own producer → `osint.capture`, no-op grațios). Wired în config/`__main__` (`capture` self-owned). 145 teste, ruff clean; core determinist (clock injectat); nu inventează semnale. **AC îndeplinit:** captură guvernată = snapshot la semnale efemere cu provenance + rate-limit. | 13 | P3 | H19.4.4 | Both |

> **Total ORIZONT 19:** 33 items, ~208 SP (WS1 38 · WS2 45 · WS3 31 · WS4 39 · WS5 55). **Primele 5 (the next concrete things):**
> H19.1.1 (ADS-B real) → H19.2.1+H19.2.2 (recon-window + alertă, wow maxim, reutilizează SGP4) → H19.3.1 (MCP server) →
> H19.3.4 (un watcher = bucla proactivă) → H19.4.3+H19.4.4 (provenance + audit). Plan complet & ADR-uri:
> [`worldview/docs/02-platform-architecture-and-delivery-plan.md`](worldview/docs/02-platform-architecture-and-delivery-plan.md).

---

## ORIZONT 20 — Hermes Mining (capabilități nete din `hermes-agent`, post-1.0) — 6/6 ✅

> Sursă: research [docs/research/2026-06-07-hermes-agent.md](docs/research/2026-06-07-hermes-agent.md) §7.
> `hermes-agent` (NousResearch, MIT, ~185.7k★, activ) se suprapune masiv cu OpenClaw (are chiar
> `hermes claw migrate`), așa că **gap-urile de reach/UX sunt deja trackuite** din
> `2026-06-05-openclaw-feature-analysis.md`: canale (H12.16), node mesh (H12.17), canvas (H12.18),
> computer-use (H15), desktop Tauri (H11.1). Aici stau doar **capabilitățile NETE, specifice Hermes**.
> Importul SKILL.md / agentskills.io e deja închis (BUG-13). **Principiu (neschimbat):** adoptăm sub
> guvernare — fiecare capabilitate trece prin approval-queue / risk-gate / secret-broker / audit.
>
> **Unde Jarvis deja conduce (NU sunt gap-uri):** approval-queue + risk-gating, audit Merkle,
> secret broker (H15.4 ✅), secrete criptate, marketplace semnat (vs Skills Hub deschis), KG bitemporal
> + RRF + reflection (vs procedural memory mai plată), dual-LLM quarantine (H17), cost analytics +
> observability. Hermes conduce pe **actuation**; Jarvis pe **guvernanță/memorie/securitate** — același wedge.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H20.1 ✅ | **Tool-RPC în sandbox (`execute_code`)** — agentul scrie Python care apelează **tool-urile Jarvis** printr-un RPC local (Unix-socket) din interiorul sandbox-ului → „zero-context-cost pipelines" (orchestrează N tool-calls într-un script, fără round-trip prin contextul LLM per pas). Secretele NU sunt citibile în sandbox (peste secret broker H15.4). **Gated:** suprafața RPC pe allowlist + approval pe tool-uri tier-extern. Cel mai mare câștig net din Hermes. **Done 2026-06-09 (suprafață guvernată):** `core/tool_rpc.py` `ToolRPCServer` — **allowlist** (doar tool-uri înregistrate; necunoscut → refuzat), **risk-gating** (read-only inline; gated/extern → **task ask-tier**, nu rulează din sandbox; execută via executor `toolrpc` DOAR după aprobare), **secret-scrub** recursiv pe răspuns (sandbox-ul nu vede secrete). `run_pipeline` = N tool-calls fără round-trip LLM. Endpoints `GET /api/toolrpc/tools`, `POST /api/toolrpc/call`. Allowlist de start: `echo`/`time` (integrările adaugă tool-uri gated). +10 teste offline (allowlist, gating+enqueue, scrub secrete, pipeline, execute post-aprobare). *(Transport Unix-socket + clientul din sandbox + rularea codului = poartă host.)* | 13 | P2 | H15.4, `sandbox.py` | hermes-agent `execute_code` |
| H20.2 ✅ | **Lățime providere + hot-swap** — adaptor **OpenRouter** (o cheie → sute de modele) + comandă chat/admin de schimbare backend la cald (`/model …`), peste hybrid router-ul existent (Claude/Gemini/LM Studio/Ollama). **Done 2026-06-09:** `core/llm/openrouter.py` `OpenRouterBackend` (LLMBackend OpenAI-compat, bearer-auth, `strip_thinking`, client injectabil → offline-testable) + `parse_model_command` (`/model <id>` → swap; `/model` → list). Endpoint admin `POST /api/llm/openrouter` (parsează comanda + raportează disponibilitatea cheii). +4 teste offline. *(Cablarea live în HybridRouter + apelul de rețea = poartă host.)* | 5 | P2 | PR #133 (LM Studio control) | hermes `hermes model` / OpenRouter |
| H20.3 ✅ | **ContextCompressor runtime** — compresie de context pentru sesiuni lungi (rezumare / eviction inteligentă pe cale fierbinte), distinct de consolidarea nocturnă (H5.15). Se leagă de tema „sleep-time compute" (H13). **Done 2026-06-09:** `core/context_compressor.py` `ContextCompressor` — buget pe tokeni (chars/4), păstrează turele recente verbatim, **evictează inteligent** restul: rezumat via summarizer injectabil (LLM, deferred) SAU **digest determinist** pe importanță (lungime/întrebare/rol) offline. Endpoint `POST /api/context/compress`. +5 teste offline (sub-buget = no-op, compresie, summarizer injectat, fallback la digest la eșec). Distinct de consolidarea nocturnă H5.15. | 8 | P2 | H5.15 | hermes ContextCompressor |
| H20.4 ✅ | **Self-evolution (DSPy / GEPA)** — optimizare automată de prompturi/skill-uri din traiectorii (ShareGPT-style), gated prin decision inbox (reversibil). Extinde learning-loop-ul de agenți (H7.11) de la „ce agent" la „cât de bine e promptat". **Done 2026-06-09:** `core/self_evolution.py` — `TrajectoryStore` (traiectorii ShareGPT-style scored; best top-K per agent) + `propose_optimization` (din cele mai bune traiectorii → prompt optimizat: few-shot demos appended SAU optimizer DSPy/GEPA injectabil/deferred; **gated + reversibil**, `requires_approval`). +5 teste offline. | 8 | P3 | H7.11, H6.5 | hermes-agent-self-evolution |
| H20.5 ✅ | **Skill self-improvement + drift manifest** — rafinează skill-uri existente (nu doar `generate_skill` care doar creează) + manifest content-hash pt. detectarea modificărilor la sync `hermes update`-style. **Done 2026-06-09:** `core/skill_drift.py` — `manifest_hash` (content-hash sha256 whitespace-normalizat), `SkillDriftManifest` (`record`/`has_drifted`/`drift_report` → new/drifted/unchanged la sync), `refine_proposal` (rafinare a unui skill EXISTENT via refiner injectabil/deferred, gated+reversibil). +6 teste offline. | 5 | P3 | BUG-13, `loader.generate_skill` | hermes Skills Hub / `.bundled_manifest` |
| H20.6 ✅ | **Delegare dinamică de sub-agenți** — agentul poate spawna la runtime un sub-agent izolat (sesiune proprie), concurent (cap configurabil), gated. Extinde WorkflowEngine (H5.6) de la paralelism author-defined la spawn inițiat de agent. **Done 2026-06-09:** `core/subagents.py` `SubAgentManager` — `spawn` rulează un sub-agent în **sesiune izolată** (`session::sub-…`) printr-un **runner injectabil** (dispatch orchestrator în prod; stub offline), **cap configurabil** de concurență (`autonomy.max_subagents`, respins peste cap → 429), eliberat pe succes/eșec. Endpoints `GET /api/subagents`, `POST /api/subagents/spawn`. +5 teste offline (izolare sesiune, cap concurență, eșec capturat). | 8 | P3 | H5.6 | hermes `delegate_tool` |

> **Total Orizont 20:** ~47 SP, **post-1.0** (NU în gate-ul 1.0.0). Headline: **H20.1**.
> Secvențiere: H20.1 → H20.2 → H20.3 → (H20.4 ∥ H20.5 ∥ H20.6).


---

## ORIZONT 21 — Cognition: Living Memory & Human-Like Personality (P1–P3) — 10/10 ✅

> **Cea mai importantă temă.** Un creier cognitiv pentru agenți: memorie **nelimitată, append-only,
> mereu valoroasă în timp** (uitarea = accesibilitate redusă + demotare pe tier, **niciodată ștergere**;
> doar utilizatorul șterge explicit) + personalitate **consistentă-dar-vie** ancorată pe **onestitate**
> (HEXACO Honesty-Humility, anti-sycophancy structural). Viitor-proof = **neuroplasticitate**
> (re-embedding pe modele mai bune, working-memory elastic). Rulează pe cortexul idle (night-shift).
>
> *(Renumerotat 19→20→21: ORIZONT 19 = WorldView (4D OSINT), ORIZONT 20 = Hermes Mining — ambele luate în alte sesiuni.)*
>
> **Complementar cu ORIZONT 20 (Hermes Mining):** Hermes conduce pe **actuation**, Cognition adâncește
> **memoria/personalitatea/guvernanța** — același wedge. Reutilizează exact primitivele unde „Jarvis deja
> conduce" (approval-queue, risk-gate, secret-broker, audit Merkle, KG bitemporal+RRF+reflection). **Nu
> dublează** bucla de skill din Hermes: H21.4 **hrănește + guvernează** H20.5 (skill self-improvement) și
> H20.4 (self-evolution DSPy/GEPA), nu le reimplementează.
>
> **Hartă schematică & diagnostic:** [`docs/COGNITION.md`](docs/COGNITION.md) (~35 analogii cu creierul,
> diagrame tier/flux, playbook simptom→cauză→remediu). **Context complet de sesiune:**
> [`docs/research/2026-06-07-cognition-and-tools-session.md`](docs/research/2026-06-07-cognition-and-tools-session.md).
>
> **Decizia de arhitectură (calitate pe termen lung):** un singur pachet `agents/core/cognition/` în
> spatele unui **`CognitionFacade`** înregistrat prin `ComponentRegistry` (1 linie în orchestrator + 2/handler) →
> **nu crește god-object-ul** (CLN-2/CLN-3). Stare tranzitorie pe un **`TurnContext` per-cerere** (repară **BUG-5**);
> stare durabilă în **`JsonStore`-uri locked, keyed** `(agent,user)`/`session` (nu atribute pe instanța partajată).
> **Master OFF = no-op măsurabil.** Reutilizează primitivele H14 deja livrate: `decay.py` (H14.4),
> `bitemporal.py` (H14.1), `consolidation.py` (H14.3), `entity.py`. *(SP-urile de mai jos nu sunt încă rulate în „Status General".)*
>
> **Metrica nord (conjunctivă, ne-gameable):** mastery/KC↑ cu calibration-error↓; accept-first-pass↑
> **cât timp** corectitudinea-gold ține (altfel alarmă de sycophancy); media trăsăturii urmărește μ cu
> varianță vie **și** pushback-reversal ≤0.05 la warmth ridicat; ID-orb ansamblu ≥80% **gated** de truth-audit.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H21.0 ✅ | **Schelet + fix BUG-5** — pachet `cognition/` + `CognitionFacade` (înregistrat în `ComponentRegistry`), `TurnContext` per-cerere, bază `JsonStore` locked+keyed, categorie settings `cognition` (toate OFF), `APIRouter`. **Zero schimbare de comportament.** **Done 2026-06-09:** pachet `core/cognition/` — `CognitionFacade` (înregistrat în `ComponentRegistry`, **master OFF = no-op**; sub-flag activ doar dacă master ȘI flag), `TurnContext` async-context-local (izolat pe taskuri concurente, ca fix-ul BUG-5), `KeyedStore` (JsonStore locked+keyed `(agent,user)`), **`APIRouter`** montat (`GET /api/cognition/status`) ca să nu crească web.py. +9 teste offline (no-op master, izolare context, store persist+reload, endpoint cu/fără orch). | 5 | P1 | — | master OFF = no-op măsurabil; `session_id` trece prin `TurnContext` (fără mutație pe instanța partajată → BUG-5 reparat); `/api/cognition/status` întoarce flagurile |
| H21.1 ✅ | **Cheia de onestitate** (start aici) — judecător anti-sycophancy/persona în `QualityMonitor` (axă deterministă în `signals` + judge LLM opțional **deferred**, nu inline); editare atribuire-în-caracter în `synthesize()`; metrica Sycophancy Index. **Done 2026-06-09 (cognition, gated):** `core/cognition/honesty.py` `HonestyModule` (înregistrat în `CognitionFacade`) — **axă deterministă** `sycophancy_signals` (flattery/agreement/capitulation; reversal‑under‑pushback = cel mai puternic semnal) + **Sycophancy Index** rulant (alertă peste prag) + `pushback_reversal_rate` pe probe set (AC ≤0.05) + **judge LLM deferred** (`HonestyJudge`, niciodată pe hot‑path). Cablat **gated** (`cognition.honesty_enabled`, master OFF = no‑op): scor pe fiecare trace în hook‑ul quality (paralel cu H10.23, nu‑l modifică) + `Agent.synthesize(in_character=)` păstrează vocile specialiștilor (param default‑False → fără schimbare când e off). Endpoint `GET /api/cognition/honesty`. +15 teste offline. | 5 | P1 | H21.0 | Sycophancy Index calculat & expus; pushback-reversal ≤0.05 pe probe set; `synthesize` păstrează vocile specialiștilor; judge rulează deferred (fără apel LLM pe hot-path) |
| H21.2 ✅ | **Afect + expresie de personalitate** — parser front-matter în `_load_soul` (corp vs `meta`; **reutilizează** parserul YAML-frontmatter introdus de BUG-13 în `loader._parse_manifest` dacă se potrivește); `affect/` (mood attractor, τ) + `personality/` (whole-trait sampler {μ,σ,skew}, seed reproducibil); injectează blocul în **ambele** prompt-buildere (`agent.process` + streaming `orchestrator.py:1115`); Objective·Obstacle·Tactic + dial de status; prosody în `tts.speak()` (afect în **cheia de cache**). Gated `cognition.affect_enabled`. **Done 2026-06-09 (cognition, gated):** `core/cognition/` — `personality.py` (whole-trait sampler {μ,σ,skew}, seed reproducibil; media realizată urmărește μ ±0.05 cu σ viu), `affect.py` (mood attractor valence/arousal, relaxare exponențială spre setpoint cu τ + clamp), `persona.py` `PersonaModule` (per-agent, seed stabil; `prompt_block` Objective·Obstacle·Tactic + dial de status; `prosody` cu cache_suffix), `frontmatter.py` (parser YAML SOUL → meta vs corp). `_load_soul` separă front-matter (no-op fără front-matter); injecție **gated** a blocului persona în `_run_agent` (acoperă ambele prompt-buildere — `agent.process` ȘI `orchestrator.process` trec prin `_call_agents_parallel`). Endpoint `GET /api/cognition/personality`. +15 teste offline. *(Prosody în `tts.speak` cache-key = descriptor expus + wire host-side la call-site-ul vocii.)* | 8 | P2 | H21.0 | media realizată a trăsăturii urmărește μ ±0.05 cu σ viu; mood-ul se relaxează spre setpoint și se clampează; prosody diferă pe agent; cache-key include afectul |
| H21.3 ✅ | **Memorie vie, NELIMITATĂ** — reutilizează H14 (`decay`/`bitemporal`/`consolidation`/`entity`); **greenfield**: gate de encodare predictive-coding (înainte de `MemoryManager._lock`, în `VectorRecord.metadata`; detectează hash-fallback), 3-vector neuromodulator (DA/NE/ACh), pattern-separation la scriere / completion la citire, **TCM** re-rank post-fusion (nu atinge RRF); split `DailyReflector` în NREM/REM (idempotency **durabil** + multi-sesiune); nightly replay, tag-and-capture, **SHY** renormalizare, mentenanță (demotare pe tier, **NICIODATĂ ștergere**), **re-projection** (re-embed pe model nou, `embed_version`); stocare tiered hot/warm/cold; core mereu-injectat (bounded JsonStore). *(Compresia pe **cale fierbinte** e ORIZONT 20 H20.3 ContextCompressor — aici e consolidarea **nocturnă** + tiering + retenție nelimitată; complementare.)* **Done 2026-06-09 (strat algoritmic cognitiv, gated):** `core/cognition/memory.py` `LivingMemory` — **neuromodulatori DA/NE/ACh** + **gate de encodare predictive-coding** (surprise→encoding strength), **pattern-separation** (write) / **completion** (read), **TieredMemory** hot/warm/cold cu **mentenanță = demotare, NICIODATĂ ștergere** (doar user-forget), **TCM re-rank** post-fusion (nu atinge RRF), **re-projection** (`embed_version`, embedder injectabil), **core memory** bounded always-injected, consolidare **NREM/REM**. Înregistrat în facade; endpoint `GET /api/cognition/memory`. +16 teste offline. *(Cablarea în MemoryManager/recall-fusion/DailyReflector live = seam de integrare.)* | 13 | P2 | H21.0 | nimic auto-șters (doar demotare; user-forget = singura ștergere); reactivare cold→hot pe cue; calibrated-recall (still-true × (1−Brier), penalizare pe fapt depășit); re-projection upgradează vectorii vechi; consolidare idempotentă peste restart + multi-sesiune; S/N stabil pe măsură ce crește |
| H21.4 ✅ | **Învățare guvernată (semnalele, nu bucla)** — `learning/kc.db` (KC dual user+agent + **calibrare**); correction-ledger (extinde `preferences.py` + capturează edit-delta); **autonomie calibration-gated** (extinde `policy._apply_scoring` cu `kc_mastery`/`calibration`); kind-uri night-shift `practice`/`reinforce`. **NU reimplementează bucla de skill** — **hrănește + guvernează** ORIZONT 20 H20.5 (skill self-improvement) & H20.4 (self-evolution) cu semnale KC/calibrare/corecții + re-gating pe payload editat (BUG-11) + Docker forțat (HF-6). **Done 2026-06-09 (semnale, gated):** `core/cognition/learning.py` `LearningModule` — `KCStore` (mastery per `(component,scope=user|agent)` + **calibrare** mean-Brier), `CorrectionLedger` (edit-delta append-only), `calibration_autonomy_adjustment` (tier bump ≥0, **niciodată coboară gating-ul**), `practice_proposals` night-shift (`practice`/`reinforce` pe KC slabe/miscalibrate). **Autonomie calibration-gated**: `policy._apply_scoring` consultă un `calibration_hook` opțional (setat de orchestrator, gated `cognition.learning_enabled`, default no-op, doar adaugă prudență, plafonat la IRREVERSIBLE). Hrănește H20.4/H20.5, nu le reimplementează. Endpoint `GET /api/cognition/learning`. +10 teste offline (mastery, Brier, scoping, ledger, hook bump/no-op/plafon). | 13 | P2 | H21.0, H21.1, H20.5, H20.4 | mastery/KC↑ cu calibration-error↓; accept-first-pass↑ cât timp gold ține; auto-îmbunătățirea de skill (H20.5) e gated de calibrare + auto-revert la regresie; payload editat re-gated |
| H21.5 ✅ | **Ansamblu & maturare** — `personality_matrix.yaml` (casting) + assert de diversitate ε la boot; `synthesize` în stil regizor (păstrează vocile); drift ancorat-în-identitate (trimestrial, bounded ±0.10 lifetime, SOUL versionat git) + self-test psihometric nightly (tripwire); deltă relațională per-(agent,user). Drift/self-mod **reversibil + human-gated** (decision inbox). **Done 2026-06-09 (cognition, gated):** `core/cognition/ensemble.py` `EnsembleModule` — `diversity_check` (niciun agent în ε în spațiul trăsăturilor; raportează min-distance + violări), **drift ancorat-în-identitate** `bounded_drift` (clamp ±0.10 lifetime per trăsătură), `drift_proposal` **reversibil + human-gated** (`requires_approval`, nu se auto-aplică), `psychometric_selftest` (tripwire pe drift > prag), `relational_delta` per-(agent,user), `diff` inspectabil. Înregistrat în facade; endpoint `GET /api/cognition/ensemble`. +8 teste offline. *(Aplicarea drift-ului prin approval-queue + SOUL versionat H10.22 = wire de integrare.)* | 8 | P3 | H21.2, H21.4 | niciun agent activ în ε în spațiul trăsăturilor; ID-orb ansamblu ≥80% gated de truth-audit; drift bounded, inspectabil `/api/personality/diff` + revertibil; self-test psihometric declanșează pe drift |

### H21 — Itemuri adiacente din sesiune (tools open-source + hardware)

> Din evaluarea celor 10 tool-uri + analiza hardware (vezi `docs/research/2026-06-07-cognition-and-tools-session.md`).
> **Deja livrate (skip):** ollama, whisper, n8n. **Sidegrade (parcate):** plausible, cal.com, appflowy, **penpot (drop)**. **Off-mission:** fooocus.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H21.A ✅ | **Secrete în afara `.env` (vaultwarden)** — plugin `vaultwarden` + secret-resolver; Jarvis ia cheile API din vault self-hosted în loc de `.env` plaintext. Aliniat HF-5 (igienă chei) + local-first; se leagă de secret-broker H15.4. **Done 2026-06-09:** `core/secrets_vault.py` `VaultResolver` — rezolvă din vault (client injectabil) cu **fallback explicit** la env; sursă raportată (vault/env/missing); fără plaintext. +4 teste offline. *(Clientul HTTP vaultwarden = poartă host.)* | 5 | P2 | — | cheile se rezolvă din vault; fallback explicit; fără cheie în plaintext în config |
| H21.B ✅ | **Skill media (yt-dlp + Whisper)** — `skills/media/`: yt-dlp ia audio → STT Whisper existent → agent rezumă („rezumă acest video/podcast"). Compune cu ce există deja. **Done 2026-06-09:** `core/media_skill.py` `MediaSummarizer` — pipeline `summarize_url` (downloader→transcriber→summarizer injectabili); yt-dlp/Whisper = poartă host (→ `host_tools_unavailable` fără ele). +3 teste offline. | 3 | P3 | — | „rezumă <url>" → transcript + rezumat; binar `yt-dlp` opțional |
| H21.C ✅ | **Skill generare imagini pe idle** — kind `image_gen`; cere ziua → night-shift descarcă LLM via `LMStudioController` → ComfyUI/diffusers (Flux FP8) generează → reîncarcă LLM → livrează în brief/Telegram. $0, local, **fără contenție VRAM** (LLM descărcat). **Done 2026-06-09:** `core/image_gen.py` `ImageGenOrchestrator` — `generate` descarcă LLM → diffusion (injectabil) → reîncarcă LLM (**fără contenție VRAM**; restaurează LLM-ul ȘI la eșec). Backend diffusion = poartă host. +3 teste offline. | 5 | P3 | autonomy night-shift | imagine generată pe idle fără să blocheze chat-ul; swap LLM↔diffusion narat; backend diffusion configurabil |
| H21.D ✅ | **Prompt-builder video (cloud manual)** — LLM-ul local redactează/rafinează un prompt video pentru lipit manual în Gemini/Veo (opt-in, **$0 tokens API**). Helper mic, nu pipeline. **Done 2026-06-09:** `core/video_prompt.py` `build_video_prompt` — LLM injectabil rafinează ideea într-un prompt video gata de lipit; fallback template determinist; **$0 API**. +3 teste offline. | 2 | P3 | — | „prompt video pentru X" → prompt gata de lipit; fără apel API plătit |
| H21.E ✅ | **Import Drive „AI" via rclone (PRIVAT, onboarding/startup)** — `core/ingestion/drive_sync.py` `DriveAISync` (rclone = poartă host, runner injectabil) oglindește un folder Drive configurat de owner într-un dir **gitignored** (`memory_logs/drive_ai`, sub `$JARVIS_HOME`) → ingest via local-docs indexer (H12.2). Startup gated `JARVIS_DRIVE_AI_SYNC` (fire-and-forget) + `scripts/import_drive_ai.py`. **Privacy:** OAuth în `rclone.conf` al userului, conținut gitignored, doar numele remote-ului în env. **Done 2026-06-20** (+`tests/test_drive_sync.py`, 7 teste; doc `docs/dev/drive-ai-import.md`). | 3 | P2 | — | folderul Drive se importă local fără să atingă repo-ul; ingestat în memorie; nimic personal comis |

> **Notă hardware (nu e task):** laptop RTX 5090 (mobile, 24GB, power-capped) **nu se poate upgrada** la GPU.
> Imagini = local pe idle ($0). Video serios local = nod GPU pe LAN (~$2.8k desktop 5090) sau eGPU — **parcate**;
> video = manual via Gemini. *(Reconciliere doc:* `JARVIS.md` descrie un desktop Windows/192GB — de aliniat cu Bonobo-ul real.)*

---

## ORIZONT 22 — Adopție OSS Runda 2: Performanță & Velocity (research 2026-06-20)

> Sursă: [`docs/research/2026-06-20-oss-adoption-perf-velocity.md`](docs/research/2026-06-20-oss-adoption-perf-velocity.md)
> — 13 repo-uri mapate la ținte la nivel de fișier (perf runtime + velocity dev).
> **Reconciliere cu H21** (`docs/research/2026-06-07-cognition-and-tools-session.md`): secret-vault =
> **deja livrat** (H21.A `secrets_vault.py`); **plausible / cal.com / appflowy = parcate (sidegrade)** sub H21;
> **penpot = drop**, **fooocus = off-mission** (image-gen idle livrat = H21.C); ollama/whisper/n8n = backend deja
> integrat. Itemurile de mai jos sunt **doar cele noi**, neacoperite de H21.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H22.1 ✅ | **Fan-out plugin concurent** (yt-dlp) — `plugin_gatherer.py`: eligibilitate (keyword+permission) separată de execuție; pluginele eligibile rulează cu `asyncio.gather` sub semafor + `wait_for`/plugin; eșec izolat (`E_PLUGIN_EXEC_FAIL`). **Done PR #264** (+`tests/test_plugin_gatherer_concurrency.py`). | 2 | P2 | — | turn cu N plugine → ~1 RTT, nu N; un plugin lent nu blochează turul; ordine deterministă |
| H22.2 ✅ | **Warm-up model local la pornire** (ollama) — `LLMBackend.warm_up()` + override Ollama (empty-prompt load + `keep_alive:-1`) + `LLMRouter.warm_up()`; `load_agents` îl lansează fire-and-forget post-`detect()`, gated `JARVIS_LLM_WARMUP`. **Done PR #264** (+`tests/test_llm_warmup.py`). | 2 | P2 | — | primul tur (voce) nu plătește cold-load; kill-switch `JARVIS_LLM_WARMUP=0` |
| H22.3 ✅ | **STT decode mai rapid** (faster-whisper) — `voice/stt.py` default greedy (`beam_size=1`) + `int8_float16` pe CUDA / `int8` pe CPU; override per-instanță/env (`JARVIS_STT_BEAM_SIZE`, `JARVIS_STT_COMPUTE_TYPE`). **Done PR #264** (+`tests/test_stt_config.py`). | 1 | P2 | — | latență STT mai mică pe enunțuri scurte; precizie reglabilă din env |
| H22.4 🟡 | **`OLLAMA_NUM_PARALLEL=2–4`** pe backend-ul Ollama — un tur voce + un apel de fundal se întrețes în loc de head-of-line blocking. **Runbook livrat** (`docs/GPU_RUNBOOK.md` §H22.4: NUM_PARALLEL + KEEP_ALIVE + flash-attn/KV-quant + verify). *Validare pe GPU = acțiune host, pending.* | 1 | P3 | — | 2 requesturi concurente pe același model nu se serializează |
| H22.5 ✅ | **Model-manager LRU fast↔deep** (Fooocus/ComfyUI `free_memory`) — track modele rezidente + unload LRU cu headroom înainte de load deep; anti-OOM-thrash în `hybrid_router`. Distinct de H21.C. **Spec:** `docs/superpowers/specs/2026-06-20-h22.5-model-manager-design.md`. **Cod livrat (PR #271):** `core/llm/model_manager.py` (LRU + headroom evict, narat) + adaptor de evicție Ollama + hook de rezidență în `synthesize()`, în spatele kill-switch; +`tests/test_model_manager.py`. *Validare GPU = acțiune host (nemăsurabil în CI).* | 5 | P3 | H22.2, H22.4 | swap fast↔deep fără OOM; evict LRU narat |
| H22.6 ✅ | **Workflow concurency bound** (n8n) — **descoperit:** engine-ul are deja gather pe batch-uri + timeout/pas (`_TIMEOUT`) + istoric prunat (`recent_runs` deque maxlen). **Gap real = fan-out nemărginit pe batch:** adăugat `_MAX_PARALLEL_STEPS=8` semafor în `engine.py` (un batch larg nu mai lansează zeci de apeluri LLM simultan). **Done** (+`tests/test_workflow_concurrency_bound.py`; 102 teste workflow verzi). *Offload pe worker-ul de autonomie = inutil (run-urile sunt deja async+timed) — descopat.* | 5 | P3 | — | ✅ fan-out batch ≤ cap; pas cu timeout; istoric mărginit (deja) |
| H22.7 🟡 | **superpowers + dev-skills jarvis** (`.claude/skills/`) — **livrate:** 4 SKILL.md (`jarvis-load-context`, `jarvis-add-route`, `jarvis-write-test`, `jarvis-add-plugin`) + README format superpowers. *Install plugin superpowers = acțiune host (1 cmd, documentat în README).* | 2 | P2 | — | skills repo trigger automat; pipeline TDD+plan+review după install plugin |
| H22.8 🟡 | **Trial codebase-memory-mcp** (`.mcp.json`) — **scaffold livrat:** `.mcp.json.example` (gitignored live config) + `docs/dev/codebase-memory-mcp.md` (setup + caveats). *Install binar + `index_repository` = acțiune host trial, pending.* | 2 | P2 | — | `index_repository` rulează; agentul găsește simboluri fără file-by-file |
| H22.9 ✅ | **Rute guvernate via MCP server** (BuilderIO/agent-native, *pattern*) — manifest acțiuni din OpenAPI; `mcp/server.py` expune rute allow-listed ca tool-uri MCP lângă agenți, reutilizând permission gate. **Spec:** `docs/superpowers/specs/2026-06-20-h22.9-agent-native-routes-design.md`. **Cod livrat:** read-only (PR #272) — `core/mcp/route_tools.py` derivă scheme din semnăturile handlerelor + allow-list; + mutating writes (PR #279) **în spatele unui al doilea kill-switch, default-off**; +`tests/test_mcp_route_tools.py`. | 5 | P3 | — | un client MCP poate conduce hub-ul prin rute guvernate |
| H22.11 ✅ | **Drift-check surse 3rd-party vendorate** — golul pe care Dependabot nu-l vede (cod vendorat: superpowers; tool doc-pinned: codebase-memory-mcp). `.github/third-party-manifest.json` + `scripts/check_thirdparty_drift.py` (consistency offline + drift vs ultimul release GitHub; fetcher injectabil) + workflow săptămânal `.github/workflows/thirdparty-drift.yml` (PR-gate consistency, deschide issue pe drift). Dependabot rămâne pt. pip/npm/actions. **Done 2026-06-20** (+`tests/test_thirdparty_drift.py`, 7 teste). | 3 | P2 | H22.7, H22.8 | ✅ versiune vendorată în urma upstream → issue automat; manifest stale → PR roșu |
| H22.10 ✅ | **Follow-up `oauth.py` → vault** (bitwarden/H21.A) — `_resolve_token_key()` ia cheia din **vault/env `JARVIS_TOKEN_KEY`** (via `secrets_vault.VaultResolver`, H21.A) → cheia nu atinge discul; fallback legacy fișier **hardening 0600** + warning. `.env.example` documentează cheia. **Done** (+`tests/test_oauth_token_key.py`, 4 teste; 99 teste oauth/token verzi). | 3 | P2 | H21.A | ✅ cheia de criptare nu mai stă în plaintext pe disc; vault/env primar, fișier 0600 fallback |

> **Stare (toate cele 3 valuri procesate):**
> - **Livrate cod+teste:** H22.1–3 (PR #264) · **H22.10** (securitate) · **H22.6** (workflow bound) ·
>   **H22.5** (model-manager LRU, PR #271 — validare GPU rămasă acțiune host) ·
>   **H22.9** (rute MCP guvernate, PR #272 read-only + #279 mutating default-off) · **H22.11** (drift-check). 8/10.
> - **Repo-side done, acțiune host rămasă (🟡):** H22.4 (runbook → validare GPU), H22.7 (skills →
>   install plugin), H22.8 (scaffold → install binar + trial). 3/10 *(se suprapun cu cele de sus)*.
> *(plausible/cal.com/appflowy NU se redeschid — decizie „sidegrade parcat" la H21; vezi nota de sus.)*

---

## ✅ Arhivă — H1–H4 + Sprint 0 (livrat în 0.5-beta)

> Toate itemurile H1–H4 sunt complet implementate. Detalii complete (67 items, 248 SP): [docs/HISTORY.md](docs/HISTORY.md).

---

## Testing Guide

> Cum testezi fiecare feature. Pentru comenzi rapide, vezi `docs/features/`.

```
Feature               Test command                          Ce verifici
─────────────────────────────────────────────────────────────────────────
All tests             python -m pytest tests/ -q            Toate feature-urile
Voice                 python tests/test_voice.py -v         STT → TTS pipeline
Telegram              python tests/test_telegram.py -v      Webhook + polling
OAuth                 python tests/test_oauth.py -v         Token refresh + PKCE
Calendar (Pepper)     python tests/test_calendar.py -v      CRUD evenimente
Gmail (Pepper)        python tests/test_gmail.py -v         Etichete, triage
Spotify (Jerome)      python tests/test_spotify_skill.py -v Play/pause/queue
Health (Hercules)     python tests/test_apple_health.py -v  Sleep/HRV/steps
Gecko (balance)       python tests/test_balance.py -v       ING/Libra/CSV/mock
Stark (analytics)     python tests/test_analytics_local.py -v  Local privacy-first KPIs (replaces GA4 mock, PR #276)
Security (Ultron)     python tests/test_security.py -v      Porturi, threats
System (Steve)        python tests/test_system.py -v        CPU/GPU/RAM/temp
n8n (Oracle)          python tests/test_n8n.py -v           CRUD workflow-uri
Sandbox               python tests/test_sandbox_gating.py -v Docker exec
Guardrails            python tests/test_guardrails.py -v    PII redact, injection block
Charts (admin)        python tests/test_admin_stats.py -v   Endpoint metrics
Learning              python tests/test_learning_live.py -v Health routing + promovare
Session               python tests/test_session*.py -v      Persistență + cross-channel
Bench                 python tests/test_bench_activation.py Bench promovare
Integration           python tests/test_agents_integration.py -v Toți agenții (SOUL+router+process)
Load                  python tests/test_load.py -v          15 paralel <30s
Smoke                 powershell smoke.ps1                  Server start + pytest
```

---

## Dependencies

| Resursă | Pentru | Cost |
|---------|--------|------|
| Google Cloud OAuth 2.0 | Pepper Gmail | Gratuit |
| Spotify Developer App | Jerome Spotify | Gratuit |
| Tavily API | Vision Research | Gratuit (1000/lună) |
| Discord Bot Token | Discord channel | Gratuit |
| Slack App Token | Slack channel | Gratuit |
| Docker (Qdrant, Neo4j, n8n) | H3.1, H3.2, H4.6 | Gratuit |
| n8n API Key | Oracle | Gratuit |
