# Blueprint — All Remaining Backlog (ORIZONT 24 execution map)

> **Purpose of this document.** A single, code-grounded implementation reference so future sessions
> execute against *this file* instead of re-reading the ~2M-token repo. Every item lists: the defect/gap,
> the exact files + seams to **reuse** (with `file:line`), the approach, acceptance, and where tests go.
> This document is the context-cheap execution map for **ORIZONT 24**; implementation proceeds phase by
> phase, each item its own PR. Linked from `BACKLOG.md` (ORIZONT 24 + Competitive-Gap sections).
> Load-bearing seams were re-verified against the codebase on 2026-06-23 (see *Fresh-eyes validation*).

## Context

The owner set direction on 2026-06-23: **primary bet = OS Kernel + Verification Fabric**, with all four
capability packs. That became **ORIZONT 24** in `BACKLOG.md` (Tracks K/V/P, 12 items + 3 CI gates), with
design specs already written for the two substrate tracks and the first pack:
- `docs/superpowers/specs/2026-06-23-orizont24-action-kernel-design.md` (Track K)
- `docs/superpowers/specs/2026-06-23-orizont24-verification-fabric-design.md` (Track V)
- `docs/superpowers/specs/2026-06-23-orizont24-p1-proactive-autonomy-design.md` (P1)

"All remaining backlog" = everything not yet DONE that stands between v0.10 and a **provable 1.0**. It
threads cleanly onto the ORIZONT 24 phases (BACKLOG `Version Roadmap` + `H23` + `Competitive-Gap` rows):

- **Phase A — Hardening (AUD-\*)**: the 2026-06-23 audit's P0/P1 findings. The foundation; skipping it is
  the OpenClaw failure mode. *(Detailed below.)*
- **Phase B — Substrate (Track K + Track V)**: the Action Kernel + Verification Fabric. *(Specs exist;
  summarized below with the build order.)*
- **Phase C — Packs (P1→P2→P3→P4)**: drive each pack SEAM→VERIFIED on the substrate. *(P1 spec exists;
  P2–P4 detailed below.)*
- **Phase D — Productionization & 1.0 proof (H23 remainder)**: operability, release eng, docs, quality
  gates, onboarding, design-partner program. *(Detailed below.)*

Owner-only / GitHub-settings items (SEC-4 branch protection, CQ-2 dismissals, CQ-3 paste-triage, mobile
Dependabot) are **out of scope for code work** — they live in `docs/OWNER_TASKS.md` and are listed at the
end as a hand-off checklist, not implemented here.

Conventions every implementation PR follows (from `AGENTS.md`): ship with tests; keep the hot path off
the event loop; gate new external behavior behind a default-off kill-switch until validated; update the
doc it makes stale; refresh `BACKLOG.md` (tick ✅ + test counter) in the **same** commit as the merge.

---

## Phase A — Hardening cluster (AUD-\*) · P0/P1 · each its own PR

> Source: `docs/research/2026-06-23-independent-audit-merged.md` (F1–F38) + `BACKLOG.md` "Hardening audit
> (2026-06-23)". All fixes **reuse existing security seams** (`security/secret_broker.py`, Fernet,
> `scanner.redact()`, the audit chain, `data_purge.py`, `backup.py`) — no new deps.

### AUD-2 / F1 — "Forget me" purge is incomplete + leaks PII
- **Defect:** `agents/core/data_purge.py:43-45` — `PURGE_DBS` only covers `missions.db`/`autonomy.db`/
  `analytics.db`; **excludes** `memory.db`, conversation transcripts (`*.json`/`*.jsonl`), embedding
  cache, Qdrant, Neo4j. And `data_purge.py:96-103` writes an **unencrypted full-PII** backup first
  (`backup.py:89-135` archives unencrypted).
- **Fix:** expand `PURGE_DBS` + add memory/vector/KG purge hooks; make the backup-first step encrypted
  (see AUD-1) or off by default for forget.
- **Test:** `tests/test_data_purge.py` — post-forget scan finds zero `*.json`/`*.jsonl`/embedding/KG PII.
- **AC:** `POST /api/admin/forget` erases memory + transcripts + vectors + graph; no plaintext PII remains.

### AUD-1 / F2 — Secrets at rest unencrypted (backups + settings.db)
- **Defect:** `agents/core/settings_db.py:96-113` stores credential fields (`twilio_auth_token`,
  `notion_integration_token`, `tuya_secret`, GA4 service account…) as `kind="text"`; `:262`
  `put_category` `json.dumps` with no encryption. `backup.py:107-135` archives `settings.db`/`tokens/`/
  `secrets.enc` unencrypted.
- **Fix (reuse `security/secret_broker.py` + Fernet):** envelope-encrypt secret-keyed values at the
  `put_category`/`get_value` boundary (a `SECRET_KEYS` set → `_encrypt_if_secret`/`_decrypt_if_secret`);
  encrypt the backup archive at write (key from `JARVIS_BACKUP_KEY`, stored outside data root).
- **Test:** `tests/test_settings_secret_encryption.py` + `tests/test_backup.py` — dump shows opaque
  values; archive contains no plaintext tokens.
- **AC:** secret columns opaque at rest; backups carry no plaintext; reads decrypt transparently.

