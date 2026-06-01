# Andrei's Cabinet — Documentație Exhaustivă

**Versiune:** 0.2.1  
**Data:** 30 Mai 2026  
**Autor:** Sistemul Jarvis

---

## Cuprins

1. [Prezentare Generală](#1-prezentare-generală)
2. [Arhitectura Sistemului](#2-arhitectura-sistemului)
3. [Agenții — Cei 15 Specialiști](#3-agenții---cei-15-specialiști)
4. [Stack Tehnologic](#4-stack-tehnologic)
5. [Componente Core](#5-componente-core)
6. [Plugin-uri și Integrări](#6-plugin-uri-și-integrări)
7. [Canale de Comunicație](#7-canale-de-comunicație)
8. [Sistemul de Skill-uri](#8-sistemul-de-skill-uri)
9. [Memorie și Învățare](#9-memorie-și-învățare)
10. [Securitate](#10-securitate)
11. [Web API și Endpoints](#11-web-api-și-endpoints)
12. [Hardware și Infrastructură](#12-hardware-și-infrastructură)
13. [Ghid de Utilizare](#13-ghid-de-utilizare)
14. [Ghid de Dezvoltare](#14-ghid-de-dezvoltare)
15. [Status și Roadmap](#15-status-și-roadmap)

---

## 1. Prezentare Generală

**Andrei's Cabinet** (nume de cod: **Jarvis**) este un sistem de orchestrare multi-agent AI conceput să gestioneze intersecția vieții personale și profesionale a utilizatorului. Sistemul constă din **15 agenți specializați** distribuiți în 4 tier-uri, coordonați de un orchestrator primar.

### Filozofia de Design

- **Local-first:** Rulează 100% local fără dependențe cloud implicite
- **Pure Python:** Fără Rust, fără containere Docker pentru funcționalitatea de bază
- **Plugin architecture:** Fiecare serviciu terț este un plugin explicit, auditabil, dezactivabil
- **Voice-first:** Control vocal prin wake-word detection
- **Multi-channel:** Interacțiune prin voce, web, Telegram, Discord, email, Slack

### Ce Rezolvă

Sistemul acoperă 4 domenii majore:
1. **Viața profesională** — Raiffeisen Bank, Digitaholic, strategie, KPIs
2. **Viața personală** — familie (Alexandra, Max), casă (Cosmina de Sus)
3. **Asset-uri fizice** — BMW E93, hardware (Bonobo WS, Pi 5)
4. **Bienestar** — fitness, somn, nutriție, recovery

---

## 2. Arhitectura Sistemului

### Diagrama Arhitecturală

```
┌─────────────────────────────────────────────────────────────────┐
│                    Andrei (Utilizator)                          │
│         Voice │ Web │ Telegram │ Discord │ Email │ Slack        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Gateway Channel Router                     │
│            (routează mesajele către orchestrator)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    JARVIS (Orchestrator)                        │
│  Intent Classification │ Routing │ Synthesis │ Memory Manager   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌───────────────┐
│  LLM Router   │   │  Plugin Gate    │   │  Skill Loader │
│ Local ↔ Cloud │   │  Permission     │   │  Import/Load  │
└───────────────┘   └─────────────────┘   └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Cei 15 Agenți Specializați                   │
│  ┌─────────┬─────────┬──────────┬──────────┬─────────────┐     │
│  │ COMMAND │ BUSINESS│   TECH   │ FOUNDATION│    BENCH    │     │
│  ├─────────┼─────────┼──────────┼──────────┼─────────────┤     │
│  │ Jarvis  │ Athena  │  Steve   │  Gecko   │  Howard     │     │
│  │ Friday  │ Stark   │  Oracle  │ Hercules │  Bruce      │     │
│  │ Pepper  │ Veronica│  Ultron  │Hephaestus│  Wanda      │     │
│  │ Jerome  │ Vision  │          │  Frigga  │  (12 more)  │     │
│  └─────────┴─────────┴──────────┴──────────┴─────────────┘     │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌───────────────┐
│   Memory      │   │   Security      │   │  Checkpoint   │
│ Conversation  │   │   Guardrails    │   │   Manager     │
│ Vector Store  │   │   Audit Log     │   │   (SQLite)    │
│ Knowledge     │   │   SSRF Protect  │   │               │
└───────────────┘   └─────────────────┘   └───────────────┘
```

### Fluxul unui Request

1. **Input** — Utilizatorul trimite un mesaj prin orice canal (voce, web, Telegram, etc.)
2. **Channel Handler** — Mesajul este recepționat de canalul corespunzător
3. **Gateway** — Routează către orchestrator, gestionând sesiuni per channel/chat_id
4. **Orchestrator (Jarvis)**:
   - Adaugă mesajul în memoria conversației
   - Parsează comenzi skill (`/skill_name command`)
   - Clasifică intenția și determină agenții țintă
   - Colectează date de la plugin-uri relevante (vreme, știri, calendar)
   - Cheamă agenții în paralel sau secvențial
   - Detectează handoff-uri către alți agenți
   - Sintetizează răspunsurile într-un singur răspuns coerent
5. **LLM Router** — Alege backend-ul optim (local LM Studio/Ollama sau cloud Claude/Gemini)
6. **Agent Processing** — Fiecare agent procesează cu SOUL.md-ul său
7. **Security Guardrails** — Scanează input/output pentru PII, secrete, injection
8. **Output** — Răspunsul este trimis prin canalul original
9. **Memory Write** — Conversația este salvată în JSONL + checkpoint SQLite
10. **Learning Loop** — Înregistrează interacțiunea pentru optimizare viitoare

---

## 3. Agenții — Cei 15 Specialiști

### Tier 1: COMMAND (Orchestrare & Operațiuni Zilnice)

#### **Jarvis** — Prime Orchestrator
- **ID:** `jarvis`
- **Arhetip:** Just A Rather Very Intelligent System
- **Rol:** Front-door al sistemului, orchestrează toți ceilalți agenți
- **Canal:** Voice (primary), Web Dashboard (fallback)
- **Heartbeat:** 12h
- **Plugin-uri:** cloud-llm, telegram
- **SOUL:** British butler, dry wit, "sir"/"Andrei", direct fără preambule
- **Responsabilități:**
  - Recepționează toate input-urile
  - Clasificare intenție și routing
  - Orchestrare multi-agent (paralel/secvențial)
  - Sinteză răspunsuri într-o singură voce
  - Fallback pentru query-uri generale
  - Morning brief la wake (Friday + Pepper + Frigga)
- **Nu face:** research profund, content writing, analiză financiară, execuție cod

#### **Friday** — Daily Intel
- **ID:** `friday`
- **Arhetip:** Daily Intel Officer
- **Rol:** Colectează vreme, știri, semnale de piață
- **Canal:** Voice
- **Heartbeat:** 6h
- **Plugin-uri:** telegram
- **Responsabilități:**
  - Morning brief zilnic
  - Vremea (localizare + forecast)
  - Știri (BBC RSS, NewsAPI)
  - Market signal (Polygon.io, Yahoo Finance)
- **Status:** ✅ Complet (H2.3)

#### **Pepper** — Chief of Staff
- **ID:** `pepper`
- **Arhetip:** Chief of Staff / Emotional Weighting
- **Rol:** Calendar, meetings, email triage, reflection
- **Canal:** Voice
- **Heartbeat:** 2h
- **Plugin-uri:** google-calendar, gmail, telegram
- **Responsabilități:**
  - Gestionare calendar Google (citește, creează, modifică evenimente)
  - Email triage Gmail (prioritizează inbox)
  - Reflection săptămânală
  - Coordonează overflow către Happy (bench)
- **Status:** ✅ Calendar (H2.1), 🔜 Email Triage (H2.2)

#### **Jerome** — Leisure & Soundtrack
- **ID:** `jerome`
- **Arhetip:** Leisure Commissioner
- **Rol:** Muzică, retro tech, decompression
- **Canal:** Voice
- **Heartbeat:** no (doar la cerere)
- **Plugin-uri:** spotify
- **Responsabilități:**
  - Control Spotify (play/pause/skip/queue)
  - Playlist suggestions (focus, relaxare, workout)
  - Overflow către Apollo (bench) la >20 requests/săptămână
- **Status:** ✅ Complet (H2.5)

---

### Tier 2: BUSINESS (Strategie & Inteligență)

#### **Athena** — External Strategist
- **ID:** `athena`
- **Arhetip:** External Strategist
- **Rol:** Digitaholic, personal brand, CMO trajectory
- **Canal:** Web Dashboard
- **Heartbeat:** 6h
- **LLM Policy:** cloud (Claude API)
- **Plugin-uri:** cloud-llm
- **Responsabilități:**
  - Strategie Digitaholic
  - Personal brand positioning
  - Traiectorie CMO
  - Counter-position requests către Loki (bench)

#### **Stark** — Internal Corporate Intel
- **ID:** `stark`
- **Arhetip:** Internal Biz Intel
- **Rol:** Raiffeisen KPIs, board prep, channels
- **Canal:** Telegram
- **Heartbeat:** 4h
- **Plugin-uri:** gmail
- **Responsabilități:**
  - KPIs Raiffeisen Bank
  - Board preparation
  - GA4 + Firebase analytics (🔴 H2.11 — dep. API access)
  - Campanii performance

#### **Veronica** — The Voice
- **ID:** `veronica`
- **Arhetip:** Content & Comms
- **Rol:** Drafturi emails, posts, captions în 5 voice profiles
- **Canal:** Telegram
- **Heartbeat:** no
- **LLM Policy:** cloud
- **Plugin-uri:** cloud-llm
- **Responsabilități:**
  - LinkedIn posts
  - Digitaholic blog drafts
  - Email drafting
  - 5 voice profiles (formal, casual, technical, personal, brand)
- **Status:** ✅ Complet (H2.10)

#### **Vision** — Deep Researcher
- **ID:** `vision`
- **Arhetip:** Deep Researcher + OSINT
- **Rol:** Cited synthesis, regulatory watch
- **Canal:** Web Dashboard
- **Heartbeat:** 6h
- **LLM Policy:** claude (Claude API only)
- **Plugin-uri:** cloud-llm, websearch
- **Responsabilități:**
  - Web research cu citări
  - OSINT (Open Source Intelligence)
  - Regulatory watch (GDPR, ATT, banking)
  - Market research CEE MarTech
- **Status:** 🔜 (H2.9)

---

### Tier 3: TECH (Infrastructură & Securitate)

#### **Steve** — CTO + Infrastructure
- **ID:** `steve`
- **Arhetip:** CTO + Builds
- **Rol:** Bonobo + Pi + models + backups
- **Canal:** Telegram
- **Heartbeat:** 1h → 2h (S0.2)
- **LLM Policy:** claude
- **Plugin-uri:** []
- **Responsabilități:**
  - System monitoring (CPU/GPU/RAM/disk/temp)
  - Bonobo WS + Pi 5 health
  - Model management (LM Studio, Ollama)
  - Backup orchestration
  - Sandbox code execution (Docker)
- **Status:** Parțial (H4.5)

#### **Oracle** — Pipeline Weaver
- **ID:** `oracle`
- **Arhetip:** N8N Workflows
- **Rol:** n8n workflows, silent when working
- **Canal:** Web Dashboard
- **Heartbeat:** no
- **Plugin-uri:** []
- **Responsabilități:**
  - n8n workflow creation/monitoring
  - Pipeline orchestration
  - GitHub integration (OracleBridgePlugin)
- **Status:** Parțial (H4.6)

#### **Ultron** — The Shield
- **ID:** `ultron`
- **Arhetip:** Security & Automation
- **Rol:** Firewall, GDPR/ATT, smart home VLAN
- **Canal:** Log-only
- **Heartbeat:** 2h → 2x/zi (S0.2)
- **Plugin-uri:** []
- **Responsabilități:**
  - Security monitoring
  - Firewall logs (Pi-hole)
  - CVE tracking
  - Traffic anomalies
  - Audit trails (Merkle chain)
  - Smart home VLAN security
- **Status:** Parțial (H4.4)

---

### Tier 4: FOUNDATION (Capital, Fitness, Familie, Asset-uri)

#### **Gecko** — Capital Allocator
- **ID:** `gecko`
- **Arhetip:** Markets & Capital
- **Rol:** ING + Libra balances, burn rate, runway
- **Canal:** Telegram
- **Heartbeat:** 2h
- **Plugin-uri:** []
- **Responsabilități:**
  - Solduri conturi (ING, Libra)
  - Burn rate calculation
  - Runway analysis
  - "Numbers cold; no advice"
- **Status:** 🔴 (H2.6 — dep. API bănci)

#### **Hercules** — Physical Engine
- **ID:** `hercules`
- **Arhetip:** Fitness & Nutrition
- **Rol:** Sleep, recovery, snowboard prep, Apple Health
- **Canal:** Telegram
- **Heartbeat:** 2h
- **Plugin-uri:** apple-health
- **Responsabilități:**
  - Sleep tracking (durată, calitate, HRV)
  - Heart rate monitoring
  - Steps/workouts
  - Pattern detection (7-day trends)
  - Nutrition (overflow către Demeter — bench)
- **Status:** ✅ Complet (H2.4)

#### **Hephaestus** — Builder & Mechanic
- **ID:** `hephaestus`
- **Arhetip:** Builder & Mechanic
- **Rol:** BMW E93 N54 + Cosmina build
- **Canal:** Telegram
- **Heartbeat:** 2h
- **Plugin-uri:** []
- **Responsabilități:**
  - BMW E93 335i N54 (piese, service, diagnostice)
  - Cosmina de Sus build (faze, termene, milestone-uri, blocker-e)
  - Project tracking în SQLite
- **Status:** ✅ Complet (H2.7)

#### **Frigga** — The Matriarch
- **ID:** `frigga`
- **Arhetip:** Family Matriarch
- **Rol:** Max + Alexandra + Beads & Blush + pisici
- **Canal:** Local-only (hard rule)
- **Heartbeat:** 4h
- **LLM Policy:** local (hard rule — zero network)
- **Plugin-uri:** whatsapp-bridge
- **Responsabilități:**
  - Max tracking (somn, HRV, mâncare, vaccinuri)
  - Alexandra (Beads & Blush parental leave)
  - Pisici: Kiwi (♀ 2018), Pepper (♂ 2019, 7.2kg)
  - SQLite local storage (zero external network)
  - Overflow către Hera (bench) la >50% capacity
- **Status:** ✅ Complet (H2.8)

#### **Howard** — Digital Twin (BENCH → Activat 2026-05-30)
- **ID:** `howard`
- **Arhetip:** Archive / Digital Twin
- **Rol:** 15 ani de date personale ingest-ate
- **Canal:** Telegram
- **Heartbeat:** no
- **LLM Policy:** local
- **Status:** ✅ Activat (trigger îndeplinit)

---

### Bench Agents (12 rezervați)

| Nume | Arhetip | Trigger Activare |
|------|---------|------------------|
| Bruce | Data Science | >20 query-uri/săptămână data analysis |
| Wanda | R&D Experimental | New prompt engineering pattern |
| Shuri | Hardware Integrations | iPod remote / Polaroid printer built |
| Natasha | Security Audit | >14 contracte/lună |
| Thor | Escalation | Pepper flags big-call decision |
| Loki | Devil's Advocate | Athena requests counter-position |
| Heimdall | All-Seeing Monitor | Cross-channel anomaly detection |
| Happy | Driver/Logistics | Pepper overflow |
| Bucky | Operations | Steve needs backup |
| Apollo | Music (Jerome overflow) | Jerome >20 music requests/săptămână |
| Hermes | Cross-Channel Router | >5 conflicte/săptămână |
| Atlas | Batch Processing | Nightly heavy jobs |
| Prometheus | Innovation Tracker | AI/MarTech landscape monitoring |
| Artemis | Lead Generation | Digitaholic client pipeline |
| Demeter | Nutrition | Hercules overflow meal tracking |
| Aria | Music Curation | Jerome split — music separate |
| Hera | Family (Frigga overflow) | Frigga >50% capacity |

**Reguli de promovare:**
- Minim 20 utilizări/lună
- Tone dedicat necesar
- Canal dedicat necesar

**Reguli de demotion:**
- Maxim 5 utilizări/lună
- 2 luni consecutive sub threshold
- Demotion pe tier-uri: command → business → tech → foundation

---

## 4. Stack Tehnologic

### Core

| Component | Tehnologie | Versiune | Scop |
|-----------|------------|----------|------|
| **Limbaj** | Python | 3.12 | Core runtime |
| **Web Framework** | FastAPI | ≥0.110 | API server + SSE streaming |
| **ASGI Server** | Uvicorn | ≥0.29 | HTTP server async |
| **Scheduler** | APScheduler | ≥3.10 | Heartbeat cron jobs |
| **HTTP Client** | HTTPX | ≥0.27 | Async HTTP calls |
| **Config** | PyYAML | ≥6.0 | YAML parsing (agents.yaml) |
| **Env Vars** | python-dotenv | ≥1.0 | .env loading |

### LLM Inference

| Backend | Port | Model | VRAM | Latență |
|---------|------|-------|------|---------|
| **LM Studio** (primary) | 1234 | google/gemma-4-31b-a4b | ~17 GB | ~4-5s |
| **Ollama** (fallback) | 11434 | qwen3:7b | ~5 GB | ~2-3s |
| **Claude API** (cloud) | — | claude-sonnet-4 | 0 GB | ~3-4s |
| **Gemini API** (cloud) | — | gemini-2.5-pro | 0 GB | ~3-5s |

**Model Details:**
- **Gemma 4 31B-A4B:** MoE (Mixture of Experts), ~4B active params, 16.76 GB VRAM
- **Extended thinking:** Produce `reasoning_content` + `content`
- **TdrDelay=8:** Registry setting pentru a preveni DPC_WATCHDOG_VIOLATION

### Voice Pipeline

| Component | Lib | Model | Scop |
|-----------|-----|-------|------|
| **Wake Word** | openWakeWord | custom | Detectare "jarvis", "hub" |
| **STT** | faster-whisper | large-v3 | Speech-to-text |
| **TTS** | edge-tts / Kokoro | — | Text-to-speech |

### Memory

| Layer | Storage | Dimensiune | Scop |
|-------|---------|------------|------|
| **Conversation** | JSONL files | — | Istoric conversații per session |
| **Vector Store** | NumPy (768-dim) | — | Similarity search (degrades without numpy) |
| **Checkpoints** | SQLite | — | Session state persistence |
| **Settings DB** | SQLite | — | Runtime settings (temp, model, wake words) |
| **Qdrant** (opțional) | Docker | — | Semantic search (H3.1) |
| **Neo4j** (opțional) | Docker | — | Knowledge graph (H3.2) |

### Security

| Component | Scop |
|-----------|------|
| **SecretScanner** | 10 patterns (API keys, tokens, passwords) |
| **PIIScanner** | 9 patterns (email, US SSN/phone, cards, RO CNP/IBAN/phone — CNP & IBAN checksum-validated) |
| **SSRF Protection** | Private IP blocking, redirect limits (max 5) |
| **AuditLogger** | SQLite + Merkle hash chain |
| **GuardrailsEngine** | WARN/REDACT/BLOCK modes |

### Channels

| Canal | Implementare | Status |
|-------|--------------|--------|
| **Web** | SSE streaming | ✅ |
| **Voice** | openWakeWord + Whisper + Kokoro | ✅ |
| **Telegram** | Bot API polling | ✅ |
| **Discord** | Bot API | 🔜 (H4.1) |
| **Email** | SMTP + IMAP | 🔜 (H4.2) |
| **Slack** | Bot API | 🔜 (H4.3) |

---

## 5. Componente Core

### 5.1 Orchestrator (`agents/core/orchestrator.py`)

**Responsabilități:**
- Încarcă toți agenții din `agents.yaml`
- Inițializează LLM Router (detectare automată LM Studio → Ollama)
- Inițializează Security Guardrails
- Încarcă plugin-uri (weather, news, cloud-llm, telegram, gmail, spotify, etc.)
- Descoperă skill-uri din `skills/`
- Gestionează checkpoint-uri SQLite
- Coordonează heartbeat scheduler
- Monitorizează settings DB (refresh la 30s)

**Metode cheie:**
- `load_agents()` — Încarcă agenții activi
- `handle_input(text, channel)` — Procesare input sincron
- `handle_input_stream(text, channel, on_token)` — Procesare streaming
- `_gather_plugin_data(text, intent)` — Colectează date de la plugin-uri
- `_call_agents_parallel(agent_ids, text, context, plugin_data)` — Cheamă agenții
- `_synthesize(responses, intent)` — Sintetizează răspunsuri multiple
- `_detect_handoff(responses)` — Detectează `[handoff:agent_id]`
- `_detect_skill_learning(responses, synthesized, intent)` — Învață skill nou

### 5.2 Agent (`agents/core/agent.py`)

**Structură:**
```python
class Agent:
    id: str              # jarvis, friday, etc.
    name: str            # Jarvis, Friday, etc.
    config: dict         # Din agents.yaml
    soul: dict           # SOUL.md content
    has_heartbeat: bool  # Da/Nu
    llm_router: HybridRouter
    permission_gate: PermissionGate
    _failures: int       # Tracking pentru demotion
    _last_latency: float # Performance tracking
```

**Ciclul de viață:**
1. `_load_soul()` — Citește `agents/<id>/SOUL.md`
2. `process(text, context)` — Execută request-ul
3. `_record_failure(reason)` — Track eșecuri
4. `should_demote` — Verifică dacă ≥5 eșecuri
5. `get_demotion_target()` — Returnează tier-ul inferior

**Control Tokens:**
- `[learn: task | step1,step2,step3 | command_name]` — Salvează skill
- `[handoff:agent_id]` — Transferă către alt agent

### 5.3 LLM Router (`agents/core/llm/`)

**HybridRouter (`hybrid_router.py`):**
- Detectare automată backend la startup
- Policy per agent (local-only, cloud-only, auto)
- Token budget estimation
- Graceful degradation

**Backends:**
- `LMStudioBackend` — OpenAI-compatible API pe port 1234
- `OllamaBackend` — Ollama API pe port 11434
- `ClaudeBackend` (anthropic.py) — Claude API streaming
- `GeminiBackend` (gemini.py) — Gemini API streaming

**Routing Logic:**
```
1. Verifică agent policy (frigga → local-only, vision → cloud-only)
2. Estimează tokeni (context + prompt)
3. Alege backend:
   - Tokeni > threshold → cloud (dacă e permis)
   - Cloud down → fallback local
   - Local down → try cloud (dacă e permis)
4. Returnează backend + model
```

### 5.4 Memory Manager (`agents/core/memory/`)

**Componente:**
- `ConversationManager` — JSONL session history
- `PersistenceManager` — Session persistence
- `VectorStore` — NumPy 768-dim similarity search
- `Manager` — Orchestrează toate cele 3

**Session Flow:**
1. `new_session()` — Creează session_id unic
2. `add_turn(session_id, role, content, agent_id)` — Adaugă mesaj
3. `get_context(session_id, last_n=6)` — Ia ultimele N mesaje
4. `get_agent_context(agent_id)` — Context specific agent

### 5.5 Checkpoint Manager (`agents/core/checkpoint.py`)

**Scop:** Persistență stare execuție pentru resume după crash/restart

**SQLite Schema:**
```sql
CREATE TABLE checkpoints (
    id INTEGER PRIMARY KEY,
    agent_id TEXT,
    session_id TEXT,
    prompt TEXT,
    timestamp REAL,
    success BOOLEAN,
    latency REAL,
    error TEXT
);

CREATE TABLE session_records (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    agent_id TEXT,
    metadata TEXT,
    created_at REAL
);
```

**Metode:**
- `save(orchestrator)` — Salvează stare curentă
- `restore(orchestrator)` — Restaurează din checkpoint
- `record_call(agent_id, success, latency, error)` — Log execuție
- `create_session_record(session_id, agent_id, metadata)` — Nouă sesiune

### 5.6 Sandbox (`agents/core/sandbox.py`)

**Scop:** Execuție cod izolat (Docker + subprocess)

**Niveluri:**
1. **Subprocess** — Execuție Python locală (rapid, menos safe)
2. **Docker** — Container izolat (lent, more safe)

**Endpoint:** `POST /sandbox/execute`
```json
{
  "code": "print('Hello')",
  "language": "python",
  "timeout": 30
}
```

### 5.7 Learning Loop (`agents/core/learning/loop.py`)

**Scop:** Înregistrează interacțiuni pentru optimizare viitoare

**Înregistrează:**
- Input text
- Răspunsuri agenți
- Răspuns sintetizat
- Latențe
- Succes/eșec
- Feedback (implicit/explicit)

**Optimizări:**
- Ajustează routing weights
- Sugerează promovare/demotion agenți
- Identifică pattern-uri de succes

---

## 6. Plugin-uri și Integrări

### 6.1 Plugin-uri Core

| Plugin | Fișier | API Key | Scop |
|--------|--------|---------|------|
| **Weather** | `weather.py` | — | wttr.in (fără API key) |
| **News** | `news.py` | — | BBC RSS feed |
| **Cloud LLM** | `cloud_llm.py` | Anthropic, OpenAI, Gemini | Fallback cloud |
| **Telegram Bot** | `telegram_bot.py` | TELEGRAM_BOT_TOKEN | Telegram channel |
| **Gmail** | `gmail_plugin.py` | GMAIL_ACCESS_TOKEN (OAuth) | Email reading |
| **Spotify** | `spotify_plugin.py` | SPOTIFY_CLIENT_ID, SECRET, TOKEN | Music control |
| **Google Calendar** | `google_calendar.py` | GOOGLE_CALENDAR_TOKEN (OAuth) | Calendar events |
| **Apple Health** | `apple_health.py` | — | iOS Health data (HTTP POST) |
| **WhatsApp Bridge** | `whatsapp_bridge.py` | — | Local bridge URL |
| **Homebridge** | `homebridge.py` | HOMEBRIDGE_URL, TOKEN | Smart home |
| **WebSearch** | `websearch.py` | TAVILY_API_KEY, SEARXNG_URL | Web research |
| **Oracle Bridge** | `oracle_bridge.py` | GITHUB_TOKEN | GitHub integration |

### 6.2 OAuth Flow (`agents/core/plugins/oauth.py`)

**Provideri:**
- Google (Gmail, Calendar)
- Spotify

**Endpoints:**
- `GET /api/oauth/status` — Status auth per provider
- `GET /api/oauth/auth-url/<provider>` — Generează URL auth
- `GET /api/oauth/callback/<provider>?code=...` — Callback OAuth

**Token Persistence:**
- Path: `memory_logs/tokens/<provider>.json`
- Auto-refresh pe 401
- Load from env sau file

### 6.3 Permission Gate (`agents/core/plugin_gate.py`)

**Scop:** Controlează care agenți pot apela care plugin-uri

**Config în `agents.yaml`:**
```yaml
jarvis:
  plugins: [cloud-llm, telegram]

frigga:
  plugins: [whatsapp-bridge]
  llm_policy: local  # Hard rule
```

**Metode:**
- `check_call(plugin_name, agent_id)` — Verifică permisiune
- `get_allowed_plugins(agent_id)` — Listă plugin-uri permise

---

## 7. Canale de Comunicație

### 7.1 Web Channel (`agents/core/channels/web.py`)

**Implementare:** SSE (Server-Sent Events) streaming

**Endpoint-uri:**
- `GET /` — Dashboard HTML
- `POST /chat` — Chat JSON (non-streaming)
- `POST /chat/stream` — Chat SSE streaming

**SSE Format:**
```
data: {"type": "start", "agent": "jarvis"}

data: {"type": "token", "text": "Bună"}

data: {"type": "token", "text": " ziua"}

data: {"type": "end", "agent": "jarvis", "text": "Bună ziua"}
```

### 7.2 Voice Channel (`agents/core/channels/voice.py`)

**Pipeline:**
1. **Wake Word Detection** — openWakeWord ("jarvis", "hub")
2. **STT** — faster-whisper → text
3. **Orchestrator** — Procesează text
4. **TTS** — Kokoro edge-tts → audio
5. **Playback** — Speaker output

**Config:**
- Wake words din settings DB: `general.wake_words`
- Fallback graceful la lipsă hardware

### 7.3 Telegram Channel (`agents/core/channels/telegram.py`)

**Implementare:** Polling API (nu webhook)

**Session Isolation:**
- Fiecare `chat_id` are sesiune separată
- `_channel_sessions["tg:<chat_id>"] = session_id`

**Config:**
- `TELEGRAM_BOT_TOKEN` în `.env`

### 7.4 Discord Channel (`agents/core/channels/discord.py`)

**Status:** 🔜 (H4.1)

**Implementare:** Discord.py bot cu slash commands

**Config:**
- `DISCORD_BOT_TOKEN` în `.env`

### 7.5 Email Channel (`agents/core/channels/email.py`)

**Status:** 🔜 (H4.2)

**Implementare:**
- SMTP pentru trimitere
- IMAP pentru citire

**Config:**
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
- `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASS`

### 7.6 Slack Channel (`agents/core/channels/slack.py`)

**Status:** 🔜 (H4.3)

**Implementare:** Slack bolt bot

**Config:**
- `SLACK_BOT_TOKEN` în `.env`

### 7.7 Gateway (`agents/core/channels/gateway.py`)

**Scop:** Routează mesajele între canale și orchestrator

**Session Management:**
```python
_channel_sessions = {
    "tg:123456789": "session_abc",  # Telegram chat_id
    "discord:987654321": "session_xyz"
}
```

**Metode:**
- `register_channel(channel_id)` — Înregistrează canal
- `route(text, channel, **kwargs)` — Routează către orchestrator

---

## 8. Sistemul de Skill-uri

### 8.1 Skill Loader (`agents/core/skills/loader.py`)

**Descoperire:**
- Scanează `skills/` directory
- Fiecare skill are `main.py` cu `SKILL.md` frontmatter

**Structură Skill:**
```
skills/
└── calendar/
    ├── SKILL.md          # Metadata + descriere
    └── main.py           # Implementare
```

**SKILL.md Frontmatter:**
```yaml
---
name: calendar-manager
version: 0.1.0
commands:
  - list: List today's events
  - add: Add new event
  - modify: Modify existing event
---
```

**Comenzi:**
- Skill-urile pot fi apelate direct: `/calendar list`
- Parser: `skills.parse_command(text)`

### 8.2 Skill Importer (`agents/core/skills/importer.py`)

**Scop:** Importă skill-uri din surse externe

**Surse:**
- Hermes skills
- OpenClaw skills
- GitHub URLs

**Endpoint:** `POST /skills/import`
```json
{
  "url": "https://github.com/user/repo/blob/main/skill.md"
}
```

### 8.3 Skill-uri Incluse

| Skill | Path | Comenzi |
|-------|------|---------|
| **Brief** | `skills/brief/` | morning, daily, weekly |
| **Calendar** | `skills/calendar/` | list, add, modify |
| **Content** | `skills/content/` | draft, edit, publish |
| **Family Store** | `skills/family_store/` | query, add (Max, Alexandra, cats) |
| **Health** | `skills/health/` | sleep, hrv, hr, steps |
| **PM** | `skills/pm/` | status, milestone, blocker (Cosmina, BMW) |
| **Spotify** | `skills/spotify/` | play, pause, skip, queue |
| **Weather** | `skills/weather/` | current, forecast |

---

## 9. Memorie și Învățare

### 9.1 Straturi de Memorie

**Working Memory:**
- Sesiune curentă
- Toate tururile, output-urile agenților, tool results
- Volatilă (se pierde la restart)

**Episodic Memory:**
- JSONL files în `memory_logs/sessions/`
- Format: `{session_id, timestamp, turns: [{role, content, agent_id}]}`
- Persistentă

**Semantic Memory:**
- Vector store (NumPy 768-dim)
- Similarity search pentru context retrieval
- Opțional: Qdrant (H3.1)

**Knowledge Graph:**
- Entități, relații, fapte
- Opțional: Neo4j (H3.2)
- Scriere doar pe confirmare explicită

### 9.2 Session Persistence

**Flow:**
1. `memory.new_session()` → session_id unic
2. `memory.add_turn(session_id, "user", text)`
3. `memory.add_turn(session_id, "assistant", response, agent_id)`
4. La close: `memory.save_session(session_id)`

**Channel Sessions:**
- Fiecare canal/chat_id are sesiune separată
- Permite continuarea conversației pe canale diferite

### 9.3 Learning Loop

**Înregistrează:**
```python
{
    "timestamp": 1717099200.0,
    "session_id": "abc123",
    "agent_id": "jarvis",
    "input": "Ce vreme e azi?",
    "responses": {"friday": "15°C, însorit"},
    "synthesized": "Sunt 15 grade și însorit.",
    "latency": 4.2,
    "success": true,
    "feedback": null  # Explicit feedback (viitor)
}
```

**Optimizări:**
- Adjustă routing weights pe baza succesului
- Sugerează promovare agenți bench la >20 uses/lună
- Identifică pattern-uri de eșec (demotion)

---

## 10. Securitate

### 10.1 Guardrails Engine (`agents/core/security/guardrails.py`)

**Mode:**
- **WARN** — Log warning, permite
- **REDACT** — Șterge informația sensibilă
- **BLOCK** — Blochează request-ul

**Config:**
```python
GuardrailsEngine(
    backend=llm_backend,
    mode=RedactionMode.WARN,
    scan_input=True,
    scan_output=True,
)
```

### 10.2 Scanner-e (`agents/core/security/`)

**SecretScanner:**
- 10 patterns (API keys, tokens, passwords, private keys)
- Regex-based detection

**PIIScanner:**
- 9 patterns (email, US SSN/phone, Visa/Mastercard/Amex, RO CNP, RO IBAN, RO phone)
- Romania-specific: CNP (control-digit checksum) + IBAN (ISO 7064 mod-97),
  validated so arbitrary 13-digit numbers / IBAN-shaped strings are not flagged

**SSRF Protection (`ssrf.py`):**
- Blochează IP-uri private (10.x.x.x, 192.168.x.x, 127.x.x.x)
- Blochează metadata cloud (169.254.169.254)
- Redirect limit: max 5
- Pre-fetch și post-redirect validation

### 10.3 Audit Logger (`agents/core/security/audit.py`)

**Stocare:** SQLite + Merkle hash chain

**Schema:**
```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    event_type TEXT,  # LLM_CALL, PLUGIN_CALL, SECURITY_EVENT
    findings TEXT,
    content_preview TEXT,
    action_taken TEXT,
    prev_hash TEXT,   # Merkle chain
    curr_hash TEXT
);
```

**Tipuri de Evenimente:**
- `LLM_CALL` — Apel către LLM
- `PLUGIN_CALL` — Apel plugin
- `SECURITY_EVENT` — Security finding
- `CHANNEL_MESSAGE` — Mesaj pe canal

### 10.4 Admin Guard (`agents/web.py`)

**Protecție `/api/admin/*`:**

1. **Token Auth:**
   - `JARVIS_ADMIN_TOKEN` în `.env`
   - Header: `X-Admin-Token: <token>`

2. **Localhost-only (fallback):**
   - Dacă token nu e setat, doar localhost poate accesa
   - Previne access din LAN fără auth

**Secret Masking:**
```python
def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-2:]}"
```

**Variabile mascate:**
- Conțin: key, token, secret, password, passwd, pass, client_id

---

## 11. Web API și Endpoints

### 11.1 Dashboard & Chat

| Endpoint | Method | Scop | Auth |
|----------|--------|------|------|
| `/` | GET | Dashboard HTML | — |
| `/favicon.ico` | GET | Favicon SVG | — |
| `/chat` | POST | Chat JSON (non-streaming) | — |
| `/chat/stream` | POST | Chat SSE streaming | — |

**Chat Request:**
```json
{
  "message": "Ce vreme e azi?",
  "agent": "friday"  # optional, default "jarvis"
}
```

**Chat Response:**
```json
{
  "reply": "Sunt 15 grade și însorit în București."
}
```

### 11.2 Status & Monitoring

| Endpoint | Method | Scop | Auth |
|----------|--------|------|------|
| `/status` | GET | System status (HUD-compatible) | — |
| `/dashboard` | GET | Dashboard data (weather, calendar) | — |
| `/tasks` | GET | Task list (placeholder) | — |
| `/ticker` | GET | Agent activity ticker | — |
| `/agents` | GET | Listă agenți | — |
| `/api/agents` | GET | Agent details (enriched) | — |

**Status Response:**
```json
{
  "sys": {
    "host": "BONOBO-WS",
    "cpu": "Intel Core Ultra 9 · 32c",
    "ram_used": 45.2,
    "ram_total": 192,
    "gpu": "RTX 5090 · 24GB",
    "vram_used": 17,
    "vram_total": 24,
    "gpu_load": 45,
    "backend": "LM Studio · 1234",
    "model": "google/gemma-4-31b-a4b",
    "latency": 4.2,
    "uptime": "02:15:33",
    "sessions": 3
  },
  "voice_state": "idle",
  "lm_online": true,
  "agents": [
    {"id": "jarvis", "status": "ready"},
    {"id": "friday", "status": "ready"}
  ],
  "agents_online": 15,
  "agents_total": 15
}
```

### 11.3 Memory & Sessions

| Endpoint | Method | Scop | Auth |
|----------|--------|------|------|
| `/sessions` | GET | Listă sesiuni | — |
| `/memory` | GET | Memory state | — |
| `/memory/clear` | POST | Clear current session | — |
| `/learning` | GET | Learning records | — |

### 11.4 Security & Admin

| Endpoint | Method | Scop | Auth |
|----------|--------|------|------|
| `/security` | GET | Security audit status | — |
| `/api/admin/env` | GET | Environment variables (masked) | Token/localhost |
| `/api/admin/settings` | GET | Settings DB | Token/localhost |
| `/api/admin/settings/clear` | POST | Clear settings DB | Token/localhost |

### 11.5 Skills & Sandbox

| Endpoint | Method | Scop | Auth |
|----------|--------|------|------|
| `/skills` | GET | Loaded skills | — |
| `/skills/imported` | GET | Imported skills | — |
| `/skills/import` | POST | Import skill from URL | — |
| `/sandbox/status` | GET | Sandbox availability | — |
| `/sandbox/execute` | POST | Execute code in sandbox | — |

### 11.6 Benchmarks

| Endpoint | Method | Scop | Auth |
|----------|--------|------|------|
| `/bench` | GET | Benchmark stats | — |

---

## 12. Hardware și Infrastructură

### 12.1 Bonobo WS (Primary)

**Specificații:**
- **CPU:** Intel Core Ultra 9 (32 cores)
- **RAM:** 192 GB DDR5
- **GPU:** NVIDIA RTX 5090 24 GB
- **Storage:** 4× NVMe + 18 TB HDD
- **OS:** Pop!_OS (System76)
- **Hostname:** BONOBO-WS

**Utilizare GPU:**
- ~17 GB VRAM: google/gemma-4-31b-a4b (MoE)
- ~7 GB VRAM: Free pentru alte modele/tasks

### 12.2 Raspberry Pi 5 (Always-on Services)

**Servicii:**
- **Qdrant** — Vector DB (H3.1)
- **Neo4j** — Knowledge Graph (H3.2)
- **n8n** — Workflow automation (H4.6)
- **Homebridge** — Smart home integration

### 12.3 Network Architecture

**VLAN-uri:**
- **Main VLAN:** Bonobo WS, Pi 5, devices
- **Smart Home VLAN:** IoT devices (izolat de Ultron)
- **Guest VLAN:** Oaspeți (fără access la Jarvis)

**Porturi:**
- **8000:** Jarvis web server (http://127.0.0.1:8000)
- **1234:** LM Studio API
- **11434:** Ollama API (fallback)

---

## 13. Ghid de Utilizare

### 13.1 Instalare (Windows 11)

**One-click (no terminal):**

1. **Prima instalare:**
   - Dublu-click `INSTALL.bat`
   - Verifică/instalează Python + Git via winget
   - Descarcă codul, build environment, instalează dependencies
   - Rulează testele

2. **Update:**
   - Dublu-click `UPDATE.bat`
   - Pull latest from GitHub
   - Install dependencies
   - Run tests

3. **Start:**
   - Dublu-click `START.bat`
   - Deschide serverul și HUD în browser
   - Ține fereastra deschisă (close = stop server)

### 13.2 Instalare (Manual — orice OS)

```bash
# Clone repo
git clone <repo-url>
cd cabinet

# Create venv
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements-beta.txt
pip install tiktoken beautifulsoup4 psutil pytest-asyncio

# Start server
python serve.py  # http://127.0.0.1:8000

# Run tests
python -m pytest  # 181 passed, 8 skipped
```

### 13.3 Utilizare Voice

**Wake words:**
- "Jarvis" — standard
- "Hub" — stealth/public contexts

**Exemple:**
- "Jarvis, ce vreme e azi?"
- "Hub, adaugă meeting mâine 10-11"
- "Jarvis, pune ceva focus" (Jerome)
- "Jarvis, cum am dormit?" (Hercules)

### 13.4 Utilizare Web

**URL-uri:**
- **HUD:** http://127.0.0.1:8000/
- **Admin:** http://127.0.0.1:8000/admin

**HUD Features:**
- System status (CPU, GPU, RAM, VRAM)
- Agent status (ready/idle)
- Chat interface (streaming)
- Weather + calendar widgets
- Activity ticker

**Admin Features:**
- Settings DB editor (temperature, max_tokens, model, wake_words)
- Memory management (clear sessions)
- OAuth status & callbacks
- Security audit log
- Benchmark stats

### 13.5 Utilizare Telegram

**Setup:**
1. Creează bot via @BotFather
2. Copiază token în `.env`: `TELEGRAM_BOT_TOKEN=...`
3. Restart server

**Comenzi:**
- Orice mesaj text → Jarvis
- Session isolation per chat_id

### 13.6 Skill Commands

**Format:** `/skill_name command args`

**Exemple:**
```
/calendar list
/calendar add "Meeting" 2026-05-31 10:00 11:00
/brief morning
/health sleep
/pm status cosmina
/spotify play focus
```

---

## 14. Ghid de Dezvoltare

### 14.1 Adăugare Agent Nou

1. **Creează director:**
   ```bash
   mkdir agents/<agent_id>
   ```

2. **Adaugă SOUL.md:**
   ```markdown
   ---
   id: <agent_id>
   name: <Display Name>
   archetype: <Role>
   status: active
   tier: <command|business|tech|foundation>
   ---

   # <Agent Name>

   ## Identity
   ...

   ## Mission
   ...

   ## Scope
   ...
   ```

3. **Actualizează `agents.yaml`:**
   ```yaml
   agents:
     <agent_id>:
       name: <Display Name>
       archetype: <Role>
       status: active
       tier: <tier>
       channel: <channel>
       heartbeat: "<interval>"
       plugins: []
   ```

4. **Restart server**

### 14.2 Adăugare Plugin Nou

1. **Creează fișier:**
   ```python
   # agents/core/plugins/<plugin_name>.py

   class <PluginName>Plugin:
       def __init__(self, api_key: str = ""):
           self.api_key = api_key

       async def do_something(self, param: str) -> str:
           # Implementare
           return result
   ```

2. **Înregistrează în orchestrator:**
   ```python
   # orchestrator.py
   from .plugins.<plugin_name> import <PluginName>Plugin

   self.plugins["<plugin_name>"] = <PluginName>Plugin(
       api_key=os.environ.get("<ENV_VAR>", ""),
   )
   ```

3. **Adaugă la agent în `agents.yaml`:**
   ```yaml
   agents:
     jarvis:
       plugins: [..., "<plugin_name>"]
   ```

### 14.3 Adăugare Skill Nou

1. **Creează director:**
   ```bash
   mkdir skills/<skill_name>
   ```

2. **Adaugă SKILL.md:**
   ```yaml
   ---
   name: <skill-name>
   version: 0.1.0
   commands:
     - <command>: <description>
   ---

   # <Skill Name>

   Description...
   ```

3. **Adaugă main.py:**
   ```python
   async def execute(command: str, args: dict, context: dict) -> str:
       if command == "<command>":
           # Implementare
           return result
       return "Unknown command"
   ```

4. **Restart server** — skill-ul este auto-descoperit

### 14.4 Adăugare Canal Nou

1. **Creează fișier:**
   ```python
   # agents/core/channels/<channel_name>.py

   from .base import ChannelAdapter

   class <ChannelName>Channel(ChannelAdapter):
       async def start(self):
           # Inițializare

       async def stop(self):
           # Cleanup

       async def send(self, message: str, **kwargs):
           # Trimite mesaj
   ```

2. **Înregistrează în web.py:**
   ```python
   from core.channels.<channel_name> import <ChannelName>Channel

   <channel>_ch = <ChannelName>Channel(handler=gateway.route)
   await orch.register_channel(<channel>_ch)
   ```

3. **Restart server**

### 14.5 Testing

**Run all tests:**
```bash
python -m pytest tests/ -v
```

**Test specific:**
```bash
python -m pytest tests/test_spotify.py -v
```

**Smoke test:**
```bash
powershell .\smoke.ps1
```

**Coverage:**
- 181 teste passing
- 8 skipped
- 39 teste pentru features specifice

### 14.6 Debugging

**Logging:**
```python
from core.log import log_error, logger

logger.info("Message")
log_error(logger, E_INTERNAL_UNEXPECTED, component="xyz", detail="...")
```

**Dev mode:**
```bash
export DEV_MODE=1
python serve.py
```

**Console:**
- Server logs în terminal
- Browser DevTools pentru frontend
- Admin panel → Security audit log

---

## 15. Status și Roadmap

### 15.1 Status Curent (v0.2.1)

**Complet (✅):**
- 15 agenți activi (4 command, 4 business, 3 tech, 4 foundation)
- 15 bench agents (rezervați)
- Hybrid LLM Router (local ↔ cloud)
- 10 plugin-uri (weather, news, cloud-llm, telegram, gmail, spotify, calendar, apple-health, whatsapp, homebridge, websearch, oracle-bridge)
- 6 canale (web, voice, telegram, discord, email, slack — ultimele 3 parțial)
- Skills system + sandbox + learning loop
- Security guardrails + audit log + SSRF protection
- Settings DB (SQLite) cu runtime updates
- OAuth flows (Google, Spotify)
- Checkpoint manager (SQLite)
- Heartbeat scheduler (APScheduler)
- 39 teste passing

**În lucru (🔜):**
- H2.2: Pepper Email Triage
- H2.9: Vision Web Research
- H2.11: Stark GA4 + Firebase
- H4.1: Discord Channel
- H4.2: Email Channel
- H4.3: Slack Channel
- H4.4: Ultron Security Monitoring
- H4.5: Steve System Monitor
- H4.6: Oracle n8n Workflows

**Blocat (🔴):**
- H2.6: Gecko Balance (API bănci necesar)
- H2.11: Stark GA4 + Firebase (API access necesar)

### 15.2 Roadmap

**Sprint 0 (Stabilitate & Performanță) — ✅ 100%**
- S0.1: Model Tiering (local 7b + cloud Claude) ✅
- S0.2: Heartbeat Sanity (intervale ≥60 min) ✅
- S0.3: Smoke Test + CI ✅

**Orizont 1 (Foundation) — ✅ 100%**
- H1.1: Voice Channel ✅
- H1.2: Telegram Channel ✅
- H1.3: Web Channel robust ✅
- H1.4: Plugin Auth wiring ✅
- H1.5: Admin DB → Runtime ✅

**Orizont 2 (Core Agent Capabilities) — 70% (8/12)**
- H2.1: Pepper Calendar ✅
- H2.2: Pepper Email Triage 🔜
- H2.3: Friday Brief Pipeline ✅
- H2.4: Hercules Health Data Loop ✅
- H2.5: Jerome Spotify Control ✅
- H2.6: Gecko Balance 🔴
- H2.7: Hephaestus PM ✅
- H2.8: Frigga Local Data Store ✅
- H2.9: Vision Web Research 🔜
- H2.10: Veronica Drafting ✅
- H2.11: Stark GA4 + Firebase 🔴

**Orizont 3 (Intelligence & Memory) — 0% (0/6)**
- H3.1: Qdrant Vector DB
- H3.2: Neo4j Knowledge Graph
- H3.3: Session Persistence cross-channel
- H3.4: Learning Loop live
- H3.5: Heartbeat System
- H3.6: Bench Agent Activation

**Orizont 4 (Platform & Security) — 0% (0/11)**
- H4.1: Discord Channel
- H4.2: Email Channel
- H4.3: Slack Channel
- H4.4: Ultron Security Monitoring
- H4.5: Steve System Monitor
- H4.6: Oracle n8n Workflows
- H4.7: MCP Client real
- H4.8: Sandbox containerized
- H4.9: Guardrails production (REDACT mode)
- H4.10: Admin Charts & Audit
- H4.11: Context Caching + Hybrid Routing Metrics

### 15.3 Metrics

| Metric | Valoare |
|--------|---------|
| **Agenți activi** | 15 |
| **Agenți bench** | 15 |
| **Plugin-uri** | 12 |
| **Canale** | 6 (3 fully functional) |
| **Skill-uri** | 8 |
| **Teste** | 181 passed, 8 skipped |
| **Endpoints API** | 17 |
| **VRAM utilizat** | ~17 GB / 24 GB |
| **Latență medie** | ~4-5s |
| **Uptime** | Variable (depinde de sesiune) |

### 15.4 Efort Estimat

| Horizon | Items | Story Points | Efort |
|---------|-------|--------------|-------|
| H2剩余 | 4 | 23 S | ~1.5 săptămâni (paralel 2) |
| H3 | 6 | 39 S | ~2.5 săptămâni (paralel 2) |
| H4 | 11 | 63 S | ~4 săptămâni (paralel 3) |
| Cross-cutting | 4 | 38 S | ~2.5 săptămâni |
| **Total** | **25** | **163 S** | **~10 săptămâni** |

**Echipă 3-4 agenți paralel:** ~3 luni până la complet

---

## Anexe

### A. Fișiere de Configurație

**`.env` (example):**
```bash
# LLM
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...

# Telegram
TELEGRAM_BOT_TOKEN=...

# OAuth (Google)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# OAuth (Spotify)
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...

# Admin
JARVIS_ADMIN_TOKEN=secure-random-token-here
```

**`agents.yaml`:**
- Agent registry
- General settings (timezone, wake_words, llm_backend)
- Plugin permissions per agent
- Bench agents definitions
- Promotion/demotion rules

**`pytest.ini`:**
```ini
[pytest]
asyncio_mode = auto
testpaths = tests/
```

### B. Comenzi Utile

```bash
# Start server
python serve.py

# LM Studio management (Windows)
lms server start
lms load google/gemma-4-31b-a4b --identifier gemma4
lms unload gemma4
lms ps

# Test status
curl http://127.0.0.1:8000/status

# Run tests
python -m pytest tests/ -v

# Smoke test
powershell .\smoke.ps1

# View logs
tail -f memory_logs/sessions/*.jsonl
```

### C. Resurse Externe

- **Documentație:** https://hermes-agent.nousresearch.com/docs
- **LM Studio:** https://lmstudio.ai/
- **Ollama:** https://ollama.ai/
- **FastAPI:** https://fastapi.tiangolo.com/
- **APScheduler:** https://apscheduler.readthedocs.io/

---

**Sfârșitul Documentației**

*Generat automat pe baza analizei codebase-ului — 30 Mai 2026*
