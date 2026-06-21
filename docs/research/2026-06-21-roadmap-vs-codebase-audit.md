# Roadmap-vs-Codebase Audit — the proposed 0.19→1.0 expansion against what's already built

> Date: 2026-06-21 · Method: 6 parallel code-exploration passes over `agents/core/**`, `frontend/`, `skills/`,
> `.github/`, `docs/`. Verdicts are grounded in concrete `file:line` / module evidence (see each row).
> Input roadmap: the uploaded `PLAN.md` ("Competitive Gap Plan: OSS Repos → Bigger Pre-1.0 Roadmap"),
> a **proposed** 0.19–1.0 expansion. The numbers `0.19…0.63` are that plan's, not the current BACKLOG version line.

## TL;DR

The proposed roadmap is **~85% already seeded**. Of the 44 feature versions (0.19–0.63):

| Verdict | Count | Meaning |
|---------|-------|---------|
| ✅ **DONE** | 6 | Working code that meets (most of) the Done-When |
| 🟢 **PARTIAL** | ~19 | Core built; a clear, bounded gap remains (often just a HUD panel or wiring) |
| 🟡 **SEED** | ~12 | A real module exists but the feature is mostly unbuilt |
| ⬜ **MISSING** | 7 | Genuinely greenfield |

**Truly greenfield (the only 7 that start from zero):** 0.20 Jarvis Vault · 0.42 Security Skills Pack ·
0.48 Video Production · 0.52 Product Demo Factory · 0.55 Design Partner Kit · 0.57 Release Packaging ·
0.62 System Profiles.

**Implication:** this should not be sequenced as 44 new builds. The fastest path to value is *finishing the
PARTIAL/DONE items that are 80% there* — most of which are **HUD panels + wiring over existing backends**,
and several of which directly unblock the north-star measurement that 1.0 actually gates on.

---

## Full audit

### Appliance / Storage / Packs / Release / DB
| Ver | Item | Verdict | Evidence | Gap to Done-When |
|-----|------|---------|----------|------------------|
| 0.19 | First-Run Command Center | 🟢 PARTIAL | `routers/onboarding.py`, `routers/status.py`, demo mode `frontend/src/api/loaders.ts` | one unified install-health + model-status + first-action screen |
| 0.20 | Jarvis Vault | ⬜ MISSING | `paths.py` (data root), `secrets_vault.py` (secrets only) | 1 TB vault, retention controls, backup/export endpoints |
| 0.21 | Offline Knowledge Packs | 🟡 SEED | `local_docs.py` (txt+PDF → memory) | Kiwix-style packaged docs + downloadable RAG collections + installer |
| 0.22 | Appliance Install/Update | 🟢 PARTIAL | `install.sh`, `start.sh`, `docker-compose.yml` | uninstall script, restore drill, signed artifacts, no-telemetry proof |
| 0.23 | HW Benchmark & Profiles | 🟢 PARTIAL | `bench.py`, `llm/model_manager.py` (VRAM headroom/eviction) | RTX scoring + mode profiles |
| 0.29 | Native Launcher | 🟢 PARTIAL | **`desktop/src-tauri/tauri.conf.json` (Tauri shell + tray exists)** | PWA manifest/SW, signed installers |
| 0.57 | Release Packaging | ⬜ MISSING | `.github/workflows/release.yml` (basic notes only) | signed artifacts, SBOM/NOTICE, compat matrix, upgrade path |
| 0.58 | Pack Manager | 🟢 PARTIAL | `skills/marketplace.py` (SQLite registry, install/update/review-gate) | unify model/domain/content packs; remove/rollback |
| 0.61 | DB Future Check | 🟡 SEED | `settings_db.py` (WAL), column-migration in `marketplace.py` | Turso/libSQL eval, formal migration framework |
| 0.62 | System Profiles | ⬜ MISSING | — (VRAM mgmt exists, no profiles) | Gaming/AI/Multimedia/Admin modes |

### Voice / Desktop / Capture / Vision
| Ver | Item | Verdict | Evidence | Gap |
|-----|------|---------|----------|-----|
| 0.24 | Voice Hotkey & Dictation | 🟢 PARTIAL | `voice/{wake_word,stt,pipeline}.py` (openWakeWord + faster-whisper) | hold-to-talk hotkey, filler removal, Parakeet option |
| 0.25 | Desktop Control Pack | 🟡 SEED | `desktop_operator.py`, `screen_grounding.py`, `browser_agent.py` | screen recording, app launch, OS volume/power, PDF read |
| 0.26 | Capture Inbox | 🟢 PARTIAL | `passive_capture.py` (H12.7 multi-surface + redaction + KG ingest), `routers/capture.py` | phone export, transcript→capture sync |
| 0.27 | Local VLM Eyes | ✅ DONE | `llm/vlm.py` + `GET /api/vlm/status` + `POST /api/vlm/describe`, `screen_grounding.py` | real-time webcam loop (plumbing exists) |
| 0.28 | Voice Persona Studio | 🟢 PARTIAL | `cognition/persona.py`, `voice/tts.py` (edge→Kokoro→pyttsx3), `voice/sentence_stream.py`, `ttsStream.ts` | voice consent, clone weights, barge-in→HUD wiring (BUG-2b.3) |

