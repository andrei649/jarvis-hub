# Jarvis Hub — Moonshot

> The north-star document. Everything else (roadmap, architecture, pricing) serves this.
> Generated: 2026-06-02 · Stage: v0.9.1-beta → v1.0.0 · Owner: Andrei
>
> **How to use this doc:** read §1–§4 to know *where we're going*, §7 to know *how we stay on
> track*. When a decision feels off-mission, check it against §5 (principles) and §1 (the bet).
> The operational docs linked in §8 are *downstream* of this one.

---

## 1. The Moonshot

> **A personal AI operating system that knows you, works while you sleep, and never sends your
> life to someone else's cloud — owned by the person it serves, not the vendor.**

Not a chatbot. Not a workflow builder. A **persistent, proactive, private cortex** that runs on
your own hardware, builds a growing understanding of your life, finds its own work, and asks for a
decision only when it genuinely needs one — then learns to stop asking.

The 10-year bet: **the default interface to your digital life is a multi-agent system you own**,
the way the OS — not the mainframe — became the default for personal computing. Jarvis Hub aims to
be that OS, starting as Andrei's "cabinet" and generalizing to anyone who refuses to rent their
private life to a hyperscaler.

---

## 2. Why Now

- **Local inference crossed the usefulness threshold** — a ~4B-active MoE on a single consumer GPU
  is good enough for 99% of daily tasks at **$0 marginal cost** (see [VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) §8).
- **Privacy is becoming a buying criterion**, not a footnote — regulated orgs and privacy-conscious
  individuals can't or won't send their data to someone else's model.
