# Jarvis Hub — Architecture Reference

> For assistant conventions see **AGENTS.md** | architecture overview: **JARVIS.md** | tasks: **BACKLOG.md**

---

## 1. TL;DR / Orientation

- Local-first multi-agent AI orchestration. Python 3.12 + FastAPI + LM Studio (port 1234).
- 17 active agents (4 tiers, incl. Argus + Howard), 17 bench agents (dormant, promotable at runtime).
- Single entry point for web: `serve.py` → `agents/web.py` (FastAPI `app`); uvicorn binds on port 8080.
- CLI REPL entry point: `agents/run.py` → `Orchestrator.handle_input`.
- Everything routes through `agents/core/orchestrator.py:Orchestrator`.
- Memory is the heart: `agents/core/memory/` — conversation + vector + graph + RRF fusion.

---

## 2. Request Lifecycle

### `Orchestrator.handle_input` (non-streaming)

```
1. memory.add_turn(session_id, "user", text)          [manager.py:add_turn]
2. skills.parse_command(text)                          [skills/loader.py]
   → if skill match: execute + persist + return early
2b. detect_llm_control(text)                           [orchestrator.py:detect_llm_control]
   → if LLM-control intent (start/load/unload/status) AND _chat_control_enabled():
     _run_llm_control → LMStudioController → narrate REAL result + return early.
     Conservative: a load needs a plausible model token, so "load up the data"
     never fires. Kill-switch gated (§5 LM Studio control).
3. router.classify(text, agents) → Intent              [router.py:IntentRouter.classify]
   → deterministic keyword/phrase matching, bilingual RO/EN
4. _gather_plugin_data(text, intent)                   [orchestrator.py:_gather_plugin_data]
   → weather / news / calendar / email / websearch (parallel)
5. _route_candidates(intent)                           [orchestrator.py:_route_candidates]
   → learning loop reranks + filters unhealthy agents
6. llm_router.select_backend(agent_id, prompt)         [llm/hybrid_router.py:HybridRouter.select_backend]
   → (backend, model, route_name)
7. _call_agents_parallel(agent_ids, ...)               [orchestrator.py:_call_agents_parallel]
   → builds prompt: history + plugin_block + recall_block + rag_block
   → each agent: agent.process(enriched_text, context)  [agent.py:Agent.process]
   → 120s asyncio.wait_for timeout per agent
8. if multi-agent: _synthesize(responses, intent)      [orchestrator.py:_synthesize → agent.py:Agent.synthesize]
9. memory.add_turn(session_id, "assistant", synthesized)
10. _maybe_checkpoint()                                 [H7.3: every N turns, default 5]
    → asyncio.to_thread(checkpoints.save, self)        [H7.2: off event loop]
11. asyncio.to_thread(_log_session, ...)               [H7.2]
12. asyncio.to_thread(_record_interactions, ...)       [learning.record + bench.record]
13. asyncio.to_thread(audit.log, SecurityEvent)        [H7.2: SQLite WAL]
```

### `Orchestrator.handle_input_stream`

Same flow but step 7 calls `backend.generate_stream(..., on_token=on_token)`.
- Gemini route: context cache checked/created async via `_async_create_cache`.
- `ThinkingStreamFilter` strips `<think>...</think>` blocks live during streaming.
- `_recall_block(text)` → `memory.recall(text, top_k=k)` injected into prompt (opt-in).
- Same `detect_llm_control` short-circuit as non-streaming (step 2b): the narrated
  result is pushed via `on_token` and returned before routing.

### Recall injection

`_recall_block` is called in both paths. Controlled by `memory.recall_enabled` (default `False`).
When on: embeds the query, runs fused recall (vector ⊕ graph), injects top-k as a prompt prefix.

---

## 3. Module Index

