# Changelog

## [Unreleased]
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