### AUD-3 / F3 — DOM XSS in shipped HUD + no CSP
- **Defect:** `agents/web/index.html:369` `nl.innerHTML = (d.news||[]).map(...)` (external RSS → HTML);
  sibling sinks lines 365/372/382; **no CSP header** (`web.py:330-339` CORS only); Tauri
  `desktop/src-tauri/tauri.conf.json:21` `"csp": null`.
- **Fix:** route untrusted strings through the existing `esc()` helper (`agents/web/components.js:15`) /
  `textContent`; add a security-headers middleware in `web.py` (CSP + `X-Content-Type-Options` +
  `X-Frame-Options`); set a real Tauri CSP string.
- **Test:** `tests/test_hud_xss.py` — a `<script>`/`<img onerror>` RSS headline renders inert; CSP header present.
- **AC:** crafted headline renders as text; CSP on all responses.

### AUD-4 / F4 — WorldView backend-api open-by-default
- **Defect:** `worldview/backend-api/src/config.ts:4` `host ?? "0.0.0.0"`; `:19` `authSecret ?? ""`
  (empty disables auth).
- **Fix:** default `host` to `127.0.0.1`; refuse to boot on a non-loopback bind when `authSecret` is empty.
- **Test (TS side):** config test asserts boot-fail on `0.0.0.0` + empty secret.
- **AC:** insecure combo fails fast with a clear error; dev default is loopback.

### AUD-11 / F5 — Sandbox containment never tested
- **Defect:** `tests/test_sandbox_gating.py:21,43` `pytest.skip` when Docker/wasmtime absent → always skipped in CI.
- **Fix:** add a Docker-enabled CI lane (`.github/workflows/ci.yml`) + `tests/test_sandbox_isolation.py`
  asserting no FS escape, no network, resource caps enforced.
- **AC:** a real containment test runs (not skipped) and passes; `os.system('curl')` inside sandbox fails.

### AUD-9 / AUD-12 / H23.5 — Audit chain not keyed + scanner stores raw secrets
- **Defect:** `agents/core/security/audit.py:91,159` row hash is plain `sha256` (anyone with DB write can
  recompute); `agents/core/security/scanner.py:198,261` stores `matched_text=match.group()` (raw secret),
  persisted into `audit.db` via `audit.py:78-79`.
- **Fix:** HMAC-SHA256 with an off-box key (`JARVIS_AUDIT_KEY`); mask `matched_text`→`[REDACTED:<pattern>]`
  at scanner creation and redact at the `routers/admin.py` audit endpoint.
- **Test:** `tests/test_audit_verify.py` (extend) — verify fails without key; tampered row fails; endpoint never returns raw secret.
- **AC:** chain verification requires the key; `GET /api/admin/audit` shows redacted matches.

### AUD-5 — Session path-traversal via unvalidated `session_id`
- **Defect:** `agents/core/routers/sessions.py:33` takes `session_id` unvalidated → `memory/persistence.py:17,27`
  `MEMORY_DIR / f"{session_id}.json"`.
- **Fix:** validate `^[A-Za-z0-9_-]+$` at the persistence boundary (and/or router).
- **Test:** `tests/test_session_traversal.py` — `../../etc/passwd` → 400.
- **AC:** traversal payloads rejected; no file touched outside data root.

