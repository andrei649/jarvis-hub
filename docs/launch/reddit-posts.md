# Reddit launch posts — Jarvis Hub

> Per the GTM research: lead with value/story (not a pitch), include the GitHub link + a
> `docker-compose`/stack details so it's replicable, keep self-promo ≤10% of account history
> (the 90/10 rule), tailor each post (don't cross-post identical text), and answer every comment.
> Fire same-day as Show HN to concentrate GitHub star velocity. Read each sub's rules first.

---

## r/LocalLLaMA

**Title:** `I built a governed, multi-agent assistant on top of local models — every autonomous action is approved + audit-logged`

**Body:**

I've been running everything through LM Studio/Ollama and kept hitting the same wall: the chat UIs are great, but the moment you want agents that *act* (not just answer), you're either gluing scripts together or reaching for an ungoverned agent runner that'll happily run wild.

So I built Jarvis Hub: 16 specialized agents with a planner, persistent memory (vector ⊕ knowledge-graph fused recall), and — the part I think this sub will care about — **governed autonomy**. Reversible actions run on their own; irreversible/costly ones block on an approval queue. Every tool call is hash-chained into a tamper-evident audit log. There's a kill-switch and a model badge that reports the *actual* loaded model (it can even start LM Studio / load/unload models from chat, behind a kill-switch).

- Local-first, hybrid optional (local for the 80%, opt-in cloud for the hard 20%)
- Auto-detects your loaded model; fast/deep routing with separate token budgets so reasoning models don't truncate mid-thought
- Pure Python, MIT, self-host; 1,623 tests passing offline
- Stack: Python 3.12 + FastAPI, LM Studio/Ollama, optional Qdrant/Neo4j

Repo (self-host, `docker-compose` + one-click Windows installer): <GITHUB_URL>

Genuinely after feedback: for those of you running agents locally — how much autonomy do you actually let them have, and what would it take for you to trust one to act unattended? What's your current model + VRAM, and where does local fall short for agent work?

---

## r/selfhosted

**Title:** `Jarvis Hub – a self-hosted, local-first personal AI assistant (16 agents, approval queue + audit log, no cloud by default)`

**Body:**

Sharing a thing I self-host: a personal AI assistant that runs entirely on my own hardware — no cloud dependency by default, ~$0/month in API cost. It's 16 agents coordinated by a planner, with persistent memory and **governed autonomy**: anything irreversible waits for my approval (Telegram one-tap or the web HUD), and every action is written to a tamper-evident audit log. A family-memory agent is hard-wired to never touch the internet.

Why I think it fits here: it's the opposite of the "point an ungoverned agent at your machine" approach. Local execution, encrypted secrets, no exposed gateway port by default, SSRF/PII/secret scanning, and a global kill-switch.

- Runs on LM Studio/Ollama (your GPU); CPU works for smaller models
- Self-host: `docker-compose` for Qdrant/Neo4j; one-click `INSTALL.bat` on Windows; `pip install -r requirements-beta.txt && python serve.py` elsewhere
- Pure Python, MIT, 1,623 offline tests; pre-1.0 (audit gate)
- Channels: web (SSE), voice, Telegram, Discord, email, Slack

Repo: <GITHUB_URL> · Hardware I run it on: <CPU/GPU/RAM>.

Feedback welcome — especially on the install/first-run experience and what you'd want governed vs. left autonomous.

---

## Checklist
- [ ] Replace `<GITHUB_URL>` and `<CPU/GPU/RAM>`.
- [ ] Confirm `docker-compose` + install paths actually work on a clean machine before posting.
- [ ] Post value-first; respond to every comment in the first few hours.
- [ ] Don't paste the same text to both subs — these are intentionally different.
