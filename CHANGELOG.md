# Changelog

## [Unreleased]
### API honesty — two inconsistencies found by running the app (2026-06-10)
- **`GET /api/agents/{id}/history` 404s for unknown agents**, consistent with `/soul` (it
  was returning a misleading `200 + empty runs` for any id, so a typo'd agent looked real
  with no history). Also validates the id against the agent-id alphabet.
- **`POST /learning/promote` of a nonexistent bench agent returns 404 / `ok:false`** instead
  of the old `{ok:true, promoted:false}` that reported success for a no-op. +3 endpoint tests.

### Governance audit pass 3 — 3 promises hold, 1 defense-in-depth gap closed (2026-06-10)
Verified four governance promises against the code (the method that found BUG-14..17):
- **Autonomy risk gate ✅ holds** — ASK-tier tasks go to BLOCKED, `runnable()` queries only
  `approved`, night-shift `max_tier` is enforced at the SQL level, edits are re-gated. An
  irreversible/money task cannot execute without explicit approval.
- **Interrupt budget ✅ holds** — `consume()` gates before every push and again at execute
  time; day-rollover is atomic; the 5th interrupt is held for daily review, not dropped.
- **Capability tokens ✅ hold** — expiry is checked at USE time (not just issue), scope is
  fixed at issue, `authorize()` requires both the token and the kill-switch.
- **Injection quarantine — wired into the untrusted-input gate.** The quarantine primitives
  existed but weren't invoked on the path that turns untrusted text into actions. *Corrected
  severity:* not a critical exploit (chat agents return text, never call mutating tools; the
  only text→task path — transcript ingest — is already hard-forced to ask-tier=3, so nothing
  auto-runs). Closed the defense-in-depth gap: transcript ingest now runs `detect_injection`
  and surfaces `injection_flags` + an `untrusted_source` marker on the **approval card**, so
  the human gate is informed when content is tainted. +1 test. Broader "taint-track every
  external channel" left as a tracked finding (architecture decision — see BACKLOG TASK-3).

### Stability & UX — found by running the app as a first-time user (2026-06-10)
Booted the server and walked the journeys a new user hits before loading a model:
- **Friendly "no model loaded" message.** A fresh install with no LLM returned a raw
  `[jarvis error: No LLM backend available]` as the chat reply — the single most common
  first-run state, with the least helpful message. Now every channel (web/telegram/discord/
  CLI) returns one actionable line: "No language model is loaded yet. Start LM Studio (or
  Ollama)…". Fixed centrally in the orchestrator's agent-call handler.
- **`AGENT_COUNT` no longer drifts.** `/api/status` (consumed by the HUD) reported 16 active
  agents while the roster was 17 — a hardcoded constant. Now computed from the canonical
  registry (`agents.yaml`) with a registry-pinned regression test.
- **Blank turns rejected.** An empty/whitespace `/chat` message was accepted and spent a full
  routing + LLM turn; now rejected with 422 before reaching the orchestrator (`min_length` +
  a not-blank validator). Cheap no-op for an accidental Enter.

### Security — governance promises verified against code, 3 fixes (2026-06-10)
Second docs-vs-code audit pass (same method that found BUG-14):
- **BUG-15 — Howard could reach the cloud.** `_select_howard_backend` short-circuits
  *before* the policy gate, and its last resort was Gemini (`cloud-fallback`) — for the
  LOCAL_ONLY digital twin holding the owner's conversation archive. Now fails closed,
  like Frigga (BUG-14). +1 test.
- **BUG-16 — `llm.cloud_fallback` was a dead knob.** The /admin privacy setting
  (`never|on-demand|always`) was defined and rendered but read by NOTHING — an owner
  selecting "never" still got cloud spill. Now honored live in `HybridRouter`
  (`never` keeps auto-policy agents local even oversized; `always` prefers cloud;
  `on-demand` = previous behavior), re-synced ≤30s by the settings watcher. +6 tests.
- **BUG-17 — the Merkle audit chain was never verified.** `AuditLogger.verify_chain()`
  had zero callers — "tamper-evident" without an evidence check. New
  `GET /api/security/audit/verify` returns `{valid, first_invalid_id, entries}`;
  unit tests prove real tampering and re-linking are detected. +5 tests
  (HUD surface queued in the TASK-2 punch-list).