### Runtime / Agents / Context / Manifest / Memory
| Ver | Item | Verdict | Evidence | Gap |
|-----|------|---------|----------|-----|
| 0.30 | Context Compression | ✅ DONE | `context_compressor.py` wired in `routers/tools.py` | auto-run on every turn (currently tool endpoint) |
| 0.31 | Code Intelligence MCP | 🟡 SEED | `mcp/{client,server}.py` | code-indexing backend / source-code KG decision |
| 0.32 | Mission Workspaces | 🟡 SEED | `autonomy_coordinator.py`, `autonomy/executor.py` | persistent workspace obj: files/plan/state/pause-resume/budget |
| 0.33 | Subagent Gateway | ✅ DONE | `subagents.py` (concurrency-capped), `autonomy_coordinator.py`, `a2a.py` (HMAC + inbox) | per-subagent result-review UI, sandbox callbacks |
| 0.34 | Workflow Runtime Upgrade | 🟢 PARTIAL | `workflows/engine.py` (per-step 120s timeout, max-parallel 8, recursion cap 5) | persistent job queue, execution pruning/backpressure |
| 0.35 | Prompt Registry | ✅ DONE | `soul_versioning.py` (git-like commit/diff/rollback + A/B experiments) | diff UI, auto-eval/harden gate |
| 0.36 | Agent-Native Action Manifest | ✅ DONE | `mcp/route_tools.py` + `web.py:1119-1190` (read+mutating tools, identity gate, audit) | broaden allow-list; **unify with `route_auth.json` (the seam I flagged)** |
| 0.37 | Memory Ingestion Lab | 🟢 PARTIAL | `ingestion/pipeline.py` (7-phase ETL), `data_spaces.py` | ontology suggestions, cross-agent sharing, provenance |

### Domain Packs
| Ver | Item | Verdict | Evidence | Gap |
|-----|------|---------|----------|-----|
| 0.38 | Today In Jarvis | 🟢 PARTIAL | `autonomy/digest.py` (morning brief), `memory/digest.py` | unified chronological timeline of captures/memories/decisions/risks |
| 0.39 | Market Intel Pack | 🟡 SEED | `plugins/{balance,analytics,signal_layer}.py` (`world_brief()`) | watchlists, source priority, alerts, disclaimers |
| 0.40 | OSINT Investigator Pack | 🟡 SEED | `plugins/worldview.py`, `argus.py` (governed facade) | SpiderFoot modules, correlation rules, evidence drawer, exports |
| 0.41 | World Signal Packs | 🟡 SEED | `signal_layer.py` (`signals/world_brief/country_assessment/ask_world`) | per-domain signal routing (finance/cyber/aviation…) |
| 0.42 | Security Skills Pack | ⬜ MISSING | `security/` is infra, not curated skills | ATT&CK/ATLAS/D3FEND/NIST skill taxonomy |
| 0.43 | Learning Coach Pack | 🟡 SEED | `learning/scheduler.py` (agent promotion, not tutoring) | curriculum, spaced review, progress, resource library |
| 0.44 | Safe Comms Pack | 🟢 PARTIAL | `channels/{telegram,email}.py`, `whatsapp_bridge.py`, `autonomy/action_approvals.py` | draft-before-send UI, per-channel rate limits |
| 0.45 | High-Risk Automation Contracts | 🟢 PARTIAL | `plugin_gate.py`, `signal_governance.py`, `routers/payments.py` (mandate/cap/approval) | reusable contract-template abstraction |