### Orchestration

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/serve.py` | Uvicorn launcher | `app` import from `agents/web.py` |
| `agents/run.py` | CLI REPL | `main()` |
| `agents/web.py` | FastAPI app shell + lifespan; mounts the 65 per-domain routers. Only **9 inline routes** stay here (app-shell `/`,`/v1`,`/v2`,favicon,sw.js + `/chat`,`/chat/stream` + `/admin`). The rest of the route surface (live count in STATUS.md, synced by `scripts/status_sync.py`) lives in `agents/core/routers/*` (CLN-3, #296) | `app`, `lifespan`, `orch` global, `_user_guard`, `_admin_guard` |
| `agents/core/routers/*.py` | **The HTTP surface** — 65 per-domain `APIRouter`s (agents_api, tools, ops, payments, eval, workflows, sessions, memory_hud, status, dashboard, voice, mcp, media_director, house, cameras, acquisition, ambient, self_improvement, …). Guards from `routers/_deps.py`; shared state via `app_state.get_orch()` / `sys.modules["agents.web"]` | one `router` per file, mounted via `app.include_router` |
| `agents/core/orchestrator.py` | Main loop (+ delegated managers: `ChannelManager`, `PluginManager`, `llm_control`, `cognition_trace`, CLN-2) | `Orchestrator`, `handle_input`, `handle_input_stream`, `_maybe_checkpoint` |
| `agents/core/routers/brain.py` | Neural Mesh page (`/brain`) + live feed (`/api/brain/summary`) — tracer rollups → canvas "brain" of agents+models firing. Viz adapted from Axon (MIT, `LICENSES/axon-MIT.txt`) | `build_summary`, `brain_page`, `brain_summary` |
| `agents/core/agent.py` | Single agent runtime | `Agent`, `Agent.process`, `Agent.synthesize`, `Agent._load_soul` |
| `agents/core/router.py` | Intent classifier | `IntentRouter.classify`, `Intent`, `INTENT_RULES` |
| `agents/core/config.py` | YAML config loader | `JarvisConfig` |
| `agents/core/heartbeat.py` | Scheduled agent heartbeats | `HeartbeatScheduler` |
| `agents/core/errors.py` | Typed error codes | `JarvisError`, `E_*` constants |
| `agents/core/log.py` | Logging setup | `setup_logging`, `log_error` |
| `agents/core/resilience.py` | Circuit breakers + retry | `resilient_call`, `get_metrics`, `_circuit_breakers` |

### LLM

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/llm/base.py` | Abstract backend + LMStudio + Ollama | `LLMBackend`, `LMStudioBackend`, `OllamaBackend`, `strip_thinking`, `ThinkingStreamFilter` |
| `agents/core/llm/router.py` | Auto-detect LMStudio → Ollama | `LLMRouter.detect` |
| `agents/core/llm/hybrid_router.py` | Multi-tier routing engine | `HybridRouter.select_backend`, `is_heavy_request`, `LOCAL_ONLY_AGENTS`, `CLAUDE_AGENTS`, `DEEP_THINK_AGENTS` |
| `agents/core/llm/lmstudio_control.py` | Start LM Studio server + load/unload models via `lms` CLI (no-shell, probed); refreshes live router; `enabled` kill-switch makes mutating ops no-ops | `LMStudioController.start_server/load_model/unload_model/status/set_enabled` |
| `agents/core/orchestrator.py` (chat control) | Detect + run LLM control from a chat message ("load gemma", "start LM Studio", "what model?") and narrate the real result | `detect_llm_control`, `_run_llm_control`, `_control_master_enabled`, `_chat_control_enabled` |
| `agents/core/llm/anthropic.py` | Claude API backend | `ClaudeBackend` |
| `agents/core/llm/gemini.py` | Gemini API backend | `GeminiBackend` |
| `agents/core/llm/gemini_cache.py` | Gemini context cache | `ContextCache`, `create_or_extend` |
| `agents/core/llm/tokenizer.py` | Token estimation | `estimate_tokens`, `estimate_messages` |
| `agents/core/llm/cost_estimator.py` | Monthly cost estimation | `estimate_monthly` |

### Memory & Recall

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/memory/manager.py` | Memory orchestration | `MemoryManager`, `embed`, `remember`, `recall`, `hybrid_search`, `add_turn` |
| `agents/core/memory/conversation.py` | Session history (JSONL, disk) | `ConversationMemory`, `Turn`, `add_turn`, `get_context` |
| `agents/core/memory/store.py` | In-memory vector store | `InMemoryVectorStore`, `VectorStore`, `VectorRecord` |
| `agents/core/memory/qdrant_store.py` | Qdrant vector store | `QdrantVectorStore` |
| `agents/core/memory/graph.py` | Knowledge graph | `KnowledgeGraph`, `InMemoryGraph`, `Neo4jGraph` |
| `agents/core/memory/fusion.py` | RRF retrieval fusion | `HybridRetriever.retrieve`, `reciprocal_rank_fusion`, `FusedHit` |
| `agents/core/memory/persistence.py` | JSON session persistence | `save_memory`, `load_memory`, `list_sessions` |
| `agents/core/memory/seed_graph.py` | Bootstrap knowledge graph | `seed_graph` |

### Autonomy / Proactive

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/autonomy/queue.py` | SQLite task queue + state machine | `TaskQueue`, `Task`, `TaskStatus`, `TaskQueueError` |
| `agents/core/autonomy/worker.py` | Queue + policy glue | `AutonomyWorker.submit`, `AutonomyWorker.tick`, `AutonomyWorker.apply_decision`, `InterruptBudget`, `is_night_window` |
| `agents/core/autonomy/policy.py` | Risk gate | `AutonomyPolicy`, `RiskTier`, `ACT/NOTIFY/ASK` |
| `agents/core/autonomy/inbox.py` | Decision card builder | `build_decision_card` |
| `agents/core/autonomy/digest.py` | Morning brief / evening retro | `build_morning_brief`, `build_evening_retro` |
| `agents/core/autonomy/observer.py` | Host resource probes | `ProactiveObserver`, `default_probes` |
| `agents/core/autonomy/watchers.py` | Personal event probes | `EventWatcher`, `EmailProbe`, `CalendarProbe`, `FinanceProbe`, `HealthProbe` |
| `agents/core/autonomy/remediation.py` | Safe service restart | `RemediationRunner.restart` |
| `agents/core/autonomy/preferences.py` | Approved-action learning | `PreferenceStore`, `suggest_autonomy_raise` |
| `agents/core/autonomy/reflection.py` | Nightly LLM reflection | `DailyReflector.run` |
| `agents/core/autonomy/executor.py` | Task kind → handler dispatch | `TaskExecutor`, `executor.register` |
| `agents/core/autonomy/error_logger.py` | Persist + group runtime errors → git-ignored `diagnostics.md` (never BACKLOG.md) | `persist_problem`, `summarize_problems`, `sync_problems_to_diagnostics` |
| `agents/core/autonomy/tech_scout.py` | Proactive Technology Scout — weekly, read-only websearch scan → informational (`RiskTier.READ_ONLY`) autonomy tasks; default-off | `TechScout.scan`, `TechScoutStore` |

### Action Kernel / Budgets

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/kernel/budget.py` | K3 scheduler ledger: token/wall-time/recursion budgets, loop breaker, and named dimensions for interrupt/mission/payment caps | `BudgetLedger`, `BudgetDimension`, `LoopDetector` |
| `agents/core/kernel/binding.py` | Binds orchestrator/config state into kernel hooks and shared ledgers | `make_action_kernel`, `make_budget_ledger` |
| `agents/core/action_origin.py` | Per-turn provenance carrier for kernel-mediated actions; public turn entrypoints bind origin by construction, inbound channels stay `origin="inbound"`, and an inbound parent context cannot be downgraded | `origin_for_channel`, `bind_turn_action_origin`, `current_action_origin` |

### Security

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/security/guardrails.py` | Scan/redact/block wrapper around LLM | `GuardrailsEngine`, `SecurityBlockError` |
| `agents/core/security/scanner.py` | Secret + PII scanners | `SecretScanner`, `PIIScanner` |
| `agents/core/security/audit.py` | SQLite audit + Merkle chain | `AuditLogger.log` |
| `agents/core/security/ssrf.py` | Private-IP SSRF protection | `SSRFProtector` |
| `agents/core/security/types.py` | Enums + data classes | `ScanFinding`, `ThreatLevel`, `RedactionMode`, `SecurityEvent` |
| `agents/core/security/quarantine.py` | Prompt-injection scanner + datamark/spotlight for untrusted text | `detect_injection`, `datamark`, `spotlight` |
| `agents/core/security/taint.py` | Untrusted-source taint flag (the kernel escalates a tainted action GRANT→QUEUE) | `mark`, `is_tainted`, `is_untrusted_source`, `UNTRUSTED_SOURCES` |
| `agents/core/security/rag_guard.py` | CDX-7 choke point: fence retrieved memory as untrusted DATA before a prompt (scan/redact/datamark/provenance) | `wrap_memory`, `provenance_from_hit`, `REDACTION` |
| `agents/core/security/hardened.py` | CDX-12 "Design-Partner / Hardened" preset (`JARVIS_HARDENED`): guardrails→REDACT, audit-key required, strict egress, mutating-MCP off | `enabled`, `posture`, `enforce`, `guardrails_default` |

### Channels

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/channels/base.py` | Abstract channel | `ChannelAdapter.start/stop/send/receive` |
| `agents/core/channels/web.py` | SSE streaming channel | `WebChannel` |
| `agents/core/channels/voice.py` | Voice channel — wraps `VoicePipeline` (server-side mic) | `VoiceChannel` |
| `agents/core/channels/telegram.py` | Telegram bot | `TelegramChannel`, `send_card`, `on_callback` |
| `agents/core/channels/discord.py` | Discord bot | `DiscordChannel` |
| `agents/core/channels/email.py` | SMTP + IMAP | `EmailChannel` |
| `agents/core/channels/slack.py` | Slack bot | `SlackChannel` |
| `agents/core/channels/gateway.py` | Message routing gateway (incl. inbound rate limit) | `Gateway.route` |
| `agents/core/channels/webhook_channels.py` | HTTP webhook channels (WhatsApp/Signal/Matrix/Teams/Google Chat) | `WebhookChannel`, `build_send`, `parse_inbound` |
| `agents/core/channels/send_rate_limit.py` | 0.44 opt-in per-channel **outbound** send rate limit (`JARVIS_CHANNEL_SEND_RATE[S]`) | `allow_send`, `SendRateLimiter`, `limit_for` |

### Plugins

| Path | Purpose | Notes |
|------|---------|-------|
| `agents/core/plugins/weather.py` | wttr.in weather | `WeatherPlugin.get_weather` |
| `agents/core/plugins/news.py` | BBC RSS news | `NewsPlugin.summarize` |
| `agents/core/plugins/cloud_llm.py` | Anthropic/OpenAI/Gemini fallback | `CloudLLMPlugin` |
| `agents/core/plugins/websearch.py` | Tavily + SearXNG | `WebSearchPlugin.search` |
| `agents/core/plugins/gmail_plugin.py` | Gmail API | `GmailPlugin` |
| `agents/core/plugins/google_calendar.py` | Google Calendar | `GoogleCalendarPlugin.get_today_events` |
| `agents/core/plugins/spotify_plugin.py` | Spotify | `SpotifyPlugin` |
| `agents/core/plugins/balance.py` | ING/Libra bank balance | `BalanceReaderPlugin` (gecko) |
| `agents/core/plugins/analytics.py` | first-party local analytics (Plausible-style; GA4 mirror opt-in) | `AnalyticsPlugin` (stark) |
| `agents/core/analytics_store.py` | local SQLite event table (H22); aggregate-on-read | `record_event` / `kpis` |
| `agents/core/plugins/oracle_bridge.py` | GitHub watcher | `OracleBridgePlugin` |
| `agents/core/plugins/n8n.py` | n8n workflows | `N8NPlugin` |
| `agents/core/plugins/homebridge.py` | HomeKit / Homebridge | `HomebridgePlugin` |
| `agents/core/plugins/apple_health.py` | Apple Health bridge | `AppleHealthPlugin` |
| `agents/core/plugins/sms_alerts.py` | Twilio SMS | `SMSAlertsPlugin` |
| `agents/core/plugins/crm_sync.py` | Notion CRM | `CRMSyncPlugin` |
| `agents/core/plugins/iot_control.py` | Tuya smart home | `IoTControlPlugin` |
| `agents/core/plugins/revenuecat.py` | RevenueCat revenue metrics (read-only) | `RevenueCatPlugin` |
| `agents/core/plugins/meta_ads.py` | Meta Ads insights (read-only) | `MetaAdsPlugin` |
| `agents/core/plugins/postiz.py` | Postiz social scheduler (draft-first) | `PostizPlugin` |
| `agents/core/plugins/whatsapp_bridge.py` | WhatsApp bridge | `WhatsAppBridgePlugin` (frigga) |
| `agents/core/plugins/telegram_bot.py` | Telegram bot plugin | `TelegramBotPlugin` |
| `agents/core/plugins/oauth.py` | OAuth token store | `init_from_env`, `load_token` |

### Skills

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/skills/loader.py` | Skill discovery + execution; CDX-8: auto-generated skills are quarantined `PENDING_REVIEW` (not exec'd) until `approve_generated_skill` | `SkillLoader.discover`, `Skill.execute`, `parse_command`, `generate_skill`, `approve_generated_skill` |
| `agents/core/skills/importer.py` | Import from Hermes/OpenClaw/GitHub | `SkillImporter.import_from_hermes` |
| `agents/core/skills/marketplace.py` | Local marketplace (install/publish/zip + 0.58 uninstall/remove) | `SkillMarketplace`, `uninstall_skill`, `remove_from_registry` |
| `agents/core/skills/signing.py` | Skill signature (SKILL.sig) — sign/verify, `JARVIS_REQUIRE_SIGNED_SKILLS` | `sign_skill`, `verify_skill`, `require_signed` |
| `skills/<name>/SKILL.md` | Skill manifest (version, agents, commands) | — |
| `skills/<name>/main.py` | Skill logic; must expose `handle(cmd, args, ctx)` or `get_commands()` | — |

Built-in skills: `brief`, `calendar`, `content`, `email_triage`, `family_store`, `health`, `pm`, `security_monitor`, `spotify`, `system_monitor`, `weather`, `web_research`.

### Capability packs & system modules

Pure, offline, deterministic capability packs (ORIZONT-24 Track P + the 0.4x roadmap) and
cross-cutting system modules. Each pack is honest (carries a disclaimer / `generated:false` /
`curated:true`, never fabricates) and read-only unless a governance rail is named; routers live
under `agents/core/routers/<name>.py`.

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/osint/correlate.py` | P2 OSINT — governed correlation over provided evidence | `correlate`, `build_brief`, `writeback_payload` |
| `agents/core/market/analyze.py` | P3 Market Intel — watchlist alerts + portfolio snapshot + daily brief (honest `no_quote`) | `evaluate_watchlist`, `portfolio_snapshot`, `daily_brief`, `DISCLAIMER` |
| `agents/core/creative/pipeline.py` | P4 Creative — pipeline planner + export packs; release held by the kernel | `plan_pipeline`, `build_export_packs`, `release_action_payload` |
| `agents/core/security_skills/pack.py` | 0.42 Security Skills — curated ATT&CK/D3FEND/NIST taxonomy + behavior→technique heuristic + playbook | `tactics`, `techniques`, `map_behavior`, `build_playbook` |
| `agents/core/coach/pack.py` | 0.43 Learning Coach — SM-2 spaced repetition + session builder + curriculum planner (stateless) | `review`, `build_session`, `plan_curriculum` |
| `agents/core/codeintel/index.py` | 0.31 Code Intelligence — AST symbol index over the source (also an MCP route tool) | `build_index`, `search_symbols`, `project_index` |
| `agents/core/system_profiles.py` | 0.62 usage-mode posture presets (`JARVIS_SYSTEM_PROFILE`); gates proactive heartbeats | `active_posture`, `list_profiles`, `PROFILES` |
| `agents/core/support_bundle.py` | 0.55 design-partner diagnostic bundle (non-sensitive, allow-list) | `build_bundle` |
| `agents/core/workflows/run_store.py` | 0.34 opt-in workflow run-history persistence (`JARVIS_WORKFLOW_PERSIST`) | `WorkflowRunStore` |
| `agents/core/plugin_gate.py` | Per-agent plugin permission gate + CDX-11 least-privilege (`agents_served` wildcard withheld for external-write under hardening) | `PermissionGate.check_call`, `add_grant`, `least_privilege_from_env` |
| `agents/core/house/` | H30 default-off Home Assistant adapter, private presence state, governed actuation, and room output | `HomeAssistantAdapter`, `HouseGraph`, `HouseActuator` |
| `agents/core/cameras/` | H31 consent-bound Frigate events, privacy masks, local rules/VLM, encrypted vault, retrieval, and typed feeds | `CameraPrivacyPolicy`, `CameraIngestionService`, `CameraEventVault` |
| `agents/core/ambient/` | H33 default-off declarative monitors over sanitized house/camera/digital events; durable debounce, health, journal, and source ownership | `AmbientEngine`, `MonitorRegistry`, `SourceOwnershipManager` |

### Voice

Two front-ends, shared engines — full subsystem doc: **`docs/VOICE.md`**.

**Browser HUD loop** (the one that ships — mic in the browser at `/v2`):

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `frontend/src/voice.ts` | mic capture + VAD + STT call + TTS playback + hands-free loop + opt-in barge-in | `useVoice` |
| `agents/web.py` | `POST /api/voice/stt` (raw audio body → Whisper), `GET /api/voice/capabilities` | `stt_endpoint`, `_stt_engine`, `voice_capabilities` |
| `agents/web.py` | `POST /tts` (text → cloned voice, fallback chain) | `tts_endpoint` |

**Server-side pipeline** ("Howard", host-attached mic; scaffolded, optional deps):

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/voice/pipeline.py` | Wake → STT → TTS coordinator | `VoicePipeline` |
| `agents/core/voice/stt.py` | faster-whisper STT | `STTEngine` |
| `agents/core/voice/tts.py` | TTS fallback chain (XTTS→ElevenLabs→Fish Audio→edge-tts→Kokoro); inline `[emotion]` tags pass through to Fish, stripped for other backends | `TTSEngine.speak`, `strip_emotion_tags` |
| `agents/core/voice/wake_word.py` | openWakeWord detection | `WakeWordDetector` |
| `agents/core/voice/wyoming.py` | Wyoming protocol, gated `voice.wyoming_enabled` (port 10700) | `WyomingServer` |

### Ingestion (Howard Digital Twin)

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/ingestion/embedder.py` | Text embedding + cache layers | `Embedder.embed`, `Embedder.from_env`, `EmbeddingCache`, `_PROC_CACHE` (LRU) |
| `agents/core/ingestion/pipeline.py` | Facebook/WhatsApp → vectors | `IngestionPipeline.run`, `search_similar` |
| `agents/core/ingestion/normalizer.py` | Message normalization | `NormalizedMessage` |
| `agents/core/ingestion/parser_facebook.py` | Facebook JSON parser | `FacebookParser` |
| `agents/core/ingestion/parser_whatsapp.py` | WhatsApp TXT parser | `WhatsAppParser` |
| `agents/core/ingestion/stylometry.py` | Stylometric voice profiling | `StylometryAnalyzer` |
| `agents/core/ingestion/knowledge.py` | Entity/relation extraction | `KnowledgeExtractor` |
| `agents/core/ingestion/watcher.py` | Continuous ingestion daemon | `IngestionWatcher.check_and_run` |

### Persistence / Infra

| Path | Purpose | Key symbols |
|------|---------|-------------|
| `agents/core/checkpoint.py` | SQLite checkpoints + session records | `CheckpointManager.save/restore/initialize` |
| `agents/core/settings_db.py` | SQLite runtime settings | `get_all`, `get_category`, `put_category`, `init_db`, `DEFAULTS` |
| `agents/core/bench.py` | Latency/throughput benchmarks | `LatencyBenchmark.record`, `get_summary` |
| `agents/core/sandbox.py` | Docker + subprocess code execution | `Sandbox.execute_python`, `execute_shell` |
| `agents/core/plugin_gate.py` | Per-agent plugin permission | `PermissionGate.check_call` |
| `agents/core/learning/loop.py` | Agent health + promotion loop | `LearningLoop.record`, `rank_candidates`, `suggest_promotions`, `is_unhealthy` |
| `agents/core/mcp/client.py` | MCP client (stdio/SSE) | `MCPManager`, `MCPServer.connect`, `MCPTool` |
| `agents/core/workflows/` | Multi-agent workflow engine | `WorkflowEngine` (engine.py), `WorkflowRegistry` (registry.py), `Pipeline`, `WorkflowStep` (pipeline.py), storage (storage.py) |
| `agents/core/observability/tracer.py` | Request tracing | `Tracer`, trace context |
| `agents/core/observability/eval.py` | LLM evaluation harness | `EvalRunner` |
| `agents/core/observability/quality.py` | Live quality monitor (per-request score + alert) | `QualityMonitor` |
| `agents/core/observability/review_queue.py` | Human review queue (flag → rubric → eval dataset) | `ReviewQueue` |
| `agents/core/observability/datasets.py` | Eval dataset store + regression runs | `DatasetStore` |
| `agents/core/observability/north_star.py` | North-star + counter-metric aggregator (MOONSHOT §6) — exposed at `GET /api/metrics/north-star?days=1-90`; see [METRICS.md](METRICS.md) | `compute_north_star` |

### Agent Registry

| File | Purpose |
|------|---------|
| `agents/_system/agents.yaml` | Canonical agent registry: id, name, tier, status, heartbeat, plugins, llm_policy |

---

## 4. Memory & Recall Subsystem

### Components

```
ConversationMemory  — session-scoped turns in RAM + disk (JSONL)
InMemoryVectorStore — 768-dim numpy cosine similarity (or QdrantVectorStore if VECTOR_BACKEND=qdrant)
InMemoryGraph       — entity/relation store (or Neo4jGraph if NEO4J_URL set)
Embedder            — LMStudio /v1/embeddings (default, recommended: mxbai-embed-large) or Ollama; hash fallback if unreachable
```

### Data flow

```
add_turn(text)
  ├─ ConversationMemory.add_turn           [in-memory + disk persist]
  └─ if MEMORY_EMBED_TURNS: remember(text) → embed(text) → vectors.add(rid, vec, meta)

recall(query_text, top_k)
  ├─ embed(query_text)          → asyncio.to_thread(embedder.embed, text)
  └─ hybrid_search(vec, keyword) → HybridRetriever.retrieve
       ├─ vectors.search(vec, k) → [(id, payload), ...]
       ├─ graph.search(keyword)  → [(name, entity), ...]
       └─ reciprocal_rank_fusion({vector: ..., graph: ...}) → [FusedHit, ...]
```

### Embedding cache layers (H7.4)

1. **In-process LRU** (`_PROC_CACHE`, max 256 entries, key = `(backend, model, text)`)
2. **Disk cache** (`EmbeddingCache`, SHA-256 content-addressed, sharded by first 2 hex chars, atomic rename writes)
3. **Backend** (LMStudio or Ollama, retried with exponential backoff, degrades to deterministic hash)

### Key settings

| Setting key | Default | Effect |
|-------------|---------|--------|
| `MEMORY_EMBED_TURNS` env | `false` | Auto-embed every turn into vector store |
| `EMBED_BACKEND` env | `lmstudio` | `lmstudio` or `ollama` |
| `EMBED_MODEL` env | `mxbai-embed-large` | Embedding model (H8.4: recommended quality model for LM Studio) |
| `VECTOR_BACKEND` env | `memory` | `memory` or `qdrant` |
| `memory.recall_enabled` | `false` | Inject recalled memories into every prompt |
| `memory.recall_top_k` | `5` | Number of recall hits to inject |
| `memory.context_window` | `6` | Conversation turns in prompt |
| `memory.checkpoint_every` | `5` | Turns between checkpoint saves |
| `memory.cross_channel_sessions` | `false` | Share session across channels |

### API endpoints

- `GET /api/memory/search?q=<text>` — run fused recall
- `POST /api/memory/remember` body `{"text": "..."}` — store a fact

---

## 5. LLM Routing & Model Tiering

### Policy per agent (`hybrid_router.py:get_agent_policy`)

Resolution order: **(1)** `LOCAL_ONLY_AGENTS` security floor (code-enforced — the registry can
never pull a strict-local agent to the cloud) → **(2)** `llm_policy` from the canonical registry
`agents/_system/agents.yaml` → **(3)** in-code fallback sets → **(4)** `auto`.

| Policy | Agents |
|--------|--------|
| `local` | `frigga`, `ultron`, `howard` — never leave the machine; **fail closed** if local backend is down (no cloud fallback, ever) |
| `claude` | `vision`, `steve`, `argus` (argus via registry) — Claude Sonnet via Anthropic API |
| `cloud` | `athena` — Gemini flash via Gemini API |
| `auto` | All others — local first, escalate on size/complexity |

### Backend selection (`HybridRouter.select_backend`)

```
howard  → Ollama (howard-lora-qwen-14b) or LMStudio fallback
DEEP_THINK_AGENTS (frigga, hephaestus, hercules) → LMStudio slot 2, DEFAULT_DEEP_MODEL (DDR5)
CLAUDE_AGENTS → ClaudeBackend (DEFAULT_CLAUDE_MODEL)
CLOUD_ONLY → GeminiBackend (gemini-2.5-flash)
AUTO (≤ LOCAL_MAX_TOKENS=8000): local slot 1
  if is_heavy_request(prompt) AND JARVIS_AUTO_DEEP: → local slot 2 (H7.5 escalation)
AUTO (≤ FLASH_MAX_TOKENS=128000): gemini-2.5-flash
AUTO (> FLASH_MAX_TOKENS): gemini-2.5-pro
```

### `is_heavy_request(prompt)` — complexity escalation (H7.5)

Returns `True` if:
- `estimate_tokens(prompt) > 2000`, OR
- prompt contains any keyword from `HEAVY_KEYWORDS` (bilingual RO/EN subset: `analiz`, `strategi`, `reasoning`, `synthes`, etc.)

### Key env vars

| Var | Default | Effect |
|-----|---------|--------|
| `JARVIS_AUTO_DEEP` | `1` | `0` disables complexity escalation |
| `JARVIS_DEEP_MODEL` | `deepseek-r1-distill-qwen-32b` | Overrides deep-slot model |
| `ANTHROPIC_API_KEY` | — | Enables Claude tiering |
| `GEMINI_API_KEY` | — | Enables cloud (Gemini) fallback |

### LM Studio lifecycle control + kill-switch

Jarvis connects to a *running* LM Studio and auto-detects the loaded model. It can
also **start the server and load/unload models** via the `lms` CLI — from the admin
UI and from chat. This is mutating control of the host, so it is gated.

**Entry points**
- **Chat (natural language):** `detect_llm_control(text)` → `_run_llm_control(action, model)`
  in the request lifecycle (step 2b). Handles `start` / `load` / `unload` / `status`
  in EN+RO, plus the explicit `llm <sub>` form. Deliberately conservative — a load/
  unload needs a *plausible* model token (a digit, a `path/`, or a known family like
  gemma/qwen/deepseek), so ordinary chatter never triggers a model load. The reply
  narrates what **actually** happened (it reads the controller result, no theatre).
- **Admin API:** `POST /api/llm/server/start | /api/llm/load | /api/llm/unload`
  (`agents/web.py`, behind `_admin_guard`). HUD badge + admin buttons call these.
- **Controller:** `LMStudioController` (`llm/lmstudio_control.py`) — argv-only (no shell),
  fixed verb set, model-id regex, per-action timeout + port recovery probe. Refreshes
  the live router after a model change so routing + the runtime-state block report the
  real model with no restart.

**Kill-switch (how to disable / "undo" without a revert)** — layered, any one signal wins:

| Lever | Scope | Effect |
|-------|-------|--------|
| env `JARVIS_LMSTUDIO_CONTROL=0` | master (chat + admin + HUD) | boot-time hard off; all mutating ops return `status:"disabled"` (read/status still works) |
| setting `llm.control_enabled=false` | master | same, **live** — propagates in ≤30s via the settings watcher, no restart |
| env `JARVIS_LMSTUDIO_CHAT_CONTROL=0` | chat only | mutes ambient NL detection; admin buttons stay live |
| setting `llm.chat_control=false` | chat only | same, live |

Resolution: `_control_master_enabled()` = env AND `llm.control_enabled`; `_chat_control_enabled()`
= master AND chat env AND `llm.chat_control`. `load_runtime_settings()` pushes the master
result into `LMStudioController.set_enabled()` on every 30s reload. Ultimate undo: revert the
squash commit.

**Troubleshooting**
- *Chat says "LM Studio control is disabled"* → a kill-switch is off; check the env vars
  and the `llm.control_enabled` / `llm.chat_control` settings.
- *`status:"failed"`, reason mentions `lms`* → the `lms` CLI isn't on PATH or LM Studio
  isn't installed where the server runs. The controller never starts LM Studio the app,
  only its server via `lms server start`.
- *`status:"rejected"`* → model id failed the `_MODEL_RE` regex (only letters/digits/`._-/:@`).
- *"load gemma" loads the wrong/no model* → the controller now resolves a partial name to the
  full servable id via `/v1/models` before `lms load` (`LMStudioController._resolve_model`). A
  unique match loads (the reply names the resolved id); several matches return
  `status:"ambiguous"` with the candidates so you can pick; if `/v1/models` is unreachable it
  falls back to passing the literal name straight to `lms load`.
- *Jarvis still names the old model after a load* → router refresh failed; check
  `refresh_active_model` on the router and the LM Studio `/v1/models` response.
- *A chat message unexpectedly triggered control* → tighten `detect_llm_control`; the
  negative-case guards live in `tests/test_llm_control_intent.py`.

---

## 6. Configuration & Settings

### Two-layer config

1. **Startup YAML** — `agents/_system/agents.yaml` → parsed by `agents/core/config.py:JarvisConfig`. Agent registry + static settings. Read-only at runtime.
2. **Runtime SQLite** — `memory_logs/settings.db` → `agents/core/settings_db.py`. Editable via `/api/admin/settings`. Loaded every 30s by `_settings_watcher_loop`. Read via `Orchestrator.get_setting(key, default)`.

### Most-used runtime setting keys

| Key | Default | Description |
|-----|---------|-------------|
| `general.timezone` | `Europe/Bucharest` | |
| `general.wake_words` | `["jarvis","hub"]` | |
| `llm.temperature` | `0.7` | |
| `llm.max_tokens` | `2048` | Deep route uses `llm.deep_max_tokens` (`8192`) |
| `llm.default_model` | `google/gemma-4-31b-a4b` | |
| `llm.cloud_fallback` | `on-demand` | `never`/`on-demand`/`always` — governs cloud *escalation* for auto-policy agents (never = stay local even oversized; honored live, ≤30s). Explicit cloud policies (athena) are unaffected |
| `llm.control_enabled` | `true` | Master kill-switch for LM Studio start/load/unload (chat + admin) |
| `llm.chat_control` | `true` | Allow natural-language LLM control in chat (admin buttons unaffected) |
| `memory.context_window` | `6` | Turns in each prompt |
| `memory.checkpoint_every` | `5` | Checkpoint debounce |
| `memory.recall_enabled` | `false` | RAG injection |
| `memory.recall_top_k` | `5` | |
| `security.guardrails_mode` | `WARN` | `WARN`/`REDACT`/`BLOCK` |
| `system.autonomy_tick` | `60` | Autonomy loop interval (s) |
| `system.observer_enabled` | `true` | Host resource probes |
| `system.watchers_enabled` | `true` | Personal event probes |
| `autonomy.night_shift` | `false` | Restrict to reversible tasks overnight |
| `autonomy.interrupt_budget` | `4` | Urgent Telegram pushes/day; mirrored into the shared K3 `BudgetLedger` when present |
| `learning.auto_promote` | `false` | Auto-promote bench agents |
| `plugins.<name>` | `true` | Toggle any plugin |

### .env variables (not in settings_db)

Key env vars loaded at startup:
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`, `GMAIL_ACCESS_TOKEN`, `SPOTIFY_CLIENT_ID/SECRET/ACCESS_TOKEN/REFRESH_TOKEN`, `GOOGLE_CALENDAR_TOKEN`, `WHATSAPP_BRIDGE_URL`, `APPLE_HEALTH_BRIDGE_URL`, `HOMEBRIDGE_URL/TOKEN`, `TAVILY_API_KEY`, `SEARXNG_URL`, `SMTP_HOST/PORT/USER/PASS`, `IMAP_HOST/PORT/USER/PASS`, `SLACK_BOT_TOKEN`, `N8N_BASE_URL/API_KEY`, `GITHUB_TOKEN`, `JARVIS_ADMIN_TOKEN`, `DEV_MODE`, `JARVIS_AUTO_DEEP`, `JARVIS_DEEP_MODEL`, `JARVIS_LMSTUDIO_CONTROL`, `JARVIS_LMSTUDIO_CHAT_CONTROL` (LM Studio control kill-switches — see §5).

---

## 7. Conventions

### Testing

- **Framework:** pytest with `asyncio_mode = auto` (see `pytest.ini`) — all `async def test_*` run without decorators.
- **Test count:** ~3,845 passing tests, 6 skipped (offline suite; counter synced via `scripts/status_sync.py`). *(WorldView, the separate `worldview/` Node stack, has its own CI + test suites — see `worldview/`.)*
- **sys.path pattern:** Every test file inserts `repo_root` and `repo_root/agents` at the top. Always use this, not relative imports.
- **Offline by default:** Tests inject fake backends (e.g. `FakeBackend(LLMBackend)`, `FakeLMStudioClient`). No real network/LLM required.
- **Orchestrator instantiation trick:** Avoid `Orchestrator(config)` in ordinary unit tests (heavy init). Use `Orchestrator.__new__(Orchestrator)` + manual attribute assignment, or mock the heavy dependencies. The capability readiness matrix is the deliberate exception: it boots a cached real orchestrator because it is testing registry truth, not a unit seam.
- **Where new tests go:** `tests/test_<module_name>.py`. Use `conftest.py:make_app` for lightweight FastAPI apps with fallback routes.
- **Run tests:** `pytest -q` from repo root.

### Branch / PR workflow

- Work on feature branches. PRs merge to main.
- Do not push directly — see `AGENTS.md` for full conventions.

### Local-first rules

- `frigga`, `ultron`, `howard` are `LOCAL_ONLY_AGENTS` in `hybrid_router.py` — never routed to cloud.
- `frigga` has `cloud_fallback: false` in `agents.yaml` — hard rule.

### Skill/plugin loader patterns

- Skills are auto-discovered on startup via `SkillLoader.discover()` scanning `skills/*/SKILL.md`.
- Plugins are instantiated in `Orchestrator.load_agents()` by name and stored in `self.plugins` dict.
- Plugin access in skills: lazy import at call time (see `skills/brief/main.py` pattern).
- Channels are registered via `orch.register_channel(adapter)` + started by `orch.start_channels()`.

---

## 8. How-to Recipes

### Personalize an agent (SOUL.local.md overlay)

The repo ships **generic template souls**. Personal specifics never go into `SOUL.md` /
`HEARTBEAT.md` (they're public); they go into `agents/<id>/SOUL.local.md` /
`HEARTBEAT.local.md` — **gitignored** files that fully override the template at load time
(`Agent._load_soul`, `HeartbeatScheduler.load_all`, `GET /api/agents/{id}/soul`). Copy the
template, personalize, restart. One-time migration after the 2026-06-10 templating change:
`python scripts/restore_personal_souls.py` (restores the pre-templating personalized souls
from git history into `*.local.md`).

### Add a new agent (active)

1. Create `agents/<agent_id>/SOUL.md` — see any existing soul for format (Identity / Mission / Voice sections). Keep it generic; personal details go in `SOUL.local.md` (above).
2. Add entry under `agents:` in `agents/_system/agents.yaml`:
   ```yaml
   myagent:
     name: MyAgent
     archetype: "What it does"
     status: active
     tier: business          # command / business / tech / foundation
     channel: telegram        # voice / web-dashboard / telegram / log-only / local-only
     heartbeat: "4h"          # interval or "no"
     plugins: [gmail]
   ```
3. Add router triggers in `agents/core/router.py:INTENT_RULES` if you want keyword routing.
4. No code changes needed — `Agent._load_soul()` picks it up on next boot.

### Add a bench agent

1. Add under `bench:` in `agents.yaml` with `trigger` and optional `triggers_on`/`threshold`.
2. Activate at runtime via `POST /learning/promote` (admin) or set `learning.auto_promote=true`.
3. `Orchestrator.promote_bench_agent` writes a stub `SOUL.md` automatically if missing.

### Add a skill

1. `mkdir skills/<name>` + create `SKILL.md`:
   ```markdown
   # SkillName
   **Version:** 0.1.0
   **Author:** you
   **Agents:** jarvis  ← comma-sep agent IDs
   ## Commands
   - `myskill <args>` — description
   ```
2. Create `skills/<name>/main.py` with either:
   - `async def handle(command, args, context) -> str` (catch-all), OR
   - `get_commands() -> list[str]` + one `async def <cmd>(args, context) -> str` per command.
3. Call `orch.skills.discover()` or restart; no registration needed.

### Add a plugin

1. Create `agents/core/plugins/<myplugin>.py` with a class `MyPlugin`.
2. Add instantiation in `Orchestrator.load_agents()` (`orchestrator.py` ~line 169+):
   ```python
   self.plugins["myplugin"] = MyPlugin(key=os.environ.get("MYPLUGIN_KEY", ""))
   ```
3. Add trigger logic in `Orchestrator._gather_plugin_data` (keyword detection → `await plugin.handle(...)`).
4. Optionally add a toggle in `settings_db.py:DEFAULTS` under `plugins`.

### Add a web endpoint

> **Convention (anti-god-object, CLN-3 — done #296):** new routes go in a **per-domain router**
> `agents/core/routers/<domain>.py`, *not* inline in `web.py` (which now keeps only 9 app-shell/chat/admin routes; the other 383 live in 63 routers).
> Mirror an existing router (e.g. `capture.py`): an `APIRouter`, guards imported from
> `routers/_deps.py`, shared state reached lazily via `from agents import web`; mount it in
> `web.py` with `app.include_router(...)`. Don't add new `@app.*` decorators inline. The
> route-parity guard (`tests/test_route_parity_guard.py`, snapshots `app.routes`) will flag any
> surface change — re-seed it in the same PR with `python tests/test_route_parity_guard.py --update`.
> Full plan: `docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md`.

1. Create/open `agents/core/routers/<domain>.py` (a fresh `@app.*` in `web.py` only for a true one-off).
2. Add your route function, e.g.:
   ```python
   @app.get("/api/myroute")
   async def my_route():
       if not orch:
           return JSONResponse({"error": "not initialized"}, status_code=503)
       return _nocache_json({"result": ...})
   ```
3. If admin-only, add `dependencies=[Depends(_admin_guard)]`. If it exposes the
   assistant, personal data (memory/notes), or runs code, add
   `dependencies=[Depends(_user_guard)]` instead (HF-1 — localhost by default,
   `X-User-Token` / `JARVIS_USER_TOKEN` to expose on a network).
4. Polling endpoints that return live data: add path to `_NO_STORE_PATHS` dict.

### Add a runtime setting

1. Open `agents/core/settings_db.py`.
2. Add a `dict(...)` entry to `DEFAULTS` list with `category`, `key`, `value`, `label`, `kind`.
3. Read it anywhere via `orch.get_setting("category.key", default)` (reloaded every 30s).
4. For per-plugin credentials, use category `"plugins"`.

### Evolve a store's schema (migrations, H23.7)

SQLite stores version their schema with `PRAGMA user_version` via
`agents/core/persistence/migrations.py`. To change a store's schema:

1. Keep the store's `CREATE TABLE IF NOT EXISTS` reflecting the **full current**
   schema (fresh DBs get it directly).
2. Add a module-level `_MIGRATIONS` list and, after the create-schema block in
   `initialize()`/`_init_db()`, call
   `apply_migrations(conn, _MIGRATIONS, name="<store>")`.
3. For each schema change, **append** one migration callable (index `i` upgrades
   `vi → v(i+1)`). Use `column_adder(table, col, decl)` for a guarded `ADD COLUMN`,
   or write a callable taking the `conn`. **Never edit or reorder a shipped
   migration** — only append. Each migration + its version bump apply atomically;
   a failure rolls back and leaves the DB at the last good version.

Reference adopters: `agents/core/security/audit.py`, `agents/core/skills/marketplace.py`.

### Add a channel

1. Create `agents/core/channels/<name>.py` subclassing `ChannelAdapter`.
2. Implement `start()`, `stop()`, `send(message, **kwargs)`.
3. In `agents/web.py:lifespan`, instantiate and `await orch.register_channel(my_channel)`.
4. Call `orch.start_channels()` already handles starting all registered channels.

---

## 9. Filesystem Map

```
serve.py                          Uvicorn launcher
agents/
  run.py                          CLI REPL
  web.py                          FastAPI app shell + lifespan (9 inline routes; mounts 63 routers → full route surface, live count in STATUS.md; uvicorn on port 8080)
  web/                            Static assets for web dashboard (HTML/CSS/JS)
  _system/agents.yaml             Agent registry (canonical source of truth)
  core/
    routers/                      65 per-domain APIRouters = the HTTP surface (CLN-3 + domain slices); _deps.py = lazy auth guards
    orchestrator.py               Main loop (+ CLN-2 managers: channel/plugin, llm_control, cognition_trace)
    agent.py                      Single agent runtime (SOUL.md loader)
    router.py                     Intent classifier
    config.py                     JarvisConfig (YAML loader)
    settings_db.py                Runtime settings (SQLite WAL)
    checkpoint.py                 Checkpoint manager (SQLite WAL)
    plugin_gate.py                Plugin permission gate
    bench.py                      Latency benchmarks
    sandbox.py                    Docker/subprocess execution
    heartbeat.py                  Agent heartbeat scheduler
    resilience.py                 Circuit breakers
    errors.py                     Typed error codes
    llm/                          LLM backends + routing
    memory/                       Conversation + vector + graph + fusion
    ingestion/                    Howard pipeline (embedder, parsers, watcher)
    autonomy/                     Self-tasking queue + worker + policy
    security/                     Guardrails + scanner + audit
    channels/                     Web/Voice/Telegram/Discord/Email/Slack
    plugins/                      All third-party integrations
    skills/                       Skill loader + importer + marketplace
    voice/                        Wake word + STT + TTS pipeline
    mcp/                          MCP client (stdio/SSE)
    learning/                     Agent health tracking + promotions
    workflows/                    Multi-agent workflow engine
    observability/                Request tracing + LLM eval harness
  jarvis/SOUL.md                  Agent identity prompt (repeat for each agent)
