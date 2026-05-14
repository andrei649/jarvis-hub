# Jarvis Hub v0.2.0 — STATUS

## ✅ Solid (gata de testat)
- 15 SOUL.md complete — toți agenții au identitate, misiune, voce, reguli
- 11 HEARTBEAT.md — pentru agenții cu heartbeat activ
- 2 template-uri reutilizabile (SOUL.template.md + HEARTBEAT.template.md)
- agents.yaml registry
- Core orchestrator Python (orchestrator.py, router.py, agent_loader.py)
- Plugin system (plugin_manager.py, permission_gate.py) — 7 plugin-uri descoperibile
- Memory manager cu relevanță semantică (keyword overlap + diacritice normalizate)
- Heartbeat scheduler (heartbeat_scheduler.py)
- Channel manager (channel_manager.py)
- Voice layer — wake word (openwakeword built-in + custom ONNX), STT (faster-whisper configurable), TTS (Kokoro cu voice map), captură microfon reală (sounddevice), pipeline wake→record→transcribe
- Web UI (web/server.py + templates/index.html) — template separat
- main.py entry point cu CLI mode (`--cli`)
- install.sh (executable, include .env bootstrap)

## 🔨 î îmbunătățiri aduse în v0.2.0

### Core
- `orchestrator.py`: Conexiune HTTP reutilizabilă (httpx.AsyncClient pool), retry cu backoff, `AgentResponse` unificat, configurable (cns_agent_id, timeout, max_retries)
- `router.py`: Normalizare diacritice, anti-patterns, scoring normalizat, cuvinte românești flexionate acceptate
- `agent_loader.py`: Validare frontmatter cu Pydantic, cache system prompt, invalidate_cache()
- `memory_manager.py`: Keyword overlap scoring cu prefix matching, normalizare diacritice, consolidate_nightly cu topic extraction, tokenizare RO/EN cu stopwords

### Voice
- `wake_word.py`: Suport model custom ONNX + built-in openwakeword, detectare multi-wake-word
- `stt.py`: Device/language configurabil, fallback cpu/int8
- `tts.py`: Voice map per limbă, lang_code configurabil
- `audio_manager.py`: Captură microfon reală (sounddevice InputStream), pipeline wake→record→transcribe, silence detection, timeout

### Plugin-uri (7)
- telegram_bot.py, gmail_bridge.py, calendar_bridge.py, slack_bridge.py, whatsapp_bridge.py, homebridge.py, spotify_control.py

### Web
- HTML extras în `web/templates/index.html` (separat de Python)

### Install
- `install.sh` executabil, copiază `.env.example` → `.env` dacă lipsește

## 📅 Roadmap
Săpt. 1: Foundation ✓ — Ollama + DeepSeek running, Web UI live, primii 3 agenți
Săpt. 2: Multi-agent ✓ — toți 15 agenții, heartbeats, routare
Săpt. 3: Voice ✓ — wake word, STT, TTS funcțional, captură microfon
Săpt. 4: Polish — plugin-uri (făcut), self-improvement, content build-in-public
