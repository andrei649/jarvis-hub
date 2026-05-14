# Jarvis Hub — Personal AI Agent System

15 agenți specializați, controlați prin voce și interfață web.
100% local, offline-first, cu plugin layer extensibil.

## Arhitectura

```
                    ┌─────────────┐
                    │   Voice In  │
                    │ (Wake+STT)  │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │   JARVIS    │ ← CNS Orchestrator
                    │ (DeepSeek)  │
                    └──┬──────┬───┘
                       │      │
              ┌────────▼──┐ ┌─▼──────────┐
              │  Router   │ │  Pepper    │
              │ (Intent)  │ │  (EA)      │
              └──┬─────┬──┘ └────────────┘
                 │     │
    ┌────────────▼──┐ ┌▼──────────────┐
    │  Specialists  │ │  Foundation   │
    │ Athena, Stark │ │ Gecko, Herc   │
    │ Steve, Vision │ │ Heph, Frigga  │
    │ Ultron, Oracle│ │               │
    │ Veronica      │ │               │
    └───────────────┘ └───────────────┘
```

## Cei 15 Agenți

### CNS (Central Nervous System)
| Agent | Model | Rol |
|-------|-------|-----|
| Jarvis | deepseek-r1:32b | Orchestrator principal |
| Friday | qwen2.5:7b | Daily intelligence |
| Pepper | qwen2.5:14b | Chief of Staff |
| Jerome | qwen2.5:7b | Leisure & DJ |

### Business
| Agent | Model | Rol |
|-------|-------|-----|
| Athena | deepseek-r1:32b | Strategie Digitaholic |
| Stark | deepseek-r1:32b | BI Raiffeisen |
| Steve | qwen2.5:7b | CTO & Infra |
| Vision | deepseek-r1:32b | Research & OSINT |

### Tech & Security
| Agent | Model | Rol |
|-------|-------|-----|
| Ultron | qwen2.5:7b | Security |
| Oracle | qwen2.5:7b | n8n Workflows |
| Veronica | qwen2.5:14b | Content & Comms |

### Foundation
| Agent | Model | Rol |
|-------|-------|-----|
| Gecko | qwen2.5:14b | Finanțe |
| Hercules | qwen2.5:7b | Fitness & Health |
| Hephaestus | qwen2.5:14b | House & Car |
| Frigga | qwen2.5:14b | Family (100% local) |

## Quick Start

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull models
ollama pull deepseek-r1:32b
ollama pull qwen2.5:14b
ollama pull qwen2.5:7b

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Start
python main.py
```

Accesează http://localhost:8765 pentru Web UI.
Spune "Jarvis" pentru voice control.

## Plugin-uri

Pluginurile sunt opt-in, fiecare cu permission scope explicit:
- telegram_bot: Telegram messaging
- gmail_bridge: Gmail read (read-only)
- calendar_bridge: Google Calendar (read-only)
- slack_bridge: Slack messaging
- whatsapp_bridge: WhatsApp (Frigga only, gated)
- homebridge: Smart home control
- spotify_control: Spotify playback

## Licență

MIT
