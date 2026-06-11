# Jarvis Hub — Launch Announcement

> Ready-to-adapt release copy for a launch blog post, Product Hunt, Show HN, or a press note.
> All numbers are verified against the codebase as of 2026-06-10 (v9.9.9, pre-1.0 audit gate).
> Voice: calm competence, butler not hype-man (see `docs/BRAND_BOOK.md` §6). Pick the length you
> need; they share the same spine.

---

## TL;DR (the one-paragraph version)

**Jarvis Hub is a personal AI operating system that runs entirely on your own hardware.** Seventeen
specialist agents work 24/7 — they monitor your world, consolidate what they learn into a knowledge
graph every night, and surface a prioritized brief each morning. Every autonomous action passes a
reversible/irreversible approval queue and a tamper-evident audit log; every cloud hop is opt-in;
and the family agent never touches the internet. No subscription, no data leaving your machine,
$0/month. The AI that works while you sleep — owned by the person it serves, not the vendor.

---

## The hook (headline + subhead options)

**Primary**
> # The AI that works while you sleep.
> A local-first personal AI OS — 17 agents, governed autonomy, zero cloud by default. Your life
> never leaves your machine.

**Alternates**
> # Your AI. Your hardware. Your rules.
> # 17 agents. One system. Your data stays home.
> # Finally, an AI that learns what to *stop* asking you.

---

## The problem (why this exists)

Every AI assistant today makes you choose between **useful** and **private**, and between
**reactive** and **safe**.

The useful ones live in someone else's cloud — your calendar, your email, your family's data,
processed on servers you don't control and used to train models you'll never see. The private ones
are toys. And the new wave of "autonomous" agents picked a third, worse option: they act on your
behalf with no brakes. In 2026 the most viral of them became the #1 infostealer target within
weeks, harvesting users' own agent-memory files.

You shouldn't have to pick. **Local-first + governed is the durable answer** — it's the privacy
promise *and* the cost advantage in one move.

---

## The product (what it actually is)

Jarvis Hub is a mesh of **17 specialist agents** coordinated by Jarvis, the orchestrator. Each owns
a domain — daily intel, calendar and meetings, research, finance, home infrastructure, family
memory — and they hand work to each other through Jarvis, in one voice, on whatever channel you
reach them: web, voice, Telegram, Discord, Slack, email.

It runs on **your** GPU via LM Studio or Ollama. Cloud models are an explicit, per-agent, auditable
opt-in — never the default.

**Three things make it different from a chatbot:**

1. **It's proactive.** A self-tasking queue runs around the clock. It finds its own work, does the
   reversible things silently, and escalates anything irreversible or costly to you — one tap to
   approve on Telegram. Approve the same kind of thing enough times and it learns to stop asking.

2. **It compounds.** Every night it reads the day's conversations, extracts people, projects, and
   facts into a knowledge graph, and fuses that with vector recall on every query. The longer you
   use it, the more it understands — with zero configuration.

3. **It's governed, provably.** Every action is classified by risk and gated accordingly. Every
   action is written to a tamper-evident, hash-chained audit log you can verify. Every fact it
   knows about you is inspectable and deletable. The strict-local agents (family, security, your
   digital twin) are *code-enforced* to never reach the cloud — not a setting, a guarantee.

---

## Proof, not adjectives

This isn't a demo. As of the pre-1.0 audit gate:

- **17 specialist agents** across 4 tiers, plus a bench of 17 more, promotable at runtime.
- **2,150+ automated tests** on the Python core, plus frontend and OSINT-stack suites — green in CI.
- **~250 API endpoints**, a real-time cockpit HUD, and 7 channels.
- **$0/month** to run for the vast majority of tasks — local inference, no metered cloud.
- A **tamper-evident audit log** with a one-call integrity check, a reversible/irreversible
  **approval queue**, signed skills, and a kill-switch.

And a story that says more than any feature list: during pre-launch hardening, an audit caught that
the strict-local family agent *could* fall back to the cloud if the local model was down. It was one
line, it was caught before launch, and it's now impossible by construction — with a test that fails
if anyone ever reintroduces it. **That's what "governed" means here: the promises are enforced in
code and proven by tests, not printed on a values page.**

---

## Who it's for

- **People who refuse to rent their private life to a hyperscaler** — and have (or will build) the
  hardware to own it.
- **The post-hype-agent disillusioned** — you wanted the always-on assistant; you didn't want the
  security horror story.
- **Households** — a family memory agent that keeps names, dates, and routines on your LAN, never
  the internet.
- **Builders & tinkerers** — pure Python, open, extensible via a plugin and skill system.

---

## Availability

Jarvis Hub is approaching its **v1.0** release. Self-host it today: one-click `INSTALL.bat` on
Windows, `install.sh` on Linux/macOS — it sets up everything, including the companion **WorldView**
4D-OSINT globe, and runs the test suite to prove the install.

> **One sentence to remember:** *a private AI that works while you sleep and is owned by the person
> it serves.*

---

## Boilerplate (for the bottom of a press piece)

> **Jarvis Hub** is a local-first, governed personal AI operating system: 17 specialist agents that
> work proactively on the owner's own hardware, with a reversible/irreversible approval queue, a
> tamper-evident audit log, living knowledge-graph memory, and a strict-local family agent that
> never touches the internet. It runs on consumer GPUs via LM Studio/Ollama for $0/month, with cloud
> models as an explicit per-agent opt-in. Open and self-hostable.

*Links: [README](../../README.md) · [MOONSHOT](../../MOONSHOT.md) (vision) · [BRAND_BOOK](../BRAND_BOOK.md) (voice, palette) · social/repo metadata in BRAND_BOOK §9.*
