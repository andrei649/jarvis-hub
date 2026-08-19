# Content Calendar & Copy Bank — Jarvis Hub launch

> Ready-to-schedule content for the launch window, sequenced to the campaign plan. Everything here
> is paste-ready and on-brand (calm, specific, butler-not-hype). Copy a row, post it. Numbers are
> verified-conservative; the approved-proof allowlist is [`../../docs/marketing/DESIGN_BRIEF.md`](../../docs/marketing/DESIGN_BRIEF.md) §5.
> Companion: [`../campaign-plan/CAMPAIGN_PLAN.md`](../campaign-plan/CAMPAIGN_PLAN.md) (the plan),
> [`../../docs/marketing/TEASER_PACK.md`](../../docs/marketing/TEASER_PACK.md) (taglines + video script).

---

## A. The teaser arc — 5 posts, T-5 → T-1 days (X / Mastodon / LinkedIn)

**T-5 · Premise**
> Most AI assistants make you choose: useful, or private.
> We refused.
> Something local-first is coming. 🧵

**T-4 · Proactivity**
> Your assistant shouldn't wait to be asked.
> Imagine 18 specialist agents that work 24/7 on *your* hardware — find their own work, do the safe
> things silently, and ask you only when it matters.
> Approve enough times, it learns to stop asking.

**T-3 · Governance (the differentiator)**
> The 2026 lesson: an autonomous AI agent with no brakes becomes the #1 infostealer target.
> We took the other road.
> Every action gated by a reversible/irreversible approval queue. Every action in a tamper-evident
> audit log. The family agent never touches the internet — enforced in code, not a setting.

**T-2 · Memory**
> It gets better the longer you use it.
> Every night it reads the day, extracts people + projects + facts into a knowledge graph, and
> fuses that into tomorrow's answers.
> No configuration. A system that learns your life — on your machine.

**T-1 · The reveal teaser**
> Tomorrow.
> 18 agents. One system. Your data stays home.
> Local-first. Governed. $0/month. Open.

---

## B. Launch-day posts

**X / Mastodon — the reveal**
> It's here: **Jarvis Hub** — a personal AI operating system you actually own.
>
> · 18 specialist agents, on your own GPU
> · proactive, governed (approval queue + tamper-evident audit log)
> · living knowledge-graph memory
> · family agent never touches the internet
> · $0/month, zero cloud by default, open
>
> The AI that works while you sleep → github.com/andrei649/jarvis-hub

**Show HN — title + first comment**
> **Title:** Show HN: Jarvis Hub — a governed, local-first multi-agent AI assistant
>
> **First comment:** I built Jarvis Hub because I wanted the always-on AI agent everyone chased in
> 2026 — without the part where my private life lives on someone else's servers, and without the
> ungoverned-autonomy security disasters.
>
> It's 18 specialist agents coordinated by an orchestrator, running locally via LM Studio/Ollama.
> What makes it different from a chatbot: it's *proactive* (a self-tasking queue runs 24/7), it
> *compounds* (nightly knowledge-graph consolidation + fused recall), and it's *governed* — every
> action is risk-classified and gated through a reversible/irreversible approval queue, written to a
> tamper-evident hash-chained audit log you can verify. The family/security/digital-twin agents are
> code-enforced to never reach the cloud.
>
> It's pure Python, ~2,150 tests, self-hostable in one command (it runs the suite to prove the
> install). Honest about limits: local handles ~99% of daily tasks at $0; heavy reasoning escalates
> to a cloud model only with an explicit, audited per-agent opt-in. Happy to go deep on the
> architecture, the governance model, or the design trade-offs. Repo: [link].

**r/LocalLLaMA — value-first post**
> **Title:** I built a local-first, governed multi-agent personal assistant — 18 agents on your own GPU, every action audited
>
> Body: Runs on LM Studio/Ollama. 18 specialist agents (daily intel, calendar, research, finance,
> home, family memory…) coordinated by an orchestrator, talking over web/voice/Telegram/Discord/
> Slack/email. The part I care most about: it *acts* for you but every autonomous action passes a
> reversible/irreversible approval queue and lands in a tamper-evident audit log; strict-local
> agents never touch the cloud. Memory is a nightly-consolidated knowledge graph + fused vector
> recall, not just RAG-over-docs. Pure Python, ~2,150 tests, one-command install, `docker-compose`
> included. Hardware: runs on a single consumer GPU. AMA on the stack / governance / why local-first.
> Repo + compose: [link]

