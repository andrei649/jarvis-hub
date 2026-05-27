# Week 1 — Foundation

## Goal

Get the jarvis running end-to-end on a CLI prompt (voice comes in week 2). By Friday, you should be able to type a message and get a routed, synthesized response from any of the 15 agents.

## Monday — Hardware & OS Prep

**Bonobo WS:**
- [ ] Confirm Pop!_OS is up to date: `sudo apt update && sudo apt upgrade -y`
- [ ] Install Python 3.12: `sudo apt install python3.12 python3.12-venv -y`
- [ ] Install Ollama: `curl -fsSL https://ollama.com/install.sh | sh`
- [ ] Pull heavy model: `ollama pull deepseek-r1:32b-q4_K_M` (starts ~20GB, runs in background)
- [ ] Pull specialist models: `ollama pull qwen2.5:14b && ollama pull qwen2.5:7b`
- [ ] Install system deps: `sudo apt install git docker.io docker-compose -y`

**Pi 5:**
- [ ] Flash Pi OS Lite, enable SSH
- [ ] Install Docker: `curl -fsSL https://get.docker.com | sh`
- [ ] Create docker-compose.yml for services

## Tuesday — Python Environment

- [ ] Clone/extract jarvis: `mkdir ~/jarvis && cd ~/jarvis && tar xzf jarvis-v0.1.0.tar.gz`
- [ ] Create venv: `python3.12 -m venv .venv && source .venv/bin/activate`
- [ ] Install core deps: `pip install pyyaml apscheduler httpx`
- [ ] Test config loader: `python -c "from core.config import JarvisConfig; c = JarvisConfig(); print(f'Loaded {len(c.agents)} agents')"`
- [ ] Test orchestrator: `python -c "from core.orchestrator import Orchestrator; print('OK')"`
- [ ] Manual test: read `agents/jarvis/SOUL.md` and verify the config matches

## Wednesday — First Agent Test

- [ ] Start Ollama: `ollama serve`
- [ ] Test DeepSeek via API: `curl http://localhost:11434/api/generate -d '{"model":"deepseek-r1:32b-q4_K_M", "prompt":"Who are you?","system":"You are Jarvis, a British butler AI."}'`
- [ ] Load Jarvis SOUL.md as system prompt, chat 5 turns
- [ ] Test Qwen 7B (Friday): same process
- [ ] Verify model switching works

## Thursday — Multi-Agent Routing

- [ ] Test router manually: `python -c "from core.router import IntentRouter; r = IntentRouter(None); print('OK')"`
- [ ] Test multi-agent orchestration with 3 agents (Jarvis + Friday + Pepper)
- [ ] Test each remaining agent with a simple prompt
- [ ] Log all responses, verify tone consistency

## Friday — End-to-End CLI

- [ ] Build a simple CLI loop: `python -m core.main` that accepts text input, routes, responds
- [ ] Test 5 conversation flows end-to-end
- [ ] Start Pi 5 services: `docker compose up -d qdrant neo4j n8n`
- [ ] Verify connectivity: Bonobo -> Pi (Qdrant port 6333, Neo4j port 7687)

## Weekend — Read & Refine

- [ ] Read all 15 SOUL.md files. Mark anything that sounds wrong.
- [ ] Test 3 agent personas in Open WebUI (paste SOUL.md as system prompt)
- [ ] Decide on wake words, addressing, and Frigga WhatsApp approach
- [ ] Report back for Week 2 plan (voice layer + heartbeats)