skills/                           Skill packs (SKILL.md + main.py)
memory_logs/                      All persistent state (SQLite, JSONL, cache)
  checkpoints/checkpoints.db
  settings.db
  security/audit.db
  autonomy.db
  embedding_cache/recall/
  learning/
tests/                            pytest suite (asyncio_mode=auto, offline)
docs/
  ARCHITECTURE.md                 ← this file
  JARVIS.md                       → high-level architecture overview
  AGENTS.md                       → assistant conventions + workflow
  BACKLOG.md                      → priorities + open tasks
  research/                       Research notes
  superpowers/                    Feature specs (Horizons 5–7)
```

---

## 10. Doc Map

| File | What it covers |
|------|---------------|
| `JARVIS.md` | High-level architecture, agent tiers, stack, LLM setup, quick commands |
| `AGENTS.md` | Assistant workflow conventions, rules, task protocol |
| `BACKLOG.md` | Prioritized task list — read/update when discussing "what's next" |
| `docs/research/` | Deep research notes on design decisions |
| `docs/superpowers/` | Feature specs for Horizons 5, 6, 7 (memory, autonomy, performance) |
| `docs/ARCHITECTURE.md` | Module index, request lifecycle, recipes (this file) |
| `docs/VOICE.md` | Voice subsystem — browser HUD loop + server pipeline, endpoints, what's real vs scaffolded |
| `docs/COGNITION.md` | Cognition subsystem (planned ORIZONT 21) — living memory + personality **schematic & diagnostic map** (brain analogies, tiers, troubleshooting playbook) |
| `worldview/README.md` | **WorldView (4D OSINT)** — separate Next.js + Fastify stack (ports 3000/4000), not sharing the Python runtime. Bridged into JARVIS by the **Argus** agent (`agents/argus/`, geoint router intent → read-only governed plugin). Launched by `START.bat`/`start.sh`. |
| `docs/contracts/worldview-bridge.md` | **The hub↔WorldView integration contract** (v1) — the only coupling between the two stacks: 6 read-only GET endpoints, enforced by contract tests on both sides (`tests/test_worldview_bridge_contract.py` · `worldview/backend-api/test/bridgeContract.test.ts`) |
| `docs/2026-06-08-future-developments-report.md` | Forward roadmap — remaining v1.0 gate, WorldView follow-ups (#169/#170), audit-debt hardening, post-1.0 horizons (O20 Hermes, O21 Cognition), recommended sequencing |