**r/selfhosted — tailored**
> **Title:** Jarvis Hub — a self-hosted personal AI that's proactive AND governed (approval queue + tamper-evident audit log)
>
> Body: For the "I want an AI assistant but not on someone's cloud" crowd. Self-host the whole thing;
> nothing leaves your machine by default. It's multi-agent + proactive (24/7 self-tasking queue) but
> with brakes: every action is risk-gated and audited, with a kill-switch. $0/month, open, one-click
> install that runs its own test suite. Stack + screenshots inside. [link]

---

## C. The launch thread (X — 7 tweets, fire after the reveal)

1. We built the always-on AI agent everyone wanted in 2026 — with the governance, audit, and privacy the viral one was missing. Here's what's different. 🧵
2. **It's local-first.** 18 specialist agents run on your own GPU via LM Studio/Ollama. Your calendar, email, family data — processed on your machine, not a hyperscaler's. $0/month.
3. **It's proactive.** A self-tasking queue runs 24/7. It finds its own work, does reversible things silently, and escalates the rest. One tap to approve on Telegram. Approve enough → it stops asking.
4. **It's governed.** Every action is risk-classified and gated: read-only and reversible run free; irreversible or costly wait for you. Every action lands in a tamper-evident, hash-chained audit log you can verify with one call.
5. **It compounds.** Each night it reads the day's conversations into a knowledge graph and fuses that into every future answer. The longer you use it, the more it knows — zero config.
6. **The proof it's real, not a demo:** during hardening, an audit caught that the *family* agent could fall back to the cloud if the local model was down. One line. Caught pre-launch. Now impossible by construction — with a test that fails if anyone reintroduces it. *That's what "governed" means here.*
7. Pure Python, ~2,150 tests, self-host in one command. The AI that works while you sleep — owned by you. → github.com/andrei649/jarvis-hub

---

## D. Long-form — blog/dev.to post outline (founder voice)

**Title:** *Why I built a governed, local-first AI assistant (and what the 2026 agent meltdown taught me)*

1. **The two false choices** — useful-but-cloud vs. private-but-a-toy; reactive-but-safe vs. autonomous-but-reckless.
2. **2026's cautionary tale** — the viral always-on agent that became the #1 infostealer target (plaintext secrets, ungoverned autonomy). The demand was real; the safety wasn't.
3. **The thesis: local-first + governed is the durable answer** — privacy promise *and* cost advantage in one move.
4. **How it works** — 18 agents, the orchestrator, the autonomy queue + risk gate, the nightly knowledge graph, the tamper-evident audit log, the strict-local agents.
5. **The honesty discipline** — the BUG-14 story; why "enforced in code, proven by tests" beats a values page.
6. **What it costs** — $0/month, hybrid by choice, your data trains no one.
7. **Try it** — one-command self-host; what's next on the road to and beyond 1.0.

> Reuse the full long-form body from [`../../docs/marketing/ANNOUNCEMENT.md`](../../docs/marketing/ANNOUNCEMENT.md).

---

## E. Evergreen / post-launch cadence (the flywheel)

| Cadence | Content | Channel |
|---------|---------|---------|
| Weekly | "Shipped this week" — one real improvement, building-in-public | X + changelog + Discord |
| Bi-weekly | A single agent spotlight (what Friday/Vision/Frigga does, with a real screenshot) | X + blog |
| Monthly | A deeper piece (the memory graph, the governance model, a competitor-honest comparison) | Blog / dev.to |
| On-demand | Answer every GitHub issue + Reddit/HN comment — durable winners "kept shipping in public" | GitHub / Reddit / HN |
| When earned | Reshare community YouTube tutorials / setups | X + Discord |

---

## F. Hashtag / community kit

- Tags: `#localfirst` `#selfhosted` `#privacy` `#opensource` `#AI` `#LLM` `#homelab` `#LocalLLaMA`
- Communities: r/LocalLLaMA, r/selfhosted, r/homelab, r/opensource, HN, lobste.rs, Mastodon
  fosstodon.org, relevant Discords.
- One-liner for bios/OG: *Local-first, governed personal AI OS. 18 agents, proactive, on your own GPU. Your data stays home.*

---

*Numbers in this file are conservative against the verified counts (18 agents, 2,156 tests → "~2,150",
~250+ routes, 7 channels). Re-check `BACKLOG.md` before changing any stat; re-verify competitor claims
(competitive brief §7) before any comparison post.*
