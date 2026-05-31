# Changelog

## [Unreleased]
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