### Media / Creative / Publishing / Design
| Ver | Item | Verdict | Evidence | Gap |
|-----|------|---------|----------|-----|
| 0.46 | Media Library | 🟢 PARTIAL | `media_gen.py`, `media_skill.py` (yt-dlp→Whisper→summary) | local catalog, searchable timeline, export bundles |
| 0.47 | Creative Asset Pipeline | 🟡 SEED | `video_prompt.py`, `image_gen.py`, `media_gen.py` | coordinated multi-asset pipeline + provenance |
| 0.48 | Video Production Pipelines | ⬜ MISSING | `video_prompt.py` is a prompt builder only | assembly/effects/localization/multi-format export |
| 0.49 | Timeline Adapter | 🟢 PARTIAL | `canvas.py` (governed canvas), `worldview/.../timelineMarkers.ts` | interactive, approval-gated timeline control |
| 0.50 | Publishing Studio | 🟡 SEED | `writeback.py` (Notion/GitHub/GCal), `social.py` (X) | export/render packs (YouTube/IG/README/landing) |
| 0.51 | Reference-Driven Creation | 🟢 PARTIAL | `plugins/websearch.py` (SSRF-safe fetch) | reference→grounded-plan choreography |
| 0.52 | Product Demo Factory | ⬜ MISSING | `docs/marketing/TEASER_PACK.md` (storyboard only) | HUD-footage capture + artifact assembly |
| 0.53 | Design System Manifest | 🟢 PARTIAL | `frontend/src/styles.css` (tokens), `BRAND_BOOK.md`, `DESIGN_BRIEF.md` | inspectable component library / UI contracts |

### Skills / Partner / Trust / Analytics / Gates
| Ver | Item | Verdict | Evidence | Gap |
|-----|------|---------|----------|-----|
| 0.54 | Skill Operating System | ✅ DONE | `skills/{loader,importer}.py`, `skill_drift.py`, SKILL.md manifests | HUD trigger UI, mandatory safety gate |
| 0.55 | Design Partner Kit | ⬜ MISSING | — (BACKLOG H23.21) | feedback/NPS widget, issue bundle, check-in, SLA |
| 0.56 | Trust Center | 🟢 PARTIAL | `security/audit.py` (Merkle), `routers/security.py` (`audit_verify`, `kill_switch_*`), `hybrid_router.py:LOCAL_ONLY_AGENTS`, `data_spaces.delete` | **kill-switch UI**, consent flow, cloud-hop log, network-monitor proof |
| 0.60 | Local Analytics | 🟢 PARTIAL | `analytics_store.py`, `observability/north_star.py`, `GET /api/metrics/north-star` | **HUD north-star panel**, activation funnel |
| 0.63 | Restore & Soak | 🟡 SEED | `resilience.py`, `native_fallback.py`, `tests/test_resilience*.py`, `MANUAL_TESTING.md` | 72h soak, one-command backup/restore, failure injection |
| 0.90–1.0 | Release Gates | 🟢 PARTIAL | `AUDIT.md`, `MANUAL_TESTING.md`, `test_route_auth_matrix.py`, `test_north_star.py` | promote eval→required gate; design partners (blocks 1.0, H23.23); landing+demo |

---

## How this reconciles with the existing BACKLOG

The proposed `PLAN.md` is a **product-maturity** expansion; the existing BACKLOG H23 layer is the
**productionization** spine. They overlap heavily — the audit shows most PLAN items map onto existing
H23 rows or already-shipped horizons:

- 0.56 Trust Center ≈ H23.3 (kill-switch UI) + H23.5 (audit verify UI) + H23.16 (network monitor) — **all EXISTS-code/no-UI.**
- 0.60 Local Analytics ≈ H23 north-star (instrumented) + H23.20 activation funnel — backend done, **HUD panel missing.**
- 0.20 Vault / 0.63 Restore ≈ H23.7–H23.10 (migrations, backup/restore, export-delete, retention).
- 0.57 Release Packaging ≈ H23.13/H23.14.
- 0.55 Design Partner Kit ≈ H23.21; 0.52/0.59 ≈ H23.22.

So the PLAN doesn't replace the version line — it **fans the same destinations into finer, product-flavored slices.**

## Recommended next moves (value per unit effort)

Finish-what's-80%-there beats start-greenfield. Ranked:

1. **Unify the Action Manifest (0.36) with `route_auth.json`** — the seam from the prior analysis. Behavior-preserving,
   hardens #279, and the single source of truth pays off for 0.32/0.49/HUD. *Pure refactor-adjacent; fully autonomous.*
2. **Trust Center + Local Analytics HUD panels (0.56 + 0.60)** — backends already expose `kill_switch_*`,
   `audit_verify`, and `/api/metrics/north-star`. This is **TASK-2 HUD depth**, and it directly unblocks the
   **north-star measurement that 1.0 gates on**. Highest product leverage; no new backend.
3. **Mission Workspaces (0.32)** — promote `autonomy_coordinator` + `subagents` into a persistent workspace object
   (files/plan/state/pause-resume/audit). High "mission control" demo value; the runtime pieces exist.
4. **Backup/restore + export-delete (0.20/0.63 ≈ H23.8/H23.9)** — the biggest genuine durability gap; real 1.0 blocker.

Greenfield items (0.42, 0.48, 0.52, 0.62) are lower priority — defer until the finish-the-PARTIALs wave lands.