- **Agent orchestration is fragmenting** into reactive chatbots vs rigid workflow builders. No
  *shipping consumer product* combines *autonomy + memory + observability + preference learning* in
  one **local-first** system: the closest combined product (Amazon's Bee) is cloud; the closest
  local-first one (open-source Omi) is passive capture, not an autonomous actor (verified 2026-06-02 —
  [docs/research/2026-06-02-personal-ai-competitors.md](docs/research/2026-06-02-personal-ai-competitors.md)).
- **The cautionary tale validates the bet.** The viral 2026 rival **OpenClaw** relaxed exactly the
  constraints this project holds non-negotiable (production-grade security, governed autonomy) — and
  within ~8 weeks became the #1 infostealer target, with malware harvesting users' agent-memory files.
  The "knows-you device" graveyard (Humane, Dot, Rewind/Limitless, Pi) was uniformly cloud-dependent.
  **Local-first + governed is the durable position, not the slow one** — this *confirms* thesis #3 below.

---

## 3. The Thesis (what has to be true)

1. **Local-first is a durable moat, not a constraint** — it's simultaneously the privacy promise
   *and* the cost-of-goods advantage (free self-host = $0 COGS; a hosted minority funds the company
   at 70–98% gross margin — [VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) §9).
2. **Proactivity compounds** — a system that works 24/7 and consolidates memory nightly gets more
   useful the longer you use it, creating switching cost no reactive tool can match.
3. **Trust is earned by inspectability** — every fact editable, every action audited, every cloud
   hop opt-in. The strict-local agent (Frigga) is the proof, not the marketing.

If any of these stops being true, revisit the moonshot — don't quietly drift from it.

---

## 4. Trajectory — From Cabinet to Platform

Mapped to the existing Horizon plan and [version roadmap](BACKLOG.md#version-roadmap). Each phase has
a clear "done" gate; we do not skip gates.

| Phase | Horizon → Version | The leap | Gate (done when…) |
|-------|-------------------|----------|-------------------|
| **0 — Foundation** ✅ | H1–H4, H5, H6, H7-perf, H9 → v0.9.1-beta | 15 agents, memory, autonomy, workflows, observability all work | Live; 909 tests green |
| **1 — Trustworthy** 🎯 | H7 hardening + H8 personal memory → **v1.0.0** | From "works for Andrei" to "works for anyone, reliably" | CI/CD on PRs, hermetic tests, LICENSE, one-command self-host, personal memory live (see [v1.0 launch checklist](GO_LIVE_PLAN.md#v10-launch-checklist)) |
| **2 — Sellable** | Hosted Pro + open-core license → v1.x | First non-Andrei users; hosted tier; first revenue | 3–5 design partners, hosted Pro live, paid conversion measured |
| **3 — Platform** | H10 Competitive Edge → v1.x–2.0 | MCP server mode, marketplace, multi-user, write-backs | Third parties build on Jarvis (agents-as-tools, embedded widget, webhooks) |

> Phase boundaries are **release gates**, not suggestions. The current gate is **Phase 1 → v1.0**;
> its blocking items are tracked in [BACKLOG.md](BACKLOG.md) (Orizont 7 propus + Orizont 8).

---

## 5. Non-Negotiable Principles (the guardrails)

These override convenience, deadlines, and clever ideas. A change that violates one of these is
wrong even if it ships faster.

1. **Local-first by default** — core functionality never *requires* the cloud. `frigga`, `ultron`,
   `howard` are `LOCAL_ONLY_AGENTS` and stay that way ([ARCHITECTURE.md](docs/ARCHITECTURE.md) §7).
2. **Opt-in for every cloud hop** — no agent leaves the machine without an explicit, auditable toggle.
3. **Inspectable & forgettable** — the user can see, edit, and delete any fact about themselves (H8.2).
4. **Proactive, not noisy** — autonomy escalates reversible work silently; interrupts are budgeted
   (≤4 urgent push/day). We optimize for *fewer, better* decisions, not more notifications.
5. **Production-grade, not demo-grade** — every feature ships with tests; the hot path stays off the
   event loop; failures degrade gracefully (recall never hard-fails).
6. **Your data trains no one's model** — anonymization and local processing are defaults, not upsells.

---

## 6. North-Star Metric & Health Signals

- **North-star:** **weekly autonomous actions accepted per active user** — it captures the whole
  thesis at once (the system is *used*, it's *proactive*, and the user *trusts* its judgment).
- **Counter-metrics (guardrails against gaming the north-star):**
  - interrupt rate (push/day) — must stay within budget; rising = we got noisy.
  - reject rate of proposed actions — rising = trust/quality eroding.
  - % tasks served locally vs cloud — falling = drifting off local-first.
  - p95 per-turn latency (non-LLM) — must stay flat as we add features.
- **Commercial signals (Phase 2+):** self-host installs, hosted paid conversion, NRR, gross margin
  (model in [VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) §6, §9).

---

## 7. Keeping On Track — Operating Rhythm & Governance

The moonshot is only real if day-to-day work bends toward it. This section is the contract between
*vision* (this doc) and *execution* (the operational docs).

### 7.1 Cadence

| Rhythm | Activity | Source of truth |
|--------|----------|-----------------|
| **Per task / PR** | Pick the next item by priority; follow conventions; ship with tests; update docs touched | [BACKLOG.md](BACKLOG.md), [AGENTS.md](AGENTS.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **Per release gate** | Verify the phase gate in §4 is met before tagging a version | [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md) launch checklist |
| **Periodic review** | "What's next / priorities / backlog?" → re-rank against the moonshot; archive done work | [BACKLOG.md](BACKLOG.md) → [docs/HISTORY.md](docs/HISTORY.md) |
| **Drift check** | When a decision feels off-mission, test it against §1 (the bet), §3 (thesis), §5 (principles) | this doc |

### 7.2 Which doc answers which question

| When you're deciding… | Read… |
|-----------------------|-------|
| *Where are we going / is this on-mission?* | **MOONSHOT.md** (this file) — §1, §3, §5 |
| *What should I work on next?* | [BACKLOG.md](BACKLOG.md) — priorities, story points, horizons |
| *Are we ready to ship v1.0?* | [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md) — launch checklist |
| *Where does this code live / how do I change it?* | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module index, recipes |
| *How should I build it (conventions, workflow)?* | [AGENTS.md](AGENTS.md) — assistant + contributor rules |
| *What's the high-level architecture / stack?* | [JARVIS.md](JARVIS.md) |
| *What did we already deliver?* | [docs/HISTORY.md](docs/HISTORY.md) |
| *What's the current snapshot?* | [STATUS.md](STATUS.md) |
| *What's it worth / how do we price & fund it?* | [docs/VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) |
| *Where are the gaps to 1.0?* | [docs/gap-analysis-1.0.md](docs/gap-analysis-1.0.md) |

### 7.3 Definition of "on track"

A change is on track when **all** hold:
- [ ] It advances the current phase gate in §4 (or fixes something that blocks it).
- [ ] It respects every principle in §5 (especially local-first + opt-in cloud).
- [ ] It ships with tests and updates any doc it makes stale ([AGENTS.md](AGENTS.md) convention).
- [ ] It does not regress a counter-metric in §6 (latency, interrupt rate, % local).
- [ ] The relevant operational doc (§7.2) is updated so the next contributor isn't surprised.

### 7.4 Decision log

Significant strategic decisions (license choice, hosted-vs-self-host, pricing changes, dropping a
principle) are recorded in [docs/HISTORY.md](docs/HISTORY.md) with date + rationale, so the moonshot
has an audit trail and future contributors understand *why*, not just *what*.

---

## 8. Doc Map (the canon)

| File | Role relative to the moonshot |
|------|-------------------------------|
| **MOONSHOT.md** | North star — *why we exist, where we're going, how we stay on track* |
| [BACKLOG.md](BACKLOG.md) | The plan — *what's next, prioritized* |
| [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md) | The launch — *features, marketing, v1.0 gate* |
| [docs/VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) | The business — *value, pricing, unit economics* |
| [JARVIS.md](JARVIS.md) | The architecture overview |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The navigable map — *where code lives, how to change it* |
| [AGENTS.md](AGENTS.md) | The conventions — *how we build* |
| [docs/HISTORY.md](docs/HISTORY.md) | The record — *what we delivered + decision log* |
| [STATUS.md](STATUS.md) | The snapshot — *where we are right now* |
| [docs/gap-analysis-1.0.md](docs/gap-analysis-1.0.md) | The gaps — *what stands between us and 1.0* |

---

*If you only remember one sentence: **a private AI that works while you sleep and is owned by the
person it serves.** Everything in this repo is in service of making that real and keeping it true.*