### Security — strict-local agents fail closed (BUG-14, 2026-06-10)
- **Frigga could reach the cloud.** `HybridRouter.select_backend` with `policy=local` fell
  back to Gemini (`cloud-fallback`) whenever the local backend was down — and a unit test
  enshrined it. This contradicted non-negotiable principle #1 (MOONSHOT §5.1, AGENTS.md:
  "no external calls, no cloud fallback — ever"). Now `policy=local` **fails closed** with an
  explicit error; tests assert frigga is never routed off-machine even with cloud available.
- **`agents.yaml` `llm_policy` is now honored** in routing (it was silently ignored —
  Argus was registered `claude` but routed `auto`). Resolution order: `LOCAL_ONLY_AGENTS`
  security floor (code-enforced, registry can't override) → registry `llm_policy` → in-code
  fallback sets → `auto`. +3 tests; ARCHITECTURE §5 updated.

### HUD v2 depth pass — UI controls for the 2026-06-09 backend wave (2026-06-10)
- **TASK-2 control gap closed** (PR #181) — the parity re-audit found ~37 backend endpoints
  with no HUD v2 control; all now have live surfaces:
  - **Cockpit:** live cognition over SSE (`/api/cognition/stream`, NTH-1) — routing decisions
    stream into the trace as they happen; the post-turn snapshot stays as fallback.
  - **Trust:** payment approve/reject/settle on the real broker ids (H16.3); sender-pairing
    approvals + pairing code (H12.19); prompt-injection scanner (H17.1).
  - **Autonomy & Agents:** heartbeat run/start/stop; transcript→governed-tasks ingest (H12.25);
    escalation targets + send (H12.11); bench promotion (`/learning/promote`); agent templates
    (H10.29).
  - **Build:** AI step builder (H10.7); sandbox execute with honest DEV_MODE 403; marketplace
    review ✓/✕ (H12.12).
  - **Memory/Observe:** nightly-reflection status + run-now; eval dataset runs + compare.
  - **Admin:** LM Studio server start / model load / unload; cloud auth-profile pools (H12.20).
- Admin-guarded Console actions now send the admin token (`actA`) instead of relying on the
  localhost exemption (kill-switch, A2A decide, capability issue, marketplace review, promote).
- `frontend/`: +7 tests (19 total) — payments/review/promote helpers, PairingPanel decide flow,
  SandboxPanel execute + 403 honesty. `tsc` clean; bundle rebuilt to `agents/web/v2/`.
- Punch-list updated: `docs/design/HUD_V2_REMAINING.md` §10 (remaining tail: plugin-gated mode
  wiring, per-panel LIVE/SEED chips, §6 toolchain, locality endpoint).

### HUD voice loop — hands-free voice in the browser (2026-06-07)
- **Browser voice loop** (PR #162) — the HUD mic button was a dead toggle and the voice
  engines only worked for a host-attached mic. New `frontend/src/voice.ts` (`useVoice`)
  captures mic audio (`getUserMedia` + `MediaRecorder`), VAD-segments an utterance, sends it
  to **local Whisper** via `POST /api/voice/stt` (raw body — deliberately no `python-multipart`),
  hands the transcript to the chat turn (`app.tsx: runTurn`, now promise-returning), and
  **speaks the reply** — server `/tts` (cloned voice) with a fully-local `speechSynthesis`
  fallback. Loops hands-free until toggled off.
- **Honest capability reporting** — `GET /api/voice/capabilities` (`{stt,tts,tts_local,providers}`)
  drives the HUD; STT returns `503` + install hint when `faster-whisper` is absent rather than
  fabricating a transcript. `tests/test_voice_stt.py` (+4 mocked, headless).
- **Voice settings** (persisted `localStorage['hud.voice']`, ⚙ popover): hands-free vs
  push-to-talk, speak via server/browser/off, language auto/RO/EN; respects `JARVIS_MIC_MUTED`.
- **Opt-in barge-in** (PR #164, default OFF, experimental) — sustained over-talk above an
  echo-resistant threshold cancels the spoken reply so the loop captures you. Renamed the SPEAK
  option `CLONED`→`SERVER` (it is your cloned voice only when XTTS is configured).
- Docs: `docs/VOICE.md` (new); `docs/ARCHITECTURE.md` §3 + Doc Map updated; BACKLOG H5.16 corrected.
- ⚠️ Live mic/audio + barge tuning need a real device — verified here by `tsc`/`vite build` +
  mocked STT test only.

### Security — Romanian PII detection (2026-06-01)
- **`PIIScanner` now detects Romanian identifiers** (`core/security/scanner.py`),
  closing the long-standing gap between the docs ("Romania-specific, CNP format")
  and the US-only implementation:
  - `ro_cnp` — national ID (CNP), **CRITICAL**, confirmed by the official
    control-digit checksum + birth month/day plausibility, so arbitrary
    13-digit numbers are not flagged.
  - `ro_iban` — Romanian IBAN, **HIGH**, confirmed by the ISO 7064 mod-97
    checksum (case-insensitive, space-tolerant).
  - `ro_phone` — Romanian mobile (`07…`, `+407…`, `0040…`), **MEDIUM**.
  Matches for the checksum-bearing patterns must pass their validator before
  being reported or redacted (a non-CNP 13-digit run is left untouched).
  Exposed `is_valid_cnp` / `is_valid_iban` helpers.
- **First direct test coverage for the scanners** — `tests/test_security_scanner.py`
  (+27 offline tests) covering `SecretScanner`, the existing generic PII patterns,
  the new RO detectors (valid vs. invalid checksum), and `GuardrailsEngine`
  REDACT/BLOCK/WARN behaviour.

### H5.17 Batch & Cache Embeddings (2026-06-01)
- **H5.17 Batch & Cache Embeddings Pipeline** (`core/ingestion/embedder.py`):
  `EmbeddingCache` — content-addressed (`sha256(namespace\x00text)`), sharded,
  crash-safe (atomic temp→rename), with hit/miss stats. `Embedder.embed_batch`
  resolves cache hits first, de-duplicates, and computes only misses (optionally
  across a thread pool). Each backend call is retried with exponential backoff
  and **degrades to the hash embedding** when the budget is exhausted, so a flaky
  rate-limited call never aborts a massive Howard ingest. Cache namespaced by
  `backend:model`; pipeline logs `cache_stats` in Phase 6. +9 offline tests.

### QA pass + Retrieval Fusion (2026-06-01)
- **H5.14 Retrieval Fusion Engine** (`core/memory/fusion.py`): `reciprocal_rank_fusion()`
  (rank-based RRF, no cross-scale normalization, with source provenance + payload
  merge) and `HybridRetriever` blending the vector store (Qdrant/in-memory) with
  the knowledge graph (Neo4j/in-memory); injected + duck-typed, so it is tested
  offline. Exposed as `MemoryManager.hybrid_search(embedding, keyword, top_k)`.
  +9 tests. Plan: `docs/superpowers/plans/2026-06-01-h5.14-retrieval-fusion.md`.
- **Test isolation fix** (CI red → green): `web.orch` leaked across test files,
  causing 2 order-dependent failures (`test_oracle_endpoints`, `test_agent_soul_endpoint`).
  Made the FastAPI `lifespan` teardown symmetric (guarded reset of `orch`/`gateway`
  on shutdown, so a closed `TestClient` context stops leaking a live orchestrator)
  and restored the global in `test_resilience_integration._admin_response`.
- **Backlog sync**: confirmed **H5.12** (Secured Shell Task Executor — `RemediationRunner`)
  and **H5.13** (Proactive Event Watchers — `EventWatcher`) were already delivered,
  wired and tested; marked done. Full suite: **749 passed, 9 skipped**.

### MCU Gap Analysis audit (2026-05-31)
- **FAZA 2 — Intent router rewrite** (`core/router.py`): replaced the v0.1
  keyword stub with a deterministic, offline-first, **scored bilingual (RO/EN)**
  classifier. Fixes substring misroutes ("car"⊄"scared"), routes Romanian
  queries ("câți bani am?"→Gecko, "cum am dormit?"→Hercules), exact-token wake
  words, confidence + score breakdown on `Intent.context`, canonical
  language-independent `keywords_found` tags, and an optional injected LLM
  fallback used only for unmatched/low-confidence input (zero hot-path latency).
  Drop-in: unchanged `classify()`/`Intent`/`ROUTING_TABLE` contract. +47 tests.
- **FAZA 3 — Proactive OS Observer** (`core/autonomy/observer.py`): the missing
  trigger layer. Samples host resources + service liveness, **debounces on state
  change**, and feeds the existing autonomy queue — plain alerts auto-approve
  (HUD/brief), remediation proposals (e.g. "restart Docker?") become tier-3 ASK
  cards in the decision inbox. Injectable probes (offline-testable). Wired into
  `_autonomy_loop` (gated by `system.observer_enabled`) + `/autonomy/observer`
  endpoints. +15 tests. Full suite: **715 passed, 8 skipped** (after reb: H5.9/H5.10).
- `docs/gap-analysis-mcu-jarvis.md` — full audit on 4 axes + OSS benchmark.

### H4 Platform
- **H4.5 Steve System Monitor** — `skills/system_monitor/` skill with 8 commands:
  - `status`, `cpu`, `ram`, `gpu`, `disk`, `temps`, `services`, `check`
  - Auto-recovery for configured services (ollama auto-restart)
  - Alert thresholds: CPU >80%, RAM >85/95%, GPU temp >85°C, disk >80/90/95%
  - Graceful degradation when psutil or nvidia-smi unavailable
  - 24 tests passing
- **H4.9 Guardrails** — already implemented and integrated (WARN/REDACT/BLOCK modes)
- **S0.2 Heartbeat Sanity** — already completed (Steve 2h, Ultron 2x/day)
### H1 Foundation (completed)
- Voice channel with wake word → STT → orchestrator → TTS pipeline
- Telegram channel with session isolation per `chat_id`
- Web channel with streaming, temperature/max_tokens/model from settings DB
- OAuth module (Google Calendar, Gmail, Spotify) with auto-refresh
- Admin DB → runtime settings with 30s refresh watcher loop
### H2 Core Agent Capabilities
- Pepper email triage routing: `email` keyword targets [pepper, veronica, stark]
- WebSearchPlugin: Tavily / SearXNG / DuckDuckGo fallback chain
- Vision agent wired with websearch plugin
### H3 Intelligence
- Heartbeat scheduler (APScheduler) wired in channel startup
- Bench agent activation — failure tracking, promotion/demotion in orchestrator
### H4 Platform
- Discord channel conditioned on `DISCORD_BOT_TOKEN`
- Email channel conditioned on `SMTP_HOST` + `IMAP_HOST`
- Slack channel conditioned on `SLACK_BOT_TOKEN`
### Cross-cutting
- 39 tests all passing

## [0.2.3] — 2026-05-30
### Fixed
- SSE deduplication: `\n\n` split across TCP chunks no longer creates duplicate messages
- Loading/offline indicators in HUD when API is down
- Admin channels panel now shows all 6 channels (including discord, email, slack)
- Deduplicated `AGENT_GLYPHS` — now uses `window.JARVIS_GLYPHS`
- Recycled `VoiceVisualizer` component (~120 lines) and dead CSS (~85 lines)
- Removed unused `SettingsPage` component

## [0.2.2] — 2026-05-30
### Fixed
- Thread-safe settings DB access with `RLock`
- Dynamic agent ring: `intent.target_agents[0]` fragile indexing
- Memory attribution — each agent's memory stays isolated
- Tests: `conftest.py` fixture isolation, `pytest.ini` config
- QA bug plan documented in `.opencode/plans/qa-bugs.md`

## [0.2.1] — 2026-05-30
### Added
- **HUD redesign**: fully offline-capable SPA with vanilla React (no JSX)
  - Admin panel at `/admin` — settings, channels, agents, audit, test LLM
  - Components: `ChatWindow`, `Sidebar`, `AgentOrchestrator`, `SystemTray`, `SettingsPage`
  - Font system: 31 custom woff2 fonts from JetBrains Mono + Cascade Code
  - Animations: network graph (`network.js`), auto-scroll, theme toggle
- **New plugins**: Apple Health, Google Calendar, Homebridge
- **Gemma 4 31B** as default LLM via Ollama
- **Settings DB**: SQLite-backed settings with admin CRUD, reseed, dynamic `force` flag
- **Security**: guardrails engine with PII detection, prompt injection blocking
- **Sandbox**: code execution isolation layer for agent tools
- **Plugin gate**: permission-based plugin access control
- **Tests**: routing, chat, sandbox/gating, startup — 39 total
- **One-click install**: `install.ps1` — virtualenv, deps, Ollama pull, startup
- **`.env.example`**: config template for all channels, OAuth, plugins

### Changed
- Monolithic `app.js` split into `components.js`, `enhancements.js`, `data.js`, `network.js`
- `style.css` reorganized: 1750 lines with density/theming support

### Removed
- JSX build step — vanilla `createElement` throughout
- External CSS/font dependencies — fully self-contained

## [0.1.0] — 2026-05-27
### Added
- Initial commit: Jarvis v0.2.1 multi-agent AI orchestration system
- Multi-agent orchestrator with routing, context, streaming
- Web UI with chat, system tray, agent status
- Plugin system: Weather, News, Gmail, Telegram, Spotify, WhatsApp
- Voice pipeline with wake word detection