### H23.9 tail — Export HTTP surface
- **Gap:** `data_export.py` is CLI-only (#303); no `/api/admin/export`.
- **Fix:** add `POST /api/admin/export` in `routers/backup.py` (sibling of `/forget`), reusing `data_export.export_data()`; `admin_guard`.
- **AC:** endpoint returns the portable bundle (conversations + memory + settings minus secrets).

### H23.10 — Retention defaults
- **Gap:** no TTL/decay config.
- **Fix:** add a `retention` category to `settings_db.py` DEFAULTS (`conversation_ttl_days=90`,
  `audit_ttl_days=365`, `memory_decay_days=180`) + a scheduled purge pass (reuse the autonomy
  coordinator tick / `data_purge`).
- **AC:** retention settings exist + a scheduled job enforces them.

> **Phase-A exit gate:** every P0 finding (F1–F5, AUD-9/12, AUD-5) has a regression test that fails on
> the un-fixed code; backups + settings carry no plaintext; forget is provably complete.

---

## Phase B — Substrate: Track K (Action Kernel) + Track V (Verification Fabric)

> Full design in the two specs (linked in Context). This is the build-order summary so the blueprint is
> self-contained. **Compose existing seams, default-off behind a kill-switch, migrate in waves.**

### Track K — Action Kernel (`kernel.authorize(action, capability, budget) → grant|deny|queue`)
- **Nucleus to reuse:** `security/capability.py:117` `authorize(broker, kill, token, capability, scope)`
  (already composes `KillSwitch` + `CapabilityBroker`) — generalize from its 2 callers to the front door.
- **K1** facade wrapping the nucleus + `policy.decide()` + budgets; `queue` path reuses the autonomy
  `TaskQueue`/`AutonomyWorker` unchanged. Default-off `JARVIS_ACTION_KERNEL`.
- **K2** generalize `CapabilityBroker` tokens to all agents (fold WorldView HMAC tokens in as one kind).
- **K3** one `Budget` unifying `InterruptBudget` (`worker.py:43`) + mission caps (`missions.py:45`) +
  payment caps; **add** per-task token/time + recursion-depth + loop-wide circuit breaker (folds H23.1).
- **K4** promote `KillSwitch` + `SecretBroker` to syscalls with one-tap HUD control (folds H23.3).
- **Gate K** — `tests/test_action_auth_matrix.py` generalizing the SEC-2 route-auth matrix
  (`INTENTIONALLY_DIRECT`/`PENDING_KERNEL` escape sets); fails CI on any un-mediated privileged action.
- **Closes audit bypasses** B1 (admin routes need a capability), B2 (MCP fail-open), B3 (egress downgrade audited).
- **Migration waves:** TaskQueue brokers → plugin egress → MCP/KG writes → admin security routes.

### Track V — Verification Fabric
- **V1 reality harness** — per-capability contract + live/real-protocol test on a CI schedule; reuse
  `observability/eval.py` `EvalHarness` as the scoring substrate; gate live mode with `JARVIS_REALITY_HARNESS`.
- **V2 capability readiness registry** — `CapabilityRecord{ id, kind, owner_agent, contract_ref, state ∈
  {SEAM,WIRED,VERIFIED,GA}, last_verified, harness_id }`; **derive** from `plugin_gate.py:BUILTIN_PLUGINS`
  + `component_registry.py` + `skills/loader.py`; expose `GET /api/metrics/capabilities` + HUD board.
- **V3 fleet-coordination gates** — `tests/test_capability_readiness_matrix.py`
  (`INTENTIONALLY_SEAM`/`PENDING_VERIFY`) + cross-agent interface-contract drift, generalizing the
  `_route_introspect.py` snapshot pattern.
- **V4 eval → required gate** (folds H23.4) — promote the golden-dataset eval + counter-metric guardrails
  (`observability/north_star.py`) to blocking jobs in `.github/workflows/ci.yml`.
- **Gate V** — nothing reaches VERIFIED without a green harness; readiness board live.

> **Phase-B exit gate:** action-auth matrix green · reality-harness live · readiness board shipped ·
> eval/counter-metrics blocking on PR.

---

## Phase C — Capability packs (drive SEAM→VERIFIED on the substrate)

> Order: **P1 (spec done) → P2 → P3 → P4**. Each pack registers in the V2 registry and is mediated by K.
> Per-pack reality-harness (`tests/test_p{N}_*_harness.py`) is the VERIFIED gate.

### P1 — Proactive Autonomy Core (north-star mover) — *spec exists*
See `…-p1-proactive-autonomy-design.md`. Loop already wired (`observer`/`watchers` → `policy` → Telegram
inbox → `TaskExecutor` → write-back/social/call → `north_star`, DONE increments the metric). Work =
route executor through `kernel.authorize` (K), per-rail harness + readiness (V), and close 3 proof gaps:
G1 unified "Today in Jarvis" timeline (`memory/timeline.py`, theme 0.38), G2 night-window split in
`compute_north_star`, G3 proposal-funnel diagnostics `GET /autonomy/debug`.

### P2 — OSINT / WorldView (themes 0.40/0.41) — **PARTIAL** (core live, deepen)
- **Live:** `plugins/worldview.py:35-160` read-only queries (state_at/recon_*/provenance), circuit-broken;
  `autonomy/watchers.py:WorldViewProbe` queues recon tasks.
- **SEAM:** `plugins/signal_layer.py:30-160` `signals()`/`world_brief()`/`country_assessment()` exist but
  **unused by Argus**; no correlation engine; no evidence drawer; KG sync writes provenance only.
- **Build:** (1) `signal_layer/correlation.py` — geofence+time-window rules over `WorldViewProbe` facts →
  correlation task-proposals; (2) `signal_layer/aggregator.py` — fuse world_brief + country_assessment +
  signals(evidence) into one brief at digest time; (3) Argus integration — on geoint intent, query
  signal_layer in parallel, cite provenance; (4) `signal_layer/domain_router.py` — route per-domain
  signals to Argus/Stark/Gecko; (5) register in V2 registry; (6) `tests/test_p2_osint_harness.py` against
  live Signal Layer on :8787.
- **Reuse:** `PluginHTTPClient.for_plugin("worldview")` + `resilient_call`; `memory/worldview_sync.py` KG
  writer; `plugin_gate.py` worldview manifest. **Governance:** untrusted external data → enforce the
  ingestion trust-boundary (closes F12); read-only bridge contract already tested
  (`test_worldview_bridge_contract.py`).
- **AC:** Argus answers cite provenance; ≥1 correlation task/week; `/api/capabilities/p2`=VERIFIED.

### P3 — Market Intel + Finance (theme 0.39) — **SEED**
- **Live:** `plugins/balance.py:59-101` `get_balances/get_summary` (ING/Libra/CSV or mock, masked);
  `plugins/analytics.py:28-93` local KPI store; `autonomy/watchers.py:FinanceProbe` already probes balance/burn.
- **SEAM:** no watchlists, no threshold alerts, no disclaimers.
- **Build:** (1) `finance/watchlist.py` — `WatchlistStore` (thresholds persisted in `settings_db`/`finance.db`);
  (2) `finance/alert_broker.py` — compare balances vs thresholds → autonomy tasks (`finance.alert.*`,
  risk_tier=1); (3) `finance/disclaimers.py` — tag every balance/KPI output ("no advice", source);
  (4) extend `FinanceProbe.probe()` to emit alert tasks; (5) `routers/gecko.py` —
  `GET /api/gecko/balance`, watchlist CRUD, `GET /api/gecko/alerts`; (6) `tests/test_p3_finance_harness.py`.
- **Reuse:** `BalanceReaderPlugin`, `AnalyticsPlugin.get_kpis`, `autonomy/inbox.py:build_decision_card`,
  existing balance/analytics manifests. **Governance:** mask IBANs (PII scanner), disclaimers at response time.
- **AC:** alert task queued on threshold breach; every Gecko output carries a disclaimer; watchlist persists.

### P4 — Creative / Publishing (themes 0.47/0.50; fuels 0.52 Demo Factory) — **SEED**
- **Live:** `writeback.py:74-150` (Notion/GitHub/GCal, queue-gated), `social.py:54-100` (X, queue-gated),
  `autonomy/executor.py` dispatch.
- **SEAM:** `media_gen.py:25-66` `MediaGenManager` is a facade with no backends; `video_prompt.py:19-36`
  prompt-builder only; `image_gen.py` missing; no provenance; no export packs; no coordinated pipeline.
- **Build:** (1) `media/backends.py` — local stub image/video backends injected into `MediaGenManager`;
  (2) `media/provenance.py` — `ProvenanceRecord` in `media.db` per generation; (3) `media/pipeline.py` —
  `ContentPipeline` (idea → image → caption → social → README) via approval queue (needs K); (4)
  `media/export.py` — YouTube/Instagram/README export packs (PIL/markdown; FFMPEG stub for video);
  (5) `routers/media.py` — library/pipeline/export/provenance endpoints; (6) `tests/test_p4_creative_harness.py`.
- **Reuse:** `MediaGenManager` facade, `video_prompt.build_video_prompt`, write-back/social governance,
  `TaskExecutor` (register `media.*` handlers). **Governance:** scan generated assets for injected
  content before publishing (`GuardrailsEngine` REDACT).
- **AC:** pipeline completes E2E with provenance; export packs render; creator panel ships.

> **Phase-C exit gate (per pack):** harness-green + kernel-mediated → VERIFIED in the registry, and the
> pack's slice of the north-star is moving.

---

## Phase D — Productionization & 1.0 proof (H23 remainder)

> Several H23 items are **already absorbed** by earlier phases — do not re-implement:
> H23.1→**K3**, H23.3→**K4**, H23.4→**V4**, H23.5→**AUD-9/12**, H23.7 ✅DONE(#305), H23.8 encryption→**AUD-1**,
> H23.9 export+purge→**AUD-2 + export surface**, H23.10→**Phase-A retention**. The rest, by version theme:

### 0.13 — Agentic-safety completeness
- **H23.2 model-version pinning & reproducibility** — `observability/tracer.py:39-60` logs only the model
  *name*. Extend `LLMBackend.generate()` to return `(text, model_info{id,version,quant,sha256})` (fetch
  from LM Studio/Ollama `/v1/models`); record in the trace; add an `approved_models:[…]` allowlist per
  agent in `agents/_system/agents.yaml`, enforced in `hybrid_router.select_backend()`. Test
  `tests/test_model_reproducibility.py`. (≈5 SP)
- **H23.6 cross-channel taint-tracking (TASK-3)** — indirect-injection data-flow tracking. Complex; the
  Action Kernel's mediation + `GuardrailsEngine` are the seam. **Recommend scoping a minimal taint flag
  on ingested content first**, full data-flow analysis deferred. (flag, not full build)

### 0.15 — Operability & distribution
- **H23.11 health/readiness + graceful shutdown + log rotation** — `/api/status` exists
  (`routers/status.py:45-77`); add lightweight `/health` (200 if orch up) + `/readiness` (503 if LLM
  backend down); wire `signal.SIGTERM/SIGINT` in `agents/web.py:lifespan` to flush checkpoints + finish
  in-flight; add `RotatingFileHandler` (10 MB ×5) for `memory_logs/jarvis.log`. Test
  `tests/test_health_readiness.py`. (≈4 SP)
- **H23.12 graceful local-LLM-down everywhere** — partial today (orchestrator step-7 `asyncio.wait_for`
  120 s + cloud fallback). Audit hot paths (plugins, workflows, streaming) for missing timeouts; ensure
  all use `resilience.py:@resilient_call`; surface circuit-breaker state in `/api/status`. Test
  `tests/test_llm_down_graceful.py`. (≈2 SP)
- **H23.13 release artifacts + signing** — extend `.github/workflows/release.yml` (today: tag→Release):
  build `jarvis-{ver}.tar.gz`/`.zip`, GPG-sign, attach SBOM/NOTICE (`pip-licenses`); optional PyPI +
  multi-arch Docker (`ghcr.io`). (≈5 SP)
- **H23.14 semver/compat/deprecation docs** — `docs/SEMVER.md` + `docs/SUPPORTED_VERSIONS.md` + platform
  matrix; link from README. (≈2 SP, docs)
- **H23.15 systemd/service templates** — `install/jarvis.service` (Restart=always) + `INSTALL_SYSTEMD.md`;
  Windows `nssm`/`New-Service` template. (≈3 SP)

### 0.16 — Observability UI
- **H23.16 network-monitor HUD panel** — `frontend/src/network.tsx` exists but has **no data source**. Add
  a thread-safe `EgressCounter` at the egress choke point (`http_client.py` / `plugin_gate.py`) → ring
  buffer + `network_events.db`; `GET /api/admin/network/calls?agent=`; wire the panel to prove
  `frigga/ultron/howard` make **zero** outbound calls (ties to the kernel's mediation). Test
  `tests/test_network_monitor.py`. (≈3 SP)

### 0.19 — Quality gates & docs
- **H23.17 quality gates** — none today beyond pytest + frontend unit. Add Playwright E2E
  (`tests/e2e/*.spec.ts` + `.github/workflows/e2e.yml`, chat + voice flows), nightly load/soak
  (`tests/load/locustfile.py`, assert p95<2 s), a11y (`@axe-core/playwright`), i18n completeness check
  (`tests/i18n_completeness.py`), browser+mobile matrix. (≈8 SP)
- **H23.18 user docs** — `docs/USER_GUIDE.md` + `FAQ.md` + `UPGRADE.md`. (≈3 SP, docs)
- **H23.19 trust/security docs** — `docs/THREAT_MODEL.md`, flesh out `SECURITY.md` (disclosure policy),
  `docs/PRIVACY.md`, ship `SBOM.json`/`NOTICE` in releases, telemetry opt-in disclosure. (≈3 SP, docs)

### 0.20 — Product-proof (the 1.0 user gate)
- **H23.20 onboarding wizard + activation funnel + cold-start guidance** — `routers/onboarding.py` exists
  (local-docs only). Add `/api/onboarding/wizard` (intro→model-select→test-chat→autonomy-budget) + a
  `/onboarding` HUD page; track funnel via `analytics_store.record_event("funnel.*")`; friendly
  cold-start errors (LLM unreachable → troubleshooting link). Tests `tests/test_onboarding_wizard.py`,
  `test_activation_funnel.py`. (≈4 SP)
- **H23.21 design-partner program** — in-app NPS/feedback widget (HUD footer → `feedback.db`),
  `POST /api/feedback` (session-scoped), `docs/DESIGN_PARTNER_PROGRAM.md` (recruit 1–3, 48 h SLA). Test
  `tests/test_feedback_widget.py`. (≈3 SP)
- **H23.22 landing page + demo video** — owner-led; dev support = GitHub Pages from `/docs` +
  `marketing/` hero. (owner)
- **H23.23 multi-user readiness — DECISION** — recommend **accept single-user for 1.0** + document the
  multi-user refactor path (`docs/SINGLE_USER_NOTE.md`); Option B (per-user isolation, `user_id` + RLS,
  ~40–60 SP) is Phase-3/post-1.0. *(Owner decision — see hand-off.)*

> **Phase-D exit gate = the 1.0 gate (MOONSHOT §4):** productionization done **and** validated by 3–5
> design partners on real usage; manual-test/audit pass → tag 1.0.

---

## Phase E — Deferred capability depth (full specs · post-1.0 unless promoted)

> Owner chose **full per-theme specs**. These sit **beyond the 1.0 critical path** — schedule after the
> substrate (K/V) so each rides the kernel/registry instead of re-inventing gating. Themes already mapped
> into A–D are not repeated (P1=0.32/0.38/0.45, P2=0.40/0.41, P3=0.39, P4=0.47/0.50/0.52; H23 covers
> 0.19/0.20/0.55/0.56/0.57/0.60/0.61; K/V cover 0.36/0.45/0.54).
> **Already DONE — do not re-spec:** 0.27 VLM eyes · 0.30 context-compression · 0.32 missions · 0.33
> subagent gateway · 0.35 prompt registry · 0.36 action-manifest (*finish-first = unify with
> `route_auth.json`*) · 0.54 skill OS · 0.56 Trust Center(#300) · 0.60 local analytics(#300).
> Format per theme: **status** · live seams `file:line` · gap · build steps · reuse · test · K/V dep.

### E1 — Voice / desktop / capture / comms
- **0.24 Voice Hotkey & Dictation** (PARTIAL). Live: `frontend/src/voice.ts:44-276` (VAD+PTT),
  `routers/voice.py:41-63`, `voice/stt.py:52-103`. Gap: physical hold-to-talk (only in-focus PTT today),
  filler-word removal, barge-in tuning UI (`voice.ts:191-200` hardcoded `BARGE_RMS/MS`). Build: hotkey
  listener→`useVoice.toggle()`; `voice/filler_filter.py:remove_fillers`; apply post-STT; settings
  `voice.hotkey_*`. Reuse: `useVoice` start/stop/toggle. Test `tests/test_voice_hotkey_0_24.py`. Dep: light (K3 budget).
- **0.25 Desktop Control Pack** (SEED). Scaffolds: `screen_grounding.py` (`parse_grounding/locate/fuse_with_a11y`),
  `browser_agent.py` (`GovernedBrowser`,`NullBrowserDriver`), `desktop_operator.py`
  (`GovernedDesktop.preview/run`, mutating classification, `NullDesktopDriver`). Gap: screenshot loop,
  app-launch registry, OS control (volume/sleep). Build: `desktop/screenshotter.py`→VLM;
  `desktop/app_registry.py` allowlist→exec; add launch/volume/sleep as mutating; route via
  `ActionApprovalQueue`; extend `NullDesktopDriver`. Reuse: `GovernedDesktop.is_mutating`,
  `action_approvals.py`. Test `tests/test_desktop_control_0_25.py`. **Dep: K1 (every mutation mediated).**
- **0.26 Capture Inbox** (PARTIAL). Live: `passive_capture.py` (`ingest/list/forget`+redaction+KG feed),
  `routers/capture.py`. Gap: phone export, transcript sync, unified inbox. Build: `POST /api/capture/from-phone`
  (shared-secret); STT→`capture.ingest("transcripts",…)`; `CaptureInbox.tsx` merges capture+memory+digest;
  `capture.phone_token` setting. Reuse: `PassiveCapture.ingest`. Test `tests/test_capture_inbox_0_26.py`. Dep: K2 (phone token=capability).
- **0.28 Voice Persona Studio** (PARTIAL, BUG-2b.3). Live: `cognition/persona.py:32-88`
  (`PersonaModule.prompt_block/prosody`), `voice/tts.py` fallback chain. Gap: consent flow, barge-in→HUD
  logging, mood dial. Build: `cognition/consent.py:ConsentStore`; `routers/cognition.py` consent endpoints;
  `PersonaMood.tsx` valence/arousal dial; barge-in event POST. Reuse: `PersonaModule`, `/tts` params. Test
  `tests/test_persona_consent_0_28.py`. Dep: light.
- **0.44 Safe Comms Pack** (PARTIAL). Live: `channels/{email,telegram,discord,slack}.py:send()`, global
  `_rate_limit` in `web.py`, `action_approvals.py`, telegram `send_card`. Gap: draft-before-send UI,
  per-channel rate limits, per-recipient consent. Build: `channels/rate_limiter.py` per `(channel,recipient)`;
  route sends through `ActionApprovalQueue`; `routers/comms.py` drafts; `channels/contact_consent.py`;
  `CommsDrafts.tsx`. Reuse: `ActionApprovalQueue`, telegram `send_card`. Test
  `tests/test_safe_comms_pack_0_44.py`. **Dep: K1 (send mediation) + K3 (rate budget).**

### E2 — Knowledge / workflow / code / packs
- **0.21 Offline Knowledge Packs** (SEED). Live: `local_docs.py:73-78` (`LocalDocsIndexer`), `:30-70`
  extract/chunk, `ingestion/embedder.py` 3-layer cache. Gap: `.jarvis-pack` format, installer, registry.
  Build: `PACK.md` manifest; `packs/installer.py:PackInstaller.download` (validate ZIP); `packs` table in
  marketplace schema; `routers/packs.py` install/list/delete; index on install→`memory.remember`. Reuse:
  marketplace migration pattern, `paths.data_path`. Test `tests/test_pack_installer.py`. Dep: 0.58.
- **0.31 Code Intelligence MCP** (SEED). Live: `mcp/client.py:22-90`, `mcp/server.py:48-100`,
  `mcp/route_tools.py:72-88` (`ROUTE_TOOL_ALLOWLIST`). Gap: code-indexing backend, semantic search, code
  route-tools. Build: `code_intelligence/indexer.py` (AST + embed signatures + call graph);
  `code_intelligence/storage.py` (`code_index.db` + migration); index at startup; add
  `route_code_search/function_context/call_graph`; `POST /api/code/index`. Reuse: `Embedder`,
  `memory/graph.py`, MCP dispatch. Test `tests/test_code_intelligence.py`. Dep: V (route-tool governance).
- **0.34 Workflow Runtime Upgrade** (PARTIAL). Live: `workflows/engine.py:24-30`
  (`_TIMEOUT/_MAX_DEPTH/_MAX_PARALLEL_STEPS`), `:41-100` run loop, ring buffer(50). Gap: persistent job
  queue, pruning/backpressure, resume, priority. Build: `workflows/persistence.py:WorkflowJobStore` (SQLite
  state machine mirroring `TaskQueue`); persist runs; hourly stale-RUNNING→FAILED; `resume(job_id,
  from_step)`; priority dequeue. Reuse: autonomy `TaskQueue`, `migrations.py`, `worker.tick`. Test
  `tests/test_workflow_persistence.py`. **Dep: K3 (job = budgeted action).**
- **0.37 Memory Ingestion Lab** (PARTIAL). Live: `ingestion/pipeline.py:36-100` (7-phase),
  `data_spaces.py:26-80`. Gap: ontology classification, cross-agent entity sharing, provenance. Build:
  `ingestion/ontology.py:OntologyClassifier` (Person/Place/Org/Concept/Decision/Event); provenance fields
  in `ingestion/knowledge.py`; `memory/entity_store.py:SharedEntityStore` (canonical dedupe + cross-agent
  vote); provenance on `memory/graph.py` nodes; `memory.recall` returns provenance. Reuse: Phase-5 extract,
  `KnowledgeGraph`, `DataSpaces`. Test `tests/test_memory_ingestion_ontology.py`. Dep: —.
- **0.58 Pack Manager** (PARTIAL). Live: `skills/marketplace.py:52-100` (`SkillMarketplace`,
  publish/ZIP/moderation), `skills/loader.py:124+`. Gap: unified pack model (skill/model/domain/content),
  uninstall, rollback, dependency resolution, per-pack budgets. Build: `packs/base.py:Pack` ABC +
  subclasses; refactor `SkillMarketplace→PackManager` (+`pack_type/depends_on/deleted_at`); `uninstall`
  soft-delete + `install_version` rollback; `routers/packs.py`; `get_budget()`. Reuse: marketplace
  `_init_db`/migrations, `SkillLoader.discover`, moderation gate. Test `tests/test_pack_manager_unified.py`.
  **Dep: K3 (pack budgets).** *(✓ validated: `marketplace.py:52` `SkillMarketplace`, `publish_skill:89`,
  `apply_migrations` via `_MIGRATIONS:36` all present — the earlier "missing" report was wrong.)*
- **0.42 Security Skills Pack** (MISSING/greenfield). Seam: `skills/loader.py:124+` standard pattern
  (`skills/<name>/SKILL.md`+`main.py`), `security/` infra, moderation gate. Build: `skills/security_pack/SKILL.md`
  (agents ultron/stark; cmds threat_assess/defense_recommend/nist_control_lookup/audit_compliance_check);
  `main.py` over cached MITRE ATT&CK/D3FEND/NIST JSON (offline); install via PackManager `review_status=pending`;
  audit each call. Reuse: `SkillLoader.discover`, `Guardrails`, `security/audit.py`. Test
  `tests/test_security_skills_pack.py`. Dep: 0.58 + audit.

### E3 — Creative / UI / learning / profiles
- **0.46 Media Library** (PARTIAL; overlaps P4). Live: `media_gen.py:25-65`, `media_skill.py:22-46`
  (yt-dlp→Whisper→summary), `routers/canvas.py`. Gap: catalog, timeline UI, export bundles. Build:
  `media/catalog.py:MediaCatalog` (SQLite); `routers/media.py` list/search; `MediaPanel.tsx`;
  `media/bundle.py`; summarizer→catalog hook. Reuse: media_gen/media_skill/canvas. Test
  `tests/test_media_library.py`. Dep: P4/K1 (gen approval exists).
- **0.48 Video Production Pipelines** (MISSING; folds into P4). Live: `video_prompt.py:19-35` (builder).
  Gap: assembly, effects, localization, multi-format export, composer UI. Build: `video/assembler.py`
  (FFmpeg); `video/effects.py` (fade/color/speed); `VideoComposer.tsx`; MP4/WebM export; subtitles (defer).
  Reuse: `video_prompt`, P4 export. Test `tests/test_video_assembly.py` (fake FFmpeg). Dep: P4.
- **0.49 Timeline Adapter** (PARTIAL). Live: `canvas.py:97-150` (`CanvasStore`), `routers/canvas.py:37-65`,
  worldview `timelineMarkers.ts`/`TimelineScrubber.tsx`. Gap: approval-gated edits, edit routes, detail
  view, worldview↔jarvis sync. Build: `approved` field on `CanvasStore`; approve/edit routes;
  `TimelineEventDetail.tsx`; `kernel.authorize("timeline.approve")`; `/api/worldview/timeline/sync`. Reuse:
  `CanvasStore`, `TimelineScrubber`. Test `tests/test_timeline_adapter.py`. **Dep: K1+K4+interrupt budget.**
- **0.51 Reference-Driven Creation** (PARTIAL). Live: `plugins/websearch.py:94-158` (SSRF-safe fetch),
  `:27-92` search. Gap: reference aggregation, grounded-plan choreography, citations, gallery UI. Build:
  `reference/aggregator.py:ReferenceManifest`; orchestrator hook injects search+fetch on creation intents;
  `reference/citations.py:CitationTracker`; `ReferenceGallery.tsx`; citations in media bundles. Reuse:
  `websearch` (plugin-gated). Test `tests/test_reference_driven.py`. Dep: P4.
- **0.53 Design System Manifest** (PARTIAL). Live: `frontend/src/styles.css:1-100` tokens, `docs/BRAND_BOOK.md`,
  `docs/DESIGN_BRIEF.md`. Gap: Storybook/inspectable library, component registry, visual-regression,
  design-tool export. Build: `.storybook/` setup; stories per HUD component; `components/REGISTRY.json`
  autogen; Playwright visual snapshots per theme; HUD `/design-system` page. Reuse: CSS tokens. Test
  `frontend/__tests__/test_design_system.spec.ts`. Dep: V2 (readiness board).
- **0.43 Learning Coach Pack** (SEED). Live: `learning/scheduler.py:21-72` (`propose_promotions`),
  `learning/loop.py`. Gap: curriculum DAG, spaced review, progress UI, resource library. Build:
  `learning/curriculum.py:CurriculumEngine` (skill DAG); `schedule_review_task` (Leitner intervals);
  progression tracking; `LearningDashboard.tsx`; `docs/learning/`. Reuse: scheduler enqueue, learning loop.
  Test `tests/test_learning_curriculum.py`. Dep: —.
- **0.62 System Profiles** (MISSING). Live: `llm/model_manager.py:159-190` (VRAM reserve/LRU),
  `bench.py:44-100`. Gap: Gaming/AI/Multimedia/Admin modes, per-profile budgets, switch UI. Build:
  `system/profiles.py:ProfileManager`; `system.active_profile` setting; `HybridRouter.select_backend`
  consults profile (slot/timeout/tokens); wire profile→K3 budgets; `SystemProfileSelector.tsx`. Reuse:
  `model_manager`, `bench`. Test `tests/test_system_profiles.py`. **Dep: K1+K3 (per-profile budgets)+V2.**

### E4 — GPU-gated (owner hardware; validate on the RTX box)
- **0.18 Fine-tune & Digital Twin** (TASK-1 Howard). Seam: `llm/model_manager.py` (load slots),
  `agents/howard/`. Gap: SFT/LoRA harness + labeled Howard dataset → `howard-lora.gguf`. AC: loads slot-2, <3 s. Owner-validated.
- **0.23 Hardware Benchmark Profiles** (PARTIAL). Seam: `bench.py`, `model_manager.py:39-42`. Gap: RTX-model
  scoring + per-card presets. AC: `get_vram_budget("RTX 5090")` returns card-specific defaults. Owner-validated.
- **0.17 Local-Ceiling Concurrency / LRU tail** (H22.4/H22.5). Seam: `model_manager.py` (LRU),
  `hybrid_router.py:334`. Gap: concurrent-request queueing under GPU ceiling, LRU evict under load. AC:
  `enqueue_or_defer(req, timeout=30)` respects slot capacity; p99 flat under burst. Owner load-test.

> **Phase E note:** all tests are greenfield; follow the `conftest.py:make_app` + fake-backend pattern
> (ARCHITECTURE §7). Most entries depend on K1/K3/V2 — do **not** start E before Phase B substrate lands,
> or you re-invent gating the kernel will own.

## Fresh-eyes validation (load-bearing seams spot-checked against the codebase)

Every seam the plan pivots on was re-verified by direct `file:line` lookup. All present and accurate:

| Seam (plan reference) | Verified location |
|---|---|
| Kernel facade target — `security/capability.py:authorize` | `CapabilityBroker:34`, `check:61`, `authorize:117` ✓ |
| Route-tool gate — `mcp/route_tools.py:ROUTE_TOOL_ALLOWLIST` | `RouteToolSpec:51`, `ROUTE_TOOL_ALLOWLIST:72`, `ALLOWLIST_BY_NAME:90` ✓ |
| Workflow bounds — `workflows/engine.py:24-30` | `_TIMEOUT=120:24`, `_MAX_DEPTH=5:26`, `_MAX_PARALLEL_STEPS=8:30` ✓ |
| Approval queue — `autonomy/action_approvals.py` | `ActionApprovalQueue:21`, `request:41`, `decide:74` ✓ |
| AUD purge gap — `data_purge.py:PURGE_DBS` | `:43` lists only `missions/autonomy/analytics.db` → confirms the under-coverage gap ✓ |
| Desktop governance — `desktop_operator.py:GovernedDesktop` | `class:49`, `is_mutating:54` ✓ |
| Pack registry — `skills/marketplace.py:SkillMarketplace` | `class:52`, `publish_skill:89`, `_MIGRATIONS:36` ✓ |

**Corrections folded:** one prior agent claimed `skills/marketplace.py` did not exist — **it does** (verified
above); the 0.58 Pack Manager spec is sound. No hallucinated paths, wrong line numbers, or already-done
items mis-scoped as new were found among the load-bearing seams. The full 200+-file deep cross-check
(every E-theme seam) was delegated to a background validation agent; this table covers the claims the
critical path actually depends on.

---

## Owner / GitHub-settings hand-off (not code work)

- **SEC-4** — promote route-auth-matrix + parity tests to **required** branch-protection checks (F-10).
- **CQ-2** — dismiss the reviewed CodeQL/secret-scan FPs in the GitHub UI.
- **CQ-3** — paste the remaining ~12 CodeQL alerts for triage.
- **Dependabot holds** — React 18→19 (#226), WorldView group (#228), mobile group (#227, real-device).
- **H23.23** — multi-user readiness **decision** (accept single-user for 1.0 & document, or scope per-user isolation).

---

## Verification (how we prove the blueprint executes)

- **Per item:** the regression test named in each entry fails on the un-fixed code and passes after.
- **Per phase:** the exit gate above is green in CI (`python -m pytest tests/ -q` + the new blocking jobs).
- **End-to-end:** boot `python -m uvicorn agents.web:app` and exercise the new endpoints
  (`/api/admin/export`, `/api/metrics/capabilities`, `/autonomy/debug`, `/api/gecko/*`, `/api/media/*`);
  confirm the north-star meter (#300) reflects each pack's accepted actions and the night-shift split.
- **Fresh-eyes validation:** a review agent re-checks every `file:line` and seam in this blueprint against
  the codebase before implementation begins (this document's own gate).
